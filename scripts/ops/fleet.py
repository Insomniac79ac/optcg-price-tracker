"""All 10 staging collectors against collector rollout receipts (session 13 tools
live_a504e47.py + fleet_vs_receipt.py).

For each collector: the live latest deployment, its status, exact-commit marker and image
digest, its cron schedule, and every deployment record created after the receipt's
completed_at, compared with the newest receipt that deployed it. A rollout receipt lists only
the services it deployed, so a fleet is described by a chain of receipts (comma-separated).
Read-only Railway queries; no deploy, no redeploy.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from ops import common

# Delivered collector rollouts, oldest first: PR #103 (a504e47, all 10 collectors) and PR #173
# (2bcbe90, the 9 yuyutei shards). snkrdunk-collector still runs the PR #103 rollout.
DEFAULT_RECEIPTS = (
    "docs/agent/handoff/2026-10-11/capacity75-session10/evidence/pr103-delivery/"
    "staging-delivery-a504e476d98ab49ad7773a0c8c6b71e9d927b125/evidence/latest-collector-rollout.json",
    "docs/agent/handoff/2026-10-18/pr173-delivery/"
    "staging-delivery-2bcbe9013c0aa9ba76a4ce4e90ca9a45c206ebf3/evidence/latest-collector-rollout.json",
)


def receipt_path(value):
    """A committed rollout receipt under docs/agent/ only."""
    value = value or DEFAULT_RECEIPTS[-1]
    path = (common.ROOT / value).resolve()
    if (not path.is_relative_to(common.ROOT / "docs/agent") or path.name != "latest-collector-rollout.json"
            or not path.is_file()):
        raise common.Refused("receipt must be a committed docs/agent/**/latest-collector-rollout.json")
    return path


def load_receipts(value):
    """Committed receipts (comma-separated, default DEFAULT_RECEIPTS), oldest completed_at first."""
    names = [v.strip() for v in (value or ",".join(DEFAULT_RECEIPTS)).split(",") if v.strip()]
    receipts = []
    for name in names:
        path = receipt_path(name)
        data = json.loads(path.read_text())
        if not re.fullmatch(r"[0-9a-f]{40}", data.get("source_sha") or ""):
            raise common.Refused(f"receipt has no source_sha: {path.name} in {path.parent.parent.name}")
        receipts.append((path, data))
    return sorted(receipts, key=lambda item: item[1]["completed_at"])


def receipt_for(name, receipts):
    """The newest receipt that deployed this service, or None."""
    owning = [item for item in receipts if name in item[1].get("deployments", {})]
    return owning[-1] if owning else None


def compare(name, receipt_row, live, records_after):
    row = {"receipt_deployment": receipt_row.get("deployment_id") or receipt_row.get("id"),
           "receipt_digest": receipt_row.get("image_digest") or receipt_row.get("digest"),
           "receipt_schedule": receipt_row.get("schedule_utc"), **live,
           "records_after_receipt": records_after}
    row["match"] = bool(row["receipt_deployment"] == live.get("live_deployment")
                        and row["receipt_digest"] == live.get("live_digest")
                        and live.get("marker") and live.get("status") == "SUCCESS"
                        and (row["receipt_schedule"] is None or row["receipt_schedule"] == live.get("schedule"))
                        and not records_after)
    return row


def live_row(node, commit, delivery, digest):
    latest = node.get("latestDeployment") or {}
    row = {"live_deployment": latest.get("id"), "status": latest.get("status"), "schedule": node.get("cronSchedule")}
    try:
        active = delivery.read_deployment(latest["id"], node["serviceId"], commit)
        row["marker"] = True
        row["live_digest"] = digest(active)
    except Exception as exc:  # noqa: BLE001 - recorded as a mismatch
        row["marker"] = False
        row["error"] = type(exc).__name__
    return row


def records_after(service_id, completed_at, railway):
    import generate_staging_state as state

    edges = railway(
        f'query {{ deployments(first:10, input:{{projectId:"{state.PROJECT}", environmentId:"{state.ENVIRONMENT}", '
        f'serviceId:"{service_id}"}}) {{ edges {{ node {{ id status createdAt }} }} }} }}')["deployments"]["edges"]
    return [e["node"] for e in edges if e["node"]["createdAt"] > completed_at]


def run(out_dir, receipt=None):
    import collector_variables as cv
    import generate_staging_state as state

    receipts = load_receipts(receipt)
    nodes = cv.delivery.inspect()
    out = {"observed_at": state.timestamp(), "read_only": True,
           "receipts": [{"receipt": str(p.relative_to(common.ROOT)), "commit": d["source_sha"],
                         "completed_at": d["completed_at"], "services": sorted(d.get("deployments", {}))}
                        for p, d in receipts], "services": {}}
    for name in sorted(cv.delivery.NAMES):
        node = nodes.get(name)
        owner = receipt_for(name, receipts)
        if node is None or owner is None:
            out["services"][name] = {"match": False, "error": "service not found" if node is None else "in no receipt"}
            continue
        data = owner[1]
        live = live_row(node, data["source_sha"], cv.delivery, cv.digest)
        after = records_after(node["serviceId"], data["completed_at"], state.railway)
        out["services"][name] = dict(compare(name, data["deployments"][name], live, after),
                                     receipt_commit=data["source_sha"])
    out["collectors"] = len(out["services"])
    out["all_match"] = out["collectors"] == 10 and all(r["match"] for r in out["services"].values())
    common.write_json(Path(out_dir) / "fleet-vs-receipt.json", out)
    by_commit = {}
    for name, row in out["services"].items():
        by_commit.setdefault(row.get("receipt_commit", "none"), []).append(name)
    return {"receipt_commits": {c: len(n) for c, n in by_commit.items()}, "collectors": out["collectors"],
            "all_match": out["all_match"],
            "mismatched": sorted(n for n, r in out["services"].items() if not r["match"]),
            "records_after_receipt": sum(len(r.get("records_after_receipt", [])) for r in out["services"].values())}
