"""Assembles GET /admin/performance/summary: row counts for the tables most
likely to grow large (price_observations, raw_snapshots,
market_signal_events, collector_activity_events, app_log_events), the most
recent slow-request warnings recorded by app.core.request_timing, and a
rollup of the db-index-audit (see app.services.db_index_audit) - a single
page to check "is this deployment's data volume/query health still fine" as
those tables grow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AppLogEvent, CollectorActivityEvent, MarketSignalEvent, PriceObservation, RawSnapshot
from app.services.db_index_audit import audit_summary, run_db_index_audit
from app.services.job_locks import get_lock_counts

SLOW_REQUEST_EVENT_TYPE = "slow_request"
RESPONSE_SIZE_WARNING_EVENT_TYPE = "response_size_warning"
LATEST_SLOW_REQUESTS_LIMIT = 20
RECENT_RESPONSE_SIZE_WARNINGS_SCAN_LIMIT = 100
LARGEST_RECENT_RESPONSES_LIMIT = 5


@dataclass
class LargestResponse:
    created_at: datetime
    method: str | None
    path: str | None
    size_bytes: int | None


@dataclass
class PerformanceSummary:
    status: str
    database: dict[str, int]
    latest_slow_requests: list[AppLogEvent]
    index_audit: dict[str, int]
    response_size_warnings_last_24h: int = 0
    slow_requests_last_24h: int = 0
    largest_recent_responses: list[LargestResponse] = field(default_factory=list)
    active_job_locks: int = 0
    expired_job_locks: int = 0


def _table_count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def _count_since(db: Session, event_type: str, since: datetime) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(AppLogEvent)
            .where(AppLogEvent.event_type == event_type, AppLogEvent.created_at >= since)
        )
        or 0
    )


def _largest_recent_responses(db: Session) -> list[LargestResponse]:
    """Scans the most recent RECENT_RESPONSE_SIZE_WARNINGS_SCAN_LIMIT
    response_size_warning rows and returns the largest few by size_bytes -
    size isn't a queryable column (it lives in context_json), so this sorts
    a bounded recent window in Python rather than the whole table."""
    recent = db.scalars(
        select(AppLogEvent)
        .where(AppLogEvent.event_type == RESPONSE_SIZE_WARNING_EVENT_TYPE)
        .order_by(AppLogEvent.created_at.desc(), AppLogEvent.id.desc())
        .limit(RECENT_RESPONSE_SIZE_WARNINGS_SCAN_LIMIT)
    ).all()

    entries = [
        LargestResponse(
            created_at=e.created_at,
            method=(e.context_json or {}).get("method"),
            path=(e.context_json or {}).get("path"),
            size_bytes=(e.context_json or {}).get("size_bytes"),
        )
        for e in recent
    ]
    entries.sort(key=lambda entry: entry.size_bytes or 0, reverse=True)
    return entries[:LARGEST_RECENT_RESPONSES_LIMIT]


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

    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    lock_counts = get_lock_counts()

    return PerformanceSummary(
        status=status,
        database=database_counts,
        latest_slow_requests=list(latest_slow_requests),
        index_audit=index_audit,
        response_size_warnings_last_24h=_count_since(db, RESPONSE_SIZE_WARNING_EVENT_TYPE, since_24h),
        slow_requests_last_24h=_count_since(db, SLOW_REQUEST_EVENT_TYPE, since_24h),
        largest_recent_responses=_largest_recent_responses(db),
        active_job_locks=lock_counts.active,
        expired_job_locks=lock_counts.expired_active,
    )
