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


def original_source(node, commit, image, read=delivery.read_deployment, listing=recent_deployments,
                    exclude=()):
    """Newest redeployable deployment carrying the exact-commit marker and the
    given (original verified) image digest. Refuses GitHub rebuilds."""
    latest = (node.get("latestDeployment") or {}).get("id")
    for identity in [latest, *listing(node["serviceId"])]:
        if not identity or identity in exclude:
            continue
        try:
            candidate = read(identity, node["serviceId"], commit)
        except state.VerificationError:
            continue
        if candidate.get("canRedeploy") and digest(candidate) == image:
            return candidate
    raise state.VerificationError("No redeployable deployment of the verified upload image")


def verified_active(node, commit, read=delivery.read_deployment, listing=recent_deployments,
                    expect_digest=None):
    """Return (active, source): the active verified upload and a redeployable
    deployment of the identical upload image. Refuses GitHub rebuilds and, when
    an original digest is given, any active image other than that original."""
    latest = node.get("latestDeployment") or {}
    if latest.get("status") != "SUCCESS":
        raise state.VerificationError("Collector is not on a successful deployment")
    # read_deployment requires destination and the exact-commit upload marker.
    active = read(latest["id"], node["serviceId"], commit)
    image = digest(active)
    if expect_digest is not None and image != expect_digest:
        raise state.VerificationError("Active image is not the original verified upload; restore it first")
    # Railway refuses to redeploy the active deployment itself; use the newest
    # deployment carrying the same marker and the byte-identical image.
    return active, original_source(node, commit, image, read, listing)


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
    """Settings-only redeploy that asks Railway to reuse the source's image.

    usePreviousImageTag:false schedules a build every time; digest stability then
    depends on layer cache (shard-6 rebuilt 2026-10-08, 954d0f1d). The flag is
    undocumented, so its effect is never trusted: callers verify the digest.
    """
    railway = railway or state.railway
    result = railway(
        f'mutation {{ deploymentRedeploy(id:"{source["id"]}",usePreviousImageTag:true) '
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


def build_lines(deployment_id, railway=None):
    """Evidence only: number of build-log lines Railway recorded for a deployment."""
    railway = railway or state.railway
    try:
        rows = railway(f'query {{ buildLogs(deploymentId:"{deployment_id}", limit:500) {{ message }} }}')
        return len(rows["buildLogs"])
    except Exception:  # evidence is best-effort; the digest is the check
        return None


def await_success(clone, node, commit, read, clock, sleep, wait_seconds):
    deadline = clock() + wait_seconds
    while clone.get("status") != "SUCCESS":
        if clone.get("status") in {"FAILED", "CRASHED", "REMOVED", "SKIPPED"} or clock() >= deadline:
            raise state.VerificationError("Verified upload redeploy did not succeed")
        sleep(10)
        clone = read(clone["id"], node["serviceId"], commit)
    return clone


def effective(previous, keys):
    """Values to restore on rollback. Unset writer keys become their code defaults
    (ENABLED=false, MODE=canary); an unset APP_ENV is left as staging, which every
    collector requires and which changes no behaviour while the writer is OFF."""
    defaults = {"RAW_DICTIONARY_STORAGE_ENABLED": "false", "RAW_DICTIONARY_STORAGE_MODE": "canary",
                "APP_ENV": "staging"}
    return {k: previous.get(k) or defaults[k] for k in keys}


def deploy_verified(name, values, commit, image, *, before, inspect, read, run, railway, variables,
                    listing, clock, sleep, wait_seconds, exclude=()):
    """Stage values, redeploy the original image, and verify every invariant.
    Returns (clone, observed, problem) where problem is None when all checks pass."""
    node = service_node(name, inspect)
    latest = (node.get("latestDeployment") or {}).get("id")
    source = original_source(node, commit, image, read, listing, exclude)
    stage(node, values, run)
    if (service_node(name, inspect).get("latestDeployment") or {}).get("id") != latest:
        raise state.VerificationError(
            "A deployment started while staging variables; verified upload not redeployed")
    clone = await_success(redeploy(source, node, commit, railway, read), node, commit, read,
                          clock, sleep, wait_seconds)
    final = service_node(name, inspect)
    observed = variables(node["serviceId"])
    if digest(clone) != image:
        return clone, observed, "Redeployed image differs from the verified upload", source
    if {"schedule": final.get("cronSchedule"), "start": final.get("startCommand")} != before:
        return clone, observed, "Collector schedule or start command changed", source
    if (final.get("latestDeployment") or {}).get("id") != clone["id"]:
        return clone, observed, "Active deployment is not the verified redeploy", source
    if any(observed[k] != v for k, v in values.items()):
        return clone, observed, "Collector variables did not read back as requested", source
    return clone, observed, None, source


def change(name, assignments, commit, *, expect_digest=None, inspect=delivery.inspect,
           read=delivery.read_deployment, run=subprocess.run, railway=None, variables=read_variables,
           listing=None, clock=time.monotonic, sleep=time.sleep, wait_seconds=600):
    """Apply a settings-only change on the original verified image, or roll back.

    Any failed invariant after the redeploy restores the previous effective values
    on the original verified upload (same digest), verifies that, and refuses.
    """
    if not re.fullmatch("[0-9a-f]{40}", commit):
        raise state.VerificationError("Full verified upload commit required")
    if not skip_deploys_supported(run):
        raise state.VerificationError("Railway CLI lacks --skip-deploys; refusing")
    listing = listing or (lambda service_id: recent_deployments(service_id, railway))
    node = service_node(name, inspect)
    before = {"schedule": node.get("cronSchedule"), "start": node.get("startCommand")}
    active, _ = verified_active(node, commit, read, listing, expect_digest)
    image = digest(active)
    previous = variables(node["serviceId"])
    common = dict(before=before, inspect=inspect, read=read, run=run, railway=railway,
                  variables=variables, listing=listing, clock=clock, sleep=sleep,
                  wait_seconds=wait_seconds)
    clone, observed, problem, source = deploy_verified(name, assignments, commit, image, **common)
    if problem:
        restored, back, rollback_problem, _ = deploy_verified(
            name, effective(previous, assignments), commit, image, exclude=(clone["id"],), **common)
        detail = (f"{problem}; rolled back to original image on {restored['id']}"
                  if rollback_problem is None else
                  f"{problem}; ROLLBACK FAILED ({rollback_problem}) on {restored['id']}")
        error = state.VerificationError(detail)
        error.receipt = {"service": name, "refused_deployment": clone["id"],
                         "refused_digest": digest(clone), "original_digest": image,
                         "rollback_deployment": restored["id"], "rollback_digest": digest(restored),
                         "rollback_observed": back, "rollback_ok": rollback_problem is None}
        raise error
    return {"target": "staging", "service": name, "service_id": node["serviceId"],
            "verified_commit": commit, "previous_deployment": active["id"],
            "source_deployment": source["id"], "deployment": clone["id"],
            "image_digest": digest(clone), "original_digest": image, "status": clone["status"],
            "marker": clone["meta"].get("cliMessage"), "requested": assignments,
            "previous_values": previous, "observed": observed, "schedule": before["schedule"],
            "build_log_lines": build_lines(clone["id"], railway),
            "observed_at": state.timestamp(), "source_jobs_triggered": 0,
            "production_accessed": False}


def restore(name, values, commit, original_digest, **kwargs):
    """Explicit rollback: put the original verified upload image back with the
    given values, even when the active deployment is a different image."""
    inspect = kwargs.get("inspect", delivery.inspect)
    node = service_node(name, inspect)
    railway = kwargs.get("railway")
    listing = kwargs.get("listing") or (lambda service_id: recent_deployments(service_id, railway))
    common = dict(before={"schedule": node.get("cronSchedule"), "start": node.get("startCommand")},
                  inspect=inspect, read=kwargs.get("read", delivery.read_deployment),
                  run=kwargs.get("run", subprocess.run), railway=railway,
                  variables=kwargs.get("variables", read_variables), listing=listing,
                  clock=kwargs.get("clock", time.monotonic), sleep=kwargs.get("sleep", time.sleep),
                  wait_seconds=kwargs.get("wait_seconds", 600))
    if not skip_deploys_supported(common["run"]):
        raise state.VerificationError("Railway CLI lacks --skip-deploys; refusing")
    clone, observed, problem, source = deploy_verified(name, values, commit, original_digest, **common)
    if problem:
        raise state.VerificationError("Restore failed: " + problem)
    return {"service": name, "deployment": clone["id"], "source_deployment": source["id"],
            "image_digest": digest(clone), "observed": observed, "observed_at": state.timestamp()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", required=True)
    parser.add_argument("--commit", required=True, help="Verified upload commit the service runs")
    parser.add_argument("--set", action="append", default=[], dest="assignments")
    parser.add_argument("--expect-digest", help="Original verified image digest (sha256:...)")
    parser.add_argument("--restore", action="store_true",
                        help="Put the original verified image back with these values")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    state.staging_environment()
    values = parse_assignments(args.assignments)
    if args.restore:
        if not args.expect_digest:
            raise state.VerificationError("--restore requires --expect-digest")
        receipt = restore(args.service, values, args.commit, args.expect_digest)
    else:
        receipt = change(args.service, values, args.commit, expect_digest=args.expect_digest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    try:
        main()
    except state.VerificationError as error:
        raise SystemExit("Collector variable change refused: " + str(error)) from None
