"""Assembles GET /admin/performance/summary: row counts for the tables most
likely to grow large (price_observations, raw_snapshots,
market_signal_events, collector_activity_events, app_log_events), the most
recent slow-request warnings recorded by app.core.request_timing, and a
rollup of the db-index-audit (see app.services.db_index_audit) - a single
page to check "is this deployment's data volume/query health still fine" as
those tables grow.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AppLogEvent, CollectorActivityEvent, MarketSignalEvent, PriceObservation, RawSnapshot
from app.services.db_index_audit import audit_summary, run_db_index_audit

SLOW_REQUEST_EVENT_TYPE = "slow_request"
LATEST_SLOW_REQUESTS_LIMIT = 20


@dataclass
class PerformanceSummary:
    status: str
    database: dict[str, int]
    latest_slow_requests: list[AppLogEvent]
    index_audit: dict[str, int]


def _table_count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def build_performance_summary(db: Session) -> PerformanceSummary:
    database_counts = {
        "price_observations_count": _table_count(db, PriceObservation),
        "raw_snapshots_count": _table_count(db, RawSnapshot),
        "market_signal_events_count": _table_count(db, MarketSignalEvent),
        "collector_activity_events_count": _table_count(db, CollectorActivityEvent),
        "app_log_events_count": _table_count(db, AppLogEvent),
    }

    latest_slow_requests = db.scalars(
        select(AppLogEvent)
        .where(AppLogEvent.event_type == SLOW_REQUEST_EVENT_TYPE)
        .order_by(AppLogEvent.created_at.desc(), AppLogEvent.id.desc())
        .limit(LATEST_SLOW_REQUESTS_LIMIT)
    ).all()

    index_checks = run_db_index_audit(db)
    index_summary = audit_summary(index_checks)
    index_audit = {"warnings": index_summary["warnings"], "critical": index_summary["critical"]}

    status = "critical" if index_audit["critical"] > 0 else "warning" if index_audit["warnings"] > 0 else "ok"

    return PerformanceSummary(
        status=status,
        database=database_counts,
        latest_slow_requests=list(latest_slow_requests),
        index_audit=index_audit,
    )
