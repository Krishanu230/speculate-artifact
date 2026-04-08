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
    Abstract base class for language-specific code analyzers.

    This class is split into two tiers:

    Compulsory (@abstractmethod)
    ----------------------------
    Five methods that every language implementation must provide.  These are
    the only ones called by language-agnostic code (the orchestration layer
    and the FrameworkAnalyzer base class).

    Optional (concrete defaults)
    ----------------------------
    Six methods that expose the richer analysis surface a paired framework
    analyzer typically relies on.  Safe empty defaults are provided so that a
    minimal implementation still runs end-to-end.  Override the ones your
    paired framework analyzer actually calls.

    Paired design
    -------------
    In practice each framework analyzer is tightly paired with a specific
    language implementation (DjangoAnalyzer ↔ PythonCodeAnalyzer,
    SpringBootFrameworkAnalyzer / JerseyFrameworkAnalyzer ↔ JavaCodeAnalyzer).
    The paired implementation may expose additional language-specific methods
    (e.g. ``get_class_ast``, ``get_method_code`` on PythonCodeAnalyzer;
    ``get_code_snippet_from_info`` on JavaCodeAnalyzer) that its framework
    analyzer calls directly.  Those methods are not declared here because they
    are not language-agnostic; they live on the concrete implementation.
    """

    # ------------------------------------------------------------------
    # Compulsory — MUST implement
    # ------------------------------------------------------------------

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
    def load_analysis_results(self, results_path: str) -> bool:
        """
        Load previously persisted analysis results from disk.

        Implementations must store the loaded data in ``self.analysis_results``
        so that other methods (``get_symbol_info``, ``get_file_classes``, etc.)
        can access it.  This method is typically called internally by
        ``analyze_project`` after the underlying analysis tool completes.

        Args:
            results_path: Path to the analysis results file produced by
                          ``analyze_project``.

        Returns:
            ``True`` if the results were loaded successfully, ``False`` otherwise.
        """
        pass

    @abstractmethod
    def get_code_snippet(self, file_path: str, start_line: int,
                         end_line: int) -> Optional[str]:
        """
        Extract a specific code snippet from a source file.

        Args:
            file_path:  Absolute path to the source file.
            start_line: Starting line number (1-indexed, inclusive).
            end_line:   Ending line number (inclusive).

        Returns:
            String containing the requested lines, or ``None`` if the file
            could not be read or the line range is invalid.
        """
        pass

    @abstractmethod
    def get_symbol_info(self, symbol_name: str, context_path: str,
                        symbol_type: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific symbol.

        Args:
            symbol_name:  Name of the symbol (class, function, or variable).
            context_path: Absolute path of the file providing import/scope
                          context for name resolution.
            symbol_type:  One of the SymbolType enum values.

        Returns:
            Dictionary with symbol information or ``None`` if not found.
            The exact keys vary by language; at minimum expect ``path``,
            ``startLine``, and ``endLine``.
        """
        pass

    @abstractmethod
    def get_symbol_reference(self, symbol_name: str, context_path: str,
                             symbol_type: str) -> Optional[Dict[str, Any]]:
        """
        Resolve a symbol name to its canonical definition location.

        Args:
            symbol_name:  Name of the symbol to resolve.
            context_path: Absolute path providing import/scope context.
            symbol_type:  One of the SymbolType enum values.

        Returns:
            Dict with at minimum ``name`` and ``path`` keys pointing to the
            canonical definition, or ``None`` if the symbol cannot be resolved.
        """
        pass

    # ------------------------------------------------------------------
    # Optional — safe defaults provided, override to improve quality
    # ------------------------------------------------------------------

    def get_file_classes(self, file_path: str) -> Dict[str, Any]:
        """
        Get all classes defined in a file from previously analysed data.

        Args:
            file_path: Absolute path to the source file.

        Returns:
            Mapping of class name → class detail dict (keys vary by language).
            The default implementation returns an empty dict.
        """
        return {}

    def get_analyzed_files(self) -> List[str]:
        """
        Return the list of all source files included in the analysis.

        Returns:
            List of absolute file paths analysed by ``analyze_project``.
            The default implementation returns an empty list.
        """
        return []

    def get_type_hierarchy(self, type_name: str, context_path: str) -> List[Dict[str, Any]]:
        """
        Get the parent/supertype hierarchy for a specific type.

        Args:
            type_name:    Fully-qualified or simple name of the type.
            context_path: File path where the type is defined, or the project
                          root when a fully-qualified name is supplied and the
                          exact file is unknown.

        Returns:
            List of dicts, each containing at minimum:
                name – name of the parent type
                path – absolute file path where the parent is defined (or None)
                code – source code of the parent class (or None)
            The default implementation returns an empty list.
        """
        return []

    def get_external_code(self, symbol: str, context_path: str) -> Optional[str]:
        """
        Retrieve source code for an external symbol not directly in the project
        (e.g. a third-party library class resolved via sys.path).

        Args:
            symbol:       Symbol name to retrieve.
            context_path: Absolute path providing context for resolution.

        Returns:
            Code snippet string, or ``None`` if not found or not supported.
            The default implementation returns ``None``.
        """
        return None

    def get_referenced_classes(self, code: str,
                               context_path: str) -> List[Dict[str, Any]]:
        """
        Extract classes referenced in the given code snippet.

        Args:
            code:         Source code snippet to analyse.
            context_path: Absolute path of the file containing the snippet.

        Returns:
            List of dicts describing each referenced class.
            The default implementation returns an empty list.
        """
        return []

    def get_inner_classes(self, class_name: str,
                          class_path: str) -> Dict[str, Dict[str, Any]]:
        """
        Get inner/nested classes defined within a class.

        Args:
            class_name: Name of the outer class.
            class_path: Absolute path of the file containing the class.

        Returns:
            Mapping of inner class name → class detail dict.
            The default implementation returns an empty dict.
        """
        return {}
