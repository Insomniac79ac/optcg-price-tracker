#!/usr/bin/env bash
# Yuyu-Tei browser feasibility spike - macOS/Linux local runner.
#
# Isolated spike: does not touch the application, database, workers,
# migrations, or deployments. Sets up a local virtual environment (if
# missing), installs pinned dependencies and the branded Chrome channel,
# then runs the local test: headed branded Chrome, a dedicated persistent
# profile under this spike directory, homepage -> OP01 category -> OP01-001
# Zoro parallel product page. Requires a real desktop display (headed).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

python3 -m playwright install chrome

python3 spike.py --mode persistent_chrome

echo
echo "Result: $SCRIPT_DIR/output/persistent_chrome/result.json"
