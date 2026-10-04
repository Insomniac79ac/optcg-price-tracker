#!/usr/bin/env python3
"""Fail-closed mission contract validation. No network, credentials or mutations."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

RED = {
    "production", "pricing_methodology", "identity_weakening", "ambiguous_approval",
    "security_or_secrets_policy", "published_history_rewrite", "yuyu_sale_policy",
    "private_data_exposure", "major_product_or_brand", "destructive_migration",
    "significant_recurring_cost", "legal_compliance",
}
AMBER = {"migration", "infrastructure", "service_cutover", "bulk_data", "source_envelope", "subsystem_activation"}
GREEN = {"application", "tests", "documentation", "state_observation", "staging_deployment"}
MANIFEST = "docs/agent/STAGING_MISSION.json"


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def change_evidence(base, head):
    # Manifest is data, never an executable policy override. It cannot hash itself.
    args = [base, head, "--", ".", f":(exclude){MANIFEST}"]
    patch = subprocess.check_output(["git", "diff", "--binary", "--no-ext-diff", *args])
    files = git("diff", "--name-only", *args).splitlines()
    return files, hashlib.sha256(patch).hexdigest()


def evaluate(mission, files, digest):
    errors = []
    impacts = mission.get("impacts", [])
    effects = {effect for item in impacts for effect in item.get("effects", [])}
    red = sorted(effects & RED)
    decisions = mission.get("red_decisions", {})
    red.extend(key for key in sorted(RED) if decisions.get(key) is True)
    if mission.get("target") != "staging":
        red.append("production: target must be staging")
    if red:
        return {"classification": "RED", "eligible": False,
                "errors": ["Human decision required: " + x for x in red]}
    if mission.get("schema_version") != 1 or not mission.get("mission"):
        errors.append("A versioned, explicitly named mission is required")
    if set(decisions) != RED or any(type(v) is not bool for v in decisions.values()):
        errors.append("Every RED impact must be explicitly assessed with a boolean")
    if mission.get("diff_sha256") != digest:
        errors.append("Impact evidence is stale: diff SHA-256 does not match this PR")
    covered = [path for item in impacts for path in item.get("files", [])]
    if len(covered) != len(set(covered)) or set(covered) != set(files):
        errors.append("Impact entries must cover each changed file exactly once")
    for item in impacts:
        if not item.get("reason") or not item.get("effects"):
            errors.append("Each impact needs an explanation and explicit effects")
    if effects - RED - AMBER - GREEN:
        errors.append("Unknown impact category")
    # Paths provide conservative floors; explicit effects can always raise them.
    floor = any(p.startswith((".github/workflows/", "deploy/", "services/api/alembic/"))
                or p.endswith("vercel.json") for p in files)
    level = "AMBER" if floor or effects & AMBER else "GREEN"
    if mission.get("classification") != level:
        errors.append(f"Declared classification must be {level}")
    if level == "AMBER":
        safeguards = mission.get("safeguards", {})
        impact = safeguards.get("impact", {})
        for key in ("resources", "routes", "dependencies", "deployment_impact"):
            if not impact.get(key):
                errors.append(f"AMBER requires impact.{key}")
        for key in ("database_writes", "source_requests", "estimated_runtime_minutes"):
            if type(impact.get(key)) is not int or impact[key] < 0:
                errors.append(f"AMBER requires bounded nonnegative impact.{key}")
        recovery = safeguards.get("recovery", {})
        for key in ("artifact", "procedure", "trigger", "backup", "validation"):
            if not recovery.get(key):
                errors.append(f"AMBER requires recovery.{key}")
        verify = safeguards.get("verification", {})
        for key in ("required_checks", "post_change", "observation_window"):
            if not verify.get(key):
                errors.append(f"AMBER requires verification.{key}")
        checks = verify.get("required_checks", [])
        if not isinstance(checks, list) or "engineering-gate" not in checks:
            errors.append("AMBER verification must require engineering-gate")
    return {"classification": level, "eligible": not errors, "errors": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--manifest", default=MANIFEST)
    parser.add_argument("--output")
    args = parser.parse_args()
    files, digest = change_evidence(args.base, args.head)
    try:
        mission = json.loads(Path(args.manifest).read_text())
        result = evaluate(mission, files, digest)
        if result["classification"] == "AMBER" and result["eligible"]:
            artifact = mission["safeguards"]["recovery"]["artifact"]
            # A documented rollback must resolve to actual retained Git source.
            git("cat-file", "-e", artifact + "^{commit}")
            for section, key in (("recovery", "validation"), ("verification", "post_change")):
                paths = mission["safeguards"][section][key]
                if not isinstance(paths, list) or not paths:
                    raise ValueError("Verification must reference repository evidence/scripts")
                for path in paths:
                    if Path(path).is_absolute() or ".." in Path(path).parts:
                        raise ValueError("Evidence must be repository-relative")
                    git("cat-file", "-e", args.head + ":" + path)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        result = {"classification": "RED", "eligible": False,
                  "errors": [f"Missing or invalid policy/recovery evidence ({type(exc).__name__})"]}
    print(json.dumps(result, indent=2))
    if args.output:
        Path(args.output).write_text(json.dumps(result) + "\n")
    return 0 if result["eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
