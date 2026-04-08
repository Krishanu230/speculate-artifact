from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple
from .framework_analyzer import FrameworkAnalyzer

class PromptManager:
    """Manages generation of prompts for OpenAPI documentation"""
    
    def __init__(self, framework_analyzer: FrameworkAnalyzer):
        """
        Initialize with framework analyzer for framework-specific instructions.

        Args:
            framework_analyzer: An instance of either DjangoFrameworkAnalyzer or JerseyFrameworkAnalyzer.
        """
        self.framework_analyzer = framework_analyzer
        self._signature_cache = {}
    
    def _get_base_system_instructions(self, task_description: str) -> str:
        """
        Generates a base system instruction common to most prompts.
        The FrameworkAnalyzer can then prepend its own specific system message.
        """
        return (
            f"You are an expert in {self.framework_analyzer.framework_name.upper()} " # Use framework name
            "and OpenAPI specifications 3.0. Your task is to generate a specific part of an "
            "OpenAPI specification based on the provided code context and instructions.\n"
            f"Specifically, you will be {task_description}.\n"
            "Analyze the code context carefully. The code might deviate from standard practices. "
            "Adhere strictly to OpenAPI 3.0 syntax."
        )
    
    def get_available_components_message(self, available_schemas_map: Dict[str, Dict[str, Any]]) -> str:
        """
        Generates a human-readable string listing the available components, their source FQNs,
        and their class signatures if available.
        """
        if not available_schemas_map:
            return "There are currently no other component schemas available for referencing. All nested custom objects MUST be defined inline."
        
        # Sort by the schema name for consistent output
        sorted_components = sorted(available_schemas_map.items())
        
        component_list_lines = []
        for name, info in sorted_components:
            line = f"- `{name}` (from class `{info.get('fqn', 'unknown FQN')}`)"

            # Safely try to get the signature
            fqn = info.get('fqn')
            signature = None
            if fqn:
                # Check cache first
                if fqn in self._signature_cache:
                    signature = self._signature_cache[fqn]
                # If not cached, try to generate it if the analyzer supports it
                elif hasattr(self.framework_analyzer, 'get_class_signature_from_fqn'):
                    try:
                        signature = self.framework_analyzer.get_class_signature_from_fqn(fqn)
                        self._signature_cache[fqn] = signature # Cache the result (even if None)
                    except Exception:
                        # Safety net in case of unexpected errors during signature generation
                        self._signature_cache[fqn] = None # Cache failure to prevent retries
            
            if signature:
                # Add it as an indented code block for better readability
                line += f"\n  ```java\n  {signature}\n  ```"
            
            component_list_lines.append(line)
        
        # Use an extra newline between entries for better readability when signatures are present
        component_list_str = "\n\n".join(component_list_lines)
        
        return (
            "\nThe following component schemas are already available and could be referenced using `$ref`:"
            f"\n{component_list_str}\n"
            "When using `$ref`, you MUST use the schema name (e.g., `User`, `Report_1`), not the Java class name.\n"
        )


    def create_component_prompt(self, component_name: str, component_info: Dict[str, Any], available_schemas_map) -> str:
        framework_system_message = self.framework_analyzer.get_component_system_message()
        # task_description = (
        #     f"creating OpenAPI component schemas (request and response versions) for the "
        #     f"{self.framework_analyzer.get_schema_component_terminology()} named '{component_info.get('name', component_name)}'."
        # )

        task_description = (
            f"creating OpenAPI component schemas for the "
            f"{self.framework_analyzer.get_schema_component_terminology()} named '{component_info.get('name', component_name)}'."
        )
        

        base_system_instructions = self._get_base_system_instructions(task_description)
        #full_system_instructions = f"{framework_system_message}\n\n{base_system_instructions}"
        full_system_instructions = f"{base_system_instructions}"
        code_context = self._build_component_code_context(component_name, component_info)
        
        # This now includes instructions on how to name schemas and handle $ref suffixes
        framework_field_and_naming_instructions = self.framework_analyzer.get_component_field_instructions(component_name, component_info)

        # Common OpenAPI rules that are not framework-specific
        common_openapi_rules = self._get_common_component_openapi_rules()

        quality_notes = self._get_common_quality_assurance_notes()

        available_components_text = self.get_available_components_message(available_schemas_map)

        full_prompt = (
            f"{full_system_instructions}"
            f"{framework_field_and_naming_instructions}"
            f"{available_components_text}"
            f"Provided Code Context:\n```\n{code_context}```\n\n"
            f"General OpenAPI Output Requirements:\n{common_openapi_rules}\n\n" # New helper
            f"Important Quality Notes:\n{quality_notes}"
        )
        return full_prompt

