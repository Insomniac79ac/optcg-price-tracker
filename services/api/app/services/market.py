"""Derives dashboard-ready market data from price_observations: the latest
observation per (source, price_type, condition_label) for each card, plus a
handful of cross-source/time signals.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Card, PriceObservation, Source
from app.schemas import MarketMoverOut, MarketPriceOut, MarketSignalsOut

# Priority order used to pick the single source+price_type series that backs
# the 24h/7d/30d change signals when a card has more than one available.
PRIMARY_SIGNAL_PAIRS = (("yuyutei", "sell"), ("snkrdunk", "floor"), ("yuyutei", "buy"))
CHANGE_WINDOWS = (("change_24h_pct", 1), ("change_7d_pct", 7), ("change_30d_pct", 30))


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _pct_change(latest_price: int, baseline_price: int) -> float | None:
    if not baseline_price:
        return None
    return round((latest_price - baseline_price) / baseline_price * 100, 2)


def _compute_signals(
    by_source_type: dict[tuple[str, str], list[PriceObservation]],
) -> MarketSignalsOut:
    def latest_of(src: str, pt: str) -> PriceObservation | None:
        series = by_source_type.get((src, pt))
        return series[-1] if series else None

    yuyutei_sell = latest_of("yuyutei", "sell")
    yuyutei_buy = latest_of("yuyutei", "buy")
    snkrdunk_floor = latest_of("snkrdunk", "floor")

    yuyutei_spread_jpy = (
        yuyutei_sell.price_jpy - yuyutei_buy.price_jpy
        if yuyutei_sell is not None and yuyutei_buy is not None
        else None
    )
    snkrdunk_floor_vs_yuyutei_buy_jpy = (
        snkrdunk_floor.price_jpy - yuyutei_buy.price_jpy
        if snkrdunk_floor is not None and yuyutei_buy is not None
        else None
    )

    changes: dict[str, float | None] = {name: None for name, _ in CHANGE_WINDOWS}

    primary_series = None
    for src, pt in PRIMARY_SIGNAL_PAIRS:
        series = by_source_type.get((src, pt))
        if series:
            primary_series = series
            break

    if primary_series:
        latest_obs = primary_series[-1]
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for field_name, days in CHANGE_WINDOWS:
            cutoff = now - timedelta(days=days)
            baseline = next(
                (
                    obs
                    for obs in reversed(primary_series[:-1])
                    if _naive(obs.observed_at) <= cutoff
                ),
                None,
            )
            if baseline is not None:
                changes[field_name] = _pct_change(latest_obs.price_jpy, baseline.price_jpy)

    return MarketSignalsOut(
        yuyutei_spread_jpy=yuyutei_spread_jpy,
        snkrdunk_floor_vs_yuyutei_buy_jpy=snkrdunk_floor_vs_yuyutei_buy_jpy,
        **changes,
    )


def get_market_movers(
    db: Session,
    source: str | None = None,
    price_type: str | None = None,
    rarity: str | None = None,
    variant: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[MarketMoverOut]:
    card_filters = []
    if rarity is not None:
        card_filters.append(Card.rarity == rarity)
    if variant is not None:
        card_filters.append(Card.variant == variant)

    cards = db.scalars(
        select(Card).where(*card_filters).order_by(Card.id).limit(limit).offset(offset)
    ).all()
    if not cards:
        return []

    card_ids = [c.id for c in cards]
    sources_by_id = {s.id: s.name for s in db.scalars(select(Source)).all()}

    observations = db.scalars(
        select(PriceObservation)
        .where(PriceObservation.card_id.in_(card_ids))
        .order_by(PriceObservation.observed_at)
    ).all()

    observations_by_card: dict[int, list[PriceObservation]] = defaultdict(list)
    for obs in observations:
        observations_by_card[obs.card_id].append(obs)

    results: list[MarketMoverOut] = []
    for card in cards:
        latest_by_group: dict[tuple[str, str, str | None], PriceObservation] = {}
        by_source_type: dict[tuple[str, str], list[PriceObservation]] = defaultdict(list)

        for obs in observations_by_card.get(card.id, []):
            source_name = sources_by_id.get(obs.source_id)
            if source_name is None:
                continue

            group_key = (source_name, obs.price_type, obs.condition_label)
            current = latest_by_group.get(group_key)
            if current is None or obs.observed_at > current.observed_at:
                latest_by_group[group_key] = obs

            by_source_type[(source_name, obs.price_type)].append(obs)

        latest_prices = [
            MarketPriceOut(
                source=group_key[0],
                price_type=group_key[1],
                price_jpy=obs.price_jpy,
                observed_at=obs.observed_at,
                condition_label=obs.condition_label,
                stock_status=obs.stock_status,
                listing_count=obs.listing_count,
            )
            for group_key, obs in latest_by_group.items()
            if (source is None or group_key[0] == source)
            and (price_type is None or group_key[1] == price_type)
        ]
        latest_prices.sort(key=lambda p: (p.source, p.price_type))

        results.append(
            MarketMoverOut(
                card_id=card.id,
                card_code=card.card_code,
                name_en=card.name_en,
                name_jp=card.name_jp,
                set_code=card.set_code,
                rarity=card.rarity,
                variant=card.variant,
                language=card.language,
                latest_prices=latest_prices,
                signals=_compute_signals(by_source_type),
            )
        )

    return results
