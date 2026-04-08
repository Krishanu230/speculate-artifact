import ast
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple
KNOWN_POST_VIEW_SUFFIXES = {"ObtainJSONWebTokenView", "RefreshJSONWebTokenView", "PasswordResetView", "PasswordResetConfirmView", "PasswordChangeView"}
KNOWN_GET_VIEW_SUFFIXES = {"SpectacularAPIView", "SpectacularSwaggerView"}
VIEWSET_MIXINS = {"CreateModelMixin": "create", "ListModelMixin": "list", "RetrieveModelMixin": "retrieve", "UpdateModelMixin": "update", "DestroyModelMixin": "destroy"}
GENERIC_VIEW_MARKERS = {"CreateAPIView": "create", "ListAPIView": "get", "RetrieveAPIView": "get", "UpdateAPIView": "patch", "DestroyAPIView": "delete", "RedirectView": "get"}
GENERIC_VIEW_METHODS = {"get": "get", "post": "create", "patch": "patch", "put": "put", "delete": "delete"}
def extract_endpoints_static(code_analyzer: Any, project_path: str, url_file: str) -> List[Dict[str, Any]]:
    analyzed = getattr(code_analyzer, "result", None)
    if not analyzed:
        raise RuntimeError("Static Django endpoint extraction requires loaded Python analysis results.")
    return _StaticEndpointParser(analyzed, os.path.abspath(project_path)).parse(os.path.abspath(url_file))

def _existing_module_path(path: str) -> Optional[str]:
    package_init = os.path.join(path, "__init__.py")
    if os.path.exists(package_init):
        return package_init
    module_path = path + ".py"
    return module_path if os.path.exists(module_path) else None
def _strip_quotes(value: str) -> str:
    if value[:1] in {"'", '"'}:
        value = value[1:]
    if value[-1:] in {"'", '"'}:
        value = value[:-1]
    return value
def _value_text(node: ast.AST) -> str:
    return ast.unparse(node).strip()
def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return _value_text(node)
def _top_level_nodes(path: str) -> List[ast.stmt]:
    with open(path, "r", encoding="utf-8") as handle:
        return ast.parse(handle.read()).body

def _parse_literal(expression: str, default: Any) -> Any:
    try:
        return ast.literal_eval(expression)
    except (SyntaxError, ValueError):
        return default

def _split_forward_slash(url: str) -> List[str]:
    current = ""
    angle = curly = curved = square = 0
    parts = []
    for char in url:
        if char == "<":
            angle += 1
        elif char == ">":
            angle -= 1
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
        if char == "/" and angle == curly == curved == square == 0:
            if current:
                parts.append(current)
            current = ""
            continue
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

def _parse_url(url: str) -> Dict[str, Any]:
    parameters = []
    final_parts = []
    for part in _split_forward_slash(url):
        if not part:
            continue
        name = None
        if "(?P" in part:
            name = part[part.find("<") + 1: part.find(">")] if "<" in part else None
            parameters.append({"name": name, "pattern": part[part.find(">") + 1: -1], "type": None})
        elif ":" in part and part.startswith("<") and part.endswith(">"):
            parameters.append(
                {
                    "name": part[part.find(":") + 1:-1],
                    "pattern": None,
                    "type": part[1:part.find(":")],
                }
            )
            name = parameters[-1]["name"]
        elif part.startswith("{") and part.endswith("}"):
            name = part[1:-1]
            parameters.append({"name": name, "pattern": None, "type": None})
        final_parts.append(("{" + name + "}" if name else part).replace("<", "{").replace(">", "}"))
    normalized = "/" + "/".join(final_parts).lstrip("/")
    normalized = normalized.replace("^", "").replace("$", "").replace("?", "").replace("*", "")
    if normalized and normalized[-1] not in {"/", "."}:
        normalized += "/"
    path_parameter_re = re.compile(r"<(?:(?P<converter>[^>:]+):)?(?P<parameter>\w+)>")
    return {
        "url": re.sub(path_parameter_re, r"{\g<parameter>}", normalized),
        "parameter": parameters,
    }

def _clean_property(value: Optional[str], default: str) -> str:
    if not value:
        return default
    value = value.strip()
    return value[1:-1] if value[:1] in {"'", '"'} and value[-1:] == value[:1] else value

