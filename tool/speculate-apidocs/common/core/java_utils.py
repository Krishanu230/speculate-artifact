"""
Shared Java analysis utilities used by both Spring Boot and Jersey analyzers.

JavaAnalyzerMixin provides methods that are identical across all Java-based
framework analyzers. Both SpringBootFrameworkAnalyzer and JerseyFrameworkAnalyzer
inherit from this mixin.

Methods here depend on self.code_analyzer, self.project_path, and self.logger,
which are provided by the concrete analyzer class. Methods that are
framework-specific (e.g. _is_potential_dto, _get_base_type, _get_java_symbol_key)
remain in each concrete analyzer and are called via self.* so Python's MRO
resolves them correctly.
"""


class JavaAnalyzerMixin:
    """
    Mixin providing shared Java analysis utilities for Spring Boot and Jersey analyzers.

    Prerequisites (must be set by the concrete class before any mixin method is called):
        self.code_analyzer  – JavaCodeAnalyzer instance
        self.project_path   – str, root directory of the project under analysis
        self.logger         – logging.Logger instance
        self.framework_name – str, human-readable framework name (from FrameworkAnalyzer)
    """
    def _is_primitive_or_common(self, type_name):
        """Checks if a type name represents a Java primitive or common stdlib/framework class."""
        if not type_name:
            return True
        base_type = type_name.replace("[]", "")  # Handle arrays

        primitive_types = {"byte", "short", "int", "long", "float", "double", "boolean", "char", "void"}
        if base_type in primitive_types:
            return True

        common_prefixes_or_exact = [
            "java.lang.", "java.util.", "java.net.", "java.io.", "java.math.", "java.time.",
            "javax.ws.rs.", "jakarta.ws.rs.",
            "javax.inject.", "jakarta.inject.",
            "javax.persistence.", "jakarta.persistence.",
            "org.springframework.http.", "org.springframework.web.bind.annotation.",
            "org.slf4j.", "java.util.logging.",
            "com.fasterxml.jackson.databind.",
        ]
        if any(base_type.startswith(prefix) for prefix in common_prefixes_or_exact):
            return True

        return False

    def _soot_descriptor_to_fqn(self, descriptor):
        """Converts Soot's Lpath/to/Class; descriptor to path.to.Class FQN."""
        if not descriptor:
            return None

        cleaned_descriptor = descriptor
        while cleaned_descriptor.startswith("["):
            cleaned_descriptor = cleaned_descriptor[1:]

        fqn = cleaned_descriptor
        if fqn.startswith("L") and fqn.endswith(";"):
            fqn = fqn[1:-1].replace('/', '.')

        return fqn

    def _infer_fields_from_getters(self, class_info):
        """
        Infers schema fields from public getter methods (e.g., getFirstName(), isEnabled())
        found in a class's analysis information.
        """
        inferred_fields = []
        if not class_info or not isinstance(class_info.get("functions"), list):
            return inferred_fields

        for method in class_info.get("functions", []):
            method_name = method.get("methodName")
            if not method_name:
                continue

            field_name = None
            if method_name.startswith("get") and len(method_name) > 3 and method_name[3].isupper():
                if len(method.get("parameters", [])) == 0:
                    field_name = method_name[3].lower() + method_name[4:]

            elif method_name.startswith("is") and len(method_name) > 2 and method_name[2].isupper():
                if len(method.get("parameters", [])) == 0:
                    field_name = method_name[2].lower() + method_name[3:]

            if field_name:
                self.logger.debug(f"Inferred field '{field_name}' from getter '{method_name}' in class '{class_info.get('className')}'.")
                inferred_fields.append({
                    "name": field_name,
                    "type": method.get("returnType"),
                    "annotations": method.get("annotations", [])
                })

        return inferred_fields

    def _topological_sort(self, adj, in_degree):
        """
        Performs a topological sort on the component dependency graph using Kahn's algorithm.
        This version correctly handles the queue as a FIFO structure to respect dependencies
        and includes a robust fallback for handling cycles.
        """
        from collections import deque
        import json

        self.logger.info("--- Starting Topological Sort ---")

        initial_zero_degree_nodes = sorted([fqn for fqn, degree in in_degree.items() if degree == 0])
        self.logger.info(f"Initial nodes with in-degree 0: {json.dumps(initial_zero_degree_nodes, indent=2)}")

        queue = deque(initial_zero_degree_nodes)
        sorted_list = []

        processed_count = 0
        while queue:
            u = queue.popleft()
            sorted_list.append(u)
            processed_count += 1

            for v in sorted(list(adj.get(u, []))):
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    queue.append(v)

        if len(sorted_list) != len(adj):
            self.logger.warning(
                f"Cycle detected in component dependencies. {len(adj) - len(sorted_list)} nodes remain."
            )
            cycled_nodes = {fqn for fqn in adj if in_degree.get(fqn, 0) > 0}
            self.logger.warning(f"Remaining nodes with in-degree > 0: {sorted(list(cycled_nodes))}")
            sorted_list.extend(sorted(list(cycled_nodes)))

        self.logger.info("--- Topological Sort Finished ---")
        return sorted_list

    def _get_all_properties_for_class(self, fqn_to_start_from):
        """
        Gathers all unique properties for a class by inspecting its declared fields,
        its inferred getter methods, and recursively doing the same for its entire
        parent hierarchy.
        """
        from common.core.code_analyzer import SymbolType

        all_props_collected = []

        def gather_from_hierarchy(current_fqn, visited_fqns_for_fields):
            if not current_fqn or current_fqn in visited_fqns_for_fields:
                return
            visited_fqns_for_fields.add(current_fqn)

            info = self.code_analyzer.get_symbol_info(current_fqn, self.project_path, SymbolType.CLASS)
            if not info:
                return

            all_props_collected.extend(info.get("fields", []))
            all_props_collected.extend(self._infer_fields_from_getters(info))

            parent_hierarchy = self.code_analyzer.get_type_hierarchy(current_fqn, self.project_path)
            for p_info_dict in parent_hierarchy:
                gather_from_hierarchy(p_info_dict.get("name"), visited_fqns_for_fields)

        gather_from_hierarchy(fqn_to_start_from, set())

        final_props_map = {}
        for prop in all_props_collected:
            name = prop.get("name")
            if name and name not in final_props_map:
                final_props_map[name] = prop
        return list(final_props_map.values())

    def _recurse_on_class_dependencies(self, class_fqn, definition_path, class_details,
                                        current_depth, max_depth, processed_keys, accumulator):
        """Helper to recursively fetch dependencies for a given class."""
        from common.core.code_analyzer import SymbolType

        next_depth = current_depth + 1

        if self._is_potential_dto(class_fqn):
            self.logger.debug(f"'{class_fqn}' is a DTO. Fetching its parent DTOs.")
            parent_hierarchy = self.code_analyzer.get_type_hierarchy(class_fqn, definition_path)
            for parent_entry in parent_hierarchy:
                parent_fqn = parent_entry.get("name")
                if parent_fqn and self._is_potential_dto(parent_fqn):
                    self._fetch_recursive_context_java(
                        parent_fqn, SymbolType.CLASS, definition_path,
                        next_depth, max_depth, processed_keys, accumulator)

        for field_info in class_details.get("fields", []):
            field_type_fqn = field_info.get("type")
            base_field_type_fqn = self._get_base_type(field_type_fqn)
            if base_field_type_fqn and self._is_potential_dto(base_field_type_fqn):
                self._fetch_recursive_context_java(
                    base_field_type_fqn, SymbolType.CLASS, definition_path,
                    next_depth, max_depth, processed_keys, accumulator)

        for method_info in class_details.get("functions", []):
            method_fqn = f"{class_fqn}.{method_info.get('methodName')}"
            self._fetch_recursive_context_java(
                method_fqn, SymbolType.FUNCTION, definition_path,
                next_depth, max_depth, processed_keys, accumulator)

    def _recurse_on_function_dependencies(self, definition_path, function_details,
                                           current_depth, max_depth, processed_keys, accumulator):
        """Helper to recursively fetch dependencies for a given function."""
        from common.core.code_analyzer import SymbolType

        next_depth = current_depth + 1

        for ref_class_fqn in function_details.get("classNames", []):
            if self._is_potential_dto(ref_class_fqn) or not self._is_primitive_or_common(ref_class_fqn):
                self._fetch_recursive_context_java(
                    ref_class_fqn, SymbolType.CLASS, definition_path,
                    next_depth, max_depth, processed_keys, accumulator)

        for called_func_info in function_details.get("functionNames", []):
            target_method_name = called_func_info.get("simpleName")
            target_class_fqn = called_func_info.get("declaringClass")
            if target_method_name and target_class_fqn and not self._is_primitive_or_common(target_class_fqn):
                self._fetch_recursive_context_java(
                    f"{target_class_fqn}.{target_method_name}", SymbolType.FUNCTION, definition_path,
                    next_depth, max_depth, processed_keys, accumulator)

        for var_info in function_details.get("variableNames", []):
            var_type_fqn = var_info.get("type")
            base_var_type_fqn = self._get_base_type(var_type_fqn)
            if base_var_type_fqn and self._is_potential_dto(base_var_type_fqn):
                self._fetch_recursive_context_java(
                    base_var_type_fqn, SymbolType.CLASS, definition_path,
                    next_depth, max_depth, processed_keys, accumulator)

    def _gather_dependencies_recursively(self, start_fqn, visited_fqns,
                                          max_depth=5, debug_context_fqn=None):
        """
        Recursively gathers the code and context for a starting FQN and all of its
        nested DTO/Enum dependencies.

        Args:
            start_fqn:          FQN of the component to start from.
            visited_fqns:       Set of FQNs already processed (prevents infinite recursion).
            max_depth:          Maximum recursion depth.
            debug_context_fqn:  Optional parent FQN used only for log messages.

        Returns:
            A flat list of context dicts for the starting component and all its
            unique, nested dependencies.
        """
        from common.core.code_analyzer import SymbolType

        if debug_context_fqn:
            self.logger.info(
                f"[RECURSIVE_GATHER][{debug_context_fqn}] (Depth {5-max_depth}) "
                f"Analyzing dependencies for: {start_fqn}")

        if max_depth <= 0:
            self.logger.warning(f"Max recursion depth reached while gathering dependencies for {start_fqn}.")
            return []

        if start_fqn in visited_fqns:
            return []

        visited_fqns.add(start_fqn)
        dep_info = self.code_analyzer.get_symbol_info(start_fqn, self.project_path, SymbolType.CLASS)
        if not dep_info:
            self.logger.warning(f"Recursive gather: Could not get info for dependency '{start_fqn}'.")
            return []

        all_related_contexts = []

        is_enum = dep_info.get("isEnum", False)
        is_dto = self._is_potential_dto(start_fqn)
        is_dto = True  # preserved as-is from original
        if not is_enum and not is_dto:
            self.logger.debug(f"Recursive gather: Skipping '{start_fqn}' as it is not a DTO or Enum.")
            return []

        dep_type_for_header = "Enum" if is_enum else "DTO"
        dep_path = dep_info.get("classFileName") or dep_info.get("filePath")
        dep_code = self.code_analyzer.get_code_snippet(
            dep_path, dep_info.get("startLine"), dep_info.get("endLine"))

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

        if not is_enum:
            properties = self._get_all_properties_for_class(start_fqn)
            for prop in properties:
                base_type_fqn = self._get_base_type(prop.get("type"))
                if not base_type_fqn or base_type_fqn in visited_fqns:
                    continue
                nested_deps = self._gather_dependencies_recursively(
                    base_type_fqn, visited_fqns, max_depth - 1)
                all_related_contexts.extend(nested_deps)

        self.logger.debug(f"Gathering parent hierarchy for '{start_fqn}'...")
        parent_hierarchy = self.code_analyzer.get_type_hierarchy(start_fqn, dep_path)
        for parent_info in parent_hierarchy:
            parent_fqn = parent_info.get("name")
            if parent_fqn and parent_fqn not in visited_fqns:
                self.logger.debug(
                    f"'{start_fqn}' has parent '{parent_fqn}'. Kicking off recursive gather for it.")
                parent_deps = self._gather_dependencies_recursively(
                    parent_fqn, visited_fqns, max_depth - 1)
                all_related_contexts.extend(parent_deps)

        return all_related_contexts

    def _fetch_recursive_context_java(self, symbol_name_from_llm, symbol_type,
                                       referencing_context_path, current_depth, max_depth,
                                       processed_keys, accumulator):
        from common.core.code_analyzer import SymbolType

        if current_depth >= max_depth:
            return

        symbol_ref = self.code_analyzer.get_symbol_reference(
            symbol_name_from_llm, referencing_context_path, symbol_type)
        if not symbol_ref:
            self.logger.warning(
                f"{self.framework_name} (Recursive): Could not resolve "
                f"'{symbol_name_from_llm}' ({symbol_type.name}) from '{referencing_context_path}'.")
            return

        canonical_name = symbol_ref.get("canonicalName")
        definition_path = symbol_ref.get("definitionPath")

        if not canonical_name or not definition_path:
            return

        symbol_key = self._get_java_symbol_key(canonical_name, definition_path, symbol_type)
        if symbol_key in processed_keys:
            return

        symbol_details = self.code_analyzer.get_symbol_info(canonical_name, definition_path, symbol_type)
        if not symbol_details:
            processed_keys.add(symbol_key)
            return

        start_line = symbol_details.get("startLine")
        end_line = symbol_details.get("endLine")
        code_snippet = "// Code not retrieved"
        if start_line and end_line:
            snip = self.code_analyzer.get_code_snippet(definition_path, start_line, end_line)
            if snip:
                code_snippet = snip.strip()

        item_name_for_list = (
            canonical_name.split('.')[-1] if symbol_type == SymbolType.CLASS else canonical_name
        )
        accumulator.append({
            "name": item_name_for_list,
            "qualifiedName": canonical_name,
            "type": symbol_type.name.upper(),
            "path": definition_path,
            "start_line": start_line, "end_line": end_line, "code": code_snippet,
        })
        processed_keys.add(symbol_key)
        self.logger.debug(
            f"{self.framework_name} (Recursive) [Depth {current_depth}]: Added context for {symbol_key}")

        if current_depth + 1 < max_depth:
            if symbol_type == SymbolType.CLASS:
                self._recurse_on_class_dependencies(
                    canonical_name, definition_path, symbol_details,
                    current_depth, max_depth, processed_keys, accumulator)
            elif symbol_type == SymbolType.FUNCTION:
                self._recurse_on_function_dependencies(
                    definition_path, symbol_details,
                    current_depth, max_depth, processed_keys, accumulator)
