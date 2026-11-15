#!/usr/bin/env python3
"""Decide whether a merged staging change may skip collector rollout and RAW DDL.

Read-only: inspects local Git only. No network, credentials or mutations.

A change skips ONLY when every changed path is on a narrow documentation
allowlist. A per-PR mission file (scripts/staging_mission.py) is not
documentation: the merge may add exactly one, as the policy declaration every
DATA-lane PR carries, and it must request no collector rollout and no RAW
dependency migration. Anything else, or any change set that cannot be
determined, runs the full delivery exactly as before. Verification and state
regeneration always run.

A PRODUCT-lane merge (scripts/product_lane.py; the policy gate already admitted
it) also skips collector rollout and RAW DDL. It adds no mission, so it can
never replay an earlier mission's requests. Its verification expects the merged
API and the repository's single Alembic head instead of the fleet state's.
"""
import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess

from staging_mission import DEPLOY_REQUEST_KEYS, FLEET, LEGACY_MANIFEST, MISSIONS_DIR, is_mission

# docs/ inputs read by delivery, migration, verification or state scripts.
# These are never documentation, whatever their extension.
OPERATIONAL_PREFIXES = ("docs/agent/evidence/", MISSIONS_DIR)
OPERATIONAL_FILES = {FLEET, LEGACY_MANIFEST, "docs/agent/CURRENT_STATE.yaml"}


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


def deploy_requests(mission):
    verification = mission.get("deployment_verification", {})
    if not isinstance(verification, dict):
        raise ValueError("Mission deployment_verification is not an object")
    return {key: verification[key] for key in DEPLOY_REQUEST_KEYS
            if verification.get(key) not in (None, [], {})}


def decide(rows, mission):
    """Return the scope decision for parsed change rows. Fail closed.

    `mission` is the merge's one added mission file, or None.
    """
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
        outside.extend(p for p in paths if not (status == "A" and is_mission(p)) and not allowlisted(p))
    if outside:
        return {**result, "reason": "Non-documentation change", "outside_allowlist": sorted(set(outside))}
    missions = [p for p in files if is_mission(p)]
    if missions and len(missions) == len(files):
        return {**result, "reason": "Mission-only change is operational"}
    if len(missions) > 1:
        return {**result, "reason": f"More than one mission file: {missions}"}
    if missions:
        if mission is None:
            return {**result, "reason": "Mission added but cannot be read"}
        try:
            requested = deploy_requests(mission)
        except (ValueError, AttributeError) as exc:
            return {**result, "reason": f"Mission unreadable: {exc}"}
        if requested:
            return {**result, "reason": "Mission requests deployment", "requested": sorted(requested)}
    return {"decision": "skip", "files": files,
            "reason": "Every changed path is allowlisted documentation; the mission requests no rollout or migration"}


def product_decision(base, merge):
    """{} (stay full) unless the merge is PRODUCT lane with one Alembic head."""
    try:
        import product_lane
        import staging_db_read_check as guard
        lane = product_lane.classify(base, merge, require_security_review=False)
        heads = sorted(guard.expected_revisions_from_repo(str(Path(__file__).resolve().parents[1])))
    except Exception as exc:  # Fail closed to the full delivery.
        return {"product_lane": f"undetermined ({type(exc).__name__})"}
    if lane["lane"] != "product":
        return {"product_lane": lane["reasons"]}
    if len(heads) != 1:
        return {"product_lane": f"expected one Alembic head, found {heads}"}
    return {"decision": "product", "api_sha": "merge", "revision": heads[0],
            "migrations": lane["migrations"],
            "reason": "PRODUCT lane: no collector rollout or RAW DDL; verify merged API and repo head"}


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
        added = [paths[0] for status, paths in rows if status == "A" and is_mission(paths[0])]
        mission = None
        if len(added) == 1:
            try:
                mission = json.loads(git("show", f"{args.merge}:{added[0]}"))
            except (subprocess.CalledProcessError, json.JSONDecodeError):
                mission = None
        result = {"base": base, "merge": args.merge, **decide(rows, mission)}
        if result["decision"] == "full":
            result = {**result, **product_decision(base, args.merge)}
    except (subprocess.CalledProcessError, ValueError, OSError) as exc:
        result = {"merge": args.merge, "decision": "full", "files": [],
                  "reason": f"Change set undetermined ({type(exc).__name__})"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