def _endpoint(
    url: str,
    view: str,
    path: Optional[str],
    method: str,
    *,
    is_viewset: bool = False,
    function: Optional[str] = None,
) -> Dict[str, Any]:
    endpoint = {
        "url": _parse_url(url),
        "view": view,
        "is_viewset": is_viewset,
        "path": path,
        "method": method,
    }
    if function:
        endpoint["function"] = function
    return endpoint

def _lookup_field(analyzed: Dict[str, Any], path: Optional[str], view_name: str) -> str:
    if not path or path not in analyzed or view_name not in analyzed[path]["classes"]:
        return "pk"
    assignments = analyzed[path]["classes"][view_name].get("property_assignments", {})
    return _clean_property(assignments.get("lookup_field"), "pk")

def _collect_viewset_mixins(
    analyzed: Dict[str, Any],
    path: Optional[str],
    view_name: str,
    mixins: Set[str],
    visited: Set[Tuple[Optional[str], str]],
) -> None:
    key = (path, view_name)
    if not path or path not in analyzed or key in visited or view_name not in analyzed[path]["classes"]:
        return
    visited.add(key)
    for parent_name, parent_info in analyzed[path]["classes"][view_name]["parentClasses"].items():
        for marker, mixin in VIEWSET_MIXINS.items():
            if marker in parent_name:
                mixins.add(mixin)
        if "ReadOnlyModelViewSet" in parent_name:
            mixins.update({"list", "retrieve"})
        elif "ModelViewSet" in parent_name:
            mixins.update({"create", "list", "retrieve", "update", "destroy"})
        _collect_viewset_mixins(analyzed, parent_info.get("path"), parent_name, mixins, visited)

def _parse_action_decorator(decorator: str) -> Optional[Dict[str, str]]:
    try:
        node = ast.parse(decorator, mode="eval").body
    except SyntaxError:
        return None
    if not isinstance(node, ast.Call) or _call_name(node.func).split(".")[-1] != "action":
        return None
    info = {}
    for key, arg in zip(("detail", "methods", "url_path"), node.args):
        info[key] = _value_text(arg)
    for keyword in node.keywords:
        if keyword.arg in {"detail", "methods", "url_path"}:
            info[keyword.arg] = _value_text(keyword.value)
    return info

def _action_methods(raw_methods: str) -> List[str]:
    parsed = _parse_literal(raw_methods, None)
    if isinstance(parsed, (list, tuple, set)):
        return [str(method).upper() for method in parsed]
    if parsed is not None:
        return [str(parsed).upper()]
    return [_strip_quotes(raw_methods).upper()]

def _viewset_endpoints(
    analyzed: Dict[str, Any],
    path: Optional[str],
    view_name: str,
    url: str,
    lookup_field: str,
) -> List[Dict[str, Any]]:
    if not path:
        return []
    mixins: Set[str] = set()
    _collect_viewset_mixins(analyzed, path, view_name, mixins, set())
    detail_url = f"{url}{{{lookup_field}}}/"
    endpoints = []
    for required, method, route_url, function in (
        ("create", "POST", url, "create"),
        ("list", "GET", url, "list"),
        ("retrieve", "GET", detail_url, "retrieve"),
        ("destroy", "DELETE", detail_url, "destroy"),
    ):
        if required in mixins:
            endpoints.append(_endpoint(route_url, view_name, path, method, is_viewset=True, function=function))
    if "update" in mixins:
        endpoints.extend(
            [
                _endpoint(detail_url, view_name, path, "PUT", is_viewset=True, function="update"),
                _endpoint(detail_url, view_name, path, "PATCH", is_viewset=True, function="partial_update"),
            ]
        )
    if path not in analyzed or view_name not in analyzed[path]["classes"]:
        return endpoints
    methods = analyzed[path]["classes"][view_name]["functions"]
    for method_name, method_info in methods.items():
        for decorator in method_info["decorators"]:
            action = _parse_action_decorator(decorator)
            if not action:
                continue
            route_tail = _strip_quotes(action.get("url_path", method_name))
            route_url = f"{detail_url}{route_tail}/" if str(_parse_literal(action.get("detail", "False"), "False")) == "True" else f"{url}{route_tail}/"
            for http_method in _action_methods(action.get("methods", "'get'")):
                endpoints.append(
                    _endpoint(route_url, view_name, path, http_method, is_viewset=True, function=method_name)
                )
    return endpoints
