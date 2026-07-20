"""Deterministic duplicate-card detection and safe canonical-identity merging
for the `cards` table - see GET/POST /admin/cards/duplicates* and
/admin/cards/{id}/merge-preview|merge.

As canonical catalog imports (app.services.card_catalog_import) and source
candidate matching (app.services.card_matching) grow the `cards` table, the
same physical card can end up stored more than once (a slightly different
card_code/variant/language formatting, a manually-imported watchlist row,
...). This module scores how likely two cards are the same physical card
(calculate_duplicate_score/explain_duplicate_match), surfaces candidate pairs
efficiently without an O(n^2) full-table comparison (detect_duplicate_cards),
and lets an admin fold one card's identity into another
(preview_card_merge/execute_card_merge) without ever deleting a row: a merged
card is marked is_active=false with merged_into_card_id pointing at the
survivor, and every other table's card_id foreign keys are reassigned to the
survivor so price/collection/wishlist/grading/tag/note history all stay
intact and queryable through the surviving card.

No AI/LLM anywhere in this module - every signal below is a fixed,
deterministic point value applied to fields already stored on the two cards
being compared, the same convention app.services.card_matching documents for
its own scorer (reused here for text normalization only, not scoring, since
the shapes being compared - two Cards, not a Card and a source listing - are
different enough to warrant separate rules).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import (
    AlertEvent,
    Card,
    CardAlias,
    CardTag,
    CollectionItem,
    CollectionItemTag,
    CollectorActivityEvent,
    CollectorNote,
    GradingSubmission,
    MarketSignalEvent,
    SourceCardMapping,
    WishlistItem,
)
from app.services.card_catalog_import import METADATA_DATE_FIELDS, METADATA_INT_FIELDS, METADATA_STRING_FIELDS
from app.services.card_matching import normalize_card_code, normalize_text

# (minimum score, label) pairs, checked highest-first - distinct scale from
# app.services.card_matching's own confidence_label: that scorer answers "is
# this source listing the same card as X", this one answers "are these two
# canonical cards actually the same card", so the labels and thresholds are
# deliberately different vocabulary even though both are 0-100.
DUPLICATE_LABEL_THRESHOLDS = (
    (90, "exact_duplicate"),
    (75, "likely_duplicate"),
    (55, "possible_duplicate"),
    (35, "weak_match"),
    (0, "not_duplicate"),
)
CONFIDENCE_LABELS = tuple(label for _, label in DUPLICATE_LABEL_THRESHOLDS)

MIN_SCORE = 0
MAX_SCORE = 100

# Below this score, execute_card_merge refuses the merge unless the caller
# explicitly sets approve_low_confidence=true - same value as the
# "likely_duplicate" floor, so a merge is only ever auto-eligible once the
# score clears that bar.
MIN_MERGE_SCORE = 75

FIELD_STRATEGIES = ("keep_target", "fill_missing_target_fields", "overwrite_target_empty_or_shorter_text")
DEFAULT_FIELD_STRATEGY = "keep_target"

# Fields eligible for field_strategy-driven merging - the catalog-enrichment
# metadata columns (see app.services.card_catalog_import), never the identity
# columns (card_code/set_code/rarity/variant/language) which stay exactly as
# stored on each card until a human explicitly edits them elsewhere.
MERGEABLE_METADATA_FIELDS: tuple[str, ...] = (*METADATA_STRING_FIELDS, *METADATA_DATE_FIELDS, *METADATA_INT_FIELDS)


def duplicate_confidence_label(score: int) -> str:
    for threshold, label in DUPLICATE_LABEL_THRESHOLDS:
        if score >= threshold:
            return label
    return "not_duplicate"


@dataclass
class DuplicateExplanation:
    positive: list[str] = field(default_factory=list)
    negative: list[str] = field(default_factory=list)
    caps_applied: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return {"positive": self.positive, "negative": self.negative, "caps_applied": self.caps_applied}


@dataclass
class DuplicateScoreResult:
    score: int
    explanation: DuplicateExplanation

    @property
    def confidence_label(self) -> str:
        return duplicate_confidence_label(self.score)


def _variant_key(variant: str | None) -> str:
    """A missing variant means "base print" for comparison purposes - the
    same convention app.services.card_matching.calculate_candidate_match
    uses for a card's own variant column."""
    return normalize_text(variant) or "base"


