#!/usr/bin/env bash
set -euo pipefail

ARTIFACT_ROOT="/artifact"
MANIFEST_PATH="$ARTIFACT_ROOT/benchmarks/django/repos.json"
TOOL_ENTRY="$ARTIFACT_ROOT/tool/knowl-apidocs/genapidocs_v2/gen_apidocs2.py"

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <repo-id> [tool-args...]" >&2
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
    "SOURCE_ROOT": meta["source_root"],
    "LOG_ROOT": meta["log_root"],
    "FRAMEWORK": meta.get("framework", "django"),
    "LANGUAGE": meta.get("language", "python"),
    "VENV_PATH": meta["venv_path"],
    "DJANGO_SETTINGS_MODULE": meta["django_settings_module"],
    "DJANGO_EXPLICIT_URLS_FILE": meta.get("django_explicit_urls_file", ""),
}

for key, value in values.items():
    print(f"{key}={shlex.quote(value)}")
PY
)"

REPO_DIR="$ARTIFACT_ROOT/benchmarks/django/$REPO_PATH"
SOURCE_DIR="$ARTIFACT_ROOT/benchmarks/django/$SOURCE_ROOT"
LOG_DIR="$ARTIFACT_ROOT/benchmarks/django/$LOG_ROOT"
OUTPUT_DIR="$ARTIFACT_ROOT/outputs/$REPO_ID"
LOG_LINK="$LOG_DIR/.knowl_logs2"
PYTHON_BIN="$VENV_PATH/bin/python"

if [ ! -d "$REPO_DIR" ]; then
  echo "[reviewer] Benchmark directory does not exist: $REPO_DIR" >&2
  exit 1
fi

if [ ! -d "$SOURCE_DIR" ]; then
  echo "[reviewer] Source directory does not exist: $SOURCE_DIR" >&2
  exit 1
fi

if [ ! -x "$PYTHON_BIN" ]; then
  echo "[reviewer] Python runtime does not exist: $PYTHON_BIN" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

if [ ! -L "$LOG_LINK" ]; then
  rm -rf "$LOG_LINK"
  ln -s "$OUTPUT_DIR" "$LOG_LINK"
fi

cd "$REPO_DIR"

echo "[reviewer] Repo: $REPO_ID"
echo "[reviewer] Repo dir: $REPO_DIR"
echo "[reviewer] Source dir: $SOURCE_DIR"
echo "[reviewer] Python: $PYTHON_BIN"

bash /artifact/scripts/validate_env.sh

extra_args=(
  "--language" "$LANGUAGE"
  "--framework" "$FRAMEWORK"
  "--django-settings-module" "$DJANGO_SETTINGS_MODULE"
)

if [ -n "$DJANGO_EXPLICIT_URLS_FILE" ]; then
  extra_args+=("--django-explicit-urls-file" "$DJANGO_EXPLICIT_URLS_FILE")
fi

tool_cmd=(
  "$PYTHON_BIN"
  "$TOOL_ENTRY"
  "$SOURCE_DIR"
  "${extra_args[@]}"
)

if [ "${#TOOL_EXTRA_ARGS[@]}" -gt 0 ]; then
  tool_cmd+=("${TOOL_EXTRA_ARGS[@]}")
fi

"${tool_cmd[@]}"

echo "[reviewer] Run completed. Generated files are under $OUTPUT_DIR"
