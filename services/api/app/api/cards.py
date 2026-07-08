from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Card, PriceObservation, Source
from app.schemas import CardOut, PriceObservationOut

router = APIRouter(prefix="/cards", tags=["cards"])


@router.get("", response_model=list[CardOut])
def list_cards(db: Session = Depends(get_db)):
    return db.scalars(select(Card)).all()


@router.get("/{card_id}", response_model=CardOut)
def get_card(card_id: int, db: Session = Depends(get_db)):
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@router.get("/{card_id}/prices", response_model=list[PriceObservationOut])
def get_card_prices(card_id: int, db: Session = Depends(get_db)):
    card = db.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")

    stmt = (
        select(PriceObservation, Source.name)
        .join(Source, Source.id == PriceObservation.source_id)
        .where(PriceObservation.card_id == card_id)
        .order_by(PriceObservation.observed_at.asc())
    )
    rows = db.execute(stmt).all()
    return [
        PriceObservationOut(
            id=observation.id,
            card_id=observation.card_id,
            source_id=observation.source_id,
            source=source_name,
            observed_at=observation.observed_at,
            price_type=observation.price_type,
            price_jpy=observation.price_jpy,
            condition_label=observation.condition_label,
            stock_status=observation.stock_status,
            listing_count=observation.listing_count,
            raw_snapshot_id=observation.raw_snapshot_id,
        )
        for observation, source_name in rows
    ]
