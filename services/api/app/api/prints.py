"""Print-centric public read endpoints - the card_print-keyed counterpart to
app.api.cards (see that module's legacy, card_id-keyed endpoints, which
remain unchanged for backward compatibility with existing frontend routes).

Every endpoint here resolves market data through app.services.print_pricing/
print_market_index, which filter strictly by price_observations.card_print_id
- never legacy card_id - so two prints bridging through the same legacy card
(e.g. OP01-013 Sanji's base and parallel prints) can never contaminate each
other's prices, Market Index, or history.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.pagination import pagination_response
from app.db import get_db
from app.models import CanonicalCard, CardPrint
from app.schemas import (
    CardPrintOut,
    PrintCatalogueListOut,
    PrintMarketIndexOut,
    PrintPriceHistoryOut,
    PrintPriceObservationOut,
    PrintPriceSeriesTrendOut,
)
from app.services.display_image import get_display_image_for_print
from app.services.print_catalogue import (
    SORT_KEYS,
    get_print_catalogue_facets,
    get_siblings,
    list_print_catalogue,
    to_print_out,
)
from app.services.print_market_index import get_market_index_for_print
from app.services.print_pricing import (
    compute_print_price_series_trends,
    get_price_history_for_print,
)

router = APIRouter(prefix="/prints", tags=["prints"])


def _get_print_or_404(db: Session, print_id: int) -> CardPrint:
    print_row = db.get(CardPrint, print_id)
    if print_row is None or not print_row.is_active:
        raise HTTPException(status_code=404, detail="Print not found")
    return print_row


def _get_canonical_or_404(db: Session, canonical_card_id: int) -> CanonicalCard:
    canonical = db.get(CanonicalCard, canonical_card_id)
    if canonical is None:
        raise HTTPException(status_code=404, detail="Canonical card not found")
    return canonical


@router.get("", response_model=PrintCatalogueListOut)
def get_print_catalogue(
    q: str | None = Query(default=None, min_length=1, max_length=128),
    treatment: str | None = Query(default=None),
    language: str | None = Query(default=None),
    rarity: str | None = Query(default=None),
    verification_status: str | None = Query(default=None),
    sort: str = Query(default="card_code"),
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """The public, paginated print catalogue - each item is one collectible
    print (never a legacy card row), with its own independently-computed
    Market Index. Sibling prints of the same canonical card (e.g. Sanji base
    and Sanji parallel) each appear as their own separate entry."""
    if sort not in SORT_KEYS:
        raise HTTPException(
            status_code=400, detail=f"Invalid sort. Must be one of {list(SORT_KEYS)}"
        )

    items, total = list_print_catalogue(
        db,
        q=q,
        treatment=treatment,
        language=language,
        rarity=rarity,
        verification_status=verification_status,
        sort=sort,  # type: ignore[arg-type]
        limit=limit,
        offset=offset,
    )
    return PrintCatalogueListOut(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        pagination=pagination_response(items, total, limit, offset),
        facets=get_print_catalogue_facets(db),
    )


@router.get("/{print_id}", response_model=CardPrintOut)
def get_print(print_id: int, db: Session = Depends(get_db)):
    print_row = _get_print_or_404(db, print_id)
    canonical = _get_canonical_or_404(db, print_row.canonical_card_id)
    market_index = get_market_index_for_print(db, print_id)
    siblings = get_siblings(db, print_row.canonical_card_id, print_id)
    display_image = get_display_image_for_print(db, print_row)
    return to_print_out(print_row, canonical, market_index, siblings, display_image)


@router.get("/{print_id}/market-index", response_model=PrintMarketIndexOut)
def get_print_market_index(print_id: int, db: Session = Depends(get_db)):
    _get_print_or_404(db, print_id)
    return get_market_index_for_print(db, print_id)


@router.get("/{print_id}/prices", response_model=PrintPriceHistoryOut)
def get_print_prices(print_id: int, db: Session = Depends(get_db)):
    _get_print_or_404(db, print_id)

    rows = get_price_history_for_print(db, print_id)
    observations = [
        PrintPriceObservationOut(
            id=obs.id,
            card_print_id=print_id,
            source_id=obs.source_id,
            source=source_name,
            observed_at=obs.observed_at,
            price_type=obs.price_type,
            price_jpy=obs.price_jpy,
            condition_label=obs.condition_label,
            listing_count=obs.listing_count,
            raw_snapshot_id=obs.raw_snapshot_id,
        )
        for obs, source_name in rows
    ]
    series = [PrintPriceSeriesTrendOut(**trend) for trend in compute_print_price_series_trends(rows)]
    return PrintPriceHistoryOut(card_print_id=print_id, observations=observations, series=series)
