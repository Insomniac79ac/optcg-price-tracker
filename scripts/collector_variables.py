#!/usr/bin/env python3
"""The only supported way to change a staging collector variable.

A plain `railway variable set` on a GitHub-connected collector triggers a
rebuild from the branch head, replacing the verified `railway up` upload and
losing its exact-commit marker (observed 2026-10-08, snkrdunk-collector
deployments 0da9274b and 518080ff). This tool instead:

1. requires the service's active deployment to be a verified upload of the
   expected commit (destination and exact-commit marker checked);
2. stages the change with `--skip-deploys` and proves no deployment started;
3. redeploys that same verified upload (deploymentRedeploy), so the new
   deployment carries the same marker and picks up the staged variables;
4. waits for SUCCESS, re-checks schedule/start command, and reads the
   variables back.

Only the RAW storage writer keys and APP_ENV=staging may be changed. Cron,
budget, pacing, claim and source settings are refused. No source job is run.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

import deploy_staging_collectors as delivery
import generate_staging_state as state

ALLOWED = {
    "RAW_DICTIONARY_STORAGE_ENABLED": {"true", "false"},
    "RAW_DICTIONARY_STORAGE_MODE": {"canary", "daily-v1"},
    "APP_ENV": {"staging"},
}
MARKER = "Structured RAW health exact commit "


def parse_assignments(items):
    assignments = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or key not in ALLOWED or value not in ALLOWED[key]:
            raise state.VerificationError(f"Collector variable change refused: {item}")
        if key in assignments:
            raise state.VerificationError(f"Duplicate collector variable: {key}")
        assignments[key] = value
    if not assignments:
        raise state.VerificationError("No collector variable change requested")
    return assignments


def service_node(name, inspect=delivery.inspect):
    if name not in delivery.NAMES:
        raise state.VerificationError("Not a staging collector: " + name)
    node = inspect().get(name)
    if not node or not re.fullmatch("[0-9a-f-]{36}", node.get("serviceId") or ""):
        raise state.VerificationError("Collector destination not found: " + name)
    return node


def digest(deployment):
    value = (deployment.get("meta") or {}).get("imageDigest")
    if not re.fullmatch("sha256:[0-9a-f]{64}", value or ""):
        raise state.VerificationError("Deployment has no image digest")
    return value


def recent_deployments(service_id, railway=None):
    railway = railway or state.railway
    rows = railway(
        f'query {{ deployments(first:20, input:{{projectId:"{state.PROJECT}", '
        f'environmentId:"{state.ENVIRONMENT}", serviceId:"{service_id}"}}) '
        f'{{ edges {{ node {{ id }} }} }} }}'
    )["deployments"]["edges"]
    return [row["node"]["id"] for row in rows]


def verified_active(node, commit, read=delivery.read_deployment, listing=recent_deployments):
    """Return (active, source): the active verified upload and a redeployable
    deployment of the identical upload image. Refuses GitHub rebuilds."""
    latest = node.get("latestDeployment") or {}
    if latest.get("status") != "SUCCESS":
        raise state.VerificationError("Collector is not on a successful deployment")
    # read_deployment requires destination and the exact-commit upload marker.
    active = read(latest["id"], node["serviceId"], commit)
    image = digest(active)
    if active.get("canRedeploy"):
        return active, active
    # Railway refuses to redeploy the active deployment itself; use the newest
    # deployment carrying the same marker and the byte-identical image.
    for identity in listing(node["serviceId"]):
        if identity == active["id"]:
            continue
        try:
            candidate = read(identity, node["serviceId"], commit)
        except state.VerificationError:
            continue
        if candidate.get("canRedeploy") and digest(candidate) == image:
            return active, candidate
    raise state.VerificationError("No redeployable deployment of the verified upload image")


def skip_deploys_supported(run=subprocess.run):
    result = run(["railway", "variable", "set", "--help"], capture_output=True, text=True, timeout=30)
    return result.returncode == 0 and "--skip-deploys" in result.stdout


def stage(node, assignments, run=subprocess.run):
    command = ["railway", "variable", "set", "--skip-deploys",
               "-p", state.PROJECT, "-e", state.ENVIRONMENT, "-s", node["serviceId"],
               *(f"{k}={v}" for k, v in sorted(assignments.items()))]
    result = run(command, capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise state.VerificationError("Staged collector variable change failed")


def redeploy(source, node, commit, railway=None, read=delivery.read_deployment):
    railway = railway or state.railway
    result = railway(
        f'mutation {{ deploymentRedeploy(id:"{source["id"]}",usePreviousImageTag:false) '
        f'{{ id projectId environmentId serviceId status meta }} }}'
    )["deploymentRedeploy"]
    # The clone must preserve both destination and the exact-commit marker.
    return read(result["id"], node["serviceId"], commit)


def read_variables(service_id):
    values = state.command_json(["railway", "variable", "list", "-p", state.PROJECT,
                                 "-e", state.ENVIRONMENT, "-s", service_id, "--json"])
    try:
        if (values.get("RAILWAY_PROJECT_ID"), values.get("RAILWAY_ENVIRONMENT_ID")) != (
                state.PROJECT, state.ENVIRONMENT):
            raise state.VerificationError("Variables read from wrong destination")
        return {k: values.get(k) for k in ALLOWED}
    finally:
        values.clear()


def change(name, assignments, commit, *, inspect=delivery.inspect, read=delivery.read_deployment,
           run=subprocess.run, railway=None, variables=read_variables, listing=None,
           clock=time.monotonic, sleep=time.sleep, wait_seconds=600):
    if not re.fullmatch("[0-9a-f]{40}", commit):
        raise state.VerificationError("Full verified upload commit required")
    if not skip_deploys_supported(run):
        raise state.VerificationError("Railway CLI lacks --skip-deploys; refusing")
    listing = listing or (lambda service_id: recent_deployments(service_id, railway))
    node = service_node(name, inspect)
    before = {"schedule": node.get("cronSchedule"), "start": node.get("startCommand")}
    active, source = verified_active(node, commit, read, listing)
    stage(node, assignments, run)
    after_stage = service_node(name, inspect)
    if (after_stage.get("latestDeployment") or {}).get("id") != active["id"]:
        raise state.VerificationError(
            "A deployment started while staging variables; verified upload not redeployed")
    clone = redeploy(source, node, commit, railway, read)
    deadline = clock() + wait_seconds
    while clone.get("status") != "SUCCESS":
        if clone.get("status") in {"FAILED", "CRASHED", "REMOVED", "SKIPPED"} or clock() >= deadline:
            raise state.VerificationError("Verified upload redeploy did not succeed")
        sleep(10)
        clone = read(clone["id"], node["serviceId"], commit)
    if digest(clone) != digest(active):
        raise state.VerificationError("Redeployed image differs from the verified upload")
    final = service_node(name, inspect)
    if {"schedule": final.get("cronSchedule"), "start": final.get("startCommand")} != before:
        raise state.VerificationError("Collector schedule or start command changed")
    if (final.get("latestDeployment") or {}).get("id") != clone["id"]:
        raise state.VerificationError("Active deployment is not the verified redeploy")
    observed = variables(node["serviceId"])
    if any(observed[k] != v for k, v in assignments.items()):
        raise state.VerificationError("Collector variables did not read back as requested")
    return {"target": "staging", "service": name, "service_id": node["serviceId"],
            "verified_commit": commit, "previous_deployment": active["id"],
            "source_deployment": source["id"], "deployment": clone["id"],
            "image_digest": digest(clone), "status": clone["status"],
            "marker": clone["meta"].get("cliMessage"), "requested": assignments,
            "observed": observed, "schedule": before["schedule"],
            "observed_at": state.timestamp(), "source_jobs_triggered": 0,
            "production_accessed": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", required=True)
    parser.add_argument("--commit", required=True, help="Verified upload commit the service runs")
    parser.add_argument("--set", action="append", default=[], dest="assignments")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    state.staging_environment()
    receipt = change(args.service, parse_assignments(args.assignments), args.commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    try:
        main()
    except state.VerificationError as error:
        raise SystemExit("Collector variable change refused: " + str(error)) from None
