from dataclasses import dataclass, asdict, field
from datetime import datetime
import logging
import shutil
from typing import List, Dict, Any, Optional, Tuple
import json
import threading
from enum import Enum
import os
from pathlib import Path
import uuid

class LLMCallType(Enum):
    # Serializer related
    SERIALIZER_SCHEMA = "serializer_schema"
    # Endpoint related
    ENDPOINT_EXTRA_CODE = "endpoint_extra_code"
    ENDPOINT_REQUEST = "endpoint_request"
    ENDPOINT_RESPONSE = "endpoint_response"
    ENDPOINT_SECURITY = "endpoint_security"
    AGENT_PLAN = "agent_plan"
    AGENT_TOOL_DECISION = "agent_tool_decision"
    AGENT_SYNTHESIS = "agent_synthesis"
    # For any unclassified calls
    OTHER = "other"

class EntityType(Enum):
    SERIALIZER = "serializer"
    ENDPOINT = "endpoint"
    
class EntityStatus(Enum):
    # Lifecycle
    IN_PROGRESS = "in_progress"          # Default starting state
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"

    # Pre-computation Failures
    FAILED_CONTEXT = "failed_context"      # Could not retrieve necessary initial code context

    # LLM Interaction Failures
    FAILED_LLM_CALL = "failed_llm_call"    # LLM API call failed after all API-level retries
    FAILED_SCHEMA = "failed_schema"        # LLM returned unusable/garbage content (pre-validation)

    # Validation Failures (during sanitize_and_validate_content)
    FAILED_YAML = "failed_yaml"            # Basic YAML parsing failed
    FAILED_VALIDATION = "failed_validation" # OpenAPI structure/syntax error (SpecsWalker)
    FAILED_REFERENCE = "failed_reference"    # Broken $ref links found

    # Post-validation Failures
    FAILED_SPEC_ADD = "failed_spec_add"      # Error adding validated content to SpecManager internal spec

    # Other Outcomes
    IGNORED = "ignored"                # Explicitly marked as <-|NOT_REQUIRED|-> by LLM
    FAILED_UNKNOWN = "failed_unknown"
    PARSE_MISSING_SYMBOLS = "parse_missing_symbols"    

@dataclass
class ToolCallStats:
    timestamp: str
    tool_name: str                       # e.g., "fs.read", "symbols.info"
    arguments: Dict[str, Any]            # sanitized/truncated arguments
    duration_ms: int
    status: str                          # "success" | "failure"
    result_size_bytes: Optional[int] = None   # length of string payload, if any
    result_count: Optional[int] = None        # e.g., matches found
    error: Optional[str] = None
    result_summary: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)
    
