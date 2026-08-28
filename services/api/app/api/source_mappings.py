from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.core.pagination import pagination_response
from app.db import get_db
from app.models import Card, Source, SourceCardMapping
from app.models.source_card_mapping import REVIEW_STATUSES
from app.schemas import (
    SourceCardMappingListOut,
    SourceCardMappingOut,
    SourceCardMappingUpdateIn,
)
from app.api._mapping_approval import APPROVED, approval_http_error, guard_transition_to_approved
from app.services.cache import delete_cache_prefix
from app.services.exact_print_approval import ExactPrintApprovalError

router = APIRouter(
    prefix="/admin/source-mappings", tags=["admin"], dependencies=[Depends(require_admin_token)]
)

SUPPORTED_SOURCES = ("yuyutei", "snkrdunk")


def _to_out(
    mapping: SourceCardMapping, card: Card | None, source: Source | None
) -> SourceCardMappingOut:
    return SourceCardMappingOut(
        id=mapping.id,
        card_id=mapping.card_id,
        card_print_id=mapping.card_print_id,
        card_code=card.card_code if card is not None else None,
        name_en=card.name_en if card is not None else None,
        name_jp=card.name_jp if card is not None else None,
        source_name=source.name if source is not None else None,
        source_url=mapping.source_url,
        source_card_id=mapping.source_card_id,
        manual_verified=mapping.manual_verified,
        match_confidence=mapping.match_confidence,
        match_confidence_label=mapping.match_confidence_label,
        last_match_checked_at=mapping.last_match_checked_at,
        is_active=mapping.is_active,
        review_status=mapping.review_status,
        review_notes=mapping.review_notes,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
        last_verified_at=mapping.last_verified_at,
    )


def _get_mapping_or_404(db: Session, mapping_id: int) -> SourceCardMapping:
    mapping = db.get(SourceCardMapping, mapping_id)
    if mapping is None:
        raise HTTPException(status_code=404, detail="Source mapping not found")
    return mapping


def _to_out_with_lookups(db: Session, mapping: SourceCardMapping) -> SourceCardMappingOut:
    # A print-authoritative mapping has no legacy card, and db.get(Card, None)
    # raises rather than returning None. _to_out already renders card=None as
    # empty card_code/name fields.
    card = db.get(Card, mapping.card_id) if mapping.card_id is not None else None
    source = db.get(Source, mapping.source_id)
    return _to_out(mapping, card, source)


@router.get("", response_model=SourceCardMappingListOut)
def list_source_mappings(
    source: str | None = Query(default=None),
    review_status: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    card_code: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if source is not None and source not in SUPPORTED_SOURCES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source. Must be one of {list(SUPPORTED_SOURCES)}",
        )
    if review_status is not None and review_status not in REVIEW_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid review_status. Must be one of {list(REVIEW_STATUSES)}",
        )

    filters = []
    if review_status is not None:
        filters.append(SourceCardMapping.review_status == review_status)
    if is_active is not None:
        filters.append(SourceCardMapping.is_active == is_active)
    if source is not None:
        filters.append(Source.name == source)
    if card_code is not None:
        filters.append(Card.card_code == card_code)

    # OUTER join to `cards`: a print-authoritative mapping has no legacy card,
    # and an inner join would drop it from the admin list entirely - the
    # mapping would exist, price things, and be invisible here. Filtering by
    # card_code still works, since a NULL card matches no code.
    base = (
        select(SourceCardMapping)
        .outerjoin(Card, SourceCardMapping.card_id == Card.id)
        .join(Source, SourceCardMapping.source_id == Source.id)
        .where(*filters)
    )
    count_base = (
        select(func.count())
        .select_from(SourceCardMapping)
        .outerjoin(Card, SourceCardMapping.card_id == Card.id)
        .join(Source, SourceCardMapping.source_id == Source.id)
        .where(*filters)
    )

    total = db.scalar(count_base) or 0
    mappings = db.scalars(
        base.order_by(SourceCardMapping.id).limit(limit).offset(offset)
    ).all()

    card_ids = {m.card_id for m in mappings if m.card_id is not None}
    source_ids = {m.source_id for m in mappings}
    cards_by_id: dict[int, Card] = {}
    if card_ids:
        cards_by_id = {
            card.id: card for card in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()
        }
    sources_by_id: dict[int, Source] = {}
    if source_ids:
        sources_by_id = {
            src.id: src for src in db.scalars(select(Source).where(Source.id.in_(source_ids))).all()
        }

    items = [
        _to_out(
            m,
            cards_by_id.get(m.card_id) if m.card_id is not None else None,
            sources_by_id.get(m.source_id),
        )
        for m in mappings
    ]
    return SourceCardMappingListOut(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        pagination=pagination_response(items, total, limit, offset),
    )


@router.get("/{mapping_id}", response_model=SourceCardMappingOut)
def get_source_mapping(mapping_id: int, db: Session = Depends(get_db)):
    mapping = _get_mapping_or_404(db, mapping_id)
    return _to_out_with_lookups(db, mapping)


@router.patch("/{mapping_id}", response_model=SourceCardMappingOut)
def update_source_mapping(
    mapping_id: int, body: SourceCardMappingUpdateIn, db: Session = Depends(get_db)
):
    mapping = _get_mapping_or_404(db, mapping_id)

    updates = body.model_dump(exclude_unset=True)
    if "review_status" in updates and updates["review_status"] not in REVIEW_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid review_status. Must be one of {list(REVIEW_STATUSES)}",
        )

    # Checked BEFORE anything is written, so a refused PATCH leaves every
    # field - not just review_status - exactly as it was. This endpoint is a
    # transition into `approved` as surely as POST /approve is.
    if updates.get("review_status") == APPROVED:
        try:
            guard_transition_to_approved(db, mapping)
        except ExactPrintApprovalError as exc:
            raise approval_http_error(exc) from exc

    for field, value in updates.items():
        setattr(mapping, field, value)

    db.commit()
    db.refresh(mapping)
    delete_cache_prefix("admin/catalog_coverage")
    delete_cache_prefix("admin/price_source_health")
    return _to_out_with_lookups(db, mapping)


@router.post("/{mapping_id}/reject", response_model=SourceCardMappingOut)
def reject_source_mapping(mapping_id: int, db: Session = Depends(get_db)):
    mapping = _get_mapping_or_404(db, mapping_id)
    mapping.is_active = False
    mapping.review_status = "rejected"
    db.commit()
    db.refresh(mapping)
    delete_cache_prefix("admin/catalog_coverage")
    delete_cache_prefix("admin/price_source_health")
    return _to_out_with_lookups(db, mapping)


@router.post("/{mapping_id}/approve", response_model=SourceCardMappingOut)
def approve_source_mapping(mapping_id: int, db: Session = Depends(get_db)):
    mapping = _get_mapping_or_404(db, mapping_id)
    # Before any write: a row with no exact print cannot become approved, and
    # nothing here fills one in for it.
    try:
        guard_transition_to_approved(db, mapping)
    except ExactPrintApprovalError as exc:
        raise approval_http_error(exc) from exc
    mapping.is_active = True
    mapping.review_status = "approved"
    mapping.last_verified_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(mapping)
    delete_cache_prefix("admin/catalog_coverage")
    delete_cache_prefix("admin/price_source_health")
    return _to_out_with_lookups(db, mapping)
