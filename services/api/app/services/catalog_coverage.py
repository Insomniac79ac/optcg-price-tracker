"""Catalog coverage reporting - a read-only aggregation answering "how
complete is the canonical card catalog" across sets/rarities/variants/
languages, source mappings, recent prices, collection/wishlist coverage,
metadata completeness, and the duplicate/mapping-quality risk already
surfaced by app.services.card_identity_merge and
app.services.source_mapping_confidence.

See GET /admin/catalog-coverage and GET /admin/catalog-coverage/gaps
(app.api.admin_catalog_coverage), `python -m app.catalog_coverage_report`,
and this module's summary-only integration into app.services.system_check
and app.services.card_audit (summarize_catalog_coverage).

Read-only: nothing here ever writes to the DB, scrapes anything, or calls an
LLM - every number below is a deterministic count/aggregate over data
already stored, and duplicate/mapping-quality scoring is delegated entirely
to the two modules named above rather than reimplemented here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Card, CollectionItem, PriceObservation, Source, SourceCardMapping, WishlistItem
from app.services.card_identity_merge import MIN_MERGE_SCORE, duplicate_pairs_at_or_above
from app.services.source_mapping_confidence import MappingQualityFilters, evaluate_source_mappings

SUPPORTED_MAPPING_SOURCES = ("yuyutei", "snkrdunk")

# Yuyu-Tei is scraped far more frequently than SNKRDUNK (see docs/operations.md's
# refresh schedule), so "recent" means something different per source - a card
# only counts as having a recent price for a given source if that source's own
# window is met.
RECENT_PRICE_WINDOWS = {"yuyutei": timedelta(hours=24), "snkrdunk": timedelta(days=7)}

GAP_TYPES = ("metadata", "mapping", "price", "duplicate", "mapping_quality")

CRITICAL = "critical"
WARNING = "warning"
REVIEW = "review"

# A large-enough-to-be-unbounded page size for internal calls into
# evaluate_source_mappings - that function computes every matching item
# regardless of `limit` (only the returned slice is affected, see its
# docstring), so this doesn't cost anything extra; it just avoids silently
# truncating the mapping-quality-risk sweep below.
_UNBOUNDED = 10_000_000

# Metadata fields considered for the catalog's overall completeness score -
# deliberately excludes gameplay fields (cost/power/counter/effect_text/...)
# since not every card needs them (see the feature spec's "do not require
# gameplay fields for metadata completion" rule).
METADATA_COMPLETION_FIELDS = (
    "name_en",
    "set_code",
    "rarity",
    "variant",
    "language",
    "image_url",
    "artist",
    "character",
    "color",
    "card_type",
)

# Superset used for gap severity/issue_types - card_code is never part of the
# completion-percentage denominator (it's a required DB column, effectively
# always present), but a blank one is still worth flagging as critical.
_CRITICAL_METADATA_FIELDS = ("card_code", "name_en")
_WARNING_METADATA_FIELDS = ("set_code", "rarity", "variant", "language")
_REVIEW_METADATA_FIELDS = ("image_url", "artist", "character", "color", "card_type")
_METADATA_CHECK_FIELDS = ("card_code", *METADATA_COMPLETION_FIELDS)


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def _missing_metadata_fields(card: Card) -> list[str]:
    return [f for f in _METADATA_CHECK_FIELDS if _is_blank(getattr(card, f))]


def _has_incomplete_metadata(card: Card) -> bool:
    return any(_is_blank(getattr(card, f)) for f in METADATA_COMPLETION_FIELDS)


def _metadata_severity(missing_fields: list[str]) -> str | None:
    if not missing_fields:
        return None
    missing = set(missing_fields)
    if missing & set(_CRITICAL_METADATA_FIELDS):
        return CRITICAL
    if missing & set(_WARNING_METADATA_FIELDS):
        return WARNING
    return REVIEW


def _naive(dt: datetime) -> datetime:
    """Strips tzinfo if present, so a loaded row's timestamp (naive under
    SQLite, aware under Postgres) can be safely compared against
    datetime.now(timezone.utc) under either dialect - same helper as
    app.services.source_mapping_confidence/job_locks."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


