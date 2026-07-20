"""One-shot, read-only diagnostic sweep used by GET /admin/system-check.
Every check here only reads and reports - none of them repair or mutate
anything. Meant as a quick "is this deployment healthy and internally
consistent" answer, not a replacement for the more detailed admin pages
(card audit, refresh runs, workflow runs, backup) it summarizes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.env import is_development_environment
from app.models import (
    AnalyticsDigestReport,
    Card,
    CollectionItem,
    FileJob,
    GradingSubmission,
    MarketIntelligenceReport,
    MarketSignalEvent,
    MarketWorkflowRun,
    PortfolioValuationSnapshot,
    PriceObservation,
    Source,
    SourceCardMapping,
    WishlistItem,
)
from app.services.backup import MODEL_BY_TABLE, REQUIRED_TABLES
from app.services.cache import redis_ping
from app.services.file_job_storage import is_storage_writable
from app.services.job_locks import get_active_locks
from app.settings import settings

# A file_job stuck in 'running' this long is likely wedged (crashed
# BackgroundTasks, worker restart mid-job, ...) rather than genuinely still
# working - see 'Large import/export jobs' in docs/operations.md.
STALE_RUNNING_FILE_JOB_HOURS = 2

STATUSES = ("pass", "warning", "fail")
SEVERITIES = ("info", "warning", "critical")

REQUIRED_SOURCE_NAMES = ("yuyutei", "snkrdunk")


@dataclass
class CheckResult:
    name: str
    status: str
    severity: str
    message: str


def _orphan_count(db: Session, fk_column, ref_column) -> int:
    """Counts rows whose fk_column doesn't match any value in ref_column.
    NULL fk values are always excluded (a NULL is "no reference", not a
    broken one) - this can't be left to SQL's three-valued `x NOT IN (...)`
    logic alone, since that degenerates to TRUE for every row, NULL
    included, whenever ref_column's table happens to be completely empty
    (e.g. a fresh install with zero cards)."""
    return db.scalar(
        select(func.count())
        .select_from(fk_column.table)
        .where(fk_column.is_not(None), ~fk_column.in_(select(ref_column)))
    ) or 0


def _check_database_reachable(db: Session) -> CheckResult:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        return CheckResult(
            "database_reachable", "fail", "critical", f"Database not reachable: {exc}"
        )
    return CheckResult("database_reachable", "pass", "critical", "Database reachable.")


def _check_required_sources(db: Session) -> CheckResult:
    try:
        names = set(db.scalars(select(Source.name)).all())
    except SQLAlchemyError as exc:
        return CheckResult(
            "required_sources", "fail", "critical", f"Could not read sources table: {exc}"
        )
    missing = [s for s in REQUIRED_SOURCE_NAMES if s not in names]
    if missing:
        return CheckResult(
            "required_sources",
            "fail",
            "critical",
            f"Missing required source(s): {', '.join(missing)}.",
        )
    return CheckResult(
        "required_sources", "pass", "critical", "yuyutei and snkrdunk sources are present."
    )


def _check_table_count(db: Session, model, name: str, label: str) -> CheckResult:
    try:
        count = db.scalar(select(func.count()).select_from(model)) or 0
    except SQLAlchemyError as exc:
        return CheckResult(name, "warning", "warning", f"{label} table not available: {exc}")
    return CheckResult(name, "pass", "info", f"{label}: {count} row(s).")


def _check_latest_timestamp(
    db: Session, model, column, name: str, label: str
) -> CheckResult:
    latest = db.scalar(select(func.max(column)))
    if latest is None:
        return CheckResult(name, "warning", "warning", f"No {label} recorded yet.")
    return CheckResult(name, "pass", "info", f"Latest {label}: {latest.isoformat()}.")


def _check_latest_workflow_run(db: Session) -> CheckResult:
    run = db.scalar(
        select(MarketWorkflowRun).order_by(MarketWorkflowRun.started_at.desc()).limit(1)
    )
    if run is None:
        return CheckResult("latest_workflow_run", "warning", "warning", "No workflow runs yet.")
    if run.status == "failed":
        return CheckResult(
            "latest_workflow_run",
            "warning",
            "warning",
            f"Latest workflow run (#{run.id}) failed: {run.error_message or 'no error message'}.",
        )
    return CheckResult(
        "latest_workflow_run", "pass", "info", f"Latest workflow run (#{run.id}): {run.status}."
    )


def _check_backup_tables_included(_db: Session) -> CheckResult:
    missing = [t for t in REQUIRED_TABLES if t not in MODEL_BY_TABLE]
    if missing:
        return CheckResult(
            "backup_tables_included",
            "fail",
            "critical",
            f"Required table(s) missing from backup/restore: {', '.join(missing)}.",
        )
    return CheckResult(
        "backup_tables_included",
        "pass",
        "critical",
        f"All {len(REQUIRED_TABLES)} required tables are covered by backup/restore.",
    )


def _check_search_responds(db: Session) -> CheckResult:
    # Imported lazily to avoid a module-level import cycle (search.py doesn't
    # import this module, but keeping the dependency direction explicit here
    # is cheap and avoids ever having to think about it).
    from app.services.search import search as run_search

    try:
        run_search(db, "system-check", limit=1)
    except Exception as exc:  # noqa: BLE001 - this is a health check, any failure is reportable
        return CheckResult(
            "search_responds", "fail", "critical", f"Search service raised an error: {exc}"
        )
    return CheckResult("search_responds", "pass", "critical", "Search service responded.")


def _check_orphan_fk(
    db: Session, fk_column, ref_column, name: str, label: str
) -> CheckResult:
    count = _orphan_count(db, fk_column, ref_column)
    if count > 0:
        return CheckResult(
            name,
            "fail",
            "critical",
            f"{count} {label} row(s) reference a missing id.",
        )
    return CheckResult(name, "pass", "critical", f"No {label} rows reference a missing id.")


def _naive(dt: datetime) -> datetime:
    """Strips tzinfo if present, so a loaded JobLock.expires_at (naive under
    SQLite, aware under Postgres - see app.services.job_locks._naive) can be
    safely compared against datetime.now(timezone.utc) under either dialect."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _check_active_job_locks(db: Session) -> CheckResult:
    """Just a count, informational - one or two active locks (a refresh or
    workflow genuinely in progress) is normal, not itself a problem. See
    _check_expired_job_locks and _check_market_workflow_lock_ttl below for
    the checks that actually flag something as wrong."""
    count = len(get_active_locks())
    return CheckResult("active_job_locks", "pass", "info", f"{count} active job lock(s).")