@dataclass
class LLMRequestStats:
    timestamp: str
    prompt: Optional[str]
    response: Optional[str]
    tokens_used: Optional[int]
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    duration_ms: int
    status: str  # success/failure
    call_type: LLMCallType
    attempt_id: Optional[str]

    error: Optional[str] = None
    error_type: Optional[str] = None

    provider: Optional[str] = None
    model: Optional[str] = None
    finish_reason: Optional[str] = None 

    cost_usd: Optional[float] = None
    temperature: Optional[float] = None
    model_params: Dict[str, Any] = field(default_factory=dict)
    reasoning_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None
    
    def to_dict(self) -> Dict:
        data = asdict(self)
        if isinstance(self.call_type, Enum):
            data['call_type'] = self.call_type.value
        return data

    @staticmethod
    def calculate_cost(
        model_name: Optional[str],
        provider: Optional[str],
        prompt_tokens: Optional[int],
        completion_tokens: Optional[int],
        total_tokens: Optional[int] # Keep for potential fallback if needed
        ) -> Optional[float]:
        """
        Calculate estimated cost based on provider, model, and token counts.
        Uses separate input/output pricing where applicable.
        Rates based on provided pricing screenshots (mid-April 2025).
        Returns None if cost cannot be determined.
        """
        if not model_name or not provider:
            logging.warning(f"Cannot calculate cost: Missing model_name ('{model_name}') or provider ('{provider}').")
            return None

        prompt_tokens = prompt_tokens or 0
        completion_tokens = completion_tokens or 0
        cost = 0.0
        calculated = False
        provider_lower = provider.lower()
        # Normalize model name key (lowercase, underscores) for dictionary lookup
        normalized_model_key = model_name.lower().replace('-', '_').replace('.', '_')

        # --- Pricing Structure (USD per 1,000 tokens) ---
        # IMPORTANT: Verify rates periodically. Gemini 1.5 rates are APPROXIMATED from character pricing.
        GEMINI_PRICING = {
            # Gemini 2.5 (Preview <= 200k context)
            "gemini_2_5_pro_preview_03_25": {"input": 0.00125, "output": 0.010},
            "gemini_2_5_flash_preview_04_17": {"input": 0.00015, "output": 0.0035}, # Using 'thinking' output rate

            # Gemini 2.0
            "gemini_2_0_flash": {"input": 0.00015, "output": 0.0006},
            "gemini_2_0_flash_001": {"input": 0.00015, "output": 0.0006}, # Assume same as latest
            "gemini_2_0_flash_lite": {"input": 0.000075, "output": 0.0003},
            "gemini_2_0_flash_lite_001": {"input": 0.000075, "output": 0.0003}, # Assume same as latest

            # Gemini 1.5 (APPROXIMATED from characters @ ~4 chars/token)
            "gemini_1_5_pro": {"input": 0.00125, "output": 0.005}, # Approx from $0.0003125 / $0.00125 per 1k chars
            "gemini_1_5_pro_latest": {"input": 0.00125, "output": 0.005}, # Approx
            "gemini_1_5_pro_001": {"input": 0.00125, "output": 0.005}, # Approx
            "gemini_1_5_pro_002": {"input": 0.00125, "output": 0.005}, # Approx

            "gemini_1_5_flash": {"input": 0.000075, "output": 0.0003}, # Approx from $0.00001875 / $0.000075 per 1k chars
            "gemini_1_5_flash_latest": {"input": 0.000075, "output": 0.0003}, # Approx
            "gemini_1_5_flash_001": {"input": 0.000075, "output": 0.0003}, # Approx
            "gemini_1_5_flash_002": {"input": 0.000075, "output": 0.0003}, # Approx

            # Gemini 1.5 Flash 8B (Assuming same price as 1.5 Flash - VERIFY!)
            "gemini_1_5_flash_8b": {"input": 0.000075, "output": 0.0003}, # Approx - VERIFY
            "gemini_1_5_flash_8b_latest": {"input": 0.000075, "output": 0.0003}, # Approx - VERIFY
            "gemini_1_5_flash_8b_001": {"input": 0.000075, "output": 0.0003}, # Approx - VERIFY

            # Older gemini-pro (placeholder, might be specific Vertex version/region)
            "gemini_pro": {"input": 0.000125, "output": 0.000375}, # Keep previous placeholder - VERIFY if used

            # Embedding Models (Priced per 1k tokens total input) - VERIFY RATES!
            "text_embedding_004": {"total": 0.00002}, # Example: $0.02/1M tokens
            "gemini_embedding_exp": {"total": 0.0}, # TODO: Find actual rate

        }

        AZURE_PRICING = {
            # GPT-5 Series (from image)
            "gpt_5": {"input": 0.00125, "output": 0.010},       # Price per 1k tokens
            "gpt_5_mini": {"input": 0.00025, "output": 0.002},  # Price per 1k tokens
            "gpt_5_nano": {"input": 0.00005, "output": 0.0004}, # Price per 1k tokens
            "gpt_5_chat": {"input": 0.00125, "output": 0.010},  # Price per 1k tokens
            
            # O-series Models
            "gpt_o1": {"input": 0.015, "output": 0.060},       # Official Name: o1
            "o3_mini": {"input": 0.0011, "output": 0.00440},   # Official Name: o3-mini
            "o4_mini": {"input": 0.0011, "output": 0.0044},    # Official Name: o4-mini
            
            # GPT-4o Series
            "gpt_4o": {"input": 0.005, "output": 0.015},       # Official Name: gpt-4o
            "gpt_4o_mini": {"input": 0.00015, "output": 0.0006}, # Official Name: gpt-4o-mini
            
            # GPT-4 Turbo Series
            "gpt_4_5_preview": {"input": 0.075, "output": 0.150}, # Official Name: gpt-4.5-preview
            
            # GPT-4.1 Series
            "gpt_4_1": {"input": 0.002, "output": 0.008},       # Official Name: gpt-4.1
            "gpt_4_1_mini": {"input": 0.0004, "output": 0.0016},   # Official Name: gpt-4.1-mini
            "gpt_4_1_nano": {"input": 0.00005, "output": 0.0001}, # Official Name: gpt-4.1-nano
            
            # Text & Code Models (Phi-3)
            "phi_3_mini": {"input": 0.00025, "output": 0.00025}, # Official Name: phi-3-mini
            "phi_3_small": {"input": 0.0005, "output": 0.0005},  # Official Name: phi-3-small
            "phi_3_medium": {"input": 0.002, "output": 0.002},   # Official Name: phi-3-medium
            
            # Embedding Models (Priced per 1k tokens total input)
            "text_embedding_3_large": {"total": 0.0001},     # Official Name: text-embedding-3-large
            "text_embedding_3_small": {"total": 0.00002},     # Official Name: text-embedding-3-small
            "text_embedding_ada_002": {"total": 0.0001},     # Official Name: text-embedding-ada-002

            "deepseek_r1":{"input":0.00135, "output":0.0054},
        }
        # --- End Pricing Structure ---


        if provider_lower == "gemini":
            matched_rate = GEMINI_PRICING.get(normalized_model_key) # Use .get for safer lookup
            if matched_rate:
                if "input" in matched_rate and "output" in matched_rate:
                    input_cost = (prompt_tokens / 1000) * matched_rate["input"]
                    output_cost = (completion_tokens / 1000) * matched_rate["output"]
                    cost = input_cost + output_cost
                    calculated = True
                elif "total" in matched_rate: # Handle embedding models
                    total_tokens_calc = total_tokens or (prompt_tokens + completion_tokens)
                    cost = (total_tokens_calc / 1000) * matched_rate["total"]
                    calculated = True
                else:
                    logging.warning(f"Gemini pricing rate format for '{normalized_model_key}' is unexpected: {matched_rate}. Cost calculation failed.")
            else:
                 logging.warning(f"No Gemini pricing found for model: {model_name} (normalized: {normalized_model_key}). Cost calculation skipped.")

        elif provider_lower == "azure":
            matched_rate = AZURE_PRICING.get(normalized_model_key) # Use .get
            if matched_rate:
                if "input" in matched_rate and "output" in matched_rate:
                    input_cost = (prompt_tokens / 1000) * matched_rate["input"]
                    output_cost = (completion_tokens / 1000) * matched_rate["output"]
                    cost = input_cost + output_cost
                    calculated = True
                else:
                    logging.warning(f"Azure pricing rate format for '{normalized_model_key}' is unexpected: {matched_rate}. Cost calculation failed.")
            else:
                 logging.warning(f"No Azure pricing found for model: {model_name} (normalized: {normalized_model_key}). Cost calculation skipped.")

        else:
            logging.warning(f"Unsupported provider for cost calculation: {provider}. Cost calculation skipped.")

        # Return calculated cost (float) or None if calculation failed/skipped
        return cost if calculated else None

