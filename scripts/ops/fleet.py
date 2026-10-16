"""All 10 staging collectors against a collector rollout receipt (session 13 tools
live_a504e47.py + fleet_vs_receipt.py).

For each collector: the live latest deployment, its status, exact-commit marker and image
digest, its cron schedule, and every deployment record created after the receipt's
completed_at, compared with the receipt. Read-only Railway queries; no deploy, no redeploy.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from ops import common

# Latest delivered collector rollout (PR #103, a504e47); all 10 collectors still run it.
DEFAULT_RECEIPT = ("docs/agent/handoff/2026-10-11/capacity75-session10/evidence/pr103-delivery/"
                   "staging-delivery-a504e476d98ab49ad7773a0c8c6b71e9d927b125/evidence/latest-collector-rollout.json")


def receipt_path(value):
    """A committed rollout receipt under docs/agent/ only."""
    value = value or DEFAULT_RECEIPT
    path = (common.ROOT / value).resolve()
    if (not path.is_relative_to(common.ROOT / "docs/agent") or path.name != "latest-collector-rollout.json"
            or not path.is_file()):
        raise common.Refused("receipt must be a committed docs/agent/**/latest-collector-rollout.json")
    return path


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

    path = receipt_path(receipt)
    data = json.loads(path.read_text())
    commit = data.get("source_sha")
    if not re.fullmatch(r"[0-9a-f]{40}", commit or ""):
        raise common.Refused("receipt has no source_sha")
    nodes = cv.delivery.inspect()
    out = {"observed_at": state.timestamp(), "read_only": True, "receipt": str(path.relative_to(common.ROOT)),
           "receipt_commit": commit, "receipt_completed_at": data["completed_at"], "services": {}}
    for name in sorted(cv.delivery.NAMES):
        node = nodes.get(name)
        if node is None:
            out["services"][name] = {"match": False, "error": "service not found"}
            continue
        live = live_row(node, commit, cv.delivery, cv.digest)
        after = records_after(node["serviceId"], data["completed_at"], state.railway)
        out["services"][name] = compare(name, data["deployments"].get(name, {}), live, after)
    out["collectors"] = len(out["services"])
    out["all_match"] = out["collectors"] == 10 and all(r["match"] for r in out["services"].values())
    common.write_json(Path(out_dir) / "fleet-vs-receipt.json", out)
    return {"receipt_commit": commit, "collectors": out["collectors"], "all_match": out["all_match"],
            "mismatched": sorted(n for n, r in out["services"].items() if not r["match"]),
            "records_after_receipt": sum(len(r.get("records_after_receipt", [])) for r in out["services"].values())}