def _check_expired_job_locks(db: Session) -> CheckResult:
    """A lock whose expires_at has passed but is still marked 'active' means
    either the job crashed without releasing it, or nothing has called GET
    /admin/job-locks/cleanup-expired since it lapsed - either way, it's
    worth a human glancing at GET /admin/job-locks (see 'Worker job
    concurrency locking' in docs/operations.md)."""
    now = _naive(datetime.now(timezone.utc))
    expired = [lock for lock in get_active_locks() if _naive(lock.expires_at) <= now]
    if expired:
        names = ", ".join(sorted({lock.lock_name for lock in expired}))
        return CheckResult(
            "expired_job_locks",
            "warning",
            "warning",
            f"{len(expired)} active lock(s) are past their expires_at and likely stale: {names}.",
        )
    return CheckResult("expired_job_locks", "pass", "info", "No expired-but-active job locks.")


def _check_market_workflow_lock_ttl(db: Session) -> CheckResult:
    """market_workflow is the longest-running, highest-TTL lock (60 minutes)
    and the one most likely to indicate a genuinely stuck job if it
    overruns - called out as its own check (on top of the general
    expired_job_locks check above) since a stuck market_workflow run blocks
    every scheduled/manual workflow trigger behind it."""
    now = _naive(datetime.now(timezone.utc))
    lock = next(
        (row for row in get_active_locks() if row.lock_name == "market_workflow"), None
    )
    if lock is None:
        return CheckResult(
            "market_workflow_lock_ttl", "pass", "info", "No active market_workflow lock."
        )
    if _naive(lock.expires_at) <= now:
        return CheckResult(
            "market_workflow_lock_ttl",
            "warning",
            "warning",
            f"market_workflow lock has been active since {lock.acquired_at.isoformat()} and is "
            "past its expected TTL - the run may be stuck. See GET /admin/job-locks.",
        )
    return CheckResult(
        "market_workflow_lock_ttl",
        "pass",
        "info",
        f"market_workflow lock active since {lock.acquired_at.isoformat()}, within its TTL.",
    )


