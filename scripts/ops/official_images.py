"""Official-images mirror status: the last runs of the Railway cron service and the check result.

- Runs: the `official-images-mirror` service's latest deployments (each cron run is one),
  status and time, read from Railway. A FAILED/CRASHED latest run is the state blocker
  `official-images-check-failed` (scripts/generate_staging_state.py).
- Check: `app.official_images.health.check_health` (the same check `check_official_images`
  runs at the end of every mirror run), database consistency only, over a read-only session.
  No R2 or Bandai request, no write.
"""
from __future__ import annotations

from pathlib import Path

from ops import common

SERVICE = "official-images-mirror"
FAILED = {"CRASHED", "FAILED"}


def runs(node, railway):
    import generate_staging_state as state

    edges = railway(
        f'query {{ deployments(first:5, input:{{projectId:"{state.PROJECT}", environmentId:"{state.ENVIRONMENT}", '
        f'serviceId:"{node["serviceId"]}"}}) {{ edges {{ node {{ id status createdAt }} }} }} }}')["deployments"]["edges"]
    return [e["node"] for e in edges]


def summarize(node, recent, health, assets):
    latest = (node or {}).get("latestDeployment") or {}
    return {
        "service_found": node is not None,
        "schedule_utc": (node or {}).get("cronSchedule"),
        "latest_run": {"deployment_id": latest.get("id"), "status": latest.get("status")},
        "recent_runs": recent,
        "latest_run_failed": latest.get("status") in FAILED,
        "check": health,
        "assets": assets,
        "healthy": node is not None and latest.get("status") not in FAILED and bool(health) and health.get("healthy"),
    }


def check(session):
    from sqlalchemy import text
    from app.official_images.health import check_health

    report = check_health(session)
    assets = session.execute(text(
        "select count(*) n, max(mirrored_at) last_mirrored_at from card_print_image_assets")).mappings().one()
    session.rollback()
    return {"healthy": report.healthy, **report.summary()}, dict(assets)


def run(out_dir):
    import deploy_staging_collectors as delivery
    import generate_staging_state as state
    from sqlalchemy.orm import Session
    from ops import db as ops_db

    node = delivery.inspect().get(SERVICE)
    recent = runs(node, state.railway) if node else []
    with Session(ops_db.engine()) as session:
        health, assets = check(session)
    result = {"observed_at": state.timestamp(), "read_only": True, "source_requests": 0, "database_writes": 0,
              **summarize(node, recent, health, assets)}
    common.write_json(Path(out_dir) / "official-images-status.json", result)
    return brief(result, health, assets)


def brief(result, health, assets):
    """The ops-summary, with each recent run's start time so REST readers can date the latest run."""
    return {"latest_run": result["latest_run"], "latest_run_failed": result["latest_run_failed"],
            "recent_runs": [{"status": r.get("status"), "created_at": r.get("createdAt")}
                            for r in result["recent_runs"]],
            "check_healthy": health.get("healthy"), "prints_checked": health.get("prints_checked"),
            "missing_copy": health.get("missing_copy"), "digest_mismatch": health.get("digest_mismatch"),
            "assets": assets.get("n"), "last_mirrored_at": assets.get("last_mirrored_at"),
            "healthy": result["healthy"]}
