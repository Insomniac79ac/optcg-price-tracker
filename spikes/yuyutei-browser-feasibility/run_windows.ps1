# Yuyu-Tei browser feasibility spike - Windows local runner.
#
# Isolated spike: does not touch the application, database, workers,
# migrations, or deployments. Sets up a local virtual environment (if
# missing), installs pinned dependencies and the branded Chrome channel,
# then runs the local test: headed branded Chrome, a dedicated persistent
# profile under this spike directory, homepage -> OP01 category -> OP01-001
# Zoro parallel product page.

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

. .\.venv\Scripts\Activate.ps1

pip install --upgrade pip
pip install -r requirements.txt

python -m playwright install chrome

python spike.py --mode persistent_chrome

Write-Host ""
Write-Host "Result: $ScriptDir\output\persistent_chrome\result.json"
