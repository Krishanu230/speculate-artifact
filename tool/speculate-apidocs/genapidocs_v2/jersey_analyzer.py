# speculate-apidocs/genapidocs_v2/jersey_analyzer.py

from collections import deque
import copy
import os
import json
import logging
import re
from typing import Dict, List, Optional, Any, Tuple, Set

# Import interfaces and base classes
from common.core.framework_analyzer import FrameworkAnalyzer
from common.core.code_analyzer import CodeAnalyzer, SymbolType
from java_analyzer import JavaCodeAnalyzer # Make sure this import works

# logger = logging.getLogger(__name__) # Use self.logger instead
NOISE_COMPONENT_BLACKLIST = [
    # Legacy V1/V2/V3 Models (Noise Category 1)
    "io.gravitee.definition.model.Endpoint",
    "io.gravitee.definition.model.EndpointGroup",
    "io.gravitee.definition.model.Proxy",
    "io.gravitee.definition.model.flow.Flow",
    "io.gravitee.definition.model.flow.Step",
    "io.gravitee.definition.model.flow.Consumer",
    "io.gravitee.definition.model.flow.PathOperator",
    "io.gravitee.definition.model.Logging",
    "io.gravitee.definition.model.LoadBalancer",
    "io.gravitee.definition.model.Failover",
    "io.gravitee.definition.model.Properties",
    "io.gravitee.definition.model.Property",
    "io.gravitee.definition.model.plugins.resources.Resource",
    "io.gravitee.rest.api.model.PlanEntity",
    "io.gravitee.rest.api.model.api.ApiEntity",
    "io.gravitee.rest.api.model.DebugApiEntity",
    "io.gravitee.rest.api.model.ApiPageEntity",
    "io.gravitee.rest.api.model.PageEntity",
    "io.gravitee.rest.api.model.PageEntity$PageRevisionId",
    "io.gravitee.rest.api.model.PageMediaEntity",
    "io.gravitee.rest.api.model.PageSourceEntity",
    "io.gravitee.rest.api.model.PlanSecurityType",
    "io.gravitee.rest.api.model.PlanStatus",
    "io.gravitee.rest.api.model.PlanType",
    "io.gravitee.rest.api.model.PlanValidationType",
    "io.gravitee.definition.model.HttpClientOptions",
    "io.gravitee.definition.model.HttpClientSslOptions",
    "io.gravitee.definition.model.HttpProxy",
    "io.gravitee.definition.model.HttpRequest",
    "io.gravitee.definition.model.HttpResponse",
    "io.gravitee.definition.model.VirtualHost",
    "io.gravitee.definition.model.ssl.KeyStore",
    "io.gravitee.definition.model.ssl.TrustStore",
    "io.gravitee.definition.model.Endpoint$Status",
    "io.gravitee.definition.model.ExecutionMode",
    "io.gravitee.definition.model.FailoverCase",
    "io.gravitee.definition.model.flow.FlowStage",
    "io.gravitee.definition.model.HttpProxyType",
    "io.gravitee.definition.model.LoadBalancerType",
    "io.gravitee.definition.model.LoggingContent",
    "io.gravitee.definition.model.LoggingMode",
    "io.gravitee.definition.model.LoggingScope",
    "io.gravitee.definition.model.ProtocolVersion",
    "io.gravitee.definition.model.ssl.KeyStoreType",
    "io.gravitee.definition.model.ssl.TrustStoreType",
    
    # Internal Service/Configuration Classes (Noise Category 2)
    "io.gravitee.definition.model.Service",
    "io.gravitee.definition.model.services.Services",
    "io.gravitee.definition.model.services.discovery.EndpointDiscoveryService",
    "io.gravitee.definition.model.services.dynamicproperty.DynamicPropertyProvider",
    "io.gravitee.definition.model.services.dynamicproperty.DynamicPropertyProviderConfiguration",
    "io.gravitee.definition.model.services.dynamicproperty.DynamicPropertyService",
    "io.gravitee.definition.model.services.healthcheck.HealthCheckService",
    "io.gravitee.definition.model.services.healthcheck.EndpointHealthCheckService",
    "io.gravitee.definition.model.services.healthcheck.HealthCheckStep",
    "io.gravitee.definition.model.services.healthcheck.HealthCheckRequest",
    "io.gravitee.definition.model.services.healthcheck.HealthCheckResponse",
    "io.gravitee.definition.model.services.schedule.ScheduledService",
    "io.gravitee.definition.model.endpoint.EndpointStatusListener",
    "io.gravitee.rest.api.management.v4.rest.resource.param.AbstractListParam",
    "io.gravitee.rest.api.management.v4.rest.resource.param.PlanStatusParam",
    "io.gravitee.rest.api.model.AccessControlEntity",
    
    # Marker Interfaces & Abstract/Utility Classes (Noise Category 3)
    "io.gravitee.definition.model.ConditionSupplier",
    "io.gravitee.rest.api.model.search.Indexable",
    "io.gravitee.rest.api.model.v4.api.GenericApiEntity",
    "io.gravitee.rest.api.model.v4.plan.GenericPlanEntity",
    
    # JDK/Common Lib classes incorrectly identified
    "java.io.Serializable",
    "java.lang.Cloneable",
    "java.lang.Comparable",
    "java.lang.Enum",
    "java.lang.Iterable",
    "java.lang.constant.Constable",
    "java.util.AbstractCollection",
    "java.util.AbstractList",
    "java.util.ArrayList",
    "java.util.Collection",
    "java.util.List",
    "java.util.RandomAccess",
    "java.util.SequencedCollection"
]
class JerseyFrameworkAnalyzer(FrameworkAnalyzer):
    """
    Jersey-specific implementation of the FrameworkAnalyzer interface.
    Uses JavaCodeAnalyzer output to identify endpoints and context.
    """

    def __init__(self, code_analyzer: CodeAnalyzer, project_path: str, logger=None):
        """
        Initialize with a JavaCodeAnalyzer instance.
        """
        if not isinstance(code_analyzer, JavaCodeAnalyzer):
            raise TypeError("JerseyFrameworkAnalyzer requires an instance of JavaCodeAnalyzer.")

        super().__init__(code_analyzer, project_path)
        self.logger = logger or logging.getLogger(__name__)
        self._cached_components: Optional[Dict[str, Dict[str, Any]]] = None
        self.endpoints= None 
        self.logger.info("JerseyFrameworkAnalyzer initialized.")
        self._implementations_map: Optional[Dict[str, List[str]]] = None
        self._serializers_map: Optional[Dict[str, str]] = None
        self._decoders_map: Optional[Dict[str, List[str]]] = None

        if not self.code_analyzer.analysis_results:
            self.logger.warning("CodeAnalyzer provided to JerseyFrameworkAnalyzer has not loaded analysis results.")

    def get_endpoints(self, output_dir: Optional[str] = None) -> List[Dict[str, Any]]:
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

        self.logger.info(f"Starting merge process for {len(raw_endpoint_methods)} raw endpoint method entries.")
        eee = []
        for r in raw_endpoint_methods: eee.extend(r['endpoints'])
        # --- Grouping Logic: Group raw methods by "HTTP_METHOD /path" ---
        grouped_methods: Dict[str, List[Dict]] = {}
        for raw_method_data in raw_endpoint_methods:
            for endpoint_path_info in raw_method_data.get("endpoints", []):
                path = endpoint_path_info.get("path")
                http_method = endpoint_path_info.get("httpMethod", "").lower()
                if not path or not http_method:
                    continue

                operation_key = f"{http_method.upper()} {path}"
                if operation_key not in grouped_methods:
                    grouped_methods[operation_key] = []
                grouped_methods[operation_key].append(raw_method_data)

        # --- Merging Logic: Process each group into a single endpoint definition ---
        final_merged_endpoints = []
        for operation_key, method_group in grouped_methods.items():
            base_method_info = method_group[0]
            base_endpoint_info = base_method_info.get("endpoints")[0]

            http_method = base_endpoint_info.get("httpMethod").upper()
            path = base_endpoint_info.get("path")
            handler_class_fqn = base_method_info.get("className")

            if not handler_class_fqn:
                self.logger.warning(f"Skipping group for {operation_key} due to missing className.")
                continue

            handler_class_info = self.code_analyzer.get_symbol_info(handler_class_fqn, self.project_path, SymbolType.CLASS)
            handler_file_path = (handler_class_info.get("classFileName") or handler_class_info.get("filePath"))if handler_class_info else "unknown_path.java"
            
            merged_metadata = {
                "handler_class_fqn": handler_class_fqn,
                "implementing_methods": []
            }

            all_path_params = {}
            handler_count = len(method_group)
            for method_info in method_group:
                method_details = {
                    "method_name": method_info.get("name"),
                    "signature": method_info.get("signature"),
                    "consumes": method_info.get("consumes", []),
                    "produces": method_info.get("produces", []),
                    "all_parameters": method_info.get("allParameters", [])
                }
                merged_metadata["implementing_methods"].append(method_details)
                
                for endpoint_data in method_info.get("endpoints", []):
                    for param in endpoint_data.get("parameters", []):
                        if param.get("in") == "path":
                            all_path_params[param.get("name")] = param

            merged_endpoint = {
                "url": {
                    "url": path,
                    "parameter": list(all_path_params.values())
                },
                "method": http_method,
                "view": handler_class_fqn.split('.')[-1],
                "path": os.path.abspath(handler_file_path) if handler_file_path else None,
                "is_viewset": True,
                "function": base_method_info.get("name"),
                "metadata": merged_metadata,
                "handler_count": handler_count
            }
            final_merged_endpoints.append(merged_endpoint)

        self.logger.info(f"Finished merge. Produced {len(final_merged_endpoints)} unique API operations.")
        
        self.endpoints = final_merged_endpoints
        return self.endpoints

    def _find_request_body_parameter(self, method_parameters_from_soot: List[Dict]) -> Optional[Dict]:
        """
        Identifies the parameter representing the request body from a list of method parameters.
        Input: method_parameters_from_soot is a list of parameter dicts from soot-analysis.json.
               Each dict has "name", "type" (Java FQN), "annotations" (list of annotation dicts).
        """
        JAX_RS_PARAM_ANNOTATIONS_FQNS = {
            "javax.ws.rs.PathParam", "jakarta.ws.rs.PathParam",
            "javax.ws.rs.QueryParam", "jakarta.ws.rs.QueryParam",
            "javax.ws.rs.HeaderParam", "jakarta.ws.rs.HeaderParam",
            "javax.ws.rs.CookieParam", "jakarta.ws.rs.CookieParam",
            "javax.ws.rs.MatrixParam", "jakarta.ws.rs.MatrixParam",
            "javax.ws.rs.FormParam", "jakarta.ws.rs.FormParam",
            "javax.ws.rs.BeanParam", "jakarta.ws.rs.BeanParam", # BeanParam itself is not the body
            "javax.ws.rs.core.Context", "jakarta.ws.rs.core.Context"
        }

        # Check if any parameter is annotated with @FormParam
        has_form_params = any(
            ann.get("name") in {"javax.ws.rs.FormParam", "jakarta.ws.rs.FormParam"}
            for param_info_soot in method_parameters_from_soot
            for ann in param_info_soot.get("annotations", [])
        )

        if has_form_params:
            self.logger.debug("Method has @FormParam; request body is form data, not a single POJO.")
            return None # No single POJO represents the body

        candidate_body_param = None
        for param_info_soot in method_parameters_from_soot:
            is_jax_rs_other_param = False
            param_annotations = param_info_soot.get("annotations", [])
            for ann in param_annotations:
                if ann.get("name") in JAX_RS_PARAM_ANNOTATIONS_FQNS:
                    is_jax_rs_other_param = True
                    break
            
            if not is_jax_rs_other_param:
                # This parameter is not explicitly a JAX-RS path/query/header etc. param. It's a candidate for body.
                # Prioritize if its type is a DTO.
                param_type_java_fqn = param_info_soot.get("type")
                # Use the existing _get_base_type for consistency
                base_type_fqn = self._get_base_type(param_type_java_fqn)
                if base_type_fqn and self._is_potential_dto(base_type_fqn):
                    self.logger.debug(f"Identified request body parameter (DTO type): {param_info_soot.get('name')} of type {param_type_java_fqn}")
                    return param_info_soot # Found a DTO, likely the body
                elif not candidate_body_param: # If not a DTO, keep it as a weaker candidate
                    candidate_body_param = param_info_soot
        
        if candidate_body_param:
            self.logger.debug(f"Identified potential request body parameter (non-DTO or fallback): {candidate_body_param.get('name')} of type {candidate_body_param.get('type')}")
        return candidate_body_param

    def _extract_class_annotation_value(self, annotations_list_from_soot: List[Dict], target_annotation_fqn: str, annotation_param_name: str = "value") -> Optional[Any]:
        """
        Extracts a value from a specific annotation in a list of annotation objects.
        Input: annotations_list_from_soot is a list of annotation dicts from soot-analysis.json.
               Each dict has "name" (annotation FQN) and "elements" (dict of its params).
        """
        for ann_data in annotations_list_from_soot:
            if ann_data.get("name") == target_annotation_fqn:
                # 'elements' is a dict like {"value": "application/json"} or {"value": ["app/json", "app/xml"]}
                value_from_elements = ann_data.get("elements", {}).get(annotation_param_name)
                if value_from_elements is not None:
                    # If value is a list (e.g. @Produces multiple types), return the list or first element based on need.
                    # For @Consumes/@Produces, typically one primary type is used, or LLM handles multiple.
                    if isinstance(value_from_elements, list) and value_from_elements:
                        return value_from_elements # Return the list for @Produces, LLM can pick
                    elif isinstance(value_from_elements, str):
                        return value_from_elements
                    # Handle other types if necessary (e.g. int, boolean if annotation params are such)
                    return str(value_from_elements) # Fallback to string
        return None
    
    def get_endpoint_context(self, endpoint: Dict[str, Any]) -> Dict[str, Any]:
        """
        Builds a single, combined context from a MERGED endpoint object.
        This is the final, refactored version that leverages the component cache,
        handles polymorphic DTOs, and correctly aggregates JAX-RS media types.
        """
        handler_class_fqn = endpoint.get("metadata", {}).get("handler_class_fqn")
        if not handler_class_fqn:
            self.logger.error("Endpoint metadata is missing 'handler_class_fqn'.")
            return {}

        if self._cached_components is None:
            self.logger.info("Component cache is empty, building it now before gathering endpoint context.")
            self.get_schema_components()

        # Initialize the final, aggregated context object.
        final_context = {
            "endpoint": endpoint, "handler_methods": [], "pojos": [], "handler_classes": [],
            "other_context": [], "framework_settings": {"framework": "jersey", "settings": {}}
        }

        # Use maps for efficient deduplication during aggregation.
        pojos_map = {}
        handler_classes_map = {}
        other_context_map = {}

        # Initialize sets to gather all media types.
        all_method_consumes = set()
        all_method_produces = set()

        # --- AGGREGATION LOOP ---
        for method_details in endpoint.get("metadata", {}).get("implementing_methods", []):
            method_signature = method_details.get("signature")
            if not method_signature: continue

            # Gather media types from the Respector data for each method.
            all_method_consumes.update(method_details.get("consumes", []))
            all_method_produces.update(method_details.get("produces", []))

            # Call the helper to get the context for this single Java method.
            single_method_context = self._get_refactored_single_method_context(handler_class_fqn, method_signature)
            if not single_method_context: continue
            
            # --- Aggregation of all context parts ---
            final_context['handler_methods'].append(single_method_context['handler'])

            if single_method_context['handler_full']:
                handler_classes_map[handler_class_fqn] = single_method_context['handler_full']

            for pojo_ctx in single_method_context.get('pojos', []):
                pojos_map[pojo_ctx['qualifiedName']] = pojo_ctx
            
            # (Currently other_context is empty, but this makes it ready for the future)
            for other_ctx in single_method_context.get('other_context', []):
                other_context_map[other_ctx['qualifiedName']] = other_ctx

        # Populate the final context with the deduplicated items.
        final_context['handler_classes'] = list(handler_classes_map.values())
        final_context['pojos'] = list(pojos_map.values())
        final_context['other_context'] = list(other_context_map.values())

        # --- MEDIA TYPE FINALIZATION ---
        class_info = self.code_analyzer.get_symbol_info(handler_class_fqn, self.project_path, SymbolType.CLASS)
        class_annotations = class_info.get("annotations", []) if class_info else []
        class_consumes = self._extract_media_types(class_annotations, "Consumes")
        class_produces = self._extract_media_types(class_annotations, "Produces")
        
        final_consumes = set(class_consumes)
        final_produces = set(class_produces)
        final_consumes.update(all_method_consumes)
        final_produces.update(all_method_produces)

        # Handle form parameter nuances
        has_form_data_param = False
        has_form_param = False
        for handler_ctx in final_context.get("handler_methods", []):
            for param_info in handler_ctx.get("method_parameters_info", []):
                for ann in param_info.get("annotations", []):
                    ann_type = ann.get("type", "")
                    if ann_type.endswith("FormDataParam;"): has_form_data_param = True
                    elif ann_type.endswith("FormParam;"): has_form_param = True
            if has_form_data_param and has_form_param: break
        
        if has_form_data_param:
            self.logger.debug("Found @FormDataParam in endpoint. Inferring 'multipart/form-data'.")
            final_consumes.add("multipart/form-data")
        if has_form_param and not has_form_data_param:
            self.logger.debug("Found @FormParam in endpoint. Inferring 'application/x-www-form-urlencoded'.")
            final_consumes.add("application/x-www-form-urlencoded")

        final_context["framework_settings"]["settings"] = {
            "all_consumes": sorted(list(final_consumes)),
            "all_produces": sorted(list(final_produces)),
        }

        if final_context["handler_methods"]:
            final_context["handler"] = final_context["handler_methods"][0]

        return final_context

    def _parse_jsonsubtypes_annotation(self, class_info: Dict[str, Any]) -> Set[str]:
        """
        Parses a @JsonSubTypes annotation on a class to extract the FQNs of the concrete subtypes.
        """
        sub_type_fqns = set()
        json_subtypes_annotation_type = "Lcom/fasterxml/jackson/annotation/JsonSubTypes;"

        for ann in class_info.get("annotations", []):
            if ann.get("type") == json_subtypes_annotation_type:
                # The 'value' element of @JsonSubTypes is an array of @JsonSubTypes.Type annotations.
                value_element = next((el for el in ann.get("elements", []) if el.get("name") == "value"), None)
                if not value_element or not isinstance(value_element.get("value"), list):
                    continue

                # Each item in the list is a nested annotation object representing @Type
                for type_annotation_obj in value_element.get("value"):
                    if not isinstance(type_annotation_obj, dict) or not type_annotation_obj.get("type", "").endswith("$Type;"):
                        continue
                    
                    # The 'value' element of the @Type annotation contains the class FQN.
                    type_value_element = next((el for el in type_annotation_obj.get("elements", []) if el.get("name") == "value"), None)
                    if type_value_element and type_value_element.get("kind") == 'c':
                        # Kind 'c' represents a class literal. The value is a soot-style descriptor.
                        class_descriptor = type_value_element.get("value")
                        fqn = self._soot_descriptor_to_fqn(class_descriptor)
                        if fqn:
                            sub_type_fqns.add(fqn)
        return sub_type_fqns
    
    def _get_refactored_single_method_context(self, class_fqn: str, method_signature: str) -> Optional[Dict[str, Any]]:
        """
        Assembles context for a single Java method, including all nuances like
        polymorphic DTOs and custom MessageBodyReaders.
        """
        class_info = self.code_analyzer.get_symbol_info(class_fqn, self.project_path, SymbolType.CLASS)
        if not class_info: return None
        method_info = next((m for m in class_info.get("functions", []) if m.get("signature") == method_signature), None)
        if not method_info: return None

        handler_file_path = class_info.get("classFileName") or class_info.get("filePath")
        class_start_line = class_info.get("startLine")
        class_end_line = class_info.get("endLine")
        class_code_snippet = self.code_analyzer.get_code_snippet(
                handler_file_path, class_start_line, class_end_line
            )

        handler_ctx = {
            "name": method_info.get("methodName"), "type": "jax-rs.method", "path": handler_file_path,
            "code": class_code_snippet,
            "location": {"start_line": method_info.get("startLine"), "end_line": method_info.get("endLine")},
            "class_name_fqn": class_fqn, "method_annotations": method_info.get("annotations", []),
            "method_parameters_info": method_info.get("parameters", []), "returnType": method_info.get("returnType", "void")
        }
        handler_class_ctx = None
        if class_code_snippet:
            handler_class_ctx = {"name": class_fqn.split('.').pop(), "type": "class", "path": handler_file_path,
                                 "code": class_code_snippet, "qualifiedName": class_fqn}

        pojos_to_include_map = {}
        other_dependencies_map = {} # Use a map for deduplication

        # --- Request Body Processing (including custom decoder/MessageBodyReader) ---
        request_param = self._find_request_body_parameter(method_info.get("parameters", []))
        if request_param:
            request_base_fqn = self._get_base_type(request_param.get("type"))
            if request_base_fqn:
                request_dtos = self._resolve_concrete_dtos_from_cache(request_base_fqn)
                for dto in request_dtos:
                    pojos_to_include_map[dto['qualifiedName']] = dto

                # This check happens AFTER we've identified the request body's type.
                decoder_info = self._find_decoder_for_type(request_base_fqn)
                if decoder_info:
                    decoder_fqn = decoder_info.get('className')
                    self.logger.info(f"Found custom decoder (MessageBodyReader) '{decoder_fqn}' for type '{request_base_fqn}'.")
                    decoder_code = self.code_analyzer.get_code_snippet_from_info(decoder_info)
                    path = decoder_info.get("classFileName") or decoder_info.get("filePath")
                    if decoder_code:
                        other_dependencies_map[decoder_fqn] = {
                            "name": decoder_fqn.split('.').pop(),
                            "type": "DECODER",
                            "path": path,
                            "code": decoder_code,
                            "qualifiedName": decoder_fqn
                        }

        # --- Response Body Processing (unchanged from last step) ---
        response_base_fqn = self._get_base_type(method_info.get("returnType"))
        if response_base_fqn:
            response_type_info = self.code_analyzer.get_symbol_info(response_base_fqn, self.project_path, SymbolType.CLASS)
            
            if response_type_info and response_type_info.get("isInterface"):
                sub_types = self._parse_jsonsubtypes_annotation(response_type_info)
                if sub_types:
                    # Tier 1: Annotation-based
                    for impl_fqn in sub_types:
                        if impl_fqn in self._cached_components:
                            pojos_to_include_map[impl_fqn] = self._cached_components[impl_fqn]
                else:
                    # Tier 2: Fallback to all implementations
                    all_implementations = self._resolve_concrete_dtos_from_cache(response_base_fqn)
                    for impl_ctx in all_implementations:
                        pojos_to_include_map[impl_ctx['qualifiedName']] = impl_ctx
                
                interface_code = self.code_analyzer.get_code_snippet_from_info(response_type_info)
                if interface_code:
                    interface_path = response_type_info.get("classFileName") or response_type_info.get("filePath")
                    pojos_to_include_map[response_base_fqn] = {"name": response_base_fqn.split('.').pop(), "type": "interface",
                                                             "path": interface_path,
                                                             "code": interface_code, "qualifiedName": response_base_fqn}
            else:
                if response_base_fqn in self._cached_components:
                    pojos_to_include_map[response_base_fqn] = self._cached_components[response_base_fqn]

        return {"handler": handler_ctx,
                "handler_full": handler_class_ctx,
                "pojos": list(pojos_to_include_map.values()),
                "other_context": list(other_dependencies_map.values())}

    def _resolve_concrete_dtos_from_cache(self, fqn: str) -> List[Dict[str, Any]]:
        """
        Given an FQN, finds the rich context for its concrete DTO implementation(s)
        by looking them up in the component cache.
        """
        results = []
        type_info = self.code_analyzer.get_symbol_info(fqn, self.project_path, SymbolType.CLASS)

        if type_info and type_info.get("isInterface"):
            self._build_discovery_maps()
            implementations = self._implementations_map.get(fqn, [])
            for impl_fqn in implementations:
                if impl_fqn in self._cached_components:
                    results.append(self._cached_components[impl_fqn])
        else:
            if fqn in self._cached_components:
                results.append(self._cached_components[fqn])

        return results

    def _find_concrete_types_in_code(self, method_info: Dict[str, Any], interface_fqn: str) -> Set[str]:
        """
        Scans for evidence of which concrete implementations of an interface are used.
        Uses a multi-strategy approach for robustness.
        """
        found_concrete_fqns = set()
        self._build_discovery_maps()
        all_implementations = set(self._implementations_map.get(interface_fqn, []))
        if not all_implementations:
            self.logger.warning(f"No known implementations found for interface '{interface_fqn}'.")
            return set()

        # --- Strategy 1: Look for Builder Pattern evidence (Handles factories like RestModels) ---
        # This is highly reliable for libraries like Immutables.io.
        # We look for calls to a '.build()' method on a builder that belongs to a known implementation.
        for called_func in method_info.get("functionNames", []):
            if called_func.get("methodName") == "build":
                # The method called on is the Builder class, e.g., "...ImmutableRestWorkflowDefinition$Builder"
                builder_fqn = called_func.get("invokedOn") 
                if builder_fqn and builder_fqn.endswith('$Builder'):
                    # Infer the parent class FQN by removing '$Builder'
                    potential_concrete_fqn = builder_fqn[:-len('$Builder')]
                    if potential_concrete_fqn in all_implementations:
                        self.logger.debug(f"Evidence found via Builder pattern: '{potential_concrete_fqn}'")
                        found_concrete_fqns.add(potential_concrete_fqn)

        # --- Strategy 2: Direct Instantiations and simple Method Returns (Original Logic) ---
        # This is good for simple cases.
        for class_name_used in method_info.get("classNames", []):
            if class_name_used in all_implementations:
                self.logger.debug(f"Evidence found via direct instantiation: '{class_name_used}'")
                found_concrete_fqns.add(class_name_used)

        for called_func in method_info.get("functionNames", []):
            return_type_of_call = self._get_base_type(called_func.get("returnType"))
            if return_type_of_call in all_implementations:
                self.logger.debug(f"Evidence found via direct method return type: '{return_type_of_call}'")
                found_concrete_fqns.add(return_type_of_call)

        # --- Strategy 3: Last Resort Fallback ---
        # If we found NO evidence at all, but there is ONLY ONE possible implementation
        # in the entire project, it's a very safe bet that it's the one being used.
        if not found_concrete_fqns and len(all_implementations) == 1:
            the_only_one = list(all_implementations)[0]
            self.logger.debug(f"No direct evidence found. Falling back to the only known implementation: '{the_only_one}'")
            found_concrete_fqns.add(the_only_one)


        if not found_concrete_fqns:
            self.logger.warning(f"Could not find any static evidence for concrete implementations of '{interface_fqn}' in method '{method_info.get('methodName')}'. Spec may be incomplete.")
        
        return found_concrete_fqns
    
    def _is_internal_project_symbol(self, fqn: Optional[str]) -> bool:
        """
        Checks if a given FQN is likely part of the user's project codebase,
        not a common Java/Jakarta/framework library. This is key to reducing noise.
        """
        if not fqn:
            return False
        
        # A list of common prefixes for libraries we want to exclude from deep context gathering.
        excluded_prefixes = [
            "java.", "javax.", "jakarta.",
            "com.google.", "org.slf4j.", "ch.qos.logback.",
            "org.glassfish.", "com.fasterxml.jackson.", "org.joda.time."
        ]
        
        if any(fqn.startswith(prefix) for prefix in excluded_prefixes):
            return False
        
        # Heuristic: If it doesn't start with a common library prefix,
        # we assume it's an internal project symbol worth investigating.
        return True
    
    def _is_excluded_dependency(self, fqn: str, method_name: str) -> bool:
        """
        Determines if a dependency should be excluded from recursive context gathering
        based on generic architectural patterns.
        """
        simple_class_name = fqn.split('.')[-1]

        # Boundary 2: Authorization / Rights Checks
        if ".rights." in fqn or ".auth." in fqn:
            self.logger.debug(f"Excluding '{fqn}' based on authorization package name pattern.")
            return True
        if method_name in ("checkRights", "authorize", "checkPermission"):
            self.logger.debug(f"Excluding dependency triggered by auth-like method call: '{method_name}'")
            return True

        # Boundary 3 & 4 (Combined): Persistence and Events
        # Check for common suffixes that indicate the class's role.
        if simple_class_name.endswith("Dao") or \
           simple_class_name.endswith("Repository") or \
           simple_class_name.endswith("Event"): # <-- NEW RULE
            self.logger.debug(f"Excluding '{fqn}' based on DAO, Repository, or Event naming convention.")
            return True

        # Check for common EventBus/Dispatcher patterns
        if "EventBus" in fqn and method_name in ("post", "publish", "dispatch"):
            self.logger.debug(f"Excluding '{fqn}' based on EventBus pattern.")
            return True
            
        return False
    
    def _collect_dependency_context_recursively(self,
                                                start_fqn: str,
                                                visited_fqns: Set[str],
                                                accumulator: List[Dict[str, Any]],
                                                max_depth: int = 5,
                                                current_depth: int = 0):
        """
        Recursively collects the source code context for a class and its internal dependencies.
        """
        # --- Base Cases to stop recursion ---
        if current_depth >= max_depth:
            self.logger.debug(f"Max depth reached for {start_fqn}.")
            return

        if not start_fqn or start_fqn in visited_fqns:
            return

        # --- Filter out non-project symbols before processing ---
        if not self._is_internal_project_symbol(start_fqn):
            self.logger.debug(f"Skipping non-project symbol: {start_fqn}")
            return
            
        visited_fqns.add(start_fqn)
        self.logger.info(f"[Context Gatherer][Depth {current_depth}] Processing: {start_fqn}")

        # --- Get Symbol Info & Add to Accumulator ---
        class_info = self.code_analyzer.get_symbol_info(start_fqn, self.project_path, SymbolType.CLASS)
        if not class_info:
            return

        file_path = class_info.get("classFileName") or class_info.get("filePath")
        start_line, end_line = class_info.get("startLine"), class_info.get("endLine")

        if file_path and start_line and end_line:
            code_snippet = self.code_analyzer.get_code_snippet(file_path, start_line, end_line)
            if code_snippet:
                accumulator.append({
                    "name": start_fqn.split('.')[-1],
                    "type": "class",
                    "path": file_path,
                    "code": code_snippet,
                    "qualifiedName": start_fqn
                })
        
        # --- Find Next Targets for Recursion ---
        next_targets_to_visit = set()

        # Target 1: Parent classes
        for parent_fqn in class_info.get("parentClasses", []):
            next_targets_to_visit.add(parent_fqn)

        # Target 2: Injected Fields (Heuristic for DI)
        for field in class_info.get("fields", []):
            is_injected = any(ann.get("type", "").endswith("Inject;") for ann in field.get("annotations", []))
            if is_injected:
                field_type_fqn = self._get_base_type(field.get("type"))
                if field_type_fqn:
                    next_targets_to_visit.add(field_type_fqn)

        # Target 3: Method call declarations
        for method in class_info.get("functions", []):
            for called_func in method.get("functionNames", []):
                declaring_class_fqn = called_func.get("declaringClass")
                called_method_name = called_func.get("simpleName")
                if not declaring_class_fqn or not called_method_name:
                    continue
                if not self._is_excluded_dependency(declaring_class_fqn, called_method_name):
                    next_targets_to_visit.add(declaring_class_fqn)

        if class_info.get("isInterface", False):
            self.logger.debug(f"'{start_fqn}' is an interface. Looking for concrete implementation...")
            # Reuse the existing helper method
            implementation_info = self._find_concrete_implementation(start_fqn)
            if implementation_info and implementation_info.get("className"):
                impl_fqn = implementation_info.get("className")
                self.logger.info(f"Found implementation for '{start_fqn}': '{impl_fqn}'. Adding to targets.")
                next_targets_to_visit.add(impl_fqn)

        # --- Recurse on the discovered targets ---
        for fqn in next_targets_to_visit:
            self._collect_dependency_context_recursively(
                fqn, visited_fqns, accumulator, max_depth, current_depth + 1
            )

    def _find_decoder_for_type(self, type_fqn: str) -> Optional[Dict[str, Any]]:
        """
        Finds the JAX-RS MessageBodyReader for a given type FQN using the pre-built map.
        
        Args:
            type_fqn: The fully qualified name of the Java type (e.g., the request body POJO).

        Returns:
            The symbol information dictionary for the decoder class, or None if not found.
        """
        self._build_discovery_maps() # Ensures maps are ready, but won't re-run if they are.
        
        decoder_fqns = self._decoders_map.get(type_fqn, [])
        if not decoder_fqns:
            self.logger.debug(f"No specific decoder found in map for type '{type_fqn}'.")
            return None

        # A more advanced implementation could inspect the decoder's @Consumes annotation
        # to find the one for "application/json", but picking the first is robust for now.
        best_decoder_fqn = decoder_fqns[0]
        self.logger.info(f"Found specific decoder via map for '{type_fqn}': '{best_decoder_fqn}'")
        
        # Return the full context of this decoder class
        return self.code_analyzer.get_symbol_info(best_decoder_fqn, self.project_path, SymbolType.CLASS)


    def _extract_media_types(self, annotations_list: List[Dict], annotation_simple_name: str) -> Set[str]:
        """Helper to extract media types from @Consumes or @Produces annotations."""
        media_types = set()
        # JAX-RS spec allows multiple annotations or one annotation with multiple values
        for ann_data in annotations_list:
            ann_fqn = ann_data.get("name")
            if ann_fqn and ann_fqn.endswith(f".{annotation_simple_name}"):
                # 'elements' is a dict like {"value": "application/json"} or {"value": ["app/json", "app/xml"]}
                values = ann_data.get("elements", {}).get("value")
                if isinstance(values, list):
                    media_types.update(values)
                elif isinstance(values, str):
                    media_types.add(values)
        return media_types

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

    def _get_java_symbol_key(self, qualified_name: Optional[str], definition_file_path: Optional[str], symbol_type_info: Any) -> Optional[str]:
        if not qualified_name or not definition_file_path: return None
        
        type_str_upper = ""
        if isinstance(symbol_type_info, SymbolType):
            type_str_upper = symbol_type_info.name # e.g., "CLASS", "FUNCTION"
        elif isinstance(symbol_type_info, str):
            type_str_upper = symbol_type_info.upper()
        else:
            self.logger.warning(f"Jersey _get_java_symbol_key: Unknown type_info")
            return None
            
        # Normalize path for consistency
        norm_path = os.path.normpath(os.path.abspath(definition_file_path))
        return f"{norm_path}:{qualified_name}:{type_str_upper}"

    def optimize_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        optimized_ctx = copy.deepcopy(context)
        if "extra_context" not in optimized_ctx or not optimized_ctx["extra_context"]:
            return optimized_ctx

        self.logger.debug("Jersey: Optimizing context by removing duplicates from 'extra_context'...")
        primary_context_item_keys: Set[str] = set()

        # Handler class and method
        handler_details = optimized_ctx.get("handler")
        if handler_details:
            # Key for the handler class itself
            class_fqn = handler_details.get("class_name_fqn")
            class_path = handler_details.get("path")
            if class_fqn and class_path:
                key = self._get_java_symbol_key(class_fqn, class_path, SymbolType.CLASS)
                if key: primary_context_item_keys.add(key)
            
            # Key for the specific handler method
            method_name = handler_details.get("name") # simple method name
            if class_fqn and method_name and class_path:
                method_fqn_key_part = f"{class_fqn}.{method_name}"
                key = self._get_java_symbol_key(method_fqn_key_part, class_path, SymbolType.FUNCTION)
                if key: primary_context_item_keys.add(key)

        # POJOs included in the primary "pojos" list (and their data_classes)
        for pojo_item in optimized_ctx.get("pojos", []):
            pojo_fqn = pojo_item.get("qualifiedName")
            pojo_path = pojo_item.get("path")
            if pojo_fqn and pojo_path:
                key = self._get_java_symbol_key(pojo_fqn, pojo_path, SymbolType.CLASS)
                if key: primary_context_item_keys.add(key)
            # Also consider nested DTOs that were part of this POJO's direct context
            for nested_dto in pojo_item.get("data_classes", []):
                nested_fqn = nested_dto.get("qualifiedName")
                nested_path = nested_dto.get("path")
                if nested_fqn and nested_path:
                    key = self._get_java_symbol_key(nested_fqn, nested_path, SymbolType.CLASS)
                    if key: primary_context_item_keys.add(key)


        # Features (if structured similarly with qualifiedName, path, type)
        for feature_item in optimized_ctx.get("features", []):
            feat_fqn = feature_item.get("qualifiedName") or feature_item.get("name") # Fallback for name
            feat_path = feature_item.get("path")
            feat_type = feature_item.get("type") # Assuming this is "CLASS" or SymbolType.CLASS
            if feat_fqn and feat_path and feat_type:
                key = self._get_java_symbol_key(feat_fqn, feat_path, feat_type)
                if key: primary_context_item_keys.add(key)
        
        self.logger.debug(f"Jersey optimize_context: Collected {len(primary_context_item_keys)} primary context keys: {primary_context_item_keys}")
        
        original_extra_count = len(optimized_ctx["extra_context"])
        deduplicated_extra_context_list = []
        # Track keys from extra_context itself to avoid adding duplicates *within* extra_context if LLM was repetitive
        keys_added_to_deduplicated_extra = set()

        for extra_item in optimized_ctx["extra_context"]:
            # extra_item structure: {"qualifiedName": FQN or FQN.method, "path": def_path, "type": "CLASS" or "FUNCTION"}
            extra_item_key = self._get_java_symbol_key(
                extra_item.get("qualifiedName"), 
                extra_item.get("path"), 
                extra_item.get("type") # Should be "CLASS" or "FUNCTION" string here
            )
            if not extra_item_key:
                self.logger.warning(f"Jersey optimize_context: Skipping extra_context item due to missing key parts: {extra_item.get('qualifiedName')}")
                continue

            if extra_item_key not in primary_context_item_keys and \
               extra_item_key not in keys_added_to_deduplicated_extra:
                deduplicated_extra_context_list.append(extra_item)
                keys_added_to_deduplicated_extra.add(extra_item_key)
            # else:
                # self.logger.debug(f"Jersey optimize_context: REMOVING {extra_item_key} from extra_context (already primary or duplicate extra)")
        
        removed_count = original_extra_count - len(deduplicated_extra_context_list)
        if removed_count > 0:
            self.logger.info(f"Jersey optimize_context: Removed {removed_count} redundant symbols from 'extra_context'.")
        
        optimized_ctx["extra_context"] = deduplicated_extra_context_list
        return optimized_ctx

    # --- Prompt instruction methods for PromptManager ---
    def get_endpoint_request_system_message(self) -> str:
        return "You are an expert in Java, JAX-RS (Jersey), relevant serialization libraries (Jackson, JAXB), and OpenAPI 3.0. Your task is to analyze a Java JAX-RS endpoint method to define its OpenAPI parameters, requestBody."

    def _get_jersey_formatted_framework_settings_prompt(self, endpoint_context: Dict[str, Any]) -> str:
        """Helper to generate Jersey framework settings string for the prompt."""
        settings = endpoint_context.get("framework_settings", {}).get("settings", {})
        lines = []
        # For Jersey, this might include default @Consumes/@Produces if not method/class specific
        # For now, let's assume endpoint-specific annotations are primary.
        # This can be expanded if global Jersey defaults are needed.
        
        # Example:
        # class_consumes = settings.get('class_consumes')
        # if class_consumes: lines.append(f"Default Class @Consumes: {class_consumes}")
        # class_produces = settings.get('class_produces')
        # if class_produces: lines.append(f"Default Class @Produces: {class_produces}")
        
        if not lines:
            return "No specific global framework settings identified for this JAX-RS endpoint request beyond method/class annotations."
        return "\n".join(lines)
    
    def get_endpoint_request_instructions(self, endpoint: Dict[str, Any], endpoint_context: Dict[str, Any], skip_components: bool = False) -> str:
        url = endpoint.get("url", {}).get("url", "N/A")
        method_lower = endpoint.get("method", "N/A").lower()
        endpoint_display_name = f"the API endpoint handling {method_lower.upper()} {url}"
        
        handler_details = endpoint_context.get("handler", {})
        handler_method_name = handler_details.get("name", "UnknownMethod")
        handler_class_fqn = handler_details.get("class_name_fqn", "UnknownClass")
        fn_name_for_prompt = f"{handler_class_fqn}.{handler_method_name}" # Used for display
        handler_methods = endpoint_context.get("handler_methods", [])

        unique_parameters = {}
        for method_handler in handler_methods:
            for param_info in method_handler.get("method_parameters_info", []):
                param_name = param_info.get("name")
                if param_name and param_name not in unique_parameters:
                    unique_parameters[param_name] = param_info
                    
        # Path parameters from URL structure
        path_params_from_url_list = endpoint.get("url", {}).get("parameter", [])
        path_params_guidance_list = [f"name: {p['name']}" + (f", type hint: {p.get('type')}" if p.get('type') else "") for p in path_params_from_url_list]
        path_params_guidance_from_url = f"Path parameters identified in URL template: [{'; '.join(path_params_guidance_list)}]." if path_params_guidance_list else "No path parameters in URL template."

        # Method parameters info from Soot analysis (in handler_context)
        method_param_details_str_list = []
        for param_name, p_soot in unique_parameters.items():
            # (The existing formatting loop can be reused here)
            annotations_on_param = p_soot.get("annotations", [])
            if not isinstance(annotations_on_param, list):
                annotations_on_param = []
            param_ann_names = []
            for ann in annotations_on_param:
                simple_name = self._get_simple_name_from_annotation_type(ann)
                if simple_name:
                    param_ann_names.append(simple_name)
            param_ann_str = f" Annotations: [{', '.join(param_ann_names)}]" if param_ann_names else ""
            method_param_details_str_list.append(
                f"- Java Param: type='{p_soot.get('type', 'Object')}', name in code='{p_soot.get('name', 'unknown')}'{param_ann_str}"
            )

        method_params_guidance_from_soot = "Analyzed Java method parameters (from signature & annotations):\n" + "\n".join(method_param_details_str_list) \
            if method_param_details_str_list else "No detailed Java method parameters found in handler context."

        if skip_components:
            request_body_schema_instructions = """
        - The `schema` for any request body MUST be defined INLINE. DO NOT use a `$ref`.
        - If the Java parameter type is a collection (e.g., `java.util.List<com.example.ItemDTO>`), the schema should be `type: array` with its `items` schema also defined INLINE.
"""
        else:
            request_body_schema_instructions = """
        - The `schema` should generally be a `$ref` to the corresponding component schema, named with a 'Request' suffix (e.g., `#/components/schemas/MyRequestDTORequest`).
        - If the Java parameter type is a collection (e.g., `java.util.List<com.example.ItemDTO>`), the schema should be `type: array` with `items: {{ $ref: '#/components/schemas/ItemDTORequest' }}`.
"""

        # Construct Jersey-specific steps
        jersey_steps = f"""
For the JAX-RS endpoint method {endpoint_display_name}:
Context: The 'handler' section provides 'class_annotations', 'method_annotations', 'method_parameters_info' (which includes parameter names, Java types, and their annotations from the source code), and 'returnType'. The 'pojos' section details relevant DTOs/POJOs.

Here is a summary of the analyzed Java method parameters from its signature:
{method_params_guidance_from_soot}

Now, follow these steps to define the OpenAPI request parts:

1.  **Parameters (Path, Query, Header, Cookie, Form, Matrix):**
    a.  {path_params_guidance_from_url} Cross-reference these with any `@PathParam`-annotated parameters found in the 'Analyzed Java method parameters' list above. Path parameters are always `required: true`. Their OpenAPI `schema.type` and `schema.format` should be derived from the Java type of the annotated parameter (e.g., `java.lang.String` -> `type: string`, `java.lang.Long` -> `type: integer, format: int64`, `int` -> `type: integer, format: int32`).
    b.  For Query, Header, Cookie, Form, Matrix params: Refer to the 'Analyzed Java method parameters' list. Look for JAX-RS annotations (e.g., `@QueryParam("name")`, `@HeaderParam("id")`, `@FormParam("field")`) on the Java method parameters.
        - The Java type (from `param.type` in the list) determines OpenAPI `schema.type`/`format`.
        - `required` is `false` by default. It becomes `true` if the Java parameter is annotated with a JSR 303/380 validation annotation implying non-nullability (e.g., `@NotNull`, `@NotBlank`, `@NotEmpty` - check the `Annotations` list for each parameter) AND there's no `@DefaultValue` JAX-RS annotation.
    c.  Analyze the handler method's body for calls to other application methods (e.g., getPagination()). You must then trace these specific calls to find any indirect parameters they access. Critically, ignore any parameter-parsing logic from other helper methods in the same or parent classes if they are not part of the handler's direct execution path.
    d.  If a Java method parameter is annotated with `@BeanParam` (check the 'Analyzed Java method parameters' list): Its fields (whose details should be in a POJO found in `pojos` or `extra_context` sections) become individual OpenAPI parameters. Analyze that POJO's fields and their JAX-RS annotations to determine each OpenAPI parameter's `name`, `in` (query, header, etc.), `schema`, and `required` status.

2.  **RequestBody:**
    a.  Identify the request body POJO: From the 'Analyzed Java method parameters' list, this is typically a Java method parameter that is *not* annotated with any JAX-RS parameter annotation (like `@PathParam`, `@QueryParam`, etc.) or `@Context`.
    b.  If such a POJO body parameter is found:
        - Its Java type (e.g., `com.example.MyRequestDTO`) is given by `param.type` in the 'Analyzed Java method parameters' list. The detailed structure (fields, nested POJOs) of this POJO should be available in the `pojos` or `extra_context` sections of the provided context.
        - Media Types: Determine the consumable media types from `@Consumes` annotations on the handler method (in `handler.method_annotations`) or on the handler class (in `handler.class_annotations`). If none, default to `application/json`.
        - For each media type (e.g., `application/json`, `application/xml`):
            {request_body_schema_instructions}
    c.  If Java method parameters are annotated with `@FormParam` (check the 'Analyzed Java method parameters' list): The `requestBody`'s content type is typically `application/x-www-form-urlencoded` or `multipart/form-data`. The `schema` should be `type: object` with `properties` corresponding to each `@FormParam`-annotated Java parameter. The `name` of each property is the value of the `@FormParam("name")` annotation.
    d.  If no request body parameter or `@FormParam`s are identified, omit the `requestBody` section.

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
         
Remember to use the exact names and types from the provided context.
"""
        
        synthesis_instructions = ""
        # Check the handler_count flag.
        if endpoint.get("handler_count", 1) > 1:
            self.logger.info(f"Detected {endpoint.get('handler_count')} handlers. Augmenting prompt with synthesis instructions.")
            
            # This is the small, targeted block of instructions that will be PREPENDED.
            synthesis_instructions = """
# --- CRITICAL: Multi-Handler Synthesis Instructions ---
This endpoint is implemented by multiple Java methods. You MUST synthesize them into a single OpenAPI operation by following these primary rules, in addition to the detailed steps below:

-   **Rule A: Synthesize Parameters.** Create a single `parameters` section by combining all unique `@QueryParam`, `@HeaderParam`, etc., from ALL handler methods. Do not duplicate parameters.
-   **Rule B: Synthesize Request Body.** Create a single `requestBody` object. The `content` of this object must have multiple entries, one for each unique way of sending data (e.g., one for `multipart/form-data`, one for `application/json`, one for `text/csv`). Derive these from the `@Consumes` and `@FormDataParam` annotations across ALL handler methods.

Now, apply these synthesis rules while following the detailed steps below.
"""
        final_instructions = synthesis_instructions + jersey_steps.strip()
        
        return final_instructions

    def get_endpoint_request_framework_specific_notes(self) -> str:
        # Jersey might not have as many strict "NOTE:" style rules as DRF for this specific prompt.
        return "NOTE: For JAX-RS, pay close attention to annotations on method parameters to determine if they are path, query, header, form parameters, or the request body."
    
    def get_endpoint_common_instructions(self, skip_components: bool = False) -> str:
        if skip_components:
            ref_instruction = "6. DO NOT use `$ref` to `#/components/schemas/`. All schemas for request bodies or responses must be defined inline within the path item."
        else:
            ref_instruction = "6. DO NOT create the `components` section of the OpenAPI definition here; component schemas are handled separately. You can, however, use `$ref` to `#/components/schemas/YourPojoRequest` or `#/components/schemas/YourPojoResponse` if a POJO is involved."
        return f"""
4. While deciding the types of each field, map Java types to standard OpenAPI primitive types (string, integer, number, boolean, array, object) and use `format` where appropriate (e.g., `int32`, `int64`, `date-time`, `byte`). Adhere to OpenAPI 3.0 specifications.
5. DO NOT add the `x-codeSamples` section to the OpenAPI definition.
{ref_instruction}
7. In the end, return ONLY the requested OpenAPI definition sections (e.g., `parameters`, `requestBody` for requests; `summary`, `responses` for responses).
8. Use all your knowledge about the rules of OpenAPI specifications 3.0, JAX-RS (Jersey), and common Java API patterns.
9. Ensure your output STRICTLY conforms to OpenAPI specifications 3.0 and is 100% syntactically correct YAML.

NOTE: Analyze the Java code context carefully. The way the code is written (e.g., use of annotations, helper classes) can vary. Rigorously analyze the provided code.
"""

    def _get_jersey_multi_handler_instructions(self, endpoint: Dict[str, Any], endpoint_context: Dict[str, Any]) -> str:
        """
        Generates specialized instructions for synthesizing an OpenAPI operation from multiple JAX-RS methods.
        This is a Jersey-specific helper.
        """
        
        # We can reuse the same well-defined instructions from the previous proposal.
        return """
# --- Multi-Handler Synthesis Instructions ---
This endpoint is implemented by multiple Java methods, each handling different request content types. You must synthesize these into a single OpenAPI operation.

1.  **Synthesize Parameters:**
    a.  Examine the 'method_parameters_info' for ALL provided handler methods.
    b.  Create a unified list of parameters for the OpenAPI `parameters` section.
    c.  If a parameter with the same `in` (e.g., "query") and `name` (e.g., "dataSource") appears in multiple methods, define it only ONCE in the final output. Its type should be consistent.
    d.  Combine all unique `@QueryParam`, `@HeaderParam`, `@PathParam`, etc., from all methods into this single list.

2.  **Synthesize RequestBody:**
    a.  Create a single `requestBody` object.
    b.  Inside the `requestBody`, populate the `content` map by inspecting each handler method:
        -   **For methods with `@FormDataParam`:** Add a `multipart/form-data` entry to the `content` map. The `schema` for this entry should be of `type: object` and its `properties` must correspond to all parameters annotated with `@FormDataParam`. The `name` of each property is the value from the `@FormDataParam("name")` annotation.
        -   **For methods with `@Consumes`:** For each media type listed in a `@Consumes` annotation (e.g., `application/json`, `text/csv`, `application/x-jsonlines`), add a corresponding entry to the `content` map.
        -   **Schema for Consumed Types:** The schema for these media types should be based on the un-annotated Java parameter in that specific method (the POJO representing the request body). Use a `$ref` to the appropriate component schema (e.g., `#/components/schemas/BulkDataRecordRequest`).

Example of a synthesized `requestBody`:
```yaml
requestBody:
  content:
    multipart/form-data:
      schema:
        type: object
        properties:
          data: # from @FormDataParam("data")
            type: string
            format: binary
    application/json:
      schema:
        $ref: '#/components/schemas/SomeRequestPojoRequest'
    text/csv:
      schema:
        type: string
        """
    
    def get_endpoint_response_system_message(self) -> str:
        return "You are an expert in Java, JAX-RS (Jersey), relevant serialization libraries (Jackson, JAXB), and OpenAPI 3.0. Your task is to analyze a Java JAX-RS endpoint method to define its OpenAPI responses and summary."

    def _get_jersey_formatted_framework_settings_for_response(self, endpoint_context: Dict[str, Any]) -> str:
        """Helper for Jersey response-related framework settings (e.g., default @Produces)."""
        settings = endpoint_context.get("framework_settings", {}).get("settings", {})
        lines = []
        # Relevant for responses are primarily @Produces annotations
        method_produces = settings.get('method_produces')
        class_produces = settings.get('class_produces')

        if method_produces:
            lines.append(f"Method is annotated to @Produces: {method_produces}")
        elif class_produces:
            lines.append(f"Handler class is annotated to @Produces: {class_produces}")
        else:
            lines.append("No specific @Produces annotation found on method or class; assume default (e.g., application/json if POJOs are returned).")
        
        return "\n".join(lines)

    def get_endpoint_response_instructions(self, endpoint: Dict[str, Any], endpoint_context: Dict[str, Any],  skip_components: bool = False) -> str:
        url = endpoint.get("url", {}).get("url", "N/A")
        method_upper = endpoint.get("method", "N/A").upper()
        
        handler_details = endpoint_context.get("handler", {})
        handler_method_name = handler_details.get("name", "UnknownMethod")
        handler_class_fqn = handler_details.get("class_name_fqn", "UnknownClass")
        fn_name_for_prompt = f"{handler_class_fqn}.{handler_method_name}"
        
        return_type_java_fqn = handler_details.get("returnType", "void")
        framework_settings_for_response_str = self._get_jersey_formatted_framework_settings_for_response(endpoint_context)

        # Default status codes for JAX-RS
        jaxrs_common_error_codes_desc = {
            "400": "Bad Request - Invalid input or request format. This could be due to issues with path parameters, query parameters, headers, or the request body itself if it fails validation (e.g., against Bean Validation constraints).",
            "401": "Unauthorized - Authentication is required and has failed or has not yet been provided. The client should authenticate and try again.",
            "403": "Forbidden - The server understood the request, but is refusing to fulfill it. Authentication may have succeeded, but the authenticated user does not have the necessary permissions for the resource.",
            "404": "Not Found - The requested resource could not be found on the server. This often occurs if a URI is mistyped or a resource identified by a path parameter does not exist.",
            "405": "Method Not Allowed - The HTTP method used in the request (e.g., POST, GET, PUT) is not supported for the requested resource.",
            "406": "Not Acceptable - The server cannot produce a response matching the list of acceptable values defined in the request's `Accept` headers.",
            "415": "Unsupported Media Type - The server is refusing to service the request because the payload is in a format not supported by this method on the target resource (check `@Consumes` annotation).",
            "500": "Internal Server Error - An unexpected condition was encountered on the server which prevented it from fulfilling the request. This is a generic error message when no more specific message is suitable.",
            "503": "Service Unavailable - The server is currently unable to handle the request due to temporary overloading or maintenance of the server."
        }

        # Convert the dictionary to a string for embedding in the prompt
        jaxrs_error_codes_str = json.dumps(jaxrs_common_error_codes_desc)

        if skip_components:
            # NEW: Instructions for inline schema
            schema_instructions = """
            - For each media type, define its `schema` INLINE.
                - If the returned entity is a POJO, its full structure must be defined inline.
                - If the returned entity is a collection, the schema should be `type: array` with `items` also defined INLINE.
                - DO NOT use `$ref` to `#/components/schemas/`.
            """
        else:
            # ORIGINAL: Instructions using $ref
            schema_instructions = """
            - For each media type, define its `schema`:
                - If the returned entity is a POJO (e.g., `com.example.ProductDTO`), its structure should be in the `pojos` list or `extra_context`. Use a `$ref` to its 'Response' component schema (e.g., `#/components/schemas/ProductDTOResponse`).
                - If the returned entity is a collection (e.g., `java.util.List<com.example.UserDTO>`), the schema should be `type: array` with `items: {{ $ref: '#/components/schemas/UserDTOResponse' }}`.
                - If the returned entity is a Java primitive (e.g., `int`, `String`, `boolean`) or a standard library type not considered a POJO (e.g., `java.util.Map<String, String>`), define its schema directly (e.g., `type: string`, `type: integer`, or `type: object` for Maps).
            """

        jersey_response_steps = f"""
For the JAX-RS endpoint method '{fn_name_for_prompt}' handling {method_upper} {url}:
Declared Java return type from static analysis: `{return_type_java_fqn}`.
Framework context (e.g., default content types):
{framework_settings_for_response_str}

Context: 'handler' provides 'method_annotations', 'class_annotations', 'code', and 'returnType'. 'pojos' lists details for any DTOs directly used as return types or wrapped in `Response`.

1.  **Summary:** Provide a concise summary for the operation (e.g., "Retrieves a specific product", "Creates a new user").

2.  **Responses:**
    a.  **Success Status Code:**
        - For `GET` operations typically returning an entity: `200 OK`.
        - For `POST` operations that create a new resource: `201 Created` is common, especially if the new resource URI is returned. `200 OK` or `202 Accepted` might also be used.
        - For `PUT` or `PATCH` operations: `200 OK` (if the updated entity is returned) or `204 No Content` (if no entity is returned).
        - For `DELETE` operations: `204 No Content` is standard.
        - **Crucially**: If the `returnType` is `javax.ws.rs.core.Response` or `jakarta.ws.rs.core.Response`, you MUST analyze the `handler.code` to find explicit status settings (e.g., `Response.ok(...)`, `Response.status(Response.Status.CREATED).entity(...)`, `Response.noContent().build()`). Prioritize these explicit settings.
    b.  **Success Response Body (Content):**
        - Determine if the method returns an entity. This can be:
            - The direct `returnType` (if it's a POJO, `List<POJO>`, primitive, etc.).
            - The entity passed to `Response.ok(entity)` or `Response.status(...).entity(entity)` if `returnType` is `Response`.
        - If an entity is returned:
            - Media Types: Determine from `@Produces` annotations on the handler method (in `handler.method_annotations`) or on the handler class (in `handler.class_annotations`). If none, and a POJO is returned, `application/json` is a common default. List all applicable media types.
            {schema_instructions}
        - If the `returnType` is `void`, or if it's `Response` and the code indicates no entity is returned (e.g., `Response.noContent().build()`, `Response.status(204).build()`), then OMIT the `content` section for that success status code.
    c.  **Error Status Codes:**
        - Analyze `handler.code` for explicit `throw new WebApplicationException(...)` or `throw new CustomExceptionMappedByProvider(...)`. The status code might be in the exception constructor or an associated JAX-RS `ExceptionMapper`.

3.  Consider `NOT_REQUIRED`: If the analysis reveals this specific `{method_upper}` method is explicitly disallowed for this endpoint (e.g., based on annotations or if it only supports other HTTP methods), output ONLY ```<-|NOT_REQUIRED|->```.

4. **Rule for component Referencing:**
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
        return jersey_response_steps.strip()

    def get_endpoint_response_framework_specific_notes(self) -> str:
        return "NOTE: For JAX-RS, the actual returned entity and status code can be dynamically determined within the method body if it returns `javax.ws.rs.core.Response`. Analyze the method's code carefully for `Response.ok(entity).build()`, `Response.status(Status.CREATED).entity(dto).build()`, etc."



    def _build_discovery_maps(self):
        """
        Pre-processes soot-analysis.json to build lookup maps for implementations and serializers.
        This is a one-time operation for efficiency.
        """
        if self._implementations_map is not None and self._serializers_map is not None:
            self.logger.debug("Discovery maps already built.")
            return

        self.logger.info("Building discovery maps for implementations and serializers...")
        self._implementations_map = {}
        self._serializers_map = {}
        self._decoders_map = {}

        all_class_data = self.code_analyzer.analysis_results.get("classIdentifiers", [])
        if not all_class_data:
            self.logger.error("Cannot build discovery maps: 'classIdentifiers' not found.")
            return

        for class_info in all_class_data:
            class_fqn = class_info.get("className")
            if not class_fqn:
                continue

            # 1. Populate the implementations map
            # Soot may place interfaces in 'parentClasses' along with superclasses.
            parent_classes = class_info.get("parentClasses", [])
            for interface_fqn in parent_classes:
                if interface_fqn not in self._implementations_map:
                    self._implementations_map[interface_fqn] = []
                self._implementations_map[interface_fqn].append(class_fqn)

            # 2. Populate the serializers (MessageBodyWriter) map
            is_provider = any(ann.get("type") == "Ljavax/ws/rs/ext/Provider;" for ann in class_info.get("annotations", []))
            is_writer = "javax.ws.rs.ext.MessageBodyWriter" in parent_classes

            if is_provider and is_writer:
                signature = class_info.get("classSignature")
                if signature:
                    # Regex to find the generic type, e.g., <Lcom/example/MyType;>
                    match = re.search(r'<L([^;<>]+);>', signature)
                    if match:
                        type_descriptor = match.group(1)
                        # Convert 'com/example/MyType' to 'com.example.MyType'
                        handled_type_fqn = type_descriptor.replace('/', '.')
                        if handled_type_fqn not in self._serializers_map:
                            self._serializers_map[handled_type_fqn] = [] # Initialize list
                        
                        self._serializers_map[handled_type_fqn].append(class_fqn)
                        self.logger.debug(f"Mapped serializer '{class_fqn}' to type '{handled_type_fqn}'.")

            is_reader = "javax.ws.rs.ext.MessageBodyReader" in parent_classes
            if is_provider and is_reader:
                signature = class_info.get("classSignature")
                if signature:
                    # Same regex logic applies for decoders
                    match = re.search(r'<L([^;<>]+);>', signature)
                    if match:
                        handled_type_fqn = match.group(1).replace('/', '.')
                        if handled_type_fqn not in self._decoders_map:
                            self._decoders_map[handled_type_fqn] = []
                        
                        self._decoders_map[handled_type_fqn].append(class_fqn)
                        self.logger.info(f"Mapped DECODER '{class_fqn}' to type '{handled_type_fqn}'.")

        self.logger.info(f"Built implementation map with {len(self._implementations_map)} entries.")
        self.logger.info(f"Built serializer map with {len(self._serializers_map)} entries.")


    def _find_concrete_implementation(self, interface_fqn: str) -> Optional[Dict[str, Any]]:
        """
        Finds the best concrete implementation for a given interface FQN.
        It prefers implementations annotated with a persistence annotation like @Entity.
        """
        self._build_discovery_maps() # Ensure maps are built
        
        implementations = self._implementations_map.get(interface_fqn, [])
        if not implementations:
            self.logger.debug(f"No implementations found for interface '{interface_fqn}'.")
            return None

        # Strategy: Find the implementation that is a Morphia/JPA @Entity
        best_candidate = None
        for impl_fqn in implementations:
            impl_info = self.code_analyzer.get_symbol_info(impl_fqn, self.project_path, SymbolType.CLASS)
            if impl_info:
                for ann in impl_info.get("annotations", []):
                    # Check for Morphia or JPA @Entity annotations
                    if ann.get("type") in ("Ldev/morphia/annotations/Entity;", "Ljavax/persistence/Entity;"):
                        self.logger.info(f"Found persistence-annotated implementation for '{interface_fqn}': '{impl_fqn}'")
                        return impl_info # Found the best one, return immediately
                if not best_candidate:
                    best_candidate = impl_info # Keep the first one as a fallback

        if best_candidate:
            self.logger.info(f"Found fallback implementation for '{interface_fqn}': '{best_candidate.get('className')}'")
        
        return best_candidate

    
    def _find_serializer_for_type(self, type_fqns_to_check: List[str]) -> Optional[Dict[str, Any]]:
        """
        Finds the best JAX-RS MessageBodyWriter for a given list of type FQNs (typically
        a class and its hierarchy). It prioritizes serializers that explicitly
        produce a JSON media type by inspecting the @Produces annotation.
        
        CORRECTED: This version correctly iterates over the input list of FQNs.
        """
        self._build_discovery_maps()

        # Ensure we are always working with a list, even if a single string was passed by mistake.
        if isinstance(type_fqns_to_check, str):
            self.logger.warning(f"[_find_serializer_for_type] Received a string '{type_fqns_to_check}', expected a list. Coercing to list.")
            type_fqns_to_check = [type_fqns_to_check]

        if not isinstance(type_fqns_to_check, list):
            self.logger.error(f"[_find_serializer_for_type] Invalid argument type: {type(type_fqns_to_check)}. Expected a list of strings.")
            return None

        # This is the main loop that correctly iterates over the provided FQNs.
        for type_fqn in type_fqns_to_check:
            if not isinstance(type_fqn, str):
                self.logger.warning(f"Skipping invalid item in FQN list: {type_fqn}")
                continue

            # Look up all candidate serializers registered for this specific string FQN.
            # The key 'type_fqn' is now guaranteed to be a string.
            candidate_serializer_fqns = self._serializers_map.get(type_fqn, [])
            if not candidate_serializer_fqns:
                continue # No serializers registered for this type, check the next one in the hierarchy.

            self.logger.debug(f"Found {len(candidate_serializer_fqns)} candidate serializers for type '{type_fqn}': {candidate_serializer_fqns}")

            # Now, inspect each candidate to see if it produces JSON.
            for serializer_fqn in candidate_serializer_fqns:
                serializer_info = self.code_analyzer.get_symbol_info(serializer_fqn, self.project_path, SymbolType.CLASS)
                if not serializer_info:
                    continue
                
                # Check the serializer's own annotations AND its parents' annotations.
                serializer_hierarchy_fqns = [serializer_fqn] + serializer_info.get("parentClasses", [])
                
                for fqn_in_hierarchy in serializer_hierarchy_fqns:
                    info_for_ann_check = self.code_analyzer.get_symbol_info(fqn_in_hierarchy, self.project_path, SymbolType.CLASS)
                    if not info_for_ann_check:
                        continue

                    produces_types = self._extract_media_types(info_for_ann_check.get("annotations", []), "Produces")
                    
                    if any("json" in media_type.lower() for media_type in produces_types):
                        self.logger.info(f"SUCCESS: Found JSON serializer for hierarchy of '{type_fqns_to_check[0]}': '{serializer_fqn}' (via @Produces on '{fqn_in_hierarchy}')")
                        return serializer_info # We found the best one, return immediately.

        self.logger.debug(f"No specific JSON serializer found for the hierarchy: {type_fqns_to_check}")
        return None
    
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

        # STAGE 2: Find the serializer
        serializer_info = self._find_serializer_for_type(primary_fqn)

        if serializer_info:
            key_artifacts.append(serializer_info)
            #processed_fqns.add(serializer_info['className'])
        # STAGE 4: Holistic Recursive Gathering
        # We now have our high-value starting points. We will gather all their dependencies.
        final_dependency_contexts = []
        self.logger.info(f"Found {len(key_artifacts)} key artifacts. Starting recursive dependency gathering...")
        for artifact_info in key_artifacts:
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
                artifact_path = artifact.get("classFileName") or artifact.get("filePath") # Renamed for clarity
                code = self.code_analyzer.get_code_snippet(
                    artifact_path, artifact.get("startLine"), artifact.get("endLine")
                )
                if code:
                    path = artifact.get("classFileName") or artifact.get("filePath")
                    final_data_classes.append({
                        "name": artifact.get("className").split('.')[-1],
                        "qualifiedName": artifact.get("className"),
                        "path": path,
                        "code": f"// --- Dependency: {artifact.get('className')} ---\n{code}"
                    })
                    processed_for_data_classes.add(artifact_fqn)

        for artifact in final_dependency_contexts:
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

    def _build_rich_context_for_component(self, concrete_fqn: str) -> Optional[Dict[str, Any]]:
        """
        Builds the complete, "clubbed" context for a single concrete component.
        This is the hybrid approach that combines Jersey's artifact hunting with
        Spring's intelligent context clubbing.
        """
        # --- STEP 1: GATHER ALL KEY ARTIFACTS ---
        # 1a. The primary concrete class itself.
        concrete_class_info = self.code_analyzer.get_symbol_info(concrete_fqn, self.project_path, SymbolType.CLASS)
        if not concrete_class_info:
            self.logger.warning(f"Could not get symbol info for concrete class '{concrete_fqn}'. Skipping.")
            return None

        # 1b. The entire inheritance hierarchy (parents AND interfaces).
        parent_hierarchy_list = self.code_analyzer.get_type_hierarchy(concrete_fqn, self.project_path)

        # 1c. The JAX-RS Serializer (MessageBodyWriter), if one exists for this class OR any of its parents/interfaces.
        # This checks the entire hierarchy for a registered serializer.
        fqns_to_check_for_serializer = [concrete_fqn] + [h.get('name') for h in parent_hierarchy_list]
        serializer_info = self._find_serializer_for_type(fqns_to_check_for_serializer) # Modified to accept a list

        key_artifacts = [concrete_class_info] + parent_hierarchy_list
        if serializer_info:
            key_artifacts.append(serializer_info)

        # --- STEP 2: GATHER ALL TRANSITIVE DEPENDENCIES ---
        # Find every other class referenced by ANY of the key artifacts.
        all_other_dependencies = []
        # The visited set must contain all key artifacts to avoid re-processing them.
        visited_fqns = {info.get('className') for info in key_artifacts if info and info.get('className')}

        for artifact_info in key_artifacts:
            if not artifact_info: continue
            artifact_fqn = artifact_info.get("className")
            # We use the robust relaxed gatherer, which looks at fields, methods, etc.
            deps = self._gather_dependencies_recursively_relaxed(
                start_fqn=artifact_fqn,
                visited_fqns=visited_fqns
            )
            all_other_dependencies.extend(deps)
        
        # --- STEP 3: ASSEMBLE THE FINAL CONTEXT (INTELLIGENT CLUBBING) ---
        # 3a. Club the primary class and its entire inheritance hierarchy together.
        concrete_class_code = self.code_analyzer.get_code_snippet_from_info(concrete_class_info) or f"// Code for {concrete_fqn} not found"
        clubbed_code_parts = [f"// --- Primary Concrete Class: {concrete_fqn} ---\n{concrete_class_code}"]
        
        for parent_info in parent_hierarchy_list:
            parent_fqn = parent_info.get("name")
            parent_code = parent_info.get("code", f"// Code for {parent_fqn} not found")
            type_label = "Interface" if parent_info.get("isInterface") else "Parent Class"
            clubbed_code_parts.append(f"\n\n// --- {type_label}: {parent_fqn} ---\n{parent_code}")

        # 3b. If a special serializer was found, it's CRITICAL context. Club it too.
        if serializer_info:
            serializer_code = self.code_analyzer.get_code_snippet_from_info(serializer_info) or f"// Code for {serializer_info.get('className')} not found"
            clubbed_code_parts.append(f"\n\n// --- Custom JAX-RS Serializer (MessageBodyWriter) ---\n{serializer_code}")
        
        # 3c. Assemble the final dictionary.
        # We need a robust way to remove duplicates from all_other_dependencies
        unique_deps_map = {dep['qualifiedName']: dep for dep in all_other_dependencies}

        return {
            "name": concrete_class_info.get("className").split('.')[-1],
            "qualifiedName": concrete_fqn,
            "path": concrete_class_info.get("classFileName") or concrete_class_info.get("filePath"),
            "code": "".join(clubbed_code_parts),
            "data_classes": list(unique_deps_map.values()),
            "fields_info": self._get_all_properties_for_class(concrete_fqn),
            "annotations": concrete_class_info.get("annotations", []),
            "parent_classes": parent_hierarchy_list,
            "is_interface": concrete_class_info.get("isInterface", False),
        }
    

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
            #self.logger.info(f"[SORT_STEP] Processing node: '{u}'")
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
            #self.logger.warning(f"Remaining nodes with in-degree > 0: {sorted(list(cycled_nodes))}")
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
        nodes_to_process_queue = deque(components_map.keys())
        processed_for_context = set(components_map.keys())

        while nodes_to_process_queue:
            fqn = nodes_to_process_queue.popleft()
            
            # If we don't have context for this node yet, build it.
            if fqn not in components_map:
                rich_context = self._build_rich_context_for_component(fqn)
                if rich_context:
                    components_map[fqn] = rich_context
                else:
                    # If we can't build context, we can't analyze it.
                    continue

            # Now that we have context, find its dependencies and add them to the queue.
            context = components_map[fqn]
            dependencies_to_queue = set()

            for parent in context.get('parent_classes', []):
                dependencies_to_queue.add(parent.get('name'))
            
            for field in self._get_all_properties_for_class(fqn):
                dependencies_to_queue.add(self._get_base_type(field.get("type")))

            for dep_fqn in dependencies_to_queue:
                if dep_fqn and dep_fqn not in processed_for_context:
                    nodes_to_process_queue.append(dep_fqn)
                    processed_for_context.add(dep_fqn)
        
        all_nodes = set(components_map.keys())

        transient_nodes_context: Dict[str, Dict[str, Any]] = {}
        
        nodes_to_discover = list(components_map.items())
        
        # This loop is just to ensure all nested dependencies are added to all_nodes
        i = 0
        while i < len(nodes_to_discover):
            fqn, rich_context = nodes_to_discover[i]
            i += 1
            for parent in rich_context.get('parent_classes', []):
                parent_fqn = parent.get('name')
                if parent_fqn and parent_fqn not in all_nodes:
                    print(f"[DEBUG-LOG] Discovered new parent node '{parent_fqn}' from child '{fqn}'. Adding to `all_nodes`.")
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
            #self.logger.info(f"\n========== Analyzing Node: '{fqn}' ==========")
            if fqn not in components_map:
                #self.logger.info(f"  [TRANSIENT NODE] Rich context for '{fqn}' not found. Building it now.")
                # Build the rich context for this newly discovered node on the fly.
                # This call populates the context with path, code, fields, parents, etc.
                rich_context = self._build_rich_context_for_component(fqn)
                if rich_context:
                    components_map[fqn] = rich_context
                    #self.logger.info(f"  - Successfully built and cached rich context for '{fqn}'.")
                else:
                    pass
                    #self.logger.warning(f"  - Failed to build rich context for transient node '{fqn}'. It may be skipped.")

            context_for_path = components_map.get(fqn) or transient_nodes_context.get(fqn)
            if not context_for_path or not context_for_path.get('path'):
                #self.logger.warning(f"  [SKIPPING] Could not find file path for node '{fqn}'.")
                continue
                
            symbol_info = self.code_analyzer.get_symbol_info(fqn, context_for_path.get('path'), SymbolType.CLASS)
            if not symbol_info:
                #self.logger.warning(f"  [SKIPPING] Could not get symbol_info for node '{fqn}'.")
                continue
                
            # --- A) Handle INHERITANCE/IMPLEMENTATION dependencies ---
            parent_classes = symbol_info.get('parentClasses', [])
            self.logger.debug(f"  [INHERITANCE] Found parents/interfaces: {parent_classes}")
            for parent_fqn in parent_classes:
                #self.logger.debug(f"    - Checking parent '{parent_fqn}'...")
                if parent_fqn in all_nodes:
                    # Get info about the parent to see if it's an interface or a class
                    parent_context = components_map.get(parent_fqn) or transient_nodes_context.get(parent_fqn)
                    if not parent_context or not parent_context.get('path'):
                        #self.logger.debug(f"    -> SKIPPING parent '{parent_fqn}': No source path found (likely a JDK or library class).")
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
                            #self.logger.debug(f"    -> CREATED INTERFACE EDGE: {fqn} -> {parent_fqn}")
                    else:
                        # Case 2: The parent is a CLASS (inheritance).
                        # The child's schema depends on the parent's.
                        # Edge: Parent -> Child
                        if fqn not in adj.get(parent_fqn, set()):
                            adj[parent_fqn].add(fqn)
                            in_degree[fqn] += 1
                            #self.logger.debug(f"    -> CREATED INHERITANCE EDGE: {parent_fqn} -> {fqn}")

            # --- B) Handle FIELD dependencies ---
            all_properties = self._get_all_properties_for_class(fqn)
            #self.logger.debug(f"  [FIELDS] Found {len(all_properties)} properties/fields to check.")
            for field in all_properties:
                
                field_name = field.get("name")
                field_type = field.get("type")
                #self.logger.debug(f"    - Checking field '{field_name}' with type '{field_type}'...")
                
                dep_fqn = self._get_base_type(field.get('type'))
                #self.logger.debug(f"      Base type is '{dep_fqn}'.")

                if dep_fqn and dep_fqn in all_nodes and dep_fqn != fqn:
                    if fqn not in adj.get(dep_fqn, set()):
                        adj[dep_fqn].add(fqn)
                        in_degree[fqn] += 1
                        #self.logger.info(f"    - SUCCESS: Created FIELD edge: {dep_fqn} -> {fqn}. New in_degree for '{fqn}' is {in_degree[fqn]}")
                    else:
                        pass
                        #self.logger.debug(f"    - INFO: Edge {dep_fqn} -> {fqn} already exists.")
                elif not dep_fqn:
                    pass
                    #self.logger.debug(f"      FAIL: Base type could not be determined.")
                elif dep_fqn == fqn:
                    pass
                    #self.logger.debug(f"      INFO: Field is a self-reference. No edge created.")
                else: # dep_fqn not in all_nodes
                    pass
                    #self.logger.warning(f"    - FAIL: Field type '{dep_fqn}' is NOT in the set of all_nodes. No edge created.")

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


    def _get_fqn_from_implementation_value(self, implementation_value: str) -> Optional[str]:
        """Cleans the 'implementation' value from a @Schema annotation."""
        if not isinstance(implementation_value, str):
            return None
        # The value is often "com.example.MyClass.class"
        if implementation_value.endswith(".class"):
            return implementation_value[:-len(".class")]
        # It might also be a Soot descriptor 'Lcom/example/MyClass;'
        return self._soot_descriptor_to_fqn(implementation_value)

    def _find_element_value(self, elements: List[Dict], element_name: str) -> Optional[Any]:
        """
        Safely finds the value of a named element within an annotation's 'elements' list.
        """
        if not isinstance(elements, list):
            return None
        for element in elements:
            if isinstance(element, dict) and element.get("name") == element_name:
                return element.get("value")
        return None

    def _extract_dtos_from_annotations(self, annotations: List[Dict[str, Any]]) -> Set[str]:
        """
        (Corrected Version)
        Parses @ApiResponse and @ApiResponses annotations to find DTOs defined in the
        `implementation` property of a @Schema annotation.
        """
        self.logger.debug("--- Running REFACTORED _extract_dtos_from_annotations ---")
        discovered_fqns = set()
        api_response_fqn = "io.swagger.v3.oas.annotations.responses.ApiResponse"
        api_responses_fqn = "io.swagger.v3.oas.annotations.responses.ApiResponses"

        # Step 1: Collect all @ApiResponse annotation objects, correctly handling the @ApiResponses container.
        api_response_objects = []
        for ann in annotations:
            ann_fqn = self._soot_descriptor_to_fqn(ann.get("type"))

            if ann_fqn == api_response_fqn:
                api_response_objects.append(ann)
            elif ann_fqn == api_responses_fqn:
                # The value of @ApiResponses is an array of @ApiResponse annotations
                nested_responses = self._find_element_value(ann.get("elements", []), "value")
                if isinstance(nested_responses, list):
                    api_response_objects.extend(nested_responses)

        self.logger.debug(f"Processing a total of {len(api_response_objects)} collected @ApiResponse objects.")

        # Step 2: Process each collected @ApiResponse object to find the schema implementation.
        for response_ann in api_response_objects:
            if not isinstance(response_ann, dict): continue

            content_list = self._find_element_value(response_ann.get("elements", []), "content")
            if not isinstance(content_list, list): continue

            for content_item in content_list:  # This is the @Content annotation
                if not isinstance(content_item, dict): continue

                schema_item = self._find_element_value(content_item.get("elements", []), "schema")
                if not isinstance(schema_item, dict): continue
                
                # We've reached the @Schema annotation, now find its 'implementation'
                implementation_value = self._find_element_value(schema_item.get("elements", []), "implementation")
                
                if implementation_value:
                    # The value is a class descriptor, e.g., "Lcom/datastax/mgmtapi/resources/models/Job;"
                    fqn = self._get_fqn_from_implementation_value(implementation_value)
                    if fqn:
                        self.logger.info(f"SUCCESS: Discovered DTO '{fqn}' from @ApiResponse.")
                        discovered_fqns.add(fqn)
        
        self.logger.debug(f"--- Finished REFACTORED _extract_dtos_from_annotations ---")
        return discovered_fqns
    

    def get_schema_components(self) -> Dict[str, Dict[str, Any]]:
        """
        Extracts schema components (POJOs/DTOs) using the "Club and Reuse" strategy.
        This involves identifying primary artifacts, pruning the list to avoid processing
        base classes individually, and then building a rich, "clubbed" context for
        each primary artifact.
        
        REFACTORED: This now uses a "top-down" seeding approach inspired by the Spring analyzer
        for improved efficiency and relevance.
        """
        if self._cached_components is not None:
            self.logger.debug("Returning cached schema components.")
            return self._cached_components

        # =================================================================================
        # PHASE 1: DISCOVERY (Spring's "Top-Down" & "Always Resolve Interfaces" logic)
        # =================================================================================
        self.logger.info("Phase 1: Discovering seed components from actual endpoint usage...")
        seed_fqns = self._discover_seed_components_jersey()
        primary_artifacts_to_process = self._collect_all_transitive_dependencies_with_impls(seed_fqns)
        #self.logger.info(f"Have {len(primary_artifacts_to_process)} components before filtering.")
        filtered_artifacts = {
            fqn for fqn in primary_artifacts_to_process 
            if fqn not in NOISE_COMPONENT_BLACKLIST
        }
        #self.logger.info(f"Have {len(filtered_artifacts)} components after filtering.")
        primary_artifacts_to_process = filtered_artifacts
        # --- VERIFICATION STEP ---
        # As requested, we will stop here to verify the seed components.
        # You can inspect the 'seed_fqns' variable in the debugger.
        self.logger.info("Phase 2: Building rich context for each concrete component...")

        # Pre-compute Jersey-specific provider maps for lazy lookups.
        self._build_discovery_maps() 

        final_components_map: Dict[str, Dict[str, Any]] = {}
        for fqn in sorted(list(primary_artifacts_to_process)):
            rich_context = self._build_rich_context_for_component(fqn)
            if rich_context:
                final_components_map[fqn] = rich_context
        self.logger.info(f"Phase 2 complete. Built rich context for {len(final_components_map)} components.")

        # To continue execution in pdb, type 'c' and press Enter.

        self.logger.info("Phase 3: Building dependency graph from rich context...")

        adj_graph, in_degree_map = self._build_dependency_graph_from_rich_context(final_components_map)
        self.logger.info("Phase 3 complete.")

        # =================================================================================
        # PHASE 4: SORTING & FINAL ASSEMBLY
        # =================================================================================
        self.logger.info("Phase 4: Topologically sorting components...")
        sorted_fqns = self._topological_sort(adj_graph, in_degree_map)
        self.logger.info(f"Phase 4 complete. Final component order established for {len(sorted_fqns)} components.")
        self.logger.info(f"Phase 4 complete. Final component order {sorted_fqns} components.")

        # Reorder the final map according to the sort.  
        self._cached_components = {fqn: final_components_map[fqn] for fqn in sorted_fqns if fqn in final_components_map}
        
        return self._cached_components

    def _find_and_filter_implementations(self, interface_fqn: str) -> List[str]:
        """
        Finds all implementations of an interface and filters them to keep only
        those that are likely DTOs/POJOs, as defined by `_is_potential_dto`.
        (Ported from Spring Analyzer for its robust logic).
        """
        self._build_discovery_maps() # Ensure the implementation map is ready

        all_implementations = self._implementations_map.get(interface_fqn, [])
        if not all_implementations:
            self.logger.debug(f"No implementations found in map for interface '{interface_fqn}'.")
            return []
        
        self.logger.debug(f"Found {len(all_implementations)} raw implementations for '{interface_fqn}': {all_implementations}")
        
        filtered_dtos = []
        for impl_fqn in all_implementations:
            if self._is_potential_dto(impl_fqn):
                filtered_dtos.append(impl_fqn)
            else:
                self.logger.debug(f"Filtered out non-DTO implementation '{impl_fqn}' for interface '{interface_fqn}'.")
        
        return filtered_dtos

    # --- REPLACE THE OLD VERSION OF THIS METHOD WITH THIS NEW ONE ---
    def _collect_all_transitive_dependencies_with_impls(self, seed_fqns: Set[str]) -> Set[str]:
        """
        PHASE 1.2: Finds the complete universe of relevant component FQNs by starting with
        a seed set and transitively exploring all dependencies.
        
        This logic is ported from the Spring analyzer for its superior handling of interfaces.
        It treats interfaces as "signposts" to discover concrete DTO implementations.
        """
        final_component_fqns = set()
        
        # Use a queue for a breadth-first search of the dependency tree.
        queue = deque(list(seed_fqns))
        # Keep track of what we've already added to the queue to avoid redundant processing.
        visited_for_queueing = set(seed_fqns)

        while queue:
            fqn = queue.popleft()

            # First, check if this FQN is even a candidate worth analyzing.
            if not self._is_potential_dto(fqn):
                continue
            
            class_info = self.code_analyzer.get_symbol_info(fqn, self.project_path, SymbolType.CLASS)
            if not class_info:
                self.logger.warning(f"Could not get class info for '{fqn}' during transitive discovery.")
                continue

            # --- "Always Resolve Interfaces" Logic ---
            # If we find an interface, we do not add it to our final set.
            # Instead, we find its concrete children and add THEM to the queue for processing.
            if class_info.get("isInterface") or class_info.get("isAbstract"):
                kind = "INTERFACE" if class_info.get("isInterface") else "ABSTRACT CLASS"
                self.logger.debug(f"'{fqn}' is an {kind}. Resolving and queueing its concrete DTO implementations.")
                implementations = self._find_and_filter_implementations(fqn)
                for impl_fqn in implementations:
                    if impl_fqn not in visited_for_queueing:
                        visited_for_queueing.add(impl_fqn)
                        queue.append(impl_fqn)
                # The interface's job is done. We move to the next item in the queue.
                continue
            
            # --- Logic for Concrete Classes ---
            # If we've reached this point, `fqn` is a concrete class we care about.
            final_component_fqns.add(fqn)
            
            dependencies_to_scan = set()

            # 1. Gather dependencies from parent classes and interfaces.
            for parent_fqn in class_info.get("parentClasses", []):
                dependencies_to_scan.add(parent_fqn)
            
            # 2. Gather dependencies from fields.
            for prop in self._get_all_properties_for_class(fqn):
                base_type = self._get_base_type(prop.get("type"))
                if base_type:
                    dependencies_to_scan.add(base_type)
            
            # 3. Queue all newly discovered dependencies for processing.
            for dep_fqn in dependencies_to_scan:
                if dep_fqn not in visited_for_queueing:
                    visited_for_queueing.add(dep_fqn)
                    queue.append(dep_fqn)
                    
        self.logger.info(f"Expanded {len(seed_fqns)} seed components to a total of {len(final_component_fqns)} concrete components.")
        print(f"Expanded {len(seed_fqns)} seed components to a total of {len(final_component_fqns)} concrete components.")
        return final_component_fqns
    
    def _deduce_async_response_type(self, method_info: Dict[str, Any]) -> Set[str]:
        """
        FINAL VERSION: Traces async flows by identifying the lambda responsible for the final
        transformation. It then finds the last declared variable within that lambda that
        passes a series of strict, general-purpose filters to qualify as a true
        response DTO, effectively removing implementation noise.
        """
        method_name_for_log = method_info.get('methodName')
        self.logger.debug(f"--- Starting Async Deduction for '{method_name_for_log}' ---")

        candidate_lambda_fqns = {
            call.get("declaringClass")
            for call in method_info.get("functionNames", [])
            if call.get("declaringClass") and "$lambda" in call.get("declaringClass")
        }

        if not candidate_lambda_fqns:
            self.logger.debug(f"[{method_name_for_log}] No lambda classes found. Aborting.")
            return set()
        
        self.logger.debug(f"[{method_name_for_log}] Phase 1: Found {len(candidate_lambda_fqns)} candidate lambda(s): {candidate_lambda_fqns}")

        discovered_fqns = set()
        for lambda_fqn in candidate_lambda_fqns:
            self.logger.debug(f"[{method_name_for_log}] Phase 2: Analyzing lambda '{lambda_fqn}'...")
            lambda_class_info = self.code_analyzer.get_symbol_info(lambda_fqn, self.project_path, SymbolType.CLASS)
            if not lambda_class_info: continue

            functional_method = next((
                func for func in lambda_class_info.get("functions", [])
                if func.get("methodName") not in ["<init>", "<clinit>", "bootstrap$"]
            ), None)

            if not functional_method: continue
            
            func_name_for_log = functional_method.get('methodName')
            self.logger.debug(f"[{method_name_for_log}] Analyzing functional method '{func_name_for_log}' in lambda '{lambda_fqn}'.")

            last_dto_candidate = None
            
            input_param_types = set()
            if functional_method.get("parameters"):
                for param in functional_method.get("parameters"):
                    base_input_type = self._get_base_type(param.get("type"))
                    if base_input_type:
                        input_param_types.add(base_input_type)
            self.logger.debug(f"[{method_name_for_log}] Identified lambda input type(s) for exclusion: {input_param_types}")

            for var_info in functional_method.get("variableNames", []):
                var_type_fqn = var_info.get("type")
                base_type = self._get_base_type(var_type_fqn)

                if not base_type:
                    continue

                # --- Start of Localized, Aggressive Filtering ---
                
                # Filter 1: Noise Category - Lambda Implementations
                if "$lambda" in base_type:
                    self.logger.debug(f"[{method_name_for_log}] FILTERED: '{base_type}' is a lambda implementation class.")
                    continue

                # Filter 2: General DTO check (our baseline). This must pass.
                if not self._is_potential_dto(base_type):
                    continue
                
                # Filter 4: Noise Category - The lambda's input parameter.
                if base_type in input_param_types:
                    self.logger.debug(f"[{method_name_for_log}] FILTERED: '{base_type}' is an input parameter to the lambda.")
                    continue

                # Filter 5: Noise Category - JAX-RS Resource classes.
                candidate_info = self.code_analyzer.get_symbol_info(base_type, self.project_path, SymbolType.CLASS)
                if candidate_info:
                    is_resource = any(
                        ".ws.rs.Path" in (self._soot_descriptor_to_fqn(ann.get("type")) or "")
                        for ann in candidate_info.get("annotations", [])
                    )
                    if is_resource:
                        self.logger.debug(f"[{method_name_for_log}] FILTERED: '{base_type}' is a JAX-RS Resource (has @Path).")
                        continue
                
                # If a type survives all filters, it becomes our new best candidate.
                self.logger.debug(f"[{method_name_for_log}] Found valid DTO candidate: '{base_type}' (from var '{var_info.get('name')}').")
                last_dto_candidate = base_type
            
            if last_dto_candidate:
                self.logger.info(f"SUCCESS: Deduced response DTO '{last_dto_candidate}' for '{method_name_for_log}' from lambda '{lambda_fqn}'.")
                discovered_fqns.add(last_dto_candidate)
            else:
                 self.logger.debug(f"[{method_name_for_log}] No variables inside lambda '{lambda_fqn}' passed the refined filter.")

        if not discovered_fqns:
            self.logger.warning(f"--- FAILED Async Deduction for '{method_name_for_log}'. No valid DTOs identified after analyzing all lambdas. ---")
        
        return discovered_fqns
    
    def _discover_seed_components_jersey(self) -> Set[str]:
        """
        PHASE 1A: Iterates through all *actual* endpoints and inspects their full
        method signatures to find the initial "seed" set of component FQNs.
        This is a "top-down" approach.
        """
        self.logger.info("--- Starting Seed Component Discovery (Jersey) ---")
        seed_component_fqns: Set[str] = set()
        
        # Ensure endpoints are loaded
        if self.endpoints is None:
            self.get_endpoints()

        if not self.endpoints:
            self.logger.warning("No endpoints found, cannot discover seed components.")
            return set()

        for endpoint in self.endpoints:
            metadata = endpoint.get("metadata", {})
            handler_class_fqn = metadata.get("handler_class_fqn")
            if not handler_class_fqn: continue

            class_info = self.code_analyzer.get_symbol_info(handler_class_fqn, self.project_path, SymbolType.CLASS)
            if not class_info: continue

            for method_details in metadata.get("implementing_methods", []):
                method_signature = method_details.get("signature")
                method_info = next((m for m in class_info.get("functions", []) if m.get("signature") == method_signature), None)
                if not method_info: continue

                # 1. Inspect return type for response DTOs
                return_type = method_info.get("returnType")
                base_return_type = self._get_base_type(return_type)
                is_async = False
                async_response_type = "javax.ws.rs.container.AsyncResponse"
                suspended_annotation_fqn = "javax.ws.rs.container.Suspended"

                for param in method_info.get("parameters", []):
                    if param.get("type") == async_response_type:
                        for ann in param.get("annotations", []):
                            ann_fqn = self._soot_descriptor_to_fqn(ann.get("type"))
                            if ann_fqn == suspended_annotation_fqn:
                                is_async = True
                                break
                    if is_async:
                        break
                
                if is_async and return_type == "void":
                    self.logger.info(f"Detected asynchronous pattern in method: {method_info.get('signature')}. Deducing response type...")
                    async_response_fqns = self._deduce_async_response_type(method_info)
                    for fqn in async_response_fqns:
                        if self._is_potential_dto(fqn):
                            self.logger.debug(f"Found seed component from async response: {fqn}")
                            seed_component_fqns.add(fqn)

                if return_type and ("javax.ws.rs.core.Response" in return_type or "jakarta.ws.rs.core.Response" in return_type):
                    self.logger.debug(f"Method '{method_info.get('methodName')}' returns 'Response'. Analyzing method body for entity types.")
                    
                    # Create a quick lookup map of variable names to their types within this method
                    variable_type_map = {var.get("name"): var.get("type") for var in method_info.get("variableNames", [])}

                    for called_func in method_info.get("functionNames", []):
                        func_name = called_func.get("simpleName")
                        
                        # Check for Response.ok(entity) or Response.created(uri).entity(entity)
                        if func_name == "ok" or func_name == "entity":
                            arguments = called_func.get("arguments", [])
                            if arguments:
                                # The argument is the variable name (e.g., "apiEntity")
                                entity_variable_name = arguments[0]
                                # Look up the variable's type in our map
                                entity_type_fqn = variable_type_map.get(entity_variable_name)
                                
                                if entity_type_fqn:
                                    base_entity_type = self._get_base_type(entity_type_fqn)
                                    if self._is_potential_dto(base_entity_type):
                                        self.logger.info(f"Found seed component from '.{func_name}({entity_variable_name})' call: {base_entity_type}")
                                        seed_component_fqns.add(base_entity_type)

                elif self._is_potential_dto(base_return_type):
                    self.logger.debug(f"Found seed component from return type: {base_return_type}")
                    seed_component_fqns.add(base_return_type)

                method_annotations = method_info.get("annotations", [])
                dtos_from_annotations = self._extract_dtos_from_annotations(method_annotations)
                for fqn in dtos_from_annotations:
                    if self._is_potential_dto(fqn):
                        self.logger.debug(f"Found seed component from @ApiResponse annotation: {fqn}")
                        seed_component_fqns.add(fqn)
                    
                # 2. Inspect parameters for request body DTOs
                request_body_param = self._find_request_body_parameter(method_info.get("parameters", []))
                if request_body_param:
                    base_req_type = self._get_base_type(request_body_param.get("type"))
                    if self._is_potential_dto(base_req_type):
                        self.logger.debug(f"Found seed component from request body: {base_req_type}")
                        seed_component_fqns.add(base_req_type)
        
        self.logger.info(f"Discovered {len(seed_component_fqns)} unique seed components from endpoint signatures.")
        return seed_component_fqns
        
    def _is_potential_dto(self, type_name: Optional[str]) -> bool:
            """
            A robust, multi-rule heuristic to determine if a class is likely a DTO,
            POJO, or Enum that should be included as a schema component.
            This is a hybrid approach combining the best logic from both the Jersey and
            Spring analyzers.
            """
            if not type_name or self._is_primitive_or_common(type_name):
                return False

            simple_name = type_name.split('.')[-1]
            if '$' in simple_name and simple_name.endswith('Json'):
                self.logger.debug(f"[_is_potential_dto] REJECT: '{type_name}' is an Immutables.io internal JSON helper.")
                return False

            if "$lambda" in simple_name:
                self.logger.debug(f"[_is_potential_dto] REJECT: '{type_name}' is a lambda function artifact.")
                return False
            
            # ACCEPT any class that starts with "Immutable". These are the concrete DTOs we must process.
            if simple_name.startswith('Immutable'):
                # This is a strong, positive signal. We can accept it immediately.
                self.logger.debug(f"[_is_potential_dto] ACCEPT: '{type_name}' is a concrete Immutables.io implementation.")
                return True

            # --- RULE 1: Hard Rejection for Obvious Non-DTO Patterns (Combined List) ---
            # Classes ending in these suffixes are almost never data transfer objects.
            excluded_suffixes = {
                # From Spring
                'Controller', 'Service', 'ServiceImpl', 'Repository', 
                'Configuration', 'Application', 'Filter', 'Handler', 
                'Manager', 'Utils',
                # From Jersey
                'Impl', 'Factory', 'Provider', 'Tracker', 'Builder', 'Support', 'Mongo'
            }
            if any(simple_name.endswith(suffix) for suffix in excluded_suffixes):
                self.logger.debug(f"[_is_potential_dto] REJECT: '{type_name}' ends with an excluded suffix.")
                return False
                
            # Also reject generic response wrappers (from Jersey)
            if simple_name.endswith('Response'):
                base_name = simple_name[:-len('Response')]
                if base_name.lower() in ['basic', 'error', 'meta', 'links', 'raw', 'api']:
                    self.logger.debug(f"[_is_potential_dto] REJECT: '{type_name}' appears to be a generic wrapper response.")
                    return False

            # --- RULE 2: Positive Inclusion based on Package Name ---
            # If the FQN contains these keywords, it's very likely a component.
            inclusion_keywords = [
                '.dto', '.dtos', '.model', '.models', '.entity', '.entities', '.domain',
                '.request', '.response', '.vo', '.enums' # Common VO/Enum package names
            ]
            if any(keyword in type_name.lower() for keyword in inclusion_keywords):
                self.logger.debug(f"[_is_potential_dto] ACCEPT (strong signal): '{type_name}' contains an inclusion keyword.")
                return True

            # --- RULE 3: Check Class Info for Strong Signals (Enum/Interface) ---
            class_info = self.code_analyzer.get_symbol_info(type_name, self.project_path, SymbolType.CLASS)
            if class_info:
                is_resource = any(
                    ".ws.rs.Path" in (self._soot_descriptor_to_fqn(ann.get("type")) or "")
                    for ann in class_info.get("annotations", [])
                )
                if is_resource:
                    self.logger.debug(f"[_is_potential_dto] REJECT: '{type_name}' is a JAX-RS Resource (has @Path).")
                    return False

                # Filter D: Reject system-level helpers that manage resources (e.g., streams).
                # A strong general signal is implementing Closeable/AutoCloseable.
                parent_fqns = {p for p in class_info.get("parentClasses", [])}
                if "java.io.Closeable" in parent_fqns or "java.lang.AutoCloseable" in parent_fqns:
                    self.logger.debug(f"[_is_potential_dto] REJECT: '{type_name}' implements Closeable/AutoCloseable, indicating it's a system resource, not a DTO.")
                    return False
                
                # CORRECT: Enums are always schema components.
                if class_info.get("isEnum"):
                    self.logger.debug(f"[_is_potential_dto] ACCEPT: '{type_name}' is an Enum.")
                    return True

                # SUPERIOR: Jersey's nuanced check for "marker interfaces".
                if class_info.get("isInterface"):
                    parent_count = len(class_info.get("parentClasses", []))
                    method_count = len(class_info.get("functions", []))
                    # If it's an interface with no parents and no methods, it's likely a marker.
                    if parent_count == 0 and method_count == 0:
                        self.logger.debug(f"[_is_potential_dto] REJECT: '{type_name}' appears to be a marker interface.")
                        return False
                    # Otherwise, it's a valid data contract interface.
                    self.logger.debug(f"[_is_potential_dto] ACCEPT: '{type_name}' is a valid contract interface.")
                    return True

            # --- RULE 4: Fallback Rejection for Ambiguous Cases (from Spring) ---
            # If none of the above rules triggered, make a final guess.
            if '.service.' in type_name or '.security.' in type_name or '.config.' in type_name or '.util.' in type_name:
                self.logger.debug(f"[_is_potential_dto] REJECT (Fallback): '{type_name}' appears to be in a non-data package.")
                return False

            # If a class survives all filters, it is a potential component candidate.
            self.logger.debug(f"[_is_potential_dto] ACCEPT (Fallback): '{type_name}' passed all filters.")
            return True

    def _get_fqn_from_annotation_element(self, element_value: str) -> Optional[str]:
        """
        Helper to convert Soot's 'Lpath/to/Class;' descriptor from an annotation
        element to a standard FQN 'path.to.Class'.
        Returns None if the format is unexpected.
        """
        if isinstance(element_value, str) and element_value.startswith('L') and element_value.endswith(';'):
            return element_value[1:-1].replace('/', '.')
        # self.logger.warning(f"Unexpected annotation element value format for FQN: {element_value}")
        return None

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
        ... (docstring) ...
        """
        # --- START DEBUG LOGGING ---
        self.logger.info(f"[_gather_dependencies_recursively_relaxed][Depth {5-max_depth}] ENTERING with FQN: '{start_fqn}'")
        if not isinstance(start_fqn, str):
            self.logger.error(f"CRITICAL ERROR: _gather_dependencies_recursively_relaxed called with non-string type: {type(start_fqn)}. Value: {start_fqn}", exc_info=True)
            return [] # Prevent crash
        # --- END DEBUG LOGGING ---
        
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
            
            dto_implementations = self._find_and_filter_implementations(start_fqn)
            
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

        is_enum = dep_info.get("isEnum", False)
        is_dto = self._is_potential_dto(start_fqn)
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

        if not is_enum:
            properties = self._get_all_properties_for_class(start_fqn)
            self.logger.info(f"[{start_fqn}] Analyzing {len(properties)} properties for dependencies...")
            for prop in properties:
                prop_type_full = prop.get("type")
                base_type_fqn = self._get_base_type(prop_type_full)
                self.logger.info(f"[{start_fqn}] Property '{prop.get('name')}' | Full Type: '{prop_type_full}' | Base Type: '{base_type_fqn}'")
                if base_type_fqn is None:
                    self.logger.warning(f"[{start_fqn}] CRITICAL: _get_base_type returned None for full type '{prop_type_full}'. This is the likely source of the error.")

                if not base_type_fqn or base_type_fqn in visited_fqns:
                    continue
                
                nested_deps = self._gather_dependencies_recursively_relaxed(
                    base_type_fqn, visited_fqns, max_depth - 1
                )
                all_related_contexts.extend(nested_deps)
        
        if not is_enum:
            methods = dep_info.get("functions", [])
            for method in methods:
                return_type_base_fqn = self._get_base_type(method.get("returnType"))
                if return_type_base_fqn:
                    new_dependencies_to_process.add(return_type_base_fqn)

                params = method.get("parameters", [])
                for param in params:
                    param_type_base_fqn = self._get_base_type(param.get("type"))
                    if param_type_base_fqn:
                        new_dependencies_to_process.add(param_type_base_fqn)

        dep_path = dep_info.get("classFileName") or dep_info.get("filePath")
        parent_hierarchy = self.code_analyzer.get_type_hierarchy(start_fqn, dep_path)
        for parent_info in parent_hierarchy:
            parent_fqn = parent_info.get("name")
            if parent_fqn:
                new_dependencies_to_process.add(parent_fqn)
        
        self.logger.debug(f"For '{start_fqn}', found {len(new_dependencies_to_process)} potential new dependencies to process.")
        for dep_fqn in new_dependencies_to_process:
            if dep_fqn not in visited_fqns:
                nested_deps = self._gather_dependencies_recursively_relaxed(
                    start_fqn=dep_fqn,
                    visited_fqns=visited_fqns,
                    max_depth=max_depth - 1,
                    debug_context_fqn=debug_context_fqn
                )
                all_related_contexts.extend(nested_deps)
                
        return all_related_contexts

    def _build_clubbed_context(self, primary_fqn: str) -> Optional[Dict[str, Any]]:
        """
        Builds the complete, "clubbed" context for a single primary artifact,
        including its implementation, parents, and dependencies (DTOs and Enums).
        """
        self.logger.debug(f"--- Building context for primary artifact: {primary_fqn} ---")
        is_debug_target = "Track" in primary_fqn
        if is_debug_target:
            self.logger.info(f"[BUILD_CONTEXT_TARGET] Starting targeted context build for PRIMARY artifact: {primary_fqn}")

        # 1. Get Primary Artifact Info
        primary_info = self.code_analyzer.get_symbol_info(primary_fqn, self.project_path, SymbolType.CLASS)
        if not primary_info:
            self.logger.warning(f"Could not get info for primary artifact '{primary_fqn}'. Skipping.")
            return None
        
        primary_path = primary_info.get("classFileName") or primary_info.get("filePath")
        if not primary_path:
             self.logger.warning(f"Primary artifact '{primary_fqn}' is missing a file path. Skipping.")
             return None

        primary_code = self.code_analyzer.get_code_snippet(
            primary_path, primary_info.get("startLine"), primary_info.get("endLine")
        ) or f"// Code for {primary_fqn} not found."

        # 2. Find Secondary Artifact (the Data Holder)
        secondary_info = None
        impl_fqn_to_use = None

        # Strategy 2a: Try to find a definitive link from annotations first
        if primary_info.get("isInterface"):
            self.logger.debug(f"Primary '{primary_fqn}' is an interface. Looking for @JsonDeserialize.")
            for ann in primary_info.get("annotations", []):
                ann_type = self._get_fqn_from_annotation_element(ann.get("type"))
                if ann_type == "com.fasterxml.jackson.databind.annotation.JsonDeserialize":
                    for element in ann.get("elements", []):
                        if element.get("name") == "as":
                            potential_impl_fqn = self._get_fqn_from_annotation_element(element.get("value"))
                            if potential_impl_fqn:
                                temp_info = self.code_analyzer.get_symbol_info(potential_impl_fqn, self.project_path, SymbolType.CLASS)
                                if temp_info:
                                    secondary_info = temp_info
                                    impl_fqn_to_use = potential_impl_fqn
                                    self.logger.info(f"Found definitive implementation via @JsonDeserialize(as=...): {impl_fqn_to_use}")
                                    break
                    if impl_fqn_to_use: break
        
        # Strategy 2b: Fallback to Naming Convention Heuristics if no annotation link found
        if not secondary_info:
            self.logger.debug(f"No definitive implementation found via annotations for '{primary_fqn}'. Trying naming conventions.")
            
            # Heuristic 1: Standard FQN + "Impl" (e.g., com.example.MyData -> com.example.MyDataImpl)
            standard_impl_fqn = primary_fqn + "Impl"
            temp_info = self.code_analyzer.get_symbol_info(standard_impl_fqn, self.project_path, SymbolType.CLASS)
            if temp_info:
                secondary_info = temp_info
                impl_fqn_to_use = standard_impl_fqn
                self.logger.info(f"Found implementation using standard naming heuristic: {impl_fqn_to_use}")
            else:
                # Heuristic 2: Package.impl.ClassNameImpl (e.g., com.example.MyData -> com.example.impl.MyDataImpl)
                package_parts = primary_fqn.split('.')
                if len(package_parts) > 1:
                    class_name_simple = package_parts[-1]
                    base_package = ".".join(package_parts[:-1])
                    subpackage_impl_fqn = f"{base_package}.impl.{class_name_simple}Impl"
                    
                    temp_info = self.code_analyzer.get_symbol_info(subpackage_impl_fqn, self.project_path, SymbolType.CLASS)
                    if temp_info:
                        secondary_info = temp_info
                        impl_fqn_to_use = subpackage_impl_fqn
                        self.logger.info(f"Found implementation using 'impl' subpackage heuristic: {impl_fqn_to_use}")

        if not secondary_info:
            self.logger.debug(f"No implementation class found for interface '{primary_fqn}'. Will use primary artifact as the source for fields.")
        
        # 3. Gather All Fields and Properties (The "Merge")
        final_fields_list = []
        if secondary_info and impl_fqn_to_use:
            self.logger.debug(f"Gathering all properties starting from implementation: {impl_fqn_to_use}")
            final_fields_list = self._get_all_properties_for_class(impl_fqn_to_use)
        else:
            self.logger.debug(f"No Impl used. Gathering all properties starting from primary: {primary_fqn}")
            final_fields_list = self._get_all_properties_for_class(primary_fqn)
        
        self.logger.debug(f"Total unique fields/properties for '{primary_fqn}': {len(final_fields_list)}")

        # 4. Assemble the "Clubbed" Code for the LLM Prompt
        code_context_parts = [f"// --- Primary Class/Interface: {primary_fqn} ---\n{primary_code}"]
        if secondary_info and impl_fqn_to_use:
            secondary_path = secondary_info.get("classFileName") or secondary_info.get("filePath")
            if secondary_path:
                secondary_code = self.code_analyzer.get_code_snippet(
                    secondary_path, secondary_info.get("startLine"), secondary_info.get("endLine")
                ) or f"// Code for {impl_fqn_to_use} not found."
                code_context_parts.append(f"\n\n// --- Implementation: {impl_fqn_to_use} ---\n{secondary_code}")

        parent_hierarchy = self.code_analyzer.get_type_hierarchy(primary_fqn, self.project_path)
        if is_debug_target:
            parent_names = [p.get('name') for p in parent_hierarchy]
            self.logger.info(f"[BUILD_CONTEXT_TARGET] '{primary_fqn}': Identified {len(parent_names)} parents. Their code will be added to the prompt, but their own dependencies will NOT be recursively analyzed from here.")
            for p_name in parent_names:
                self.logger.info(f"[BUILD_CONTEXT_TARGET]   - Found Parent: {p_name}")
        
        # for parent in parent_hierarchy:
        #     if parent.get("code"):
        #         code_context_parts.append(f"\n\n// --- Parent Class: {parent['name']} ---\n{parent['code']}")

        clubbed_code = "".join(code_context_parts)

        # --- 5. Find and Recursively Add ALL Dependencies ---
        data_classes_context = []
        # This set is now crucial. It tracks every dependency ever added to any context
        # to avoid duplicating work and code in the final prompt.
        processed_deps_fqns = {primary_fqn}

        self.logger.info(f"Analyzing {len(final_fields_list)} fields of '{primary_fqn}' for recursive dependencies...")

        if is_debug_target:
            self.logger.info(f"[BUILD_CONTEXT_TARGET] '{primary_fqn}': Now starting recursive dependency gathering for the types of its fields ONLY.")

        for field in final_fields_list:
            base_type_fqn = self._get_base_type(field.get("type"))
            if not base_type_fqn or self._is_primitive_or_common(base_type_fqn):
                continue
            
            # Kick off the recursive gathering for this dependency.
            # The helper function will handle the 'visited' check and recursion.
            debug_context = primary_fqn if is_debug_target else None
            dependency_contexts = self._gather_dependencies_recursively(
                start_fqn=base_type_fqn,
                visited_fqns=processed_deps_fqns,
                max_depth=5, # A safe depth limit
                debug_context_fqn=debug_context
            )
            data_classes_context.extend(dependency_contexts)
        
        self.logger.info(f"[BUILD_CONTEXT] '{primary_fqn}': Now analyzing parent hierarchy for dependencies...")
        for parent_info in parent_hierarchy:
            parent_fqn = parent_info.get("name")
            if parent_fqn and self._is_potential_dto(parent_fqn):
                self.logger.debug(f"[BUILD_CONTEXT] '{primary_fqn}': Found potential DTO parent '{parent_fqn}'. Kicking off recursive gather.")
                # Use the same recursive function to gather this parent's full context.
                # The visited_fqns set will prevent re-processing if it was already seen as a field type.
                dependency_contexts = self._gather_dependencies_recursively(
                    start_fqn=parent_fqn,
                    visited_fqns=processed_deps_fqns,
                    max_depth=2 # A safe depth limit
                )
                data_classes_context.extend(dependency_contexts)

        # --- 6. Assemble Final Rich Context Dictionary ---
        simple_name = primary_info.get("className").split('.')[-1]

        return {
            "name": simple_name,
            "qualifiedName": primary_fqn,
            "path": primary_path,
            "code": clubbed_code,
            "fields_info": final_fields_list,
            "parent_classes": parent_hierarchy,
            "data_classes": data_classes_context,
            "annotations": primary_info.get("annotations", []),
            "is_interface": primary_info.get("isInterface", False),
            "supports_request": True,
            "supports_response": True
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
                #self.logger.debug(f"Inferred field '{field_name}' from getter '{method_name}' in class '{class_info.get('className')}'.")
                # The type of the inferred field is the return type of the getter.
                # Annotations on the getter method are also relevant for the field.
                inferred_fields.append({
                    "name": field_name,
                    "type": method.get("returnType"), # Type comes from getter's return type
                    "annotations": method.get("annotations", []) # Carry over annotations from getter
                })
        
        return inferred_fields
    
    def _get_all_inherited_fields(self, fqn: str, visited_fqns: Set[str]) -> List[Dict[str, Any]]:
        """
        Recursively walks the inheritance tree for a given FQN and collects all fields
        from its parent classes.
        """
        if fqn in visited_fqns:
            return []
        visited_fqns.add(fqn)

        all_fields = []
        parent_hierarchy = self.code_analyzer.get_type_hierarchy(fqn, self.project_path)

        for parent in parent_hierarchy:
            parent_fqn = parent.get("name")
            if not parent_fqn:
                continue

            parent_info = self.code_analyzer.get_symbol_info(parent_fqn, self.project_path, SymbolType.CLASS)
            if parent_info:
                parent_fields = parent_info.get("fields", [])
                if parent_fields:
                    self.logger.debug(f"Adding {len(parent_fields)} fields from parent: {parent_fqn}")
                    all_fields.extend(parent_fields)
                # Recurse to get fields from this parent's parents
                all_fields.extend(self._get_all_inherited_fields(parent_fqn, visited_fqns))
        
        return all_fields


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

    def _get_base_type(self, type_name: Optional[str]) -> Optional[str]:
        """
        Extracts the base, non-collection, non-primitive type from a Java type string.
        This parser correctly handles nested generics and common library collections.
        
        UPGRADED: Now handles Guava's Optional and collection types.
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
        # Add Guava and other common library containers to this list.
        containers = [
            # Standard JDK
            "java.util.List", "java.util.Set", "java.util.Collection",
            "java.util.Optional", "javax.ws.rs.core.Response", "jakarta.ws.rs.core.Response",
            # Google Guava
            "com.google.common.base.Optional",
            "com.google.common.collect.ImmutableList",
            "com.google.common.collect.ImmutableSet",
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
                        #self.logger.debug(f"Unwrapped '{container}' -> '{inner_content}'")
                        type_name = inner_content
                        changed_in_iteration = True
                        break 
            if changed_in_iteration:
                continue

            # Unbox Map<K, V>, focusing only on the value type V
            # This can also handle Guava's ImmutableMap
            map_prefixes = ["java.util.Map<", "com.google.common.collect.ImmutableMap<"]
            for map_prefix in map_prefixes:
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
                            #self.logger.debug(f"Unwrapped Map Value -> '{value_type}'")
                            type_name = value_type
                            changed_in_iteration = True
                            break # Break from the inner map_prefixes loop
                    else: # Handle cases like Map<String> which is invalid but might appear
                        break
            if changed_in_iteration:
                continue


        # --- Step 3: Final processing of the extracted base type ---
        final_base_type = self._soot_descriptor_to_fqn(type_name)
        
        # If after all unwrapping, we are left with a primitive, it's not a component FQN.
        if self._is_primitive_or_common(final_base_type) and "java" not in final_base_type:
             #self.logger.debug(f"_get_base_type: Final extracted type '{final_base_type}' is primitive or common, returning None as it's not a component FQN.")
             return None

        #self.logger.info(f"_get_base_type: For original='{original_type_for_logging}', extracted base type='{final_base_type}'")
        return final_base_type
    
    def _is_list_type(self, type_name: Optional[str]) -> bool:
        """Checks if a type name represents a List, Set, Collection, or Array."""
        if not type_name:
            return False
        # Check for array first
        if type_name.endswith("[]"):
            return True
        # Check for common collection interfaces/classes
        # Using startswith is generally safe for fully qualified names
        return type_name.startswith("java.util.List") or \
               type_name.startswith("java.util.Set") or \
               type_name.startswith("java.util.Collection")

    def _get_simple_name_from_annotation_type(self, annotation_data: Dict[str, Any]) -> Optional[str]:
        """
        Parses an annotation data dictionary from the Java analyzer to extract its simple name.
        Handles Java type descriptors (e.g., 'Lpath/to/Annotation;') and converts them to a simple name.

        Args:
            annotation_data: A dictionary representing a single annotation.
                             Expected to have a 'type' key with a Java type descriptor.

        Returns:
            The simple name of the annotation (e.g., "QueryParam"), or None if parsing fails.
        """
        if not isinstance(annotation_data, dict):
            return None

        # The Java analyzer provides the FQN in a descriptor format in the 'type' key
        type_descriptor = annotation_data.get('type')

        if not isinstance(type_descriptor, str) or not type_descriptor.startswith('L') or not type_descriptor.endswith(';'):
            # The key is missing or the format is unexpected.
            return None
        
        # Strip 'L' and ';' and replace '/' with '.' to get the FQN
        # e.g., 'Ljavax/ws/rs/QueryParam;' -> 'javax.ws.rs.QueryParam'
        fqn = type_descriptor[1:-1].replace('/', '.')
        
        # Return the simple name (the last part of the FQN)
        return fqn.split('.')[-1]
    
    @property
    def framework_name(self) -> str:
        return "Jersey"

    @property
    def language_name(self) -> str:
        return "java"

    def get_schema_component_terminology(self) -> str:
        # Describe what a schema component represents in Java/Jersey context
        return "POJO/DTO" # Plain Old Java Object / Data Transfer Object

#     def get_component_system_message(self) -> str:
#         # Provide a good system message for the LLM when generating component schemas
#         return """You are an expert in Java, JAX-RS (Jersey), object-oriented design, common Java libraries (like Jackson for JSON, JAXB for XML), and OpenAPI 3.0 specifications.
# Your task is to analyze Java Plain Old Java Objects (POJOs) or Data Transfer Objects (DTOs) and their related context (parent classes, field types) to generate corresponding OpenAPI component schemas (request and response versions).
# Pay close attention to annotations (like Jackson, JAXB, JSR 303/380 validation) as they provide critical hints for serialization, validation, and schema properties."""

    def get_component_system_message(self) -> str:
            # Provide a good system message for the LLM when generating component schemas
            return """You are an expert in Java, JAX-RS (Jersey), object-oriented design, common Java libraries (like Jackson for JSON, JAXB for XML), and OpenAPI 3.0 specifications.
    Your task is to analyze Java Plain Old Java Objects (POJOs) or Data Transfer Objects (DTOs) and their related context (parent classes, field types) to generate corresponding OpenAPI component schemas.
    Pay close attention to annotations (like Jackson, JAXB, JSR 303/380 validation) as they provide critical hints for serialization, validation, and schema properties."""



#     def get_component_field_instructions(self, component_name: str, component_info: Dict[str, Any]) -> str:
#         # 'component_name' is likely the FQN key, use component_info for user-friendly name
#         simple_name = component_info.get('name', component_name.split('.')[-1])
#         request_schema_name = f"{simple_name}Request"
#         response_schema_name = f"{simple_name}Response"

#         return f"""
# For the Java class '{component_info.get('qualifiedName', component_name)}' provided in the context:
# 1.  Generate two separate schemas: '{request_schema_name}' (for request contexts) and '{response_schema_name}' (for response contexts).
# 2.  Analyze the fields defined in the primary class (`{simple_name}`), its parent classes (code provided in `parent_classes`), and any related component classes (code provided in `data_classes`). Inheritance matters.
# 3.  Identify all relevant fields for serialization. This typically includes public fields and fields exposed via public getters (e.g., `getXyz()`, `isAbc()`). Consider fields from parent classes unless overridden.
# 4.  Exclude fields explicitly marked for exclusion using annotations like Jackson's `@JsonIgnore`, JAXB's `@XmlTransient`, or JPA's `@Transient`.
# 5.  For each relevant field:
#     a.  Determine its final Java type considering inheritance and potential generics (e.g., `String`, `int`, `List<String>`, `com.example.RelatedPojo`).
#     b.  Map the Java type to an OpenAPI `type` (`string`, `integer`, `number`, `boolean`, `object`, `array`) and optionally `format` (e.g., `int32`, `int64`, `float`, `double`, `date-time`, `byte`, `binary`). Use standard mappings (e.g., `java.util.Date`/`java.time.OffsetDateTime` -> `string`+`date-time`, `int`/`Integer` -> `integer`+`int32`, `long`/`Long` -> `integer`+`int64`, `byte[]` -> `string`+`byte`).
#     c.  If the field type is a collection (`List`, `Set`, array), set OpenAPI `type: array` and define the `items` schema. The `items` schema should usually be a `$ref` to the element type's corresponding *Request* or *Response* schema (e.g., `items: {{ $ref: '#/components/schemas/RelatedPojoResponse' }}`). If the element type is primitive, define it directly (e.g., `items: {{ type: string }}`).
#     d.  If the field type is another custom POJO/DTO identified in the context, use a `$ref` to its corresponding *Request* or *Response* schema (e.g., `$ref: '#/components/schemas/{request_schema_name}'` or `$ref: '#/components/schemas/{response_schema_name}'` for the correct context, or `RelatedPojoRequest`/`RelatedPojoResponse` for other POJOs). Be consistent with the Request/Response suffix.
#     e.  Infer `description` from JavaDocs (`/** ... */`) on the field or its getter if available. Otherwise, provide a reasonable description based on the field name.
#     f.  Infer `readOnly`/`writeOnly` status:
#         - Fields only having a getter (or `isXyz`) but no setter are often `readOnly: true` (especially for responses).
#         - Fields only having a setter but no getter are often `writeOnly: true` (especially for requests).
#         - Annotations like Jackson's `@JsonProperty(access = READ_ONLY/WRITE_ONLY)` are strong indicators.
#         - JPA `@Id` fields, especially if auto-generated (`@GeneratedValue`), are typically `readOnly: true` in responses.
#     g.  Determine `required` fields for the **request schema** (`{request_schema_name}`):
#         - Check for validation annotations like `@NotNull`, `@NotBlank`, `@NotEmpty`, `@Size(min=1)` (from `javax.validation.constraints` or `jakarta.validation.constraints`).
#         - Java primitive types (`int`, `boolean`, etc., *not* their wrappers `Integer`, `Boolean`) are implicitly required unless specifically annotated otherwise (though explicit validation annotations are preferred).
#         - Fields initialized with default values in constructors or directly might not be required.
#     h. Determine `required` fields for the **response schema** (`{response_schema_name}`): Generally include fields that are *always* expected to be present in a valid response. Nullable fields might not be required. Primitives are usually required.
# 6.  Name the schemas exactly as `{request_schema_name}` and `{response_schema_name}`.
# 7.  Place both schemas under the `components.schemas` path in the output YAML.
# """


    def get_component_field_instructions(self, component_name: str, component_info: Dict[str, Any]) -> str:
        # This is a complete rewrite tailored for JAX-RS/Jersey with meta-reasoning
        simple_name = component_info.get('name', component_name.split('.')[-1])

        # Check if the component is an Enum (This logic is framework-agnostic and remains)
        if component_info.get('code', '').lstrip().startswith('public enum'):
            enum_constants = [
                field['name'] for field in component_info.get('fields_info', [])
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
        - Identify all fields and their Java types from the class and its parents.
        - Note JAXB annotations (@XmlElement, @XmlAttribute, @XmlTransient, @XmlAccessorType). Model the Public Contract, Not the Internal Structure. The final JSON structure is determined by the JAX-RS provider's serialization rules (often JAXB/MOXy/JSON-B), not just the private field layout. Public getters and fields annotated with `@XmlElement` are the primary source of truth.
        - Check for parent classes and their fields (inheritance matters).

        ### Q2: How does this class behave at runtime?
        - Does the constructor set default values for any fields?
        - What happens when fields are missing from incoming JSON? Are they initialized to null or a default?

        ### Q3: What constraints exist on the data?
        - Look for validation annotations (@NotNull, @NotBlank, @NotEmpty, @Size, @Min, @Max, @Pattern from `jakarta.validation.constraints` or `javax.validation.constraints`).
        - Check if this is an entity with JPA annotations (@Column, @NotNull on entity fields).
        - Are there constants that define limits (MAX_LENGTH, MIN_VALUE)?
        - What validations would cause a 400 Bad Request?

        ### Q4: Which fields are truly required?
        For each field, consider:
        - Does it have @NotNull, @NotBlank, or @NotEmpty?
        - Is it a Java primitive type (`int`, `boolean`, etc.) which cannot be null?
        - For entities: Does the database column allow NULL (e.g., no `@Column(nullable = false)`)?
        - Would the API actually reject a request if this field is missing?

        ### Q5: How are special types handled?
        - For dates: Use `type: string` and `format: date-time` for standard types like `java.time.OffsetDateTime`. Adhere to ISO-8601.
        - For enums: Extract ALL possible values from the enum definition.
        - For collections: Identify the element type.

        ## Generation Rules Based on Your Analysis:

        ### For each field, define its schema properties:
        - If the field's type is another POJO/DTO (its code is in data_classes), use a $ref following the rules if reference. Example: $ref: '#/components/schemas/{simple_name}OfNestedObject'.

        **Rule for Referencing:**
        - **IF** a field's type is a custom class (like `Address`) AND its name (e.g., `Address`) is in the list of available schemas, you could use a `$ref` if you think the component is used as is.
          Example: `address: {{ $ref: '#/components/schemas/Address' }}`

        - **IF** a field's type is a custom class (like `Profile`) AND its name is **NOT** in the list of available schemas, you **MUST NOT** use a `$ref`. Instead, you **MUST** define its schema *inline* under the field.


        ### Field Naming and Inclusion:
        a. Use the name from JAXB's @XmlElement(name="custom_name") if present. Otherwise, use the Java field name.
        b. Exclude fields annotated with @XmlTransient (for JAXB) or @JsonIgnore (if Jackson is used as the provider). Also exclude fields marked with the `transient` keyword.

        ### Type Mapping:
        - String, UUID → type: string (UUID gets format: uuid)
        - Integer, int → type: integer, format: int32
        - Long, long → type: integer, format: int64
        - Double, double, Float, float → type: number
        - Boolean, boolean → type: boolean
        - LocalDateTime, Date, OffsetDateTime -> type: string, format: date-time
        - Custom POJOs → $ref: '#/components/schemas/{simple_name}' or inline
        - Enums → type: string with enum: [...] containing ALL constant names
        - Collections (List, Set, []) → type: array with items schema

        ### Additional Properties:
        - readOnly: true if a field has a public getter but no public setter, or is a JPA `@Id` with `@GeneratedValue`.
        - writeOnly: true if a field has a public setter but no public getter.
        - Include validation constraints: minLength, maxLength, minimum, maximum, pattern.

        ### Required Fields - Critical Analysis:
        Create a 'required' array. Include a field ONLY if:
        
        Step 1 - Check for validation annotations:
        - Has @NotNull, @NotBlank, or @NotEmpty from javax/jakarta.validation
        - Is a primitive type (not wrapper) - these can't be null
        
        Step 2 - Consider nullability overrides:
        - If has an `@Nullable` annotation → NOT required
        - For entities: If JPA `@Column` allows null (e.g., no `nullable=false`) → NOT required
        
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
        - [ ] Date formats are correctly represented (e.g., date-time for standard date objects)?
        - [ ] Required array contains ONLY fields that would cause errors if missing?
        - [ ] Field names match JAXB annotations (@XmlElement) or default Java naming conventions?
        - [ ] Validation constraints (min/max/pattern) are included where found?

        ## Output format:
        The output open API specs should have the following yaml syntax. It has two sections under 'components' and 'x-schemas-metadata':
        ```yaml
            components:
                schemas:
                    YourClassName:
                    type: object
                    properties:
                        field_name:  # From @XmlElement or field name
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
        - Think like JAX-RS/Jersey - Consider how the configured JSON provider (like JAXB, MOXy, JSON-B) serializes objects based on annotations and public accessors.
        - Do not give anything other than the spec output in the response
        - Think hard before answering.
        """

    def get_initial_context_presentation_for_missing_symbols(self,  endpoint: Dict[str, Any], endpoint_context: Dict[str, Any]) -> str:
        """
        Formats the Jersey-specific initial endpoint context for the missing symbols prompt.
        """
        url = endpoint.get("url", {}).get("url", "N/A")
        http_method = endpoint.get("method", "N/A").upper()
        handler_details = endpoint_context.get("handler", {})
        handler_method_name = handler_details.get("name", "UnknownMethod")
        handler_class_fqn = handler_details.get("class_name_fqn", "UnknownClass")
        fn_name_for_prompt = f"{handler_class_fqn}.{handler_method_name}"
        # Preamble for Jersey
        prompt_str = f"""You are analyzing the JAX-RS API endpoint '{http_method} {url}' handled by the method '{fn_name_for_prompt}' in class '{handler_class_fqn}''.
The goal is to generate a complete OpenAPI specification path item for this endpoint.

Here is the initial code context retrieved for this endpoint:

"""
        # Code context blocks for Jersey
        code = self._format_endpoint_context_for_prompt(endpoint_context)
        prompt_str += code

        return prompt_str.strip()
    
    def _format_endpoint_context_for_prompt(self, endpoint_context: Dict[str, Any]) -> str:
        """
        Formats the structured endpoint context into a string for LLM prompts.
        This method is backward-compatible and handles both:
        1. The new Jersey context with a 'handler_methods' list and 'pojos'.
        2. The old Django context with a single 'handler' and 'serializers'.
        """
        formatted_string_parts = []
        delimiter = "\n===###===\n"

        # --- Handler Formatting (Handles both Jersey and Django cases) ---
        if "handler_methods" in endpoint_context and endpoint_context["handler_methods"]:
            handler_methods = endpoint_context["handler_methods"]
            formatted_string_parts.append("Handler Method Definitions:")
            for idx, handler in enumerate(handler_methods):
                formatted_string_parts.append(f"\n--- Handler Method {idx + 1} of {len(handler_methods)} ---")
                if handler.get('code'):
                    formatted_string_parts.append(f"Source File: {handler.get('path', 'N/A')}")
                    formatted_string_parts.append(f"Code Snippet ({handler.get('name')}):\n```java\n{handler['code']}\n```")
        elif "handler" in endpoint_context and endpoint_context["handler"]:
            handler = endpoint_context["handler"]
            formatted_string_parts.append(f"Source File: {handler.get('path', 'N/A')}")
            formatted_string_parts.append(f"Line Number: {handler.get('location', {}).get('start_line', 'N/A')}-{handler.get('location', {}).get('end_line', 'N/A')}")
            formatted_string_parts.append(f"Code Snippet:\n{handler.get('code', '# Handler code not available')}\n")
        else:
            formatted_string_parts.append("# Handler code not available.")

        # --- Serializer / POJO Formatting (Handled Separately) ---

        # Case 1: Django Context with 'serializers'
        serializers = endpoint_context.get("serializers", [])
        if serializers:
            formatted_string_parts.append(f"{delimiter}Serializer and Model code starts:")
            for ser in serializers:
                formatted_string_parts.append(f"{delimiter}Source File: {ser.get('path', 'N/A')}")
                formatted_string_parts.append(f"Line Number: {ser.get('start_line', 'N/A')}-{ser.get('end_line', 'N/A')}")
                formatted_string_parts.append(f"Code Snippet (Serializer/Model: {ser.get('name', 'N/A')}):\n{ser.get('code', '# Code not available')}\n")
                for model in ser.get("data_classes", []):
                    formatted_string_parts.append(f"{delimiter}Source File: {model.get('path', 'N/A')}")
                    formatted_string_parts.append(f"Code Snippet (Model: {model.get('name', 'N/A')}):\n{model.get('code', '# Code not available')}\n")
            formatted_string_parts.append(f"{delimiter}Serializer and Model code ends")

        
        handler_classes = endpoint_context.get("handler_classes", [])
        if handler_classes:
            formatted_string_parts.append(f"{delimiter}Handler Classes:")
            for item in handler_classes:
                # Use a generic header for all these additional classes
                item_name = item.get("qualifiedName") or item.get("name", "N/A")
                formatted_string_parts.append(f"{delimiter}Source File: {item.get('path', 'N/A')}")
                formatted_string_parts.append(f"Code Snippet (Class: {item_name}):\n```java\n{item.get('code', '# Code not available')}\n```")
                
        # Case 2: Jersey Context with 'pojos'
        pojos = endpoint_context.get("pojos", [])
        processed_pojos = []
        if pojos:
            formatted_string_parts.append(f"{delimiter}Associated POJOs/DTOs:")
            for pojo in pojos:
                name_key = "qualifiedName" if "qualifiedName" in pojo else "name"
                if name_key in processed_pojos:
                    continue
                formatted_string_parts.append(f"{delimiter}Source File: {pojo.get('path', 'N/A')}")
                formatted_string_parts.append(f"POJO: {pojo.get(name_key, 'N/A')}")
                formatted_string_parts.append(f"Code Snippet:\n```java\n{pojo.get('code', '# Code not available')}\n```")
                processed_pojos.append('name_key')
                data_classes = pojo.get('data_classes', [])
                parent_classes = pojo.get('parent_classes', [])
                
                for data_class in data_classes:
                    name_key = "qualifiedName" if "qualifiedName" in data_class else "name"
                    if name_key in processed_pojos:
                        continue
                    formatted_string_parts.append(f"{delimiter}Source File: {data_class.get('path', 'N/A')}")
                    # Use a consistent header for all related classes
                    formatted_string_parts.append(f"POJO/DTO Dependency: {data_class.get(name_key, 'N/A')}")
                    formatted_string_parts.append(f"Code Snippet:\n```java\n{data_class.get('code', '# Code not available')}\n```")
                    processed_pojos.append(name_key)

                for parent_class in parent_classes:
                    name_key = "qualifiedName" if "qualifiedName" in parent_class else "name"
                    if name_key in processed_pojos:
                        continue
                    formatted_string_parts.append(f"{delimiter}Source File: {parent_class.get('path', 'N/A')}")
                    # Use a consistent header for all related classes
                    formatted_string_parts.append(f"POJO/DTO Dependency: {parent_class.get(name_key, 'N/A')}")
                    formatted_string_parts.append(f"Code Snippet:\n```java\n{parent_class.get('code', '# Code not available')}\n```")
                    processed_pojos.append(name_key)

        # --- Common Logic for Features and Extra Context ---
        
        # Custom Features (Pagination, Filters etc.)
        features = endpoint_context.get("features", [])
        if features:
            formatted_string_parts.append(f"{delimiter}Custom code starts:") # Match original Django prompt
            for feat in features:
                formatted_string_parts.append(f"{delimiter}Source File: {feat.get('path', 'N/A')}")
                formatted_string_parts.append(f"Line Number: {feat.get('start_line', 'N/A')}-{feat.get('end_line', 'N/A')}")
                formatted_string_parts.append(f"Code Snippet (Feature: {feat.get('name', 'N/A')}, Type: {feat.get('type', 'N/A')}):\n{feat.get('code', '# Code not available')}\n")
            formatted_string_parts.append(f"{delimiter}Custom code ends")

        other_context = endpoint_context.get("other_context", [])
        if other_context:
            formatted_string_parts.append(f"{delimiter}Other Relevant Classes:")
            for item in other_context:
                # Use a generic header for all these additional classes
                item_name = item.get("qualifiedName") or item.get("name", "N/A")
                formatted_string_parts.append(f"{delimiter}Source File: {item.get('path', 'N/A')}")
                formatted_string_parts.append(f"Code Snippet (Class: {item_name}):\n```java\n{item.get('code', '# Code not available')}\n```")
                
                
        # Extra Context from recursive fetching
        extra_context = endpoint_context.get("extra_context", [])
        if extra_context:
            # Replicating the original Django formatting for this section
            extra_funcs = [item for item in extra_context if item.get('type') == 'FUNCTION']
            extra_classes = [item for item in extra_context if item.get('type') == 'CLASS']
            extra_vars = [item for item in extra_context if item.get('type') == 'VARIABLE']

            if extra_funcs:
                 formatted_string_parts.append(f"{delimiter}Extra Functions Code Start")
                 for item in extra_funcs:
                      formatted_string_parts.append(f"{delimiter}Source File: {item.get('path', 'N/A')}")
                      formatted_string_parts.append(f"Code Snippet (Function: {item.get('name', 'N/A')}):\n{item.get('code', '# Code not available')}\n")
                 formatted_string_parts.append(f"{delimiter}Extra Functions Code End")
            
            if extra_classes:
                 formatted_string_parts.append(f"{delimiter}Extra Classes Code Start")
                 for item in extra_classes:
                      formatted_string_parts.append(f"{delimiter}Source File: {item.get('path', 'N/A')}")
                      formatted_string_parts.append(f"Code Snippet (Class: {item.get('name', 'N/A')}):\n{item.get('code', '# Code not available')}\n")
                 formatted_string_parts.append(f"{delimiter}Extra Classes Code End")

            # if extra_vars:
            #     formatted_string += f"{delimiter}Extra Variables Code Start\n"
            #     for item in extra_vars:
            #           formatted_string += f"{delimiter}Source File: {item.get('path', 'N/A')}\n"
            #           formatted_string += f"Line Number: {item.get('start_line', 'N/A')}-{item.get('end_line', 'N/A')}\n"
            #           formatted_string += f"Code Snippet (Variable: {item.get('name', 'N/A')}):\n{item.get('code', '# Code not available')}\n"
            #     formatted_string += f"{delimiter}Extra Variables Code End\n"

        # Final cleanup to remove any leading delimiter if the first section was empty
        final_string = "\n".join(formatted_string_parts)
        if final_string.startswith(delimiter):
            final_string = final_string[len(delimiter):]

        return final_string.strip()
    
    def get_framework_specific_guidance_for_missing_symbols(self) -> str:
        """
        Provides Jersey-specific instructions on what kinds of custom symbols to look for.
        """
        return """
Focus on:
1.  **Custom Types**:
    *   Project-specific classes for method parameters (in `handler.method_parameters_info.type`), return types (`handler.returnType`), or POJO fields (in `pojos.*.fields_info.*.type`) if their full definition is NOT already provided in 'Associated POJOs/DTOs'.
    *   Custom classes instantiated (e.g., `new MyCustomValidator()`) or used as local variable types within the `handler.code` or POJO method code (if available).
2.  **Custom Annotations**: Project-specific annotation definitions (the `@interface` code) if they clarify behavior (e.g., custom validation, serialization rules) and are not standard JAX-RS, Bean Validation, Jackson, etc.
3.  **Static Method Calls**: Calls to static utility methods from other custom classes in your project (e.g., `com.example.MyUtil.formatData(...)`).
4.  **Helper/Service Class Methods**: Calls to methods on injected (e.g., via `@Autowired` if Spring is used alongside, or `@Inject`) or instantiated helper/service objects, if these are custom project classes whose definitions are needed.
5.  **Parent Classes/Interfaces**: Custom, non-JDK/framework parent classes or interfaces if their definition is crucial for understanding inherited fields/behavior and not already provided.
6.  **JAX-RS Extensibility Points**: Potentially custom `MessageBodyReader/Writer`, `ExceptionMapper`, JAX-RS Filters (`ContainerRequestFilter`, `ContainerResponseFilter`), or Interceptors (`ReaderInterceptor`, `WriterInterceptor`) if explicitly referenced by name/binding and their logic is critical for the API contract.
"""

    def get_framework_specific_exclusions_for_missing_symbols(self) -> List[str]:
        """
        Returns Jersey-specific patterns or FQNs to exclude.
        """
        return [
            "javax.ws.rs.*",
            "jakarta.ws.rs.*",
            "org.glassfish.jersey.*", # Jersey internals
            "java.net.URI", # Common return/param type, not a custom symbol
            # Add common library FQNs like Jackson, JAXB if they are never custom-extended
            "com.fasterxml.jackson.databind.*",
            "javax.xml.bind.annotation.*",
            "io.swagger.annotations.*", # Swagger annotations themselves
        ]

    def get_framework_specific_exclusion_instructions_for_missing_symbols(self) -> str:
        """
        Returns the Jersey-specific "Exclusions:" section.
        """
        jersey_specific_exclusions = self.get_framework_specific_exclusions_for_missing_symbols() # Get list of patterns

        exclusion_text = "Exclusions:\n"
        exclusion_text += "- Do NOT include standard JDK classes (e.g., `java.lang.String`, `java.util.List`) or Python standard library modules (e.g., `os`, `json`) unless they have been significantly subclassed with custom logic relevant to the API contract.\n"
        exclusion_text += "- Do NOT include unmodified base classes/interfaces from the primary framework (e.g., JAX-RS's `javax.ws.rs.core.Response`, `jakarta.ws.rs.Path`) unless they have been significantly subclassed *and* the specific subclass is referenced *and* its custom logic is relevant to the API contract.\n"
        
        if jersey_specific_exclusions:
            exclusion_text += "- Specifically, also avoid unmodified versions of symbols from common libraries like:\n"
            for exc_pattern in sorted(list(set(jersey_specific_exclusions))):
                exclusion_text += f"  - `{exc_pattern}`\n"
        return exclusion_text
    
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