@dataclass
class ValidationAttempt:
    """Represents a single validation attempt after an LLM call."""
    timestamp: str
    attempt_id: str
    is_valid: bool
    errors: Optional[List[str]] = None

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class EntityStats:
    entity_type: EntityType
    entity_id: str  # serializer name or endpoint url+method
    start_time: str
    end_time: Optional[str] = None
    duration_ms: Optional[int] = None
    status: EntityStatus = EntityStatus.IN_PROGRESS
    error: Optional[str] = None
    error_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    llm_requests: List[LLMRequestStats] = field(default_factory=list)
    
    validation_attempts: List[ValidationAttempt] = field(default_factory=list)
    validation_retry_count: int = 0 
    
    extra_code_requested: bool = False
    extra_code_count: int = 0
    extra_code_components: List[str] = field(default_factory=list)
    tool_calls: List[ToolCallStats] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    name_conflict_details: List[Dict[str, str]] = field(default_factory=list)

    def add_validation_attempt(self, validation_attempt: ValidationAttempt):
        """Adds a validation attempt stat and updates retry count."""
        self.validation_attempts.append(validation_attempt)
        linked_llm_call = next((call for call in self.llm_requests if call.attempt_id == validation_attempt.attempt_id), None)
        if linked_llm_call:
            # Get the retry attempt number from the LLM call's model_params
            llm_attempt_number = linked_llm_call.model_params.get("retry_attempt", 0) # Default to 0 if missing
            # Increment if this is the validation for attempt 0 and it failed
            if llm_attempt_number == 0 and not validation_attempt.is_valid:
                self.validation_retry_count += 1

    def track_extra_code(self, components: List[str]):
        """Track when extra code is requested"""
        self.extra_code_requested = True
        self.extra_code_count += 1
        self.extra_code_components.extend(components)

    def to_dict(self) -> Dict:
        """Serializes the entity stats to a dictionary."""
        base_dict = asdict(self)
        base_dict['entity_type'] = self.entity_type.value
        base_dict['status'] = self.status.value
        base_dict['llm_requests'] = [req.to_dict() for req in self.llm_requests]
        base_dict['validation_attempts'] = [attempt.to_dict() for attempt in self.validation_attempts]
        base_dict['tool_calls'] = [tc.to_dict() for tc in self.tool_calls]
        return base_dict

    def add_llm_request(self, request_stats: LLMRequestStats):
        """Adds an LLM request stat, associated with its call type."""
        self.llm_requests.append(request_stats)

    def add_tool_call(self, tool_call: ToolCallStats):
        self.tool_calls.append(tool_call)

