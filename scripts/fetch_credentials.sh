#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ARTIFACT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_FILE="$ARTIFACT_DIR/reviewer.env"

usage() {
  cat >&2 <<'EOF'
Usage: ./scripts/fetch_credentials.sh <credentials-url>

Downloads LLM credentials from the URL provided in the reviewer notes.
The file is saved as reviewer.env in the artifact root directory.

Example:
  ./scripts/fetch_credentials.sh "https://ksbot0223142443.blob.core.windows.net/..."
EOF
  exit 2
}

if [ "$#" -lt 1 ] || [ -z "$1" ]; then
  usage
fi

URL="$1"

if [ -f "$OUTPUT_FILE" ]; then
  echo "[setup] reviewer.env already exists at $OUTPUT_FILE"
  read -r -p "[setup] Overwrite? [y/N] " answer
  case "$answer" in
    [yY]*) ;;
    *) echo "[setup] Aborted."; exit 0 ;;
  esac
fi

echo "[setup] Downloading credentials..."
if command -v curl >/dev/null 2>&1; then
  curl -fsSL -o "$OUTPUT_FILE" "$URL"
elif command -v wget >/dev/null 2>&1; then
  wget -q -O "$OUTPUT_FILE" "$URL"
else
  echo "[setup] Error: neither curl nor wget found." >&2
  exit 1
fi

echo "[setup] Credentials saved to $OUTPUT_FILE"
echo "[setup] You can now run:"
echo "  docker run --env-file reviewer.env ..."
