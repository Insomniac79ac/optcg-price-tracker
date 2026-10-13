from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import MarketMoverOut
from app.services.market import get_market_movers

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
