#!/usr/bin/env python3
"""Prepare and check a local rollback patch; never apply it or contact a provider.

Publish the patch through a new authorized PR and strict staging delivery.
Settle pending discovery without requests, so it cannot strand the fairness cursor.
All retained RAW and unmatched candidates remain evidence, not deletion targets.
"""

import argparse
import difflib
import hashlib
from pathlib import Path
import re
import subprocess

BASE = "1ddb234b8a0a51a2ad313359e22168182bf07dbd"
PATH = "services/snkrdunk_collector/snkrdunk_collector/due.py"
ROOT = Path(__file__).resolve().parents[1]


def rollback_source(before):
    """Retain prior RAW/recovery behavior and fence off discovery without traffic."""
    refusal = """def reject_disabled_discovery(session, claim, *, freshness):
    result = CaptureResult(
        "identity_refusal", failure="published_discovery_disabled_by_rollback"
    )
    freshness.result = result
    return result


"""
    entry = "def run_due("
    call = (
        "                max_work=settings.BATCH_MAX_MAPPINGS_PER_RUN,\n"
        "                delay_seconds="
    )
    if before.count(entry) != 1 or before.count(call) != 1:
        raise ValueError("Retained dispatcher shape differs; rollback refused")
    return before.replace(entry, refusal + entry).replace(
        call,
        "                max_work=settings.BATCH_MAX_MAPPINGS_PER_RUN,\n"
        "                discovery_runner=reject_disabled_discovery,\n"
        "                delay_seconds=",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default=BASE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch("[0-9a-f]{40}", args.baseline):
        raise SystemExit("Full retained rollback commit required")
    before = subprocess.check_output(
        ["git", "show", args.baseline + ":" + PATH], cwd=ROOT, text=True
    )
    current = (ROOT / PATH).read_text()
    if "discovery_runner=" in before or "consume_planned_recovery" not in before:
        raise SystemExit(
            "Prior dispatcher is not the retained refresh/recovery baseline"
        )
    if current.count("discovery_runner=run_discovery") != 1:
        raise SystemExit("Expected bounded discovery dispatcher is not current")
    recovered = rollback_source(before)
    patch = "".join(
        difflib.unified_diff(
            current.splitlines(True),
            recovered.splitlines(True),
            fromfile="a/" + PATH,
            tofile="b/" + PATH,
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(patch)
    subprocess.run(
        ["git", "apply", "--check", str(args.output.resolve())], cwd=ROOT, check=True
    )
    print(
        "Checked local rollback patch SHA256="
        + hashlib.sha256(patch.encode()).hexdigest()
    )


if __name__ == "__main__":
    main()
