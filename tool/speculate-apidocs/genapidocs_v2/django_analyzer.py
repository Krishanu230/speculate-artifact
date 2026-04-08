import ast
import os
import json
import re
import subprocess
import sys
import traceback
from typing import Dict, List, Set, Optional, Any, Tuple
import copy

from common.core.framework_analyzer import FrameworkAnalyzer
from common.core.code_analyzer import CodeAnalyzer, SymbolType
from genapidocs_v2.django_static_endpoint_parser import extract_endpoints_static
import textwrap

DRF_default_response_codes = {
    "GET_List": {
        "400": "Bad Request - Invalid query parameters.",
        "401": "Unauthorized - Authentication credentials were not provided.",
        "403": "Forbidden - User does not have permission to view the list.",
        "406": "Not Acceptable - Requested content type is not acceptable according to the Accept headers.",
    },
    "GET_Retrieve": {
        "400": "Bad Request - Invalid query parameters.",
        "401": "Unauthorized - Authentication credentials were not provided.",
        "403": "Forbidden - User does not have permission to view this object.",
        "404": "Not Found - Object with the given identifier does not exist.",
        "406": "Not Acceptable - Requested content type is not acceptable according to the Accept headers.",
    },
    "DELETE": {
        "400": "Bad Request - Bad input parameter.",
        "401": "Unauthorized - Authentication credentials were not provided.",
        "403": "Forbidden - User does not have permission to delete this object.",
        "404": "Not Found - Object to be deleted does not exist.",
        "405": "Method Not Allowed - DELETE method not allowed on the endpoint.",
        "429": "Too Many Requests - Too many requests; rate limit exceeded.",
    },
    "PATCH": {
        "400": "Bad Request - Bad input, validation error, or partial update not allowed.",
        "401": "Unauthorized - Authentication credentials were not provided.",
        "403": "Forbidden - User does not have permission to edit this object.",
        "404": "Not Found - Object to be updated does not exist.",
        "405": "Method Not Allowed - PATCH method not allowed on the endpoint.",
        "406": "Not Acceptable - Requested content type is not acceptable.",
        "415": "Unsupported Media Type - Unsupported media type in request.",
        "429": "Too Many Requests - Too many requests; rate limit exceeded.",
    },
    "POST": {
        "400": "Bad Request - Bad input, validation error.",
        "401": "Unauthorized - Authentication credentials were not provided.",
        "403": "Forbidden - User does not have permission to create the object.",
        "404": "Not Found - URL not found.",
        "405": "Method Not Allowed - POST method not allowed on the endpoint.",
        "406": "Not Acceptable - Requested content type is not acceptable.",
        "415": "Unsupported Media Type - Unsupported media type in request.",
        "429": "Too Many Requests - Too many requests; rate limit exceeded.",
    },
}

