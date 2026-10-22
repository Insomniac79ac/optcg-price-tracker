"""collector-redeploy: put every staging collector back on its own verified image (owner-gated).

A Railway service picks up changed shared variables only on a new deployment; a restart or a
cron run keeps the values of the deployment it runs (2026-10-22: the Postgres password was
rotated after Railway's security incident and every collector kept the old one). Railway's
dashboard offers only "Deploy latest commit" on a collector, which builds from the branch and
loses the verified upload. This runbook makes the new deployment without a build:

For each of the 10 collectors, in name order, the fleet pin in docs/agent/STAGING_FLEET.json
(snkr_component for snkrdunk-collector, yuyu_reader_component for the yuyutei shards; the same
pins Verify staging merge checks) gives the exact commit. The source is the newest redeployable
deployment carrying that exact-commit marker, and its image digest is the one restored.
collector_variables.restore stages APP_ENV=staging with --skip-deploys (a value every collector
already carries, so nothing changes), redeploys that source, waits for SUCCESS, and checks digest,
cron schedule, start command and the read-back. No branch build, no code change, no source job.
Stops at the first failure.

The committed rollout receipts are not used: a delivery's receipt is a CI artifact and only some
were committed (2026-10-22: the receipt chain still named the PR #103 SNKR image, while the fleet
pin and the live collector had moved to the PR #180 delivery).

Dry run (default): per collector, the pinned commit, the source deployment and its digest, and the
live deployment. The plan SHA-256 covers service, commit, digest and the live deployment id, so any
deployment between the dry run and the apply refuses the apply.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from ops import common

FLEET = "docs/agent/STAGING_FLEET.json"

NOOP = {"APP_ENV": "staging"}


def check_apply(apply, expected_sha256, sha):
    if not apply:
        return
    if not (isinstance(expected_sha256, str) and len(expected_sha256) == 64
            and all(c in "0123456789abcdef" for c in expected_sha256)):
        raise common.Refused("apply needs expected_sha256: the plan SHA-256 from a dry run")
    if expected_sha256 != sha:
        raise common.Refused("the plan differs from the dry run's (expected_sha256); dry run again")


def plan_sha(rows):
    pinned = [[r["service"], r["commit"], r["image_digest"], r["live_deployment"]] for r in rows]
    return hashlib.sha256(json.dumps(pinned, separators=(",", ":")).encode()).hexdigest()


def fleet_pins(names, root=None):
    """{collector: pinned commit} from STAGING_FLEET.json; refuses a missing or non-SHA pin."""
    verification = json.loads((Path(root or common.ROOT) / FLEET).read_text())["deployment_verification"]
    keys = {"snkr": "snkr_component", "yuyu": "yuyu_reader_component"}
    pins = {}
    for name in sorted(names):
        key = keys["snkr"] if name == "snkrdunk-collector" else keys["yuyu"] if name.startswith(
            "yuyutei-collector-shard-") else None
        commit = verification.get(key) if key else None
        if not (isinstance(commit, str) and re.fullmatch("[0-9a-f]{40}", commit)):
            raise common.Refused(f"{name}: no full commit pin in {FLEET}")
        pins[name] = commit
    return pins


def pinned_source(node, commit, *, read, listing, error=Exception):
    """Newest redeployable deployment carrying the pin's exact-commit marker and an image."""
    for identity in listing(node["serviceId"]):
        try:
            candidate = read(identity, node["serviceId"], commit)
        except error:
            continue
        digest = (candidate.get("meta") or {}).get("imageDigest") or ""
        if candidate.get("canRedeploy") and re.fullmatch("sha256:[0-9a-f]{64}", digest):
            return candidate
    raise error("No redeployable deployment of the pinned commit")


def plan(live, pins, source_for):
    """One row per collector: pinned commit, redeploy source and its digest, live deployment."""
    rows = []
    for name, commit in sorted(pins.items()):
        node = live.get(name)
        if node is None:
            raise common.Refused(f"{name}: service not found")
        latest = node.get("latestDeployment") or {}
        out = {"service": name, "commit": commit, "image_digest": None,
               "live_deployment": latest.get("id"), "live_status": latest.get("status"),
               "schedule": node.get("cronSchedule")}
        try:
            source = source_for(node, commit)
            out["source_deployment"] = source["id"]
            out["image_digest"] = source["meta"]["imageDigest"]
        except Exception as error:  # noqa: BLE001 - provider text is never echoed
            out["source_deployment"] = None
            out["problem"] = str(error) if type(error).__name__ == "VerificationError" else type(error).__name__
        rows.append(out)
    return rows


def apply_rows(rows, restore, now=common.now_utc):
    """Redeploy in order; stop at the first failure or at the collector quiet window."""
    done, stopped = [], None
    for row in rows:
        reason = common.quiet_window_refusal(now(), collector_affecting=True, write=True)
        if reason:
            stopped = {"service": row["service"], "reason": reason}
            break
        try:
            receipt = restore(row["service"], dict(NOOP), row["commit"], row["image_digest"])
        except Exception as error:  # noqa: BLE001
            detail = str(error) if type(error).__name__ == "VerificationError" else type(error).__name__
            stopped = {"service": row["service"], "reason": detail}
            break
        done.append({"service": row["service"], "previous_deployment": row["live_deployment"],
                     "source_deployment": receipt["source_deployment"], "deployment": receipt["deployment"],
                     "image_digest": receipt["image_digest"], "observed_at": receipt["observed_at"]})
    return done, stopped


def run(out_dir, *, apply=False, expected_sha256=""):
    import collector_variables as cv
    import generate_staging_state as state

    state.staging_environment()
    pins = fleet_pins(cv.delivery.NAMES)
    live = cv.delivery.inspect()
    rows = plan(live, pins, lambda node, commit: pinned_source(
        node, commit, read=cv.delivery.read_deployment, listing=cv.recent_deployments,
        error=state.VerificationError))
    sha = plan_sha(rows)
    missing = [r["service"] for r in rows if not r["source_deployment"]]
    out = {"observed_at": state.timestamp(), "apply": bool(apply), "plan_sha256": sha,
           "pins_from": FLEET, "plan": rows}
    summary = {"plan_sha256": sha, "collectors": len(rows), "apply": bool(apply),
               "no_source": missing,
               "plan": [{k: r.get(k) for k in ("service", "commit", "image_digest", "live_deployment",
                                               "live_status", "source_deployment", "problem")
                         if r.get(k) is not None}
                        for r in rows]}
    if missing:
        summary["ok"] = False
        common.write_json(Path(out_dir) / "collector-redeploy.json", out)
        return summary
    if not apply:
        summary["ok"] = True
        common.write_json(Path(out_dir) / "collector-redeploy.json", out)
        return summary
    check_apply(apply, expected_sha256, sha)
    done, stopped = apply_rows(rows, cv.restore)
    out.update(redeployed=done, stopped=stopped, production_accessed=False, source_jobs_triggered=0)
    common.write_json(Path(out_dir) / "collector-redeploy.json", out)
    summary.pop("plan")
    summary.update(ok=stopped is None and len(done) == len(rows), redeployed=done, stopped=stopped)
    return summary
