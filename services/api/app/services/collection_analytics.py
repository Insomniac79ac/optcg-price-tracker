"""Collection analytics: composition, cost basis, valuation exposure, grading
exposure, wishlist exposure, and concentration risk for one user's
collection - see GET /analytics/collection.

Builds entirely on top of app.services.portfolio_valuation.get_portfolio_valuation
rather than re-deriving per-item market/graded-adjusted values - this module
only aggregates/groups/ranks the already-computed per-item values, it never
recomputes how a value_jpy itself is derived (no valuation formula lives
here). get_portfolio_valuation is always called with valuation_mode=
"graded_adjusted" internally regardless of the caller's requested mode,
because that's the one call that populates both the raw-market
(market_floor_value_jpy) AND graded-adjusted (graded_adjusted.value_jpy)
figures on every item - valuation_mode only selects which of those two
already-computed figures this module treats as "the" value for pnl/
breakdowns/concentration.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CollectionItem, WishlistItem
from app.schemas import (
    CollectionAnalyticsBreakdownItemOut,
    CollectionAnalyticsBreakdownsOut,
    CollectionAnalyticsConcentrationOut,
    CollectionAnalyticsCostBasisOut,
    CollectionAnalyticsHighestCostBasisItemOut,
    CollectionAnalyticsOut,
    CollectionAnalyticsSummaryOut,
    CollectionAnalyticsTopCardOut,
    CollectionAnalyticsValuationQualityOut,
    PortfolioValuationItemOut,
    ValuationMode,
)
from app.services.grading import WAITING_RETURN_STATUSES
from app.services.portfolio_valuation import get_portfolio_valuation

# How many entries each ranked list (concentration's top cards, cost basis's
# highest items) carries - not spec'd beyond "top 5"/"top 10" for
# concentration; 10 is reused for the cost-basis ranking too for consistency.
TOP_CARDS_LIMIT = 5
TOP_10_LIMIT = 10
HIGHEST_COST_BASIS_LIMIT = 10


def _pct(numerator: int, denominator: int) -> float | None:
    """Same rounding/None-on-zero-denominator convention as the private
    `_pct` in app.services.portfolio_valuation - duplicated here (not
    imported) because it's a generic percent-rounding utility, not a
    valuation formula."""
    if not denominator:
        return None
    return round(numerator / denominator * 100, 2)


def _selected_value_jpy(item: PortfolioValuationItemOut, valuation_mode: ValuationMode) -> int | None:
    if valuation_mode == "graded_adjusted":
        return item.graded_adjusted.value_jpy
    return item.valuations.market_floor_value_jpy


def _weight_pct(value_jpy: int, total_selected_value_jpy: int) -> float:
    if not total_selected_value_jpy:
        return 0.0
    return round(value_jpy / total_selected_value_jpy * 100, 2)


def _build_breakdown(
    entries: Iterable[tuple[str, str, PortfolioValuationItemOut]],
    selected_values: dict[int, int | None],
    total_selected_value_jpy: int,
) -> list[CollectionAnalyticsBreakdownItemOut]:
    """entries is (key, label, item) tuples - an item can appear under more
    than one key (tags/groups), in which case its cost basis/value counts
    toward every bucket it belongs to, same as tag/group filtering
    elsewhere in this app."""
    buckets: dict[str, dict] = {}
    for key, label, item in entries:
        bucket = buckets.setdefault(
            key, {"label": label, "item_count": 0, "quantity": 0, "cost_basis_jpy": 0, "value_jpy": 0}
        )
        bucket["item_count"] += 1
        bucket["quantity"] += item.quantity
        bucket["cost_basis_jpy"] += item.cost_basis_jpy or 0
        bucket["value_jpy"] += selected_values[item.collection_item_id] or 0

    results = []
    for key, bucket in buckets.items():
        pnl_jpy = bucket["value_jpy"] - bucket["cost_basis_jpy"]
        results.append(
            CollectionAnalyticsBreakdownItemOut(
                key=key,
                label=bucket["label"],
                item_count=bucket["item_count"],
                quantity=bucket["quantity"],
                cost_basis_jpy=bucket["cost_basis_jpy"],
                value_jpy=bucket["value_jpy"],
                pnl_jpy=pnl_jpy,
                pnl_pct=_pct(pnl_jpy, bucket["cost_basis_jpy"]),
                portfolio_weight_pct=_weight_pct(bucket["value_jpy"], total_selected_value_jpy),
            )
        )
    results.sort(key=lambda r: (-r.value_jpy, r.key))
    return results


def get_collection_analytics(
    db: Session,
    *,
    user_id: int,
    valuation_mode: ValuationMode = "raw_market",
    include_sold: bool = False,
) -> CollectionAnalyticsOut:
    status_by_item_id = dict(
        db.execute(
            select(CollectionItem.id, CollectionItem.status).where(CollectionItem.user_id == user_id)
        ).all()
    )

    # Always computed in graded_adjusted mode - see module docstring - so
    # both market_floor_value_jpy and graded_adjusted.value_jpy are
    # populated on every item regardless of the caller's valuation_mode.
    portfolio = get_portfolio_valuation(db, user_id=user_id, valuation_mode="graded_adjusted")

    items = [
        item
        for item in portfolio.items
        if include_sold or status_by_item_id.get(item.collection_item_id) != "sold"
    ]

    selected_values = {item.collection_item_id: _selected_value_jpy(item, valuation_mode) for item in items}

    total_cost_basis_jpy = sum(item.cost_basis_jpy or 0 for item in items)
    raw_market_floor_value_jpy = sum(item.valuations.market_floor_value_jpy or 0 for item in items)
    graded_adjusted_value_jpy = sum(item.graded_adjusted.value_jpy or 0 for item in items)
    total_selected_value_jpy = (
        raw_market_floor_value_jpy if valuation_mode == "raw_market" else graded_adjusted_value_jpy
    )

    unrealized_pnl_jpy = total_selected_value_jpy - total_cost_basis_jpy
    unrealized_pnl_pct = _pct(unrealized_pnl_jpy, total_cost_basis_jpy) or 0.0

    items_missing_cost_basis = sum(1 for item in items if item.cost_basis_jpy is None)
    items_missing_market_price = sum(
        1 for item in items if selected_values[item.collection_item_id] is None
    )

    owned_unique_cards = len({item.card_id for item in items})

    wishlist_unique_cards = (
        db.scalar(
            select(func.count(func.distinct(WishlistItem.card_id))).where(
                WishlistItem.user_id == user_id, WishlistItem.status != "removed"
            )
        )
        or 0
    )

    grading_active_count = sum(
        1
        for item in items
        if item.grading.has_grading_submission and item.grading.latest_status in WAITING_RETURN_STATUSES
    )

    summary = CollectionAnalyticsSummaryOut(
        total_items=len(items),
        total_quantity=sum(item.quantity for item in items),
        total_cost_basis_jpy=total_cost_basis_jpy,
        raw_market_floor_value_jpy=raw_market_floor_value_jpy,
        graded_adjusted_value_jpy=graded_adjusted_value_jpy,
        unrealized_pnl_jpy=unrealized_pnl_jpy,
        unrealized_pnl_pct=unrealized_pnl_pct,
        items_missing_cost_basis=items_missing_cost_basis,
        items_missing_market_price=items_missing_market_price,
        owned_unique_cards=owned_unique_cards,
        wishlist_unique_cards=wishlist_unique_cards,
        grading_active_count=grading_active_count,
    )

    by_set = _build_breakdown(
        ((item.set_code, item.set_code, item) for item in items), selected_values, total_selected_value_jpy
    )
    by_rarity = _build_breakdown(
        ((item.rarity, item.rarity, item) for item in items), selected_values, total_selected_value_jpy
    )
    by_variant = _build_breakdown(
        ((item.variant or "none", item.variant or "None", item) for item in items),
        selected_values,
        total_selected_value_jpy,
    )
    by_language = _build_breakdown(
        ((item.language, item.language, item) for item in items), selected_values, total_selected_value_jpy
    )
    by_status = _build_breakdown(
        (
            (
                status_by_item_id.get(item.collection_item_id, "unknown"),
                status_by_item_id.get(item.collection_item_id, "unknown"),
                item,
            )
            for item in items
        ),
        selected_values,
        total_selected_value_jpy,
    )
    by_tag = _build_breakdown(
        ((tag.slug, tag.name, item) for item in items for tag in item.tags),
        selected_values,
        total_selected_value_jpy,
    )
    by_group = _build_breakdown(
        ((group.slug, group.name, item) for item in items for group in item.groups),
        selected_values,
        total_selected_value_jpy,
    )
    by_grading_status = _build_breakdown(
        (
            (item.grading.latest_status or "none", item.grading.latest_status or "None", item)
            for item in items
        ),
        selected_values,
        total_selected_value_jpy,
    )

    breakdowns = CollectionAnalyticsBreakdownsOut(
        by_set=by_set,
        by_rarity=by_rarity,
        by_variant=by_variant,
        by_language=by_language,
        by_status=by_status,
        by_tag=by_tag,
        by_group=by_group,
        by_grading_status=by_grading_status,
    )

    sorted_by_value = sorted(
        items, key=lambda item: (-(selected_values[item.collection_item_id] or 0), item.collection_item_id)
    )
    top_5 = sorted_by_value[:TOP_CARDS_LIMIT]
    top_10 = sorted_by_value[:TOP_10_LIMIT]

    top_5_cards_by_value = [
        CollectionAnalyticsTopCardOut(
            collection_item_id=item.collection_item_id,
            card_id=item.card_id,
            card_code=item.card_code,
            name_en=item.name_en,
            name_jp=item.name_jp,
            quantity=item.quantity,
            value_jpy=selected_values[item.collection_item_id] or 0,
            portfolio_weight_pct=_weight_pct(
                selected_values[item.collection_item_id] or 0, total_selected_value_jpy
            ),
        )
        for item in top_5
    ]
    top_10_cards_value_pct = _weight_pct(
        sum(selected_values[item.collection_item_id] or 0 for item in top_10), total_selected_value_jpy
    )
    largest_single_card_value_pct = (
        top_5_cards_by_value[0].portfolio_weight_pct if top_5_cards_by_value else 0.0
    )
    largest_set_exposure = max(by_set, key=lambda b: b.portfolio_weight_pct, default=None)
    largest_rarity_exposure = max(by_rarity, key=lambda b: b.portfolio_weight_pct, default=None)

    concentration = CollectionAnalyticsConcentrationOut(
        top_5_cards_by_value=top_5_cards_by_value,
        top_10_cards_value_pct=top_10_cards_value_pct,
        largest_single_card_value_pct=largest_single_card_value_pct,
        largest_set_exposure=largest_set_exposure,
        largest_rarity_exposure=largest_rarity_exposure,
    )

    cost_basis_values = [item.cost_basis_jpy for item in items if item.cost_basis_jpy is not None]
    items_with_cost_basis = len(cost_basis_values)
    items_without_cost_basis = len(items) - items_with_cost_basis
    average_cost_basis_jpy = (
        round(sum(cost_basis_values) / items_with_cost_basis) if items_with_cost_basis else 0
    )
    median_cost_basis_jpy = (
        round(statistics.median(cost_basis_values)) if items_with_cost_basis else 0
    )
    highest_cost_basis_sorted = sorted(
        (item for item in items if item.cost_basis_jpy is not None),
        key=lambda item: (-item.cost_basis_jpy, item.collection_item_id),
    )[:HIGHEST_COST_BASIS_LIMIT]
    highest_cost_basis_items = [
        CollectionAnalyticsHighestCostBasisItemOut(
            collection_item_id=item.collection_item_id,
            card_id=item.card_id,
            card_code=item.card_code,
            name_en=item.name_en,
            name_jp=item.name_jp,
            cost_basis_jpy=item.cost_basis_jpy,
        )
        for item in highest_cost_basis_sorted
    ]

    cost_basis = CollectionAnalyticsCostBasisOut(
        items_with_cost_basis=items_with_cost_basis,
        items_without_cost_basis=items_without_cost_basis,
        average_cost_basis_jpy=average_cost_basis_jpy,
        median_cost_basis_jpy=median_cost_basis_jpy,
        highest_cost_basis_items=highest_cost_basis_items,
    )

    items_with_yuyutei_sell = sum(1 for item in items if not item.flags.missing_yuyutei_sell)
    items_with_yuyutei_buy = sum(1 for item in items if not item.flags.missing_yuyutei_buy)
    items_with_snkrdunk_floor = sum(1 for item in items if not item.flags.missing_snkrdunk_floor)
    items_using_graded_value = sum(1 for item in items if item.graded_adjusted.basis == "graded_value")
    items_using_raw_fallback = sum(
        1 for item in items if item.graded_adjusted.raw_fallback_basis is not None
    )
    coverage_pct = (
        round((len(items) - items_missing_market_price) / len(items) * 100, 2) if items else 0.0
    )

    valuation_quality = CollectionAnalyticsValuationQualityOut(
        items_with_yuyutei_sell=items_with_yuyutei_sell,
        items_with_yuyutei_buy=items_with_yuyutei_buy,
        items_with_snkrdunk_floor=items_with_snkrdunk_floor,
        items_using_graded_value=items_using_graded_value,
        items_using_raw_fallback=items_using_raw_fallback,
        coverage_pct=coverage_pct,
    )

    return CollectionAnalyticsOut(
        summary=summary,
        breakdowns=breakdowns,
        concentration=concentration,
        cost_basis=cost_basis,
        valuation_quality=valuation_quality,
    )