class DjangoAnalyzer(FrameworkAnalyzer):
    """
    Django-specific implementation of the FrameworkAnalyzer interface.
    Analyzes Django projects to extract API endpoints, serializers, and other information.
    """
    
    def __init__(self, code_analyzer: CodeAnalyzer, project_path: str, analysis_path: str = None, 
                 use_dynamic: bool = True, settings_path: str = None, logger=None,settings_module_str: str = None,
        explicit_settings_file_path: str = None, 
        explicit_urls_file_path: str = None,
        ):
        """
        Initialize with Python code analyzer.
        
        Args:
            code_analyzer: Implementation of CodeAnalyzer for the language
            project_path: Root path of the project
            analysis_path: Path to existing analysis results (optional)
            use_dynamic: Whether to use dynamic URL extraction (default: True)
            settings_path: Path to Django settings module (optional)
        """
        super().__init__(code_analyzer, project_path, analysis_path)
        self.endpoints = []
        self.is_serializer = {}
        self.is_model = {}
        self._models_identified = False
        self.is_viewset = {}
        self.component_contexts = {}

        self.urls_module = None
        self.use_dynamic = use_dynamic
        self.settings_path = settings_path
        self.settings_module_str = settings_module_str
        self.explicit_settings_file_path = explicit_settings_file_path
        self.explicit_urls_file_path = explicit_urls_file_path
        self.debug_mode = True
        self.logger = logger
        

        # Feature Class Identification - Initialized Empty
        self.is_pagination_class = {}
        self.is_auth_class = {}
        self.is_filter_class = {}
        self._feature_classes_identified = False # Flag
        # Default settings from Django REST Framework
        self.default_settings = {
            "DEFAULT_AUTHENTICATION_CLASSES": [],
            "DEFAULT_PAGINATION_CLASS": None,
            "DEFAULT_FILTER_BACKENDS": [],
            "PAGE_SIZE": None
        }
        
        self.BASE_PAGINATION_CLASSES = {
            "PageNumberPagination", "LimitOffsetPagination", "CursorPagination", "BasePagination"
        }
        self.BASE_AUTH_CLASSES = {
            "BaseAuthentication", "BasicAuthentication", "SessionAuthentication",
            "TokenAuthentication", "RemoteUserAuthentication", "JSONWebTokenAuthentication" # Added JWT
        }
        # Includes django-filter base classes
        self.BASE_FILTER_CLASSES = {"BaseFilterBackend", "FilterSet", "BaseFilterSet"}

        # If analysis_path is provided, try to load endpoints
        if analysis_path:
            self._load_endpoints(analysis_path)
    
    def get_endpoints(self, output_dir: str) -> List[Dict[str, Any]]:
        """
        Extract API endpoints from the project.
        
        Returns:
            List of dictionaries, each containing:
                - url: Dictionary with URL pattern and parameters
                - method: HTTP method (GET, POST, etc.)
                - view: Handler class or function name
                - path: File path where the handler is defined
                - is_viewset: Whether the handler is a viewset
                - function: Function name (if viewset)
        """
        # If we already have endpoints, return them
        if self.endpoints:
            return self.endpoints
        
        # Try dynamic extraction first if enabled
        if self.use_dynamic:
            success = self._extract_endpoints_dynamic(output_dir)
            if not success:
                raise RuntimeError(
                    "Dynamic Django endpoint extraction failed. Prefer fixing the Django "
                    "runtime environment and retrying. If that is not feasible, rerun "
                    "with --django-use-static-endpoints to use the best-effort static "
                    "endpoint parser."
                )
        else:
            self._extract_endpoints_static()
        
        return self.endpoints
    
          
    def _extract_endpoints_dynamic(self, result_dir) -> bool:
        script_path = self._find_script_path("runtime_endpoint_generation.py")
        if not script_path:
            print("Could not find runtime_endpoint_generation.py script")
            if self.debug_mode:
                print("Searched in:")
                print(f"  Current directory: {os.getcwd()}")
                print(f"  Module directory: {os.path.dirname(os.path.abspath(__file__))}")
            return False
        
        starting_point = self._find_starting_point()
        if not starting_point:
            print("Could not find Django manage.py file")
            if self.debug_mode:
                print(f"Searched in project directory: {self.project_path}")
            return False
        
        url_file = self._find_url_module() # This now uses the new prioritized logic
        if not url_file:
            print("Could not find Django URL configuration file (root urls.py).")
            if self.debug_mode:
                print(f"  Project path: {self.project_path}")
                print(f"  explicit_urls_file_path provided: {self.explicit_urls_file_path}")
                print(f"  explicit_settings_file_path provided: {self.explicit_settings_file_path}")
                print(f"  settings_module_str provided: {self.settings_module_str}")
                print("  Ensure one of these is set correctly, or auto-discovery can find settings with ROOT_URLCONF.")
            return False
        
        os.makedirs(result_dir, exist_ok=True)
        
        try:
            command = [
                sys.executable,
                script_path,
                self.project_path,
                result_dir,
                url_file,
                starting_point
            ]
            
            if self.settings_module_str:
                command.append(self.settings_module_str)
            
            if self.debug_mode:
                print("Running command for dynamic endpoint extraction:")
                print(f"  {' '.join(command)}")
            
            result = subprocess.run(
                command,
                text=True,
                capture_output=True,
                encoding='utf-8' 
            )
            self.logger.info("--- Subprocess `runtime_endpoint_generation.py` Output ---")
            if result.stdout:
                self.logger.debug(f"STDOUT:\n{result.stdout}")
            else:
                self.logger.debug("STDOUT: [empty]")
            
            if result.stderr:
                self.logger.error(f"STDERR:\n{result.stderr}")
            else:
                self.logger.debug("STDERR: [empty]")
            self.logger.info("--- End Subprocess Output ---")
            if result.returncode != 0:
                print(f"Error running URL extraction script (return code {result.returncode}):")
                print(f"STDOUT: {result.stdout}")
                print(f"STDERR: {result.stderr}")
                return False
            
            endpoint_file = os.path.join(result_dir, "django_endpoints.json")
            if os.path.exists(endpoint_file):
                success = self._load_endpoints(endpoint_file)
                if not success and self.debug_mode:
                    print(f"Failed to load endpoints from {endpoint_file}")
                return success
            else:
                print(f"URL extraction script did not generate output file: {endpoint_file}")
                if self.debug_mode:
                    print(f"Script output:")
                    print(f"STDOUT: {result.stdout}")
                    print(f"STDERR: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"Exception during dynamic URL extraction: {e}")
            if self.debug_mode:
                traceback.print_exc()
            return False


    def _load_endpoints(self, endpoint_file: str) -> bool:
        """
        Load endpoints from a JSON file.
        
        Args:
            endpoint_file: Path to the JSON file containing endpoints
            
        Returns:
            True if successful, False otherwise
        """
        try:
            with open(endpoint_file, 'r') as f:
                data = json.load(f)
                
                # Extract endpoints
                self.endpoints = data.get('endpoints', [])
                
                # Extract default settings
                self.default_settings["DEFAULT_AUTHENTICATION_CLASSES"] = data.get("DEFAULT_AUTHENTICATION_CLASSES", [])
                self.default_settings["DEFAULT_PAGINATION_CLASS"] = data.get("DEFAULT_PAGINATION_CLASS")
                self.default_settings["DEFAULT_FILTER_BACKENDS"] = data.get("DEFAULT_FILTER_BACKENDS", [])
                self.default_settings["PAGE_SIZE"] = data.get("PAGE_SIZE")
                
                # Store sys_path if available
                if "sys_path" in data and self.analysis_results:
                    self.analysis_results["sys_path"] = data["sys_path"]
                
                if self.debug_mode:
                    print(f"Loaded {len(self.endpoints)} endpoints from {endpoint_file}")
                
                return len(self.endpoints) > 0
        except Exception as e:
            print(f"Error loading endpoints from {endpoint_file}: {e}")
            if self.debug_mode:
                traceback.print_exc()
            return False
    
    def _find_script_path(self, script_name: str) -> Optional[str]:
        """
        Find the path to a script.
        
        Args:
            script_name: Name of the script to find
            
        Returns:
            Path to the script or None if not found
        """
        # Look in the current directory
        if os.path.exists(script_name):
            return os.path.abspath(script_name)
        
        # Look in the directory of this module
        module_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(module_dir, script_name)
        if os.path.exists(script_path):
            return script_path
        
        # Look in package directories
        try:
            import pypi.speculate_apidocs
            package_dir = os.path.dirname(pypi.speculate_apidocs.__file__)
            script_path = os.path.join(package_dir, script_name)
            if os.path.exists(script_path):
                return script_path
        except ImportError:
            pass
        
        # Try parent directories
        current_dir = os.path.abspath(os.getcwd())
        for _ in range(3):  # Try up to 3 levels up
            parent_dir = os.path.dirname(current_dir)
            if parent_dir == current_dir:  # Reached root
                break
            current_dir = parent_dir
            script_path = os.path.join(current_dir, script_name)
            if os.path.exists(script_path):
                return script_path
        
        # Not found
        return None
    
    def _find_starting_point(self) -> Optional[str]:
        """
        Find the starting point (manage.py) for the Django project.
        
        Returns:
            Path to the starting point or None if not found
        """
        # Look for manage.py in project path
        manage_py = os.path.join(self.project_path, 'manage.py')
        if os.path.exists(manage_py):
            return manage_py
            
        # Look for manage.py in subdirectories
        for root, _, files in os.walk(self.project_path):
            if 'manage.py' in files:
                return os.path.join(root, 'manage.py')
        
        # Not found
        return None
          
    def _find_url_module(self) -> Optional[str]:
        """
        Find the URL configuration file (root urls.py) for the Django project.
        Prioritizes explicit paths, then uses settings, then falls back to auto-discovery.

        Returns:
            Absolute path to the URL configuration file or None if not found.
        """
        if self.urls_module: # Already found/set perhaps by a previous call or direct set
            if self.debug_mode: print(f"DEBUG: _find_url_module: Returning cached self.urls_module: {self.urls_module}")
            return self.urls_module


        # Priority 1: Explicitly provided path to the root urls.py file
        if self.explicit_urls_file_path:
            if self.debug_mode: print(f"DEBUG: _find_url_module: Trying explicit_urls_file_path: {self.explicit_urls_file_path}")
            abs_explicit_urls_path = os.path.abspath(self.explicit_urls_file_path)
            if os.path.exists(abs_explicit_urls_path) and abs_explicit_urls_path.endswith(".py"):
                self.urls_module = abs_explicit_urls_path
                if self.debug_mode: print(f"DEBUG: _find_url_module: Using explicit_urls_file_path: {self.urls_module}")
                return self.urls_module
            elif self.debug_mode:
                print(f"DEBUG: _find_url_module: explicit_urls_file_path '{abs_explicit_urls_path}' does not exist or is not a .py file.")

        # Priority 2: Explicitly provided path to the settings file
        # From this settings file, we'll read ROOT_URLCONF and resolve it.
        if self.explicit_settings_file_path:
            if self.debug_mode: print(f"DEBUG: _find_url_module: Trying explicit_settings_file_path: {self.explicit_settings_file_path}")
            abs_explicit_settings_path = os.path.abspath(self.explicit_settings_file_path)
            if os.path.exists(abs_explicit_settings_path):
                try:
                    with open(abs_explicit_settings_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    url_conf_pattern = r"ROOT_URLCONF\s*=\s*['\"]([^'\"]+)['\"]"
                    match = re.search(url_conf_pattern, content)
                    if match:
                        url_module_name = match.group(1)
                        if self.debug_mode: print(f"DEBUG: _find_url_module: Found ROOT_URLCONF='{url_module_name}' in explicit_settings_file: {abs_explicit_settings_path}")
                        
                        # Try resolving ROOT_URLCONF relative to project_path first (most common)
                        resolved_path = self._resolve_url_conf_to_file_path(url_module_name, self.project_path)
                        if resolved_path:
                            self.urls_module = resolved_path
                            return self.urls_module
                        
                        # Fallback: Try resolving relative to the settings file's directory
                        settings_dir = os.path.dirname(abs_explicit_settings_path)
                        resolved_path_rel_settings = self._resolve_url_conf_to_file_path(url_module_name, settings_dir)
                        if resolved_path_rel_settings:
                            self.urls_module = resolved_path_rel_settings
                            return self.urls_module
                        elif self.debug_mode:
                            print(f"DEBUG: _find_url_module: Could not resolve ROOT_URLCONF '{url_module_name}' from explicit settings file.")
                    elif self.debug_mode:
                        print(f"DEBUG: _find_url_module: ROOT_URLCONF not found in explicit_settings_file: {abs_explicit_settings_path}")
                except Exception as e:
                    if self.debug_mode: print(f"DEBUG: _find_url_module: Error reading explicit_settings_file {abs_explicit_settings_path}: {e}")
            elif self.debug_mode:
                print(f"DEBUG: _find_url_module: explicit_settings_file_path '{abs_explicit_settings_path}' does not exist.")

        # Priority 3: Using self.settings_module_str (e.g., "myproject.settings.development")
        # Convert this module string to a file path, read ROOT_URLCONF, then resolve it.
        if self.settings_module_str:
            if self.debug_mode: print(f"DEBUG: _find_url_module: Trying to use self.settings_module_str: {self.settings_module_str}")
            
            settings_file_rel_path_parts = self.settings_module_str.split('.')
            settings_file_rel_path = os.path.join(*settings_file_rel_path_parts) + ".py"
            potential_settings_file_abs_path = os.path.join(self.project_path, settings_file_rel_path)
            
            if self.debug_mode: print(f"DEBUG: _find_url_module: Potential settings file from module string: {potential_settings_file_abs_path}")

            if os.path.exists(potential_settings_file_abs_path):
                try:
                    with open(potential_settings_file_abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    url_conf_pattern = r"ROOT_URLCONF\s*=\s*['\"]([^'\"]+)['\"]"
                    match = re.search(url_conf_pattern, content)
                    if match:
                        url_module_name = match.group(1)
                        if self.debug_mode: print(f"DEBUG: _find_url_module: Found ROOT_URLCONF='{url_module_name}' in settings file derived from module string: {potential_settings_file_abs_path}")
                        
                        resolved_path = self._resolve_url_conf_to_file_path(url_module_name, self.project_path)
                        if resolved_path:
                            self.urls_module = resolved_path
                            return self.urls_module

                        settings_dir = os.path.dirname(potential_settings_file_abs_path)
                        resolved_path_rel_settings = self._resolve_url_conf_to_file_path(url_module_name, settings_dir)
                        if resolved_path_rel_settings:
                            self.urls_module = resolved_path_rel_settings
                            return self.urls_module
                        elif self.debug_mode:
                            print(f"DEBUG: _find_url_module: Could not resolve ROOT_URLCONF '{url_module_name}' from settings_module_str.")
                    elif self.debug_mode:
                        print(f"DEBUG: _find_url_module: ROOT_URLCONF not found in settings file: {potential_settings_file_abs_path}")
                except Exception as e:
                    if self.debug_mode: print(f"DEBUG: _find_url_module: Error reading settings file {potential_settings_file_abs_path}: {e}")
            elif self.debug_mode:
                print(f"DEBUG: _find_url_module: Settings file '{potential_settings_file_abs_path}' derived from module string does not exist.")

        # Priority 4: Fallback to automatic discovery (your improved version)
        if self.debug_mode: print(f"DEBUG: _find_url_module: Falling back to automatic discovery.")
        discovered_settings_files = []
        for root, dirs, files in os.walk(self.project_path):
            # Pruning common irrelevant directories
            dirs[:] = [d for d in dirs if d not in ['site-packages', 'node_modules', '.git', 'venv', '__pycache__', '.mymedia', 'migrations', 'static', 'media']]
            
            for file_name in files:
                if file_name.endswith(".py"):
                    is_potential_settings = (
                        file_name == 'settings.py' or
                        os.path.basename(root) == 'settings' or # any .py file in a 'settings' directory
                        file_name in ['base.py', 'development.py', 'production.py', 'local.py', 'test.py'] # common names
                    )
                    if is_potential_settings:
                        discovered_settings_files.append(os.path.join(root, file_name))
        
        if self.debug_mode: print(f"DEBUG: _find_url_module (auto-discovery): Potential settings files: {discovered_settings_files}")

        for settings_file_path in discovered_settings_files:
            try:
                with open(settings_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                url_conf_pattern = r"ROOT_URLCONF\s*=\s*['\"]([^'\"]+)['\"]"
                match = re.search(url_conf_pattern, content)
                if match:
                    url_module_name = match.group(1)
                    if self.debug_mode: print(f"DEBUG: _find_url_module (auto-discovery): Found ROOT_URLCONF='{url_module_name}' in {settings_file_path}")
                    
                    resolved_path = self._resolve_url_conf_to_file_path(url_module_name, self.project_path)
                    if resolved_path:
                        self.urls_module = resolved_path
                        return self.urls_module

                    settings_dir = os.path.dirname(settings_file_path)
                    resolved_path_rel_settings = self._resolve_url_conf_to_file_path(url_module_name, settings_dir)
                    if resolved_path_rel_settings:
                        self.urls_module = resolved_path_rel_settings
                        return self.urls_module
            except Exception as e:
                if self.debug_mode: print(f"DEBUG: _find_url_module (auto-discovery): Error with {settings_file_path}: {e}")
                continue
        
        if self.debug_mode:
            if not self.urls_module:
                print("DEBUG: _find_url_module: All methods failed to find the URL module. self.urls_module is None.")
        return self.urls_module # Will be None if nothing found

    def _extract_endpoints_static(self) -> None:
        """Extract API endpoints using static analysis."""
        url_file = self._find_url_module()
        if not url_file:
            raise RuntimeError("Could not find Django URL configuration file for static endpoint extraction.")

        self.endpoints = extract_endpoints_static(
            code_analyzer=self.code_analyzer,
            project_path=self.project_path,
            url_file=url_file,
        )
    
    
    def _find_imperative_symbols_in_code(self, code: str, context_path: str, symbol_suffix: str) -> List[str]:
        """
        Finds symbols ending with a specific suffix (e.g., 'Serializer')
        that are instantiated or referenced in a block of code using AST.
        Returns a list of unique CANONICAL names for the found symbols.
        """
        found_symbols = set()
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue

                func_node = node.func
                symbol_name_in_code = None
                if isinstance(func_node, ast.Name):
                    symbol_name_in_code = func_node.id
                elif isinstance(func_node, ast.Attribute):
                    symbol_name_in_code = ast.unparse(func_node)

                if symbol_name_in_code and symbol_name_in_code.endswith(symbol_suffix):
                    ref = self.code_analyzer.get_symbol_reference(symbol_name_in_code, context_path, SymbolType.CLASS)
                    if ref and ref.get('name'):
                        found_symbols.add(ref['name'])
                        self.logger.debug(f"AST Discovery: Found imperative call to '{symbol_name_in_code}' (suffix: {symbol_suffix}), resolved to canonical name '{ref['name']}'.")

        except SyntaxError as e:
            self.logger.warning(f"AST Syntax Error while finding imperative '{symbol_suffix}' in {context_path}: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error in _find_imperative_symbols_in_code for {context_path}: {e}", exc_info=True)

        return list(found_symbols)
    
    def _deduplicate_and_prioritize_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Takes the raw, potentially redundant context and returns a clean version.
        FIXED: More aggressively prevents models from getting a top-level component
        if they are already included as a dependency.
        """
        self.logger.info(f"{context['handler']['name']}: De-duplicating and prioritizing gathered context...")

        # Use canonical keys for tracking (path:name)
        final_components = {}
        included_data_class_keys = set()

        # --- Step 1: First Pass - Collect all REAL serializers ---
        # Real serializers are the highest priority.
        real_serializers = [c for c in context.get('serializers', []) if c.get('type') == 'serializer']
        for component in real_serializers:
            component_key = f"{component.get('path')}:{component.get('name')}"
            if component_key not in final_components:
                final_components[component_key] = component
                self.logger.debug(f"Prioritizing real serializer: '{component.get('name')}'")
                for model in component.get("data_classes", []):
                    model_key = f"{model.get('path')}:{model.get('name')}"
                    included_data_class_keys.add(model_key)
        
        self.logger.debug(f"After pass 1 (real serializers), store has {len(final_components)} components. "
                        f"{len(included_data_class_keys)} models are included as dependencies.")

        # --- Step 2: Second Pass - Add synthetic model groups ---
        synthetic_model_groups = [c for c in context.get('serializers', []) if c.get('type') == 'model_group']
        # Sort them to process deterministically, perhaps by number of dependencies
        synthetic_model_groups.sort(key=lambda x: len(x.get('data_classes', [])), reverse=True)

        for component in synthetic_model_groups:
            component_key = f"{component.get('path')}:{component.get('name')}"

            # If this model is ALREADY included as part of another component's context, skip it.
            if component_key in included_data_class_keys:
                self.logger.debug(f"Skipping synthetic group for '{component.get('name')}'; it's already a dependency of another component.")
                continue

            # If the synthetic group itself isn't in our final list yet, add it.
            if component_key not in final_components:
                # Before adding, filter its own data_classes to not include things we already have.
                cleaned_data_classes = []
                for model in component.get("data_classes", []):
                    model_key = f"{model.get('path')}:{model.get('name')}"
                    if model_key not in included_data_class_keys:
                        cleaned_data_classes.append(model)
                        included_data_class_keys.add(model_key) # Mark as included now
                
                # Update the component with the cleaned list
                component['data_classes'] = cleaned_data_classes
                final_components[component_key] = component
                # Add the key of the component itself to the set of included models
                included_data_class_keys.add(component_key)
                self.logger.debug(f"Adding synthetic group for '{component.get('name')}', providing {len(cleaned_data_classes)} new models.")

        # --- Step 3: Rebuild the context ---
        optimized_list = list(final_components.values())
        optimized_list.sort(key=lambda x: (x.get('type') != 'serializer', x.get('name')))
        
        self.logger.info(f"Context de-duplication complete. Final component count: {len(optimized_list)}")
        context['serializers'] = optimized_list
        
        return context

    def _find_models_from_meta_class(self, code: str, context_path: str) -> List[str]:
        """
        Finds Django models declared in a 'class Meta' by looking for 'model = ...'.
        Returns a list of unique CANONICAL model names found.
        """
        found_models = set()
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                # Find a class definition named 'Meta'
                if isinstance(node, ast.ClassDef) and node.name == 'Meta':
                    # Look for an assignment statement inside Meta
                    for item in node.body:
                        if isinstance(item, ast.Assign):
                            # Check if the target of the assignment is 'model'
                            for target in item.targets:
                                if isinstance(target, ast.Name) and target.id == 'model':
                                    model_name_in_code = ast.unparse(item.value)
                                    ref = self.code_analyzer.get_symbol_reference(model_name_in_code, context_path, SymbolType.CLASS)
                                    if ref and ref.get('name'):
                                        found_models.add(ref['name'])
                                        self.logger.debug(f"AST Discovery: Found declarative 'model = {model_name_in_code}' in Meta, resolved to '{ref['name']}'.")
        except SyntaxError as e:
            self.logger.warning(f"AST Syntax Error while finding Meta class models in {context_path}: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error in _find_models_from_meta_class for {context_path}: {e}", exc_info=True)
        return list(found_models)
    
    def _build_function_component(self, func_info: Dict[str, Any]) -> Dict[str, Any]:
        """Creates the standard dictionary structure for a function component."""
        func_name = func_info['name']
        func_path = func_info['path']
        return {
            "name": func_name,
            "path": func_path,
            "code": self.code_analyzer.get_code_snippet(func_path, func_info.get('startLine', 0), func_info.get('endLine', 0)),
            "type": "function",
        }
    
    def get_endpoint_context(self, endpoint: Dict[str, Any]) -> Dict[str, str]:
        """
        
        Args:
            endpoint: Dictionary containing endpoint information
            
        Returns:
            Dictionary containing endpoint context sections
        """
        # Extract endpoint information
        path = endpoint.get("path")
        view = endpoint.get("view")
        is_viewset = endpoint.get("is_viewset", False)
        handler_function_name = endpoint.get("function")

        log_prefix = f"[{view}:{handler_function_name or 'api_view'}]"

        self.logger.info(f"{log_prefix} Starting context gathering for endpoint: {endpoint.get('method')} {endpoint.get('url', {}).get('url')}")
        if handler_function_name:
            self.logger.info(f"[{view}] Target handler method identified: '{handler_function_name}'")
        # Initialize context sections
        context = {
            "endpoint": endpoint,
            "handler": {
                "name": view,
                "type": "django.viewset" if is_viewset else "django.api_view",
                "path": path,
                "is_external": False,
                "external_description": f"Viewset {view} of a famous python package.",
                "code": None,
                "location": {
                    "start_line": None,
                    "end_line": None
                },
                "parent_classes": []
            },
            "serializers": [],
            "framework_settings": {
                "framework": "django",
                "settings": {
                    "pagination_class": self.default_settings.get("DEFAULT_PAGINATION_CLASS"),
                    "page_size": self.default_settings.get("PAGE_SIZE"),
                    "authentication_classes": self.default_settings.get("DEFAULT_AUTHENTICATION_CLASSES", []),
                    "filter_backends": self.default_settings.get("DEFAULT_FILTER_BACKENDS", [])
                }
            },
            "features": []
        }

        self.logger.debug(f"{log_prefix} Stage 1: Fetching full handler class code.")

        # Get viewset code section
        classes = self.code_analyzer.get_file_classes(path)
        analyzed_files = self.code_analyzer.get_analyzed_files()
        viewset_code = None
        if path and path in analyzed_files and view in classes:
            view_info = classes[view]
            start_line, end_line = view_info["startLine"], view_info["endLine"]
            viewset_code = self.code_analyzer.get_code_snippet(path, start_line, end_line)
            context['handler']['code'] = viewset_code
            context['handler']['location'] = {"start_line": start_line, "end_line": end_line}
            context['handler']['parent_classes'] = self.code_analyzer.get_class_inheritance_tree(view, path)
            self.logger.debug(f"{log_prefix} Successfully fetched handler class code and metadata.")
        else:
            context['handler']['is_external'] = True
            self.logger.warning(f"{log_prefix} Could not find handler class info in analysis results. Context will be limited.")
            return context
        
        processed_components = set()

        # --- Stage 2: Shallow Analysis (Declarative) on Full Class Code ---
        self.logger.info(f"{log_prefix} Stage 1.5: Performing shallow analysis for declarative serializers and plugins...")

        declarative_serializers = self._get_serializer(self.is_serializer, viewset_code, path, set())
        for ser_comp in declarative_serializers:
            if ser_comp['name'] not in processed_components:
                context['serializers'].append(ser_comp)
                processed_components.add(ser_comp['name'])
                self.logger.debug(f"{log_prefix} Found declarative serializer: '{ser_comp['name']}'.")
                for model in ser_comp.get("data_classes", []):
                    processed_components.add(model['name'])
        self.logger.debug(f"{log_prefix} Shallow analysis found {len(declarative_serializers)} declarative serializers and {len(context['features'])} plugins (features).")
        
        local_features = self._get_feature_components(viewset_code, endpoint.get("path"), set())
        context["features"].extend(local_features)

        default_pagination_path_str = self.default_settings.get("DEFAULT_PAGINATION_CLASS")
        if default_pagination_path_str:
                self.logger.info(f"{log_prefix} Found default pagination class in settings: {default_pagination_path_str}")
                # Resolve the string path to a file path and class name, then create the component
                default_pagination_component = self._create_component_from_string_path(
                    component_path_str=default_pagination_path_str,
                    component_type="pagination",
                    processed_keys=processed_components
                )
                if default_pagination_component:
                    context["features"].append(default_pagination_component)
        
        # --- Stage 3: Deep Analysis (Imperative) Scoped to Handler Method ---
        self.logger.info(f"{log_prefix} Stage 2: Preparing scopes for deep analysis...")
        deep_analysis_scopes = []

        # Scope 1: The Handler Method itself
        if handler_function_name:
            self.logger.debug(f"{log_prefix} ViewSet detected. Attempting to scope deep analysis to method: '{handler_function_name}'.")
            handler_method_code = self.code_analyzer.get_method_code(view, handler_function_name, path)
            if handler_method_code:
                deep_analysis_scopes.append({"code": handler_method_code, "path": path, "name": handler_function_name})
                self.logger.debug(f"{log_prefix} Successfully added handler method '{handler_function_name}' to deep analysis scopes.")
            else:
                self.logger.warning(f"{log_prefix} Could not get code for method '{handler_function_name}'. Falling back to full class analysis for this scope.")
                deep_analysis_scopes.append({"code": viewset_code, "path": path, "name": f"{view} (fallback)"})
        else:
            self.logger.debug(f"{log_prefix} Non-ViewSet (e.g., APIView) detected. Adding full view '{view}' to deep analysis scopes.")
            deep_analysis_scopes.append({"code": viewset_code, "path": path, "name": view})
        
        # Scope 2...N: The "Plugin" Classes (Filters, Auth, etc.)
        for feature in context.get("features", []):
            self.logger.debug(f"{log_prefix} Adding {len(context.get('features'))} discovered plugins to deep analysis scopes.")
            feature_name = feature.get("name")
            feature_code = feature.get("code")
            feature_path = feature.get("path")
            self.logger.debug(f"[{view}] Adding plugin '{feature_name}' to deep analysis scopes.")
            if feature_code and feature_path:
                deep_analysis_scopes.append({"code": feature_code, "path": feature_path, "name": feature_name})
                self.logger.debug(f"{log_prefix} Added plugin '{feature_name}' to deep analysis scopes.")
            else:
                self.logger.warning(f"{log_prefix} Plugin '{feature_name}' is missing code or path and will be skipped for deep analysis.")

        # Now, iterate through the collected scopes and run the deep analysis on each.
        self.logger.info(f"{log_prefix} Performing deep analysis on {len(deep_analysis_scopes)} total code scope(s).")
        for scope in deep_analysis_scopes:
            scope_name = scope.get("name")
            self.logger.debug(f"{log_prefix} Analyzing scope: '{scope_name}'...")
            
            # Find ORM calls within this scope
            orm_models = self._find_models_from_orm_calls_in_code(scope["code"], scope["path"])
            if orm_models:
                self.logger.debug(f"{log_prefix} Scope '{scope_name}': Found {len(orm_models)} ORM model references: {orm_models}")
                for model_name in orm_models:
                    if model_name not in processed_components:
                        self.logger.debug(f"[{view}] Discovered model '{model_name}' from ORM call in scope '{scope_name}'.")
                        model_ref = self.code_analyzer.get_symbol_reference(model_name, scope["path"], SymbolType.CLASS)
                        if model_ref:
                            synthetic_model_comp = self._create_synthetic_model_component_lean(model_ref['name'], model_ref['path'])
                            if synthetic_model_comp:
                                context['serializers'].append(synthetic_model_comp)
                                self.logger.debug(f"{log_prefix} Added synthetic component for model '{model_ref['name']}'.")

            # Find imperative serializers within this scope
            imperative_serializers = self._find_imperative_symbols_in_code(scope["code"], scope["path"], "Serializer")
            if imperative_serializers:
                self.logger.debug(f"{log_prefix} Scope '{scope_name}': Found {len(imperative_serializers)} imperative serializer references: {imperative_serializers}")
                for ser_name in imperative_serializers:
                    if ser_name not in processed_components:
                        self.logger.debug(f"[{view}] Discovered imperative serializer '{ser_name}' in scope '{scope_name}'.")
                        if ser_name in self.component_contexts:
                            ser_comp = self.component_contexts[ser_name]
                            context['serializers'].append(ser_comp)
                            processed_components.add(ser_name)
                            self.logger.debug(f"{log_prefix} Added imperative serializer component: '{ser_name}'.")
                            for model in ser_comp.get("data_classes", []):
                                processed_components.add(model['name'])
                        else:
                            self.logger.warning(f"{log_prefix} Imperative serializer '{ser_name}' was found in scope '{scope_name}' but is not in component cache.")

            meta_models = self._find_models_from_meta_class(scope["code"], scope["path"])
            if meta_models:
                self.logger.debug(f"{log_prefix} Scope '{scope_name}': Found {len(meta_models)} declarative models in Meta: {meta_models}")
                for model_name in meta_models:
                    if model_name not in processed_components:
                        # ... (same logic as before to create and add synthetic component) ...
                        model_ref = self.code_analyzer.get_symbol_reference(model_name, scope["path"], SymbolType.CLASS)
                        if model_ref:
                            synthetic_model_comp = self._create_synthetic_model_component_lean(model_ref['name'], model_ref['path'])
                            if synthetic_model_comp:
                                context['serializers'].append(synthetic_model_comp)
                                self.logger.debug(f"{log_prefix} Added synthetic component for Meta model '{model_ref['name']}'.")


        # --- Stage 3: Final Cleanup ---
        self.logger.info(f"{log_prefix} Raw context gathering complete. Running final de-duplication...")
        final_context = self._deduplicate_and_prioritize_context(context)
        self.logger.info(f"{log_prefix} Context gathering finished. Final context contains {len(final_context.get('serializers',[]))} serializer/model groups and {len(final_context.get('features',[]))} features.")

        return final_context
    
    def _create_component_from_string_path(self, component_path_str: str, component_type: str, processed_keys: set) -> Optional[Dict[str, Any]]:
        """
        Resolves a string component path (e.g., 'core.pagination.AppPagination')
        into a full feature component dictionary, including its source code.

        Args:
            component_path_str: The Python path to the component.
            component_type: The type of component ('pagination', 'authentication', etc.).
            processed_keys: A set of keys that have already been added to the context to prevent duplicates.

        Returns:
            A dictionary representing the feature component, or None if it cannot be resolved.
        """
        try:
            # Convert Python path to file path and class name
            # e.g., 'core.pagination.AppPagination' -> ('core/pagination', 'AppPagination')
            path_parts = component_path_str.split('.')
            class_name = path_parts[-1]
            module_path = ".".join(path_parts[:-1])
            
            # The code_analyzer should have a method to resolve a module to a file path.
            # We can adapt an existing helper for this. `_resolve_url_conf_to_file_path` is a good starting point.
            file_path = self._resolve_module_to_file_path(module_path)

            if not file_path:
                self.logger.error(f"Could not resolve module '{module_path}' to a file path.")
                return None
            
            component_key = f"{file_path}:{class_name}"
            if component_key in processed_keys:
                self.logger.debug(f"Default component '{component_key}' already processed. Skipping.")
                return None

            # Now that we have the file path and class name, we can get its info and code.
            class_info = self.code_analyzer.get_symbol_info(class_name, file_path, SymbolType.CLASS)
            if not class_info:
                self.logger.error(f"Could not get symbol info for default component '{class_name}' at '{file_path}'.")
                return None

            start_line = class_info.get("startLine")
            end_line = class_info.get("endLine")
            if not start_line or not end_line: return None

            component_code = self.code_analyzer.get_code_snippet(file_path, start_line, end_line)
            if not component_code: return None

            processed_keys.add(component_key) # Mark as processed
            
            self.logger.info(f"Successfully fetched code for default {component_type} component: '{class_name}'")
            return {
                "name": class_name,
                "path": file_path,
                "code": component_code,
                "type": component_type,
                "parent_classes": self.code_analyzer.get_class_inheritance_tree(class_name, file_path)
            }
        except Exception as e:
            self.logger.error(f"Failed to create component from string path '{component_path_str}': {e}", exc_info=True)
            return None

    def _resolve_module_to_file_path(self, module_str: str) -> Optional[str]:
        """
        Converts a Python module string (e.g., 'core.pagination') into a file path.
        This is a simplified helper; a robust implementation would check for packages vs. modules.
        """
        # This can be made more robust.
        rel_path = module_str.replace('.', '/') + '.py'
        # Search for this relative path within the project root.
        for root, _, files in os.walk(self.project_path):
            for file in files:
                full_path = os.path.join(root, file)
                if full_path.endswith(rel_path):
                    return os.path.abspath(full_path)
        return None # Not found
    
    def _find_models_from_orm_calls_in_code(self, code: str, context_path: str) -> List[str]:
        """
        Finds Django models by looking for `.objects` calls (e.g., `Job.objects.get()`).
        Returns a list of unique CANONICAL model names found.
        """
        found_models = set()
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == 'objects':
                    model_node = node.value
                    model_name_in_code = ast.unparse(model_node)

                    ref = self.code_analyzer.get_symbol_reference(model_name_in_code, context_path, SymbolType.CLASS)
                    if ref and ref.get('name'):
                        model_key = f"{ref['path']}:{ref['name']}"
                        if model_key in self.is_model:
                            found_models.add(ref['name'])
                            self.logger.debug(f"AST Discovery: Found ORM call for '{model_name_in_code}', resolved to model '{ref['name']}'.")

        except SyntaxError as e:
            self.logger.warning(f"AST Syntax Error while finding ORM calls in {context_path}: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error in _find_models_from_orm_calls_in_code for {context_path}: {e}", exc_info=True)

        return list(found_models)

    def _get_feature_components(self, viewset_code: str, path: str, is_done: Set[str]) -> List[Dict[str, Any]]:
        """
        Get custom feature components (pagination, authentication, filters) referenced
        in the handler code. Relies on feature classes being identified.
        (Same as previous response, but adds call to ensure identification)
        """
        feature_components = []
        if not viewset_code:
             return feature_components

        # Ensure feature component types are identified (lazily)
        self._ensure_feature_classes_identified()

        # Get classes referenced within the handler code
        referenced_classes = self.code_analyzer.get_referenced_classes(viewset_code, path)

        for ref_class in referenced_classes:
            ref_name = ref_class.get("name")
            ref_path = ref_class.get("path")

            if not ref_name or not ref_path:
                continue

            class_key = f"{ref_path}:{ref_name}"

            # Skip if already processed
            if class_key in is_done:
                continue

            feature_type = None
            # Check against the pre-populated dictionaries
            if class_key in self.is_pagination_class and self.is_pagination_class[class_key]:
                feature_type = "pagination"
            elif class_key in self.is_auth_class and self.is_auth_class[class_key]:
                feature_type = "authentication"
            elif class_key in self.is_filter_class and self.is_filter_class[class_key]:
                # Distinguish between FilterSet (more like a schema) and FilterBackend (more like logic) if needed
                # For now, just 'filter'
                feature_type = "filter"

            if feature_type:
                # Found a referenced feature class, get its details
                class_info = self.code_analyzer.get_symbol_info(ref_name, ref_path, SymbolType.CLASS)
                if not class_info:
                    if self.logger: self.logger.warning(f"Could not get info for identified {feature_type} class {ref_name} at {ref_path}")
                    continue

                start_line=class_info.get("startLine")
                end_line=class_info.get("endLine")
                if not start_line or not end_line: continue

                feature_code = self.code_analyzer.get_code_snippet(ref_path, start_line, end_line)
                if not feature_code: continue

                parent_classes = self.code_analyzer.get_class_inheritance_tree(ref_name, ref_path)

                feature_component = {
                    "name": ref_name,
                    "path": ref_path,
                    "start_line": start_line,
                    "end_line": end_line,
                    "code": feature_code,
                    "parent_classes": parent_classes,
                    "type": feature_type,
                    "functions": class_info.get("functions", {}),
                    "properties": class_info.get("properties", []),
                }
                feature_components.append(feature_component)
                is_done.add(class_key) # Mark feature component as processed
                # Also mark parents as processed
                for parent in parent_classes:
                    if parent.get("path") and parent.get("name"):
                        parent_key = f"{parent['path']}:{parent['name'].split('.')[-1]}"
                        is_done.add(parent_key)

                if self.logger: self.logger.debug(f"Added feature component: {feature_type} class {ref_name}")

        return feature_components
    
    def _create_synthetic_model_component_lean(self, model_name: str, model_path: str, max_depth: int = 2) -> Dict[str, Any]:
        """
        Creates a 'synthetic' component for a model and all its recursive dependencies.
        This version is leaner and does not handle de-duplication itself.
        """
        
        self.logger.debug(f"Creating synthetic component for model '{model_name}' at {model_path}...")
        model_info = self.code_analyzer.get_symbol_info(model_name, model_path, SymbolType.CLASS)
        if not model_info:
            return {}

        primary_model_key = f"{model_path}:{model_name}"
        visited_for_recursion = {primary_model_key}
        
        # This will now only collect *other* related models
        related_models_info = self._collect_related_data_classes(model_info, visited_for_recursion, current_depth=0, max_depth=max_depth)
        
        # The list of all models to get code for is now JUST the related ones.
        all_model_infos = related_models_info # No longer includes the primary model_info

        final_data_classes = []
        seen_final_keys = set()
        for m_info in all_model_infos:
            key = f"{m_info['path']}:{m_info['name']}"
            if key not in seen_final_keys:
                model_code = self.code_analyzer.get_code_snippet(m_info['path'], m_info.get('startLine', 0), m_info.get('endLine', 0))
                if model_code:
                    final_data_classes.append({
                        "name": m_info['name'],
                        "path": m_info['path'],
                        "code": model_code
                    })
                    seen_final_keys.add(key)
        
        # The main component still holds the code for the primary model
        primary_model_code = self.code_analyzer.get_code_snippet(model_path, model_info.get('startLine'), model_info.get('endLine'))

        self.logger.debug(f"Synthetic component for '{model_name}' now contains {len(final_data_classes)} *other* related models.")
        
        return {
            "name": model_name,
            "path": model_path,
            "code": primary_model_code,
            "type": "model_group",
            "data_classes": final_data_classes # This list no longer contains the primary model
        }

    def _get_serializer(self, is_serializer, viewset_code, path, is_done):
        """
        Get serializer code used in a viewset.
        
        Args:
            is_serializer: Dictionary mapping class keys to serializer status
            viewset_code: Viewset code
            result: Analysis results
            path: Path to the file containing the viewset
            is_model: Dictionary mapping class keys to model status
            is_done: Set of already processed classes
            
        Returns:
            String containing serializer code
        """
        if not self.component_contexts:
            self.logger.warning("Component context cache is empty. This may indicate an issue in execution order. Populating now as a fallback.")
            self.get_schema_components()

        referenced_serializers_in_view = []
        referenced_classes = self.code_analyzer.get_referenced_classes(viewset_code, path)
        for ref_class in referenced_classes:
            class_name = ref_class.get("name")
            
            # Check if the referenced class is a serializer by looking it up in our cache.
            if class_name in self.component_contexts:
                # Retrieve the full, rich context directly from the cache.
                referenced_serializers_in_view.append(self.component_contexts[class_name])
                self.logger.debug(f"Retrieved cached context for serializer '{class_name}' for endpoint defined in '{path}'.")
        
        return referenced_serializers_in_view
    
    def _get_model_code(self, code, result, path, is_model, is_done, external_parent=None):
        """
        Get model code referenced in serializer code.
        
        Args:
            code: Serializer code
            result: Analysis results
            path: Path to the file containing the serializer
            is_model: Dictionary mapping class keys to model status
            is_done: Set of already processed classes
            external_parent: Set of external parent models
            
        Returns:
            String containing model code
        """
        if external_parent is None:
            external_parent = set()
        
        prompt = "===###===\n"
        
        try:
            tree = ast.parse(code)
            # Get identifiers in the file
            identifiers = result[path]["identifiers"]["classes"]
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    fname = ast.unparse(node)
                    # Check if the name is a model in our identifiers
                    if fname in identifiers:
                        fpath = identifiers[fname]["path"]
                        key = f"{fpath}:{fname}"
                        
                        # Check if it's a model
                        if key in is_model and is_model[key]:
                            # Get model code
                            start_line = result[fpath]["classes"][fname]["startLine"]
                            end_line = result[fpath]["classes"][fname]["endLine"]
                            fcode = self.code_analyzer.get_code_snippet(fpath, start_line, end_line)
                            
                            if fname not in is_done:
                                is_done.add(fname)
                                prompt += f"Source File: {fpath}\n"
                                prompt += f"Line Number: {start_line}-{end_line}\n"
                                prompt += f"Code Snippet:\n {fcode}\n"
                                prompt += self._get_parent_code(result, fpath, fname, identifiers, is_done, external_parent)
                                prompt += self._get_model_code(fcode, result, fpath, is_model, is_done, external_parent)
                
                # Check attribute references (e.g., model.field)
                elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    fname = ast.unparse(node)
                    if fname in identifiers:
                        fpath = identifiers[fname]["path"]
                        key = f"{fpath}:{fname}"
                        
                        if key in is_model and is_model[key]:
                            name = identifiers[fname]["name"]
                            start_line = result[fpath]["classes"][name]["startLine"]
                            end_line = result[fpath]["classes"][name]["endLine"]
                            fcode = self.code_analyzer.get_code_snippet(fpath, start_line, end_line)
                            
                            if fname not in is_done:
                                is_done.add(fname)
                                prompt += f"Source File: {fpath}\n"
                                prompt += f"Line Number: {start_line}-{end_line}\n"
                                prompt += f"Code Snippet:\n {fcode}\n"
                                prompt += self._get_parent_code(result, fpath, name, identifiers, is_done, external_parent)
                                prompt += self._get_model_code(fcode, result, fpath, is_model, is_done, external_parent)
        except SyntaxError:
            # Handle potential syntax errors in code chunks
            self.logger.warning(f"Syntax error while extracting models from code: {code[:100]}...")
        
        return prompt

    def _get_feature_code(self, viewset_code, path, is_done):
        """
        Get feature-related code (pagination, authentication, filters).
        
        Args:
            viewset_code: Viewset code
            path: Path to the file containing the viewset
            is_done: Set of already processed classes
            
        Returns:
            String containing feature code
        """
        feature_code = ""
        
        # Add default settings for pagination, authentication, filters
        for feature_name in ["pagination", "authentication", "filter"]:
            feature_prompt = self._get_feature_prompt(feature_name)
            if feature_prompt:
                feature_code += f"\t{feature_prompt}\n"
        
        return feature_code

    def _get_feature_prompt(self, feature_name):
        """
        Get feature default settings prompt.
        
        Args:
            feature_name: Name of the feature (pagination, authentication, filter)
            
        Returns:
            String containing feature prompt
        """
        if feature_name == "pagination":
            if "DEFAULT_PAGINATION_CLASS" in self.default_settings:
                prompt = f"The following is the pagination class defined at the project level: {self.default_settings['DEFAULT_PAGINATION_CLASS']}."
                if "PAGE_SIZE" in self.default_settings:
                    prompt += f" The default page size is {self.default_settings['PAGE_SIZE']}."
                return prompt + " Use the aforementioned pagination class and page size as default until and unless overridden somewhere in the code."
            return "Default pagination class not set in project's settings. Assume no pagination unless overridden somewhere."
        
        elif feature_name == "authentication":
            if "DEFAULT_AUTHENTICATION_CLASSES" in self.default_settings:
                auth_classes = self.default_settings["DEFAULT_AUTHENTICATION_CLASSES"]
                prompt = "The following are the authentication classes defined at the project level: "
                prompt += ", ".join(auth_classes)
                return prompt + ". Use the aforementioned authentication classes as default until and unless overridden somewhere in the code."
            return "Default authentication classes are not set in the project's settings. Assume these as the default authentication classes unless overridden somewhere: `rest_framework.authentication.SessionAuthentication` and `rest_framework.authentication.BasicAuthentication`."
        
        elif feature_name == "filter":
            if "DEFAULT_FILTER_BACKENDS" in self.default_settings:
                filter_backends = self.default_settings["DEFAULT_FILTER_BACKENDS"]
                prompt = "The following are the filter backends defined at the project level: "
                prompt += ", ".join(filter_backends)
                return prompt + ". Use the aforementioned filter backends as the default until and unless overridden somewhere in the code."
            return "Default filter backends are not set in the project's settings. Assume that the default filter backends are NONE unless overridden somewhere."
        
        return ""
    

    # --- Feature Class Identification ---
    def _identify_component_type(self, file_path: str, cls_name: str,
                                 component_dict: Dict[str, bool],
                                 base_class_names: Set[str],
                                 visited: Set[str]) -> bool:
        """
        Generic helper to determine if a class inherits from a set of base classes.
        Uses memoization via component_dict and a visited set for recursion cycle handling.
        (Same as previous response - this is safe and generic)
        """
        # Handle cases where class name contains a dot (e.g., from imports)
        clean_cls_name = cls_name.split(".")[-1]
        key = f"{file_path}:{clean_cls_name}"

        # Return cached result if available in the specific component_dict
        if key in component_dict:
            return component_dict[key]

        # Avoid infinite recursion using the visited set for the current path
        if key in visited:
            return False
        visited.add(key)

        class_info = self.code_analyzer.get_symbol_info(clean_cls_name, file_path, SymbolType.CLASS)
        if not class_info:
            component_dict[key] = False
            visited.remove(key) # Backtrack
            return False

        is_target_type = False
        parent_classes = class_info.get("parentClasses", {})

        for parent_full_name, parent_details in parent_classes.items():
            parent_name_only = parent_full_name.split(".")[-1] # Get the base name

            # Direct check against base names (including module prefixes if present)
            if any(base_name in parent_full_name for base_name in base_class_names):
                 is_target_type = True
                 break

            # Recursively check parent classes if path is known
            parent_path = parent_details.get("path")
            if parent_path:
                 # Pass the same visited set down the recursion path
                if self._identify_component_type(parent_path, parent_name_only, component_dict, base_class_names, visited):
                    is_target_type = True
                    break

        component_dict[key] = is_target_type
        visited.remove(key) # Backtrack: Remove from visited after exploring this node's branch
        return is_target_type

    def _ensure_feature_classes_identified(self):
        """
        Identifies Pagination, Authentication, and Filter classes across the project
        if not already done. Populates the respective self.is_* dictionaries.
        """
        if self._feature_classes_identified:
            return

        if self.logger: self.logger.info("Performing feature class identification...")

        all_files = self.code_analyzer.get_analyzed_files()
        if not all_files:
             if self.logger: self.logger.warning("No analyzed files found by CodeAnalyzer for feature identification.")
             self._feature_classes_identified = True # Mark as done even if no files
             return

        # Reset dictionaries before identification
        self.is_pagination_class = {}
        self.is_auth_class = {}
        self.is_filter_class = {}

        # Process each file
        for file_path in all_files:
            classes_in_file = self.code_analyzer.get_file_classes(file_path)
            if not classes_in_file:
                continue

            for cls_name in classes_in_file.keys():
                # Identify Pagination Classes
                # Pass a new visited set for each top-level call to _identify_component_type
                self._identify_component_type(file_path, cls_name, self.is_pagination_class, self.BASE_PAGINATION_CLASSES, set())

                # Identify Authentication Classes
                self._identify_component_type(file_path, cls_name, self.is_auth_class, self.BASE_AUTH_CLASSES, set())

                # Identify Filter Classes/FilterSets
                self._identify_component_type(file_path, cls_name, self.is_filter_class, self.BASE_FILTER_CLASSES, set())

        self._feature_classes_identified = True
        if self.logger:
            self.logger.info("Feature class identification complete.")
            self.logger.debug(f"Found {sum(self.is_pagination_class.values())} pagination classes.")
            self.logger.debug(f"Found {sum(self.is_auth_class.values())} auth classes.")
            self.logger.debug(f"Found {sum(self.is_filter_class.values())} filter classes.")

    #schema related 
    def _identify_all_serializers(self):
        """
        Helper to proactively identify all serializers if not already done.
        This populates `self.is_serializer`.
        """
        if self.is_serializer: # Check if already populated
            return

        all_files = self.code_analyzer.get_analyzed_files()
        if not all_files:
            self.logger.warning("No analyzed files found to identify serializers.")
            return

        self.logger.info("Performing proactive identification of all DRF serializers...")
        for file_path in all_files:
            classes_in_file = self.code_analyzer.get_file_classes(file_path)
            for cls_name in classes_in_file.keys():
                self._identify_serializer(file_path, cls_name) # This populates self.is_serializer

        self.logger.info(f"Serializer identification complete. Found {len(self.is_serializer)} potential serializers.")


    def _build_single_component_context(self, class_name: str, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Builds the rich context for a SINGLE serializer, finding only its DIRECT dependencies.
        This method does NOT recurse.
        """
        serializer_info = self.code_analyzer.get_symbol_info(class_name, file_path, SymbolType.CLASS)
        if not serializer_info:
            return None
        
        component_code = self.code_analyzer.get_code_snippet(file_path, serializer_info.get('startLine'), serializer_info.get('endLine'))

        direct_dependencies = []
        processed_dep_keys = set()

        def add_dependency(dep_component):
            if not dep_component: return
            dep_key = self._get_symbol_key(dep_component)
            if dep_key and dep_key not in processed_dep_keys:
                direct_dependencies.append(dep_component)
                processed_dep_keys.add(dep_key)
                
        # 1. Find and add direct Model dependencies
        model_deps = self._get_model_dependencies(serializer_info)
        for model_info in model_deps:
            model_key = self._get_symbol_key(model_info)
            if model_key and model_key not in processed_dep_keys:
                direct_dependencies.append(self._build_model_component(model_info))
                processed_dep_keys.add(model_key)

        # 2. Find and add direct nested Serializer dependencies
        nested_serializer_refs = self._get_nested_serializer_refs(class_name, file_path)
        for ref in nested_serializer_refs:
            ref_key = self._get_symbol_key(ref)
            if ref_key and ref_key not in processed_dep_keys:
                # For serializers, we fetch their full info to create the dependency dict.
                nested_info = self.code_analyzer.get_symbol_info(ref['name'], ref['path'], SymbolType.CLASS)
                if nested_info:
                    direct_dependencies.append(self._build_serializer_ref_component(nested_info))
                    processed_dep_keys.add(ref_key)
        
        orm_models = self._find_models_from_orm_calls_in_code(component_code, file_path)
        for model_name in orm_models:
            ref = self.code_analyzer.get_symbol_reference(model_name, file_path, SymbolType.CLASS)
            if ref:
                model_info = self.code_analyzer.get_symbol_info(ref['name'], ref['path'], SymbolType.CLASS)
                if model_info:
                    add_dependency(self._build_model_component(model_info))
        
        # After potentially adding more dependencies, update the list
        # The direct_dependencies list has been modified in place by add_dependency
        final_dependency_list = direct_dependencies
        
        # Assemble the final component with its flat list of direct dependencies.
        return {
            "name": class_name,
            "path": file_path,
            "code": self.code_analyzer.get_code_snippet(file_path, serializer_info.get('startLine'), serializer_info.get('endLine')),
            "parent_classes": self.code_analyzer.get_class_inheritance_tree(class_name, file_path),
            "type": "serializer",
            "data_classes": final_dependency_list, # Flat list of direct dependencies
            "start_line": serializer_info.get('startLine'),
            "end_line": serializer_info.get('endLine'),
            "functions": serializer_info.get("functions", {}),
            "properties": serializer_info.get("properties", []),
            "supports_request": True,
            "supports_response": True,
            "inner_classes": self.code_analyzer.get_inner_classes(class_name, file_path),
        }

    def _build_serializer_ref_component(self, serializer_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Creates the dictionary structure for a nested serializer to be placed in `data_classes`.
        This is lean and contains just enough info to be identified as a dependency.
        """
        ser_name = serializer_info['name']
        ser_path = serializer_info['path']
        return {
            "name": ser_name,
            "path": ser_path,
            "code": self.code_analyzer.get_code_snippet(ser_path, serializer_info.get('startLine', 0), serializer_info.get('endLine', 0)),
            "type": "serializer", 
        }

    def get_schema_components(self) -> Dict[str, Dict[str, Any]]:
        """
        Extracts schema components (serializers), finds all their nested dependencies
        (serializers and models) iteratively, and returns a rich context for each.
        This is the main orchestrator for pre-processing all components.
        """
        # Step 1: Ensure all models and serializers in the project are identified.
        self._identify_all_models()
        self._identify_all_serializers() # Create this new helper

        # This dictionary will be our master cache, keyed by 'path:name'.
        # It stores the final, rich component data.
        all_components_cache: Dict[str, Dict[str, Any]] = {}

        # This set will hold the keys of components we need to process in the next wave.
        # Start with all serializers identified in the project.
        processing_queue = {key for key, is_ser in self.is_serializer.items() if is_ser}
        
        # Use a set to track what has been queued to avoid adding duplicates to the queue.
        queued_keys = set(processing_queue)

        self.logger.info(f"Starting component processing with {len(processing_queue)} top-level serializers.")

        while processing_queue:
            # Process all items currently in the queue (one "wave" or "depth level").
            current_wave_keys = list(processing_queue)
            processing_queue.clear() # Clear the queue for the next wave
            
            self.logger.debug(f"Processing wave with {len(current_wave_keys)} components.")

            for component_key in current_wave_keys:
                # If it's already been fully processed in a previous wave (e.g., as a dependency), skip.
                if component_key in all_components_cache:
                    continue

                file_path, class_name = component_key.split(":")

                # Build the rich context for this single component.
                component_context = self._build_single_component_context(class_name, file_path)
                if not component_context:
                    continue
                
                # Store the final, rich context in our master cache.
                all_components_cache[component_key] = component_context

                # Now, find all direct dependencies of the component we just built.
                for dependency in component_context.get("data_classes", []):
                    dep_key = self._get_symbol_key(dependency)
                    
                    # If this dependency is a serializer and we haven't processed or queued it yet,
                    # add it to the queue for the *next* wave.
                    if self.is_serializer.get(dep_key) and dep_key not in queued_keys:
                        processing_queue.add(dep_key)
                        queued_keys.add(dep_key)
                        self.logger.debug(f"Queued nested serializer dependency '{dep_key}' for next wave.")

        self.logger.info(f"Finished processing all components. Total unique components built: {len(all_components_cache)}")

        # The final step is to create the dictionary keyed by simple name for the caller.
        final_components_by_name = {
            comp['name']: comp 
            for comp in all_components_cache.values() 
            if comp.get('type') == 'serializer' # Only return serializers at the top level
        }
        
        self.component_contexts = final_components_by_name
        return self.component_contexts

    def _identify_serializer(self, file_path: str, cls_name: str) -> bool:
        """
        Determine if a class is a serializer by checking its inheritance hierarchy.
        Also identifies associated models for ModelSerializers.
        """
        self.logger.debug(f"[_identify_serializer] Checking: {cls_name} in {file_path}")
        # Handle cases where class name contains a dot
        if "." in cls_name:
            cls_name = cls_name.split(".")[-1]
        
        # Create key for lookups
        key = f"{file_path}:{cls_name}"
        
        # Return cached result if available
        if key in self.is_serializer:
            self.logger.debug(f"[_identify_serializer] Result for {key} found in cache: {self.is_serializer[key]}")
            return self.is_serializer[key]
        
        class_info = self.code_analyzer.get_symbol_info(cls_name, file_path, SymbolType.CLASS)
        if not class_info:
            self.logger.debug(f"[_identify_serializer] No symbol info found for {key}. Caching result: False.")
            self.is_serializer[key] = False
            return False
        
        #todo this is hardcoded assumption of structure. we will finalize the interface and remove it
        parent_classes = class_info["parentClasses"]
        is_serializer_ = False

        self.logger.debug(f"[_identify_serializer] Analyzing parents for {cls_name}: {list(parent_classes.keys())}")
        for parent_class, parent_details in parent_classes.items():
            # If parent class contains "Serializer"
            if "Serializer" in parent_class:
                is_serializer_ = True
                self.logger.debug(f"[_identify_serializer] Found 'Serializer' in direct parent '{parent_class}' for {cls_name}. Marking as serializer.")
                break
            
            # Recursively check parent classes
            if parent_details.get("path"):
                parent_name = parent_class.split(".")[-1]
                is_serializer_ = self._identify_serializer(
                    parent_details["path"], 
                    parent_name
                )
                if is_serializer_:
                    self.logger.debug(f"[_identify_serializer] Recursive check confirmed parent '{parent_name}' is a serializer. Marking {cls_name} as serializer.")

        if not is_serializer_:
            self.is_serializer[key] = False
            return False

        self.logger.debug(f"[_identify_serializer] Final decision for {key}: {is_serializer_}. Caching result.")

        self.is_serializer[key] = is_serializer_
        return is_serializer_

    def _build_component_and_dependencies_recursive(self, class_name: str, file_path: str, all_components_cache: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Builds a single component if not already cached. Finds all its dependencies (models and serializers),
        ensures they are also built and cached via recursion, and returns the final component
        with all dependency contexts nested inside its `data_classes` key.
        """
        component_key = f"{file_path}:{class_name}"

        # Base Case 1: If component is already fully built and cached, return it.
        if component_key in all_components_cache:
            return all_components_cache[component_key]

        # --- Start building the new component ---
        self.logger.debug(f"Building component for: {component_key}")
        
        serializer_info = self.code_analyzer.get_symbol_info(class_name, file_path, SymbolType.CLASS)
        if not serializer_info:
            self.logger.warning(f"Could not get symbol info for component '{component_key}'")
            return None

        # Temporarily add a placeholder to the cache to handle circular dependencies.
        all_components_cache[component_key] = {"name": class_name, "path": file_path, "status": "processing"}

        # --- Gather all dependencies ---
        dependency_contexts = []
        processed_dep_keys = set()

        # 1. Find and process Model dependencies
        model_deps = self._get_model_dependencies(serializer_info)
        for model_info in model_deps:
            model_key = f"{model_info['path']}:{model_info['name']}"
            if model_key not in processed_dep_keys:
                dependency_contexts.append(self._build_model_component(model_info))
                processed_dep_keys.add(model_key)

        # 2. Find and process nested Serializer dependencies
        nested_serializer_refs = self._get_nested_serializer_refs(class_name, file_path)
        for ref in nested_serializer_refs:
            ref_key = f"{ref['path']}:{ref['name']}"
            if ref_key not in processed_dep_keys:
                # RECURSIVE CALL: build the nested serializer component.
                # This will either build it or return it from the cache.
                nested_comp_context = self._build_component_and_dependencies_recursive(ref['name'], ref['path'], all_components_cache)
                if nested_comp_context:
                    dependency_contexts.append(nested_comp_context)
                processed_dep_keys.add(ref_key)

        # --- Assemble the final component with all dependencies unified in `data_classes` ---
        component_data = {
            "name": class_name,
            "path": file_path,
            "code": self.code_analyzer.get_code_snippet(file_path, serializer_info.get('startLine'), serializer_info.get('endLine')),
            "parent_classes": self.code_analyzer.get_class_inheritance_tree(class_name, file_path),
            "type": "serializer",
            "data_classes": dependency_contexts,
            "start_line": serializer_info.get('startLine'),
            "end_line": serializer_info.get('endLine'),
            "functions": serializer_info.get("functions", {}),
            "properties": serializer_info.get("properties", []),
            "inner_classes": self.code_analyzer.get_inner_classes(class_name, file_path),
        }

        # Replace the placeholder in the cache with the fully built component.
        all_components_cache[component_key] = component_data
        self.logger.debug(f"Finished building component for: {component_key}")
        return component_data

    def _get_nested_serializer_refs(self, serializer_name: str, serializer_path: str) -> List[Dict[str, str]]:
        """
        Analyzes a serializer's AST to find fields that are other serializers.
        Returns a list of lightweight references {'name': ..., 'path': ...}.
        """
        refs = []
        class_ast = self.code_analyzer.get_class_ast(serializer_name, serializer_path)
        if not class_ast:
            return refs

        for node in ast.walk(class_ast):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                potential_ser_name = ast.unparse(node.value.func)
                ref = self.code_analyzer.get_symbol_reference(potential_ser_name, serializer_path, SymbolType.CLASS)
                if ref:
                    resolved_key = f"{ref['path']}:{ref['name']}"
                    if self.is_serializer.get(resolved_key):
                        refs.append({'name': ref['name'], 'path': ref['path'], 'type': 'serializer'})
        return refs

    def _get_model_dependencies(self, serializer_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Finds the primary model and all its related models for a given serializer.
        This reuses your existing model-finding logic.
        """
        serializer_name = serializer_info.get('name')
        serializer_path = serializer_info.get('path')

        inner_classes_data = self.code_analyzer.get_inner_classes(serializer_name, serializer_path)
        primary_model_info = self._get_primary_model_info_from_serializer(inner_classes_data, serializer_path)

        all_model_infos = []
        if primary_model_info:
            visited_model_keys = {f"{primary_model_info['path']}:{primary_model_info['name']}"}
            all_model_infos.append(primary_model_info)
            nested_models = self._collect_related_data_classes(primary_model_info, visited_model_keys)
            all_model_infos.extend(nested_models)
        
        for info in all_model_infos:
            info['type'] = 'model' # Add the type key
        return all_model_infos

    def _build_model_component(self, model_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Creates the standard dictionary structure for a model to be placed in `data_classes`.
        """
        model_name = model_info['name']
        model_path = model_info['path']
        model_code = self.code_analyzer.get_code_snippet(
            model_path, model_info.get('startLine', 0), model_info.get('endLine', 0)
        )
        # The 'type' key here is just for internal description; it won't be in the final JSON
        # unless you want it to be. The prompt manager doesn't use it.
        return {
            "name": model_name,
            "path": model_path,
            "code": model_code,
            "type": "model", 
            "parent_classes": self.code_analyzer.get_class_inheritance_tree(model_name, model_path),
            "properties": model_info.get('properties', []),
            "methods": model_info.get('functions', {})
        }
    
    def _collect_related_data_classes(self, model_class_info: Dict[str, Any], visited_keys: Set[str], current_depth: int = 0, max_depth: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Given the structured info for a model, analyzes its AST to find all
        directly related models via its relationship fields, and then recurses.
        """
        if max_depth is not None and current_depth >= max_depth:
            self.logger.debug(f"Max depth ({max_depth}) reached. Stopping recursion for dependencies of '{model_class_info.get('name')}'.")
            return []
        
        related_models_info = []
        model_name = model_class_info.get('name')
        model_path = model_class_info.get('path')

        if not model_name or not model_path:
            return []

        # Get the AST for the model class definition.
        class_ast = self.code_analyzer.get_class_ast(model_name, model_path)
        if not class_ast:
            self.logger.warning(f"Could not retrieve AST for model {model_name} at {model_path}")
            return []

        # 1. Iterate through the model's fields (ast.Assign nodes in the class body).
        for node in class_ast.body:
            if not isinstance(node, ast.Assign):
                continue

            # 2. Check if the assignment is a Django Relationship Field.
            related_model_name = self._get_related_model_from_assignment(node)
            if not related_model_name:
                continue

            # 3. Resolve the found model name to its own class_info.
            related_model_info = self._resolve_django_model_reference(
                reference=related_model_name,
                current_model_info=model_class_info,
                context_path=model_path
            )
            if not related_model_info:
                continue

            related_model_key = f"{related_model_info['path']}:{related_model_info['name']}"

            # 4. If we haven't processed this related model yet, add it and recurse.
            if related_model_key not in visited_keys:
                visited_keys.add(related_model_key)

                # Add the newly found model's info to our results for this level.
                related_models_info.append(related_model_info)

                # 5. RECURSE: Call this function on the newly found model.
                nested_related_models = self._collect_related_data_classes(
                    related_model_info,
                    visited_keys,
                    current_depth + 1,
                    max_depth
                )
                related_models_info.extend(nested_related_models)

        return related_models_info

    def _resolve_django_model_reference(self, reference: str, current_model_info: Dict[str, Any], context_path: str) -> Optional[Dict[str, Any]]:
        """
        Resolves a model reference which can be a direct name, a lazy-loaded
        string ('app.Model' or 'Model'), or 'self'. This version correctly uses
        the CodeAnalyzer interface instead of direct result access.

        Args:
            reference: The model reference string or name to resolve.
            current_model_info: The full info dictionary of the model containing the reference.
                                Required for handling the 'self' case.
            context_path: The file path where the reference occurs.

        Returns:
            The full class_info dictionary for the resolved model, or None.
        """
        # Case 1: Handle self-reference
        if reference.lower() == 'self':
            self.logger.debug(f"Resolved model reference 'self' to current model '{current_model_info.get('name')}'.")
            return current_model_info

        # Case 2: Handle lazy-loaded string reference (e.g., 'reviews.Supplier')
        if '.' in reference:
            try:
                app_label, model_name = reference.rsplit('.', 1)
            except ValueError:
                self.logger.warning(f"Invalid lazy model reference format: '{reference}'. Skipping.")
                return None

            # Get all analyzed files from the CodeAnalyzer.
            all_analyzed_files = self.code_analyzer.get_analyzed_files()
            if not all_analyzed_files:
                self.logger.error("Cannot resolve lazy model reference: CodeAnalyzer returned no analyzed files.")
                return None

            # Search for the model file path based on the app_label.
            target_path_suffix = os.path.join(app_label, 'models.py')
            found_model_file_path = None
            for file_path in all_analyzed_files:
                if file_path.endswith(target_path_suffix):
                    found_model_file_path = file_path
                    break
            
            if found_model_file_path:
                # We found the file. Now use the public interface to get the class info.
                # The context_path for get_symbol_info here is the file where the symbol is defined.
                resolved_info = self.code_analyzer.get_symbol_info(model_name, found_model_file_path, SymbolType.CLASS)
                if resolved_info:
                    self.logger.debug(f"Resolved lazy reference '{reference}' to class '{model_name}' in '{found_model_file_path}'.")
                    return resolved_info
                else:
                    self.logger.warning(f"Found model file '{found_model_file_path}' for '{reference}', but class '{model_name}' not found within it.")
                    return None
            else:
                self.logger.warning(f"Could not find a 'models.py' file for app_label '{app_label}' to resolve lazy reference '{reference}'.")
                return None

        # Case 3: Handle direct class name reference (e.g., Manufacturer)
        # This falls back to the original, generic resolution logic, which correctly uses the public interface.
        self.logger.debug(f"Attempting to resolve '{reference}' as a direct, imported class name.")
        return self._resolve_model_name_to_class_info(reference, context_path)
    
    def _identify_all_models(self):
        """
        Proactively identifies all Django models in the project by checking for
        inheritance from 'django.db.models.Model'. This populates self.is_model
        for reliable lookups later.
        """
        if self._models_identified:
            return

        all_analyzed_files = self.code_analyzer.get_analyzed_files()
        if not all_analyzed_files:
            self.logger.error("Cannot identify models: CodeAnalyzer returned no analyzed files.")
            self._models_identified = True # Mark as "done" to avoid retrying.
            return

        self.logger.info("Starting proactive identification of all Django models...")

        # Step 3: Build a complete list of every class in the project to check.
        all_classes_to_check = []
        for file_path in all_analyzed_files:
            # Use the public interface to get classes for a file.
            classes_in_file = self.code_analyzer.get_file_classes(file_path)
            for class_name in classes_in_file.keys():
                all_classes_to_check.append({'path': file_path, 'name': class_name})

        self.logger.debug(f"Found {len(all_classes_to_check)} total classes to check for model inheritance.")

        # Step 4: Iterate through the complete list and check each one.
        # This loop MUST run to completion for all classes. There is no early return.
        for class_ref in all_classes_to_check:
            class_path = class_ref['path']
            class_name = class_ref['name']
            
            # The key for storing results.
            class_key = f"{class_path}:{class_name}"

            # The recursive helper `_is_django_model_recursive_check` does the heavy lifting.
            # It needs a new 'visited' set for each top-level call to handle potential
            # cycles within that specific class's inheritance check.
            is_model = self._is_django_model_recursive_check(class_path, class_name, set())
            print(f"{class_key} {is_model}")
            if is_model:
                # If it's a model, add it to our comprehensive map.
                self.is_model[class_key] = True
                self.logger.debug(f"Identified Model: {class_key}")

        # Step 5: After checking all classes, set the flag and log the final count.
        self._models_identified = True
        self.logger.info(f"Model identification complete. Found {len(self.is_model)} models in total.")
    
    def _is_django_model_recursive_check(self, class_path: str, class_name: str, visited: set) -> bool:
        """
        Recursively checks if a class inherits from 'django.db.models.Model'.
        
        Args:
            class_path: The file path of the class to check.
            class_name: The name of the class to check.
            visited: A set to track visited classes and prevent infinite recursion.
        """
        class_key = f"{class_path}:{class_name}"
        if class_key in visited:
            return False # Cycle detected
        visited.add(class_key)

        try:
            inheritance_tree = self.code_analyzer.get_class_inheritance_tree(class_name, class_path)
        except Exception as e:
            self.logger.error(f"Error getting inheritance tree for {class_key}: {e}")
            return False

        for parent_info in inheritance_tree:
            parent_full_name = parent_info.get("name")
            if parent_full_name and ('models.Model' in parent_full_name or 'db.models.Model' in parent_full_name):
                # We found the base model, this is a Django model.
                return True

        return False

    def _get_primary_model_info_from_serializer(self, inner_classes_data: Dict[str, Any], serializer_path: str) -> Optional[Dict[str, Any]]:
        meta_class_info = inner_classes_data.get('Meta')
        if not meta_class_info: return None
        
        model_name_str = meta_class_info.get('property_assignments', {}).get('model')
        if not model_name_str:
            self.logger.warning(f"Could not find 'model' property assignment in Meta class for serializer at {serializer_path}")
            return None
        
        return self._resolve_model_name_to_class_info(model_name_str, serializer_path)

    def _get_related_model_from_assignment(self, assign_node: ast.Assign) -> Optional[str]:
        """
        If an assignment is a Django relationship field (ForeignKey, etc.),
        this extracts the referenced model name string.
        """
        if not isinstance(assign_node.value, ast.Call):
            return None

        call_func_str = ast.unparse(assign_node.value.func)
        relationship_fields = {'ForeignKey', 'OneToOneField', 'ManyToManyField'}

        if not any(field_name in call_func_str for field_name in relationship_fields):
            return None

        # Check 'through' keyword argument for ManyToManyField first.
        for kw in assign_node.value.keywords:
            if kw.arg == 'through':
                if isinstance(kw.value, (ast.Constant, ast.Str)):
                    return kw.value.value
                elif isinstance(kw.value, ast.Name):
                    return kw.value.id

        # If not a 'through' M2M, the related model is the first positional argument.
        if not assign_node.value.args:
            return None

        first_arg = assign_node.value.args[0]
        if isinstance(first_arg, ast.Name):  # e.g., ForeignKey(Category, ...)
            return first_arg.id
        elif isinstance(first_arg, (ast.Constant, ast.Str)):  # e.g., ForeignKey('reviews.Supplier', ...)
            return first_arg.value

        return None

    def _resolve_model_name_to_class_info(self, model_name: str, context_path: str) -> Optional[Dict[str, Any]]:
        """
        Takes a model name (which could be simple like 'Category' or string-based like
        'reviews.Supplier') and resolves it to its full class_info dictionary.
        """
        # Use the code_analyzer's symbol resolution, which is designed for this.
        ref = self.code_analyzer.get_symbol_reference(model_name, context_path, SymbolType.CLASS)
        if not ref:
            self.logger.warning(f"Could not resolve model reference '{model_name}' from context '{context_path}'.")
            return None

        # Now that we have the canonical path and name, check if it's a known model.
        model_key = f"{ref['path']}:{ref['name']}"
        if model_key not in self.is_model:
            # It's a valid class, but not a model we care about.
            return None

        # Get the full class_info for this resolved model.
        return self.code_analyzer.get_symbol_info(ref['name'], ref['path'], SymbolType.CLASS)
    

    #prompt related 
    #TODO: the parsing should not be done by the framework layer
    def parse_missing_symbols_response(self, response_content: str) -> List[Dict[str, str]]:
        """
        Parses the JSON response from the LLM that identifies missing symbols.

        Args:
            response_content: The raw string content from the LLM (expected to be JSON).

        Returns:
            A list of dictionaries, each representing a required symbol,
            e.g., [{"name": "MyClass", "type": "class", "context_path": "/path/to/file.py"}, ...]
            Returns an empty list if parsing fails or no symbols are found.
        """
        required_symbols = []
        if not response_content:
            self.logger.debug("Received empty response for missing symbols.")
            return required_symbols

        try:
            # The LLM might wrap the JSON in backticks or add explanations.
            # Try to extract JSON robustly.
            json_match = re.search(r"\{.*\}", response_content, re.DOTALL)
            if not json_match:
                self.logger.warning(f"Could not find JSON object in missing symbols response: {response_content[:200]}...")
                return required_symbols

            extracted_json_str = json_match.group(0)
            data = json.loads(extracted_json_str)

            # Adjust parsing based on the actual JSON structure returned by the prompt
            # Example structure assumed: {"missing_symbols": [{"name": ..., "type": ..., "context_path": ...}]}
            symbols_list = data.get("missing_symbols", [])

            if not isinstance(symbols_list, list):
                self.logger.warning(f"Expected 'missing_symbols' to be a list, but got: {type(symbols_list)}")
                return required_symbols

            for item in symbols_list:
                if isinstance(item, dict) and "name" in item and "type" in item and "context_path" in item:
                    # Basic validation
                    symbol_type_str = item.get("type", "").lower()
                    symbol_type = None
                    if symbol_type_str == "class":
                        symbol_type = SymbolType.CLASS
                    elif symbol_type_str == "function":
                        symbol_type = SymbolType.FUNCTION
                    elif symbol_type_str == "variable":
                        # Assuming variables might be needed, though less common for structure
                        # Add SymbolType.VARIABLE if defined, otherwise handle appropriately
                        # For now, we might skip variables unless specifically needed by prompts.
                        self.logger.debug(f"Skipping requested variable symbol: {item.get('name')}")
                        continue # Skip variables for now

                    if symbol_type:
                        required_symbols.append({
                            "name": item["name"],
                            "type": symbol_type, # Store the Enum value
                            "context_path": item["context_path"]
                        })
                    else:
                        self.logger.warning(f"Unknown symbol type '{symbol_type_str}' requested for '{item.get('name')}'")
                else:
                    self.logger.warning(f"Skipping malformed item in missing_symbols list: {item}")

            self.logger.debug(f"Parsed {len(required_symbols)} required symbols from LLM response.")
            return required_symbols

        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to decode JSON from missing symbols response: {e}. Response: {response_content[:500]}...")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error parsing missing symbols response: {e}", exc_info=True)
            return []

    def _fetch_recursive_context(self,
                                symbol_name: str,
                                symbol_type: SymbolType,
                                context_path: str,
                                current_depth: int,
                                max_depth: int,
                                processed_keys: Set[str],
                                accumulator: List[Dict[str, Any]]):
        """
        Recursively fetches context for a symbol and symbols referenced within it,
        replicating the original get_missing_code behavior using pre-analyzed data.

        Args:
            symbol_name: Name of the symbol to fetch (can be qualified or alias).
            symbol_type: Type of the symbol (SymbolType enum).
            context_path: Path where the symbol was referenced (for resolution).
            current_depth: Current recursion depth.
            max_depth: Maximum depth to recurse.
            processed_keys: Set of already processed symbol keys ('path:name:type').
            accumulator: List to append fetched context dictionaries to.
        """
        if current_depth >= max_depth:
            self.logger.debug(f"Max depth ({max_depth}) reached for {symbol_name}, stopping recursion.")
            return

        # --- 1. Resolve Symbol Reference ---
        # Find where the symbol used in 'context_path' is actually defined.
        symbol_ref = self.code_analyzer.get_symbol_reference(symbol_name, context_path, symbol_type)
        if not symbol_ref:
            # Attempt to find external symbols if reference resolution fails locally
            # Note: This assumes get_external_code or similar logic exists and works
            # external_code = self.code_analyzer.get_external_code(symbol_name, context_path)
            # if external_code:
            #     # Handle external code - might need separate logic as path/info differ
            #     self.logger.debug(f"[Depth {current_depth}] Found external code for '{symbol_name}'. (Handling TBD)")
            # else:
            #     self.logger.warning(f"[Depth {current_depth}] Could not resolve reference or find external code for symbol '{symbol_name}' ({symbol_type.name}) from context {context_path}")
            self.logger.warning(f"[Depth {current_depth}] Could not resolve reference for symbol '{symbol_name}' ({symbol_type.name}) from context {context_path}. Skipping.")
            return

        actual_name = symbol_ref.get("name") # The canonical name in its definition file
        actual_path = symbol_ref.get("path") # The file path where it's defined

        if not actual_name or not actual_path:
            self.logger.warning(f"[Depth {current_depth}] Resolved reference for '{symbol_name}' missing name or path: {symbol_ref}")
            return

        # --- 2. Check if Already Processed ---
        # Use the actual definition path and name for the key
        symbol_key = f"{actual_path}:{actual_name}:{symbol_type.name}"
        if symbol_key in processed_keys:
            self.logger.debug(f"[Depth {current_depth}] Skipping already processed symbol: {symbol_key}")
            return

        # --- 3. Get Symbol Info & Code ---
        # Fetch details from the definition file using the actual name
        symbol_info = self.code_analyzer.get_symbol_info(actual_name, actual_path, symbol_type)
        if not symbol_info:
            # Check if the file itself wasn't analyzed (e.g., external dependency without source)
            if actual_path not in self.code_analyzer.result:
                 self.logger.warning(f"[Depth {current_depth}] Symbol '{actual_name}' is in file '{actual_path}' which was not analyzed (likely external). Skipping.")
            else:
                 self.logger.warning(f"[Depth {current_depth}] Could not get symbol info for '{actual_name}' at {actual_path}. Data might be incomplete.")
            # Mark as processed even if info fails to prevent repeated attempts for this key
            processed_keys.add(symbol_key)
            return

        start_line = symbol_info.get("startLine")
        end_line = symbol_info.get("endLine")

        if symbol_type == SymbolType.VARIABLE:
            # Original logic fetched the assignment statement.
            # Replicate this if the CodeAnalyzer stores it, otherwise get snippet.
            # Assuming get_code_snippet works for variables too (gets the assignment line(s))
            if not start_line or not end_line:
                 self.logger.warning(f"[Depth {current_depth}] Missing line numbers for variable '{actual_name}' at {actual_path}")
                 code_snippet = f"# Variable '{actual_name}' definition not found precisely."
            else:
                 code_snippet = self.code_analyzer.get_code_snippet(actual_path, start_line, end_line)

        elif symbol_type in [SymbolType.CLASS, SymbolType.FUNCTION]:
            if not start_line or not end_line:
                self.logger.warning(f"[Depth {current_depth}] Missing line numbers for {symbol_type.name} '{actual_name}' at {actual_path}")
                # Mark processed and return, as we can't get code or recurse
                processed_keys.add(symbol_key)
                return
            code_snippet = self.code_analyzer.get_code_snippet(actual_path, start_line, end_line)
            if not code_snippet:
                self.logger.warning(f"[Depth {current_depth}] Could not retrieve code snippet for {symbol_type.name} '{actual_name}' at {actual_path} ({start_line}-{end_line})")
                # Mark processed and return
                processed_keys.add(symbol_key)
                return
        else:
            self.logger.warning(f"[Depth {current_depth}] Unsupported symbol type {symbol_type} for recursive fetch.")
            processed_keys.add(symbol_key)
            return


        # --- 4. Add to Accumulator and Mark as Processed ---
        self.logger.debug(f"[Depth {current_depth}] Fetched context for symbol: {symbol_key}")
        accumulator.append({
            "name": actual_name,
            "type": symbol_type.name,
            "path": actual_path,
            "start_line": start_line,
            "end_line": end_line,
            "code": code_snippet.strip(), # Add strip() for cleaner output
        })
        processed_keys.add(symbol_key)

        # --- 5. Recurse for Nested Symbols (Only for Functions and Classes) ---
        if symbol_type in [SymbolType.CLASS, SymbolType.FUNCTION] and current_depth + 1 < max_depth:
            # The 'identifiers' key within symbol_info holds the pre-analyzed list
            # of functions, classes, and variables used *within* this symbol's code.
            nested_identifiers = symbol_info.get("identifiers", {})

            # Recurse for nested classes
            nested_classes = nested_identifiers.get("classes", [])
            if nested_classes:
                self.logger.debug(f"[Depth {current_depth}] Found {len(nested_classes)} nested classes in '{actual_name}': {nested_classes}")
                for nested_name in nested_classes:
                    # The context for resolving these nested names is the current symbol's definition file (actual_path)
                    self._fetch_recursive_context(
                        symbol_name=nested_name, # Use the name as found in the identifiers list
                        symbol_type=SymbolType.CLASS,
                        context_path=actual_path,
                        current_depth=current_depth + 1,
                        max_depth=max_depth,
                        processed_keys=processed_keys,
                        accumulator=accumulator
                    )

            # Recurse for nested functions
            nested_functions = nested_identifiers.get("functions", [])
            if nested_functions:
                self.logger.debug(f"[Depth {current_depth}] Found {len(nested_functions)} nested functions in '{actual_name}': {nested_functions}")
                for nested_name in nested_functions:
                    self._fetch_recursive_context(
                        symbol_name=nested_name,
                        symbol_type=SymbolType.FUNCTION,
                        context_path=actual_path,
                        current_depth=current_depth + 1,
                        max_depth=max_depth,
                        processed_keys=processed_keys,
                        accumulator=accumulator
                    )

            # Recurse for nested variables (if needed - replicating original)
            # Original seemed to fetch variable definitions recursively too.
            nested_variables = nested_identifiers.get("variables", [])
            if nested_variables:
                 self.logger.debug(f"[Depth {current_depth}] Found {len(nested_variables)} nested variables in '{actual_name}': {nested_variables}")
                 for nested_name in nested_variables:
                     # Check if it's a simple variable or potentially an object instantiation needing class recursion
                     # This requires more advanced analysis - for now, fetch as variable
                     self._fetch_recursive_context(
                        symbol_name=nested_name,
                        symbol_type=SymbolType.VARIABLE, # Fetch the assignment statement
                        context_path=actual_path,
                        current_depth=current_depth + 1,
                        max_depth=max_depth, # Variables usually don't need deep recursion, maybe adjust depth?
                        processed_keys=processed_keys,
                        accumulator=accumulator
                     )
    
    def get_missing_context(self, initial_context: Dict[str, Any], required_symbols: List[Dict[str, Any]], max_depth: int = 2) -> Dict[str, Any]:
        """
        Retrieves code and information for the required symbols and symbols
        referenced within them recursively up to max_depth. Adds results
        to the initial context dictionary. Replicates original recursive behavior.

        Args:
            initial_context: The context dictionary returned by get_endpoint_context.
            required_symbols: A list of dicts from parse_missing_symbols_response.
                              Each dict MUST contain 'name', 'type' (SymbolType), 'context_path'.
            max_depth: How many levels deep to fetch referenced code (default: 2).

        Returns:
            The augmented context dictionary with an 'extra_context' key containing
            the details of all fetched symbols (initial + recursive).
        """
        if not required_symbols:
            self.logger.debug("No required symbols provided, returning initial context.")
            return initial_context

        augmented_context = copy.deepcopy(initial_context)
        extra_context_list = [] # Populated by the recursive helper
        processed_keys = set()    # Shared tracking across recursive calls

        self.logger.info(f"Fetching extra context recursively (max_depth={max_depth}) for {len(required_symbols)} initial symbols.")

        # --- Initiate Recursion for Each Initially Required Symbol ---
        for symbol_request in required_symbols:
            symbol_name = symbol_request.get("name")
            symbol_type = symbol_request.get("type") # Expecting SymbolType Enum
            context_path = symbol_request.get("context_path")

            if not all([symbol_name, isinstance(symbol_type, SymbolType), context_path]):
                 self.logger.error(f"Invalid symbol request format: {symbol_request}. Skipping.")
                 continue

            self.logger.debug(f"Initiating recursive fetch for: {symbol_name} ({symbol_type.name}) from {context_path}")
            self._fetch_recursive_context(
                symbol_name=symbol_name,
                symbol_type=symbol_type,
                context_path=context_path,
                current_depth=0, # Start at depth 0
                max_depth=max_depth,
                processed_keys=processed_keys, # Pass the shared set
                accumulator=extra_context_list # Pass the shared list
            )

        # --- Finalize and Add to Context ---
        if extra_context_list:
            # Deduplication should be handled by processed_keys, but check just in case
            unique_extra_context = []
            seen_keys_final = set()
            for item in extra_context_list:
                key = f"{item['path']}:{item['name']}:{item['type']}"
                if key not in seen_keys_final:
                    unique_extra_context.append(item)
                    seen_keys_final.add(key)
                else:
                     self.logger.debug(f"Duplicate symbol '{key}' removed during final check.")


            # Sort for consistent output (optional, but helpful for debugging)
            unique_extra_context.sort(key=lambda x: (x['path'], x.get('start_line', 0)))

            augmented_context["extra_context"] = unique_extra_context
            self.logger.info(f"Added total {len(unique_extra_context)} unique symbols to extra context after recursion.")
            # For debugging, log the names added:
            # self.logger.debug(f"Extra context symbols added: {[item['name'] for item in unique_extra_context]}")
        else:
            self.logger.info("No extra context symbols were ultimately fetched or added.")


        return augmented_context
    
    def _get_symbol_key(self, symbol_data: Dict[str, Any]) -> Optional[str]:
        """
        Creates a robust and unique key for a symbol dictionary by normalizing
        its path and standardizing its type. This is crucial for de-duplication.

        Args:
            symbol_data: A dictionary representing a symbol, must contain
                         'path', 'name', and 'type' keys.

        Returns:
            A normalized string key (e.g., "/abs/path/to/file.py:MyClass:CLASS")
            or None if essential information is missing.
        """
        path = symbol_data.get('path')
        name = symbol_data.get('name')
        # The 'type' can be an Enum, or a string like 'serializer', 'filter', 'CLASS'
        type_info = symbol_data.get('type')

        if not all([path, name, type_info]):
            self.logger.warning(f"Could not generate key for symbol data due to missing info: {symbol_data.get('name', 'N/A')}")
            return None


        try:
            # Using abspath is generally safer if the path might be relative
            normalized_path = os.path.normpath(os.path.abspath(path))
        except Exception:
            # Fallback for paths that might not exist on the filesystem (e.g., during tests)
            normalized_path = os.path.normpath(path)

        type_mapping = {
            # These are all fundamentally classes
            'serializer': SymbolType.CLASS,
            'model_group': SymbolType.CLASS,
            'model': SymbolType.CLASS,
            'pagination': SymbolType.CLASS,
            'authentication': SymbolType.CLASS,
            'filter': SymbolType.CLASS,
            'django.viewset': SymbolType.CLASS,
            'django.api_view': SymbolType.CLASS,
            'class': SymbolType.CLASS,
            'CLASS': SymbolType.CLASS,
            # Functions
            'function': SymbolType.FUNCTION,
            'FUNCTION': SymbolType.FUNCTION,
            # Variables
            'variable': SymbolType.VARIABLE,
            'VARIABLE': SymbolType.VARIABLE,
        }

        canonical_type = None
        if isinstance(type_info, SymbolType):
            canonical_type = type_info
        elif isinstance(type_info, str):
            canonical_type = type_mapping.get(type_info.lower())

        if not canonical_type:
            self.logger.warning(f"Unrecognized symbol type '{type_info}' for '{name}'. Cannot generate key.")
            return None

        # Return the fully normalized key
        return f"{normalized_path}:{name}:{canonical_type.name}"
        
    def optimize_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Removes items from 'extra_context' if they represent symbols already
        present in the primary context sections (handler, serializers, models, features).
        Operates on a deep copy to avoid modifying the original input dictionary.

        Args:
            context: The potentially verbose endpoint context dictionary.

        Returns:
            An optimized context dictionary with 'extra_context' potentially trimmed.
        """
        optimized_ctx = copy.deepcopy(context)
        extra_context_to_process = optimized_ctx.get("extra_context")

        if not extra_context_to_process:
            self.logger.debug("optimize_context: No 'extra_context' to process.")
            return optimized_ctx

        self.logger.info(f"optimize_context: Starting de-duplication of {len(extra_context_to_process)} extra context items...")
        primary_context_keys = set()

        # --- Gather keys from primary context sections ---
        # Handler
        if "handler" in optimized_ctx and optimized_ctx["handler"]:
            key = self._get_symbol_key(optimized_ctx["handler"])
            if key:
                primary_context_keys.add(key)
                self.logger.debug(f"optimize_context: Added primary key for handler: {key}")

        # Serializers and their Data Classes (Models)
        for serializer in optimized_ctx.get("serializers", []):
            ser_key = self._get_symbol_key(serializer)
            if ser_key:
                primary_context_keys.add(ser_key)
                self.logger.debug(f"optimize_context: Added primary key for serializer/model_group: {ser_key}")
            for model in serializer.get("data_classes", []):
                model_key = self._get_symbol_key({"path": model.get('path'), "name": model.get('name'), "type": "CLASS"})
                if model_key:
                    primary_context_keys.add(model_key)
                    self.logger.debug(f"optimize_context: Added primary key for nested data_class: {model_key}")

        # Features
        for feature in optimized_ctx.get("features", []):
            key = self._get_symbol_key(feature)
            if key:
                primary_context_keys.add(key)
                self.logger.debug(f"optimize_context: Added primary key for feature: {key}")
        
        # --- Filter extra_context ---
        original_extra_count = len(extra_context_to_process)
        deduplicated_extra_context = []
        for item in extra_context_to_process:
            item_key = self._get_symbol_key(item)
            if not item_key:
                self.logger.warning(f"optimize_context: Skipping extra context item without valid key: {item.get('name')}")
                continue
            
            if item_key not in primary_context_keys:
                deduplicated_extra_context.append(item)
            else:
                self.logger.debug(f"optimize_context: Removing redundant extra_context item '{item_key}'")

        removed_count = original_extra_count - len(deduplicated_extra_context)
        if removed_count > 0:
            self.logger.info(f"optimize_context: Removed {removed_count} redundant symbols from 'extra_context'.")
        
        optimized_ctx["extra_context"] = deduplicated_extra_context
        return optimized_ctx
    
    @property
    def framework_name(self) -> str:
        return "Django"

    @property
    def language_name(self) -> str:
        return "python"

    def get_schema_component_terminology(self) -> str:
        return "serializer"

    def get_component_system_message(self) -> str:
        # This should be the original system message part from your Django component prompt
        return """You are an expert in python Django Rest Framework(DRF) and openAPI specifications 3.0.
You have extensive knowledge about the codebase of well-known python packages.
You must leverage all your knowledge about all aspects of python DRF. Utilize your understanding of popular Python packages' code.
You should use your entire knowledge about openAPI specifications 3.0 combined with your best analytical ability."""

    def get_component_field_instructions(self, component_name: str, component_info: Dict[str, Any]) -> str:
        # This method now provides BOTH the field analysis rules AND the schema naming/referencing rules for Django.
        # Ensure 'component_name' here is the base name (e.g., "ReviewSerializer")
        base_component_name = component_info.get('name', component_name) # Use the simple name from component_info

        django_field_analysis_instructions = f"""
0. Code for some parent classes will not be provided because they are part of famous python packages, append their code from your knowledge repository to the provided code and take decisions on this entire code.
Perform these steps to create Component section of Open API specs for the serializer: {base_component_name} only. Remember that you need to create two schemas, one for request and one for response. Create two 'set' of fields, one for request schema and another for response schema.
1. Find the 'set' of fields(and their properties readOnly, writeOnly, type and being a "required" field) of the serializer class: {base_component_name} by using your expertise in python DRF, your understanding of the code and by using the following rules:
    1.1 If the fields property in meta class contains some fields then add them to a 'set' containing the fields. IGNORE ALL OTHER FIELDS including the fields of model or any of it's parent classes. Also IGNORE the fields defined outside meta class in the serializer or in the parent classes of the serializer which are NOT present in the fields property. Also follow the following rules:
        - For the properties readOnly, writeOnly, type, required=True, Try to find the properties for each field in the serializer code itself, for the fields whose properties you couldn't find in the serializer refer to the associated model to find the properties.
        - For foreign key references, relatedfields the type should be integer.
        - If the field definition does not have read_only=True, then assume it is false. In same way, if the field definition does not have write_only=True, assume it is false.
        - For request schema a field needs to be present in the required section until and unless: explicitly set as "required=False" OR it has a default value such as default=<value_or_function> in the model or the serializer OR it is marked "null=True or blank=True" in the model or serializer. Make a 'list' of all such fields.
    1.2 Else if the fields property in meta class is absent or is set to "__all__" then add the fields mentioned in the model and also the parent classes of the model to the 'set' of fields. Also add the fields present outside the meta class in the serializer and in the parent classes of the serializer to the 'set' of fields. Code for some model parent classes would not be there because they are part of famous python packages. Also follow the following rules:
        - In case of a name conflict for a field or conflict among the properties of a field. First preference will be given to serializer, then it's parent clasess, then the model and then the models parent classes.
        - For foreign key references, relatedfields the type should be integer.
        - For the properties readOnly, writeOnly, type, required=True, Try to find the properties for each field in the serializer code itself, for the fields whose properties you couldn't find in the serializer refer to the parent serializers and then the associated model and it's parent classes to find the properties.
        - If the field definition does not have read_only=True, then assume it is false. In same way, if the field definition does not have write_only=True, assume it is false.
        - For request schema a field needs to be present in the required section until and unless:  explicitly set as "required=False" OR it has a default value such as default=<value_or_function> in the model OR the serializer or it is marked "null=True or blank=True" in the model or serializer. Make a 'list' of all such fields.
    1.3 Appropriately edit the fields of request and response schema by looking at the code overall and also relevant properties such as exclude in the meta class.
2. In deciding the type of each field appropriately take care of each RelatedField and it's effects on the type of each field. While deciding the type of each field make sure you adhere to the standard primitive types of openAPI. Remember that "null" is not a primitive type.
3. From the 'set' of fields, if a field has a set of properties to be defined and if you feel you do not have the complete information about the properties then leave a curly braces placeholder for properties for that field.
4. Use the Field information gathered until now and the code given above to create component section of Open API specs.
5. As mentioned before you need to create two schemas. One for request and one for response.
"""
        # These are the Django-specific naming and schema structure rules (points 6-16 from original component prompt)
        django_naming_and_structure_instructions = f"""
6. Use the name of serializer: {base_component_name} and append the string "Request" to it for the request schema. Request schema serializer's name: {base_component_name}Request.
7. Use the name of serializer: {base_component_name} and append the string "Response" to it for the response schema. Response schema serializer's name: {base_component_name}Response.
8. Response schema should have exactly 3 mandatory sections: properties, type and required. properties section should contain the 'set' of fields for Response schema.
9. Request schema should have two mandatory sections: properties and type. properties section should contain the 'set' of fields for Request schema. A 3rd section required should only be present if 'list' is non-empty. The required section should contain all the fields in 'list'.
10. If you $ref another serializer for any field then accordingly append the string "Request" or "Response" to the name of the serializer being $ref'd.
11. The schema syntax for each schema should be such that there is the name of the schema and then the aforementioned sections.
12. Every field in the property section of the schema should have exactly three mandatory sections: type, readOnly and writeOnly.
13. For every property in schema, add readOnly and writeOnly to it. readOnly, writeOnly are properties that should be used within the definition of individual properties, not at the schema object level.
14. Use all your knowledge about the rules of openAPI specifications 3.0, python DRF and your best analytical ability and quantitative aptitude.
15. Both the schemas should be nested inside ONLY one "components" section. Start with 'components:' at the root level. Have a 'schemas:' key directly under components. Place all schema definitions under the schemas key.
16. Clearly state ALL the properties of both the request and response schema even if they have the same properties.
"""
        return django_field_analysis_instructions + django_naming_and_structure_instructions
    
    def get_endpoint_request_system_message(self) -> str:
        return "You are an expert in python Django Rest Framework(DRF) and openAPI specifications 3.0." # Or more specific

    def _get_django_formatted_feature_prompt(self, endpoint_context: Dict[str, Any]) -> str:
        """Helper to generate the Django feature prompt string."""
        settings = endpoint_context.get("framework_settings", {}).get("settings", {})
        feature_lines = []
        auth_classes = settings.get('authentication_classes')
        if auth_classes:
            feature_lines.append(f"Default Authentication Classes: {', '.join(auth_classes)}")
        else:
            feature_lines.append("Default Authentication Classes: Not Set (Assume Session/Basic)")
        
        pag_class = settings.get('pagination_class')
        pag_size = settings.get('page_size')
        if pag_class:
            pag_line = f"Default Pagination Class: {pag_class}"
            if pag_size: pag_line += f", Default Page Size: {pag_size}"
            feature_lines.append(pag_line)
        else:
            feature_lines.append("Default Pagination: Not Set")
            
        filter_backends = settings.get('filter_backends')
        if filter_backends:
            feature_lines.append(f"Default Filter Backends: {', '.join(filter_backends)}")
        else:
            feature_lines.append("Default Filter Backends: Not Set (Assume None)")
        return "\n".join(feature_lines)
    
    def get_endpoint_request_instructions(self, endpoint: Dict[str, Any], endpoint_context: Dict[str, Any], skip_components: bool = False) -> str:
        url = endpoint.get("url", {}).get("url", "N/A")
        parameters = endpoint.get("url", {}).get("parameter", []) # List of path param dicts
        method_lower = endpoint.get("method", "N/A").lower()
        
        if endpoint.get("is_viewset"):
            fn_display_name = endpoint.get("function") # e.g., "list", "retrieve", "custom_action"
            if not fn_display_name and method_lower == "get" and "{" not in url: # Heuristic for list views
                fn_display_name = "list"
            elif not fn_display_name and method_lower == "get" and "{" in url: # Heuristic for retrieve
                 fn_display_name = "retrieve" # Or parse from URL if specific pk name is known
            elif not fn_display_name: # Fallback
                fn_display_name = endpoint_context.get("handler", {}).get("name", "N/A") # Viewset name
        else:
            fn_display_name = endpoint_context.get("handler", {}).get("name", "N/A") # APIView function name

        viewset_code = endpoint_context.get("handler", {}).get("code", "")
        # Check for the presence of specific attribute assignments in the ViewSet's code
        local_pagination_class_defined = 'pagination_class' in viewset_code
        local_filter_defined = 'filter_backends' in viewset_code or 'filterset_class' in viewset_code or 'filterset_fields' in viewset_code

        # --- Step 2: Get GLOBAL default settings from the existing logic ---
        global_settings = endpoint_context.get("framework_settings", {}).get("settings", {})
        global_pagination_class = global_settings.get('pagination_class')
        global_filters = global_settings.get('filter_backends')

        if local_pagination_class_defined:
            pagination_instructions = """
        - **Pagination:** This viewset EXPLICITLY defines its own `pagination_class`. You MUST analyze this class (its code is provided in the context) and generate the specific query parameters it uses (e.g., 'page', 'page_size', 'limit', 'offset'). IGNORE any project-level default pagination.
        """
        elif global_pagination_class:
            pagination_instructions = f"""
        - **Pagination:** This viewset does not define a local `pagination_class`, but the project has a DEFAULT pagination class set to `{global_pagination_class}`. You MUST generate the standard query parameters for this default class.
        """
        else: # This is the key case for the bug fix
            pagination_instructions = """
        - **Pagination:** This viewset DOES NOT define a `pagination_class`, and there is NO project-level default set. Therefore, this endpoint might NOT paginated. You must analyse the code carefully and you MUST NOT generate any pagination-related query parameters like 'page', 'page_size', 'limit', or 'offset' if it does not support pagination.
        """

        # 3.B: Filter Instructions
        if local_filter_defined:
            filter_instructions = """
        - **Filtering:** This viewset EXPLICITLY defines its own filtering attributes (`filter_backends`, `filterset_class`, etc.). You MUST analyze these custom filters (their code is provided in the context) and generate a query parameter for each defined filter field. IGNORE any project-level default filters.
        """
        elif global_filters:
            filter_instructions = f"""
        - **Filtering:** This viewset does not define local filtering attributes, but the project has DEFAULT filter backends: `{', '.join(global_filters)}`. You MUST analyze these default backends and generate the appropriate query parameters if applicable for a GET request.
        """
        else: # This is the key case for the bug fix
            filter_instructions = """
        - **Filtering:** This viewset DOES NOT define any filtering attributes, and there are NO project-level default filters set. Therefore, analyse this endpoint if it has imperative filtering otherwose it does NOT support filtering. You MUST NOT generate any query parameters for filtering if it does not support filtering.
        """

        # Construct parameter_section for Django
        parameter_section_str = ""
        if parameters: # Path parameters
            path_params_details_list = []
            for p_param in parameters:
                detail = f"parameter_name={p_param['name']}"
                path_params_details_list.append(detail)
            
            parameter_section_str = (
                "For PATH PARAMETERS: Look at the following path parameters : "
                f"{', '.join(path_params_details_list)}. These appear as a path parameter in url. "
                "Create a parameter section and add all of these to it with fields name, in, required and schema. "
                "If these path parameters have regex, add a pattern section and add it regex to it."
            )
        else:
            parameter_section_str = "No PATH PARAMETERS identified in the URL." # Or empty if preferred

        # Get the Django-specific framework settings string
        feature_prompt_str = self._get_django_formatted_feature_prompt(endpoint_context)
        pagination_instructions = """
        3.3.4 To gather PAGINATION PARAMETERS:
            a. Examine the viewset code for a `pagination_class` attribute.
            b. If `pagination_class` is defined, find the source code for that class in the provided "Custom code" or "Extra Classes" context.
            c. Analyze the pagination class code:
                - If it inherits from `PageNumberPagination`, look for `page_query_param` (default: 'page') and `page_size_query_param` (default: 'page_size'). Add these as query parameters.
                - If it inherits from `LimitOffsetPagination`, look for `limit_query_param` (default: 'limit') and `offset_query_param` (default: 'offset'). Add these as query parameters.
                - If it inherits from `CursorPagination`, look for `cursor_query_param` (default: 'cursor'). Add this as a query parameter.
            d. If `pagination_class` is not set on the viewset, check the project-level settings provided. If a default pagination class is set there, apply the same logic. If no pagination is defined anywhere, do not add any pagination parameters.
        """

        if skip_components:
            # NEW: Instructions for when components are skipped
            request_body_schema_instructions = """
        b. Since component generation is skipped, you MUST define the schema for the request body INLINE. DO NOT use a `$ref` to `#/components/schemas/`.
        c. Clearly state all the fields from the 'set' of request fields directly under the `schema` key. If 'list' (the list of required fields) is non-empty, you MUST include the `required` section within this inline schema, containing all the properties in 'list'. While stating the properties, make sure you are strictly adhering to OpenAPI specifications 3.0.
"""
        else:
            request_body_schema_instructions = """
    b. If a ``serializer`` present in the code exactly matches the 'request body schema', populate schema section for request with ref '#/components/schemas/{{serializer_name}}' where you will replace {{serializer_name}} with the full name of the ``serializer`` present in code appended with the string "Request". For example: $ref: '#/components/schemas/LambdaSerializerRequest'. Here the ``serializer`` name in the code was "LambdaSerializer" and we appended the word "Request" it. Remember to use the full name of the ``serializer``.
    c. If no serializer present in the code exactly matches the 'request body schema', do not use ref and clearly state all the fields from the 'set' of request fields. If 'list' is non-empty then include the required section in the requestBody subsection containing all the properties in 'list'. While stating the properties make sure you are strictly adhering to openAPI specifications 3.0.
"""
        django_steps = f"""
0. If the code explicitly raises an exception specifically for the {fn_display_name} endpoint(NOTE: The presence of exception for other endpoints should not be interpreted as implying the same for {fn_display_name}) or if the {method_lower} method is not mentioned in the list of "allowed_methods" in the viewset, then the endpoint/method combination {fn_display_name}/{method_lower} is not allowed and you don't need to create path section for this endpoint and method. ONLY and ONLY give "```<-|NOT_REQUIRED|->```" as the output(under the triple backticks and without even a single extra character) and ignore all the subsequent information.
1. If the method is not explicitly specified then you need to figure out the method(s) to be used for this endpoint from your expertise in python DRF, your knowledge of well-known python packages and the code provided to you.
2. If there is NO viewset code available and just a famous python package name is mentioned instead, then use use your expertise in python DRF and knowledge of famous python packages to generate all the information. In this case don't reference a serializer, instead state all it's properties in the path section itself.
2.5 Code for some parent classes will not be provided because they are part of famous python packages, append their code from your knowledge repository to the provided code and take decisions on this entire code.
3. Now you need to create the requestBody subsection. Focus on finding the fields which can be in the request from an external user of this endpoint, focus on determining the fields which are mandatory and will require a place in the required section of the requestBody schema and lastly focus on determining the properties of each field. To create the requestBody subsection follow these steps:
        a Along with your knowledge of DRF, your overall understanding of the code, use the following rules to finalise the 'request body schema':
            a1. If a serializer is being used for this method then use the following rules to gather the 'set' of request fields:
                - If: the corresponding serializer's meta class has at least one field explicitly defined in it's fields property then `consider` ONLY and ONLY the field(s) present in the meta class for adding to the 'set' of request fields. IGNORE ALL other fields defined anywhere else in the code.
                - Else If: the serializer's meta class doesn't have fields property OR the fields property is set to "_all_" then `consider` all the fields of the model and it's parent classes and serializer and it's parent classes for adding to the 'set' of request fields.
                - Have concrete reasoning for inclusion/exclusion of each possible field and have concrete reasoning behind deciding each property of each field.
                - Line-by-Line deftly scan the associated code for each field being `considered` and then if it is deemed fit to be in the request then add it to the 'set' of request fields.
                - While deciding the properties(type, name etc.) for each field give first preference to properties defined in the serializer or it's parent classes and then the model and it's parent classes.
            a2. Line-by-Line deftly scan the viewset code for any possible request field apart from the ones in serializer and add each such request field to the 'set' of request fields.
            a3. A field needs to be present in the required section of the 'request body schema' until and unless it satisfies at least one of the following conditions:
                    - Explicitly set as "required=False"
                    - It is marked default=True or has a default value, such as default=<value_or_function> wherever it is defined.
                    - It is marked "null=True or blank=True" in the model or the serializer.
                a3.1 Make a 'list' of all the fields which need to be in the required section of the 'request body schema'.
            a4. Use the 'set' of request fields to finalise the 'request body schema'.
        {request_body_schema_instructions} 
    3.1 If this method does not require payload then omit the requestBody subsection.

    3.2 Use the following steps to create the parameter subsection:
        - {parameter_section_str}
        - To gather the QUERY PARAMETERS: Carefully analyse the viewset code, serializer code, any other corresponding code to gather all the query parameters that need to be sent as part of the request ONLY for the endpoint {fn_display_name} with http method {method_lower} and url {url} . If there are query parameters then add those query parameters to the parameter section. For each query parameter please be rigorous in deciding if a query parameter is mandatory(meaning required:True in openAPI). Take help from corresponding validate functions inside the serializer. Analyse all the code associated with query parameters and If query params are conditionally mandatory then clearly and elaborately specify the same in the description.
        - To gather the QUERY PARAMETERS: Remember that the filters inside the filterset_class are only applicable to actions which involve the filter_queryset function, in default DRF functionality only list action with the method GET involves the filter_queryset function. Add the filters in the filterset_class as the query parameters if this is a list action(and GET method) or there is explicit use of filter_queryset function in the corresponding code.
        - {pagination_instructions}
        - {filter_instructions}
        - - **Conclusion:** Your final `parameters` list MUST ONLY contain parameters derived from the rules above. If no parameters are identified, provide an empty list `parameters: []`.
"""
        return django_steps.strip()
    
    def get_endpoint_request_framework_specific_notes(self) -> str:
        return "NOTE: Do not include fields from model if serializer's meta class's fields property has explicitly defined even one field." 
    
    def get_endpoint_response_system_message(self) -> str:
        return "You are an expert in python Django Rest Framework(DRF) and openAPI specifications 3.0." # Or more specific

    def get_endpoint_common_instructions(self,  skip_components: bool = False) -> str:
        # This is the content of the original path_section_common_prompt
        if skip_components:
            # NEW: Instruction when skipping components
            ref_instruction = "8. DO NOT use a `$ref` to `#/components/schemas/` for any schema definition. All schemas must be defined inline."
        else:
            # ORIGINAL: Instruction when using components
            ref_instruction = "8. DO NOT reference($ref) a serializer which isn't mentioned in the code."
        return f"""
4. While deciding the types of each field make sure you adhere to the standard primitive types of openAPI.
5. DO NOT add the x-codeSamples section to the openAPI definition.
6. DO NOT create the component section of openAPI definition. 
7. In the end return ONLY the openAPI definition.
{ref_instruction}
9. Use all your knowledge about the rules of openAPI specifications 3.0, python DRF and your best analytical ability and quantitative aptitude.
10. Make sure your output STRICTLY conforms to openAPI specifications 3.0 and is a 100 percent syntactically correct YAML.

NOTE: Analyse the code carefully. The way that the code is written could vary significantly from standard ways of writing APIs in DRF. Hence, rigorously analyse the code.
"""

    def _get_django_formatted_feature_prompt_for_response(self, endpoint_context: Dict[str, Any]) -> str:
            """Helper to generate the Django feature prompt string specifically for responses (focus on pagination)."""
            settings = endpoint_context.get("framework_settings", {}).get("settings", {})
            feature_lines = []
            
            pag_class = settings.get('pagination_class')
            pag_size = settings.get('page_size')
            if pag_class:
                pag_line = f"Default Pagination Class: {pag_class}"
                if pag_size: pag_line += f", Default Page Size: {pag_size}"
                feature_lines.append(pag_line)
            else:
                feature_lines.append("Default Pagination: Not Set")

            # Authentication might be relevant for 401/403 responses
            auth_classes = settings.get('authentication_classes')
            if auth_classes:
                feature_lines.append(f"Default Authentication Classes: {', '.join(auth_classes)}")
            else:
                feature_lines.append("Default Authentication Classes: Not Set (Assume Session/Basic)")
            return "\n".join(feature_lines)

    def get_endpoint_response_instructions(self, endpoint: Dict[str, Any], endpoint_context: Dict[str, Any], skip_components: bool = False) -> str:
        # From original Django response prompt
        url = endpoint.get("url", {}).get("url", "N/A") # Not directly used in instructions but good for context
        method_upper = endpoint.get("method", "N/A").upper()
        
        # Determine 'fn_display_name' (target function/method name for prompt display)
        if endpoint.get("is_viewset"):
            fn_display_name = endpoint.get("function")
            if not fn_display_name and method_upper == "GET" and "{" not in url: fn_display_name = "list"
            elif not fn_display_name and method_upper == "GET" and "{" in url: fn_display_name = "retrieve"
            elif not fn_display_name: fn_display_name = endpoint_context.get("handler", {}).get("name", "N/A")
        else:
            fn_display_name = endpoint_context.get("handler", {}).get("name", "N/A")
        
        feature_prompt_for_response_str = self._get_django_formatted_feature_prompt_for_response(endpoint_context)

        # The DRF_default_response_codes is a large dict, so stringifying it directly.
        pagination_response_instructions = """
                b.3 While deciding the output schema, determine if the response is paginated. Pagination is typically applied only to `list` actions.
                    - Check if the viewset has a `pagination_class` defined.
                    - If it does, the success response (e.g., '200') schema MUST be an object with the following properties:
                        - `count`: An `integer` representing the total number of items.
                        - `next`: A `string` (format: uri, nullable: true) for the URL of the next page.
                        - `previous`: A `string` (format: uri, nullable: true) for the URL of the previous page.
                        - `results`: An `array` of objects. The `items` of this array should be a `$ref` to the appropriate response serializer (e.g., '#/components/schemas/ProductSerializerResponse').
                    - If no `pagination_class` is set on the view or in project defaults, the success response is typically just a direct array of objects.
        """

        if skip_components:
            # NEW: Instructions for when components are skipped
            schema_instructions = """
            e. Since component generation is skipped, you MUST define all response schemas INLINE. Do not use `$ref` to `#/components/schemas/`.
            f. For scenarios where a schema is required, clearly state all the properties directly. If there are no properties to define, you can simply omit the properties field but DO NOT set properties to null. For empty responses (like 204 No Content), omit the `content` section entirely for that status code.
            """
        else:
            # ORIGINAL: Instructions for when components are present
            schema_instructions = """
            e. The scenarios for which a ``serializer``(NOT the model) mentioned in the code exactly matches the output schema, populate schema section for those status codes with ref '#/components/schemas/{{serializer_name}}' where you will replace {{serializer_name}} with the full name of the ``serializer`` present in code appended with the string "Response" .For example: $ref: '#/components/schemas/NablaSerializerResponse'. Here the name of the ``serializer`` in the code was "NablaSerializer" and we appended the word "Response" to it. Remember to use the full name of the ``serializer``. For paginated list responses, the $ref should be nested under `properties.results.items`.
            f. The scenarios for which there is no serializer mentioned in the code which exactly matches the output schema, do not use ref and clearly state all the properties. While stating the properties make sure you are strictly adhering to openAPI specifications 3.0. If there are no properties to define, you can simply omit the properties field but DO NOT set properties to null. For empty responses (like 204 No Content), omit the `content` section entirely for that status code.
            """

        django_response_steps = f"""
2. Code for some parent classes will not be provided because they are part of famous python packages, append their code from your knowledge repository to the provided code and take decisions on this entire code.
3. If viewset code is available then follow these steps:
    3.1 To provide correct response information follow these steps:
            a. Analyse the viewset code and try to decipher the possible success and failure scenarios.
            b. Then try to decipher the exact output schema for each of those scenarios.
                b.1 If the {fn_display_name} function is overridden in the viewset code then start your output schema deciphering process from the line in {fn_display_name} where the response is being returned and then move to previous lines.
                b.2 While deciding the output schema take into account DRF pagination rules as well. Remember that pagination is typically ONLY applied to list action outputs in DRF until response is explicitly paginated for a particular endpoint. Here are the relevant default project level settings:
{feature_prompt_for_response_str}
                {textwrap.dedent(pagination_response_instructions)}
            c. For each scenario try to find as many status codes inside the code itself as possible.
            d. For the scenarios whose status codes you couldn't find in the code use the following default status code and scenario mapping for python DRF: {json.dumps(DRF_default_response_codes)}.
            {schema_instructions}
4. Provide a concise, accurate `summary` for the endpoint operation based on its purpose (e.g., "Retrieve a specific category", "List all products", "Create a review").
5. Consider `NOT_REQUIRED`: If the analysis reveals this specific `{method_upper}` method is explicitly disallowed for this endpoint (e.g., not in `allowed_methods`, raises `MethodNotAllowed`), output ONLY ```<-|NOT_REQUIRED|->```."""
        return django_response_steps.strip()
    
    def get_endpoint_response_framework_specific_notes(self) -> str:
        # Django response prompt example didn't have a trailing "NOTE:" like the request one.
        # It was part of the common instructions, which is now handled by get_endpoint_common_instructions().
        return "" # No specific trailing notes for Django response beyond common ones.
    
    def _resolve_url_conf_to_file_path(self, url_module_name: str, base_search_path: str) -> Optional[str]:
        """
        Resolves a ROOT_URLCONF module string (e.g., 'myapp.urls') to an absolute file path.
        Searches relative to base_search_path.

        Args:
            url_module_name: The module string like 'myapp.urls' or 'project.urls'.
            base_search_path: The directory to start searching from (e.g., self.project_path or dirname(settings_file)).

        Returns:
            Absolute path to the urls.py file or None.
        """
        if self.debug_mode:
            print(f"DEBUG: _resolve_url_conf_to_file_path: Resolving '{url_module_name}' relative to '{base_search_path}'")

        path_components = url_module_name.split('.')
        if not path_components:
            if self.debug_mode: print(f"DEBUG: _resolve_url_conf_to_file_path: Empty url_module_name provided.")
            return None

        # Attempt 1: Resolve as a .py file (e.g., base_search_path/component1/component2.py)
        # e.g., for 'myproject.urls', components are ['myproject', 'urls'] -> base/myproject/urls.py
        # e.g., for 'urls', components are ['urls'] -> base/urls.py
        module_file_name = path_components[-1] + ".py"
        dir_components = path_components[:-1] # This will be empty if only one component
        
        potential_file_path = os.path.join(base_search_path, *dir_components, module_file_name)
        if os.path.exists(potential_file_path):
            resolved_path = os.path.abspath(potential_file_path)
            if self.debug_mode: print(f"DEBUG: _resolve_url_conf_to_file_path: Resolved (file) to: {resolved_path}")
            return resolved_path

        # Attempt 2: Resolve as a package (e.g., base_search_path/component1/component2/__init__.py)
        # e.g., for 'myproject.urls_package', components are ['myproject', 'urls_package'] -> base/myproject/urls_package/__init__.py
        potential_package_init_path = os.path.join(base_search_path, *path_components, "__init__.py")
        if os.path.exists(potential_package_init_path):
            resolved_path = os.path.abspath(potential_package_init_path)
            if self.debug_mode: print(f"DEBUG: _resolve_url_conf_to_file_path: Resolved (package __init__.py) to: {resolved_path}")
            return resolved_path

        if self.debug_mode:
            print(f"DEBUG: _resolve_url_conf_to_file_path: Could not resolve '{url_module_name}' under '{base_search_path}'.")
            print(f"DEBUG: Checked (file): {potential_file_path}")
            print(f"DEBUG: Checked (package): {potential_package_init_path}")
        return None

    def get_initial_context_presentation_for_missing_symbols(self, endpoint: Dict[str, Any], endpoint_context: Dict[str, Any]) -> str:
        """
        Formats the Django-specific initial endpoint context for the missing symbols prompt.
        This mirrors the preamble and context building part of the original Django prompt.
        """
        url = endpoint.get("url", {}).get("url", "N/A")
        method = endpoint.get("method", "N/A").upper()
        
        handler_details = endpoint_context.get("handler", {})
        view_name = handler_details.get("name", "N/A")
        handler_code = handler_details.get("code", "# Handler code not available")
        handler_path = handler_details.get("path", "N/A")

        # Preamble from the original Django prompt
        prompt_str = f"""You are analyzing the API endpoint '{method} {url}' handled by the view/viewset '{view_name}' defined in '{handler_path}'.
The goal is to generate a complete OpenAPI specification path item for this endpoint, including parameters, request body, responses, and summary.

Here is the initial code context retrieved for this endpoint:

"""
        # Code context blocks (same as original prompt)
        prompt_str += f"=== Handler Code ({view_name}) ===\n"
        prompt_str += f"Path: {handler_path}\n"
        prompt_str += f"```python\n{handler_code}\n```\n"
        prompt_str += "=== End Handler Code ===\n"

        serializers = endpoint_context.get("serializers", [])
        if serializers:
            prompt_str += "\n=== Associated Serializers/Models ===\n"
            for idx, ser in enumerate(serializers):
                prompt_str += f"-- Serializer/Model {idx+1}: {ser.get('name')} (Path: {ser.get('path')}) --\n"
                prompt_str += f"```python\n{ser.get('code', '# Serializer/Model code not available')}\n```\n" # Assuming python for Django
                data_classes = ser.get("data_classes", [])
                if data_classes:
                    prompt_str += f"--- Models for Serialzier {ser.get('name')} ---\n"
                    for dc_idx, dc in enumerate(data_classes):
                        prompt_str += f"---- Model {dc_idx+1}: {dc.get('name')} ----\n"
                        prompt_str += f"---- Model {dc_idx+1} Path: {dc.get('path')} ----\n"
                        prompt_str += f"```python\n{dc.get('code', '# Model code not available')}\n```\n" # Assuming python
                    prompt_str += f"--- End Models for {ser.get('name')} ---\n" # This was slightly mis-indented in original example, fixing
            prompt_str += "=== End Associated Serializers/Models ===\n" # Corrected placement

        features = endpoint_context.get("features", [])
        if features:
            prompt_str += "\n=== Associated Features (Pagination, Auth, Filters) ===\n"
            for idx, feat in enumerate(features):
                prompt_str += f"-- Feature {idx+1}: {feat.get('name')} ({feat.get('type')}, Path: {feat.get('path')}) --\n"
                prompt_str += f"```python\n{feat.get('code', '# Feature code not available')}\n```\n" # Assuming python
            prompt_str += "=== End Associated Features ===\n"
        
        # Framework settings were commented out in original, keep it that way or decide if needed.
        # settings = endpoint_context.get("framework_settings", {}).get("settings", {})
        # if settings:
        #     prompt_str += "\n=== Relevant Framework Settings ===\n"
        #     # ... add settings if needed ...
        #     prompt_str += "=== End Framework Settings ===\n"

        return prompt_str.strip()

    def get_framework_specific_guidance_for_missing_symbols(self) -> str:
        """
        Provides Django-specific instructions on what kinds of custom symbols to look for.
        This is the "Focus on:" section of the original Django prompt.
        """
        return """Focus on:
1.  **Completeness:** Ensure you list all relevant custom symbols referenced in the provided context snippets (handler, serializers, features, etc.).
2.  **Custom Logic:** Prioritize user-defined classes and functions specific to this project. Include classes directly assigned to view attributes like `permission_classes`, `authentication_classes`, `filterset_class`, `serializer_class` (if different from the main one), and `pagination_class`, as their internal logic often influences the API behavior or contract. Also include classes instantiated or functions called directly within the handler's methods (like `perform_create`, `list_products`, `get_queryset`).
3.  **Relevance & Necessity:** Only include symbols directly impacting or clarifying the OpenAPI spec generation for *this* endpoint. Their code definition should provide meaningful information about fields, types, validation, structure, status codes, permissions, or data manipulation relevant to the external API contract.
4.  **Data Flow:** Consider symbols involved in data validation (e.g., custom validators called), serialization (alternative serializers used), database interaction (if it affects response structure), permission checks (custom permission classes), authentication schemes (custom auth classes), filtering (custom filtersets/backends), pagination (custom pagination classes), and custom helper/utility functions called by the handler."""
        # Note: The original prompt had "5.  **Data Flow:** ..." This was a typo, it should be 4. Corrected here.
        # The example had "5." as "Exclusions:" but that's a separate section.

    def get_framework_specific_exclusion_instructions_for_missing_symbols(self) -> str:
        """
        Returns the Django-specific "Exclusions:" paragraph.
        """
        return """Exclusions:
Do **not** include standard library imports (like `re`, `datetime`). Do **not** include well-known, unmodified framework base classes (like `viewsets.ModelViewSet`, `serializers.ModelSerializer`, `permissions.BasePermission`, `BaseAuthentication`, `PageNumberPagination`, `filters.FilterSet`) unless they have been significantly subclassed *and* the specific subclass is referenced *and* its custom logic is relevant."""

    def get_framework_specific_exclusions_for_missing_symbols(self) -> List[str]:
        """
        Returns Django-specific patterns or FQNs to exclude.
        """
        return [
            "django.db.models",
            "django.contrib.auth.models",
            "rest_framework.viewsets.ModelViewSet",
            "rest_framework.serializers.ModelSerializer",
            "rest_framework.permissions.BasePermission",
            "rest_framework.authentication.BaseAuthentication",
            "rest_framework.pagination.PageNumberPagination",
            "django_filters.FilterSet",
        ]
    
    def is_relaxed_obj_validation(self):
        return False
    
