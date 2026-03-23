import json
import os
from pathlib import Path
import subprocess
import logging
from typing import Dict, List, Optional, Any, Tuple
import shutil
import glob

# Import the interface and potentially common types
from common.interfaces.code_analyzer import CodeAnalyzer, SymbolType

# Get loggers (assuming logging_config is accessible)
from common.logging_config import SetupLogging
console_logger = SetupLogging.get_console_logger()
debug_logger = SetupLogging.get_debug_logger()

class JavaCodeAnalyzer(CodeAnalyzer):
    """
    Java implementation of the CodeAnalyzer interface.
    Runs an external Java/Soot tool and queries its JSON output.
    """

    
    def __init__(self, logger=None, multi_module: bool = False, java_module_paths: Optional[str] = None, java_source_root: Optional[str] = None):
        self.logger = logger or debug_logger
        self.multi_module = multi_module
        self.provided_module_paths = java_module_paths
        self.provided_source_root = java_source_root
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.java_analyzer_base_path = os.path.abspath(os.path.join(current_dir, "java_analyzer_impl"))
        self.pom_file_path = os.path.join(self.java_analyzer_base_path, "pom.xml")
        self.analyzer_jar_path_pattern = os.path.join(
            self.java_analyzer_base_path, "target", "jersey-analyzer-*-jar-with-dependencies.jar"
        )
        if not os.path.isdir(self.java_analyzer_base_path):
            raise FileNotFoundError(f"Embedded Java analyzer project path not found: {self.java_analyzer_base_path}")
        if not os.path.isfile(self.pom_file_path):
            raise FileNotFoundError(f"Java analyzer pom.xml not found: {self.pom_file_path}")
        self.analysis_results: Optional[Dict[str, Any]] = None
        self.respector_results: Optional[Dict[str, Any]] = None
        self.analysis_output_dir: Optional[str] = None
        self._class_lookup: Dict[str, Dict] = {}
        self._file_to_classes: Dict[str, List[str]] = {}
        self.build_system: Optional[str] = None
        self.analyzer_java_cmd = os.environ.get("JAVA_ANALYZER_JAVA", "java")
        log_mode = "Multi-Module" if self.multi_module else "Single-Module"
        self.logger.info(f"JavaCodeAnalyzer initialized in {log_mode} mode. Expects Java project at: {self.java_analyzer_base_path}")

    def _detect_build_system(self, project_path: str) -> str:
        if os.path.isfile(os.path.join(project_path, 'build.gradle')) or os.path.isfile(os.path.join(project_path, 'build.gradle.kts')):
            self.logger.info("Detected Gradle build system.")
            return "gradle"
        elif os.path.isfile(os.path.join(project_path, 'pom.xml')):
            self.logger.info("Detected Maven build system.")
            return "maven"
        else:
            self.logger.warning("Could not detect a standard build system (pom.xml or build.gradle). Will attempt Maven-style analysis.")
            return "maven" # Default to original behavior if nothing is found
    
    def _discover_modules(self, project_path: str) -> List[str]:
        self.logger.info(f"Discovering modules for a '{self.build_system}' project...")
        module_paths = []

        if self.build_system == "maven":
            module_marker_file = 'pom.xml'
        elif self.build_system == "gradle":
            module_marker_file = 'build.gradle' # or build.gradle.kts
        else: # Should not happen
            return []

        for root, _, files in os.walk(project_path):
            if module_marker_file in files or ('build.gradle.kts' in files and self.build_system == "gradle"):
                # Avoid crawling into build output directories
                path_parts = root.split(os.sep)
                if any(part in ['target', 'build', 'node_modules', '.git'] for part in path_parts):
                    continue
                self.logger.debug(f"Found module at: {root}")
                module_paths.append(root)
        
        return module_paths
    
    def _get_class_paths_for_modules(self, module_paths: List[str]) -> List[str]:
        discovered_class_paths = []

        # --- Maven Strategy ---
        if self.build_system == "maven":
            classes_dir_name = os.path.join("target", "classes")
        # --- Gradle Strategy ---
        elif self.build_system == "gradle":
            classes_dir_name = os.path.join("build", "classes", "java", "main")
        else:
            return []

        for module_path in module_paths:
            classes_dir = os.path.join(module_path, classes_dir_name)
            if os.path.isdir(classes_dir):
                discovered_class_paths.append(classes_dir)
                self.logger.info(f"  + Found classes path for analysis: {classes_dir}")
        
        return discovered_class_paths
    
    def _build_java_analyzer(self) -> bool:
        """Helper to build the Java analyzer using Maven."""
        self.logger.info("Building Java Analyzer implementation...")
        # Construct the Maven command
        command = [
            "mvn",                # Assumes mvn is in the system PATH
            "clean",
            "package",
            "assembly:single",    # To build the fat JAR
            "-f", self.pom_file_path # Specify the POM file location
            # Add -q for quieter build, remove for more verbose output if needed
            # "-q"
        ]
        success = self._run_java_analyzer_process(command, "Build")
        if not success:
            self.logger.error("Java Analyzer build failed.")
        return success

    def _find_analyzer_jar(self) -> Optional[str]:
        jars = sorted(glob.glob(self.analyzer_jar_path_pattern))
        if not jars:
            self.logger.error(f"Analyzer JAR not found matching pattern: {self.analyzer_jar_path_pattern}")
            return None
        non_empty_jars = [jar for jar in jars if os.path.getsize(jar) > 0]
        if not non_empty_jars:
            self.logger.error("Analyzer JAR candidates were found, but all are empty files.")
            return None
        if len(non_empty_jars) > 1:
                self.logger.warning(f"Multiple analyzer JARs found, using the first non-empty JAR: {non_empty_jars[0]}")
        return non_empty_jars[0]

    def _get_or_build_analyzer_jar(self, current_output_dir: str) -> Optional[str]:
        """
        Finds a usable analyzer JAR, prioritizing a local build, then previously
        saved JARs, and finally building from source as a last resort.
        Returns the path to the JAR in the local 'target' directory.
        """
        # 1. Check local 'target' directory first. This is fastest.
        self.logger.info("Looking for pre-compiled Java analyzer JAR...")
        local_jar = self._find_analyzer_jar()
        if local_jar:
            self.logger.info(f"Found analyzer JAR in local target directory: {local_jar}")
            return local_jar

        # 2. Check past run directories for a saved JAR.
        self.logger.info("Local JAR not found. Searching in previous analysis runs...")
        try:
            logs_parent_dir = str(Path(current_output_dir).parent)
            past_runs = sorted(
                [d for d in glob.glob(os.path.join(logs_parent_dir, '*')) if os.path.isdir(d)],
                reverse=True
            )
            for past_run_dir in past_runs:
                found_jars = glob.glob(os.path.join(past_run_dir, "analyzer_build", "jersey-analyzer-*-jar-with-dependencies.jar"))
                if found_jars:
                    reused_jar_path = found_jars[0]
                    self.logger.info(f"Found reusable analyzer JAR in '{os.path.basename(past_run_dir)}'.")
                    
                    target_dir = os.path.join(self.java_analyzer_base_path, "target")
                    os.makedirs(target_dir, exist_ok=True)
                    shutil.copy(reused_jar_path, target_dir)
                    self.logger.info(f"Copied reusable JAR to local target directory for use.")
                    
                    return self._find_analyzer_jar()
        except Exception as e:
            self.logger.warning(f"Error while searching for pre-built JARs: {e}")

        # 3. If still no JAR, then build from source as a last resort.
        if not self._build_java_analyzer():
            self.logger.error("Failed to build analyzer from source.")
            return None
        
        return self._find_analyzer_jar()
    
    def _run_java_analyzer_process(self, command: List[str], operation_name: str) -> bool:
        self.logger.info(f"Executing Java Analyzer {operation_name}: {' '.join(command)}")
        try:
            process = subprocess.run(
                command,
                cwd=self.java_analyzer_base_path,
                capture_output=True,
                text=True,
                check=False,
                encoding='utf-8', 
            )
            if process.stdout:
                self.logger.debug(f"Java Analyzer {operation_name} STDOUT:\n{process.stdout}")
            if process.stderr:
                log_level = logging.ERROR if process.returncode != 0 else logging.WARNING
                self.logger.log(log_level, f"Java Analyzer {operation_name} STDERR:\n{process.stderr}")
            if process.returncode != 0:
                self.logger.error(f"Java Analyzer {operation_name} failed with exit code {process.returncode}.")
                return False
            else:
                self.logger.info(f"Java Analyzer {operation_name} completed successfully.")
                return True
        except FileNotFoundError:
            self.logger.error(f"Error: '{command[0]}' command not found. Cannot execute.")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error running Java Analyzer {operation_name}: {e}", exc_info=True)
            return False
    
    def _find_and_copy_previous_analysis(self, logs_parent_dir: str, current_output_dir: str) -> Optional[str]:
        """
        Looks for the latest successful analysis in sibling directories and copies it
        to the current output directory to avoid re-running the analysis.
        """
        if not os.path.isdir(logs_parent_dir):
            return None

        self.logger.info("Searching for previous analysis results to reuse...")
        try:
            past_runs = sorted(
                [d for d in glob.glob(os.path.join(logs_parent_dir, '*')) if os.path.isdir(d) and os.path.abspath(d) != os.path.abspath(current_output_dir)],
                reverse=True
            )
        except Exception:
            return None

        for past_run_dir in past_runs:
            main_result_file = os.path.join(past_run_dir, "soot-analysis.json")
            if os.path.isfile(main_result_file):
                self.logger.info(f"Found reusable analysis results in: {os.path.basename(past_run_dir)}")
                os.makedirs(current_output_dir, exist_ok=True)
                
                dest_main_file = os.path.join(current_output_dir, "soot-analysis.json")
                shutil.copy(main_result_file, dest_main_file)
                self.logger.info(f"Copied {os.path.basename(main_result_file)} to current output directory.")

                respector_result_file = os.path.join(past_run_dir, "soot-respector.json")
                if os.path.isfile(respector_result_file):
                    dest_respector_file = os.path.join(current_output_dir, "soot-respector.json")
                    shutil.copy(respector_result_file, dest_respector_file)
                
                return dest_main_file

        self.logger.info("No previous analysis results found to reuse.")
        return None
    
    def _analyze_single_project_path(self, project_path: str, output_dir: str,override_soot_path: Optional[str] = None, 
                                     override_source_path: Optional[str] = None) -> Optional[str]:
        self.analysis_output_dir = os.path.abspath(output_dir)
        abs_project_path = os.path.abspath(project_path)
        target_path_for_soot=None
        if override_soot_path:
            target_path_for_soot = override_soot_path
            self.logger.info(f"Using overridden Soot path: {target_path_for_soot}")
        else:
            # Original single-module path finding logic
            target_classes_path = os.path.join(abs_project_path, "target", "classes")
            if os.path.isdir(target_classes_path):
                self.logger.info(f"Found 'target/classes' directory, which is the preferred analysis path.")
                target_path_for_soot = target_classes_path
            
            # 2. FALLBACK to finding a JAR if 'target/classes' doesn't exist.
            if not target_path_for_soot:
                self.logger.warning("'target/classes' not found. Falling back to JAR file search (might be less effective).")
                search_dirs = [os.path.join(abs_project_path, "target"), os.path.join(abs_project_path, "build", "libs")]
                for build_dir in search_dirs:
                    if os.path.isdir(build_dir):
                        # Find the largest JAR, assuming it's the fat/uber JAR
                        jars_in_dir = [os.path.join(build_dir, f) for f in os.listdir(build_dir) if f.endswith(".jar")]
                        if jars_in_dir:
                            largest_jar = max(jars_in_dir, key=os.path.getsize)
                            target_path_for_soot = largest_jar
                            self.logger.info(f"Found fallback JAR: {target_path_for_soot}")
                            break
            
            # 3. FINAL FALLBACK if nothing else is found.
            if not target_path_for_soot:
                self.logger.error(f"Could not find a suitable 'target/classes' directory or a JAR file in {abs_project_path}.")
                return None

        if override_source_path:
            target_src_path = override_source_path
            self.logger.info(f"Using overridden source path: {target_src_path}")
        else:
            # Original single-module source finding logic
            target_src_path = os.path.join(abs_project_path, "src", "main", "java")
            if not os.path.isdir(target_src_path):
                 if os.path.isdir(os.path.join(abs_project_path, "src")):
                     target_src_path = os.path.join(abs_project_path, "src")
                 else:
                     self.logger.error(f"Could not find standard Java source directory in {abs_project_path}.")
                     return None

        self.logger.info(f"Final Soot Path: {target_path_for_soot}")
        self.logger.info(f"Final Source Path: {target_src_path}")

        # --- The rest of the method is completely unchanged ---
        if not self._build_java_analyzer(): return None
        analyzer_jar = self._find_analyzer_jar()
        if not analyzer_jar: return None

        os.makedirs(self.analysis_output_dir, exist_ok=True)
        java_command = [
            "java", "-cp", analyzer_jar, "com.analyzer.ListClasses",
            target_path_for_soot, target_src_path, self.analysis_output_dir
        ]
        
        self.logger.info("-----------------------------------------------------------------")
        self.logger.info("--- VERIFYING ARGUMENTS PASSED TO JAVA ANALYZER ---")
        self.logger.info(f"  Arg 0 (for Soot): {java_command[4]}")
        self.logger.info(f"  Arg 1 (for JavaParser source root): {java_command[5]}")
        self.logger.info(f"  Arg 2 (Output Dir): {java_command[6]}")
        self.logger.info("-----------------------------------------------------------------")
        if not self._run_java_analyzer_process(java_command, "Analysis"):
            self.logger.error("Java code analysis script failed.")
            return None

        final_main_output_path = os.path.join(self.analysis_output_dir, "soot-analysis.json")
        if os.path.isfile(final_main_output_path):
            self.logger.info(f"Main analysis output generated at: {final_main_output_path}")
            if self.load_analysis_results(final_main_output_path):
                 return final_main_output_path
            else:
                 self.logger.error("Failed to load the generated analysis results.")
                 return None
        else:
            self.logger.error(f"Expected main output file not found after analysis: {final_main_output_path}")
            return None

    def analyze_project(self, project_path: str, output_dir: str, framework: str) -> Optional[str]:
        try:
            logs_parent_dir = str(Path(output_dir).parent)
            reused_results_path = self._find_and_copy_previous_analysis(logs_parent_dir, output_dir)
            if reused_results_path and self.load_analysis_results(reused_results_path):
                self.logger.info("Successfully loaded reused analysis results. Skipping Java analysis.")
                return reused_results_path
        except Exception as e:
            self.logger.warning(f"Error checking for previous analysis, proceeding with new run: {e}", exc_info=True)

        abs_project_path = os.path.abspath(project_path)
        self.analysis_output_dir = os.path.abspath(output_dir)
        
        # 1. DETECT build system
        self.build_system = self._detect_build_system(abs_project_path)
        
        soot_process_path = ""
        java_parser_source_root = ""

        if self.multi_module:
            if self.provided_module_paths:
                self.logger.info("Using manually provided paths for multi-module analysis.")
                soot_process_path = self.provided_module_paths
                # Use the provided source root if it exists, otherwise default to the project root.
                if self.provided_source_root:
                    java_parser_source_root = self.provided_source_root
                    self.logger.info(f"  - Using explicitly provided source root: {java_parser_source_root}")
                else:
                    java_parser_source_root = abs_project_path # Sensible default
                    self.logger.info(f"  - Using project root as default source root: {java_parser_source_root}")

            else:
                # Original automatic discovery logic for multi-module
                module_paths = self._discover_modules(abs_project_path)
                if not module_paths:
                    self.logger.error("Multi-module mode enabled, but no modules were found.")
                    return None
                
                class_paths = self._get_class_paths_for_modules(module_paths)
                if not class_paths:
                    self.logger.error(f"Could not find any compiled class directories. Please ensure the project is built (e.g., 'mvn install' or 'gradle build').")
                    return None
                
                soot_process_path = os.pathsep.join(class_paths)
                java_parser_source_root = abs_project_path # Safest to use the root for sources
        else:
            # 2. STRATEGIZE for single-module
            if self.build_system == "maven":
                soot_process_path = os.path.join(abs_project_path, "target", "classes")
            elif self.build_system == "gradle":
                soot_process_path = os.path.join(abs_project_path, "build", "classes", "java", "main")
            
            possible_source_roots = [
                os.path.join(abs_project_path, "src", "main", "java"),
                os.path.join(abs_project_path, "src", "main", "lombok"),
                os.path.join(abs_project_path, "src", "main", "kotlin"),
                os.path.join(abs_project_path, "src") # A general fallback
            ]
            
            found_source_root = None
            for root in possible_source_roots:
                if os.path.isdir(root):
                    self.logger.info(f"Found valid source root for JavaParser: {root}")
                    found_source_root = root
                    break
            
            if not found_source_root:
                self.logger.error(f"Could not find a standard source directory (e.g., src/main/java) in {abs_project_path}.")
                return None
            
            java_parser_source_root = found_source_root
            
            if not os.path.isdir(soot_process_path):
                self.logger.error(f"Could not find compiled classes at '{soot_process_path}'. Please ensure the project is built.")
                return None

        # 3. EXECUTE the analysis with the correctly determined paths
        return self._run_java_analysis_jar(soot_process_path, java_parser_source_root, framework)

    def _run_java_analysis_jar(self, target_path_for_soot: str, target_src_path: str, framework:str) -> Optional[str]:
        """Runs the external analyzer JAR with the provided paths."""
        analyzer_jar = self._get_or_build_analyzer_jar(self.analysis_output_dir)
        if not analyzer_jar: return None

        os.makedirs(self.analysis_output_dir, exist_ok=True)
        java_command = [
            self.analyzer_java_cmd, "-cp", analyzer_jar, "com.analyzer.ListClasses",
            target_path_for_soot, target_src_path, self.analysis_output_dir, framework
        ]
        
        self.logger.info("-----------------------------------------------------------------")
        self.logger.info("--- VERIFYING ARGUMENTS PASSED TO JAVA ANALYZER ---")
        self.logger.info(f"  Soot Classpath: {java_command[4]}")
        self.logger.info(f"  JavaParser Source Root: {java_command[5]}")
        self.logger.info(f"  Output Directory: {java_command[6]}")
        self.logger.info("-----------------------------------------------------------------")

        if not self._run_java_analyzer_process(java_command, "Analysis"):
            self.logger.error("Java code analysis script failed.")
            return None

        final_main_output_path = os.path.join(self.analysis_output_dir, "soot-analysis.json")
        if os.path.isfile(final_main_output_path):
            self.logger.info(f"Main analysis output generated at: {final_main_output_path}")
            if self.load_analysis_results(final_main_output_path):
                 return final_main_output_path
            else:
                 self.logger.error("Failed to load the generated analysis results.")
                 return None
        else:
            self.logger.error(f"Expected main output file not found after analysis: {final_main_output_path}")
            return None
   
    def load_analysis_results(self, results_path: str) -> bool:
            """Load persisted Java analysis results (soot-analysis.json)."""
            self.logger.info(f"Loading Java analysis results from: {results_path}")
            try:
                with open(results_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                # Use the correct top-level key based on your merged output
                class_data_list = data.get("classIdentifiers") # <--- Use the key from merged JSON
                if class_data_list is None:
                     # Maybe try the direct key if merge wasn't done? (Less ideal)
                     class_data_list = data.get("classes")

                if class_data_list is None or not isinstance(class_data_list, list):
                    self.logger.error(f"Invalid format: Expected 'classIdentifiers' or 'classes' key with a list in {results_path}")
                    return False

                self.analysis_results = data # Store the whole loaded structure
                self.analysis_output_dir = os.path.dirname(results_path)

                # --- Build internal lookups ---
                self._class_lookup = {}
                self._file_to_classes = {}
                for class_data in class_data_list: # Iterate through the list
                    fqn = class_data.get("className")
                    if fqn == "org.javiermf.features.models.Product":
                        self.logger.info(f"JavaCA.load_analysis_results: Product class_data from JSON: {class_data.get('fields')}")
                    # Use the correct key for file path
                    file_path = class_data.get("classFileName") or class_data.get("filePath") # <--- Check multiple keys
                    if fqn:
                        # Ensure file_path is absolute for consistency
                        abs_file_path = os.path.abspath(file_path) if file_path else None
                        class_data['filePath'] = abs_file_path # Standardize key if needed
                        self._class_lookup[fqn] = class_data
                        if abs_file_path:
                            if abs_file_path not in self._file_to_classes:
                                self._file_to_classes[abs_file_path] = []
                            self._file_to_classes[abs_file_path].append(fqn)
                if "org.javiermf.features.models.Product" in self._class_lookup:
                    self.logger.info(f"JavaCA.load_analysis_results: Product fields in _class_lookup: {self._class_lookup['org.javiermf.features.models.Product'].get('fields')}")
                self.logger.info(f"Loaded {len(self._class_lookup)} classes from analysis results.")

                # --- Load Respector Results (Optional) ---
                respector_path = os.path.join(self.analysis_output_dir, "soot-respector.json")
                if os.path.exists(respector_path):
                    try:
                        with open(respector_path, 'r', encoding='utf-8') as f:
                            self.respector_results = json.load(f)
                        self.logger.info("Loaded respector results.")
                    except Exception as e:
                        self.logger.warning(f"Failed to load respector results from {respector_path}: {e}")
                        self.respector_results = None
                else:
                    self.logger.debug("Respector results file not found (optional).")
                    self.respector_results = None

                return True
            except FileNotFoundError:
                self.logger.error(f"Analysis results file not found: {results_path}")
                return False
            except json.JSONDecodeError as e:
                self.logger.error(f"Error decoding JSON from {results_path}: {e}")
                return False
            except Exception as e:
                self.logger.error(f"Unexpected error loading analysis results: {e}", exc_info=True)
                return False

    def get_code_snippet(self, file_path: str, start_line: int, end_line: int) -> Optional[str]:
        """Extract a specific code snippet from a Java file."""
        # Basic Python file reading
        if not file_path or not os.path.isfile(file_path):
            self.logger.warning(f"get_code_snippet: File path not found or invalid: {file_path}")
            return None
        if not start_line or not end_line or start_line <= 0 or end_line < start_line:
            self.logger.warning(f"get_code_snippet: Invalid line numbers ({start_line}-{end_line}) for file {file_path}")
            return None

        snippet_lines = []
        try:
            with open(file_path, "r", encoding='utf-8') as file: # Specify encoding
                for current_line, line in enumerate(file, start=1):
                    if start_line <= current_line <= end_line:
                        snippet_lines.append(line)
                    elif current_line > end_line:
                        break
            return "".join(snippet_lines) if snippet_lines else None
        except FileNotFoundError:
             self.logger.error(f"get_code_snippet: File not found during read: {file_path}")
             return None
        except Exception as e:
            self.logger.error(f"Error reading code snippet from {file_path}: {e}", exc_info=True)
            return None

    def get_symbol_info(self, symbol_name: str, context_path: str, symbol_type: SymbolType) -> Optional[Dict[str, Any]]:
            """Get detailed information about a Java class or method."""
            if not self.analysis_results:
                self.logger.warning("Analysis results not loaded, cannot get symbol info.")
                return None

            if symbol_type == SymbolType.CLASS:
                if symbol_name in self._class_lookup:
                    return self._class_lookup[symbol_name]
                else:
                    # Try finding based on simple name if context_path is provided
                    abs_context_path = os.path.abspath(context_path)
                    possible_fqns = [fqn for fqn in self._class_lookup
                                     if fqn.endswith("." + symbol_name) or fqn == symbol_name]
                    # TODO: Need import resolution here for accuracy
                    if len(possible_fqns) == 1:
                        self.logger.debug(f"Resolved simple class name '{symbol_name}' to '{possible_fqns[0]}'")
                        return self._class_lookup[possible_fqns[0]]
                    elif len(possible_fqns) > 1:
                         self.logger.warning(f"Ambiguous simple class name '{symbol_name}' in context '{context_path}'. Found: {possible_fqns}")
                    else:
                         self.logger.debug(f"Class symbol info not found: {symbol_name}")
                    return None

            elif symbol_type == SymbolType.FUNCTION: # Java methods
                # Expect symbol_name like "com.example.MyClass.myMethod"
                parts = symbol_name.rsplit('.', 1)
                if len(parts) == 2:
                    class_fqn, method_simple_name = parts
                    if class_fqn in self._class_lookup:
                        class_data = self._class_lookup[class_fqn]
                        # Use 'functions' key based on soot-analysis.json structure
                        for method_data in class_data.get("functions", []):
                            if method_data.get("methodName") == method_simple_name:
                                # Add file path for consistency
                                method_data["filePath"] = class_data.get("classFileName") or class_data.get("filePath")
                                return method_data
                self.logger.debug(f"Method symbol info not found (requires FQN.methodName format): {symbol_name}")
                return None

            self.logger.warning(f"Symbol type {symbol_type} lookup not fully implemented or symbol not found: {symbol_name}")
            return None

    def get_symbol_reference(self, symbol_name: str, context_path: str, symbol_type: SymbolType) -> Optional[Dict[str, Any]]:
        # For Java, this is often the same as get_symbol_info if FQN is known
        # or requires complex resolution based on imports in context_path.
        # Let's return a simplified reference for now.
        symbol_info = self.get_symbol_info(symbol_name, context_path, symbol_type)
        if symbol_info:
            ref = {
                "canonicalName": symbol_info.get("className") or symbol_info.get("methodName"),
                "definitionPath": symbol_info.get("classFileName") or symbol_info.get("filePath"), # Adjust keys
                "symbolType": symbol_type.name # Return string name
            }
            # Check if essential parts are present
            if ref["canonicalName"] and ref["definitionPath"]:
                 return ref
        return None

    def get_file_classes(self, file_path: str) -> Dict[str, Any]:
        """Get info for all classes defined in a file."""
        if not self.analysis_results: return {}
        abs_path = os.path.abspath(file_path)
        class_fqns = self._file_to_classes.get(abs_path, [])
        class_data_map = {}
        for fqn in class_fqns:
            if fqn in self._class_lookup:
                 simple_name = fqn.split('.')[-1]
                 # Use simple name as key for consistency with Python version?
                 class_data_map[simple_name] = self._class_lookup[fqn]
        return class_data_map

    def get_analyzed_files(self) -> List[str]:
         """Gets list of analyzed files."""
         if not self.analysis_results: return []
         files = set()
         for class_data in self.analysis_results.get("classIdentifiers", []): # Use correct key
             # Use correct key for file path
             file_path = class_data.get("classFileName") or class_data.get("filePath")
             if file_path:
                  files.add(os.path.abspath(file_path)) # Ensure absolute
         return list(files)


    def get_type_hierarchy(self, type_name: str, context_path: str) -> List[Dict[str, Any]]:
        """Gets the inheritance tree (parents) for a Java class."""
        if not self.analysis_results: return []

        inheritance_tree = []
        processed_fqns = set()

        # Use FQN for tracking
        class_info = self.get_symbol_info(type_name, context_path, SymbolType.CLASS)
        if not class_info: return []
        start_fqn = class_info.get("className")
        if not start_fqn: return []

        queue = [(start_fqn)] # Queue of FQNs to process
        processed_fqns.add(start_fqn)

        while queue:
            current_fqn = queue.pop(0)
            current_info = self._class_lookup.get(current_fqn)

            if not current_info: continue

            parents = current_info.get("parentClasses", [])
            for parent_fqn in parents:
                if parent_fqn not in processed_fqns:
                    processed_fqns.add(parent_fqn)
                    parent_info = self._class_lookup.get(parent_fqn)
                    parent_entry = {
                        "name": parent_fqn, # Store FQN
                        "path": parent_info.get("classFileName") if parent_info else None,
                        "code": None # Placeholder, code fetching might be expensive here
                    }
                    # Fetch code snippet if path is known
                    if parent_entry["path"] and parent_info:
                        start = parent_info.get("startLine")
                        end = parent_info.get("endLine")
                        if start and end:
                             parent_entry["code"] = self.get_code_snippet(parent_entry["path"], start, end)

                    inheritance_tree.append(parent_entry)
                    queue.append(parent_fqn) # Add parent to queue for its parents

        return inheritance_tree

    # --- Methods likely NOT directly applicable/needed or need different implementation for Java ---

    def get_external_code(self, symbol: str, context_path: str) -> Optional[str]:
        """Retrieving external Java code (from dependencies) is complex and not implemented."""
        self.logger.warning("get_external_code is not implemented for JavaCodeAnalyzer.")
        return None

    def extract_class_names(self, code: str) -> List[str]:
        """Parsing raw Java snippets with Python AST is not feasible."""
        self.logger.warning("extract_class_names called on JavaCodeAnalyzer - relies on pre-analyzed data.")
        # Could potentially use regex as a *very* crude fallback, but unreliable.
        # Better to rely on get_referenced_classes if needed.
        return []

    def extract_property_value(self, file_path: str, class_name: str, property_name: str) -> Optional[str]:
        """Extracting specific Java field initializers requires parsing."""
        # This would need a Java parser (like JavaParser) integrated here or assume
        # the value is simple and present in the field info from Soot (unlikely).
        self.logger.warning("extract_property_value not implemented for Java - requires Java parsing.")
        return None

    def get_referenced_classes(self, code: str, context_path: str) -> List[Dict[str, Any]]:
         """Gets classes referenced within a specific Java method or class body."""
         # This should query the pre-analyzed `referencedClasses` list from `soot-analysis.json`.
         # The 'code' snippet isn't actually needed if analysis is pre-computed.
         # Find the relevant method/class in self.analysis_results based on context_path
         # and potentially a method/class name extracted from the code context.

         self.logger.warning("get_referenced_classes(code, ...) should preferably use pre-analyzed data. Searching based on context_path...")
         # Crude implementation: find symbol info containing the line numbers of the snippet?
         # Better: FrameworkAnalyzer should call get_symbol_info for the relevant scope
         #         and then access its 'identifiers'.'referencedClasses' field.
         # Return empty for now as direct snippet parsing is not the right approach here.
         return []


    def get_inner_classes(self, class_name: str, class_path: str) -> Dict[str, Dict[str, Any]]:
        """Gets inner classes for a Java class."""
        # The soot-analysis.json structure needs to be checked if it captures inner classes.
        # Assuming it might be nested within ClassInfo or a separate list.
        class_info = self.get_symbol_info(class_name, class_path, SymbolType.CLASS)
        if class_info and "innerClasses" in class_info: # Adjust key if needed
            # Process the inner class info from the JSON
            # This might require constructing the full inner class structure
            # based on the data provided by the Java analysis tool.
            self.logger.warning("get_inner_classes needs implementation based on actual JSON output structure.")
            return class_info["innerClasses"] # Placeholder
        return {}
    
    def get_code_snippet_from_info(self, symbol_info: Dict[str, Any]) -> Optional[str]:
        """
        A convenience wrapper to get a code snippet directly from a symbol_info dictionary.
        """
        if not symbol_info:
            return None
        path = symbol_info.get("classFileName") or symbol_info.get("filePath")
        start = symbol_info.get("startLine")
        end = symbol_info.get("endLine")
        if all([path, start, end]):
            return self.get_code_snippet(path, start, end)
        self.logger.warning(f"Could not get code snippet from info dict, missing location: {symbol_info.get('className')}")
        return None
