import ast
import os
import re
from typing import Any, Dict, List, Optional, Set


KNOWN_POST_VIEW_SUFFIXES = {
    "ObtainJSONWebTokenView",
    "RefreshJSONWebTokenView",
    "PasswordResetView",
    "PasswordResetConfirmView",
    "PasswordChangeView",
}

KNOWN_GET_VIEW_SUFFIXES = {
    "SpectacularAPIView",
    "SpectacularSwaggerView",
}


def extract_endpoints_static(code_analyzer: Any, project_path: str, url_file: str) -> List[Dict[str, Any]]:
    analyzed = getattr(code_analyzer, "result", None)
    if not analyzed:
        raise RuntimeError("Static Django endpoint extraction requires loaded Python analysis results.")

    endpoints: List[Dict[str, Any]] = []
    parser = _UrlPatternsParser(
        analyzed=analyzed,
        base_url="/",
        endpoints=endpoints,
        path=os.path.abspath(url_file),
        project_path=os.path.abspath(project_path),
        variable_name="urlpatterns",
    )
    parser.get_endpoints()
    return endpoints


def _ensure_module_path_exists(path: str) -> Optional[str]:
    package_init = os.path.join(path, "__init__.py")
    if os.path.exists(package_init):
        return package_init

    module_path = path + ".py"
    if os.path.exists(module_path):
        return module_path

    return None


def _remove_quotes(value: str) -> str:
    if value and value[0] in {"'", '"'}:
        value = value[1:]
    if value and value[-1] in {"'", '"'}:
        value = value[:-1]
    return value


def _get_top_level_statements(code: str) -> List[str]:
    tree = ast.parse(code)
    statements = []
    for statement in tree.body:
        if isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        statements.append(ast.unparse(statement))
    return statements


