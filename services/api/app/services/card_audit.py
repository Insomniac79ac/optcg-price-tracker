"""Read-only data-quality audit for the card catalog.

Phase 1 of collection tracking needs a trustworthy `cards` table and clean
links to `source_card_mappings`/`price_observations` before any tracking
logic gets built on top of it. This module only reads data and reports
issues - it never mutates or deletes anything.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Card, PriceObservation, Source, SourceCardMapping
from app.models.card_alias import CardAlias
from app.models.snkrdunk_candidate import SnkrdunkCandidate
from app.services.card_catalog_import import LANGUAGE_SYNONYMS, VARIANT_SYNONYMS
from app.services.card_identity_merge import MIN_MERGE_SCORE, duplicate_pairs_at_or_above
from app.services.catalog_coverage import summarize_catalog_coverage
from app.services.source_mapping_confidence import (
    MappingQualityFilters,
    evaluate_source_mappings,
    summarize_mapping_quality,
)

# app.services.card_matching.UNMATCHED_SCORE_THRESHOLD - duplicated here
# (rather than imported) so this module never has to reconcile the two
# different scales SourceCardMapping.match_confidence is written on: the
# legacy manual-match endpoints always write a 0.0-1.0 fraction, while
# approve-match (app.api.admin_snkrdunk_matching) writes the raw 0-100
# card_matching score - see _check_low_confidence_mappings below.
LOW_MATCH_CONFIDENCE_THRESHOLD = 55

CRITICAL = "critical"
WARNING = "warning"

# Shared ground truth with app.services.card_catalog_import, imported rather
# than duplicated - these two modules must never silently disagree on what
# counts as a valid language/variant value, since the importer normalizes to
# exactly these values and the audit below flags anything outside them.
CANONICAL_LANGUAGE_VALUES = set(LANGUAGE_SYNONYMS.values())
CANONICAL_VARIANT_VALUES = set(VARIANT_SYNONYMS.values())

# Catalog-enrichment columns considered by _check_suspicious_empty_metadata -
# the metadata a card_catalog_import CSV import is meant to fill in, not the
# original identity columns which are never blank on a valid row.
_ENRICHMENT_METADATA_FIELDS = (
    "artist",
    "character",
    "color",
    "card_type",
    "cost",
    "power",
    "counter",
    "attribute",
    "effect_text",
    "trigger_text",
)

# Maps a lowercased/stripped raw language value to its canonical form. Raw
# values already equal to the canonical form are left alone; everything else
# is flagged for normalization.
CANONICAL_LANGUAGES = {
    "en": "en",
    "english": "en",
    "jp": "jp",
    "japanese": "jp",
    "japan": "jp",
}

# Variant text that doesn't actually describe a specific print/edition.
VAGUE_VARIANT_TOKENS = {"base", "normal", "regular", "standard"}


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


@dataclass
class AuditIssue:
    issue_type: str
    severity: str
    message: str
    suggested_action: str
    card_ids: list[int] = field(default_factory=list)
    card_code: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "issue_type": self.issue_type,
            "severity": self.severity,
            "card_ids": self.card_ids,
            "card_code": self.card_code,
            "message": self.message,
            "suggested_action": self.suggested_action,
        }
        if self.details is not None:
            payload["details"] = self.details
        return payload


@dataclass
class CardAuditReport:
    total_cards: int
    issues: list[AuditIssue]
    # Populated by run_card_audit from
    # app.services.source_mapping_confidence.summarize_mapping_quality - see
    # that module's docstring for what each count means. None only for
    # CardAuditReport instances built outside run_card_audit (e.g. in tests
    # that construct one directly without a db session).
    mapping_quality: dict[str, int] | None = None

    # Populated by run_card_audit from
    # app.services.catalog_coverage.summarize_catalog_coverage - a top-line
    # summary only (see GET /admin/catalog-coverage for the full breakdown
    # and per-card gap lists), so this audit doesn't duplicate every
    # metadata/mapping/price/duplicate/mapping-quality gap the coverage page
    # already lists individually.
    catalog_coverage: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        critical_issues = sum(1 for issue in self.issues if issue.severity == CRITICAL)
        warning_issues = sum(1 for issue in self.issues if issue.severity == WARNING)
        summary: dict[str, Any] = {
            "total_cards": self.total_cards,
            "total_issues": len(self.issues),
            "critical_issues": critical_issues,
            "warning_issues": warning_issues,
        }
        if self.mapping_quality is not None:
            summary["mapping_quality"] = self.mapping_quality
        return {
            "summary": summary,
            "issues": [issue.to_dict() for issue in self.issues],
            "catalog_coverage": self.catalog_coverage,
        }


def _check_duplicate_card_code_conflicting_names(cards: list[Card]) -> list[AuditIssue]:
    by_code: dict[str, list[Card]] = defaultdict(list)
    for card in cards:
        by_code[card.card_code].append(card)

    issues: list[AuditIssue] = []
    for card_code, group in by_code.items():
        if len(group) < 2:
            continue
        distinct_names = {(_norm(c.name_en), _norm(c.name_jp)) for c in group}
        if len(distinct_names) > 1:
            issues.append(
                AuditIssue(
                    issue_type="duplicate_card_code_conflicting_names",
                    severity=CRITICAL,
                    card_ids=sorted(c.id for c in group),
                    card_code=card_code,
                    message=(
                        f"card_code '{card_code}' is shared by {len(group)} cards with "
                        f"conflicting names: {sorted(str(n) for n in distinct_names)}"
                    ),
                    suggested_action="review_duplicate_card",
                )
            )
    return issues


def _check_inconsistent_language_values(cards: list[Card]) -> list[AuditIssue]:
    by_raw_value: dict[str, list[Card]] = defaultdict(list)
    for card in cards:
        if card.language:
            by_raw_value[card.language].append(card)

    issues: list[AuditIssue] = []
    for raw_value, group in by_raw_value.items():
        canonical = CANONICAL_LANGUAGES.get(raw_value.strip().lower())
        if canonical is None or raw_value == canonical:
            continue
        issues.append(
            AuditIssue(
                issue_type="inconsistent_language_values",
                severity=WARNING,
                card_ids=sorted(c.id for c in group),
                card_code=None,
                message=(
                    f"Language value '{raw_value}' should be normalized to '{canonical}' "
                    f"({len(group)} card(s) affected)"
                ),
                suggested_action="normalize_language_value",
                details={"raw_value": raw_value, "canonical_value": canonical},
            )
        )
    return issues


def _check_suspicious_variant_values(cards: list[Card]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []

    empty_variant_cards = [c for c in cards if c.variant is not None and c.variant.strip() == ""]
    if empty_variant_cards:
        issues.append(
            AuditIssue(
                issue_type="suspicious_variant_values",
                severity=WARNING,
                card_ids=sorted(c.id for c in empty_variant_cards),
                card_code=None,
                message=(
                    f"{len(empty_variant_cards)} card(s) have an empty (non-null) variant value"
                ),
                suggested_action="normalize_variant_value",
            )
        )

    by_normalized: dict[str, dict[str, list[Card]]] = defaultdict(lambda: defaultdict(list))
    for card in cards:
        normalized = _norm(card.variant)
        if normalized is None:
            continue
        by_normalized[normalized.lower()][card.variant].append(card)

    for normalized, raw_variants in by_normalized.items():
        card_ids = sorted(c.id for group in raw_variants.values() for c in group)

        if len(raw_variants) > 1:
            issues.append(
                AuditIssue(
                    issue_type="suspicious_variant_values",
                    severity=WARNING,
                    card_ids=card_ids,
                    card_code=None,
                    message=(
                        f"Variant value '{normalized}' has inconsistent casing across cards: "
                        f"{sorted(raw_variants.keys())}"
                    ),
                    suggested_action="normalize_variant_value",
                )
            )

        if normalized in VAGUE_VARIANT_TOKENS:
            issues.append(
                AuditIssue(
                    issue_type="suspicious_variant_values",
                    severity=WARNING,
                    card_ids=card_ids,
                    card_code=None,
                    message=(
                        f"Variant value(s) {sorted(raw_variants.keys())} are too vague to "
                        "identify a specific print"
                    ),
                    suggested_action="clarify_variant_value",
                )
            )

    return issues


def _check_duplicate_source_url(
    mappings: list[SourceCardMapping], sources_by_id: dict[int, Source]
) -> list[AuditIssue]:
    # The DB only enforces exact-string uniqueness of (source_id, source_url),
    # so this catches near-duplicates (whitespace/casing) that slip past it.
    groups: dict[tuple[int, str], dict[str, list[SourceCardMapping]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for mapping in mappings:
        normalized = _norm(mapping.source_url)
        if normalized is None:
            continue
        groups[(mapping.source_id, normalized.lower())][mapping.source_url].append(mapping)

    issues: list[AuditIssue] = []
    for (source_id, _normalized_url), raw_urls in groups.items():
        all_mappings = [m for group in raw_urls.values() for m in group]
        if len(all_mappings) < 2:
            continue

        source = sources_by_id.get(source_id)
        source_name = source.name if source is not None else str(source_id)
        card_ids = sorted({m.card_id for m in all_mappings})
        issues.append(
            AuditIssue(
                issue_type="duplicate_source_url",
                severity=CRITICAL,
                card_ids=card_ids,
                card_code=None,
                message=(
                    f"URL(s) {sorted(raw_urls.keys())} for source '{source_name}' are mapped "
                    f"{len(all_mappings)} times"
                ),
                suggested_action="review_duplicate_source_mapping",
                details={
                    "source_id": source_id,
                    "mapping_ids": sorted(m.id for m in all_mappings),
                },
            )
        )
    return issues


def _check_source_card_code_mismatch(
    mappings: list[SourceCardMapping], cards_by_id: dict[int, Card]
) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for mapping in mappings:
        card = cards_by_id.get(mapping.card_id)
        if card is None:
            continue

        source_card_id = _norm(mapping.source_card_id)
        card_code = _norm(card.card_code)
        if source_card_id is None or card_code is None or source_card_id == card_code:
            continue

        issues.append(
            AuditIssue(
                issue_type="source_card_code_mismatch",
                severity=CRITICAL,
                card_ids=[card.id],
                card_code=card.card_code,
                message=(
                    f"Mapping {mapping.id} has source_card_id '{mapping.source_card_id}' "
                    f"which does not match card_code '{card.card_code}' (card {card.id})"
                ),
                suggested_action="review_source_mapping",
                details={"mapping_id": mapping.id, "source_card_id": mapping.source_card_id},
            )
        )
    return issues


def _check_cards_without_source_mappings(
    cards: list[Card], mapped_card_ids: set[int]
) -> list[AuditIssue]:
    missing = [c for c in cards if c.id not in mapped_card_ids]
    if not missing:
        return []
    return [
        AuditIssue(
            issue_type="cards_without_source_mappings",
            severity=WARNING,
            card_ids=sorted(c.id for c in missing),
            card_code=None,
            message=f"{len(missing)} card(s) have no source_card_mappings",
            suggested_action="add_source_mapping",
        )
    ]


def _check_cards_with_prices_but_no_active_mapping(
    priced_card_ids: set[int], active_mapped_card_ids: set[int]
) -> list[AuditIssue]:
    orphaned = sorted(priced_card_ids - active_mapped_card_ids)
    if not orphaned:
        return []
    return [
        AuditIssue(
            issue_type="cards_with_prices_but_no_active_mapping",
            severity=CRITICAL,
            card_ids=orphaned,
            card_code=None,
            message=(
                f"{len(orphaned)} card(s) have price_observations but no active "
                "source_card_mappings"
            ),
            suggested_action="restore_source_mapping",
        )
    ]


def _check_missing_set_code(cards: list[Card]) -> list[AuditIssue]:
    missing = [c for c in cards if _norm(c.set_code) is None]
    if not missing:
        return []
    return [
        AuditIssue(
            issue_type="missing_set_code",
            severity=CRITICAL,
            card_ids=sorted(c.id for c in missing),
            card_code=None,
            message=f"{len(missing)} card(s) have no set_code",
            suggested_action="add_set_code",
        )
    ]


def _check_set_code_mismatch_card_code(cards: list[Card]) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for card in cards:
        code = _norm(card.card_code)
        set_code = _norm(card.set_code)
        if code is None or set_code is None or "-" not in code:
            continue
        inferred = code.split("-", 1)[0]
        if inferred != set_code:
            issues.append(
                AuditIssue(
                    issue_type="set_code_mismatch_card_code",
                    severity=CRITICAL,
                    card_ids=[card.id],
                    card_code=card.card_code,
                    message=(
                        f"card_code '{card.card_code}' implies set_code '{inferred}' but the "
                        f"stored set_code is '{card.set_code}'"
                    ),
                    suggested_action="fix_set_code",
                    details={"inferred_set_code": inferred, "stored_set_code": card.set_code},
                )
            )
    return issues


def _check_missing_name_en(cards: list[Card]) -> list[AuditIssue]:
    missing = [c for c in cards if _norm(c.name_en) is None]
    if not missing:
        return []
    return [
        AuditIssue(
            issue_type="missing_name_en",
            severity=WARNING,
            card_ids=sorted(c.id for c in missing),
            card_code=None,
            message=f"{len(missing)} card(s) have no name_en",
            suggested_action="add_name_en",
        )
    ]


def _check_duplicate_card_code_same_language_variant(cards: list[Card]) -> list[AuditIssue]:
    """Groups by (card_code, language, variant) - a narrower key than the
    DB's own (card_code, set_code, rarity, variant, language) uniqueness
    constraint, so a group here always represents *different* set_code/
    rarity rows the DB itself allowed. That's sometimes legitimate (a
    reprint, or several rarities of the same card in one set) and sometimes
    a data-entry mistake (the same print entered twice under a slightly
    different set_code/rarity) - flagged as a warning either way, for a
    human to confirm rather than a hard rule."""
    groups: dict[tuple[str, str, str | None], list[Card]] = defaultdict(list)
    for card in cards:
        groups[(card.card_code, card.language, _norm(card.variant))].append(card)

    issues: list[AuditIssue] = []
    for (card_code, language, variant), group in groups.items():
        if len(group) < 2:
            continue
        issues.append(
            AuditIssue(
                issue_type="duplicate_card_code_same_language_variant",
                severity=WARNING,
                card_ids=sorted(c.id for c in group),
                card_code=card_code,
                message=(
                    f"card_code '{card_code}' (language={language}, variant={variant}) appears "
                    f"{len(group)} times across different set_code/rarity values - confirm these "
                    "are genuinely distinct prints, not duplicate data entry"
                ),
                suggested_action="review_duplicate_card_variant",
            )
        )
    return issues


def _check_invalid_language(cards: list[Card]) -> list[AuditIssue]:
    invalid = [c for c in cards if c.language not in CANONICAL_LANGUAGE_VALUES]
    if not invalid:
        return []
    return [
        AuditIssue(
            issue_type="invalid_language",
            severity=WARNING,
            card_ids=sorted(c.id for c in invalid),
            card_code=None,
            message=(
                f"{len(invalid)} card(s) have a language value outside "
                f"{sorted(CANONICAL_LANGUAGE_VALUES)}"
            ),
            suggested_action="normalize_language_value",
        )
    ]


def _check_invalid_variant(cards: list[Card]) -> list[AuditIssue]:
    invalid = [
        c for c in cards if c.variant is not None and c.variant not in CANONICAL_VARIANT_VALUES
    ]
    if not invalid:
        return []
    return [
        AuditIssue(
            issue_type="invalid_variant",
            severity=WARNING,
            card_ids=sorted(c.id for c in invalid),
            card_code=None,
            message=(
                f"{len(invalid)} card(s) have a variant value outside "
                f"{sorted(CANONICAL_VARIANT_VALUES)}"
            ),
            suggested_action="normalize_variant_value",
        )
    ]


def _check_suspicious_empty_metadata(cards: list[Card]) -> list[AuditIssue]:
    """Only fires once catalog enrichment has actually started (at least one
    card in the catalog has some metadata) - otherwise every legacy card
    (created before this feature existed) would trip this unconditionally,
    which isn't an actionable per-card issue so much as "nobody has bulk-
    imported catalog metadata yet", a statement about the whole catalog, not
    this card."""
    has_any_metadata = any(
        any(getattr(c, f) is not None for f in _ENRICHMENT_METADATA_FIELDS) for c in cards
    )
    if not has_any_metadata:
        return []

    empty = [
        c for c in cards if all(getattr(c, f) is None for f in _ENRICHMENT_METADATA_FIELDS)
    ]
    if not empty:
        return []
    return [
        AuditIssue(
            issue_type="suspicious_empty_metadata",
            severity=WARNING,
            card_ids=sorted(c.id for c in empty),
            card_code=None,
            message=(
                f"{len(empty)} card(s) have no catalog metadata at all "
                f"({', '.join(_ENRICHMENT_METADATA_FIELDS)} are all empty)"
            ),
            suggested_action="enrich_card_metadata",
        )
    ]


def _check_invalid_numeric_fields(cards: list[Card]) -> list[AuditIssue]:
    invalid = [
        c
        for c in cards
        if any(
            getattr(c, f) is not None and getattr(c, f) < 0 for f in ("cost", "power", "counter")
        )
    ]
    if not invalid:
        return []
    return [
        AuditIssue(
            issue_type="invalid_numeric_fields",
            severity=WARNING,
            card_ids=sorted(c.id for c in invalid),
            card_code=None,
            message=f"{len(invalid)} card(s) have a negative cost/power/counter value",
            suggested_action="fix_numeric_fields",
        )
    ]


def _match_confidence_as_score(match_confidence: float) -> float:
    """Normalizes SourceCardMapping.match_confidence to a 0-100 scale
    regardless of which write-path produced it: legacy manual-match
    endpoints always write a 0.0-1.0 fraction, while approve-match writes
    the raw 0-100 app.services.card_matching score directly (see that
    endpoint's docstring). Anything at or below 1.0 is treated as the
    legacy fractional scale."""
    return match_confidence * 100 if match_confidence <= 1.0 else match_confidence


def _check_low_confidence_mappings(
    mappings: list[SourceCardMapping], cards_by_id: dict[int, Card]
) -> list[AuditIssue]:
    low_confidence = [
        m
        for m in mappings
        if m.match_confidence is not None
        and _match_confidence_as_score(m.match_confidence) < LOW_MATCH_CONFIDENCE_THRESHOLD
    ]
    if not low_confidence:
        return []

    issues: list[AuditIssue] = []
    for mapping in low_confidence:
        card = cards_by_id.get(mapping.card_id)
        score = round(_match_confidence_as_score(mapping.match_confidence), 1)
        issues.append(
            AuditIssue(
                issue_type="low_match_confidence_mapping",
                severity=WARNING,
                card_ids=[mapping.card_id],
                card_code=card.card_code if card is not None else None,
                message=(
                    f"Mapping {mapping.id} (source_id={mapping.source_id}) has a low match "
                    f"confidence of {score}/100"
                ),
                suggested_action="review_source_mapping",
                details={"mapping_id": mapping.id, "match_confidence_score": score},
            )
        )
    return issues


def _check_candidate_variant_mismatch(candidates: list[SnkrdunkCandidate]) -> list[AuditIssue]:
    """Flags a matched candidate whose stored match_explanation_json (set by
    rank_candidate_matches/approve-match, see app.services.card_matching)
    recorded a variant mismatch against the card it was matched to - a
    human overriding the suggestion is allowed, but it's worth surfacing."""
    flagged = [
        c
        for c in candidates
        if c.match_status == "matched"
        and c.match_explanation_json
        and "variant mismatch" in (c.match_explanation_json.get("negative") or [])
    ]
    if not flagged:
        return []

    issues: list[AuditIssue] = []
    for candidate in flagged:
        issues.append(
            AuditIssue(
                issue_type="candidate_variant_mismatch",
                severity=WARNING,
                card_ids=[candidate.matched_card_id] if candidate.matched_card_id else [],
                card_code=candidate.detected_card_code,
                message=(
                    f"Candidate {candidate.id} was matched to card_id={candidate.matched_card_id} "
                    "despite a recorded variant mismatch"
                ),
                suggested_action="review_candidate_match",
                details={"candidate_id": candidate.id},
            )
        )
    return issues


def _check_duplicate_card_identity(db: Session) -> list[AuditIssue]:
    """One AuditIssue per active-card pair that
    app.services.card_identity_merge scores at or above MIN_MERGE_SCORE
    (the same bar execute_card_merge itself requires without an explicit
    approve_low_confidence override) - see GET /admin/cards/duplicates for
    the full reviewable list this summarizes."""
    issues: list[AuditIssue] = []
    for pair in duplicate_pairs_at_or_above(db, MIN_MERGE_SCORE):
        issues.append(
            AuditIssue(
                issue_type="duplicate_card_identity",
                severity=WARNING,
                card_ids=sorted([pair.source_card.id, pair.target_card.id]),
                card_code=pair.source_card.card_code,
                message=(
                    f"Cards {pair.source_card.id} and {pair.target_card.id} look like duplicates "
                    f"(score={pair.score}, {pair.confidence_label}) - review at "
                    "GET /admin/cards/duplicates"
                ),
                suggested_action="review_card_merge",
                details={
                    "score": pair.score,
                    "confidence_label": pair.confidence_label,
                    "recommended_target_card_id": pair.recommended_target_card_id,
                },
            )
        )
    return issues


def _check_inactive_card_without_merge_target(cards: list[Card]) -> list[AuditIssue]:
    missing = [c for c in cards if not c.is_active and c.merged_into_card_id is None]
    if not missing:
        return []
    return [
        AuditIssue(
            issue_type="inactive_card_without_merge_target",
            severity=WARNING,
            card_ids=sorted(c.id for c in missing),
            card_code=None,
            message=f"{len(missing)} card(s) are inactive but have no merged_into_card_id set",
            suggested_action="set_merge_target_or_reactivate",
        )
    ]


def _check_active_card_merged_into_another_card(cards: list[Card]) -> list[AuditIssue]:
    inconsistent = [c for c in cards if c.is_active and c.merged_into_card_id is not None]
    if not inconsistent:
        return []
    return [
        AuditIssue(
            issue_type="active_card_merged_into_another_card",
            severity=CRITICAL,
            card_ids=sorted(c.id for c in inconsistent),
            card_code=None,
            message=(
                f"{len(inconsistent)} card(s) are marked active but also have a "
                "merged_into_card_id set"
            ),
            suggested_action="fix_merge_state",
        )
    ]


def _check_merged_card_still_has_active_source_mapping(
    mappings: list[SourceCardMapping], cards_by_id: dict[int, Card]
) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for mapping in mappings:
        if not mapping.is_active:
            continue
        card = cards_by_id.get(mapping.card_id)
        if card is None or card.is_active or card.merged_into_card_id is None:
            continue
        issues.append(
            AuditIssue(
                issue_type="merged_card_still_has_active_source_mapping",
                severity=CRITICAL,
                card_ids=[card.id],
                card_code=card.card_code,
                message=(
                    f"Mapping {mapping.id} is still active and points at merged (inactive) "
                    f"card {card.id}, which was merged into card {card.merged_into_card_id} - it "
                    "should have been reassigned by the merge"
                ),
                suggested_action="reassign_or_deactivate_source_mapping",
                details={"mapping_id": mapping.id, "merged_into_card_id": card.merged_into_card_id},
            )
        )
    return issues


def _check_card_alias_without_card(db: Session, card_ids: set[int]) -> list[AuditIssue]:
    aliases = list(db.scalars(select(CardAlias)).all())
    orphaned = [a for a in aliases if a.card_id not in card_ids]
    if not orphaned:
        return []
    return [
        AuditIssue(
            issue_type="card_alias_without_card",
            severity=WARNING,
            card_ids=sorted({a.card_id for a in orphaned}),
            card_code=None,
            message=f"{len(orphaned)} card_aliases row(s) reference a card_id that no longer exists",
            suggested_action="remove_orphaned_alias",
            details={"alias_ids": sorted(a.id for a in orphaned)},
        )
    ]


def _check_critical_mapping_quality(db: Session) -> list[AuditIssue]:
    """One AuditIssue per source_card_mappings row that
    app.services.source_mapping_confidence.evaluate_source_mapping rates
    risk_level="critical" (missing card reference, a card_code that
    conflicts with the mapped card, very-low confidence, or a near-duplicate
    source URL) - see GET /admin/source-mappings/quality for the full
    per-mapping breakdown this summarizes."""
    critical_items, _total, _summary = evaluate_source_mappings(
        db, MappingQualityFilters(risk_level="critical"), limit=500, offset=0
    )
    issues: list[AuditIssue] = []
    for item in critical_items:
        issues.append(
            AuditIssue(
                issue_type="critical_mapping_quality",
                severity=CRITICAL,
                card_ids=[item.card_id],
                card_code=item.card_code,
                message=(
                    f"Mapping {item.mapping_id} (source={item.source_name}) is critical risk: "
                    f"{', '.join(item.issue_types)}"
                ),
                suggested_action="review_source_mapping_quality",
                details={"mapping_id": item.mapping_id, "issue_types": item.issue_types},
            )
        )
    return issues


def run_card_audit(db: Session) -> CardAuditReport:
    cards = list(db.scalars(select(Card)).all())
    mappings = list(db.scalars(select(SourceCardMapping)).all())
    candidates = list(db.scalars(select(SnkrdunkCandidate)).all())
    sources_by_id = {s.id: s for s in db.scalars(select(Source)).all()}
    cards_by_id = {c.id: c for c in cards}

    mapped_card_ids = {m.card_id for m in mappings}
    active_mapped_card_ids = {m.card_id for m in mappings if m.is_active}
    priced_card_ids = set(db.scalars(select(PriceObservation.card_id).distinct()).all())

    issues: list[AuditIssue] = [
        *_check_duplicate_card_code_conflicting_names(cards),
        *_check_inconsistent_language_values(cards),
        *_check_suspicious_variant_values(cards),
        *_check_duplicate_source_url(mappings, sources_by_id),
        *_check_source_card_code_mismatch(mappings, cards_by_id),
        *_check_cards_without_source_mappings(cards, mapped_card_ids),
        *_check_cards_with_prices_but_no_active_mapping(priced_card_ids, active_mapped_card_ids),
        *_check_missing_set_code(cards),
        *_check_set_code_mismatch_card_code(cards),
        *_check_missing_name_en(cards),
        *_check_duplicate_card_code_same_language_variant(cards),
        *_check_invalid_language(cards),
        *_check_invalid_variant(cards),
        *_check_suspicious_empty_metadata(cards),
        *_check_invalid_numeric_fields(cards),
        *_check_low_confidence_mappings(mappings, cards_by_id),
        *_check_candidate_variant_mismatch(candidates),
        *_check_critical_mapping_quality(db),
        *_check_duplicate_card_identity(db),
        *_check_inactive_card_without_merge_target(cards),
        *_check_active_card_merged_into_another_card(cards),
        *_check_merged_card_still_has_active_source_mapping(mappings, cards_by_id),
        *_check_card_alias_without_card(db, set(cards_by_id.keys())),
    ]

    return CardAuditReport(
        total_cards=len(cards),
        issues=issues,
        mapping_quality=summarize_mapping_quality(db),
        catalog_coverage=summarize_catalog_coverage(db),
    )