@dataclass
class GlobalStats:
    run_id: str
    start_time: str
    repo_name: str
    end_time: Optional[str] = None
    duration_ms: Optional[int] = None
    total_validation_retries: int = 0
    
    # Token and cost tracking
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost_usd: float = 0
    
    # New: LLM call statistics
    total_llm_calls: int = 0
    successful_llm_calls: int = 0
    failed_llm_calls: int = 0
    avg_llm_call_duration_ms: float = 0
    avg_tokens_per_call: float = 0
    
    total_validation_retries: int = 0

    metadata: Dict[str, Any] = field(default_factory=dict)

    serializer_counts: Dict[EntityStatus, int] = field(default_factory=lambda: { status: 0 for status in EntityStatus })
    total_serializers: int = 0
    serializer_stats: List[EntityStats] = field(default_factory=list)

    # Endpoint stats
    endpoint_counts: Dict[EntityStatus, int] = field(default_factory=lambda: { status: 0 for status in EntityStatus })
    total_endpoints: int = 0
    endpoint_stats: List[EntityStats] = field(default_factory=list)

    # Breakdown by call type
    calls_by_type: Dict[LLMCallType, int] = field(default_factory=lambda: { ct: 0 for ct in LLMCallType })
    tokens_by_type: Dict[LLMCallType, int] = field(default_factory=lambda: { ct: 0 for ct in LLMCallType })
    cost_by_type: Dict[LLMCallType, float] = field(default_factory=lambda: { ct: 0.0 for ct in LLMCallType })
    avg_duration_by_type: Dict[LLMCallType, Tuple[float, int]] = field(default_factory=lambda: { ct: (0.0, 0) for ct in LLMCallType })

    total_tool_calls: int = 0
    successful_tool_calls: int = 0
    failed_tool_calls: int = 0
    avg_tool_call_duration_ms: float = 0.0
    tool_calls_by_name: Dict[str, int] = field(default_factory=dict)
    total_reasoning_tokens: int = 0
    total_cached_tokens: int = 0

    def to_dict(self) -> Dict:
        final_avg_duration_by_type = {
            ct.value: (total_dur / count) if count > 0 else 0.0
            for ct, (total_dur, count) in self.avg_duration_by_type.items()
        }
        
        base_dict = asdict(self)
        del base_dict['serializer_stats']
        del base_dict['endpoint_stats']
        del base_dict['serializer_counts']
        del base_dict['endpoint_counts']
        del base_dict['calls_by_type']
        del base_dict['tokens_by_type']
        del base_dict['cost_by_type']
        del base_dict['avg_duration_by_type']

        
        return {
             **base_dict,
             "llm_stats": {
                 "total_calls": self.total_llm_calls,
                 "successful_calls": self.successful_llm_calls,
                 "failed_calls": self.failed_llm_calls,
                 "avg_duration_ms": self.avg_llm_call_duration_ms,
                 "avg_tokens_per_call": self.avg_tokens_per_call,
                 "total_tokens": self.total_tokens,
                 "prompt_tokens": self.prompt_tokens,
                 "completion_tokens": self.completion_tokens,
                 "total_cost_usd": self.total_cost_usd,
                 "by_call_type": {
                    call_type.value: {
                        "calls": self.calls_by_type.get(call_type, 0),
                        "tokens": self.tokens_by_type.get(call_type, 0),
                        "cost_usd": self.cost_by_type.get(call_type, 0.0),
                        "avg_duration_ms": final_avg_duration_by_type.get(call_type.value, 0.0)
                    } for call_type in LLMCallType
                 }
             },
             "validation_stats": {
                  "total_validation_retries": self.total_validation_retries
             },
             "serializers": {
                 "total": self.total_serializers,
                 "status_counts": {k.value: v for k, v in self.serializer_counts.items()},
                 "entities": [s.to_dict() for s in self.serializer_stats]
             },
             "endpoints": {
                 "total": self.total_endpoints,
                 "status_counts": {k.value: v for k, v in self.endpoint_counts.items()},
                 "entities": [e.to_dict() for e in self.endpoint_stats]
             },
             "metadata": self.metadata,
             "tool_stats": {
                "total_calls": self.total_tool_calls,
                "successful_calls": self.successful_tool_calls,
                "failed_calls": self.failed_tool_calls,
                "avg_duration_ms": self.avg_tool_call_duration_ms,
                "by_tool_name": self.tool_calls_by_name
            }
        }