def _get_function_arguments(stmt: str) -> List[str]:
    tree = ast.parse(stmt.strip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            return [ast.unparse(arg) for arg in node.args]
    return []


def _split_top_level_args(stmt: str) -> List[str]:
    opening = {"<", "{", "[", "("}
    closing = {">", "}", "]", ")"}
    current = ""
    parts = []
    depth = 0

    for char in stmt:
        if char == "," and depth == 0:
            parts.append(current)
            current = ""
            continue
        if char in opening:
            depth += 1
        elif char in closing:
            depth -= 1
        current += char

    if current:
        parts.append(current)
    return parts


def _convert_regex_to_url(regex: str) -> str:
    result = ""
    group_depth = 0
    in_name = False

    for char in regex:
        if char in {"^", "$"}:
            continue
        if char == "(":
            group_depth += 1
            continue
        if char == ")":
            group_depth -= 1
            continue
        if group_depth:
            if char == "<":
                in_name = True
                result += "{"
            elif char == ">":
                in_name = False
                result += "}"
            elif in_name:
                result += char
            continue
        result += char

    return result


def _split_forward_slash(url: str) -> List[str]:
    current = ""
    arrow = curved = curly = square = 0
    result = []

    for char in url:
        if char == "<":
            arrow += 1
        elif char == ">":
            arrow -= 1
        elif char == "{":
            curly += 1
        elif char == "}":
            curly -= 1
        elif char == "(":
            curved += 1
        elif char == ")":
            curved -= 1
        elif char == "[":
            square += 1
        elif char == "]":
            square -= 1

        if char == "/" and arrow == curly == curved == square == 0:
            if current:
                result.append(current)
            current = ""
            continue
        current += char

    if current:
        result.append(current)
    return result


def _parse_url(url: str) -> Dict[str, Any]:
    parts = _split_forward_slash(url)
    final_parts = []
    parameters = []

    for part in parts:
        if not part:
            continue

        name = None
        if "(?P" in part:
            name = part[part.find("<") + 1: part.find(">")] if "<" in part else None
            pattern = part[part.find(">") + 1: -1]
            parameters.append({"name": name, "pattern": pattern, "type": None})
        elif ":" in part and part.startswith("<") and part.endswith(">"):
            type_name = part[1:part.find(":")]
            name = part[part.find(":") + 1:-1]
            parameters.append({"name": name, "pattern": None, "type": type_name})
        elif part.startswith("{") and part.endswith("}"):
            name = part[1:-1]
            parameters.append({"name": name, "pattern": None, "type": None})

        if name is not None:
            part = "{" + name + "}"

        final_parts.append(part.replace("<", "{").replace(">", "}"))

    final_url = "/" + "/".join(final_parts).lstrip("/")
    final_url = final_url.replace("^", "").replace("$", "").replace("?", "").replace("*", "")
    if final_url and final_url[-1] not in {"/", "."}:
        final_url += "/"

    path_parameter_re = re.compile(r"<(?:(?P<converter>[^>:]+):)?(?P<parameter>\w+)>")
    return {
        "url": re.sub(path_parameter_re, r"{\g<parameter>}", final_url),
        "parameter": parameters,
    }


def _clean_property_string(value: Optional[str], default: str) -> str:
    if not value:
        return default
    value = value.strip()
    if value and value[0] in {"'", '"'} and value[-1] == value[0]:
        return value[1:-1]
    return value


def _infer_known_view_methods(view_name: str, parent_names: Set[str]) -> List[str]:
    candidate_names = {view_name}
    for parent_name in parent_names:
        candidate_names.add(parent_name.split(".")[-1])

    for candidate_name in candidate_names:
        if any(candidate_name.endswith(suffix) for suffix in KNOWN_POST_VIEW_SUFFIXES):
            return ["POST"]
        if any(candidate_name.endswith(suffix) for suffix in KNOWN_GET_VIEW_SUFFIXES):
            return ["GET"]
    return []


class _RouterParser:
    def __init__(self, analyzed: Dict[str, Any], base_url: str, endpoints: List[Dict[str, Any]], path: str, project_path: str, router_name: str):
        self.analyzed = analyzed
        self.base_url = base_url
        self.endpoints = endpoints
        self.path = path
        self.project_path = project_path
        self.router_name = router_name
        self.patterns = [
            {
                "pattern": re.compile(rf"^{router_name}\.register\((.*?)\)(?:#|$)", re.DOTALL),
                "handler": self.register_parser,
            },
            {
                "pattern": re.compile(rf"^\s*(\w+)={router_name}\.register\((.*?)\)", re.DOTALL),
                "handler": self.nested_register_parser,
            },
        ]

    def register_parser(self, stmt: str) -> str:
        args = _get_function_arguments(f"register({stmt})")
        if len(args) < 2:
            return self.base_url

        url = _remove_quotes(args[0])
        if url and not url.endswith("/"):
            url += "/"

        view = args[1]
        class_identifiers = self.analyzed[self.path]["identifiers"]["classes"]
        if view not in class_identifiers:
            return self.base_url + url

        class_info = class_identifiers[view]
        view_path = class_info["path"]
        view_name = class_info["name"]
        lookup_field = _get_lookup_field(self.analyzed, view_path, view_name)
        new_url = self.base_url + url
        _add_viewset(self.analyzed, self.endpoints, view_path, view_name, new_url, lookup_field)
        return new_url

    def nested_register_parser(self, match: Any) -> None:
        router_name, register_stmt = match
        new_url = self.register_parser(register_stmt)
        variable_identifiers = self.analyzed[self.path]["identifiers"]["variables"]
        if router_name not in variable_identifiers:
            return

        router_path = variable_identifiers[router_name]["path"]
        _RouterParser(self.analyzed, new_url, self.endpoints, router_path, self.project_path, router_name).get_endpoints()

    def get_endpoints(self) -> None:
        with open(self.path, "r", encoding="utf-8") as handle:
            code = handle.read()

        for statement in _get_top_level_statements(code):
            compact_statement = statement.replace(" ", "").replace("\n", "")
            for pattern_entry in self.patterns:
                matches = re.findall(pattern_entry["pattern"], compact_statement)
                if not matches:
                    continue
                pattern_entry["handler"](matches[0])
                break


class _UrlPatternsParser:
    def __init__(self, analyzed: Dict[str, Any], base_url: str, endpoints: List[Dict[str, Any]], path: str, project_path: str, variable_name: str = "urlpatterns"):
        self.analyzed = analyzed
        self.base_url = base_url
        self.endpoints = endpoints
        self.path = path
        self.project_path = project_path
        self.patterns = [
            {
                "pattern": re.compile(rf"^{variable_name}\s*=\s*\[(.*?)\](?:#|$)", re.DOTALL),
                "handler": self.equal_or_plus_parser,
            },
            {
                "pattern": re.compile(rf"^{variable_name}\s*\+\s*=\s*\[(.*?)\](?:#|$)", re.DOTALL),
                "handler": self.equal_or_plus_parser,
            },
            {
                "pattern": re.compile(rf"^{variable_name}\.append\(\s*(.*?)\s*\)(?:#|$)", re.DOTALL),
                "handler": self.append_parser,
            },
            {
                "pattern": re.compile(rf"^{variable_name}\.extend\(\s*(.*?)\s*\)(?:#|$)", re.DOTALL),
                "handler": self.extend_parser,
            },
            {
                "pattern": re.compile(rf"^{variable_name}\s*=\s*(.*?)(?:#|$)", re.DOTALL),
                "handler": self.equal_no_array_parser,
            },
        ]

    def include_parser(self, stmt: str, url: str) -> None:
        args = _get_function_arguments(stmt)
        if not args:
            return

        view = args[0]
        if view and view[0] in {"(", "{", "["}:
            nested = _split_top_level_args(view[1:-1])
            if not nested:
                return
            view = nested[0]

        if view and view[0] in {"'", '"'}:
            resolved = _ensure_module_path_exists(os.path.join(self.project_path, view[1:-1].replace(".", "/")))
            if not resolved:
                return
            _UrlPatternsParser(
                self.analyzed,
                self.base_url + url,
                self.endpoints,
                resolved,
                self.project_path,
            ).get_endpoints()
            return

        identifiers = self.analyzed[self.path]["identifiers"]
        if view in identifiers["variables"]:
            resolved = identifiers["variables"][view]["path"]
            _UrlPatternsParser(
                self.analyzed,
                self.base_url + url,
                self.endpoints,
                resolved,
                self.project_path,
                view,
            ).get_endpoints()
            return

        if view in identifiers["file_identifiers"]:
            resolved = identifiers["file_identifiers"][view]["path"]
            _UrlPatternsParser(
                self.analyzed,
                self.base_url + url,
                self.endpoints,
                resolved,
                self.project_path,
            ).get_endpoints()
            return

        if view.endswith(".urls"):
            router_name = view[:-5]
            if router_name in identifiers["variables"]:
                router_path = identifiers["variables"][router_name]["path"]
                _RouterParser(
                    self.analyzed,
                    self.base_url + url,
                    self.endpoints,
                    router_path,
                    self.project_path,
                    router_name,
                ).get_endpoints()

    def repath_parser(self, stmt: str) -> None:
        args = _get_function_arguments(stmt)
        if len(args) < 2:
            return

        url = _convert_regex_to_url(_remove_quotes(args[0]))
        view = _remove_quotes(args[1])
        self._handle_path_view(url, view)

    def path_parser(self, stmt: str) -> None:
        args = _get_function_arguments(stmt)
        if len(args) < 2:
            return

        url = _remove_quotes(args[0])
        view = args[1]
        self._handle_path_view(url, view)

    def _handle_path_view(self, url: str, view: str) -> None:
        if view.startswith("include"):
            self.include_parser(view, url)
            return

        if ".as_view(" in view:
            view_name = view[:view.find(".as_view")]
            class_identifiers = self.analyzed[self.path]["identifiers"]["classes"]
            class_path = None
            if view_name in class_identifiers:
                class_path = class_identifiers[view_name]["path"]
                resolved_name = class_identifiers[view_name]["name"]
            else:
                resolved_name = view_name
            _add_as_view_endpoints(self.analyzed, self.endpoints, class_path, resolved_name, self.base_url + url)
            return

        if "," in view:
            nested = _split_top_level_args(view)
            if nested:
                view = nested[0]

        function_identifiers = self.analyzed[self.path]["identifiers"]["functions"]
        if view not in function_identifiers:
            return

        function_path = function_identifiers[view]["path"]
        function_name = function_identifiers[view]["name"]
        decorators = self.analyzed[function_path]["functions"][function_name]["decorators"]

        methods = ["GET"]
        for decorator in decorators:
            if decorator.startswith("api_view"):
                methods = [method.upper() for method in ast.literal_eval(decorator[9:-1])]

        for method in methods:
            self.endpoints.append(
                {
                    "url": _parse_url(self.base_url + url),
                    "view": view,
                    "is_viewset": False,
                    "path": function_path,
                    "method": method,
                }
            )

    def equal_or_plus_parser(self, stmt: str) -> None:
        for path_stmt in _extract_path_calls(stmt):
            if path_stmt.startswith("re_path"):
                self.repath_parser(path_stmt)
            else:
                self.path_parser(path_stmt)

    def append_parser(self, stmt: str) -> None:
        if stmt.startswith("re_path"):
            self.repath_parser(stmt)
        elif stmt.startswith("path"):
            self.path_parser(stmt)

    def extend_parser(self, stmt: str) -> None:
        value = stmt.strip()
        if value.startswith("[") and value.endswith("]"):
            self.equal_or_plus_parser(value[1:-1])
            return
        self.equal_no_array_parser(value)

    def equal_no_array_parser(self, stmt: str) -> None:
        stmt = stmt.strip()
        variable_identifiers = self.analyzed[self.path]["identifiers"]["variables"]

        if stmt.endswith(".urls"):
            router_name = stmt[:-5]
            if router_name in variable_identifiers:
                router_path = variable_identifiers[router_name]["path"]
                _RouterParser(self.analyzed, self.base_url, self.endpoints, router_path, self.project_path, router_name).get_endpoints()

        if stmt in variable_identifiers:
            nested_path = variable_identifiers[stmt]["path"]
            _UrlPatternsParser(
                self.analyzed,
                self.base_url,
                self.endpoints,
                nested_path,
                self.project_path,
                stmt,
            ).get_endpoints()

    def get_endpoints(self) -> None:
        with open(self.path, "r", encoding="utf-8") as handle:
            code = handle.read()

        for statement in _get_top_level_statements(code):
            for pattern_entry in self.patterns:
                matches = re.findall(pattern_entry["pattern"], statement.strip())
                if not matches:
                    continue
                pattern_entry["handler"](matches[0])
                break


def _extract_path_calls(stmt: str) -> List[str]:
    bracket_depth = 0
    current = ""
    results = []

    for char in stmt:
        current += char
        if char == "(":
            bracket_depth += 1
        elif char == ")":
            bracket_depth -= 1
            if bracket_depth == 0:
                current = current[1:] if current.startswith(",") else current
                if current:
                    results.append(current)
                current = ""

    current = current[1:] if current.startswith(",") else current
    if current:
        results.append(current)
    return results


def _get_lookup_field(analyzed: Dict[str, Any], path: Optional[str], view_name: str) -> str:
    if not path or path not in analyzed or view_name not in analyzed[path]["classes"]:
        return "pk"

    property_assignments = analyzed[path]["classes"][view_name].get("property_assignments", {})
    lookup_value = property_assignments.get("lookup_field")
    return _clean_property_string(lookup_value, "pk")


def _is_viewset(path: Optional[str], view_name: str, analyzed: Dict[str, Any], visited: Set[str]) -> bool:
    if not path or path not in analyzed or view_name in visited or view_name not in analyzed[path]["classes"]:
        return False

    visited.add(view_name)
    parent_classes = analyzed[path]["classes"][view_name]["parentClasses"]
    for parent_name, parent_info in parent_classes.items():
        if "ViewSet" in parent_name or "ModelViewSet" in parent_name or "ReadOnlyModelViewSet" in parent_name:
            return True
        if _is_viewset(parent_info.get("path"), parent_name, analyzed, visited):
            return True
    return False


def _collect_viewset_mixins(path: Optional[str], view_name: str, analyzed: Dict[str, Any], mixins: Set[str], visited: Set[str]) -> None:
    if not path or path not in analyzed or view_name in visited or view_name not in analyzed[path]["classes"]:
        return

    visited.add(view_name)
    parent_classes = analyzed[path]["classes"][view_name]["parentClasses"]
    for parent_name, parent_info in parent_classes.items():
        if "CreateModelMixin" in parent_name:
            mixins.add("create")
        if "ListModelMixin" in parent_name:
            mixins.add("list")
        if "RetrieveModelMixin" in parent_name:
            mixins.add("retrieve")
        if "UpdateModelMixin" in parent_name:
            mixins.add("update")
        if "DestroyModelMixin" in parent_name:
            mixins.add("destroy")
        if "ReadOnlyModelViewSet" in parent_name:
            mixins.update({"retrieve", "list"})
        if "ModelViewSet" in parent_name and "ReadOnlyModelViewSet" not in parent_name:
            mixins.update({"create", "list", "retrieve", "update", "destroy"})
        _collect_viewset_mixins(parent_info.get("path"), parent_name, analyzed, mixins, visited)


def _add_viewset(analyzed: Dict[str, Any], endpoints: List[Dict[str, Any]], path: Optional[str], view_name: str, url: str, lookup_field: str) -> None:
    if not path:
        return

    mixins: Set[str] = set()
    _collect_viewset_mixins(path, view_name, analyzed, mixins, set())

    if "create" in mixins:
        endpoints.append(
            {
                "url": _parse_url(url),
                "view": view_name,
                "is_viewset": True,
                "path": path,
                "method": "POST",
                "function": "create",
            }
        )
    if "list" in mixins:
        endpoints.append(
            {
                "url": _parse_url(url),
                "view": view_name,
                "is_viewset": True,
                "path": path,
                "method": "GET",
                "function": "list",
            }
        )
    detail_url = url + "{" + lookup_field + "}/"
    if "retrieve" in mixins:
        endpoints.append(
            {
                "url": _parse_url(detail_url),
                "view": view_name,
                "is_viewset": True,
                "path": path,
                "method": "GET",
                "function": "retrieve",
            }
        )
    if "update" in mixins:
        endpoints.append(
            {
                "url": _parse_url(detail_url),
                "view": view_name,
                "is_viewset": True,
                "path": path,
                "method": "PUT",
                "function": "update",
            }
        )
        endpoints.append(
            {
                "url": _parse_url(detail_url),
                "view": view_name,
                "is_viewset": True,
                "path": path,
                "method": "PATCH",
                "function": "partial_update",
            }
        )
    if "destroy" in mixins:
        endpoints.append(
            {
                "url": _parse_url(detail_url),
                "view": view_name,
                "is_viewset": True,
                "path": path,
                "method": "DELETE",
                "function": "destroy",
            }
        )

    if path not in analyzed or view_name not in analyzed[path]["classes"]:
        return

    methods = analyzed[path]["classes"][view_name]["functions"]
    action_pattern = r"action\((.*)\)"
    arg_splitter = re.compile(r",(?![^\[]*[\]])")
    keys = ["detail", "methods", "url_path"]

    for method_name, method_info in methods.items():
        for decorator in method_info["decorators"]:
            matches = re.findall(action_pattern, decorator)
            if not matches:
                continue

            action_args = re.split(arg_splitter, matches[0])
            action_info: Dict[str, Any] = {}
            for index, action_arg in enumerate(action_args):
                action_arg = action_arg.strip().replace(" ", "")
                if "=" in action_arg:
                    key, raw_value = action_arg.split("=", 1)
                    if key not in keys:
                        continue
                    action_info[key] = _remove_quotes(raw_value) if raw_value.startswith(("'", '"')) else raw_value
                elif index < len(keys):
                    action_info[keys[index]] = action_arg

            methods_value = action_info.get("methods", "get")
            if methods_value.startswith("["):
                action_methods = [method.strip().strip("'\"").upper() for method in methods_value[1:-1].split(",") if method.strip()]
            else:
                action_methods = [methods_value.strip().strip("'\"").upper()]

            detail = action_info.get("detail", "False")
            url_value = action_info.get("url_path", method_name)
            route_url = url + "{" + lookup_field + "}/" + url_value + "/" if detail == "True" else url + url_value + "/"

            for http_method in action_methods:
                endpoints.append(
                    {
                        "url": _parse_url(route_url),
                        "view": view_name,
                        "is_viewset": True,
                        "path": path,
                        "method": http_method,
                        "function": method_name,
                    }
                )


def _collect_as_view_mixins(path: Optional[str], view_name: str, analyzed: Dict[str, Any], mixins: Set[str], parent_names: Set[str], visited: Set[str]) -> None:
    if not path or path not in analyzed or view_name in visited or view_name not in analyzed[path]["classes"]:
        return

    visited.add(view_name)
    class_info = analyzed[path]["classes"][view_name]
    parent_classes = class_info["parentClasses"]

    for parent_name, parent_info in parent_classes.items():
        parent_names.add(parent_name)
        if "CreateAPIView" in parent_name:
            mixins.add("create")
        if "ListAPIView" in parent_name:
            mixins.add("list")
        if "RetrieveAPIView" in parent_name:
            mixins.add("retrieve")
        if "UpdateAPIView" in parent_name:
            mixins.add("update")
        if "DestroyAPIView" in parent_name:
            mixins.add("destroy")
        if "GenericAPIView" in parent_name or "APIView" in parent_name:
            function_names = set(class_info["functions"].keys())
            if "get" in function_names:
                mixins.add("list")
            if "patch" in function_names:
                mixins.add("update")
            if "post" in function_names:
                mixins.add("create")
            if "put" in function_names:
                mixins.add("update_put")
            if "delete" in function_names:
                mixins.add("destroy")
        if "RedirectView" in parent_name:
            mixins.add("list")
        _collect_as_view_mixins(parent_info.get("path"), parent_name, analyzed, mixins, parent_names, visited)


def _add_as_view_endpoints(analyzed: Dict[str, Any], endpoints: List[Dict[str, Any]], path: Optional[str], view_name: str, url: str) -> None:
    mixins: Set[str] = set()
    parent_names: Set[str] = set()
    _collect_as_view_mixins(path, view_name, analyzed, mixins, parent_names, set())

    if not mixins:
        known_methods = _infer_known_view_methods(view_name, parent_names)
        if known_methods:
            for method in known_methods:
                endpoints.append(
                    {
                        "url": _parse_url(url),
                        "view": view_name.split(".")[-1],
                        "is_viewset": False,
                        "path": path,
                        "method": method,
                    }
                )
        return

    normalized_view_name = view_name.split(".")[-1]
    if "create" in mixins:
        endpoints.append(
            {
                "url": _parse_url(url),
                "view": normalized_view_name,
                "is_viewset": False,
                "path": path,
                "method": "POST",
            }
        )
    if "list" in mixins or "retrieve" in mixins:
        endpoints.append(
            {
                "url": _parse_url(url),
                "view": normalized_view_name,
                "is_viewset": False,
                "path": path,
                "method": "GET",
            }
        )
    if "update_put" in mixins:
        endpoints.append(
            {
                "url": _parse_url(url),
                "view": normalized_view_name,
                "is_viewset": False,
                "path": path,
                "method": "PUT",
            }
        )
    if "update" in mixins:
        endpoints.append(
            {
                "url": _parse_url(url),
                "view": normalized_view_name,
                "is_viewset": False,
                "path": path,
                "method": "PATCH",
            }
        )
    if "destroy" in mixins:
        endpoints.append(
            {
                "url": _parse_url(url),
                "view": normalized_view_name,
                "is_viewset": False,
                "path": path,
                "method": "DELETE",
            }
        )
