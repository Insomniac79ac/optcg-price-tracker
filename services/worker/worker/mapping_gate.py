"""The worker-local rule for whether a source mapping may write a price.

A price row is a claim that a specific printing sold for a specific amount at
a specific source. A mapping is what authorises that claim, and it authorises
it only in one state:

  * `is_active` - the mapping has not been withdrawn; and
  * `review_status == 'approved'` - a human confirmed the mapping;
  * `card_print_id IS NOT NULL` - the mapping identifies an exact print;
  * the referenced print exists, is active, and is verified; and
  * the mapping's source agrees with the writer's requested/adapted source.

`needs_review` is the explicit "nobody has confirmed this yet" state and
`rejected` is the explicit "this is wrong" state. Neither can back a price,
and an active-but-unapproved row is precisely the case that reads as safe and
is not: it is live, it is fetchable, and nothing about it has been verified.

The API and worker are separate deployables that share no model code, so this
module provides the smallest reusable worker-side contract for generic refresh
and candidate-price ingestion. Dedicated collector guards remain unchanged.

This is a gate on WRITING new prices only. Historical observations and legacy
card-only mappings remain readable and unchanged.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from worker.models import CardPrint, Source, SourceCardMapping

APPROVED_REVIEW_STATUS = "approved"

# SQL-level form, for callers that select mappings in bulk. Spread into a
# query with `.filter(*PRICEABLE_MAPPING_CONDITIONS)`.
PRICEABLE_MAPPING_CONDITIONS = (
    SourceCardMapping.is_active.is_(True),
    SourceCardMapping.review_status == APPROVED_REVIEW_STATUS,
    SourceCardMapping.card_print_id.is_not(None),
)

PRICEABLE_PRINT_CONDITIONS = (
    CardPrint.is_active.is_(True),
    CardPrint.verification_status == "verified",
)


@dataclass(frozen=True)
class PriceableMappingLineage:
    """Authoritative IDs copied onto a new observation after validation."""

    mapping_id: int
    card_id: int | None
    card_print_id: int
    source_id: int


def is_priceable_mapping(mapping: SourceCardMapping) -> bool:
    """Cheap row-local portion of the contract.

    Callers that can write must still use ``load_priceable_mapping_lineage``
    so the referenced print and source are checked in the database.
    """
    return (
        bool(mapping.is_active)
        and mapping.review_status == APPROVED_REVIEW_STATUS
        and mapping.card_print_id is not None
    )


def load_priceable_mapping_lineage(
    db: Session,
    mapping_id: int,
    *,
    expected_source_name: str,
) -> PriceableMappingLineage | None:
    """Return authoritative write lineage only when the full contract holds.

    The scalar query deliberately reloads current database state rather than
    trusting an ORM mapping selected earlier in a potentially slow fetch.
    """
    row = (
        db.query(
            SourceCardMapping.id,
            SourceCardMapping.card_id,
            SourceCardMapping.card_print_id,
            SourceCardMapping.source_id,
        )
        .join(Source, Source.id == SourceCardMapping.source_id)
        .join(CardPrint, CardPrint.id == SourceCardMapping.card_print_id)
        .filter(
            SourceCardMapping.id == mapping_id,
            Source.name == expected_source_name,
            *PRICEABLE_MAPPING_CONDITIONS,
            *PRICEABLE_PRINT_CONDITIONS,
        )
        .one_or_none()
    )
    if row is None:
        return None

    return PriceableMappingLineage(
        mapping_id=row.id,
        card_id=row.card_id,
        card_print_id=row.card_print_id,
        source_id=row.source_id,
    )
