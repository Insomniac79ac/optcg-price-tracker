from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import MarketMoverOut, MarketSignalsResponseOut
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
