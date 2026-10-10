#!/usr/bin/env python3
"""Explicit mission-scoped collector rollout inside the staging delivery lease.

No service/config creation, migration, Run Now, source calls or production override.
Only existing destination-pinned services may receive the exact merged checkout.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import generate_staging_state as state
from datetime import datetime, timezone

# The complete IDs are supplied by the pinned live baseline in the reviewed
# mission manifest, then checked against live name/id/destination before upload.
NAMES = {
    "snkrdunk-collector",
    *(f"yuyutei-collector-shard-{i}" for i in range(9) if i != 4),
    "yuyutei-collector-shard-4-v2",
}


def selection(manifest):
    requested = manifest.get("deployment_verification", {}).get(
        "collector_services", []
    )
    if not requested:
        return []
    if manifest.get("target") != "staging" or manifest.get("classification") != "AMBER":
        raise state.VerificationError(
            "Collector rollout requires reviewed staging AMBER preflight"
        )
    if (
        not isinstance(requested, list)
        or len(requested) > 10
        or len({r["name"] for r in requested}) != len(requested)
    ):
        raise state.VerificationError("Invalid bounded collector manifest")
    for row in requested:
        if (
            set(row) != {"name", "service_id", "recovery_deployment_id"}
            or row["name"] not in NAMES
            or not re.fullmatch("[0-9a-f-]{36}", row["service_id"])
        ):
            raise state.VerificationError("Unapproved collector destination")
    return requested


def inspect():
    data = state.staging_environment()
    return {
        edge["node"]["serviceName"]: edge["node"]
        for edge in data["serviceInstances"]["edges"]
    }


def upload(row, expected):
    branch = state.command_json(
        ["gh", "api", f"repos/{state.REPOSITORY}/branches/staging"]
    )
    if branch["commit"]["sha"] != expected:
        raise state.VerificationError("Obsolete collector delivery; no upload allowed")
    command = [
        "railway",
        "up",
        "--project",
        state.PROJECT,
        "--environment",
        state.ENVIRONMENT,
        "--service",
        row["service_id"],
        "--detach",
        "--message",
        "Structured RAW health exact commit " + expected,
    ]
    result = subprocess.run(
        command, cwd=state.ROOT, capture_output=True, text=True, timeout=120
    )
    if result.returncode:
        raise state.VerificationError("Staging collector upload failed: " + row["name"])


def read_deployment(deployment_id, service_id, expected):
    if not re.fullmatch("[0-9a-f-]{36}", deployment_id):
        raise state.VerificationError("Invalid deployment identity")
    row = state.railway(
        f'query {{ deployment(id:"{deployment_id}") {{ id projectId environmentId serviceId status canRedeploy meta }} }}'
    )["deployment"]
    meta = row.get("meta") or {}
    meta = json.loads(meta) if isinstance(meta, str) else meta
    if (row.get("projectId"), row.get("environmentId"), row.get("serviceId")) != (
        state.PROJECT,
        state.ENVIRONMENT,
        service_id,
    ) or meta.get("cliMessage") != "Structured RAW health exact commit " + expected:
        raise state.VerificationError("Uploaded deployment destination/source mismatch")
    row["meta"] = meta
    return row


def latest_uploaded(row, expected):
    rows = state.command_json(
        [
            "railway",
            "deployment",
            "list",
            "--project",
            state.PROJECT,
            "--environment",
            state.ENVIRONMENT,
            "--service",
            row["service_id"],
            "--limit",
            "3",
            "--json",
        ]
    )
    for item in rows:
        meta = item.get("meta") or {}
        meta = json.loads(meta) if isinstance(meta, str) else meta
        if meta.get("cliMessage") == "Structured RAW health exact commit " + expected:
            return read_deployment(item["id"], row["service_id"], expected)
    return None


def redeploy_uploaded(row, source, expected):
    # No watch-path/configuration change and no Run Now: rebuild this exact upload.
    checked = read_deployment(source["id"], row["service_id"], expected)
    if not checked.get("canRedeploy"):
        raise state.VerificationError("Uploaded staging snapshot cannot be redeployed")
    current = state.command_json(
        ["gh", "api", f"repos/{state.REPOSITORY}/branches/staging"]
    )
    if current["commit"]["sha"] != expected:
        raise state.VerificationError(
            "Obsolete collector delivery; no redeploy allowed"
        )
    result = state.railway(
        f'mutation {{ deploymentRedeploy(id:"{checked["id"]}",usePreviousImageTag:false) {{ id projectId environmentId serviceId status meta }} }}'
    )["deploymentRedeploy"]
    # The clone must preserve both destination and the uploaded source marker.
    return read_deployment(result["id"], row["service_id"], expected)


def rollout_deployment(service, before, tracked, expected):
    # Check configuration even when following a redeploy child. The provider's
    # latestDeployment may still point at its skipped/failed parent.
    if (service.get("serviceId"), service.get("startCommand"), service.get("cronSchedule")) != (
        before["service_id"], before["start_command"], before["schedule_utc"]
    ):
        raise state.VerificationError("Collector configuration changed during rollout")
    if tracked:
        return read_deployment(tracked, service["serviceId"], expected)
    return service.get("latestDeployment") or {}


def build_markers(requested):
    # Watch patterns cover each collector package, not the shared API package.
    # Change a build-only file in each selected package as well as the installed
    # shared runtime marker; never mutate service watch configuration.
    markers = [state.ROOT / "services/api/app/services/collector_build.py"]
    for package in sorted({"snkrdunk_collector" if r["name"] == "snkrdunk-collector" else "yuyutei_collector" for r in requested}):
        markers.append(state.ROOT / "services" / package / package / "_delivery_revision.py")
    return markers


MARKER = "Structured RAW health exact commit "
# A collector is changed only between its own cron turns: at least this long
# after a scheduled fire (turns finish in ~3-4 min; startup precedes any claim)
# and before the next one (so the new image is active before it fires), and
# never while one of its attempts is open.
SLOT_AFTER_FIRE_MINUTES = 5
SLOT_BEFORE_FIRE_MINUTES = 8
SLOT_WAIT_SECONDS = 1500
ROLLOUT_WAIT_SECONDS = 900
# Collector releases avoid the 02:00-06:00 UTC daily busy window. A forward
# rollout (bounded by the 180-minute delivery job) may start only when it would
# finish before the window. Rollback is never held back by this.
FORWARD_START_HOURS_UTC = range(6, 23)


def outside_busy_window(now=None):
    now = now or datetime.now(timezone.utc)
    if now.hour not in FORWARD_START_HOURS_UTC:
        raise state.VerificationError(
            "Collector release refused: could overlap the 02:00-06:00 UTC busy window"
        )


def claim_prefix(name):
    if name == "snkrdunk-collector":
        return "snkrdunk-due"
    match = re.fullmatch(r"yuyutei-collector-shard-(\d)(?:-v2)?", name)
    if not match:
        raise state.VerificationError("Unapproved collector destination")
    return "yuyutei-due-" + match.group(1)


def cron_minutes(schedule):
    match = re.fullmatch(r"(\d{1,2}(?:,\d{1,2})*) \* \* \* \*", schedule or "")
    if not match or any(int(m) > 59 for m in match.group(1).split(",")):
        raise state.VerificationError("Unrecognised collector schedule; no safe slot")
    return sorted(int(m) for m in match.group(1).split(","))


def slot_gaps(minutes, now):
    """(minutes since the last scheduled fire, minutes until the next one)."""
    t = now.minute + now.second / 60
    return min((t - m) % 60 for m in minutes), min((m - t) % 60 for m in minutes)


def open_attempts(prefix):
    import psycopg

    proxies = state.railway(
        f'query {{ tcpProxies(environmentId:"{state.ENVIRONMENT}", serviceId:"{state.POSTGRES}") {{ domain proxyPort applicationPort }} }}'
    )["tcpProxies"]
    if len(proxies) != 1 or proxies[0]["applicationPort"] != 5432:
        raise state.VerificationError("Staging database endpoint is ambiguous")
    variables = state.command_json(
        ["railway", "variable", "list", "-p", state.PROJECT, "-e", state.ENVIRONMENT,
         "-s", state.POSTGRES, "--json"]
    )
    try:
        with psycopg.connect(
            host=proxies[0]["domain"], port=proxies[0]["proxyPort"],
            user=variables["PGUSER"], password=variables["PGPASSWORD"],
            dbname=variables["PGDATABASE"], connect_timeout=15,
            options="-c default_transaction_read_only=on -c statement_timeout=30000",
        ) as connection:
            return connection.execute(
                "SELECT count(*) FROM freshness_attempts "
                "WHERE finished_at IS NULL AND claimed_by LIKE %s",
                (prefix + ":%",),
            ).fetchone()[0]
    except Exception:
        raise state.VerificationError("Open-attempt check failed; no safe slot") from None
    finally:
        variables.clear()


def wait_for_slot(name, schedule, *, now=None, attempts=None, clock=None, sleep=None):
    now = now or (lambda: datetime.now(timezone.utc))
    attempts = attempts or open_attempts
    clock, sleep = clock or time.monotonic, sleep or time.sleep
    minutes = cron_minutes(schedule)
    deadline = clock() + SLOT_WAIT_SECONDS
    while True:
        since, until = slot_gaps(minutes, now())
        if (
            since >= SLOT_AFTER_FIRE_MINUTES
            and until >= SLOT_BEFORE_FIRE_MINUTES
            and attempts(claim_prefix(name)) == 0
        ):
            return
        if clock() > deadline:
            raise state.VerificationError("No safe rollout slot for " + name)
        sleep(20)


def marker_commit(deployment):
    meta = deployment.get("meta") or {}
    meta = json.loads(meta) if isinstance(meta, str) else meta
    message = meta.get("cliMessage") or ""
    commit = message[len(MARKER):] if message.startswith(MARKER) else ""
    if not re.fullmatch("[0-9a-f]{40}", commit):
        raise state.VerificationError("Active collector is not a verified exact-commit upload")
    return commit


def await_rollout(row, before, expected, *, clock=None, sleep=None):
    """Follow one collector's upload to SUCCESS (one bounded build retry, one
    watched-snapshot redeploy), exactly as the parallel loop did per service."""
    name = row["name"]
    clock, sleep = clock or time.monotonic, sleep or time.sleep
    deadline = clock() + ROLLOUT_WAIT_SECONDS
    retried = forced = tracked = None
    while True:
        service = inspect()[name]
        deployment = rollout_deployment(service, before, tracked, expected)
        meta = deployment.get("meta") or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        if meta.get("cliMessage") != MARKER + expected:
            deployment = latest_uploaded(row, expected)
            meta = (deployment or {}).get("meta") or {}
        if deployment is None or deployment.get("id") == retried:
            pass  # upload not visible yet, or provider metadata after a retry
        elif deployment["status"] == "SKIPPED":
            if forced or meta.get("skippedReason") != "No changes to watched files":
                raise state.VerificationError(
                    "Unrecognized/repeated skipped collector deployment: " + name
                )
            forced = deployment["id"]
            tracked = redeploy_uploaded(row, deployment, expected)["id"]
        elif deployment["status"] == "FAILED" and not retried:
            retried = deployment["id"]
            tracked = redeploy_uploaded(row, deployment, expected)["id"]
        elif deployment["status"] in {"FAILED", "CRASHED"}:
            raise state.VerificationError("Collector deployment failed: " + name)
        elif deployment["status"] == "SUCCESS":
            return deployment, retried, forced
        if clock() > deadline:
            raise state.VerificationError("Bounded collector deployment wait expired: " + name)
        sleep(15)


def verify_released(row, before, deployment, expected):
    """After each collector: exact marker and SUCCESS, unchanged schedule,
    start command and writer flags. The image is new by design."""
    import collector_variables as cv

    service = inspect()[row["name"]]
    checked = read_deployment(deployment["id"], row["service_id"], expected)
    if checked.get("status") != "SUCCESS":
        raise state.VerificationError("Released collector is not SUCCESS: " + row["name"])
    if (service.get("cronSchedule"), service.get("startCommand")) != (
        before["schedule_utc"], before["start_command"]
    ):
        raise state.VerificationError("Collector configuration changed during rollout")
    if cv.read_variables(row["service_id"]) != before["variables"]:
        raise state.VerificationError("Collector writer flags changed during rollout")
    return cv.digest(checked)


def roll_back(released, before, *, slot=None):
    """All-or-nothing: put every collector touched so far back on its original
    verified image, newest first, verifying each (collector_variables.restore)."""
    import collector_variables as cv

    slot = slot or wait_for_slot
    results = {}
    for name in reversed(released):
        row = before[name]
        values = {k: v for k, v in row["variables"].items() if v is not None}
        try:
            slot(name, row["schedule_utc"])
            results[name] = {"ok": True, **cv.restore(name, values, row["commit"], row["digest"])}
        except Exception as error:  # keep restoring the rest; report loudly
            results[name] = {"ok": False, "error": str(error)[:300]}
    return results


def capture_before(row, service):
    """Pre-change state, and a proven rollback before any collector is changed:
    its active verified upload and a redeployable copy of that exact image."""
    import collector_variables as cv

    latest = service.get("latestDeployment") or {}
    if (
        service.get("serviceId") != row["service_id"]
        or "--due-work" not in (service.get("startCommand") or "")
        or not service.get("cronSchedule")
        or latest.get("status") != "SUCCESS"
    ):
        raise state.VerificationError(
            "Collector identity/scheduled due-work configuration changed"
        )
    cron_minutes(service["cronSchedule"])
    commit = marker_commit(latest)
    image = cv.digest(read_deployment(latest["id"], row["service_id"], commit))
    cv.original_source(service, commit, image)
    return {
        "service_id": row["service_id"],
        "start_command": service["startCommand"],
        "schedule_utc": service["cronSchedule"],
        "deployment_id": latest["id"],
        "commit": commit,
        "digest": image,
        "variables": cv.read_variables(row["service_id"]),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    requested = selection(json.loads(args.manifest.read_text()))
    if not requested:
        return 0
    if not re.fullmatch("[0-9a-f]{40}", args.expected):
        raise state.VerificationError("Full merged SHA required")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    branch = state.command_json(
        ["gh", "api", f"repos/{state.REPOSITORY}/branches/staging"]
    )
    if head != args.expected or branch["commit"]["sha"] != args.expected:
        raise state.VerificationError(
            "Collector upload checkout is not current merged staging"
        )
    outside_busy_window()
    live = inspect()
    before = {row["name"]: capture_before(row, live.get(row["name"], {})) for row in requested}
    # This build-only module is copied into the installed shared package. It
    # identifies actual uploaded source without trusting a stale runtime env var.
    markers = build_markers(requested)
    if any(marker.exists() for marker in markers):
        raise state.VerificationError("Unreviewed build revision marker exists")
    started = state.timestamp()
    released, deployed, retried, forced = [], {}, {}, {}
    try:
        for marker in markers:
            marker.write_text("REVISION = " + repr(args.expected) + "\n")
        # One collector at a time: each is uploaded only in its own safe slot
        # and fully verified before the next is touched.
        for row in requested:
            name = row["name"]
            wait_for_slot(name, before[name]["schedule_utc"])
            released.append(name)  # before upload: a partial upload is rolled back too
            upload(row, args.expected)
            deployment, retry, force = await_rollout(row, before[name], args.expected)
            if retry:
                retried[name] = retry
            if force:
                forced[name] = force
            deployed[name] = {
                "service_id": row["service_id"],
                "deployment_id": deployment["id"],
                "source_sha": args.expected,
                "schedule_utc": before[name]["schedule_utc"],
                "image_digest": verify_released(row, before[name], deployment, args.expected),
                "verified_at": state.timestamp(),
            }
    except Exception as error:
        rollback = roll_back(released, before)
        print(json.dumps({"rollout_failed": str(error)[:300], "rollback": rollback},
                         indent=2, default=str))
        complete = all(r["ok"] for r in rollback.values())
        raise state.VerificationError(
            "Collector rollout failed at "
            + (released[-1] if released else "preflight")
            + ("; every released collector restored to its original image"
               if complete else "; ROLLBACK INCOMPLETE")
        ) from None
    finally:
        for marker in markers:
            marker.unlink(missing_ok=True)
    receipt = {
        "schema_version": 2,
        "target": "staging",
        "started_at": started,
        "completed_at": state.timestamp(),
        "source_sha": args.expected,
        "sequential": True,
        "before": {
            name: {
                "service_id": row["service_id"],
                "deployment_id": row["deployment_id"],
                "schedule_utc": row["schedule_utc"],
                "start_command_sha256": hashlib.sha256(
                    row["start_command"].encode()
                ).hexdigest(),
                "commit": row["commit"],
                "image_digest": row["digest"],
                "variables": row["variables"],
            }
            for name, row in before.items()
        },
        "deployments": deployed,
        "bounded_build_retries": retried,
        "watched_snapshot_redeploys": forced,
        "natural_runs_not_yet_verified": True,
        "production_accessed": False,
    }
    state.atomic_write(args.output, json.dumps(receipt, indent=2) + "\n")
    print(
        "Destination-pinned staging collector rollout complete; natural evidence still required"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except state.VerificationError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        raise SystemExit(
            "Staging collector rollout failed ("
            + type(error).__name__
            + "); no success receipt written"
        ) from None
