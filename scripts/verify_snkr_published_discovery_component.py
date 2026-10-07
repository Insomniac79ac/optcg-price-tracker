#!/usr/bin/env python3
"""Read-only verification of unchanged API bytes and naturally adopted SNKR bytes."""

import json
import subprocess

import generate_staging_state as state

API = "1ddb234b8a0a51a2ad313359e22168182bf07dbd"
SNKR = "ffbb5a8a1ca852d28763b175e2e850b0824edeea"
SERVICE = "2d7ab69b-ec1f-4c66-8da1-9c8769a6d14a"
API_PATHS = (
    "services/api",
    "packages/opcg_source_identity",
    "deploy/railway/api.Dockerfile",
)
SNKR_PATHS = (
    "services/snkrdunk_collector",
    "services/api",
    "packages/opcg_source_identity",
    "deploy/railway/snkrdunk-collector.Dockerfile",
)


def continuity(component, head, paths, *, run=subprocess.check_output):
    changed = run(
        ["git", "diff", "--name-only", component, head, "--", *paths],
        cwd=state.ROOT,
        text=True,
    ).strip()
    if changed:
        raise state.VerificationError(
            "Adopted component source differs from expected runtime inputs"
        )


def verify(live, head):
    if live["repository"]["sha"] != head or live["mode"] != "live":
        raise state.VerificationError("Staging source changed or live evidence missing")
    api = next(
        s for s in live["railway"]["services"] if s["name"] == "optcg-price-tracker"
    )
    collector = next(
        s for s in live["railway"]["services"] if s["service_id"] == SERVICE
    )
    if api["git_sha"] != API or api["status"] != "SUCCESS":
        raise state.VerificationError("Unexpected adopted API deployment")
    if (
        collector["status"] != "SUCCESS"
        or collector["reported_sha"] != SNKR
        or collector["schedule_utc"] != "27,57 * * * *"
        or not collector["due_work_configured"]
    ):
        raise state.VerificationError("Unexpected deployed SNKR source or schedule")
    runs = [
        r
        for r in live["database"]["operational_runs"]
        if r["identity"]["service"] == "snkrdunk-collector"
        and r["identity"].get("finished_at")
    ]
    if not runs:
        raise state.VerificationError("No completed ordinary SNKR runtime receipt")
    receipt = max(runs, key=lambda r: r["identity"]["finished_at"])
    if (
        receipt["identity"]["revision"] != SNKR
        or receipt["identity"]["deployment_id"] != collector["deployment_id"]
        or receipt["exit"]["terminal_state"] != "completed"
        or receipt["safety"]["singleton"] != "held"
    ):
        raise state.VerificationError("Actual SNKR runtime adoption not verified")
    for field in (
        "claims_remaining",
        "expired_claims",
        "reservations_remaining",
        "reservation_overruns",
        "duplicate_requests",
    ):
        if receipt["safety"][field] != 0:
            raise state.VerificationError("SNKR runtime safety receipt refused")
    for field in ("http_403", "http_429", "challenge"):
        if receipt["failure"][field] != 0:
            raise state.VerificationError("SNKR required denial remains unresolved")
    return {
        "api_component": API,
        "snkr_component": SNKR,
        "snkr_actual_runtime_identity": receipt["identity"],
        "identity_basis": "Unchanged Git runtime inputs plus actual installed component receipt; platform Git may be unknown",
        "source_jobs_triggered": 0,
        "production_accessed": False,
    }


def main():
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=state.ROOT, text=True
    ).strip()
    continuity(API, head, API_PATHS)
    continuity(SNKR, head, SNKR_PATHS)
    print(json.dumps(verify(state.collect_live(), head), indent=2))


if __name__ == "__main__":
    main()
