"""Values the collection from three market perspectives using the latest
price_observations per card/source/price_type:

- retail value: latest Yuyu-Tei sell price (shop price to buy from Yuyu-Tei)
- liquidation value: latest Yuyu-Tei buy price (what Yuyu-Tei pays to buy it from you)
- market floor value: latest SNKRDUNK floor price (cheapest peer listing)
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Card, CollectionItem, GradingSubmission
from app.schemas import (
    BestWorstPerformerOut,
    GradedAdjustedValuationOut,
    HighestValueItemOut,
    PortfolioValuationInsightsOut,
    PortfolioValuationItemOut,
    PortfolioValuationOut,
    PortfolioValuationSummaryOut,
    RetailLiquidationGapOut,
    SnkrdunkFloorSnapshotOut,
    ValuationDetailOut,
    ValuationFlagsOut,
    ValuationLatestPricesOut,
    ValuationMode,
    YuyuteiPriceSnapshotOut,
)
from app.services.collector import get_groups_for_collection_items, get_tags_for_collection_items
from app.services.grading import (
    build_grading_info,
    get_submissions_for_items,
    latest_submission,
    latest_updated_submission,
    received_grading_cost_jpy,
)
from app.services.latest_prices import get_latest_price_map

# (source name, price_type) pairs backing each valuation perspective.
YUYUTEI_SELL = ("yuyutei", "sell")
YUYUTEI_BUY = ("yuyutei", "buy")
SNKRDUNK_FLOOR = ("snkrdunk", "floor")


def _pct(pnl_jpy: int, cost_basis_jpy: int) -> float | None:
    if not cost_basis_jpy:
        return None
    return round(pnl_jpy / cost_basis_jpy * 100, 2)


def _empty_graded_adjusted() -> GradedAdjustedValuationOut:
    return GradedAdjustedValuationOut(
        value_jpy=None,
        basis=None,
        grading_submission_id=None,
        grading_company=None,
        final_grade=None,
        graded_value_jpy=None,
        raw_fallback_basis=None,
        pnl_jpy=None,
        pnl_pct=None,
    )


def _compute_graded_adjusted(
    submissions: list[GradingSubmission],
    cost_basis_jpy: int | None,
    market_floor_value_jpy: int | None,
    retail_value_jpy: int | None,
) -> tuple[GradedAdjustedValuationOut, int | None]:
    """Resolves the graded-adjusted value for one item: the graded_value_jpy
    of its most-recently-*updated* submission when that submission is
    'received' and has a graded value, otherwise the same SNKRDUNK-floor
    -then-Yuyu-Tei-sell fallback order used elsewhere for "current value".
    Also returns the graded-adjusted cost basis (purchase cost plus grading
    cost from 'received' submissions only) for the caller to aggregate."""
    latest = latest_updated_submission(submissions)
    grading_cost_jpy = received_grading_cost_jpy(submissions)

    if (
        latest is not None
        and latest.submission_status == "received"
        and latest.graded_value_jpy is not None
    ):
        value_jpy = latest.graded_value_jpy
        basis = "graded_value"
        grading_submission_id = latest.id
        grading_company = latest.grading_company
        final_grade = latest.final_grade
        graded_value_jpy = latest.graded_value_jpy
        raw_fallback_basis = None
    elif market_floor_value_jpy is not None:
        value_jpy = market_floor_value_jpy
        basis = raw_fallback_basis = "snkrdunk_floor"
        grading_submission_id = grading_company = final_grade = graded_value_jpy = None
    elif retail_value_jpy is not None:
        value_jpy = retail_value_jpy
        basis = raw_fallback_basis = "yuyutei_sell"
        grading_submission_id = grading_company = final_grade = graded_value_jpy = None
    else:
        value_jpy = basis = raw_fallback_basis = None
        grading_submission_id = grading_company = final_grade = graded_value_jpy = None

    adjusted_cost_basis_jpy = (
        cost_basis_jpy + grading_cost_jpy if cost_basis_jpy is not None else None
    )

    if value_jpy is not None and adjusted_cost_basis_jpy is not None:
        pnl_jpy = value_jpy - adjusted_cost_basis_jpy
        pnl_pct = _pct(pnl_jpy, adjusted_cost_basis_jpy)
    else:
        pnl_jpy = pnl_pct = None

    return (
        GradedAdjustedValuationOut(
            value_jpy=value_jpy,
            basis=basis,
            grading_submission_id=grading_submission_id,
            grading_company=grading_company,
            final_grade=final_grade,
            graded_value_jpy=graded_value_jpy,
            raw_fallback_basis=raw_fallback_basis,
            pnl_jpy=pnl_jpy,
            pnl_pct=pnl_pct,
        ),
        adjusted_cost_basis_jpy,
    )


def _empty_insights() -> PortfolioValuationInsightsOut:
    return PortfolioValuationInsightsOut(
        best_performing_item=None,
        worst_performing_item=None,
        largest_retail_liquidation_gap=None,
        highest_value_item=None,
    )


def _empty_summary(valuation_mode: ValuationMode) -> PortfolioValuationSummaryOut:
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
        insights=_empty_insights(),
        valuation_mode=valuation_mode,
        graded_adjusted_value_jpy=0,
        pnl_vs_graded_adjusted_jpy=0,
        pnl_vs_graded_adjusted_pct=0.0,
        items_using_graded_value=0,
        items_using_raw_fallback=0,
        items_missing_graded_adjusted_value=0,
    )


def _resolve_current_value(item: PortfolioValuationItemOut) -> tuple[int, str] | None:
    """Prefers the SNKRDUNK market floor value, falling back to the Yuyu-Tei
    retail (sell) value when the floor is missing. Returns None if neither is
    available for this item."""
    if item.valuations.market_floor_value_jpy is not None:
        return item.valuations.market_floor_value_jpy, "market_floor"
    if item.valuations.retail_value_jpy is not None:
        return item.valuations.retail_value_jpy, "retail"
    return None


def _compute_insights(items: list[PortfolioValuationItemOut]) -> PortfolioValuationInsightsOut:
    best_performing_item: BestWorstPerformerOut | None = None
    worst_performing_item: BestWorstPerformerOut | None = None
    largest_retail_liquidation_gap: RetailLiquidationGapOut | None = None
    highest_value_item: HighestValueItemOut | None = None

    best_pnl_jpy: int | None = None
    worst_pnl_jpy: int | None = None
    largest_gap_jpy: int | None = None
    highest_value_jpy: int | None = None

    for item in items:
        current = _resolve_current_value(item)

        if current is not None and item.cost_basis_jpy is not None:
            value_jpy, basis = current
            pnl_jpy = value_jpy - item.cost_basis_jpy
            pnl_pct = _pct(pnl_jpy, item.cost_basis_jpy)

            if best_pnl_jpy is None or pnl_jpy > best_pnl_jpy:
                best_pnl_jpy = pnl_jpy
                best_performing_item = BestWorstPerformerOut(
                    collection_item_id=item.collection_item_id,
                    card_code=item.card_code,
                    name_en=item.name_en,
                    name_jp=item.name_jp,
                    pnl_jpy=pnl_jpy,
                    pnl_pct=pnl_pct,
                    basis=basis,
                )

            if worst_pnl_jpy is None or pnl_jpy < worst_pnl_jpy:
                worst_pnl_jpy = pnl_jpy
                worst_performing_item = BestWorstPerformerOut(
                    collection_item_id=item.collection_item_id,
                    card_code=item.card_code,
                    name_en=item.name_en,
                    name_jp=item.name_jp,
                    pnl_jpy=pnl_jpy,
                    pnl_pct=pnl_pct,
                    basis=basis,
                )

        retail_value_jpy = item.valuations.retail_value_jpy
        liquidation_value_jpy = item.valuations.liquidation_value_jpy
        if retail_value_jpy is not None and liquidation_value_jpy is not None:
            gap_jpy = retail_value_jpy - liquidation_value_jpy
            gap_pct = _pct(gap_jpy, retail_value_jpy)

            if largest_gap_jpy is None or gap_jpy > largest_gap_jpy:
                largest_gap_jpy = gap_jpy
                largest_retail_liquidation_gap = RetailLiquidationGapOut(
                    collection_item_id=item.collection_item_id,
                    card_code=item.card_code,
                    name_en=item.name_en,
                    name_jp=item.name_jp,
                    gap_jpy=gap_jpy,
                    gap_pct=gap_pct,
                )

        if current is not None:
            value_jpy, basis = current
            if highest_value_jpy is None or value_jpy > highest_value_jpy:
                highest_value_jpy = value_jpy
                highest_value_item = HighestValueItemOut(
                    collection_item_id=item.collection_item_id,
                    card_code=item.card_code,
                    name_en=item.name_en,
                    name_jp=item.name_jp,
                    value_jpy=value_jpy,
                    basis=basis,
                )

    return PortfolioValuationInsightsOut(
        best_performing_item=best_performing_item,
        worst_performing_item=worst_performing_item,
        largest_retail_liquidation_gap=largest_retail_liquidation_gap,
        highest_value_item=highest_value_item,
    )


def get_portfolio_valuation(
    db: Session, user_id: int | None = None, valuation_mode: ValuationMode = "raw_market"
) -> PortfolioValuationOut:
    """user_id scopes the valuation to one person's collection (the
    interactive GET /collection/valuation endpoint always passes the
    calling user's id). Left as None, every collection item across every
    user is combined - this is intentional for the admin-only aggregate
    callers (snapshot_portfolio_valuation.py, market_report.py), which are
    not yet multi-tenant; see the "explicit scope boundary" note in the
    auth/deployment plan."""
    query = select(CollectionItem).order_by(CollectionItem.id)
    if user_id is not None:
        query = query.where(CollectionItem.user_id == user_id)
    items = db.scalars(query).all()
    if not items:
        return PortfolioValuationOut(summary=_empty_summary(valuation_mode), items=[])

    card_ids = {item.card_id for item in items}
    cards_by_id = {
        card.id: card for card in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()
    }

    item_ids = {item.id for item in items}
    tags_by_item = get_tags_for_collection_items(db, item_ids)
    groups_by_item = get_groups_for_collection_items(db, item_ids)
    submissions_by_item = get_submissions_for_items(db, item_ids)

    latest_by_card = get_latest_price_map(db, card_ids)

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
    graded_adjusted_value_total = 0
    graded_adjusted_cost_basis_total = 0
    items_using_graded_value = 0
    items_using_raw_fallback = 0
    items_missing_graded_adjusted_value = 0

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

        if valuation_mode == "graded_adjusted":
            graded_adjusted, graded_adjusted_cost_basis_jpy = _compute_graded_adjusted(
                submissions_by_item.get(item.id, []),
                cost_basis_jpy,
                market_floor_value_jpy,
                retail_value_jpy,
            )
            if graded_adjusted.value_jpy is not None:
                graded_adjusted_value_total += graded_adjusted.value_jpy
            else:
                items_missing_graded_adjusted_value += 1
            if graded_adjusted_cost_basis_jpy is not None:
                graded_adjusted_cost_basis_total += graded_adjusted_cost_basis_jpy
            if graded_adjusted.basis == "graded_value":
                items_using_graded_value += 1
            elif graded_adjusted.raw_fallback_basis is not None:
                items_using_raw_fallback += 1
        else:
            graded_adjusted = _empty_graded_adjusted()

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
                tags=tags_by_item.get(item.id, []),
                groups=groups_by_item.get(item.id, []),
                grading=build_grading_info(latest_submission(submissions_by_item, item.id)),
                graded_adjusted=graded_adjusted,
            )
        )

    # Portfolio-level P/L compares aggregate value against aggregate cost
    # basis; it does not require every item to have both figures individually
    # (that per-item nullability is already captured on each item's flags).
    summary_pnl_vs_retail_jpy = retail_value_total - total_cost_basis_jpy
    summary_pnl_vs_liquidation_jpy = liquidation_value_total - total_cost_basis_jpy
    summary_pnl_vs_market_floor_jpy = floor_value_total - total_cost_basis_jpy
    summary_pnl_vs_graded_adjusted_jpy = (
        graded_adjusted_value_total - graded_adjusted_cost_basis_total
    )

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
        insights=_compute_insights(result_items),
        valuation_mode=valuation_mode,
        graded_adjusted_value_jpy=graded_adjusted_value_total,
        pnl_vs_graded_adjusted_jpy=summary_pnl_vs_graded_adjusted_jpy,
        pnl_vs_graded_adjusted_pct=(
            _pct(summary_pnl_vs_graded_adjusted_jpy, graded_adjusted_cost_basis_total) or 0.0
        ),
        items_using_graded_value=items_using_graded_value,
        items_using_raw_fallback=items_using_raw_fallback,
        items_missing_graded_adjusted_value=items_missing_graded_adjusted_value,
    )

    return PortfolioValuationOut(summary=summary, items=result_items)
