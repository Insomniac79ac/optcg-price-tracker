"""Price source health reporting - a read-only aggregation answering "is each
price source (Yuyu-Tei, SNKRDUNK, ...) actually healthy right now": recent
refresh success/failure, SNKRDUNK automated-discovery blocked status, stale
or missing prices on active source_card_mappings, and coverage by set/rarity.

See GET /admin/price-source-health and GET /admin/price-source-health/gaps
(app.api.admin_price_source_health), `python -m app.price_source_health_report`,
and this module's summary-only integration into app.services.system_check,
app.services.card_audit, and app.services.catalog_coverage.

Read-only: nothing here ever writes to the DB, triggers a refresh, scrapes
anything, or calls an LLM. SNKRDUNK automated discovery can be blocked by the
site (see SnkrdunkDiscoveryRun.status == "blocked") - this module only
reports that fact; it never works around it. When discovery is blocked, use
the existing manual SNKRDUNK candidate import flow instead (see
app.services.card_catalog_import / GET /admin/import-templates) - see
'Price source health workflow' in docs/operations.md.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Card, PriceObservation, Source, SourceCardMapping
from app.models.price_refresh_run import PriceRefreshRun
from app.models.snkrdunk_discovery_run import SnkrdunkDiscoveryRun

# Duplicated (not imported) from app.services.catalog_coverage - importing it
# here would create a cycle, since that module imports
# summarize_price_source_health from this one to embed a summary in its own
# report (see compute_catalog_coverage's price_source_health field). Keep
# these two modules' copies in sync if the thresholds ever change.
SUPPORTED_MAPPING_SOURCES = ("yuyutei", "snkrdunk")
RECENT_PRICE_WINDOWS = {"yuyutei": timedelta(hours=24), "snkrdunk": timedelta(days=7)}
DEFAULT_RECENT_PRICE_WINDOW = timedelta(days=7)

GAP_TYPES = ("stale", "missing", "failed_refresh", "blocked", "low_coverage")

CRITICAL = "critical"
WARNING = "warning"
REVIEW = "review"

HEALTH_STATUSES = ("healthy", "degraded", "stale", "blocked", "error", "unknown")

# How far back "recent" refresh/discovery activity (success rate, blocked/
# error counts, average duration) looks - see the source item's
# blocked_count_7d/error_count_7d fields.
RECENT_REFRESH_LOOKBACK_DAYS = 7

# A source is "stale" once more than this share of its active mappings have
# no recent price (a price exists, just not within the freshness window).
STALE_HEALTH_THRESHOLD_PCT = 50.0
# A source is "degraded" once more than this share of its active mappings
# have a stale-or-missing price, or its recent refresh success rate drops
# below DEGRADED_SUCCESS_RATE_PCT.
DEGRADED_PRICE_GAP_THRESHOLD_PCT = 20.0
DEGRADED_SUCCESS_RATE_PCT = 80.0

RESOLVED_REFRESH_STATUSES = ("completed", "completed_with_warnings", "failed")


def _naive(dt: datetime) -> datetime:
    """Strips tzinfo if present, so a loaded row's timestamp (naive under
    SQLite, aware under Postgres) can be safely compared against
    datetime.now(timezone.utc) under either dialect - same helper as
    app.services.catalog_coverage/source_mapping_confidence."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


@dataclass
class PriceSourceHealthFilters:
    source: str | None = None
    set_code: str | None = None
    rarity: str | None = None
    variant: str | None = None
    language: str | None = None
    include_inactive_mappings: bool = False


