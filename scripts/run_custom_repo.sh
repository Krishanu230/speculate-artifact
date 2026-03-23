#!/usr/bin/env bash
set -euo pipefail

ARTIFACT_ROOT="/artifact"
TOOL_DIR="$ARTIFACT_ROOT/tool/knowl-apidocs/genapidocs_v2"
OUTPUTS_DIR="$ARTIFACT_ROOT/outputs"

usage() {
  cat >&2 <<'EOF'
usage:
  run_custom_repo.sh \
    --repo-path <path> \
    --language <java|python> \
    --framework <jersey|spring|django|fastapi> \
    [--output-label <name>] \
    [--java-source-root <path>] \
    [--java-class-path <path>]... \
    [--spec-model <model>] \
    [--context-model <model>] \
    [-- <extra gen_apidocs2.py args>]

notes:
  - for Java, this wrapper is intended for Respector-style use with precompiled class directories
  - if one or more --java-class-path values are provided, the wrapper passes them via
    --multi-module and --java-module-paths to the tool
  - outputs are written under /artifact/outputs/<output-label>
EOF
  exit 2
}

REPO_PATH=""
LANGUAGE=""
FRAMEWORK=""
OUTPUT_LABEL=""
JAVA_SOURCE_ROOT=""
SPEC_MODEL=""
CONTEXT_MODEL=""
declare -a JAVA_CLASS_PATHS=()
declare -a TOOL_EXTRA_ARGS=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo-path)
      [ "$#" -ge 2 ] || usage
      REPO_PATH="$2"
      shift 2
      ;;
    --language)
      [ "$#" -ge 2 ] || usage
      LANGUAGE="$2"
      shift 2
      ;;
    --framework)
      [ "$#" -ge 2 ] || usage
      FRAMEWORK="$2"
      shift 2
      ;;
    --output-label)
      [ "$#" -ge 2 ] || usage
      OUTPUT_LABEL="$2"
      shift 2
      ;;
    --java-source-root)
      [ "$#" -ge 2 ] || usage
      JAVA_SOURCE_ROOT="$2"
      shift 2
      ;;
    --java-class-path)
      [ "$#" -ge 2 ] || usage
      JAVA_CLASS_PATHS+=("$2")
      shift 2
      ;;
    --spec-model)
      [ "$#" -ge 2 ] || usage
      SPEC_MODEL="$2"
      shift 2
      ;;
    --context-model)
      [ "$#" -ge 2 ] || usage
      CONTEXT_MODEL="$2"
      shift 2
      ;;
    --)
      shift
      TOOL_EXTRA_ARGS=("$@")
      break
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "[reviewer] Unknown argument: $1" >&2
      usage
      ;;
  esac
done

[ -n "$REPO_PATH" ] || usage
[ -n "$LANGUAGE" ] || usage
[ -n "$FRAMEWORK" ] || usage

if [ ! -d "$REPO_PATH" ]; then
  echo "[reviewer] Repository path does not exist: $REPO_PATH" >&2
  exit 1
fi

if [ -z "$OUTPUT_LABEL" ]; then
  OUTPUT_LABEL="$(basename "$REPO_PATH")"
fi

BENCHMARK_OUTPUT_DIR="$OUTPUTS_DIR/$OUTPUT_LABEL"
mkdir -p "$BENCHMARK_OUTPUT_DIR"

LOG_LINK="$REPO_PATH/.knowl_logs2"
if [ ! -L "$LOG_LINK" ]; then
  rm -rf "$LOG_LINK"
  ln -s "$BENCHMARK_OUTPUT_DIR" "$LOG_LINK"
fi

/artifact/scripts/validate_env.sh

cd "$TOOL_DIR"

extra_args=(
  "--language" "$LANGUAGE"
  "--framework" "$FRAMEWORK"
)

if [ -n "$SPEC_MODEL" ]; then
  extra_args+=("--spec-model" "$SPEC_MODEL")
fi

if [ -n "$CONTEXT_MODEL" ]; then
  extra_args+=("--context-model" "$CONTEXT_MODEL")
fi

if [ "$LANGUAGE" = "java" ] && [ "${#JAVA_CLASS_PATHS[@]}" -gt 0 ]; then
  if [ -z "$JAVA_SOURCE_ROOT" ]; then
    echo "[reviewer] --java-source-root is required when --java-class-path is used." >&2
    exit 1
  fi

  for class_path in "${JAVA_CLASS_PATHS[@]}"; do
    if [ ! -e "$class_path" ]; then
      echo "[reviewer] Java class path does not exist: $class_path" >&2
      exit 1
    fi
  done

  joined_paths=""
  for class_path in "${JAVA_CLASS_PATHS[@]}"; do
    if [ -z "$joined_paths" ]; then
      joined_paths="$class_path"
    else
      joined_paths="${joined_paths}:$class_path"
    fi
  done

  extra_args+=(
    "--multi-module"
    "--java-module-paths" "$joined_paths"
    "--java-source-root" "$JAVA_SOURCE_ROOT"
  )
fi

echo "[reviewer] Repo path: $REPO_PATH"
echo "[reviewer] Language: $LANGUAGE"
echo "[reviewer] Framework: $FRAMEWORK"
echo "[reviewer] Output label: $OUTPUT_LABEL"

if [ "${#JAVA_CLASS_PATHS[@]}" -gt 0 ]; then
  echo "[reviewer] Java class paths:"
  for class_path in "${JAVA_CLASS_PATHS[@]}"; do
    echo "[reviewer]   - $class_path"
  done
  echo "[reviewer] Java source root: $JAVA_SOURCE_ROOT"
fi

python3 gen_apidocs2.py "$REPO_PATH" "${extra_args[@]}" "${TOOL_EXTRA_ARGS[@]}"

echo "[reviewer] Run completed. Generated files are under $BENCHMARK_OUTPUT_DIR"