def _is_known_language(language: str | None) -> bool:
    return bool(language) and language.strip().lower() in ("en", "jp")


def calculate_duplicate_score(card_a: Card, card_b: Card) -> DuplicateScoreResult:
    """Scores whether card_a and card_b are the same physical card, 0-100.
    See the module docstring for the intent; see this function's inline
    comments for exactly which spec rule each block implements."""
    positive: list[str] = []
    negative: list[str] = []
    caps_applied: list[str] = []
    score = 0

    code_a = normalize_card_code(card_a.card_code)
    code_b = normalize_card_code(card_b.card_code)
    same_card_code = code_a is not None and code_a == code_b

    if card_a.card_code == card_b.card_code:
        score += 55
        positive.append("exact card_code match")
    elif same_card_code:
        score += 50
        positive.append("normalized card_code match")

    if card_a.set_code and card_b.set_code:
        if card_a.set_code.strip().upper() == card_b.set_code.strip().upper():
            score += 10
            positive.append("same set_code")
        else:
            score -= 30
            negative.append("different set_code")

    if card_a.rarity and card_b.rarity:
        if card_a.rarity.strip().upper() == card_b.rarity.strip().upper():
            score += 5
            positive.append("same rarity")
        else:
            score -= 10
            negative.append("different rarity")

    variant_a, variant_b = _variant_key(card_a.variant), _variant_key(card_b.variant)
    if variant_a == variant_b:
        score += 10
        positive.append("same variant")
    else:
        score -= 25
        negative.append("different variant")

    if card_a.language and card_b.language:
        if card_a.language.strip().lower() == card_b.language.strip().lower():
            score += 5
            positive.append("same language")
        else:
            score -= 10
            negative.append("different language")

    name_en_a, name_en_b = normalize_text(card_a.name_en), normalize_text(card_b.name_en)
    if name_en_a and name_en_b:
        if name_en_a == name_en_b:
            score += 20
            positive.append("exact name_en match")
        elif name_en_a in name_en_b or name_en_b in name_en_a:
            score += 8
            positive.append("partial name_en match")

    name_jp_a, name_jp_b = normalize_text(card_a.name_jp), normalize_text(card_b.name_jp)
    if name_jp_a and name_jp_b:
        if name_jp_a == name_jp_b:
            score += 20
            positive.append("exact name_jp match")
        elif name_jp_a in name_jp_b or name_jp_b in name_jp_a:
            score += 8
            positive.append("partial name_jp match")

    if card_a.character and card_b.character and normalize_text(card_a.character) == normalize_text(card_b.character):
        score += 5
        positive.append("same character")

    if card_a.card_type and card_b.card_type and normalize_text(card_a.card_type) == normalize_text(card_b.card_type):
        score += 5
        positive.append("same card_type")

    # "different set_code should never score above 60 unless exact card_code
    # match exists"
    if "different set_code" in negative and card_a.card_code != card_b.card_code and score > 60:
        score = 60
        caps_applied.append("set_code_mismatch_cap_60")

    # "same card_code but different variant should be possible_duplicate or
    # lower unless variant can be normalized to same value" - variant_a ==
    # variant_b (handled above) already covers the "normalizes to the same
    # value" escape hatch, so this only fires on a genuine mismatch.
    if same_card_code and "different variant" in negative and score > 74:
        score = 74
        caps_applied.append("variant_mismatch_cap_74")

    # "same card_code but different language should be likely_duplicate only
    # if language is missing/unknown on one side" - i.e. capped below
    # likely_duplicate whenever BOTH sides have a known, differing language.
    if (
        same_card_code
        and "different language" in negative
        and _is_known_language(card_a.language)
        and _is_known_language(card_b.language)
        and score > 74
    ):
        score = 74
        caps_applied.append("language_mismatch_cap_74")

    score = max(MIN_SCORE, min(MAX_SCORE, score))
    return DuplicateScoreResult(score=score, explanation=DuplicateExplanation(positive, negative, caps_applied))


def explain_duplicate_match(card_a: Card, card_b: Card) -> dict[str, list[str]]:
    """Thin convenience wrapper for callers that only want the explanation,
    not the full scored result."""
    return calculate_duplicate_score(card_a, card_b).explanation.to_dict()


def _card_summary(card: Card) -> dict[str, Any]:
    return {
        "id": card.id,
        "card_code": card.card_code,
        "name_en": card.name_en,
        "name_jp": card.name_jp,
        "set_code": card.set_code,
        "rarity": card.rarity,
        "variant": card.variant,
        "language": card.language,
        "is_active": card.is_active,
        "merged_into_card_id": card.merged_into_card_id,
    }


