#!/usr/bin/env bash
set -euo pipefail

TOOL_BUILD_DIR="/artifact/tool/speculate-apidocs/genapidocs_v2/java_analyzer_impl"
FAT_JAR="$TOOL_BUILD_DIR/target/jersey-analyzer-1.0-SNAPSHOT-jar-with-dependencies.jar"

export JAVA_HOME="${JDK11_HOME:?JDK11_HOME is not set}"
export PATH="$JAVA_HOME/bin:$PATH"

run_with_retries() {
  local attempt=1
  local max_attempts=4
  local delay=5

  while true; do
    if "$@"; then
      return 0
    fi

    if [ "$attempt" -ge "$max_attempts" ]; then
      echo "[build] Command failed after $attempt attempts: $*" >&2
      return 1
    fi

    echo "[build] Command failed, retrying in ${delay}s: $*" >&2
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay + 5))
  done
}

mkdir -p "$TOOL_BUILD_DIR/target"

if [ -s "$FAT_JAR" ]; then
  echo "[build] Embedded Java analyzer JAR already present."
  exit 0
fi

rm -f "$FAT_JAR"

echo "[build] Building embedded Java analyzer with JDK 11 ..."
cd "$TOOL_BUILD_DIR"
run_with_retries mvn -B \
  -Dmaven.wagon.http.retryHandler.count=5 \
  -DskipTests \
  clean package assembly:single
