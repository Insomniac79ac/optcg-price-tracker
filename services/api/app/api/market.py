from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Card, CollectionItem, MarketSignalEvent
from app.models.market_signal_event import STATUSES as EVENT_STATUSES
from app.schemas import (
    MarketMoverOut,
    MarketSignalEventListOut,
    MarketSignalEventOut,
    MarketSignalEventsSummaryOut,
    MarketSignalEventUpdateIn,
    MarketSignalsResponseOut,
)
from app.services.market import get_market_movers
from app.services.market_signals import SIGNAL_TYPES, get_market_signals

router = APIRouter(prefix="/market", tags=["market"])

VALID_SOURCES = ("yuyutei", "snkrdunk")
VALID_PRICE_TYPES = ("sell", "buy", "floor", "sold")


@router.get("/movers", response_model=list[MarketMoverOut])
def market_movers(
    source: str | None = Query(default=None),
    price_type: str | None = Query(default=None),
    rarity: str | None = Query(default=None),
    variant: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if source is not None and source not in VALID_SOURCES:
        raise HTTPException(
            status_code=400, detail=f"Invalid source. Must be one of {list(VALID_SOURCES)}"
        )
    if price_type is not None and price_type not in VALID_PRICE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid price_type. Must be one of {list(VALID_PRICE_TYPES)}",
        )

    return get_market_movers(
        db,
        source=source,
        price_type=price_type,
        rarity=rarity,
        variant=variant,
        limit=limit,
        offset=offset,
    )


@router.get("/signals", response_model=MarketSignalsResponseOut)
def market_signals(
    signal_type: str | None = Query(default=None),
    set_code: str | None = Query(default=None),
    rarity: str | None = Query(default=None),
    source: str | None = Query(default=None),
    owned: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if signal_type is not None and signal_type not in SIGNAL_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid signal_type. Must be one of {list(SIGNAL_TYPES)}",
        )
    if source is not None and source not in VALID_SOURCES:
        raise HTTPException(
            status_code=400, detail=f"Invalid source. Must be one of {list(VALID_SOURCES)}"
        )

    return get_market_signals(
        db,
        signal_type=signal_type,
        set_code=set_code,
        rarity=rarity,
        source=source,
        owned=owned,
        limit=limit,
        offset=offset,
    )


def _owned_quantity_for_card(db: Session, card_id: int | None) -> int:
    if card_id is None:
        return 0
    total = db.scalar(
        select(func.coalesce(func.sum(CollectionItem.quantity), 0)).where(
            CollectionItem.card_id == card_id
        )
    )
    return int(total or 0)


