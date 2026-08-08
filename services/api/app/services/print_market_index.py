"""Market Index v1 applied independently per card_print - the print-scoped
counterpart to app.services.market_index. Reuses that module's source
resolvers and combination rule verbatim (see its docstring for the full
methodology, which this module does not change); the only difference here is
that every observation lookup is scoped by card_print_id via
app.services.print_pricing, so a print's index can never be computed from a
sibling print's observations even when both bridge through the same legacy
card_id.

This module never calls app.services.market_index.get_market_index_for_card
or get_market_index_for_cards - it only imports the pure per-observation
resolver functions and the shared _compute_index_fields combination helper.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PriceObservation, Source
from app.schemas import PrintMarketIndexOut
from app.services.market_index import (
    SNKRDUNK,
    SNKRDUNK_SOLD_WINDOW_DAYS,
    YUYUTEI,
    _compute_index_fields,
    _resolve_snkrdunk,
    _resolve_yuyutei_buy,
    _resolve_yuyutei_sell,
)
from app.services.print_pricing import get_latest_price_map_for_prints


def _fetch_recent_snkrdunk_sold_for_prints(
    db: Session, print_ids: list[int], now: datetime
) -> dict[int, list[PriceObservation]]:
    """Print-scoped counterpart to
    app.services.market_index._fetch_recent_snkrdunk_sold - same bounded
    30-day window query, filtered by card_print_id instead of card_id."""
    if not print_ids:
        return {}

    snkrdunk_source_id = db.scalar(select(Source.id).where(Source.name == SNKRDUNK))
    if snkrdunk_source_id is None:
        return {}

    cutoff = now - timedelta(days=SNKRDUNK_SOLD_WINDOW_DAYS)
    rows = db.scalars(
        select(PriceObservation)
        .where(
            PriceObservation.card_print_id.in_(print_ids),
            PriceObservation.source_id == snkrdunk_source_id,
            PriceObservation.price_type == "sold",
            PriceObservation.observed_at >= cutoff,
        )
        .order_by(PriceObservation.observed_at.desc(), PriceObservation.id.desc())
    ).all()

    by_print: dict[int, list[PriceObservation]] = defaultdict(list)
    for row in rows:
        by_print[row.card_print_id].append(row)
    return by_print


def get_market_index_for_prints(
    db: Session, print_ids: list[int]
) -> dict[int, PrintMarketIndexOut]:
    """The one entry point both GET /prints/{print_id}/market-index and the
    print catalogue call - issues a fixed number of queries regardless of
    len(print_ids), same batch-safe shape as
    app.services.market_index.get_market_index_for_cards."""
    if not print_ids:
        return {}

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    yuyutei_latest = get_latest_price_map_for_prints(
        db, print_ids, source_names=(YUYUTEI,), price_types=("sell", "buy")
    )
    snkrdunk_floor_latest = get_latest_price_map_for_prints(
        db, print_ids, source_names=(SNKRDUNK,), price_types=("floor",)
    )
    snkrdunk_sold_by_print = _fetch_recent_snkrdunk_sold_for_prints(db, print_ids, now)

    results: dict[int, PrintMarketIndexOut] = {}
    for print_id in print_ids:
        print_yuyutei = yuyutei_latest.get(print_id, {})
        print_snkrdunk_floor = snkrdunk_floor_latest.get(print_id, {})

        sell_value = _resolve_yuyutei_sell(print_yuyutei.get((YUYUTEI, "sell")), now)
        buy_value = _resolve_yuyutei_buy(print_yuyutei.get((YUYUTEI, "buy")))
        snkrdunk_value = _resolve_snkrdunk(
            snkrdunk_sold_by_print.get(print_id, []),
            print_snkrdunk_floor.get((SNKRDUNK, "floor")),
            now,
        )

        auxiliary_values = [buy_value] if buy_value is not None else []
        fields = _compute_index_fields([sell_value, snkrdunk_value], auxiliary_values, now)
        results[print_id] = PrintMarketIndexOut(card_print_id=print_id, **fields)

    return results


def get_market_index_for_print(db: Session, print_id: int) -> PrintMarketIndexOut:
    return get_market_index_for_prints(db, [print_id])[print_id]
