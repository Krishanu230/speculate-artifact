from datetime import datetime
from enum import Enum
import json
import re
import traceback
from typing import Optional, Dict, Any, List, Set, Tuple
from abc import ABC, abstractmethod
import os
import logging
import asyncio
import uuid
import aiofiles
import httpcore
import httpx
from dataclasses import dataclass, field
from openai import AsyncAzureOpenAI 

import openai

from google import genai
# import google.generativeai as genai
from google.genai import types
# from google.generativeai import types
from google.api_core import exceptions as google_exceptions

from azure.ai.inference.aio import ChatCompletionsClient           # async
from azure.ai.inference.models import SystemMessage, UserMessage   # message types
from azure.core.credentials import AzureKeyCredential


from stats import LLMCallType, LLMRequestStats, StatsCollector


def _clean_env_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        cleaned = cleaned[1:-1].strip()
    return cleaned


@dataclass
class LLMRequest:
    """Represents a structured request to any LLM provider"""
    prompt: str
    system_message: Optional[str] = None
    model: Optional[str] = None
    temperature: float = 0.2
    max_tokens: Optional[int] = None
    is_json: bool = False
    seed: int = 18790  # Adding fixed seed
    metadata: Dict[str, Any] = field(default_factory=dict) 

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

class MessageRole(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

@dataclass
class ToolFunctionCall:
    name: str                # function name requested by the model
    arguments: str           # raw JSON string

@dataclass
class ToolCall:
    id: Optional[str]        # tool_call id (Azure may omit; we can synthesize upstream if needed)
    function: ToolFunctionCall

@dataclass
class ChatMessage:
    """Represents a single message in a chat conversation"""
    role: MessageRole
    content: str
    # Optional fields for tool messages
    tool_call_id: Optional[str] = None
    # Optional metadata for each message
    metadata: Dict[str, Any] = field(default_factory=dict)
    # NEW: assistant tool call requests (what the model is asking us to run)
    tool_calls: Optional[List[ToolCall]] = None


@dataclass
class LLMChatRequest:
    """
    Represents a chat-style request to any LLM provider.
    This extends the concept of LLMRequest to support multi-turn conversations.
    """
    messages: List[ChatMessage]
    model: Optional[str] = None
    temperature: float = 0.2
    max_tokens: Optional[int] = None
    is_json: bool = False
    seed: int = 18790
    # System message can still be provided separately for convenience
    # It will be prepended to messages if provided
    system_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

@dataclass
class LLMResponse:
    """Standardized response from any LLM provider"""
    content: str
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    model_used: str
    raw_response: Any = None
    finish_reason: Optional[str] = None
    reasoning_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None

class LLMError(Exception):
    def __init__(self, message: str, error_type: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.error_type = error_type
        self.original_error = original_error

class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        pass

    @abstractmethod
    def get_default_model(self) -> str:
        pass

@dataclass
class AzureConfig:
    """Holds configuration for a single Azure endpoint."""
    name: str
    endpoint: str
    api_key: str
    api_version: str

class DeepSeekInferenceProvider(LLMProvider):
    """
    Async provider for DeepSeek models served via Azure AI Inference.
    Hard‑codes a single endpoint/deployment (good enough for a PoC).
    """
    def __init__(self) -> None:
        self.endpoint = _clean_env_value(os.getenv("DEEPSEEK_ENDPOINT", "")) or ""
        self.api_key = _clean_env_value(os.getenv("DEEPSEEK_API_KEY", "")) or ""
        self.model_name = _clean_env_value(os.getenv("DEEPSEEK_MODEL_NAME", "DeepSeek-R1-0528")) or "DeepSeek-R1-0528"
        self.api_version = "2024-05-01-preview"

        if not self.api_key:
            logging.error("DeepSeek provider not initialised: missing DEEPSEEK_API_KEY")
            self.is_available = False
            return

        self.client = ChatCompletionsClient(                 # async client
            endpoint=self.endpoint,
            credential=AzureKeyCredential(self.api_key),
            api_version=self.api_version
        )
        self.is_available = True
        logging.info("DeepSeekInferenceProvider ready.")

    # ------------------------------------------------------------------ #
    # LLMProvider interface
    # ------------------------------------------------------------------ #
    def get_default_model(self) -> str:
        return self.model_name

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.is_available:
            raise LLMError("DeepSeek provider unavailable", "config_error")

        # --- build Azure‑Inference style messages ---------------------
        msgs: List[Any] = []
        if request.system_message:
            msgs.append(SystemMessage(content=request.system_message))
        msgs.append(UserMessage(content=request.prompt))

        # --- make the call (non‑streaming) ---------------------------
        try:
            result = await self.client.complete(
                messages=msgs,
                model=self.model_name,
                max_tokens=request.max_tokens or 2048,
                temperature=request.temperature,
                # honour JSON mode if requested
                response_format="json_object" if request.is_json else "text",
                seed=request.seed
            )
        except Exception as ex:
            # wrap any SDK / HTTP errors
            raise LLMError(f"Azure AI Inference error: {ex}", "api_error", ex)

        # --- flatten response ----------------------------------------
        choice = result.choices[0]                       # single completion
        usage  = result.usage                            # CompletionsUsage object

        return LLMResponse(
            content           = choice.message.content or "",
            total_tokens      = getattr(usage, "total_tokens",    0),
            prompt_tokens     = getattr(usage, "prompt_tokens",   0),
            completion_tokens = getattr(usage, "completion_tokens",0),
            model_used        = self.model_name,
            raw_response      = result,
            finish_reason     = choice.finish_reason
        )

class AzureProvider(LLMProvider):
    DEFAULT_MODEL = "gpt-4o-mini"
    UNSUPPORTED_TEMP_DEPLOYMENTS: Set[str] = {
        "o4-mini",
        "o1",
        "o3-mini",
        "gpt-5-nano"
    }

    def __init__(self):
        self.configurations: Dict[str, AzureConfig] = {}
        self.clients: Dict[str, AsyncAzureOpenAI] = {}
        # Map: user_model_name (lower) -> (config_name, deployment_name_on_azure)
        self.model_deployment_map: Dict[str, Tuple[str, str]] = {}
        self.default_model_name = _clean_env_value(os.getenv("AZURE_DEFAULT_MODEL_NAME")) # User-facing default name
        self.global_api_version_fallback = _clean_env_value(os.getenv("AZURE_API_VERSION_FALLBACK", "2024-05-01-preview")) or "2024-05-01-preview"

        self._load_client_configs()
        self._load_model_mappings()

        if not self.configurations:
            logging.error("AzureProvider: No client configurations loaded. Provider unusable.")
        elif not self.model_deployment_map:
            logging.warning("AzureProvider: No model mappings loaded (check AZURE_MODEL_MAP_* env vars). Provider might not function as expected.")
        else:
             # Validate default model name exists in the map
             if self.default_model_name:
                  normalized_default = self.default_model_name.lower().replace('-', '_').replace('.', '_')
                  if normalized_default not in self.model_deployment_map:
                       logging.warning(f"AzureProvider: Default model name '{self.default_model_name}' (normalized: '{normalized_default}') not found in model map. Defaulting may fail.")
                  else:
                       logging.info(f"AzureProvider: Default model set to '{self.default_model_name}'.")
             else:
                 logging.warning("AzureProvider: AZURE_DEFAULT_MODEL_NAME not set. Default model resolution will fail if no model is specified.")


    def _load_client_configs(self):
        """Loads endpoint/key configurations."""
        config_names_str = _clean_env_value(os.getenv("AZURE_CONFIG_NAMES"))
        if not config_names_str:
            logging.warning("AzureProvider: AZURE_CONFIG_NAMES not set.")
            return

        config_names = [_clean_env_value(name) for name in config_names_str.split(',')]
        config_names = [name for name in config_names if name]
        if not config_names: return

        loaded_configs = 0
        for name in config_names:
            endpoint = _clean_env_value(os.getenv(f"AZURE_ENDPOINT_{name}"))
            api_key = _clean_env_value(os.getenv(f"AZURE_API_KEY_{name}"))
            api_version = _clean_env_value(os.getenv(f"AZURE_API_VERSION_{name}", self.global_api_version_fallback))

            if endpoint and api_key:
                self.configurations[name] = AzureConfig(
                    name=name, endpoint=endpoint, api_key=api_key, api_version=api_version
                )
                logging.info(f"AzureProvider: Loaded client configuration '{name}'.")
                loaded_configs += 1
            else:
                logging.warning(f"AzureProvider: Missing endpoint/key for config '{name}'. Skipping.")

        if loaded_configs == 0:
            logging.error("AzureProvider: No valid client configurations could be loaded.")

    def _load_model_mappings(self):
        """Loads model name -> config/deployment mappings from env."""
        map_prefix = "AZURE_MODEL_MAP_"
        loaded_maps = 0
        for env_var, value in os.environ.items():
            if env_var.startswith(map_prefix):
                model_name_env = env_var[len(map_prefix):]
                # Normalize model name from env var (lower, replace separators with _)
                model_name_key = model_name_env.lower().replace('-', '_').replace('.', '_')

                if not model_name_key:
                    logging.warning(f"AzureProvider: Skipping invalid model map variable '{env_var}'.")
                    continue

                cleaned_value = _clean_env_value(value)
                if not cleaned_value or '/' not in cleaned_value:
                    logging.warning(f"AzureProvider: Invalid format for {env_var}='{value}'. Expected 'config_name/deployment_name'. Skipping map.")
                    continue

                config_name, deployment_name = cleaned_value.split('/', 1)
                config_name = _clean_env_value(config_name)
                deployment_name = _clean_env_value(deployment_name)

                # Validate that the referenced config_name was actually loaded
                if config_name not in self.configurations:
                    logging.warning(f"AzureProvider: Config '{config_name}' referenced in {env_var}='{value}' was not loaded or is invalid. Skipping map for '{model_name_key}'.")
                    continue

                if model_name_key in self.model_deployment_map:
                     logging.warning(f"AzureProvider: Duplicate mapping for model '{model_name_key}' (from {env_var}). Overwriting previous.")

                self.model_deployment_map[model_name_key] = (config_name, deployment_name)
                logging.info(f"AzureProvider: Mapped model '{model_name_key}' -> Config='{config_name}', Deployment='{deployment_name}'.")
                loaded_maps += 1

        if loaded_maps == 0:
            logging.warning("AzureProvider: No AZURE_MODEL_MAP_* variables found or loaded.")

    def _get_client(self, config_name: str) -> Optional[AsyncAzureOpenAI]:
        """Gets or creates an Azure client for the given configuration name."""
        if config_name in self.clients:
            return self.clients[config_name]

        if config_name not in self.configurations:
            logging.error(f"Attempted to get client for unknown Azure configuration: '{config_name}'")
            return None

        config = self.configurations[config_name]
        try:
            client = AsyncAzureOpenAI(
                azure_endpoint=config.endpoint,
                api_key=config.api_key,
                api_version=config.api_version
            )
            self.clients[config_name] = client # Cache the client
            logging.info(f"Created Azure client for configuration: '{config_name}'")
            return client
        except Exception as e:
            logging.error(f"Failed to create Azure client for configuration '{config_name}': {e}", exc_info=True)
            return None

    def get_default_model(self) -> str:
        """Returns the *user-facing* default model name."""
        return self.default_model_name or "" # Return empty if not set
    
    def resolve_deployment(self, requested_model_name: Optional[str]) -> Optional[Tuple[str, str, str]]:
         """
         Resolves a user-facing model name to its config name and deployment name.
         Returns: Tuple(config_name, deployment_name, resolved_model_name) or None
         """
         model_to_resolve = requested_model_name or self.default_model_name
         if not model_to_resolve:
              logging.error("AzureProvider: Cannot resolve deployment - no model requested and no default set.")
              return None

         # Normalize the requested/default name for map lookup
         normalized_key = model_to_resolve.lower().replace('-', '_').replace('.', '_')

         mapping = self.model_deployment_map.get(normalized_key)

         if mapping:
              config_name, deployment_name = mapping
              # Double-check config exists (should be guaranteed by load logic, but safer)
              if config_name not in self.configurations:
                   logging.error(f"AzureProvider: Mapped config '{config_name}' for model '{model_to_resolve}' not found. Resolution failed.")
                   return None
              return config_name, deployment_name, model_to_resolve # Return original name requested/defaulted
         else:
              logging.error(f"AzureProvider: Model name '{model_to_resolve}' (normalized: '{normalized_key}') not found in AZURE_MODEL_MAP_*. Cannot resolve deployment.")
              return None

    def _prepare_messages(self, request: LLMRequest) -> List[Dict[str, Any]]:
        messages = []
        if request.system_message:
            messages.append({"role": "system", "content": request.system_message})
        messages.append({"role": "user", "content": request.prompt})
        return messages

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generates content using a resolved deployment based on the requested model name."""
        if not self.configurations or not self.model_deployment_map:
             raise LLMError("AzureProvider is not properly configured (missing client configs or model maps).", "config_error")

        # Resolve the requested model name (e.g., "o4-mini") to config/deployment
        resolution = self.resolve_deployment(request.model)
        if not resolution:
             raise LLMError(f"Could not resolve Azure deployment for requested model: '{request.model or 'None specified'}'. Check mapping and defaults.", "config_error")

        config_name, deployment_to_use, resolved_model_name = resolution
        config = self.configurations[config_name] # We know this exists from resolve_deployment

        # Get or create the client for this configuration
        client = self._get_client(config_name)
        if not client:
            raise LLMError(f"Failed to get Azure client for configuration '{config_name}'.", "client_error")

        logging.debug(f"AzureProvider resolved '{resolved_model_name}' -> config='{config_name}', deployment='{deployment_to_use}'")

        try:
            messages = self._prepare_messages(request)
            completion_params = {
                "model": deployment_to_use,
                "messages": messages,
                "max_completion_tokens": request.max_tokens or 32000,
                "stream": False,
            }

            # Conditionally add temperature
            if deployment_to_use not in self.UNSUPPORTED_TEMP_DEPLOYMENTS:
                completion_params["temperature"] = request.temperature
                logging.debug(f"Included temperature ({request.temperature}) for deployment '{deployment_to_use}'.")
            else:
                logging.debug(f"Skipped temperature parameter for unsupported deployment '{deployment_to_use}'.")

            # Add optional params
            if request.seed is not None: completion_params["seed"] = request.seed
            if request.is_json: completion_params["response_format"] = {"type": "json_object"}

            completion = await client.chat.completions.create(**completion_params)
            # --- Response ---
            if not completion.choices:
                 raise LLMError("Azure API returned no choices.", "api_error", None)

            # Return the *user-facing model name* that was resolved
            # The actual Azure deployment used is logged above and could be added to metadata if needed
            reasoning_tokens_val: Optional[int] = None
            cached_tokens_val: Optional[int] = None
            if completion.usage:
                # Safely access nested completion_tokens_details
                completion_details = getattr(completion.usage, 'completion_tokens_details', None)
                if completion_details:
                    reasoning_tokens_val = getattr(completion_details, 'reasoning_tokens', None)

                # Safely access nested prompt_tokens_details
                prompt_details = getattr(completion.usage, 'prompt_tokens_details', None)
                if prompt_details:
                    cached_tokens_val = getattr(prompt_details, 'cached_tokens', None)

            return LLMResponse(
                 content=completion.choices[0].message.content or "",
                 total_tokens=completion.usage.total_tokens if completion.usage else 0,
                 prompt_tokens=completion.usage.prompt_tokens if completion.usage else 0,
                 completion_tokens=completion.usage.completion_tokens if completion.usage else 0,
                 model_used=resolved_model_name, # Report the name the user requested/defaulted to
                 raw_response=completion,
                 finish_reason=completion.choices[0].finish_reason,
                 reasoning_tokens=reasoning_tokens_val,
                 cached_tokens=cached_tokens_val
             )

        # Error handling remains largely the same, but logs can be more specific
        except openai.NotFoundError as e:
             logging.error(f"Azure deployment '{deployment_to_use}' (for model '{resolved_model_name}') not found on config '{config_name}'. Check deployment name and API version.", exc_info=True)
             raise LLMError(f"Azure deployment not found for config '{config_name}': {deployment_to_use}. Error: {e}", "config_error", e)
        except openai.BadRequestError as e:
             logging.error(f"Azure API Bad Request using config '{config_name}', deployment '{deployment_to_use}': {e}", exc_info=True)
             raise LLMError(f"Azure API Bad Request (config '{config_name}', check deployment/params/API version): {e}", "api_error", e)
        except openai.AuthenticationError as e:
             logging.error(f"Azure authentication failed for config '{config_name}' (Endpoint: {config.endpoint}). Check API key.", exc_info=True)
             raise LLMError(f"Azure authentication failed for config '{config_name}'. Error: {e}", "authentication_error", e)
        except (httpcore.ReadTimeout, httpx.ReadTimeout) as e:
             logging.warning(f"Azure request timed out for config '{config_name}', deployment '{deployment_to_use}'. Error: {e}")
             raise LLMError(f"Azure request timed out for config '{config_name}': {e}", "timeout", e)
        except openai.RateLimitError as e:
              logging.warning(f"Azure rate limit exceeded for config '{config_name}', deployment '{deployment_to_use}'. Error: {e}")
              raise LLMError(f"Azure rate limit exceeded for config '{config_name}': {e}", "rate_limit", e)
        except openai.APIConnectionError as e:
              logging.warning(f"Azure connection error for config '{config_name}' (Endpoint: {config.endpoint}). Error: {e}")
              raise LLMError(f"Azure connection error for config '{config_name}': {e}", "connection_error", e)
        except Exception as e:
            logging.error(f"Unexpected error in AzureProvider generate for model '{resolved_model_name}' (config '{config_name}', deployment '{deployment_to_use}'): {e}", exc_info=True)
            raise LLMError(f"Unexpected error in AzureProvider (model '{resolved_model_name}'): {e}", "unknown", e)

    def get_mapped_azure_model_names(self) -> List[str]:
         """Returns a list of user-facing model names mapped for Azure."""
         # Return the keys from the map (these are the normalized names)
         return list(self.model_deployment_map.keys())

    async def generate_with_chat(self, request: LLMChatRequest) -> LLMResponse:
        """
        Generates content using a chat-style conversation with Azure OpenAI.
        This properly maintains conversation history without flattening.
        """
        if not self.configurations or not self.model_deployment_map:
            raise LLMError("AzureProvider is not properly configured", "config_error")
        
        # Resolve deployment (reuse existing logic)
        resolution = self.resolve_deployment(request.model)
        if not resolution:
            raise LLMError(
                f"Could not resolve Azure deployment for model: '{request.model or 'None specified'}'",
                "config_error"
            )
        
        config_name, deployment_to_use, resolved_model_name = resolution
        
        # Get or create client
        client = self._get_client(config_name)
        if not client:
            raise LLMError(f"Failed to get Azure client for configuration '{config_name}'", "client_error")
        
        logging.debug(f"AzureProvider chat resolved '{resolved_model_name}' -> config='{config_name}', deployment='{deployment_to_use}'")
        
        try:
            # Build messages list for Azure OpenAI format
            messages = []
            
            # Add system message if provided
            if request.system_message:
                messages.append({"role": "system", "content": request.system_message})
            
            # Convert ChatMessage objects to Azure OpenAI format
            for msg in request.messages:
                if msg.role == MessageRole.SYSTEM:
                    messages.append({"role": "system", "content": msg.content})
                elif msg.role == MessageRole.USER:
                    messages.append({"role": "user", "content": msg.content})
                elif msg.role == MessageRole.ASSISTANT:
                    messages.append({"role": "assistant", "content": msg.content})
                elif msg.role == MessageRole.TOOL:
                    # Azure OpenAI uses 'tool' role for function responses
                    messages.append({
                        "role": "tool",
                        "content": msg.content,
                        "tool_call_id": msg.tool_call_id
                    })
            
            # Prepare completion parameters
            completion_params = {
                "model": deployment_to_use,
                "messages": messages,
                "max_completion_tokens": request.max_tokens or 32000,
                "stream": False,
            }
            
            # Conditionally add temperature
            if deployment_to_use not in self.UNSUPPORTED_TEMP_DEPLOYMENTS:
                completion_params["temperature"] = request.temperature
            
            # Add optional parameters
            if request.seed is not None:
                completion_params["seed"] = request.seed
            if request.is_json:
                completion_params["response_format"] = {"type": "json_object"}
            
            # Make the API call
            completion = await client.chat.completions.create(**completion_params)
            
            # Process response
            if not completion.choices:
                raise LLMError("Azure API returned no choices.", "api_error", None)
            
            return LLMResponse(
                content=completion.choices[0].message.content or "",
                total_tokens=completion.usage.total_tokens if completion.usage else 0,
                prompt_tokens=completion.usage.prompt_tokens if completion.usage else 0,
                completion_tokens=completion.usage.completion_tokens if completion.usage else 0,
                model_used=resolved_model_name,
                raw_response=completion,
                finish_reason=completion.choices[0].finish_reason
            )
            
        except openai.NotFoundError as e:
            logging.error(f"Azure deployment '{deployment_to_use}' not found", exc_info=True)
            raise LLMError(f"Azure deployment not found: {e}", "config_error", e)
        except openai.BadRequestError as e:
            logging.error(f"Azure API Bad Request: {e}", exc_info=True)
            raise LLMError(f"Azure API Bad Request: {e}", "api_error", e)
        except Exception as e:
            logging.error(f"Unexpected error in generate_with_chat: {e}", exc_info=True)
            raise LLMError(f"Unexpected error: {e}", "unknown", e)
        
class GeminiProvider(LLMProvider):
    """
    LLMProvider implementation for Google Gemini models via Vertex AI.
    Uses Application Default Credentials (ADC) and explicit client initialization
    following the google-genai library documentation.
    Requires 'google-generativeai' library. Uses the native async client methods.
    """
    DEFAULT_MODEL = "gemini-1.5-flash-latest" # User-facing default

    def __init__(self):
        """
        Initializes the GeminiProvider for Vertex AI. Reads config, initializes
        the Vertex client via genai.Client, and relies on ADC for auth.
        """
        self.project_id = _clean_env_value(os.getenv("GOOGLE_VERTEX_PROJECT_ID"))
        self.location = _clean_env_value(os.getenv("GOOGLE_VERTEX_LOCATION"))
        self.client: Optional[genai.Client] = None # Stores the genai.Client instance
        self.is_available = False

        if not self.project_id:
            logging.warning("Vertex Project ID (GOOGLE_VERTEX_PROJECT_ID) not found. GeminiProvider unavailable.")
            return
        if not self.location:
            logging.warning("Vertex Location (GOOGLE_VERTEX_LOCATION) not found. GeminiProvider unavailable.")
            return

        try:
            self.client = genai.Client(
                vertexai=True,
                project=self.project_id,
                location=self.location,
            )
            # ------------------------------------------------------------------
            self.is_available = True
            logging.info("GeminiProvider configured for Vertex AI using explicit genai.Client.")
            logging.info(f"  Project ID: {self.project_id}")
            logging.info(f"  Location: {self.location}")
            logging.info("  Authentication: Using Application Default Credentials (ADC).")

        except google_exceptions.PermissionDenied as e:
             logging.error(f"Vertex Permission Denied during client initialization for project '{self.project_id}'. Check ADC/IAM roles/API enablement.", exc_info=False)
             self.is_available = False
        except AttributeError as e:
             # Catch if genai.Client is still missing (library version issue)
             print(e)
             if "'Client'" in str(e):
                  logging.error("FATAL: 'genai.Client' not found. Please ensure 'google-generativeai' library is installed and up-to-date (`pip install --upgrade google-generativeai`).", exc_info=False)
             else:
                  logging.error(f"Unexpected AttributeError during GeminiProvider client init: {e}", exc_info=True)
             self.is_available = False
        except Exception as e:
            self.is_available = False
            logging.error(f"Unexpected error during GeminiProvider (Vertex) client initialization: {e}", exc_info=True)

    def get_default_model(self) -> str:
        """Returns the default user-facing model name for Gemini."""
        return self.DEFAULT_MODEL

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """
        Generates content using a Gemini model via the configured Vertex AI async client method.
        """
        if not self.is_available or not self.client:
             raise LLMError("GeminiProvider (Vertex) is not available or client failed to initialize.", "config_error")

        model_name_to_call = request.model or self.DEFAULT_MODEL
        resolved_model_name = model_name_to_call # Keep track for the response object

        logging.debug(f"GeminiProvider (Vertex) using async client for model: '{model_name_to_call}'")

        try:
            contents_to_send: Any = request.prompt

            # --- Prepare Generation Config (as Dict or types.GenerateContentConfig) ---
            gen_config_dict: Dict[str, Any] = {
                "temperature": request.temperature,
                "max_output_tokens": request.max_tokens or 32000, # Or None if API handles default well
                # "top_p": ..., # Add if needed
                # "top_k": ..., # Add if needed
                # "seed": ..., # Add if needed and supported by this method
            }
            if request.is_json:
                gen_config_dict["response_mime_type"] = "application/json"
                # If a specific JSON schema is needed, add 'response_schema' here
                # gen_config_dict["response_schema"] = ... (Dict or Pydantic model)

            # Add system instruction to the config dictionary, SDK expects it here for this method
            if request.system_message:
                 # Pass as string directly as shown in docs for config object
                 gen_config_dict["system_instruction"] = request.system_message

            # Convert dict to the typed object if preferred, otherwise dict works
            generation_config = types.GenerateContentConfig(**gen_config_dict)

            # --- API Call using the Native Async Client Method ---
            logging.debug(f"Calling client.aio.models.generate_content for model '{model_name_to_call}'...")
            response = await self.client.aio.models.generate_content(
                model=model_name_to_call,         # Pass model identifier string
                contents=contents_to_send,        # Pass string or list[Content]
                config=generation_config, # Pass config dict or object
                # stream=False, # Default
                # tools=...,
                # tool_config=...,
                # request_options=...,
            )
            logging.debug("Async call completed.")
            # --- End API Call ---


            # --- Response Processing ---
            finish_reason_str = None
            candidate = None
            content = "" # Default

            # Safely access response attributes
            if hasattr(response, 'candidates') and response.candidates:
                 candidate = response.candidates[0]
                 # Safely get finish reason
                 finish_reason_enum = getattr(candidate, 'finish_reason', None)
                 if finish_reason_enum:
                     finish_reason_str = finish_reason_enum.name # Get the string name

                 # Safely get content text (using the nested structure)
                 try:
                     if hasattr(candidate, 'content') and candidate.content and \
                        hasattr(candidate.content, 'parts') and candidate.content.parts and \
                        hasattr(candidate.content.parts[0], 'text'):
                          content = candidate.content.parts[0].text
                     else: logging.warning("GeminiProvider (Vertex Async): Response structure missing expected content parts/text.")
                 except IndexError: logging.warning("GeminiProvider (Vertex Async): Response 'parts' list is empty.")
                 except Exception as e: logging.warning(f"GeminiProvider (Vertex Async): Error extracting content text: {e}")

            # Safety Checks
            prompt_feedback = getattr(response, 'prompt_feedback', None)
            if prompt_feedback and getattr(prompt_feedback, 'block_reason', None):
                 prompt_block_reason = prompt_feedback.block_reason.name
                 raise LLMError(f"Vertex Gemini prompt blocked: {prompt_block_reason}", "content_safety")

            if candidate and finish_reason_str == 'SAFETY':
                 raise LLMError("Vertex Gemini response blocked: SAFETY", "content_safety")
            # Add other checks (RECITATION, etc.) if necessary

            # Token Counts
            prompt_tokens, completion_tokens, total_tokens = 0, 0, 0
            usage_metadata = getattr(response, 'usage_metadata', None)
            if usage_metadata:
                 prompt_tokens = getattr(usage_metadata, 'prompt_token_count', 0)
                 # Use 'completion_token_count' if available, fallback to 'candidates_token_count'
                 completion_tokens = getattr(usage_metadata, 'completion_token_count',
                                            getattr(usage_metadata, 'candidates_token_count', 0))
                 ttc = getattr(usage_metadata, 'total_token_count', 0)
                 total_tokens = ttc if ttc > 0 else (prompt_tokens + completion_tokens)

            return LLMResponse(
                content=content,
                total_tokens=total_tokens,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                model_used=resolved_model_name, 
                raw_response=response,         
                finish_reason=finish_reason_str
            )

        # --- Error Handling (Keep specific Google exceptions) ---
        except google_exceptions.PermissionDenied as e:
             logging.error(f"Vertex Permission Denied for project '{self.project_id}'. Check ADC/IAM roles/API enablement.", exc_info=False)
             raise LLMError(f"Vertex Permission Denied: {e}", "authentication_error", e)
        except google_exceptions.ResourceExhausted as e:
             logging.warning(f"Vertex resource exhausted (quota/rate limit) for project '{self.project_id}'. Error: {e}")
             raise LLMError(f"Vertex rate limit or quota exceeded: {e}", "rate_limit", e)
        except google_exceptions.InvalidArgument as e:
             # This can happen if model name is invalid, or config options are wrong
             logging.error(f"Vertex Invalid Argument for model '{model_name_to_call}'. Check args/config. Error: {e}", exc_info=False)
             raise LLMError(f"Vertex Invalid Argument (check model/params): {e}", "api_error", e)
        except google_exceptions.NotFound as e:
             logging.error(f"Vertex resource not found (model '{model_name_to_call}' in project '{self.project_id}/{self.location}'?). Error: {e}", exc_info=False)
             raise LLMError(f"Vertex resource not found (model '{model_name_to_call}' in {self.location}?): {e}", "config_error", e)
        except google_exceptions.FailedPrecondition as e:
             logging.error(f"Vertex Failed Precondition for project '{self.project_id}'. Check API enablement/project state. Error: {e}", exc_info=False)
             raise LLMError(f"Vertex Failed Precondition (check API enablement/project state): {e}", "config_error", e)
        except google_exceptions.GoogleAPIError as e: # Catch-all for other Google API errors
            error_details = f"Vertex API error: {getattr(e, 'message', str(e))}"
            status_code = getattr(e, 'code', None)
            error_type = "api_error"
            # ... (map status codes to error types if needed) ...
            logging.error(f"{error_details} (Provider: Gemini/Vertex, Model: {model_name_to_call})", exc_info=False)
            raise LLMError(error_details, error_type, e)
        except Exception as e: # Catch unexpected Python errors
            logging.error(f"Unexpected error in GeminiProvider (Vertex Async) for model '{model_name_to_call}': {e}", exc_info=True)
            raise LLMError(f"Unexpected error in GeminiProvider (Vertex Async): {type(e).__name__}: {e}", "unknown", e)

class LLMManager:
    """Manages LLM interactions with retry logic and error handling"""
    DEFAULT_PROVIDER = "azure"

    def __init__(self,
                 max_retries: int = 5,
                 logger: Optional[logging.Logger] = None,
                 stats_collector: Optional[StatsCollector] = None):
        """
        Initializes the LLMManager.

        Args:
            max_retries: Maximum number of times to retry an LLM API call on failure.
            logger: Optional logger instance. If None, a default logger is used.
            stats_collector: Optional StatsCollector instance for recording metrics.
        """
        self.max_retries = max_retries
        self.logger = logger or logging.getLogger(__name__)
        self.stats_collector = stats_collector

        # Dictionary to hold successfully initialized and configured providers
        self.providers: Dict[str, LLMProvider] = {} # type: Dict[str, LLMProvider]

        self.logger.info("Initializing LLMManager...")

        # --- Attempt to Initialize AzureProvider ---
        try:
            azure_provider = AzureProvider()
            # Check if the provider loaded any valid configurations from environment variables
            if azure_provider.configurations:
                self.providers["azure"] = azure_provider
                self.logger.info(f"Azure Provider initialized with {len(azure_provider.configurations)} configuration(s).")
            else:
                # AzureProvider logs specific warnings internally if configs are missing/invalid
                self.logger.warning("Azure Provider instance created but found no valid configurations (check AZURE_* env vars). It will be unavailable.")
        except Exception as e:
            # Catch unexpected errors during AzureProvider instantiation
            self.logger.error(f"CRITICAL ERROR during AzureProvider instantiation: {e}", exc_info=True)

        # --- Attempt to Initialize GeminiProvider ---
        try:
            gemini_provider = GeminiProvider()
            # Check the flag set during GeminiProvider's initialization
            if gemini_provider.is_available:
                 self.providers["gemini"] = gemini_provider
                 self.logger.info("Gemini Provider initialized successfully.")
            else:
                 # GeminiProvider logs specific warnings internally if key is missing
                 self.logger.warning("Gemini Provider instance created but is unavailable (check GOOGLE_API_KEY).")
        except Exception as e:
             # Catch unexpected errors during GeminiProvider instantiation
             self.logger.error(f"CRITICAL ERROR during GeminiProvider instantiation: {e}", exc_info=True)

        try:
            deepseek_provider = DeepSeekInferenceProvider()
            if deepseek_provider.is_available:
                self.providers["deepseek"] = deepseek_provider
                self.logger.info("DeepSeek Provider initialised.")
            else:
                self.logger.warning("DeepSeek Provider present but unavailable.")
        except Exception as e:
            self.logger.error(f"CRITICAL: DeepSeek provider failed: {e}", exc_info=True)

        # --- Final Check and Logging ---
        if not self.providers:
             # This is a critical state - the manager cannot function without providers.
             self.logger.critical("FATAL: No LLM providers could be initialized successfully. LLMManager cannot make API calls.")
             self.logger.critical("Please check logs above for specific provider errors and ensure API keys/configurations are correctly set in environment variables or .env file.")
             # Consider raising an exception if the application cannot proceed without LLMs
             # raise RuntimeError("LLMManager could not initialize any providers. Aborting.")
        else:
             provider_names = list(self.providers.keys())
             self.logger.info(f"LLMManager initialization complete. Available providers: {provider_names}")

    def _get_provider(self, requested_model_name: Optional[str]) -> Tuple[LLMProvider, str]:
        """
        Determines the provider and the final *user-facing model name* to use.
        """
        if not self.providers:
             raise LLMError("No LLM providers are available.", "config_error")

        provider_key = None
        final_model_name = requested_model_name # Start with the request
        
        # --- Determine Provider ---
        if requested_model_name:
             normalized_request = requested_model_name.lower().replace('-', '_').replace('.', '_')
             if requested_model_name and "deepseek" in requested_model_name.lower():
                provider_key = "deepseek"
             # 1. Check if it's explicitly mapped in AzureProvider
             if "azure" in self.providers:
                  azure_provider = self.providers["azure"]
                  # Use the helper method to check map keys
                  if normalized_request in azure_provider.get_mapped_azure_model_names():
                       provider_key = "azure"
                       self.logger.debug(f"Identified '{requested_model_name}' as Azure via model map.")

             if not provider_key and "gemini" in self.providers and requested_model_name and "gemini" in requested_model_name.lower():
               provider_key = "gemini"
               self.logger.debug(f"Identified '{requested_model_name}' as Gemini.")


        # 3. If provider still unknown, use default provider
        if not provider_key:
            provider_key = self.DEFAULT_PROVIDER
            self.logger.debug(f"No specific provider indicated or matched for '{requested_model_name}', using default provider '{provider_key}'.")
            # If no model was requested AND we fell back to default provider, get *that* provider's default model name
            if not final_model_name and provider_key in self.providers:
                 final_model_name = self.providers[provider_key].get_default_model()
                 self.logger.debug(f"Using default model name '{final_model_name}' for default provider '{provider_key}'.")

        # --- Validate Provider Availability & Final Model ---
        if provider_key not in self.providers:
            # ... (fallback logic remains the same) ...
            available_keys = list(self.providers.keys())
            if available_keys: fallback_key = available_keys[0]; self.logger.warning(...); provider_key = fallback_key
            else: raise LLMError(...)

        provider = self.providers[provider_key]

        # Ensure we have a final model name, using provider default if needed
        if not final_model_name:
             final_model_name = provider.get_default_model()
             if not final_model_name:
                  raise LLMError(f"Could not determine a final model name for provider '{provider_key}'. Default not set or provider misconfigured.", "config_error")

        # --- Final Compatibility Check (Optional but recommended) ---
        # Check if the final model name seems valid for the chosen provider
        normalized_final_name = final_model_name.lower().replace('-', '_').replace('.', '_')
        if provider_key == "azure":
             if "gemini" in normalized_final_name: # Looks like Gemini but going to Azure?
                  self.logger.warning(f"Model name '{final_model_name}' looks like Gemini but routing to Azure. Switching to Azure default.")
                  final_model_name = provider.get_default_model()
             elif normalized_final_name not in provider.get_mapped_azure_model_names(): # Not explicitly mapped?
                  # This might happen if the default name wasn't mapped correctly
                  self.logger.error(f"Azure model name '{final_model_name}' is not mapped in AZURE_MODEL_MAP_*. Cannot proceed.")
                  raise LLMError(f"Azure model '{final_model_name}' is not mapped.", "config_error")
        elif provider_key == "gemini":
              if "gemini" not in normalized_final_name: # Doesn't look like Gemini?
                   self.logger.warning(f"Model name '{final_model_name}' does not look like Gemini but routing to Gemini. Switching to Gemini default.")
                   final_model_name = provider.get_default_model()


        self.logger.debug(f"Selected Provider: {provider_key}, Final Model Name: {final_model_name}")
        # Return the provider instance and the *user-facing model name*
        return provider, final_model_name
    
    def _extract_code_blocks(self, content: str) -> str:
        """Extract content from code blocks"""
        match = re.search(r"```(?:[a-zA-Z0-9_]+)?\s*\n(.*?)\n```", content, re.DOTALL)
        if match:
            return match.group(1).strip()

        match = re.search(r"```(.*?)```", content, re.DOTALL)
        if match:
             return match.group(1).strip()

        return content
    
    def _handle_response_content(self, response: LLMResponse, request: LLMRequest) -> str:
        if not response or not response.content:
            return ""


        content = response.content
        # Only attempt extraction if the original request didn't specifically ask for JSON,
        # as the JSON itself might be wrapped in a code block by the LLM.
        if not request.is_json:
            extracted_content = self._extract_code_blocks(content)
            return extracted_content
        else:
            # If JSON was requested, return the raw content (potentially including ```json ... ```)
            # Further validation/parsing should happen *after* this method returns.
            return content

    def _get_total_attempts(self) -> int:
        """Interpret max_retries as retries after the first attempt."""
        return max(1, self.max_retries + 1)
    
    async def generate(self,
                      prompt: str,
                      error_file: str,
                      system_message: Optional[str] = None,
                      model: Optional[str] = None,
                      is_json: bool = False,
                      max_tokens: Optional[int] = None,
                      temperature: float = 0.2,
                      seed: Optional[int] = 18790,
                      prefix: str = "",
                      counter: Optional[Any] = None,
                      batch_size: Optional[int] = None,
                      debug_logger: Optional[logging.Logger] = None,
                      entity_id: Optional[str] = None,
                      call_type: Optional[LLMCallType] = None,
                      attempt_id: Optional[str] = None,
                      agent_id: Optional[str] = None,
                      agent_step: Optional[int] = None
                      ) -> tuple[Optional[str], Optional[int]]:

        # Use self.logger if passed during init, else use the provided debug_logger or default
        logger = self.logger or debug_logger or logging.getLogger(__name__)

        is_done = False
        llm_response: Optional[LLMResponse] = None # Use the LLMResponse dataclass
        current_prompt = prompt
        # Using original_prompt for potential retries with modifications
        original_prompt = prompt
        count = f"[{counter.get_value()}/{batch_size}]" if counter is not None and batch_size is not None else ""
        
        provider: Optional[LLMProvider] = None
        model_to_use: Optional[str] = None
        provider_name: str = "unknown"

        try:
            provider, model_to_use = self._get_provider(model)
            provider_name = type(provider).__name__.replace("Provider", "").lower() # "azure" or "gemini"
            logger.info(f"{count} {prefix} Using {provider_name.upper()} provider with model '{model_to_use}'")

        except LLMError as e:
             logger.error(f"{count} {prefix} Failed to select LLM provider: {e}")
             return None, None
        except Exception as e:
             logger.error(f"{count} {prefix} Unexpected error during provider selection: {e}", exc_info=True)
             return None, None
    
        llm_api_request = LLMRequest(
            prompt=current_prompt,
            system_message=system_message,
            model=model_to_use,
            temperature=temperature,
            max_tokens=max_tokens,
            is_json=is_json,
            seed=seed,
            metadata={
                "prefix": prefix,
                "attempt_id": attempt_id,
                "entity_id": entity_id,
                "call_type": call_type.value if call_type else None,
                "provider": provider_name,
                "agent_id": agent_id,
                "agent_step": agent_step
            },
        )

        total_attempts = self._get_total_attempts()

        for retry in range(total_attempts):
            request_start_time = datetime.utcnow()
            request_stats: Optional[LLMRequestStats] = None # Initialize request_stats
            llm_api_request.metadata["llm_retry"] = retry

            try:
                logger.debug(f"{count} {prefix} Attempt {retry+1}: {provider_name.upper()} API call started for model '{llm_api_request.model}'")
                
                llm_response = await provider.generate(llm_api_request)
                request_end_time = datetime.utcnow()
                duration_ms = int((request_end_time - request_start_time).total_seconds() * 1000)

                if llm_response:
                     log_content_snippet = (llm_response.content[:100] + '...') if llm_response.content and len(llm_response.content) > 100 else llm_response.content
                     logger.debug(f"[{entity_id}-{llm_api_request.metadata['call_type']}-Attempt {retry+1}] Raw LLM Response (Finish: {llm_response.finish_reason}, Tokens: {llm_response.total_tokens}):\n```\n{llm_response.content}\n```")
                     # Check for empty content despite successful API call
                     if llm_response.content is None or llm_response.content == "":
                         logger.warning(f"{count} {prefix} Attempt {retry+1}: LLM Response received but content is empty. Finish Reason: {llm_response.finish_reason}")
                else:
                     # This case should ideally be handled by the provider raising an error, but as a safeguard:
                     logger.error(f"{count} {prefix} Attempt {retry+1}: Provider returned None response object.")
                     raise LLMError("Provider returned None response", "api_error") # Treat as error
                
                # --- Create SUCCESS stats object ---
                request_stats = LLMRequestStats(
                    timestamp=request_start_time.isoformat(),
                    prompt=original_prompt,
                    response=llm_response.content,
                    tokens_used=llm_response.total_tokens,
                    prompt_tokens=llm_response.prompt_tokens,
                    completion_tokens=llm_response.completion_tokens,
                    duration_ms=duration_ms,
                    status="success",
                    call_type=call_type or LLMCallType.OTHER,
                    attempt_id=attempt_id, 
                    model=llm_response.model_used,
                    temperature=llm_api_request.temperature,
                    finish_reason=llm_response.finish_reason,
                    provider=provider_name,
                    model_params={
                        "requested_model": llm_api_request.model,
                        "is_json": llm_api_request.is_json,
                        "seed": llm_api_request.seed,
                        "retry_attempt": retry,
                        "max_tokens_requested": llm_api_request.max_tokens,
                        "system_message_provided": bool(llm_api_request.system_message),
                        "agent_id": agent_id,
                        "agent_step": agent_step
                        },
                    cost_usd=LLMRequestStats.calculate_cost(
                        model_name=llm_response.model_used,
                        total_tokens=llm_response.total_tokens,
                        prompt_tokens=llm_response.prompt_tokens,
                        completion_tokens=llm_response.completion_tokens,
                        provider=provider_name
                        ),
                    reasoning_tokens=llm_response.reasoning_tokens,
                    cached_tokens=llm_response.cached_tokens
                )

                logger.debug(f"{count} {prefix} Attempt {retry+1}: {provider_name.upper()} API call success. Duration: {duration_ms} ms. Tokens: {llm_response.total_tokens}. Finish: {llm_response.finish_reason}")

                is_done = True
                break # Exit retry loop on success

            except LLMError as e:
                request_end_time = datetime.utcnow()
                duration_ms = int((request_end_time - request_start_time).total_seconds() * 1000)
                error_type = e.error_type # Use error type from LLMError
                error_msg = str(e)
                logger.error(f"{count} {prefix} Attempt {retry+1}: LLMError ({error_type}): {error_msg}")

                if e.original_error:
                    logger.debug(f"Original Exception for LLMError:", exc_info=e.original_error)

                # --- Create FAILURE stats object ---
                request_stats = LLMRequestStats(
                    timestamp=request_start_time.isoformat(),
                    prompt=original_prompt, # Log original prompt
                    response=None,
                    tokens_used=None, prompt_tokens=None, completion_tokens=None, # No token info on failure usually
                    duration_ms=duration_ms,
                    status="failure",
                    call_type=call_type or LLMCallType.OTHER,
                    attempt_id=attempt_id,
                    error=error_msg,
                    error_type=error_type,
                    model=llm_api_request.model, # Log intended model
                    temperature=llm_api_request.temperature,
                    provider=provider_name,
                    finish_reason=None, # No finish reason on failure
                    model_params={
                         "requested_model": llm_api_request.model,
                         "is_json": llm_api_request.is_json,
                         "seed": llm_api_request.seed,
                         "retry_attempt": retry,
                         "max_tokens_requested": llm_api_request.max_tokens,
                         "system_message_provided": bool(llm_api_request.system_message),
                         "agent_id": agent_id,
                         "agent_step": agent_step
                         }
                )

                try:
                    async with aiofiles.open(error_file, mode="a", encoding="utf-8") as f:
                        await f.write(f"--- LLM Error ({provider_name.upper()} - {prefix} Attempt {retry+1}) ---\n")
                        await f.write(f"Timestamp: {request_start_time.isoformat()}\n")
                        await f.write(f"Provider: {provider_name}\nModel Requested: {llm_api_request.model}\n")
                        await f.write(f"Entity ID: {entity_id}\nCall Type: {call_type.value if call_type else 'N/A'}\nAttempt ID: {attempt_id}\n")
                        await f.write(f"Error Type: {error_type}\nMessage: {error_msg}\n")
                        if e.original_error:
                            await f.write("Original Exception Traceback:\n")
                            tb_lines = traceback.format_exception(type(e.original_error), e.original_error, e.original_error.__traceback__)
                            await f.write("".join(tb_lines))
                        # Log prompt snippet safely
                        prompt_snippet = original_prompt[:500].encode('utf-8', 'replace').decode('utf-8')
                        await f.write(f"Prompt Snippet (first 500 chars):\n{prompt_snippet}...\n")
                        await f.write("\n" + "-"*50 + "\n\n")
                except Exception as file_err:
                    logger.error(f"[{prefix} Attempt {retry+1}] Failed to write LLMError log to {error_file}: {file_err}")
                
                if retry < total_attempts - 1:
                    llm_api_request.prompt = original_prompt
                    sleep_time = 2**retry # Exponential backoff
                    logger.info(f"{count} {prefix} Retrying in {sleep_time} seconds...")
                    await asyncio.sleep(sleep_time)
                    continue
                else:
                    logger.error(f"{count} {prefix} Not retrying {provider_name.upper()} call. max retries ({self.max_retries}) reached.")
                    break

            except Exception as e:
                # Catch any other unexpected error during the process
                request_end_time = datetime.utcnow()
                duration_ms = int((request_end_time - request_start_time).total_seconds() * 1000)
                logger.error(f"{count} {prefix} Attempt {retry+1}: Unexpected error during LLM call ({provider_name.upper()}): {e}", exc_info=True)
                error_type = f"unknown_{type(e).__name__}"
                error_msg = str(e)

                # --- Create UNKNOWN FAILURE stats object ---
                request_stats = LLMRequestStats(
                    timestamp=request_start_time.isoformat(),
                    prompt=original_prompt,
                    response=None, tokens_used=None, prompt_tokens=None, completion_tokens=None,
                    duration_ms=duration_ms, status="failure",
                    attempt_id=attempt_id, 
                    call_type=call_type or LLMCallType.OTHER,
                    error=error_msg, error_type=error_type,
                    model=llm_api_request.model,
                    temperature=llm_api_request.temperature,
                    provider=provider_name, finish_reason=None,
                    model_params={
                         "requested_model": llm_api_request.model,
                         "is_json": llm_api_request.is_json,
                         "seed": llm_api_request.seed,
                         "retry_attempt": retry,
                         "max_tokens_requested": llm_api_request.max_tokens,
                         "system_message_provided": bool(llm_api_request.system_message),
                         "agent_id": agent_id,
                         "agent_step": agent_step
                         }
                )
                # Log to main error file
                try:
                    async with aiofiles.open(error_file, mode="a", encoding="utf-8") as f:
                        await f.write(f"--- Unexpected Error during LLM Generate ({provider_name.upper()} - {prefix} Attempt {retry+1}) ---\n")
                        await f.write(f"Timestamp: {request_start_time.isoformat()}\n")
                        await f.write(f"Provider: {provider_name}\nModel Requested: {llm_api_request.model}\n")
                        await f.write(f"Entity ID: {entity_id}\nCall Type: {call_type.value if call_type else 'N/A'}\nAttempt ID: {attempt_id}\n")
                        await f.write(f"Error Type: {error_type}\nMessage: {error_msg}\n")
                        await f.write("Traceback:\n")
                        tb_lines = traceback.format_exception(type(e), e, e.__traceback__)
                        await f.write("".join(tb_lines))
                        prompt_snippet = original_prompt[:500].encode('utf-8', 'replace').decode('utf-8')
                        await f.write(f"Prompt Snippet (first 500 chars):\n{prompt_snippet}...\n")
                        await f.write("\n" + "-"*50 + "\n\n")
                except Exception as file_err:
                    logger.error(f"[{prefix} Attempt {retry+1}] Failed to write unexpected error log to {error_file}: {file_err}")

                break

            finally:
                 if self.stats_collector and entity_id and request_stats:
                      final_call_type = call_type or LLMCallType.OTHER
                      try:
                          self.stats_collector.add_llm_request(entity_id, final_call_type, request_stats)
                      except Exception as stats_err:
                           logger.error(f"Failed to add request stats for entity {entity_id}, call_type {final_call_type}: {stats_err}", exc_info=True)


        if not is_done or llm_response is None:
            logger.error(
                f"{count} {prefix} LLM call failed definitively after {total_attempts} attempts "
                f"({self.max_retries} retries) for model '{model_to_use}' using {provider_name.upper()}."
            )
            return None, None

        # Return the content from the successful response
        final_content = self._handle_response_content(llm_response, llm_api_request)

        if llm_response.content and not final_content and not llm_api_request.is_json:
            logger.warning(f"{count} {prefix} Content extraction resulted in empty string. Review extraction logic or LLM output format. Returning original content.")
            final_content = llm_response.content

        return final_content, llm_response.total_tokens

    async def generate_with_chat_manager(
        self,
        messages: List[ChatMessage],
        error_file: str,
        system_message: Optional[str] = None,
        model: Optional[str] = None,
        is_json: bool = False,
        max_tokens: Optional[int] = None,
        temperature: float = 0.2,
        seed: Optional[int] = 18790,
        prefix: str = "",
        counter: Optional[Any] = None,
        batch_size: Optional[int] = None,
        debug_logger: Optional[logging.Logger] = None,
        entity_id: Optional[str] = None,
        call_type: Optional[LLMCallType] = None,
        attempt_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        agent_step: Optional[int] = None
    ) -> tuple[Optional[str], Optional[int]]:
        """
        Generate a response using chat-style conversation history.
        This properly maintains conversation context without flattening.
        """
        logger = self.logger or debug_logger or logging.getLogger(__name__)
        
        is_done = False
        llm_response: Optional[LLMResponse] = None
        count = f"[{counter.get_value()}/{batch_size}]" if counter is not None and batch_size is not None else ""
        
        # Get provider and model
        try:
            provider, model_to_use = self._get_provider(model)
            provider_name = type(provider).__name__.replace("Provider", "").lower()
            logger.info(f"{count} {prefix} Using {provider_name.upper()} provider with model '{model_to_use}' for chat")
        except LLMError as e:
            logger.error(f"{count} {prefix} Failed to select LLM provider: {e}")
            return None, None
        except Exception as e:
            logger.error(f"{count} {prefix} Unexpected error during provider selection: {e}", exc_info=True)
            return None, None
        
        # Create chat request
        chat_request = LLMChatRequest(
            messages=messages,
            system_message=system_message,
            model=model_to_use,
            temperature=temperature,
            max_tokens=max_tokens,
            is_json=is_json,
            seed=seed,
            metadata={
                "prefix": prefix,
                "attempt_id": attempt_id,
                "entity_id": entity_id,
                "call_type": call_type.value if call_type else None,
                "provider": provider_name,
                "agent_id": agent_id,
                "agent_step": agent_step
            }
        )
        
        # Retry loop
        total_attempts = self._get_total_attempts()

        for retry in range(total_attempts):
            request_start_time = datetime.utcnow()
            request_stats: Optional[LLMRequestStats] = None
            chat_request.metadata["llm_retry"] = retry
            
            try:
                logger.debug(f"{count} {prefix} Attempt {retry+1}: {provider_name.upper()} chat API call started")
                
                # Check if provider has chat support, otherwise fall back to flattening
                if hasattr(provider, 'generate_with_chat'):
                    llm_response = await provider.generate_with_chat(chat_request)
                else:
                    # Fallback: convert to traditional request
                    logger.warning(f"Provider {provider_name} doesn't support chat interface, falling back to flattened prompt")
                    
                    # Build flattened prompt
                    prompt_parts = []
                    for msg in messages:
                        if msg.role == MessageRole.USER:
                            prompt_parts.append(f"User: {msg.content}")
                        elif msg.role == MessageRole.ASSISTANT:
                            prompt_parts.append(f"Assistant: {msg.content}")
                    
                    flattened_prompt = "\n\n".join(prompt_parts)
                    
                    # Create traditional request
                    traditional_request = LLMRequest(
                        prompt=flattened_prompt,
                        system_message=system_message,
                        model=model_to_use,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        is_json=is_json,
                        seed=seed,
                        metadata=chat_request.metadata
                    )
                    
                    llm_response = await provider.generate(traditional_request)
                
                request_end_time = datetime.utcnow()
                duration_ms = int((request_end_time - request_start_time).total_seconds() * 1000)
                
                if llm_response:
                    logger.debug(f"[{entity_id}-{chat_request.metadata['call_type']}-Attempt {retry+1}] Chat Response received")
                    
                    # Create success stats
                    request_stats = LLMRequestStats(
                        timestamp=request_start_time.isoformat(),
                        prompt=str(messages),  # Log the messages
                        response=llm_response.content,
                        tokens_used=llm_response.total_tokens,
                        prompt_tokens=llm_response.prompt_tokens,
                        completion_tokens=llm_response.completion_tokens,
                        duration_ms=duration_ms,
                        status="success",
                        call_type=call_type or LLMCallType.OTHER,
                        attempt_id=attempt_id,
                        model=llm_response.model_used,
                        temperature=chat_request.temperature,
                        finish_reason=llm_response.finish_reason,
                        provider=provider_name,
                        model_params={
                            "requested_model": chat_request.model,
                            "is_json": chat_request.is_json,
                            "seed": chat_request.seed,
                            "retry_attempt": retry,
                            "max_tokens_requested": chat_request.max_tokens,
                            "system_message_provided": bool(chat_request.system_message),
                            "message_count": len(messages),
                            "is_chat_mode": True,
                            "agent_id": agent_id,
                            "agent_step": agent_step
                        },
                        cost_usd=LLMRequestStats.calculate_cost(
                            model_name=llm_response.model_used,
                            total_tokens=llm_response.total_tokens,
                            prompt_tokens=llm_response.prompt_tokens,
                            completion_tokens=llm_response.completion_tokens,
                            provider=provider_name
                        ),
                        reasoning_tokens=llm_response.reasoning_tokens,
                        cached_tokens=llm_response.cached_tokens
                    )
                    
                    is_done = True
                    break
                    
            except LLMError as e:
                request_end_time = datetime.utcnow()
                duration_ms = int((request_end_time - request_start_time).total_seconds() * 1000)
                error_type = e.error_type
                error_msg = str(e)
                logger.error(f"{count} {prefix} Attempt {retry+1}: LLMError ({error_type}): {error_msg}")
                
                # Log error to file
                try:
                    async with aiofiles.open(error_file, mode="a", encoding="utf-8") as f:
                        await f.write(f"--- Chat LLM Error ({provider_name.upper()} - {prefix} Attempt {retry+1}) ---\n")
                        await f.write(f"Timestamp: {request_start_time.isoformat()}\n")
                        await f.write(f"Message Count: {len(messages)}\n")
                        await f.write(f"Error Type: {error_type}\nMessage: {error_msg}\n")
                        await f.write("\n" + "-"*50 + "\n\n")
                except Exception as file_err:
                    logger.error(f"Failed to write error log: {file_err}")
                
                if retry < total_attempts - 1:
                    sleep_time = 2**retry
                    logger.info(f"{count} {prefix} Retrying in {sleep_time} seconds...")
                    await asyncio.sleep(sleep_time)
                    continue
                else:
                    logger.error(f"{count} {prefix} Max retries reached.")
                    break
                    
            except Exception as e:
                logger.error(f"{count} {prefix} Unexpected error: {e}", exc_info=True)
                break
                
            finally:
                if self.stats_collector and entity_id and request_stats:
                    try:
                        self.stats_collector.add_llm_request(
                            entity_id, 
                            call_type or LLMCallType.OTHER, 
                            request_stats
                        )
                    except Exception as stats_err:
                        logger.error(f"Failed to add request stats: {stats_err}", exc_info=True)
        
        if not is_done or llm_response is None:
            logger.error(f"{count} {prefix} Chat LLM call failed after {total_attempts} attempts ({self.max_retries} retries)")
            return None, None
        
        # Handle response content
        final_content = self._handle_response_content(llm_response, chat_request)
        
        return final_content, llm_response.total_tokens
    
    def _build_chat_payload_for_tools(
        self,
        messages: List[ChatMessage],
        system_message: Optional[str],
    ) -> List[Dict[str, Any]]:
        """
        Convert ChatMessage list to OpenAI/Azure payload for tools mode.
        IMPORTANT: if an assistant message requested tools (has tool_calls),
        we must serialize those tool_calls so that any following role='tool'
        messages are considered valid responses.
        """
        payload: List[Dict[str, Any]] = []
        if system_message:
            payload.append({"role": "system", "content": system_message})

        for m in messages:
            role = m.role.value

            # Assistant: include tool_calls when present
            if role == "assistant":
                entry: Dict[str, Any] = {
                    "role": "assistant",
                    "content": m.content or ""
                }
                if m.tool_calls:
                    tc_serialized: List[Dict[str, Any]] = []
                    for tc in m.tool_calls:
                        # Ensure we have a stable id (preserve model id if given)
                        tc_id = tc.id or f"fn_{uuid.uuid4()}"
                        fn_name = tc.function.name if tc.function else ""
                        fn_args = tc.function.arguments if tc.function else "{}"
                        # Azure/OpenAI expects stringified JSON in 'arguments'
                        if not isinstance(fn_args, str):
                            try:
                                fn_args = json.dumps(fn_args)
                            except Exception:
                                fn_args = "{}"
                        tc_serialized.append({
                            "id": tc_id,
                            "type": "function",
                            "function": {
                                "name": fn_name,
                                "arguments": fn_args
                            }
                        })
                    entry["tool_calls"] = tc_serialized
                payload.append(entry)

            # Tool: must include tool_call_id that matches a previous assistant.tool_calls[].id
            elif role == "tool":
                entry: Dict[str, Any] = {
                    "role": "tool",
                    "content": m.content or "",
                    "tool_call_id": m.tool_call_id or ""  # MUST match the assistant tool_calls id
                }
                payload.append(entry)

            elif role == "user":
                payload.append({"role": "user", "content": m.content})
            elif role == "system":
                payload.append({"role": "system", "content": m.content})
            else:
                # Fallback (shouldn't happen)
                payload.append({"role": role, "content": m.content})

        return payload
    
    async def chat_completions_with_tools(
        self,
        messages: List[ChatMessage],
        tools: List[Dict[str, Any]],
        tool_choice: Any = "auto",  # "auto" | {"type":"function","function":{"name":"..."}}
        system_message: Optional[str] = None,
        model: Optional[str] = None,
        error_file: str = "",
        entity_id: Optional[str] = None,
        call_type: Optional[LLMCallType] = None,
        prefix: str = "",
        attempt_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        agent_step: Optional[int] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        seed: Optional[int] = 18790,
        is_json: bool = False,
    ) -> Optional[ChatMessage]:

        logger = self.logger or logging.getLogger(__name__)

        # --- Provider resolution (Azure only here) ---
        try:
            provider, model_to_use = self._get_provider(model)
            provider_name = type(provider).__name__.replace("Provider", "").lower()
            if provider_name != "azure":
                raise LLMError("chat_completions_with_tools currently implemented only for AzureProvider", "config_error")
            logger.info(f"{prefix} Using {provider_name.upper()} with model '{model_to_use}' for tools/function-calling")
        except LLMError as e:
            logger.error(f"{prefix} Provider selection failed: {e}")
            return None
        except Exception as e:
            logger.error(f"{prefix} Unexpected error during provider selection: {e}", exc_info=True)
            return None

        azure: AzureProvider = provider  # type: ignore
        resolved = azure.resolve_deployment(model_to_use)
        if not resolved:
            logger.error(f"{prefix} Could not resolve deployment for model '{model_to_use}'")
            return None
        config_name, deployment_to_use, resolved_model_name = resolved

        client = azure._get_client(config_name)
        if not client:
            logger.error(f"{prefix} Failed to get Azure client for config '{config_name}'")
            return None

        # --- Build payload ---
        api_messages = self._build_chat_payload_for_tools(messages, system_message)

        # tools must be [{"type":"function","function":{...}}, ...]
        tools_param = tools if tools else None

        # Prepare call kwargs: use tools + tool_choice (NOT functions/function_call)
        completion_kwargs: Dict[str, Any] = {
            "model": deployment_to_use,
            "messages": api_messages,
            "tools": tools_param,
            "tool_choice": tool_choice if tools_param else None,
            "max_completion_tokens": max_tokens or 32000,
            "stream": False,
        }
        # Temperature parity with your AzureProvider logic
        if deployment_to_use not in azure.UNSUPPORTED_TEMP_DEPLOYMENTS:
            completion_kwargs["temperature"] = temperature
        if seed is not None:
            completion_kwargs["seed"] = seed
        if is_json:
            completion_kwargs["response_format"] = {"type": "json_object"}

        # Remove Nones
        completion_kwargs = {k: v for k, v in completion_kwargs.items() if v is not None}

        # --- Retry loop with stats ---
        last_error: Optional[Exception] = None
        total_attempts = self._get_total_attempts()

        for retry in range(total_attempts):
            request_start_time = datetime.utcnow()
            request_stats: Optional[LLMRequestStats] = None

            try:
                logger.debug(f"{prefix} Attempt {retry+1}: Azure chat.completions (tools) starting")
                completion = await client.chat.completions.create(**completion_kwargs)
                request_end_time = datetime.utcnow()
                duration_ms = int((request_end_time - request_start_time).total_seconds() * 1000)
                if not completion.choices:
                    raise LLMError("Azure API returned no choices.", "api_error")

                choice = completion.choices[0]
                msg = choice.message
                finish_reason = choice.finish_reason

                # Build assistant ChatMessage
                assistant_content = msg.content or ""
                assistant_message = ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=assistant_content,
                    metadata={
                        "model_used": resolved_model_name,
                        "finish_reason": finish_reason,
                        "provider": provider_name,
                        "call_type": call_type.value if call_type else None,
                        "entity_id": entity_id,
                        "attempt_id": attempt_id,
                        "agent_id": agent_id,
                        "agent_step": agent_step,
                    },
                    tool_calls=None
                )

                # Parse tool calls (tools mode always uses msg.tool_calls; keep legacy fallback just in case)
                tool_calls_list: List[ToolCall] = []
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        fn = getattr(tc, "function", None)
                        if fn:
                            tool_calls_list.append(
                                ToolCall(
                                    id=getattr(tc, "id", f"fn_{uuid.uuid4()}"),
                                    function=ToolFunctionCall(
                                        name=getattr(fn, "name", ""),
                                        arguments=getattr(fn, "arguments", "{}"),
                                    )
                                )
                            )
                elif hasattr(msg, "function_call") and msg.function_call:
                    fc = msg.function_call
                    tool_calls_list.append(
                        ToolCall(
                            id=f"fn_{uuid.uuid4()}",
                            function=ToolFunctionCall(
                                name=getattr(fc, "name", ""),
                                arguments=getattr(fc, "arguments", "{}"),
                            )
                        )
                    )

                if tool_calls_list:
                    assistant_message.tool_calls = tool_calls_list

                # --- Stats (success) ---
                total_tokens = completion.usage.total_tokens if completion.usage else 0
                prompt_tokens = completion.usage.prompt_tokens if completion.usage else 0
                completion_tokens = completion.usage.completion_tokens if completion.usage else 0
                try:
                    prompt_log = json.dumps(api_messages)[:4000]
                except Exception:
                    prompt_log = str(api_messages)[:4000]

                request_stats = LLMRequestStats(
                    timestamp=request_start_time.isoformat(),
                    prompt=prompt_log,
                    response=assistant_content,
                    tokens_used=total_tokens,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    duration_ms=duration_ms,
                    status="success",
                    call_type=call_type or LLMCallType.OTHER,
                    attempt_id=attempt_id,
                    model=resolved_model_name,
                    temperature=temperature,
                    finish_reason=finish_reason,
                    provider=provider_name,
                    model_params={
                        "requested_model": model_to_use,
                        "is_json": is_json,
                        "seed": seed,
                        "retry_attempt": retry,
                        "max_tokens_requested": max_tokens,
                        "system_message_provided": bool(system_message),
                        "message_count": len(messages),
                        "has_tools": bool(tools_param),
                        "tool_choice": tool_choice,
                        "agent_id": agent_id,
                        "agent_step": agent_step,
                    },
                    cost_usd=LLMRequestStats.calculate_cost(
                        model_name=resolved_model_name,
                        total_tokens=total_tokens,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        provider=provider_name,
                    ),
                )
                if self.stats_collector and entity_id and request_stats:
                    try:
                        self.stats_collector.add_llm_request(
                            entity_id, call_type or LLMCallType.OTHER, request_stats
                        )
                    except Exception as stats_err:
                        logger.error(f"{prefix} Failed to add request stats: {stats_err}", exc_info=True)

                logger.debug(
                    f"{prefix} Attempt {retry+1} SUCCESS | "
                    f"Finish={finish_reason} Tokens={total_tokens} "
                    f"ToolCalls={len(assistant_message.tool_calls or [])}"
                )
                return assistant_message

            except LLMError as e:
                last_error = e
                request_end_time = datetime.utcnow()
                duration_ms = int((request_end_time - request_start_time).total_seconds() * 1000)
                error_type = e.error_type
                error_msg = str(e)
                logger.error(f"{prefix} Attempt {retry+1}: LLMError ({error_type}): {error_msg}")

                if error_file:
                    try:
                        async with aiofiles.open(error_file, mode="a", encoding="utf-8") as f:
                            await f.write(f"--- Tools LLM Error (AZURE - {prefix} Attempt {retry+1}) ---\n")
                            await f.write(f"Timestamp: {request_start_time.isoformat()}\n")
                            await f.write(f"Provider: azure\nDeployment: {deployment_to_use}\n")
                            await f.write(f"Entity ID: {entity_id}\nCall Type: {call_type.value if call_type else 'N/A'}\nAttempt ID: {attempt_id}\n")
                            await f.write(f"Error Type: {error_type}\nMessage: {error_msg}\n")
                            await f.write("\n" + "-"*50 + "\n\n")
                    except Exception as file_err:
                        logger.error(f"{prefix} Failed writing error log: {file_err}")

                # Failure stats
                try:
                    prompt_log = json.dumps(api_messages)[:4000]
                except Exception:
                    prompt_log = str(api_messages)[:4000]

                request_stats = LLMRequestStats(
                    timestamp=request_start_time.isoformat(),
                    prompt=prompt_log,
                    response=None,
                    tokens_used=None,
                    prompt_tokens=None,
                    completion_tokens=None,
                    duration_ms=duration_ms,
                    status="failure",
                    call_type=call_type or LLMCallType.OTHER,
                    attempt_id=attempt_id,
                    error=error_msg,
                    error_type=error_type,
                    model=model_to_use,
                    temperature=temperature,
                    provider="azure",
                    finish_reason=None,
                    model_params={
                        "requested_model": model_to_use,
                        "is_json": is_json,
                        "seed": seed,
                        "retry_attempt": retry,
                        "max_tokens_requested": max_tokens,
                        "system_message_provided": bool(system_message),
                        "message_count": len(messages),
                        "has_tools": bool(tools_param),
                        "tool_choice": tool_choice,
                        "agent_id": agent_id,
                        "agent_step": agent_step,
                    },
                )
                if self.stats_collector and entity_id:
                    try:
                        self.stats_collector.add_llm_request(
                            entity_id, call_type or LLMCallType.OTHER, request_stats
                        )
                    except Exception as stats_err:
                        logger.error(f"{prefix} Failed to add failure stats: {stats_err}", exc_info=True)

                if retry < total_attempts - 1:
                    sleep_time = 2 ** retry
                    logger.info(f"{prefix} Retrying in {sleep_time} seconds...")
                    await asyncio.sleep(sleep_time)
                    continue
                else:
                    break

            except Exception as e:
                last_error = e
                logger.error(f"{prefix} Attempt {retry+1}: Unexpected error during tools call: {e}", exc_info=True)

                if error_file:
                    try:
                        async with aiofiles.open(error_file, mode="a", encoding="utf-8") as f:
                            await f.write(f"--- Unexpected Error in Tools Call ({prefix} Attempt {retry+1}) ---\n")
                            await f.write(f"Timestamp: {datetime.utcnow().isoformat()}\n")
                            await f.write(f"Provider: azure\nDeployment: {deployment_to_use}\n")
                            await f.write(f"Entity ID: {entity_id}\nCall Type: {call_type.value if call_type else 'N/A'}\nAttempt ID: {attempt_id}\n")
                            await f.write(f"Error: {type(e).__name__}: {str(e)}\n")
                            await f.write("\n" + "-"*50 + "\n\n")
                    except Exception as file_err:
                        logger.error(f"{prefix} Failed writing unexpected error log: {file_err}")

                if retry < total_attempts - 1:
                    sleep_time = 2 ** retry
                    logger.info(f"{prefix} Retrying in {sleep_time} seconds...")
                    await asyncio.sleep(sleep_time)
                    continue
                else:
                    break

        if last_error:
            logger.error(f"{prefix} Tools call failed after {total_attempts} attempts ({self.max_retries} retries): {last_error}")
        else:
            logger.error(f"{prefix} Tools call failed after {total_attempts} attempts ({self.max_retries} retries) (no explicit error captured).")
        return None
