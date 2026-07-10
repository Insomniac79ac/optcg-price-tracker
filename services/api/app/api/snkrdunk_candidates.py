from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.models import Card, Source, SourceCardMapping
from app.models.snkrdunk_candidate import MATCH_STATUSES, SnkrdunkCandidate
from app.schemas import (
    CardOut,
    SnkrdunkCandidateListOut,
    SnkrdunkCandidateMatchIn,
    SnkrdunkCandidateOut,
)

router = APIRouter(
    prefix="/snkrdunk", tags=["snkrdunk"], dependencies=[Depends(require_admin_token)]
)


def _to_out(candidate: SnkrdunkCandidate, card: Card | None) -> SnkrdunkCandidateOut:
    return SnkrdunkCandidateOut(
        id=candidate.id,
        discovery_run_id=candidate.discovery_run_id,
        source_url=candidate.source_url,
        title=candidate.title,
        price_jpy=candidate.price_jpy,
        image_url=candidate.image_url,
        listing_count=candidate.listing_count,
        condition_label=candidate.condition_label,
        normalized_title=candidate.normalized_title,
        detected_card_code=candidate.detected_card_code,
        detected_set_code=candidate.detected_set_code,
        detected_rarity=candidate.detected_rarity,
        detected_variant=candidate.detected_variant,
        match_status=candidate.match_status,
        matched_card_id=candidate.matched_card_id,
        match_confidence=candidate.match_confidence,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
        matched_card=CardOut.model_validate(card) if card is not None else None,
    )


def _get_candidate_or_404(db: Session, candidate_id: int) -> SnkrdunkCandidate:
    candidate = db.get(SnkrdunkCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


@router.get("/candidates", response_model=SnkrdunkCandidateListOut)
def list_candidates(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if status is not None and status not in MATCH_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of {list(MATCH_STATUSES)}",
        )

    filters = []
    if status is not None:
        filters.append(SnkrdunkCandidate.match_status == status)

    total = db.scalar(
        select(func.count()).select_from(SnkrdunkCandidate).where(*filters)
    ) or 0

    candidates = db.scalars(
        select(SnkrdunkCandidate)
        .where(*filters)
        .order_by(SnkrdunkCandidate.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    card_ids = {c.matched_card_id for c in candidates if c.matched_card_id is not None}
    cards_by_id: dict[int, Card] = {}
    if card_ids:
        cards_by_id = {
            card.id: card
            for card in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()
        }

    items = [_to_out(c, cards_by_id.get(c.matched_card_id)) for c in candidates]
    return SnkrdunkCandidateListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/candidates/{candidate_id}", response_model=SnkrdunkCandidateOut)
def get_candidate(candidate_id: int, db: Session = Depends(get_db)):
    candidate = _get_candidate_or_404(db, candidate_id)
    card = db.get(Card, candidate.matched_card_id) if candidate.matched_card_id else None
    return _to_out(candidate, card)


@router.post("/candidates/{candidate_id}/match", response_model=SnkrdunkCandidateOut)
def match_candidate(
    candidate_id: int, body: SnkrdunkCandidateMatchIn, db: Session = Depends(get_db)
):
    candidate = _get_candidate_or_404(db, candidate_id)

    card = db.get(Card, body.card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")

    source = db.query(Source).filter_by(name="snkrdunk").one_or_none()
    if source is None:
        raise HTTPException(status_code=500, detail="snkrdunk source is not configured")

    candidate.match_status = "auto_matched"
    candidate.matched_card_id = card.id
    candidate.match_confidence = 1.0

    mapping = (
        db.query(SourceCardMapping)
        .filter_by(card_id=card.id, source_id=source.id)
        .one_or_none()
    )
    if mapping is None:
        mapping = SourceCardMapping(
            card_id=card.id,
            source_id=source.id,
            source_card_id=candidate.detected_card_code or candidate.source_url,
        )
        db.add(mapping)

    mapping.source_card_id = candidate.detected_card_code or candidate.source_url
    mapping.source_url = candidate.source_url
    mapping.match_confidence = 1.0
    mapping.manual_verified = body.manual_verified
    mapping.is_active = True
    mapping.review_status = "approved" if body.manual_verified else "needs_review"

    db.commit()
    db.refresh(candidate)
    return _to_out(candidate, card)


@router.post("/candidates/{candidate_id}/reject", response_model=SnkrdunkCandidateOut)
def reject_candidate(candidate_id: int, db: Session = Depends(get_db)):
    candidate = _get_candidate_or_404(db, candidate_id)
    candidate.match_status = "rejected"
    db.commit()
    db.refresh(candidate)
    card = db.get(Card, candidate.matched_card_id) if candidate.matched_card_id else None
    return _to_out(candidate, card)
