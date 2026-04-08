import ast
from enum import Enum
import json
import os
import re
import textwrap
from typing import Dict, List, Set, Optional, Any, Tuple
import copy

from common.core.code_analyzer import CodeAnalyzer, SymbolType

    
class PythonCodeAnalyzer(CodeAnalyzer):
    """
    Python implementation of the CodeAnalyzer interface.
    Analyzes Python code to extract classes, functions, and their relationships.
    """
    
    def __init__(self):
        """Initialize analyzer with empty state."""
        # Inherited from current implementation
        self.total_classes = 0
        self.total_functions = 0
        self.total_statements = 0
        self.full_code_arr = []
        self.max_statement_group_token_limit = 2000
        self.imports = {}
        self.starting_point = None
        self.url_path = None
        self.resolved_imports = {}
        self.files = set()
        self.is_done = set()
        self.file_identifiers = {}
        self.apis = {}
        self.unresolved_path_to_module = {}
        self.module_to_path = {}
        self.result = {}
        self.no_of_lines = 0
        self.unresolved_imports = {}
        
        # Sys path for external code resolution
        self.sys_path = None
    
    def analyze_project(self, project_path: str, output_dir: str, framework=None) -> str:
        """
        Analyze a Python project and persist results.
        
        Args:
            project_path: Path to the project directory
            output_dir: Directory to store analysis results
            
        Returns:
            Path to the analysis results file
        """
        # Ensure absolute paths
        abs_project_path = os.path.abspath(project_path)
        abs_output_dir = os.path.abspath(output_dir)
        
        # Find all Python files
        files_list = []
        for root, _, files in os.walk(abs_project_path):
            for file in files:
                if file.endswith(".py"):
                    files_list.append(os.path.abspath(os.path.join(root, file)))
        
        # Look for starting point (manage.py for Django)
        self.starting_point = None
        for file_path in files_list:
            if file_path.endswith("manage.py"):
                self.starting_point = file_path
                break
        
        if self.starting_point is None:
            print("WARNING: Cannot find starting point (manage.py) in project. Using project directory as starting point.")
            self.starting_point = abs_project_path
        
        # Find URL configuration
        self._find_url_configuration(files_list)
        
        # Prepare file lists - using absolute paths
        for root, dirs, files in os.walk(os.path.dirname(self.starting_point)):
            abs_root = os.path.abspath(root)
            for dir_name in dirs:
                self.files.add(os.path.abspath(os.path.join(abs_root, dir_name)))
            for file_name in files:
                self.files.add(os.path.abspath(os.path.join(abs_root, file_name)))
        
        # First pass: build imports and identifiers
        for file_path in files_list:
            self._set_imports(file_path)
            self._set_file_identifiers(file_path)
        
        # Second pass: resolve dependencies
        for file_path in files_list:
            self.resolve_dependencies(file_path)
        
        # Set sys.path for external code resolution
        self._set_sys_path()
        
        # Persist results
        os.makedirs(abs_output_dir, exist_ok=True)
        result_path = os.path.join(abs_output_dir, "py_analysed.json")
        
        with open(result_path, "w") as file:
            json.dump({
                "result": self.result,
                "module_to_path": self.module_to_path,
                "file_identifiers": self.file_identifiers,
                "no_of_lines": self.no_of_lines,
                "unresolved_imports": self.unresolved_imports,
                "sys_path": self.sys_path
            }, file, indent=2)
        
        return result_path
    
    def load_analysis_results(self, results_path: str) -> Dict[str, Any]:
        """
        Load previously persisted analysis results.
        
        Args:
            results_path: Path to the analysis results file
            
        Returns:
            Dictionary containing the loaded analysis results
        """
        with open(results_path) as f:
            data = json.load(f)
            
            # Restore state from loaded data
            self.result = data["result"]
            self.module_to_path = data["module_to_path"]
            self.file_identifiers = data["file_identifiers"]
            self.no_of_lines = data["no_of_lines"]
            self.unresolved_imports = data.get("unresolved_imports", {})
            self.sys_path = data.get("sys_path")
            
            return data
    
    def analyze_file(self, file_path: str) -> Dict[str, Any]:
        """
        Analyze a single Python file.
        
        Args:
            file_path: Path to the file to analyze
            
        Returns:
            Dictionary containing analysis results
        """
        # Ensure absolute path
        abs_file_path = os.path.abspath(file_path)
        
        #print(f"Analyzing file: {abs_file_path}")
        with open(abs_file_path) as f:
            file_content = f.read()
        
        self.full_code_arr = file_content.split("\n")
        
        try:
            code_tree = ast.parse(file_content)
            #print(f"AST parsed successfully for {abs_file_path}")
            
            # See what's in the tree
            top_level_classes = [node.name for node in code_tree.body if isinstance(node, ast.ClassDef)]
            #print(f"Top-level classes in AST: {top_level_classes}")
            
            classes = self._process_classes(code_tree, abs_file_path)
            #print(f"Classes after _process_classes: {list(classes.keys())}")
            
            functions = self._process_functions(code_tree)
            statements = self._process_statements(code_tree)
            
            identifiers = self.file_identifiers.get(abs_file_path, {})
            
            return {
                "classes": classes,
                "functions": functions,
                "statements": statements,
                "identifiers": identifiers,
            }
        except Exception as e:
            import traceback
            print(f"Error analyzing file {abs_file_path}: {e}")
            traceback.print_exc()
            return {
                "classes": {},
                "functions": {},
                "statements": [],
                "not_analyzed": file_content,
                "error": str(e)
            }
        
    def analyze_single_file(self, file_path: str) -> Dict[str, Any]:
        """
        Analyze a single file including imports.
        
        Args:
            file_path: Path to the file to analyze
            
        Returns:
            Dictionary containing complete file analysis
        """
        with open(file_path) as f:
            file_content = f.read()
        
        self.full_code_arr = file_content.split("\n")
        code_tree = ast.parse(file_content)
        
        # Set up file identifiers and imports
        self._set_file_identifiers(file_path)
        self._set_imports(file_path)
        
        # Process file contents
        classes = self._process_classes(code_tree, file_path)
        functions = self._process_functions(code_tree)
        statements = self._process_statements(code_tree)
        identifiers = self.file_identifiers.get(file_path, {})
        
        return {
            "classes": classes,
            "functions": functions,
            "statements": statements,
            "identifiers": identifiers,
            "imports": self.imports.get(file_path, {})
        }
    
    def resolve_dependencies(self, file_path: str) -> Dict[str, Any]:
        """
        Resolve dependencies for a specific file.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Dictionary containing resolved dependencies
        """
        if file_path in self.is_done:
            return {}
        
        self.is_done.add(file_path)
        
        # Get imports for this file
        imports = self.imports.get(file_path, {})
        identifiers = self.file_identifiers.get(file_path, {})
        
        # Process each import
        for alias in imports:
            imp = imports[alias]
            name = imp["name"]
            path, import_file_as_alias = self._ensure_path_exists(imp["path"], name)
            
            if path is None:
                # Track unresolved import
                if file_path not in self.unresolved_imports:
                    self.unresolved_imports[file_path] = {}
                self.unresolved_imports[file_path][alias] = {
                    "alias": alias,
                    "name": name,
                    "code": imp["code"]
                }
                continue
            
            # Recursively resolve dependencies
            self.resolve_dependencies(path)
            
            # Process resolved import based on type
            f_identifier = copy.deepcopy(self.file_identifiers.get(path, {}))
            is_star = imp["is_star"]
            is_from = imp["is_from"]
            
            # Update identifiers based on import type
            if is_from:
                if is_star:
                    # From module import *
                    identifiers["classes"].update(f_identifier.get("classes", {}))
                    identifiers["functions"].update(f_identifier.get("functions", {}))
                    identifiers["variables"].update(f_identifier.get("variables", {}))
                elif import_file_as_alias:
                    # From module import name as alias
                    self._update_identifiers_with_prefix(identifiers, f_identifier, alias)
                else:
                    # From module import name
                    if name in f_identifier.get("classes", {}):
                        if "classes" not in identifiers:
                            identifiers["classes"] = {}
                        identifiers["classes"][alias] = f_identifier["classes"][name]
                        identifiers["classes"][alias]["alias"] = alias
                    elif name in f_identifier.get("functions", {}):
                        if "functions" not in identifiers:
                            identifiers["functions"] = {}
                        identifiers["functions"][alias] = f_identifier["functions"][name]
                        identifiers["functions"][alias]["alias"] = alias
                    elif name in f_identifier.get("variables", {}):
                        if "variables" not in identifiers:
                            identifiers["variables"] = {}
                        identifiers["variables"][alias] = f_identifier["variables"][name]
                        identifiers["variables"][alias]["alias"] = alias
                    elif os.path.basename(path) == "__init__.py":
                        epath = os.path.dirname(path) + "/" + name + ".py"
                        if epath in self.files:
                            self.resolve_dependencies(epath)
                            e_identifier = self.file_identifiers.get(epath, {})
                            
                            # Add nested identifiers
                            for key in e_identifier.get("functions", {}):
                                f_alias = alias + "." + e_identifier["functions"][key]["alias"]
                                if "functions" not in identifiers:
                                    identifiers["functions"] = {}
                                identifiers["functions"][f_alias] = e_identifier["functions"][key].copy()
                                identifiers["functions"][f_alias]["alias"] = f_alias
                            
                            for key in e_identifier.get("classes", {}):
                                c_alias = alias + "." + e_identifier["classes"][key]["alias"]
                                if "classes" not in identifiers:
                                    identifiers["classes"] = {}
                                identifiers["classes"][c_alias] = e_identifier["classes"][key].copy()
                                identifiers["classes"][c_alias]["alias"] = c_alias
                            
                            for key in e_identifier.get("variables", {}):
                                v_alias = alias + "." + e_identifier["variables"][key]["alias"]
                                if "variables" not in identifiers:
                                    identifiers["variables"] = {}
                                identifiers["variables"][v_alias] = e_identifier["variables"][key].copy()
                                identifiers["variables"][v_alias]["alias"] = v_alias
                            
                            if "file_identifiers" not in identifiers:
                                identifiers["file_identifiers"] = {}
                            identifiers["file_identifiers"][alias] = {
                                "alias": alias,
                                "name": name,
                                "path": epath,
                            }
            else:
                # Import module [as alias]
                for key in f_identifier.get("functions", {}):
                    f_alias = alias + "." + f_identifier["functions"][key]["alias"]
                    if "functions" not in identifiers:
                        identifiers["functions"] = {}
                    identifiers["functions"][f_alias] = f_identifier["functions"][key].copy()
                    identifiers["functions"][f_alias]["alias"] = f_alias

                for key in f_identifier.get("classes", {}):
                    c_alias = alias + "." + f_identifier["classes"][key]["alias"]
                    if "classes" not in identifiers:
                        identifiers["classes"] = {}
                    identifiers["classes"][c_alias] = f_identifier["classes"][key].copy()
                    identifiers["classes"][c_alias]["alias"] = c_alias

                for key in f_identifier.get("variables", {}):
                    v_alias = alias + "." + f_identifier["variables"][key]["alias"]
                    if "variables" not in identifiers:
                        identifiers["variables"] = {}
                    identifiers["variables"][v_alias] = f_identifier["variables"][key].copy()
                    identifiers["variables"][v_alias]["alias"] = v_alias
                
                if "file_identifiers" not in identifiers:
                    identifiers["file_identifiers"] = {}
                identifiers["file_identifiers"][alias] = {
                    "alias": alias,
                    "name": name,
                    "path": path,
                }
        
        # Update file identifiers
        self.file_identifiers[file_path] = identifiers
        
        # Analyze file and store in results
        self.result[file_path] = self.analyze_file(file_path)
        
        return self.result[file_path]
    
    def get_code_snippet(self, file_path: str, start_line: int, end_line: int) -> str:
        """
        Extract a specific code snippet from a file.
        
        Args:
            file_path: Path to the file
            start_line: Starting line number (1-indexed)
            end_line: Ending line number (inclusive)
            
        Returns:
            String containing the code snippet
        """
        snippet_lines = []
        with open(file_path, "r") as file:
            for current_line, line in enumerate(file, start=1):
                if start_line <= current_line <= end_line:
                    snippet_lines.append(line)
                elif current_line > end_line:
                    break
        return "".join(snippet_lines)
    
    def get_symbol_info(self, symbol_name: str, context_path: str, symbol_type) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific symbol.
        
        Args:
            symbol_name: Name of the symbol to look up
            context_path: File providing context for resolution
            
        Returns:
            Dictionary with symbol information or None if not found
        """
        if isinstance(symbol_type, SymbolType):
            # Retrieve the symbol using the plural form
            return self.result[context_path][symbol_type.analysis_key()][symbol_name]
    
    def get_symbol_reference(self, symbol_name: str, context_path: str, symbol_type) -> Optional[Dict[str, Any]]:
        if context_path in self.file_identifiers:
                if symbol_type.analysis_key() in self.file_identifiers[context_path]:
                        identifiers = self.file_identifiers[context_path][symbol_type.analysis_key()]
                        if symbol_name in identifiers:
                            # Return full symbol info
                            return identifiers[symbol_name]
        
        # Symbol not found
        return None
    
    def get_type_hierarchy(self, type_name: str, context_path: str) -> List[Dict[str, Any]]:
        """
        Get the parent type hierarchy for a specific type.

        Args:
            type_name:    Name of the type
            context_path: File where the type is defined

        Returns:
            List of dictionaries containing parent type information
        """
        if context_path not in self.result or type_name not in self.result[context_path]["classes"]:
            return []

        hierarchy = []
        visited = set([type_name])

        # Get immediate parent classes
        parent_classes = self.result[context_path]["classes"][type_name]["parentClasses"]
        
        for parent_name, parent_info in parent_classes.items():
            if parent_name in visited:
                continue
                
            visited.add(parent_name)
            parent_path = parent_info.get("path")
            
            # Create parent entry
            parent_entry = {
                "name": parent_name,
                "path": parent_path,
                "source": self.get_code_snippet(parent_path, 
                                              self.result[parent_path]["classes"].get(parent_name, {}).get("startLine", 0),
                                              self.result[parent_path]["classes"].get(parent_name, {}).get("endLine", 0))
                if parent_path and parent_name in self.result.get(parent_path, {}).get("classes", {}) else None
            }
            
            hierarchy.append(parent_entry)
            
            # Recursively get parent's hierarchy if available
            if parent_path and parent_name in self.result.get(parent_path, {}).get("classes", {}):
                further_hierarchy = self.get_type_hierarchy(parent_name, parent_path)
                # Only add entries not already in hierarchy
                for entry in further_hierarchy:
                    if entry["name"] not in visited:
                        hierarchy.append(entry)
                        visited.add(entry["name"])
        
        return hierarchy
    
    def get_external_code(self, symbol: str, context_path: str) -> Optional[str]:
        """
        Retrieve code for an external symbol not directly in the project.
        This is a faithful port of the current implementation from resolve_external_dependencies.py.
        
        Args:
            symbol: Symbol name to retrieve
            context_path: Path providing context for symbol resolution
            
        Returns:
            Code snippet for the external symbol or None if not found
        """
        if self.sys_path is None:
            return None
            
        try:
            if context_path not in self.unresolved_imports:
                return None
                
            # Match progressively longer prefixes of the symbol
            var_split = symbol.split(".")
            fvar = ""
            
            for var_ in var_split:
                fvar = fvar + "." + var_
                if fvar[0] == ".":
                    fvar = fvar[1:]
                if fvar in self.unresolved_imports[context_path]:
                    break
                    
            if fvar not in self.unresolved_imports[context_path]:
                return None
                
            # Get the import statement
            imp = self.unresolved_imports[context_path][fvar]["code"]
            
            # Resolve the import
            analyzed, resolved_path = self._resolve_import(self.sys_path, imp, symbol, context_path)
            
            if analyzed is None:
                return None
                
            # Get code snippet
            return self.get_code_snippet(resolved_path, analyzed["startLine"], analyzed["endLine"])
            
        except Exception as e:
            print(f"Error in get_external_code: {e}")
            return None
    
    def get_analyzed_files(self) -> List[str]:
        """
        Get a list of all files that have been analyzed.
        
        Returns:
            List of absolute file paths that have been analyzed
        """
        # Return keys from result dictionary which contains all analyzed files
        if hasattr(self, 'result') and self.result:
            file_paths = list(self.result.keys())
            # Convert to absolute paths if they aren't already
            absolute_paths = [os.path.abspath(path) for path in file_paths]
            return absolute_paths
        return []


    def get_file_classes(self, file_path: str) -> List[str]:
        """Get all class names defined in a file from previously analyzed data."""
        # Access the already analyzed data directly
        if file_path in self.result and "classes" in self.result[file_path]:
            return self.result[file_path]["classes"]
        return {}

    def get_referenced_classes(self, code: str, context_path: str) -> List[Dict[str, Any]]:
        """Extract classes referenced in the given code."""
        referenced_classes = []
        
        try:
            tree = ast.parse(code)
            
            # Extract class names using existing method
            class_names = self.extract_class_names(code)
            
            # Resolve each class name to a complete reference
            for class_name in class_names:
                # Handle simple names vs qualified names
                if "." in class_name:
                    base_name = class_name.split(".")[0]
                    # Look up base in file identifiers
                    if context_path in self.file_identifiers and base_name in self.file_identifiers[context_path].get("classes", {}):
                        # This is a reference to an imported class
                        class_ref = self.file_identifiers[context_path]["classes"][base_name]
                        referenced_classes.append({
                            "name": class_name.split(".")[-1],
                            "path": class_ref.get("path"),
                            "full_name": class_name
                        })
                else:
                    # Look up directly in file identifiers
                    if context_path in self.file_identifiers and class_name in self.file_identifiers[context_path].get("classes", {}):
                        class_ref = self.file_identifiers[context_path]["classes"][class_name]
                        referenced_classes.append({
                            "name": class_name,
                            "path": class_ref.get("path"),
                            "full_name": class_name
                        })
        
        except SyntaxError:
            # Handle potential syntax errors in code snippet
            pass
            
        return referenced_classes

    def get_class_inheritance_tree(self, class_name: str, class_path: str) -> List[Dict[str, Any]]:
        """Get the complete inheritance tree for a class."""
        inheritance_tree = []
        all_parent_names_in_tree = set()
        queue = [(class_name, class_path)]
        
        processed_in_this_run = set()
        processed_in_this_run.add(f"{class_path}:{class_name}")
        
        while queue:
            current_name, current_path = queue.pop(0)

            class_info = self.get_symbol_info(current_name, current_path, SymbolType.CLASS)
            if not class_info:
                continue

            for parent_name, parent_info in class_info.get("parentClasses", {}).items():
                
                # Check if we have already added this parent to our final list.
                if parent_name in all_parent_names_in_tree:
                    continue

                parent_path = parent_info.get("path")

                # Add the parent to our results tree.
                parent_entry = {
                    "name": parent_name,
                    "path": parent_path,
                    "code": None  # Initially set code to None.
                }

                # If the parent is an internal class, we can get its code and
                # add it to the queue to process its parents.
                if parent_path:
                    parent_class_name_simple = parent_name.split(".")[-1]
                    parent_class_info = self.get_symbol_info(parent_class_name_simple, parent_path, SymbolType.CLASS)
                    
                    if parent_class_info:
                        parent_entry["code"] = self.get_code_snippet(
                            parent_path,
                            parent_class_info.get("startLine", 0),
                            parent_class_info.get("endLine", 0)
                        )
                    
                    # Add this internal parent to the queue to traverse its parents,
                    # ensuring we don't process it again.
                    parent_key = f"{parent_path}:{parent_class_name_simple}"
                    if parent_key not in processed_in_this_run:
                        queue.append((parent_class_name_simple, parent_path))
                        processed_in_this_run.add(parent_key)

                # Add the constructed parent entry to our final list and mark it as seen.
                inheritance_tree.append(parent_entry)
                all_parent_names_in_tree.add(parent_name)

        return inheritance_tree

    def get_inner_classes(self, class_name: str, class_path: str) -> Dict[str, Dict[str, Any]]:
        """
        Gets inner classes defined within a class, returning the full, rich
        information dictionary for each, including 'property_assignments'.
        """
        inner_classes_map = {}
        
        class_info = self.get_symbol_info(class_name, class_path, SymbolType.CLASS)
        if not class_info:
            return inner_classes_map
            
        # The 'innerClasses' key holds a list of full-featured dictionaries.
        for inner_class_info in class_info.get("innerClasses", []):
            inner_class_name = inner_class_info.get("name")
            if not inner_class_name:
                continue

            # Instead of creating a new, limited dict, we pass the whole thing.
            # But we must ensure the 'code' snippet is also present, as the caller relies on it.
            # The original 'get_inner_classes' was responsible for adding the code. We must preserve that.
            
            # Create a copy to avoid modifying the original analysis result data.
            full_inner_class_info = inner_class_info.copy()
            
            # Add the code snippet, as was done previously.
            full_inner_class_info['code'] = self.get_code_snippet(
                class_path, # Inner classes are in the same file as the outer class.
                inner_class_info.get("startLine", 0),
                inner_class_info.get("endLine", 0)
            )

            inner_classes_map[inner_class_name] = full_inner_class_info
        
        return inner_classes_map

    def get_class_ast(self, class_name: str, file_path: str) -> Optional[ast.ClassDef]:
        """
        Retrieves the AST ClassDef node for a specific class from a file.
        This is a specific utility needed by framework analyzers to inspect
        the internal structure of a class.
        """
        if not os.path.exists(file_path):
            return None

        with open(file_path, 'r', encoding='utf-8') as f:
            file_content = f.read()

        try:
            tree = ast.parse(file_content)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == class_name:
                    return node
        except SyntaxError as e:
            self.logger.error(f"Syntax error parsing {file_path} in get_class_ast: {e}")
            return None
        return None
    
    # Internal helper methods
    def _find_url_configuration(self, files_list: List[str]) -> None:
        """Find the root URL configuration file."""
        pattern = r"^ROOT_URLCONF\s*=\s*(.*)$"
        
        for file_path in files_list:
            with open(file_path) as f:
                code = f.read()
            
            statements = self._get_all_statements(code)
            for statement in statements:
                matches = re.findall(pattern, statement)
                if matches:
                    prefix = os.path.dirname(self.starting_point)
                    while prefix != "/":
                        path = os.path.join(prefix, self._remove_quotes(matches[0]).replace(".", "/") + ".py")
                        if os.path.exists(path):
                            self.url_path = path
                            return
                        
                        path = os.path.join(prefix, self._remove_quotes(matches[0]).replace(".", "/"), "__init__.py")
                        if os.path.exists(path):
                            self.url_path = path
                            return
                        
                        prefix = os.path.dirname(prefix)
    
    def _set_imports(self, file_path: str) -> None:
        """Extract imports from a file."""
        with open(file_path) as f:
            file_content = f.read()
        
        imports = {}
        node = ast.parse(file_content)
        
        for item in node.body:
            if isinstance(item, ast.Import):
                for name_obj in item.names:
                    alias = name_obj.asname
                    name = name_obj.name
                    key = alias if alias else name
                    imports[key] = {
                        "alias": key,
                        "name": name,
                        "path": self._convert_module_to_path(name, file_path),
                        "is_star": False,
                        "is_from": False,
                        "code": ast.unparse(item)
                    }
            elif isinstance(item, ast.ImportFrom):
                pattern = r"from(.*?)import"
                matches = re.findall(pattern, ast.unparse(item))
                module = matches[0].strip()
                
                for name_obj in item.names:
                    alias = name_obj.asname
                    name = name_obj.name
                    path = self._convert_module_to_path(module, file_path)
                    key = alias if alias else name
                    is_star = key == "*"
                    
                    imports[f"{ast.unparse(item)}" if is_star else key] = {
                        "alias": key,
                        "name": name,
                        "path": path,
                        "is_star": is_star,
                        "is_from": True,
                        "code": ast.unparse(item)
                    }
        
        self.imports[file_path] = imports
    
    def _set_file_identifiers(self, file_path: str) -> None:
        """Extract and categorize identifiers in a file."""
        with open(file_path) as f:
            file_content = f.read()
        
        tree = ast.parse(file_content)
        functions = {}
        classes = {}
        variables = {}
        
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                functions[node.name] = {
                    "alias": node.name,
                    "name": node.name,
                    "path": file_path,
                    "type": "function",
                }
            elif isinstance(node, ast.ClassDef):
                classes[node.name] = {
                    "alias": node.name,
                    "name": node.name,
                    "path": file_path,
                    "type": "classes",
                }
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        variables[target.id] = {
                            "alias": target.id,
                            "name": target.id,
                            "path": file_path,
                            "type": "variable",
                            "action": type(target.ctx).__name__,
                            "startLine": node.lineno,
                            "endLine": node.end_lineno,
                            "nested_identifiers": {},
                        }
                        
                        # Check if value is a class or function call
                        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
                            variables[target.id]["object"] = node.value.func.id
        
        self.file_identifiers[file_path] = {
            "classes": classes,
            "functions": functions,
            "variables": variables,
            "file_identifiers": {},
        }

    def _process_classes(self, code_tree, file_path: str) -> Dict[str, Any]:
        """Process classes in an AST tree."""
        #print(f"Starting _process_classes for {file_path}")
        classes = {}
        
        for node in code_tree.body:
            if isinstance(node, ast.ClassDef):
                #print(f"Processing class: {node.name}")
                class_info = self._process_class(node, file_path, [])
                #print(f"Processed class {node.name}, adding to classes dict")
                classes[node.name] = class_info  # KEY FIX: Use class name as the key
        
        #print(f"Finished _process_classes, found classes: {list(classes.keys())}")
        return classes
    
    
    def _process_class(self, cls, file_path: str, parent_classes: List[str]) -> Dict[str, Any]:
        """Process a single class."""
        #print(f"Starting _process_class for {cls.name}")
        name = cls.name
        start_line = cls.lineno
        end_line = cls.end_lineno
        
        properties = []
        property_assignments = {}
        functions = {}
        inner_classes = []
        constructors = []
        
        # Get parent classes
        parent_classes_bases = [ast.unparse(base) for base in cls.bases]
        is_root = len(parent_classes) == 0
        parent_classes_dict = {}
        
        for parent_class in parent_classes_bases:
            path = None
            if "classes" in self.file_identifiers.get(file_path, {}):
                if parent_class in self.file_identifiers[file_path]["classes"]:
                    path = self.file_identifiers[file_path]["classes"][parent_class]["path"]
            elif not is_root:
                path = file_path
            
            parent_classes_dict[parent_class] = {
                "name": parent_class,
                "path": path
            }
        
        # Get comment
        comment = self._get_leading_comment(start_line)
        
        # Create a copy of parent_classes to avoid modifying the original list
        parent_classes_copy = parent_classes.copy()
        parent_classes_copy.append(name)
        
        # Process class body
        for class_item in cls.body:
            if isinstance(class_item, ast.Assign):
                for target in class_item.targets:
                    if isinstance(target, ast.Name):
                        properties.append(ast.unparse(target))
                        property_assignments[target.id] = ast.unparse(class_item.value)
            
            elif isinstance(class_item, ast.FunctionDef) and class_item.name == "__init__":
                constructors.append(self._process_function(class_item, parent_classes_copy))
            
            elif isinstance(class_item, ast.FunctionDef) and class_item.name != "__init__":
                fn = self._process_function(class_item, parent_classes_copy)
                functions[fn["context"]["name"]] = fn
            
            elif isinstance(class_item, ast.ClassDef):
                inner_class = self._process_class(class_item, file_path, parent_classes_copy)
                inner_classes.append(inner_class)
        
        # Update class count
        self.total_classes += 1
        
        # Add class to file identifiers if it's a root class
        if is_root:
            if file_path not in self.file_identifiers:
                self.file_identifiers[file_path] = {"classes": {}, "functions": {}, "variables": {}, "file_identifiers": {}}
            
            if "classes" not in self.file_identifiers[file_path]:
                self.file_identifiers[file_path]["classes"] = {}
            
            self.file_identifiers[file_path]["classes"][name] = {
                "name": name,
                "alias": name,
                "path": file_path,
                "type": "class",
            }
        
        # Update line count
        self.no_of_lines += end_line - start_line
        
        class_info = {
            "name": name,
            "path": file_path,
            "startLine": start_line,
            "endLine": end_line,
            "functions": functions,
            "constructors": constructors,
            "properties": properties,
             "property_assignments": property_assignments,
            "innerClasses": inner_classes,
            "parentClasses": parent_classes_dict,
            "comment": comment,
            "identifiers": self._set_code_identifiers(ast.unparse(cls)),
        }
        
        #print(f"Finished _process_class for {name}")
        return class_info
    
    def _process_functions(self, code_tree) -> Dict[str, Any]:
        """Process functions in an AST tree."""
        functions = {}
        for fn in code_tree.body:
            if isinstance(fn, ast.FunctionDef):
                fn = self._process_function(fn, parent_classes=[])
                functions[fn["context"]["name"]] = fn
        return functions
    
    def _process_function(self, fn, parent_classes: List[str]) -> Dict[str, Any]:
        """Process a single function."""
        name = fn.name
        start_line_number = fn.lineno
        end_line_number = fn.end_lineno
        code = ast.unparse(fn)
        
        # Get function signature
        signature = self._get_function_signature(code)
        
        # Get leading comment
        comment = self._get_leading_comment(start_line_number)
        
        # Update function count
        self.total_functions += 1
        
        # Get return type if specified
        return_type = ""
        if hasattr(fn, 'returns') and isinstance(fn.returns, ast.Name):
            return_type = ast.dump(fn.returns, annotate_fields=False)
        
        # Check if function is an API endpoint
        is_api = False
        for decorator in fn.decorator_list:
            if isinstance(decorator, ast.Call) and hasattr(decorator.func, "id") and decorator.func.id == "action":
                is_api = True
        
        # Create context information
        name_prefix = ""
        nested_context = ""
        if parent_classes:
            name_prefix = ".".join(parent_classes) + "."
            parent_class = parent_classes[-1]
            nested_context = "parent class: " + parent_class
        
        full_name = name_prefix + name
        
        # Update line count
        self.no_of_lines += end_line_number - start_line_number
        
        context = {
            "signature": signature,
            "name": name,
            "returnType": return_type,
            "fullName": full_name,
            "nestedContext": nested_context,
        }
        
        # Get decorators
        decorator_list = [ast.unparse(d) for d in fn.decorator_list]
        
        return {
            "startLine": start_line_number,
            "endLine": end_line_number,
            "comment": comment,
            "decorators": decorator_list,
            "context": context,
            "is_api": is_api,
            "identifiers": self._set_code_identifiers(code),
        }
    
    def _process_statements(self, code_tree) -> List[Dict[str, Any]]:
        """Process statements in an AST tree."""
        statements = []
        start_line = -1
        end_line = -1
        code = ""
        comment = ""
        total_token_count = 0
        
        for statement in code_tree.body:
            # Skip classes and functions (handled separately)
            if isinstance(statement, (ast.ClassDef, ast.FunctionDef)):
                continue
                
            current_token_count = len(ast.unparse(statement).split())
            
            # Skip initial imports
            if len(statements) == 0 and isinstance(statement, (ast.Import, ast.ImportFrom)):
                continue
            
            # Start new statement group if needed
            if (
                total_token_count + current_token_count > self.max_statement_group_token_limit
            ):
                if start_line != -1:
                    self.no_of_lines += end_line - start_line
                    statements.append({
                        "startLine": start_line,
                        "endLine": end_line,
                        "comment": comment,
                        "identifiers": self._set_code_identifiers(code),
                    })
                    start_line = -1
                    end_line = -1
                    code = ""
                    comment = ""
                    total_token_count = 0
            
            # Start new statement group if needed
            if start_line == -1:
                start_line = statement.lineno
                comment = self._get_leading_comment(start_line)
            
            # Update end line and add code
            end_line = statement.end_lineno
            code = code + "\n" + ast.unparse(statement)
            total_token_count += current_token_count
        
        # Add final statement group if any
        if start_line != -1:
            self.no_of_lines += end_line - start_line
            statements.append({
                "startLine": start_line,
                "endLine": end_line,
                "comment": comment,
                "identifiers": self._set_code_identifiers(code),
            })
        
        self.total_statements += len(statements)
        return statements
    
    def _get_leading_comment(self, code_start_line: int) -> str:
        """Get comment preceding a code line."""
        code_start_line = code_start_line - 1
        end_line = code_start_line - 1
        start_line = None
        
        for line in range(end_line, -1, -1):
            if line >= len(self.full_code_arr):
                continue
                
            code = self.full_code_arr[line]
            
            if code.strip() == "":
                continue
            elif code.strip().startswith("#") or code.strip().startswith('"""'):
                start_line = line
                break
            elif code.strip().endswith('"""'):
                continue
            else:
                return ""
        
        if not start_line:
            return ""
        
        return "".join(self.full_code_arr[start_line:code_start_line])
    
    def _get_function_signature(self, code: str) -> str:
        """Extract function signature from code."""
        try:
            start = code.index("def") + 4
            end = code.index(":")
            return code[start:end]
        except ValueError:
            return ""
    
    def _set_code_identifiers(self, code: str) -> Dict[str, List[str]]:
        """Extract identifiers from code."""
        try:
            tree = ast.parse(code)
            functions = set()
            classes = set()
            variables = set()
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            variables.add(target.id)
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        functions.add(node.func.id)
                        classes.add(node.func.id)
                    elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                        functions.add(ast.unparse(node.func))
            
            return {
                "classes": list(classes),
                "functions": list(functions),
                "variables": list(variables),
            }
        except SyntaxError:
            # Handle potential syntax errors in partial code snippets
            print(f"Syntax error in _set_code_identifiers with code: {code[:100]}...")
            return {
                "classes": [],
                "functions": [],
                "variables": [],
            }
    
    def _convert_module_to_path(self, module: str, file_path: str) -> Optional[str]:
        """Convert module name to file path."""
        if self.starting_point is None:
            return None
        
        module_path = None
        if module.startswith("."):
            dir_path = os.path.dirname(file_path)
            if module.startswith(".."):
                module_path = "../" + module[2:].replace(".", "/")
            elif module.startswith("."):
                module_path = "./" + module[1:].replace(".", "/")
        else:
            dir_path = os.path.dirname(self.starting_point)
            module_path = module.replace(".", "/")
        
        final_path = os.path.normpath(os.path.join(dir_path, module_path))
        self.unresolved_path_to_module[final_path] = module
        
        return final_path
    
    def _ensure_path_exists(self, path: str, suffix: Optional[str] = None) -> Tuple[Optional[str], bool]:
        """Ensure a path exists and resolve it properly."""
        final_path = None
        import_file_as_alias = False
        
        if suffix and os.path.join(path, suffix + ".py") in self.files:
            final_path = os.path.join(path, suffix + ".py")
            import_file_as_alias = True
        elif suffix and os.path.join(path, suffix, "__init__.py") in self.files:
            final_path = os.path.join(path, suffix, "__init__.py")
            import_file_as_alias = True
        elif path + "/__init__.py" in self.files:
            final_path = path + "/__init__.py"
        elif path + ".py" in self.files:
            final_path = path + ".py"
        
        if path in self.unresolved_path_to_module:
            self.module_to_path[self.unresolved_path_to_module[path]] = final_path
        
        return final_path, import_file_as_alias
    
    def _update_identifiers_with_prefix(self, target_identifiers: Dict, source_identifiers: Dict, prefix: str) -> None:
        """Update identifiers with a prefix."""
        # Initialize target sections if needed
        for section in ["classes", "functions", "variables", "file_identifiers"]:
            if section not in target_identifiers:
                target_identifiers[section] = {}
                
        # Classes
        if "classes" in source_identifiers:
            classes = {f"{prefix}.{key}": value.copy() for key, value in source_identifiers["classes"].items()}
            for key, value in classes.items():
                value["alias"] = key
            target_identifiers["classes"].update(classes)
        
        # Functions
        if "functions" in source_identifiers:
            functions = {f"{prefix}.{key}": value.copy() for key, value in source_identifiers["functions"].items()}
            for key, value in functions.items():
                value["alias"] = key
            target_identifiers["functions"].update(functions)
        
        # Variables
        if "variables" in source_identifiers:
            variables = {f"{prefix}.{key}": value.copy() for key, value in source_identifiers["variables"].items()}
            for key, value in variables.items():
                value["alias"] = key
            target_identifiers["variables"].update(variables)
    
    def _get_all_statements(self, code: str) -> List[str]:
        """Get all top-level statements from code."""
        try:
            tree = ast.parse(code)
            result = []
            for statement in tree.body:
                if isinstance(statement, (ast.ClassDef, ast.FunctionDef)):
                    continue
                result.append(ast.unparse(statement))
            return result
        except:
            return []
    
    def _remove_quotes(self, stmt: str) -> str:
        """Remove quotes from a string."""
        if stmt and (stmt[0] == '"' or stmt[0] == "'"):
            stmt = stmt[1:]
        if stmt and (stmt[-1] == '"' or stmt[-1] == "'"):
            stmt = stmt[:-1]
        return stmt
    
    def _is_django_serializer(self, type_path: str, type_name: str, visited: set) -> bool:
        """Determine if a type is a Django serializer."""
        if type_name in visited:
            return False
            
        visited.add(type_name)
        
        if type_path not in self.result or type_name not in self.result[type_path]["classes"]:
            return False
        
        parent_classes = self.result[type_path]["classes"][type_name]["parentClasses"]
        
        for parent_name in parent_classes:
            if "Serializer" in parent_name:
                return True
            
            parent_path = parent_classes[parent_name]["path"]
            if parent_path and self._is_django_serializer(parent_path, parent_name, visited):
                return True
        
        return False
    
    def _is_django_viewset(self, type_path: str, type_name: str, visited: set) -> bool:
        """Determine if a type is a Django viewset."""
        if type_name in visited:
            return False
            
        visited.add(type_name)
        
        if type_path not in self.result or type_name not in self.result[type_path]["classes"]:
            return False
        
        parent_classes = self.result[type_path]["classes"][type_name]["parentClasses"]
        
        for parent_name in parent_classes:
            if "ViewSet" in parent_name or "ModelViewSet" in parent_name or "ReadOnlyModelViewSet" in parent_name:
                return True
            
            parent_path = parent_classes[parent_name]["path"]
            if parent_path and self._is_django_viewset(parent_path, parent_name, visited):
                return True
        
        return False
    
    def _is_django_model(self, type_path: str, type_name: str, visited: set) -> bool:
        """Determine if a type is a Django model."""
        if type_name in visited:
            return False
                
        visited.add(type_name)
        
        if type_path not in self.result or type_name not in self.result[type_path]["classes"]:
            return False
        
        # Check if it's a serializer first - serializers are never models
        if self._is_django_serializer(type_path, type_name, set()):
            return False
            
        # Check for model indicators
        class_info = self.result[type_path]["classes"][type_name]
        
        # Check parent classes for models.Model
        parent_classes = class_info["parentClasses"]
        for parent_name in parent_classes:
            if "Model" in parent_name and "models." in parent_name:
                return True
                
        # Check for model fields
        for prop in class_info.get("properties", []):
            if prop == "objects" or prop.endswith("_set"):
                return True
                
        # Check for Meta inner class (common in Django models)
        for inner_class in class_info.get("innerClasses", []):
            if inner_class["name"] == "Meta":
                return True
        
        return False
    
    def _set_sys_path(self) -> None:
        """Set sys.path for external code resolution."""
        # This is simplified - in reality we'd want to capture the Python
        # interpreter's actual sys.path from the project
        if self.starting_point:
            project_root = os.path.dirname(self.starting_point)
            self.sys_path = [
                project_root,
                os.path.join(project_root, "site-packages"),
                # Add more likely paths for external packages
            ]
    
    def _find_in_syspath(self, path: str) -> Optional[str]:
        """Find a module in syspath."""
        if self.sys_path is None:
            return None
            
        for spath in self.sys_path:
            curpath = os.path.join(spath, path)
            if os.path.exists(curpath) or os.path.exists(curpath + ".py"):
                return curpath
                
        return None
    
    def _resolve_import(self, sys_path: List[str], imp: str, module: str, calling_path: str = None) -> Tuple[Dict, str]:
        """
        Resolve an import statement to get code for an external module.
        
        Args:
            sys_path: List of directories to search for modules
            imp: Import statement as text
            module: Module or symbol being looked up
            calling_path: Path of the file that contains the import
            
        Returns:
            Tuple of (analyzed module info, file path)
        """
        # Simplified version - in reality would use advanced import resolution
        imp = re.sub(' +', ' ', imp)
        
        if imp.startswith("import"):
            # Regular import
            package_path = imp[6:].strip()
            module_path = self._find_in_syspath(package_path.replace(".", os.path.sep))
            remaining_module = module[len(package_path)+1:] if package_path in module else module
            
        else:
            # From import
            package_name = imp[4: imp.find("import")].strip()
            
            if package_name.startswith("."):
                # Relative import
                if package_name.startswith(".."):
                    package_name = "../" + package_name[2:].replace(".", os.path.sep)
                else:
                    package_name = "./" + package_name[1:].replace(".", os.path.sep)
                    
                if calling_path:
                    module_path = os.path.abspath(os.path.join(os.path.dirname(calling_path), package_name))
                else:
                    module_path = None
            else:
                # Absolute import
                module_path = self._find_in_syspath(package_name.replace(".", os.path.sep))
                
            remaining_module = module
        
        if not module_path:
            return None, None
            
        # Handle multi-part module names (package.module.submodule)
        module_arr = remaining_module.split(".")
        index = 0
        curr_path = module_path
        
        # Add empty string at start to handle the initial checking
        module_arr.insert(0, "")
        
        for i in range(len(module_arr)):
            curr_path = os.path.join(curr_path, module_arr[i])
            
            # Check for .py file
            py_path = curr_path[:-1] + ".py" if curr_path[-1] == "/" else curr_path + ".py"
            if os.path.exists(py_path):
                module_path = py_path
                index = i
                break
                
            # Check for package with __init__.py
            init_path = os.path.join(curr_path, "__init__.py")
            if os.path.exists(init_path):
                module_path = init_path
                index = i
            elif os.path.exists(curr_path):
                module_path = curr_path
                index = i
            else:
                break
        
        # Get the remaining module to look for
        remaining_module = module_arr[index+1] if index+1 < len(module_arr) else ""
        
        # Analyze the file and find the symbol
        try:
            analyzed = self.analyze_single_file(module_path)
            
            if remaining_module in analyzed["classes"]:
                return analyzed["classes"][remaining_module], module_path
            elif remaining_module in analyzed["functions"]:
                return analyzed["functions"][remaining_module], module_path
            elif remaining_module in analyzed["identifiers"]["variables"]:
                return analyzed["identifiers"]["variables"][remaining_module], module_path
            elif remaining_module in analyzed["imports"]:
                code = analyzed["imports"][remaining_module]["code"]
                name = analyzed["imports"][remaining_module]["name"]
                return self._resolve_import(sys_path, code, name, os.path.dirname(module_path))
            else:
                # Try to find in star imports
                for alias in analyzed["imports"]:
                    if analyzed["imports"][alias]["is_star"]:
                        code = analyzed["imports"][alias]["code"]
                        module_code = self._resolve_import(sys_path, code, remaining_module, os.path.dirname(module_path))
                        if module_code is not None:
                            return module_code
                            
                return None, None
        except Exception as e:
            print(f"Error analyzing external file: {e}")
            return None, None
        
    def extract_class_names(self, code: str) -> List[str]:
        """
        Extract class names from code using AST.
        
        Args:
            code: Code to analyze
            
        Returns:
            List of class names
        """
        class_names = set()
        
        try:
            tree = ast.parse(code)
            
            # Visit all nodes in the AST
            for node in ast.walk(tree):
                # Extract names from function/class declarations
                if isinstance(node, ast.Name):
                    class_names.add(node.id)
                    
                # Extract names from assignments
                elif isinstance(node, ast.Assign):
                    if isinstance(node.value, ast.Attribute):
                        if isinstance(node.value.value, ast.Name):
                            class_names.add(node.value.attr)
                    elif isinstance(node.value, ast.Name):
                        class_names.add(node.value.id)
                        
                    # Extract from list/tuple assignments
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        for elt in node.value.elts:
                            if isinstance(elt, ast.Name):
                                class_names.add(elt.id)
                            elif isinstance(elt, ast.Attribute):
                                class_names.add(self._extract_attribute(elt))
                
                # Extract names from attribute access
                elif isinstance(node, ast.Attribute):
                    if isinstance(node.value, ast.Name):
                        class_names.add(node.value.id + "." + node.attr)
                
                # Extract names from function calls
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                        class_names.add(node.func.value.id + "." + node.func.attr)
                    elif isinstance(node.func, ast.Name):
                        class_names.add(node.func.id)
                
                # Extract from function argument annotations
                elif isinstance(node, ast.arg):
                    if isinstance(node.annotation, ast.Name):
                        class_names.add(node.annotation.id)
                    elif isinstance(node.annotation, ast.Attribute) and isinstance(node.annotation.value, ast.Name):
                        class_names.add(node.annotation.value.id + "." + node.annotation.attr)
            
            return list(class_names)
        except SyntaxError:
            # Handle potential syntax errors in partial code snippets
            if self.debug_mode:
                print(f"Syntax error in extract_class_names with code: {code[:100]}...")
            return []
        
    def _extract_attribute(self, node):
        """
        Helper for extract_class_names to get attribute names.
        
        Args:
            node: AST attribute node
            
        Returns:
            Attribute name
        """
        if isinstance(node.value, ast.Name):
            return node.value.id + "." + node.attr
        return node.attr
    
    def extract_property_value(self, file_path: str, class_name: str, property_name: str) -> Optional[str]:
        """
        Extract property value using AST.
        
        Args:
            file_path: Path to the file
            class_name: Name of the class
            property_name: Name of the property
            
        Returns:
            Property value or None
        """
        # Skip if file not found
        if not os.path.exists(file_path):
            return None
        
        # Get class code
        class_info = self.get_symbol_info(class_name, file_path, SymbolType.CLASS)
        if not class_info:
            return None
        
        start_line = class_info.get("startLine")
        end_line = class_info.get("endLine")
        if not start_line or not end_line:
            return None
        
        code = self.get_code_snippet(file_path, start_line, end_line)
        
        try:
            # Parse the code
            tree = ast.parse(code)
            
            # Look for assignments to the property
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == property_name:
                            # Found the property, get its value
                            if isinstance(node.value, ast.Name):
                                return node.value.id
                            elif isinstance(node.value, ast.Str):
                                return node.value.s
                            elif isinstance(node.value, ast.Constant):
                                return str(node.value.value)
                            else:
                                # For other types, try using ast.unparse
                                return ast.unparse(node.value)
        except Exception as e:
            if hasattr(self, 'debug_mode') and self.debug_mode:
                print(f"Error extracting property {property_name} from {class_name}: {e}")
        
        return None
    
    def get_method_code(self, class_name: str, method_name: str, file_path: str) -> Optional[str]:
        """
        Retrieves the source code of a specific method within a class from an analyzed file.

        Args:
            class_name: The name of the class containing the method.
            method_name: The name of the method to retrieve.
            file_path: The absolute path to the file containing the class.

        Returns:
            A string containing the method's source code, or None if not found.
        """
        if not hasattr(self, 'result') or file_path not in self.result:
            # self.logger is not available here, but the caller should log.
            # print(f"DEBUG: get_method_code: Analysis result for {file_path} not found.")
            return None

        class_info = self.result[file_path].get("classes", {}).get(class_name)
        if not class_info:
            # print(f"DEBUG: get_method_code: Class '{class_name}' not found in {file_path}.")
            return None

        # The method info is nested under 'functions' inside the class info.
        method_info = class_info.get("functions", {}).get(method_name)
        if not method_info:
            # print(f"DEBUG: get_method_code: Method '{method_name}' not found in class '{class_name}'.")
            return None

        start_line = method_info.get("startLine")
        end_line = method_info.get("endLine")

        if start_line and end_line:
            # get_code_snippet is 1-indexed and inclusive, which is what we need.
            raw_snippet = self.get_code_snippet(file_path, start_line, end_line)
            if raw_snippet:
                # *** FIX: Apply dedent to remove common leading whitespace ***
                return textwrap.dedent(raw_snippet)

        # print(f"DEBUG: get_method_code: Missing line numbers for method '{method_name}'.")
        return None