class StatsCollector:
    """Thread-safe stats collector that manages global, entity and LLM request stats"""
    
    def __init__(self, repo_name: str, output_dir: str, logger):
        self.run_id = str(uuid.uuid4())
        self.global_stats = GlobalStats(
            run_id=self.run_id,
            start_time=datetime.utcnow().isoformat(),
            repo_name=repo_name
        )
        self.output_dir = output_dir
        self._lock = threading.Lock()
        self._entity_map: Dict[str, EntityStats] = {}
        self.logger = logger or logging.getLogger(__name__)
        
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    def add_llm_request(self, entity_id: str, call_type: LLMCallType, request_stats: LLMRequestStats):
        """Add stats for an LLM request to an entity and update global stats."""
        with self._lock:
            if entity_id not in self._entity_map:
                self.logger.warning(f"Entity '{entity_id}' not found when adding LLM request for call type '{call_type.value}'. Request ignored for this entity.")
                return

            entity = self._entity_map[entity_id]
            # Ensure the call_type from request_stats is used if available
            call_type = request_stats.call_type # Use the enum from the stats object

            entity.add_llm_request(request_stats)

            # --- Update Global Stats ---
            self.global_stats.total_llm_calls += 1

            if request_stats.status == "success":
                self.global_stats.successful_llm_calls += 1
            else:
                self.global_stats.failed_llm_calls += 1

            # Update global duration average incrementally
            count = self.global_stats.total_llm_calls
            old_avg_dur = self.global_stats.avg_llm_call_duration_ms
            # Avoid division by zero if count somehow becomes 0 (shouldn't happen here)
            if count > 0:
                self.global_stats.avg_llm_call_duration_ms += (request_stats.duration_ms - old_avg_dur) / count
            else: # Should only happen on the very first call if logic was different
                 self.global_stats.avg_llm_call_duration_ms = request_stats.duration_ms


            # Update call type specific counts and duration accumulator
            self.global_stats.calls_by_type[call_type] = self.global_stats.calls_by_type.get(call_type, 0) + 1

            current_dur_total, current_dur_count = self.global_stats.avg_duration_by_type.get(call_type, (0.0, 0))

            # Calculate the new total duration and count
            new_total_dur = current_dur_total + request_stats.duration_ms
            new_count = current_dur_count + 1

            # Store the UPDATED TUPLE back into the dictionary
            self.global_stats.avg_duration_by_type[call_type] = (new_total_dur, new_count)

            # Update global token counts and averages if available
            if request_stats.tokens_used is not None:
                self.global_stats.total_tokens += request_stats.tokens_used
                old_avg_tokens = self.global_stats.avg_tokens_per_call
                if count > 0:
                     self.global_stats.avg_tokens_per_call += (request_stats.tokens_used - old_avg_tokens) / count
                else:
                     self.global_stats.avg_tokens_per_call = request_stats.tokens_used

                # Update tokens by type
                self.global_stats.tokens_by_type[call_type] = self.global_stats.tokens_by_type.get(call_type, 0) + request_stats.tokens_used

            if request_stats.prompt_tokens is not None:
                self.global_stats.prompt_tokens += request_stats.prompt_tokens
            if request_stats.completion_tokens is not None:
                self.global_stats.completion_tokens += request_stats.completion_tokens
            
            if request_stats.reasoning_tokens is not None:
                self.global_stats.total_reasoning_tokens += request_stats.reasoning_tokens
            if request_stats.cached_tokens is not None:
                self.global_stats.total_cached_tokens += request_stats.cached_tokens

            # Update global cost if available
            if request_stats.cost_usd is not None:
                self.global_stats.total_cost_usd += request_stats.cost_usd
                # Update cost by type
                self.global_stats.cost_by_type[call_type] = self.global_stats.cost_by_type.get(call_type, 0.0) + request_stats.cost_usd

    def add_tool_call(self, entity_id: str, tool_call: ToolCallStats):
        with self._lock:
            if entity_id not in self._entity_map:
                self.logger.warning(f"Entity '{entity_id}' not found when adding tool call '{tool_call.tool_name}'.")
                return

            entity = self._entity_map[entity_id]
            entity.add_tool_call(tool_call)

            # Global counters
            self.global_stats.total_tool_calls += 1
            if tool_call.status == "success":
                self.global_stats.successful_tool_calls += 1
            else:
                self.global_stats.failed_tool_calls += 1

            # Average duration (incremental)
            count = self.global_stats.total_tool_calls
            old_avg = self.global_stats.avg_tool_call_duration_ms
            if count > 0:
                self.global_stats.avg_tool_call_duration_ms += (tool_call.duration_ms - old_avg) / count
            else:
                self.global_stats.avg_tool_call_duration_ms = tool_call.duration_ms

            # By tool name
            self.global_stats.tool_calls_by_name[tool_call.tool_name] = \
                self.global_stats.tool_calls_by_name.get(tool_call.tool_name, 0) + 1


    def track_extra_code(self, entity_id: str, components: List[str]):
        """Track when extra code is requested for an entity"""
        with self._lock:
            if entity_id not in self._entity_map:
                self.logger.warning(f"Entity '{entity_id}' not found when tracking extra code.")
                return
            
            entity = self._entity_map[entity_id]
            entity.track_extra_code(components)
        
    def _get_stats_file_path(self) -> str:
        """Get path for stats JSON file with run ID"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_repo_name = self.global_stats.repo_name.replace('/', '_').replace('\\', '_')
        filename = f"{safe_repo_name}_stats_{timestamp}_{self.run_id[:8]}.json"
        return os.path.join(self.output_dir, filename)

    def start_entity(self, entity_type: EntityType, entity_id: str, metadata: Optional[Dict] = None) -> str:
        """Start tracking stats for a new entity"""
        with self._lock:
            if entity_id in self._entity_map:
                 self.logger.warning(f"Entity '{entity_id}' already started. Reusing existing entry.")
                 # Optionally update metadata? For now, just return existing ID.
                 return entity_id
            
            stats = EntityStats(
                entity_type=entity_type,
                entity_id=entity_id,
                start_time=datetime.utcnow().isoformat(),
                metadata=metadata or {}
            )
            self._entity_map[entity_id] = stats
            
            if entity_type == EntityType.SERIALIZER:
                self.global_stats.total_serializers += 1
                self.global_stats.serializer_counts[EntityStatus.IN_PROGRESS] += 1
            elif entity_type == EntityType.ENDPOINT:
                self.global_stats.total_endpoints += 1
                self.global_stats.endpoint_counts[EntityStatus.IN_PROGRESS] += 1
            else:
                 self.logger.warning(f"Unhandled entity type '{entity_type}' in start_entity.")

            return entity_id

    def update_entity_status(self, 
                           entity_id: str, 
                           status: EntityStatus, 
                           error: Optional[str] = None,
                           error_type: Optional[str] = None,
                           end: bool = True):
        """Update entity status with optional error info"""
        with self._lock:
            if entity_id not in self._entity_map:
                self.logger.warning(f"Entity '{entity_id}' not found when updating status to '{status.value}'.")
                return
                
            entity = self._entity_map[entity_id]
            
            # Update status
            old_status = entity.status
            entity.status = status
            
            # Update error info if provided
            if error:
                entity.error = error
            if error_type:
                entity.error_type = error_type
            
            counts_dict = None
            if entity.entity_type == EntityType.SERIALIZER:
                counts_dict = self.global_stats.serializer_counts
            elif entity.entity_type == EntityType.ENDPOINT:
                counts_dict = self.global_stats.endpoint_counts

            if counts_dict is not None:
                 # Decrement old status count if it wasn't the initial IN_PROGRESS
                 if old_status in counts_dict:
                    counts_dict[old_status] = counts_dict.get(old_status, 0) - 1
                 # Increment new status count
                 counts_dict[status] = counts_dict.get(status, 0) + 1
                 # Ensure counts don't go negative (shouldn't happen with correct logic)
                 if counts_dict[old_status] < 0: counts_dict[old_status] = 0
            
            if end and entity.end_time is None: # Only set end time once
                end_time_dt = datetime.utcnow()
                entity.end_time = end_time_dt.isoformat()
                try:
                    start_time_dt = datetime.fromisoformat(entity.start_time)
                    entity.duration_ms = int((end_time_dt - start_time_dt).total_seconds() * 1000)
                except ValueError:
                    self.logger.error(f"Could not parse start_time '{entity.start_time}' for entity '{entity_id}' to calculate duration.")
                    entity.duration_ms = -1 # Indicate error

    def add_validation_attempt(self, entity_id: str, validation_attempt: ValidationAttempt):
        with self._lock:
            if entity_id not in self._entity_map:
                self.logger.warning(f"Entity '{entity_id}' not found when adding validation attempt.")
                return
            entity = self._entity_map[entity_id]
            entity.add_validation_attempt(validation_attempt)

            linked_llm_call = next((call for call in entity.llm_requests if call.attempt_id == validation_attempt.attempt_id), None)
            if linked_llm_call:
                 llm_attempt_number = linked_llm_call.model_params.get("retry_attempt", 0)
                 if llm_attempt_number == 0 and not validation_attempt.is_valid:
                       self.global_stats.total_validation_retries += 1

    def finalize(self) -> str:
        """Finalize stats collection and save to file"""
        with self._lock:
            end_time_dt = datetime.utcnow()
            self.global_stats.end_time = end_time_dt.isoformat()

            if self.global_stats.start_time:
                 try:
                    start_time_dt = datetime.fromisoformat(self.global_stats.start_time)
                    self.global_stats.duration_ms = int((end_time_dt - start_time_dt).total_seconds() * 1000)
                 except ValueError:
                      self.logger.error(f"Could not parse global start_time '{self.global_stats.start_time}' to calculate duration.")
                      self.global_stats.duration_ms = -1
            else:
                 self.global_stats.duration_ms = 0

            # --- Populate the lists before serializing ---
            self.global_stats.serializer_stats = []
            self.global_stats.endpoint_stats = []
            for entity_id, entity in self._entity_map.items():
                # Final check: if entity is still in progress, mark as unknown failure
                if entity.status == EntityStatus.IN_PROGRESS:
                    self.logger.warning(f"Entity '{entity_id}' was still IN_PROGRESS during finalize. Marking as FAILED_UNKNOWN.")
                    self.update_entity_status(
                        entity_id,
                        EntityStatus.FAILED_UNKNOWN,
                        error="Processing did not complete before finalize was called.",
                        end=True
                    )
                    entity = self._entity_map[entity_id]

                if entity.entity_type == EntityType.SERIALIZER:
                    self.global_stats.serializer_stats.append(entity)
                else:  # EntityType.ENDPOINT
                    self.global_stats.endpoint_stats.append(entity)
            # --------------------------------------------

            stats_file = self._get_stats_file_path()
            try:
                final_stats_dict = self.global_stats.to_dict()
                with open(stats_file, 'w', encoding='utf-8') as f:
                    json.dump(final_stats_dict, f, indent=2, ensure_ascii=False)
                self.logger.info(f"Successfully saved final stats to: {stats_file}")

                # Generate HTML dashboard using the final dictionary
                html_file = stats_file.replace('.json', '.html')
                self._generate_html_dashboard(html_file, final_stats_dict)

            except Exception as e:
                self.logger.error(f"Failed to save final stats or generate dashboard: {e}", exc_info=True)
                return "" # Return empty string or raise error on failure

            return stats_file

    def _generate_html_dashboard(self, html_file_path: str, stats_data: dict):
        """Generate HTML dashboard with stats visualization, including retries and failures."""
        # --- MINIMAL HTML TEMPLATE (Focus on React part) ---
        try:
            script_dir = Path(__file__).parent
            template_dir = script_dir / './templates/stats/'
            html_template_path = template_dir / "dashboard.html"
            css_template_path = template_dir / "dashboard.css"
            js_template_path = template_dir / "dashboard.js"

            with open(html_template_path, 'r', encoding='utf-8') as f:
                html_content = f.read()

                # --- Inject JSON Data ---
                # Convert Python dict to JSON string. Use ensure_ascii=False for broader compatibility.
            json_data_string = json.dumps(stats_data, ensure_ascii=False)
                # Replace the placeholder. Be careful with escaping if stats_data could contain HTML/JS problematic chars.
                # Using a simple placeholder like shown should be safe if JSON is valid.
            html_content = html_content.replace(
                    '{/* STATS_DATA_JSON_PLACEHOLDER */}',
                    json_data_string
                )

                # --- Write Final HTML ---
            output_dir = Path(html_file_path).parent
            output_dir.mkdir(parents=True, exist_ok=True) # Ensure output dir exists
            with open(html_file_path, 'w', encoding='utf-8') as f:
                    f.write(html_content)
            self.logger.info(f"Generated HTML dashboard at: {html_file_path}")

                # --- Copy CSS and JS Assets ---
            try:
                    # Copy CSS file to the same directory as the HTML output
                    shutil.copy2(css_template_path, output_dir / css_template_path.name)
                    # Copy JS file to the same directory as the HTML output
                    shutil.copy2(js_template_path, output_dir / js_template_path.name)
                    self.logger.info(f"Copied dashboard assets (CSS, JS) to: {output_dir}")
            except Exception as copy_err:
                    self.logger.error(f"Error copying dashboard assets to {output_dir}: {copy_err}", exc_info=True)

        except FileNotFoundError as e:
             self.logger.error(f"Error finding template file: {e}", exc_info=True)
        except Exception as e:
            self.logger.error(f"Error generating HTML dashboard: {e}", exc_info=True)

    def add_entity_tag(self, entity_id: str, tag: str):
        """Adds a tag to a specific entity's stats."""
        with self._lock:
            if entity_id not in self._entity_map:
                self.logger.warning(f"Entity '{entity_id}' not found when adding tag '{tag}'.")
                return
            entity = self._entity_map[entity_id]
            if tag not in entity.tags:
                entity.tags.append(tag)