def _collect_class_view_labels(
    analyzed: Dict[str, Any],
    path: Optional[str],
    view_name: str,
    labels: Set[str],
    parent_names: Set[str],
    visited: Set[Tuple[Optional[str], str]],
) -> None:
    key = (path, view_name)
    if not path or path not in analyzed or key in visited or view_name not in analyzed[path]["classes"]:
        return
    visited.add(key)
    class_info = analyzed[path]["classes"][view_name]
    function_names = set(class_info["functions"])
    for parent_name, parent_info in class_info["parentClasses"].items():
        parent_names.add(parent_name)
        for marker, label in GENERIC_VIEW_MARKERS.items():
            if marker in parent_name:
                labels.add(label)
        if "GenericAPIView" in parent_name or "APIView" in parent_name:
            for function_name, label in GENERIC_VIEW_METHODS.items():
                if function_name in function_names:
                    labels.add(label)
        _collect_class_view_labels(analyzed, parent_info.get("path"), parent_name, labels, parent_names, visited)

def _infer_known_view_methods(view_name: str, parent_names: Set[str]) -> List[str]:
    candidates = {view_name, *(parent_name.split(".")[-1] for parent_name in parent_names)}
    for candidate in candidates:
        if any(candidate.endswith(suffix) for suffix in KNOWN_POST_VIEW_SUFFIXES):
            return ["POST"]
        if any(candidate.endswith(suffix) for suffix in KNOWN_GET_VIEW_SUFFIXES):
            return ["GET"]
    return []
def _class_view_endpoints(
    analyzed: Dict[str, Any],
    path: Optional[str],
    view_name: str,
    url: str,
) -> List[Dict[str, Any]]:
    labels: Set[str] = set()
    parent_names: Set[str] = set()
    _collect_class_view_labels(analyzed, path, view_name, labels, parent_names, set())
    normalized_view_name = view_name.split(".")[-1]
    if not labels:
        return [_endpoint(url, normalized_view_name, path, method) for method in _infer_known_view_methods(view_name, parent_names)]
    endpoints = []
    for label, method in (("create", "POST"), ("get", "GET"), ("put", "PUT"), ("patch", "PATCH"), ("delete", "DELETE")):
        if label in labels:
            endpoints.append(_endpoint(url, normalized_view_name, path, method))
    return endpoints