@dataclass
class PriceGapItem:
    mapping_id: int
    card_id: int
    card_code: str | None
    name_en: str | None
    set_code: str | None
    rarity: str | None
    variant: str | None
    language: str | None
    source_name: str
    source_url: str | None
    latest_price_observed_at: datetime | None
    latest_price_type: str | None
    latest_price_jpy: int | None
    issue_type: str
    severity: str
    suggested_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_id": self.mapping_id,
            "card_id": self.card_id,
            "card_code": self.card_code,
            "name_en": self.name_en,
            "set_code": self.set_code,
            "rarity": self.rarity,
            "variant": self.variant,
            "language": self.language,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "latest_price_observed_at": (
                self.latest_price_observed_at.isoformat() if self.latest_price_observed_at else None
            ),
            "latest_price_type": self.latest_price_type,
            "latest_price_jpy": self.latest_price_jpy,
            "issue_type": self.issue_type,
            "severity": self.severity,
            "suggested_action": self.suggested_action,
        }


@dataclass
class SourceHealthItem:
    source_id: int
    source_name: str
    active_mapping_count: int = 0
    recent_price_count: int = 0
    stale_price_count: int = 0
    missing_price_count: int = 0
    latest_price_observed_at: datetime | None = None
    latest_refresh_status: str | None = None
    latest_refresh_started_at: datetime | None = None
    latest_refresh_finished_at: datetime | None = None
    recent_refresh_success_rate_pct: float = 0.0
    average_refresh_duration_seconds: float | None = None
    blocked_count_7d: int = 0
    error_count_7d: int = 0
    health_status: str = "unknown"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_name": self.source_name,
            "active_mapping_count": self.active_mapping_count,
            "recent_price_count": self.recent_price_count,
            "stale_price_count": self.stale_price_count,
            "missing_price_count": self.missing_price_count,
            "latest_price_observed_at": (
                self.latest_price_observed_at.isoformat() if self.latest_price_observed_at else None
            ),
            "latest_refresh_status": self.latest_refresh_status,
            "latest_refresh_started_at": (
                self.latest_refresh_started_at.isoformat() if self.latest_refresh_started_at else None
            ),
            "latest_refresh_finished_at": (
                self.latest_refresh_finished_at.isoformat() if self.latest_refresh_finished_at else None
            ),
            "recent_refresh_success_rate_pct": self.recent_refresh_success_rate_pct,
            "average_refresh_duration_seconds": self.average_refresh_duration_seconds,
            "blocked_count_7d": self.blocked_count_7d,
            "error_count_7d": self.error_count_7d,
            "health_status": self.health_status,
            "warnings": self.warnings,
        }


@dataclass
class HealthCoverageBreakdownItem:
    key: str
    label: str
    mapped_cards: int = 0
    recent_price_cards: int = 0
    stale_price_cards: int = 0
    missing_price_cards: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "mapped_cards": self.mapped_cards,
            "recent_price_cards": self.recent_price_cards,
            "stale_price_cards": self.stale_price_cards,
            "missing_price_cards": self.missing_price_cards,
            "coverage_pct": _pct(self.recent_price_cards, self.mapped_cards),
        }


@dataclass
class RefreshRunSummaryItem:
    id: int
    status: str
    source_filter: str | None
    started_at: datetime
    finished_at: datetime | None
    dry_run: bool
    mappings_checked: int
    mappings_failed: int
    error_message: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "source_filter": self.source_filter,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "dry_run": self.dry_run,
            "mappings_checked": self.mappings_checked,
            "mappings_failed": self.mappings_failed,
            "error_message": self.error_message,
        }


