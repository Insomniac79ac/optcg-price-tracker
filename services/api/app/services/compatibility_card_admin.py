"""Compatibility-card administration for source mappings.

This service edits only ``SourceCardMapping.card_id``. It deliberately has no
API for ``card_print_id`` and never changes approval, verification, activity,
source-listing identity, observations, or persisted authoritative confidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Card, SourceCardMapping
from app.services.source_mapping_identity import (
    BROKEN,
    EXACT,
    LEGACY_COMPATIBILITY,
    load_source_mapping_identity,
)

ERROR_COMPATIBILITY_CARD_NOT_FOUND = "compatibility_card_not_found"
ERROR_BROKEN_MAPPING_IDENTITY = "broken_mapping_identity"
ERROR_LEGACY_COMPATIBILITY_CARD_REQUIRED = "legacy_compatibility_card_required"
ERROR_IDENTITY_CLASSIFICATION_CHANGED = "identity_classification_changed"


class CompatibilityCardEditError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class CompatibilityCardEditResult:
    mapping: SourceCardMapping
    previous_compatibility_card_id: int | None
    new_compatibility_card_id: int | None
    authoritative_card_print_id: int | None
    identity_classification: str
    pricing_identity_changed: bool = False


def update_mapping_compatibility_card(
    db: Session,
    mapping: SourceCardMapping,
    *,
    compatibility_card_id: int | None,
    review_notes: str | None = None,
) -> CompatibilityCardEditResult:
    """Edit compatibility metadata while preserving pricing identity.

    Broken rows fail closed: changing a legacy pointer must not be presented as
    repair of structural exact lineage. A legacy compatibility mapping also
    cannot be cleared, because that would turn the row into ``broken`` rather
    than keep it a compatibility record.
    """
    before = load_source_mapping_identity(db, mapping.id)
    if before is None or before.classification == BROKEN:
        raise CompatibilityCardEditError(
            ERROR_BROKEN_MAPPING_IDENTITY,
            "Compatibility-card metadata cannot repair a mapping with broken "
            "identity lineage.",
        )
    if compatibility_card_id is None and before.classification == LEGACY_COMPATIBILITY:
        raise CompatibilityCardEditError(
            ERROR_LEGACY_COMPATIBILITY_CARD_REQUIRED,
            "A legacy_compatibility mapping must retain a valid compatibility card; "
            "clearing it would create broken lineage.",
        )
    if (
        compatibility_card_id is not None
        and db.get(Card, compatibility_card_id) is None
    ):
        raise CompatibilityCardEditError(
            ERROR_COMPATIBILITY_CARD_NOT_FOUND,
            f"Compatibility Card {compatibility_card_id} was not found.",
        )

    previous_card_id = mapping.card_id
    authoritative_print_id = mapping.card_print_id
    operational_state = (
        mapping.is_active,
        mapping.review_status,
        mapping.manual_verified,
        mapping.last_verified_at,
        mapping.source_url,
        mapping.source_card_id,
        mapping.match_confidence,
        mapping.match_confidence_label,
        mapping.match_explanation_json,
        mapping.last_match_checked_at,
    )

    mapping.card_id = compatibility_card_id
    if review_notes is not None:
        mapping.review_notes = review_notes
    db.flush()

    after = load_source_mapping_identity(db, mapping.id)
    expected_classification = (
        EXACT if before.classification == EXACT else LEGACY_COMPATIBILITY
    )
    current_operational_state = (
        mapping.is_active,
        mapping.review_status,
        mapping.manual_verified,
        mapping.last_verified_at,
        mapping.source_url,
        mapping.source_card_id,
        mapping.match_confidence,
        mapping.match_confidence_label,
        mapping.match_explanation_json,
        mapping.last_match_checked_at,
    )
    if (
        after is None
        or after.classification != expected_classification
        or mapping.card_print_id != authoritative_print_id
        or current_operational_state != operational_state
    ):
        mapping.card_id = previous_card_id
        raise CompatibilityCardEditError(
            ERROR_IDENTITY_CLASSIFICATION_CHANGED,
            "Compatibility-card edit was refused because it would change pricing "
            "identity or operational mapping state.",
        )

    return CompatibilityCardEditResult(
        mapping=mapping,
        previous_compatibility_card_id=previous_card_id,
        new_compatibility_card_id=compatibility_card_id,
        authoritative_card_print_id=authoritative_print_id,
        identity_classification=after.classification,
    )


__all__ = [
    "CompatibilityCardEditError",
    "CompatibilityCardEditResult",
    "ERROR_BROKEN_MAPPING_IDENTITY",
    "ERROR_COMPATIBILITY_CARD_NOT_FOUND",
    "ERROR_IDENTITY_CLASSIFICATION_CHANGED",
    "ERROR_LEGACY_COMPATIBILITY_CARD_REQUIRED",
    "update_mapping_compatibility_card",
]
