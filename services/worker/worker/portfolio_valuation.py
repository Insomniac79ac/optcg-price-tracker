"""Computes portfolio valuation summary figures and stores them as a
snapshot row. Mirrors the summary aggregation in
services/api/app/services/portfolio_valuation.py - the two must stay in
sync since they derive the same P/L figures from the same tables, but the
worker has no shared code with the api service (see worker/models.py, which
already duplicates the api's ORM models table-for-table), so this
duplicates the summary formula rather than importing it.
"""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from worker.models import CollectionItem, PortfolioValuationSnapshot, PriceObservation, Source

YUYUTEI_SELL = ("yuyutei", "sell")
YUYUTEI_BUY = ("yuyutei", "buy")
SNKRDUNK_FLOOR = ("snkrdunk", "floor")


def create_portfolio_valuation_snapshot(db: Session) -> PortfolioValuationSnapshot:
    items = db.scalars(select(CollectionItem)).all()

    if not items:
        snapshot = PortfolioValuationSnapshot(
            total_items=0,
            total_quantity=0,
            total_cost_basis_jpy=0,
            retail_value_jpy=0,
            liquidation_value_jpy=0,
            market_floor_value_jpy=0,
            pnl_vs_retail_jpy=0,
            pnl_vs_liquidation_jpy=0,
            pnl_vs_market_floor_jpy=0,
            items_missing_yuyutei_sell=0,
            items_missing_yuyutei_buy=0,
            items_missing_snkrdunk_floor=0,
            items_missing_cost_basis=0,
            cards_above_target_sell=0,
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)
        return snapshot

    card_ids = {item.card_id for item in items}
    sources_by_id = {s.id: s.name for s in db.scalars(select(Source)).all()}

    observations = db.scalars(
        select(PriceObservation)
        .where(PriceObservation.card_id.in_(card_ids))
        .order_by(PriceObservation.observed_at)
    ).all()

    latest_by_card: dict[int, dict[tuple[str, str], PriceObservation]] = defaultdict(dict)
    for obs in observations:
        source_name = sources_by_id.get(obs.source_id)
        if source_name is None:
            continue
        key = (source_name, obs.price_type)
        current = latest_by_card[obs.card_id].get(key)
        if current is None or obs.observed_at > current.observed_at:
            latest_by_card[obs.card_id][key] = obs

    total_cost_basis_jpy = 0
    total_quantity = 0
    retail_value_total = 0
    liquidation_value_total = 0
    floor_value_total = 0
    items_missing_yuyutei_sell = 0
    items_missing_yuyutei_buy = 0
    items_missing_snkrdunk_floor = 0
    items_missing_cost_basis = 0
    cards_above_target_sell = 0

    for item in items:
        card_latest = latest_by_card.get(item.card_id, {})

        yuyutei_sell_obs = card_latest.get(YUYUTEI_SELL)
        yuyutei_buy_obs = card_latest.get(YUYUTEI_BUY)
        snkrdunk_floor_obs = card_latest.get(SNKRDUNK_FLOOR)

        quantity = item.quantity
        total_quantity += quantity

        cost_basis_jpy = (
            item.purchase_price_jpy * quantity if item.purchase_price_jpy is not None else None
        )
        if cost_basis_jpy is None:
            items_missing_cost_basis += 1
        else:
            total_cost_basis_jpy += cost_basis_jpy

        if yuyutei_sell_obs is None:
            items_missing_yuyutei_sell += 1
        else:
            retail_value_total += yuyutei_sell_obs.price_jpy * quantity

        if yuyutei_buy_obs is None:
            items_missing_yuyutei_buy += 1
        else:
            liquidation_value_total += yuyutei_buy_obs.price_jpy * quantity

        if snkrdunk_floor_obs is None:
            items_missing_snkrdunk_floor += 1
        else:
            floor_value_total += snkrdunk_floor_obs.price_jpy * quantity

        # "Above target" is judged against the SNKRDUNK market floor (the
        # realistic peer-listing price a seller would compete against), not
        # the shop retail/liquidation prices.
        above_target_sell = (
            item.target_sell_price_jpy is not None
            and snkrdunk_floor_obs is not None
            and snkrdunk_floor_obs.price_jpy >= item.target_sell_price_jpy
        )
        if above_target_sell:
            cards_above_target_sell += 1

    snapshot = PortfolioValuationSnapshot(
        total_items=len(items),
        total_quantity=total_quantity,
        total_cost_basis_jpy=total_cost_basis_jpy,
        retail_value_jpy=retail_value_total,
        liquidation_value_jpy=liquidation_value_total,
        market_floor_value_jpy=floor_value_total,
        pnl_vs_retail_jpy=retail_value_total - total_cost_basis_jpy,
        pnl_vs_liquidation_jpy=liquidation_value_total - total_cost_basis_jpy,
        pnl_vs_market_floor_jpy=floor_value_total - total_cost_basis_jpy,
        items_missing_yuyutei_sell=items_missing_yuyutei_sell,
        items_missing_yuyutei_buy=items_missing_yuyutei_buy,
        items_missing_snkrdunk_floor=items_missing_snkrdunk_floor,
        items_missing_cost_basis=items_missing_cost_basis,
        cards_above_target_sell=cards_above_target_sell,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot
