#!/usr/bin/env python3
"""Per-PR staging missions and the shared fleet state. Fail closed.

Read-only: local Git and files only. No network, credentials or mutations.

Every DATA-lane PR adds exactly one docs/agent/missions/<name>.json that
describes that change (mission, classification, RED decisions, impacts,
safeguards, diff_sha256, and any rollout or RAW migration it requests). State
that carries from one delivery to the next (API and Alembic expectations,
pinned collector components, verification checks, operational notes) lives in
docs/agent/STAGING_FLEET.json, which only PRs that move the fleet edit.

compose() rebuilds the single manifest shape that the policy evaluator, the
delivery scripts and the verifiers have always read. A mission may add only
deployment requests and, for its own delivery, component expectations; it can
never replace the fleet's API or Alembic expectations.

The diff hash covers what the PR itself changes (merge-base to head, full index
lines), so merging staging into a PR does not make its mission stale.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

MISSIONS_DIR = "docs/agent/missions/"
FLEET = "docs/agent/STAGING_FLEET.json"
# Retired by per-PR missions. Nothing reads it; a revert restores that flow.
LEGACY_MANIFEST = "docs/agent/STAGING_MISSION.json"
DEPLOY_REQUEST_KEYS = ("collector_services", "raw_dependency_migration")
# A collector PR expects its own merge ("merge"); the fleet pins full SHAs.
COMPONENT_KEYS = ("yuyu_reader_component", "snkr_component")
FLEET_KEYS = {"schema_version", "deployment_verification", "operational_notes"}
MISSION_NAME = re.compile(r"docs/agent/missions/[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.json")
FULL_SHA = re.compile(r"[0-9a-f]{40}")
# Set by a delivery job so verifiers read its composed manifest.
MANIFEST_ENV = "STAGING_MISSION_MANIFEST"


class MissionError(ValueError):
    pass


def git(*args):
    return subprocess.check_output(["git", *args], text=True)


def is_mission(path):
    return path.startswith(MISSIONS_DIR)


def merge_base(base, head):
    return git("merge-base", base, head).strip()


def mission_rows(base, head):
    """(status, path) for every mission path the PR changes (merge-base to head)."""
    out = git("diff", "--name-status", "--no-renames", "-z", merge_base(base, head), head,
              "--", MISSIONS_DIR)
    fields = out.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % 2:
        raise MissionError("Malformed name-status output")
    return [(fields[i], fields[i + 1]) for i in range(0, len(fields), 2)]


def added_mission(rows, allow_none=False):
    """The one mission file the PR adds. Any other mission change is refused."""
    changed = [path for status, path in rows if status != "A"]
    if changed:
        raise MissionError(f"Mission files may only be added, never changed or removed: {changed}")
    added = [path for _, path in rows]
    if not added and allow_none:
        return None
    if len(added) != 1:
        raise MissionError(f"Exactly one added mission file is required, found {len(added)}")
    if not MISSION_NAME.fullmatch(added[0]):
        raise MissionError(f"Mission file must be {MISSIONS_DIR}<name>.json: {added[0]}")
    return added[0]


def change_evidence(base, head, mission_path):
    """(files, sha256) of what the PR itself changes, excluding its own mission."""
    args = [merge_base(base, head), head, "--", ".", f":(exclude){mission_path}"]
    patch = subprocess.check_output(["git", "diff", "--binary", "--full-index", "--no-ext-diff", *args])
    files = git("diff", "--name-only", *args).splitlines()
    return files, hashlib.sha256(patch).hexdigest()


def read_at(rev, path):
    try:
        return json.loads(git("show", f"{rev}:{path}"))
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        raise MissionError(f"Cannot read {path} at {rev[:12]} ({type(exc).__name__})") from exc


def compose(mission, fleet):
    """The manifest shape delivery has always read: fleet state plus one mission."""
    if not isinstance(mission, dict) or not isinstance(fleet, dict):
        raise MissionError("Mission and fleet state must be JSON objects")
    if fleet.get("schema_version") != 1 or set(fleet) - FLEET_KEYS:
        raise MissionError(f"Fleet state must be schema_version 1 with only {sorted(FLEET_KEYS)}")
    fleet_verification = fleet.get("deployment_verification")
    if not isinstance(fleet_verification, dict):
        raise MissionError("Fleet state has no deployment_verification")
    if set(fleet_verification) & set(DEPLOY_REQUEST_KEYS):
        raise MissionError("Fleet state may not request a rollout or RAW migration")
    for key in COMPONENT_KEYS:
        if key in fleet_verification and not FULL_SHA.fullmatch(str(fleet_verification[key])):
            raise MissionError(f"Fleet {key} must be pinned to a full SHA")
    if "operational_notes" in mission:
        raise MissionError("operational_notes belong in the fleet state")
    requests = mission.get("deployment_verification", {})
    if not isinstance(requests, dict):
        raise MissionError("Mission deployment_verification must be an object")
    extra = set(requests) - set(DEPLOY_REQUEST_KEYS) - set(COMPONENT_KEYS)
    if extra:
        raise MissionError(f"A mission may not set fleet expectations: {sorted(extra)}")
    for key in COMPONENT_KEYS:
        if key in requests and requests[key] != "merge" and not FULL_SHA.fullmatch(str(requests[key])):
            raise MissionError(f"Mission {key} must be merge or a full SHA")
    composed = {key: value for key, value in mission.items() if key != "deployment_verification"}
    composed["deployment_verification"] = {**fleet_verification, **requests}
    if "operational_notes" in fleet:
        composed["operational_notes"] = fleet["operational_notes"]
    return composed


def manifest_for(base, head, allow_none=False):
    """(mission path or None, composed manifest) for the change base..head."""
    path = added_mission(mission_rows(base, head), allow_none)
    fleet = read_at(head, FLEET)
    return path, compose(read_at(head, path) if path else {}, fleet)


def deployment_verification(root):
    """Verifier expectations: the delivery's composed manifest, else the fleet state."""
    path = os.environ.get(MANIFEST_ENV) or str(Path(root) / FLEET)
    return json.loads(Path(path).read_text())["deployment_verification"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    digest = sub.add_parser("digest", help="Print the PR's mission path, changed files and diff_sha256")
    build = sub.add_parser("compose", help="Write the composed manifest for base..head")
    for cmd in (digest, build):
        cmd.add_argument("--base", required=True)
        cmd.add_argument("--head", default="HEAD")
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--allow-none", action="store_true",
                       help="Use the fleet state alone when the change adds no mission")
    args = parser.parse_args(argv)
    try:
        if args.command == "digest":
            path = added_mission(mission_rows(args.base, args.head))
            files, sha = change_evidence(args.base, args.head, path)
            print(json.dumps({"mission": path, "files": files, "diff_sha256": sha}, indent=2))
            return 0
        path, manifest = manifest_for(args.base, args.head, args.allow_none)
    except (MissionError, subprocess.CalledProcessError, OSError) as exc:
        print(json.dumps({"error": str(exc) if isinstance(exc, MissionError) else type(exc).__name__}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"mission": path, "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
