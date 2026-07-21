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
    ImportValidationReport,
    MarketIntelligenceReport,
    MarketSignalEvent,
    MarketWorkflowRun,
    PortfolioValuationSnapshot,
    PriceObservation,
    Source,
    SourceCardMapping,
    WishlistItem,
)
from app.models.snkrdunk_candidate import SnkrdunkCandidate
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

# If at least this share of candidates need a human decision (ambiguous or
# unmatched), matching quality is degrading enough to flag - see
# _check_candidate_match_backlog. Only evaluated once there's a meaningful
# sample (MIN_CANDIDATES_FOR_BACKLOG_CHECK), so a handful of fresh imports
# doesn't trip this on a near-empty table.
CANDIDATE_BACKLOG_WARNING_RATIO = 0.5
MIN_CANDIDATES_FOR_BACKLOG_CHECK = 10

# See _check_recent_failed_import_validation_reports - this many (or more)
# failed POST /admin/import-validation/{import_type} calls within the
# lookback window suggests a source file (or the process producing it) is
# systematically broken, not just one bad upload.
IMPORT_VALIDATION_FAILURE_LOOKBACK_DAYS = 7
IMPORT_VALIDATION_FAILURE_COUNT_THRESHOLD = 3


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


def _check_candidate_match_backlog(db: Session) -> CheckResult:
    total = db.scalar(select(func.count()).select_from(SnkrdunkCandidate)) or 0
    if total < MIN_CANDIDATES_FOR_BACKLOG_CHECK:
        return CheckResult(
            "candidate_match_backlog",
            "pass",
            "info",
            f"Only {total} SNKRDUNK candidate(s) - too few to evaluate match backlog.",
        )

    needs_review = (
        db.scalar(
            select(func.count())
            .select_from(SnkrdunkCandidate)
            .where(SnkrdunkCandidate.match_status.in_(("ambiguous", "unmatched")))
        )
        or 0
    )
    ratio = needs_review / total
    if ratio >= CANDIDATE_BACKLOG_WARNING_RATIO:
        return CheckResult(
            "candidate_match_backlog",
            "warning",
            "warning",
            f"{needs_review}/{total} SNKRDUNK candidates ({ratio:.0%}) are ambiguous or "
            "unmatched. See GET /admin/snkrdunk-candidates/rematch-all or review manually.",
        )
    return CheckResult(
        "candidate_match_backlog",
        "pass",
        "info",
        f"{needs_review}/{total} SNKRDUNK candidates ({ratio:.0%}) are ambiguous or unmatched.",
    )


def _check_low_confidence_source_mappings(db: Session) -> CheckResult:
    # Kept in sync with app.services.card_audit's identically-named
    # threshold and scale-normalization logic (imported, not duplicated) -
    # see that module's docstring on _match_confidence_as_score for why
    # match_confidence isn't a single consistent scale.
    from app.services.card_audit import LOW_MATCH_CONFIDENCE_THRESHOLD, _match_confidence_as_score

    mappings = db.scalars(
        select(SourceCardMapping).where(SourceCardMapping.match_confidence.isnot(None))
    ).all()
    low_confidence_count = sum(
        1 for m in mappings if _match_confidence_as_score(m.match_confidence) < LOW_MATCH_CONFIDENCE_THRESHOLD
    )
    if low_confidence_count > 0:
        return CheckResult(
            "low_confidence_source_mappings",
            "warning",
            "warning",
            f"{low_confidence_count} source_card_mappings row(s) have a match confidence below "
            f"{LOW_MATCH_CONFIDENCE_THRESHOLD}/100. See GET /admin/card-audit.",
        )
    return CheckResult(
        "low_confidence_source_mappings", "pass", "info", "No low-confidence source mappings."
    )


# Number of mapping-quality "low_confidence" issues (see
# app.services.source_mapping_confidence) that's worth a system-check
# warning on its own, separate from _check_low_confidence_source_mappings'
# older/narrower match_confidence-only check above.
MAPPING_QUALITY_LOW_CONFIDENCE_COUNT_THRESHOLD = 5


def _check_mapping_quality_summary(db: Session) -> CheckResult:
    """Rolls up app.services.source_mapping_confidence.summarize_mapping_quality
    into one system-check warning: any critical-risk mapping, more than
    MAPPING_QUALITY_LOW_CONFIDENCE_COUNT_THRESHOLD low-confidence mappings,
    or any near-duplicate source URL is worth a human glancing at GET
    /admin/source-mappings/quality."""
    from app.services.source_mapping_confidence import summarize_mapping_quality

    summary = summarize_mapping_quality(db)
    reasons = []
    if summary["critical_count"] > 0:
        reasons.append(f"{summary['critical_count']} critical-risk mapping(s)")
    if summary["low_confidence_count"] > MAPPING_QUALITY_LOW_CONFIDENCE_COUNT_THRESHOLD:
        reasons.append(f"{summary['low_confidence_count']} low-confidence mapping(s)")
    if summary["duplicate_source_url_count"] > 0:
        reasons.append(f"{summary['duplicate_source_url_count']} duplicate source URL(s)")

    if reasons:
        return CheckResult(
            "mapping_quality_summary",
            "warning",
            "warning",
            f"Source mapping quality needs review: {', '.join(reasons)}. "
            "See GET /admin/source-mappings/quality.",
        )
    return CheckResult(
        "mapping_quality_summary", "pass", "info", "Source mapping quality looks healthy."
    )


