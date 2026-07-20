"""Confidence scoring and data-quality review for source_card_mappings.

Reuses app.services.card_matching's deterministic 0-100 scorer (see that
module's docstring - no AI/LLM anywhere) against a mapping's
source_card_id/source_url and its currently-mapped card, by adapting the
mapping's fields into the same "candidate" shape card_matching already
scores SNKRDUNK candidates against (see _adapt_mapping below).

Distinct from app.services.card_audit, which flags catalog-and-mapping-wide
data-quality problems fresh on every request; this module additionally
persists a mapping's last-evaluated confidence (match_confidence,
match_confidence_label, match_explanation_json, last_match_checked_at - see
GET/POST /admin/source-mappings/quality|recheck-quality) and adds
mapping-specific health signals that aren't about the card catalog itself:
staleness, near-duplicate source URLs, and active/inactive mappings that
disagree with recent price activity.

This module only writes to the DB from bulk_recheck_source_mappings (and
only when dry_run=False) and from the admin endpoints that call
evaluate_source_mapping after an explicit human action (replace-card). It
never deletes mappings or price observations, and never auto-resolves an
ambiguous match - see app.api.admin_source_mapping_quality for the write
paths and their safety rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Card, PriceObservation, Source, SourceCardMapping
from app.services.card_matching import (
    calculate_candidate_match,
    extract_set_code,
    normalize_card_code,
    rank_candidate_matches,
)

ISSUE_TYPES = (
    "low_confidence",
    "card_code_mismatch",
    "set_code_mismatch",
    "variant_mismatch",
    "duplicate_source_url",
    "inactive_with_recent_price",
    "active_without_recent_price",
    "stale_mapping",
    "unverified_mapping",
    "missing_source_url",
    "missing_card_reference",
)

CONFIDENCE_LABELS = ("exact", "high", "medium", "low", "very_low", "unknown")
RISK_LEVELS = ("ok", "review", "warning", "critical")

# Below this 0-100 score, a mapping is "low_confidence" - same threshold as
# app.services.card_matching.SUGGESTED_SCORE_THRESHOLD's neighbor,
# UNMATCHED_SCORE_THRESHOLD, reused here rather than imported since the
# semantics differ slightly (an *existing, already-approved* mapping scoring
# this low is a review signal, not "no match found").
LOW_CONFIDENCE_SCORE_THRESHOLD = 55

# A mapping that hasn't been human-verified (last_verified_at) within this
# many days - and was created before that window too - is "stale": nobody
# has confirmed it's still correct in a long time.
STALE_MAPPING_DAYS = 90

# A price_observation older than this doesn't count as "recent" for
# active_without_recent_price / inactive_with_recent_price.
RECENT_PRICE_DAYS = 30


@dataclass
class MappingQualityItem:
    mapping_id: int
    source_name: str | None
    source_url: str | None
    source_card_id: str
    card_id: int
    card_code: str | None
    name_en: str | None
    name_jp: str | None
    set_code: str | None
    rarity: str | None
    variant: str | None
    is_active: bool
    manual_verified: bool
    review_status: str
    match_confidence: int | None
    match_confidence_label: str
    risk_level: str
    issue_types: list[str]
    explanation: dict[str, list[str]]
    latest_price_observed_at: datetime | None
    last_match_checked_at: datetime | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_id": self.mapping_id,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "source_card_id": self.source_card_id,
            "card_id": self.card_id,
            "card_code": self.card_code,
            "name_en": self.name_en,
            "name_jp": self.name_jp,
            "set_code": self.set_code,
            "rarity": self.rarity,
            "variant": self.variant,
            "is_active": self.is_active,
            "manual_verified": self.manual_verified,
            "review_status": self.review_status,
            "match_confidence": self.match_confidence,
            "match_confidence_label": self.match_confidence_label,
            "risk_level": self.risk_level,
            "issue_types": self.issue_types,
            "explanation": self.explanation,
            "latest_price_observed_at": (
                self.latest_price_observed_at.isoformat() if self.latest_price_observed_at else None
            ),
            "last_match_checked_at": (
                self.last_match_checked_at.isoformat() if self.last_match_checked_at else None
            ),
        }


@dataclass
class _MappingCandidateAdapter:
    """Duck-types SnkrdunkCandidate's fields well enough for
    calculate_candidate_match/rank_candidate_matches to score a mapping
    against a card - source_card_id stands in for a detected card code,
    source_url is the closest thing to raw listing text a mapping has."""

    title: str | None
    normalized_title: str | None
    raw_text: str | None
    detected_card_code: str | None
    detected_set_code: str | None = None
    detected_rarity: str | None = None
    detected_variant: str | None = None
    condition_label: str | None = None


def _adapt_mapping(mapping: SourceCardMapping) -> _MappingCandidateAdapter:
    source_card_id = mapping.source_card_id or None
    text_blob = " ".join(filter(None, [source_card_id, mapping.source_url]))
    return _MappingCandidateAdapter(
        title=source_card_id,
        normalized_title=source_card_id,
        raw_text=mapping.source_url,
        detected_card_code=normalize_card_code(source_card_id) if source_card_id else None,
        detected_set_code=extract_set_code(text_blob) if text_blob else None,
    )


def _naive(dt: datetime) -> datetime:
    """Strips tzinfo if present, so a loaded row's timestamp (naive under
    SQLite, aware under Postgres - see app.services.job_locks._naive) can be
    safely compared against datetime.now(timezone.utc) under either
    dialect."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _is_stale(mapping: SourceCardMapping, now: datetime) -> bool:
    cutoff = _naive(now) - timedelta(days=STALE_MAPPING_DAYS)
    if mapping.last_verified_at is not None:
        return _naive(mapping.last_verified_at) < cutoff
    return mapping.created_at is not None and _naive(mapping.created_at) < cutoff


