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

CRITICAL = "critical"
WARNING = "warning"

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

    def to_dict(self) -> dict[str, Any]:
        critical_issues = sum(1 for issue in self.issues if issue.severity == CRITICAL)
        warning_issues = sum(1 for issue in self.issues if issue.severity == WARNING)
        return {
            "summary": {
                "total_cards": self.total_cards,
                "total_issues": len(self.issues),
                "critical_issues": critical_issues,
                "warning_issues": warning_issues,
            },
            "issues": [issue.to_dict() for issue in self.issues],
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


def run_card_audit(db: Session) -> CardAuditReport:
    cards = list(db.scalars(select(Card)).all())
    mappings = list(db.scalars(select(SourceCardMapping)).all())
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
    ]

    return CardAuditReport(total_cards=len(cards), issues=issues)
