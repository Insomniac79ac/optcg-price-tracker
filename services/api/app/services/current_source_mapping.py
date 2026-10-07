"""Database-backed current listing lookup; never chooses among conflicting rows."""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from opcg_source_identity import canonical_source_listing_identity

from app.models import Source, SourceCardMapping
from app.services.exact_print_approval import (
    ExactPrintApprovalError,
    REFUSAL_LISTING_ALREADY_MAPPED,
    REFUSAL_MULTIPLE_MAPPINGS_FOR_LISTING,
    REFUSAL_SOURCE_URL_NOT_CANONICAL,
)


def assert_print_source_available(db, *, source, card_print_id, mapping=None):
    """Serialize supported writers and preserve the existing exact source row.

    Another listing for the same physical print is not a second source. Never
    activate it while a current mapping already owns that print/source pair.
    """
    # Approvals still exclude each other. Allow collectors' foreign-key KEY
    # SHARE checks to retain raw snapshots while this transaction is open.
    db.scalar(select(Source.id).where(Source.id == source.id).with_for_update(key_share=True))
    query = select(SourceCardMapping.id).where(
        SourceCardMapping.source_id == source.id,
        SourceCardMapping.card_print_id == card_print_id,
        SourceCardMapping.is_active.is_(True),
        SourceCardMapping.superseded_at.is_(None),
    )
    if mapping is not None and mapping.id is not None:
        query = query.where(SourceCardMapping.id != mapping.id)
    if db.scalar(query.order_by(SourceCardMapping.id).limit(1)) is not None:
        raise ExactPrintApprovalError(
            "print_source_already_mapped",
            "A current active mapping already monitors this exact print on this source; preserve that mapping.",
        )

CURRENT_LISTING_UNIQUE_INDEX = "uq_mapping_current_canonical_listing_identity"


def current_identity_conflict(db: Session, exc: IntegrityError) -> ExactPrintApprovalError | None:
    """Translate only this index's race loss; discard the entire failed write."""
    diagnostic = getattr(exc.orig, "diag", None)
    if getattr(diagnostic, "constraint_name", None) != CURRENT_LISTING_UNIQUE_INDEX:
        return None
    db.rollback()
    return ExactPrintApprovalError(
        REFUSAL_LISTING_ALREADY_MAPPED,
        "This source listing already has a current mapping; reload before retrying.",
    )


@dataclass(frozen=True)
class CurrentMappingLookup:
    current: SourceCardMapping | None
    historical: tuple[SourceCardMapping, ...]


def lookup_current_mapping(db: Session, *, source: Source, url: str | None, for_update: bool = False) -> CurrentMappingLookup:
    identity = canonical_source_listing_identity(source.name, url)
    if identity is None:
        raise ExactPrintApprovalError(REFUSAL_SOURCE_URL_NOT_CANONICAL, "Supported canonical listing identity is required.")
    # Serialize supported writers for a readable refusal. PostgreSQL's partial
    # unique index is the final boundary if another writer races this lookup.
    if for_update:
        db.execute(select(Source.id).where(Source.id == source.id).with_for_update(key_share=True)).scalar_one()
    rows = db.scalars(select(SourceCardMapping).where(
        SourceCardMapping.source_id == source.id,
        SourceCardMapping.canonical_source_listing_identity == identity,
    ).order_by(SourceCardMapping.id)).all()
    current = [m for m in rows if m.superseded_at is None]
    if len(current) > 1:
        raise ExactPrintApprovalError(
            REFUSAL_MULTIPLE_MAPPINGS_FOR_LISTING,
            f"Listing {identity} has {len(current)} mappings currently claiming it; explicit repair required.",
            alternatives=[m.id for m in current],
        )
    return CurrentMappingLookup(current[0] if current else None, tuple(m for m in rows if m.superseded_at is not None))
