#!/usr/bin/env python3
"""Read-only verification of unchanged API bytes and naturally adopted SNKR bytes."""

import json
import os
import re
import subprocess
import time

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


class AdoptionPending(state.VerificationError):
    """Installed source has not yet produced a completed scheduled receipt."""


def verify(live, head, snkr_expected=SNKR, api_expected=API):
    if live["repository"]["sha"] != head or live["mode"] != "live":
        raise state.VerificationError("Staging source changed or live evidence missing")
    api = next(
        s for s in live["railway"]["services"] if s["name"] == "optcg-price-tracker"
    )
    collector = next(
        s for s in live["railway"]["services"] if s["service_id"] == SERVICE
    )
    if api["git_sha"] != api_expected or api["status"] != "SUCCESS":
        raise state.VerificationError("Unexpected adopted API deployment")
    if (
        collector["status"] != "SUCCESS"
        or collector["reported_sha"] != snkr_expected
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
        raise AdoptionPending("No completed ordinary SNKR runtime receipt")
    receipt = max(runs, key=lambda r: r["identity"]["finished_at"])
    if (
        receipt["exit"]["terminal_state"] != "completed"
        or receipt["safety"]["singleton"] != "held"
    ):
        raise state.VerificationError("SNKR terminal/singleton receipt refused")
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
    if (
        receipt["identity"]["revision"] != snkr_expected
        or receipt["identity"]["deployment_id"] != collector["deployment_id"]
    ):
        raise AdoptionPending("Actual SNKR runtime adoption not yet verified")
    return {
        "api_component": api_expected,
        "snkr_component": snkr_expected,
        "snkr_actual_runtime_identity": receipt["identity"],
        "identity_basis": "Unchanged Git runtime inputs plus actual installed component receipt; platform Git may be unknown",
        "source_jobs_triggered": 0,
        "production_accessed": False,
    }


def wait_for_adoption(
    head,
    snkr_expected,
    *,
    collect=state.collect_live,
    clock=time.monotonic,
    sleep=time.sleep,
    timeout=1800,
    api_expected=API,
):
    deadline = clock() + timeout
    while True:
        try:
            return verify(collect(), head, snkr_expected, api_expected)
        except AdoptionPending:
            remaining = deadline - clock()
            if remaining <= 0:
                raise state.VerificationError("Natural SNKR adoption deadline exceeded")
            sleep(min(30, remaining))


def expected_api(declared, head, environ=os.environ):
    """api_sha=merge uses the delivery verifier's resolved API source when given.

    verify_staging_delivery resolves a legitimately skipped API build to its
    previous verified SHA and exports it; continuity() below still requires the
    API inputs to be byte-identical between that SHA and head.
    """
    if declared != "merge":
        return declared
    resolved = environ.get("STAGING_RESOLVED_API_SHA", "")
    return resolved if re.fullmatch("[0-9a-f]{40}", resolved) else head


def main():
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=state.ROOT, text=True
    ).strip()
    mission = json.loads((state.ROOT / "docs/agent/STAGING_MISSION.json").read_text())
    expected = mission["deployment_verification"].get("snkr_component", SNKR)
    expected = head if expected == "merge" else expected
    api_expected = expected_api(mission["deployment_verification"]["api_sha"], head)
    continuity(api_expected, head, API_PATHS)
    continuity(expected, head, SNKR_PATHS)
    print(
        json.dumps(
            wait_for_adoption(head, expected, api_expected=api_expected), indent=2
        )
    )


if __name__ == "__main__":
    main()
