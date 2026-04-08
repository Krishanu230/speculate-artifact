#!/usr/bin/env python3
import argparse
import asyncio
from datetime import datetime
from dotenv import load_dotenv
import os
import sys
import time
from pathlib import Path
import traceback
from typing import Callable, Optional
import uuid

current_script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_script_dir)
common_path = os.path.join(project_root, 'common')

if common_path not in sys.path:
    sys.path.insert(0, common_path)
if project_root not in sys.path:
     sys.path.insert(0, project_root)

from common.core.code_analyzer import CodeAnalyzer
from common.core.framework_analyzer import FrameworkAnalyzer
from common.core.prompt_management import PromptManager
from common.core.spec_manager import OpenAPISpecManager, ValidationResult
from common.core.batch_processor import BatchProcessor
from common.llm.llm import LLMManager
from common.stats import EntityStatus, EntityType, LLMCallType, StatsCollector, ValidationAttempt

from python_analyzer import PythonCodeAnalyzer
from django_analyzer import DjangoAnalyzer

from java_analyzer import JavaCodeAnalyzer
from jersey_analyzer import JerseyFrameworkAnalyzer
from spring_analyzer import SpringBootFrameworkAnalyzer

from common.logging_config import SetupLogging, configure_logging_directory

console_logger = SetupLogging.get_console_logger()  # This will show to customer
debug_logger = SetupLogging.get_debug_logger()  # This will go in our log file

