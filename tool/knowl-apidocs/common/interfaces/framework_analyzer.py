from abc import ABC, abstractmethod
from typing import Dict, List, Set, Optional, Any, Tuple
from .code_analyzer import CodeAnalyzer

class FrameworkAnalyzer(ABC):
    """
    Abstract base class for framework-specific analyzers.
    Provides methods to extract API endpoints, schema components,
    and other framework-specific information needed for OpenAPI generation.
    """
    
    def __init__(self, code_analyzer: CodeAnalyzer, project_path: str, analysis_path: str = None):
        """
        Initialize with a CodeAnalyzer implementation.
        
        Args:
            code_analyzer: Implementation of CodeAnalyzer for the language
            project_path: Root path of the project
            analysis_path: Path to existing analysis results (optional)
        """
        self.code_analyzer = code_analyzer
        self.project_path = project_path
        
        # If analysis path is provided, load previously analyzed code
        if analysis_path:
            self.analysis_results = code_analyzer.load_analysis_results(analysis_path)
        else:
            self.analysis_results = None
    
    @abstractmethod
    def get_endpoints(self) -> List[Dict[str, Any]]:
        """
        Extract API endpoints from the project.
        
        Returns:
            List of dictionaries, each containing:
                - url: Dictionary with URL pattern and parameters
                - method: HTTP method (GET, POST, etc.)
                - view: Handler class or function name
                - path: File path where the handler is defined
                - is_viewset: Whether the handler is a viewset (or controller/resource)
                - function: Function name (if viewset)
                - metadata: Framework-specific metadata
        """
        pass
    
    @abstractmethod
    def get_schema_components(self) -> Dict[str, Dict[str, Any]]:
        """
        Extract schema components from the project.
        
        Returns:
            Dictionary mapping component names to their details:
                - path: File path where the component is defined
                - is_request: Whether it's a request schema
                - is_model: Whether it's a model schema
                - fields: Component fields and their properties
        """
        pass
    
    def get_component_field_instructions(self, component_name: str) -> str:
        """
        Get framework-specific instructions for processing schema components
        
        Args:
            component_name: Name of the schema component
            
        Returns:
            Framework-specific instructions for field extraction and processing
        """
        raise NotImplementedError("Each framework implementation must provide this method")
    
    def get_component_system_message(self) -> str:
        """
        Get framework-specific instructions for processing schema components

        Returns:
            Framework-specific instructions for field extraction and processing
        """
        raise NotImplementedError("Each framework implementation must provide this method")
    
    # @abstractmethod
    # def get_authentication_mechanisms(self) -> List[Dict[str, Any]]:
    #     """
    #     Extract authentication configuration from the project.
        
    #     Returns:
    #         List of dictionaries describing authentication mechanisms
    #     """
    #     pass
    
    # @abstractmethod
    # def get_endpoint_context(self, endpoint: Dict[str, Any]) -> Dict[str, str]:
    #     """
    #     Build the context needed for OpenAPI prompt generation for an endpoint.
        
    #     Args:
    #         endpoint: Endpoint dictionary from get_endpoints()
            
    #     Returns:
    #         Dictionary containing code context needed for prompt generation:
    #             - handler_code: Code for the endpoint handler
    #             - request_schema_code: Code for request schema
    #             - response_schema_code: Code for response schema
    #             - model_code: Code for related models
    #             - auth_code: Code for authentication mechanisms
    #             - helpers_code: Code for helper functions/utilities
    #     """
    #     pass
    
    # @abstractmethod
    # def get_missing_context(self, endpoint_context: Dict[str, str], required_symbols: List[Dict[str, Any]]) -> Dict[str, str]:
    #     """
    #     Get additional code context for missing/referenced symbols.
        
    #     Args:
    #         endpoint_context: Current context dictionary
    #         required_symbols: List of required symbol information
            
    #     Returns:
    #         Updated context dictionary with additional code
    #     """
    #     pass
    
    # @abstractmethod
    # def identify_required_symbols(self, endpoint: Dict[str, Any], context: Dict[str, str]) -> List[Dict[str, Any]]:
    #     """
    #     Identify symbols required for comprehensive context.
        
    #     Args:
    #         endpoint: Endpoint dictionary
    #         context: Current context dictionary
            
    #     Returns:
    #         List of dictionaries containing information about required symbols
    #     """
    #     pass
    
    # @abstractmethod
    # def post_process_openapi_spec(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform framework-specific validation or post-processing on the OpenAPI spec.
        
        Args:
            spec: Generated OpenAPI specification
            
        Returns:
            Validated/processed OpenAPI specification
        """
        pass