@dataclass
class CatalogCoverageFilters:
    set_code: str | None = None
    language: str | None = None
    variant: str | None = None
    rarity: str | None = None
    include_inactive: bool = False


@dataclass
class CoverageGapItem:
    card_id: int
    card_code: str | None
    name_en: str | None
    name_jp: str | None
    set_code: str | None
    rarity: str | None
    variant: str | None
    language: str | None
    issue_types: list[str]
    severity: str
    suggested_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "card_code": self.card_code,
            "name_en": self.name_en,
            "name_jp": self.name_jp,
            "set_code": self.set_code,
            "rarity": self.rarity,
            "variant": self.variant,
            "language": self.language,
            "issue_types": self.issue_types,
            "severity": self.severity,
            "suggested_action": self.suggested_action,
        }


@dataclass
class CoverageBreakdownItem:
    key: str
    label: str
    total_cards: int = 0
    active_cards: int = 0
    mapped_cards: int = 0
    unmapped_cards: int = 0
    recent_price_cards: int = 0
    collection_cards: int = 0
    wishlist_cards: int = 0
    missing_metadata_cards: int = 0
    duplicate_risk_cards: int = 0
    mapping_quality_risk_cards: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "total_cards": self.total_cards,
            "active_cards": self.active_cards,
            "mapped_cards": self.mapped_cards,
            "unmapped_cards": self.unmapped_cards,
            "recent_price_cards": self.recent_price_cards,
            "collection_cards": self.collection_cards,
            "wishlist_cards": self.wishlist_cards,
            "missing_metadata_cards": self.missing_metadata_cards,
            "duplicate_risk_cards": self.duplicate_risk_cards,
            "mapping_quality_risk_cards": self.mapping_quality_risk_cards,
            "mapping_coverage_pct": _pct(self.mapped_cards, self.total_cards),
            "recent_price_coverage_pct": _pct(self.recent_price_cards, self.total_cards),
            "metadata_completion_pct": _pct(self.total_cards - self.missing_metadata_cards, self.total_cards),
        }


@dataclass
class CatalogCoverageReport:
    summary: dict[str, Any]
    coverage_by_set: list[CoverageBreakdownItem] = field(default_factory=list)
    coverage_by_rarity: list[CoverageBreakdownItem] = field(default_factory=list)
    coverage_by_variant: list[CoverageBreakdownItem] = field(default_factory=list)
    coverage_by_language: list[CoverageBreakdownItem] = field(default_factory=list)
    metadata_gaps: list[CoverageGapItem] = field(default_factory=list)
    mapping_gaps: list[CoverageGapItem] = field(default_factory=list)
    price_gaps: list[CoverageGapItem] = field(default_factory=list)
    duplicate_risks: list[CoverageGapItem] = field(default_factory=list)
    mapping_quality_risks: list[CoverageGapItem] = field(default_factory=list)

    def gaps_for(self, gap_type: str) -> list[CoverageGapItem]:
        return {
            "metadata": self.metadata_gaps,
            "mapping": self.mapping_gaps,
            "price": self.price_gaps,
            "duplicate": self.duplicate_risks,
            "mapping_quality": self.mapping_quality_risks,
        }[gap_type]

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "coverage_by_set": [i.to_dict() for i in self.coverage_by_set],
            "coverage_by_rarity": [i.to_dict() for i in self.coverage_by_rarity],
            "coverage_by_variant": [i.to_dict() for i in self.coverage_by_variant],
            "coverage_by_language": [i.to_dict() for i in self.coverage_by_language],
            "metadata_gaps": [i.to_dict() for i in self.metadata_gaps],
            "mapping_gaps": [i.to_dict() for i in self.mapping_gaps],
            "price_gaps": [i.to_dict() for i in self.price_gaps],
            "duplicate_risks": [i.to_dict() for i in self.duplicate_risks],
            "mapping_quality_risks": [i.to_dict() for i in self.mapping_quality_risks],
        }


