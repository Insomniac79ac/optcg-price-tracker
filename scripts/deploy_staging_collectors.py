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
    live = inspect()
    before = {}
    for row in requested:
        service = live.get(row["name"], {})
        if (
            service.get("serviceId") != row["service_id"]
            or "--due-work" not in (service.get("startCommand") or "")
            or not service.get("cronSchedule")
        ):
            raise state.VerificationError(
                "Collector identity/scheduled due-work configuration changed"
            )
        before[row["name"]] = {
            "service_id": row["service_id"],
            "start_command": service["startCommand"],
            "schedule_utc": service["cronSchedule"],
            "deployment_id": service["latestDeployment"]["id"],
        }
    # This build-only module is copied into the installed shared package. It
    # identifies actual uploaded source without trusting a stale runtime env var.
    marker = state.ROOT / "services/api/app/services/collector_build.py"
    if marker.exists():
        raise state.VerificationError("Unreviewed build revision marker exists")
    marker.write_text("REVISION = " + repr(args.expected) + "\n")
    started = state.timestamp()
    try:
        for row in requested:
            upload(row, args.expected)
        deadline = time.monotonic() + 1800
        pending = {row["name"] for row in requested}
        retried = {}
        forced = {}
        tracked = {}
        deployed = {}
        while pending:
            current = inspect()
            for name in list(pending):
                service = current[name]
                if name in tracked:
                    deployment = read_deployment(
                        tracked[name], service["serviceId"], args.expected
                    )
                elif (
                    service["serviceId"],
                    service["startCommand"],
                    service["cronSchedule"],
                ) != (
                    before[name]["service_id"],
                    before[name]["start_command"],
                    before[name]["schedule_utc"],
                ):
                    raise state.VerificationError(
                        "Collector configuration changed during rollout"
                    )
                deployment = service.get("latestDeployment") or {}
                meta = deployment.get("meta") or {}
                if isinstance(meta, str):
                    meta = json.loads(meta)
                if (
                    meta.get("cliMessage")
                    != "Structured RAW health exact commit " + args.expected
                ):
                    candidate = latest_uploaded(
                        next(r for r in requested if r["name"] == name), args.expected
                    )
                    if candidate is None:
                        continue
                    deployment = candidate
                if deployment["status"] == "SKIPPED":
                    if (
                        name in forced
                        or deployment["meta"].get("skippedReason")
                        != "No changes to watched files"
                    ):
                        raise state.VerificationError(
                            "Unrecognized/repeated skipped collector deployment: "
                            + name
                        )
                    forced[name] = deployment["id"]
                    child = redeploy_uploaded(
                        next(r for r in requested if r["name"] == name),
                        deployment,
                        args.expected,
                    )
                    tracked[name] = child["id"]
                    continue
                if deployment.get("id") == retried.get(name):
                    continue  # allow provider metadata propagation after a retry
                if deployment["status"] == "FAILED" and name not in retried:
                    retried[name] = deployment["id"]
                    child = redeploy_uploaded(
                        next(r for r in requested if r["name"] == name),
                        deployment,
                        args.expected,
                    )
                    tracked[name] = child["id"]
                    continue
                if deployment["status"] in {"FAILED", "CRASHED"}:
                    raise state.VerificationError(
                        "Collector deployment failed: " + name
                    )
                if deployment["status"] == "SUCCESS":
                    deployed[name] = {
                        "service_id": service["serviceId"],
                        "deployment_id": deployment["id"],
                        "source_sha": args.expected,
                        "schedule_utc": service["cronSchedule"],
                    }
                    pending.remove(name)
            if pending:
                if time.monotonic() > deadline:
                    raise state.VerificationError(
                        "Bounded collector deployment wait expired"
                    )
                time.sleep(15)
    finally:
        marker.unlink(missing_ok=True)
    receipt = {
        "schema_version": 1,
        "target": "staging",
        "started_at": started,
        "completed_at": state.timestamp(),
        "source_sha": args.expected,
        "before": {
            name: {
                "service_id": row["service_id"],
                "deployment_id": row["deployment_id"],
                "schedule_utc": row["schedule_utc"],
                "start_command_sha256": hashlib.sha256(
                    row["start_command"].encode()
                ).hexdigest(),
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