def _risk_level(issue_types: list[str], confidence_label: str) -> str:
    if "missing_card_reference" in issue_types or "card_code_mismatch" in issue_types:
        return "critical"
    if confidence_label == "very_low" or "duplicate_source_url" in issue_types:
        return "critical"
    if (
        "low_confidence" in issue_types
        or "set_code_mismatch" in issue_types
        or "variant_mismatch" in issue_types
        or "inactive_with_recent_price" in issue_types
        or "active_without_recent_price" in issue_types
    ):
        return "warning"
    if (
        "stale_mapping" in issue_types
        or "unverified_mapping" in issue_types
        or "missing_source_url" in issue_types
    ):
        return "review"
    return "ok"


def _latest_price_observed_at(db: Session, card_id: int, source_id: int) -> datetime | None:
    return db.scalar(
        select(func.max(PriceObservation.observed_at)).where(
            PriceObservation.card_id == card_id, PriceObservation.source_id == source_id
        )
    )


def _duplicate_mapping_ids(mappings: list[SourceCardMapping]) -> set[int]:
    """Mirrors app.services.card_audit._check_duplicate_source_url's
    near-duplicate grouping (same source, same URL modulo whitespace/case) -
    the DB's UNIQUE(source_id, source_url) only catches exact-string
    duplicates."""
    groups: dict[tuple[int, str], list[int]] = {}
    for mapping in mappings:
        if not mapping.source_url:
            continue
        normalized = mapping.source_url.strip().lower()
        if not normalized:
            continue
        groups.setdefault((mapping.source_id, normalized), []).append(mapping.id)

    flagged: set[int] = set()
    for ids in groups.values():
        if len(ids) > 1:
            flagged.update(ids)
    return flagged


