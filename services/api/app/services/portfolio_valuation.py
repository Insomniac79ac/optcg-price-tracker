"""Values the collection from three market perspectives using the latest
price_observations per card/source/price_type:

- retail value: latest Yuyu-Tei sell price (shop price to buy from Yuyu-Tei)
- liquidation value: latest Yuyu-Tei buy price (what Yuyu-Tei pays to buy it from you)
- market floor value: latest SNKRDUNK floor price (cheapest peer listing)
"""

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Card, CollectionItem, PriceObservation, Source
from app.schemas import (
    PortfolioValuationItemOut,
    PortfolioValuationOut,
    PortfolioValuationSummaryOut,
    SnkrdunkFloorSnapshotOut,
    ValuationDetailOut,
    ValuationFlagsOut,
    ValuationLatestPricesOut,
    YuyuteiPriceSnapshotOut,
)

# (source name, price_type) pairs backing each valuation perspective.
YUYUTEI_SELL = ("yuyutei", "sell")
YUYUTEI_BUY = ("yuyutei", "buy")
SNKRDUNK_FLOOR = ("snkrdunk", "floor")


def _pct(pnl_jpy: int, cost_basis_jpy: int) -> float | None:
    if not cost_basis_jpy:
        return None
    return round(pnl_jpy / cost_basis_jpy * 100, 2)


def _empty_summary() -> PortfolioValuationSummaryOut:
    return PortfolioValuationSummaryOut(
        total_items=0,
        total_quantity=0,
        total_cost_basis_jpy=0,
        retail_value_jpy=0,
        liquidation_value_jpy=0,
        market_floor_value_jpy=0,
        pnl_vs_retail_jpy=0,
        pnl_vs_retail_pct=0.0,
        pnl_vs_liquidation_jpy=0,
        pnl_vs_liquidation_pct=0.0,
        pnl_vs_market_floor_jpy=0,
        pnl_vs_market_floor_pct=0.0,
        items_missing_yuyutei_sell=0,
        items_missing_yuyutei_buy=0,
        items_missing_snkrdunk_floor=0,
        items_missing_cost_basis=0,
        cards_above_target_sell=0,
    )


