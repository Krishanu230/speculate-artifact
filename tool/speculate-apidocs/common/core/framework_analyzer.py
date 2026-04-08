from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from .code_analyzer import CodeAnalyzer


class FrameworkAnalyzer(ABC):
    """
    Abstract base class for framework-specific analyzers.

    Every supported framework (Django, Spring Boot, Jersey, …) subclasses this
    and provides concrete implementations of its methods.  The class is split
    into two groups:

    Compulsory (@abstractmethod)
    ----------------------------
    Python will refuse to instantiate a subclass that is missing any of these.
    They form the minimum contract that Speculate needs to generate an OpenAPI
    specification.  If you are adding support for a new framework you MUST
    implement all of them.

    Optional (concrete defaults)
    ----------------------------
    These are part of the context-enrichment ("missing symbols") pass that
    improves specification quality but is not required for the tool to produce
    output.  Sensible no-op defaults are provided so that a minimal new
    framework implementation still runs end-to-end.  Override them to improve
    result quality.
    """

    def __init__(self, code_analyzer: CodeAnalyzer, project_path: str,
                 analysis_path: str = None):
        """
        Args:
            code_analyzer:  Language-specific CodeAnalyzer implementation.
            project_path:   Root directory of the project being analysed.
            analysis_path:  Path to pre-computed analysis results (optional).
                            When supplied the results are loaded immediately so
                            that get_endpoints() / get_schema_components() do
                            not have to re-analyse the project from scratch.
        """
        self.code_analyzer = code_analyzer
        self.project_path = project_path
        self.analysis_results = (
            code_analyzer.load_analysis_results(analysis_path)
            if analysis_path else None
        )

    # ------------------------------------------------------------------
    # Identity — COMPULSORY
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def framework_name(self) -> str:
        """
        Human-readable framework name, e.g. ``'Django'``, ``'Spring-Boot'``,
        ``'Jersey'``.  Used in LLM prompts and log messages.
        """

    @property
    def language_name(self) -> str:
        """
        Programming language for this framework, e.g. ``'python'``, ``'java'``.
        Used to select syntax highlighting and to phrase language-specific
        instructions in prompts.  Defaults to ``'unknown'``; override in every
        concrete subclass.
        """
        return "unknown"

    # ------------------------------------------------------------------
    # Project extraction — COMPULSORY
    # ------------------------------------------------------------------

    @abstractmethod
    def get_endpoints(self, output_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Extract every API endpoint from the project.

        Returns a list of endpoint dictionaries.  Each dictionary must contain:
            url         – dict with keys ``url`` (str) and ``parameter`` (list)
            method      – HTTP method string, e.g. ``'GET'``, ``'POST'``
            view        – handler class or function name (str)
            path        – absolute file path where the handler is defined (str)
            is_viewset  – True if the handler is a viewset / controller / resource
            function    – action / function name within the handler (str)
            metadata    – dict of framework-specific extra data (may be empty)
        """

    @abstractmethod
    def get_schema_components(self) -> Dict[str, Dict[str, Any]]:
        """
        Extract every schema component (serializer, DTO, POJO, …) from the
        project.

        Returns a mapping of component name → component detail dict.  Each
        detail dict must contain:
            path        – absolute file path where the component is defined
            is_request  – True if the component is used as a request body schema
            is_model    – True if the component wraps a database model
            fields      – list / dict describing the component's fields
        """

    @abstractmethod
    def get_endpoint_context(self, endpoint: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build the source-code context needed to generate the OpenAPI description
        for one endpoint.

        Args:
            endpoint: One element from the list returned by ``get_endpoints()``.

        Returns a dict whose keys are context-slot names (e.g.
        ``'handler_code'``, ``'model_code'``, ``'auth_code'``) and whose values
        are the relevant source-code strings.  Unknown keys are passed through
        to the prompt unchanged, so framework-specific slots are fine.
        """

    # ------------------------------------------------------------------
    # Component prompt generation — COMPULSORY
    # ------------------------------------------------------------------

    @abstractmethod
    def get_schema_component_terminology(self) -> str:
        """
        Return the framework-native term for a schema component, used in LLM
        prompts so the model understands what kind of object it is examining.

        Examples: ``'serializer'`` (Django), ``'POJO/DTO'`` (Java).
        """

    @abstractmethod
    def get_component_system_message(self) -> str:
        """
        Return the system-level instruction string for the component-generation
        LLM call.  This is sent as the ``system`` role message and should
        orient the model toward the framework's conventions for data schemas.
        """

    @abstractmethod
    def get_component_field_instructions(self, component_name: str,
                                         component_info: Dict[str, Any]) -> str:
        """
        Return framework-specific field-extraction instructions appended to the
        component-generation prompt.

        Args:
            component_name: Schema name as it will appear in the OpenAPI spec.
            component_info: Component detail dict from ``get_schema_components()``.

        Returns a string that is inserted verbatim into the LLM prompt.
        """

    # ------------------------------------------------------------------
    # Endpoint prompt generation — COMPULSORY
    # ------------------------------------------------------------------

    @abstractmethod
    def get_endpoint_request_system_message(self) -> str:
        """
        System-role message for the endpoint *request* LLM call.
        """

    @abstractmethod
    def get_endpoint_response_system_message(self) -> str:
        """
        System-role message for the endpoint *response* LLM call.
        """

    @abstractmethod
    def get_endpoint_common_instructions(self,
                                         skip_components: bool = False) -> str:
        """
        Instructions that are shared between the request and response prompts
        for every endpoint (e.g. output format rules, what to omit).

        Args:
            skip_components: When True the prompt should instruct the model not
                             to emit ``$ref`` component references.
        """

    @abstractmethod
    def get_endpoint_request_instructions(self, endpoint: Dict[str, Any],
                                          endpoint_context: Dict[str, Any],
                                          skip_components: bool = False) -> str:
        """
        Full user-turn instructions for generating the *request* portion of an
        endpoint's OpenAPI entry.

        Args:
            endpoint:         Endpoint dict from ``get_endpoints()``.
            endpoint_context: Context dict from ``get_endpoint_context()``.
            skip_components:  Passed through from the generation pipeline.
        """

    @abstractmethod
    def get_endpoint_response_instructions(self, endpoint: Dict[str, Any],
                                           endpoint_context: Dict[str, Any],
                                           skip_components: bool = False) -> str:
        """
        Full user-turn instructions for generating the *response* portion of an
        endpoint's OpenAPI entry.

        Args:
            endpoint:         Endpoint dict from ``get_endpoints()``.
            endpoint_context: Context dict from ``get_endpoint_context()``.
            skip_components:  Passed through from the generation pipeline.
        """

    @abstractmethod
    def get_endpoint_request_framework_specific_notes(self) -> str:
        """
        Short framework-specific addendum appended to every request prompt,
        e.g. notes about authentication decorators or routing conventions.
        Return an empty string if there is nothing framework-specific to add.
        """

    @abstractmethod
    def get_endpoint_response_framework_specific_notes(self) -> str:
        """
        Short framework-specific addendum appended to every response prompt,
        e.g. notes about pagination wrappers or error envelope conventions.
        Return an empty string if there is nothing framework-specific to add.
        """

    @abstractmethod
    def is_relaxed_obj_validation(self) -> bool:
        """
        Return ``True`` if the OpenAPI spec validator should accept ``object``
        schemas that lack a ``properties`` definition, ``False`` to enforce
        strict object validation.

        Use ``True`` for frameworks whose generated schemas commonly use
        free-form objects (e.g. dynamic response envelopes in Django), and
        ``False`` for statically-typed frameworks (Spring Boot, Jersey) where
        every object schema is expected to have explicit properties.
        """

    # ------------------------------------------------------------------
    # Context enrichment — OPTIONAL
    #
    # These methods support the "missing symbols" pass that fetches additional
    # source-code context before the main LLM generation step.  Overriding
    # them improves specification quality but the defaults below are sufficient
    # for a working (if lower-quality) implementation.
    # ------------------------------------------------------------------

    def optimize_context(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Trim or reorder the context dict before it is sent to the LLM in order
        to stay within token limits.

        The default implementation returns ``context`` unchanged.  Override to
        remove low-value slots, truncate large code blocks, or reorder entries
        so the most relevant code appears first.

        Args:
            context: Context dict from ``get_endpoint_context()``.
        """
        return context

    def get_missing_context(self, initial_context: Dict[str, Any],
                            required_symbols: List[Dict[str, Any]],
                            max_depth: int = 2) -> Dict[str, Any]:
        """
        Fetch additional source-code context for symbols that the LLM reported
        as missing from the initial context.

        The default implementation returns ``initial_context`` unchanged (i.e.
        no extra context is fetched).  Override to resolve symbols via the
        ``code_analyzer`` and merge the results into the context dict.

        Args:
            initial_context:  Context dict built by ``get_endpoint_context()``.
            required_symbols: List of symbol dicts parsed from the LLM's
                              "missing context" response.
            max_depth:        How many levels of transitive dependencies to
                              follow when resolving symbols.
        """
        return initial_context

    def parse_missing_symbols_response(self,
                                       response_content: str,
                                       ) -> List[Dict[str, Any]]:
        """
        Parse the LLM's free-text response to the "what context is missing?"
        prompt and return a structured list of symbols to look up.

        The default implementation returns an empty list (no symbols resolved).
        Override to extract symbol names, types, and file hints from the
        response text using framework-aware heuristics.

        Args:
            response_content: Raw text returned by the LLM.
        """
        return []

    def get_initial_context_presentation_for_missing_symbols(
            self,
            endpoint: Dict[str, Any],
            endpoint_context: Dict[str, Any]) -> str:
        """
        Format the initial context as the opening section of the
        "missing symbols" prompt so the LLM can identify what is absent.

        The default implementation returns an empty string, which disables the
        missing-symbols pass for this framework.

        Args:
            endpoint:         Endpoint dict from ``get_endpoints()``.
            endpoint_context: Context dict from ``get_endpoint_context()``.
        """
        return ""

    def get_framework_specific_guidance_for_missing_symbols(self) -> str:
        """
        Return framework-specific guidance appended to the "what is missing?"
        prompt, e.g. explaining which symbols are always available via the
        framework itself and need not be fetched.

        The default implementation returns an empty string.
        """
        return ""

    def get_framework_specific_exclusion_instructions_for_missing_symbols(
            self) -> str:
        """
        Return instructions that tell the LLM which symbol types to exclude
        when reporting missing context (e.g. built-in framework classes that
        are always available).

        The default implementation returns an empty string.
        """
        return ""
