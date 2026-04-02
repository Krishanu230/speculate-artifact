#!/bin/bash

# ==============================================================================
#  A careful script to run long-running Python processes sequentially.
#  - It does not exit on error.
#  - It logs the output of each command to a separate file.
#  - It prints the exact command before running it.
#  - It creates a final summary report.
# ==============================================================================

# --- FIX: Set the correct environment ---

# 1. Set the full path to your project's working directory.
#    Run `pwd` in the directory where your command works manually.
PROJECT_DIR="/Users/abc/llm-openapi-paper/knowl-apidocs/genapidocs_v2" 

# 2. Set the full path to the Python executable from your virtual environment.
#    Run `which python` while 'popper' is active.
PYTHON_EXECUTABLE="/Users/abc/.virtualenvs/popper/bin/python" # <-- IMPORTANT: REPLACE THIS PATH

# The main python script to run
PYTHON_SCRIPT="$PYTHON_EXECUTABLE gen_apidocs2.py"


# --- Configuration ---

# Define common paths and arguments to avoid repetition
BASE_DIR="/Users/abc/llm-openapi-paper/Respector/dataset/gravitee-api-management"
API_PATH="$BASE_DIR/gravitee-apim-rest-api"
JAVA_SOURCE_ROOT="$BASE_DIR"
JAVA_MODULE_PATHS="'$API_PATH/gravitee-apim-rest-api-management-v4/gravitee-apim-rest-api-management-v4-rest/target/classes/:$API_PATH/../gravitee-apim-rest-api/gravitee-apim-rest-api-model/target/classes/:$BASE_DIR/gravitee-apim-definition/gravitee-apim-definition-model/target/classes/'"

BASE_CMD_ARGS=(
  "'$API_PATH'"
  --language java
  --framework jersey
  --multi-module
  --java-module-paths "$JAVA_MODULE_PATHS"
  --java-source-root "'$JAVA_SOURCE_ROOT'"
)

# --- Script Setup ---
LOG_DIR="run_logs"
mkdir -p "$LOG_DIR"
REPORT_FILE="run_report.txt"
TIMESTAMP=$(date +"%Y-%m-%d %T")
echo "Script execution started at: $TIMESTAMP" > "$REPORT_FILE"
echo "==================================================" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# --- Helper Function ---
execute_and_report() {
  local description="$1"
  local log_file="$2"
  shift 2
  local cmd=("$@")

  echo "--- [STARTING] $description ---"
  echo "    Executing: $PYTHON_SCRIPT ${cmd[@]}"
  
  # Using `eval` here is safe because we have constructed the command carefully with quotes.
  # It correctly handles the nested quotes in JAVA_MODULE_PATHS.
  eval "$PYTHON_SCRIPT ${cmd[@]}" > "$LOG_DIR/$log_file" 2>&1
  
  local exit_code=$?

  if [ $exit_code -eq 0 ]; then
    echo "--- [SUCCESS] $description completed successfully. ---"
    echo "[SUCCESS] - $description" >> "$REPORT_FILE"
  else
    echo "--- [FAILURE] $description failed with exit code $exit_code. ---"
    echo "    Check log file for details: $LOG_DIR/$log_file"
    echo "[FAILURE] - $description (Exit Code: $exit_code) - Log: $LOG_DIR/$log_file" >> "$REPORT_FILE"
  fi
  echo
}

# --- Main Execution ---

execute_and_report \
  "Run 1: Default models" \
  "run_1_default.log" \
  "${BASE_CMD_ARGS[@]}"

# ... (rest of the commands are the same)
execute_and_report \
  "Run 2: Default models (repeat)" \
  "run_2_default_repeat.log" \
  "${BASE_CMD_ARGS[@]}"

execute_and_report \
  "Run 3: Models gpt_4_1" \
  "run_3_gpt_4_1.log" \
  "${BASE_CMD_ARGS[@]}" --spec-model gpt_4_1 --context-model gpt_4_1

execute_and_report \
  "Run 4: Models gpt_o1" \
  "run_4_gpt_o1.log" \
  "${BASE_CMD_ARGS[@]}" --spec-model gpt_o1 --context-model gpt_o1

execute_and_report \
  "Run 5: Models deepseek_r1" \
  "run_5_deepseek_r1.log" \
  "${BASE_CMD_ARGS[@]}" --spec-model deepseek_r1 --context-model deepseek_r1

# --- Final Summary ---
echo ""
echo "=================================================="
echo "All processes have finished."
echo "Final summary has been saved to: $REPORT_FILE"
echo "=================================================="
cat "$REPORT_FILE"
echo "=================================================="