def get_portfolio_valuation(db: Session) -> PortfolioValuationOut:
    items = db.scalars(select(CollectionItem).order_by(CollectionItem.id)).all()
    if not items:
        return PortfolioValuationOut(summary=_empty_summary(), items=[])

    card_ids = {item.card_id for item in items}
    cards_by_id = {
        card.id: card for card in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()
    }
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

    result_items: list[PortfolioValuationItemOut] = []

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
        card = cards_by_id[item.card_id]
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

        retail_value_jpy = (
            yuyutei_sell_obs.price_jpy * quantity if yuyutei_sell_obs is not None else None
        )
        liquidation_value_jpy = (
            yuyutei_buy_obs.price_jpy * quantity if yuyutei_buy_obs is not None else None
        )
        market_floor_value_jpy = (
            snkrdunk_floor_obs.price_jpy * quantity if snkrdunk_floor_obs is not None else None
        )

        if yuyutei_sell_obs is None:
            items_missing_yuyutei_sell += 1
        else:
            retail_value_total += retail_value_jpy

        if yuyutei_buy_obs is None:
            items_missing_yuyutei_buy += 1
        else:
            liquidation_value_total += liquidation_value_jpy

        if snkrdunk_floor_obs is None:
            items_missing_snkrdunk_floor += 1
        else:
            floor_value_total += market_floor_value_jpy

        def _pnl(value_jpy: int | None) -> tuple[int | None, float | None]:
            if value_jpy is None or cost_basis_jpy is None:
                return None, None
            pnl_jpy = value_jpy - cost_basis_jpy
            return pnl_jpy, _pct(pnl_jpy, cost_basis_jpy)

        pnl_vs_retail_jpy, pnl_vs_retail_pct = _pnl(retail_value_jpy)
        pnl_vs_liquidation_jpy, pnl_vs_liquidation_pct = _pnl(liquidation_value_jpy)
        pnl_vs_market_floor_jpy, pnl_vs_market_floor_pct = _pnl(market_floor_value_jpy)

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

        result_items.append(
            PortfolioValuationItemOut(
                collection_item_id=item.id,
                card_id=card.id,
                card_code=card.card_code,
                name_en=card.name_en,
                name_jp=card.name_jp,
                set_code=card.set_code,
                rarity=card.rarity,
                variant=card.variant,
                language=card.language,
                quantity=quantity,
                condition_label=item.condition_label,
                purchase_price_jpy=item.purchase_price_jpy,
                cost_basis_jpy=cost_basis_jpy,
                target_sell_price_jpy=item.target_sell_price_jpy,
                latest_prices=ValuationLatestPricesOut(
                    yuyutei_sell=(
                        YuyuteiPriceSnapshotOut(
                            price_jpy=yuyutei_sell_obs.price_jpy,
                            observed_at=yuyutei_sell_obs.observed_at,
                        )
                        if yuyutei_sell_obs is not None
                        else None
                    ),
                    yuyutei_buy=(
                        YuyuteiPriceSnapshotOut(
                            price_jpy=yuyutei_buy_obs.price_jpy,
                            observed_at=yuyutei_buy_obs.observed_at,
                        )
                        if yuyutei_buy_obs is not None
                        else None
                    ),
                    snkrdunk_floor=(
                        SnkrdunkFloorSnapshotOut(
                            price_jpy=snkrdunk_floor_obs.price_jpy,
                            observed_at=snkrdunk_floor_obs.observed_at,
                            listing_count=snkrdunk_floor_obs.listing_count,
                            condition_label=snkrdunk_floor_obs.condition_label,
                        )
                        if snkrdunk_floor_obs is not None
                        else None
                    ),
                ),
                valuations=ValuationDetailOut(
                    retail_value_jpy=retail_value_jpy,
                    liquidation_value_jpy=liquidation_value_jpy,
                    market_floor_value_jpy=market_floor_value_jpy,
                    pnl_vs_retail_jpy=pnl_vs_retail_jpy,
                    pnl_vs_retail_pct=pnl_vs_retail_pct,
                    pnl_vs_liquidation_jpy=pnl_vs_liquidation_jpy,
                    pnl_vs_liquidation_pct=pnl_vs_liquidation_pct,
                    pnl_vs_market_floor_jpy=pnl_vs_market_floor_jpy,
                    pnl_vs_market_floor_pct=pnl_vs_market_floor_pct,
                ),
                flags=ValuationFlagsOut(
                    missing_yuyutei_sell=yuyutei_sell_obs is None,
                    missing_yuyutei_buy=yuyutei_buy_obs is None,
                    missing_snkrdunk_floor=snkrdunk_floor_obs is None,
                    missing_cost_basis=cost_basis_jpy is None,
                    above_target_sell=above_target_sell,
                ),
            )
        )

    # Portfolio-level P/L compares aggregate value against aggregate cost
    # basis; it does not require every item to have both figures individually
    # (that per-item nullability is already captured on each item's flags).
    summary_pnl_vs_retail_jpy = retail_value_total - total_cost_basis_jpy
    summary_pnl_vs_liquidation_jpy = liquidation_value_total - total_cost_basis_jpy
    summary_pnl_vs_market_floor_jpy = floor_value_total - total_cost_basis_jpy

    summary = PortfolioValuationSummaryOut(
        total_items=len(items),
        total_quantity=total_quantity,
        total_cost_basis_jpy=total_cost_basis_jpy,
        retail_value_jpy=retail_value_total,
        liquidation_value_jpy=liquidation_value_total,
        market_floor_value_jpy=floor_value_total,
        pnl_vs_retail_jpy=summary_pnl_vs_retail_jpy,
        pnl_vs_retail_pct=_pct(summary_pnl_vs_retail_jpy, total_cost_basis_jpy) or 0.0,
        pnl_vs_liquidation_jpy=summary_pnl_vs_liquidation_jpy,
        pnl_vs_liquidation_pct=(
            _pct(summary_pnl_vs_liquidation_jpy, total_cost_basis_jpy) or 0.0
        ),
        pnl_vs_market_floor_jpy=summary_pnl_vs_market_floor_jpy,
        pnl_vs_market_floor_pct=(
            _pct(summary_pnl_vs_market_floor_jpy, total_cost_basis_jpy) or 0.0
        ),
        items_missing_yuyutei_sell=items_missing_yuyutei_sell,
        items_missing_yuyutei_buy=items_missing_yuyutei_buy,
        items_missing_snkrdunk_floor=items_missing_snkrdunk_floor,
        items_missing_cost_basis=items_missing_cost_basis,
        cards_above_target_sell=cards_above_target_sell,
    )

    return PortfolioValuationOut(summary=summary, items=result_items)