#     def _get_common_component_openapi_rules(self) -> str:
#         """Get common OpenAPI output rules for component schemas, without naming specifics."""
#         return """
# 1.  You will generate two separate OpenAPI component schemas.
# 2.  Each schema MUST be a valid OpenAPI 3.0 Schema Object.
# 3.  Primarily, each schema definition should contain a `type: object` and a `properties` field.
# 4.  For each field within `properties`:
#     a.  Determine its OpenAPI `type` (e.g., string, integer, number, boolean, object, array).
#     b.  Provide a concise `description` for the field.
#     c.  If the field's type is an `array`, define its `items` schema.
#     d.  If the field's type is another component, use a `$ref`. The exact format of the $ref (including suffixes like 'Request' or 'Response') will be guided by framework-specific instructions. If the referenced component is external or a primitive, define its schema inline.
# 5.  For the **request schema**:
#     a.  Include a `required` array listing all fields that are mandatory for a request.
#     b.  Indicate fields that are effectively `readOnly` if discernible.
# 6.  For the **response schema**:
#     a.  Include a `required` array listing all fields typically present in a response.
#     b.  Indicate fields that are `writeOnly` if discernible.
# 7.  The final output MUST start with `components:`, followed by `schemas:`, under which the generated schema definitions are placed. Do not include any other OpenAPI sections.
# 8.  Do not include `x-codeSamples`.
# 9.  Strictly adhere to OpenAPI 3.0 syntax.
# 10. Ensure all generated text (descriptions, examples) is enclosed in double-quotes.
# """


    def _get_common_component_openapi_rules(self) -> str:
        """Get common OpenAPI output rules for component schemas, without naming specifics."""
        return """
1.  You will generate OpenAPI component schema.
2.  Each schema MUST be a valid OpenAPI 3.0 Schema Object.
3.  Primarily, each schema definition should contain a `type: object` and a `properties` field.
4.  For each field within `properties`:
    a.  Determine its OpenAPI `type` (e.g., string, integer, number, boolean, object, array).
    b.  If the field's type is an `array`, define its `items` schema.
    c.  If the field's type is another component, use a `$ref`. The exact format of the $ref  will be guided by framework-specific instructions. If the referenced component is external or a primitive, define its schema inline.
7.  Do not include `x-codeSamples`.
8.  Strictly adhere to OpenAPI 3.0 syntax.
"""

    def _build_component_code_context(self, component_name: str, component_info: Dict[str, Any]) -> str:
        """Build the code context for the component prompt, generalized."""
        # component_info directly comes from FrameworkAnalyzer.get_schema_components()
        # It should contain keys like 'name', 'path', 'code', 'parent_classes' (list of dicts),
        # 'data_classes' (list of dicts - for Django models, or related POJOs for Java).

        code_context_parts = []
        processed_fqns = set()
        primary_fqn = component_info.get('qualifiedName')

        # Component's own code
        code_context_parts.append(
            f"# Component Definition: {component_info.get('name', component_name)}\n"
            f"# Source File: {component_info.get('path', 'N/A')}\n"
            f"{component_info.get('code', '# Code not available')}\n"
        )
        if primary_fqn:
            processed_fqns.add(primary_fqn)


        # Parent classes
        parent_classes = component_info.get('parent_classes', [])
        if parent_classes:
            code_context_parts.append("# Parent Class Definitions (if any):")
            for parent in parent_classes:
                code_context_parts.append(
                    f"## Parent Class: {parent.get('name', 'UnknownParent')}\n"
                    f"## Source File: {parent.get('path', 'N/A')}\n"
                    f"{parent.get('code', '# Parent code not available')}\n"
                )

        # Related data classes (e.g., Django models for serializers, or nested POJOs for Java)
        data_classes = component_info.get('data_classes', [])
        if data_classes:
            term = "Model(s)" if self.framework_analyzer.framework_name.lower() == "django" else "Related Data Class(es)"
            code_context_parts.append(f"# Associated {term} (if any):")
            for dc in data_classes:
                dc_fqn = dc.get('qualifiedName')
                if dc_fqn:
                    if dc_fqn in processed_fqns:
                        continue
                    else:
                        code_context_parts.append(
                        f"## {term[:-3] if term.endswith('(s)') else term}: {dc.get('name', 'UnknownDataClass')}\n"
                        f"## Source File: {dc.get('path', 'N/A')}\n"
                        f"{dc.get('code', '# Data class code not available')}\n"
                    )
                        processed_fqns.add(dc_fqn)
                else:
                    code_context_parts.append(
                        f"## {term[:-3] if term.endswith('(s)') else term}: {dc.get('name', 'UnknownDataClass')}\n"
                        f"## Source File: {dc.get('path', 'N/A')}\n"
                        f"{dc.get('code', '# Data class code not available')}\n"
                    )
        
        # Add common imports relevant to the framework (optional, could be part of system message)
        # For Java, this might include common JAX-RS, Jackson, JPA imports.
        # For Django, it might include rest_framework.serializers, models.
        # This part can be delegated to framework_analyzer.get_common_component_imports_context()
        return "\n".join(code_context_parts)

