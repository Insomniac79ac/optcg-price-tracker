"""Surfaces cards that may be worth a second look - buy opportunities, sell
opportunities, momentum, liquidity, ownership-relative moves, and data
quality gaps - derived purely from price_observations, source_card_mappings,
and collection_items.

Mirrors services/api/app/services/market_signals.py's detection formulas
exactly (the worker has no shared code with the api service - see
worker/models.py, which already duplicates the api's ORM models
table-for-table). This copy skips the Pydantic response schema, filtering,
and pagination the api's HTTP endpoint needs - the worker only ever wants
the full current signal set, to snapshot into market_signal_events.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from worker.models import Card, CollectionItem, PriceObservation, Source, SourceCardMapping

SIGNAL_TYPES = (
    "price_up_7d",
    "price_down_7d",
    "price_up_30d",
    "price_down_30d",
    "yuyutei_buy_sell_spread_compressed",
    "yuyutei_buy_sell_spread_wide",
    "snkrdunk_floor_below_yuyutei_sell",
    "snkrdunk_floor_above_yuyutei_sell",
    "owned_above_target_sell",
    "owned_below_cost_basis",
    "missing_recent_price",
    "stale_mapping_price",
)

# Same source+price_type priority used by the api's get_market_movers/
# get_market_signals - the single series that backs the price_up/down_7d/30d
# signals when a card has more than one available.
PRIMARY_SIGNAL_PAIRS = (("yuyutei", "sell"), ("snkrdunk", "floor"), ("yuyutei", "buy"))

PRICE_UP_7D_THRESHOLD_PCT = 10.0
PRICE_DOWN_7D_THRESHOLD_PCT = -10.0
PRICE_UP_30D_THRESHOLD_PCT = 20.0
PRICE_DOWN_30D_THRESHOLD_PCT = -20.0

YUYUTEI_SPREAD_COMPRESSED_THRESHOLD_PCT = 20.0
YUYUTEI_SPREAD_WIDE_THRESHOLD_PCT = 45.0

SNKRDUNK_VS_YUYUTEI_GAP_THRESHOLD_PCT = 10.0

STALE_HOURS_BY_SOURCE = {"yuyutei": 24, "snkrdunk": 7 * 24}
DEFAULT_STALE_HOURS = 24


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _pct(numerator: int, denominator: int) -> float | None:
    if not denominator:
        return None
    return round(numerator / denominator * 100, 2)


def _card_label(card: Card) -> str:
    return card.name_en or card.name_jp or card.card_code


@dataclass
class CandidateSignal:
    signal_type: str
    severity: str
    source: str | None
    card: Card
    owned_quantity: int
    yuyutei_sell: int | None
    yuyutei_buy: int | None
    snkrdunk_floor: int | None
    message: str
    suggested_action: str
    change_pct: float | None = None
    spread_pct: float | None = None
    gap_pct: float | None = None
    gap_jpy: int | None = None
    collection_item_id: int | None = None

    def to_payload_dict(self) -> dict:
        """Same JSON shape as the api's MarketSignalOut.model_dump(), so
        events created here look identical to ones created by the api's CLI
        regardless of which side snapshotted them."""
        return {
            "signal_type": self.signal_type,
            "severity": self.severity,
            "card_id": self.card.id,
            "card_code": self.card.card_code,
            "name_en": self.card.name_en,
            "name_jp": self.card.name_jp,
            "set_code": self.card.set_code,
            "rarity": self.card.rarity,
            "variant": self.card.variant,
            "language": self.card.language,
            "owned_quantity": self.owned_quantity,
            "collection_item_id": self.collection_item_id,
            "latest_prices": {
                "yuyutei_sell": self.yuyutei_sell,
                "yuyutei_buy": self.yuyutei_buy,
                "snkrdunk_floor": self.snkrdunk_floor,
            },
            "metrics": {
                "change_pct": self.change_pct,
                "spread_pct": self.spread_pct,
                "gap_pct": self.gap_pct,
                "gap_jpy": self.gap_jpy,
            },
            "message": self.message,
            "suggested_action": self.suggested_action,
        }


def _latest_price_trio(
    by_source_type: dict[tuple[str, str], list[PriceObservation]],
) -> dict[str, int | None]:
    def latest(src: str, pt: str) -> int | None:
        series = by_source_type.get((src, pt))
        return series[-1].price_jpy if series else None

    return {
        "yuyutei_sell": latest("yuyutei", "sell"),
        "yuyutei_buy": latest("yuyutei", "buy"),
        "snkrdunk_floor": latest("snkrdunk", "floor"),
    }


def _resolve_current_value(latest_trio: dict[str, int | None]) -> tuple[int, str] | None:
    """Prefers the SNKRDUNK market floor value, falling back to Yuyu-Tei
    sell. Returns None if neither is available."""
    if latest_trio["snkrdunk_floor"] is not None:
        return latest_trio["snkrdunk_floor"], "market_floor"
    if latest_trio["yuyutei_sell"] is not None:
        return latest_trio["yuyutei_sell"], "retail"
    return None


def _basis_label(basis: str) -> str:
    return "SNKRDUNK floor" if basis == "market_floor" else "Yuyu-Tei sell"


def _closest_observation(
    series: list[PriceObservation], target_dt: datetime
) -> PriceObservation | None:
    """Among all but the most recent observation in `series` (assumed sorted
    ascending by observed_at), returns the one whose observed_at is closest
    to target_dt. Returns None if there is no earlier observation at all -
    the price movement signal is skipped rather than fabricating a baseline."""
    candidates = series[:-1]
    if not candidates:
        return None
    return min(candidates, key=lambda obs: abs((_naive(obs.observed_at) - target_dt).total_seconds()))


def _price_movement_signals(
    card: Card,
    by_source_type: dict[tuple[str, str], list[PriceObservation]],
    latest_trio: dict[str, int | None],
    owned_quantity: int,
) -> list[CandidateSignal]:
    signals: list[CandidateSignal] = []

    primary = None
    for src, pt in PRIMARY_SIGNAL_PAIRS:
        series = by_source_type.get((src, pt))
        if series:
            primary = (src, pt, series)
            break
    if primary is None:
        return signals

    src, pt, series = primary
    latest_obs = series[-1]
    label = _card_label(card)

    windows = (
        (7, PRICE_UP_7D_THRESHOLD_PCT, "price_up_7d", PRICE_DOWN_7D_THRESHOLD_PCT, "price_down_7d"),
        (30, PRICE_UP_30D_THRESHOLD_PCT, "price_up_30d", PRICE_DOWN_30D_THRESHOLD_PCT, "price_down_30d"),
    )

    for days, up_threshold, up_type, down_threshold, down_type in windows:
        target_dt = _naive(latest_obs.observed_at) - timedelta(days=days)
        baseline = _closest_observation(series, target_dt)
        if baseline is None:
            continue

        pct = _pct(latest_obs.price_jpy - baseline.price_jpy, baseline.price_jpy)
        if pct is None:
            continue

        if pct >= up_threshold:
            signals.append(
                CandidateSignal(
                    signal_type=up_type,
                    severity="info",
                    source=src,
                    card=card,
                    owned_quantity=owned_quantity,
                    **latest_trio,
                    change_pct=pct,
                    message=(
                        f"{label} {src} {pt} price up {pct:.2f}% over the last {days} days."
                    ),
                    suggested_action="monitor_momentum",
                )
            )
        elif pct <= down_threshold:
            signals.append(
                CandidateSignal(
                    signal_type=down_type,
                    severity="info",
                    source=src,
                    card=card,
                    owned_quantity=owned_quantity,
                    **latest_trio,
                    change_pct=pct,
                    message=(
                        f"{label} {src} {pt} price down {abs(pct):.2f}% over the last {days} days."
                    ),
                    suggested_action="monitor_drop",
                )
            )

    return signals


def _yuyutei_spread_signals(
    card: Card, latest_trio: dict[str, int | None], owned_quantity: int
) -> list[CandidateSignal]:
    signals: list[CandidateSignal] = []
    sell = latest_trio["yuyutei_sell"]
    buy = latest_trio["yuyutei_buy"]
    if sell is None or buy is None:
        return signals

    spread_pct = _pct(sell - buy, sell)
    if spread_pct is None:
        return signals

    label = _card_label(card)

    if spread_pct <= YUYUTEI_SPREAD_COMPRESSED_THRESHOLD_PCT:
        signals.append(
            CandidateSignal(
                signal_type="yuyutei_buy_sell_spread_compressed",
                severity="info",
                source="yuyutei",
                card=card,
                owned_quantity=owned_quantity,
                **latest_trio,
                spread_pct=spread_pct,
                message=f"{label} Yuyu-Tei buy/sell spread is compressed at {spread_pct:.2f}%.",
                suggested_action="review_sell_opportunity",
            )
        )
    elif spread_pct >= YUYUTEI_SPREAD_WIDE_THRESHOLD_PCT:
        signals.append(
            CandidateSignal(
                signal_type="yuyutei_buy_sell_spread_wide",
                severity="info",
                source="yuyutei",
                card=card,
                owned_quantity=owned_quantity,
                **latest_trio,
                spread_pct=spread_pct,
                message=f"{label} Yuyu-Tei buy/sell spread is wide at {spread_pct:.2f}%.",
                suggested_action="none",
            )
        )

    return signals


def _snkrdunk_gap_signals(
    card: Card, latest_trio: dict[str, int | None], owned_quantity: int
) -> list[CandidateSignal]:
    signals: list[CandidateSignal] = []
    floor = latest_trio["snkrdunk_floor"]
    sell = latest_trio["yuyutei_sell"]
    if floor is None or sell is None:
        return signals

    gap_jpy = floor - sell
    gap_pct = _pct(gap_jpy, sell)
    if gap_pct is None:
        return signals

    label = _card_label(card)

    if gap_pct <= -SNKRDUNK_VS_YUYUTEI_GAP_THRESHOLD_PCT:
        signals.append(
            CandidateSignal(
                signal_type="snkrdunk_floor_below_yuyutei_sell",
                severity="info",
                source="snkrdunk",
                card=card,
                owned_quantity=owned_quantity,
                **latest_trio,
                gap_pct=gap_pct,
                gap_jpy=gap_jpy,
                message=f"{label} SNKRDUNK floor is {abs(gap_pct):.2f}% below Yuyu-Tei sell.",
                suggested_action="review_buy_opportunity",
            )
        )
    elif gap_pct >= SNKRDUNK_VS_YUYUTEI_GAP_THRESHOLD_PCT:
        signals.append(
            CandidateSignal(
                signal_type="snkrdunk_floor_above_yuyutei_sell",
                severity="info",
                source="snkrdunk",
                card=card,
                owned_quantity=owned_quantity,
                **latest_trio,
                gap_pct=gap_pct,
                gap_jpy=gap_jpy,
                message=f"{label} SNKRDUNK floor is {gap_pct:.2f}% above Yuyu-Tei sell.",
                suggested_action="review_sell_opportunity",
            )
        )

    return signals


def _owned_signals(
    card: Card,
    card_items: list[CollectionItem],
    latest_trio: dict[str, int | None],
    owned_quantity: int,
) -> list[CandidateSignal]:
    """One owned_above_target_sell / owned_below_cost_basis signal per
    qualifying collection_item (not per card) - each carries that item's
    collection_item_id, which market_signal_events needs for a stable
    per-item event identity distinct from other items of the same card."""
    signals: list[CandidateSignal] = []
    current = _resolve_current_value(latest_trio)
    if current is None:
        return signals
    value_jpy, basis = current
    basis_label = _basis_label(basis)
    label = _card_label(card)

    for item in card_items:
        if item.target_sell_price_jpy is not None and value_jpy >= item.target_sell_price_jpy:
            gap_jpy = value_jpy - item.target_sell_price_jpy
            gap_pct = _pct(gap_jpy, item.target_sell_price_jpy)
            signals.append(
                CandidateSignal(
                    signal_type="owned_above_target_sell",
                    severity="info",
                    source=basis,
                    card=card,
                    owned_quantity=owned_quantity,
                    collection_item_id=item.id,
                    **latest_trio,
                    gap_jpy=gap_jpy,
                    gap_pct=gap_pct,
                    message=(
                        f"Owned {label} reached its target sell price: "
                        f"{value_jpy} JPY via {basis_label} vs target "
                        f"{item.target_sell_price_jpy} JPY."
                    ),
                    suggested_action="review_sell_opportunity",
                )
            )

        if item.purchase_price_jpy is not None and value_jpy < item.purchase_price_jpy:
            gap_jpy = value_jpy - item.purchase_price_jpy
            gap_pct = _pct(gap_jpy, item.purchase_price_jpy)
            signals.append(
                CandidateSignal(
                    signal_type="owned_below_cost_basis",
                    severity="warning",
                    source=basis,
                    card=card,
                    owned_quantity=owned_quantity,
                    collection_item_id=item.id,
                    **latest_trio,
                    gap_jpy=gap_jpy,
                    gap_pct=gap_pct,
                    message=(
                        f"Owned {label} is below cost basis: "
                        f"{value_jpy} JPY via {basis_label} vs purchase "
                        f"{item.purchase_price_jpy} JPY ({gap_pct:.2f}%)."
                    ),
                    suggested_action="monitor_drop",
                )
            )

    return signals


def _data_quality_signals(
    card: Card,
    mapped_source_names: set[str],
    by_source_type: dict[tuple[str, str], list[PriceObservation]],
    latest_trio: dict[str, int | None],
    owned_quantity: int,
    now_naive: datetime,
) -> list[CandidateSignal]:
    """At most one missing_recent_price and one stale_mapping_price signal
    per card, aggregating every affected source into a single message - the
    market_signal_events dedupe key for these two types is card-level
    (signal_type:card:<id>:suggested_action), so a card with more than one
    simultaneously-missing/stale mapping (e.g. both yuyutei and snkrdunk)
    must not produce more than one row of each type, or upserting would hit
    the same dedupe_key twice in one snapshot."""
    signals: list[CandidateSignal] = []
    label = _card_label(card)

    missing_sources: list[str] = []
    stale_sources: list[tuple[str, PriceObservation]] = []

    for source_name in sorted(mapped_source_names):
        source_observations = [
            obs for (src, _pt), series in by_source_type.items() if src == source_name for obs in series
        ]

        if not source_observations:
            missing_sources.append(source_name)
            continue

        latest_obs = max(source_observations, key=lambda o: o.observed_at)
        stale_after = timedelta(hours=STALE_HOURS_BY_SOURCE.get(source_name, DEFAULT_STALE_HOURS))
        age = now_naive - _naive(latest_obs.observed_at)

        if age > stale_after:
            stale_sources.append((source_name, latest_obs))

    if missing_sources:
        signals.append(
            CandidateSignal(
                signal_type="missing_recent_price",
                severity="warning",
                source=missing_sources[0],
                card=card,
                owned_quantity=owned_quantity,
                **latest_trio,
                message=(
                    f"{label} has active mapping(s) with no price observations yet: "
                    f"{', '.join(missing_sources)}."
                ),
                suggested_action="review_mapping",
            )
        )

    if stale_sources:
        stale_text = ", ".join(
            f"{name} (last observed {obs.observed_at.isoformat()})" for name, obs in stale_sources
        )
        signals.append(
            CandidateSignal(
                signal_type="stale_mapping_price",
                severity="warning",
                source=stale_sources[0][0],
                card=card,
                owned_quantity=owned_quantity,
                **latest_trio,
                message=f"{label} price is stale for: {stale_text}.",
                suggested_action="update_prices",
            )
        )

    return signals


def compute_all_signals(db: Session) -> list[CandidateSignal]:
    """Every currently-applicable signal across the whole catalog - no
    filtering or pagination, since market_signal_events needs the complete
    current set to upsert/resolve against."""
    cards = db.scalars(select(Card).order_by(Card.id)).all()
    if not cards:
        return []

    card_ids = [c.id for c in cards]
    sources_by_id = {s.id: s.name for s in db.scalars(select(Source)).all()}

    mappings = db.scalars(
        select(SourceCardMapping).where(
            SourceCardMapping.card_id.in_(card_ids),
            SourceCardMapping.is_active.is_(True),
        )
    ).all()
    mapped_sources_by_card: dict[int, set[str]] = defaultdict(set)
    for mapping in mappings:
        source_name = sources_by_id.get(mapping.source_id)
        if source_name is not None:
            mapped_sources_by_card[mapping.card_id].add(source_name)

    observations = db.scalars(
        select(PriceObservation)
        .where(PriceObservation.card_id.in_(card_ids))
        .order_by(PriceObservation.observed_at)
    ).all()
    observations_by_card: dict[int, list[PriceObservation]] = defaultdict(list)
    for obs in observations:
        observations_by_card[obs.card_id].append(obs)

    items = db.scalars(select(CollectionItem).where(CollectionItem.card_id.in_(card_ids))).all()
    items_by_card: dict[int, list[CollectionItem]] = defaultdict(list)
    for item in items:
        items_by_card[item.card_id].append(item)

    now_naive = _naive(datetime.now(timezone.utc))

    all_signals: list[CandidateSignal] = []
    for card in cards:
        card_items = items_by_card.get(card.id, [])
        owned_quantity = sum(item.quantity for item in card_items)

        by_source_type: dict[tuple[str, str], list[PriceObservation]] = defaultdict(list)
        for obs in observations_by_card.get(card.id, []):
            source_name = sources_by_id.get(obs.source_id)
            if source_name is None:
                continue
            by_source_type[(source_name, obs.price_type)].append(obs)

        latest_trio = _latest_price_trio(by_source_type)

        all_signals.extend(_price_movement_signals(card, by_source_type, latest_trio, owned_quantity))
        all_signals.extend(_yuyutei_spread_signals(card, latest_trio, owned_quantity))
        all_signals.extend(_snkrdunk_gap_signals(card, latest_trio, owned_quantity))
        if card_items:
            all_signals.extend(_owned_signals(card, card_items, latest_trio, owned_quantity))
        all_signals.extend(
            _data_quality_signals(
                card,
                mapped_sources_by_card.get(card.id, set()),
                by_source_type,
                latest_trio,
                owned_quantity,
                now_naive,
            )
        )

    all_signals.sort(key=lambda s: (s.card.id, s.signal_type))
    return all_signals