@dataclass
class DuplicatePair:
    source_card: Card
    target_card: Card
    score: int
    confidence_label: str
    explanation: dict[str, list[str]]
    recommended_target_card_id: int
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_card": _card_summary(self.source_card),
            "target_card": _card_summary(self.target_card),
            "score": self.score,
            "confidence_label": self.confidence_label,
            "explanation": self.explanation,
            "recommended_target_card_id": self.recommended_target_card_id,
            "warnings": self.warnings,
        }


@dataclass
class DuplicateDetectionFilters:
    q: str | None = None
    set_code: str | None = None
    rarity: str | None = None
    variant: str | None = None
    language: str | None = None
    confidence_label: str | None = None
    min_score: int = 55
    include_inactive: bool = False


def _filtered_cards(db: Session, filters: DuplicateDetectionFilters) -> list[Card]:
    query = select(Card)
    conditions = []
    if not filters.include_inactive:
        conditions.append(Card.is_active.is_(True))
    if filters.set_code:
        conditions.append(Card.set_code == filters.set_code)
    if filters.rarity:
        conditions.append(Card.rarity == filters.rarity)
    if filters.variant:
        conditions.append(Card.variant == filters.variant)
    if filters.language:
        conditions.append(Card.language == filters.language)
    if filters.q:
        like = f"%{filters.q}%"
        conditions.append(
            Card.card_code.ilike(like) | Card.name_en.ilike(like) | Card.name_jp.ilike(like)
        )
    if conditions:
        query = query.where(*conditions)
    return list(db.scalars(query).all())


def _candidate_pair_ids(cards: list[Card]) -> set[tuple[int, int]]:
    """Buckets cards by cheap-to-compute keys (normalized card_code; set_code
    + normalized name; normalized name + rarity) and only pairs cards that
    land in the same bucket - avoids ever comparing every card against every
    other card. A real duplicate always shares at least one of these keys
    with its counterpart, so this never misses a pair calculate_duplicate_score
    would otherwise have scored above 0."""
    by_code: dict[str, list[Card]] = defaultdict(list)
    by_set_name_en: dict[tuple[str, str], list[Card]] = defaultdict(list)
    by_set_name_jp: dict[tuple[str, str], list[Card]] = defaultdict(list)
    by_name_en_rarity: dict[tuple[str, str], list[Card]] = defaultdict(list)
    by_name_jp_rarity: dict[tuple[str, str], list[Card]] = defaultdict(list)

    for card in cards:
        code_norm = normalize_card_code(card.card_code)
        if code_norm:
            by_code[code_norm].append(card)

        name_en_norm = normalize_text(card.name_en)
        name_jp_norm = normalize_text(card.name_jp)
        if name_en_norm:
            by_set_name_en[(card.set_code, name_en_norm)].append(card)
            by_name_en_rarity[(name_en_norm, card.rarity)].append(card)
        if name_jp_norm:
            by_set_name_jp[(card.set_code, name_jp_norm)].append(card)
            by_name_jp_rarity[(name_jp_norm, card.rarity)].append(card)

    pair_ids: set[tuple[int, int]] = set()
    for bucket in (by_code, by_set_name_en, by_set_name_jp, by_name_en_rarity, by_name_jp_rarity):
        for group in bucket.values():
            if len(group) < 2:
                continue
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    pair_ids.add((min(a.id, b.id), max(a.id, b.id)))
    return pair_ids


def _evaluate_all_pairs(db: Session, filters: DuplicateDetectionFilters) -> list[DuplicatePair]:
    cards = _filtered_cards(db, filters)
    cards_by_id = {c.id: c for c in cards}
    pair_ids = _candidate_pair_ids(cards)

    results: list[DuplicatePair] = []
    for lo_id, hi_id in pair_ids:
        card_lo, card_hi = cards_by_id[lo_id], cards_by_id[hi_id]
        score_result = calculate_duplicate_score(card_lo, card_hi)
        if score_result.score < filters.min_score:
            continue
        label = score_result.confidence_label
        if filters.confidence_label is not None and label != filters.confidence_label:
            continue

        warnings: list[str] = []
        for c in (card_lo, card_hi):
            if not c.is_active:
                warnings.append(
                    f"card {c.id} is already inactive/merged (merged_into_card_id={c.merged_into_card_id})"
                )

        # The lower id is assumed to be the original canonical entry (created
        # first) and recommended as the merge target; the higher id is the
        # apparent duplicate. This is only a recommendation - the admin
        # reviewing GET /admin/cards/duplicates can always merge in either
        # direction via POST /admin/cards/merge.
        results.append(
            DuplicatePair(
                source_card=card_hi,
                target_card=card_lo,
                score=score_result.score,
                confidence_label=label,
                explanation=score_result.explanation.to_dict(),
                recommended_target_card_id=card_lo.id,
                warnings=warnings,
            )
        )

    results.sort(key=lambda p: (-p.score, p.source_card.id))
    return results


