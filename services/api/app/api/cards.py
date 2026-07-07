from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Card, PriceObservation
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
        select(PriceObservation)
        .where(PriceObservation.card_id == card_id)
        .order_by(PriceObservation.observed_at.asc())
    )
    return db.scalars(stmt).all()
