"""collector-sibling-on / collector-sibling-off: set RAW_DICTIONARY_SIBLING on every staging
collector and make it take effect (owner-gated; owner decision 2026-10-24, perfectionist).

A collector reads its variables only on a new deployment, and Railway no longer redeploys
their images (2026-10-22), so each collector is re-uploaded on its fleet-pinned commit:

For each of the 10 collectors, in name order, in its own safe slot (between cron turns, no
open attempt): the active deployment must be a SUCCESS exact-commit upload of its fleet pin
(docs/agent/STAGING_FLEET.json). Stage RAW_DICTIONARY_SIBLING=<value> with --skip-deploys and
prove no deployment started; re-upload the pinned commit from a detached worktree with the
release build markers plus a one-off nonce (so Railway does not skip it as unchanged; the
runtime REVISION stays the commit); follow it to SUCCESS; check it is the active deployment
with the exact marker, unchanged schedule and start command, and the writer flags as before
except RAW_DICTIONARY_SIBLING = <value>. A collector already at <value> is left alone.

Stops at the first failure and puts that collector back (previous value staged, re-upload),
reporting the result. Stops before the 02:00 UTC collector quiet window. Dry run (default):
the plan and its SHA-256 over service, commit, live deployment, current and target value.
No source request, no database write.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from ops import common
from ops.collector_redeploy import check_apply, fleet_pins

KEY = "RAW_DICTIONARY_SIBLING"


def plan_sha(rows):
    pinned = [[r["service"], r["commit"], r["live_deployment"], r["current"], r["target"]] for r in rows]
    return hashlib.sha256(json.dumps(pinned, separators=(",", ":")).encode()).hexdigest()


def plan(live, pins, value, *, marker_commit, variables):
    rows = []
    for name, commit in sorted(pins.items()):
        node = live.get(name)
        if node is None:
            raise common.Refused(f"{name}: service not found")
        latest = node.get("latestDeployment") or {}
        if latest.get("status") != "SUCCESS":
            raise common.Refused(f"{name}: active deployment is not SUCCESS")
        active = marker_commit(latest)
        if active != commit:
            raise common.Refused(f"{name}: runs {active[:7]}, not its fleet pin {commit[:7]}")
        current = variables(node["serviceId"])
        rows.append({"service": name, "service_id": node["serviceId"], "commit": commit,
                     "live_deployment": latest["id"], "schedule": node.get("cronSchedule"),
                     "start_command": node.get("startCommand"), "variables": current,
                     "current": current.get(KEY), "target": value,
                     "action": "none" if current.get(KEY) == value else "set-and-reupload"})
    return rows


def switch(row, value, *, inspect, stage, reupload, verify, slot, nonce):
    """Stage the value, re-upload the pinned commit, verify. Returns the new deployment id."""
    name = row["service"]
    slot(name, row["schedule"])
    node = inspect()[name]
    latest = (node.get("latestDeployment") or {}).get("id")
    stage(node, {KEY: value})
    if (inspect()[name].get("latestDeployment") or {}).get("id") != latest:
        raise common.Refused(f"{name}: a deployment started while staging the variable")
    expected = dict(row["variables"], **{KEY: value})
    before = {"commit": row["commit"], "service_id": row["service_id"], "deployment_id": latest,
              "schedule_utc": row["schedule"], "start_command": row["start_command"],
              "variables": expected}
    deployment = reupload(name, before, nonce=nonce)
    if deployment["id"] == latest:
        # A skipped upload would leave the old deployment, which never read the new value.
        raise common.Refused(f"{name}: the re-upload was skipped; the new value is not live")
    checked = verify(name, before, deployment)
    return checked["deployment"]


def apply_rows(rows, value, *, inspect, stage, reupload, verify, slot, now=common.now_utc, stamp=None):
    done, stopped = [], None
    stamp = stamp or (lambda: datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    for row in rows:
        if row["action"] == "none":
            done.append({"service": row["service"], "deployment": row["live_deployment"], "changed": False})
            continue
        reason = common.quiet_window_refusal(now(), collector_affecting=True, write=True)
        if reason:
            stopped = {"service": row["service"], "reason": reason}
            break
        kwargs = dict(inspect=inspect, stage=stage, reupload=reupload, verify=verify, slot=slot)
        try:
            deployment = switch(row, value, nonce=f"{KEY}={value}@{stamp()}", **kwargs)
            done.append({"service": row["service"], "deployment": deployment, "changed": True})
        except Exception as error:  # noqa: BLE001
            detail = str(error) if type(error).__name__ in ("VerificationError", "Refused") else type(error).__name__
            stopped = {"service": row["service"], "reason": detail}
            previous = row["current"] if row["current"] is not None else "false"
            try:
                back = switch(dict(row, variables=dict(row["variables"])), previous,
                              nonce=f"{KEY}={previous}@{stamp()}-revert", **kwargs)
                stopped["reverted"] = {"value": previous, "deployment": back}
            except Exception as revert_error:  # noqa: BLE001
                stopped["revert_failed"] = (str(revert_error) if type(revert_error).__name__ in
                                            ("VerificationError", "Refused") else type(revert_error).__name__)
            break
    return done, stopped


def run(out_dir, *, value, apply=False, expected_sha256=""):
    import collector_variables as cv
    import deploy_staging_collectors as delivery
    import generate_staging_state as state

    state.staging_environment()
    pins = fleet_pins(cv.delivery.NAMES)
    live = cv.delivery.inspect()
    rows = plan(live, pins, value, marker_commit=delivery.marker_commit, variables=cv.read_variables)
    sha = plan_sha(rows)
    summary = {"key": KEY, "target": value, "plan_sha256": sha, "apply": bool(apply),
               "plan": [{k: r[k] for k in ("service", "commit", "live_deployment", "current", "action")}
                        for r in rows]}
    out = {"observed_at": state.timestamp(), **summary}
    if not apply:
        summary["ok"] = True
        common.write_json(Path(out_dir) / "collector-flag.json", out)
        return summary
    check_apply(apply, expected_sha256, sha)
    done, stopped = apply_rows(rows, value, inspect=cv.delivery.inspect, stage=cv.stage,
                               reupload=delivery.reupload, verify=delivery.verify_reupload,
                               slot=delivery.wait_for_slot)
    out.update(done=done, stopped=stopped, source_requests=0, database_writes=0)
    common.write_json(Path(out_dir) / "collector-flag.json", out)
    summary.pop("plan")
    summary.update(ok=stopped is None and len(done) == len(rows), done=done, stopped=stopped)
    return summary