@dataclass
class PriceSourceHealthReport:
    summary: dict[str, Any]
    sources: list[SourceHealthItem] = field(default_factory=list)
    coverage_by_set: list[HealthCoverageBreakdownItem] = field(default_factory=list)
    coverage_by_rarity: list[HealthCoverageBreakdownItem] = field(default_factory=list)
    stale_prices: list[PriceGapItem] = field(default_factory=list)
    missing_prices: list[PriceGapItem] = field(default_factory=list)
    failed_refresh_gaps: list[PriceGapItem] = field(default_factory=list)
    blocked_gaps: list[PriceGapItem] = field(default_factory=list)
    low_coverage_gaps: list[PriceGapItem] = field(default_factory=list)
    refresh_runs: list[RefreshRunSummaryItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def gaps_for(self, gap_type: str) -> list[PriceGapItem]:
        return {
            "stale": self.stale_prices,
            "missing": self.missing_prices,
            "failed_refresh": self.failed_refresh_gaps,
            "blocked": self.blocked_gaps,
            "low_coverage": self.low_coverage_gaps,
        }[gap_type]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "sources": [s.to_dict() for s in self.sources],
            "coverage_by_set": [i.to_dict() for i in self.coverage_by_set],
            "coverage_by_rarity": [i.to_dict() for i in self.coverage_by_rarity],
            "stale_prices": [i.to_dict() for i in self.stale_prices],
            "missing_prices": [i.to_dict() for i in self.missing_prices],
            "refresh_runs": [r.to_dict() for r in self.refresh_runs],
            "warnings": self.warnings,
        }


def _filtered_mappings(db: Session, filters: PriceSourceHealthFilters) -> list[tuple[SourceCardMapping, Card, Source]]:
    query = (
        select(SourceCardMapping, Card, Source)
        .join(Card, SourceCardMapping.card_id == Card.id)
        .join(Source, SourceCardMapping.source_id == Source.id)
    )
    conditions = []
    if not filters.include_inactive_mappings:
        conditions.append(SourceCardMapping.is_active.is_(True))
    if filters.source:
        conditions.append(Source.name == filters.source)
    if filters.set_code:
        conditions.append(Card.set_code == filters.set_code)
    if filters.rarity:
        conditions.append(Card.rarity == filters.rarity)
    if filters.variant:
        conditions.append(Card.variant == filters.variant)
    if filters.language:
        conditions.append(Card.language == filters.language)
    if conditions:
        query = query.where(*conditions)
    return list(db.execute(query).all())


def _latest_price_by_card_source(
    db: Session, card_ids: set[int], source_ids: set[int]
) -> dict[tuple[int, int], tuple[datetime, str, int]]:
    if not card_ids or not source_ids:
        return {}
    # Window function keyed by (card_id, source_id), newest first - same
    # latest-observation approach as app.services.latest_prices, but scoped
    # to just the mappings in play here rather than the whole catalog.
    subq = (
        select(
            PriceObservation.card_id,
            PriceObservation.source_id,
            PriceObservation.observed_at,
            PriceObservation.price_type,
            PriceObservation.price_jpy,
            func.row_number()
            .over(
                partition_by=(PriceObservation.card_id, PriceObservation.source_id),
                order_by=PriceObservation.observed_at.desc(),
            )
            .label("rn"),
        )
        .where(PriceObservation.card_id.in_(card_ids), PriceObservation.source_id.in_(source_ids))
        .subquery()
    )
    rows = db.execute(
        select(subq.c.card_id, subq.c.source_id, subq.c.observed_at, subq.c.price_type, subq.c.price_jpy).where(
            subq.c.rn == 1
        )
    ).all()
    return {(r.card_id, r.source_id): (r.observed_at, r.price_type, r.price_jpy) for r in rows}


@dataclass
class _MappingFact:
    mapping: SourceCardMapping
    card: Card
    source: Source
    latest_observed_at: datetime | None
    latest_price_type: str | None
    latest_price_jpy: int | None

    @property
    def freshness_window(self) -> timedelta:
        return RECENT_PRICE_WINDOWS.get(self.source.name, DEFAULT_RECENT_PRICE_WINDOW)

    def is_recent(self, now: datetime) -> bool:
        if self.latest_observed_at is None:
            return False
        return _naive(self.latest_observed_at) >= _naive(now) - self.freshness_window

    def is_missing(self) -> bool:
        return self.latest_observed_at is None

    def is_stale(self, now: datetime) -> bool:
        return not self.is_missing() and not self.is_recent(now)