def _summarize_pairs(db: Session, pairs: list[DuplicatePair]) -> dict[str, int]:
    inactive_merged_cards = db.scalar(
        select(func.count()).select_from(Card).where(Card.is_active.is_(False))
    ) or 0
    return {
        "total_pairs": len(pairs),
        "exact_duplicate_count": sum(1 for p in pairs if p.confidence_label == "exact_duplicate"),
        "likely_duplicate_count": sum(1 for p in pairs if p.confidence_label == "likely_duplicate"),
        "possible_duplicate_count": sum(1 for p in pairs if p.confidence_label == "possible_duplicate"),
        "weak_match_count": sum(1 for p in pairs if p.confidence_label == "weak_match"),
        "inactive_merged_cards": inactive_merged_cards,
    }


def detect_duplicate_cards(
    db: Session, filters: DuplicateDetectionFilters, limit: int = 100, offset: int = 0
) -> tuple[list[DuplicatePair], int, dict[str, int]]:
    """Returns (page_of_pairs, total_matching, summary) - summary is computed
    over the full filtered-and-scored set, before pagination, same shape as
    app.services.source_mapping_confidence.evaluate_source_mappings."""
    pairs = _evaluate_all_pairs(db, filters)
    summary = _summarize_pairs(db, pairs)
    return pairs[offset : offset + limit], len(pairs), summary


def summarize_duplicate_quality(db: Session) -> dict[str, int]:
    """Unfiltered (default filters) summary - used by the duplicates
    endpoint's own default view and by app.services.card_audit/system_check
    for their own duplicate-quality integration."""
    return _summarize_pairs(db, _evaluate_all_pairs(db, DuplicateDetectionFilters()))


def duplicate_pairs_at_or_above(db: Session, min_score: int) -> list[DuplicatePair]:
    """Convenience wrapper for app.services.card_audit - every active-card
    duplicate pair scoring at least min_score, unpaginated."""
    return _evaluate_all_pairs(db, DuplicateDetectionFilters(min_score=min_score))


def bulk_duplicate_merge_previews(
    db: Session, *, min_score: int = 90, confidence_label: str | None = "exact_duplicate", limit: int = 50
) -> list["MergePreview"]:
    """Read-only merge previews for the top duplicate pairs matching the
    given filters - never writes. Only includes pairs with a clear
    recommendation (neither card already merged/inactive) - see the module
    docstring's "manual approval per merge is preferred" rule; this is a
    suggestion list, not something meant to be executed in bulk."""
    filters = DuplicateDetectionFilters(min_score=min_score, confidence_label=confidence_label)
    pairs = [p for p in _evaluate_all_pairs(db, filters) if not p.warnings][:limit]
    return [preview_card_merge(db, p.source_card.id, p.target_card.id) for p in pairs]


# --- Merge preview/execution --------------------------------------------


class MergeValidationError(ValueError):
    """A merge request that fails a safety rule (same id, target already
    merged, low confidence without approval, ...) - see
    app.api.admin_card_merge for how each is translated to an HTTP status."""


def _get_card_or_error(db: Session, card_id: int, label: str) -> Card:
    card = db.get(Card, card_id)
    if card is None:
        raise MergeValidationError(f"{label} card {card_id} not found")
    return card


