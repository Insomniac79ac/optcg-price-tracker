"""Data retention and pruning, run on a schedule by Celery Beat when
DATA_RETENTION_ENABLED=true (see worker.celery_app's prune-data-retention
task and "Data retention and pruning" in docs/operations.md).

Mirrors app.services.data_retention on the api service - same policy, same
table list, same protections (latest price_observation per card/source/
price_type never deleted; open/watching market_signal_events never
deleted; collector records - cards, collection_items, wishlist_items,
grading_submissions, collector_tags/groups/notes, alert_rules,
dashboard_preferences - never touched at all). Kept as a separate
implementation against worker.models rather than importing from the api
service, matching how this worker already keeps its own mirrored copy of
every model it needs (see worker/models.py) instead of depending on the api
package - the two services are deployed as separate images with no shared
Python code today.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from worker.models import (
    AppLogEvent,
    CollectorActivityEvent,
    MarketIntelligenceReport,
    MarketReportDigestSend,
    MarketSignalEvent,
    MarketWorkflowRun,
    PortfolioValuationSnapshot,
    PriceObservation,
    PriceRefreshRun,
    RawSnapshot,
)

CONFIRM_PHRASE = "PRUNE"
THINNING_FRESH_WINDOW_DAYS = 90
IMPORTANT_LOG_LEVELS = ("error", "critical")


class PruneConfirmationRequired(ValueError):
    pass


@dataclass
class RetentionPolicy:
    table: str
    retention_days: int
    mode: str
    protected_records: str
    enabled: bool = True


POLICIES: dict[str, RetentionPolicy] = {
    "raw_snapshots": RetentionPolicy("raw_snapshots", 30, "delete_old_rows", "none"),
    "app_log_events": RetentionPolicy(
        "app_log_events", 60, "delete_old_rows_keep_errors_180d",
        "error/critical logs kept 180 days",
    ),
    "collector_activity_events": RetentionPolicy(
        "collector_activity_events", 365, "delete_old_rows", "none"
    ),
    "price_refresh_runs": RetentionPolicy("price_refresh_runs", 180, "delete_old_rows", "none"),
    "market_workflow_runs": RetentionPolicy("market_workflow_runs", 180, "delete_old_rows", "none"),
    "market_report_digest_sends": RetentionPolicy(
        "market_report_digest_sends", 180, "delete_old_rows", "none"
    ),
    "market_intelligence_reports": RetentionPolicy(
        "market_intelligence_reports", 365, "delete_old_rows", "none"
    ),
    "portfolio_valuation_snapshots": RetentionPolicy(
        "portfolio_valuation_snapshots", 365, "delete_old_rows_with_weekly_thinning",
        "one snapshot per ISO week kept beyond 90 days",
    ),
    "price_observations": RetentionPolicy(
        "price_observations", 365, "delete_old_rows_with_daily_thinning_protect_latest",
        "latest observation per card/source/price_type",
    ),
    "market_signal_events": RetentionPolicy(
        "market_signal_events", 365, "delete_old_dismissed_resolved", "open/watching events"
    ),
}

PRUNABLE_TABLES: tuple[str, ...] = (
    "raw_snapshots",
    "app_log_events",
    "collector_activity_events",
    "price_refresh_runs",
    "market_workflow_runs",
    "market_report_digest_sends",
    "market_intelligence_reports",
    "portfolio_valuation_snapshots",
    "price_observations",
    "market_signal_events",
)


@dataclass
class TablePruneResult:
    table: str
    retention_days: int | None
    rows_would_delete: int
    rows_deleted: int = 0
    status: str = "ok"
    warning: str | None = None


@dataclass
class PruneRunResult:
    dry_run: bool
    results: list[TablePruneResult] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        return {
            "tables_checked": len(self.results),
            "total_rows_would_delete": sum(r.rows_would_delete for r in self.results),
            "total_rows_deleted": sum(r.rows_deleted for r in self.results),
            "warnings": sum(1 for r in self.results if r.status != "ok"),
        }


def _cutoff(now: datetime, days: int) -> datetime:
    return now - timedelta(days=days)


def _simple_cutoff_ids(db: Session, model, date_column, days: int, now: datetime) -> list[int]:
    cutoff = _cutoff(now, days)
    return list(db.scalars(select(model.id).where(date_column < cutoff)))


def _app_log_events_candidate_ids(db: Session, now: datetime) -> list[int]:
    policy = POLICIES["app_log_events"]
    cutoff_default = _cutoff(now, policy.retention_days)
    cutoff_important = _cutoff(now, 180)
    return list(
        db.scalars(
            select(AppLogEvent.id).where(
                AppLogEvent.created_at < cutoff_default,
                (AppLogEvent.level.notin_(IMPORTANT_LOG_LEVELS))
                | (AppLogEvent.created_at < cutoff_important),
            )
        )
    )


def _market_signal_events_candidate_ids(db: Session, now: datetime) -> list[int]:
    policy = POLICIES["market_signal_events"]
    cutoff = _cutoff(now, policy.retention_days)
    return list(
        db.scalars(
            select(MarketSignalEvent.id).where(
                MarketSignalEvent.status.in_(("dismissed", "resolved")),
                MarketSignalEvent.last_seen_at < cutoff,
            )
        )
    )


def _protected_price_observation_ids(db: Session) -> set[int]:
    row_number = (
        func.row_number()
        .over(
            partition_by=(
                PriceObservation.card_id,
                PriceObservation.source_id,
                PriceObservation.price_type,
            ),
            order_by=PriceObservation.observed_at.desc(),
        )
        .label("rn")
    )
    ranked = select(PriceObservation.id, row_number).subquery()
    return set(db.scalars(select(ranked.c.id).where(ranked.c.rn == 1)).all())


def _price_observations_candidate_ids(db: Session, now: datetime) -> list[int]:
    policy = POLICIES["price_observations"]
    hard_cutoff = _cutoff(now, policy.retention_days)
    fresh_cutoff = _cutoff(now, THINNING_FRESH_WINDOW_DAYS)
    protected_ids = _protected_price_observation_ids(db)

    candidate_ids: list[int] = []

    hard_delete_ids = db.scalars(
        select(PriceObservation.id).where(PriceObservation.observed_at < hard_cutoff)
    ).all()
    candidate_ids.extend(i for i in hard_delete_ids if i not in protected_ids)

    thinning_rows = db.execute(
        select(
            PriceObservation.id,
            PriceObservation.card_id,
            PriceObservation.source_id,
            PriceObservation.price_type,
            PriceObservation.observed_at,
        ).where(
            PriceObservation.observed_at >= hard_cutoff,
            PriceObservation.observed_at < fresh_cutoff,
        )
    ).all()

    by_day_group: dict[tuple[int, int, str, object], list[tuple[int, datetime]]] = defaultdict(list)
    for row_id, card_id, source_id, price_type, observed_at in thinning_rows:
        key = (card_id, source_id, price_type, observed_at.date())
        by_day_group[key].append((row_id, observed_at))

    for rows in by_day_group.values():
        if len(rows) <= 1:
            continue
        rows.sort(key=lambda r: r[1])
        candidate_ids.extend(row_id for row_id, _observed_at in rows[1:] if row_id not in protected_ids)

    return candidate_ids


def _iso_week_key(dt: datetime) -> tuple[int, int]:
    iso = dt.isocalendar()
    return (iso[0], iso[1])


def _portfolio_valuation_snapshots_candidate_ids(db: Session, now: datetime) -> list[int]:
    policy = POLICIES["portfolio_valuation_snapshots"]
    hard_cutoff = _cutoff(now, policy.retention_days)
    fresh_cutoff = _cutoff(now, THINNING_FRESH_WINDOW_DAYS)

    candidate_ids: list[int] = list(
        db.scalars(
            select(PortfolioValuationSnapshot.id).where(
                PortfolioValuationSnapshot.created_at < hard_cutoff
            )
        )
    )

    thinning_rows = db.execute(
        select(PortfolioValuationSnapshot.id, PortfolioValuationSnapshot.created_at).where(
            PortfolioValuationSnapshot.created_at >= hard_cutoff,
            PortfolioValuationSnapshot.created_at < fresh_cutoff,
        )
    ).all()

    by_week: dict[tuple[int, int], list[tuple[int, datetime]]] = defaultdict(list)
    for row_id, created_at in thinning_rows:
        by_week[_iso_week_key(created_at)].append((row_id, created_at))

    for rows in by_week.values():
        if len(rows) <= 1:
            continue
        rows.sort(key=lambda r: r[1])
        candidate_ids.extend(row_id for row_id, _created_at in rows[1:])

    return candidate_ids


_CANDIDATE_ID_FUNCS = {
    "raw_snapshots": lambda db, now: _simple_cutoff_ids(
        db, RawSnapshot, RawSnapshot.fetched_at, POLICIES["raw_snapshots"].retention_days, now
    ),
    "app_log_events": _app_log_events_candidate_ids,
    "collector_activity_events": lambda db, now: _simple_cutoff_ids(
        db,
        CollectorActivityEvent,
        CollectorActivityEvent.created_at,
        POLICIES["collector_activity_events"].retention_days,
        now,
    ),
    "price_refresh_runs": lambda db, now: _simple_cutoff_ids(
        db,
        PriceRefreshRun,
        PriceRefreshRun.started_at,
        POLICIES["price_refresh_runs"].retention_days,
        now,
    ),
    "market_workflow_runs": lambda db, now: _simple_cutoff_ids(
        db,
        MarketWorkflowRun,
        MarketWorkflowRun.started_at,
        POLICIES["market_workflow_runs"].retention_days,
        now,
    ),
    "market_report_digest_sends": lambda db, now: _simple_cutoff_ids(
        db,
        MarketReportDigestSend,
        MarketReportDigestSend.created_at,
        POLICIES["market_report_digest_sends"].retention_days,
        now,
    ),
    "market_intelligence_reports": lambda db, now: _simple_cutoff_ids(
        db,
        MarketIntelligenceReport,
        MarketIntelligenceReport.created_at,
        POLICIES["market_intelligence_reports"].retention_days,
        now,
    ),
    "portfolio_valuation_snapshots": _portfolio_valuation_snapshots_candidate_ids,
    "price_observations": _price_observations_candidate_ids,
    "market_signal_events": _market_signal_events_candidate_ids,
}

_MODEL_BY_TABLE = {
    "raw_snapshots": RawSnapshot,
    "app_log_events": AppLogEvent,
    "collector_activity_events": CollectorActivityEvent,
    "price_refresh_runs": PriceRefreshRun,
    "market_workflow_runs": MarketWorkflowRun,
    "market_report_digest_sends": MarketReportDigestSend,
    "market_intelligence_reports": MarketIntelligenceReport,
    "portfolio_valuation_snapshots": PortfolioValuationSnapshot,
    "price_observations": PriceObservation,
    "market_signal_events": MarketSignalEvent,
}


def prune_tables(
    db: Session,
    *,
    dry_run: bool = True,
    tables: list[str] | None = None,
    confirm: str | None = None,
    now: datetime | None = None,
) -> PruneRunResult:
    if not dry_run and confirm != CONFIRM_PHRASE:
        raise PruneConfirmationRequired(f"dry_run=false requires confirm={CONFIRM_PHRASE!r}.")

    now = now or datetime.now(timezone.utc)

    requested = list(tables) if tables else list(PRUNABLE_TABLES)
    requested_set = set(requested)
    ordered = [t for t in PRUNABLE_TABLES if t in requested_set]

    results: list[TablePruneResult] = []

    for table in [t for t in requested if t not in PRUNABLE_TABLES]:
        results.append(
            TablePruneResult(
                table=table,
                retention_days=None,
                rows_would_delete=0,
                rows_deleted=0,
                status="skipped",
                warning="Unknown or protected table - not eligible for pruning.",
            )
        )

    for table in ordered:
        policy = POLICIES[table]
        try:
            candidate_ids = _CANDIDATE_ID_FUNCS[table](db, now)
            rows_would_delete = len(candidate_ids)
            rows_deleted = 0

            if not dry_run and candidate_ids:
                model = _MODEL_BY_TABLE[table]
                db.execute(delete(model).where(model.id.in_(candidate_ids)))
                db.commit()
                rows_deleted = rows_would_delete

            results.append(
                TablePruneResult(
                    table=table,
                    retention_days=policy.retention_days,
                    rows_would_delete=rows_would_delete,
                    rows_deleted=rows_deleted,
                    status="ok",
                )
            )
        except Exception as exc:  # noqa: BLE001 - one table's failure must not stop the rest
            db.rollback()
            results.append(
                TablePruneResult(
                    table=table,
                    retention_days=policy.retention_days,
                    rows_would_delete=0,
                    rows_deleted=0,
                    status="error",
                    warning=str(exc),
                )
            )

    return PruneRunResult(dry_run=dry_run, results=results)