def _event_to_out(
    event: MarketSignalEvent, card: Card | None, owned_quantity: int
) -> MarketSignalEventOut:
    return MarketSignalEventOut(
        id=event.id,
        signal_type=event.signal_type,
        status=event.status,
        severity=event.severity,
        suggested_action=event.suggested_action,
        card_id=event.card_id,
        card_code=card.card_code if card is not None else None,
        name_en=card.name_en if card is not None else None,
        name_jp=card.name_jp if card is not None else None,
        set_code=card.set_code if card is not None else None,
        rarity=card.rarity if card is not None else None,
        variant=card.variant if card is not None else None,
        language=card.language if card is not None else None,
        collection_item_id=event.collection_item_id,
        owned_quantity=owned_quantity,
        message=event.message,
        notes=event.notes,
        first_seen_at=event.first_seen_at,
        last_seen_at=event.last_seen_at,
        seen_count=event.seen_count,
        last_payload=event.last_payload_json,
        dismissed_at=event.dismissed_at,
        resolved_at=event.resolved_at,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def _get_event_or_404(db: Session, event_id: int) -> MarketSignalEvent:
    event = db.get(MarketSignalEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Market signal event not found")
    return event


def _build_event_out(db: Session, event: MarketSignalEvent) -> MarketSignalEventOut:
    card = db.get(Card, event.card_id) if event.card_id is not None else None
    owned_quantity = _owned_quantity_for_card(db, event.card_id)
    return _event_to_out(event, card, owned_quantity)


@router.get("/signal-events", response_model=MarketSignalEventListOut)
def list_market_signal_events(
    status: str | None = Query(default=None),
    signal_type: str | None = Query(default=None),
    suggested_action: str | None = Query(default=None),
    card_code: str | None = Query(default=None),
    owned: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if status is not None and status not in EVENT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of {list(EVENT_STATUSES)}",
        )

    filters = []
    if status is not None:
        filters.append(MarketSignalEvent.status == status)
    if signal_type is not None:
        filters.append(MarketSignalEvent.signal_type == signal_type)
    if suggested_action is not None:
        filters.append(MarketSignalEvent.suggested_action == suggested_action)

    query = select(MarketSignalEvent)
    if card_code is not None:
        query = query.join(Card, MarketSignalEvent.card_id == Card.id).where(
            Card.card_code == card_code, *filters
        )
    else:
        query = query.where(*filters)

    events = db.scalars(query.order_by(MarketSignalEvent.last_seen_at.desc())).all()

    card_ids = {e.card_id for e in events if e.card_id is not None}
    cards_by_id: dict[int, Card] = {}
    owned_quantities: dict[int, int] = {}
    if card_ids:
        cards_by_id = {
            c.id: c for c in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()
        }
        rows = db.execute(
            select(CollectionItem.card_id, func.sum(CollectionItem.quantity))
            .where(CollectionItem.card_id.in_(card_ids))
            .group_by(CollectionItem.card_id)
        ).all()
        owned_quantities = {card_id: int(qty or 0) for card_id, qty in rows}

    enriched = [
        (event, cards_by_id.get(event.card_id), owned_quantities.get(event.card_id, 0))
        for event in events
    ]

    if owned is not None:
        enriched = [(e, c, q) for (e, c, q) in enriched if (q > 0) == owned]

    by_signal_type: dict[str, int] = {}
    by_suggested_action: dict[str, int] = {}
    open_events = watching_events = dismissed_events = resolved_events = 0
    for event, _card, _qty in enriched:
        by_signal_type[event.signal_type] = by_signal_type.get(event.signal_type, 0) + 1
        if event.suggested_action:
            by_suggested_action[event.suggested_action] = (
                by_suggested_action.get(event.suggested_action, 0) + 1
            )
        if event.status == "open":
            open_events += 1
        elif event.status == "watching":
            watching_events += 1
        elif event.status == "dismissed":
            dismissed_events += 1
        elif event.status == "resolved":
            resolved_events += 1

    summary = MarketSignalEventsSummaryOut(
        total_events=len(enriched),
        open_events=open_events,
        watching_events=watching_events,
        dismissed_events=dismissed_events,
        resolved_events=resolved_events,
        by_signal_type=by_signal_type,
        by_suggested_action=by_suggested_action,
    )

    page = enriched[offset : offset + limit]
    return MarketSignalEventListOut(
        summary=summary,
        events=[_event_to_out(event, card, qty) for event, card, qty in page],
    )


@router.get("/signal-events/{event_id}", response_model=MarketSignalEventOut)
def get_market_signal_event(event_id: int, db: Session = Depends(get_db)):
    event = _get_event_or_404(db, event_id)
    return _build_event_out(db, event)


@router.patch("/signal-events/{event_id}", response_model=MarketSignalEventOut)
def update_market_signal_event(
    event_id: int, body: MarketSignalEventUpdateIn, db: Session = Depends(get_db)
):
    event = _get_event_or_404(db, event_id)

    updates = body.model_dump(exclude_unset=True)
    new_status = updates.get("status")
    if new_status is not None and new_status not in EVENT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of {list(EVENT_STATUSES)}",
        )

    now = datetime.now(timezone.utc)
    if "status" in updates and new_status is not None:
        event.status = new_status
        if new_status == "dismissed":
            event.dismissed_at = now
        elif new_status == "resolved":
            event.resolved_at = now
        elif new_status in ("open", "watching"):
            event.dismissed_at = None
            event.resolved_at = None
    if "notes" in updates:
        event.notes = updates["notes"]

    db.commit()
    db.refresh(event)
    return _build_event_out(db, event)


@router.post("/signal-events/{event_id}/dismiss", response_model=MarketSignalEventOut)
def dismiss_market_signal_event(event_id: int, db: Session = Depends(get_db)):
    event = _get_event_or_404(db, event_id)
    event.status = "dismissed"
    event.dismissed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(event)
    return _build_event_out(db, event)


@router.post("/signal-events/{event_id}/watch", response_model=MarketSignalEventOut)
def watch_market_signal_event(event_id: int, db: Session = Depends(get_db)):
    event = _get_event_or_404(db, event_id)
    event.status = "watching"
    event.dismissed_at = None
    db.commit()
    db.refresh(event)
    return _build_event_out(db, event)


@router.post("/signal-events/{event_id}/resolve", response_model=MarketSignalEventOut)
def resolve_market_signal_event(event_id: int, db: Session = Depends(get_db)):
    event = _get_event_or_404(db, event_id)
    event.status = "resolved"
    event.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(event)
    return _build_event_out(db, event)
