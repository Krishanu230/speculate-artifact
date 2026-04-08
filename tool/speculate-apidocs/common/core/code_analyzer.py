from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Set, Optional, Any, Tuple

class SymbolType(Enum):
    CLASS = "class"
    FUNCTION = "function"
    VARIABLE = "variable"
    FILE_IDENTIFIER = "file_identifier"

    def analysis_key(self) -> str:
        """
        Returns the plural version of the identifier.
        
        Examples:
        AnalysisIdentifier.CLASS.plural() -> "classes"
        AnalysisIdentifier.FUNCTION.plural() -> "functions"
        """
        plurals = {
            SymbolType.CLASS: "classes",
            SymbolType.FUNCTION: "functions", 
            SymbolType.VARIABLE: "variables",
            SymbolType.FILE_IDENTIFIER: "file_identifiers"
        }
        return plurals[self]
        
class CodeAnalyzer(ABC):
    """
    Base interface for language-specific code analyzers.
    Provides methods to analyze code structure, resolve dependencies,
    and extract code snippets for OpenAPI generation.
    """
    
    @abstractmethod
    def analyze_project(self, project_path: str, output_dir: str,
                        framework: str) -> Optional[str]:
        """
        Analyze an entire project and persist the results.

        Args:
            project_path: Path to the root directory of the project.
            output_dir:   Directory where analysis results should be stored.
            framework:    Framework identifier (e.g. ``'spring'``, ``'jersey'``,
                          ``'django'``).  Passed to the underlying analysis tool
                          so it can apply framework-specific extraction rules.

        Returns:
            Absolute path to the persisted analysis results file, or ``None``
            if analysis failed.
        """
        pass
    
    @abstractmethod
    def load_analysis_results(self, results_path: str) -> Dict[str, Any]:
        """
        Load previously persisted analysis results.
        
        Args:
            results_path: Path to the analysis results file
            
        Returns:
            Dictionary containing the loaded analysis results
        """
        pass
    
    @abstractmethod
    def get_code_snippet(self, file_path: str, start_line: int, end_line: int) -> str:
        """
        Extract a specific code snippet from a file.
        
        Args:
            file_path: Path to the source file
            start_line: Starting line number (1-indexed)
            end_line: Ending line number (inclusive)
            
        Returns:
            String containing the requested code snippet
        """
        pass
    
    @abstractmethod
    def get_symbol_info(self, symbol_name: str, context_path: str, symbol_type:str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific symbol.
        
        Args:
            symbol_name: Name of the symbol (class, function, variable)
            context_path: Path of the file providing context for resolution
            
        Returns:
            Dictionary with symbol information or None if not found
        """
        pass
    
    @abstractmethod
    def get_symbol_reference(self, symbol_name: str, context_path: str, symbol_type:str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def get_file_classes(self, file_path: str):
        """
        Get all class names defined in a file from previously analyzed data.
        
        Args:
            file_path: Path to the file
            
        Returns:
            List of class names defined in the file
        """
        pass

    @abstractmethod
    def get_type_hierarchy(self, type_path: str, type_name: str) -> List[Dict[str, Any]]:
        """
        Get the parent/supertype hierarchy for a specific type.
        
        Args:
            type_path: File path where the type is defined
            type_name: Name of the type
            
        Returns:
            List of dictionaries containing parent/supertype information
        """
        pass
    
    @abstractmethod
    def get_external_code(self, symbol: str, context_path: str) -> Optional[str]:
        """
        Retrieve code for an external symbol not directly in the project.
        
        Args:
            symbol: Symbol name to retrieve
            context_path: Path providing context for symbol resolution
            
        Returns:
            Code snippet for the external symbol or None if not found
        """
        pass

    @abstractmethod
    def get_referenced_classes(self, code: str, context_path: str) -> List[Dict[str, Any]]:
        """
        Extract classes referenced in the given code.
        
        Args:
            code: Code snippet to analyze
            context_path: Path of the file containing the code
            
        Returns:
            List of dictionaries containing referenced class information
        """
        pass

    @abstractmethod 
    def get_inner_classes(self, class_name: str, class_path: str) -> Dict[str, Dict[str, Any]]:
        """
        Get inner classes defined within a class.
        
        Args:
            class_name: Name of the class
            class_path: Path of the file containing the class
            
        Returns:
            Dictionary mapping inner class names to their information
        """
        pass