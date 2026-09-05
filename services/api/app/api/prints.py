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
from app.models import CanonicalCard, CardPrint, PriceObservation
from app.schemas import (
    CardPrintOut,
    PrintCatalogueListOut,
    PrintMarketIndexOut,
    PrintPriceHistoryOut,
    PrintPriceObservationOut,
    PrintPriceSeriesTrendOut,
    PrintSeriesHistoryOut,
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
from app.services.print_series import (
    DEFAULT_WINDOW,
    WINDOW_DAYS,
    SeriesKeyError,
    get_print_series,
    parse_series_key,
)
from app.services.source_instruments import describe_instrument
from app.services.source_semantics import classify_observation

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


def _to_price_observation_out(
    print_id: int, obs: PriceObservation, source_name: str
) -> PrintPriceObservationOut:
    """One stored observation, returned verbatim plus its source semantics
    and its instrument name.

    The raw row is copied field for field - nothing is filtered, reordered,
    rounded or rewritten - and both annotations ride alongside it (see
    PrintPriceObservationOut). Every source-specific rule is asked of
    classify_observation, the same classifier market_index's resolvers use, so
    no threshold, source name or platform minimum is restated in this module.
    A future auxiliary price_type flows through the same call and picks up its
    configured semantics automatically, with no branch added here.

    `reference_type`/`evidence_type` come from describe_instrument for the
    same reason and with the same shape: the stored `price_type` -> public
    instrument mapping is resolved HERE, once, so no client has to decode a
    collector's private storage spelling to name what a row measures. No
    source name and no price_type literal appears in this module - an
    unconfigured pair yields None for both rather than a guess.
    """
    semantics = classify_observation(source_name, obs.price_type, obs.price_jpy)
    instrument = describe_instrument(source_name, obs.price_type)
    return PrintPriceObservationOut(
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
        constraint=semantics.constraint,
        eligible=semantics.eligible,
        ineligible_reason=semantics.ineligible_reason,
        reference_type=instrument.reference_type,
        evidence_type=instrument.evidence_type,
    )


@router.get("/{print_id}/prices", response_model=PrintPriceHistoryOut)
def get_print_prices(print_id: int, db: Session = Depends(get_db)):
    _get_print_or_404(db, print_id)

    rows = get_price_history_for_print(db, print_id)
    # Same rows, same order, one-to-one - get_price_history_for_print already
    # orders oldest-first and this endpoint deliberately applies no freshness
    # or eligibility filter of its own: history keeps every observation it
    # ever recorded, annotated rather than pruned.
    observations = [
        _to_price_observation_out(print_id, obs, source_name) for obs, source_name in rows
    ]
    series = [PrintPriceSeriesTrendOut(**trend) for trend in compute_print_price_series_trends(rows)]
    return PrintPriceHistoryOut(card_print_id=print_id, observations=observations, series=series)


@router.get("/{print_id}/series", response_model=PrintSeriesHistoryOut)
def get_print_series_history(
    print_id: int,
    series: list[str] | None = Query(
        default=None,
        description=(
            "Repeatable platform selector: 'market_index' or 'source:<name>'. "
            "Selection is platform-level - which instruments a platform contributes is "
            "the server's decision and is reported per segment, so no request depends "
            "on stored price_type vocabulary. Source names resolve against the sources "
            "table; there is no allowlist, so a source added later works with no code "
            "change. Omit to get Market Index plus every source that has observed "
            "this print."
        ),
    ),
    window: str = Query(
        default=DEFAULT_WINDOW,
        description="7d, 30d or all. 90d is not offered yet - see app.services.print_series.",
    ),
    db: Session = Depends(get_db),
):
    """One print's history, one series per platform the caller selected.

    Everything this endpoint does beyond parsing lives in
    app.services.print_series: daily normalisation, instrument segmentation,
    version breaks and coverage. Semantics come from the shipped
    classify_observation and Market Index history is read verbatim from
    market_index_snapshots - no index is ever recomputed here.

    A series key naming a source Atlas does not collect is NOT an error: it
    comes back as an explicitly unavailable series (see PrintSeriesOut). Only
    an unparseable key or an unsupported window is a 400, because those are
    client mistakes rather than statements about the data.
    """
    _get_print_or_404(db, print_id)

    if window not in WINDOW_DAYS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid window. Must be one of {sorted(WINDOW_DAYS)}",
        )
    try:
        requests = [parse_series_key(key) for key in series] if series else None
    except SeriesKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return PrintSeriesHistoryOut(
        **get_print_series(db, print_id, series=requests, window=window)
    )
