#!/usr/bin/env bash
set -euo pipefail

CREDS_URL="https://ksbot0223142443.blob.core.windows.net/artifact-creds/reviewer.env?se=2026-07-31T00%3A00%3A00Z&sp=r&spr=https&sv=2026-02-06&sr=b&sig=Dzjz6thSVllHNfdj3hx0uE%2BDQM7zEn6C3z4dVAq6iXg%3D"

# Check if the reviewer already provided LLM credentials via --env-file
has_creds=0

if [ -n "${AZURE_CONFIG_NAMES:-}" ]; then
  has_creds=1
fi
if [ -n "${GOOGLE_API_KEY:-}" ] && [ "${GOOGLE_API_KEY:-}" != "CHANGE_ME" ]; then
  has_creds=1
fi
if [ -n "${DEEPSEEK_API_KEY:-}" ] && [ "${DEEPSEEK_API_KEY:-}" != "CHANGE_ME" ]; then
  has_creds=1
fi

if [ "$has_creds" -eq 0 ]; then
  echo "[setup] No LLM credentials detected. Fetching default credentials..."
  tmpenv=$(mktemp)
  if curl -fsSL -o "$tmpenv" "$CREDS_URL" 2>/dev/null; then
    set -a
    # shellcheck disable=SC1090
    . "$tmpenv"
    set +a
    rm -f "$tmpenv"
    echo "[setup] Default credentials loaded successfully."
  else
    rm -f "$tmpenv"
    echo "[setup] Warning: Could not fetch default credentials." >&2
    echo "[setup] Please provide credentials via --env-file. See README.md." >&2
  fi
else
  echo "[setup] Using reviewer-provided LLM credentials."
fi

exec "$@"
