"""Price source health reporting - a read-only aggregation answering "is each
price source (Yuyu-Tei, SNKRDUNK, ...) actually healthy right now": recent
refresh success/failure, SNKRDUNK automated-discovery blocked status, stale
or missing prices on exact source mappings, and coverage by physical-print
release product/rarity/language.

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

from app.models import PriceObservation, Source, SourceCardMapping
from app.models.price_refresh_run import PriceRefreshRun
from app.models.snkrdunk_discovery_run import SnkrdunkDiscoveryRun
from app.services.source_mapping_identity import (
    BROKEN,
    EXACT,
    LEGACY_COMPATIBILITY,
    SourceMappingIdentity,
    load_source_mapping_identities,
)

# Duplicated (not imported) from app.services.catalog_coverage - importing it
# here would create a cycle, since that module imports
# summarize_price_source_health from this one to embed a summary in its own
# report (see compute_catalog_coverage's price_source_health field). Keep
# these two modules' copies in sync if the thresholds ever change.
SUPPORTED_MAPPING_SOURCES = ("yuyutei", "snkrdunk")
RECENT_PRICE_WINDOWS = {"yuyutei": timedelta(hours=24), "snkrdunk": timedelta(days=7)}
DEFAULT_RECENT_PRICE_WINDOW = timedelta(days=7)

GAP_TYPES = (
    "stale",
    "missing",
    "failed_refresh",
    "blocked",
    "low_coverage",
    LEGACY_COMPATIBILITY,
    BROKEN,
)

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
    source_id: int
    card_print_id: int | None
    canonical_card_id: int | None
    release_product_id: int | None
    compatibility_card_id: int | None
    identity_classification: str
    card_code: str | None
    name_en: str | None
    name_jp: str | None
    release_product_code: str | None
    release_product_name: str | None
    rarity: str | None
    official_asset_variant: str | None
    treatment: str | None
    language: str | None
    source_name: str | None
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
            "source_id": self.source_id,
            "card_print_id": self.card_print_id,
            "canonical_card_id": self.canonical_card_id,
            "release_product_id": self.release_product_id,
            "compatibility_card_id": self.compatibility_card_id,
            "identity_classification": self.identity_classification,
            "card_code": self.card_code,
            "name_en": self.name_en,
            "name_jp": self.name_jp,
            "release_product_code": self.release_product_code,
            "release_product_name": self.release_product_name,
            "rarity": self.rarity,
            "official_asset_variant": self.official_asset_variant,
            "treatment": self.treatment,
            "language": self.language,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "latest_price_observed_at": (
                self.latest_price_observed_at.isoformat()
                if self.latest_price_observed_at
                else None
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
    legacy_compatibility_mapping_count: int = 0
    broken_mapping_count: int = 0
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
            "legacy_compatibility_mapping_count": self.legacy_compatibility_mapping_count,
            "broken_mapping_count": self.broken_mapping_count,
            "latest_price_observed_at": (
                self.latest_price_observed_at.isoformat()
                if self.latest_price_observed_at
                else None
            ),
            "latest_refresh_status": self.latest_refresh_status,
            "latest_refresh_started_at": (
                self.latest_refresh_started_at.isoformat()
                if self.latest_refresh_started_at
                else None
            ),
            "latest_refresh_finished_at": (
                self.latest_refresh_finished_at.isoformat()
                if self.latest_refresh_finished_at
                else None
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
    mapped_prints: int = 0
    recent_price_prints: int = 0
    stale_price_prints: int = 0
    missing_price_prints: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "mapped_prints": self.mapped_prints,
            "recent_price_prints": self.recent_price_prints,
            "stale_price_prints": self.stale_price_prints,
            "missing_price_prints": self.missing_price_prints,
            "coverage_pct": _pct(self.recent_price_prints, self.mapped_prints),
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
    coverage_by_release_product: list[HealthCoverageBreakdownItem] = field(
        default_factory=list
    )
    coverage_by_rarity: list[HealthCoverageBreakdownItem] = field(default_factory=list)
    coverage_by_language: list[HealthCoverageBreakdownItem] = field(
        default_factory=list
    )
    stale_prices: list[PriceGapItem] = field(default_factory=list)
    missing_prices: list[PriceGapItem] = field(default_factory=list)
    failed_refresh_gaps: list[PriceGapItem] = field(default_factory=list)
    blocked_gaps: list[PriceGapItem] = field(default_factory=list)
    low_coverage_gaps: list[PriceGapItem] = field(default_factory=list)
    legacy_compatibility_mappings: list[PriceGapItem] = field(default_factory=list)
    broken_mappings: list[PriceGapItem] = field(default_factory=list)
    refresh_runs: list[RefreshRunSummaryItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def gaps_for(self, gap_type: str) -> list[PriceGapItem]:
        return {
            "stale": self.stale_prices,
            "missing": self.missing_prices,
            "failed_refresh": self.failed_refresh_gaps,
            "blocked": self.blocked_gaps,
            "low_coverage": self.low_coverage_gaps,
            LEGACY_COMPATIBILITY: self.legacy_compatibility_mappings,
            BROKEN: self.broken_mappings,
        }[gap_type]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "sources": [s.to_dict() for s in self.sources],
            "coverage_by_release_product": [
                i.to_dict() for i in self.coverage_by_release_product
            ],
            "coverage_by_rarity": [i.to_dict() for i in self.coverage_by_rarity],
            "coverage_by_language": [i.to_dict() for i in self.coverage_by_language],
            "stale_prices": [i.to_dict() for i in self.stale_prices],
            "missing_prices": [i.to_dict() for i in self.missing_prices],
            "legacy_compatibility_mappings": [
                i.to_dict() for i in self.legacy_compatibility_mappings
            ],
            "broken_mappings": [i.to_dict() for i in self.broken_mappings],
            "refresh_runs": [r.to_dict() for r in self.refresh_runs],
            "warnings": self.warnings,
        }


def _filtered_identities(
    db: Session, filters: PriceSourceHealthFilters
) -> list[SourceMappingIdentity]:
    conditions = []
    if not filters.include_inactive_mappings:
        conditions.append(SourceCardMapping.is_active.is_(True))
    identities = load_source_mapping_identities(db, conditions=conditions)

    def matches(identity: SourceMappingIdentity) -> bool:
        if filters.source and (
            identity.source is None or identity.source.name != filters.source
        ):
            return False
        if identity.classification == EXACT:
            print_row = identity.card_print
            canonical = identity.canonical_card
            product = identity.release_product
            if print_row is None or canonical is None:
                return False
            if filters.set_code and (
                product is None or product.official_code != filters.set_code
            ):
                return False
            if filters.rarity and print_row.official_rarity != filters.rarity:
                return False
            if filters.variant and print_row.treatment != filters.variant:
                return False
            if filters.language and print_row.language != filters.language:
                return False
            return True

        # Compatibility rows remain reportable, but filters can only use the
        # metadata that row actually carries.  None of it is promoted into an
        # exact print identity.
        card = identity.compatibility_card
        if any((filters.set_code, filters.rarity, filters.variant, filters.language)):
            if card is None:
                return False
            if filters.set_code and card.set_code != filters.set_code:
                return False
            if filters.rarity and card.rarity != filters.rarity:
                return False
            if filters.variant and card.variant != filters.variant:
                return False
            if filters.language and card.language != filters.language:
                return False
        return True

    return [identity for identity in identities if matches(identity)]


def _latest_price_by_mapping(
    db: Session, mapping_ids: set[int]
) -> dict[int, tuple[datetime, str, int]]:
    if not mapping_ids:
        return {}
    # The composite equality mirrors the PostgreSQL lineage FK.  Keeping it
    # in this read query also makes SQLite tests and any imported malformed
    # rows unable to lend health to a different print or source.
    subq = (
        select(
            PriceObservation.source_card_mapping_id,
            PriceObservation.observed_at,
            PriceObservation.price_type,
            PriceObservation.price_jpy,
            func.row_number()
            .over(
                partition_by=PriceObservation.source_card_mapping_id,
                order_by=PriceObservation.observed_at.desc(),
            )
            .label("rn"),
        )
        .join(
            SourceCardMapping,
            (SourceCardMapping.id == PriceObservation.source_card_mapping_id)
            & (SourceCardMapping.card_print_id == PriceObservation.card_print_id)
            & (SourceCardMapping.source_id == PriceObservation.source_id),
        )
        .where(PriceObservation.source_card_mapping_id.in_(mapping_ids))
        .subquery()
    )
    rows = db.execute(
        select(
            subq.c.source_card_mapping_id,
            subq.c.observed_at,
            subq.c.price_type,
            subq.c.price_jpy,
        ).where(subq.c.rn == 1)
    ).all()
    return {
        r.source_card_mapping_id: (r.observed_at, r.price_type, r.price_jpy)
        for r in rows
    }


@dataclass
class _MappingFact:
    identity: SourceMappingIdentity
    latest_observed_at: datetime | None
    latest_price_type: str | None
    latest_price_jpy: int | None

    @property
    def freshness_window(self) -> timedelta:
        assert self.identity.source is not None
        return RECENT_PRICE_WINDOWS.get(
            self.identity.source.name, DEFAULT_RECENT_PRICE_WINDOW
        )

    @property
    def mapping(self) -> SourceCardMapping:
        return self.identity.mapping

    @property
    def source(self) -> Source:
        assert self.identity.source is not None
        return self.identity.source

    def is_recent(self, now: datetime) -> bool:
        if self.latest_observed_at is None:
            return False
        return _naive(self.latest_observed_at) >= _naive(now) - self.freshness_window

    def is_missing(self) -> bool:
        return self.latest_observed_at is None

    def is_stale(self, now: datetime) -> bool:
        return not self.is_missing() and not self.is_recent(now)


def _build_mapping_facts(
    db: Session, identities: list[SourceMappingIdentity]
) -> list[_MappingFact]:
    exact = [identity for identity in identities if identity.classification == EXACT]
    latest_by_mapping = _latest_price_by_mapping(
        db, {identity.mapping.id for identity in exact}
    )
    facts: list[_MappingFact] = []
    for identity in exact:
        latest = latest_by_mapping.get(identity.mapping.id)
        facts.append(
            _MappingFact(
                identity=identity,
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
        db.scalars(
            select(PriceRefreshRun)
            .order_by(PriceRefreshRun.started_at.desc())
            .limit(500)
        ).all()
    )
    latest: dict[str | None, PriceRefreshRun] = {}
    for run in runs:
        if run.source_filter not in latest:
            latest[run.source_filter] = run
    return latest


def _refresh_run_for_source(
    latest_by_filter: dict[str | None, PriceRefreshRun], source_name: str
) -> PriceRefreshRun | None:
    specific = latest_by_filter.get(source_name)
    combined = latest_by_filter.get(None)
    if specific is None:
        return combined
    if combined is None:
        return specific
    return (
        specific
        if _naive(specific.started_at) >= _naive(combined.started_at)
        else combined
    )


def _recent_refresh_stats(
    db: Session, source_name: str, now: datetime
) -> tuple[float, float | None, int]:
    """Returns (success_rate_pct, average_duration_seconds, error_count) over
    PriceRefreshRun rows scoped to source_name (source_filter == source_name
    or NULL, i.e. a combined run) within RECENT_REFRESH_LOOKBACK_DAYS."""
    cutoff = _naive(now) - timedelta(days=RECENT_REFRESH_LOOKBACK_DAYS)
    runs = list(
        db.scalars(
            select(PriceRefreshRun).where(
                (PriceRefreshRun.source_filter == source_name)
                | (PriceRefreshRun.source_filter.is_(None)),
                PriceRefreshRun.started_at >= cutoff,
                PriceRefreshRun.status.in_(RESOLVED_REFRESH_STATUSES),
            )
        ).all()
    )
    if not runs:
        return 0.0, None, 0

    succeeded = sum(
        1 for r in runs if r.status in ("completed", "completed_with_warnings")
    )
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
            .where(
                SnkrdunkDiscoveryRun.status == "blocked",
                SnkrdunkDiscoveryRun.started_at >= cutoff,
            )
        )
        or 0
    )


def _latest_discovery_run(db: Session) -> SnkrdunkDiscoveryRun | None:
    return db.scalar(
        select(SnkrdunkDiscoveryRun)
        .order_by(SnkrdunkDiscoveryRun.started_at.desc())
        .limit(1)
    )


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
    succeeded = sum(
        1 for r in runs if r.status in ("completed", "completed_with_warnings")
    )
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
        source_name == "snkrdunk"
        and latest_refresh_status is None
        and latest_discovery_status == "failed"
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
            warnings.append(
                f"{gap_pct}% of active mappings have a stale or missing price."
            )
            return "degraded", warnings

    if (
        has_resolved_runs
        and recent_refresh_success_rate_pct < DEGRADED_SUCCESS_RATE_PCT
    ):
        warnings.append(
            f"Recent refresh success rate is {recent_refresh_success_rate_pct}%."
        )
        return "degraded", warnings

    return "healthy", warnings


def _build_sources(
    db: Session,
    facts: list[_MappingFact],
    identities: list[SourceMappingIdentity],
    filters: PriceSourceHealthFilters,
    now: datetime,
) -> list[SourceHealthItem]:
    source_query = select(Source)
    if filters.source:
        source_query = source_query.where(Source.name == filters.source)
    sources = list(db.scalars(source_query.order_by(Source.name)).all())

    facts_by_source: dict[int, list[_MappingFact]] = defaultdict(list)
    for fact in facts:
        facts_by_source[fact.source.id].append(fact)

    identities_by_source: dict[int, list[SourceMappingIdentity]] = defaultdict(list)
    for identity in identities:
        if identity.source is not None:
            identities_by_source[identity.source.id].append(identity)

    latest_refresh_by_filter = _latest_refresh_runs_by_source(db)
    latest_discovery_run = _latest_discovery_run(db)

    items: list[SourceHealthItem] = []
    for source in sources:
        source_facts = facts_by_source.get(source.id, [])
        source_identities = identities_by_source.get(source.id, [])
        active_mapping_count = len(source_facts)
        recent = [f for f in source_facts if f.is_recent(now)]
        stale = [f for f in source_facts if f.is_stale(now)]
        missing = [f for f in source_facts if f.is_missing()]

        latest_observed_at = max(
            (
                f.latest_observed_at
                for f in source_facts
                if f.latest_observed_at is not None
            ),
            default=None,
        )

        latest_refresh_run = _refresh_run_for_source(
            latest_refresh_by_filter, source.name
        )
        success_rate, avg_duration, error_count_7d = _recent_refresh_stats(
            db, source.name, now
        )
        blocked_count_7d = _blocked_count_7d(db, source.name, now)

        latest_discovery_status = (
            latest_discovery_run.status
            if source.name == "snkrdunk" and latest_discovery_run
            else None
        )
        has_ever_refreshed = (
            latest_refresh_run is not None or latest_discovery_run is not None
        )
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
            latest_refresh_status=(
                latest_refresh_run.status if latest_refresh_run else None
            ),
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
                legacy_compatibility_mapping_count=sum(
                    identity.classification == LEGACY_COMPATIBILITY
                    for identity in source_identities
                ),
                broken_mapping_count=sum(
                    identity.classification == BROKEN for identity in source_identities
                ),
                latest_price_observed_at=latest_observed_at,
                latest_refresh_status=(
                    latest_refresh_run.status if latest_refresh_run else None
                ),
                latest_refresh_started_at=(
                    latest_refresh_run.started_at if latest_refresh_run else None
                ),
                latest_refresh_finished_at=(
                    latest_refresh_run.finished_at if latest_refresh_run else None
                ),
                recent_refresh_success_rate_pct=success_rate,
                average_refresh_duration_seconds=avg_duration,
                blocked_count_7d=blocked_count_7d,
                error_count_7d=error_count_7d,
                health_status=health_status,
                warnings=health_warnings,
            )
        )
    return items


def _breakdown_key(identity: SourceMappingIdentity, dimension: str) -> str:
    print_row = identity.card_print
    if print_row is None:
        return "none"
    if dimension == "release_product":
        product = identity.release_product
        value = (
            product.official_code
            or product.display_name
            or f"release_product:{product.id}"
            if product is not None
            else None
        )
    elif dimension == "rarity":
        value = print_row.official_rarity
    else:
        value = getattr(print_row, dimension)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return "none"
    return str(value)


def _build_breakdown(
    facts: list[_MappingFact], dimension: str, now: datetime
) -> list[HealthCoverageBreakdownItem]:
    by_print: dict[int, list[_MappingFact]] = defaultdict(list)
    for fact in facts:
        assert fact.identity.card_print_id is not None
        by_print[fact.identity.card_print_id].append(fact)

    groups: dict[str, HealthCoverageBreakdownItem] = {}
    for print_facts in by_print.values():
        key = _breakdown_key(print_facts[0].identity, dimension)
        item = groups.setdefault(key, HealthCoverageBreakdownItem(key=key, label=key))
        item.mapped_prints += 1
        if any(f.is_recent(now) for f in print_facts):
            item.recent_price_prints += 1
        elif any(not f.is_missing() for f in print_facts):
            item.stale_price_prints += 1
        else:
            item.missing_price_prints += 1
    return sorted(groups.values(), key=lambda i: i.key)


def _identity_gap_item(
    identity: SourceMappingIdentity,
    issue_type: str,
    severity: str,
    suggested_action: str,
    *,
    latest: tuple[datetime | None, str | None, int | None] = (None, None, None),
) -> PriceGapItem:
    canonical = identity.canonical_card
    print_row = identity.card_print
    product = identity.release_product
    compatibility_card = identity.compatibility_card
    return PriceGapItem(
        mapping_id=identity.mapping.id,
        source_id=identity.mapping.source_id,
        card_print_id=identity.card_print_id,
        canonical_card_id=identity.canonical_card_id,
        release_product_id=identity.release_product_id,
        compatibility_card_id=identity.compatibility_card_id,
        identity_classification=identity.classification,
        card_code=(
            canonical.card_code
            if canonical is not None
            else (
                compatibility_card.card_code if compatibility_card is not None else None
            )
        ),
        name_en=(
            canonical.name_en
            if canonical is not None
            else compatibility_card.name_en if compatibility_card is not None else None
        ),
        name_jp=(
            canonical.name_jp
            if canonical is not None
            else compatibility_card.name_jp if compatibility_card is not None else None
        ),
        release_product_code=product.official_code if product is not None else None,
        release_product_name=product.display_name if product is not None else None,
        rarity=print_row.official_rarity if print_row is not None else None,
        official_asset_variant=(
            print_row.official_asset_variant if print_row is not None else None
        ),
        treatment=print_row.treatment if print_row is not None else None,
        language=(
            print_row.language
            if print_row is not None
            else compatibility_card.language if compatibility_card is not None else None
        ),
        source_name=identity.source.name if identity.source is not None else None,
        source_url=identity.mapping.source_url,
        latest_price_observed_at=latest[0],
        latest_price_type=latest[1],
        latest_price_jpy=latest[2],
        issue_type=issue_type,
        severity=severity,
        suggested_action=suggested_action,
    )


def _gap_item(
    fact: _MappingFact, issue_type: str, severity: str, suggested_action: str
) -> PriceGapItem:
    return _identity_gap_item(
        fact.identity,
        issue_type,
        severity,
        suggested_action,
        latest=(
            fact.latest_observed_at,
            fact.latest_price_type,
            fact.latest_price_jpy,
        ),
    )


def _severity_sort_key(item: PriceGapItem) -> tuple:
    rank = {"critical": 0, "warning": 1, "review": 2}
    return (rank.get(item.severity, 3), item.card_code or "", item.mapping_id)


def _build_gaps(
    facts: list[_MappingFact],
    identities: list[SourceMappingIdentity],
    sources: list[SourceHealthItem],
    coverage_by_release_product: list[HealthCoverageBreakdownItem],
    coverage_by_rarity: list[HealthCoverageBreakdownItem],
    now: datetime,
) -> dict[str, list[PriceGapItem]]:
    stale_prices: list[PriceGapItem] = []
    missing_prices: list[PriceGapItem] = []
    for fact in facts:
        if fact.is_stale(now):
            stale_prices.append(
                _gap_item(fact, "stale_price", WARNING, "run_refresh_or_review_mapping")
            )
        elif fact.is_missing():
            missing_prices.append(
                _gap_item(
                    fact, "missing_price", WARNING, "run_refresh_or_review_mapping"
                )
            )

    failed_sources = {
        s.source_name for s in sources if s.latest_refresh_status == "failed"
    }
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

    low_coverage_products = {
        i.key
        for i in coverage_by_release_product
        if i.mapped_prints > 0 and _pct(i.recent_price_prints, i.mapped_prints) < 50.0
    }
    low_coverage_rarities = {
        i.key
        for i in coverage_by_rarity
        if i.mapped_prints > 0 and _pct(i.recent_price_prints, i.mapped_prints) < 50.0
    }
    low_coverage_gaps = [
        _gap_item(fact, "low_coverage", REVIEW, "review_source_mapping_coverage")
        for fact in facts
        if _breakdown_key(fact.identity, "release_product") in low_coverage_products
        or _breakdown_key(fact.identity, "rarity") in low_coverage_rarities
    ]

    compatibility_mappings = [
        _identity_gap_item(
            identity,
            LEGACY_COMPATIBILITY,
            REVIEW,
            "retain_as_legacy_compatibility",
        )
        for identity in identities
        if identity.classification == LEGACY_COMPATIBILITY
    ]
    broken_mappings = [
        _identity_gap_item(
            identity,
            BROKEN,
            CRITICAL,
            "investigate_mapping_identity",
        )
        for identity in identities
        if identity.classification == BROKEN
    ]

    return {
        "stale_prices": sorted(stale_prices, key=_severity_sort_key),
        "missing_prices": sorted(missing_prices, key=_severity_sort_key),
        "failed_refresh_gaps": sorted(failed_refresh_gaps, key=_severity_sort_key),
        "blocked_gaps": sorted(blocked_gaps, key=_severity_sort_key),
        "low_coverage_gaps": sorted(low_coverage_gaps, key=_severity_sort_key),
        "legacy_compatibility_mappings": sorted(
            compatibility_mappings, key=_severity_sort_key
        ),
        "broken_mappings": sorted(broken_mappings, key=_severity_sort_key),
    }


def _recent_refresh_runs(db: Session, limit: int = 10) -> list[RefreshRunSummaryItem]:
    runs = list(
        db.scalars(
            select(PriceRefreshRun)
            .order_by(PriceRefreshRun.started_at.desc())
            .limit(limit)
        ).all()
    )
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


def _build_summary(
    db: Session,
    sources: list[SourceHealthItem],
    identities: list[SourceMappingIdentity],
    now: datetime,
) -> dict[str, Any]:
    total_active_mappings = sum(s.active_mapping_count for s in sources)
    mappings_with_recent_price = sum(s.recent_price_count for s in sources)
    mappings_without_recent_price = total_active_mappings - mappings_with_recent_price
    stale_price_count = sum(s.stale_price_count for s in sources)
    missing_price_count = sum(s.missing_price_count for s in sources)

    successful_runs_at = [
        s.latest_refresh_finished_at
        for s in sources
        if s.latest_refresh_status in ("completed", "completed_with_warnings")
        and s.latest_refresh_finished_at
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
        "exact_mapping_count": sum(
            identity.classification == EXACT for identity in identities
        ),
        "legacy_compatibility_mapping_count": sum(
            identity.classification == LEGACY_COMPATIBILITY for identity in identities
        ),
        "broken_mapping_count": sum(
            identity.classification == BROKEN for identity in identities
        ),
        "total_active_mappings": total_active_mappings,
        "mappings_with_recent_price": mappings_with_recent_price,
        "mappings_without_recent_price": mappings_without_recent_price,
        "stale_price_count": stale_price_count,
        "missing_price_count": missing_price_count,
        "last_successful_refresh_at": (
            max(successful_runs_at) if successful_runs_at else None
        ),
        "last_failed_refresh_at": (
            max(r for r in failed_runs_at if r is not None)
            if any(r is not None for r in failed_runs_at)
            else None
        ),
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

    identities = _filtered_identities(db, filters)
    facts = _build_mapping_facts(db, identities)
    sources = _build_sources(db, facts, identities, filters, now)
    coverage_by_release_product = _build_breakdown(facts, "release_product", now)
    coverage_by_rarity = _build_breakdown(facts, "rarity", now)
    coverage_by_language = _build_breakdown(facts, "language", now)
    gaps = _build_gaps(
        facts,
        identities,
        sources,
        coverage_by_release_product,
        coverage_by_rarity,
        now,
    )
    summary = _build_summary(db, sources, identities, now)
    warnings = _build_warnings(sources)
    refresh_runs = _recent_refresh_runs(db)

    return PriceSourceHealthReport(
        summary=summary,
        sources=sources,
        coverage_by_release_product=coverage_by_release_product,
        coverage_by_rarity=coverage_by_rarity,
        coverage_by_language=coverage_by_language,
        stale_prices=gaps["stale_prices"],
        missing_prices=gaps["missing_prices"],
        failed_refresh_gaps=gaps["failed_refresh_gaps"],
        blocked_gaps=gaps["blocked_gaps"],
        low_coverage_gaps=gaps["low_coverage_gaps"],
        legacy_compatibility_mappings=gaps["legacy_compatibility_mappings"],
        broken_mappings=gaps["broken_mappings"],
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
