"""Public persisted Market Value endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.market_value_schemas import (
    MarketValueErrorOut,
    MarketValueOut,
    MarketValueReleasesOut,
    MarketValueWindow,
)
from app.services.market_value_read import (
    MarketValueUnavailableError,
    UnknownMarketValueReleaseError,
    get_market_value,
    list_market_value_releases,
)

router = APIRouter(prefix="/analytics/market-value", tags=["analytics"])
UNSEEDED = {
    503: {
        "model": MarketValueErrorOut,
        "description": "Persisted Market Value series has not been seeded.",
    }
}


@router.get(
    "",
    response_model=MarketValueOut,
    responses={
        **UNSEEDED,
        404: {
            "model": MarketValueErrorOut,
            "description": "Unknown ReleaseProduct ID.",
        },
    },
)
def get_market_value_endpoint(
    release_product_id: int | None = Query(
        default=None,
        ge=1,
        description="Authoritative ReleaseProduct ID; omitted selects Overall. Unknown IDs return 404. Never inferred from a card code.",
    ),
    window: MarketValueWindow = Query(
        default="7d",
        description="7d/30d require the complete daily span ending at persisted as_of. all returns stored history and movement only if its entire span is continuous.",
    ),
    db: Session = Depends(get_db),
):
    """Literal partial tracked JPY value and separate coverage-neutral movement.

    Public and read-only. as_of is the latest persisted UTC date, not a live
    valuation. Missing/failed daily steps yield null movement. Chart performance
    is computed with Decimal from persisted factors and rebased at the first
    valid visible point; it never bridges a break or replays price snapshots.
    """
    try:
        return get_market_value(
            db, release_product_id=release_product_id, window=window
        )
    except UnknownMarketValueReleaseError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MarketValueUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/releases", response_model=MarketValueReleasesOut, responses=UNSEEDED)
def get_market_value_releases_endpoint(db: Session = Depends(get_db)):
    """Persisted summaries for all active coded JP releases, including sparse ones.

    Active membership comes from persisted physical counts, not a fresh price
    calculation. Each row carries its own as_of date and partial coverage.
    Uses the same authoritative chronology as /releases: newest dated first,
    deterministic ties, undated last. Unavailable 7D/30D percentages are null.
    """
    try:
        return list_market_value_releases(db)
    except MarketValueUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
