"""Print-scoped "latest price observation" + price-history/trend lookups -
the card_print_id-keyed counterpart to app.services.latest_prices, built so
two card_prints that bridge through the same legacy card_id (e.g. a base
print and a parallel print of the same canonical card) can never see each
other's observations.

Every query here filters on price_observations.card_print_id. That column is
only ever set together with source_card_mapping_id (see the paired-lineage
check constraint on PriceObservation), so a legacy, lineage-less observation
(card_print_id IS NULL) can never match any requested print id and can never
become print-market evidence - no separate "has lineage" check is needed
beyond the card_print_id filter itself.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PriceObservation, Source

# Mirrors app.services.market's CHANGE_WINDOWS - same 24h/7d/30d convention,
# applied per print instead of per legacy card.
CHANGE_WINDOWS = (("change_24h_pct", 1), ("change_7d_pct", 7), ("change_30d_pct", 30))


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _pct_change(latest_price: int, baseline_price: int) -> float | None:
    if not baseline_price:
        return None
    return round((latest_price - baseline_price) / baseline_price * 100, 2)


def get_latest_prices_for_prints(
    db: Session, print_ids: set[int] | list[int]
) -> dict[int, list[PriceObservation]]:
    """Print-scoped counterpart to
    app.services.latest_prices.get_latest_prices_for_cards - identical
    window-function shape, partitioned by card_print_id instead of card_id.
    Prints with no observations are simply absent from the returned dict."""
    print_ids = list(print_ids)
    if not print_ids:
        return {}

    row_number = (
        func.row_number()
        .over(
            partition_by=(
                PriceObservation.card_print_id,
                PriceObservation.source_id,
                PriceObservation.price_type,
            ),
            order_by=(PriceObservation.observed_at.desc(), PriceObservation.id.desc()),
        )
        .label("rn")
    )
    ranked = (
        select(PriceObservation.id, row_number)
        .where(PriceObservation.card_print_id.in_(print_ids))
        .subquery()
    )
    latest_ids = select(ranked.c.id).where(ranked.c.rn == 1)

    observations = db.scalars(
        select(PriceObservation).where(PriceObservation.id.in_(latest_ids))
    ).all()

    by_print: dict[int, list[PriceObservation]] = defaultdict(list)
    for obs in observations:
        by_print[obs.card_print_id].append(obs)
    return by_print


def get_latest_price_map_for_prints(
    db: Session,
    print_ids: set[int] | list[int],
    source_names: tuple[str, ...] | None = None,
    price_types: tuple[str, ...] | None = None,
) -> dict[int, dict[tuple[str, str], PriceObservation]]:
    """Print-scoped counterpart to
    app.services.latest_prices.get_latest_price_map - reshaped into
    print_id -> {(source_name, price_type): PriceObservation}."""
    by_print_raw = get_latest_prices_for_prints(db, print_ids)
    if not by_print_raw:
        return {}

    sources_by_id = {s.id: s.name for s in db.scalars(select(Source)).all()}

    result: dict[int, dict[tuple[str, str], PriceObservation]] = defaultdict(dict)
    for print_id, observations in by_print_raw.items():
        for obs in observations:
            source_name = sources_by_id.get(obs.source_id)
            if source_name is None:
                continue
            if source_names is not None and source_name not in source_names:
                continue
            if price_types is not None and obs.price_type not in price_types:
                continue
            result[print_id][(source_name, obs.price_type)] = obs
    return result


def get_price_history_for_print(
    db: Session, print_id: int
) -> list[tuple[PriceObservation, str]]:
    """Every accepted price_observations row for exactly this print, oldest
    first, paired with its source name - never a sibling print's
    observations, even when both bridge through the same legacy card_id."""
    stmt = (
        select(PriceObservation, Source.name)
        .join(Source, Source.id == PriceObservation.source_id)
        .where(PriceObservation.card_print_id == print_id)
        .order_by(PriceObservation.observed_at.asc(), PriceObservation.id.asc())
    )
    return list(db.execute(stmt).all())


def compute_print_price_series_trends(
    rows: list[tuple[PriceObservation, str]], now: datetime | None = None
) -> list[dict]:
    """One trend summary per (source, price_type) series actually present in
    `rows`. A series with a single observation is `sufficient_history=False`
    and every change_*_pct stays null - this module never fabricates a
    24h/7d/30d change from less than two real observations, and never
    borrows a baseline from another series or another print."""
    now = _naive(now) if now is not None else datetime.now(timezone.utc).replace(tzinfo=None)

    by_series: dict[tuple[str, str], list[PriceObservation]] = defaultdict(list)
    for obs, source_name in rows:
        by_series[(source_name, obs.price_type)].append(obs)

    trends: list[dict] = []
    for (source_name, price_type), series in by_series.items():
        series = sorted(series, key=lambda o: (o.observed_at, o.id))
        latest = series[-1]
        sufficient = len(series) >= 2
        changes: dict[str, float | None] = {name: None for name, _ in CHANGE_WINDOWS}
        if sufficient:
            for field_name, days in CHANGE_WINDOWS:
                cutoff = now - timedelta(days=days)
                baseline = next(
                    (obs for obs in reversed(series[:-1]) if _naive(obs.observed_at) <= cutoff),
                    None,
                )
                if baseline is not None:
                    changes[field_name] = _pct_change(latest.price_jpy, baseline.price_jpy)
        trends.append(
            {
                "source": source_name,
                "price_type": price_type,
                "latest_price_jpy": latest.price_jpy,
                "latest_observed_at": latest.observed_at,
                "latest_stock_status": latest.stock_status,
                "sufficient_history": sufficient,
                **changes,
            }
        )

    trends.sort(key=lambda t: (t["source"], t["price_type"]))
    return trends
