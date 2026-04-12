#!/usr/bin/env bash
set -euo pipefail

ARTIFACT_ROOT="/artifact"
MANIFEST_PATH="$ARTIFACT_ROOT/benchmarks/java/repos.json"
TOOL_DIR="$ARTIFACT_ROOT/tool/speculate-apidocs/genapidocs_v2"

MODE="analyze"

case "${1:-}" in
  --full)
    MODE="full"
    shift
    ;;
  --compile-only)
    MODE="compile"
    shift
    ;;
  --analyze-only)
    MODE="analyze"
    shift
    ;;
esac

if [ "$#" -lt 1 ]; then
  echo "usage: $0 [--full|--compile-only|--analyze-only] <repo-id> [tool-args...]" >&2
  exit 2
fi

REPO_ID="$1"
shift
TOOL_EXTRA_ARGS=("$@")

eval "$(
  python3 - "$MANIFEST_PATH" "$REPO_ID" <<'PY'
import json
import shlex
import sys

manifest_path, repo_id = sys.argv[1], sys.argv[2]

with open(manifest_path, "r", encoding="utf-8") as handle:
    manifest = json.load(handle)

if repo_id not in manifest:
    raise SystemExit(f"Unknown repo id: {repo_id}")

meta = manifest[repo_id]
values = {
    "REPO_PATH": meta["path"],
    "BUILD_ROOT": meta.get("build_root", meta["path"]),
    "LANGUAGE": meta.get("language", "java"),
    "FRAMEWORK": meta["framework"],
    "BUILD_SYSTEM": meta["build_system"],
    "BUILD_COMMAND": meta["build_command"],
    "JAVA_VERSION": str(meta["java_version"]),
    "MULTI_MODULE": "true" if meta.get("multi_module") else "false",
    "CLASSES_HINT": meta.get("classes_hint", ""),
}

for key, value in values.items():
    print(f"{key}={shlex.quote(value)}")
PY
)"

case "$JAVA_VERSION" in
  8)
    export JAVA_HOME="${JDK8_HOME:?JDK8_HOME is not set}"
    ;;
  11)
    export JAVA_HOME="${JDK11_HOME:?JDK11_HOME is not set}"
    ;;
  *)
    echo "[reviewer] Unsupported Java version for $REPO_ID: $JAVA_VERSION" >&2
    exit 1
    ;;
esac

export PATH="$JAVA_HOME/bin:$PATH"
export JAVA_ANALYZER_JAVA="${JDK11_HOME:?JDK11_HOME is not set}/bin/java"
export JAVA_ANALYZER_JAVA_OPTS="${JAVA_ANALYZER_JAVA_OPTS:--Xmx6g}"

BENCHMARK_DIR="$ARTIFACT_ROOT/benchmarks/java/$REPO_PATH"
BUILD_DIR="$ARTIFACT_ROOT/benchmarks/java/$BUILD_ROOT"
BENCHMARK_OUTPUT_DIR="$ARTIFACT_ROOT/outputs/$REPO_ID"
LOG_LINK="$BENCHMARK_DIR/.speculate_logs"

if [ ! -d "$BENCHMARK_DIR" ]; then
  echo "[reviewer] Benchmark directory does not exist: $BENCHMARK_DIR" >&2
  exit 1
fi

if [ ! -d "$BUILD_DIR" ]; then
  echo "[reviewer] Build directory does not exist: $BUILD_DIR" >&2
  exit 1
fi

mkdir -p "$BENCHMARK_OUTPUT_DIR"

if [ ! -L "$LOG_LINK" ]; then
  rm -rf "$LOG_LINK"
  ln -s "$BENCHMARK_OUTPUT_DIR" "$LOG_LINK"
fi

run_with_retries() {
  local attempt=1
  local max_attempts=4
  local delay=5

  while true; do
    if "$@"; then
      return 0
    fi

    if [ "$attempt" -ge "$max_attempts" ]; then
      echo "[reviewer] Command failed after $attempt attempts: $*" >&2
      return 1
    fi

    echo "[reviewer] Command failed, retrying in ${delay}s: $*" >&2
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay + 5))
  done
}

run_build_command() {
  if [ "$BUILD_SYSTEM" = "maven" ]; then
    mvn() {
      command mvn -B -Dmaven.wagon.http.retryHandler.count=5 "$@"
    }
    eval "$BUILD_COMMAND"
    return
  fi

  eval "$BUILD_COMMAND"
}

echo "[reviewer] Repo: $REPO_ID"
echo "[reviewer] Build system: $BUILD_SYSTEM"
echo "[reviewer] Java version: $JAVA_VERSION"
echo "[reviewer] JAVA_HOME: $JAVA_HOME"

if [ "$MODE" != "analyze" ]; then
  echo "[reviewer] Compiling $REPO_ID ..."
  cd "$BUILD_DIR"
  run_with_retries run_build_command
fi

if [ "$MODE" = "compile" ]; then
  echo "[reviewer] Compilation completed for $REPO_ID."
  exit 0
fi

echo "[reviewer] Running API spec generation ..."
cd "$TOOL_DIR"

/artifact/scripts/validate_env.sh

extra_args=()
if [ "$MULTI_MODULE" = "true" ]; then
  extra_args+=("--multi-module")
fi
if [ -n "$CLASSES_HINT" ]; then
  extra_args+=("--java-module-paths" "$BENCHMARK_DIR/$CLASSES_HINT")
fi

python3 gen_apidocs2.py "$BENCHMARK_DIR" --language "$LANGUAGE" --framework "$FRAMEWORK" "${extra_args[@]}" "${TOOL_EXTRA_ARGS[@]}"

echo "[reviewer] Run completed. Generated files are under $BENCHMARK_OUTPUT_DIR"
