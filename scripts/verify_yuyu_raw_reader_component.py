#!/usr/bin/env python3
"""Pinned read-only all-nine natural reader adoption; no source invocation."""

import json
import subprocess
import time
import generate_staging_state as state
from verify_snkr_published_discovery_component import AdoptionPending


def verify(live, head, component=None, *, capacity_cadence=False):
    component = component or head
    if live["mode"] != "live" or live["repository"]["sha"] != head:
        raise state.VerificationError("Current merged staging source required")
    services = [
        s
        for s in live["railway"]["services"]
        if s["name"].startswith("yuyutei-collector-shard-")
    ]
    if len(services) != 9 or {s["name"] for s in services} != {
        *(f"yuyutei-collector-shard-{i}" for i in range(9) if i != 4),
        "yuyutei-collector-shard-4-v2",
    }:
        raise state.VerificationError("Nine existing staging shards required")
    receipts = []
    profiles = []
    for service in services:
        shard = int(service["name"].split("shard-")[1].split("-")[0])
        minute = shard * 3
        legacy = f"{minute},{minute+30} * * * *"
        bounded = (
            ",".join(str(shard + offset) for offset in range(0, 60, 10)) + " * * * *"
        )
        schedule = service["schedule_utc"]
        profiles.append(
            "legacy"
            if schedule == legacy
            else "bounded" if capacity_cadence and schedule == bounded else "invalid"
        )
        if (
            service["status"] != "SUCCESS"
            or service["reported_sha"] != component
            or profiles[-1] == "invalid"
            or not service["due_work_configured"]
        ):
            raise state.VerificationError("Yuyu deployed source/schedule changed")
        runs = [
            r
            for r in live["database"]["operational_runs"]
            if r["identity"]["service"] == service["name"]
            and r["identity"].get("finished_at")
        ]
        if not runs:
            raise AdoptionPending("Awaiting completed ordinary shard receipt")
        receipt = max(runs, key=lambda r: r["identity"]["finished_at"])
        if (
            receipt["identity"]["revision"] != component
            or receipt["identity"]["deployment_id"] != service["deployment_id"]
        ):
            raise AdoptionPending("Awaiting actual installed reader adoption")
        if (
            receipt["exit"]["terminal_state"] != "completed"
            or receipt["work"]["max_work"] != 16
        ):
            raise state.VerificationError(
                "Reader-only release changed admission/runtime"
            )
        if any(
            receipt["safety"][k]
            for k in (
                "claims_remaining",
                "expired_claims",
                "reservations_remaining",
                "reservation_overruns",
                "duplicate_requests",
                "wrong_shard",
            )
        ):
            raise state.VerificationError("Shard ownership/admission safety failed")
        if any(receipt["failure"][k] for k in ("http_403", "http_429", "challenge")):
            raise state.VerificationError("Required source denial remains unresolved")
        receipts.append(receipt["identity"])
    if len(set(profiles)) != 1:
        raise state.VerificationError(
            "All nine shards require one declared cadence profile"
        )
    return {
        "actual_natural_reader_components": receipts,
        "encoded_writes_enabled": False,
        "source_jobs_triggered": 0,
        "production_accessed": False,
    }


def main():
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=state.ROOT, text=True
    ).strip()
    manifest = json.loads((state.ROOT / "docs/agent/STAGING_MISSION.json").read_text())
    declared = manifest["deployment_verification"].get("yuyu_reader_component", "merge")
    component = head if declared == "merge" else declared
    capacity_cadence = manifest["deployment_verification"].get(
        "yuyu_capacity_cadence", False
    )
    if capacity_cadence:
        installed = subprocess.check_output(
            [
                "git",
                "show",
                component + ":services/api/app/services/freshness_queue.py",
            ],
            text=True,
        )
        if (
            "YUYU_ACTIVE_CLAIM_LIMIT = 4" not in installed
            or "YUYU_ACTIVE_CLAIM_LIMIT - active" not in installed
        ):
            raise state.VerificationError(
                "Declared cadence requires installed four-claim admission"
            )
    if component != head:
        import re

        if not re.fullmatch("[0-9a-f]{40}", component):
            raise state.VerificationError("Full installed reader component required")
        changed = subprocess.check_output(
            [
                "git",
                "diff",
                "--name-only",
                component,
                head,
                "--",
                "services/api",
                "services/yuyutei_collector",
                "packages/opcg_source_identity",
            ],
            cwd=state.ROOT,
            text=True,
        ).strip()
        if changed:
            raise state.VerificationError(
                "Installed Yuyu reader runtime inputs changed"
            )
    deadline = time.monotonic() + 1800
    while True:
        try:
            result = verify(
                state.collect_live(),
                head,
                component,
                capacity_cadence=capacity_cadence,
            )
            print(json.dumps(result, indent=2))
            return
        except AdoptionPending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise state.VerificationError(
                    "All-nine natural reader adoption deadline exceeded"
                )
            time.sleep(min(30, remaining))


if __name__ == "__main__":
    main()
