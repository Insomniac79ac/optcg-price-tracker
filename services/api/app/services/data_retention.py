"""Data retention and pruning for the highest-volume tables - see GET
/admin/data-retention/policy, POST /admin/data-retention/prune, and
python -m app.prune_data_retention (a CLI wrapper around the same logic, for
use without going through the API - e.g. a cron job on the deploy host).

Retention policy (see docs/operations.md "Data retention and pruning"):
never-pruned tables (cards, sources, source_card_mappings, collection_items,
wishlist_items, grading_submissions, collector_tags, collector_groups,
collector_notes, alert_rules, dashboard_preferences, users) simply never
appear in PRUNABLE_TABLES/POLICIES below - prune_tables() rejects any
table name that isn't in that whitelist, so there is no way to prune a
collector record by mistake.

Two tables additionally thin (rather than only hard-delete) rather than
losing all history past their retention window:
- price_observations: keeps every observation from the last 90 days as-is,
  thins anything older to at most one row per (series, day), and never
  deletes the single latest observation per series no matter how old it is -
  a print that stopped getting price updates keeps its last known price
  forever instead of going priceless. "Series" here is exact-print aware:
  see _series_identity below.
- portfolio_valuation_snapshots: keeps every snapshot from the last 90 days,
  thins anything older to at most one snapshot per ISO week.

Thinning is computed in Python (fetch just id/grouping-key/timestamp for the
candidate rows, group, keep one per group, delete the rest by id) rather
than a single cross-dialect SQL statement - this is a low-frequency
maintenance operation, not a hot path, so the simpler/more obviously-correct
approach is worth more here than a marginally faster one.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from app.models import (
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
from app.services.job_locks import with_job_lock

CONFIRM_PHRASE = "PRUNE"

# Rows older than this are eligible for thinning-to-one-per-day/week instead
# of being kept in full - see module docstring.
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
    "raw_snapshots": RetentionPolicy(
        table="raw_snapshots",
        retention_days=30,
        mode="delete_old_rows",
        protected_records="none",
    ),
    "app_log_events": RetentionPolicy(
        table="app_log_events",
        retention_days=60,
        mode="delete_old_rows_keep_errors_180d",
        protected_records="error/critical logs kept 180 days",
    ),
    "collector_activity_events": RetentionPolicy(
        table="collector_activity_events",
        retention_days=365,
        mode="delete_old_rows",
        protected_records="none",
    ),
    "price_refresh_runs": RetentionPolicy(
        table="price_refresh_runs",
        retention_days=180,
        mode="delete_old_rows",
        protected_records="none",
    ),
    "market_workflow_runs": RetentionPolicy(
        table="market_workflow_runs",
        retention_days=180,
        mode="delete_old_rows",
        protected_records="none",
    ),
    "market_report_digest_sends": RetentionPolicy(
        table="market_report_digest_sends",
        retention_days=180,
        mode="delete_old_rows",
        protected_records="none",
    ),
    "market_intelligence_reports": RetentionPolicy(
        table="market_intelligence_reports",
        retention_days=365,
        mode="delete_old_rows",
        protected_records="none",
    ),
    "portfolio_valuation_snapshots": RetentionPolicy(
        table="portfolio_valuation_snapshots",
        retention_days=365,
        mode="delete_old_rows_with_weekly_thinning",
        protected_records="one snapshot per ISO week kept beyond 90 days",
    ),
    "price_observations": RetentionPolicy(
        table="price_observations",
        retention_days=365,
        mode="delete_old_rows_with_daily_thinning_protect_latest",
        protected_records="latest observation per exact print (or legacy card)/source/price_type",
    ),
    "market_signal_events": RetentionPolicy(
        table="market_signal_events",
        retention_days=365,
        mode="delete_old_dismissed_resolved",
        protected_records="open/watching events",
    ),
}

# Canonical order - the order results are returned in, and the order "all
# tables" iterates in when the caller doesn't specify `tables`.
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


def list_policies() -> list[RetentionPolicy]:
    return [POLICIES[t] for t in PRUNABLE_TABLES]


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


# --- per-table candidate-id computation -------------------------------------
# Each returns the full set of row ids this table's policy says should be
# deleted right now - dry-run just counts len(ids); applying just issues
# DELETE ... WHERE id IN (ids). Counting and deleting can never disagree,
# since they're the same computation.


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


def _series_identity(card_id: int, card_print_id: int | None) -> tuple[str, int]:
    """The entity half of the price series an observation belongs to.

    A print-linked observation (card_print_id IS NOT NULL - only ever set
    together with source_card_mapping_id, see
    ck_price_observations_lineage_paired) belongs to its exact print, so two
    card_prints that bridge through the same legacy card_id - a base and a
    parallel print of the same canonical card - are separate series here,
    exactly as they are for every public read path (see
    app.services.print_pricing). A legacy, lineage-less observation keeps its
    historical one-series-per-legacy-card behaviour.

    The "print"/"card" tag is load-bearing: card_prints.id and cards.id are
    independent sequences, so an untagged key would group a print's
    observations together with an unrelated legacy card's whenever the two
    ids happened to collide.
    """
    if card_print_id is not None:
        return ("print", card_print_id)
    return ("card", card_id)


def _series_partition_by() -> tuple:
    """SQL counterpart of _series_identity, for the window function below.

    CASE WHEN card_print_id IS NULL THEN card_id END is NULL for every
    print-linked row, so a print's partition key is (NULL, print_id, source,
    type) and a legacy row's is (card_id, NULL, source, type) - the two can
    never collide, because card_id is NOT NULL. Both SQLite and PostgreSQL
    treat NULLs as equal for PARTITION BY, which is what keeps all of one
    legacy card's rows in a single partition as before.
    """
    return (
        case((PriceObservation.card_print_id.is_(None), PriceObservation.card_id)),
        PriceObservation.card_print_id,
        PriceObservation.source_id,
        PriceObservation.price_type,
    )


def _protected_price_observation_ids(db: Session) -> set[int]:
    """The id of the single latest observation per (series, source_id,
    price_type), across the WHOLE table (not scoped to any particular set of
    cards or prints) - these must never be deleted by pruning, no matter
    their age. Same ROW_NUMBER()-over-partition technique as
    app.services.latest_prices, just without an entity filter.

    Series identity is exact-print aware (see _series_identity /
    _series_partition_by), so sibling prints sharing one legacy card_id each
    keep their own last-known price. Grouping on card_id alone would protect
    only whichever sibling was observed most recently and leave the other
    prunable down to nothing.
    """
    row_number = (
        func.row_number()
        .over(
            partition_by=_series_partition_by(),
            # id.desc() as a tiebreaker, matching
            # app.services.latest_prices/print_pricing exactly: when two
            # observations in one series share an identical observed_at (e.g.
            # a batch import stamping every row with the same fetch
            # timestamp), ROW_NUMBER's order among tied rows is otherwise
            # unspecified. Without it, retention could protect a different
            # row than the one the read path serves as "latest" - and then
            # delete the row collectors actually display.
            order_by=(PriceObservation.observed_at.desc(), PriceObservation.id.desc()),
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

    # Past the hard retention window entirely - delete outright (unless
    # protected as the last-known price for its series).
    hard_delete_ids = db.scalars(
        select(PriceObservation.id).where(PriceObservation.observed_at < hard_cutoff)
    ).all()
    candidate_ids.extend(i for i in hard_delete_ids if i not in protected_ids)

    # Thinning zone: older than 90 days but still within the 365-day hard
    # cutoff - keep one row per (series, day), thin the rest. Series is the
    # same exact-print-aware identity the protection query partitions on, so
    # one print's busy day can never thin away a sibling print's only
    # observation of that day. Only fetches the columns needed to group, not
    # full rows.
    thinning_rows = db.execute(
        select(
            PriceObservation.id,
            PriceObservation.card_id,
            PriceObservation.card_print_id,
            PriceObservation.source_id,
            PriceObservation.price_type,
            PriceObservation.observed_at,
        ).where(
            PriceObservation.observed_at >= hard_cutoff,
            PriceObservation.observed_at < fresh_cutoff,
        )
    ).all()

    by_day_group: dict[
        tuple[tuple[str, int], int, str, object], list[tuple[int, datetime]]
    ] = defaultdict(list)
    for row_id, card_id, card_print_id, source_id, price_type, observed_at in thinning_rows:
        key = (_series_identity(card_id, card_print_id), source_id, price_type, observed_at.date())
        by_day_group[key].append((row_id, observed_at))

    for rows in by_day_group.values():
        if len(rows) <= 1:
            continue
        # (observed_at ASC, id ASC): the earliest observation of the day is
        # kept, exactly as before - id.asc() only breaks ties. When several
        # rows in one series/day share an identical observed_at (a batch
        # import stamping every row with the same fetch timestamp), which
        # one survived was otherwise decided by the order the database
        # happened to return rows in, so the same data could thin to a
        # different survivor on a different run or backend. Deliberately
        # ASC, mirroring the keep-earliest policy - the protection window
        # above keeps the LATEST row and so tie-breaks DESC.
        rows.sort(key=lambda r: (r[1], r[0]))  # observed_at ASC, id ASC
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
        rows.sort(key=lambda r: r[1])  # earliest snapshot of the week is kept
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
    skip_lock: bool = False,
) -> PruneRunResult:
    """Evaluates (and, if dry_run=False, applies) the retention policy for
    each requested table - or every prunable table, if `tables` is omitted/
    empty. Each table runs in its own transaction: a failure on one table is
    recorded as that table's warning and does not stop the others (see
    module docstring).

    Acquires the 'data_retention_prune' concurrency lock for the call
    (including dry_run - see 'Worker job concurrency locking' in
    docs/operations.md) - shared by app/prune_data_retention.py's CLI, POST
    /admin/data-retention/prune, and the same-named lock the worker's
    scheduled prune task (worker.celery_app.prune_data_retention_task)
    acquires independently against the same table, so a scheduled and a
    manual prune can never overlap. skip_lock is test/dev-CLI only."""
    with with_job_lock("data_retention_prune", skip_lock=skip_lock):
        return _prune_tables_locked(db, dry_run=dry_run, tables=tables, confirm=confirm, now=now)


def _prune_tables_locked(
    db: Session,
    *,
    dry_run: bool = True,
    tables: list[str] | None = None,
    confirm: str | None = None,
    now: datetime | None = None,
) -> PruneRunResult:
    if not dry_run and confirm != CONFIRM_PHRASE:
        raise PruneConfirmationRequired(
            f"dry_run=false requires confirm={CONFIRM_PHRASE!r}."
        )

    now = now or datetime.now(timezone.utc)

    requested = list(tables) if tables else list(PRUNABLE_TABLES)
    # De-dupe while preserving canonical order, so a caller-supplied list in
    # any order still produces results in the same stable order every time.
    requested_set = set(requested)
    ordered = [t for t in PRUNABLE_TABLES if t in requested_set]
    unknown = [t for t in requested if t not in PRUNABLE_TABLES]

    results: list[TablePruneResult] = []

    for table in unknown:
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
        if not policy.enabled:
            results.append(
                TablePruneResult(
                    table=table,
                    retention_days=policy.retention_days,
                    rows_would_delete=0,
                    rows_deleted=0,
                    status="skipped",
                    warning="Policy disabled.",
                )
            )
            continue

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