def _build_mapping_facts(db: Session, filters: PriceSourceHealthFilters) -> list[_MappingFact]:
    rows = _filtered_mappings(db, filters)
    if not rows:
        return []

    card_ids = {c.id for _m, c, _s in rows}
    source_ids = {s.id for _m, _c, s in rows}
    latest_by_pair = _latest_price_by_card_source(db, card_ids, source_ids)

    facts: list[_MappingFact] = []
    for mapping, card, source in rows:
        latest = latest_by_pair.get((card.id, source.id))
        facts.append(
            _MappingFact(
                mapping=mapping,
                card=card,
                source=source,
                latest_observed_at=latest[0] if latest else None,
                latest_price_type=latest[1] if latest else None,
                latest_price_jpy=latest[2] if latest else None,
            )
        )
    return facts


def _latest_refresh_runs_by_source(db: Session) -> dict[str | None, PriceRefreshRun]:
    """Most recent PriceRefreshRun per distinct source_filter value (None
    included, meaning "all sources") - one query, then _refresh_run_for_source
    resolves a given source name against both its own filter value and the
    None ("ran for every source") value."""
    # Capped rather than scanning the whole table - the latest run for each
    # of the handful of distinct source_filter values (None/"yuyutei"/
    # "snkrdunk") is always going to be within the most recent runs, not
    # buried arbitrarily far back.
    runs = list(
        db.scalars(select(PriceRefreshRun).order_by(PriceRefreshRun.started_at.desc()).limit(500)).all()
    )
    latest: dict[str | None, PriceRefreshRun] = {}
    for run in runs:
        if run.source_filter not in latest:
            latest[run.source_filter] = run
    return latest


def _refresh_run_for_source(latest_by_filter: dict[str | None, PriceRefreshRun], source_name: str) -> PriceRefreshRun | None:
    specific = latest_by_filter.get(source_name)
    combined = latest_by_filter.get(None)
    if specific is None:
        return combined
    if combined is None:
        return specific
    return specific if _naive(specific.started_at) >= _naive(combined.started_at) else combined


def _recent_refresh_stats(db: Session, source_name: str, now: datetime) -> tuple[float, float | None, int]:
    """Returns (success_rate_pct, average_duration_seconds, error_count) over
    PriceRefreshRun rows scoped to source_name (source_filter == source_name
    or NULL, i.e. a combined run) within RECENT_REFRESH_LOOKBACK_DAYS."""
    cutoff = _naive(now) - timedelta(days=RECENT_REFRESH_LOOKBACK_DAYS)
    runs = list(
        db.scalars(
            select(PriceRefreshRun).where(
                (PriceRefreshRun.source_filter == source_name) | (PriceRefreshRun.source_filter.is_(None)),
                PriceRefreshRun.started_at >= cutoff,
                PriceRefreshRun.status.in_(RESOLVED_REFRESH_STATUSES),
            )
        ).all()
    )
    if not runs:
        return 0.0, None, 0

    succeeded = sum(1 for r in runs if r.status in ("completed", "completed_with_warnings"))
    error_count = sum(1 for r in runs if r.status == "failed")
    success_rate = _pct(succeeded, len(runs))

    durations = [
        (_naive(r.finished_at) - _naive(r.started_at)).total_seconds()
        for r in runs
        if r.finished_at is not None
    ]
    avg_duration = round(sum(durations) / len(durations), 2) if durations else None
    return success_rate, avg_duration, error_count


def _blocked_count_7d(db: Session, source_name: str, now: datetime) -> int:
    if source_name != "snkrdunk":
        return 0
    cutoff = _naive(now) - timedelta(days=RECENT_REFRESH_LOOKBACK_DAYS)
    return (
        db.scalar(
            select(func.count())
            .select_from(SnkrdunkDiscoveryRun)
            .where(SnkrdunkDiscoveryRun.status == "blocked", SnkrdunkDiscoveryRun.started_at >= cutoff)
        )
        or 0
    )


