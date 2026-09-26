#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"

progress() { printf '\n[codespaces] %s\n' "$1"; }

progress "Checking universal-image tooling"
for tool in git gh docker curl bash node npm; do
  command -v "$tool" >/dev/null || { printf 'Missing required base tool: %s\n' "$tool" >&2; exit 1; }
done

# universal:5.1.5-noble includes Python 3.12.1. Isolate project packages from
# its bundled data-science packages in one user-owned, rebuildable environment.
base_python=/usr/local/python/3.12.1/bin/python3.12
venv_dir="$HOME/.venvs/cardpirate"
if [[ ! -x "$base_python" ]]; then
  printf 'Expected Python 3.12 from the pinned universal image is missing.\n' >&2
  exit 1
fi
progress "Installing Python dependencies in one environment outside /workspaces"
if [[ ! -x "$venv_dir/bin/python" ]]; then
  "$base_python" -m venv "$venv_dir"
fi
source "$venv_dir/bin/activate"
export PATH="$venv_dir/bin:$HOME/.local/bin:$PATH"
export PYTHONNOUSERSITE=1
python -m pip install --disable-pip-version-check --no-cache-dir \
  -r services/api/requirements.txt \
  -r services/worker/requirements.txt \
  -r services/snkrdunk_collector/requirements.txt \
  -r services/yuyutei_collector/requirements.txt \
  ./packages/opcg_source_identity
python --version
python -m pip check
python -c 'import fastapi, sqlalchemy, playwright, boto3, opcg_source_identity'
python -c 'from importlib.metadata import version; assert version("playwright") == "1.61.0"'

# remoteEnv covers editor/Codex processes; also activate after shell startup
# files so login shells do not replace the environment with the image default.
activation='[ ! -f "$HOME/.venvs/cardpirate/bin/activate" ] || . "$HOME/.venvs/cardpirate/bin/activate"'
for profile in "$HOME/.bashrc" "$HOME/.profile"; do
  if ! grep -Fqx "$activation" "$profile" 2>/dev/null; then
    printf '\n%s\n' "$activation" >> "$profile"
  fi
done

progress "Installing frontend dependencies from package-lock.json"
node --version
npm --version
(cd apps/web && npm ci --no-audit --no-fund)
test -x apps/web/node_modules/.bin/tsc
test -x apps/web/node_modules/.bin/vitest
apps/web/node_modules/.bin/tsc --version
apps/web/node_modules/.bin/vitest --version

progress "Installing host Chromium headless shell and its system dependencies"
# Default headless Playwright launches use the shell. Avoid a second full
# Chromium download: existing Preview evidence scripts need branded Chrome.
python -m playwright install --with-deps --only-shell chromium
progress "Installing Google Chrome for native Preview and channel=chrome workflows"
python -m playwright install chrome
python -m playwright install --list
google-chrome --version

progress "Installing Railway CLI without authentication"
npm install --global --prefix "$HOME/.local" --no-audit --no-fund @railway/cli@5.62.1
railway --version

progress "Ensuring Codex CLI is available without authentication"
if ! command -v codex >/dev/null || ! codex --version >/dev/null 2>&1; then
  npm install --global --prefix "$HOME/.local" --no-audit --no-fund @openai/codex
  hash -r
fi
codex --version

progress "Ready: Python, frontend tools, host browsers, Railway CLI, and Codex CLI"