def evaluate_source_mapping(
    db: Session,
    mapping: SourceCardMapping,
    *,
    card: Card | None = None,
    source: Source | None = None,
    latest_price_observed_at: datetime | int | None = 0,
    is_duplicate: bool | None = None,
    now: datetime | None = None,
) -> MappingQualityItem:
    """Evaluates one mapping. Callers that already have the related
    card/source/latest-price/duplicate-group loaded (evaluate_source_mappings,
    bulk_recheck_source_mappings) should pass them in to avoid N+1 queries;
    standalone callers (replace-card) can omit them and this looks them up
    itself. `latest_price_observed_at=0` is the "not provided, look it up"
    sentinel - None is a valid "no observations" result."""
    now = now or datetime.now(timezone.utc)

    if card is None:
        card = db.get(Card, mapping.card_id)
    if source is None:
        source = db.get(Source, mapping.source_id)
    if latest_price_observed_at == 0:
        latest_price_observed_at = (
            _latest_price_observed_at(db, mapping.card_id, mapping.source_id)
            if card is not None
            else None
        )
    if is_duplicate is None:
        is_duplicate = mapping.id in _duplicate_mapping_ids(
            db.scalars(select(SourceCardMapping).where(SourceCardMapping.source_id == mapping.source_id)).all()
        )

    issue_types: list[str] = []
    positive: list[str] = []
    negative: list[str] = []
    caps_applied: list[str] = []
    score: int | None = None
    label = "unknown"

    if card is None:
        issue_types.append("missing_card_reference")
    else:
        adapted = _adapt_mapping(mapping)
        result = calculate_candidate_match(adapted, card)
        score = result.score
        label = result.confidence_label
        positive = result.explanation.positive
        negative = result.explanation.negative
        caps_applied = result.explanation.caps_applied

        if score < LOW_CONFIDENCE_SCORE_THRESHOLD:
            issue_types.append("low_confidence")

        source_card_id_norm = normalize_card_code(mapping.source_card_id)
        card_code_norm = normalize_card_code(card.card_code)
        if (
            source_card_id_norm is not None
            and card_code_norm is not None
            and source_card_id_norm != card_code_norm
            # A card_code-looking source_card_id that mismatches is a real
            # conflict; a non-code source_card_id (e.g. a numeric listing
            # id) never equaling the card_code isn't - see extract_card_code
            # in card_matching for the same "\b[A-Z]{1,5}\d{0,2}-\d{3,4}\b"
            # shape this reuses implicitly via normalize_card_code's callers
            # elsewhere. Here we only compare when source_card_id looks like
            # a card code to begin with (contains a hyphen), same heuristic
            # app.services.card_audit._check_source_card_code_mismatch skips
            # by comparing unconditionally against a *required* field - this
            # mirrors that check's intent for this mapping-scoped view.
            and "-" in source_card_id_norm
        ):
            issue_types.append("card_code_mismatch")

        if "set_code mismatch" in negative:
            issue_types.append("set_code_mismatch")
        if "variant mismatch" in negative:
            issue_types.append("variant_mismatch")

    if not mapping.source_url:
        issue_types.append("missing_source_url")
    if is_duplicate:
        issue_types.append("duplicate_source_url")

    recent_cutoff = _naive(now) - timedelta(days=RECENT_PRICE_DAYS)
    has_recent_price = (
        latest_price_observed_at is not None and _naive(latest_price_observed_at) >= recent_cutoff
    )
    if not mapping.is_active and has_recent_price:
        issue_types.append("inactive_with_recent_price")
    if mapping.is_active and not has_recent_price:
        issue_types.append("active_without_recent_price")

    if _is_stale(mapping, now):
        issue_types.append("stale_mapping")
    if not mapping.manual_verified:
        issue_types.append("unverified_mapping")

    risk_level = _risk_level(issue_types, label)

    return MappingQualityItem(
        mapping_id=mapping.id,
        source_name=source.name if source is not None else None,
        source_url=mapping.source_url,
        source_card_id=mapping.source_card_id,
        card_id=mapping.card_id,
        card_code=card.card_code if card is not None else None,
        name_en=card.name_en if card is not None else None,
        name_jp=card.name_jp if card is not None else None,
        set_code=card.set_code if card is not None else None,
        rarity=card.rarity if card is not None else None,
        variant=card.variant if card is not None else None,
        is_active=mapping.is_active,
        manual_verified=mapping.manual_verified,
        review_status=mapping.review_status,
        match_confidence=score,
        match_confidence_label=label,
        risk_level=risk_level,
        issue_types=issue_types,
        explanation={"positive": positive, "negative": negative, "caps_applied": caps_applied},
        latest_price_observed_at=latest_price_observed_at,
        last_match_checked_at=mapping.last_match_checked_at,
    )


@dataclass
class MappingQualityFilters:
    source: str | None = None
    review_status: str | None = None
    is_active: bool | None = None
    manual_verified: bool | None = None
    confidence_label: str | None = None
    risk_level: str | None = None
    issue_type: str | None = None
    q: str | None = None


