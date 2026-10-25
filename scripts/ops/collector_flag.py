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
except RAW_DICTIONARY_SIBLING = <value>. Every collector is re-uploaded, even one whose variable
already reads <value> (a staged value says nothing about what the running deployment read), so a
re-run is safe and completes a partial run.

Stops at the first failure; if that collector's value was already staged it is put back (previous
value staged, re-upload). A collector starts only with enough job time and enough time before the
next quiet window (02:00 or 19:30 UTC) for itself plus a revert. Dry run (default):
the plan and its SHA-256 over service, commit, live deployment, current and target value.
No source request, no database write.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import time

from ops import common
from ops.collector_redeploy import check_apply, fleet_pins

KEY = "RAW_DICTIONARY_SIBLING"


def plan_sha(rows):
    pinned = [[r["service"], r["commit"], r["live_deployment"], r["current"], r["target"]] for r in rows]
    return hashlib.sha256(json.dumps(pinned, separators=(",", ":")).encode()).hexdigest()


# One collector can take a full slot wait plus a rollout wait, twice with a revert.
COLLECTOR_BUDGET_SECONDS = 2 * (1500 + 900)
# The runbook job's own timeout (ops-write.yml) less a margin for setup and reporting.
JOB_BUDGET_SECONDS = 340 * 60


def plan(live, pins, value, *, marker_commit, variables):
    """Every collector is re-uploaded, even one whose variable already reads the target:
    a staged value says nothing about what its running deployment read."""
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
                     "current": current.get(KEY), "target": value})
    return rows


def switch(row, value, *, inspect, stage, reupload, verify, slot, nonce, progress, expected_latest=None):
    """Stage the value, re-upload the pinned commit, verify. Records how far it got in
    `progress` (staged, uploaded). Returns the new deployment id."""
    name = row["service"]
    slot(name, row["schedule"])
    node = inspect()[name]
    latest = (node.get("latestDeployment") or {}).get("id")
    if expected_latest is not None and latest != expected_latest:
        raise common.Refused(f"{name}: deployed since the dry run ({latest}); dry run again")
    stage(node, {KEY: value})
    progress["staged"] = True
    if (inspect()[name].get("latestDeployment") or {}).get("id") != latest:
        raise common.Refused(f"{name}: a deployment started while staging the variable")
    expected = dict(row["variables"], **{KEY: value})
    before = {"commit": row["commit"], "service_id": row["service_id"], "deployment_id": latest,
              "schedule_utc": row["schedule"], "start_command": row["start_command"],
              "variables": expected}
    deployment = reupload(name, before, nonce=nonce)
    progress["uploaded"] = True
    if deployment["id"] == latest:
        # A skipped upload would leave the old deployment, which never read the new value.
        raise common.Refused(f"{name}: the re-upload was skipped; the new value is not live")
    checked = verify(name, before, deployment)
    return checked["deployment"]


def seconds_to_next_quiet(now):
    """Seconds until the next collector (02:00) or write (19:30) quiet window starts."""
    starts = []
    for quiet in (common.COLLECTOR_QUIET[0], common.WRITE_QUIET[0]):
        start = now.replace(hour=quiet.hour, minute=quiet.minute, second=0, microsecond=0)
        if start <= now:
            start = start + timedelta(days=1)
        starts.append((start - now).total_seconds())
    return min(starts)


def apply_rows(rows, value, *, inspect, stage, reupload, verify, slot, now=common.now_utc, stamp=None,
               clock=time.monotonic, job_budget=JOB_BUDGET_SECONDS):
    done, stopped = [], None
    stamp = stamp or (lambda: datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    deadline = clock() + job_budget
    kwargs = dict(inspect=inspect, stage=stage, reupload=reupload, verify=verify, slot=slot)
    for row in rows:
        reason = common.quiet_window_refusal(now(), collector_affecting=True, write=True)
        if not reason and seconds_to_next_quiet(now()) < COLLECTOR_BUDGET_SECONDS:
            reason = "not enough time before the next quiet window for one collector and a revert"
        if not reason and deadline - clock() < COLLECTOR_BUDGET_SECONDS:
            reason = "not enough job time left for one collector and a revert"
        if reason:
            stopped = {"service": row["service"], "reason": reason, "untouched": True}
            break
        progress = {"staged": False, "uploaded": False}
        try:
            deployment = switch(row, value, nonce=f"{KEY}={value}@{stamp()}", progress=progress,
                                expected_latest=row["live_deployment"], **kwargs)
            done.append({"service": row["service"], "deployment": deployment, "was": row["current"]})
        except Exception as error:  # noqa: BLE001
            detail = str(error) if type(error).__name__ in ("VerificationError", "Refused") else type(error).__name__
            stopped = {"service": row["service"], "reason": detail, "progress": dict(progress)}
            if not progress["staged"]:
                stopped["untouched"] = True  # nothing changed on this collector; nothing to revert
                break
            previous = row["current"] if row["current"] is not None else "false"
            try:
                back = switch(row, previous, nonce=f"{KEY}={previous}@{stamp()}-revert", progress={},
                              **kwargs)
                stopped["reverted"] = {"value": previous, "was_unset": row["current"] is None,
                                       "deployment": back}
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
               "plan": [{k: r[k] for k in ("service", "commit", "live_deployment", "current")}
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
