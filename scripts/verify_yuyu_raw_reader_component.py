#!/usr/bin/env python3
"""Pinned read-only all-nine natural reader adoption; no source invocation."""

import json
import subprocess
import time
import generate_staging_state as state
from verify_snkr_published_discovery_component import AdoptionPending


def verify(live, head, component=None):
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
    for service in services:
        shard = int(service["name"].split("shard-")[1].split("-")[0])
        minute = shard * 3
        if (
            service["status"] != "SUCCESS"
            or service["reported_sha"] != component
            or service["schedule_utc"] != f"{minute},{minute+30} * * * *"
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
            result = verify(state.collect_live(), head, component)
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