def _latest_discovery_run(db: Session) -> SnkrdunkDiscoveryRun | None:
    return db.scalar(select(SnkrdunkDiscoveryRun).order_by(SnkrdunkDiscoveryRun.started_at.desc()).limit(1))


def _overall_recent_refresh_success_rate(db: Session, now: datetime) -> float:
    """System-wide (not per-source) recent refresh success rate - one
    PriceRefreshRun row is one attempt regardless of which source(s) it
    covered, so this is a simple resolved-run success/total over the last
    RECENT_REFRESH_LOOKBACK_DAYS, used for the summary's top-line
    recent_refresh_success_rate_pct and system_check's threshold."""
    cutoff = _naive(now) - timedelta(days=RECENT_REFRESH_LOOKBACK_DAYS)
    runs = list(
        db.scalars(
            select(PriceRefreshRun).where(
                PriceRefreshRun.started_at >= cutoff,
                PriceRefreshRun.status.in_(RESOLVED_REFRESH_STATUSES),
            )
        ).all()
    )
    if not runs:
        return 0.0
    succeeded = sum(1 for r in runs if r.status in ("completed", "completed_with_warnings"))
    return _pct(succeeded, len(runs))


def _health_status(
    *,
    source_name: str,
    active_mapping_count: int,
    stale_price_count: int,
    missing_price_count: int,
    latest_refresh_status: str | None,
    latest_discovery_status: str | None,
    recent_refresh_success_rate_pct: float,
    has_resolved_runs: bool,
    has_ever_refreshed: bool,
) -> tuple[str, list[str]]:
    warnings: list[str] = []

    if not has_ever_refreshed and active_mapping_count == 0:
        return "unknown", warnings

    if source_name == "snkrdunk" and latest_discovery_status == "blocked":
        warnings.append(
            "SNKRDUNK automated discovery is currently blocked - use the manual candidate "
            "import flow instead of retrying automated discovery."
        )
        return "blocked", warnings

    if latest_refresh_status == "failed" or (
        source_name == "snkrdunk" and latest_refresh_status is None and latest_discovery_status == "failed"
    ):
        warnings.append("Latest refresh run for this source failed.")
        return "error", warnings

    if active_mapping_count > 0:
        stale_pct = _pct(stale_price_count, active_mapping_count)
        gap_pct = _pct(stale_price_count + missing_price_count, active_mapping_count)
        if stale_pct > STALE_HEALTH_THRESHOLD_PCT:
            warnings.append(f"{stale_pct}% of active mappings have a stale price.")
            return "stale", warnings
        if gap_pct > DEGRADED_PRICE_GAP_THRESHOLD_PCT:
            warnings.append(f"{gap_pct}% of active mappings have a stale or missing price.")
            return "degraded", warnings

    if has_resolved_runs and recent_refresh_success_rate_pct < DEGRADED_SUCCESS_RATE_PCT:
        warnings.append(f"Recent refresh success rate is {recent_refresh_success_rate_pct}%.")
        return "degraded", warnings

    return "healthy", warnings