def _field_action(strategy: str, source_value: Any, target_value: Any) -> tuple[Any, str]:
    """Returns (result_value, action) for one metadata field under the given
    field_strategy. Only ever called for fields where source_value !=
    target_value - see _field_merge_preview."""
    is_target_empty = target_value is None or (isinstance(target_value, str) and target_value.strip() == "")

    if strategy == "keep_target":
        return target_value, "keep_target"

    if strategy == "fill_missing_target_fields":
        if is_target_empty and source_value is not None:
            return source_value, "fill_missing_target_fields"
        return target_value, "keep_target"

    if strategy == "overwrite_target_empty_or_shorter_text":
        if is_target_empty and source_value is not None:
            return source_value, "fill_missing_target_fields"
        if (
            isinstance(target_value, str)
            and isinstance(source_value, str)
            and len(source_value) > len(target_value)
        ):
            return source_value, "overwrite_target_empty_or_shorter_text"
        return target_value, "keep_target"

    raise MergeValidationError(f"Invalid field_strategy: {strategy}")


def _field_merge_preview(source: Card, target: Card, field_strategy: str) -> dict[str, dict[str, Any]]:
    preview: dict[str, dict[str, Any]] = {}
    for f in MERGEABLE_METADATA_FIELDS:
        source_value = getattr(source, f)
        target_value = getattr(target, f)
        if source_value == target_value:
            continue
        result, action = _field_action(field_strategy, source_value, target_value)
        preview[f] = {"source": source_value, "target": target_value, "result": result, "action": action}
    return preview


def _affected_records(db: Session, source_card_id: int) -> dict[str, int]:
    def _count(model, column) -> int:
        return db.scalar(select(func.count()).select_from(model).where(column == source_card_id)) or 0

    grading_submissions = db.scalar(
        select(func.count())
        .select_from(GradingSubmission)
        .join(CollectionItem, GradingSubmission.collection_item_id == CollectionItem.id)
        .where(CollectionItem.card_id == source_card_id)
    ) or 0

    collection_item_tags = db.scalar(
        select(func.count())
        .select_from(CollectionItemTag)
        .join(CollectionItem, CollectionItemTag.collection_item_id == CollectionItem.id)
        .where(CollectionItem.card_id == source_card_id)
    ) or 0

    return {
        "source_card_mappings": _count(SourceCardMapping, SourceCardMapping.card_id),
        "collection_items": _count(CollectionItem, CollectionItem.card_id),
        "wishlist_items": _count(WishlistItem, WishlistItem.card_id),
        # grading_submissions has no card_id of its own (only
        # collection_item_id) - counted here for visibility, but it "follows"
        # its collection_item automatically once that row's card_id is
        # reassigned, so execute_card_merge never touches this table
        # directly.
        "grading_submissions": grading_submissions,
        "card_tags": _count(CardTag, CardTag.card_id),
        # Same story as grading_submissions: collection_item_tags has no
        # card_id of its own.
        "collection_item_tags": collection_item_tags,
        "notes": _count(CollectorNote, CollectorNote.card_id),
        "market_signal_events": _count(MarketSignalEvent, MarketSignalEvent.card_id),
        # market_intelligence_reports/analytics_digest_reports store their
        # data as opaque report_payload_json/digest_payload_json blobs with
        # no card_id column at all - there's no reliable way to detect (let
        # alone safely rewrite) a reference to this card inside them, so
        # these are always reported as 0/undetected rather than guessed - see
        # the module docstring and the spec's "do not rewrite historical
        # JSON" rule.
        "market_reports": 0,
        "analytics_digest_reports": 0,
        # Not in the original spec's affected_records example, but both are
        # real card_id foreign keys ("any report/event tables with card_id if
        # present") - included so a merge doesn't leave alert/activity
        # history silently pointing at a now-inactive card.
        "alert_events": _count(AlertEvent, AlertEvent.card_id),
        "collector_activity_events": _count(CollectorActivityEvent, CollectorActivityEvent.card_id),
    }


@dataclass
class MergePreview:
    source_card: Card
    target_card: Card
    duplicate_score: int
    confidence_label: str
    explanation: dict[str, list[str]]
    field_merge_preview: dict[str, dict[str, Any]]
    affected_records: dict[str, int]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_card": _card_summary(self.source_card),
            "target_card": _card_summary(self.target_card),
            "duplicate_score": self.duplicate_score,
            "confidence_label": self.confidence_label,
            "explanation": self.explanation,
            "field_merge_preview": self.field_merge_preview,
            "affected_records": self.affected_records,
            "warnings": self.warnings,
        }


