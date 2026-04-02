# genapidocs_v2/fastapi_analyzer.py

import ast
import os
import re
from typing import Any, Dict, List, Optional, Set

from common.interfaces.code_analyzer import CodeAnalyzer, SymbolType
from common.interfaces.framework_analyzer import FrameworkAnalyzer


class FastAPIAnalyzer(FrameworkAnalyzer):
    """
    FastAPI-specific implementation of the FrameworkAnalyzer interface.
    Analyzes FastAPI projects to extract API endpoints and schema components.
    """

    def __init__(self, code_analyzer: CodeAnalyzer, project_path: str, logger=None):
        """
        Initialize with a Python code analyzer.
        """
        super().__init__(code_analyzer, project_path)
        self.logger = logger
        self.endpoints: List[Dict[str, Any]] = []

    def get_endpoints(self, output_dir=None) -> List[Dict[str, Any]]:
        """
        Extract API endpoints from the FastAPI project. This implementation is tuned
        for projects with a central `app.py` that uses `include_router`.
        """
        if self.endpoints:
            return self.endpoints

        self.logger.info("Starting FastAPI endpoint extraction...")
        try:
            entrypoint_file = os.path.join(self.project_path, "tracecat/api/app.py")
            if not os.path.exists(entrypoint_file):
                self.logger.error(f"Entrypoint file not found: {entrypoint_file}")
                return []
                
            self._extract_endpoints_from_ast(entrypoint_file)
        except Exception as e:
            self.logger.error(f"Failed during endpoint extraction: {e}", exc_info=True)
        
        self.logger.info(f"FastAPI endpoint extraction complete. Found {len(self.endpoints)} endpoints.")
        return self.endpoints

    def _extract_endpoints_from_ast(self, entrypoint_file: str):
        """
        Parses the entrypoint file to find `include_router` calls, then analyzes
        each router file for endpoint decorators.
        """
        # CORRECTED: Use the new, proper method to get the file's AST
        tree = self.code_analyzer.get_file_ast(entrypoint_file)
        if not tree:
            self.logger.error(f"Could not parse AST for {entrypoint_file}")
            return
            
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
                continue
            call = node.value
            if isinstance(call.func, ast.Attribute) and call.func.attr == 'include_router':
                if not call.args:
                    continue

                router_node = call.args[0]
                if not isinstance(router_node, ast.Name):
                    continue
                
                router_var_name = router_node.id
                
                prefix = ""
                tags = []
                for kw in call.keywords:
                    if kw.arg == 'prefix' and isinstance(kw.value, ast.Constant):
                        prefix = kw.value.value
                    if kw.arg == 'tags' and isinstance(kw.value, ast.List):
                        tags = [elt.value for elt in kw.value.elts if isinstance(elt, ast.Constant)]
                
                import pdb; pdb.set_trace()
                ref = self.code_analyzer.get_symbol_reference(router_var_name, entrypoint_file, SymbolType.VARIABLE)
                if not ref or not ref.get('path'):
                    self.logger.warning(f"Could not resolve router variable '{router_var_name}' in {entrypoint_file}")
                    continue
                
                router_file_path = ref['path']
                self.logger.info(f"Analyzing router '{router_var_name}' from '{router_file_path}' with prefix '{prefix}'")
                self._analyze_router_file(router_file_path, prefix, tags)


    def _analyze_router_file(self, file_path: str, url_prefix: str, tags: list[str]):
        """
        Analyzes a single router file to find all endpoint decorators.
        """
        # CORRECTED: Use the new, proper method to get the file's AST
        tree = self.code_analyzer.get_file_ast(file_path)
        if not tree:
            self.logger.error(f"Could not parse AST for router file {file_path}")
            return
            
        http_methods = {"get", "post", "put", "patch", "delete", "options", "head"}

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                    method_name = decorator.func.attr
                    if method_name in http_methods:
                        if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                            continue
                            
                        sub_path = decorator.args[0].value
                        full_path = self._join_url_paths(url_prefix, sub_path)
                        path_params = self._parse_path_params(full_path)
                        
                        endpoint = {
                            "url": {
                                "url": full_path,
                                "parameter": path_params
                            },
                            "method": method_name.upper(),
                            "view": node.name,
                            "path": file_path,
                            "is_viewset": False,
                            "function": node.name,
                            "metadata": {"tags": tags}
                        }
                        self.endpoints.append(endpoint)
                        self.logger.debug(f"Discovered endpoint: {method_name.upper()} {full_path}")


    def _join_url_paths(self, prefix: str, sub_path: str) -> str:
        """Safely joins a URL prefix and a sub-path."""
        return f"/{prefix.strip('/')}/{sub_path.strip('/')}".replace('//', '/')

    def _parse_path_params(self, path: str) -> List[Dict[str, str]]:
        """Parses path parameters from a URL string (e.g., /items/{item_id})."""
        params = []
        for match in re.finditer(r"\{([^}]+)\}", path):
            param_name_with_type = match.group(1)
            if ":" in param_name_with_type:
                name, type_hint = param_name_with_type.split(":", 1)
                params.append({"name": name, "type": type_hint})
            else:
                params.append({"name": param_name_with_type, "type": "string"})
        return params

    # --- Other required methods (to be implemented) ---

    def get_schema_components(self) -> Dict[str, Dict[str, Any]]:
        self.logger.warning("get_schema_components is not yet implemented for FastAPI.")
        return {}

    def get_component_field_instructions(self, component_name: str, component_info: Dict[str, Any]) -> str:
        raise NotImplementedError
        
    def get_component_system_message(self) -> str:
        raise NotImplementedError
        
    def get_endpoint_request_instructions(self, endpoint: Dict[str, Any], endpoint_context: Dict[str, Any]) -> str:
        raise NotImplementedError
    
    def get_endpoint_response_instructions(self, endpoint: Dict[str, Any], endpoint_context: Dict[str, Any]) -> str:
        raise NotImplementedError