def _build_sources(
    db: Session, facts: list[_MappingFact], filters: PriceSourceHealthFilters, now: datetime
) -> list[SourceHealthItem]:
    source_query = select(Source)
    if filters.source:
        source_query = source_query.where(Source.name == filters.source)
    sources = list(db.scalars(source_query.order_by(Source.name)).all())

    facts_by_source: dict[int, list[_MappingFact]] = defaultdict(list)
    for fact in facts:
        facts_by_source[fact.source.id].append(fact)

    latest_refresh_by_filter = _latest_refresh_runs_by_source(db)
    latest_discovery_run = _latest_discovery_run(db)

    items: list[SourceHealthItem] = []
    for source in sources:
        source_facts = facts_by_source.get(source.id, [])
        active_mapping_count = len(source_facts)
        recent = [f for f in source_facts if f.is_recent(now)]
        stale = [f for f in source_facts if f.is_stale(now)]
        missing = [f for f in source_facts if f.is_missing()]

        latest_observed_at = max(
            (f.latest_observed_at for f in source_facts if f.latest_observed_at is not None), default=None
        )

        latest_refresh_run = _refresh_run_for_source(latest_refresh_by_filter, source.name)
        success_rate, avg_duration, error_count_7d = _recent_refresh_stats(db, source.name, now)
        blocked_count_7d = _blocked_count_7d(db, source.name, now)

        latest_discovery_status = (
            latest_discovery_run.status if source.name == "snkrdunk" and latest_discovery_run else None
        )
        has_ever_refreshed = latest_refresh_run is not None or latest_discovery_run is not None
        # success_rate/error_count_7d are both derived from the same
        # resolved-runs-in-window query (_recent_refresh_stats) - nonzero
        # runs in that window always show up as at least one of the two
        # (succeeded+failed == len(runs)), so this correctly means "there
        # was real data in the lookback window", not just "0% success".
        has_resolved_runs = error_count_7d > 0 or success_rate > 0

        health_status, health_warnings = _health_status(
            source_name=source.name,
            active_mapping_count=active_mapping_count,
            stale_price_count=len(stale),
            missing_price_count=len(missing),
            latest_refresh_status=latest_refresh_run.status if latest_refresh_run else None,
            latest_discovery_status=latest_discovery_status,
            recent_refresh_success_rate_pct=success_rate,
            has_resolved_runs=has_resolved_runs,
            has_ever_refreshed=has_ever_refreshed,
        )

        items.append(
            SourceHealthItem(
                source_id=source.id,
                source_name=source.name,
                active_mapping_count=active_mapping_count,
                recent_price_count=len(recent),
                stale_price_count=len(stale),
                missing_price_count=len(missing),
                latest_price_observed_at=latest_observed_at,
                latest_refresh_status=latest_refresh_run.status if latest_refresh_run else None,
                latest_refresh_started_at=latest_refresh_run.started_at if latest_refresh_run else None,
                latest_refresh_finished_at=latest_refresh_run.finished_at if latest_refresh_run else None,
                recent_refresh_success_rate_pct=success_rate,
                average_refresh_duration_seconds=avg_duration,
                blocked_count_7d=blocked_count_7d,
                error_count_7d=error_count_7d,
                health_status=health_status,
                warnings=health_warnings,
            )
        )
    return items


def _breakdown_key(card: Card, dimension: str) -> str:
    value = getattr(card, dimension)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return "none"
    return value


def _build_breakdown(facts: list[_MappingFact], dimension: str, now: datetime) -> list[HealthCoverageBreakdownItem]:
    by_card: dict[int, list[_MappingFact]] = defaultdict(list)
    for fact in facts:
        by_card[fact.card.id].append(fact)

    groups: dict[str, HealthCoverageBreakdownItem] = {}
    for card_facts in by_card.values():
        card = card_facts[0].card
        key = _breakdown_key(card, dimension)
        item = groups.setdefault(key, HealthCoverageBreakdownItem(key=key, label=key))
        item.mapped_cards += 1
        if any(f.is_recent(now) for f in card_facts):
            item.recent_price_cards += 1
        elif any(not f.is_missing() for f in card_facts):
            item.stale_price_cards += 1
        else:
            item.missing_price_cards += 1
    return sorted(groups.values(), key=lambda i: i.key)