def _check_duplicate_cards(db: Session) -> CheckResult:
    """Rolls up app.services.card_identity_merge.summarize_duplicate_quality
    into one system-check warning - any exact or likely duplicate pair is
    worth a human glancing at GET /admin/cards/duplicates."""
    from app.services.card_identity_merge import summarize_duplicate_quality

    summary = summarize_duplicate_quality(db)
    reasons = []
    if summary["exact_duplicate_count"] > 0:
        reasons.append(f"{summary['exact_duplicate_count']} exact duplicate pair(s)")
    if summary["likely_duplicate_count"] > 0:
        reasons.append(f"{summary['likely_duplicate_count']} likely duplicate pair(s)")

    if reasons:
        return CheckResult(
            "duplicate_cards",
            "warning",
            "warning",
            f"Potential duplicate cards found: {', '.join(reasons)}. See GET /admin/cards/duplicates.",
        )
    return CheckResult(
        "duplicate_cards", "pass", "info", "No exact/likely duplicate cards detected."
    )


def _check_inactive_cards_missing_merge_target(db: Session) -> CheckResult:
    count = (
        db.scalar(
            select(func.count())
            .select_from(Card)
            .where(Card.is_active.is_(False), Card.merged_into_card_id.is_(None))
        )
        or 0
    )
    if count > 0:
        return CheckResult(
            "inactive_cards_missing_merge_target",
            "warning",
            "warning",
            f"{count} inactive card(s) have no merged_into_card_id set. See GET /admin/card-audit.",
        )
    return CheckResult(
        "inactive_cards_missing_merge_target",
        "pass",
        "info",
        "All inactive cards have a merge target set.",
    )


# Below these thresholds, catalog coverage is degraded enough to be worth a
# system-check warning - see _check_catalog_coverage_summary and 'Catalog
# coverage workflow' in docs/operations.md.
CATALOG_COVERAGE_MAPPING_WARNING_PCT = 50.0
CATALOG_COVERAGE_RECENT_PRICE_WARNING_PCT = 50.0
CATALOG_COVERAGE_METADATA_WARNING_PCT = 70.0


def _check_catalog_coverage_summary(db: Session) -> CheckResult:
    """Rolls up app.services.catalog_coverage.summarize_catalog_coverage into
    one system-check warning - low mapping/recent-price/metadata coverage,
    or any duplicate/mapping-quality risk, is worth a human glancing at GET
    /admin/catalog-coverage."""
    from app.services.catalog_coverage import summarize_catalog_coverage

    summary = summarize_catalog_coverage(db)
    reasons = []
    if summary["mapping_coverage_pct"] < CATALOG_COVERAGE_MAPPING_WARNING_PCT:
        reasons.append(
            f"mapping coverage {summary['mapping_coverage_pct']}% "
            f"({summary['cards_without_any_mapping']} unmapped card(s))"
        )
    if summary["recent_price_coverage_pct"] < CATALOG_COVERAGE_RECENT_PRICE_WARNING_PCT:
        reasons.append(
            f"recent price coverage {summary['recent_price_coverage_pct']}% "
            f"({summary['cards_without_recent_price']} card(s) without a recent price)"
        )
    if summary["metadata_completion_pct"] < CATALOG_COVERAGE_METADATA_WARNING_PCT:
        reasons.append(f"metadata completion {summary['metadata_completion_pct']}%")
    if summary["cards_with_duplicate_risk"] > 0:
        reasons.append(f"{summary['cards_with_duplicate_risk']} card(s) with duplicate risk")
    if summary["cards_with_mapping_quality_risk"] > 0:
        reasons.append(f"{summary['cards_with_mapping_quality_risk']} card(s) with mapping quality risk")

    if reasons:
        return CheckResult(
            "catalog_coverage_summary",
            "warning",
            "warning",
            f"Catalog coverage needs review: {'; '.join(reasons)}. See GET /admin/catalog-coverage.",
        )
    return CheckResult(
        "catalog_coverage_summary",
        "pass",
        "info",
        f"Catalog coverage looks healthy: mapping {summary['mapping_coverage_pct']}%, "
        f"recent price {summary['recent_price_coverage_pct']}%, "
        f"metadata {summary['metadata_completion_pct']}%.",
    )


