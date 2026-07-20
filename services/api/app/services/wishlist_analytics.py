"""Wishlist analytics: budget planning, target hits, priority exposure, and
acquisition planning for one user's wishlist - see GET /analytics/wishlist.

Builds entirely on top of app.services.wishlist.get_wishlist_items rather
than re-deriving current-price resolution or the target-hit/gap formulas -
this module only filters/aggregates/ranks the already-computed per-item
values (preferred_current_price_jpy, target_hit, gap_to_target_jpy/pct),
never recomputes any of them.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.schemas import (
    WishlistAnalyticsBreakdownItemOut,
    WishlistAnalyticsBreakdownsOut,
    WishlistAnalyticsBudgetPlanOut,
    WishlistAnalyticsOut,
    WishlistAnalyticsPriceCoverageOut,
    WishlistAnalyticsSummaryOut,
    WishlistAnalyticsTargetItemOut,
    WishlistItemOut,
)
from app.services.wishlist import get_wishlist_items

# How many entries each ranked budget-plan list carries - not spec'd beyond
# "top" grail/high-priority/gap/budget items; 10 matches the same cap used
# by app.services.collection_analytics' ranked lists.
LIST_LIMIT = 10


def _pct(numerator: int, denominator: int) -> float | None:
    """Same rounding/None-on-zero-denominator convention as the private
    `_pct` helpers in app.services.portfolio_valuation/collection_analytics -
    duplicated here (not imported) because it's a generic percent-rounding
    utility, not a pricing/target-hit formula."""
    if not denominator:
        return None
    return round(numerator / denominator * 100, 2)


def _remaining_quantity(item: WishlistItemOut) -> int:
    return max(item.desired_quantity - item.acquired_quantity, 0)


def _to_target_item(item: WishlistItemOut) -> WishlistAnalyticsTargetItemOut:
    return WishlistAnalyticsTargetItemOut(
        wishlist_item_id=item.id,
        card_id=item.card_id,
        card_code=item.card_code,
        name_en=item.name_en,
        name_jp=item.name_jp,
        set_code=item.set_code,
        rarity=item.rarity,
        priority=item.priority,
        status=item.status,
        desired_quantity=item.desired_quantity,
        owned_quantity=item.owned_quantity,
        target_buy_price_jpy=item.target_buy_price_jpy,
        max_buy_price_jpy=item.max_buy_price_jpy,
        preferred_current_price_jpy=item.preferred_current_price_jpy,
        preferred_current_price_source=item.preferred_current_price_source,
        target_hit=item.target_hit,
        gap_to_target_jpy=item.gap_to_target_jpy,
        gap_to_target_pct=item.gap_to_target_pct,
    )


def _build_breakdown(
    entries: Iterable[tuple[str, str, WishlistItemOut]],
    remaining_by_id: dict[int, int],
    total_target_budget_jpy: int,
) -> list[WishlistAnalyticsBreakdownItemOut]:
    buckets: dict[str, dict] = {}
    for key, label, item in entries:
        bucket = buckets.setdefault(
            key,
            {
                "label": label,
                "item_count": 0,
                "desired_quantity": 0,
                "target_budget_jpy": 0,
                "max_budget_jpy": 0,
                "current_price_jpy": 0,
                "target_hit_count": 0,
                "owned_count": 0,
            },
        )
        remaining = remaining_by_id[item.id]
        bucket["item_count"] += 1
        bucket["desired_quantity"] += item.desired_quantity
        if item.target_buy_price_jpy is not None:
            bucket["target_budget_jpy"] += item.target_buy_price_jpy * remaining
        if item.max_buy_price_jpy is not None:
            bucket["max_budget_jpy"] += item.max_buy_price_jpy * remaining
        if item.preferred_current_price_jpy is not None:
            bucket["current_price_jpy"] += item.preferred_current_price_jpy * remaining
        if item.target_hit:
            bucket["target_hit_count"] += 1
        if item.owned_quantity > 0:
            bucket["owned_count"] += 1

    results = []
    for key, bucket in buckets.items():
        weight_pct = _pct(bucket["target_budget_jpy"], total_target_budget_jpy) or 0.0
        results.append(
            WishlistAnalyticsBreakdownItemOut(
                key=key,
                label=bucket["label"],
                item_count=bucket["item_count"],
                desired_quantity=bucket["desired_quantity"],
                target_budget_jpy=bucket["target_budget_jpy"],
                max_budget_jpy=bucket["max_budget_jpy"],
                current_price_jpy=bucket["current_price_jpy"],
                target_hit_count=bucket["target_hit_count"],
                owned_count=bucket["owned_count"],
                budget_weight_pct=weight_pct,
            )
        )
    results.sort(key=lambda r: (-r.target_budget_jpy, r.key))
    return results


def get_wishlist_analytics(
    db: Session,
    *,
    user_id: int,
    include_removed: bool = False,
    include_purchased: bool = False,
) -> WishlistAnalyticsOut:
    all_items = get_wishlist_items(db, user_id, limit=1_000_000, offset=0).items

    items = [
        item
        for item in all_items
        if (include_removed or item.status != "removed")
        and (include_purchased or item.status != "purchased")
    ]

    remaining_by_id = {item.id: _remaining_quantity(item) for item in items}

    target_prices = [item.target_buy_price_jpy for item in items if item.target_buy_price_jpy is not None]
    total_target_budget_jpy = sum(
        item.target_buy_price_jpy * remaining_by_id[item.id]
        for item in items
        if item.target_buy_price_jpy is not None
    )
    total_max_budget_jpy = sum(
        item.max_buy_price_jpy * remaining_by_id[item.id]
        for item in items
        if item.max_buy_price_jpy is not None
    )
    total_current_price_jpy = sum(
        item.preferred_current_price_jpy * remaining_by_id[item.id]
        for item in items
        if item.preferred_current_price_jpy is not None
    )

    summary = WishlistAnalyticsSummaryOut(
        total_items=len(items),
        watching_count=sum(1 for i in items if i.status == "watching"),
        target_hit_count=sum(1 for i in items if i.target_hit),
        purchased_count=sum(1 for i in items if i.status == "purchased"),
        passed_count=sum(1 for i in items if i.status == "passed"),
        grail_count=sum(1 for i in items if i.priority == "grail"),
        high_priority_count=sum(1 for i in items if i.priority == "high"),
        owned_already_count=sum(1 for i in items if i.owned_quantity > 0),
        total_target_budget_jpy=total_target_budget_jpy,
        total_max_budget_jpy=total_max_budget_jpy,
        total_current_price_jpy=total_current_price_jpy,
        budget_gap_to_target_jpy=total_current_price_jpy - total_target_budget_jpy,
        budget_gap_to_max_jpy=total_current_price_jpy - total_max_budget_jpy,
        average_target_price_jpy=(
            round(sum(target_prices) / len(target_prices)) if target_prices else 0
        ),
        median_target_price_jpy=(
            round(statistics.median(target_prices)) if target_prices else 0
        ),
    )

    by_priority = _build_breakdown(
        ((i.priority, i.priority.replace("_", " ").capitalize(), i) for i in items),
        remaining_by_id,
        total_target_budget_jpy,
    )
    by_status = _build_breakdown(
        ((i.status, i.status.replace("_", " ").capitalize(), i) for i in items),
        remaining_by_id,
        total_target_budget_jpy,
    )
    by_set = _build_breakdown(
        ((i.set_code, i.set_code, i) for i in items), remaining_by_id, total_target_budget_jpy
    )
    by_rarity = _build_breakdown(
        ((i.rarity, i.rarity, i) for i in items), remaining_by_id, total_target_budget_jpy
    )
    by_preferred_source = _build_breakdown(
        (
            ((i.preferred_source or "none"), (i.preferred_source or "None"), i)
            for i in items
        ),
        remaining_by_id,
        total_target_budget_jpy,
    )
    by_preferred_condition = _build_breakdown(
        (
            ((i.preferred_condition or "none"), (i.preferred_condition or "None"), i)
            for i in items
        ),
        remaining_by_id,
        total_target_budget_jpy,
    )

    breakdowns = WishlistAnalyticsBreakdownsOut(
        by_priority=by_priority,
        by_status=by_status,
        by_set=by_set,
        by_rarity=by_rarity,
        by_preferred_source=by_preferred_source,
        by_preferred_condition=by_preferred_condition,
    )

    target_hits = sorted(
        (item for item in items if item.target_hit),
        key=lambda i: (i.gap_to_target_jpy if i.gap_to_target_jpy is not None else 0, i.id),
    )
    target_hits_out = [_to_target_item(i) for i in target_hits]

    grail_targets = sorted(
        (i for i in items if i.priority == "grail"),
        key=lambda i: (-(i.target_buy_price_jpy or 0) * remaining_by_id[i.id], i.id),
    )[:LIST_LIMIT]
    high_priority_targets = sorted(
        (i for i in items if i.priority == "high"),
        key=lambda i: (-(i.target_buy_price_jpy or 0) * remaining_by_id[i.id], i.id),
    )[:LIST_LIMIT]
    best_gap_to_target = sorted(
        (i for i in items if i.gap_to_target_jpy is not None),
        key=lambda i: (i.gap_to_target_jpy, i.id),
    )[:LIST_LIMIT]
    largest_budget_items = sorted(
        (i for i in items if i.target_buy_price_jpy is not None),
        key=lambda i: (-(i.target_buy_price_jpy * remaining_by_id[i.id]), i.id),
    )[:LIST_LIMIT]
    already_owned = sorted(
        (i for i in items if i.owned_quantity > 0 and i.status != "purchased"),
        key=lambda i: (-i.owned_quantity, i.id),
    )[:LIST_LIMIT]

    budget_plan = WishlistAnalyticsBudgetPlanOut(
        grail_targets=[_to_target_item(i) for i in grail_targets],
        high_priority_targets=[_to_target_item(i) for i in high_priority_targets],
        best_gap_to_target=[_to_target_item(i) for i in best_gap_to_target],
        largest_budget_items=[_to_target_item(i) for i in largest_budget_items],
        already_owned=[_to_target_item(i) for i in already_owned],
    )

    items_with_current_price = sum(1 for i in items if i.preferred_current_price_jpy is not None)
    items_missing_current_price = len(items) - items_with_current_price
    price_coverage = WishlistAnalyticsPriceCoverageOut(
        items_with_current_price=items_with_current_price,
        items_missing_current_price=items_missing_current_price,
        coverage_pct=_pct(items_with_current_price, len(items)) or 0.0,
    )

    return WishlistAnalyticsOut(
        summary=summary,
        breakdowns=breakdowns,
        target_hits=target_hits_out,
        budget_plan=budget_plan,
        price_coverage=price_coverage,
    )