def _filtered_cards(db: Session, filters: CatalogCoverageFilters) -> list[Card]:
    query = select(Card)
    conditions = []
    if not filters.include_inactive:
        conditions.append(Card.is_active.is_(True))
    if filters.set_code:
        conditions.append(Card.set_code == filters.set_code)
    if filters.language:
        conditions.append(Card.language == filters.language)
    if filters.variant:
        conditions.append(Card.variant == filters.variant)
    if filters.rarity:
        conditions.append(Card.rarity == filters.rarity)
    if conditions:
        query = query.where(*conditions)
    return list(db.scalars(query).all())


def _mapped_sources_by_card(db: Session, card_ids: set[int]) -> dict[int, set[str]]:
    if not card_ids:
        return {}
    rows = db.execute(
        select(SourceCardMapping.card_id, Source.name)
        .join(Source, SourceCardMapping.source_id == Source.id)
        .where(
            SourceCardMapping.card_id.in_(card_ids),
            SourceCardMapping.is_active.is_(True),
            Source.name.in_(SUPPORTED_MAPPING_SOURCES),
        )
    ).all()
    result: dict[int, set[str]] = defaultdict(set)
    for card_id, source_name in rows:
        result[card_id].add(source_name)
    return result


def _latest_price_by_card_source(db: Session, card_ids: set[int]) -> dict[int, dict[str, datetime]]:
    if not card_ids:
        return {}
    rows = db.execute(
        select(
            PriceObservation.card_id,
            Source.name,
            func.max(PriceObservation.observed_at),
        )
        .join(Source, PriceObservation.source_id == Source.id)
        .where(PriceObservation.card_id.in_(card_ids), Source.name.in_(SUPPORTED_MAPPING_SOURCES))
        .group_by(PriceObservation.card_id, Source.name)
    ).all()
    result: dict[int, dict[str, datetime]] = defaultdict(dict)
    for card_id, source_name, observed_at in rows:
        result[card_id][source_name] = observed_at
    return result


def _recent_price_sources(latest_by_source: dict[str, datetime], now: datetime) -> set[str]:
    recent: set[str] = set()
    for source_name, window in RECENT_PRICE_WINDOWS.items():
        observed_at = latest_by_source.get(source_name)
        if observed_at is not None and _naive(observed_at) >= _naive(now) - window:
            recent.add(source_name)
    return recent


def _card_ids_with_rows(db: Session, model, card_ids: set[int]) -> set[int]:
    if not card_ids:
        return set()
    return set(
        db.scalars(
            select(model.card_id).where(model.card_id.in_(card_ids)).distinct()
        ).all()
    )


@dataclass
class _CardFacts:
    card: Card
    mapped_sources: set[str] = field(default_factory=set)
    recent_price_sources: set[str] = field(default_factory=set)
    in_collection: bool = False
    on_wishlist: bool = False
    missing_metadata_fields: list[str] = field(default_factory=list)
    duplicate_confidence: str | None = None
    mapping_quality_risk_level: str | None = None
    mapping_quality_issue_types: list[str] = field(default_factory=list)