def _gap_item(fact: _MappingFact, issue_type: str, severity: str, suggested_action: str) -> PriceGapItem:
    card = fact.card
    return PriceGapItem(
        mapping_id=fact.mapping.id,
        card_id=card.id,
        card_code=card.card_code,
        name_en=card.name_en,
        set_code=card.set_code,
        rarity=card.rarity,
        variant=card.variant,
        language=card.language,
        source_name=fact.source.name,
        source_url=fact.mapping.source_url,
        latest_price_observed_at=fact.latest_observed_at,
        latest_price_type=fact.latest_price_type,
        latest_price_jpy=fact.latest_price_jpy,
        issue_type=issue_type,
        severity=severity,
        suggested_action=suggested_action,
    )


def _severity_sort_key(item: PriceGapItem) -> tuple:
    rank = {"critical": 0, "warning": 1, "review": 2}
    return (rank.get(item.severity, 3), item.card_code or "", item.mapping_id)


def _build_gaps(
    facts: list[_MappingFact],
    sources: list[SourceHealthItem],
    coverage_by_set: list[HealthCoverageBreakdownItem],
    coverage_by_rarity: list[HealthCoverageBreakdownItem],
    now: datetime,
) -> dict[str, list[PriceGapItem]]:
    stale_prices: list[PriceGapItem] = []
    missing_prices: list[PriceGapItem] = []
    for fact in facts:
        if fact.is_stale(now):
            stale_prices.append(_gap_item(fact, "stale_price", WARNING, "run_refresh_or_review_mapping"))
        elif fact.is_missing():
            missing_prices.append(_gap_item(fact, "missing_price", WARNING, "run_refresh_or_review_mapping"))

    failed_sources = {s.source_name for s in sources if s.latest_refresh_status == "failed"}
    failed_refresh_gaps = [
        _gap_item(fact, "refresh_failed", CRITICAL, "review_refresh_run")
        for fact in facts
        if fact.source.name in failed_sources
    ]

    blocked_sources = {s.source_name for s in sources if s.health_status == "blocked"}
    blocked_gaps = [
        _gap_item(fact, "source_blocked", CRITICAL, "use_manual_snkrdunk_import")
        for fact in facts
        if fact.source.name in blocked_sources
    ]

    low_coverage_sets = {i.key for i in coverage_by_set if i.mapped_cards > 0 and _pct(i.recent_price_cards, i.mapped_cards) < 50.0}
    low_coverage_rarities = {
        i.key for i in coverage_by_rarity if i.mapped_cards > 0 and _pct(i.recent_price_cards, i.mapped_cards) < 50.0
    }
    low_coverage_gaps = [
        _gap_item(fact, "low_coverage", REVIEW, "review_source_mapping_coverage")
        for fact in facts
        if _breakdown_key(fact.card, "set_code") in low_coverage_sets
        or _breakdown_key(fact.card, "rarity") in low_coverage_rarities
    ]

    return {
        "stale_prices": sorted(stale_prices, key=_severity_sort_key),
        "missing_prices": sorted(missing_prices, key=_severity_sort_key),
        "failed_refresh_gaps": sorted(failed_refresh_gaps, key=_severity_sort_key),
        "blocked_gaps": sorted(blocked_gaps, key=_severity_sort_key),
        "low_coverage_gaps": sorted(low_coverage_gaps, key=_severity_sort_key),
    }


def _recent_refresh_runs(db: Session, limit: int = 10) -> list[RefreshRunSummaryItem]:
    runs = list(db.scalars(select(PriceRefreshRun).order_by(PriceRefreshRun.started_at.desc()).limit(limit)).all())
    return [
        RefreshRunSummaryItem(
            id=r.id,
            status=r.status,
            source_filter=r.source_filter,
            started_at=r.started_at,
            finished_at=r.finished_at,
            dry_run=r.dry_run,
            mappings_checked=r.mappings_checked,
            mappings_failed=r.mappings_failed,
            error_message=r.error_message,
        )
        for r in runs
    ]


