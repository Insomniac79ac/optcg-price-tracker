"""Database-backed current listing lookup; never chooses among conflicting rows."""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session
from opcg_source_identity import canonical_source_listing_identity

from app.models import Source, SourceCardMapping
from app.services.exact_print_approval import ExactPrintApprovalError, REFUSAL_MULTIPLE_MAPPINGS_FOR_LISTING, REFUSAL_SOURCE_URL_NOT_CANONICAL


@dataclass(frozen=True)
class CurrentMappingLookup:
    current: SourceCardMapping | None
    historical: tuple[SourceCardMapping, ...]


def lookup_current_mapping(db: Session, *, source: Source, url: str | None, for_update: bool = False) -> CurrentMappingLookup:
    identity = canonical_source_listing_identity(source.name, url)
    if identity is None:
        raise ExactPrintApprovalError(REFUSAL_SOURCE_URL_NOT_CANONICAL, "Supported canonical listing identity is required.")
    # Serialize supported writers until the follow-up unique-current index.
    # Read-only diagnostics use the reporting projection, not this writer gate.
    if for_update:
        db.execute(select(Source.id).where(Source.id == source.id).with_for_update()).scalar_one()
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
