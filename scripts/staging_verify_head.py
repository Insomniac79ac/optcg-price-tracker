#!/usr/bin/env python3
"""Does this Verify staging merge run still own verification? Read-only.

A push run verifies its own merge. A workflow_dispatch run re-verifies the
sha its expected_sha input names, and only while that sha is the staging
head: an older sha is obsolete (exit 0, current=false), so a stale dispatch
can never certify a commit that staging has moved past. A malformed sha fails.
"""
import argparse
import os
import re
import subprocess
import sys

REPOSITORY = "Insomniac79ac/optcg-price-tracker"
OBSOLETE = "Obsolete queued verification; newer staging commit owns verification."


def staging_head():
    return subprocess.run(
        ["gh", "api", f"repos/{REPOSITORY}/branches/staging", "--jq", ".commit.sha"],
        check=True, capture_output=True, text=True).stdout.strip()


def require_sha(expected):
    if not re.fullmatch("[0-9a-f]{40}", expected or ""):
        raise SystemExit("expected sha must be a full 40-hex staging commit")


def decide(expected, current):
    """True when expected is the staging head; False when staging moved on."""
    require_sha(expected)
    if not re.fullmatch("[0-9a-f]{40}", current or ""):
        raise SystemExit("could not read the staging head")
    return expected == current


def main(argv=None, head=staging_head):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", required=True)
    args = parser.parse_args(argv)
    require_sha(args.expected)  # before any network read
    current = decide(args.expected, head())
    if not current:
        print(OBSOLETE)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a") as handle:
            handle.write(f"current={'true' if current else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
