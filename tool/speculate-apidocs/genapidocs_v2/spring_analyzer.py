import copy
import os
import json
import logging
import re
from typing import Dict, List, Optional, Any, Tuple, Set
from collections import deque


# Import interfaces and base classes
from common.interfaces.framework_analyzer import FrameworkAnalyzer
from common.interfaces.code_analyzer import CodeAnalyzer, SymbolType
from java_analyzer import JavaCodeAnalyzer # Make sure this import works

REST_CONTROLLER_ANNOTATION = "Lorg/springframework/web/bind/annotation/RestController;"
CONTROLLER_ANNOTATION = "Lorg/springframework/stereotype/Controller;"
RESPONSE_BODY_ANNOTATION = "Lorg/springframework/web/bind/annotation/ResponseBody;"

class SpringBootFrameworkAnalyzer(FrameworkAnalyzer):
    """
    Spring Boot-specific implementation of the FrameworkAnalyzer interface.
    Uses JavaCodeAnalyzer output to identify endpoints and context.
    """

    def __init__(self, code_analyzer: CodeAnalyzer, project_path: str, logger=None):
        if not isinstance(code_analyzer, JavaCodeAnalyzer):
            raise TypeError("SpringBootFrameworkAnalyzer requires an instance of JavaCodeAnalyzer.")

        super().__init__(code_analyzer, project_path)
        self.logger = logger or logging.getLogger(__name__)
        self._cached_components: Optional[Dict[str, Dict[str, Any]]] = None
        self.endpoints: Optional[List[Dict[str, Any]]] = None
        self.logger.info("SpringBootFrameworkAnalyzer initialized.")
        self._implementations_map: Optional[Dict[str, List[str]]] = None
        self._serializers_map: Optional[Dict[str, str]] = None
        self._decoders_map: Optional[Dict[str, List[str]]] = None
        self._cached_error_handlers: Optional[List[Dict[str, Any]]] = None

        if not self.code_analyzer.analysis_results:
            self.logger.warning("CodeAnalyzer provided to SpringBootFrameworkAnalyzer has not loaded analysis results.")

        
    def _is_actual_endpoint(self, method_data: Dict[str, Any], class_info_map: Dict[str, Any]) -> bool:
        class_name = method_data.get("className")
        if not class_name or class_name not in class_info_map:
            return False

        class_info = class_info_map[class_name]
        class_annotations: Set[str] = {ann.get("type") for ann in class_info.get("annotations", [])}

        # --- Positive Identification Logic ---

        # Case A: The class is a @RestController. This is the strongest signal.
        if REST_CONTROLLER_ANNOTATION in class_annotations:
            return True

        # Case B: The class is a standard @Controller.
        if CONTROLLER_ANNOTATION in class_annotations:
            method_signature = method_data.get("signature")
            if not method_signature:
                return False

            # Find the full method details from the soot-analysis.json data
            full_method_info = next(
                (m for m in class_info.get("functions", []) if m.get("signature") == method_signature),
                None
            )

            if not full_method_info:
                self.logger.warning(f"Could not match method signature '{method_signature}' in class '{class_name}'.")
                return False

            # Condition 1: The method is explicitly annotated with @ResponseBody.
            method_annotations: Set[str] = {ann.get("type") for ann in full_method_info.get("annotations", [])}
            if RESPONSE_BODY_ANNOTATION in method_annotations:
                return True

            # Condition 2: The method returns a ResponseEntity. In this case, @ResponseBody is implicit.
            return_type = full_method_info.get("returnType")
            if return_type and "ResponseEntity" in return_type:
                return True
        
        # If none of the above conditions are met, it's not an endpoint.
        return False

    def _get_profiles_from_annotations(self, annotations: List[Dict[str, Any]]) -> List[str]:
        """
        Parses a list of annotation data dictionaries to find and extract Spring profile names.
        This version is tailored to the clean output format of the project's static analyzer.

        Handles:
        - @Profile("dev") -> kind: 's', value: "dev"
        - @Profile({"dev", "prod"}) -> kind: '[', value: ["dev", "prod"]

        Args:
            annotations: A list of annotation data dictionaries from soot-analysis.json.

        Returns:
            A list of profile names found.
        """
        PROFILE_ANNOTATION_FQN = "Lorg/springframework/context/annotation/Profile;"
        found_profiles: Set[str] = set()

        if not annotations:
            return []
            
        for ann in annotations:
            if ann.get("type") == PROFILE_ANNOTATION_FQN:
                for element in ann.get("elements", []):
                    # Check for the default 'value' attribute
                    if element.get("name") == "value" or element.get("name") is None:
                        kind = element.get("kind")
                        value = element.get("value")

                        if kind == 's' and isinstance(value, str):
                            # Single value, e.g., @Profile("dev")
                            clean_value = value.lstrip('!').strip()
                            if clean_value:
                                found_profiles.add(clean_value)
                        
                        elif kind == '[' and isinstance(value, list):
                            # Array of values, e.g., @Profile({"dev", "prod"})
                            # The `value` is a clean list of profile strings.
                            for profile_name in value:
                                if isinstance(profile_name, str):
                                    clean_value = profile_name.lstrip('!').strip()
                                    if clean_value:
                                        found_profiles.add(clean_value)
        
        return sorted(list(found_profiles))

    def detect_spring_profiles(self) -> List[str]:
        """
        Detects all unique Spring profiles mentioned in @Profile annotations throughout the project.
        This approach scans all class and method annotations from the static analysis results.

        Returns:
            A sorted list of unique profile names found.
        """
        self.logger.info("Detecting Spring profiles from @Profile annotations...")
        if not self.code_analyzer.analysis_results:
            self.logger.warning("Cannot detect profiles: analysis results not loaded.")
            return []

        all_profiles: Set[str] = set()
        class_identifiers = self.code_analyzer.analysis_results.get("classIdentifiers", [])

        for class_info in class_identifiers:
            # Check class-level annotations
            class_profiles = self._get_profiles_from_annotations(class_info.get("annotations", []))
            all_profiles.update(class_profiles)

            # Check method-level annotations (typically for @Bean definitions within @Configuration)
            for method_info in class_info.get("functions", []):
                method_profiles = self._get_profiles_from_annotations(method_info.get("annotations", []))
                all_profiles.update(method_profiles)
        
        sorted_profiles = sorted(list(all_profiles))
        self.logger.info(f"Detected {len(sorted_profiles)} unique profiles: {sorted_profiles}")
        return sorted_profiles

    def get_profile_metadata(self) -> Dict[str, Any]:
        """
        Gets metadata about which endpoints and components belong to which profiles
        by analyzing @Profile annotations on their defining classes.

        Returns:
            A dictionary with profile information, including mappings for endpoints and components.
        """
        self.logger.info("Gathering profile metadata for endpoints and components...")
        
        all_profiles = self.detect_spring_profiles()
        endpoint_profiles = {}
        component_profiles = {}

        # Ensure endpoints and components are discovered and cached first
        self.get_endpoints()
        self.get_schema_components()

        # 1. Map endpoints to profiles
        if self.endpoints:
            for endpoint in self.endpoints:
                handler_class_fqn = endpoint.get("metadata", {}).get("handler_class_fqn")
                if not handler_class_fqn:
                    continue

                class_info = self.code_analyzer.get_symbol_info(handler_class_fqn, self.project_path, SymbolType.CLASS)
                if not class_info:
                    continue
                
                # The endpoint's profile is determined by its controller class's @Profile annotation
                profiles_for_endpoint = self._get_profiles_from_annotations(class_info.get("annotations", []))

                endpoint_key = f"{endpoint.get('method', '').upper()} {endpoint.get('url', {}).get('url', '')}"

                # If a controller has no @Profile annotation, it's active in all profiles
                # (or more accurately, when no specific profile is active).
                # For this tool's purpose, we'll map it to all detected profiles for clarity.
                endpoint_profiles[endpoint_key] = profiles_for_endpoint if profiles_for_endpoint else all_profiles

        # 2. Map components (DTOs, Services etc.) to profiles
        if self._cached_components:
            self.logger.info(f"Assigning all {len(self._cached_components)} cached components to all detected profiles.")
            for component_fqn in self._cached_components.keys():
                # Simply assign the list of all detected profiles to every component.
                component_profiles[component_fqn] = all_profiles

        return {
            "profiles": all_profiles,
            "endpoint_profiles": endpoint_profiles,
            "component_profiles": component_profiles
        }
    
    def get_endpoints(self, *args, **kwargs) -> List[Dict[str, Any]]:
        """
        Merges raw endpoint methods from static analysis into unique API operations.
        This handles method overloading for different content types.
        """
        if self.endpoints is not None:
            self.logger.debug("Returning cached and merged endpoints.")
            return self.endpoints

        if not isinstance(self.code_analyzer, JavaCodeAnalyzer) or not self.code_analyzer.respector_results:
            self.logger.error("Cannot get endpoints: Respector results not loaded in JavaCodeAnalyzer.")
            return []

        raw_endpoint_methods = self.code_analyzer.respector_results.get("endpointMethods", [])
        
        if not raw_endpoint_methods:
            self.logger.warning("No endpoint methods found in respector results.")
            return []

        # --- Filter out methods that are not actual endpoints ---
        analysis_data = self.code_analyzer.analysis_results
        class_identifiers = analysis_data.get("classIdentifiers", [])
        class_info_map = {ci.get("className"): ci for ci in class_identifiers if ci.get("className")}
        actual_endpoint_methods = [
            method for method in raw_endpoint_methods
            if method.get("endpoints") and self._is_actual_endpoint(method, class_info_map)
        ]

        self.logger.info(f"Found {len(actual_endpoint_methods)} raw entries that represent actual endpoints.")

        # --- Grouping Logic: Group raw methods by "HTTP_METHOD /path" ---
        grouped_methods: Dict[str, List[tuple]] = {}
        for raw_method_data in actual_endpoint_methods:
            for endpoint_path_info in raw_method_data.get("endpoints", []):
                path = endpoint_path_info.get("path")
                http_method = endpoint_path_info.get("httpMethod", "").lower()
                if not path or not http_method:
                    continue
                
                operation_key = f"{http_method.upper()} {path}"
                if operation_key not in grouped_methods:
                    grouped_methods[operation_key] = []
                grouped_methods[operation_key].append((raw_method_data, endpoint_path_info))


        final_merged_endpoints = []
        for operation_key, method_group in grouped_methods.items():
            # Now, base_endpoint_info is guaranteed to be the one that matches the group key.
            base_method_info, base_endpoint_info = method_group[0]

            http_method = base_endpoint_info.get("httpMethod").upper()
            path = base_endpoint_info.get("path")
            handler_class_fqn = base_method_info.get("className")

            if not handler_class_fqn:
                self.logger.warning(f"Skipping group for {operation_key} due to missing className.")
                continue
            
            handler_class_info = self.code_analyzer.get_symbol_info(handler_class_fqn, self.project_path, SymbolType.CLASS)
            handler_file_path = handler_class_info.get("classFileName") if handler_class_info else "unknown_path.java"
            
            merged_metadata = {
                "handler_class_fqn": handler_class_fqn,
                "implementing_methods": []
            }

            all_path_params = {}
            for method_info, endpoint_info in method_group:
                method_details = {
                    "method_name": method_info.get("name"),
                    "signature": method_info.get("signature"),
                    "consumes": method_info.get("consumes", []),
                    "produces": method_info.get("produces", []),
                    "all_parameters": method_info.get("allParameters", [])
                }
                merged_metadata["implementing_methods"].append(method_details)
                
                # Collect all unique path parameters from the *correct* endpoint info
                for param in endpoint_info.get("parameters", []):
                    if param.get("in") == "path":
                        all_path_params[param.get("name")] = param

            # The final structure of this dictionary is UNCHANGED.
            merged_endpoint = {
                "url": {
                    "url": path,
                    "parameter": list(all_path_params.values())
                },
                "method": http_method,
                "view": handler_class_fqn.split('.')[-1],
                "path": os.path.abspath(handler_file_path) if handler_file_path and os.path.exists(handler_file_path) else None,
                "is_viewset": True,
                "function": base_method_info.get("name"),
                "metadata": merged_metadata,
                "handler_count": len(method_group)
            }
            final_merged_endpoints.append(merged_endpoint)

        self.logger.info(f"Finished merge. Produced {len(final_merged_endpoints)} unique API operations.")
        
        self.endpoints = final_merged_endpoints
        return self.endpoints
    
    def _find_request_body_parameter_spring(self, method_parameters_from_soot: List[Dict]) -> Optional[Dict]:
        """
        Identifies the parameter representing the request body by looking for the @RequestBody annotation.
        """
        SPRING_REQUEST_BODY_FQN = "org.springframework.web.bind.annotation.RequestBody"

        for param_info_soot in method_parameters_from_soot:
            for ann in param_info_soot.get("annotations", []):
                # The annotation type from Soot is a descriptor
                if ann.get("type") == f"L{SPRING_REQUEST_BODY_FQN.replace('.', '/')};":
                    self.logger.debug(f"Found @RequestBody on parameter '{param_info_soot.get('name')}'")
                    return param_info_soot
        return None

    def _is_primitive_or_common(self, type_name: Optional[str]) -> bool:
        """Checks if a type name represents a Java primitive or common stdlib/framework class."""
        if not type_name:
            return True
        base_type = type_name.replace("[]", "") # Handle arrays

        primitive_types = {"byte", "short", "int", "long", "float", "double", "boolean", "char", "void"}
        if base_type in primitive_types:
            return True

        common_prefixes_or_exact = [
            "java.lang.", "java.util.", "java.net.", "java.io.", "java.math.", "java.time.",
            "javax.ws.rs.", "jakarta.ws.rs.",
            "javax.inject.", "jakarta.inject.", # Common dependency injection
            "javax.persistence.", "jakarta.persistence.", # JPA / Jakarta Persistence
            "org.springframework.http.", "org.springframework.web.bind.annotation.", # Common Spring web types if used with Jersey
            "org.slf4j.", "java.util.logging.", # Logging
            "com.fasterxml.jackson.databind.", # Jackson types themselves
        ]
        if any(base_type.startswith(prefix) for prefix in common_prefixes_or_exact):
            return True

        return False
    
    def _is_potential_dto(self, type_name: Optional[str]) -> bool:
        """
        A more robust, multi-rule heuristic to determine if a class is likely a DTO,
        POJO, or Enum that should be included as a schema component.
        """
        if not type_name or self._is_primitive_or_common(type_name):
            return False

        # --- RULE 1: Hard Rejection for Obvious Non-DTO Patterns ---
        # Classes ending in these suffixes are almost never data transfer objects.
        # This is our strongest filter.
        excluded_suffixes = [
            'Controller', 'Service', 'ServiceImpl', 'Repository', 
            'Factory', 'Builder', 'Configuration', 'Application',
            'Filter', 'Handler', 'Manager', 'Provider', 'Utils'
        ]
        simple_name = type_name.split('.')[-1]
        if any(simple_name.endswith(suffix) for suffix in excluded_suffixes):
            self.logger.debug(f"[_is_potential_dto] REJECT: '{type_name}' ends with an excluded suffix.")
            return False

        # --- RULE 2: Positive Inclusion based on Package Name ---
        # If the FQN contains these keywords, it's very likely a component.
        # This is more flexible than checking just one part of the package.
        inclusion_keywords = [
            '.dto', '.model', '.entities', '.entity', '.requestbody', '.responsebody', '.enums'
        ]
        if any(keyword in type_name.lower() for keyword in inclusion_keywords):
            self.logger.debug(f"[_is_potential_dto] ACCEPT: '{type_name}' contains an inclusion keyword.")
            return True

        # --- RULE 3: Check Class Info for Strong Positive Signals (Enum/Interface) ---
        # If we have static analysis info, being an Enum or an Interface (that isn't
        # a common utility) is a very strong signal it's part of the data model.
        class_info = self.code_analyzer.get_symbol_info(type_name, self.project_path, SymbolType.CLASS)
        if class_info:
            if class_info.get("isEnum"):
                self.logger.debug(f"[_is_potential_dto] ACCEPT: '{type_name}' is an Enum.")
                return True
            if class_info.get("isInterface"):
                # Avoid common generic interfaces like 'List' if they slip through
                if not type_name.startswith('java.util.'):
                    self.logger.debug(f"[_is_potential_dto] ACCEPT: '{type_name}' is an Interface.")
                    return True

        # --- RULE 4: Fallback for Ambiguous Cases ---
        # If none of the above rules triggered, we make a final guess. We reject things
        # that look like they are in service or security packages, otherwise we accept.
        if '.services.' in type_name or '.security.' in type_name or '.config.' in type_name:
             self.logger.debug(f"[_is_potential_dto] REJECT (Fallback): '{type_name}' is in a service/security/config package.")
             return False

        self.logger.debug(f"[_is_potential_dto] ACCEPT (Fallback): '{type_name}' passed all filters.")
        return True

    def _get_base_type(self, type_name: Optional[str]) -> Optional[str]:
        """
        Extracts the base, non-collection, non-primitive type from a Java type string.
        This parser correctly handles nested generics like Map<String, List<MyDTO>>
        and also converts Soot's L...; type descriptors to FQNs.

        Args:
            type_name: The Java type string to parse (e.g., "java.util.List<Lcom/example/MyDTO;>[]").

        Returns:
            The fully qualified name of the base type.
        """
        if not type_name:
            self.logger.debug(f"_get_base_type: Input is None or empty.")
            return None

        original_type_for_logging = type_name
        
        # --- Step 1: Pre-process for arrays ---
        type_name = type_name.strip()
        while type_name.endswith("[]"):
            type_name = type_name[:-2].strip()

        # --- Step 2: Iteratively unwrap known generic containers ---
        containers = [
            "java.util.List", "java.util.Set", "java.util.Collection",
            "java.util.Optional", "javax.ws.rs.core.Response", "jakarta.ws.rs.core.Response"
        ]
        
        changed_in_iteration = True
        while changed_in_iteration:
            changed_in_iteration = False
            
            # Unbox standard containers like List<T>
            for container in containers:
                prefix = container + "<"
                if type_name.startswith(prefix) and type_name.endswith(">"):
                    inner_content = type_name[len(prefix):-1].strip()
                    if inner_content:
                        type_name = inner_content
                        changed_in_iteration = True
                        break 
            if changed_in_iteration:
                continue

            # Unbox Map<K, V>, focusing only on the value type V
            map_prefix = "java.util.Map<"
            if type_name.startswith(map_prefix) and type_name.endswith(">"):
                inner_content = type_name[len(map_prefix):-1].strip()
                
                balance = 0
                split_index = -1
                for i, char in enumerate(inner_content):
                    if char == '<': balance += 1
                    elif char == '>': balance -= 1
                    elif char == ',' and balance == 0:
                        split_index = i
                        break
                
                if split_index != -1:
                    value_type = inner_content[split_index + 1:].strip()
                    if value_type:
                        type_name = value_type
                        changed_in_iteration = True
                else:
                    break

        # --- Step 3: Final processing of the extracted base type ---
        # After unwrapping, `type_name` is now the core type. It might be a
        # clean FQN like "com.example.MyDTO" or a Soot descriptor like "Lcom/example/MyDTO;".
        # This final conversion ensures a standard FQN is always returned.
        final_base_type = self._soot_descriptor_to_fqn(type_name)

        self.logger.info(f"_get_base_type: For original='{original_type_for_logging}', extracted base type='{final_base_type}'")
        return final_base_type

    def _soot_descriptor_to_fqn(self, descriptor: Optional[str]) -> Optional[str]:
        """Converts Soot's Lpath/to/Class; descriptor to path.to.Class FQN."""
        if not descriptor:
            return None
        
        # Handle array descriptors like "[Ljava/lang/String;" -> "java.lang.String[]"
        # This part should ideally be integrated into how _get_base_type handles arrays from the start.
        # For now, let's assume _get_base_type already stripped array markers and we only get L...; or primitives.
        
        cleaned_descriptor = descriptor
        is_array = False
        while cleaned_descriptor.startswith("["):
            is_array = True
            cleaned_descriptor = cleaned_descriptor[1:]

        fqn = cleaned_descriptor
        if fqn.startswith("L") and fqn.endswith(";"):
            fqn = fqn[1:-1].replace('/', '.')
        
        # If it was an array, re-append brackets (this is simplistic,
        # _get_base_type's array handling is better)
        # This helper is primarily for converting the *element type* if it's a descriptor.
        # For a type like "[Ljava.lang.String;", _get_base_type should have already
        # called itself with "Ljava.lang.String;", which then gets converted here.
        
        return fqn
    
    def _get_all_properties_for_class(self, fqn_to_start_from: str) -> List[Dict[str, Any]]:
        """
        Gathers all unique properties for a class by inspecting its declared fields,
        its inferred getter methods, and recursively doing the same for its entire
        parent hierarchy.
        """
        all_props_collected = []
        
        # Inner recursive helper
        def gather_from_hierarchy(current_fqn: str, visited_fqns_for_fields: Set[str]):
            if not current_fqn or current_fqn in visited_fqns_for_fields:
                return
            visited_fqns_for_fields.add(current_fqn)

            info = self.code_analyzer.get_symbol_info(current_fqn, self.project_path, SymbolType.CLASS)
            if not info: return

            # Add declared fields of the current class first
            all_props_collected.extend(info.get("fields", []))
            # Then add fields inferred from getters of the current class
            all_props_collected.extend(self._infer_fields_from_getters(info))

            # Then recurse on parents
            parent_hierarchy = self.code_analyzer.get_type_hierarchy(current_fqn, self.project_path)
            for p_info_dict in parent_hierarchy:
                gather_from_hierarchy(p_info_dict.get("name"), visited_fqns_for_fields)
        
        gather_from_hierarchy(fqn_to_start_from, set())
        
        # De-duplicate the collected properties. The first one found (most specific class) wins.
        final_props_map = {}
        for prop in all_props_collected:
            name = prop.get("name")
            if name and name not in final_props_map:
                final_props_map[name] = prop
        return list(final_props_map.values())
    
    def _build_implementation_map(self):
        """
        Pre-processes soot-analysis.json to build a lookup map of interface -> concrete classes.
        This is a one-time operation for efficiency.
        """
        if self._implementations_map is not None:
            self.logger.debug("Implementation map already built.")
            return

        self.logger.info("Building implementation map...")
        self._implementations_map = {}

        all_class_data = self.code_analyzer.analysis_results.get("classIdentifiers", [])
        if not all_class_data:
            self.logger.error("Cannot build implementation map: 'classIdentifiers' not found.")
            return

        for class_info in all_class_data:
            class_fqn = class_info.get("className")
            if not class_fqn or class_info.get("isInterface"):
                continue

            # 'parentClasses' in our analysis output includes both superclasses and interfaces.
            parent_classes = class_info.get("parentClasses", [])
            for interface_fqn in parent_classes:
                if interface_fqn not in self._implementations_map:
                    self._implementations_map[interface_fqn] = []
                self._implementations_map[interface_fqn].append(class_fqn)

        self.logger.info(f"Built implementation map with {len(self._implementations_map)} interface entries.")
        
    def _find_concrete_implementation(self, interface_fqn: str) -> Optional[Dict[str, Any]]:
        """
        Finds the best concrete implementation for a given interface FQN.
        It prefers implementations annotated with a persistence annotation like @Entity.
        """
        self._build_implementation_map()
        implementations = self._implementations_map.get(interface_fqn, [])
        if not implementations:
            self.logger.debug(f"No implementations found for interface '{interface_fqn}'.")
            return None

        # Strategy: Find the implementation that is a Morphia/JPA @Entity
        best_candidate_info = None
        for impl_fqn in implementations:
            # Prefer a direct naming convention match if available
            if impl_fqn == f"{interface_fqn}Impl" or impl_fqn.endswith(f".{interface_fqn.split('.')[-1]}Impl"):
                 self.logger.info(f"Found implementation via naming convention for '{interface_fqn}': '{impl_fqn}'")
                 return self.code_analyzer.get_symbol_info(impl_fqn, self.project_path, SymbolType.CLASS)
            
            # Keep the first one as a fallback if no naming convention matches
            if not best_candidate_info:
                best_candidate_info = self.code_analyzer.get_symbol_info(impl_fqn, self.project_path, SymbolType.CLASS)

        if best_candidate_info:
            self.logger.info(f"Found fallback implementation for '{interface_fqn}': '{best_candidate_info.get('className')}'")
        
        return best_candidate_info

    def _gather_dependencies_recursively(self, 
                                     start_fqn: str, 
                                     visited_fqns: Set[str], 
                                     max_depth: int = 5,
                                     debug_context_fqn: Optional[str] = None
                                     ) -> List[Dict[str, Any]]:
        """
        Recursively gathers the code and context for a starting FQN and all of its
        nested DTO/Enum dependencies.

        Args:
            start_fqn: The Fully Qualified Name of the component to start from.
            visited_fqns: A set of FQNs that have already been processed to prevent
                        infinite recursion in case of circular dependencies.
            max_depth: The maximum recursion depth to prevent runaway processing.

        Returns:
            A flat list of context dictionaries for the starting component and all
            its unique, nested dependencies.
        """
        if debug_context_fqn:
            self.logger.info(f"[RECURSIVE_GATHER][{debug_context_fqn}] (Depth {5-max_depth}) Analyzing dependencies for: {start_fqn}")
        # --- Base Cases for Recursion ---
        if max_depth <= 0:
            self.logger.warning(f"Max recursion depth reached while gathering dependencies for {start_fqn}.")
            return []
        
        if start_fqn in visited_fqns:
            return []

        # --- Mark as Visited & Get Info ---
        visited_fqns.add(start_fqn)
        dep_info = self.code_analyzer.get_symbol_info(start_fqn, self.project_path, SymbolType.CLASS)
        if not dep_info:
            self.logger.warning(f"Recursive gather: Could not get info for dependency '{start_fqn}'.")
            return []

        # --- This list will hold this component AND all its children ---
        all_related_contexts = []
        
        # --- Determine Component Type & Add Itself to the Context List ---
        is_enum = dep_info.get("isEnum", False)
        is_dto = self._is_potential_dto(start_fqn)
        is_dto=True
        if not is_enum and not is_dto:
            self.logger.debug(f"Recursive gather: Skipping '{start_fqn}' as it is not a DTO or Enum.")
            return []

        dep_type_for_header = "Enum" if is_enum else "DTO"
        dep_path = dep_info.get("classFileName") or dep_info.get("filePath")
        dep_code = self.code_analyzer.get_code_snippet(dep_path, dep_info.get("startLine"), dep_info.get("endLine"))

        if dep_code:
            header = f"// --- Dependency: {dep_type_for_header} ({start_fqn}) ---\n"
            all_related_contexts.append({
                "name": start_fqn.split('.')[-1],
                "qualifiedName": start_fqn,
                "path": dep_path,
                "code": header + dep_code,
                "type": dep_type_for_header.lower()
            })
            self.logger.debug(f"Recursively added context for {dep_type_for_header}: {start_fqn}")

        # --- Recurse on Children (if not an Enum) ---
        if not is_enum:
            properties = self._get_all_properties_for_class(start_fqn)
            for prop in properties:
                base_type_fqn = self._get_base_type(prop.get("type"))
                if not base_type_fqn or base_type_fqn in visited_fqns:
                    continue
                
                # RECURSIVE CALL for nested dependencies
                nested_deps = self._gather_dependencies_recursively(
                    base_type_fqn, visited_fqns, max_depth - 1
                )
                all_related_contexts.extend(nested_deps)

        self.logger.debug(f"Gathering parent hierarchy for '{start_fqn}'...")
        parent_hierarchy = self.code_analyzer.get_type_hierarchy(start_fqn, dep_path)
        
        for parent_info in parent_hierarchy:
            parent_fqn = parent_info.get("name")
            
            # The parent FQN is valid and we haven't processed it yet
            if parent_fqn and parent_fqn not in visited_fqns:
                # The recursive call will handle all checks (is it a DTO? an Enum? already visited?)
                # This ensures we don't pull in the entire JDK or classes like 'Object'.
                # The internal checks in this same function will filter them out.
                self.logger.debug(f"'{start_fqn}' has parent '{parent_fqn}'. Kicking off recursive gather for it.")
                parent_deps = self._gather_dependencies_recursively(
                    parent_fqn, visited_fqns, max_depth - 1
                )
                all_related_contexts.extend(parent_deps)
                
        return all_related_contexts
    
    def _gather_dependencies_recursively_relaxed(self, 
                                     start_fqn: str, 
                                     visited_fqns: Set[str], 
                                     max_depth: int = 5,
                                     debug_context_fqn: Optional[str] = None
                                     ) -> List[Dict[str, Any]]:
        """
        Recursively gathers the code and context for a starting FQN and all of its
        nested DTO/Enum dependencies.

        Args:
            start_fqn: The Fully Qualified Name of the component to start from.
            visited_fqns: A set of FQNs that have already been processed to prevent
                        infinite recursion in case of circular dependencies.
            max_depth: The maximum recursion depth to prevent runaway processing.

        Returns:
            A flat list of context dictionaries for the starting component and all
            its unique, nested dependencies.
        """
        self.logger.info(f"[_gather_dependencies_recursively]: Attempting to process FQN: '{start_fqn}'")
        if debug_context_fqn:
            self.logger.info(f"[RECURSIVE_GATHER][{debug_context_fqn}] (Depth {5-max_depth}) Analyzing dependencies for: {start_fqn}")
        # --- Base Cases for Recursion ---
        if max_depth <= 0:
            self.logger.warning(f"Max recursion depth reached while gathering dependencies for {start_fqn}.")
            return []
        
        if start_fqn in visited_fqns:
            return []

        # --- Mark as Visited & Get Info ---
        visited_fqns.add(start_fqn)
        dep_info = self.code_analyzer.get_symbol_info(start_fqn, self.project_path, SymbolType.CLASS)
        if not dep_info:
            self.logger.warning(f"Recursive gather: Could not get info for dependency '{start_fqn}'.")
            return []

        # --- This list will hold this component AND all its children ---
        all_related_contexts = []
        is_interface = dep_info.get("isInterface", False)
        if is_interface:
            self.logger.debug(f"'{start_fqn}' is an interface. Finding and gathering context for its concrete DTO implementations.")
            
            # Reuse the proven, safe filtering mechanism
            dto_implementations = self._find_and_filter_implementations(start_fqn)
            
            # Also include the interface definition itself in the context, as it's relevant
            # The existing logic below will handle adding the interface's own code
            
            # Now, for each *filtered* DTO implementation, recurse.
            for impl_fqn in dto_implementations:
                if impl_fqn not in visited_fqns:
                    # RECURSIVE CALL for each valid DTO implementation
                    impl_deps = self._gather_dependencies_recursively_relaxed(
                        start_fqn=impl_fqn,
                        visited_fqns=visited_fqns, # Pass the same visited set
                        max_depth=max_depth - 1,
                        debug_context_fqn=start_fqn # Pass parent for better logging
                    )
                    all_related_contexts.extend(impl_deps)

        # --- Determine Component Type & Add Itself to the Context List ---
        is_enum = dep_info.get("isEnum", False)
        is_dto = self._is_potential_dto(start_fqn)
        is_dto=True
        if not is_enum and not is_dto:
            self.logger.debug(f"Recursive gather: Skipping '{start_fqn}' as it is not a DTO or Enum.")
            return all_related_contexts

        dep_type_for_header = "Enum" if is_enum else ("Interface" if is_interface else "DTO")
        dep_path = dep_info.get("classFileName") or dep_info.get("filePath")
        dep_code = self.code_analyzer.get_code_snippet(dep_path, dep_info.get("startLine"), dep_info.get("endLine"))
        if dep_code:
            header = f"// --- Dependency: {dep_type_for_header} ({start_fqn}) ---\n"
            all_related_contexts.append({
                "name": start_fqn.split('.')[-1],
                "qualifiedName": start_fqn,
                "path": dep_path,
                "code": header + dep_code,
                "type": dep_type_for_header.lower()
            })
            self.logger.debug(f"Recursively added context for {dep_type_for_header}: {start_fqn}")
        new_dependencies_to_process = set()
        # --- Recurse on Children (if not an Enum) ---
        if not is_enum:
            properties = self._get_all_properties_for_class(start_fqn)
            for prop in properties:
                base_type_fqn = self._get_base_type(prop.get("type"))
                if not base_type_fqn or base_type_fqn in visited_fqns:
                    continue
                
                # RECURSIVE CALL for nested dependencies
                nested_deps = self._gather_dependencies_recursively_relaxed(
                    base_type_fqn, visited_fqns, max_depth - 1
                )
                all_related_contexts.extend(nested_deps)
        
        if not is_enum:
            methods = dep_info.get("functions", [])
            for method in methods:
                # 1. Analyze return type
                return_type_base_fqn = self._get_base_type(method.get("returnType"))
                if return_type_base_fqn:
                    new_dependencies_to_process.add(return_type_base_fqn)

                # 2. Analyze parameters (this is the key for finding injected dependencies)
                params = method.get("parameters", [])
                for param in params:
                    param_type_base_fqn = self._get_base_type(param.get("type"))
                    if param_type_base_fqn:
                        new_dependencies_to_process.add(param_type_base_fqn)

        parent_hierarchy = self.code_analyzer.get_type_hierarchy(start_fqn, dep_info.get("classFileName"))
        for parent_info in parent_hierarchy:
            parent_fqn = parent_info.get("name")
            if parent_fqn:
                new_dependencies_to_process.add(parent_fqn)

        self.logger.debug(f"For '{start_fqn}', found {len(new_dependencies_to_process)} potential new dependencies to process.")
        for dep_fqn in new_dependencies_to_process:
            if dep_fqn not in visited_fqns:
                # RECURSIVE CALL for all discovered nested dependencies
                nested_deps = self._gather_dependencies_recursively_relaxed(
                    start_fqn=dep_fqn,
                    visited_fqns=visited_fqns, # Pass the same set to maintain state across the entire call stack
                    max_depth=max_depth - 1,
                    debug_context_fqn=debug_context_fqn
                )
                all_related_contexts.extend(nested_deps)
                
        return all_related_contexts
    
    def _find_and_include_type_converters(self, 
                                        field_types_to_check: Set[str], 
                                        processed_fqns: Set[str]) -> List[Dict[str, Any]]:
        """
        Scans the project for Morphia TypeConverters that handle the given field types.
        """
        all_converters_context = []
        
        # Pre-scan for all TypeConverter classes in the project
        all_converter_classes_info = []
        for class_info in self.code_analyzer.analysis_results.get("classIdentifiers", []):
            if "dev.morphia.converters.TypeConverter" in class_info.get("parentClasses", []):
                all_converter_classes_info.append(class_info)
        
        self.logger.info(f"Found {len(all_converter_classes_info)} potential TypeConverter classes.")

        for fqn_to_check in field_types_to_check:
            if self._is_primitive_or_common(fqn_to_check):
                continue

            for converter_info in all_converter_classes_info:
                converter_fqn = converter_info.get("className")
                if converter_fqn in processed_fqns:
                    continue

                # Check if this converter handles our target FQN
                # (A simplified check: does the FQN appear in the converter's file content or constructor signature?)
                # A more robust check would analyze the super() call as described in the algorithm.
                if fqn_to_check in json.dumps(converter_info): # Heuristic check
                    self.logger.info(f"Found potential converter '{converter_fqn}' for type '{fqn_to_check}'.")
                    
                    # If found, gather its full context and all of *its* dependencies recursively
                    converter_dependencies = self._gather_dependencies_recursively(
                        start_fqn=converter_fqn,
                        visited_fqns=processed_fqns,
                        max_depth=5 # Give it enough depth to find implementations
                    )
                    all_converters_context.extend(converter_dependencies)
                    # No need to check other converters for this type
                    break 

        return all_converters_context
    
    def _find_and_filter_implementations(self, interface_fqn: str) -> List[str]:
        """
        Finds all implementations of an interface and filters them to keep only
        those that are likely DTOs/POJOs.
        """
        self._build_implementation_map() # Ensure map is ready

        all_implementations = self._implementations_map.get(interface_fqn, [])
        if not all_implementations:
            self.logger.debug(f"No implementations found in map for interface '{interface_fqn}'.")
            return []
        
        self.logger.debug(f"Found {len(all_implementations)} raw implementations for '{interface_fqn}': {all_implementations}")
        
        # This is the "aggressive filtering" step
        filtered_dtos = []
        for impl_fqn in all_implementations:
            if self._is_potential_dto(impl_fqn):
                filtered_dtos.append(impl_fqn)
            else:
                self.logger.debug(f"Filtered out non-DTO implementation '{impl_fqn}' for interface '{interface_fqn}'.")
        
        return filtered_dtos
    
    def build_concrete_component_context(self, primary_fqn: str) -> Optional[Dict[str, Any]]:
        """
        Builds a complete, concrete context for a component by finding its
        implementation, serializer, and all transitive dependencies.
        This is the new primary method to be called for each component.
        """
        self.logger.info(f"--- Building CONCRETE context for primary artifact: {primary_fqn} ---")
        primary_info = self.code_analyzer.get_symbol_info(primary_fqn, self.project_path, SymbolType.CLASS)
        if not primary_info:
            self.logger.warning(f"Could not get info for primary artifact '{primary_fqn}'. Skipping.")
            return None
        
        primary_path = primary_info.get("classFileName") or primary_info.get("filePath")
        if not primary_path:
             self.logger.warning(f"Primary artifact '{primary_fqn}' is missing a file path. Skipping.")
             return None

        # This set tracks every FQN we add to the context to avoid duplicates.
        processed_fqns = set()

        # This list will hold the symbol_info dictionaries of all relevant artifacts.
        key_artifacts = []

        # Step 0: Get the primary interface info
        key_artifacts.append(primary_info)

        # STAGE 1: Find the concrete data model
        implementation_info = self._find_concrete_implementation(primary_fqn)
        if implementation_info:
            key_artifacts.append(implementation_info)
            #processed_fqns.add(implementation_info['className'])


        # STAGE 4: Holistic Recursive Gathering
        # We now have our high-value starting points. We will gather all their dependencies.
        final_dependency_contexts = []
        self.logger.info(f"Found {len(key_artifacts)} key artifacts. Starting recursive dependency gathering...")
        for artifact_info in key_artifacts:
            # if "Track" in primary_fqn:
            #     print(">>> DEBUGGER: Paused after recursive gathering. Inspect 'final_dependency_contexts'.")
            #     import pdb; pdb.set_trace()
            artifact_fqn = artifact_info.get("className")
            self.logger.debug(f"  > Gathering dependencies for key artifact: {artifact_fqn}")
            # The 'processed_fqns' set is passed by reference and updated by the recursive call
            dependencies = self._gather_dependencies_recursively_relaxed(
                start_fqn=artifact_fqn,
                visited_fqns=processed_fqns,
                max_depth=5 # A safe depth limit
            )
            final_dependency_contexts.extend(dependencies)


        # Final Assembly for the LLM prompt
        self.logger.info("Assembling final context for LLM prompt...")
        
        primary_path = primary_info.get("classFileName") or primary_info.get("filePath")
        primary_code=self.code_analyzer.get_code_snippet(
            primary_path, primary_info.get("startLine"), primary_info.get("endLine")
        ) or f"// Code for {primary_fqn} not found."

        prompt_code = f"// --- Primary Class/Interface: {primary_fqn} ---\n{primary_code}"

        parent_hierarchy_list = self.code_analyzer.get_type_hierarchy(primary_fqn, self.project_path)
        parent_fqns = {p.get("name") for p in parent_hierarchy_list if p.get("name")}
        impl_fqn = implementation_info.get("className") if implementation_info else None
        fqn_for_fields = impl_fqn or primary_fqn
        final_fields_list = self._get_all_properties_for_class(fqn_for_fields)
        clubbed_code_parts = [f"// --- Primary Class/Interface: {primary_fqn} ---\n{primary_code}"]
        final_data_classes = []

        #gather converters
        field_types_needing_converters = set()
        for field in final_fields_list:
            base_type = self._get_base_type(field.get("type")) # Assuming you have a working type parser now
            if base_type and not self._is_potential_dto(base_type): # Look for types that aren't other DTOs
                 field_types_needing_converters.add(base_type)
        
        if field_types_needing_converters:
            self.logger.info(f"Checking for custom type converters for types: {field_types_needing_converters}")
            converter_contexts = self._find_and_include_type_converters(
                field_types_needing_converters, 
                processed_fqns # Use the same set to avoid re-processing
            )
            final_dependency_contexts.extend(converter_contexts)

        # if "Track" in primary_fqn:
        #         print(">>> DEBUGGER: Paused after recursive gathering. Inspect 'final_dependency_contexts'.")
        #         import pdb; pdb.set_trace() 
        
        # This set tracks FQNs whose code is "clubbed" into the main `code` block.
        claimed_for_clubbing_fqns = {primary_fqn}

        # Add implementation to clubbed code
        if implementation_info:
            impl_path = implementation_info.get("classFileName") or implementation_info.get("filePath")
            impl_code = self.code_analyzer.get_code_snippet(
                impl_path, implementation_info.get("startLine"), implementation_info.get("endLine")
            )
            if impl_code:
                clubbed_code_parts.append(f"\n\n// --- Implementation: {impl_fqn} ---\n{impl_code}")
                claimed_for_clubbing_fqns.add(impl_fqn)

        # Add parents to clubbed code
        for parent_info in parent_hierarchy_list:
            parent_fqn = parent_info.get("name")
            if parent_fqn and parent_info.get("code"):
                clubbed_code_parts.append(f"\n\n// --- Parent Class: {parent_fqn} ---\n{parent_info['code']}")
                claimed_for_clubbing_fqns.add(parent_fqn)
        
        clubbed_code_str = "".join(clubbed_code_parts)

        processed_for_data_classes = set()
        # Format the dependencies for the 'data_classes' section of the prompt
        for artifact in key_artifacts[1:]:
            artifact_fqn=artifact.get("className")
            if artifact_fqn not in claimed_for_clubbing_fqns and artifact_fqn not in processed_for_data_classes:
                artifact_path = artifact.get("classFileName") or artifact.get("filePath")
                code = self.code_analyzer.get_code_snippet(
                    artifact_path, artifact.get("startLine"), artifact.get("endLine")
                )
                if code:
                    final_data_classes.append({
                        "name": artifact.get("className").split('.')[-1],
                        "qualifiedName": artifact.get("className"),
                        "path": artifact.get("classFileName"),
                        "code": f"// --- Dependency: {artifact.get('className')} ---\n{code}"
                    })
                    processed_for_data_classes.add(artifact_fqn)

        for artifact in final_dependency_contexts:
            # get_code_snippet_from_info is a hypothetical helper you'd create
            artifact_fqn = artifact.get('qualifiedName')
            if artifact_fqn not in claimed_for_clubbing_fqns and artifact_fqn not in processed_for_data_classes:
                    code = artifact.get('code')
                    if code:
                        final_data_classes.append({
                            "name": artifact.get('name'),
                            "qualifiedName": artifact.get("qualifiedName"),
                            "path": artifact.get("path"),
                            "code": f"// --- Dependency: {artifact.get('qualifiedName')} ---\n{code}"
                        })
                        processed_for_data_classes.add(artifact_fqn)
        # Return the final dictionary in the format your prompt manager expects
        return {
            "name": primary_fqn.split('.')[-1],
            "qualifiedName": primary_fqn,
            "path": primary_path,
            "code": clubbed_code_str,
            "fields_info": final_fields_list,
            "parent_classes": parent_hierarchy_list,
            "data_classes": final_data_classes,
            "annotations": primary_info.get("annotations", []),
            "is_interface": primary_info.get("isInterface", False),
            "supports_request": True,
            "supports_response": True,
        }
    
    def _infer_fields_from_getters(self, class_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Infers schema fields from public getter methods (e.g., getFirstName(), isEnabled())
        found in a class's analysis information.
        """
        inferred_fields = []
        if not class_info or not isinstance(class_info.get("functions"), list):
            return inferred_fields

        for method in class_info.get("functions", []): # Ensure functions is treated as a list
            method_name = method.get("methodName")
            if not method_name:
                continue

            field_name = None
            # Check for get...() pattern, e.g., getFirstName -> firstName
            if method_name.startswith("get") and len(method_name) > 3 and method_name[3].isupper():
                # Ensure it's a no-arg method (a true getter)
                if len(method.get("parameters", [])) == 0:
                    field_name = method_name[3].lower() + method_name[4:]
            
            # Check for is...() pattern for booleans, e.g., isEnabled -> enabled
            elif method_name.startswith("is") and len(method_name) > 2 and method_name[2].isupper():
                if len(method.get("parameters", [])) == 0:
                     field_name = method_name[2].lower() + method_name[3:]

            if field_name:
                self.logger.debug(f"Inferred field '{field_name}' from getter '{method_name}' in class '{class_info.get('className')}'.")
                # The type of the inferred field is the return type of the getter.
                # Annotations on the getter method are also relevant for the field.
                inferred_fields.append({
                    "name": field_name,
                    "type": method.get("returnType"), # Type comes from getter's return type
                    "annotations": method.get("annotations", []) # Carry over annotations from getter
                })
        
        return inferred_fields

    def _discover_seed_components(self) -> Set[str]:
        """
        PHASE 1: Iterates through all *actual* endpoints and inspects their full
        method signatures in soot-analysis.json to find the initial set of
        component FQNs used in @RequestBody parameters and return types.
        """
        self.logger.info("--- Starting Seed Component Discovery ---")
        seed_component_fqns: Set[str] = set()
        
        raw_endpoint_methods = self.code_analyzer.respector_results.get("endpointMethods", [])
        self.logger.debug(f"Found {len(raw_endpoint_methods)} total method entries in soot-respector.json.")

        for i, raw_method_data in enumerate(raw_endpoint_methods):
            self.logger.debug(f"--- Processing Respector Entry #{i+1} ---")
            
            # Filter for actual endpoints
            if not raw_method_data.get("endpoints"):
                self.logger.debug("Entry is not an endpoint (missing 'endpoints' key). Skipping.")
                continue

            class_fqn = raw_method_data.get("className")
            method_sig = raw_method_data.get("signature")
            self.logger.debug(f"Endpoint found in class: '{class_fqn}'")
            self.logger.debug(f"Signature: '{method_sig}'")

            if not class_fqn or not method_sig:
                self.logger.warning("Respector entry is missing className or signature. Skipping.")
                continue

            # Look up the full method details in the code index (soot-analysis.json)
            class_info = self.code_analyzer.get_symbol_info(class_fqn, self.project_path, SymbolType.CLASS)
            if not class_info:
                self.logger.warning(f"Could not find class info for '{class_fqn}' in soot-analysis.json. Skipping method.")
                continue

            method_info = next((m for m in class_info.get("functions", []) if m.get("signature") == method_sig), None)
            if not method_info:
                self.logger.warning(f"Could not find matching method for signature '{method_sig}' in class '{class_fqn}' within soot-analysis.json. Skipping method.")
                continue
            
            self.logger.debug("Successfully matched method in soot-analysis.json. Inspecting parameters...")

            # --- 1. Discover Request Body component via @RequestBody ---
            method_parameters = method_info.get("parameters", [])
            self.logger.debug(f"Method has {len(method_parameters)} parameter(s).")
            request_body_param = self._find_request_body_parameter_spring(method_parameters)
            if request_body_param:
                param_type = request_body_param.get("type")
                self.logger.debug(f"Found @RequestBody parameter. Original type: '{param_type}'")
                base_type = self._get_base_type(param_type)
                self.logger.debug(f"Base type after parsing: '{base_type}'")
                if self._is_potential_dto(base_type):
                    self.logger.info(f"SUCCESS: Identified Request DTO: {base_type}")
                    seed_component_fqns.add(base_type)
                else:
                    self.logger.debug(f"Type '{base_type}' was not considered a potential DTO. Not adding.")
            else:
                self.logger.debug("No @RequestBody parameter found for this method.")

            # --- 2. Discover Response Body component from return type ---
            return_type_fqn = method_info.get("returnType")
            self.logger.debug(f"Inspecting return type. Original: '{return_type_fqn}'")

            if return_type_fqn and "ResponseEntity" in return_type_fqn:
                match = re.search(r'ResponseEntity<([^>]+)>', return_type_fqn)
                if match:
                    unwrapped_type = match.group(1).strip()
                    self.logger.debug(f"Unwrapped ResponseEntity to: '{unwrapped_type}'")
                    return_type_fqn = unwrapped_type
            
            base_return_type = self._get_base_type(return_type_fqn)
            self.logger.debug(f"Base return type after parsing: '{base_return_type}'")
            if self._is_potential_dto(base_return_type):
                self.logger.info(f"SUCCESS: Identified Response DTO: {base_return_type}")
                seed_component_fqns.add(base_return_type)
            else:
                self.logger.debug(f"Return type '{base_return_type}' was not considered a potential DTO. Not adding.")

        self.logger.info("--- Seed Component Discovery Finished ---")
        return seed_component_fqns
    
    def _collect_transitive_component_fqns(self, fqn: str, all_components_info: Dict[str, Dict], implemented_interface_fqn: Optional[str]=None):
        """
        PHASE 2 HELPER: Recursively discovers the complete set of component FQNs
        (POJOs, Enums, Parents) related to a starting FQN.

        This function's ONLY purpose is to populate a set with names. It does not
        fetch code or build rich context.

        Args:
            fqn: The FQN to start the discovery from.
            all_fqns_set: The set that accumulates all discovered FQNs.
        """
        # Base cases for recursion:
        # 1. We already processed this FQN.
        # 2. It's not a valid FQN.
        # 3. It's a primitive/common type that we don't consider a component.
        self.logger.info(f"[RECURSE] ==> Analyzing FQN: '{fqn}'.")

        # --- Base Case 1: Already processed or not a potential component ---
        if fqn in all_components_info:
            self.logger.info(f"[RECURSE] STOP! '{fqn}' is already in the component map. Returning.")
            return
        if not self._is_potential_dto(fqn):
            return
        
        if not fqn:
            return

        self.logger.debug(f"Dependency Discovery: Processing {fqn}")
        
        class_info = self.code_analyzer.get_symbol_info(fqn, self.project_path, SymbolType.CLASS)
        if not class_info:
            return

        is_abstract_or_interface = class_info.get("isInterface") or class_info.get("isAbstract")
        if is_abstract_or_interface:
            # Improved logging to distinguish the two cases.
            kind = "INTERFACE" if class_info.get("isInterface") else "ABSTRACT CLASS"
            self.logger.info(f"[RECURSE] '{fqn}' is an {kind}. It will not be added...")
            concrete_implementations = self._find_and_filter_implementations(fqn)
            for impl_fqn in concrete_implementations:
                # RECURSIVE CALL: We pass the interface's FQN down to the implementation.
                # The implementation will be responsible for adding itself to the map.
                self._collect_transitive_component_fqns(
                    fqn=impl_fqn, 
                    all_components_info=all_components_info,
                    implemented_interface_fqn=fqn  # Pass the context
                )
            # An interface's job is done after it kicks off recursion for its children.
            return 
        
        self.logger.info(f"[RECURSE] '{fqn}' is a CONCRETE class. Adding to component map.")
        # 1. Add the component to the map to mark it as "visited" and create its entry.
        all_components_info[fqn] = {}

        # 2. Populate its information (type, parents, etc.)
        if class_info.get("isEnum"):
            all_components_info[fqn]['component_type'] = 'enum'
        else:
            all_components_info[fqn]['component_type'] = 'dto'
            
        all_components_info[fqn]['parentClasses'] = class_info.get("parentClasses", [])
        
        # 3. Add the metadata if it was passed down from an interface
        if implemented_interface_fqn:
            all_components_info[fqn]['di_discovered'] = True
            all_components_info[fqn]['implemented_interface'] = implemented_interface_fqn

        dependencies_to_scan: Set[str] = set()
    
        # Add parents (which could be other classes or interfaces)
        for parent_fqn in class_info.get("parentClasses", []):
            dependencies_to_scan.add(parent_fqn)
            
        # Add field types
        for field in class_info.get("fields", []):
            base_type = self._get_base_type(field.get("type"))
            if base_type:
                dependencies_to_scan.add(base_type)

        self.logger.info(f"[RECURSE] Dependencies to scan for concrete class '{fqn}': {list(dependencies_to_scan)}")

        for dep_fqn in dependencies_to_scan:
            self._collect_transitive_component_fqns(dep_fqn, all_components_info)
        
        self.logger.info(f"[RECURSE] <== Finished processing for concrete class: '{fqn}'.")

    def _topological_sort(self, adj: Dict[str, Set[str]], in_degree: Dict[str, int]) -> List[str]:
        """
        Performs a topological sort on the component dependency graph using Kahn's algorithm.
        This version correctly handles the queue as a FIFO structure to respect dependencies
        and includes a robust fallback for handling cycles.
        """
        self.logger.info("--- Starting Topological Sort ---")

        # Initialize the queue with all nodes that have an in-degree of 0.
        # Sorting here ensures a deterministic starting order for nodes without dependencies.
        initial_zero_degree_nodes = sorted([fqn for fqn, degree in in_degree.items() if degree == 0])
        self.logger.info(f"Initial nodes with in-degree 0: {json.dumps(initial_zero_degree_nodes, indent=2)}")
        
        # Use a deque for efficient popleft() operations (O(1) complexity).
        queue = deque(initial_zero_degree_nodes)
        sorted_list = []
        
        processed_count = 0
        while queue:
            # Dequeue the next node to process.
            u = queue.popleft()
            sorted_list.append(u)
            processed_count += 1
            
            # For each neighbor of the processed node, decrement its in-degree.
            # Sorting neighbors ensures deterministic behavior if multiple nodes become ready at once.
            for v in sorted(list(adj.get(u, []))):
                in_degree[v] -= 1
                # If a neighbor's in-degree becomes 0, it's ready to be processed.
                if in_degree[v] == 0:
                    queue.append(v)

        # After the loop, check if all nodes were processed. If not, a cycle exists.
        if len(sorted_list) != len(adj):
            self.logger.warning(
                f"Cycle detected in component dependencies. {len(adj) - len(sorted_list)} nodes remain."
            )
            # Handle the remaining nodes that are part of a cycle.
            # This is a fallback to ensure all components are included, though their internal order is not guaranteed.
            cycled_nodes = {fqn for fqn in adj if in_degree.get(fqn, 0) > 0}
            self.logger.warning(f"Remaining nodes with in-degree > 0: {sorted(list(cycled_nodes))}")
            sorted_list.extend(sorted(list(cycled_nodes)))
        
        self.logger.info("--- Topological Sort Finished ---")
        return sorted_list
    
    def _build_dependency_graph_from_rich_context(self, components_map: Dict[str, Dict[str, Any]]) -> tuple[Dict[str, Set[str]], Dict[str, int]]:
        """
        Builds a complete dependency graph for ALL components (top-level and transient)
        by analyzing the provided rich context map.

        NOTE on methodology: This function intentionally includes all dependencies,
        including external JDK or library classes (like java.lang.Enum), in its
        initial set of graph nodes. This allows for a complete theoretical graph.
        However, it only creates dependency edges between nodes that exist within
        the analyzed project's source code. The final topological sort result is
        then filtered to only include the original top-level project components.
        """
        self.logger.info("--- Building Self-Sufficient Dependency Graph from Rich Context ---")

        # --- STEP 1: Discover ALL unique nodes ---
        all_nodes: Set[str] = set(components_map.keys())
        transient_nodes_context: Dict[str, Dict[str, Any]] = {}
        
        # Using a list to preserve order for easier debugging
        nodes_to_discover = list(components_map.items())
        
        # This loop is just to ensure all nested dependencies are added to all_nodes
        i = 0
        while i < len(nodes_to_discover):
            fqn, rich_context = nodes_to_discover[i]
            i += 1
            
            for parent in rich_context.get('parent_classes', []):
                parent_fqn = parent.get('name')
                if parent_fqn and parent_fqn not in all_nodes:
                    all_nodes.add(parent_fqn)
                    transient_nodes_context[parent_fqn] = parent
                    # We need to process this new node as well, but can't modify list while iterating
                    # For now, let's just add it. A more robust solution might re-queue.

            for data_class in rich_context.get('data_classes', []):
                dep_fqn = data_class.get('qualifiedName')
                if dep_fqn and dep_fqn not in all_nodes:
                    all_nodes.add(dep_fqn)
                    transient_nodes_context[dep_fqn] = data_class
        
        all_nodes.discard(None)
        
        self.logger.info(f"Discovered {len(all_nodes)} total unique nodes for graph construction.")
        self.logger.info(f"--- ALL NODES IN GRAPH ---:\n{json.dumps(sorted(list(all_nodes)), indent=2)}")

        # --- STEP 2: Initialize Graph Data Structures ---
        adj: Dict[str, Set[str]] = {fqn: set() for fqn in all_nodes}
        in_degree: Dict[str, int] = {fqn: 0 for fqn in all_nodes}

        # --- STEP 3: Build Edges ---
        self.logger.info("--- Building Dependency Edges ---")
        for fqn in sorted(list(all_nodes)): # Sort for deterministic logging
            self.logger.info(f"\n========== Analyzing Node: '{fqn}' ==========")
            
            context_for_path = components_map.get(fqn) or transient_nodes_context.get(fqn)
            if not context_for_path or not context_for_path.get('path'):
                self.logger.warning(f"  [SKIPPING] Could not find file path for node '{fqn}'.")
                continue
                
            symbol_info = self.code_analyzer.get_symbol_info(fqn, context_for_path.get('path'), SymbolType.CLASS)
            if not symbol_info:
                self.logger.warning(f"  [SKIPPING] Could not get symbol_info for node '{fqn}'.")
                continue
                
            # --- A) Handle INHERITANCE/IMPLEMENTATION dependencies ---
            parent_classes = symbol_info.get('parentClasses', [])
            self.logger.debug(f"  [INHERITANCE] Found parents/interfaces: {parent_classes}")
            for parent_fqn in parent_classes:
                self.logger.debug(f"    - Checking parent '{parent_fqn}'...")
                if parent_fqn in all_nodes:
                    # Get info about the parent to see if it's an interface or a class
                    parent_context = components_map.get(parent_fqn) or transient_nodes_context.get(parent_fqn)
                    if not parent_context or not parent_context.get('path'):
                        self.logger.debug(f"    -> SKIPPING parent '{parent_fqn}': No source path found (likely a JDK or library class).")
                        continue

                    parent_info = self.code_analyzer.get_symbol_info(parent_fqn, parent_context.get('path'), SymbolType.CLASS)
                    if not parent_info: continue

                    # --- NEW LOGIC ---
                    if parent_info.get("isInterface"):
                        # Case 1: The parent is an INTERFACE.
                        # The interface's schema will need a oneOf, so it depends on the child.
                        # Edge: Child -> Parent
                        if parent_fqn not in adj.get(fqn, set()):
                            adj[fqn].add(parent_fqn)
                            in_degree[parent_fqn] += 1
                            self.logger.debug(f"    -> CREATED INTERFACE EDGE: {fqn} -> {parent_fqn}")
                    else:
                        # Case 2: The parent is a CLASS (inheritance).
                        # The child's schema depends on the parent's.
                        # Edge: Parent -> Child
                        if fqn not in adj.get(parent_fqn, set()):
                            adj[parent_fqn].add(fqn)
                            in_degree[fqn] += 1
                            self.logger.debug(f"    -> CREATED INHERITANCE EDGE: {parent_fqn} -> {fqn}")

            # --- B) Handle FIELD dependencies ---
            all_properties = self._get_all_properties_for_class(fqn)
            self.logger.debug(f"  [FIELDS] Found {len(all_properties)} properties/fields to check.")
            for field in all_properties:
                field_name = field.get("name")
                field_type = field.get("type")
                self.logger.debug(f"    - Checking field '{field_name}' with type '{field_type}'...")
                
                dep_fqn = self._get_base_type(field.get('type'))
                self.logger.debug(f"      Base type is '{dep_fqn}'.")

                if dep_fqn and dep_fqn in all_nodes and dep_fqn != fqn:
                    if fqn not in adj.get(dep_fqn, set()):
                        adj[dep_fqn].add(fqn)
                        in_degree[fqn] += 1
                        self.logger.info(f"    - SUCCESS: Created FIELD edge: {dep_fqn} -> {fqn}. New in_degree for '{fqn}' is {in_degree[fqn]}")
                    else:
                        self.logger.debug(f"    - INFO: Edge {dep_fqn} -> {fqn} already exists.")
                elif not dep_fqn:
                    self.logger.debug(f"      FAIL: Base type could not be determined.")
                elif dep_fqn == fqn:
                    self.logger.debug(f"      INFO: Field is a self-reference. No edge created.")
                else: # dep_fqn not in all_nodes
                    self.logger.warning(f"    - FAIL: Field type '{dep_fqn}' is NOT in the set of all_nodes. No edge created.")

        # --- STEP 4: Final Logging for Verification ---
        self.logger.info("\n--- Dependency Graph Construction Complete ---")
        self.logger.info("Final Adjacency List (adj):")
        for key, value in sorted(adj.items()):
            if value:
                self.logger.info(f"  {key}: {sorted(list(value))}")

        self.logger.info("Final In-Degree Map (in_degree):")
        for key, value in sorted(in_degree.items()):
            self.logger.info(f"  {key}: {value}")
            
        nodes_with_zero_in_degree = sorted([fqn for fqn, degree in in_degree.items() if degree == 0])
        self.logger.info(f"Found {len(nodes_with_zero_in_degree)} nodes with in-degree 0 (potential sort start points): {nodes_with_zero_in_degree}")
                        
        return adj, in_degree

    def get_schema_components(self) -> Dict[str, Dict[str, Any]]:
        """
        Extracts schema components (POJOs/DTOs) by discovering which classes are
        actually used in endpoint request bodies and responses, then recursively
        finding all dependencies.
        """
        if self._cached_components is not None:
            self.logger.debug("Returning cached schema components.")
            return self._cached_components

        # --- PHASE 1: SEED DISCOVERY ---
        self.logger.info("Phase 1: Discovering 'seed' components from actual endpoint usage...")
        self.get_endpoints() # Ensures self.endpoints is populated
        if not self.endpoints:
            self.logger.warning("No endpoints found, cannot discover components.")
            return {}

        seed_component_fqns = self._discover_seed_components()
        self.logger.info(f"Phase 1 complete. Found {len(seed_component_fqns)} seed components.")

        # --- PHASE 2: FULL DEPENDENCY DISCOVERY ---
        self.logger.info("Phase 2: Recursively discovering all dependencies for seed components...")
        all_components_info: Dict[str, Dict] = {}
        for fqn in seed_component_fqns:
            self._collect_transitive_component_fqns(fqn, all_components_info, None)

        all_component_fqns = all_components_info.keys()
        self.logger.info(f"Phase 2 complete. Total components including dependencies: {len(all_component_fqns)}.")
        # --- PHASE 3: DEPENDENCY GRAPH & TOPOLOGICAL SORT ---
        # self.logger.info("Phase 3: Building dependency graph and sorting components for processing...")
        # import pdb; pdb.set_trace()
        # adj_graph, in_degree = self._build_dependency_graph(set(all_component_fqns))
        # sorted_fqns = self._topological_sort(adj_graph, in_degree)
        # self.logger.info(f"Phase 3 complete. Sorted {len(sorted_fqns)} components.")

        # --- PHASE 4: RICH CONTEXT BUILDING ---
        self.logger.info("Phase 4: Building rich context for each component in dependency order...")
        final_components_map: Dict[str, Dict[str, Any]] = {}
        for fqn in all_component_fqns:
            rich_context = self.build_concrete_component_context(fqn)
            if rich_context:
                rich_context['discovery_info'] = all_components_info.get(fqn, {})
                final_components_map[fqn] = rich_context

        self.logger.info("Phase 4: Building dependency graph from rich context...")

        adj_graph, in_degree = self._build_dependency_graph_from_rich_context(final_components_map)
        all_sorted_fqns = self._topological_sort(adj_graph, in_degree)

        # --- NEW: Filter the sorted list to keep only the original top-level components ---
        top_level_fqns = set(final_components_map.keys())
        final_sorted_top_level_fqns = [fqn for fqn in all_sorted_fqns if fqn in top_level_fqns]

        self.logger.info(f"Final sorted order for top-level components: {final_sorted_top_level_fqns}")

        # Reorder the final map according to the filtered sort
        self._cached_components = {fqn: final_components_map[fqn] for fqn in final_sorted_top_level_fqns}
        return self._cached_components

    def _find_and_cache_error_handlers(self) -> List[Dict[str, Any]]:
        """
        Scans all analyzed classes once to find any annotated with @ControllerAdvice
        or @RestControllerAdvice, caches, and returns their full code context.
        """
        error_handlers = []
        all_classes = self.code_analyzer.analysis_results.get("classIdentifiers", [])
        
        CONTROLLER_ADVICE_FQN = "Lorg/springframework/web/bind/annotation/ControllerAdvice;"
        REST_CONTROLLER_ADVICE_FQN = "Lorg/springframework/web/bind/annotation/RestControllerAdvice;"
        
        for class_info in all_classes:
            is_advice = False
            for ann in class_info.get("annotations", []):
                if ann.get("type") in [CONTROLLER_ADVICE_FQN, REST_CONTROLLER_ADVICE_FQN]:
                    is_advice = True
                    break
            
            if is_advice:
                class_fqn = class_info.get("className")
                self.logger.info(f"Found global error handler: {class_fqn}")
                class_context = self._get_full_class_context(class_fqn)
                if class_context:
                    error_handlers.append(class_context)
                    
        return error_handlers

    def _get_full_class_context(self, class_fqn: str) -> Optional[Dict[str, Any]]:
        """
        Helper to fetch the full code snippet and metadata for a single class.
        """
        class_info = self.code_analyzer.get_symbol_info(class_fqn, self.project_path, SymbolType.CLASS)
        if not class_info:
            return None
        
        file_path = class_info.get("classFileName") or class_info.get("filePath")
        start_line, end_line = class_info.get("startLine"), class_info.get("endLine")

        if not (file_path and start_line and end_line):
            return None

        code_snippet = self.code_analyzer.get_code_snippet(file_path, start_line, end_line)
        if not code_snippet:
            return None

        return {
            "name": class_fqn.split('.')[-1],
            "type": "class",
            "path": file_path,
            "code": code_snippet,
            "qualifiedName": class_fqn
        }

    def _get_single_method_context_by_signature(self, class_fqn: str, method_signature: str) -> Optional[Dict[str, Any]]:
        """
        Gathers all context related to a single Java method signature, adapted for Spring Boot.
        """
        class_info = self.code_analyzer.get_symbol_info(class_fqn, self.project_path, SymbolType.CLASS)
        if not class_info: return None

        method_info = next((m for m in class_info.get("functions", []) if m.get("signature") == method_signature), None)
        if not method_info: return None
        
        handler_ctx = {
            "name": method_info.get("methodName"),
            "type": "spring.method",
            "path": class_info.get("classFileName"),
            "code": self.code_analyzer.get_code_snippet(
                class_info.get("classFileName"), method_info.get("startLine"), method_info.get("endLine")
            ) or "// Code not available",
            "class_name_fqn": class_fqn,
            "method_parameters_info": method_info.get("parameters", []),
            "returnType": method_info.get("returnType", "void")
        }
        
        pojos_to_get: Set[str] = set()
        
        # Discover response POJO from return type (handles ResponseEntity<T>)
        return_type = handler_ctx["returnType"]
        if "ResponseEntity" in return_type:
             match = re.search(r'<([^>]+)>', return_type)
             if match:
                return_type = match.group(1).strip()
        
        base_return_type = self._get_base_type(return_type)
        if self._is_potential_dto(base_return_type):
            pojos_to_get.add(base_return_type)
            
        # Discover request POJO via @RequestBody annotation
        req_body_param = self._find_request_body_parameter_spring(handler_ctx["method_parameters_info"])
        if req_body_param:
            base_req_type = self._get_base_type(req_body_param.get("type"))
            if self._is_potential_dto(base_req_type):
                pojos_to_get.add(base_req_type)

        # Get the rich context for all discovered POJOs from the component "library"
        all_components = self.get_schema_components()
        final_pojo_contexts = [all_components[fqn] for fqn in pojos_to_get if fqn in all_components]
        
        # Get extra context (e.g., services called by the handler)
        extra_context = self._gather_dependencies_recursively_relaxed(start_fqn=class_fqn, visited_fqns=set(), max_depth=3)
        
        return {
            "handler": handler_ctx,
            "handler_full": self._get_full_class_context(class_fqn),
            "pojos": final_pojo_contexts,
            "extra_context": extra_context
        }

    def get_endpoint_context(self, endpoint: Dict[str, Any]) -> Dict[str, Any]:
        """
        Builds a single, combined context for a given Spring Boot endpoint object,
        including global error handlers and all related code.
        """
        metadata = endpoint.get("metadata", {})
        handler_class_fqn = metadata.get("handler_class_fqn")
        if not handler_class_fqn:
            self.logger.error("Endpoint metadata is missing 'handler_class_fqn'.")
            return {}

        # --- Initialize the final context object ---
        final_context = {
            "endpoint": endpoint,
            "handler_methods": [],
            "pojos": [],
            "handler_classes": [],
            "framework_settings": {"framework": "springboot", "settings": {}},
            "other_context": [],
            "error_handlers": []
        }
        # --- Step 1: Gather and Cache Global Error Handlers (@ControllerAdvice) ---
        if self._cached_error_handlers is None:
            self.logger.info("First endpoint: Scanning for global @ControllerAdvice classes...")
            self._cached_error_handlers = self._find_and_cache_error_handlers()
        final_context["error_handlers"] = self._cached_error_handlers

        # --- Step 2: Iterate through each Java method implementing the endpoint ---
        processed_pojo_fqns: Set[str] = set()
        dynamic_context_workers: List[Dict[str, Any]] = []
        processed_dynamic_workers: Set[str] = set()
        for method_details in metadata.get("implementing_methods", []):
            method_signature = method_details.get("signature")
            if not method_signature:
                continue
            
            handler_method_info = self._get_method_info_from_signature(handler_class_fqn, method_signature)
            if not handler_method_info:
                continue

            parameter_style = self._detect_parameter_style(handler_method_info.get("parameters", []))
            if parameter_style == 'DYNAMIC_SERVLET':
                self.logger.info(f"Dynamic style detected for '{method_signature}'. Activating trace.")
                # Call the new, intelligent tracer
                traced_workers = self._trace_dynamic_request_context(
                    handler_class_fqn,
                    method_signature
                )
                for worker in traced_workers:
                    worker_fqn = worker.get("qualifiedName")
                    if worker_fqn and worker_fqn not in processed_dynamic_workers:
                        dynamic_context_workers.append(worker)
                        processed_dynamic_workers.add(worker_fqn)

            single_method_context = self._get_single_method_context_by_signature(
                handler_class_fqn, method_signature
            )
            if not single_method_context:
                continue

            # --- Step 3: Aggregate data from each implementing method ---
            final_context["handler_methods"].append(single_method_context["handler"])
            if single_method_context["handler_full"]:
                final_context["handler_classes"].append(single_method_context["handler_full"])
            final_context["other_context"].extend(single_method_context["extra_context"])
            
            for pojo in single_method_context.get("pojos", []):
                pojo_fqn = pojo.get("qualifiedName")
                if pojo_fqn and pojo_fqn not in processed_pojo_fqns:
                    final_context["pojos"].append(pojo)
                    processed_pojo_fqns.add(pojo_fqn)
        
        # --- Step 4: Finalize and Deduplicate ---
        final_context["handler_classes"] = list({c['qualifiedName']: c for c in final_context["handler_classes"]}.values())
        final_context["other_context"] = list({c['qualifiedName']: c for c in final_context["other_context"]}.values())
        
        if final_context["handler_methods"]:
            final_context["handler"] = final_context["handler_methods"][0]
        
        return final_context

    def _get_method_info_from_signature(self, class_fqn: str, method_signature: str) -> Optional[Dict[str, Any]]:
        """Helper to fetch full method details from soot-analysis.json."""
        class_info = self.code_analyzer.get_symbol_info(class_fqn, self.project_path, SymbolType.CLASS)
        if not class_info: return None
        return next((m for m in class_info.get("functions", []) if m.get("signature") == method_signature), None)

    def _trace_dynamic_request_context(self, handler_class_fqn: str, handler_method_signature: str, max_depth: int = 3) -> List[Dict[str, Any]]:
        """
        Performs a targeted trace starting from an HttpServletRequest parameter to find
        all 'worker' classes that process it, gathering their full code context.
        This version includes heavy logging for debugging purposes.
        """
        self.logger.info(f"--- [TRACE_START] Tracing dynamic context for: {handler_class_fqn} -> {handler_method_signature}")
        
        # A queue for BFS traversal. Stores tuples of (class_fqn, method_signature).
        queue = deque([(handler_class_fqn, handler_method_signature)])
        
        # Sets to avoid redundant processing.
        visited_methods: Set[str] = set()
        accumulated_context: Dict[str, Dict[str, Any]] = {} # Use dict with FQN as key to auto-deduplicate classes
        
        depth = 0
        while queue and depth < max_depth:
            level_size = len(queue)
            self.logger.debug(f"--- [TRACE_DEPTH {depth}] --- Processing {level_size} methods in queue.")
            
            for i in range(level_size):
                current_class_fqn, current_method_sig = queue.popleft()
                method_key = f"{current_class_fqn}:{current_method_sig}"
                
                if method_key in visited_methods:
                    self.logger.debug(f"[{i+1}/{level_size}] Method '{method_key}' already visited. Skipping.")
                    continue
                visited_methods.add(method_key)

                self.logger.info(f"[{i+1}/{level_size}] Now processing method: {method_key}")

                method_info = self._get_method_info_from_signature(current_class_fqn, current_method_sig)
                if not method_info:
                    self.logger.warning(f"  -> Could not find method details for '{current_method_sig}'. Stopping this trace path.")
                    continue

                # STEP 1: Find the HttpServletRequest parameter to trace
                http_req_param_name = None
                method_params = method_info.get("parameters", [])
                self.logger.debug(f"  -> Method has {len(method_params)} parameter(s). Searching for HttpServletRequest.")
                for param in method_params:
                    if param.get("type") == "javax.servlet.http.HttpServletRequest":
                        http_req_param_name = param.get("name")
                        break
                
                if not http_req_param_name:
                    self.logger.info(f"  -> Trace stopped on this path: Method does not accept an HttpServletRequest parameter.")
                    continue
                
                self.logger.info(f"  -> Found HttpServletRequest parameter to trace. Variable name: '{http_req_param_name}'")

                # STEP 2: Inspect all method calls made from within the current method's body
                function_calls = method_info.get("functionNames", [])
                self.logger.info(f"  -> Inspecting {len(function_calls)} function calls made by this method.")
                if not function_calls:
                    self.logger.warning(f"  -> CRITICAL: The 'functionNames' key is missing or empty in the static analysis data for this method. The trace cannot proceed.")
                    # Also log the full method_info object for complete debugging
                    self.logger.debug(f"  -> FULL METHOD_INFO DUMP: {json.dumps(method_info, indent=2)}")

                for call_index, call in enumerate(function_calls):
                    call_args = call.get("arguments", [])
                    target_class_fqn = call.get("declaringClass")
                    target_method_name = call.get("simpleName")
                    self.logger.debug(f"    - Call #{call_index+1}: {target_class_fqn}.{target_method_name}({', '.join(call_args)})")
                    
                    # STEP 3: Check if our traced parameter is used in this call
                    if http_req_param_name in call_args:
                        self.logger.info(f"    - MATCH! Traced parameter '{http_req_param_name}' is used in this call.")
                        
                        if not target_class_fqn or self._is_primitive_or_common(target_class_fqn):
                            self.logger.debug(f"    - Discarding match: Target class '{target_class_fqn}' is common or primitive.")
                            continue

                        # We found a worker class!
                        if target_class_fqn not in accumulated_context:
                            self.logger.info(f"    - DISCOVERY! Found new worker class: '{target_class_fqn}'. Fetching its context.")
                            class_context = self._get_full_class_context(target_class_fqn)
                            if class_context:
                                accumulated_context[target_class_fqn] = class_context
                                self.logger.debug(f"    - Successfully added context for '{target_class_fqn}'.")
                            else:
                                self.logger.warning(f"    - Failed to get context for worker class '{target_class_fqn}'.")
                        else:
                            self.logger.debug(f"    - Worker class '{target_class_fqn}' already processed. Skipping context fetch.")

                        # STEP 4: Enqueue the called method to continue the trace
                        target_class_info = self.code_analyzer.get_symbol_info(target_class_fqn, self.project_path, SymbolType.CLASS)
                        if target_class_info:
                            for func_in_worker in target_class_info.get("functions", []):
                                # Simplistic match by name. For constructors, name is "<init>".
                                if func_in_worker.get("methodName") == target_method_name:
                                    next_method_sig = func_in_worker.get("signature")
                                    if f"{target_class_fqn}:{next_method_sig}" not in visited_methods:
                                        self.logger.info(f"    - ENQUEUEING for next level: {target_class_fqn} -> {next_method_sig}")
                                        queue.append((target_class_fqn, next_method_sig))
                                        break # Assume first match is correct for simplicity
                    else:
                        self.logger.debug(f"    - No match. Traced parameter '{http_req_param_name}' not in arguments.")

            depth += 1
        
        if not queue and depth < max_depth:
            self.logger.debug(f"--- [TRACE_END] Trace finished because queue is empty. ---")
        elif depth >= max_depth:
            self.logger.warning(f"--- [TRACE_END] Trace finished because max depth ({max_depth}) was reached. ---")

        final_worker_count = len(accumulated_context)
        self.logger.info(f"Dynamic trace complete. Discovered {final_worker_count} worker classes: {list(accumulated_context.keys())}")
        return list(accumulated_context.values())
      
    def _get_java_symbol_key(self, qualified_name: Optional[str], definition_file_path: Optional[str], symbol_type_info: Any) -> Optional[str]:
            """
            Generates a consistent, unique key for a Java symbol.
            Key format: "absolute/path/to/file.java:com.package.ClassName:TYPE"
            """
            if not qualified_name or not definition_file_path:
                return None
            
            type_str_upper = ""
            if isinstance(symbol_type_info, SymbolType):
                type_str_upper = symbol_type_info.name.upper()
            elif isinstance(symbol_type_info, str):
                # Normalize types like 'pojo', 'dto', 'enum' to 'CLASS' for keying purposes
                type_lower = symbol_type_info.lower()
                if type_lower in ['pojo', 'dto', 'enum', 'class']:
                    type_str_upper = "CLASS"
                else:
                    type_str_upper = type_lower.upper()
            else:
                return None
                
            norm_path = os.path.normpath(os.path.abspath(definition_file_path))
            return f"{norm_path}:{qualified_name}:{type_str_upper}"

    def _detect_parameter_style(self, method_parameters_info: List[Dict[str, Any]]) -> str:
        """
        Analyzes a method's parameters to determine its parameter binding style.
        
        Returns:
            - 'ANNOTATED': Modern Spring style with @RequestParam, @PathVariable, etc.
            - 'DYNAMIC_SERVLET': Classic style using HttpServletRequest.
            - 'UNKNOWN': No discernible pattern for parameters.
        """
        has_http_servlet_request = False
        has_spring_annotations = False

        SPRING_PARAM_ANNOTATIONS = {
            "Lorg/springframework/web/bind/annotation/RequestParam;",
            "Lorg/springframework/web/bind/annotation/PathVariable;",
            "Lorg/springframework/web/bind/annotation/RequestHeader;",
            "Lorg/springframework/web/bind/annotation/RequestBody;",
        }

        for param in method_parameters_info:
            if param.get("type") == "javax.servlet.http.HttpServletRequest":
                has_http_servlet_request = True

            for ann in param.get("annotations", []):
                if ann.get("type") in SPRING_PARAM_ANNOTATIONS:
                    has_spring_annotations = True
                    break
            if has_spring_annotations:
                break
                
        if has_http_servlet_request and not has_spring_annotations:
            self.logger.info("Detected DYNAMIC_SERVLET parameter style.")
            return 'DYNAMIC_SERVLET'
        
        if has_spring_annotations:
            self.logger.info("Detected ANNOTATED parameter style.")
            return 'ANNOTATED'
            
        self.logger.info("No specific parameter style detected (e.g., no parameters).")
        return 'UNKNOWN'
    
    def optimize_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deduplicates the context by identifying all symbols in the primary context sections
        (handler, pojos, error_handlers) and removing them from the 'other_context' list.
        """
        optimized_ctx = copy.deepcopy(context)
        
        primary_symbol_keys: Set[str] = set()

        # --- Step 1: Gather keys from all PRIMARY context sections ---
        
        # Key from the handler class itself
        # Note: 'handler_classes' is a list of full class contexts
        for handler_class in optimized_ctx.get("handler_classes", []):
            key = self._get_java_symbol_key(
                handler_class.get("qualifiedName"),
                handler_class.get("path"),
                "CLASS"
            )
            if key: primary_symbol_keys.add(key)

        # Keys from all associated POJOs and their nested dependencies
        for pojo in optimized_ctx.get("pojos", []):
            key = self._get_java_symbol_key(pojo.get("qualifiedName"), pojo.get("path"), "CLASS")
            if key: primary_symbol_keys.add(key)
            
            # Also add keys for any nested DTOs that came with the POJO's rich context
            for nested_dto in pojo.get("data_classes", []):
                key = self._get_java_symbol_key(nested_dto.get("qualifiedName"), nested_dto.get("path"), "CLASS")
                if key: primary_symbol_keys.add(key)

        # Keys from all global error handlers
        for error_handler in optimized_ctx.get("error_handlers", []):
            key = self._get_java_symbol_key(error_handler.get("qualifiedName"), error_handler.get("path"), "CLASS")
            if key: primary_symbol_keys.add(key)
            
        self.logger.debug(f"Optimize Context: Collected {len(primary_symbol_keys)} primary symbol keys to use for deduplication.")

        # --- Step 2: Filter the "other_context" list ---
        
        original_other_context = optimized_ctx.get("other_context", [])
        if not original_other_context:
            return optimized_ctx # Nothing to do
            
        optimized_other_context = []
        
        for item in original_other_context:
            # Generate the key for this item from the "other" list
            # The type should be "class" or "enum" from the recursive gatherer, which _get_java_symbol_key handles
            item_key = self._get_java_symbol_key(
                item.get("qualifiedName"),
                item.get("path"),
                item.get("type", "CLASS") # Default to class if type is missing
            )

            # The core logic: only keep it if its key is NOT in the primary set
            if item_key and item_key not in primary_symbol_keys:
                optimized_other_context.append(item)
                # Add the key to the set now to prevent duplicates *within* other_context
                primary_symbol_keys.add(item_key)
            else:
                self.logger.debug(f"Optimize Context: Removing '{item.get('qualifiedName')}' from other_context (redundant).")
        
        removed_count = len(original_other_context) - len(optimized_other_context)
        if removed_count > 0:
            self.logger.info(f"Optimize Context: Removed {removed_count} redundant symbols from 'other_context'.")

        optimized_ctx["other_context"] = optimized_other_context
        return optimized_ctx
    
    def parse_missing_symbols_response(self, response_content: str) -> List[Dict[str, Any]]:
        # (Assuming the previous version of this for Jersey/generic is fine)
        # Key output: list of {"name": ..., "type": SymbolType.XXX, "context_path": ...}
        required_symbols = []
        if not response_content:
            self.logger.debug("Jersey: Received empty response for missing symbols.")
            return required_symbols
        try:
            # LLM might wrap JSON in ```json ... ``` or have other text
            json_match = re.search(r"\{[\s\S]*\}", response_content) # More robust regex for JSON block
            if not json_match:
                self.logger.warning(f"Jersey: Could not find JSON object in missing symbols response: {response_content[:300]}...")
                return required_symbols

            extracted_json_str = json_match.group(0)
            data = json.loads(extracted_json_str)
            
            symbols_list_from_llm = data.get("missing_symbols", [])

            if not isinstance(symbols_list_from_llm, list):
                self.logger.warning(f"Jersey: Expected 'missing_symbols' to be a list, got: {type(symbols_list_from_llm)}")
                return required_symbols

            for item_llm in symbols_list_from_llm:
                if isinstance(item_llm, dict) and "name" in item_llm and "type" in item_llm and "context_path" in item_llm:
                    symbol_type_str = item_llm.get("type", "").lower()
                    symbol_type_enum_val = None
                    if symbol_type_str == "class": symbol_type_enum_val = SymbolType.CLASS
                    elif symbol_type_str == "function": symbol_type_enum_val = SymbolType.FUNCTION
                    # elif symbol_type_str == "variable": symbol_type_enum_val = SymbolType.VARIABLE 

                    if symbol_type_enum_val:
                        required_symbols.append({
                            "name": item_llm["name"], # Name as LLM identified it (could be simple or FQN)
                            "type": symbol_type_enum_val,
                            "context_path": item_llm["context_path"] # Path of the file *using* the symbol
                        })
                    else:
                        self.logger.warning(f"Jersey: Unknown/unsupported symbol type '{symbol_type_str}' requested by LLM for '{item_llm.get('name')}'")
                else:
                    self.logger.warning(f"Jersey: Skipping malformed item in missing_symbols list from LLM: {item_llm}")
            self.logger.debug(f"Jersey: Parsed {len(required_symbols)} required symbols from LLM response.")
            return required_symbols
        except json.JSONDecodeError as e:
            self.logger.error(f"Jersey: Failed to decode JSON from missing symbols response: {e}. Response: {response_content[:500]}...")
            return []
        except Exception as e:
            self.logger.error(f"Jersey: Unexpected error parsing missing symbols response: {e}", exc_info=True)
            return []
    
    def get_missing_context(self, initial_context: Dict[str, Any], required_symbols: List[Dict[str, Any]], max_depth: int = 2) -> Dict[str, Any]:
        if not required_symbols:
            self.logger.debug("Jersey: No required symbols provided, returning initial context.")
            return initial_context

        augmented_context = copy.deepcopy(initial_context)
        extra_context_list: List[Dict[str, Any]] = []
        processed_keys_global: Set[str] = set()

        self.logger.info(f"Jersey: Fetching extra context recursively (max_depth={max_depth}) for {len(required_symbols)} initial symbols.")

        for symbol_request in required_symbols:
            symbol_name_from_llm = symbol_request.get("name") # This is the name LLM identified
            symbol_type_enum = symbol_request.get("type")     # This is SymbolType Enum
            referencing_file_path = symbol_request.get("context_path") # Path of file that *used* the symbol

            if not all([symbol_name_from_llm, isinstance(symbol_type_enum, SymbolType), referencing_file_path]):
                 self.logger.error(f"Jersey: Invalid symbol request format for get_missing_context: {symbol_request}. Skipping.")
                 continue
            
            simple_symbol_name = symbol_name_from_llm
            if '.' in symbol_name_from_llm:
                # This handles both FQNs like "a.b.C" and static method calls like "MyClass.myMethod"
                simple_symbol_name = symbol_name_from_llm.split('.')[-1]
                self.logger.debug(f"Identified qualified name '{symbol_name_from_llm}', will search for simple name '{simple_symbol_name}'.")

            self._fetch_recursive_context_java(
                simple_symbol_name, symbol_type_enum, referencing_file_path,
                current_depth=0, max_depth=max_depth,
                processed_keys=processed_keys_global,
                accumulator=extra_context_list
            )
        
        if extra_context_list:
            unique_extra_context = []
            seen_final_keys = set()
            for item in extra_context_list:
                # Key uses 'qualifiedName' which should be the FQN or FQN.method
                key = f"{os.path.abspath(item['path'])}:{item['qualifiedName']}:{item['type']}"
                if key not in seen_final_keys:
                    unique_extra_context.append(item)
                    seen_final_keys.add(key)
            unique_extra_context.sort(key=lambda x: (x['path'], x.get('start_line', 0))) # Sort for consistency
            augmented_context["extra_context"] = unique_extra_context
            self.logger.info(f"Jersey: Added {len(unique_extra_context)} unique symbols to extra_context after recursion.")
        else:
            self.logger.info("Jersey: No extra context symbols were ultimately fetched or added by get_missing_context.")
        
        return augmented_context
          
    @property
    def framework_name(self) -> str:
        return "Spring-Boot"

    @property
    def language_name(self) -> str:
        return "java"

    def get_schema_component_terminology(self) -> str:
        """
        Describes what a schema component represents in a Spring Boot context.
        """
        return "POJO/DTO"

    def _format_endpoint_context_for_prompt(self, endpoint_context: Dict[str, Any]) -> str:
        """
        Formats the structured endpoint context into a string for LLM prompts.
        This is a generic formatter that works for both Jersey and Spring Boot context structures.
        """
        formatted_string_parts = []
        delimiter = "\n===###===\n"

        # --- Handler Formatting ---
        handler_methods = endpoint_context.get("handler_methods", [])
        if handler_methods:
            formatted_string_parts.append("Handler Method Definitions:")
            for idx, handler in enumerate(handler_methods):
                formatted_string_parts.append(f"\n--- Handler Method {idx + 1} of {len(handler_methods)} ---")
                if handler.get('code'):
                    formatted_string_parts.append(f"Source File: {handler.get('path', 'N/A')}")
                    formatted_string_parts.append(f"Code Snippet ({handler.get('name')}):\n```java\n{handler['code']}\n```")
        elif endpoint_context.get("handler"): # Fallback for single handler
             handler = endpoint_context["handler"]
             formatted_string_parts.append(f"Source File: {handler.get('path', 'N/A')}")
             formatted_string_parts.append(f"Code Snippet:\n```java\n{handler.get('code', '# Handler code not available')}\n```")
        else:
            formatted_string_parts.append("# Handler code not available.")

        # --- POJO / DTO Formatting ---
        pojos = endpoint_context.get("pojos", [])
        if pojos:
            formatted_string_parts.append(f"{delimiter}Associated POJOs/DTOs:")
            for pojo in pojos:
                name_key = pojo.get("qualifiedName") or pojo.get("name", "N/A")
                formatted_string_parts.append(f"{delimiter}Source File: {pojo.get('path', 'N/A')}")
                formatted_string_parts.append(f"POJO: {name_key}")
                formatted_string_parts.append(f"Code Snippet:\n```java\n{pojo.get('code', '# Code not available')}\n```")

        # --- Error Handler Formatting ---
        error_handlers = endpoint_context.get("error_handlers", [])
        if error_handlers:
            formatted_string_parts.append(f"{delimiter}Global Error Handlers (@ControllerAdvice):")
            for handler in error_handlers:
                name_key = handler.get("qualifiedName") or handler.get("name", "N/A")
                formatted_string_parts.append(f"{delimiter}Source File: {handler.get('path', 'N/A')}")
                formatted_string_parts.append(f"Error Handler Class: {name_key}")
                formatted_string_parts.append(f"Code Snippet:\n```java\n{handler.get('code', '# Code not available')}\n```")
        
        # --- Other Context Formatting ---
        other_context = endpoint_context.get("other_context", [])
        if other_context:
            formatted_string_parts.append(f"{delimiter}Other Relevant Classes (Services, Repositories, etc.):")
            for item in other_context:
                item_name = item.get("qualifiedName") or item.get("name", "N/A")
                formatted_string_parts.append(f"{delimiter}Source File: {item.get('path', 'N/A')}")
                formatted_string_parts.append(f"Code Snippet (Class: {item_name}):\n```java\n{item.get('code', '# Code not available')}\n```")

        final_string = "\n".join(formatted_string_parts)
        return final_string.strip()
    

    def get_component_system_message(self) -> str:
        """
        Provides the system message for the LLM when generating Spring Boot component schemas.
        """
        # --- SPRING CHANGE ---
        # Changed persona from JAX-RS/JAXB to Spring Boot/Jackson.
        return """You are an expert in Java, Spring Boot, object-oriented design, the Jackson serialization library, and OpenAPI 3.0 specifications.
Your task is to analyze Java Plain Old Java Objects (POJOs), DTOs, or Enums and their related context to generate a corresponding OpenAPI component schema."""
    
    def get_component_field_instructions(self, component_name: str, component_info: Dict[str, Any]) -> str:
        # This is a complete rewrite tailored for Spring Boot and Jackson with meta-reasoning
        simple_name = component_info.get('name', component_name.split('.')[-1])

        # Check if the component is an Enum
        if component_info.get('code', '').lstrip().startswith('public enum'):
            # Provide specific, simpler instructions for Enums
            enum_constants = [
                field['name'] for field in component_info.get('fields_info', [])
                # Filter out compiler-generated fields like $VALUES and instance fields
                if field['name'].isupper() and field.get('type') == component_info.get('qualifiedName')
            ]
            enum_list_str = f"[{', '.join(enum_constants)}]"

            return f"""
            For the Java Enum '{component_info.get('qualifiedName', component_name)}' provided in the context:
            1.  Generate one schema named '{simple_name}'.
            2.  The schema MUST have `type: string`.
            3.  The schema MUST have an `enum` property containing the list of all enum constant names.
            4.  Based on the provided code, the list of enum constants is: {enum_list_str}.

            Example Output:
            ```yaml
            {simple_name}:
            type: string
            enum:
                - CONSTANT_ONE
                - CONSTANT_TWO
            ```
            """
        
        return f"""
        For the Java class '{component_info.get('qualifiedName', component_name)}' provided in the context:

        Generate OpenAPI component schemas for the POJO/DTO named '{simple_name}'.

        ## Analysis Phase - Think Through These Questions First:

        ### Q1: What is the true structure of this **JSON output**?
        - Identify all fields and their Java types
        - Note Jackson annotations (@JsonProperty, @JsonIgnore, @JsonFormat, @JsonSetter) Model the Public Contract, Not the Internal Structure. The final JSON structure is determined by Jackson's serialization rules, not the private field layout of the Java class. Public getters, especially those with @JsonProperty, are the primary source of truth for the output schema.
        - Check for parent classes and their fields

        ### Q2: How does this class behave at runtime?
        - Does the constructor set default values for any fields?
        - Are there @JsonSetter(nulls = Nulls.SKIP) annotations affecting null handling?
        - What happens when fields are missing from incoming JSON?

        ### Q3: What constraints exist on the data?
        - Look for validation annotations (@NotNull, @NotBlank, @NotEmpty, @Size, @Min, @Max, @Pattern)
        - Check if this is an entity with JPA annotations (@Column, @NotNull on entity fields)
        - Are there constants that define limits (MAX_LENGTH, MIN_VALUE)?
        - What validations would cause a 400 Bad Request?

        ### Q4: Which fields are truly required?
        For each field, consider:
        - Does it have @NotNull, @NotBlank, or @NotEmpty?
        - BUT also: Does it have @JsonSetter(nulls = Nulls.SKIP) with a constructor default?
        - For entities: Does the database column allow NULL?
        - Would the API actually reject a request if this field is missing?

        ### Q5: How are special types handled?
        - For dates: Check for @JsonFormat(pattern="...") - use the exact pattern, not standard format
        - For enums: Extract ALL possible values from the enum definition
        - For collections: Identify the element type

        ## Generation Rules Based on Your Analysis:

        ### For each field, define its schema properties:
        - If the field's type is another POJO/DTO (its code is in data_classes), use a $ref following the rules if reference. Example: $ref: '#/components/schemas/{simple_name}OfNestedObject'.

        **Rule for Referencing:**
        - **IF** a field's type is a custom class (like `Address`) AND its name (e.g., `Address`) is in the list of available schemas, you could use a `$ref` if you think the component is used as is.
          Example: `address: {{ $ref: '#/components/schemas/Address' }}`

        - **IF** a field's type is a custom class (like `Profile`) AND its name is **NOT** in the list of available schemas, you **MUST NOT** use a `$ref`. Instead, you **MUST** define its schema *inline* under the field.


        ### Field Naming and Inclusion:
        a. Use @JsonProperty("custom_name") value if present, otherwise use the Java field name
        b. Exclude fields with @JsonIgnore

        ### Type Mapping:
        - String, UUID → type: string (UUID gets format: uuid)
        - Integer, int → type: integer, format: int32
        - Long, long → type: integer, format: int64
        - Double, double, Float, float → type: number
        - Boolean, boolean → type: boolean
        - LocalDateTime, Date → type: string (check @JsonFormat for pattern vs format: date-time)
        - Custom POJOs → $ref: '#/components/schemas/{simple_name}' or inline
        - Enums → type: string with enum: [...] containing ALL constant names
        - Collections (List, Set, []) → type: array with items schema

        ### Additional Properties:
        - readOnly: true if @JsonProperty(access = READ_ONLY) or has getter but no setter
        - writeOnly: true if @JsonProperty(access = WRITE_ONLY)
        - Include validation constraints: minLength, maxLength, minimum, maximum, pattern

        ### Required Fields - Critical Analysis:
        Create a 'required' array. Include a field ONLY if:
        
        Step 1 - Check for validation annotations:
        - Has @NotNull, @NotBlank, or @NotEmpty from javax/jakarta.validation
        - Is a primitive type (not wrapper) - these can't be null
        
        Step 2 - Consider nullability overrides:
        - If has @JsonSetter(nulls = Nulls.SKIP) AND constructor default → NOT required
        - If has @Nullable annotation → NOT required
        - For entities: If JPA @Column allows null (no @NotNull) → NOT required
        
        Step 3 - Verify by reasoning:
        - Would the API reject a request missing this field?
        - Can this field be null in a valid response?

        Step 4 - Add metadata for each generated schema:
        - Along with each schema you generate, you MUST provide metadata about its origin:

        ## Metadata Requirements:
        Along with each schema you generate, you MUST provide metadata about its origin:
        - For the main schema '{simple_name}': This is the primary component being analyzed
        - For any additional schemas generated (nested classes, dependencies):
          * Provide the fully qualified Java class name it represents
          * Indicate if it's a nested/inner class.
          * If it's from data_classes context, specify which one

        ## Self-Verification Before Finalizing:
        - [ ] All enum values from the enum definition are included?
        - [ ] Date patterns match @JsonFormat annotations exactly?
        - [ ] Required array contains ONLY fields that would cause errors if missing?
        - [ ] Field names match @JsonProperty annotations?
        - [ ] Validation constraints (min/max/pattern) are included where found?

        ## Output format:
        The output open API specs should have the following yaml syntax. It has two sections under 'components' and 'x-schemas-metadata':
        ```yaml
            components:
                schemas:
                    YourClassName:
                    type: object
                    properties:
                        field_name:  # From @JsonProperty or field name
                        type: <type>
                        format: <format>  # If applicable
                        # Include all applicable constraints:
                        enum: [...]  # For enums - ALL values
                        minLength: X
                        maxLength: Y
                        minimum: X
                        maximum: Y
                        pattern: "..."
                        readOnly: true/false  # If applicable
                        writeOnly: true/false  # If applicable
                        another_field:
                        type: array  # For collections
                        items:
                            type: <element-type>
                            # or $ref: '#/components/schemas/ElementClass'
                    required:  # Only truly required fields
                        - field_name
                        - another_field
                    # Additional schemas if any nested/referenced classes need definition

            x-schemas-metadata:
                YourClassName:
                    source_fqn: "fully.qualified.class.Name"
                    relationship: "primary"
                # For any additional schemas generated:
                OtherSchemaName:
                    source_fqn: "fully.qualified.class.Name"
                    relationship: "nested|dependency"  # nested if inner class, dependency if from data_classes
        ```

        ## Important Notes:
        - Don't assume standard patterns - Respect what the code actually does
        - For EVERY schema you generate, add a corresponding entry in x-schemas-metadata
        - Check everything - A field might look required but have subtle optional behavior
        - Be complete - Include ALL enum values, ALL constraints
        - Think like Spring Boot - Consider how Jackson serialization actually works
        - Do not give anything other than the spec output in the response
        - Think hard before answering.
        """

    def get_initial_context_presentation_for_missing_symbols(self, endpoint: Dict[str, Any], endpoint_context: Dict[str, Any]) -> str:
        """
        Formats the Spring Boot initial endpoint context for the missing symbols prompt.
        This reuses the generic formatter.
        """
        url = endpoint.get("url", {}).get("url", "N/A")
        http_method = endpoint.get("method", "N/A").upper()
        
        handler_details = endpoint_context.get("handler", {})
        handler_method_name = handler_details.get("name", "UnknownMethod")
        handler_class_fqn = handler_details.get("class_name_fqn", "UnknownClass")
        fn_name_for_prompt = f"{handler_class_fqn}.{handler_method_name}"
        
        prompt_str = f"""Based on the API endpoint and code context presented below, your goal is to identify all classes and functions/static methods from the project whose full code definitions are helpful and necessary to fully deduce the request structure (parameters, requestBody fields, validation) and the response structure (response body fields, status codes) for this specific endpoint method with 100% precision and recall but are not present in the code context. You are analyzing the Spring Boot API endpoint '{http_method} {url}' handled by the method '{fn_name_for_prompt}' in class '{handler_class_fqn}''.
Context retrieved for this endpoint:

"""
        # _format_endpoint_context_for_prompt is a generic helper we will add later,
        # assuming it's the same as Jersey's for now.
        code = self._format_endpoint_context_for_prompt(endpoint_context)
        prompt_str += code

        return prompt_str.strip()

    def get_framework_specific_guidance_for_missing_symbols(self) -> str:
        """
        Provides Spring Boot-specific instructions on what kinds of custom symbols to look for.
        """
        return """
Focus on finding these Spring Boot patterns in the provided code:

1.  **Injected Dependencies (@Autowired):**
    - Look for fields annotated with `@Autowired` or constructor parameters that are not simple types. These are often Service or Repository classes.
    - If you see a method call like `userAccountService.signupNewUserAccount(...)` inside the handler method, you MUST identify the type of the `userAccountService` variable (e.g., `UserAccountService`) as a missing CLASS.

2.  **Custom Exceptions:**
    - Look for `throw new SomeCustomException(...)` statements within the handler code.
    - You MUST identify "SomeCustomException" as a missing CLASS. This is critical because its definition is needed to understand how a global `@ExceptionHandler` in a `@ControllerAdvice` class might handle it.

3.  **Repository/Service Method Calls:**
    - Look for method calls on repository or service objects (e.g., `userRepository.save(account)`).
    - You MUST identify the class of the object being passed in (e.g., the `account` variable is likely a `UserAccount` entity) as a missing CLASS if its full code definition is not already provided in the context.

4.  **Mapper Usage:**
    - If you see calls like `modelMapper.map(source, DestinationDTO.class)`, you MUST identify `DestinationDTO` as a missing CLASS.
"""

    def get_framework_specific_exclusion_instructions_for_missing_symbols(self) -> str:
        """
        Returns the Spring Boot-specific "Exclusions:" section for the prompt.
        """
        #spring_specific_exclusions = self.get_framework_specific_exclusions_for_missing_symbols()

        exclusion_text = "Exclusions:\n"
        exclusion_text += "- Do NOT include standard JDK classes (e.g., `java.lang.String`, `java.util.List`).\n"
        exclusion_text += "- Do NOT include unmodified base classes/interfaces from the primary framework.\n"
        
        # if spring_specific_exclusions:
        #     exclusion_text += "- Specifically, also avoid unmodified versions of symbols from common Spring Boot libraries like:\n"
        #     for exc_pattern in sorted(list(set(spring_specific_exclusions))):
        #         exclusion_text += f"  - `{exc_pattern}`\n"
        return exclusion_text
    
    def _recurse_on_class_dependencies(self, class_fqn: str, definition_path: str, class_details: Dict[str, Any], current_depth: int, max_depth: int, processed_keys: Set[str], accumulator: List[Dict[str, Any]]):
        """Helper to recursively fetch dependencies for a given class."""
        next_depth = current_depth + 1

        # --- 1. Fetch Parent Dependencies if it's a DTO ---
        if self._is_potential_dto(class_fqn):
            self.logger.debug(f"'{class_fqn}' is a DTO. Fetching its parent DTOs.")
            parent_hierarchy = self.code_analyzer.get_type_hierarchy(class_fqn, definition_path)
            for parent_entry in parent_hierarchy:
                parent_fqn = parent_entry.get("name")
                if parent_fqn and self._is_potential_dto(parent_fqn):
                    self._fetch_recursive_context_java(
                        parent_fqn, SymbolType.CLASS, definition_path,
                        next_depth, max_depth, processed_keys, accumulator
                    )
        
        # --- 2. Fetch Child Dependencies (Fields) ---
        for field_info in class_details.get("fields", []):
            field_type_fqn = field_info.get("type")
            base_field_type_fqn = self._get_base_type(field_type_fqn)
            if base_field_type_fqn and self._is_potential_dto(base_field_type_fqn):
                self._fetch_recursive_context_java(
                    base_field_type_fqn, SymbolType.CLASS, definition_path,
                    next_depth, max_depth, processed_keys, accumulator
                )
        
        # --- 3. Fetch Defined Methods ---
        for method_info in class_details.get("functions", []):
            method_fqn = f"{class_fqn}.{method_info.get('methodName')}"
            self._fetch_recursive_context_java(
                method_fqn, SymbolType.FUNCTION, definition_path,
                next_depth, max_depth, processed_keys, accumulator
            )

    def _recurse_on_function_dependencies(self, definition_path: str, function_details: Dict[str, Any], current_depth: int, max_depth: int, processed_keys: Set[str], accumulator: List[Dict[str, Any]]):
        """Helper to recursively fetch dependencies for a given function."""
        next_depth = current_depth + 1

        # --- 1. Fetch Referenced Classes ---
        for ref_class_fqn in function_details.get("classNames", []):
            if self._is_potential_dto(ref_class_fqn) or not self._is_primitive_or_common(ref_class_fqn):
                self._fetch_recursive_context_java(
                    ref_class_fqn, SymbolType.CLASS, definition_path,
                    next_depth, max_depth, processed_keys, accumulator
                )

        # --- 2. Fetch Called Methods ---
        for called_func_info in function_details.get("functionNames", []):
            target_method_name = called_func_info.get("simpleName")
            target_class_fqn = called_func_info.get("declaringClass")
            if target_method_name and target_class_fqn and not self._is_primitive_or_common(target_class_fqn):
                self._fetch_recursive_context_java(
                    f"{target_class_fqn}.{target_method_name}", SymbolType.FUNCTION, definition_path,
                    next_depth, max_depth, processed_keys, accumulator
                )
        
        # --- 3. Fetch Variable Types that are DTOs ---
        for var_info in function_details.get("variableNames", []):
            var_type_fqn = var_info.get("type")
            base_var_type_fqn = self._get_base_type(var_type_fqn)
            if base_var_type_fqn and self._is_potential_dto(base_var_type_fqn):
                self._fetch_recursive_context_java(
                    base_var_type_fqn, SymbolType.CLASS, definition_path,
                    next_depth, max_depth, processed_keys, accumulator
                )

    def _fetch_recursive_context_java(self,
                                   symbol_name_from_llm: str,
                                   symbol_type: SymbolType,
                                   referencing_context_path: str,
                                   current_depth: int, max_depth: int,
                                   processed_keys: Set[str],
                                   accumulator: List[Dict[str, Any]]):
        if current_depth >= max_depth:
            return

        # 1. Resolve symbol to its canonical name and definition path
        symbol_ref = self.code_analyzer.get_symbol_reference(symbol_name_from_llm, referencing_context_path, symbol_type)
        if not symbol_ref:
            self.logger.warning(f"Jersey (Recursive): Could not resolve '{symbol_name_from_llm}' ({symbol_type.name}) from '{referencing_context_path}'.")
            return

        canonical_name = symbol_ref.get("canonicalName") # Should be FQN for classes, FQN.method for methods
        definition_path = symbol_ref.get("definitionPath")

        if not canonical_name or not definition_path: return

        symbol_key = self._get_java_symbol_key(canonical_name, definition_path, symbol_type)
        if symbol_key in processed_keys: return

        # 2. Get symbol info and code snippet
        symbol_details = self.code_analyzer.get_symbol_info(canonical_name, definition_path, symbol_type)
        if not symbol_details:
            processed_keys.add(symbol_key) # Mark processed even if no info to avoid retries
            return

        start_line = symbol_details.get("startLine")
        end_line = symbol_details.get("endLine")
        code_snippet = "// Code not retrieved"
        if start_line and end_line:
            snip = self.code_analyzer.get_code_snippet(definition_path, start_line, end_line)
            if snip: code_snippet = snip.strip()

        # 3. Add the found symbol to the accumulator
        item_name_for_list = canonical_name.split('.')[-1] if symbol_type == SymbolType.CLASS else canonical_name
        accumulator.append({
            "name": item_name_for_list, # Simple name for class, FQN.method for method
            "qualifiedName": canonical_name,
            "type": symbol_type.name.upper(), # "CLASS" or "FUNCTION"
            "path": definition_path,
            "start_line": start_line, "end_line": end_line, "code": code_snippet,
        })
        processed_keys.add(symbol_key)
        self.logger.debug(f"Jersey (Recursive) [Depth {current_depth}]: Added context for {symbol_key}")

        # 4. Delegate recursion to specialized helpers
        if current_depth + 1 < max_depth:
            if symbol_type == SymbolType.CLASS:
                self._recurse_on_class_dependencies(
                    canonical_name, definition_path, symbol_details,
                    current_depth, max_depth, processed_keys, accumulator
                )
            elif symbol_type == SymbolType.FUNCTION:
                self._recurse_on_function_dependencies(
                    definition_path, symbol_details,
                    current_depth, max_depth, processed_keys, accumulator
                )

    def get_endpoint_request_system_message(self) -> str:
        """Sets the LLM's persona and primary goal for generating request specs."""
        return """You are an expert in Java, Spring Boot, the Jackson serialization library, and OpenAPI 3.0. Your task is to analyze a Spring Boot controller method and its related code context to define its OpenAPI `parameters` and `requestBody` sections."""

    def get_endpoint_request_framework_specific_notes(self) -> str:
        """Provides a high-impact, concise note about Spring Boot's request binding."""
        return """NOTE: Spring Boot is explicit. The request body is ALWAYS marked with `@RequestBody`. Parameters for query strings or form data are typically marked with `@RequestParam`."""
    
    def get_endpoint_common_instructions(self, skip_components: bool = False) -> str:
        """
        Provides common, framework-agnostic instructions for the final output format.
        This implementation can be shared between different framework analyzers.
        """
        if skip_components:
            ref_instruction = "6. DO NOT use `$ref` to `#/components/schemas/`. All schemas for request bodies or responses must be defined inline within the path item."
        else:
            ref_instruction = "6. DO NOT create the `components` section of the OpenAPI definition here; component schemas are handled separately. You MUST, however, use `$ref` to `#/components/schemas/YourPojoName` if a POJO is involved."

        return f"""
4.  Map Java types to standard OpenAPI primitive types (string, integer, number, boolean, array, object) and use `format` where appropriate (e.g., `int32`, `int64`, `date-time`, `byte`).
5.  DO NOT add the `x-codeSamples` section.
{ref_instruction}
7.  Return ONLY the requested OpenAPI definition sections (`parameters` and `requestBody`).
8.  Ensure your output STRICTLY conforms to OpenAPI 3.0 specifications and is 100% syntactically correct YAML.
"""
    
    def _get_simple_name_from_annotation_type(self, annotation_data: Dict[str, Any]) -> Optional[str]:
        """
        Parses an annotation data dictionary to extract its simple name.
        e.g., 'Lorg/springframework/web/bind/annotation/RequestBody;' -> 'RequestBody'
        """
        if not isinstance(annotation_data, dict):
            return None

        type_descriptor = annotation_data.get('type')
        if not isinstance(type_descriptor, str) or not type_descriptor.startswith('L') or not type_descriptor.endswith(';'):
            return None
        
        fqn = type_descriptor[1:-1].replace('/', '.')
        return fqn.split('.')[-1]
    
    def get_endpoint_request_instructions(self, endpoint: Dict[str, Any], endpoint_context: Dict[str, Any], skip_components: bool = False) -> str:
        """
        Generates the detailed, step-by-step instructions for the LLM to create the
        OpenAPI 'parameters' and 'requestBody' sections for a Spring Boot endpoint.
        """
        # --- Part 1: Prepare Metadata ---
        handler_details = endpoint_context.get("handler", {})
        method_params_info = handler_details.get("method_parameters_info", [])
        parameter_style = self._detect_parameter_style(method_params_info)
        if parameter_style == 'ANNOTATED':
            return self._get_instructions_for_annotated_style(endpoint, endpoint_context, skip_components)
        elif parameter_style == 'DYNAMIC_SERVLET':
            # This branch generates the NEW, fallback instructions.
            return self._get_instructions_for_dynamic_style(endpoint, endpoint_context, skip_components)
        else:
            # Default case (e.g., no parameters) - can use the annotated style as it will likely result in an empty (but correct) parameter list.
            return self._get_instructions_for_annotated_style(endpoint, endpoint_context, skip_components)

    def _get_instructions_for_annotated_style(self, endpoint: Dict[str, Any], endpoint_context: Dict[str, Any], skip_components: bool = False) -> str:
         # --- Part 1: Prepare Metadata ---
        url = endpoint.get("url", {}).get("url", "N/A")
        method_lower = endpoint.get("method", "N/A").lower()
        handler_details = endpoint_context.get("handler", {})
        handler_method_name = handler_details.get("name", "UnknownMethod")
        handler_class_fqn = handler_details.get("class_name_fqn", "UnknownClass")
        method_params_info = handler_details.get("method_parameters_info", [])
        parameter_style = self._detect_parameter_style(method_params_info)

        # --- Part 2: Create Parameter Summary ---
        unique_parameters = {}
        for method_handler in endpoint_context.get("handler_methods", []):
            for param_info in method_handler.get("method_parameters_info", []):
                param_name = param_info.get("name")
                if param_name and param_name not in unique_parameters:
                    unique_parameters[param_name] = param_info
        
        method_param_details_str_list = []
        for p_soot in unique_parameters.values():
            param_ann_names = [
                f"@{name}" for ann in p_soot.get("annotations", [])
                if (name := self._get_simple_name_from_annotation_type(ann))
            ]
            param_ann_str = f" Annotations: [{', '.join(param_ann_names)}]" if param_ann_names else ""
            method_param_details_str_list.append(
                f"- Java Param: type='{p_soot.get('type', 'Object')}', name in code='{p_soot.get('name', 'unknown')}'{param_ann_str}"
            )
        method_params_guidance_from_soot = "\n".join(method_param_details_str_list)

        # --- Part 3: Construct Final Instruction String ---
        return f"""
You are analyzing the Spring Boot endpoint '{method_lower.upper()} {url}' handled by the method '{handler_class_fqn}.{handler_method_name}'.

Here is a summary of the statically analyzed Java method parameters from its signature:
{method_params_guidance_from_soot}

Follow these steps precisely to generate the `parameters` and `requestBody` sections:

1.  **Parameters (Path, Query, Header):**
    a.  **Path Parameters:** For each parameter in the URL path (e.g., `{{id}}`), find the corresponding Java method parameter annotated with `@PathVariable`. These are ALWAYS `required: true`. The OpenAPI `schema` should match the Java type (e.g., `java.lang.String` -> `type: string`, `java.lang.Long` -> `type: integer, format: int64`).
    b.  **Query Parameters:** Find Java parameters annotated with `@RequestParam`. The annotation's `value` or `name` attribute is the OpenAPI parameter `name`. The `required` property in OpenAPI is determined by the `required` attribute of the annotation (it defaults to true). If the annotation has a `defaultValue`, the parameter is not required and you should include the default value.
    c. Parameter Usage Analysis & Schema Refinement: After defining a parameter based on its signature, you MUST inspect the handler method's code to refine the schema:
        - Enum Validation: If a String or Integer parameter is used to initialize an Enum (e.g., via Enum.valueOf() or a custom factory method), the OpenAPI schema MUST list the possible values from the Enum definition provided in the context.
        - Validation Constraints: If a parameter is checked against hardcoded values or constants (e.g., if (limit > MAX_SEARCH_LIMIT)), you MUST add corresponding validation constraints to the schema (e.g., minimum, maximum, minLength, maxLength, pattern).

2.  **RequestBody:**
    a.  **Primary Rule:** Examine the summarized Java parameters. Find the ONE parameter annotated with `@RequestBody`. The Java type of this parameter (e.g., `CreateUserDTO`) is the request body.
    b.  **Media Types:** The `consumes` attribute of the mapping annotation (e.g., `@PostMapping(consumes = "application/xml")`) defines the media type. If not present, default to `application/json`.
    c.  **Schema:** The schema for the request body MUST be a `$ref` to the corresponding component (e.g., `$ref: '#/components/schemas/CreateUserDTO'`). The full code for this DTO is in the 'Associated POJOs/DTOs' context.
    d.  **Form Data Fallback:** IF AND ONLY IF there is NO `@RequestBody` annotation, the endpoint might accept `application/x-www-form-urlencoded` data. In this case, each method parameter (especially those annotated with `@RequestParam`) could represent a form field. The `requestBody` schema should be `type: object` with properties matching these parameters.
    e.  **Omission:** If neither of the above conditions is met, OMIT the `requestBody` section entirely.

3. **Rule for component Referencing:**
    - The component schema represents the static data structure.
    - The controller code represents the actual runtime contract.
    Step 3.a: CRITICAL CHECK - Analyze Controller Logic for Contract Changes

        Before deciding how to define the schema, you MUST analyze the Java code of the controller method. Look for any logic that inspects or validates the fields of the request body object. Ask these questions:
        * Does the code check if a field is null or .isEmpty()? (This implies required: true).
        * Does the code check a string's .length()? (This implies minLength and/or maxLength).
        * Does the code check a number against a minimum or maximum value? (This implies minimum and/or maximum).
        * Does the code throw an exception if any of these checks fail?

    Step 3.b: Choose Your Schema Strategy based on the Critical Check

        Scenario 1: IF the controller adds validation (IF you answered YES to any question in 3.a):
        * You MUST define the schema inline.
        * Do NOT use a $ref for the top-level request body, as the reference would be inaccurate.
        * In your inline schema, add the constraints you discovered. For example, add the field to the required array, or set minLength/maxLength.
        * For nested objects within the inlined schema, you may still use $ref if they are not modified.

        Scenario 2: IF the controller does NOT add validation (the object is simply passed to a service layer without inspection):
        * You SHOULD use a $ref to the component schema (e.g., $ref: '#/components/schemas/UploadPasteRequestBody'), PROVIDED its name is on the list of available schemas.
        * This is the only situation where a top-level $ref for the request body is acceptable.

"""
    
    def _get_instructions_for_dynamic_style(self, endpoint: Dict[str, Any], endpoint_context: Dict[str, Any], skip_components: bool = False) -> str:
        url = endpoint.get("url", {}).get("url", "N/A")
        method_lower = endpoint.get("method", "N/A").lower()
        handler_details = endpoint_context.get("handler", {})
        handler_method_name = handler_details.get("name", "UnknownMethod")
        handler_class_fqn = handler_details.get("class_name_fqn", "UnknownClass")
        method_params_info = handler_details.get("method_parameters_info", [])
        return f"""
You are analyzing the Spring Boot endpoint '{method_lower.upper()} {url}' handled by the method '{handler_class_fqn}.{handler_method_name}'.

The method signature uses a dynamic `HttpServletRequest` object to process parameters instead of explicit Spring annotations like `@RequestParam`. You MUST deduce the parameters by analyzing the provided code context that consumes this request object.

Follow these steps precisely to generate the `parameters` and `requestBody` sections:

1.  **Parameters (Path, Query, Header, Form Data):**
    a.  **Path Parameters:** First, check the endpoint URL `{url}` for any path parameters (e.g., `{{id}}`). If found, define them as `in: path` and `required: true`. Their details can be found in the endpoint's metadata.
    b.  **Dynamic Parameter Discovery (Trace the Request Object):** The primary source for identifying all other valid parameters is the code that consumes the `HttpServletRequest` object.
        i.  **Trace the Variable:** Analyze the handler method's code to see where the `servletRequest` variable is passed. It will typically be used to construct a new object (e.g., `new ExecutorClass(servletRequest, ...)`) or passed to a method of another object (e.g., `helperObject.process(servletRequest)`).
        ii. **Identify the Worker Class:** Determine the fully qualified class name of the "worker" class that receives the `servletRequest` object.
        iii. **Find the Parameter List:** Look inside this worker class for methods that define or validate the list of expected parameters. Look for patterns like direct calls to `request.getParameter("paramName")` or helper methods with names like `getResourceSpecificParams`, `checkParameters`, or `validateRequest`. The logic inside these methods is the definitive source for parameter names.
    c.  **Parameter Usage Analysis & Schema Refinement:** After identifying a parameter's name from the worker class, you MUST inspect the surrounding code to refine its schema:
        - **Requirement:** If the code throws an exception (e.g., via a class named `ExceptionMessages`) when a parameter or a group of parameters is missing, you MUST reflect this in the parameter's `description`. Mark individual parameters as `required: false` unless the code shows a single parameter is always mandatory.
        - **Type & Format:** Determine the `type` (e.g., `string`, `boolean`, `integer`) by observing how the parameter is parsed or used (e.g., `Double.parseDouble`, `Boolean.parseBoolean`).
        - **Enum Validation:** If a String parameter is checked against a fixed set of values or used to populate an Enum, the OpenAPI schema MUST list the possible values in an `enum` array.
        - **Default Values:** If the code provides a fallback value when a parameter is absent, specify this in the `default` field.

2.  **RequestBody:**
    a.  **Primary Rule for this Pattern:**
        - For **`GET`** requests, there is no request body. OMIT the `requestBody` section entirely. The parameters you discovered in Step 1 are query parameters.
        - For **`POST`** requests using this pattern, the parameters are typically sent as `application/x-www-form-urlencoded` form data.
    b.  **Form Data Schema:** If a `requestBody` is needed (for POST), define it with `content` type `application/x-www-form-urlencoded`. The `schema` should be `type: object`, and its `properties` MUST match the parameter names and schemas you discovered in Step 1.
    c.  **Omission:** If the method is `GET` or if no parameters are discovered for a `POST` method, OMIT the `requestBody` section.

3. **Rule for component Referencing:**
    - The component schema represents the static data structure.
    - The controller code represents the actual runtime contract.
    Step 3.a: CRITICAL CHECK - Analyze Controller Logic for Contract Changes

        Before deciding how to define the schema, you MUST analyze the Java code of the controller method. Look for any logic that inspects or validates the fields of the request body object. Ask these questions:
        * Does the code check if a field is null or .isEmpty()? (This implies required: true).
        * Does the code check a string's .length()? (This implies minLength and/or maxLength).
        * Does the code check a number against a minimum or maximum value? (This implies minimum and/or maximum).
        * Does the code throw an exception if any of these checks fail?

    Step 3.b: Choose Your Schema Strategy based on the Critical Check

        Scenario 1: IF the controller adds validation (IF you answered YES to any question in 3.a):
        * You MUST define the schema inline.
        * Do NOT use a $ref for the top-level request body, as the reference would be inaccurate.
        * In your inline schema, add the constraints you discovered. For example, add the field to the required array, or set minLength/maxLength.
        * For nested objects within the inlined schema, you may still use $ref if they are not modified.

        Scenario 2: IF the controller does NOT add validation (the object is simply passed to a service layer without inspection):
        * You SHOULD use a $ref to the component schema (e.g., $ref: '#/components/schemas/UploadPasteRequestBody'), PROVIDED its name is on the list of available schemas.
        * This is the only situation where a top-level $ref for the request body is acceptable.

"""
    
    def get_endpoint_response_system_message(self) -> str:
        """Sets the LLM's persona and primary goal for generating response specs."""
        return """You are an expert in Java, Spring Boot, and OpenAPI 3.0. Your task is to analyze a Spring Boot controller method and its related context, including global exception handlers (`@ControllerAdvice`), to define its OpenAPI `summary` and `responses` sections."""
    
    def get_endpoint_response_framework_specific_notes(self) -> str:
        """Provides a high-impact, concise note about Spring Boot's response generation patterns."""
        return """NOTE: For Spring Boot, the actual HTTP status code and response body for errors are often defined globally in a `@ControllerAdvice` class, not in the controller method itself. You must cross-reference exceptions thrown in the controller with the `@ExceptionHandler` methods in the provided error handler context."""
    
          
    def get_endpoint_response_instructions(self, endpoint: Dict[str, Any], endpoint_context: Dict[str, Any], skip_components: bool = False) -> str:
            """
            Generates the detailed, step-by-step instructions for the LLM to create the
            OpenAPI 'summary' and 'responses' sections for a Spring Boot endpoint.
            """
            # --- Part 1: Prepare Metadata ---
            url = endpoint.get("url", {}).get("url", "N/A")
            method_upper = endpoint.get("method", "N/A").upper()
            handler_details = endpoint_context.get("handler", {})
            handler_method_name = handler_details.get("name", "UnknownMethod")
            handler_class_fqn = handler_details.get("class_name_fqn", "UnknownClass")
            return_type_java_fqn = handler_details.get("returnType", "void")
            
            # --- Part 2: Construct Final Instruction String ---
            return f"""
    You are analyzing the Spring Boot endpoint '{method_upper} {url}'.
    The handler method's declared Java return type is: `{return_type_java_fqn}`.

    The provided code context contains the handler method's code, the definitions of relevant DTOs/POJOs, and critically, a section named 'Global Error Handlers (@ControllerAdvice)' which contains project-wide exception handling logic.

    Follow these steps precisely to generate the `summary` and `responses` sections:

    1.  **Summary:** Provide a concise, one-sentence summary for the operation based on the handler method's name and code.

    2.  **Success Responses (e.g., 200, 201, 204):**
        a.  **Status Code:**
            - If the return type is `ResponseEntity`, you MUST analyze the handler's code for explicit status settings (e.g., `ResponseEntity.ok(...)` for 200, `ResponseEntity.status(HttpStatus.CREATED)` for 201).
            - If the return type is `void`, the success code is `204 No Content`.
            - Otherwise (e.g., returning a POJO directly from a `@RestController`), the default success code is `200 OK`.
        b.  **Response Body (Content):**
            - Determine the returned entity (either the direct return type or the object inside a `ResponseEntity<T>`).
            - If an entity is returned, determine its mesdia type from the `produces` attribute of the mapping annotation (e.g., `@GetMapping(produces = "...")`). If not specified, default to `application/json`.
            - The `schema` for the response body MUST be a `$ref` to the component schema (e.g., `$ref: '#/components/schemas/UserDTO'`). The DTO's full code definition is in the 'Associated POJOs/DTOs' context.
            - If no entity is returned (e.g., `void` or `ResponseEntity<Void>`), OMIT the `content` section.
    
    3. Final Review: Before concluding, ensure your list of responses accurately reflects the method's guaranteed behavior based on its implementation, not just its declared signature.

    **Rule for Referencing:**
        - Perform a quick check of the controller code for last-minute modifications to the response object. **If** you find any modifications that alter the standard structure of the DTO, you should inline the schema for that response to accurately describe the final output.
        - **IF** a field's type is a custom class (like `Address`) AND its name (e.g., `Address`) is in the list of available schemas, you could use a `$ref` if you think the component is being used without any modification in the contoller.
          Example: `address: {{ $ref: '#/components/schemas/Address' }}`

        - **IF** a field's type is a custom class (like `Profile`) AND its name is **NOT** in the list of available schemas, you **MUST NOT** use a `$ref`. Instead, you **MUST** define its schema *inline* under the field.
    """

    def get_class_signature_from_fqn(self, fqn: str) -> Optional[str]:
        """
        Looks up a class by its FQN, gets its full hierarchy, and constructs a
        Java-like class signature string.

        Example: public class MyDTO extends BaseDTO implements Serializable
        """
        class_info = self.code_analyzer.get_symbol_info(fqn, self.project_path, SymbolType.CLASS)
        if not class_info:
            self.logger.warning(f"Could not find class info for FQN '{fqn}' to generate signature.")
            return None
        
        parent_hierarchy_infos = self.code_analyzer.get_type_hierarchy(fqn, self.project_path)
        
        parts = ["public"]
        if class_info.get("isEnum"):
            parts.append("enum")
        elif class_info.get("isInterface"):
            parts.append("interface")
        else:
            parts.append("class")
        
        simple_name = class_info.get("className", fqn).split('.')[-1]
        parts.append(simple_name)

        superclass = None
        interfaces = []
        for parent_info in parent_hierarchy_infos:
            parent_name = parent_info.get("name")
            if not parent_name or parent_name == "java.lang.Object":
                continue
            
            # The parent_info dictionary contains isInterface, allowing us to distinguish
            if not parent_info.get("isInterface") and not superclass:
                superclass = parent_name.split('.')[-1]
            elif parent_info.get("isInterface"):
                interfaces.append(parent_name.split('.')[-1])

        if superclass:
            parts.append("extends")
            parts.append(superclass)
        
        if interfaces:
            parts.append("implements")
            parts.append(", ".join(sorted(interfaces)))

        return " ".join(parts)
        
    def is_relaxed_obj_validation(self):
        return True
    