class _StaticEndpointParser:
    def __init__(self, analyzed: Dict[str, Any], project_path: str):
        self.analyzed = analyzed
        self.project_path = project_path
        self.endpoints: List[Dict[str, Any]] = []

    def parse(self, url_file: str) -> List[Dict[str, Any]]:
        self._parse_urlpatterns(url_file, "/", "urlpatterns")
        return self.endpoints
    def _parse_urlpatterns(self, path: str, base_url: str, variable_name: str) -> None:
        for node in _top_level_nodes(path):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == variable_name:
                        self._consume_urlpattern_value(path, base_url, node.value)
            elif (
                isinstance(node, ast.AugAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == variable_name
                and isinstance(node.op, ast.Add)
            ):
                self._consume_urlpattern_value(path, base_url, node.value)
            elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
                self._handle_urlpattern_call(path, base_url, variable_name, node.value)
    def _handle_urlpattern_call(self, path: str, base_url: str, variable_name: str, call: ast.Call) -> None:
        if not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name):
            return
        if call.func.value.id != variable_name or not call.args:
            return
        if call.func.attr == "append":
            self._consume_route(path, base_url, call.args[0])
        elif call.func.attr == "extend":
            self._consume_urlpattern_value(path, base_url, call.args[0])
    def _consume_urlpattern_value(self, path: str, base_url: str, value: ast.AST) -> None:
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            for item in value.elts:
                self._consume_route(path, base_url, item)
            return
        if isinstance(value, ast.Call):
            self._consume_route(path, base_url, value)
            return
        value_text = _value_text(value)
        if value_text.endswith(".urls"):
            self._parse_router_from_name(path, base_url, value_text[:-5])
        if isinstance(value, ast.Name):
            variables = self.analyzed[path]["identifiers"]["variables"]
            if value.id in variables:
                self._parse_urlpatterns(variables[value.id]["path"], base_url, value.id)
    def _consume_route(self, path: str, base_url: str, node: ast.AST) -> None:
        if not isinstance(node, ast.Call):
            return
        route_type = _call_name(node.func).split(".")[-1]
        if route_type not in {"path", "re_path"} or len(node.args) < 2:
            return
        url = _strip_quotes(_value_text(node.args[0]))
        route_url = base_url + (_convert_regex_to_url(url) if route_type == "re_path" else url)
        self._handle_view(path, route_url, node.args[1])
    def _handle_view(self, path: str, route_url: str, view_node: ast.AST) -> None:
        if isinstance(view_node, ast.Call) and _call_name(view_node.func).split(".")[-1] == "include":
            self._handle_include(path, route_url, view_node)
            return
        view_name = _value_text(view_node)
        if ".as_view(" in view_name:
            base_name = view_name.split(".as_view(", 1)[0]
            class_info = self.analyzed[path]["identifiers"]["classes"].get(base_name)
            class_path = class_info["path"] if class_info else None
            resolved_name = class_info["name"] if class_info else base_name
            self.endpoints.extend(_class_view_endpoints(self.analyzed, class_path, resolved_name, route_url))
            return
        functions = self.analyzed[path]["identifiers"]["functions"]
        if view_name not in functions:
            return
        function_path = functions[view_name]["path"]
        function_name = functions[view_name]["name"]
        methods = ["GET"]
        decorators = self.analyzed[function_path]["functions"][function_name]["decorators"]
        for decorator in decorators:
            if decorator.startswith("api_view"):
                methods = [str(method).upper() for method in _parse_literal(decorator[9:-1], ["GET"])]
        for method in methods:
            self.endpoints.append(_endpoint(route_url, view_name, function_path, method))
    def _handle_include(self, path: str, route_url: str, call: ast.Call) -> None:
        if not call.args:
            return
        target = call.args[0]
        if isinstance(target, (ast.Tuple, ast.List, ast.Set)) and target.elts:
            target = target.elts[0]
        identifiers = self.analyzed[path]["identifiers"]
        if isinstance(target, ast.Constant) and isinstance(target.value, str):
            resolved = _existing_module_path(os.path.join(self.project_path, target.value.replace(".", "/")))
            if resolved:
                self._parse_urlpatterns(resolved, route_url, "urlpatterns")
            return
        if isinstance(target, ast.Name):
            if target.id in identifiers["variables"]:
                self._parse_urlpatterns(identifiers["variables"][target.id]["path"], route_url, target.id)
                return
            if target.id in identifiers["file_identifiers"]:
                self._parse_urlpatterns(identifiers["file_identifiers"][target.id]["path"], route_url, "urlpatterns")
                return
        target_name = _value_text(target)
        if target_name.endswith(".urls"):
            self._parse_router_from_name(path, route_url, target_name[:-5])
    def _parse_router_from_name(self, path: str, base_url: str, router_name: str) -> None:
        variables = self.analyzed[path]["identifiers"]["variables"]
        if router_name in variables:
            self._parse_router(variables[router_name]["path"], base_url, router_name)
    def _parse_router(self, path: str, base_url: str, router_name: str) -> None:
        for node in _top_level_nodes(path):
            alias, call = self._router_register_call(node, router_name)
            if not call:
                continue
            next_base_url = self._register_viewset(path, base_url, call)
            if alias:
                variables = self.analyzed[path]["identifiers"]["variables"]
                if alias in variables:
                    self._parse_router(variables[alias]["path"], next_base_url, alias)
    def _router_register_call(self, node: ast.stmt, router_name: str) -> Tuple[Optional[str], Optional[ast.Call]]:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            return (None, node.value) if _call_name(node.value.func) == f"{router_name}.register" else (None, None)
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and _call_name(node.value.func) == f"{router_name}.register"
        ):
            return node.targets[0].id, node.value
        return None, None
    def _register_viewset(self, path: str, base_url: str, call: ast.Call) -> str:
        if len(call.args) < 2:
            return base_url
        url = _strip_quotes(_value_text(call.args[0]))
        if url and not url.endswith("/"):
            url += "/"
        new_url = base_url + url
        classes = self.analyzed[path]["identifiers"]["classes"]
        view_name = _value_text(call.args[1])
        if view_name not in classes:
            return new_url
        view_path = classes[view_name]["path"]
        resolved_name = classes[view_name]["name"]
        lookup_field = _lookup_field(self.analyzed, view_path, resolved_name)
        self.endpoints.extend(_viewset_endpoints(self.analyzed, view_path, resolved_name, new_url, lookup_field))
        return new_url