def _check_cache_backend(_db: Session) -> CheckResult:
    """Read-only reachability check for app.services.cache - see 'Cache
    operations' in docs/operations.md. Only CACHE_BACKEND=redis actually
    checks anything live; memory/none are reported based on environment
    alone, matching how app.services.cache itself only ever falls back to
    memory in development (see cache._handle_backend_failure)."""
    if not settings.CACHE_ENABLED:
        return CheckResult("cache_backend", "pass", "info", "Caching disabled (CACHE_ENABLED=false).")

    backend = (settings.CACHE_BACKEND or "redis").strip().lower()
    if backend == "none":
        return CheckResult("cache_backend", "pass", "info", "Caching disabled (CACHE_BACKEND=none).")
    if backend == "memory":
        if is_development_environment():
            return CheckResult(
                "cache_backend", "pass", "info", "Using in-memory cache backend (development)."
            )
        return CheckResult(
            "cache_backend",
            "warning",
            "warning",
            "CACHE_BACKEND=memory in a non-development environment - the cache is "
            "per-process and not shared across instances/workers.",
        )

    if redis_ping():
        return CheckResult("cache_backend", "pass", "info", "Redis cache backend reachable.")
    return CheckResult(
        "cache_backend",
        "warning",
        "warning",
        "CACHE_ENABLED with CACHE_BACKEND=redis but Redis is unreachable - reads are "
        "falling back to uncached (or, in development only, an in-memory cache).",
    )


def _check_file_job_storage(_db: Session) -> CheckResult:
    if is_storage_writable():
        return CheckResult(
            "file_job_storage_writable", "pass", "info", "File job storage directory is writable."
        )
    return CheckResult(
        "file_job_storage_writable",
        "warning",
        "warning",
        "File job storage directory (settings.FILE_JOB_STORAGE_DIR) is not writable - "
        "background import/export jobs will fail.",
    )


def _check_stale_running_file_jobs(db: Session) -> CheckResult:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STALE_RUNNING_FILE_JOB_HOURS)
    stale_count = (
        db.scalar(
            select(func.count())
            .select_from(FileJob)
            .where(FileJob.status == "running", FileJob.started_at < cutoff)
        )
        or 0
    )
    if stale_count > 0:
        return CheckResult(
            "stale_running_file_jobs",
            "warning",
            "warning",
            f"{stale_count} file job(s) have been 'running' for over "
            f"{STALE_RUNNING_FILE_JOB_HOURS}h and are likely stuck. See GET /file-jobs?status=running.",
        )
    return CheckResult(
        "stale_running_file_jobs", "pass", "info", "No long-running file jobs detected."
    )


def run_system_check(db: Session) -> list[CheckResult]:
    checks: list[CheckResult] = [
        _check_database_reachable(db),
        _check_required_sources(db),
        _check_table_count(db, Card, "cards_count", "Cards"),
        _check_table_count(db, CollectionItem, "collection_items_count", "Collection items"),
        _check_table_count(db, WishlistItem, "wishlist_items_count", "Wishlist items"),
        _check_table_count(
            db, GradingSubmission, "grading_submissions_count", "Grading submissions"
        ),
        _check_latest_timestamp(
            db,
            PriceObservation,
            PriceObservation.observed_at,
            "latest_price_observation",
            "price observation",
        ),
        _check_latest_timestamp(
            db,
            PortfolioValuationSnapshot,
            PortfolioValuationSnapshot.created_at,
            "latest_portfolio_snapshot",
            "portfolio valuation snapshot",
        ),
        _check_latest_timestamp(
            db,
            MarketIntelligenceReport,
            MarketIntelligenceReport.created_at,
            "latest_market_report",
            "market intelligence report",
        ),
        _check_latest_timestamp(
            db,
            AnalyticsDigestReport,
            AnalyticsDigestReport.created_at,
            "latest_analytics_digest",
            "analytics digest",
        ),
        _check_latest_workflow_run(db),
        _check_backup_tables_included(db),
        _check_search_responds(db),
        _check_orphan_fk(
            db,
            SourceCardMapping.card_id,
            Card.id,
            "source_mappings_valid_card_id",
            "source_card_mappings",
        ),
        _check_orphan_fk(
            db, CollectionItem.card_id, Card.id, "collection_items_valid_card_id", "collection_items"
        ),
        _check_orphan_fk(
            db, WishlistItem.card_id, Card.id, "wishlist_items_valid_card_id", "wishlist_items"
        ),
        _check_orphan_fk(
            db,
            GradingSubmission.collection_item_id,
            CollectionItem.id,
            "grading_submissions_valid_collection_item_id",
            "grading_submissions",
        ),
        _check_orphan_fk(
            db,
            MarketSignalEvent.card_id,
            Card.id,
            "market_signal_events_valid_card_id",
            "market_signal_events",
        ),
        _check_active_job_locks(db),
        _check_expired_job_locks(db),
        _check_market_workflow_lock_ttl(db),
        _check_cache_backend(db),
        _check_file_job_storage(db),
        _check_stale_running_file_jobs(db),
    ]
    return checks


def overall_status(checks: list[CheckResult]) -> str:
    if any(c.status == "fail" for c in checks):
        return "critical"
    if any(c.status == "warning" for c in checks):
        return "warning"
    return "ok"
