#!/usr/bin/env bash
# Generate exact, hashed Python dependency locks in the same Linux image
# families used by the deployable services. This script only writes the four
# requirements.lock.txt files; runtime Docker/CI installs continue to use the
# human-maintained requirements.txt files until M4C.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$SCRIPT_DIR/.." && pwd)"

python_image="python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea"
playwright_image="mcr.microsoft.com/playwright/python:v1.61.0-jammy@sha256:108b33fc1c785c056665b04c320a612526503b0b081209eea2e1ec89e3b69a8f"
lock_pip_version="25.0.1"
lock_tool_version="7.5.1"

compile_lock() {
  local image="$1"
  local service_dir="$2"

  docker run --rm \
    --user "$(id -u):$(id -g)" \
    --env HOME=/tmp \
    --env PIP_DISABLE_PIP_VERSION_CHECK=1 \
    --env "LOCK_PIP_VERSION=$lock_pip_version" \
    --env "LOCK_TOOL_VERSION=$lock_tool_version" \
    --volume "$repo_root:/repo" \
    --workdir "/repo/$service_dir" \
    "$image" \
    sh -ceu '
      tool_dir="$(mktemp -d)"
      python -m pip install --quiet --no-cache-dir \
        --target "$tool_dir" \
        "pip==$LOCK_PIP_VERSION" "pip-tools==$LOCK_TOOL_VERSION"
      CUSTOM_COMPILE_COMMAND=./scripts/compile_python_locks.sh \
      PYTHONPATH="$tool_dir" python -m piptools compile \
        --quiet \
        --constraint=../../constraints/python-shared.txt \
        --generate-hashes \
        --newline=lf \
        --no-emit-index-url \
        --no-emit-trusted-host \
        --output-file=requirements.lock.txt \
        --resolver=backtracking \
        --strip-extras \
        requirements.txt
    '
}

compile_lock "$python_image" services/api
compile_lock "$python_image" services/worker
compile_lock "$playwright_image" services/yuyutei_collector
compile_lock "$playwright_image" services/snkrdunk_collector