def _build_card_facts(db: Session, cards: list[Card]) -> dict[int, _CardFacts]:
    card_ids = {c.id for c in cards}
    now = datetime.now(timezone.utc)

    mapped_sources = _mapped_sources_by_card(db, card_ids)
    latest_prices = _latest_price_by_card_source(db, card_ids)
    collection_ids = _card_ids_with_rows(db, CollectionItem, card_ids)
    wishlist_ids = _card_ids_with_rows(db, WishlistItem, card_ids)

    duplicate_confidence: dict[int, str] = {}
    # DUPLICATE_LABEL_THRESHOLDS-ordered rank so the "worst" (highest) label
    # wins when a card appears in more than one flagged pair.
    _label_rank = {"exact_duplicate": 3, "likely_duplicate": 2, "possible_duplicate": 1, "weak_match": 0}
    for pair in duplicate_pairs_at_or_above(db, MIN_MERGE_SCORE):
        for c in (pair.source_card, pair.target_card):
            if c.id not in card_ids:
                continue
            current = duplicate_confidence.get(c.id)
            if current is None or _label_rank.get(pair.confidence_label, 0) > _label_rank.get(current, 0):
                duplicate_confidence[c.id] = pair.confidence_label

    mapping_quality_risk: dict[int, tuple[str, set[str]]] = {}
    _risk_rank = {"critical": 2, "warning": 1}
    items, _total, _mq_summary = evaluate_source_mappings(
        db, MappingQualityFilters(), limit=_UNBOUNDED, offset=0
    )
    for item in items:
        if item.risk_level not in ("critical", "warning") or item.card_id not in card_ids:
            continue
        current = mapping_quality_risk.get(item.card_id)
        if current is None or _risk_rank.get(item.risk_level, 0) > _risk_rank.get(current[0], 0):
            issue_types = current[1] if current else set()
            mapping_quality_risk[item.card_id] = (item.risk_level, issue_types | set(item.issue_types))
        else:
            mapping_quality_risk[item.card_id] = (current[0], current[1] | set(item.issue_types))

    facts: dict[int, _CardFacts] = {}
    for card in cards:
        latest_by_source = latest_prices.get(card.id, {})
        risk = mapping_quality_risk.get(card.id)
        facts[card.id] = _CardFacts(
            card=card,
            mapped_sources=mapped_sources.get(card.id, set()),
            recent_price_sources=_recent_price_sources(latest_by_source, now),
            in_collection=card.id in collection_ids,
            on_wishlist=card.id in wishlist_ids,
            missing_metadata_fields=_missing_metadata_fields(card),
            duplicate_confidence=duplicate_confidence.get(card.id),
            mapping_quality_risk_level=risk[0] if risk else None,
            mapping_quality_issue_types=sorted(risk[1]) if risk else [],
        )
    return facts


def _breakdown_key(card: Card, dimension: str) -> str:
    value = getattr(card, dimension)
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return "none"
    return value


def _build_breakdown(facts_by_id: dict[int, _CardFacts], dimension: str) -> list[CoverageBreakdownItem]:
    groups: dict[str, CoverageBreakdownItem] = {}
    for facts in facts_by_id.values():
        key = _breakdown_key(facts.card, dimension)
        item = groups.setdefault(key, CoverageBreakdownItem(key=key, label=key))
        item.total_cards += 1
        if facts.card.is_active:
            item.active_cards += 1
        if facts.mapped_sources:
            item.mapped_cards += 1
        else:
            item.unmapped_cards += 1
        if facts.recent_price_sources:
            item.recent_price_cards += 1
        if facts.in_collection:
            item.collection_cards += 1
        if facts.on_wishlist:
            item.wishlist_cards += 1
        if _has_incomplete_metadata(facts.card):
            item.missing_metadata_cards += 1
        if facts.duplicate_confidence is not None:
            item.duplicate_risk_cards += 1
        if facts.mapping_quality_risk_level is not None:
            item.mapping_quality_risk_cards += 1
    return sorted(groups.values(), key=lambda i: i.key)


_DUPLICATE_SEVERITY = {
    "exact_duplicate": CRITICAL,
    "likely_duplicate": CRITICAL,
    "possible_duplicate": WARNING,
    "weak_match": REVIEW,
}


def _gap_item(facts: _CardFacts, issue_types: list[str], severity: str, suggested_action: str) -> CoverageGapItem:
    card = facts.card
    return CoverageGapItem(
        card_id=card.id,
        card_code=card.card_code,
        name_en=card.name_en,
        name_jp=card.name_jp,
        set_code=card.set_code,
        rarity=card.rarity,
        variant=card.variant,
        language=card.language,
        issue_types=issue_types,
        severity=severity,
        suggested_action=suggested_action,
    )


