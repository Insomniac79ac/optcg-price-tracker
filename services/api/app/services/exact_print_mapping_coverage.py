"""Read-only source-mapping coverage for authoritative Japanese CardPrints.

The denominator is the physical print, never a card-code-derived set.  A
source mapping counts only through ``SourceCardMapping.card_print_id``;
``card_id`` is surfaced solely as legacy compatibility evidence.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import (
    CanonicalCard,
    CardPrint,
    PriceObservation,
    ReleaseProduct,
    Source,
    SourceCardMapping,
    SourceCollectionAttempt,
)
from app.services.print_catalogue import effective_rarity
from app.services.print_market_index import get_market_index_for_prints
from app.services.source_mapping_identity import (
    EXACT,
    LEGACY_COMPATIBILITY,
    SourceMappingIdentity,
    load_source_mapping_identities,
)

YUYUTEI = "yuyutei"
SNKRDUNK = "snkrdunk"
SUPPORTED_SOURCES = (YUYUTEI, SNKRDUNK)
JAPANESE_LANGUAGE = "jp"

EXACT_APPROVED_ACTIVE = "exact_approved_active"
EXACT_NEEDS_REVIEW = "exact_needs_review"
EXACT_REJECTED = "exact_rejected"
EXACT_INACTIVE = "exact_inactive"
LEGACY_CARD_ONLY = "legacy_card_only"
UNMAPPED = "unmapped"
AMBIGUOUS_MULTIPLE_EXACT_MAPPINGS = "ambiguous_multiple_exact_mappings"

MAPPING_STATES = (
    EXACT_APPROVED_ACTIVE,
    EXACT_NEEDS_REVIEW,
    EXACT_REJECTED,
    EXACT_INACTIVE,
    LEGACY_CARD_ONLY,
    UNMAPPED,
    AMBIGUOUS_MULTIPLE_EXACT_MAPPINGS,
)

NEVER_ATTEMPTED = "never_attempted"
ATTEMPTED_NO_OBSERVATION = "attempted_no_observation"
HAS_OBSERVATION = "has_observation"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass(frozen=True)
class CurrentRepresentative:
    available: bool
    value_jpy: int | None
    observed_at: datetime | None
    reference_type: str
    evidence_type: str
    eligible: bool
    stale: bool
    constraint: str | None
    unavailable_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "value_jpy": self.value_jpy,
            "observed_at": _iso(self.observed_at),
            "reference_type": self.reference_type,
            "evidence_type": self.evidence_type,
            "eligible": self.eligible,
            "stale": self.stale,
            "constraint": self.constraint,
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True)
class MappingEvidence:
    status: str
    latest_collection_attempt_status: str | None = None
    latest_attempt_at: datetime | None = None
    latest_observation_at: datetime | None = None
    latest_price_jpy: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "latest_collection_attempt_status": self.latest_collection_attempt_status,
            "latest_attempt_at": _iso(self.latest_attempt_at),
            "latest_observation_at": _iso(self.latest_observation_at),
            "latest_price_jpy": self.latest_price_jpy,
        }


@dataclass(frozen=True)
class PrintSourceCoverage:
    source: str
    mapping_state: str
    exact_mapping_ids: tuple[int, ...] = ()
    legacy_mapping_ids: tuple[int, ...] = ()
    evidence: MappingEvidence | None = None
    current_representative: CurrentRepresentative | None = None

    @property
    def exact_approved_active(self) -> bool:
        return self.mapping_state == EXACT_APPROVED_ACTIVE

    @property
    def has_observation(self) -> bool:
        return self.evidence is not None and self.evidence.status == HAS_OBSERVATION

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "mapping_state": self.mapping_state,
            "exact_mapping_ids": list(self.exact_mapping_ids),
            "legacy_mapping_ids": list(self.legacy_mapping_ids),
            "price_evidence": self.evidence.to_dict() if self.evidence else None,
            "current_representative": (
                self.current_representative.to_dict()
                if self.current_representative
                else None
            ),
        }


@dataclass(frozen=True)
class ExactPrintCoverageRow:
    card_print_id: int
    canonical_card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    release_product_id: int
    release_official_code: str | None
    release_display_name: str
    language: str
    official_asset_variant: str
    treatment: str | None
    official_rarity: str | None
    display_rarity: str | None
    image_url: str | None
    artwork_key: str
    sources: dict[str, PrintSourceCoverage]
    priority: str
    priority_reason: str

    def to_gap_dict(self) -> dict[str, Any]:
        return {
            "card_print_id": self.card_print_id,
            "canonical_card_id": self.canonical_card_id,
            "card_code": self.card_code,
            "name_en": self.name_en,
            "name_jp": self.name_jp,
            "release_product_id": self.release_product_id,
            "release_official_code": self.release_official_code,
            "release_display_name": self.release_display_name,
            "official_asset_variant": self.official_asset_variant,
            "treatment": self.treatment,
            "official_rarity": self.official_rarity,
            "display_rarity": self.display_rarity,
            "image_url": self.image_url,
            "artwork_key": self.artwork_key,
            "yuyutei_mapping_state": self.sources[YUYUTEI].mapping_state,
            "snkrdunk_mapping_state": self.sources[SNKRDUNK].mapping_state,
            "priority": self.priority,
            "priority_reason": self.priority_reason,
        }


@dataclass
class ReleaseCoverage:
    release_product_id: int
    official_code: str | None
    display_name: str
    total_verified_active_jp_prints: int = 0
    source_state_counts: dict[str, Counter[str]] = field(
        default_factory=lambda: {source: Counter() for source in SUPPORTED_SOURCES}
    )
    source_observation_counts: Counter[str] = field(default_factory=Counter)
    mapped_by_both: int = 0
    mapped_by_yuyutei_only: int = 0
    mapped_by_snkrdunk_only: int = 0
    mapped_by_neither: int = 0
    any_price_observation_coverage: int = 0
    both_source_observation_coverage: int = 0

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "release_product_id": self.release_product_id,
            "official_code": self.official_code,
            "display_name": self.display_name,
            "total_verified_active_jp_prints": self.total_verified_active_jp_prints,
            "mapped_by_both": self.mapped_by_both,
            "mapped_by_yuyutei_only": self.mapped_by_yuyutei_only,
            "mapped_by_snkrdunk_only": self.mapped_by_snkrdunk_only,
            "mapped_by_neither": self.mapped_by_neither,
            "any_price_observation_coverage": self.any_price_observation_coverage,
            "both_source_observation_coverage": self.both_source_observation_coverage,
        }
        for source in SUPPORTED_SOURCES:
            counts = self.source_state_counts[source]
            result[source] = {
                **{state: counts[state] for state in MAPPING_STATES},
                "mappings_with_any_observation": self.source_observation_counts[source],
            }
        return result


@dataclass
class ExactPrintMappingCoverageReport:
    prints: list[ExactPrintCoverageRow]
    releases: list[ReleaseCoverage]
    overall: dict[str, Any]
    gap_total: int
    gap_limit: int
    gap_offset: int
    gap_page: list[ExactPrintCoverageRow]
    op17_mixed_code_findings: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": {
                "coverage_unit": "physical_card_print",
                "language": JAPANESE_LANGUAGE,
                "required_print_state": "active_verified_with_authoritative_identity",
                "authoritative_mapping_lineage": "source_card_mappings.card_print_id",
                "legacy_card_id_role": "compatibility_metadata_only",
                "release_grouping": "card_prints.release_product_id",
                "sources": list(SUPPORTED_SOURCES),
                "mapping_states": list(MAPPING_STATES),
                "priority_chronology_available": False,
                "priority_chronology_limitation": (
                    "release_products has no authoritative release-date field; "
                    "P0 newest-release ordering is intentionally omitted"
                ),
            },
            "overall": self.overall,
            "releases": [release.to_dict() for release in self.releases],
            "gaps": {
                "total": self.gap_total,
                "limit": self.gap_limit,
                "offset": self.gap_offset,
                "items": [row.to_gap_dict() for row in self.gap_page],
            },
            "op17_mixed_code_findings": self.op17_mixed_code_findings,
        }


def _denominator(
    db: Session,
) -> list[tuple[CardPrint, CanonicalCard, ReleaseProduct]]:
    """The collector-facing active, verified Japanese physical catalogue."""
    stmt = (
        select(CardPrint, CanonicalCard, ReleaseProduct)
        .join(CanonicalCard, CanonicalCard.id == CardPrint.canonical_card_id)
        .join(ReleaseProduct, ReleaseProduct.id == CardPrint.release_product_id)
        .where(
            CardPrint.is_active.is_(True),
            CardPrint.verification_status == "verified",
            CardPrint.language == JAPANESE_LANGUAGE,
            CardPrint.canonical_card_id.is_not(None),
            CardPrint.release_product_id.is_not(None),
            CardPrint.official_asset_variant.is_not(None),
            CardPrint.artwork_key.is_not(None),
        )
        .order_by(CardPrint.id)
    )
    return list(db.execute(stmt).all())


def _classify_exact_rows(mappings: list[SourceCardMapping]) -> str:
    """Classify one print/source without selecting among conflicting rows.

    Rejected or inactive rows are historical/non-operational and do not
    conflict with one live candidate.  More than one active non-rejected row
    is ambiguous because either could become authoritative; no row is chosen.
    """
    if not mappings:
        return UNMAPPED
    live_candidates = [
        mapping
        for mapping in mappings
        if mapping.superseded_at is None and mapping.is_active and mapping.review_status != "rejected"
    ]
    if len(live_candidates) > 1:
        return AMBIGUOUS_MULTIPLE_EXACT_MAPPINGS
    if len(live_candidates) == 1:
        return (
            EXACT_APPROVED_ACTIVE
            if live_candidates[0].review_status == "approved"
            else EXACT_NEEDS_REVIEW
        )
    if any(mapping.is_active and mapping.superseded_at is None for mapping in mappings):
        return EXACT_REJECTED
    return EXACT_INACTIVE


def _latest_attempts(
    db: Session, mapping_ids: set[int]
) -> dict[int, SourceCollectionAttempt]:
    if not mapping_ids:
        return {}
    rows = db.scalars(
        select(SourceCollectionAttempt)
        .where(SourceCollectionAttempt.source_card_mapping_id.in_(mapping_ids))
        .order_by(
            SourceCollectionAttempt.source_card_mapping_id,
            SourceCollectionAttempt.selected_at.desc(),
            SourceCollectionAttempt.id.desc(),
        )
    ).all()
    result: dict[int, SourceCollectionAttempt] = {}
    for row in rows:
        result.setdefault(row.source_card_mapping_id, row)
    return result


def _latest_observations(
    db: Session, mapping_ids: set[int]
) -> dict[int, PriceObservation]:
    if not mapping_ids:
        return {}
    rows = db.scalars(
        select(PriceObservation)
        .join(
            SourceCardMapping,
            and_(
                SourceCardMapping.id == PriceObservation.source_card_mapping_id,
                SourceCardMapping.card_print_id == PriceObservation.card_print_id,
                SourceCardMapping.source_id == PriceObservation.source_id,
            ),
        )
        .where(PriceObservation.source_card_mapping_id.in_(mapping_ids))
        .order_by(
            PriceObservation.source_card_mapping_id,
            PriceObservation.observed_at.desc(),
            PriceObservation.id.desc(),
        )
    ).all()
    result: dict[int, PriceObservation] = {}
    for row in rows:
        assert row.source_card_mapping_id is not None
        result.setdefault(row.source_card_mapping_id, row)
    return result


def _evidence_for(
    mapping: SourceCardMapping,
    latest_attempts: dict[int, SourceCollectionAttempt],
    latest_observations: dict[int, PriceObservation],
) -> MappingEvidence:
    attempt = latest_attempts.get(mapping.id)
    observation = latest_observations.get(mapping.id)
    if observation is not None:
        status = HAS_OBSERVATION
    elif attempt is not None:
        status = ATTEMPTED_NO_OBSERVATION
    else:
        status = NEVER_ATTEMPTED
    return MappingEvidence(
        status=status,
        latest_collection_attempt_status=attempt.status if attempt else None,
        latest_attempt_at=(attempt.started_at or attempt.selected_at) if attempt else None,
        latest_observation_at=observation.observed_at if observation else None,
        latest_price_jpy=observation.price_jpy if observation else None,
    )


def _representatives(db: Session, print_ids: list[int]) -> dict[tuple[int, str], CurrentRepresentative]:
    results: dict[tuple[int, str], CurrentRepresentative] = {}
    if not print_ids:
        return results
    resolved = get_market_index_for_prints(db, print_ids)
    for print_id, market_index in resolved.items():
        for value in market_index.source_values:
            if value.source not in SUPPORTED_SOURCES:
                continue
            results[(print_id, value.source)] = CurrentRepresentative(
                available=value.eligible and value.value_jpy is not None,
                value_jpy=value.value_jpy,
                observed_at=value.observed_at,
                reference_type=value.reference_type,
                evidence_type=value.evidence_type,
                eligible=value.eligible,
                stale=value.stale,
                constraint=value.constraint,
                unavailable_reason=value.ineligible_reason,
            )
    return results


def _priority(row_sources: dict[str, PrintSourceCoverage], rarity: str | None, treatment: str | None) -> tuple[str, str]:
    rarity_token = rarity.strip().upper() if rarity else None
    treatment_token = treatment.strip().lower() if treatment else None
    if rarity_token in {"SP", "SP CARD", "SPカード", "SEC", "SR"} or (
        treatment_token is not None
        and ("parallel" in treatment_token or "special" in treatment_token)
    ):
        return "P1", "authoritative rarity/treatment marks a special or high-interest print"
    mapped = sum(item.exact_approved_active for item in row_sources.values())
    if mapped == 1:
        return "P2", "one source has exact approved coverage and the other does not"
    return "P3", "remaining verified exact-print mapping work"


def _op17_findings(rows: list[ExactPrintCoverageRow]) -> dict[str, Any] | None:
    op17_rows = [row for row in rows if row.release_official_code == "OP-17"]
    if not op17_rows:
        return None
    mixed = [row for row in op17_rows if not row.card_code.upper().startswith("OP17-")]
    return {
        "release_product_id": op17_rows[0].release_product_id,
        "official_code": "OP-17",
        "display_name": op17_rows[0].release_display_name,
        "total_physical_prints": len(op17_rows),
        "non_op17_card_code_prefix_prints": len(mixed),
        "example_card_codes": sorted({row.card_code for row in mixed})[:20],
        "grouping_basis": "card_prints.release_product_id",
        "prefix_used_for_membership": False,
    }


def _compute_exact_print_mapping_coverage(
    db: Session,
    *,
    gap_limit: int = 100,
    gap_offset: int = 0,
) -> ExactPrintMappingCoverageReport:
    """Build the report using SELECTs only; never flush or mutate the session."""
    if gap_limit < 1 or gap_limit > 1000:
        raise ValueError("gap_limit must be between 1 and 1000")
    if gap_offset < 0:
        raise ValueError("gap_offset must be non-negative")

    denominator = _denominator(db)
    print_ids = [print_row.id for print_row, _canonical, _product in denominator]

    identities = load_source_mapping_identities(
        db, conditions=(Source.name.in_(SUPPORTED_SOURCES),)
    )
    exact_by_pair: dict[tuple[int, str], list[SourceMappingIdentity]] = defaultdict(list)
    legacy_by_card: dict[tuple[str, str, str], list[SourceMappingIdentity]] = defaultdict(list)
    for identity in identities:
        if identity.source is None:
            continue
        if identity.classification == EXACT and identity.card_print_id in print_ids:
            assert identity.card_print_id is not None
            exact_by_pair[(identity.card_print_id, identity.source.name)].append(identity)
        elif identity.classification == LEGACY_COMPATIBILITY and identity.compatibility_card:
            card = identity.compatibility_card
            # Exact equality is a compatibility projection only. It never
            # assigns this mapping to a physical print or counts as coverage.
            legacy_by_card[(card.card_code, card.language, identity.source.name)].append(identity)

    pair_states: dict[tuple[int, str], str] = {}
    approved_mapping_by_pair: dict[tuple[int, str], SourceCardMapping] = {}
    approved_mapping_ids: set[int] = set()
    for print_row, _canonical, _product in denominator:
        for source in SUPPORTED_SOURCES:
            identities_for_pair = exact_by_pair.get((print_row.id, source), [])
            mappings = [identity.mapping for identity in identities_for_pair]
            state = _classify_exact_rows(mappings)
            pair_states[(print_row.id, source)] = state
            if state == EXACT_APPROVED_ACTIVE:
                mapping = next(
                    mapping
                    for mapping in mappings
                    if mapping.superseded_at is None and mapping.is_active and mapping.review_status == "approved"
                )
                approved_mapping_by_pair[(print_row.id, source)] = mapping
                approved_mapping_ids.add(mapping.id)

    latest_attempts = _latest_attempts(db, approved_mapping_ids)
    latest_observations = _latest_observations(db, approved_mapping_ids)
    representatives = _representatives(db, print_ids)

    rows: list[ExactPrintCoverageRow] = []
    for print_row, canonical, product in denominator:
        source_coverage: dict[str, PrintSourceCoverage] = {}
        for source in SUPPORTED_SOURCES:
            exact_identities = exact_by_pair.get((print_row.id, source), [])
            legacy_identities = legacy_by_card.get(
                (canonical.card_code, print_row.language, source), []
            )
            state = pair_states[(print_row.id, source)]
            if not exact_identities and legacy_identities:
                state = LEGACY_CARD_ONLY
            mapping = approved_mapping_by_pair.get((print_row.id, source))
            source_coverage[source] = PrintSourceCoverage(
                source=source,
                mapping_state=state,
                exact_mapping_ids=tuple(sorted(i.mapping.id for i in exact_identities)),
                legacy_mapping_ids=tuple(sorted(i.mapping.id for i in legacy_identities)),
                evidence=(
                    _evidence_for(mapping, latest_attempts, latest_observations)
                    if mapping is not None
                    else None
                ),
                current_representative=(
                    representatives.get((print_row.id, source))
                    if mapping is not None
                    else None
                ),
            )
        display_rarity = effective_rarity(print_row, canonical)
        priority, priority_reason = _priority(
            source_coverage, display_rarity, print_row.treatment
        )
        rows.append(
            ExactPrintCoverageRow(
                card_print_id=print_row.id,
                canonical_card_id=canonical.id,
                card_code=canonical.card_code,
                name_en=canonical.name_en,
                name_jp=canonical.name_jp,
                release_product_id=product.id,
                release_official_code=product.official_code,
                release_display_name=product.display_name,
                language=print_row.language,
                official_asset_variant=print_row.official_asset_variant,  # type: ignore[arg-type]
                treatment=print_row.treatment,
                official_rarity=print_row.official_rarity,
                display_rarity=display_rarity,
                image_url=print_row.image_url,
                artwork_key=print_row.artwork_key,  # type: ignore[arg-type]
                sources=source_coverage,
                priority=priority,
                priority_reason=priority_reason,
            )
        )

    releases_by_id: dict[int, ReleaseCoverage] = {}
    state_counts = {source: Counter() for source in SUPPORTED_SOURCES}
    source_observations = Counter()
    cross = Counter()
    for row in rows:
        release = releases_by_id.setdefault(
            row.release_product_id,
            ReleaseCoverage(
                release_product_id=row.release_product_id,
                official_code=row.release_official_code,
                display_name=row.release_display_name,
            ),
        )
        release.total_verified_active_jp_prints += 1
        for source in SUPPORTED_SOURCES:
            item = row.sources[source]
            state_counts[source][item.mapping_state] += 1
            release.source_state_counts[source][item.mapping_state] += 1
            if item.has_observation:
                source_observations[source] += 1
                release.source_observation_counts[source] += 1

        yuyu_mapped = row.sources[YUYUTEI].exact_approved_active
        snkr_mapped = row.sources[SNKRDUNK].exact_approved_active
        yuyu_observed = row.sources[YUYUTEI].has_observation
        snkr_observed = row.sources[SNKRDUNK].has_observation
        if yuyu_mapped and snkr_mapped:
            cross["mapped_by_both"] += 1
            release.mapped_by_both += 1
        elif yuyu_mapped:
            cross["mapped_by_yuyutei_only"] += 1
            release.mapped_by_yuyutei_only += 1
        elif snkr_mapped:
            cross["mapped_by_snkrdunk_only"] += 1
            release.mapped_by_snkrdunk_only += 1
        else:
            cross["mapped_by_neither"] += 1
            release.mapped_by_neither += 1
        if yuyu_observed or snkr_observed:
            cross["any_price_observation_coverage"] += 1
            release.any_price_observation_coverage += 1
        if yuyu_observed and snkr_observed:
            cross["both_source_observation_coverage"] += 1
            release.both_source_observation_coverage += 1

    releases = sorted(
        releases_by_id.values(),
        key=lambda item: (item.official_code or "", item.display_name, item.release_product_id),
    )
    overall = {
        "total_verified_active_jp_card_prints": len(rows),
        "sources": {
            source: {
                **{state: state_counts[source][state] for state in MAPPING_STATES},
                "mappings_with_any_observation": source_observations[source],
            }
            for source in SUPPORTED_SOURCES
        },
        **{key: cross[key] for key in (
            "mapped_by_both",
            "mapped_by_yuyutei_only",
            "mapped_by_snkrdunk_only",
            "mapped_by_neither",
            "any_price_observation_coverage",
            "both_source_observation_coverage",
        )},
    }

    gaps = [
        row
        for row in rows
        if any(
            row.sources[source].mapping_state != EXACT_APPROVED_ACTIVE
            for source in SUPPORTED_SOURCES
        )
    ]
    priority_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    gaps.sort(
        key=lambda row: (
            priority_rank[row.priority],
            row.release_official_code or "",
            row.card_code,
            row.card_print_id,
        )
    )
    return ExactPrintMappingCoverageReport(
        prints=rows,
        releases=releases,
        overall=overall,
        gap_total=len(gaps),
        gap_limit=gap_limit,
        gap_offset=gap_offset,
        gap_page=gaps[gap_offset : gap_offset + gap_limit],
        op17_mixed_code_findings=_op17_findings(rows),
    )


def compute_exact_print_mapping_coverage(
    db: Session,
    *,
    gap_limit: int = 100,
    gap_offset: int = 0,
) -> ExactPrintMappingCoverageReport:
    """Public read-only boundary, including protection from ORM autoflush.

    A caller may have unrelated pending objects on its session.  SQLAlchemy
    normally flushes those before a SELECT; suppressing autoflush here keeps
    this reporting service from turning somebody else's pending mutation into
    a write.  The staging CLI adds PostgreSQL's server-side READ ONLY guard.
    """
    with db.no_autoflush:
        return _compute_exact_print_mapping_coverage(
            db, gap_limit=gap_limit, gap_offset=gap_offset
        )


__all__ = [
    "AMBIGUOUS_MULTIPLE_EXACT_MAPPINGS",
    "ATTEMPTED_NO_OBSERVATION",
    "EXACT_APPROVED_ACTIVE",
    "EXACT_INACTIVE",
    "EXACT_NEEDS_REVIEW",
    "EXACT_REJECTED",
    "HAS_OBSERVATION",
    "JAPANESE_LANGUAGE",
    "LEGACY_CARD_ONLY",
    "MAPPING_STATES",
    "NEVER_ATTEMPTED",
    "SNKRDUNK",
    "SUPPORTED_SOURCES",
    "UNMAPPED",
    "YUYUTEI",
    "ExactPrintMappingCoverageReport",
    "compute_exact_print_mapping_coverage",
]
