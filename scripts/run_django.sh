#!/usr/bin/env bash
set -euo pipefail

export MSYS_NO_PATHCONV=1

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ARTIFACT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE="${ARTIFACT_IMAGE:-speculate-artifact}"

if [ "$#" -lt 1 ]; then
  echo "usage: $0 <repo-id> [tool-args...]" >&2
  echo "repo ids: education-backend, librephotos, mathesar, treeherder" >&2
  exit 2
fi

REPO_ID="$1"
shift
TOOL_ARGS=("$@")

env_args=()
if [ -f "$ARTIFACT_ROOT/reviewer.env" ]; then
  env_args+=(--env-file "$ARTIFACT_ROOT/reviewer.env")
fi

mkdir -p "$ARTIFACT_ROOT/outputs"

docker_args=(
  run
  --rm
  -v "$ARTIFACT_ROOT/outputs:/artifact/outputs"
)

if [ "${#env_args[@]}" -gt 0 ]; then
  docker_args+=("${env_args[@]}")
fi

docker_args+=(
  "$IMAGE"
  /artifact/scripts/run_django_repo.sh
  "$REPO_ID"
)

if [ "${#TOOL_ARGS[@]}" -gt 0 ]; then
  docker_args+=("${TOOL_ARGS[@]}")
fi

docker "${docker_args[@]}"
