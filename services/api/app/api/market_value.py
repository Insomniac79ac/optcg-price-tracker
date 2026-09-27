"""Public persisted Market Value endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.market_value_ranking_schemas import (
    MarketValueMostValuableOut,
    MarketValueMoverOrder,
    MarketValueMoversOut,
    MarketValueRankingErrorOut,
)
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
from app.services.market_value_rankings import (
    MarketValueIntegrityError,
    get_market_value_most_valuable,
    get_market_value_movers,
)

router = APIRouter(prefix="/analytics/market-value", tags=["analytics"])
UNSEEDED = {
    503: {
        "model": MarketValueErrorOut,
        "description": "Persisted Market Value series has not been seeded.",
    }
}
RANKING_ERRORS = {
    404: {"model": MarketValueErrorOut, "description": "Unknown ReleaseProduct ID."},
    503: {
        "model": MarketValueRankingErrorOut,
        "description": "Unseeded persisted scope, or fail-closed archive/persistence integrity mismatch. No rankings returned.",
    },
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


@router.get("/movers", response_model=MarketValueMoversOut, responses=RANKING_ERRORS)
def get_market_value_movers_endpoint(
    release_product_id: int | None = Query(
        default=None,
        ge=1,
        description="Exact ReleaseProduct scope; omitted means Overall, unknown ID returns 404.",
    ),
    order: MarketValueMoverOrder = Query(
        default="gainers",
        description="Gainers/losers rank exact-print percentage changes; impact ranks absolute JPY changes, retaining signed values. Ties use card_print_id ASC.",
    ),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """One latest published DAILY monetary Market Value step, never 7D/30D attribution.

    Public SELECT-only reconstruction from exactly two immutable snapshot
    dates. scope_as_of may be later than step_date; neither claims live prices.
    The full comparable panel must reconcile to persistence before truncation.
    No published step returns available=false with null basket movement.
    """
    try:
        return get_market_value_movers(
            db, release_product_id=release_product_id, order=order, limit=limit
        )
    except UnknownMarketValueReleaseError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MarketValueUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except MarketValueIntegrityError as exc:
        raise HTTPException(status_code=503, detail=exc.detail.model_dump()) from exc


@router.get(
    "/most-valuable",
    response_model=MarketValueMostValuableOut,
    responses=RANKING_ERRORS,
)
def get_market_value_most_valuable_endpoint(
    release_product_id: int | None = Query(
        default=None,
        ge=1,
        description="Exact ReleaseProduct scope; omitted means Overall. Membership must match the frozen persisted revision.",
    ),
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Exact physical prints decomposing the persisted headline's partial JPY basket.

    One persisted as_of date and one coherent UTC calculation instant. Positive
    snapshot values only, ordered value DESC then card_print_id ASC. Siblings
    remain separate. Full count and JPY sum reconcile before pagination; no live
    resolver, source fetch, canonical-family collapse or inferred missing price.
    """
    try:
        return get_market_value_most_valuable(
            db, release_product_id=release_product_id, limit=limit, offset=offset
        )
    except UnknownMarketValueReleaseError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MarketValueUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except MarketValueIntegrityError as exc:
        raise HTTPException(status_code=503, detail=exc.detail.model_dump()) from exc
