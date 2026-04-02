#!/bin/bash

# Script to collect all Java code from a repository into one file,
# including the directory structure at the top.

# --- Configuration ---
# Directories/patterns to exclude from BOTH tree and find
# Use pipe '|' to separate multiple patterns for tree's -I flag
# Use '-o -path ... -prune' for find's exclusions
TREE_EXCLUDE_PATTERN='target|build|bin|.git|.idea|.vscode|out|dist|node_modules|*.class|*.jar|*.log'
FIND_EXCLUDE_PATHS=( -path "*/target" -prune -o -path "*/build" -prune -o -path "*/bin" -prune -o -path "*/.git" -prune -o -path "*/.idea" -prune -o -path "*/.vscode" -prune -o -path "*/out" -prune -o -path "*/dist" -prune -o -path "*/node_modules" -prune )

# --- Functions ---
usage() {
  echo "Usage: $0 <repository_directory> <output_file>"
  echo "Example: $0 ./my-java-project combined_code.txt"
  exit 1
}

# --- Argument Handling ---
REPO_DIR="$1"
OUTPUT_FILE="$2"

if [ -z "$REPO_DIR" ] || [ -z "$OUTPUT_FILE" ]; then
  usage
fi

if [ ! -d "$REPO_DIR" ]; then
  echo "Error: Repository directory '$REPO_DIR' not found or is not a directory."
  exit 1
fi

# Canonicalize repo path (removes trailing slashes, resolves . ..)
REPO_DIR=$(cd "$REPO_DIR" && pwd)
if [ $? -ne 0 ]; then
    echo "Error: Could not access repository directory '$1'."
    exit 1
fi

# --- Prerequisites Check ---
if ! command -v tree &> /dev/null; then
  echo "Error: 'tree' command not found. Please install it."
  echo "  Ubuntu/Debian: sudo apt update && sudo apt install tree"
  echo "  macOS (Homebrew): brew install tree"
  echo "  Fedora: sudo dnf install tree"
  exit 1
fi

# --- Main Logic ---

echo "Starting code collection..."
echo "Repository: $REPO_DIR"
echo "Output File: $OUTPUT_FILE"

# 1. Generate Directory Structure
echo "Generating directory structure (excluding: $TREE_EXCLUDE_PATTERN)..."
{
  echo "======================================================================"
  echo " DIRECTORY STRUCTURE: $REPO_DIR"
  echo " (Excluding: $TREE_EXCLUDE_PATTERN)"
  echo "======================================================================"
  # Use tree with exclusions. -f prints full path, easier for context.
  # Or just use tree without -f for a cleaner visual tree. Adjust as needed.
  tree -a -I "$TREE_EXCLUDE_PATTERN" "$REPO_DIR" || echo "[tree command failed or directory empty]"
  echo -e "\n\n======================================================================"
  echo " JAVA SOURCE CODE CONTENT"
  echo "======================================================================"
} > "$OUTPUT_FILE" # Overwrite/create the output file

if [ $? -ne 0 ]; then
    echo "Error: Failed to write initial structure to '$OUTPUT_FILE'."
    exit 1
fi

# 2. Find and Concatenate Java Files
echo "Finding and appending Java files..."
# Use find with exclusions. -print0 and read -d are robust for weird filenames.
# The construct "${FIND_EXCLUDE_PATHS[@]}" expands the array correctly.
find "$REPO_DIR" "${FIND_EXCLUDE_PATHS[@]}" -o -type f -name "*.java" -print0 | while IFS= read -r -d $'\0' file; do
  # Get relative path for better readability in the output file
  relative_path="${file#$REPO_DIR/}"
  echo "  Appending: $relative_path"

  # Append separator and file content
  {
    echo -e "\n\n--//----------------------------------------------------------"
    echo "--// File: $relative_path"
    echo "--//----------------------------------------------------------"
    cat "$file"
  } >> "$OUTPUT_FILE" # Append to the output file

  if [ $? -ne 0 ]; then
      echo "Warning: Failed to append content from '$file'. Check permissions or file integrity."
      # Decide if you want to exit on error or just warn:
      # exit 1
  fi
done

echo "----------------------------------------"
echo "Code collection complete."
echo "Output written to: $OUTPUT_FILE"
exit 0