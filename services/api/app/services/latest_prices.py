"""Shared "latest price observation" lookup, used by every service that
needs the current price(s) for a set of cards (portfolio valuation,
wishlist, market movers/signals, dashboard overview) instead of each one
loading and reducing the *entire* observation history for those cards in
Python.

Uses a ROW_NUMBER() OVER (PARTITION BY card_id, source_id, price_type ORDER
BY observed_at DESC) window function so the database itself picks the
latest row per series - only those rows are ever fetched, not every
historical observation. Portable across this app's two supported backends
(Postgres in production, SQLite in tests - both support window functions).

Callers that also need historical trend data (e.g. market movers'/market
signals' 7d/30d % change, which needs a baseline observation from the past,
not just the latest one) still query PriceObservation directly and are not
replaced by this module - see app.services.market/market_signals.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PriceObservation, Source


def get_latest_prices_for_cards(
    db: Session, card_ids: set[int] | list[int]
) -> dict[int, list[PriceObservation]]:
    """Returns, for each given card_id, the latest PriceObservation per
    distinct (source_id, price_type) series - one row per series, at its
    most recent observed_at. Cards with no observations are simply absent
    from the returned dict (never an empty list)."""
    card_ids = list(card_ids)
    if not card_ids:
        return {}

    row_number = (
        func.row_number()
        .over(
            partition_by=(
                PriceObservation.card_id,
                PriceObservation.source_id,
                PriceObservation.price_type,
            ),
            # id.desc() as a tiebreaker makes "the latest row" deterministic
            # even when two observations in the same series share an exact
            # observed_at (e.g. a batch mock/import run that stamps every row
            # with the same fetch timestamp) - otherwise ROW_NUMBER's order
            # among tied rows is unspecified and callers (e.g. Market Index)
            # could get a different "latest" observation from one call to
            # the next with no underlying data change.
            order_by=(PriceObservation.observed_at.desc(), PriceObservation.id.desc()),
        )
        .label("rn")
    )
    ranked = (
        select(PriceObservation.id, row_number)
        .where(PriceObservation.card_id.in_(card_ids))
        .subquery()
    )
    latest_ids = select(ranked.c.id).where(ranked.c.rn == 1)

    observations = db.scalars(
        select(PriceObservation).where(PriceObservation.id.in_(latest_ids))
    ).all()

    by_card: dict[int, list[PriceObservation]] = defaultdict(list)
    for obs in observations:
        by_card[obs.card_id].append(obs)
    return by_card


def get_latest_price_map(
    db: Session,
    card_ids: set[int] | list[int],
    source_names: tuple[str, ...] | None = None,
    price_types: tuple[str, ...] | None = None,
) -> dict[int, dict[tuple[str, str], PriceObservation]]:
    """Same lookup as get_latest_prices_for_cards, reshaped into the form
    every caller actually wants: card_id -> {(source_name, price_type):
    PriceObservation}. source_names/price_types optionally narrow the
    result to just the series a caller cares about (e.g. only
    ("yuyutei", "sell")/("yuyutei", "buy")/("snkrdunk", "floor")) - the
    underlying query already fetched only latest rows, so this is a plain
    in-memory filter, not an extra round trip."""
    by_card_raw = get_latest_prices_for_cards(db, card_ids)
    if not by_card_raw:
        return {}

    sources_by_id = {s.id: s.name for s in db.scalars(select(Source)).all()}

    result: dict[int, dict[tuple[str, str], PriceObservation]] = defaultdict(dict)
    for card_id, observations in by_card_raw.items():
        for obs in observations:
            source_name = sources_by_id.get(obs.source_id)
            if source_name is None:
                continue
            if source_names is not None and source_name not in source_names:
                continue
            if price_types is not None and obs.price_type not in price_types:
                continue
            result[card_id][(source_name, obs.price_type)] = obs
    return result