def preview_card_merge(
    db: Session, source_card_id: int, target_card_id: int, *, field_strategy: str = DEFAULT_FIELD_STRATEGY
) -> MergePreview:
    if source_card_id == target_card_id:
        raise MergeValidationError("source_card_id and target_card_id cannot be the same")
    if field_strategy not in FIELD_STRATEGIES:
        raise MergeValidationError(f"Invalid field_strategy: {field_strategy}")

    source = _get_card_or_error(db, source_card_id, "Source")
    target = _get_card_or_error(db, target_card_id, "Target")

    score_result = calculate_duplicate_score(source, target)

    warnings: list[str] = []
    if not target.is_active:
        warnings.append("target card is inactive/already merged")
    if source.merged_into_card_id is not None and source.merged_into_card_id != target_card_id:
        warnings.append("source card is already merged into a different target card")
    if score_result.score < MIN_MERGE_SCORE:
        warnings.append(
            f"duplicate_score {score_result.score} is below the {MIN_MERGE_SCORE} review threshold"
        )

    return MergePreview(
        source_card=source,
        target_card=target,
        duplicate_score=score_result.score,
        confidence_label=score_result.confidence_label,
        explanation=score_result.explanation.to_dict(),
        field_merge_preview=_field_merge_preview(source, target, field_strategy),
        affected_records=_affected_records(db, source_card_id),
        warnings=warnings,
    )


@dataclass
class MergeOptions:
    dry_run: bool = True
    merge_notes: str | None = None
    field_strategy: str = DEFAULT_FIELD_STRATEGY
    approve_low_confidence: bool = False


@dataclass
class MergeResult:
    dry_run: bool
    merged: bool
    source_card_id: int
    target_card_id: int
    affected_records: dict[str, int]
    field_changes: dict[str, Any]
    warnings: list[str]
    duplicate_score: int
    confidence_label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "merged": self.merged,
            "source_card_id": self.source_card_id,
            "target_card_id": self.target_card_id,
            "affected_records": self.affected_records,
            "field_changes": self.field_changes,
            "warnings": self.warnings,
            "duplicate_score": self.duplicate_score,
            "confidence_label": self.confidence_label,
        }


def _reassign_card_tags(db: Session, source_card_id: int, target_card_id: int) -> int:
    """card_tags has UNIQUE(card_id, tag_id), so a straight bulk UPDATE could
    violate it whenever the target card already carries the same tag. Walks
    row-by-row instead, skipping (never deleting) any tag already present on
    the target - it's left attached to the now-inactive source card."""
    existing_tag_ids = set(
        db.scalars(select(CardTag.tag_id).where(CardTag.card_id == target_card_id)).all()
    )
    rows = db.scalars(select(CardTag).where(CardTag.card_id == source_card_id)).all()
    reassigned = 0
    for row in rows:
        if row.tag_id in existing_tag_ids:
            continue
        row.card_id = target_card_id
        existing_tag_ids.add(row.tag_id)
        reassigned += 1
    return reassigned


def _create_merge_aliases(db: Session, source: Card, target: Card) -> int:
    """Records the source card's identity fields as aliases on the surviving
    target, wherever they differ - so the merged-away card_code/name can
    still be found later. See app.models.card_alias."""
    created = 0
    if source.card_code and source.card_code != target.card_code:
        db.add(CardAlias(card_id=target.id, alias_type="merged_card_code", alias_value=source.card_code))
        created += 1
    if source.name_en and source.name_en != target.name_en:
        db.add(CardAlias(card_id=target.id, alias_type="old_name_en", alias_value=source.name_en))
        created += 1
    if source.name_jp and source.name_jp != target.name_jp:
        db.add(CardAlias(card_id=target.id, alias_type="old_name_jp", alias_value=source.name_jp))
        created += 1
    return created


def _apply_field_changes(target: Card, field_merge_preview: dict[str, dict[str, Any]]) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for f, change in field_merge_preview.items():
        if change["action"] == "keep_target":
            continue
        setattr(target, f, change["result"])
        changes[f] = {"old": change["target"], "new": change["result"]}
    return changes


