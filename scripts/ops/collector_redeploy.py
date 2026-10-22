"""collector-redeploy: put every staging collector back on its own verified image (owner-gated).

A Railway service picks up changed shared variables only on a new deployment; a restart or a
cron run keeps the values of the deployment it runs (2026-10-22: the Postgres password was
rotated after Railway's security incident and every collector kept the old one). Railway's
dashboard offers only "Deploy latest commit" on a collector, which builds from the branch and
loses the verified upload. This runbook makes the new deployment without a build:

For each of the 10 collectors, in name order, the newest committed rollout receipt that deployed
it (fleet.DEFAULT_RECEIPTS) gives the exact commit and image digest. collector_variables.restore
stages APP_ENV=staging with --skip-deploys (a value every collector already carries, so nothing
changes), redeploys the newest redeployable deployment that carries that exact-commit marker and
the byte-identical image, waits for SUCCESS, and checks digest, cron schedule, start command and
the read-back. No branch build, no code change, no source job. Stops at the first failure.

Dry run (default): per collector, the receipt commit and digest, the live deployment and the
source deployment a redeploy would use. The plan SHA-256 covers service, commit, digest and the
live deployment id, so any deployment between the dry run and the apply refuses the apply.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ops import common, fleet

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


def plan(live, receipts, names, source_for):
    """One row per collector: receipt commit and digest, live deployment, redeploy source."""
    rows = []
    for name in sorted(names):
        node = live.get(name)
        owner = fleet.receipt_for(name, receipts)
        if node is None or owner is None:
            raise common.Refused(f"{name}: " + ("service not found" if node is None else "in no receipt"))
        data = owner[1]
        row = data["deployments"][name]
        commit = row.get("source_sha") or data["source_sha"]
        digest = row.get("image_digest") or row.get("digest")
        latest = node.get("latestDeployment") or {}
        out = {"service": name, "commit": commit, "image_digest": digest,
               "live_deployment": latest.get("id"), "live_status": latest.get("status"),
               "schedule": node.get("cronSchedule")}
        try:
            out["source_deployment"] = source_for(node, commit, digest)["id"]
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
    receipts = fleet.load_receipts(None)
    live = cv.delivery.inspect()
    rows = plan(live, receipts, cv.delivery.NAMES, cv.original_source)
    sha = plan_sha(rows)
    missing = [r["service"] for r in rows if not r["source_deployment"]]
    out = {"observed_at": state.timestamp(), "apply": bool(apply), "plan_sha256": sha,
           "receipts": [str(p.relative_to(common.ROOT)) for p, _ in receipts], "plan": rows}
    summary = {"plan_sha256": sha, "collectors": len(rows), "apply": bool(apply),
               "no_source": missing,
               "plan": [{k: r.get(k) for k in ("service", "commit", "live_deployment", "live_status",
                                               "source_deployment", "problem") if r.get(k) is not None}
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