# Below these thresholds, price source health is degraded enough to be
# worth a system-check warning - see _check_price_source_health_summary and
# 'Price source health workflow' in docs/operations.md.
PRICE_SOURCE_HEALTH_SUCCESS_RATE_WARNING_PCT = 80.0
PRICE_SOURCE_HEALTH_MISSING_PRICE_WARNING_PCT = 20.0
PRICE_SOURCE_HEALTH_STALE_PRICE_WARNING_PCT = 20.0


def _check_price_source_health_summary(db: Session) -> CheckResult:
    """Rolls up app.services.price_source_health.summarize_price_source_health
    into one system-check warning - a blocked/error source, a low refresh
    success rate, or a lot of stale/missing prices is worth a human glancing
    at GET /admin/price-source-health."""
    from app.services.price_source_health import summarize_price_source_health

    summary = summarize_price_source_health(db)
    reasons = []
    if summary["blocked_source_count"] > 0:
        reasons.append(f"{summary['blocked_source_count']} blocked source(s)")
    if summary["error_source_count"] > 0:
        reasons.append(f"{summary['error_source_count']} source(s) in error")
    if summary["recent_refresh_success_rate_pct"] < PRICE_SOURCE_HEALTH_SUCCESS_RATE_WARNING_PCT:
        reasons.append(f"recent refresh success rate {summary['recent_refresh_success_rate_pct']}%")
    total = summary["total_active_mappings"]
    missing_pct = (summary["mappings_without_recent_price"] / total * 100) if total else 0.0
    if missing_pct > PRICE_SOURCE_HEALTH_MISSING_PRICE_WARNING_PCT:
        reasons.append(
            f"{summary['mappings_without_recent_price']} mapping(s) without a recent price "
            f"({round(missing_pct, 2)}%)"
        )
    stale_pct = (summary["stale_price_count"] / total * 100) if total else 0.0
    if stale_pct > PRICE_SOURCE_HEALTH_STALE_PRICE_WARNING_PCT:
        reasons.append(f"{summary['stale_price_count']} stale price(s) ({round(stale_pct, 2)}%)")
    if summary["last_successful_refresh_at"] is None:
        reasons.append("no successful refresh recorded")

    if reasons:
        return CheckResult(
            "price_source_health_summary",
            "warning",
            "warning",
            f"Price source health needs review: {'; '.join(reasons)}. See GET /admin/price-source-health.",
        )
    return CheckResult(
        "price_source_health_summary",
        "pass",
        "info",
        f"Price source health looks healthy: recent refresh success rate "
        f"{summary['recent_refresh_success_rate_pct']}%.",
    )


def _check_latest_import_validation_report(db: Session) -> CheckResult:
    latest = db.scalar(
        select(ImportValidationReport).order_by(ImportValidationReport.created_at.desc()).limit(1)
    )
    if latest is None:
        return CheckResult(
            "latest_import_validation_report", "pass", "info", "No import validation reports yet."
        )
    if not latest.valid:
        return CheckResult(
            "latest_import_validation_report",
            "warning",
            "warning",
            f"Latest import validation report (#{latest.id}, {latest.import_type}) has "
            f"{latest.error_rows} error row(s). See GET /admin/import-validation/reports/{latest.id}.",
        )
    return CheckResult(
        "latest_import_validation_report",
        "pass",
        "info",
        f"Latest import validation report (#{latest.id}, {latest.import_type}) is valid.",
    )


def _check_recent_failed_import_validation_reports(db: Session) -> CheckResult:
    cutoff = datetime.now(timezone.utc) - timedelta(days=IMPORT_VALIDATION_FAILURE_LOOKBACK_DAYS)
    failed_count = (
        db.scalar(
            select(func.count())
            .select_from(ImportValidationReport)
            .where(ImportValidationReport.valid.is_(False), ImportValidationReport.created_at >= cutoff)
        )
        or 0
    )
    if failed_count >= IMPORT_VALIDATION_FAILURE_COUNT_THRESHOLD:
        return CheckResult(
            "recent_failed_import_validation_reports",
            "warning",
            "warning",
            f"{failed_count} import validation report(s) failed in the last "
            f"{IMPORT_VALIDATION_FAILURE_LOOKBACK_DAYS} day(s). See GET /admin/import-validation.",
        )
    return CheckResult(
        "recent_failed_import_validation_reports",
        "pass",
        "info",
        f"{failed_count} import validation report(s) failed in the last "
        f"{IMPORT_VALIDATION_FAILURE_LOOKBACK_DAYS} day(s).",
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
        _check_candidate_match_backlog(db),
        _check_low_confidence_source_mappings(db),
        _check_mapping_quality_summary(db),
        _check_duplicate_cards(db),
        _check_inactive_cards_missing_merge_target(db),
        _check_catalog_coverage_summary(db),
        _check_price_source_health_summary(db),
        _check_latest_import_validation_report(db),
        _check_recent_failed_import_validation_reports(db),
    ]
    return checks


def overall_status(checks: list[CheckResult]) -> str:
    if any(c.status == "fail" for c in checks):
        return "critical"
    if any(c.status == "warning" for c in checks):
        return "warning"
    return "ok"
