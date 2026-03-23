#!/bin/bash

# ==============================================================================
# run.sh (Standalone Java Analyzer Runner)
# Location: knowl-apidocs/genapidocs_v2/java_analyzer_impl/run.sh
#
# Usage (when run from the 'java_analyzer_impl' directory):
#   bash run.sh <path/to/target/fat-jar.jar> <path/to/target/project/src/main/java> <path/to/output/directory>
#
# Example (run from java_analyzer_impl directory):
#   bash run.sh ../../../feature-service/feature-services-code/target/features-service-1.0.0-SNAPSHOT.jar ../../../feature-service/feature-services-code/src/main/java ./analysis_output
#
# Example (run from project root 'knowl-apidocs'):
#   bash genapidocs_v2/java_analyzer_impl/run.sh feature-service/feature-services-code/target/features-service-1.0.0-SNAPSHOT.jar feature-service/feature-services-code/src/main/java genapidocs_v2/java_analyzer_impl/analysis_output
#
# Arguments:
#   $1: Path to the target project's fat JAR.
#   $2: Path to the target project's src/main/java directory.
#   $3: Directory where output JSON files should be created.
# ==============================================================================

# --- Configuration ---
# Find the analyzer JAR within the target directory of this project ('java_analyzer_impl/target')
# Using find is more robust than globbing if there are multiple versions
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)

# Find the analyzer JAR within the target directory RELATIVE to the script's location
ANALYZER_JAR=$(find "$SCRIPT_DIR/target" -name 'jersey-analyzer-*-jar-with-dependencies.jar' -print -quit)

echo "------------------------------------------"
echo "DEBUG: Checking Java version used by script:"
java -version
echo "------------------------------------------"
# --- End Debug ---


# --- Execute Java Analyzer ---
echo "Running Java Analyzer..."

# --- Argument Validation ---
if [ "$#" -ne 3 ]; then
    echo "Error: Incorrect number of arguments." >&2
    echo "Usage: $0 <target-jar-path> <target-src-dir> <output-dir>" >&2
    exit 1
fi

TARGET_JAR="$1"
TARGET_SRC="$2"
OUTPUT_DIR="$3"

# --- Prerequisite Checks ---
# Check if Analyzer JAR exists (relative to this script's location)
if [ ! -f "$ANALYZER_JAR" ]; then
    echo "Error: Analyzer JAR not found in target/ directory relative to this script." >&2
    echo "Please build the analyzer first (e.g., run 'mvn clean package assembly:single' in this directory)." >&2
    exit 1
fi
# Check if Target JAR exists (path provided as argument)
if [ ! -f "$TARGET_JAR" ]; then
    echo "Error: Target JAR not found at the specified path: $TARGET_JAR" >&2
    exit 1
fi
# Check if Target Source Directory exists (path provided as argument)
if [ ! -d "$TARGET_SRC" ]; then
    echo "Error: Target source directory not found at the specified path: $TARGET_SRC" >&2
    exit 1
fi

# Create the output directory if it doesn't exist
# Use the path provided as an argument
mkdir -p "$OUTPUT_DIR"
if [ ! -d "$OUTPUT_DIR" ]; then
     echo "Error: Failed to create output directory: $OUTPUT_DIR" >&2
     exit 1
fi


# --- Execute Java Analyzer ---
echo "Running Java Analyzer..."
echo "  Analyzer JAR: $ANALYZER_JAR"
echo "  Target JAR: $TARGET_JAR"
echo "  Target Source: $TARGET_SRC"
echo "  Output Dir: $OUTPUT_DIR"

# Resolve paths to absolute paths for robustness, especially for the Java process
# Check if realpath command exists, otherwise fallback to cd/pwd
if command -v realpath &> /dev/null; then
    TARGET_JAR_ABS=$(realpath "$TARGET_JAR")
    TARGET_SRC_ABS=$(realpath "$TARGET_SRC")
    OUTPUT_DIR_ABS=$(realpath "$OUTPUT_DIR")
    ANALYZER_JAR_ABS=$(realpath "$ANALYZER_JAR")
else
    # Fallback using cd and pwd (less reliable with complex paths/symlinks)
    TARGET_JAR_ABS=$(cd "$(dirname "$TARGET_JAR")" && pwd)/$(basename "$TARGET_JAR")
    TARGET_SRC_ABS=$(cd "$TARGET_SRC" && pwd)
    OUTPUT_DIR_ABS=$(cd "$OUTPUT_DIR" && pwd)
    ANALYZER_JAR_ABS=$(cd "$(dirname "$ANALYZER_JAR")" && pwd)/$(basename "$ANALYZER_JAR")
fi


# Execute the ListClasses main method using absolute paths
java -cp "$ANALYZER_JAR_ABS" com.analyzer.ListClasses \
    "$TARGET_JAR_ABS" \
    "$TARGET_SRC_ABS" \
    "$OUTPUT_DIR_ABS"

EXIT_CODE=$?
if [ $EXIT_CODE -ne 0 ]; then
    echo "Error: Java analysis process failed with exit code $EXIT_CODE." >&2
    exit $EXIT_CODE
fi

echo "Java analysis finished successfully. Output files should be in $OUTPUT_DIR_ABS"
exit 0