def _build_summary(db: Session, sources: list[SourceHealthItem], now: datetime) -> dict[str, Any]:
    total_active_mappings = sum(s.active_mapping_count for s in sources)
    mappings_with_recent_price = sum(s.recent_price_count for s in sources)
    mappings_without_recent_price = total_active_mappings - mappings_with_recent_price
    stale_price_count = sum(s.stale_price_count for s in sources)
    missing_price_count = sum(s.missing_price_count for s in sources)

    successful_runs_at = [
        s.latest_refresh_finished_at
        for s in sources
        if s.latest_refresh_status in ("completed", "completed_with_warnings") and s.latest_refresh_finished_at
    ]
    failed_runs_at = [
        s.latest_refresh_finished_at or s.latest_refresh_started_at
        for s in sources
        if s.latest_refresh_status == "failed"
    ]

    overall_success_rate = _overall_recent_refresh_success_rate(db, now)

    return {
        "sources_count": len(sources),
        "active_sources_count": sum(1 for s in sources if s.active_mapping_count > 0),
        "total_active_mappings": total_active_mappings,
        "mappings_with_recent_price": mappings_with_recent_price,
        "mappings_without_recent_price": mappings_without_recent_price,
        "stale_price_count": stale_price_count,
        "missing_price_count": missing_price_count,
        "last_successful_refresh_at": max(successful_runs_at) if successful_runs_at else None,
        "last_failed_refresh_at": max(r for r in failed_runs_at if r is not None) if any(r is not None for r in failed_runs_at) else None,
        "recent_refresh_success_rate_pct": overall_success_rate,
        "blocked_source_count": sum(1 for s in sources if s.health_status == "blocked"),
        "error_source_count": sum(1 for s in sources if s.health_status == "error"),
    }


def _build_warnings(sources: list[SourceHealthItem]) -> list[str]:
    warnings: list[str] = []
    for source in sources:
        for w in source.warnings:
            warnings.append(f"{source.source_name}: {w}")
    return warnings


def compute_price_source_health(
    db: Session, filters: PriceSourceHealthFilters | None = None
) -> PriceSourceHealthReport:
    filters = filters or PriceSourceHealthFilters()
    now = datetime.now(timezone.utc)

    facts = _build_mapping_facts(db, filters)
    sources = _build_sources(db, facts, filters, now)
    coverage_by_set = _build_breakdown(facts, "set_code", now)
    coverage_by_rarity = _build_breakdown(facts, "rarity", now)
    gaps = _build_gaps(facts, sources, coverage_by_set, coverage_by_rarity, now)
    summary = _build_summary(db, sources, now)
    warnings = _build_warnings(sources)
    refresh_runs = _recent_refresh_runs(db)

    return PriceSourceHealthReport(
        summary=summary,
        sources=sources,
        coverage_by_set=coverage_by_set,
        coverage_by_rarity=coverage_by_rarity,
        stale_prices=gaps["stale_prices"],
        missing_prices=gaps["missing_prices"],
        failed_refresh_gaps=gaps["failed_refresh_gaps"],
        blocked_gaps=gaps["blocked_gaps"],
        low_coverage_gaps=gaps["low_coverage_gaps"],
        refresh_runs=refresh_runs,
        warnings=warnings,
    )


def summarize_price_source_health(db: Session) -> dict[str, Any]:
    """Unfiltered summary-only view (no per-mapping gap lists, no per-source
    detail) - used by app.services.system_check, app.services.card_audit,
    and app.services.catalog_coverage so none of them has to pull in the
    full report just to report a handful of top-line numbers. See GET
    /admin/price-source-health for the full report."""
    return compute_price_source_health(db, PriceSourceHealthFilters()).summary


def paginated_gaps(
    db: Session,
    gap_type: str,
    filters: PriceSourceHealthFilters,
    *,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[PriceGapItem], int]:
    """Returns (page_of_items, total_matching) for one gap_type - used by GET
    /admin/price-source-health/gaps."""
    report = compute_price_source_health(db, filters)
    items = report.gaps_for(gap_type)
    total = len(items)
    return items[offset : offset + limit], total
