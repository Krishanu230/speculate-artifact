#!/usr/bin/env bash
set -euo pipefail

has_real_value() {
  local value
  value="$(normalize_value "${1:-}")"
  if [ -z "$value" ]; then
    return 1
  fi

  case "$value" in
    CHANGE_ME|your-gcp-project-id|https://example.openai.azure.com/|https://api.deepseek.com)
      return 1
      ;;
  esac

  return 0
}

normalize_value() {
  local value="${1:-}"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  value="${value#\"}"
  value="${value%\"}"
  value="${value#\'}"
  value="${value%\'}"
  printf '%s' "$value"
}

has_azure_config=0
if [ -n "${AZURE_CONFIG_NAMES:-}" ]; then
  IFS=',' read -r -a azure_names <<< "${AZURE_CONFIG_NAMES}"
  for raw_name in "${azure_names[@]}"; do
    name="$(normalize_value "$raw_name")"
    if [ -z "$name" ]; then
      continue
    fi
    endpoint_var="AZURE_ENDPOINT_${name}"
    api_key_var="AZURE_API_KEY_${name}"
    if has_real_value "${!endpoint_var:-}" && has_real_value "${!api_key_var:-}"; then
      has_azure_config=1
      break
    fi
  done
fi

has_gemini_config=0
if has_real_value "${GOOGLE_VERTEX_PROJECT_ID:-}" && has_real_value "${GOOGLE_VERTEX_LOCATION:-}" && has_real_value "${GOOGLE_API_KEY:-}"; then
  has_gemini_config=1
fi

has_deepseek_config=0
if has_real_value "${DEEPSEEK_ENDPOINT:-}" && has_real_value "${DEEPSEEK_API_KEY:-}"; then
  has_deepseek_config=1
fi

if [ "$has_azure_config" -eq 1 ] || [ "$has_gemini_config" -eq 1 ] || [ "$has_deepseek_config" -eq 1 ]; then
  exit 0
fi

cat >&2 <<'EOF'
[reviewer] No usable LLM provider configuration was found in the container environment.
[reviewer] Supply real credentials at runtime, for example:
[reviewer]   docker run --rm --env-file /path/to/reviewer.env ...
[reviewer] Accepted options:
[reviewer]   - Azure: AZURE_CONFIG_NAMES, AZURE_ENDPOINT_<name>, AZURE_API_KEY_<name>, AZURE_MODEL_MAP_*, AZURE_DEFAULT_MODEL_NAME
[reviewer]   - Gemini: GOOGLE_VERTEX_PROJECT_ID, GOOGLE_VERTEX_LOCATION, GOOGLE_API_KEY
[reviewer]   - DeepSeek: DEEPSEEK_ENDPOINT, DEEPSEEK_API_KEY
EOF
exit 1
