"""Read-only identity projection for source-card mappings.

Pricing identity is the physical ``CardPrint``.  ``card_id`` is retained only
as optional compatibility metadata and is never used to infer a print.  This
module deliberately contains no mutation helpers: operational reports can
share one classification without acquiring approval or writer capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    PriceObservation,
    ReleaseProduct,
    Source,
    SourceCardMapping,
)

EXACT = "exact"
LEGACY_COMPATIBILITY = "legacy_compatibility"
BROKEN = "broken"
IDENTITY_CLASSIFICATIONS = (EXACT, LEGACY_COMPATIBILITY, BROKEN)


@dataclass(frozen=True)
class SourceMappingIdentity:
    mapping: SourceCardMapping
    source: Source | None
    card_print: CardPrint | None
    canonical_card: CanonicalCard | None
    release_product: ReleaseProduct | None
    compatibility_card: Card | None
    classification: str

    @property
    def source_card_mapping_id(self) -> int:
        return self.mapping.id

    @property
    def source_id(self) -> int:
        return self.mapping.source_id

    @property
    def card_print_id(self) -> int | None:
        return self.mapping.card_print_id

    @property
    def canonical_card_id(self) -> int | None:
        return (
            self.card_print.canonical_card_id if self.card_print is not None else None
        )

    @property
    def release_product_id(self) -> int | None:
        return (
            self.card_print.release_product_id if self.card_print is not None else None
        )

    @property
    def compatibility_card_id(self) -> int | None:
        return self.mapping.card_id

    @property
    def is_priceable_print(self) -> bool:
        """Mirror the existing exact-approval priceability contract.

        ``assert_print_is_priceable`` requires an existing, active, verified
        print.  The verified-print database constraint supplies its settled
        product/artwork fields; reporting does not invent an additional
        Market Index or Card Pirate eligibility rule here.
        """
        return (
            self.classification == EXACT
            and self.card_print is not None
            and self.card_print.is_active
            and self.card_print.verification_status == "verified"
        )

    @property
    def is_operationally_eligible(self) -> bool:
        """Whether the mapping may participate in current exact pricing.

        This mirrors the read-only portion of the worker mapping gate.  It
        does not approve, activate, or otherwise mutate a mapping.
        """
        return (
            self.mapping.is_active
            and self.mapping.superseded_at is None
            and self.mapping.review_status == "approved"
            and self.is_priceable_print
        )


def classify_mapping_identity(
    mapping: SourceCardMapping,
    *,
    source: Source | None,
    card_print: CardPrint | None,
    canonical_card: CanonicalCard | None,
    release_product: ReleaseProduct | None,
    compatibility_card: Card | None,
) -> str:
    """Classify only from durable foreign-key identity; never infer a print."""
    if mapping.card_print_id is not None:
        print_lineage_exists = (
            card_print is not None
            and canonical_card is not None
            and (card_print.release_product_id is None or release_product is not None)
        )
        return EXACT if source is not None and print_lineage_exists else BROKEN

    if (
        mapping.card_id is not None
        and compatibility_card is not None
        and source is not None
    ):
        return LEGACY_COMPATIBILITY

    return BROKEN


def classify_observation_identity(
    observation: PriceObservation,
    *,
    mapping_identity: SourceMappingIdentity | None,
) -> str:
    """Classify observation lineage without inferring identity from Card.

    Historical rows with neither exact-lineage field remain legitimate
    compatibility observations.  A row is exact only when both lineage
    fields are present and agree with an exact mapping's print and source.
    ``card_id`` is intentionally irrelevant to this decision.
    """
    mapping_id = observation.source_card_mapping_id
    print_id = observation.card_print_id
    if mapping_id is None and print_id is None:
        return LEGACY_COMPATIBILITY
    if mapping_id is None or print_id is None:
        return BROKEN
    if mapping_identity is None or mapping_identity.classification != EXACT:
        return BROKEN
    mapping = mapping_identity.mapping
    if (
        mapping.id != mapping_id
        or mapping.card_print_id != print_id
        or mapping.source_id != observation.source_id
    ):
        return BROKEN
    return EXACT


def load_source_mapping_identities(
    db: Session,
    *,
    conditions: Iterable[ColumnElement[bool]] = (),
) -> list[SourceMappingIdentity]:
    """Load mappings and every identity parent with outer joins, read-only."""
    stmt = (
        select(
            SourceCardMapping,
            Source,
            CardPrint,
            CanonicalCard,
            ReleaseProduct,
            Card,
        )
        .outerjoin(Source, Source.id == SourceCardMapping.source_id)
        .outerjoin(CardPrint, CardPrint.id == SourceCardMapping.card_print_id)
        .outerjoin(CanonicalCard, CanonicalCard.id == CardPrint.canonical_card_id)
        .outerjoin(ReleaseProduct, ReleaseProduct.id == CardPrint.release_product_id)
        .outerjoin(Card, Card.id == SourceCardMapping.card_id)
        .where(*tuple(conditions))
        .order_by(SourceCardMapping.id)
    )
    rows = db.execute(stmt).all()
    identities: list[SourceMappingIdentity] = []
    for mapping, source, card_print, canonical, product, compatibility_card in rows:
        classification = classify_mapping_identity(
            mapping,
            source=source,
            card_print=card_print,
            canonical_card=canonical,
            release_product=product,
            compatibility_card=compatibility_card,
        )
        identities.append(
            SourceMappingIdentity(
                mapping=mapping,
                source=source,
                card_print=card_print,
                canonical_card=canonical,
                release_product=product,
                compatibility_card=compatibility_card,
                classification=classification,
            )
        )
    return identities


def load_source_mapping_identity(
    db: Session, mapping_id: int
) -> SourceMappingIdentity | None:
    """Load one mapping through the same shared identity projection."""
    identities = load_source_mapping_identities(
        db, conditions=(SourceCardMapping.id == mapping_id,)
    )
    return identities[0] if identities else None


__all__ = [
    "BROKEN",
    "EXACT",
    "IDENTITY_CLASSIFICATIONS",
    "LEGACY_COMPATIBILITY",
    "SourceMappingIdentity",
    "classify_observation_identity",
    "classify_mapping_identity",
    "load_source_mapping_identity",
    "load_source_mapping_identities",
]