def _base_query(filters: MappingQualityFilters):
    query = (
        select(SourceCardMapping)
        .join(Card, SourceCardMapping.card_id == Card.id)
        .join(Source, SourceCardMapping.source_id == Source.id)
    )
    conditions = []
    if filters.review_status is not None:
        conditions.append(SourceCardMapping.review_status == filters.review_status)
    if filters.is_active is not None:
        conditions.append(SourceCardMapping.is_active == filters.is_active)
    if filters.manual_verified is not None:
        conditions.append(SourceCardMapping.manual_verified == filters.manual_verified)
    if filters.source is not None:
        conditions.append(Source.name == filters.source)
    if filters.q:
        like = f"%{filters.q}%"
        conditions.append(
            (SourceCardMapping.source_url.ilike(like))
            | (SourceCardMapping.source_card_id.ilike(like))
            | (Card.card_code.ilike(like))
        )
    if conditions:
        query = query.where(*conditions)
    return query


def _evaluate_all(db: Session, filters: MappingQualityFilters) -> list[MappingQualityItem]:
    """Evaluates every mapping matching the DB-level filters (source,
    review_status, is_active, manual_verified, q) - confidence_label/
    risk_level/issue_type filters are applied afterward in Python since
    they're derived, not stored columns. Batches the card/source/latest-
    price/duplicate lookups so this stays a handful of queries regardless of
    mapping count."""
    mappings = list(db.scalars(_base_query(filters)).all())
    if not mappings:
        return []

    now = datetime.now(timezone.utc)
    card_ids = {m.card_id for m in mappings}
    source_ids = {m.source_id for m in mappings}
    cards_by_id = {c.id: c for c in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()}
    sources_by_id = {
        s.id: s for s in db.scalars(select(Source).where(Source.id.in_(source_ids))).all()
    }

    price_rows = db.execute(
        select(
            PriceObservation.card_id,
            PriceObservation.source_id,
            func.max(PriceObservation.observed_at),
        )
        .where(PriceObservation.card_id.in_(card_ids), PriceObservation.source_id.in_(source_ids))
        .group_by(PriceObservation.card_id, PriceObservation.source_id)
    ).all()
    latest_price_by_pair = {(row[0], row[1]): row[2] for row in price_rows}

    # Duplicate grouping is computed across ALL of each source's mappings
    # (not just this filtered page) - a mapping filtered out of this view
    # can still be the other half of a duplicate pair.
    all_mappings_by_source: dict[int, list[SourceCardMapping]] = {}
    for source_id in source_ids:
        all_mappings_by_source[source_id] = list(
            db.scalars(select(SourceCardMapping).where(SourceCardMapping.source_id == source_id)).all()
        )
    duplicate_ids: set[int] = set()
    for source_mappings in all_mappings_by_source.values():
        duplicate_ids |= _duplicate_mapping_ids(source_mappings)

    items = [
        evaluate_source_mapping(
            db,
            m,
            card=cards_by_id.get(m.card_id),
            source=sources_by_id.get(m.source_id),
            latest_price_observed_at=latest_price_by_pair.get((m.card_id, m.source_id)),
            is_duplicate=m.id in duplicate_ids,
            now=now,
        )
        for m in mappings
    ]

    if filters.confidence_label is not None:
        items = [i for i in items if i.match_confidence_label == filters.confidence_label]
    if filters.risk_level is not None:
        items = [i for i in items if i.risk_level == filters.risk_level]
    if filters.issue_type is not None:
        items = [i for i in items if filters.issue_type in i.issue_types]

    return items


def evaluate_source_mappings(
    db: Session, filters: MappingQualityFilters, limit: int = 100, offset: int = 0
) -> tuple[list[MappingQualityItem], int, dict[str, int]]:
    """Returns (page_of_items, total_matching, summary_counts) - summary is
    computed over the full filtered-and-evaluated set, before pagination."""
    items = _evaluate_all(db, filters)
    summary = _summarize(items)
    total = len(items)
    return items[offset : offset + limit], total, summary


