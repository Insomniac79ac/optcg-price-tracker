"""Builds the GET /admin/observability/summary payload - a fast, single-call
"is production healthy right now" snapshot that pulls together app_log_events
counts with the latest run of each of the other admin-visible processes
(market workflow, price refresh, db backup, system check), so an admin can
see the whole picture without visiting four separate pages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AppLogEvent, MarketWorkflowRun, PriceRefreshRun
from app.services.app_logging import list_app_logs
from app.services.db_backups import list_db_backups
from app.services.system_check import overall_status, run_system_check
from app.settings import settings

STATUSES = ("ok", "warning", "critical")


@dataclass
class ObservabilitySummary:
    status: str
    last_24h: dict[str, int]
    latest_error: AppLogEvent | None
    latest_market_workflow_run: dict | None
    latest_price_refresh_run: dict | None
    latest_backup: dict | None
    latest_system_check_status: str | None


def _summary_status(last_24h: dict[str, int]) -> str:
    if last_24h["critical"] > 0:
        return "critical"
    if last_24h["error"] > 0 or last_24h["warning"] > 0:
        return "warning"
    return "ok"


def build_observability_summary(db: Session) -> ObservabilitySummary:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    last_24h_result = list_app_logs(db, since_hours=24, limit=1)
    level_lookup = {
        "critical": last_24h_result.critical_count,
        "error": last_24h_result.error_count,
        "warning": last_24h_result.warning_count,
        "info": db.scalar(
            select(func.count())
            .select_from(AppLogEvent)
            .where(AppLogEvent.level == "info", AppLogEvent.created_at >= cutoff)
        )
        or 0,
    }

    latest_error = db.scalar(
        select(AppLogEvent)
        .where(AppLogEvent.level.in_(("error", "critical")))
        .order_by(AppLogEvent.created_at.desc(), AppLogEvent.id.desc())
    )

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

    latest_refresh_run = db.scalar(
        select(PriceRefreshRun).order_by(
            PriceRefreshRun.started_at.desc(), PriceRefreshRun.id.desc()
        )
    )
    latest_refresh_run_out = (
        None
        if latest_refresh_run is None
        else {
            "id": latest_refresh_run.id,
            "status": latest_refresh_run.status,
            "started_at": latest_refresh_run.started_at.isoformat(),
            "finished_at": latest_refresh_run.finished_at.isoformat()
            if latest_refresh_run.finished_at
            else None,
            "error_message": latest_refresh_run.error_message,
        }
    )

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

    system_check_status = overall_status(run_system_check(db))

    return ObservabilitySummary(
        status=_summary_status(level_lookup),
        last_24h=level_lookup,
        latest_error=latest_error,
        latest_market_workflow_run=latest_workflow_run_out,
        latest_price_refresh_run=latest_refresh_run_out,
        latest_backup=latest_backup_out,
        latest_system_check_status=system_check_status,
    )