class SpecGenerator:
    """Main controller for the API documentation generation process"""
    
    def __init__(self,
                code_analyzer: CodeAnalyzer,
                framework_analyzer: FrameworkAnalyzer,
                prompt_manager: PromptManager,
                llm_manager: LLMManager,
                spec_manager: OpenAPISpecManager,
                batch_processor: BatchProcessor,
                stats_collector: StatsCollector = None,
                logger = None,
                spec_model_name: Optional[str] = None,
                context_model_name: Optional[str] = None,
                skip_components=False,
                skip_missing_context=False,
                force_add_components=False,
                validation_max_retries: int = 2,
                framework=None
                ):
        """Initialize with all required components"""
        self.code_analyzer = code_analyzer
        self.framework_analyzer = framework_analyzer
        self.prompt_manager = prompt_manager
        self.llm_manager = llm_manager
        self.spec_manager = spec_manager
        self.batch_processor = batch_processor
        self.stats_collector = stats_collector
        self.logger = logger or debug_logger
        self.spec_model_name = spec_model_name
        self.context_model_name = context_model_name
        self.skip_components = skip_components
        self.skip_missing_context = skip_missing_context
        self.force_add_components = force_add_components
        self.validation_max_retries = validation_max_retries
        self.framework = framework
        self.logger.info(
            f"SpecGenerator configured with Spec Model: {self.spec_model_name or 'Default'}, "
            f"Context Model: {self.context_model_name or 'Default'}, "
            f"Validation Max Retries: {self.validation_max_retries}"
        )
    
    async def generate_spec(self, project_path: str, output_path: str) -> str:
        """Main entry point for generating an OpenAPI specification"""
        start_time = time.time()
        error_file = os.path.join(output_path, "errors.txt")
        
        # Step 1: Analyze the project code
        self.logger.info("Starting code analysis...")
        analysis_path = self.code_analyzer.analyze_project(project_path, output_path, self.framework)
        
        # Step 3: Get endpoints and schema components
        self.logger.info("Extracting endpoints and schema components...")
        endpoints = self.framework_analyzer.get_endpoints(output_dir=output_path)
        components = self.framework_analyzer.get_schema_components()
        self.logger.info(f"Found {len(endpoints)} endpoints and {len(components)} schema components")
        print(f"Found {len(endpoints)} endpoints and {len(components)} schema components")

        # Step 4: Process schema components
        self.logger.info("Processing schema components...")
        component_results = await self.process_components(components, error_file)
        component_results_path = os.path.join(output_path, "component_results.yaml")
        with open(component_results_path, "w") as f:
                for component_name, content in component_results:
                    if content is not None:
                        f.write(f"{component_name}:\n{content}\n\n")
            
        # Get the component keys for validation
        component_keys = set(component for component, _ in component_results if component is not None)
        # Step 5: Process endpoints
        self.logger.info("Processing endpoints...")
        await self.process_endpoints(endpoints, error_file)

        # Step 6: Post-process and finalize the specification
        self.logger.info("Finalizing the OpenAPI specification...")
        self.spec_manager.post_process_components()
        
        # Generate the final specification file
        spec_path = os.path.join(output_path, "openapi.yaml")
        with open(spec_path, "w") as f:
            f.write(self.spec_manager.serialize())
        
        # Finalize statistics
        if self.stats_collector:
            stats_path = self.stats_collector.finalize()
            self.logger.info(f"Generation statistics saved to {stats_path}")
        
        elapsed_time = time.time() - start_time
        self.logger.info(f"OpenAPI specification generated in {elapsed_time:.2f} seconds")
        self.logger.info(f"Specification saved to {spec_path}")
        
        return spec_path
    
    async def _generate_and_validate_with_retry(
        self,
        prompt_func: Callable[[], str],
        system_message: str,
        entity_id: str,
        call_type: LLMCallType,
        error_file: str,
        index: int,
        total_items: int,
        max_retries: Optional[int] = None,
        is_json_output: bool = False,
        model_override: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generates content using LLM, validates it, and retries on validation failure
        by modifying the prompt.

        Returns:
            Validated YAML string, "<-|NOT_REQUIRED|->", or None on failure.
        """
        current_prompt: Optional[str] = None
        retry_count = 0
        log_prefix = f"[{index + 1}/{total_items}][{entity_id}][Retry {retry_count}]"
        accumulated_errors = []
        max_retries = self.validation_max_retries if max_retries is None else max_retries
        original_prompt = prompt_func() # Generate the initial prompt

        while retry_count <= max_retries:
            log_prefix = f"[{index + 1}/{total_items}][{entity_id}][Retry {retry_count}]"
            # Use original prompt on first try, modified prompt on retries
            prompt_to_use = current_prompt if current_prompt else original_prompt

            if not prompt_to_use:
                self.logger.error(f"[{entity_id}] Attempt {retry_count}: Prompt generation failed for {call_type}. Skipping.")
                return ValidationResult(False, None, None, None)

            attempt_id = f"{entity_id}-{call_type.value}-{retry_count}-{uuid.uuid4().hex[:6]}"
            # Stats: Log LLM attempt - Handled by LLMManager now, ensure it gets entity_id/call_type
            self.logger.info(f"[{entity_id}] Attempt {retry_count} (ID: {attempt_id}): Calling LLM for {call_type}...")
            # Call LLM - LLMManager handles API-level retries
            # LLMManager should associate the call stats with entity_id and call_type
            content, _ = await self.llm_manager.generate(
                prompt=prompt_to_use,
                system_message=system_message,
                model=model_override,
                error_file=error_file,
                entity_id=entity_id,
                call_type=call_type,
                attempt_id=attempt_id,
                is_json=is_json_output,
                prefix=f"[ {entity_id} - {call_type.value} - Attempt {retry_count} ]",
                debug_logger=self.logger
            )
            # Handle critical LLM failure (after LLMManager's retries)
            if content is None:
                self.logger.error(f"[{entity_id}] Attempt {retry_count}: LLM call failed definitively for {call_type}.")
                # Status might already be set by LLMManager, but ensure it's failed
                if self.stats_collector:
                     self.stats_collector.update_entity_status(entity_id, EntityStatus.FAILED_LLM_CALL, # Or a more specific LLM failure status?
                                                               error=f"LLM call failed after retries for {call_type.value}", end=False)
                return ValidationResult(False, None, None, None)

            # Validate the received content
            self.logger.debug(f"[{entity_id}] Attempt {retry_count}: Validating content for {call_type}...")
            relax_object_validation = self.framework_analyzer.is_relaxed_obj_validation()

            validation_result = self.spec_manager.sanitize_and_validate_content(content, relax_object_validation)

            # Stats: Log validation attempt
            if self.stats_collector:
                 error_list_for_stats = [e.get('message') for e in validation_result.errors] if validation_result.errors else None
                 val_attempt = ValidationAttempt(
                     timestamp=datetime.utcnow().isoformat(),
                     attempt_id=attempt_id,
                     is_valid=validation_result.is_valid,
                     errors=error_list_for_stats
                 )
                 self.stats_collector.add_validation_attempt(entity_id, val_attempt)

            # Check validation outcome
            if validation_result.is_valid:
                sanitized_content = validation_result.sanitized_content
                if sanitized_content == "<-|NOT_REQUIRED|->":
                    self.logger.info(f"[{entity_id}] Attempt {retry_count}: Content marked as <-|NOT_REQUIRED|-> for {call_type}.")
                    # Status updated in the main processing function
                    return ValidationResult(True, sanitized_content, None, validation_result.metadata)
                else:
                    self.logger.info(f"[{entity_id}] Attempt {retry_count}: Validation successful for {call_type}.")
                    return ValidationResult(True, sanitized_content, None, validation_result.metadata)

            # --- Validation Failed ---
            retry_count += 1
            error_messages_only = [e.get('message', 'Unknown') for e in (validation_result.errors or [])]
            error_str = "; ".join(error_messages_only)
            self.logger.warning(f"[{entity_id}] Attempt {retry_count-1}: Validation failed for {call_type}. Errors: {error_str}")

            if validation_result.errors:
                for error in validation_result.errors:
                    if error not in accumulated_errors:
                        accumulated_errors.append(error)
            # Check if max retries reached
            if retry_count > max_retries:
                self.logger.error(f"[{entity_id}] Max validation retries ({max_retries}) reached for {call_type}. Failing.")
                final_error_messages = [e.get('message', 'Unknown') for e in accumulated_errors]
                final_error_str = "; ".join(sorted(final_error_messages))
                if self.stats_collector:
                     self.stats_collector.update_entity_status(entity_id, EntityStatus.FAILED_VALIDATION,
                                                               error=f"Validation failed after {max_retries} retries: {final_error_str}", end=False)
                # Log the final invalid content attempt
                with open(error_file, "a") as f:
                    f.write(f"--- Final Invalid Content for {entity_id} ({call_type.value}) after {max_retries} retries ---\nErrors: {final_error_str}\nContent:\n{content}\n------\n")
                return ValidationResult(False, validation_result.sanitized_content, validation_result.errors, validation_result.metadata)

            # --- Prepare for Retry: Modify Prompt ---
            self.logger.info(f"[{entity_id}] Preparing retry {retry_count}/{max_retries} for {call_type}...")
            # Simple modification strategy: append error info
            formatted_errors_list = []
            sorted_errors = sorted(accumulated_errors, key=lambda x: x.get('message', ''))
            for i, error_info in enumerate(sorted_errors):
                message = error_info.get('message', 'Unknown Error')
                context = error_info.get('context')

                error_line = f"{i+1}. {message}"
                
                if context and context.strip() and context.strip() != 'N/A':
                    indented_context = "\n".join([f"    {line}" for line in context.strip().split("\n")])
                    error_line += f"\n  - This error occurred in the following snippet:\n{indented_context}"
                
                formatted_errors_list.append(error_line)
            
            # Join with an extra newline for better separation between errors
            formatted_errors = "\n\n".join(formatted_errors_list)
        
            modification_instruction = (
                "\n\n--- Previous Attempt Feedback ---\n"
                "The previous attempts failed validation. Here is a consolidated, unique list of all errors encountered so far. "
                "Please carefully review the OpenAPI 3.0 specification, the output format requirements, and correct ALL of the following errors in your next response.\n\n"
                f"ERRORS TO FIX:\n{formatted_errors}\n"
                "Do not make these same mistakes again\n"
                "--- End Feedback ---"
            )
            current_prompt = modification_instruction + '\n' + original_prompt
        return ValidationResult(False, validation_result.sanitized_content, validation_result.errors, validation_result.metadata)
    
    async def process_components(self, components, error_file):
        """Process schema components into OpenAPI components section"""
        if not components:
            self.logger.info("No components found to process.")
            return []
        component_items_with_index = list(enumerate(components.items()))
        total_components = len(component_items_with_index)

        self.logger.info(f"Processing {total_components} components using BatchProcessor "
                         f"(max_concurrency={self.batch_processor.max_concurrency or 'Unlimited'})...")

        # Define the function to process a single item (including index)
        async def single_component_processor(item_tuple_with_index: tuple):
            index, (component_name, component_info) = item_tuple_with_index
            # Pass index and total count to the processing function
            return await self.process_single_component(
                index=index,
                total_items=total_components,
                component_name=component_name,
                component_info=component_info,
                error_file=error_file
            )

        # Use the batch processor instance
        all_results = await self.batch_processor.process_in_batches(
            items=component_items_with_index, # Pass items with index
            processor_func=single_component_processor
        )

        self.logger.info(f"Component batch processing finished. Results count: {len(all_results)}")
        return all_results
    
    async def process_single_component(self,
                                       index: int,
                                       total_items: int,
                                       component_name: str,
                                       component_info: dict,
                                       error_file: str):
        """Process a single schema component"""
        print(f"[{index + 1}/{total_items}] Starting Component: {component_name}...", flush=True)
        if self.skip_components:
            return None, None
        entity_id = None
        if self.stats_collector:
            metadata_for_stats = {
                'path': component_info.get('path'),
                'qualifiedName': component_info.get('qualifiedName'),
                'is_interface': component_info.get('is_interface', False)
            }
            discovery_info = component_info.get('discovery_info', {})
            
            # 1. ADD DI PARENT INTERFACE FQN TO STATS METADATA
            if 'implemented_interface' in discovery_info:
                metadata_for_stats['implemented_interface'] = discovery_info['implemented_interface']

            entity_id = self.stats_collector.start_entity(
                EntityType.SERIALIZER,
                component_name,
                metadata=metadata_for_stats
            )
            
            # Add tag for DI-discovered components
            if discovery_info.get('di_discovered'):
                self.stats_collector.add_entity_tag(entity_id, "di_discovered")

            self.logger.info(f"Processing Component [{entity_id}]: {component_name} ...")
        result_status = "FAILED"
        try:
            # Generate prompt for the component
            def get_prompt():
                return self.prompt_manager.create_component_prompt(component_name, component_info, self.spec_manager._schema_name_to_fqn_map)
            system_prompt = self.prompt_manager.get_component_system_message()

            validation_result = await self._generate_and_validate_with_retry(
                    prompt_func=get_prompt,
                    system_message=system_prompt,
                    model_override=self.spec_model_name,
                    entity_id=entity_id,
                    call_type=LLMCallType.SERIALIZER_SCHEMA,
                    error_file=error_file,
                    index=index,
                    total_items=total_items,
                    is_json_output=False
                )
            validated_content = validation_result.sanitized_content
            is_success = validation_result.is_valid
            validation_metadata = validation_result.metadata

            # else:
            #validated_content, is_success =None, False
            if not is_success:
                if self.force_add_components:
                    self.logger.warning(f"[{entity_id}] Component {component_name} failed validation, but proceeding to add due to --force-add-components flag.")
                else:
                    self.logger.error(f"[{entity_id}] Component {component_name} failed validation. Skipping addition. Use --force-add-components to override.")
                    # Status already set to FAILED_VALIDATION in retry wrapper
                    result_status = "FAILED (Validation)"
                    return None, None
                
            if validated_content is None:
                 # Error status should have been set within the wrapper or LLMManager
                 self.logger.error(f"[{entity_id}] Failed to get validated content for component {component_name} after retries.")
                 result_status = "FAILED (Validation/LLM)"
                 return None, None # Indicate failure
            elif validated_content == "<-|NOT_REQUIRED|->":
                 result_status = "SKIPPED (Not Required)"
                 self.logger.info(f"[{entity_id}] Component {component_name} marked as not required.")
                 if self.stats_collector: self.stats_collector.update_entity_status(entity_id, EntityStatus.IGNORED, error="Component marked as not required")
                 return None, None # Indicate skipped

            self.logger.debug(f"[{entity_id}] Component YAML validated for {component_name}.")
            add_results = self.spec_manager.add_component_schema(
                component_name_context=component_name,
                yaml_content_str=validated_content,
                validation_metadata=validation_metadata
            )

            if add_results:
                schema_count = len(add_results)
                self.stats_collector.add_entity_tag(entity_id, f"schemas_generated:{schema_count}")

                for res in add_results:
                        status = res.get('status')
                        if status != 'added_new':
                            # Add general tag if not a simple new add
                            self.stats_collector.add_entity_tag(entity_id, "same_name_encountered")
                            
                            # Store detailed conflict info
                            conflict_info = {
                                "schema_name": res.get('original_name'),
                                "resolution": status,
                                "conflicting_fqn": res.get('conflict_fqn', 'N/A'),
                                "final_name": res.get('final_name')
                            }
                            # Get the entity from the collector to append details
                            entity_stats = self.stats_collector._entity_map.get(entity_id)
                            if entity_stats:
                                entity_stats.name_conflict_details.append(conflict_info)

                        # Add specific tags based on resolution
                        if status == 'collision_renamed':
                            self.stats_collector.add_entity_tag(entity_id, "name_collision")
                        elif status == 'duplicate_upgraded':
                            self.stats_collector.add_entity_tag(entity_id, "duplicate_upgraded")

                self.logger.info(f"[{entity_id}] Successfully processed and added schema(s) for {component_name}.")
                if is_success:
                    if self.stats_collector: self.stats_collector.update_entity_status(entity_id, EntityStatus.SUCCESS)
                result_status = "SUCCESS"
                return component_name, validated_content
            else:
                error_msg = f"Failed to add component schema(s) for {component_name}..."
                self.logger.error(f"[{entity_id}] {error_msg}")
                if self.stats_collector: self.stats_collector.update_entity_status(entity_id, EntityStatus.FAILED_SCHEMA, error=error_msg)
                result_status = "FAILED (Spec Add)"
                return None, None
            
        except Exception as e:
            self.logger.error(f"Error processing component {component_name}: {e}")
            if self.stats_collector and entity_id:
                self.stats_collector.update_entity_status(
                    entity_id,
                    EntityStatus.FAILED_UNKNOWN,
                    error=str(e),
                    error_type=type(e).__name__
                )

            result_status = f"FAILED (Exception: {type(e).__name__})"
            return None, None
            
        finally:
            # --- Direct Console Output End ---
            print(f"[{index + 1}/{total_items}] Finished Component: {component_name} ({result_status})", flush=True)
    
    async def process_endpoints(self, endpoints, error_file):
        if not endpoints:
            self.logger.info("No endpoints found to process.")
            return []

        # Prepare items with index: [(index, endpoint_dict), ...]
        endpoint_items_with_index = list(enumerate(endpoints))
        total_endpoints = len(endpoint_items_with_index)

        self.logger.info(f"Processing {total_endpoints} endpoints using BatchProcessor "
                        f"(max_concurrency={self.batch_processor.max_concurrency or 'Unlimited'})...")

        # Define the function to process a single endpoint item (including index)
        # This function will be called concurrently by the BatchProcessor
        async def single_endpoint_processor(item_tuple_with_index: tuple):
            index, endpoint_item = item_tuple_with_index
            # Call the actual worker function, passing the index and total count
            return await self.process_single_endpoint(
                index=index,
                total_items=total_endpoints,
                endpoint=endpoint_item,
                error_file=error_file          # Captured from outer scope
            )

        # Use the batch processor instance.
        # process_in_batches handles creating batches, running them with controlled
        # concurrency via the semaphore initialized in BatchProcessor, and gathering results.
        all_results = await self.batch_processor.process_in_batches(
            items=endpoint_items_with_index,    # Pass the list of (index, item) tuples
            processor_func=single_endpoint_processor # Pass the async function defined above
            # batch_size defaults to the value set in BatchProcessor.__init__
        )

        # Log completion and summary
        self.logger.info(f"Endpoint batch processing finished. Processed {len(all_results)} items.")
        successful_results = [res for res in all_results if res is not None]
        failed_count = total_endpoints - len(successful_results)
        self.logger.info(f"Successfully generated spec sections for {len(successful_results)} endpoints.")
        if failed_count > 0:
            self.logger.warning(f"{failed_count} endpoints failed or were skipped during processing.")

        return all_results
    
    async def process_single_endpoint(self,
                                      index: int,
                                      total_items: int,
                                      endpoint: dict,
                                      error_file: str):
        """Process a single endpoint"""
        url = endpoint.get("url", {}).get("url", "")
        method = endpoint.get("method", "").lower()
        endpoint_id = f"{url}:{method}"
        print(f"[{index + 1}/{total_items}] Starting Endpoint: {method.upper()} {url}...", flush=True)
        # Track the entity in stats collector
        entity_id = None
        if self.stats_collector:
            entity_id = self.stats_collector.start_entity(
                EntityType.ENDPOINT,
                endpoint_id,
                metadata={
                    "url": url,
                    "method": method,
                    "path": endpoint.get("path"),
                    "view": endpoint.get("view"),
                    "function": endpoint.get("function"),
                    "is_viewset": endpoint.get("is_viewset", False)
                }
            )
            self.logger.info(f"Processing Endpoint: {endpoint_id}")

        result_status = "FAILED" # Default status for logging end message
        should_ignore = False
        try:
            # 1. Get the initial context for the endpoint
            self.logger.debug(f"[{endpoint_id}] Getting initial context...")
            initial_endpoint_context = self.framework_analyzer.get_endpoint_context(endpoint)
            if not initial_endpoint_context or not initial_endpoint_context.get('handler', {}).get('code'):
                self.logger.warning(f"[{endpoint_id}] Could not get initial context or handler code. Skipping.")
                if self.stats_collector and entity_id:
                    self.stats_collector.update_entity_status(entity_id, EntityStatus.FAILED_CONTEXT, error="Missing initial context or handler code")
                return None
            
            self.logger.debug(f"[{endpoint_id}] Optimizing initial context before asking for missing symbols...")
            optimized_initial_context = self.framework_analyzer.optimize_context(initial_endpoint_context)
            
            # 2. Generate prompt to identify missing symbols
            system_prompt = self.prompt_manager.get_component_system_message()
            
            if not self.skip_missing_context:
                self.logger.debug(f"[{endpoint_id}] Creating prompt for missing symbols...")
                missing_symbols_prompt = self.prompt_manager.create_missing_symbols_prompt(endpoint, optimized_initial_context)

                # 3. Get missing symbols using LLM
                self.logger.debug(f"[{endpoint_id}] Calling LLM to identify missing symbols...")
                missing_symbols_response, _ = await self.llm_manager.generate(
                    prompt=missing_symbols_prompt,
                    system_message=system_prompt,
                    model=self.context_model_name,
                    error_file=error_file,
                    entity_id=entity_id,
                    call_type=LLMCallType.ENDPOINT_EXTRA_CODE,
                    is_json=True,
                    prefix=f"[ Endpoint: {endpoint_id} - Find Missing ]",
                    debug_logger=self.logger
                )

                full_endpoint_context = optimized_initial_context # Start with initial context
                if missing_symbols_response:
                    self.logger.debug(f"[{endpoint_id}] Parsing LLM response for missing symbols...")
                    try:
                        # Let Framework Analyzer parse the response (needs implementation)
                        required_symbols = self.framework_analyzer.parse_missing_symbols_response(missing_symbols_response)
                        if required_symbols:
                            self.logger.debug(f"[{endpoint_id}] Identified {len(required_symbols)} required symbols. Fetching missing context...")
                            # Let Framework Analyzer fetch the code and augment the context (needs implementation)
                            full_endpoint_context = self.framework_analyzer.get_missing_context(
                                initial_context=optimized_initial_context,
                                required_symbols=required_symbols
                            )

                            # Track extra code fetched
                            if self.stats_collector and entity_id:
                                symbol_names = [s.get("name", "unknown") for s in required_symbols]
                                self.stats_collector.track_extra_code(entity_id, symbol_names)
                                self.logger.debug(f"[{endpoint_id}] Tracked extra code: {symbol_names}")
                        else:
                            self.logger.debug(f"[{endpoint_id}] LLM indicated no missing symbols required.")

                    except Exception as parse_err:
                        self.logger.error(f"[{endpoint_id}] Error parsing missing symbols response or getting context: {parse_err}", exc_info=True)
                        # Proceed with initial context, but log the error
                        if self.stats_collector and entity_id:
                            self.stats_collector.update_entity_status(
                                entity_id,
                                EntityStatus.PARSE_MISSING_SYMBOLS,
                                error=str(parse_err),
                                error_type=type(parse_err).__name__
                            )
                else:
                    self.logger.debug(f"[{endpoint_id}] LLM did not return missing symbols response. Proceeding with initial context.")
            else:
                full_endpoint_context = optimized_initial_context

            # ---> 6. Optimize the Context <---
            self.logger.debug(f"[{endpoint_id}] Optimizing endpoint context...")
            final_optimized_context = self.framework_analyzer.optimize_context(full_endpoint_context)
            # 4. Generate request section
            self.logger.info(f"[{entity_id}] Processing Request section...")
            def get_request_prompt():
                return self.prompt_manager.create_endpoint_request_prompt(endpoint, final_optimized_context, self.spec_manager._schema_name_to_fqn_map, skip_components=self.skip_components)

            validation_result = await self._generate_and_validate_with_retry(
                prompt_func=get_request_prompt, system_message=system_prompt,
                model_override=self.spec_model_name,
                entity_id=entity_id, call_type=LLMCallType.ENDPOINT_REQUEST,
                error_file=error_file, index=index, total_items=total_items # Pass index/total
            )
            if isinstance(validation_result, ValidationResult):
                request_result_yaml = validation_result.sanitized_content
                is_success_req = validation_result.is_valid
                validation_metadata = validation_result.metadata
            else:
                # Fallback for old format
                (request_result_yaml, is_success_req)  = validation_result
                validation_metadata = None

            final_request_yaml=None
            if request_result_yaml == "<-|NOT_REQUIRED|->":
                 self.logger.info(f"[{entity_id}] Request section explicitly marked as <-|NOT_REQUIRED|->.")
                 # If request isn't required, we might still process response.
                 # Set flag to potentially ignore endpoint later if response also fails/isn't required.
                 should_ignore = True # Mark potential ignore
                 final_request_yaml = request_result_yaml # Keep marker to signal add_path_operation
                 request_succeeded = True # Treat "not required" as a form of success for this part
            elif request_result_yaml is not None and is_success_req:
                 self.logger.info(f"[{entity_id}] Request section successfully validated.")
                 final_request_yaml = request_result_yaml
                 request_succeeded = True
            else:
                 # Failed validation after retries
                 self.logger.error(f"[{entity_id}] Failed to get validated request YAML after retries.")
                 # Status FAILED_YAML/FAILED_VALIDATION set by retry wrapper
                 request_succeeded = False
                 final_request_yaml = request_result_yaml
            
            # 5. Generate response section
            self.logger.info(f"[{entity_id}] Processing Response section...")
            def get_response_prompt():
                return self.prompt_manager.create_endpoint_response_prompt(endpoint, final_optimized_context, self.spec_manager._schema_name_to_fqn_map, skip_components=self.skip_components)

            validation_result = await self._generate_and_validate_with_retry(
                prompt_func=get_response_prompt, system_message=system_prompt,
                model_override=self.spec_model_name,
                entity_id=entity_id, call_type=LLMCallType.ENDPOINT_RESPONSE,
                error_file=error_file, index=index, total_items=total_items # Pass index/total
            )
            if isinstance(validation_result, ValidationResult):
                response_result_yaml = validation_result.sanitized_content
                is_success_res = validation_result.is_valid
                validation_metadata = validation_result.metadata
            else:
                # Fallback for old format
                (response_result_yaml, is_success_res)  = validation_result
                validation_metadata = None

            final_response_yaml=None
            if response_result_yaml == "<-|NOT_REQUIRED|->":
                self.logger.info(f"[{entity_id}] Response section explicitly marked as <-|NOT_REQUIRED|->.")
                should_ignore = True # Mark potential ignore
                final_response_yaml = response_result_yaml
                response_succeeded = True # Treat as success for this part
            elif response_result_yaml is not None and is_success_res:
                self.logger.info(f"[{entity_id}] Response section successfully validated.")
                final_response_yaml = response_result_yaml
                response_succeeded = True
            else:
                 # Failed validation after retries
                 self.logger.error(f"[{entity_id}] Failed to get validated response YAML after retries.")
                 # Status set by retry wrapper
                 response_succeeded = False
                 final_response_yaml = response_result_yaml
            
            # 6. Add the endpoint to the OpenAPI spec
            if should_ignore:
                result_status = "SKIPPED (Not Required)"
                self.logger.info(f"[{entity_id}] Endpoint processing resulted in <-|NOT_REQUIRED|->. Skipping addition.")
                if self.stats_collector: self.stats_collector.update_entity_status(entity_id, EntityStatus.IGNORED, error="Request or Response marked as not required")
                return None # Skip

            # Scenario 2: At least one part succeeded validation
            elif request_succeeded or response_succeeded:
                is_fully_successful = request_succeeded and response_succeeded
                final_status = EntityStatus.SUCCESS if is_fully_successful else EntityStatus.PARTIAL_SUCCESS
                result_status_log = "SUCCESS" if is_fully_successful else "PARTIAL SUCCESS"


                self.logger.info(f"[{entity_id}] Attempting to add potentially partial path operation (Request Success: {request_succeeded}, Response Success: {response_succeeded})...")
                add_success = self.spec_manager.add_path_operation(
                    path=url, method=method,
                    request_yaml_str=final_request_yaml, # Pass None if validation failed
                    response_yaml_str=final_response_yaml # Pass None if validation failed
                )

                if add_success:
                    # Even partial success is logged as SUCCESS overall for the endpoint entity
                    result_status = "SUCCESS" + (" (Partial)" if not (request_succeeded and response_succeeded) else "")
                    self.logger.info(f"[{entity_id}] Successfully added path operation ({result_status_log}).")
                    if self.stats_collector: self.stats_collector.update_entity_status(entity_id, final_status)
                    return {"url": url, "method": method}
                else:
                    error_msg = "Failed to add path operation to spec manager."
                    result_status = "FAILED (Spec Add)"
                    self.logger.error(f"[{entity_id}] {error_msg}")
                    # If adding fails even with partial data, mark as FAILED_SPEC_ADD
                    if self.stats_collector: self.stats_collector.update_entity_status(entity_id, EntityStatus.FAILED_SPEC_ADD, error=error_msg)
                    return None

            # Scenario 3: Both parts failed validation
            else:
                self.logger.error(f"[{entity_id}] Both request and response sections failed validation after retries. Skipping endpoint.")
                # The status (FAILED_YAML/FAILED_VALIDATION) should have been set by the last failing retry call.
                # No need to update status again here unless we want a specific "BOTH_FAILED" status.
                result_status = "FAILED (Validation/LLM)"
                return None
            
        except Exception as e:
            self.logger.error(f"[{entity_id}] Unhandled error processing endpoint: {e}", exc_info=True)
            if self.stats_collector and entity_id: self.stats_collector.update_entity_status(entity_id, EntityStatus.FAILED_UNKNOWN, error=str(e), error_type=type(e).__name__)
             # Log to error file
            with open(error_file, "a") as f:
                 f.write(f"--- Unhandled Exception for {endpoint_id} [{entity_id}] ---\n")
                 traceback.print_exc(file=f)
                 f.write("------\n")
            result_status = f"FAILED (Exception: {type(e).__name__})"
            return None

        finally:
            # --- Direct Console Output End ---
            print(f"[{index + 1}/{total_items}] Finished Endpoint: {method.upper()} {url} ({result_status})", flush=True)
    
    async def generate_profile_specs_if_applicable(self, output_path: str):
        # Spring-specific capability: @Profile annotation support. Not part of the
        # common interface because profiles are a Spring concept with no equivalent
        # in other frameworks.
        if not hasattr(self.framework_analyzer, 'get_profile_metadata'):
            self.logger.debug("Framework does not support profile specifications")
            return []
        
        try:
            # Get profile metadata from the framework analyzer
            profile_metadata = self.framework_analyzer.get_profile_metadata()
            if not profile_metadata or not profile_metadata.get("profiles"):
                self.logger.info("No profiles detected for spec generation")
                return []
            
            # Delegate to spec manager to generate profile-specific specs
            self.logger.info("Generating profile-specific specifications...")
            return self.spec_manager.generate_profile_specific_specs(profile_metadata, output_path)
            
        except Exception as e:
            self.logger.error(f"Error generating profile specs: {e}", exc_info=True)
            return []
        
async def generate_api_docs(args):
    """Main function to generate API documentation"""
    project_path = os.path.abspath(args.directory)
    language = args.language
    framework = args.framework
    
    spec_model_arg = args.spec_model
    context_model_arg = args.context_model
    repo_name = os.path.basename(project_path)
    skip_components = args.skip_components
    skip_missing_context = args.skip_missing_context
    force_add_components = args.force_add_components
    
    # Create output directory
    spec_model_name_safe = (spec_model_arg or "default_spec").replace('/', '_').replace('.', '-')
    context_model_name_safe = (context_model_arg or "default_context").replace('/', '_').replace('.', '-')
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir_name = f"{timestamp}_{spec_model_name_safe}_{context_model_name_safe}_{repo_name}"

    speculate_folder = os.path.join(".speculate_logs", run_dir_name)
    output_path = os.path.join(project_path, speculate_folder)

    Path(output_path).mkdir(parents=True, exist_ok=True)

    # Configure logging with the same approach as original implementation
    configure_logging_directory(project_path, speculate_folder)
    
    debug_logger.info(f"Starting API documentation generation for {project_path}")
    debug_logger.info(f"Output will be saved to: {output_path}")
    debug_logger.debug(f"Parameters: language={language}, framework={framework}")
    
    try:
        # Create the appropriate code analyzer based on language
        if language.lower() == "python":
            code_analyzer = PythonCodeAnalyzer()
            if framework.lower() == "django":
                django_settings_module = getattr(args, 'django_settings_module', None)
                django_explicit_settings_file = getattr(args, 'django_explicit_settings_file', None)
                django_explicit_urls_file = getattr(args, 'django_explicit_urls_file', None)
                django_use_static_endpoints = getattr(args, 'django_use_static_endpoints', False)

                debug_logger.info(f"Instantiating DjangoAnalyzer with:")
                debug_logger.info(f"  project_path: {project_path}")
                debug_logger.info(f"  settings_module_str: {django_settings_module}")
                debug_logger.info(f"  explicit_settings_file_path: {django_explicit_settings_file}")
                debug_logger.info(f"  explicit_urls_file_path: {django_explicit_urls_file}")
                debug_logger.info(f"  use_dynamic_endpoint_extraction: {not django_use_static_endpoints}")

                framework_analyzer = DjangoAnalyzer(
                    code_analyzer=code_analyzer,
                    project_path=project_path,
                    use_dynamic=not django_use_static_endpoints,
                    logger=debug_logger,
                    settings_module_str=django_settings_module,
                    explicit_settings_file_path=django_explicit_settings_file,
                    explicit_urls_file_path=django_explicit_urls_file
                )
            else:
                raise ValueError(f"Unsupported Python framework: {framework}")
        elif language.lower() == "java":
            code_analyzer = JavaCodeAnalyzer(logger=debug_logger, multi_module=args.multi_module, java_module_paths=args.java_module_paths, java_source_root=args.java_source_root)
            if framework.lower() == "jersey":
                framework_analyzer = JerseyFrameworkAnalyzer(code_analyzer, project_path, logger=debug_logger)
            elif framework.lower() == "spring":
                framework_analyzer = SpringBootFrameworkAnalyzer(code_analyzer, project_path, logger=debug_logger)
            else:
                raise ValueError(f"Unsupported Java framework: {framework}")
        else:
            raise ValueError(f"Unsupported language: {language}")
        
        # Create supporting components
        prompt_manager = PromptManager(framework_analyzer)
        batch_processor = BatchProcessor(
            default_batch_size=args.batch_size,
            max_concurrency=args.concurrency,
            request_spacing=2,
            adaptive_spacing=True,
            min_spacing=1,
            max_spacing=3
        )
        spec_manager = OpenAPISpecManager(repo_name=os.path.basename(project_path))
        
        # Create stats collector
        stats_collector = StatsCollector(
            repo_name=os.path.basename(project_path),
            output_dir=os.path.join(output_path, "stats"),
            logger=debug_logger,
        )
        
        # Create LLM manager with stats collector
        llm_manager = LLMManager(
            max_retries=args.llm_max_retries,
            logger=debug_logger,
            stats_collector=stats_collector
        )
        
        # Create the spec generator
        spec_generator = SpecGenerator(
            code_analyzer=code_analyzer,
            framework_analyzer=framework_analyzer,
            prompt_manager=prompt_manager,
            llm_manager=llm_manager,
            spec_manager=spec_manager,
            batch_processor=batch_processor,
            stats_collector=stats_collector,
            spec_model_name=spec_model_arg,
            context_model_name=context_model_arg,
            logger=debug_logger,
            skip_components = skip_components,
            skip_missing_context=skip_missing_context,
            force_add_components=force_add_components,
            validation_max_retries=args.validation_max_retries,
            framework=framework
        )
        
        # Generate the spec
        spec_path = await spec_generator.generate_spec(project_path, output_path)
        
        debug_logger.info(f"API documentation generation complete. Specification saved to {spec_path}")

        if framework == "spring":
            try:
                profile_specs = await spec_generator.generate_profile_specs_if_applicable(output_path)
                if profile_specs:
                    debug_logger.info(f"Generated {len(profile_specs)} profile-specific specifications")
                    console_logger.info(f"Generated {len(profile_specs)} profile-specific OpenAPI specs:")
                    for profile_spec_path in profile_specs:
                        console_logger.info(f"  - {profile_spec_path}")
            except Exception as e:
                # Log error but don't fail the main generation
                debug_logger.error(f"Error in profile spec generation: {e}", exc_info=True)
                console_logger.warning(f"Warning: Could not generate profile-specific specs: {e}")
            
        return spec_path
        
    except Exception as e:
        debug_logger.error(f"Error generating API documentation: {str(e)}", exc_info=True)
        console_logger.error(f"Error: {str(e)}")
        raise

def main():
    """Command-line entry point"""
    current_script_path = os.path.abspath(__file__)
    current_script_dir = os.path.dirname(current_script_path)
    project_root_dir = os.path.dirname(current_script_dir) 
    dotenv_path = os.path.join(project_root_dir, '.env')

    # Load the .env file if it exists
    loaded = load_dotenv(dotenv_path=dotenv_path, verbose=True) # verbose logs which file is loaded

    if loaded:
        print(f"Loaded environment variables from: {dotenv_path}")
    else:
        print(f"Warning: '.env' file not found at {dotenv_path}. Proceeding with system environment variables.")

    parser = argparse.ArgumentParser(description="Generate OpenAPI documentation from code")
    parser.add_argument("directory", help="Directory path to process")
    parser.add_argument("--language", "-l", default="python", choices=["python", "java"], 
                      help="Programming language of the project")
    parser.add_argument("--framework", "-f", default="django", 
                      choices=["django", "spring", "jersey"],
                      help="Web framework used in the project")
    parser.add_argument(
        "--spec-model",
        help="User-facing model name (e.g., o4_mini, gpt_4_1, gemini-1.5-pro-latest) to use for generating spec components (schemas, requests, responses)."
             " If not provided, the default model configured in the environment (.env) or LLMManager will be used."
    )
    parser.add_argument(
        "--context-model",
        help="User-facing model name to use for identifying missing context/symbols."
             " If not provided, the default model will be used."
    )
    parser.add_argument("--batch-size", type=int, default=30, help="Batch size for concurrent processing")
    parser.add_argument("--concurrency", type=int, default=5, help="Max concurrent LLM calls")
    parser.add_argument(
        "--llm-max-retries",
        type=int,
        default=3,
        help="Maximum number of API-level retries for each LLM call."
    )
    parser.add_argument(
        "--validation-max-retries",
        type=int,
        default=2,
        help="Maximum number of validation/regeneration retries after invalid OpenAPI output."
    )
    parser.add_argument(
        "--django-settings-module",
        help="For Django projects: The Python path to your settings module (e.g., 'myproject.settings.development')."
             " Used by the analyzer to find ROOT_URLCONF and by the runtime script.",
        default=None
    )
    parser.add_argument(
        "--django-explicit-settings-file",
        help="For Django projects: The direct file system path to the specific Django settings file "
             "(e.g., '/path/to/project/settings/development.py') that contains ROOT_URLCONF.",
        default=None
    )
    parser.add_argument(
        "--django-explicit-urls-file",
        help="For Django projects: The direct file system path to your root urls.py file "
             "(e.g., '/path/to/project/myapp/urls.py'). Highest precedence for URL discovery.",
        default=None
    )
    parser.add_argument(
        "--django-use-static-endpoints",
        action="store_true",
        help="For Django projects: use the best-effort static endpoint parser instead of runtime Django URL introspection. Prefer the default dynamic mode when possible.",
    )
    parser.add_argument(
        "--multi-module",
        action="store_true",
        help="Enable multi-module analysis for Java projects. The input directory should be the project root."
    )
    
    parser.add_argument(
        "--skip-components",
        action="store_true",
        help="Skip the component schema generation and processing steps."
    )

    parser.add_argument(
        "--skip-missing-context",
        action="store_true", 
        help="Skip the extra msissing context call."
    )
    parser.add_argument(
        "--force-add-components",
        action="store_false",
        help="Add components to the spec even if they fail validation after all retries."
    )
    parser.add_argument(
        "--java-source-root",
        help="Optional: For Java multi-module projects, specify the root directory of the source code. "
             "Defaults to the main project directory. Use this to override the default if needed.",
        default=None
    )
    parser.add_argument(
        "--java-module-paths",
        help="For Java multi-module projects: Manually provide a colon-separated list of paths to the 'classes' directories."
             " This bypasses automatic module discovery.",
        default=None
    )
    args = parser.parse_args()
        
    try:
        console_logger.info("Starting API documentation generation")
        debug_logger.info("Starting API documentation generation")
        spec_path = asyncio.run(generate_api_docs(args))
        console_logger.info(f"OpenAPI specification generated successfully at: {spec_path}")
    except KeyboardInterrupt:
        console_logger.error("Operation cancelled by user")
        sys.exit(1)
    except Exception as e:
        console_logger.error(f"Fatal error: {str(e)}")
        if debug_logger:
             debug_logger.error("Fatal error during execution:", exc_info=True)
        else:
             traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
