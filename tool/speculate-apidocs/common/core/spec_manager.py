# interfaces/spec_manager.py
from abc import ABC, abstractmethod
import os
import re
import yaml
import logging
from typing import Dict, List, Set, Optional, Any, Tuple, NamedTuple
import copy # Import copy

# --- SpecsWalker Class (Adapted from fix_specs.py) ---
class SpecsWalker:
    def __init__(self, yaml_data, logger, relax_object_validation_at_depth: bool = False):
        # Deep copy to avoid modifying the original object passed to the constructor
        # during the fix process, allowing comparison or retry if needed.
        self.yaml = copy.deepcopy(yaml_data)
        self.path_field_map = { # Mapping HTTP methods to their handler functions
            "get": self.get,
            "put": self.put,
            "post": self.post,
            "delete": self.delete,
            "patch": self.patch
        }
        self.errors = [] 
        self.is_valid = True # Flag indicating if the spec is structurally valid
        self.logger = logger # Use the passed logger
        self.relax_object_validation_at_depth = relax_object_validation_at_depth
        self.object_validation_depth_threshold = 3
        
    def _add_error(self, message: str, error_obj: Any, parent_context: Optional[Any] = None):
        """
        Adds a structured error, preferring the stored parent for context.
        """
        # Use the stored parent for a better snippet if available, otherwise use direct context.
        context_to_dump = parent_context if parent_context is not None else error_obj

        try:
            context_str = yaml.dump(context_to_dump, indent=2, sort_keys=False, allow_unicode=True, width=120)
            lines = context_str.splitlines()
            if len(lines) > 20: # Limit the snippet size for readability
                 context_str = '\n'.join(lines[:20]) + "\n..."
        except Exception:
            context_str = str(context_to_dump)

        error_entry = {'message': message, 'context': context_str}
        if error_entry not in self.errors:
            self.errors.append(error_entry)
        
    def schemas(self, components_obj: Dict, parent_context: Optional[Any] = None):
        if 'schemas' not in components_obj or not isinstance(components_obj['schemas'], dict):
             # If 'schemas' key is missing or not a dict, nothing to process
             # self.logger.debug("No valid 'schemas' dictionary found in components.")
             return
        schemas_dict = components_obj['schemas']
        components_to_delete = [] # Collect keys to delete safely
        for component_name, component_data in schemas_dict.items():
            if not isinstance(component_data, dict):
                 self.logger.warning(f"Schema definition for '{component_name}' is not a dictionary. Skipping.")
                 continue # Skip invalid schema definitions

            # Remove top-level readOnly/writeOnly from schema definition itself
            if "readOnly" in component_data:
                self.logger.debug(f"Validation fix: Removing top-level 'readOnly' from schema '{component_name}'.")
                del component_data["readOnly"]
            if "writeOnly" in component_data:
                self.logger.debug(f"Validation fix: Removing top-level 'writeOnly' from schema '{component_name}'.")
                del component_data["writeOnly"]

            # Check properties: remove schema if properties are invalid or empty
            properties = component_data.get("properties")
            if "properties" in component_data and (not isinstance(properties, dict) or not properties):
                self.logger.warning(f"Schema '{component_name}' has invalid or empty 'properties'. Marking for deletion.")
                #components_to_delete.append(component_name)
                self.is_valid = False # Invalid structure if properties is wrong type
                self._add_error(f"Schema '{component_name}' has invalid or empty 'properties'.", component_data, parent_context=schemas_dict)
                continue

            # Process 'required' list
            self.required(component_data) # Handles validation and checks against properties

            # Process 'type', which often implies 'object' for schemas
            if "type" in component_data:
                # Usually schemas are objects, validate/fix nested types
                if component_data["type"] == "object":
                     self.object(component_data)
                else:
                     # It's unusual for a top-level schema to not be 'object', but validate its type
                     self.type_parser(component_data)
            elif "properties" in component_data:
                 # If type is missing but properties exist, assume object and process
                 self.logger.debug(f"Schema '{component_name}' missing 'type', assuming 'object' due to 'properties'.")
                 self.object(component_data)


        # Delete marked components after iteration
        for name in components_to_delete:
            del schemas_dict[name]

    # --- Robust Required Method ---
    def required(self, parent):
        if 'required' not in parent: return # Skip if not present

        required_value = parent['required']
        if not isinstance(required_value, list):
            self.logger.warning(f"Validation fix: 'required' is not a list ({type(required_value)}), removing.")
            self._add_error("'required' field must be a list.", parent)
            self.is_valid = False # Required MUST be a list
            del parent['required']
            return

        if not required_value: # Empty list
            self.logger.debug("Validation fix: 'required' list is empty, removing.")
            del parent['required']
            return

        # Filter for valid types (should be strings) and fix bools as strings
        final_required = []
        has_changes = False
        for item in required_value:
            if isinstance(item, str):
                item_str_lower = item.lower()
                if item_str_lower in ["true", "false"]:
                     # OpenAPI spec requires field names, not booleans here. This is likely an error.
                     self.logger.warning(f"Validation Error: Found boolean-like string '{item}' in 'required' list. Removing.")
                     self._add_error(f"Invalid item '{item}' found in 'required' list.", parent)
                     self.is_valid = False
                     has_changes = True
                else:
                     final_required.append(item) # Keep valid string
            elif isinstance(item, (int, float, bool)): # Also invalid
                 self.logger.warning(f"Validation Error: Found non-string item '{item}' ({type(item)}) in 'required' list. Removing.")
                 self._add_error(f"Invalid non-string item '{item}' ({type(item)}) found in 'required' list.", parent)
                 self.is_valid = False
                 has_changes = True
            # else: Allow other types? No, spec says strings.

        # Ensure required fields exist in properties if properties exist
        properties = parent.get("properties")
        if isinstance(properties, dict):
            filtered_required = [field for field in final_required if field in properties]
            if len(filtered_required) != len(final_required):
                 removed = set(final_required) - set(filtered_required)
                 self.logger.warning(f"Validation fix: Removing fields from 'required' not found in 'properties': {removed}")
                 has_changes = True
            final_required = filtered_required

        # Update or remove the 'required' list
        if final_required:
            parent['required'] = final_required
        elif 'required' in parent: # Remove if it became empty
             self.logger.debug("Validation fix: 'required' list became empty after filtering, removing.")
             del parent['required']


    def fix(self):
        """Main entry point for validation/fixing the loaded YAML object."""
        if not isinstance(self.yaml, dict):
             self.logger.error("Validation Error: Root YAML structure is not a dictionary.")
             self._add_error("Root YAML structure must be a dictionary.", self.yaml)
             self.is_valid = False
             return self.is_valid, self.errors

        # Process top-level sections if they exist
        if "paths" in self.yaml and isinstance(self.yaml['paths'], dict):
            self.paths(self.yaml)
        elif "paths" in self.yaml:
             self.logger.warning("Validation Error: 'paths' section is not a dictionary.")
             self._add_error("'paths' section must be a dictionary.", self.yaml)
             self.is_valid = False


        if "components" in self.yaml and isinstance(self.yaml['components'], dict):
            self.components(self.yaml)
        elif "components" in self.yaml:
             self.logger.warning("Validation Error: 'components' section is not a dictionary.")
             self._add_error("'components' section must be a dictionary.", self.yaml)
             self.is_valid = False

        return self.is_valid, self.errors

    # --- Components Method (Simplified, calls schemas/securitySchemes) ---
    def components(self, parent):
        # Assumes parent['components'] is already verified as dict by fix()
        if "schemas" in parent["components"]:
            if isinstance(parent["components"]["schemas"], dict):
                 self.schemas(parent["components"])
            elif parent["components"]["schemas"] is not None:
                 self.logger.warning("Validation Error: 'components.schemas' is not a dictionary.")
                 self._add_error("'components.schemas' is not a dictionary.", parent["components"])
                 self.is_valid = False

        if "securitySchemes" in parent["components"]:
            if isinstance(parent["components"]["securitySchemes"], dict):
                 self.securitySchemes(parent["components"])
            elif parent["components"]["securitySchemes"] is not None:
                 self.logger.warning("Validation Error: 'components.securitySchemes' is not a dictionary.")
                 self._add_error("'components.securitySchemes' is not a dictionary.", parent["components"])
                 self.is_valid = False

    # --- Security Schemes Method ---
    def securitySchemes(self, parent):
        # Assumes parent['securitySchemes'] is dict
        schemes_to_delete = []
        for scheme_name, scheme_data in parent["securitySchemes"].items():
            if not isinstance(scheme_data, dict):
                 self.logger.warning(f"Security scheme '{scheme_name}' definition is not a dictionary. Removing.")
                 schemes_to_delete.append(scheme_name)
                 self.is_valid = False; 
                 self._add_error(f"Invalid definition for security scheme '{scheme_name}'.", scheme_data)
                 continue

            # Remove invalid 'example' field (OpenAPI spec doesn't define it here)
            if "example" in scheme_data:
                self.logger.debug(f"Validation fix: Removing 'example' from security scheme '{scheme_name}'.")
                del scheme_data["example"]

            # Validate 'in' field if present (required for apiKey)
            scheme_type = scheme_data.get('type')
            scheme_in = scheme_data.get('in')
            if scheme_type == 'apiKey':
                if not scheme_in:
                     self.logger.warning(f"Validation Error: 'in' field missing for apiKey security scheme '{scheme_name}'.")
                     self._add_error(f"'in' field required for apiKey scheme '{scheme_name}'.", scheme_data)
                     self.is_valid = False
                elif scheme_in not in ["header", "query", "cookie"]:
                    self.logger.warning(f"Validation Error: Invalid 'in' value '{scheme_in}' for apiKey scheme '{scheme_name}'.")
                    self._add_error(f"Invalid 'in' value '{scheme_in}' for apiKey scheme '{scheme_name}'. Must be header, query, or cookie.", scheme_data)
                    self.is_valid = False
            # Add validation for other scheme types (http, oauth2, openIdConnect) if needed

        for name in schemes_to_delete:
            del parent["securitySchemes"][name]

    # --- Paths Method ---
    def paths(self, parent):
        # Assumes parent['paths'] is dict
        path_pattern = r"\{(.+?)\}" # Extracts param names like {id} -> id
        paths_to_delete = []

        for path_url, path_data in parent["paths"].items():
            if not isinstance(path_data, dict):
                 self.logger.warning(f"Path item definition for '{path_url}' is not a dictionary. Removing.")
                 paths_to_delete.append(path_url)
                 self._add_error(f"Invalid definition for path '{path_url}'.", path_data)
                 continue

            methods_to_delete = []
            methods_to_add = {} # Store {lower_case: original_data} for fixing case

            # Extract path parameter names defined in the URL string itself
            expected_path_params = set(re.findall(path_pattern, path_url))

            for method_name, method_data in path_data.items():
                lower_method = method_name.lower()

                # Check if method name is valid
                valid_methods = ["get", "post", "patch", "delete", "put", "options", "head", "trace"]
                if lower_method not in valid_methods:
                    self._add_error(f"Invalid HTTP method '{method_name}' found in path '{path_url}'.", path_data)
                    self.logger.warning(f"Validation Error: Invalid HTTP method '{method_name}' in path '{path_url}'.")
                    self.is_valid = False
                    # Decide: remove invalid method or try to proceed? Let's remove.
                    methods_to_delete.append(method_name)
                    continue

                # Fix casing if needed (store data under lower_method later)
                if method_name != lower_method:
                     self.logger.debug(f"Validation fix: Correcting method case from '{method_name}' to '{lower_method}' in path '{path_url}'.")
                     if lower_method in path_data: # If lowercase version already exists (duplicate)
                          self._add_error(f"Duplicate HTTP method '{lower_method}' (case-insensitive) found in path '{path_url}'.", path_data)
                          self.logger.warning(f"Validation Error: Duplicate method '{lower_method}' in path '{path_url}'. Keeping first encountered.")
                          # Keep the one already there, mark this one for deletion
                          methods_to_delete.append(method_name)
                     else:
                          methods_to_add[lower_method] = method_data
                          methods_to_delete.append(method_name) # Mark original case for deletion
                     continue # Skip processing original case further

                # Validate method_data structure
                if not isinstance(method_data, dict):
                     self.logger.warning(f"Operation definition for '{lower_method.upper()} {path_url}' is not a dictionary. Removing.")
                     methods_to_delete.append(method_name)
                     self.is_valid = False; 
                     self._add_error(f"Invalid operation definition for '{lower_method.upper()} {path_url}'.", method_data)
                     continue

                # Apply method-specific validation/fixing via dispatcher
                if lower_method in self.path_field_map:
                     fixer = self.path_field_map[lower_method]
                     fixer(path_data, expected_path_params) # Pass path_data (parent dict) and expected params
                else:
                     # Handle OPTIONS, HEAD, TRACE if specific rules apply, otherwise just check structure
                     if "parameters" in method_data: self.parameters(method_data, expected_path_params)
                     if "responses" in method_data: self.responses(method_data)

            # Apply deletions and additions for the current path_data
            for method_to_delete in methods_to_delete:
                if method_to_delete in path_data: del path_data[method_to_delete]
            path_data.update(methods_to_add)

            # If a path item becomes empty after cleaning methods, mark it for deletion
            if not path_data:
                 paths_to_delete.append(path_url)


        # Delete marked paths after iteration
        for path_to_delete in paths_to_delete:
            del parent['paths'][path_to_delete]

    # --- Parameters Method ---
    def parameters(self, parent_operation, expected_path_params):
        # Validates/fixes the 'parameters' list within a path operation (parent_operation)
        if 'parameters' not in parent_operation or not isinstance(parent_operation['parameters'], list):
            if 'parameters' in parent_operation: # If it exists but isn't a list
                 self.logger.warning(f"Validation Error: 'parameters' is not a list in operation. Removing.")
                 self._add_error("'parameters' must be a list.", parent_operation)
                 self.is_valid = False
                 del parent_operation['parameters']
            return # Nothing to process or invalid structure

        valid_parameters = []
        seen_param_keys = set() # Track (name, in) pairs to detect duplicates

        for parameter in parent_operation['parameters']:
            if not isinstance(parameter, dict):
                 self.logger.warning(f"Validation Error: Item in 'parameters' list is not a dictionary: {parameter}. Skipping.")
                 self.is_valid = False; 
                 self._add_error("Invalid item found in 'parameters' list (must be a dictionary).", parameter)
                 continue

            param_in = parameter.get('in')
            param_name = parameter.get('name')

            # Basic structure checks
            if not param_in or not param_name:
                 self.logger.warning(f"Validation Error: Parameter missing 'in' or 'name': {parameter}. Skipping.")
                 self.is_valid = False;
                 self._add_error("Parameter definition requires 'in' and 'name'.", parameter)
                 continue

            valid_in_values = ["path", "query", "header", "cookie"]
            if param_in not in valid_in_values:
                 self.logger.warning(f"Validation Error: Invalid 'in' value '{param_in}' for parameter '{param_name}'. Skipping.")
                 self.is_valid = False; 
                 self._add_error(f"Invalid 'in' value '{param_in}' for parameter '{param_name}'.", parameter)
                 continue

            # Path parameter validation
            if param_in == 'path':
                 # Path params MUST be required
                 if parameter.get('required') is not True:
                     self.logger.debug(f"Validation fix: Setting 'required: true' for path parameter '{param_name}'.")
                     parameter['required'] = True
                 # Check if path parameter name actually exists in the path URL template
                 if param_name not in expected_path_params:
                     self.logger.warning(f"Validation Error: Path parameter '{param_name}' defined but not found in URL template. Skipping.")
                     self.is_valid = False; 
                     self._add_error(f"Path parameter '{param_name}' defined but not found in URL.", parameter)
                     continue
            # Query/Header/Cookie: Ensure 'required' is boolean if present
            elif 'required' in parameter and not isinstance(parameter.get('required'), bool):
                 self.logger.warning(f"Validation fix: 'required' for {param_in} parameter '{param_name}' is not boolean. Removing.")
                 del parameter['required']

            # Check for duplicate (name, in) pairs
            param_key = (param_name, param_in)
            if param_key in seen_param_keys:
                 self.logger.warning(f"Validation Error: Duplicate parameter definition for ('{param_name}', '{param_in}'). Skipping duplicate.")
                 self.is_valid = False;
                 self._add_error(f"Duplicate parameter ('{param_name}', '{param_in}').", parameter)
                 continue
            seen_param_keys.add(param_key)

            # Validate nested schema if present
            if 'schema' in parameter:
                self.schema(parameter, depth=1) # schema() handles nested validation

            # If all checks pass, add to the list of valid parameters
            valid_parameters.append(parameter)

        # Replace original list with the validated/filtered one
        if not valid_parameters:
             del parent_operation['parameters'] # Remove if empty
        else:
             parent_operation['parameters'] = valid_parameters


    # --- GET Method ---
    def get(self, parent_path_item, expected_path_params):
        method_op = parent_path_item.get('get')
        if not isinstance(method_op, dict): return # Already handled by paths()

        # Rule: GET operations must not have a requestBody
        if "requestBody" in method_op:
            self.logger.warning("Validation fix: Removing 'requestBody' from GET operation.")
            del method_op["requestBody"]

        if "parameters" in method_op:
            self.parameters(method_op, expected_path_params)
        if "responses" in method_op:
            self.responses(method_op)

    # --- PATCH Method ---
    def patch(self, parent_path_item, expected_path_params):
        method_op = parent_path_item.get('patch')
        if not isinstance(method_op, dict): return

        if "requestBody" in method_op:
            self.requestBody(method_op)
        if "parameters" in method_op: # Check in method_op now
            self.parameters(method_op, expected_path_params)
        if "responses" in method_op:
            self.responses(method_op)

    # --- POST Method ---
    def post(self, parent_path_item, expected_path_params):
        method_op = parent_path_item.get('post')
        if not isinstance(method_op, dict): return

        if "requestBody" in method_op:
            self.requestBody(method_op)
        if "parameters" in method_op:
            self.logger.debug("Modification: Removing 'parameters' section from POST endpoint as requested.")
            del method_op["parameters"]
        if "responses" in method_op:
            self.responses(method_op)

    # --- PUT Method ---
    def put(self, parent_path_item, expected_path_params):
        method_op = parent_path_item.get('put')
        if not isinstance(method_op, dict): return

        if "requestBody" in method_op:
            self.requestBody(method_op)
        if "parameters" in method_op:
            self.parameters(method_op, expected_path_params)
        if "responses" in method_op:
            self.responses(method_op)

    # --- DELETE Method ---
    def delete(self, parent_path_item, expected_path_params):
        method_op = parent_path_item.get('delete')
        if not isinstance(method_op, dict): return

        # Rule: DELETE operations should generally not have a requestBody (though allowed by spec, often unused)
        # Let's keep it less strict than GET, but maybe log a warning if present?
        # if "requestBody" in method_op:
        #     self.logger.debug("Validation Note: 'requestBody' found in DELETE operation (allowed but potentially unusual).")

        if "parameters" in method_op:
            self.parameters(method_op, expected_path_params)
        if "responses" in method_op:
            self.responses(method_op)

    # --- Request Body Method ---
    def requestBody(self, parent_operation):
        if 'requestBody' not in parent_operation or not isinstance(parent_operation['requestBody'], dict):
             if 'requestBody' in parent_operation: # Exists but wrong type
                  self.logger.warning("Validation Error: 'requestBody' is not a dictionary. Removing.")
                  self._add_error("'requestBody' must be a dictionary.", parent_operation)
                  self.is_valid = False
                  del parent_operation['requestBody']
             return

        rb_data = parent_operation['requestBody']

        # Remove if empty (valid YAML might load empty string as {})
        if not rb_data:
             self.logger.debug("Validation fix: 'requestBody' is empty, removing.")
             del parent_operation['requestBody']
             return

        # Validate 'required' field within requestBody object
        if 'required' in rb_data and not isinstance(rb_data['required'], bool):
             self.logger.warning("Validation fix: 'requestBody.required' is not boolean. Removing.")
             # Let's remove it rather than guess, as default is false
             del rb_data['required']

        # Validate 'content' field
        if 'content' in rb_data:
             self.content(rb_data) # content() handles validation
             # If content became empty after validation, remove requestBody?
             if 'content' in rb_data and not rb_data['content']:
                  self.logger.debug("Validation fix: 'requestBody.content' became empty after validation, removing 'requestBody'.")
                  del parent_operation['requestBody']
        elif rb_data: # Request body exists but has no content - invalid
            self.logger.warning("Validation Error: 'requestBody' exists but lacks 'content' field. Removing.")
            self._add_error("'requestBody' must have a 'content' field.", rb_data)
            self.is_valid = False
            del parent_operation['requestBody']


    # --- Responses Method ---
    def responses(self, parent_operation, depth: int = 0):
        if 'responses' not in parent_operation or not isinstance(parent_operation['responses'], dict):
             if 'responses' in parent_operation:
                  self.logger.warning("Validation Error: 'responses' is not a dictionary. Removing.")
                  self._add_error("'responses' must be a dictionary.", parent_operation)
                  self.is_valid = False
                  del parent_operation['responses']
             return

        responses_data = parent_operation['responses']
        if not responses_data: # Empty responses dict
             # OpenAPI requires at least one response. Add a default? Or flag error?
             self.logger.warning("Validation Error: 'responses' dictionary is empty.")
             self._add_error("'responses' must contain at least one response definition.", parent_operation)
             self.is_valid = False
             # Let's not remove it, just flag error. User might add manually.
             return

        codes_to_delete = []
        codes_to_add = {} # Store {'str_code': data}

        for status_code, response_data in responses_data.items():
             str_status_code = str(status_code) # Ensure string key

             # Validate status code format ('default' or HTTP code)
             if str_status_code != 'default' and not re.fullmatch(r"[1-5](?:[0-9]{2}|XX)", str_status_code):
                  self.logger.warning(f"Validation Error: Invalid status code '{status_code}' in responses. Removing.")
                  self._add_error(f"Invalid status code '{status_code}' in responses.", responses_data)
                  self.is_valid = False
                  codes_to_delete.append(status_code)
                  continue

             # Fix non-string keys
             if status_code != str_status_code:
                  self.logger.debug(f"Validation fix: Converting status code key '{status_code}' to string '{str_status_code}'.")
                  if str_status_code in responses_data: # Check for conflict after conversion
                       self.logger.warning(f"Validation Error: Duplicate status code '{str_status_code}' (case-insensitive or type) found in responses. Keeping first.")
                       self._add_error(f"Duplicate status code '{str_status_code}'.", responses_data)
                       self.is_valid = False
                       # Keep existing str_status_code, mark original for deletion
                       codes_to_delete.append(status_code)
                  else:
                       codes_to_add[str_status_code] = response_data
                       codes_to_delete.append(status_code)
                  continue # Skip processing original key

             # Validate response_data structure
             if not isinstance(response_data, dict):
                  self.logger.warning(f"Validation Error: Response definition for status code '{str_status_code}' is not a dictionary. Removing.")
                  self._add_error(f"Invalid response definition for status code '{str_status_code}'.", response_data)
                  self.is_valid = False
                  codes_to_delete.append(status_code)
                  continue

             # Response object MUST have a 'description'
             if 'description' not in response_data or not isinstance(response_data['description'], str) or not response_data['description'].strip():
                 self.logger.warning(f"Validation Error/Fix: Response '{str_status_code}' missing or invalid 'description'. Adding placeholder.")
                 self._add_error(f"Response '{str_status_code}' requires a non-empty string 'description'.", response_data)
                 response_data['description'] = "Description not provided." # Add placeholder
                 # Don't mark as invalid for this fix, just warn/log.

             # Validate 'content' if present
             if 'content' in response_data:
                 self.content(response_data, depth=depth)
                 # If content became empty after validation, remove it
                 if 'content' in response_data and not response_data['content']:
                      self.logger.debug(f"Validation fix: 'content' for response '{str_status_code}' became empty after validation. Removing.")
                      del response_data['content']

             # Add validation for 'headers', 'links' if needed

        # Apply deletions and additions for responses_data
        for code_to_delete in codes_to_delete:
            if code_to_delete in responses_data: del responses_data[code_to_delete]
        responses_data.update(codes_to_add)

        # Check again if responses became empty after cleaning
        if not responses_data:
             self.logger.warning("Validation Error: 'responses' dictionary became empty after cleaning invalid entries.")
             self._add_error("'responses' must contain at least one valid response definition.", parent_operation)
             self.is_valid = False


    # --- Content Method ---
    def content(self, parent_with_content, depth: int = 0):
        # Validates the 'content' map (e.g., within requestBody or response)
        if 'content' not in parent_with_content or not isinstance(parent_with_content['content'], dict):
            if 'content' in parent_with_content: # Exists but wrong type
                 self.logger.warning("Validation Error: 'content' field is not a dictionary. Removing.")
                 self._add_error("'content' must be a dictionary mapping media types to media type objects.", parent_with_content)
                 self.is_valid = False
                 del parent_with_content['content']
            return

        content_data = parent_with_content['content']
        if not content_data: # Empty content dict is valid (means no body described)
            self.logger.debug("Validation Note: 'content' dictionary is empty.")
            return

        media_types_to_delete = []
        for media_type, media_type_obj in content_data.items():
            if not isinstance(media_type_obj, dict):
                 self.logger.warning(f"Validation Error: Definition for media type '{media_type}' is not a dictionary. Removing.")
                 self._add_error(f"Invalid definition for media type '{media_type}'.", media_type_obj)
                 self.is_valid = False
                 media_types_to_delete.append(media_type)
                 continue

            # Validate 'schema' within the media type object
            if 'schema' in media_type_obj:
                self.schema(media_type_obj, depth=depth) # schema() handles validation
                # If schema became invalid/empty during its validation? schema() doesn't explicitly signal this. Assume schema() fixes or leaves it.
            # else: Schema is optional

            # Add validation for 'example', 'examples', 'encoding' if needed

        for mt_to_delete in media_types_to_delete:
            del content_data[mt_to_delete]

        # If content dict becomes empty after cleaning, remove it
        if not content_data:
             self.logger.debug("Validation fix: 'content' dictionary became empty after cleaning. Removing.")
             del parent_with_content['content']


    # --- Schema Method ---
    def schema(self, parent_with_schema, depth: int = 0):
        # Validates the 'schema' object within content, parameters, etc.
        if 'schema' not in parent_with_schema or not isinstance(parent_with_schema['schema'], dict):
             if 'schema' in parent_with_schema:
                 self.logger.warning("Validation Error: 'schema' field is not a dictionary. Removing.")
                 self._add_error("'schema' field must be a dictionary.", parent_with_schema)
                 self.is_valid = False
                 del parent_with_schema['schema']
             return

        schema_data = parent_with_schema['schema']
        if not schema_data: # Empty schema object is valid
             self.logger.debug("Validation Note: 'schema' dictionary is empty.")
             return

        # Schema object can be just a $ref, or have 'type', etc.
        if '$ref' in schema_data:
             # Basic check if $ref value is a string
             if not isinstance(schema_data['$ref'], str):
                  self.logger.warning("Validation Error: '$ref' value is not a string. Removing schema.")
                  self._add_error("'$ref' value must be a string.", schema_data)
                  self.is_valid = False
                  del parent_with_schema['schema']
             # Deeper $ref validation happens later in sanitize_and_validate_content
             return # If $ref exists, other keywords are ignored by spec rules

        # If not a $ref, it should usually have a 'type'
        if 'type' in schema_data:
            self.type_parser(schema_data, depth=depth + 1) # type_parser handles validation
        elif schema_data: # Exists, not $ref, but no type - this is usually invalid unless specific keywords like 'oneOf', 'allOf', 'anyOf', 'not' are used.
             # Add checks for composition keywords if needed. For now, warn if basic type is missing without composition.
             is_composition = any(k in schema_data for k in ['oneOf', 'allOf', 'anyOf', 'not'])
             if not is_composition:
                  self.logger.warning("Validation Warning: 'schema' object lacks '$ref' and 'type', and no composition keywords found. Structure might be invalid.")
                  # self.errors.add("Schema object should have '$ref', 'type', or composition keywords.")
                  # self.is_valid = False # Be stricter?
                  # Let's allow it for now but warn.


    # --- Type Parser Method ---
    def type_parser(self, current_schema, depth: int = 0, parent_context: Optional[Any] = None):
        # Validates schema object based on its 'type'
        if not isinstance(current_schema, dict):
            self.logger.warning("Validation Error: Expected dictionary for type parsing, got %s. Skipping.", type(current_schema))
            self._add_error("Invalid structure passed for type parsing (expected dictionary).", current_schema)
            self.is_valid = False
            return

        # Remove 'required' if it exists at this level (should be higher up in parent object)
        if "required" in current_schema:
            self.logger.debug("Validation fix: Removing 'required' found inside a type definition.")
            del current_schema["required"]

        # Handle 'enum'
        if "enum" in current_schema:
            self.enum(current_schema) # Handles validation/fixing within

        # Check 'type' validity before recursing
        current_type = current_schema.get("type")
        # OpenAPI valid types
        valid_types = ["array", "boolean", "integer", "number", "object", "string"]

        if current_type not in valid_types:
            self._add_error(f"Invalid 'type' field value: {current_type}", current_schema)
            self.logger.warning(f"Validation Error: Invalid 'type' field value: {current_type}")
            self.is_valid = False
            return # Stop processing this schema if type is fundamentally wrong

        # Recurse based on valid type
        if current_type == "array":
            self.array(current_schema, depth=depth)
        elif current_type == "object":
            self.object(current_schema, depth=depth)
        # No recursion needed for primitive types (boolean, integer, number, string)


    # --- Object Method ---
    def object(self, current_schema, depth: int = 0):
        # Validates schema object where type is 'object'
        if not isinstance(current_schema, dict): return # Safety

        # Validate 'additionalProperties' - can be boolean or schema object
        if "additionalProperties" in current_schema:
            ap_value = current_schema["additionalProperties"]
            if isinstance(ap_value, bool):
                # We are explicitly disallowing `additionalProperties: true` as it's a sign of LLM laziness.
                if ap_value is True:
                    self.logger.warning("Validation Error: 'additionalProperties: true' is disallowed. A concrete schema is required.")
                    self._add_error("'additionalProperties' cannot be `true`; a specific schema must be defined.", current_schema)
                    self.is_valid = False
                    del current_schema["additionalProperties"]
                # `additionalProperties: false` is acceptable.
            
            elif isinstance(ap_value, dict):
                # An empty schema for additionalProperties is also a sign of laziness.
                if not ap_value:
                    self.logger.warning("Validation Error: 'additionalProperties' schema cannot be an empty object.")
                    self._add_error("'additionalProperties' schema must not be empty.", current_schema)
                    self.is_valid = False
                    del current_schema["additionalProperties"]
                else:
                    # Recursively validate the nested schema.
                    self.type_parser(ap_value, depth=depth + 1, parent_context=current_schema)
            
            else: # Not a bool or dict, so invalid.
                self.logger.warning(f"Validation Error: 'additionalProperties' has invalid type ({type(ap_value)}). Removing.")
                self._add_error("'additionalProperties' must be a boolean or a schema object.", current_schema)
                self.is_valid = False
                del current_schema["additionalProperties"]

        has_properties_keyword = "properties" in current_schema
        properties_value = current_schema.get("properties")
        relax_validation = (
            self.relax_object_validation_at_depth and
            depth > self.object_validation_depth_threshold
        )
        if not relax_validation:
        # Condition 1: 'properties' keyword should generally be present for an 'object' type.
            if not has_properties_keyword:
                
                is_defined_by_other_means = (
                    isinstance(current_schema.get("additionalProperties"), dict) or
                    any(k in current_schema for k in ['oneOf', 'allOf', 'anyOf', 'not', 'discriminator'])
                )
                if not is_defined_by_other_means:
                    self._add_error("Schema of type 'object' must have a 'properties' field or be defined by other means (e.g. composition keywords).", current_schema)
                    self.logger.warning("Validation Error: Schema of type 'object' is missing 'properties' field and lacks alternative definitions. This may render the schema invalid.")
                    self.is_valid = False
            else:
                # Condition 3: If 'properties' is a dictionary, it must not be empty (as per user request).
                # Note: OpenAPI specification (v3.0.x, v3.1.x) considers `properties: {}` (an empty object)
                # as valid, meaning the object has no defined properties.
                # This check enforces a stricter rule based on the user's prompt.
                if not properties_value: # properties_value is an empty dictionary {}
                    self._add_error("'properties' field in an 'object' schema, if present and a dictionary, must not be empty (user-defined rule).", current_schema)
                    self.logger.warning("Validation Warning: 'properties' field in 'object' schema is an empty dictionary. Enforcing user-defined rule: must not be empty. Removing 'properties'.")
                    self.is_valid = False
                    del current_schema["properties"] # Remove empty properties as it's deemed invalid by this specific rule.

        # Validate 'properties'
        if "properties" in current_schema:
            properties_dict = current_schema["properties"]
            if not isinstance(properties_dict, dict):
                if properties_dict is None:
                    self.logger.debug("Validation fix: 'properties' is None, removing.")
                    del current_schema["properties"]
                else:
                    self._add_error("'properties' field must be a dictionary.", current_schema)
                    self.logger.warning("Validation Error: 'properties' field is not a dictionary. Removing.")
                    self.is_valid = False
                    del current_schema["properties"]
                return # Stop processing properties if structure is wrong

            prop_keys_to_delete = []
            prop_keys_to_add = {} # For fixing non-string keys

            for prop_name, prop_value in properties_dict.items():
                 # Fix non-string keys first
                 if not isinstance(prop_name, str):
                     self.logger.debug(f"Validation fix: Converting non-string property key '{prop_name}' to string.")
                     if str(prop_name) in properties_dict: # Conflict after conversion
                          self.logger.warning(f"Validation Error: Duplicate property key '{str(prop_name)}' after converting non-string key. Skipping original.")
                          self.errors.add(f"Duplicate property key '{str(prop_name)}'.")
                          self.is_valid = False
                     else:
                          prop_keys_to_add[str(prop_name)] = prop_value
                     prop_keys_to_delete.append(prop_name)
                     continue # Process the string version later if added

                 # Validate property value structure (must be schema object or ref)
                 if not isinstance(prop_value, dict):
                      self.logger.warning(f"Validation Error: Value for property '{prop_name}' is not a dictionary ({type(prop_value)}). Removing property.")
                      self._add_error(f"Invalid definition for property '{prop_name}'.", prop_value)
                      self.is_valid = False
                      prop_keys_to_delete.append(prop_name)
                      continue

                 # Remove 'required' if mistakenly placed inside property definition
                 if "required" in prop_value:
                     self.logger.debug(f"Validation fix: Removing 'required' found inside property '{prop_name}'.")
                     del prop_value["required"]

                 # Recurse for nested type or handle $ref
                 if '$ref' in prop_value:
                      if not isinstance(prop_value['$ref'], str):
                           self.logger.warning(f"Validation Error: '$ref' value in property '{prop_name}' is not a string. Removing property.")
                           self._add_error(f"Invalid '$ref' in property '{prop_name}'.", prop_value)
                           self.is_valid = False
                           prop_keys_to_delete.append(prop_name)
                 elif "type" in prop_value:
                      self.type_parser(prop_value, depth=depth + 1)
                 elif prop_value: # Exists, not $ref, no type
                      is_comp = any(k in prop_value for k in ['oneOf', 'allOf', 'anyOf', 'not'])
                      if not is_comp:
                           self.logger.warning(f"Validation Warning: Property '{prop_name}' schema lacks '$ref' and 'type', and no composition keywords.")
                           # Allow for now, but potentially problematic

                 # Handle 'oneOf', 'allOf', etc. if present
                 if "oneOf" in prop_value: self.oneOf(prop_value, depth=depth + 1)
                 # Add calls for allOf, anyOf, not if needed


            # Apply property key deletions and additions
            for key in prop_keys_to_delete:
                 if key in properties_dict: del properties_dict[key]
            properties_dict.update(prop_keys_to_add)

            # Remove properties dict if it became empty
            if not properties_dict:
                 self.logger.debug("Validation fix: 'properties' dictionary became empty after cleaning. Removing.")
                 del current_schema["properties"]

        # Validate 'required' list against final properties
        self.required(current_schema) # Call required again to sync with potentially cleaned properties


    # --- Array Method ---
    def array(self, current_schema, depth: int = 0):
        if not isinstance(current_schema, dict): return # Safety

        # Rule: 'items' is required for type array
        if "items" not in current_schema:
            self._add_error("'items' field is required for schemas of type 'array'.", current_schema)
            self.logger.warning("Validation Error: 'items' field missing in array definition. Marking schema as invalid.")
            self.is_valid = False
            return # Cannot proceed without items

        items_value = current_schema["items"]
        # Rule: 'items' must be a schema object
        if not isinstance(items_value, dict):
            self._add_error("'items' field in array must be a schema object.", current_schema)
            self.logger.warning(f"Validation Error: 'items' value in array is not a dictionary ({type(items_value)}). Marking schema as invalid.")
            self.is_valid = False
            return

        # Validate the items schema itself (recurse or check $ref)
        if '$ref' in items_value:
             if not isinstance(items_value['$ref'], str):
                 self.logger.warning("Validation Error: '$ref' value in array 'items' is not a string. Invalid array schema.")
                 self._add_error("Invalid '$ref' in array 'items'.", items_value)
                 self.is_valid = False
        elif 'type' in items_value:
            self.type_parser(items_value, depth=depth + 1)
        elif items_value: # Exists, not $ref, no type
             is_comp = any(k in items_value for k in ['oneOf', 'allOf', 'anyOf', 'not'])
             if not is_comp:
                 self.logger.warning("Validation Warning: Array 'items' schema lacks '$ref' and 'type', and no composition keywords.")
                 # self.is_valid = False # Be stricter? Allow for now.
        # Else: Empty items object {} is technically valid, represents 'any' type.


    # --- Enum Method ---
    def enum(self, parent_schema):
        if not isinstance(parent_schema, dict) or 'enum' not in parent_schema: return

        enum_value = parent_schema['enum']

        # Allow string enums, convert to list
        if isinstance(enum_value, str):
            self.logger.debug("Validation fix: Converting string 'enum' to list.")
            parent_schema['enum'] = [enum_value]
            enum_value = parent_schema['enum'] # Update local variable

        # Rule: 'enum' must be a non-empty list
        if not isinstance(enum_value, list):
            self._add_error("'enum' field must be a list.", parent_schema)
            self.logger.warning(f"Validation Error: 'enum' field is not a list ({type(enum_value)}). Removing.")
            self.is_valid = False
            del parent_schema['enum']
            return

        if not enum_value: # Empty list
            self._add_error("'enum' list must not be empty.", parent_schema)
            self.logger.warning("Validation Error: 'enum' list is empty. Removing.")
            self.is_valid = False # Empty enum is invalid per spec
            del parent_schema['enum']
            return

        # Optional: Check if enum values match schema 'type' if provided? Defer this complexity.
        # Optional: Check for duplicates in enum list?
        # if len(set(enum_value)) != len(enum_value):
        #     self.logger.warning("Validation Warning: Duplicate values found in 'enum' list.")
        #     parent_schema['enum'] = list(dict.fromkeys(enum_value)) # Deduplicate


    # --- oneOf Method ---
    def oneOf(self, parent_schema, depth: int = 0):
        if not isinstance(parent_schema, dict) or 'oneOf' not in parent_schema: return

        oneOf_value = parent_schema['oneOf']

        # Rule: 'oneOf' must be a list of schema objects
        if not isinstance(oneOf_value, list):
            self._add_error("'oneOf' field must be a list.", parent_schema)
            self.logger.warning(f"Validation Error: 'oneOf' field is not a list ({type(oneOf_value)}). Removing.")
            self.is_valid = False
            del parent_schema['oneOf']
            return

        valid_oneOf_items = []
        has_changes = False
        for item in oneOf_value:
            # Each item must be a schema object (dict)
            if not isinstance(item, dict):
                 self.logger.warning(f"Validation fix: Removing non-dictionary item from 'oneOf': {item}")
                 has_changes = True
                 continue

            # Validate the schema item itself (recurse or check $ref)
            if '$ref' in item:
                 if not isinstance(item['$ref'], str):
                      self.logger.warning(f"Validation fix: Removing item with invalid '$ref' from 'oneOf': {item}")
                      has_changes = True
                 else:
                      valid_oneOf_items.append(item) # Keep valid $ref
            elif 'type' in item:
                 # We could recurse type_parser here, but it might get complex.
                 # Let's assume for now the nested structure is valid if type exists.
                 # A full validator would recurse.
                 valid_oneOf_items.append(item)
            elif item: # Exists, not $ref, no type
                  is_comp = any(k in item for k in ['oneOf', 'allOf', 'anyOf', 'not'])
                  if is_comp:
                       # Again, full validator would recurse. Allow for now.
                       valid_oneOf_items.append(item)
                  else:
                       self.logger.warning(f"Validation fix: Removing item from 'oneOf' lacking '$ref', 'type', or composition: {item}")
                       has_changes = True
            # else: Allow empty dict {}? No, schema must be meaningful.

        # Rule: 'oneOf' list must not be empty
        if not valid_oneOf_items:
             self._add_error("'oneOf' list cannot be empty after filtering invalid items.", parent_schema)
             self.logger.warning("Validation Error: 'oneOf' list became empty after filtering. Removing.")
             self.is_valid = False # Empty oneOf is invalid
             del parent_schema['oneOf']
        elif has_changes:
             parent_schema['oneOf'] = valid_oneOf_items

