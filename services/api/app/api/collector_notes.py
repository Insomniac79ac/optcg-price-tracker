from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.core.pagination import pagination_response
from app.models import CollectorNote, User
from app.models.collector_note import NOTE_TYPES
from app.db import get_db
from app.schemas import (
    CollectorNoteCreateIn,
    CollectorNoteListOut,
    CollectorNoteOut,
    CollectorNoteUpdateIn,
)
from app.services.activity_timeline import record_activity_event

router = APIRouter(prefix="/collector/notes", tags=["collector-notes"])


def _get_note_or_404(db: Session, note_id: int) -> CollectorNote:
    note = db.get(CollectorNote, note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.get("", response_model=CollectorNoteListOut)
def list_notes(
    note_type: str | None = None,
    card_id: int | None = None,
    collection_item_id: int | None = None,
    wishlist_item_id: int | None = None,
    grading_submission_id: int | None = None,
    market_signal_event_id: int | None = None,
    market_report_id: int | None = None,
    pinned: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(require_current_user),
):
    filters = []
    if note_type is not None:
        filters.append(CollectorNote.note_type == note_type)
    if card_id is not None:
        filters.append(CollectorNote.card_id == card_id)
    if collection_item_id is not None:
        filters.append(CollectorNote.collection_item_id == collection_item_id)
    if wishlist_item_id is not None:
        filters.append(CollectorNote.wishlist_item_id == wishlist_item_id)
    if grading_submission_id is not None:
        filters.append(CollectorNote.grading_submission_id == grading_submission_id)
    if market_signal_event_id is not None:
        filters.append(CollectorNote.market_signal_event_id == market_signal_event_id)
    if market_report_id is not None:
        filters.append(CollectorNote.market_report_id == market_report_id)
    if pinned is not None:
        filters.append(CollectorNote.pinned == pinned)

    total = db.scalar(select(func.count()).select_from(CollectorNote).where(*filters)) or 0
    items = db.scalars(
        select(CollectorNote)
        .where(*filters)
        .order_by(
            CollectorNote.pinned.desc(),
            CollectorNote.created_at.desc(),
            CollectorNote.id.desc(),
        )
        .limit(limit)
        .offset(offset)
    ).all()

    return CollectorNoteListOut(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        pagination=pagination_response(items, total, limit, offset),
    )


@router.post("", response_model=CollectorNoteOut, status_code=201)
def create_note(
    body: CollectorNoteCreateIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_current_user),
):
    if body.note_type not in NOTE_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid note_type: {body.note_type}")

    note = CollectorNote(
        note_type=body.note_type,
        card_id=body.card_id,
        collection_item_id=body.collection_item_id,
        wishlist_item_id=body.wishlist_item_id,
        grading_submission_id=body.grading_submission_id,
        market_signal_event_id=body.market_signal_event_id,
        market_report_id=body.market_report_id,
        title=body.title,
        body=body.body,
        pinned=body.pinned,
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    record_activity_event(
        db,
        event_type="note_created",
        event_source="note",
        title=note.title or "Note added",
        message=note.body[:280],
        card_id=note.card_id,
        collection_item_id=note.collection_item_id,
        wishlist_item_id=note.wishlist_item_id,
        grading_submission_id=note.grading_submission_id,
        market_signal_event_id=note.market_signal_event_id,
    )

    return note


@router.patch("/{note_id}", response_model=CollectorNoteOut)
def update_note(
    note_id: int,
    body: CollectorNoteUpdateIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_current_user),
):
    note = _get_note_or_404(db, note_id)
    updates = body.model_dump(exclude_unset=True)

    if "note_type" in updates and updates["note_type"] not in NOTE_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid note_type: {updates['note_type']}")

    for field, value in updates.items():
        setattr(note, field, value)

    db.commit()
    db.refresh(note)
    return note


@router.delete("/{note_id}", status_code=204)
def delete_note(
    note_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_current_user),
):
    note = _get_note_or_404(db, note_id)
    db.delete(note)
    db.commit()
    return None