def _summarize(items: list[MappingQualityItem]) -> dict[str, int]:
    def count_issue(issue_type: str) -> int:
        return sum(1 for i in items if issue_type in i.issue_types)

    return {
        "total_mappings": len(items),
        "ok_count": sum(1 for i in items if i.risk_level == "ok"),
        "review_count": sum(1 for i in items if i.risk_level == "review"),
        "warning_count": sum(1 for i in items if i.risk_level == "warning"),
        "critical_count": sum(1 for i in items if i.risk_level == "critical"),
        "low_confidence_count": count_issue("low_confidence"),
        "duplicate_source_url_count": count_issue("duplicate_source_url"),
        "stale_mapping_count": count_issue("stale_mapping"),
        "unverified_count": count_issue("unverified_mapping"),
        "inactive_with_recent_price_count": count_issue("inactive_with_recent_price"),
        "active_without_recent_price_count": count_issue("active_without_recent_price"),
    }


def summarize_mapping_quality(db: Session) -> dict[str, int]:
    """Unfiltered summary counts across every mapping - used by the quality
    endpoint's default view and by app.services.card_audit/system_check for
    their own mapping-quality integration."""
    return _summarize(_evaluate_all(db, MappingQualityFilters()))


@dataclass
class RecheckSummary:
    selected: int = 0
    would_update: int = 0
    updated: int = 0
    ok: int = 0
    review: int = 0
    warning: int = 0
    critical: int = 0


def bulk_recheck_source_mappings(
    db: Session,
    filters: MappingQualityFilters,
    limit: int = 100,
    dry_run: bool = True,
) -> tuple[RecheckSummary, list[MappingQualityItem]]:
    """Re-evaluates up to `limit` mappings matching the DB-level filters. In
    dry_run mode (the default), nothing is written - the same evaluation is
    returned as a preview. In a real run, each mapping's match_confidence
    (raw 0-100 int - see app.models.source_card_mapping's docstring on why
    this shares the legacy float column), match_confidence_label,
    match_explanation_json, and last_match_checked_at are updated and
    committed. Never touches review_status/is_active/manual_verified -
    that's POST /admin/source-mappings/bulk-update's job."""
    mappings = list(db.scalars(_base_query(filters).limit(limit)).all())
    now = datetime.now(timezone.utc)

    summary = RecheckSummary(selected=len(mappings))
    preview: list[MappingQualityItem] = []

    if not mappings:
        return summary, preview

    card_ids = {m.card_id for m in mappings}
    source_ids = {m.source_id for m in mappings}
    cards_by_id = {c.id: c for c in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()}
    sources_by_id = {
        s.id: s for s in db.scalars(select(Source).where(Source.id.in_(source_ids))).all()
    }
    duplicate_ids: set[int] = set()
    for source_id in source_ids:
        source_mappings = list(
            db.scalars(select(SourceCardMapping).where(SourceCardMapping.source_id == source_id)).all()
        )
        duplicate_ids |= _duplicate_mapping_ids(source_mappings)

    for mapping in mappings:
        item = evaluate_source_mapping(
            db,
            mapping,
            card=cards_by_id.get(mapping.card_id),
            source=sources_by_id.get(mapping.source_id),
            latest_price_observed_at=_latest_price_observed_at(db, mapping.card_id, mapping.source_id),
            is_duplicate=mapping.id in duplicate_ids,
            now=now,
        )
        preview.append(item)
        summary.would_update += 1
        setattr(summary, item.risk_level, getattr(summary, item.risk_level) + 1)

        if not dry_run:
            mapping.match_confidence = item.match_confidence
            mapping.match_confidence_label = item.match_confidence_label
            mapping.match_explanation_json = item.explanation
            mapping.last_match_checked_at = now
            summary.updated += 1

    if not dry_run:
        db.commit()

    return summary, preview


def suggested_cards_for_mapping(db: Session, mapping: SourceCardMapping, limit: int = 10):
    """Ranks every canonical card against this mapping's source fields,
    reusing app.services.card_matching.rank_candidate_matches - same
    response shape as the SNKRDUNK candidate matching endpoints
    (app.api.admin_snkrdunk_matching)."""
    adapted = _adapt_mapping(mapping)
    return rank_candidate_matches(db, adapted, limit=limit)