#     def _get_common_quality_assurance_notes(self) -> str:
#         """Get common quality assurance notes."""
#         return """
# -   Note: Request and response schemas for the same logical entity can differ.
# -   Note: Use your knowledge of common library patterns for the given framework.
# -   Note: Ensure strict conformance to OpenAPI 3.0.
# -   Note: Provide complete and exhaustive schemas. Do not omit information or provide incomplete details.
# -   Note: Do not ask for missing information; generate the complete spec for both request and response schemas based on the provided context.
# """


    def _get_common_quality_assurance_notes(self) -> str:
            """Get common quality assurance notes."""
            return """
    -   Note: Use your knowledge of common library patterns for the given framework.
    -   Note: Ensure strict conformance to OpenAPI 3.0.
    -   Note: Provide complete and exhaustive schemas. Do not omit information or provide incomplete details.
    -   Note: Do not ask for missing information; generate the complete spec for schemas based on the provided context.
    """



    # def _build_component_code_context(self, component_name: str, component_info: Dict[str, Any]) -> str:
    #     """Build the code context for the component prompt"""
    #     code_context = ""
        
    #     # Framework context (common imports)
    #     code_context += """
    # from model_utils import Choices
    # from rest_framework import serializers
    # from rest_framework_simplejwt.exceptions import AuthenticationFailed
    # from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
    # from rest_framework_simplejwt.settings import api_settings
    # from django.contrib.auth.models import update_last_login
    # from django.db import transaction
    # from rest_framework import filters, mixins, pagination, status, viewsets
    # from rest_framework.decorators import action
    # from rest_framework.permissions import AllowAny, IsAuthenticated
    # from rest_framework.response import Response
    # from rest_framework.settings import api_settings
    # from rest_framework_extensions.mixins import NestedViewSetMixin
    # from rest_framework_simplejwt.views import TokenObtainPairView
    # import json
    # import logging
    # import random
    # from collections import defaultdict
    # import requests
    # from bs4 import BeautifulSoup
    # from django.core.cache import cache as redis_cache
    # from django.db.models import Count, Exists, OuterRef, Prefetch, Q
    # from django_filters.rest_framework import DjangoFilterBackend, FilterSet
    # from drf_spectacular.utils import extend_schema
    # """
        
    #     # Serializer code
    #     code_context += f"\n\n# Serializer Definition\n"
    #     code_context += f"Source File: {component_info['path']}\n"
    #     code_context += f"{component_info['code']}\n\n"
        
    #     # Add parent classes if available
    #     if component_info['parent_classes']:
    #         code_context += "# Parent Classes\n"
    #         for parent in component_info['parent_classes']:
    #             code_context += f"Class: {parent['name']}\n"
    #             code_context += f"Source File: {parent['path']}\n"
    #             code_context += f"Code:\n{parent.get('code', 'Code not available')}\n\n"
        
    #     # Add model and data classes
    #     if component_info['data_classes']:
    #         code_context += "# Related Models\n"
    #         for model in component_info['data_classes']:
    #             code_context += f"Model: {model['name']}\n"
    #             code_context += f"Source File: {model['path']}\n"
    #             code_context += f"Code:\n{model['code']}\n\n"
        
    #     return code_context

    # def _get_generic_system_instructions(self, component_name: str) -> str:
    #     """Get the generic system instructions for component generation"""
    #     return f"""Forget all the instructions given before. You need to create openAPI definition for a customer-facing API which will be called by the customer by following the openAPI definition you provide.
    # Given below is a serializer {component_name} and the model associated with the serializer. Create the component section of Open API specs for serializer: {component_name} ONLY. 
    # You need to create two separate schemas for this serializer. One will be for request schema and one will be for response schema."""

    def _get_output_format_instructions(self, component_name: str) -> str:
        """Get the generic output format instructions"""
        return f"""
    # Output Format Requirements
    6. Use the name of serializer: {component_name} and append the string "Request" to it for the request schema. Request schema serializer's name: {component_name}Request.

    7. Use the name of serializer: {component_name} and append the string "Response" to it for the response schema. Response schema serializer's name: {component_name}Response. 

    8. Response schema should have exactly 3 mandatory sections: properties, type and required. properties section should contain the 'set' of fields for Response schema.

    9. Request schema should have two mandatory sections: properties and type. properties section should contain the 'set' of fields for Request schema. A 3rd section required should only be present if 'list' is non-empty. The required section should contain all the fields in 'list'. 

    10. If you $ref another serializer for any field then accordingly append the string "Request" or "Response" to the name of the serializer being $ref'd.

    11. The schema syntax for each schema should be such that there is the name of the schema and then the aforementioned sections.

    12. Every field in the property section of the schema should have exactly three mandatory sections: type, readOnly and writeOnly.

    13. For every property in schema, add readOnly and writeOnly to it. readOnly, writeOnly are properties that should be used within the definition of individual properties, not at the schema object level.

    14. Use all your knowledge about the rules of openAPI specifications 3.0, python DRF and your best analytical ability and quantitative aptitude.

    15. Both the schemas should be nested inside ONLY one "components" section. Start with 'components:' at the root level. Have a 'schemas:' key directly under components. Place all schema definitions under the schemas key.

    16. Clearly state ALL the properties of both the request and response schema even if they have the same properties."""

    def _get_quality_assurance_notes(self) -> str:
        """Get the generic quality assurance notes"""
        return """
    # Quality Assurance Notes
    Note: Keep in mind that request and response will have two different schemas and could have two different serializers in the code.
    Note: You need to use your own knowledge to get info about famous packages.
    Note: Make sure your output STRICTLY CONFORMS to openAPI specifications 3.0.
    Note: Give me complete, exhaustive, accurate response and request schemas. Do not under any circumstance omit any information or give incomplete information. I am doing very critical work. 
    Note: Do not give me incomplete information and ask me to fill it, give me complete spec with all the information for BOTH the request and response schemas. DO NOT BE LAZY, I am doing very critical work."""
    
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
            self.framework_analyzer.logger.debug("Formatting context for a multi-method (Jersey) endpoint.")
            handler_methods = endpoint_context["handler_methods"]
            formatted_string_parts.append("Handler Method Definitions:")
            for idx, handler in enumerate(handler_methods):
                formatted_string_parts.append(f"\n--- Handler Method {idx + 1} of {len(handler_methods)} ---")
                if handler.get('code'):
                    formatted_string_parts.append(f"Source File: {handler.get('path', 'N/A')}")
                    formatted_string_parts.append(f"Code Snippet ({handler.get('name')}):\n```java\n{handler['code']}\n```")
        elif "handler" in endpoint_context and endpoint_context["handler"]:
            self.framework_analyzer.logger.debug("Formatting context for a single-method (Django) endpoint.")
            handler = endpoint_context["handler"]
            formatted_string_parts.append(f"Source File: {handler.get('path', 'N/A')}")
            formatted_string_parts.append(f"Line Number: {handler.get('location', {}).get('start_line', 'N/A')}-{handler.get('location', {}).get('end_line', 'N/A')}")
            formatted_string_parts.append(f"Code Snippet:\n{handler.get('code', '# Handler code not available')}\n")
        else:
            self.framework_analyzer.logger.warning("No handler or handler_methods found in endpoint context.")
            formatted_string_parts.append("# Handler code not available.")

        handler_classes = endpoint_context.get("handler_classes", [])
        if handler_classes:
            formatted_string_parts.append(f"{delimiter}Handler Classes:")
            for item in handler_classes:
                # Use a generic header for all these additional classes
                item_name = item.get("qualifiedName") or item.get("name", "N/A")
                formatted_string_parts.append(f"{delimiter}Source File: {item.get('path', 'N/A')}")
                formatted_string_parts.append(f"Code Snippet (Class: {item_name}):\n```java\n{item.get('code', '# Code not available')}\n```")

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

        
        # if endpoint_context['endpoint']['url']['url'] ==  '/entities/{entityId}':
        #     import pdb; pdb.set_trace()
        # Case 2: Jersey Context with 'pojos'
        pojos = endpoint_context.get("pojos", [])
        processed_pojos = []
        if pojos:
            formatted_string_parts.append(f"{delimiter}Associated POJOs/DTOs:")
            for pojo in pojos:
                # if pojo['name'] == 'SzEntityResponse':
                #     import pdb; pdb.set_trace()
                name_key = "qualifiedName" if "qualifiedName" in pojo else "name"
                pojo_name = pojo.get(name_key, 'N/A')
                if pojo_name in processed_pojos:
                    continue
                formatted_string_parts.append(f"{delimiter}Source File: {pojo.get('path', 'N/A')}")
                formatted_string_parts.append(f"POJO: {pojo.get(name_key, 'N/A')}")
                formatted_string_parts.append(f"Code Snippet:\n```java\n{pojo.get('code', '# Code not available')}\n```")
                processed_pojos.append(pojo_name)
                data_classes = pojo.get('data_classes', [])
                parent_classes = pojo.get('parent_classes', [])
                
                for data_class in data_classes:
                    name_key = "qualifiedName" if "qualifiedName" in data_class else "name"
                    data_class_name=data_class.get(name_key, 'N/A')
                    if data_class_name in processed_pojos:
                        continue
                    formatted_string_parts.append(f"{delimiter}Source File: {data_class.get('path', 'N/A')}")
                    # Use a consistent header for all related classes
                    formatted_string_parts.append(f"POJO/DTO Dependency: {data_class.get(name_key, 'N/A')}")
                    formatted_string_parts.append(f"Code Snippet:\n```java\n{data_class.get('code', '# Code not available')}\n```")
                    processed_pojos.append(data_class_name)

                for parent_class in parent_classes:
                    name_key = "qualifiedName" if "qualifiedName" in parent_class else "name"
                    parent_name=parent_class.get(name_key, 'N/A')
                    if parent_name in processed_pojos:
                        continue
                    formatted_string_parts.append(f"{delimiter}Source File: {parent_class.get('path', 'N/A')}")
                    # Use a consistent header for all related classes
                    formatted_string_parts.append(f"POJO/DTO Dependency: {parent_class.get(name_key, 'N/A')}")
                    formatted_string_parts.append(f"Code Snippet:\n```java\n{parent_class.get('code', '# Code not available')}\n```")
                    processed_pojos.append(parent_name)

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
    
    def create_endpoint_request_prompt(self, endpoint: Dict[str, Any], endpoint_context: Dict[str, Any], available_schemas_map, skip_components: bool = False) -> str:
        """Generate prompt for endpoint request section documentation using optimized context."""

        # --- Extract common data from inputs ---
        url_details = endpoint.get("url", {})
        url = url_details.get("url", "N/A")
        method_lower = endpoint.get("method", "N/A").lower()

        # Determine 'fn_display_name' (target function/method name for prompt display)
        # This logic can be generalized or delegated to FrameworkAnalyzer if needed
        if self.framework_analyzer.framework_name == "Django":
            if endpoint.get("is_viewset"):
                fn_display_name = endpoint.get("function") 
                if not fn_display_name and method_lower == "get" and "{" not in url: fn_display_name = "list"
                elif not fn_display_name and method_lower == "get" and "{" in url: fn_display_name = "retrieve"
                elif not fn_display_name: fn_display_name = endpoint_context.get("handler", {}).get("name", "N/A")
            else:
                fn_display_name = endpoint_context.get("handler", {}).get("name", "N/A")
        elif self.framework_analyzer.framework_name.lower() in ["jersey", "spring"]:
            handler_ctx = endpoint_context.get("handler", {})
            handler_class_fqn = handler_ctx.get("class_name_fqn", "UnknownClass")
            handler_method_name = handler_ctx.get("name", "UnknownMethod")
            fn_display_name = f"{handler_class_fqn}.{handler_method_name}"
        else:
            fn_display_name = "N/A" # Fallback


        # --- Format the code context string ---
        code_context_str = self._format_endpoint_context_for_prompt(endpoint_context)

        available_components_text = self.get_available_components_message(available_schemas_map)
        # --- Determine if requestBody is likely needed ---
        # (GET/DELETE typically don't have requestBody, but allow if framework says otherwise)
        is_payload_method = method_lower not in ["get", "delete"]
        request_body_section_mention = ", requestBody subsection" if is_payload_method else ""
        # For Jersey, @FormParam implies requestBody, so this might need refinement if is_payload_method is too simple.
        # However, the detailed instructions from JerseyAnalyzer should guide the LLM correctly.


        # --- Assemble the prompt ---
        # 1. Common Preamble
        # The framework-specific system message is fetched and prepended by the LLMManager or here.
        # For now, let's assume the first line of the user prompt sets the scene.
        prompt = f""" You need to create openAPI definition for a customer-facing API which will be called by the customer by following the openAPI definition you provide.
Use only the following information and instructions to create ONLY the parameter subsection{request_body_section_mention} of the openAPI specs for the endpoint {fn_display_name} with http method {method_lower} and url {url}.
You will be given a context. The context consists of code snippets from the various source files in the code repository.
"""
        # 2. Add the formatted code context

        # 3. Add common output syntax hint
        prompt += f"""
The output open API specs should have the following syntax:
        ```yaml
        # YAML should start directly with parameters or requestBody
        # Example for POST:
        parameters:
          # ... path/query params ...
        requestBody:
          # ... request body definition ...

        # Example for GET:
        parameters:
          # ... path/query params ...
        ```
"""
        # 4. Add Framework-Specific Instructions
        # These instructions from the FrameworkAnalyzer will include details on path params, query params,
        # requestBody,, including embedding framework settings.
        framework_instructions = self.framework_analyzer.get_endpoint_request_instructions(endpoint, endpoint_context, skip_components=skip_components)
        prompt += f"\nSteps to create path section:\n{framework_instructions}\n"

        prompt += f"\n{available_components_text}\n"

        framework_common_rules = self.framework_analyzer.get_endpoint_common_instructions(skip_components=skip_components)
        if framework_common_rules: # Check if it's not an empty string
            prompt += f"\n{framework_common_rules}\n" # Add extra newline for separation

        # 6. Add Framework-Specific Notes
        framework_notes = self.framework_analyzer.get_endpoint_request_framework_specific_notes()
        if framework_notes:
            prompt += f"\n{framework_notes}\n"

        prompt += f"\nContext:\n{code_context_str}\n"  
        # 7. Add Final Common Note about output structure
        omit_request_body_note = "If this method does not require payload then omit the requestBody section. " if not is_payload_method else ""
        prompt += f"""
NOTE: Create ONLY the parameter subsection{request_body_section_mention} of the path section of openAPI specs for the endpoint {fn_display_name} with http method {method_lower} and url {url}. {omit_request_body_note}Your output should be ONLY the YAML content for these sections, starting directly with `parameters:` or `requestBody:`."""

        return prompt.strip()

    def create_endpoint_response_prompt(self, endpoint: Dict[str, Any], endpoint_context: Dict[str, Any], available_schemas_map, skip_components: bool = False) -> str:
        """Generate prompt for endpoint response documentation using optimized context."""

        # --- Extract common data from inputs ---
        url_details = endpoint.get("url", {})
        url = url_details.get("url", "N/A")
        method_lower = endpoint.get("method", "N/A").lower()
        available_components_text = self.get_available_components_message(available_schemas_map)
        # Determine 'fn_display_name' (target function/method name for prompt display)
        if self.framework_analyzer.framework_name == "Django":
            # ... (fn_display_name logic for Django) ...
            if endpoint.get("is_viewset"):
                fn_display_name = endpoint.get("function")
                if not fn_display_name and method_lower == "get" and "{" not in url: fn_display_name = "list"
                elif not fn_display_name and method_lower == "get" and "{" in url: fn_display_name = "retrieve"
                elif not fn_display_name: fn_display_name = endpoint_context.get("handler", {}).get("name", "N/A")
            else:
                fn_display_name = endpoint_context.get("handler", {}).get("name", "N/A")
        elif self.framework_analyzer.framework_name == "Jersey":
            # ... (fn_display_name logic for Jersey) ...
            handler_ctx = endpoint_context.get("handler", {})
            handler_class_fqn = handler_ctx.get("class_name_fqn", "UnknownClass")
            handler_method_name = handler_ctx.get("name", "UnknownMethod")
            fn_display_name = f"{handler_class_fqn}.{handler_method_name}"
        else:
            fn_display_name = "N/A"

        code_context_str = self._format_endpoint_context_for_prompt(endpoint_context)

        # --- Assemble the prompt ---
        # 1. Common Preamble
        prompt = f""" You need to create openAPI definition for a customer-facing API which will be called by the customer by following the openAPI definition you provide.
Use the following information and instructions to create ONLY the responses and summary subsections of the path section of openAPI spec for the endpoint {fn_display_name} with http method {method_lower} and url {url}.
You will be given a context. The context consists of code snippets from the various source files in the code repository.
"""

        # 3. Add common output syntax hint
        prompt += """\nThe output open API specs should have the following syntax:
        ```yaml
        # YAML should start directly with responses: or summary:
        # Example:
        summary: A brief description of the endpoint.
        responses:
          '200':
            content:
              application/json:
                schema:
                  # ... schema definition or $ref ...
          '400':
            # ... optional content ...
        ```
        """
        # 4. Add Framework-Specific Detailed Instructions
        # This now correctly calls the method on the specific framework analyzer
        framework_instructions = self.framework_analyzer.get_endpoint_response_instructions(endpoint, endpoint_context, skip_components=skip_components)
        prompt += f"\nInstructions:\n{framework_instructions}\n" # Changed from "Steps to create..." to "Instructions:" to match example

        # 5. Add Framework-Specific Common OpenAPI Rules
        framework_common_rules = self.framework_analyzer.get_endpoint_common_instructions(skip_components=skip_components)
        if framework_common_rules:
            prompt += f"\n{framework_common_rules}\n"

        # 6. Add Framework-Specific Notes for Response (NEW)
        framework_response_notes = self.framework_analyzer.get_endpoint_response_framework_specific_notes()
        if framework_response_notes:
            prompt += f"\n{framework_response_notes}\n"
        
        prompt += f"\n{available_components_text}\n"
        prompt += f"\nContext:\n{code_context_str}\n"
        # 7. Add Final Common Note about output structure
        prompt += f"""
NOTE: Create ONLY the responses and summary subsections of the path section of openAPI specs for the endpoint {fn_display_name} with http method {method_lower} and url {url}. Your output should be ONLY the YAML content for these sections, starting directly with `responses:` or `summary:`."""
        
        return prompt.strip()
    
    def _format_code_context(self, context_dict: Dict[str, str]) -> str:
        """Format the code context dictionary into a string format for the prompt"""
        formatted_context = ""
        for section_name, section_content in context_dict.items():
            formatted_context += f"=== {section_name} ===\n{section_content}\n\n"
        return formatted_context
    
    def get_component_system_message(self) -> str:
        """Get system message for component schema generation"""
        # Delegate to framework analyzer for appropriate framework-specific message
        return self.framework_analyzer.get_component_system_message()
    
    def create_retry_prompt(self,
                            original_prompt: str,
                            failed_content: str,
                            validation_errors: List[str],
                            entity_type: str = "section" # e.g., "component schema", "request section", "response section"
                           ) -> str:
        """
                Creates a prompt asking the LLM to correct its previous output based on validation errors.

                Args:
                    original_prompt: The initial prompt that led to the failed output.
                    failed_content: The raw output from the LLM that failed validation.
                    validation_errors: A list of error messages from the validator.
                    entity_type: A string describing what was being generated (for context).

                Returns:
                    A new prompt string incorporating the feedback.
        """
        error_string = "\n - ".join(validation_errors)

        retry_prompt = f"""Your previous attempt to generate the {entity_type} based on the original instructions resulted in the following output:

        ```yaml
        {failed_content}

            

        IGNORE_WHEN_COPYING_START
        Use code with caution.Python
        IGNORE_WHEN_COPYING_END

        This output failed validation with the following errors:

            {error_string}

        Please carefully review the original instructions (provided below) and the errors identified. Generate a corrected version of the {entity_type} that addresses these specific errors and fully adheres to the original request and OpenAPI 3.0 specifications. Output ONLY the corrected YAML content, properly formatted within ```yaml code blocks.

        --- ORIGINAL INSTRUCTIONS ---

        {original_prompt}
        """
        return retry_prompt
    
    def _get_common_missing_symbols_role_and_goal(self) -> str:
        return f"""You are an expert in {self.framework_analyzer.framework_name.upper()} and analyzing code for API documentation.
Your task is to analyze the provided initial code context for a specific API endpoint.
The goal is to identify **all additional custom classes and functions/static methods**
from the project whose full code definitions are helpful or necessary to fully understand
the request structure (parameters, requestBody fields, validation) and the response
structure (response body fields, status codes) for *this specific endpoint method*.
"""

    def _get_common_missing_symbols_output_format(self) -> str:
        name_field_example = ("The **Fully Qualified Name** of the class (e.g., \"com.example.MyCustomType\") "
                              "or static method (e.g., \"com.example.MyUtil.helperMethod\"). "
                              "If only a simple name was used in an import, provide that simple name."
                              if self.framework_analyzer.framework_name.lower() == "jersey" else
                              "The exact name of the class or function as referenced in the code "
                              "(e.g., \"IsAdminOrReadOnlyCustom\", \"calculate_discount\", \"validators.is_profane\").")
        
        context_path_file_ext = ".java" if self.framework_analyzer.framework_name.lower() in ["jersey", "spring"] else ".py"

        return f"""
Output Format:
Return your answer ONLY as a JSON object with a single key "missing_symbols".
The value should be a list of objects. Each object represents one required symbol.
- "name": {name_field_example}
- "type": Either "class" or "function" (for static utility methods or Python functions).
- "context_path": CRITICAL: The absolute path of the {context_path_file_ext} source file WHERE THE SYMBOL WAS REFERENCED (i.e., the file *using* the symbol). Use the exact path provided in the context headers (e.g., the 'Path:' line for the handler or POJO/Serializer).

Example JSON Output (format is the same, content differs by framework):
```json
{{
  "missing_symbols": [
    {{
      "name": "com.example.dtos.DetailedAddressDTO", // or myapp.utils.DetailedAddress
      "type": "class",
      "context_path": "/app/src/main/java/com/example/resources/UserResource.java" // or /app/myapp/views.py
    }}
  ]
}}

If no additional code definitions are strictly necessary based on the provided context, return an empty list:
{{ "missing_symbols": [] }}
Do not include any explanations or text outside the JSON object.
"""

          
    def create_missing_symbols_prompt(self, endpoint: Dict[str, Any], endpoint_context: Dict[str, Any]) -> str:
            role_and_goal = self._get_common_missing_symbols_role_and_goal()
            output_format = self._get_common_missing_symbols_output_format()
            
            # FrameworkAnalyzer now constructs the complete preamble and code context string
            initial_context_with_preamble = self.framework_analyzer.get_initial_context_presentation_for_missing_symbols(endpoint, endpoint_context)
            
            framework_specific_focus_guidance = self.framework_analyzer.get_framework_specific_guidance_for_missing_symbols()
            framework_specific_exclusion_instructions = self.framework_analyzer.get_framework_specific_exclusion_instructions_for_missing_symbols()

            # The Instruction section. The endpoint is already introduced in initial_context_with_preamble.
            instruction_part = f"""Instruction:
            Based on the API endpoint and code context presented above, your goal is to identify all additional custom classes and functions/static methods from the project whose full code definitions are helpful or necessary to fully understand the request structure (parameters, requestBody fields, validation) and the response structure (response body fields, status codes) for this specific endpoint method.
            {framework_specific_focus_guidance}"""
            full_prompt = f"""{role_and_goal}
            {initial_context_with_preamble}
            {instruction_part}
            {framework_specific_exclusion_instructions}
            {output_format}
            """

                
            return full_prompt.strip()


    