"""Shared helpers for the ops runbooks: import paths, secret masking, quiet windows, output.

No network and no credentials here. Every runbook writes JSON into one output directory that
the workflow uploads as an artifact; nothing secret may reach it (``assert_clean``).
"""
from __future__ import annotations

from datetime import datetime, time, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
for extra in ("scripts", "services/api", "packages/opcg_source_identity/src"):
    if str(ROOT / extra) not in sys.path:
        sys.path.insert(0, str(ROOT / extra))

# Environment variables that may hold credentials in an ops job. Their values must never
# appear in an output file. Values fetched at runtime (the Postgres password) are added
# with register_secret().
SECRET_ENV = ("RAILWAY_TOKEN", "STAGING_RAILWAY_TOKEN", "STAGING_VERCEL_READ_TOKEN",
              "GH_TOKEN", "GITHUB_TOKEN")
_secrets: set[str] = set()

# Quiet windows (UTC), enforced by run.py before any runbook starts.
# Collector-affecting: no collector change 02:00-06:00 (docs/agent/STAGING_DELIVERY.md).
# Write: nothing written 19:30-20:30 (market-index-snapshot at 20:00 and its receipt).
COLLECTOR_QUIET = (time(2, 0), time(6, 0))
WRITE_QUIET = (time(19, 30), time(20, 30))


class Refused(Exception):
    """A runbook refused to run or to continue. The message is safe to print."""


def register_secret(value):
    """Mask a runtime secret in the Actions log and remember it for the output scan."""
    if not value or len(value) < 6:
        return
    _secrets.add(value)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        # Workflow command: the runner masks the value in every later log line.
        sys.stdout.write(f"::add-mask::{value}\n")
        sys.stdout.flush()


def secret_values():
    values = set(_secrets)
    for name in SECRET_ENV:
        value = os.environ.get(name)
        if value and len(value) >= 6:
            values.add(value)
    return values


def assert_clean(out_dir):
    """Refuse to publish an output directory that contains any known secret value."""
    values = [v.encode() for v in secret_values()]
    leaked = []
    for path in sorted(Path(out_dir).rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            if any(v in data for v in values):
                leaked.append(path.name)
    if leaked:
        for path in Path(out_dir).rglob("*"):
            if path.is_file():
                path.unlink()
        raise Refused("secret value found in output; outputs deleted: " + ", ".join(leaked))


def in_window(now, window):
    start, end = window
    return start <= now.astimezone(timezone.utc).time() < end


def quiet_window_refusal(now, *, collector_affecting, write):
    """None when the runbook may start now, else the reason it may not."""
    now = now or datetime.now(timezone.utc)
    if collector_affecting and in_window(now, COLLECTOR_QUIET):
        return "collector quiet window 02:00-06:00 UTC: no collector-affecting runbook"
    if write and in_window(now, WRITE_QUIET):
        return "write quiet window 19:30-20:30 UTC: no write runbook"
    return None


def json_default(value):
    from datetime import date
    from decimal import Decimal

    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(type(value).__name__)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, default=json_default, ensure_ascii=False) + "\n")
    return path


def now_utc():
    return datetime.now(timezone.utc)
