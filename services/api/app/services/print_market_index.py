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

# What this module reads, and what counts as evidence -----------------------
#
# Two related but deliberately distinct sets, declared here once so no other
# module has to restate a source name or a price_type.
#
#   INDEX_INPUT_PRICE_TYPES     what the resolver READS
#   AUXILIARY_ONLY_PRICE_TYPES  the subset it can never compute an index from
#   INDEX_EVIDENCE_PRICE_TYPES  the difference - market-facing evidence
#
# Keeping them separate matters because the two questions are different.
# "Should the resolver fetch this observation?" is answered by the inputs:
# Yuyu-Tei dealer buy belongs there because the payload reports it as an
# auxiliary value, and dropping it would silently remove a number collectors
# already show. "Does this print have market-facing pricing evidence?" is
# answered by the evidence set, and a dealer-buy quote is not an answer to it:
# _resolve_yuyutei_buy hardcodes eligible=False with
# ineligible_reason="auxiliary_only", so no quantity of buy observations can
# ever produce an index value.
#
# app.snapshot_market_index.select_snapshottable_print_ids imports the
# evidence set to decide which prints are worth snapshotting. Deriving it by
# subtraction rather than writing a second literal is what keeps the two
# honest: a price_type added to the inputs is market-facing evidence unless it
# is also declared auxiliary-only, and a resolver that stops being auxiliary
# starts qualifying prints automatically.
YUYUTEI_SELL_PRICE_TYPE = "sell"
YUYUTEI_BUY_PRICE_TYPE = "buy"
SNKRDUNK_FLOOR_PRICE_TYPE = "floor"
SNKRDUNK_SOLD_PRICE_TYPE = "sold"

INDEX_INPUT_PRICE_TYPES: dict[str, tuple[str, ...]] = {
    YUYUTEI: (YUYUTEI_SELL_PRICE_TYPE, YUYUTEI_BUY_PRICE_TYPE),
    SNKRDUNK: (SNKRDUNK_FLOOR_PRICE_TYPE, SNKRDUNK_SOLD_PRICE_TYPE),
}

# Read and reported, never eligible - see _resolve_yuyutei_buy, whose
# ineligible_reason is the constant "auxiliary_only" rather than a condition.
AUXILIARY_ONLY_PRICE_TYPES: dict[str, tuple[str, ...]] = {
    YUYUTEI: (YUYUTEI_BUY_PRICE_TYPE,),
}

# Inputs minus auxiliary-only. A source whose every input is auxiliary drops
# out entirely rather than appearing with an empty tuple, so callers can
# iterate this without having to special-case a source that can contribute
# nothing.
INDEX_EVIDENCE_PRICE_TYPES: dict[str, tuple[str, ...]] = {
    source: evidence
    for source, price_types in INDEX_INPUT_PRICE_TYPES.items()
    if (
        evidence := tuple(
            price_type
            for price_type in price_types
            if price_type not in AUXILIARY_ONLY_PRICE_TYPES.get(source, ())
        )
    )
}


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
            PriceObservation.price_type == SNKRDUNK_SOLD_PRICE_TYPE,
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
        db, print_ids, source_names=(YUYUTEI,), price_types=INDEX_INPUT_PRICE_TYPES[YUYUTEI]
    )
    snkrdunk_floor_latest = get_latest_price_map_for_prints(
        db, print_ids, source_names=(SNKRDUNK,), price_types=(SNKRDUNK_FLOOR_PRICE_TYPE,)
    )
    snkrdunk_sold_by_print = _fetch_recent_snkrdunk_sold_for_prints(db, print_ids, now)

    results: dict[int, PrintMarketIndexOut] = {}
    for print_id in print_ids:
        print_yuyutei = yuyutei_latest.get(print_id, {})
        print_snkrdunk_floor = snkrdunk_floor_latest.get(print_id, {})

        sell_value = _resolve_yuyutei_sell(
            print_yuyutei.get((YUYUTEI, YUYUTEI_SELL_PRICE_TYPE)), now
        )
        buy_value = _resolve_yuyutei_buy(
            print_yuyutei.get((YUYUTEI, YUYUTEI_BUY_PRICE_TYPE))
        )
        snkrdunk_value = _resolve_snkrdunk(
            snkrdunk_sold_by_print.get(print_id, []),
            print_snkrdunk_floor.get((SNKRDUNK, SNKRDUNK_FLOOR_PRICE_TYPE)),
            now,
        )

        auxiliary_values = [buy_value] if buy_value is not None else []
        fields = _compute_index_fields([sell_value, snkrdunk_value], auxiliary_values, now)
        results[print_id] = PrintMarketIndexOut(card_print_id=print_id, **fields)

    return results


def get_market_index_for_print(db: Session, print_id: int) -> PrintMarketIndexOut:
    return get_market_index_for_prints(db, [print_id])[print_id]
