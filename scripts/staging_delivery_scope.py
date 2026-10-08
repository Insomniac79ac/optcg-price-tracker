#!/usr/bin/env python3
"""Decide whether a merged staging change may skip collector rollout and RAW DDL.

Read-only: inspects local Git only. No network, credentials or mutations.

A change skips ONLY when every changed path is on a narrow documentation
allowlist. The per-PR mission manifest is not documentation: it may change only
as the policy declaration every staging PR must carry, and it must request no
collector rollout and no RAW dependency migration. Anything else, or any change
set that cannot be determined, runs the full delivery exactly as before.
Verification and state regeneration always run.
"""
import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess

MANIFEST = "docs/agent/STAGING_MISSION.json"
# docs/ inputs read by delivery, migration, verification or state scripts.
# These are never documentation, whatever their extension.
OPERATIONAL_PREFIXES = ("docs/agent/evidence/",)
OPERATIONAL_FILES = {MANIFEST, "docs/agent/CURRENT_STATE.yaml"}
# Manifest keys that request a mutation from the delivery job.
DEPLOY_REQUEST_KEYS = ("collector_services", "raw_dependency_migration")


def allowlisted(path):
    p = PurePosixPath(path)
    if path in OPERATIONAL_FILES or path.startswith(OPERATIONAL_PREFIXES):
        return False
    if ".." in p.parts or p.is_absolute():
        return False
    if path.startswith("docs/agent/handoff/"):
        return True
    return path.startswith("docs/") and p.suffix == ".md"


def parse_name_status(text):
    """Parse `git diff --name-status -M -z` output into (status, paths) rows."""
    fields = text.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    rows, i = [], 0
    while i < len(fields):
        status = fields[i]
        if not status:
            raise ValueError("Malformed name-status output")
        width = 2 if status[0] in "RC" else 1
        paths = fields[i + 1:i + 1 + width]
        if len(paths) != width or not all(paths):
            raise ValueError("Malformed name-status output")
        rows.append((status, paths))
        i += 1 + width
    return rows


def deploy_requests(manifest):
    verification = manifest.get("deployment_verification")
    if not isinstance(verification, dict):
        raise ValueError("Manifest has no deployment_verification")
    return {key: verification[key] for key in DEPLOY_REQUEST_KEYS
            if verification.get(key) not in (None, [], {})}


def decide(rows, head_manifest):
    """Return the scope decision for parsed change rows. Fail closed."""
    files = sorted({path for _, paths in rows for path in paths})
    result = {"decision": "full", "files": files}
    if not rows:
        return {**result, "reason": "Empty or undetermined change set"}
    outside = []
    for status, paths in rows:
        if status[0] in "RC":
            # A rename/copy is documentation only when both sides are.
            if not all(allowlisted(p) for p in paths):
                return {**result, "reason": f"Rename/copy crosses the documentation allowlist: {paths}"}
        elif status[0] not in "AMD":
            return {**result, "reason": f"Unsupported change status {status}: {paths}"}
        outside.extend(p for p in paths if p != MANIFEST and not allowlisted(p))
    if outside:
        return {**result, "reason": "Non-documentation change", "outside_allowlist": sorted(set(outside))}
    if not any(p != MANIFEST for p in files):
        return {**result, "reason": "Manifest-only change is operational"}
    if MANIFEST in files:
        if head_manifest is None:
            return {**result, "reason": "Manifest changed but cannot be read"}
        try:
            requested = deploy_requests(head_manifest)
        except (ValueError, AttributeError) as exc:
            return {**result, "reason": f"Manifest unreadable: {exc}"}
        if requested:
            return {**result, "reason": "Manifest requests deployment", "requested": sorted(requested)}
    return {"decision": "skip", "files": files,
            "reason": "Every changed path is allowlisted documentation; manifest requests no rollout or migration"}


def git(*args):
    return subprocess.check_output(["git", *args], text=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merge", required=True, help="Merged staging commit")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        base = git("rev-parse", "--verify", args.merge + "^1").strip()
        rows = parse_name_status(git("diff", "--name-status", "-M", "-z", base, args.merge))
        try:
            head_manifest = json.loads(git("show", f"{args.merge}:{MANIFEST}"))
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            head_manifest = None
        result = {"base": base, "merge": args.merge, **decide(rows, head_manifest)}
    except (subprocess.CalledProcessError, ValueError, OSError) as exc:
        result = {"merge": args.merge, "decision": "full", "files": [],
                  "reason": f"Change set undetermined ({type(exc).__name__})"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