def _build_gaps(facts_by_id: dict[int, _CardFacts]) -> dict[str, list[CoverageGapItem]]:
    metadata_gaps: list[CoverageGapItem] = []
    mapping_gaps: list[CoverageGapItem] = []
    price_gaps: list[CoverageGapItem] = []
    duplicate_risks: list[CoverageGapItem] = []
    mapping_quality_risks: list[CoverageGapItem] = []

    for facts in facts_by_id.values():
        if facts.missing_metadata_fields:
            severity = _metadata_severity(facts.missing_metadata_fields)
            metadata_gaps.append(
                _gap_item(
                    facts,
                    [f"missing_{f}" for f in facts.missing_metadata_fields],
                    severity or REVIEW,
                    "update_catalog_metadata",
                )
            )

        missing_sources = [s for s in SUPPORTED_MAPPING_SOURCES if s not in facts.mapped_sources]
        if missing_sources:
            severity = CRITICAL if len(missing_sources) == len(SUPPORTED_MAPPING_SOURCES) else WARNING
            mapping_gaps.append(
                _gap_item(
                    facts,
                    [f"missing_{s}_mapping" for s in missing_sources],
                    severity,
                    "add_source_mapping",
                )
            )

        stale_sources = [s for s in SUPPORTED_MAPPING_SOURCES if s not in facts.recent_price_sources]
        if stale_sources:
            severity = CRITICAL if len(stale_sources) == len(SUPPORTED_MAPPING_SOURCES) else WARNING
            price_gaps.append(
                _gap_item(
                    facts,
                    [f"missing_recent_{s}_price" for s in stale_sources],
                    severity,
                    "review_price_refresh",
                )
            )

        if facts.duplicate_confidence is not None:
            duplicate_risks.append(
                _gap_item(
                    facts,
                    [f"possible_duplicate_{facts.duplicate_confidence}"],
                    _DUPLICATE_SEVERITY.get(facts.duplicate_confidence, WARNING),
                    "review_card_merge",
                )
            )

        if facts.mapping_quality_risk_level is not None:
            mapping_quality_risks.append(
                _gap_item(
                    facts,
                    facts.mapping_quality_issue_types,
                    facts.mapping_quality_risk_level,
                    "review_source_mapping_quality",
                )
            )

    def _sort_key(item: CoverageGapItem) -> tuple:
        severity_rank = {"critical": 0, "warning": 1, "review": 2}
        return (severity_rank.get(item.severity, 3), item.card_code or "", item.card_id)

    return {
        "metadata_gaps": sorted(metadata_gaps, key=_sort_key),
        "mapping_gaps": sorted(mapping_gaps, key=_sort_key),
        "price_gaps": sorted(price_gaps, key=_sort_key),
        "duplicate_risks": sorted(duplicate_risks, key=_sort_key),
        "mapping_quality_risks": sorted(mapping_quality_risks, key=_sort_key),
    }


def _build_summary(cards: list[Card], facts_by_id: dict[int, _CardFacts]) -> dict[str, Any]:
    total_cards = len(cards)
    active_cards = sum(1 for c in cards if c.is_active)
    inactive_merged_cards = total_cards - active_cards
    sets_count = len({c.set_code for c in cards if c.set_code})

    cards_with_yuyutei_mapping = sum(1 for f in facts_by_id.values() if "yuyutei" in f.mapped_sources)
    cards_with_snkrdunk_mapping = sum(1 for f in facts_by_id.values() if "snkrdunk" in f.mapped_sources)
    cards_without_any_mapping = sum(1 for f in facts_by_id.values() if not f.mapped_sources)

    cards_with_recent_yuyutei_price = sum(
        1 for f in facts_by_id.values() if "yuyutei" in f.recent_price_sources
    )
    cards_with_recent_snkrdunk_price = sum(
        1 for f in facts_by_id.values() if "snkrdunk" in f.recent_price_sources
    )
    cards_without_recent_price = sum(1 for f in facts_by_id.values() if not f.recent_price_sources)

    cards_in_collection = sum(1 for f in facts_by_id.values() if f.in_collection)
    cards_on_wishlist = sum(1 for f in facts_by_id.values() if f.on_wishlist)
    cards_with_missing_metadata = sum(1 for c in cards if _has_incomplete_metadata(c))
    cards_with_duplicate_risk = sum(1 for f in facts_by_id.values() if f.duplicate_confidence is not None)
    cards_with_mapping_quality_risk = sum(
        1 for f in facts_by_id.values() if f.mapping_quality_risk_level is not None
    )

    return {
        "total_cards": total_cards,
        "active_cards": active_cards,
        "inactive_merged_cards": inactive_merged_cards,
        "sets_count": sets_count,
        "cards_with_yuyutei_mapping": cards_with_yuyutei_mapping,
        "cards_with_snkrdunk_mapping": cards_with_snkrdunk_mapping,
        "cards_without_any_mapping": cards_without_any_mapping,
        "cards_with_recent_yuyutei_price": cards_with_recent_yuyutei_price,
        "cards_with_recent_snkrdunk_price": cards_with_recent_snkrdunk_price,
        "cards_without_recent_price": cards_without_recent_price,
        "cards_in_collection": cards_in_collection,
        "cards_on_wishlist": cards_on_wishlist,
        "cards_with_missing_metadata": cards_with_missing_metadata,
        "cards_with_duplicate_risk": cards_with_duplicate_risk,
        "cards_with_mapping_quality_risk": cards_with_mapping_quality_risk,
        "metadata_completion_pct": _pct(total_cards - cards_with_missing_metadata, total_cards),
        "mapping_coverage_pct": _pct(total_cards - cards_without_any_mapping, total_cards),
        "recent_price_coverage_pct": _pct(total_cards - cards_without_recent_price, total_cards),
    }