# --- OpenAPISpecManager Class ---
class ValidationResult(NamedTuple):
    """Structured result of schema validation operations"""
    is_valid: bool
    sanitized_content: Optional[str] # YAML string, "<-|NOT_REQUIRED|->", or None if invalid
    errors: Optional[List[Dict[str, str]]] = None
    metadata: Optional[Dict[str, Any]] = None  # Schema FQN mappings


class OpenAPISpecManager:
    """
    Manages the creation, validation, and manipulation of OpenAPI specifications.
    Provides methods to add components, paths, and combine them into a valid spec.
    """
    def __init__(self, repo_name: str = "API"):
        """Initialize with empty spec structure."""
        self.spec = {
            "openapi": "3.0.0",
            "info": {
                "title": f"API Documentation for {repo_name}",
                "version": "1.0.0"
            },
            "paths": {},
            "components": {
                "schemas": {},
                "securitySchemes": {} # Ensure this exists
            }
        }
        # This maps the original FQN to the schema name used in the spec.
        # Example: { 'eu.fayder.restcountries.v1.domain.Country': 'CountryV1' }
        self._schema_name_to_fqn_map: Dict[str, Dict[str, Any]] = {}
        self.component_keys = set(self.spec['components']['schemas'].keys())
        self.logger = logging.getLogger(__name__)
        self.repo_name = repo_name

    def sanitize_and_validate_content(self, content: str, relax_object_validation: bool = False) -> ValidationResult:
        """
        Sanitizes, validates structure, and validates references in LLM response.
        Uses the current spec's component keys for reference validation.

        Args:
            content: Raw LLM response content string.

        Returns:
            ValidationResult containing validation status, sanitized YAML string, and errors.
        """
        errors = []
        sanitized_yaml_str = None # Will hold the final valid YAML string
        structurally_fixed_yaml_obj = None
        content_to_parse = None
        content_stripped = content.strip()

        if content_stripped == "<-|NOT_REQUIRED|->":
            self.logger.info("Content is exactly <-|NOT_REQUIRED|->.")
            return ValidationResult(True, "<-|NOT_REQUIRED|->", None)
        
        if not content:
            self.logger.info("Content is none.")
            return ValidationResult(False, None, [{'message': 'The response is empty', 'context': ''}])
        # 1. Extract content from backticks
        backticks_found = False
        match = re.search(r"```(?:yaml|yml|json)?\s*([\s\S]*?)\s*```", content, re.IGNORECASE)
        if match:
            backticks_found = True
            extracted_text = match.group(1).strip()
            # Handle explicit non-requirement marker
            if extracted_text == "<-|NOT_REQUIRED|->" or "<-|NOT_REQUIRED|->" in extracted_text:
                self.logger.info("Content marked as <-|NOT_REQUIRED|->.")
                # Return True validity but specific content marker
                return ValidationResult(True, "<-|NOT_REQUIRED|->", None)
            content_to_parse = extracted_text
        else:
            if content.strip().startswith(tuple(chr(c) for c in range(ord('a'), ord('z')+1)) + ('-', '"', "'")) and ':' in content.split('\n', 1)[0]:
                 self.logger.debug("No backticks found, but content looks like YAML. Attempting parse.")
                 content_to_parse = content.strip()
            else:
                 self.logger.warning("Content not wrapped in ``` and does not appear to be valid YAML.")
                 return ValidationResult(False, None, [{'message': "Content not wrapped in ``` and does not appear to be valid YAML. Please make sure your yaml response is wrapped in backticks.", 'context': content[:200]}])


        if not content_to_parse:
             self.logger.warning("Extracted YAML content is empty.")
             return ValidationResult(False, None, [{'message': "Extracted content is empty.", 'context': ''}])

        try:
            lines = content_to_parse.split('\n')
            fixed_lines = []
            for line in lines:
                stripped_line = line.lstrip()
                # We only care about lines that define a 'pattern:'.
                if stripped_line.startswith('pattern:'):
                    parts = line.split(':', 1)
                    # Ensure the split was successful before proceeding
                    if len(parts) == 2:
                        key_part = parts[0]
                        value_part = parts[1]
                        stripped_value = value_part.strip()
                        
                        # Check if the value is non-empty and does not start with a quote character.
                        is_unquoted = stripped_value and not (
                            stripped_value.startswith("'") or 
                            stripped_value.startswith('"') or 
                            stripped_value.startswith('|')
                        )
                        
                        if is_unquoted:
                            # Escape internal single quotes and wrap the whole value in single quotes.
                            safe_value = stripped_value.replace("'", "''")
                            fixed_line = f"{key_part}: '{safe_value}'"
                            self.logger.debug(f"Validator Fix (Unquoted): Corrected unquoted pattern. Fixed: '{fixed_line.strip()}'")
                            fixed_lines.append(fixed_line)
                            continue # The line is fixed, move to the next one

                        elif stripped_value.startswith('"'):
                            #replace the first two double quotes with single quotes,
                            # which preserves backslashes for the regex engine.
                            fixed_line = line.replace('"', "'", 2)
                            self.logger.debug(f"Validator Fix (Double-Quoted): Converted double quotes to single. Original: '{line.strip()}', Fixed: '{fixed_line.strip()}'")
                            fixed_lines.append(fixed_line)
                            continue # The line is fixed, move to the next one

                # If the line is not a pattern we need to fix, or if it's already valid,
                # append the original line to preserve the content.
                fixed_lines.append(line)
                
            # Re-assemble the content with all fixes applied.
            content_to_parse = '\n'.join(fixed_lines)

        except Exception as e:
            # If the pre-processing fails, log it but continue with the original content.
            self.logger.error(f"Error during YAML pre-processing fix: {e}", exc_info=True)

        # 2. Load YAML
        try:
            loaded_yaml = yaml.safe_load(content_to_parse)
            if loaded_yaml is None:
                 self.logger.warning("Loaded YAML content is null (empty or just 'null').")
                 # Treat null/empty as invalid for adding content
                 return ValidationResult(False, None, [{"message": "Loaded YAML content is null or empty.", "context": content_to_parse}])
            
            metadata_dict = {}
            if isinstance(loaded_yaml, dict):
                    # Extract and remove metadata section
                    raw_metadata = loaded_yaml.pop("x-schemas-metadata", None)
                    if raw_metadata and isinstance(raw_metadata, dict):
                        metadata_dict = raw_metadata
                        self.logger.debug(f"Extracted x-schemas-metadata with {len(metadata_dict)} entries")
                        content_to_parse = yaml.safe_dump(loaded_yaml, sort_keys=False)
                        
                    else:
                        self.logger.debug("No x-schemas-metadata found in response")

        except yaml.YAMLError as e:
            self.logger.error(f"YAML parsing error: {e}\nContent:\n{content_to_parse[:500]}...")
            return ValidationResult(False, content_to_parse, [{'message': f"YAML parsing error: {str(e)}", 'context': content_to_parse[:500]}])
        except Exception as e:
            self.logger.error(f"Unexpected error loading YAML: {e}", exc_info=True)
            return ValidationResult(False, content_to_parse, [{'message': f"Unexpected error loading YAML: {str(e)}", 'context': content_to_parse[:500]}])


        
        # 3. Validate/Fix Structure using SpecsWalker
        try:
            # Pass the loaded object (which might be modified by SpecsWalker)
            walker = SpecsWalker(loaded_yaml, self.logger, relax_object_validation_at_depth=relax_object_validation)
            is_struct_valid, struct_errors = walker.fix()
            structurally_fixed_yaml_obj = walker.yaml
            # walker.yaml now holds the potentially fixed structure
            if not is_struct_valid:
                enhanced_errors = []
                source_lines = content_to_parse.splitlines()

                for error in struct_errors:
                    context_snippet = error.get('context', '')
                    # Try to find a good line to search for in the original content
                    search_line = None
                    if context_snippet:
                        context_lines = context_snippet.strip().splitlines()
                        if context_lines:
                            # Heuristic: the longest line is often the most unique and descriptive
                            search_line = max(context_lines, key=len).strip()

                    found_line_index = -1
                    if search_line:
                        for i, source_line in enumerate(source_lines):
                            # Search for the content of the line. 'in' is robust against indentation.
                            if search_line in source_line:
                                found_line_index = i
                                break
                    
                    if found_line_index != -1:
                        # We found the snippet, now create a more descriptive context window
                        window_size = 4 # Lines to show above and below
                        start = max(0, found_line_index - window_size)
                        end = min(len(source_lines), found_line_index + window_size + 1)
                        
                        context_with_lines = []
                        if start > 0:
                            context_with_lines.append("...")

                        for i in range(start, end):
                            line_num = i + 1
                            # Point to the line we found to draw attention to the area
                            prefix = f"{line_num:4d}> " if i == found_line_index else f"{line_num:4d}  "
                            context_with_lines.append(f"{prefix}{source_lines[i]}")

                        if end < len(source_lines):
                            context_with_lines.append("...")
                        
                        new_context = "\n".join(context_with_lines)
                        enhanced_error = error.copy()
                        enhanced_error['context'] = new_context
                        enhanced_errors.append(enhanced_error)
                    else:
                        # If we couldn't find the snippet, fallback to the original error
                        enhanced_errors.append(error)
                
                errors.extend(enhanced_errors)
                self.logger.warning(
                    f"Structural validation failed with {len(struct_errors)} errors. "
                    f"First error: {struct_errors[0] if struct_errors else 'N/A'}"
                )

            # Dump the structurally fixed object back to string for ref check
            structurally_fixed_yaml_str = yaml.safe_dump(structurally_fixed_yaml_obj, sort_keys=False)
        except Exception as e:
            self.logger.error(f"Error during structural validation (SpecsWalker): {e}", exc_info=True)
            errors.append(f"Error during structural validation: {str(e)}")
            # Return False, use original loaded YAML for debugging context if needed
            return ValidationResult(False, yaml.safe_dump(loaded_yaml), errors)


        # 4. Validate Reference
        ref_errors = []
        if structurally_fixed_yaml_str: # Only check refs if we have a string from walker
            try:
                known_global_schemas = self.component_keys
                local_schemas = structurally_fixed_yaml_obj.get("components", {}).get("schemas", {})
                valid_schema_names = known_global_schemas.union(local_schemas.keys())
                self.logger.debug(f"Reference validation context: {len(known_global_schemas)} global schemas, {len(local_schemas)} local schemas. Total unique: {len(valid_schema_names)}.")
                def find_and_report_bad_refs(data: Any) -> list:
                    bad_refs_found = []
                    def walk(sub_data: Any, parent_data: Any = None):
                        if isinstance(sub_data, dict):
                            for key, value in sub_data.items():
                                if key == "$ref" and isinstance(value, str) and value.startswith("#/components/schemas/"):
                                    ref_name = value.split('/')[-1]
                                    if ref_name not in valid_schema_names:
                                        message = f"Reference to non-existent schema: '{ref_name}'. Please in-line the schema or ensure it is defined."
                                        context_obj = parent_data if parent_data is not None else sub_data
                                        try:
                                            context_str = yaml.dump(context_obj, indent=2, sort_keys=False)
                                        except Exception:
                                            context_str = str(context_obj)
                                        bad_refs_found.append({'message': message, 'context': context_str})
                                else:
                                    walk(value, sub_data)
                        elif isinstance(sub_data, list):
                            for item in sub_data:
                                walk(item, sub_data)
                    walk(data)
                    return bad_refs_found
                
                ref_errors = find_and_report_bad_refs(structurally_fixed_yaml_obj)
                if ref_errors:
                    errors.extend(ref_errors)

            except Exception as e:
                self.logger.error(f"Error during reference validation: {e}", exc_info=True)
                errors.append(f"Error during reference validation: {str(e)}")

        # 5. Final Decision and Return
        is_overall_valid = is_struct_valid and not ref_errors # Valid only if structure AND refs are OK
        if is_overall_valid:
             self.logger.debug("Content sanitized and validated successfully.")
             return ValidationResult(True, structurally_fixed_yaml_str, None, metadata_dict)
        else:
             unique_errors = [dict(t) for t in {tuple(sorted(d.items())) for d in errors}]
             self.logger.warning(f"Content validation failed with errors: {unique_errors}")
             return ValidationResult(False, structurally_fixed_yaml_str, unique_errors, metadata_dict)

    def _get_unique_schema_name_base(self, fqn: str) -> str:
        """
        Generates a more descriptive schema name from a Fully Qualified Name (FQN)
        by trying a hierarchy of heuristics. This is called ONLY when a name
        collision is detected.
        """
        if not isinstance(fqn, str) or '.' not in fqn:
            return fqn if isinstance(fqn, str) else "UnknownSchema"

        parts = fqn.split('.')
        simple_name = parts[-1]

        # --- Heuristic 1: Look for explicit versioning (v1, v2, etc.) ---
        # This is the best signal.
        # e.g., eu.fayder.restcountries.v1.domain.Country -> CountryV1
        version_match = re.search(r'\.(v\d+)\.', fqn)
        if version_match:
            version_suffix = version_match.group(1).capitalize()
            return f"{simple_name}{version_suffix}"

        # --- Heuristic 2: Use the preceding package name as a differentiator ---
        # This is the next best signal.
        # e.g., com.example.auth.dto.User -> UserAuth
        if len(parts) > 2:
            distinguishing_part = parts[-2].lower()
            # Avoid generic package names like 'model', 'domain', 'dto', etc.
            generic_parts = {'domain', 'model', 'models', 'dto', 'dtos', 'entity', 'entities', 'schema'}
            if distinguishing_part not in generic_parts:
                return f"{simple_name}{distinguishing_part.capitalize()}"

        # --- Fallback: If no good differentiator is found, return the simple name ---
        # The calling function's counter logic will then take over to ensure uniqueness.
        return simple_name
    
    def add_component_schema(self, component_name_context: str, yaml_content_str: str, validation_metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Add component schemas from a validated YAML string to the spec.

        Args:
            component_name_context: Name used for logging (original name before Request/Response).
            yaml_content_str: Validated YAML string containing the component schema(s).

        Returns:
            Boolean indicating if at least one schema was successfully added.
        """

        if not yaml_content_str or yaml_content_str == "<-|NOT_REQUIRED|->":
             self.logger.debug(f"Skipping add_component_schema for {component_name_context} due to empty or NOT_REQUIRED content.")
             return False # Nothing to add
        add_results: List[Dict[str, Any]] = []
        added_schemas_count = 0
        try:
            data = yaml.safe_load(yaml_content_str)

            # Robust check for the expected structure
            if not isinstance(data, dict):
                self.logger.error(f"Invalid YAML root structure for component {component_name_context}. Expected a dictionary. YAML:\n{yaml_content_str[:500]}...")
                return False
            components_section = data.get("components")
            if not isinstance(components_section, dict):
                self.logger.error(f"Invalid/Missing 'components' section in YAML for {component_name_context}. YAML:\n{yaml_content_str[:500]}...")
                return False
            schemas_to_add = components_section.get("schemas")
            if not isinstance(schemas_to_add, dict):
                self.logger.error(f"Invalid/Missing 'components.schemas' section in YAML for {component_name_context}. YAML:\n{yaml_content_str[:500]}...")
                return False

            if not schemas_to_add:
                 self.logger.warning(f"No schemas found under components.schemas in YAML for {component_name_context}.")
                 return False # Nothing to add, but not necessarily an error

            # Iterate and add valid schemas
            for schema_name, schema_definition in schemas_to_add.items():
                if not isinstance(schema_definition, dict):
                      self.logger.warning(f"Schema definition for '{schema_name}' (from {component_name_context}) is not a dictionary. Skipping.")
                      continue
                 
                schema_fqn = None
                status = 'added_new'
                metadata_source = "default"
                conflict_details = {}

                # First try: explicit metadata
                if validation_metadata and schema_name in validation_metadata:
                    metadata_entry = validation_metadata[schema_name]
                    if isinstance(metadata_entry, dict):
                        schema_fqn = metadata_entry.get("source_fqn")
                        if schema_fqn:
                            metadata_source = "explicit"
                            self.logger.debug(f"Found explicit FQN for '{schema_name}': {schema_fqn}")

                # Second try: infer from context if no explicit metadata
                if not schema_fqn:
                    # If this is the primary component (matches the context name)
                    if schema_name == component_name_context.split('.')[-1]:
                        schema_fqn = component_name_context
                        metadata_source = "inferred-primary"
                        self.logger.debug(f"Inferred FQN for primary schema '{schema_name}': {schema_fqn}")
                    else:
                        # For nested/dependency schemas without metadata, use a qualified name
                        schema_fqn = f"{component_name_context}.{schema_name}"
                        metadata_source = "inferred-nested"
                        self.logger.debug(f"No metadata for '{schema_name}', using inferred FQN: {schema_fqn}")
                        
                generation_context = "dependency"  # default
                if validation_metadata and schema_name in validation_metadata:
                    relationship = validation_metadata[schema_name].get("relationship", "")
                    if relationship == "primary":
                        generation_context = "primary"
                elif schema_name == component_name_context.split('.')[-1]:
                    generation_context = "primary"
                
                final_schema_name = schema_name
                if schema_name in self._schema_name_to_fqn_map:
                    existing_info = self._schema_name_to_fqn_map[schema_name]
                    if isinstance(existing_info, str):
                        # Upgrade old format to new
                        existing_info = {"fqn": existing_info, "context": "dependency"}
                    
                    existing_fqn = existing_info["fqn"]
                    existing_context = existing_info.get("context", "dependency")
                    conflict_details = {'conflict_fqn': existing_fqn} 
                    if existing_fqn == schema_fqn:
                        if generation_context == "primary" and existing_context != "primary":
                            status = 'duplicate_upgraded'
                            self.logger.info(
                                f"Upgrading schema '{schema_name}' from {existing_context} to primary context"
                            )
                            # Replace with better version
                            self.spec["components"]["schemas"][schema_name] = schema_definition
                            self._schema_name_to_fqn_map[schema_name] = {
                                "fqn": schema_fqn,
                                "context": generation_context,
                                "parent": component_name_context
                            }
                            added_schemas_count += 1
                            add_results.append({'final_name': schema_name, 'original_name': schema_name, 'status': status, **conflict_details})
                        else:
                            status = 'duplicate_skipped'
                            self.logger.debug(f"Schema '{schema_name}' already exists with same/better context")
                            add_results.append({'final_name': schema_name, 'original_name': schema_name, 'status': status, **conflict_details})
                        continue
                    else:
                        # Different FQN = collision
                        status = 'collision_renamed'
                        self.logger.warning(
                            f"Name collision for '{schema_name}'. "
                            f"Existing FQN: {existing_fqn}, "
                            f"New FQN: {schema_fqn} (source: {metadata_source})"
                        )
                        
                        # If we only have inferred FQNs, be more conservative
                        if metadata_source.startswith("inferred"):
                            self.logger.info("Collision detected with inferred FQN. Applying conservative renaming.")
                        
                        # Use existing renaming logic
                        base_name = self._get_unique_schema_name_base(schema_fqn)
                        counter = 1
                        unique_name_candidate = base_name
                        while unique_name_candidate in self.component_keys:
                            unique_name_candidate = f"{base_name}_{counter}"
                            counter += 1
                        final_schema_name = unique_name_candidate
                        self.logger.info(f"Renamed '{schema_name}' to '{final_schema_name}' to avoid collision")
                 # Add/overwrite the schema in the spec
                
                self.spec["components"]["schemas"][final_schema_name] = schema_definition
                self.component_keys.add(final_schema_name)
                self._schema_name_to_fqn_map[final_schema_name] = {
                    "fqn": schema_fqn,
                    "context": generation_context,
                    "parent": component_name_context
                }
                
                # Track metadata quality for debugging
                if not hasattr(self, '_metadata_quality_stats'):
                    self._metadata_quality_stats = {'explicit': 0, 'inferred-primary': 0, 'inferred-nested': 0, 'default': 0}
                self._metadata_quality_stats[metadata_source] += 1
                
                added_schemas_count += 1
                add_results.append({
                    'final_name': final_schema_name,
                    'original_name': schema_name,
                    'status': status,
                    **conflict_details
                })
                self.logger.info(f"Added schema '{final_schema_name}' (FQN: {schema_fqn}, source: {metadata_source})")

            return add_results

        except yaml.YAMLError as e:
            self.logger.error(f"YAML error parsing component schema YAML for {component_name_context}: {e}. YAML:\n{yaml_content_str[:500]}...")
            return  []
        except Exception as e:
            self.logger.error(f"Unexpected error adding component schema {component_name_context}: {e}", exc_info=True)
            return  []

    def add_path_operation(self, path: str, method: str, request_yaml_str: Optional[str], response_yaml_str: Optional[str]) -> bool:
        """
        Add a path operation to the spec from validated YAML strings.

        Args:
            path: URL path (e.g., /api/users/)
            method: HTTP method (e.g., get, post)
            request_yaml_str: Validated YAML string for request parts. Can be None or "<-|NOT_REQUIRED|->".
            response_yaml_str: Validated YAML string for response parts. Can be None or "<-|NOT_REQUIRED|->".

        Returns:
            Boolean indicating success (if at least some operation data was added).
        """
        method = method.lower()
        try:
            # Ensure path exists in spec
            if path not in self.spec["paths"]:
                self.spec["paths"][path] = {}

            operation_data = {} # Dictionary to hold the combined operation details

            # --- Process Request YAML ---
            if request_yaml_str and request_yaml_str != "<-|NOT_REQUIRED|->":
                try:
                    request_data = yaml.safe_load(request_yaml_str)
                    # Check if loaded data is a dictionary
                    if isinstance(request_data, dict):
                        # Copy relevant keys if they exist and are valid
                        if "parameters" in request_data and isinstance(request_data["parameters"], list):
                            operation_data["parameters"] = request_data["parameters"]
                        if "requestBody" in request_data and isinstance(request_data["requestBody"], dict):
                            operation_data["requestBody"] = request_data["requestBody"]
                        if "security" in request_data and isinstance(request_data["security"], list):
                            operation_data["security"] = request_data["security"]
                    else:
                         self.logger.warning(f"Parsed request YAML for {method.upper()} {path} is not a dict ({type(request_data)}). Skipping request part.")
                except yaml.YAMLError as e:
                    self.logger.error(f"Error parsing request YAML for {method.upper()} {path} during add: {e}. YAML:\n{request_yaml_str[:500]}...")
                except Exception as e:
                     self.logger.error(f"Unexpected error loading request YAML for {method.upper()} {path} during add: {e}", exc_info=True)

            # --- Process Response YAML ---
            if response_yaml_str and response_yaml_str != "<-|NOT_REQUIRED|->":
                try:
                    response_data = yaml.safe_load(response_yaml_str)
                    # Check if loaded data is a dictionary
                    if isinstance(response_data, dict):
                        # Copy relevant keys if they exist and are valid
                        if "responses" in response_data and isinstance(response_data["responses"], dict):
                            operation_data["responses"] = response_data["responses"]
                        if "summary" in response_data and isinstance(response_data["summary"], str):
                            operation_data["summary"] = response_data["summary"]
                    else:
                         self.logger.warning(f"Parsed response YAML for {method.upper()} {path} is not a dict ({type(response_data)}). Skipping response part.")
                except yaml.YAMLError as e:
                    self.logger.error(f"Error parsing response YAML for {method.upper()} {path} during add: {e}. YAML:\n{response_yaml_str[:500]}...")
                except Exception as e:
                     self.logger.error(f"Unexpected error loading response YAML for {method.upper()} {path} during add: {e}", exc_info=True)

            # --- Add the combined operation data to the spec if not empty ---
            if operation_data:
                # Ensure responses exist, add default if missing (OpenAPI requirement)
                if "responses" not in operation_data or not operation_data["responses"]:
                     self.logger.warning(f"Operation {method.upper()} {path} missing 'responses'. Adding default error response.")
                     operation_data["responses"] = {
                          "default": {"description": "Unexpected error"}
                     }

                self.spec["paths"][path][method] = operation_data
                self.logger.info(f"Added/Updated operation {method.upper()} {path} with keys: {list(operation_data.keys())}")
                return True
            else:
                # Log if nothing was added, helps diagnose issues
                self.logger.warning(f"No valid operation data generated or parsed for {method.upper()} {path}. Operation not added.")
                return False # Indicate nothing was added

        except Exception as e:
            # Catch-all for unexpected errors during the add process
            self.logger.error(f"Fatal error adding path operation {method.upper()} {path}: {e}", exc_info=True)
            return False

    def post_process_components(self) -> None:
        """
        Post-process component schemas: apply semantic rules (readOnly/writeOnly, required)
        and resolve reference issues (Request/Response suffix).
        """
        schemas = self.spec.get("components", {}).get("schemas")
        if not schemas or not isinstance(schemas, dict):
             self.logger.info("post_process_components: No schemas found or invalid structure. Skipping.")
             return

        self.logger.info(f"post_process_components: Starting semantic rule application on {len(schemas)} schemas...")
        # Apply semantic rules (modifies schemas dict in-place)
        for schema_name, schema_details in schemas.items():
            # Make a deep copy ONLY if _apply_schema_semantic_rules modifies nested structures
            # in a way that could interfere with iteration. If it only modifies top-level
            # keys or simple values, copy might not be needed. Let's assume it's safer with copy.
            schema_copy = copy.deepcopy(schema_details)
            try:
                is_request_schema = schema_name.endswith("Request")
                # This helper modifies schema_copy in place
                self._apply_schema_semantic_rules(schema_copy, is_request_schema)
                # Replace original with processed copy
                schemas[schema_name] = schema_copy
            except Exception as e:
                 # Log error but continue with other schemas
                 self.logger.error(f"Error applying semantic rules to schema '{schema_name}': {e}", exc_info=True)

        self.logger.info("post_process_components: Starting reference resolution...")
        # Fix reference errors (modifies schemas dict in-place)
        try:
            # This helper modifies schemas in place
            self._resolve_reference_issues(schemas)
        except Exception as e:
             self.logger.error(f"Error during reference resolution: {e}", exc_info=True)

        self.logger.info("post_process_components: Finished.")

    # --- Helper for Semantic Rules (from previous response) ---
    def _apply_schema_semantic_rules(self, schema: Dict[str, Any], is_request_schema: bool) -> None:
        # (Keep the implementation from the previous response)
        if not isinstance(schema, dict): return # Safety check

        properties = schema.get("properties", {})
        if not isinstance(properties, dict): return # Safety check

        required_fields = schema.get('required', [])
        # Ensure required_fields is a list, default to empty list if not
        if not isinstance(required_fields, list):
            self.logger.warning(f"post_process: 'required' is not a list in schema, resetting. Schema content: {schema}")
            required_fields = []
            if 'required' in schema: del schema['required'] # Remove invalid required


        new_properties = {}
        current_required = set(required_fields) # Use set for efficient removal

        for prop, details in properties.items():
            if not isinstance(details, dict): continue # Skip invalid property definitions

            # Rule: Remove readOnly props from request schema / writeOnly from response
            if (is_request_schema and details.get('readOnly') is True) or \
               (not is_request_schema and details.get('writeOnly') is True):
                current_required.discard(prop) # Remove from required if present
                continue # Skip adding this property

            # Rule: Remove readOnly/writeOnly attributes from the final property definition
            details.pop('readOnly', None)
            details.pop('writeOnly', None)

            new_properties[prop] = details

        # Update properties
        schema['properties'] = new_properties

        # Rule: For response schemas, all *remaining* properties should be required
        if not is_request_schema:
            # Required is the list of keys in the final new_properties
            # final_required = list(new_properties.keys())
            # if final_required:
            #     schema['required'] = sorted(final_required) # Sort for consistency
            # elif 'required' in schema: # Remove if it exists but is now empty
            #      del schema['required']
            pass
        else:
            # For request schemas, update required based on removals
            final_required = list(current_required)
             # Filter again to ensure required exist in final properties
            final_required = [req for req in final_required if req in new_properties]
            if final_required:
                 schema['required'] = sorted(final_required) # Sort for consistency
            elif 'required' in schema: # Remove if it exists but is now empty
                 del schema['required']

    # --- Helper for Reference Fixing (from previous response) ---
    def _resolve_reference_issues(self, schemas: Dict[str, Any]) -> None:
        # (Keep the implementation from the previous response)
        count_fixed = 0
        count_cleared = 0
        schema_keys = set(schemas.keys()) # Get current keys for quick lookup

        for schema_name, schema_info in schemas.items():
             if not isinstance(schema_info, dict): continue
             properties = schema_info.get("properties", {})
             if not isinstance(properties, dict): continue

             # Use list(properties.items()) for safe iteration if dict is modified
             for property_name, property_info in list(properties.items()):
                 if not isinstance(property_info, dict): continue

                 ref_to_fix = None
                 target_dict = None
                 ref_key = None
                 is_in_items = False

                 # Check direct $ref
                 if "$ref" in property_info:
                     ref_to_fix = property_info["$ref"]
                     target_dict = property_info
                     ref_key = "$ref"

                 # Check $ref inside items (for arrays)
                 elif "items" in property_info and isinstance(property_info.get("items"), dict) and "$ref" in property_info["items"]:
                     ref_to_fix = property_info["items"]["$ref"]
                     target_dict = property_info["items"]
                     ref_key = "$ref"
                     is_in_items = True


                 # If a potentially broken ref was found
                 if ref_to_fix and isinstance(ref_to_fix, str) and ref_to_fix.startswith("#/components/schemas/"):
                     original_ref_name = ref_to_fix.split('/')[-1]

                     # If the ref is already valid, skip
                     if original_ref_name in schema_keys:
                         continue

                     # Attempt to fix by adding Request/Response suffix
                     fixed = False
                     if schema_name.endswith("Request"):
                         alt_name = original_ref_name + "Request"
                         if alt_name in schema_keys:
                             new_ref = f"#/components/schemas/{alt_name}"
                             target_dict[ref_key] = new_ref
                             fixed = True
                             self.logger.debug(f"Post-process: Fixed ref in '{schema_name}.{property_name}' from '{ref_to_fix}' to '{new_ref}'")
                             count_fixed += 1
                     elif schema_name.endswith("Response"):
                         alt_name = original_ref_name + "Response"
                         if alt_name in schema_keys:
                             new_ref = f"#/components/schemas/{alt_name}"
                             target_dict[ref_key] = new_ref
                             fixed = True
                             self.logger.debug(f"Post-process: Fixed ref in '{schema_name}.{property_name}' from '{ref_to_fix}' to '{new_ref}'")
                             count_fixed += 1
                     # Add a check for base name if suffixes fail?
                     # elif original_ref_name in schema_keys: # Maybe the suffix was wrong?
                     #      new_ref = f"#/components/schemas/{original_ref_name}"
                     #      target_dict[ref_key] = new_ref
                     #      fixed = True
                     #      self.logger.debug(f"Post-process: Fixed ref in '{schema_name}.{property_name}' from '{ref_to_fix}' to '{new_ref}' (base name match)")
                     #      count_fixed += 1


                     # If not fixed, log and clear the reference part
                     if not fixed:
                         count_cleared += 1
                         self.logger.warning(f"Post-process: Could not resolve reference '{ref_to_fix}' in '{schema_name}.{property_name}'. Clearing target.")
                         # Clear the dictionary containing the bad ref
                         if is_in_items:
                             property_info["items"] = {"type": "object", "description": "Reference removed due to resolution error"} # Clear items, provide fallback
                         else:
                             # Replace the whole property with a placeholder? Or just remove $ref? Let's clear it.
                             properties[property_name] = {"type": "object", "description": "Reference removed due to resolution error"} # Clear the whole property

        if count_fixed > 0:
            self.logger.info(f"Post-process: Fixed {count_fixed} schema references using suffix logic.")
        if count_cleared > 0:
             self.logger.info(f"Post-process: Cleared {count_cleared} unresolved references.")

    def _get_base_spec(self) -> Dict[str, Any]:
        """
        Creates the base structure of an OpenAPI specification document
        with placeholders for paths and components.
        """
        # This can be customized with your project's info
        return {
            "openapi": "3.0.3",
            "info": {
                "title": f"API Documentation for {self.repo_name}",
                "version": "1.0.0"
            },
            "paths": {},
            "components": {
                "schemas": {}
            }
        }

    def _cleanup_unused_components(self, spec_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Removes any schemas from the components section that are not referenced
        by any path or by another required schema (handles transitive dependencies).
        This is a corrected and robust implementation.
        """
        if "components" not in spec_dict or "schemas" not in spec_dict["components"]:
            self.logger.debug("Cleanup: No components section found.")
            return spec_dict

        all_schemas = spec_dict["components"].get("schemas", {})
        if not all_schemas:
            self.logger.debug("Cleanup: Schemas section is empty.")
            return spec_dict

        # Helper to find all $ref values within a given data structure
        def find_refs_recursive(data: Any) -> Set[str]:
            found = set()
            if isinstance(data, dict):
                for key, value in data.items():
                    if key == "$ref" and isinstance(value, str) and value.startswith("#/components/schemas/"):
                        found.add(value.split('/')[-1])
                    else:
                        found.update(find_refs_recursive(value))
            elif isinstance(data, list):
                for item in data:
                    found.update(find_refs_recursive(item))
            return found

        # Step 1: Find all schema names directly referenced in paths
        processing_queue = list(find_refs_recursive(spec_dict.get("paths", {})))
        self.logger.info(f"Cleanup: Found {len(processing_queue)} direct schema references in paths.")
        
        # Step 2: Iteratively find all transitive dependencies
        required_schemas: Set[str] = set(processing_queue)
        
        head = 0
        while head < len(processing_queue):
            schema_name = processing_queue[head]
            head += 1
            
            if schema_name not in all_schemas:
                continue

            # Find refs inside this schema's definition
            transitive_refs = find_refs_recursive(all_schemas[schema_name])
            
            for ref_name in transitive_refs:
                if ref_name not in required_schemas:
                    required_schemas.add(ref_name)
                    processing_queue.append(ref_name)

        # Step 3: Filter the components.schemas dictionary
        original_count = len(all_schemas)
        cleaned_schemas = {name: schema for name, schema in all_schemas.items() if name in required_schemas}
        
        removed_count = original_count - len(cleaned_schemas)
        if removed_count > 0:
            self.logger.info(f"Cleanup: Removed {removed_count} unused schemas. {len(cleaned_schemas)} schemas remain.")
        else:
            self.logger.info("Cleanup: No unused schemas were found to remove.")

        spec_dict["components"]["schemas"] = cleaned_schemas
        return spec_dict
    
    def generate_profile_specific_specs(self, profile_metadata, output_dir: str):
        """
        Generates and saves a separate OpenAPI specification for each detected Spring profile.
        Each spec contains only the endpoints and necessary components for that profile.
        
        This method assumes `self.spec` has been fully populated with the master list
        of all paths and components before being called.
        """
        self.logger.info("Starting generation of profile-specific OpenAPI specifications...")

        # Get profile mappings. This assumes the analyzer has already been run.
        all_profiles = profile_metadata.get("profiles", [])
        endpoint_profiles = profile_metadata.get("endpoint_profiles", {})

        if not all_profiles:
            self.logger.info("No profiles detected. Skipping profile-specific spec generation.")
            return
            
        self.logger.info(f"Found profiles: {all_profiles}. Generating a spec for each.")

        master_paths = self.spec.get("paths", {})
        master_components = self.spec.get("components", {})

        for profile in all_profiles:
            self.logger.info(f"--- Assembling spec for profile: '{profile}' ---")
            
            # 1. Start with a fresh, clean spec structure for this profile
            profile_spec = self._get_base_spec()
            profile_spec["info"]["title"] = f"API Specification ({profile.capitalize()} Profile)"
            
            # 2. Filter paths to include only those relevant to the current profile
            for path, path_item in master_paths.items():
                filtered_methods = {}
                for method, method_item in path_item.items():
                    # The key format is "METHOD /path/url"
                    endpoint_key = f"{method.upper()} {path}"
                    # Check if this endpoint is associated with the current profile
                    if endpoint_key in endpoint_profiles and profile in endpoint_profiles[endpoint_key]:
                        filtered_methods[method] = method_item
                
                if filtered_methods:
                    profile_spec["paths"][path] = filtered_methods
            
            self.logger.info(f"Filtered to {len(profile_spec['paths'])} paths for profile '{profile}'.")

            # 3. Add ALL master components initially. The cleanup step will prune them.
            profile_spec["components"] = copy.deepcopy(master_components)

            # 4. CRITICAL: Clean up unused components from this profile-specific spec
            self.logger.info(f"Running cleanup for profile '{profile}' to remove unreferenced components...")
            cleaned_profile_spec = self._cleanup_unused_components(profile_spec)

            # 5. Save the final, cleaned spec
            try:
                os.makedirs(output_dir, exist_ok=True)
                file_path = os.path.join(output_dir, f"{profile}-spec.yaml")
                with open(file_path, 'w', encoding='utf-8') as f:
                    # Use a custom dumper if you need specific formatting, otherwise this is fine
                    yaml.dump(cleaned_profile_spec, f, sort_keys=False, indent=2, default_flow_style=False)
                self.logger.info(f"Successfully saved '{profile}' profile spec to {file_path}")
            except Exception as e:
                self.logger.error(f"Failed to save spec for profile '{profile}': {e}", exc_info=True)

        self.logger.info("Finished generating all profile-specific specs.")

    def serialize(self) -> str:
        """Serialize the spec to YAML string."""
        try:
            # Sort paths for consistent output
            sorted_paths = dict(sorted(self.spec.get("paths", {}).items()))

            # Sort components sub-sections
            sorted_schemas = dict(sorted(self.spec.get("components", {}).get("schemas", {}).items()))
            sorted_security = dict(sorted(self.spec.get("components", {}).get("securitySchemes", {}).items()))
            # Add sorting for other component types if used (parameters, requestBodies, etc.)

            # Create the final structure for dumping
            spec_to_dump = copy.deepcopy(self.spec) # Start with a copy
            spec_to_dump["paths"] = sorted_paths
            spec_to_dump["components"]["schemas"] = sorted_schemas
            spec_to_dump["components"]["securitySchemes"] = sorted_security
            # Ensure components key exists even if empty subsections
            if "components" not in spec_to_dump: spec_to_dump["components"] = {}
            if "schemas" not in spec_to_dump["components"]: spec_to_dump["components"]["schemas"] = {}
            if "securitySchemes" not in spec_to_dump["components"]: spec_to_dump["components"]["securitySchemes"] = {}

            # Use yaml.dump for proper YAML formatting
            # sort_keys=False preserves order within dicts where possible (like properties)
            # allow_unicode=True handles non-ASCII characters
            # width=float("inf") prevents line wrapping for long strings (optional)
            return yaml.dump(spec_to_dump, sort_keys=False, allow_unicode=True, width=float("inf"))

        except Exception as e:
            self.logger.error(f"Error during serialization: {e}", exc_info=True)
            # Fallback to basic string representation in case of error
            return str(self.spec)
