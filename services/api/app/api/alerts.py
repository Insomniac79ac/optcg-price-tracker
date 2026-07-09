from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.models import AlertEvent, AlertRule, Card, Source
from app.models.alert_event import EVENT_STATUSES, EVENT_TYPES
from app.schemas import AlertEventListOut, AlertEventOut, AlertRuleOut, AlertRuleUpdateIn

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_token)])


def _card_name(card: Card | None) -> str | None:
    if card is None:
        return None
    return card.name_en or card.name_jp


def _to_event_out(
    event: AlertEvent, card: Card | None, source: Source | None
) -> AlertEventOut:
    return AlertEventOut(
        id=event.id,
        created_at=event.created_at,
        event_type=event.event_type,
        card_id=event.card_id,
        card_code=card.card_code if card is not None else None,
        card_name=_card_name(card),
        source_name=source.name if source is not None else None,
        price_observation_id=event.price_observation_id,
        refresh_run_id=event.refresh_run_id,
        title=event.title,
        message=event.message,
        dedupe_key=event.dedupe_key,
        sent_at=event.sent_at,
        status=event.status,
        error_message=event.error_message,
    )


@router.get("/alert-events", response_model=AlertEventListOut)
def list_alert_events(
    status: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if status is not None and status not in EVENT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of {list(EVENT_STATUSES)}",
        )
    if event_type is not None and event_type not in EVENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event_type. Must be one of {list(EVENT_TYPES)}",
        )

    filters = []
    if status is not None:
        filters.append(AlertEvent.status == status)
    if event_type is not None:
        filters.append(AlertEvent.event_type == event_type)

    total = db.scalar(
        select(func.count()).select_from(AlertEvent).where(*filters)
    ) or 0

    events = db.scalars(
        select(AlertEvent)
        .where(*filters)
        .order_by(AlertEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    card_ids = {e.card_id for e in events if e.card_id is not None}
    source_ids = {e.source_id for e in events if e.source_id is not None}

    cards_by_id: dict[int, Card] = {}
    if card_ids:
        cards_by_id = {
            card.id: card for card in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()
        }

    sources_by_id: dict[int, Source] = {}
    if source_ids:
        sources_by_id = {
            source.id: source
            for source in db.scalars(select(Source).where(Source.id.in_(source_ids))).all()
        }

    items = [
        _to_event_out(event, cards_by_id.get(event.card_id), sources_by_id.get(event.source_id))
        for event in events
    ]
    return AlertEventListOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/alert-events/{event_id}", response_model=AlertEventOut)
def get_alert_event(event_id: int, db: Session = Depends(get_db)):
    event = db.get(AlertEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Alert event not found")

    card = db.get(Card, event.card_id) if event.card_id is not None else None
    source = db.get(Source, event.source_id) if event.source_id is not None else None
    return _to_event_out(event, card, source)


@router.get("/alert-rules", response_model=list[AlertRuleOut])
def list_alert_rules(db: Session = Depends(get_db)):
    rules = db.scalars(select(AlertRule).order_by(AlertRule.name)).all()
    return [AlertRuleOut.model_validate(rule) for rule in rules]


@router.patch("/alert-rules/{rule_id}", response_model=AlertRuleOut)
def update_alert_rule(rule_id: int, body: AlertRuleUpdateIn, db: Session = Depends(get_db)):
    rule = db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(rule, field, value)

    db.commit()
    db.refresh(rule)
    return AlertRuleOut.model_validate(rule)
