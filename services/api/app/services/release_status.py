"""Builds the GET /admin/release-status payload - a single-call "is this
deployment safe to consider released" snapshot for docs/release_checklist.md
step D (post-deploy validation). Reuses the same building blocks as
GET /admin/observability/summary and GET /admin/system-check rather than
re-implementing any of their checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.version import get_version_info
from app.models import AppLogEvent, MarketWorkflowRun
from app.services.app_logging import list_app_logs
from app.services.db_backups import list_db_backups
from app.services.system_check import overall_status, run_system_check
from app.settings import settings


@dataclass
class ReleaseStatus:
    version: str
    git_commit: str
    build_time: str
    app_env: str
    latest_market_workflow_run: dict[str, Any] | None
    latest_system_check: dict[str, Any]
    latest_backup: dict[str, Any] | None
    latest_error: AppLogEvent | None
    release_readiness: dict[str, Any] = field(default_factory=dict)


def build_release_status(db: Session) -> ReleaseStatus:
    version_info = get_version_info()

    latest_workflow_run = db.scalar(
        select(MarketWorkflowRun).order_by(
            MarketWorkflowRun.started_at.desc(), MarketWorkflowRun.id.desc()
        )
    )
    latest_workflow_run_out = (
        None
        if latest_workflow_run is None
        else {
            "id": latest_workflow_run.id,
            "status": latest_workflow_run.status,
            "started_at": latest_workflow_run.started_at.isoformat(),
            "finished_at": latest_workflow_run.finished_at.isoformat()
            if latest_workflow_run.finished_at
            else None,
            "error_message": latest_workflow_run.error_message,
        }
    )

    checks = run_system_check(db)
    system_check_status = overall_status(checks)
    latest_system_check_out = {
        "status": system_check_status,
        "summary": {
            "checks_total": len(checks),
            "checks_passed": sum(1 for c in checks if c.status == "pass"),
            "warnings": sum(1 for c in checks if c.status == "warning"),
            "critical": sum(1 for c in checks if c.status == "fail"),
        },
        "checks": [
            {"name": c.name, "status": c.status, "severity": c.severity, "message": c.message}
            for c in checks
        ],
    }

    backups = list_db_backups(settings.DB_BACKUP_DIR)
    latest_backup_out = (
        None
        if not backups
        else {
            "filename": backups[0].filename,
            "size_bytes": backups[0].size_bytes,
            "created_at": backups[0].created_at.isoformat(),
        }
    )

    last_24h = list_app_logs(db, since_hours=24, limit=1)
    latest_error = db.scalar(
        select(AppLogEvent)
        .where(AppLogEvent.level.in_(("error", "critical")))
        .order_by(AppLogEvent.created_at.desc(), AppLogEvent.id.desc())
    )

    return ReleaseStatus(
        version=version_info["version"],
        git_commit=version_info["git_commit"],
        build_time=version_info["build_time"],
        app_env=version_info["app_env"],
        latest_market_workflow_run=latest_workflow_run_out,
        latest_system_check=latest_system_check_out,
        latest_backup=latest_backup_out,
        latest_error=latest_error,
        release_readiness={
            "system_check_status": system_check_status,
            "critical_logs_last_24h": last_24h.critical_count,
            "latest_backup_available": latest_backup_out is not None,
        },
    )