def execute_card_merge(
    db: Session, source_card_id: int, target_card_id: int, options: MergeOptions
) -> MergeResult:
    """Merges source_card_id's identity into target_card_id. dry_run=true
    (the default via MergeOptions) only previews - see preview_card_merge for
    the read path this shares its scoring/field-preview logic with. A real
    run (dry_run=false) is expected to run inside the caller's own
    transaction; it flushes/commits once at the end and never deletes a row
    (see the module docstring)."""
    if source_card_id == target_card_id:
        raise MergeValidationError("source_card_id and target_card_id cannot be the same")
    if options.field_strategy not in FIELD_STRATEGIES:
        raise MergeValidationError(f"Invalid field_strategy: {options.field_strategy}")

    source = _get_card_or_error(db, source_card_id, "Source")
    target = _get_card_or_error(db, target_card_id, "Target")

    if not target.is_active or target.merged_into_card_id is not None:
        raise MergeValidationError("Target card is already merged/inactive and cannot receive a merge")
    if source.merged_into_card_id is not None and source.merged_into_card_id != target_card_id:
        raise MergeValidationError(
            "Source card is already merged into a different target card - not supported without a force flag"
        )

    score_result = calculate_duplicate_score(source, target)
    warnings: list[str] = []
    if score_result.score < MIN_MERGE_SCORE:
        if not options.approve_low_confidence:
            raise MergeValidationError(
                f"duplicate_score {score_result.score} is below {MIN_MERGE_SCORE}; "
                "set approve_low_confidence=true to override"
            )
        warnings.append(
            f"merged despite low duplicate_score {score_result.score} (approve_low_confidence=true)"
        )

    affected_records = _affected_records(db, source_card_id)
    field_merge_preview = _field_merge_preview(source, target, options.field_strategy)

    if options.dry_run:
        return MergeResult(
            dry_run=True,
            merged=False,
            source_card_id=source_card_id,
            target_card_id=target_card_id,
            affected_records=affected_records,
            field_changes=field_merge_preview,
            warnings=warnings,
            duplicate_score=score_result.score,
            confidence_label=score_result.confidence_label,
        )

    now = datetime.now(timezone.utc)

    mapping_count = db.execute(
        update(SourceCardMapping)
        .where(SourceCardMapping.card_id == source_card_id)
        .values(card_id=target_card_id)
    ).rowcount
    collection_count = db.execute(
        update(CollectionItem).where(CollectionItem.card_id == source_card_id).values(card_id=target_card_id)
    ).rowcount
    wishlist_count = db.execute(
        update(WishlistItem).where(WishlistItem.card_id == source_card_id).values(card_id=target_card_id)
    ).rowcount
    notes_count = db.execute(
        update(CollectorNote).where(CollectorNote.card_id == source_card_id).values(card_id=target_card_id)
    ).rowcount
    market_signal_count = db.execute(
        update(MarketSignalEvent)
        .where(MarketSignalEvent.card_id == source_card_id)
        .values(card_id=target_card_id)
    ).rowcount
    alert_event_count = db.execute(
        update(AlertEvent).where(AlertEvent.card_id == source_card_id).values(card_id=target_card_id)
    ).rowcount
    activity_event_count = db.execute(
        update(CollectorActivityEvent)
        .where(CollectorActivityEvent.card_id == source_card_id)
        .values(card_id=target_card_id)
    ).rowcount
    card_tags_reassigned = _reassign_card_tags(db, source_card_id, target_card_id)
    if card_tags_reassigned < affected_records["card_tags"]:
        warnings.append(
            f"{affected_records['card_tags'] - card_tags_reassigned} card_tags row(s) were left on "
            "the merged-away card because the target already has the same tag"
        )

    field_changes = _apply_field_changes(target, field_merge_preview)
    aliases_created = _create_merge_aliases(db, source, target)

    source.is_active = False
    source.merged_into_card_id = target_card_id
    source.merged_at = now
    source.merge_notes = options.merge_notes

    db.commit()

    actual_affected = {
        "source_card_mappings": mapping_count,
        "collection_items": collection_count,
        "wishlist_items": wishlist_count,
        "grading_submissions": affected_records["grading_submissions"],
        "card_tags": card_tags_reassigned,
        "collection_item_tags": affected_records["collection_item_tags"],
        "notes": notes_count,
        "market_signal_events": market_signal_count,
        "market_reports": 0,
        "analytics_digest_reports": 0,
        "alert_events": alert_event_count,
        "collector_activity_events": activity_event_count,
        "card_aliases_created": aliases_created,
    }

    return MergeResult(
        dry_run=False,
        merged=True,
        source_card_id=source_card_id,
        target_card_id=target_card_id,
        affected_records=actual_affected,
        field_changes=field_changes,
        warnings=warnings,
        duplicate_score=score_result.score,
        confidence_label=score_result.confidence_label,
    )