def compute_catalog_coverage(
    db: Session, filters: CatalogCoverageFilters | None = None, *, include_gaps: bool = True
) -> CatalogCoverageReport:
    """Computes the full catalog coverage report for the given filters. Pass
    include_gaps=False (see summarize_catalog_coverage) to skip building the
    five gap-item lists when only the summary counts are needed - the
    per-card facts (mapping/price/metadata/duplicate/mapping-quality) still
    have to be computed either way, but this avoids the extra allocation and
    sort for callers (system_check, card_audit) that run on every request
    and only look at aggregate counts."""
    filters = filters or CatalogCoverageFilters()
    cards = _filtered_cards(db, filters)
    facts_by_id = _build_card_facts(db, cards)

    summary = _build_summary(cards, facts_by_id)
    coverage_by_set = _build_breakdown(facts_by_id, "set_code")
    coverage_by_rarity = _build_breakdown(facts_by_id, "rarity")
    coverage_by_variant = _build_breakdown(facts_by_id, "variant")
    coverage_by_language = _build_breakdown(facts_by_id, "language")

    gaps = (
        _build_gaps(facts_by_id)
        if include_gaps
        else {
            "metadata_gaps": [],
            "mapping_gaps": [],
            "price_gaps": [],
            "duplicate_risks": [],
            "mapping_quality_risks": [],
        }
    )

    return CatalogCoverageReport(
        summary=summary,
        coverage_by_set=coverage_by_set,
        coverage_by_rarity=coverage_by_rarity,
        coverage_by_variant=coverage_by_variant,
        coverage_by_language=coverage_by_language,
        **gaps,
    )


def summarize_catalog_coverage(db: Session) -> dict[str, Any]:
    """Unfiltered summary-only view (no gap lists) - used by
    app.services.system_check and app.services.card_audit so neither has to
    pull in the full gap breakdown just to report a handful of top-line
    numbers. See GET /admin/catalog-coverage for the full report."""
    return compute_catalog_coverage(db, CatalogCoverageFilters(), include_gaps=False).summary


def paginated_gaps(
    db: Session,
    gap_type: str,
    filters: CatalogCoverageFilters,
    *,
    severity: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[CoverageGapItem], int]:
    """Returns (page_of_items, total_matching) for one gap_type - used by GET
    /admin/catalog-coverage/gaps. Recomputes the report scoped to `filters`
    (the same set_code/rarity/variant/language/include_inactive filters the
    main endpoint takes) rather than reusing a cached copy, since this
    endpoint is meant for drilling into a specific slice on demand."""
    report = compute_catalog_coverage(db, filters, include_gaps=True)
    items = report.gaps_for(gap_type)
    if severity is not None:
        items = [i for i in items if i.severity == severity]
    total = len(items)
    return items[offset : offset + limit], total
