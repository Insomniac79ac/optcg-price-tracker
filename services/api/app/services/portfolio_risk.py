"""Portfolio risk and exposure analytics: concentration, data-quality,
liquidity-proxy, grading-exposure, and wishlist-overlap risk, plus exposure
breakdowns by set/rarity/variant/language/tag/group - see GET
/analytics/portfolio-risk.

Builds on top of app.services.portfolio_valuation.get_portfolio_valuation
(current value/cost basis/P&L/tags/groups) and app.services.grading
(get_submissions_for_items/latest_submission, needed for expected_return_date
and per-submission status that GradingInfoOut doesn't expose) and
app.services.wishlist.get_wishlist_items (wishlist overlap) - this module
only combines, scores, and buckets what those services already compute. It
never re-derives a price or a valuation formula. Every scoring rule below is
a fixed, deterministic point value - there is no AI/LLM involvement.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CollectionItem, GradingSubmission
from app.schemas import (
    PortfolioRiskBreakdownOut,
    PortfolioRiskCardOut,
    PortfolioRiskConcentrationOut,
    PortfolioRiskDataQualityCardOut,
    PortfolioRiskDataQualityOut,
    PortfolioRiskExposureItemOut,
    PortfolioRiskExposuresOut,
    PortfolioRiskFlagOut,
    PortfolioRiskGradingCardOut,
    PortfolioRiskGradingExposureOut,
    PortfolioRiskLevel,
    PortfolioRiskLiquidityCardOut,
    PortfolioRiskLiquidityProxyOut,
    PortfolioRiskOut,
    PortfolioRiskSummaryOut,
    PortfolioRiskWishlistCardOut,
    PortfolioRiskWishlistOverlapOut,
    PortfolioValuationItemOut,
    ValuationMode,
    WishlistItemOut,
)
from app.services.grading import get_submissions_for_items, latest_submission
from app.services.portfolio_valuation import get_portfolio_valuation
from app.services.wishlist import get_wishlist_items

# Submitted-but-not-back-in-hand grading statuses - same set duplicated
# across grading_analytics.py (ACTIVE_STATUSES) and sell_decision_support.py
# (ACTIVE_GRADING_STATUSES); kept as its own copy here per this app's
# convention of not sharing small status-list constants across analytics
# modules.
ACTIVE_GRADING_STATUSES = ("planned", "preparing", "submitted", "grading", "shipped_back")

HIGH_PRIORITY_WISHLIST = ("grail", "high")

# Same per-source staleness thresholds as market_signals.py's
# STALE_HOURS_BY_SOURCE (24h Yuyu-Tei, 7 days SNKRDUNK) - duplicated rather
# than imported since that module's constant is private to its own signal
# generation.
STALE_HOURS_BY_SOURCE = {"yuyutei": 24, "snkrdunk": 7 * 24}

WIDE_SPREAD_THRESHOLD_PCT = 45.0

CONCENTRATION_MAX = 30
DATA_QUALITY_MAX = 25
LIQUIDITY_MAX = 20
GRADING_MAX = 15
WISHLIST_MAX = 10
TOTAL_MAX = CONCENTRATION_MAX + DATA_QUALITY_MAX + LIQUIDITY_MAX + GRADING_MAX + WISHLIST_MAX

# "Top N" ranked lists (top_cards, top_sets/rarities, high-cost pending
# grading items) use the same cap as every other analytics module's ranked
# lists (see grading_analytics.LIST_LIMIT/wishlist_analytics.LIST_LIMIT).
# The diagnostic/troubleshooting lists (missing prices, stale prices, wide
# spreads, ...) have no pagination of their own on this endpoint, so they use
# a more generous cap just to bound response size - the summary counts
# already carry the true totals regardless of how many rows are shown here.
LIST_LIMIT = 10
DETAIL_LIST_LIMIT = 25


def _pct(numerator: int, denominator: int) -> float | None:
    """Same rounding/None-on-zero-denominator convention duplicated across
    every analytics service in this app - a generic percent-rounding
    utility, not a valuation formula."""
    if not denominator:
        return None
    return round(numerator / denominator * 100, 2)


def _weight_pct(value_jpy: int, total_value_jpy: int) -> float:
    if not total_value_jpy:
        return 0.0
    return round(value_jpy / total_value_jpy * 100, 2)


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _risk_level(score: int, max_score: int) -> PortfolioRiskLevel:
    pct = (score / max_score * 100) if max_score else 0.0
    if pct >= 75:
        return "critical"
    if pct >= 50:
        return "high"
    if pct >= 25:
        return "medium"
    return "low"


def _selected_value_jpy(item: PortfolioValuationItemOut, valuation_mode: ValuationMode) -> int | None:
    """Same mode switch as collection_analytics._selected_value_jpy,
    duplicated here (private to that module, not imported) - raw_market
    weighs by the SNKRDUNK market floor only (no Yuyu-Tei fallback), so
    concentration/exposure weights stay consistent with collection
    analytics' own concentration figures."""
    if valuation_mode == "graded_adjusted":
        return item.graded_adjusted.value_jpy
    return item.valuations.market_floor_value_jpy


def _latest_observed_at(item: PortfolioValuationItemOut) -> datetime | None:
    candidates = [
        obs.observed_at
        for obs in (
            item.latest_prices.yuyutei_sell,
            item.latest_prices.yuyutei_buy,
            item.latest_prices.snkrdunk_floor,
        )
        if obs is not None
    ]
    return max(candidates) if candidates else None


def _total_grading_cost_jpy(submission: GradingSubmission) -> int:
    """grading_fee + shipping_fee + insurance_fee + other_fee, treating an
    unset fee as 0 - same 0-fallback convention as
    grading_analytics._total_grading_cost_jpy (duplicated, not imported)."""
    return (
        (submission.grading_fee_jpy or 0)
        + (submission.shipping_fee_jpy or 0)
        + (submission.insurance_fee_jpy or 0)
        + (submission.other_fee_jpy or 0)
    )


def _to_card_out(
    item: PortfolioValuationItemOut, value_jpy: int | None, weight_pct: float, warnings: list[str]
) -> PortfolioRiskCardOut:
    return PortfolioRiskCardOut(
        card_id=item.card_id,
        collection_item_id=item.collection_item_id,
        card_code=item.card_code,
        name_en=item.name_en,
        set_code=item.set_code,
        rarity=item.rarity,
        quantity=item.quantity,
        value_jpy=value_jpy,
        portfolio_weight_pct=weight_pct,
        cost_basis_jpy=item.cost_basis_jpy,
        warnings=warnings,
    )


def _to_data_quality_card_out(
    item: PortfolioValuationItemOut,
    value_jpy: int | None,
    weight_pct: float,
    issue: str,
    latest_observed_at: datetime | None,
    suggested_action: str,
) -> PortfolioRiskDataQualityCardOut:
    return PortfolioRiskDataQualityCardOut(
        **_to_card_out(item, value_jpy, weight_pct, []).model_dump(),
        issue=issue,
        latest_observed_at=latest_observed_at,
        suggested_action=suggested_action,
    )


def _to_liquidity_card_out(
    item: PortfolioValuationItemOut,
    value_jpy: int | None,
    weight_pct: float,
    spread_pct: float | None,
    warnings: list[str],
) -> PortfolioRiskLiquidityCardOut:
    yuyutei_sell = item.latest_prices.yuyutei_sell
    yuyutei_buy = item.latest_prices.yuyutei_buy
    snkrdunk_floor = item.latest_prices.snkrdunk_floor
    return PortfolioRiskLiquidityCardOut(
        **_to_card_out(item, value_jpy, weight_pct, warnings).model_dump(),
        yuyutei_sell_jpy=yuyutei_sell.price_jpy if yuyutei_sell is not None else None,
        yuyutei_buy_jpy=yuyutei_buy.price_jpy if yuyutei_buy is not None else None,
        spread_pct=spread_pct,
        snkrdunk_floor_jpy=snkrdunk_floor.price_jpy if snkrdunk_floor is not None else None,
        listing_count=snkrdunk_floor.listing_count if snkrdunk_floor is not None else None,
    )


def _to_grading_card_out(
    item: PortfolioValuationItemOut,
    value_jpy: int | None,
    weight_pct: float,
    submission: GradingSubmission,
    overdue: bool,
) -> PortfolioRiskGradingCardOut:
    return PortfolioRiskGradingCardOut(
        **_to_card_out(item, value_jpy, weight_pct, ["overdue"] if overdue else []).model_dump(),
        grading_company=submission.grading_company,
        submission_status=submission.submission_status,
        grading_cost_jpy=_total_grading_cost_jpy(submission),
        expected_return_date=submission.expected_return_date,
        overdue=overdue,
    )


def _to_wishlist_card_out(item: WishlistItemOut) -> PortfolioRiskWishlistCardOut:
    return PortfolioRiskWishlistCardOut(
        wishlist_item_id=item.id,
        card_id=item.card_id,
        card_code=item.card_code,
        name_en=item.name_en,
        set_code=item.set_code,
        rarity=item.rarity,
        wishlist_priority=item.priority,
        wishlist_status=item.status,
        owned_quantity=item.owned_quantity,
        desired_quantity=item.desired_quantity,
        suggested_action="update_wishlist_status",
    )


def _build_exposure(
    entries: Iterable[tuple[str, str, PortfolioValuationItemOut]],
    selected_values: dict[int, int | None],
    total_value_jpy: int,
) -> list[PortfolioRiskExposureItemOut]:
    """entries is (key, label, item) tuples - an item can appear under more
    than one key (tags/groups), same convention as
    collection_analytics._build_breakdown."""
    buckets: dict[str, dict] = {}
    for key, label, item in entries:
        bucket = buckets.setdefault(
            key, {"label": label, "quantity": 0, "cost_basis_jpy": 0, "value_jpy": 0}
        )
        bucket["quantity"] += item.quantity
        bucket["cost_basis_jpy"] += item.cost_basis_jpy or 0
        bucket["value_jpy"] += selected_values[item.collection_item_id] or 0

    results = []
    for key, bucket in buckets.items():
        weight_pct = _weight_pct(bucket["value_jpy"], total_value_jpy)
        pnl_jpy = bucket["value_jpy"] - bucket["cost_basis_jpy"]
        risk_flags: list[str] = []
        if weight_pct >= 50:
            risk_flags.append("high_concentration")
        elif weight_pct >= 25:
            risk_flags.append("moderate_concentration")
        results.append(
            PortfolioRiskExposureItemOut(
                key=key,
                label=bucket["label"],
                quantity=bucket["quantity"],
                value_jpy=bucket["value_jpy"],
                cost_basis_jpy=bucket["cost_basis_jpy"],
                portfolio_weight_pct=weight_pct,
                pnl_jpy=pnl_jpy,
                pnl_pct=_pct(pnl_jpy, bucket["cost_basis_jpy"]),
                risk_flags=risk_flags,
            )
        )
    results.sort(key=lambda r: (-r.value_jpy, r.key))
    return results


def _empty_portfolio_risk() -> PortfolioRiskOut:
    return PortfolioRiskOut(
        summary=PortfolioRiskSummaryOut(
            risk_score=0,
            risk_level="low",
            total_value_jpy=0,
            total_cost_basis_jpy=0,
            largest_single_card_weight_pct=0.0,
            top_5_weight_pct=0.0,
            top_10_weight_pct=0.0,
            largest_set_weight_pct=0.0,
            largest_rarity_weight_pct=0.0,
            missing_price_count=0,
            missing_cost_basis_count=0,
            stale_price_count=0,
            wide_spread_count=0,
            active_grading_count=0,
            wishlist_overlap_count=0,
        ),
        risk_breakdown=PortfolioRiskBreakdownOut(
            concentration=PortfolioRiskConcentrationOut(
                score=0, level="low", warnings=[], top_cards=[], top_sets=[], top_rarities=[]
            ),
            data_quality=PortfolioRiskDataQualityOut(
                score=0, level="low", warnings=[], missing_prices=[], missing_cost_basis=[], stale_prices=[]
            ),
            liquidity_proxy=PortfolioRiskLiquidityProxyOut(
                score=0, level="low", warnings=[], wide_spread_cards=[], low_listing_cards=[]
            ),
            grading_exposure=PortfolioRiskGradingExposureOut(
                score=0, level="low", warnings=[], active_grading_items=[], high_cost_pending_items=[]
            ),
            wishlist_overlap=PortfolioRiskWishlistOverlapOut(
                score=0, level="low", warnings=[], owned_wishlist_items=[]
            ),
        ),
        exposures=PortfolioRiskExposuresOut(
            by_set=[], by_rarity=[], by_variant=[], by_language=[], by_tag=[], by_group=[]
        ),
        recommendation_flags=[],
    )


def get_portfolio_risk(
    db: Session,
    *,
    user_id: int,
    valuation_mode: ValuationMode = "raw_market",
    include_sold: bool = False,
) -> PortfolioRiskOut:
    status_by_item_id = dict(
        db.execute(
            select(CollectionItem.id, CollectionItem.status).where(CollectionItem.user_id == user_id)
        ).all()
    )

    # Always fetched in graded_adjusted mode - same convention as
    # collection_analytics.get_collection_analytics - so both the raw
    # (market_floor) and graded-adjusted figures are populated on every item
    # regardless of the caller's requested valuation_mode.
    portfolio = get_portfolio_valuation(db, user_id=user_id, valuation_mode="graded_adjusted")

    items = [
        item
        for item in portfolio.items
        if include_sold or status_by_item_id.get(item.collection_item_id) != "sold"
    ]

    if not items:
        return _empty_portfolio_risk()

    selected_values = {item.collection_item_id: _selected_value_jpy(item, valuation_mode) for item in items}
    total_value_jpy = sum(v or 0 for v in selected_values.values())
    total_cost_basis_jpy = sum(item.cost_basis_jpy or 0 for item in items)
    total_items = len(items)

    def value_of(item: PortfolioValuationItemOut) -> int | None:
        return selected_values[item.collection_item_id]

    def weight_of(item: PortfolioValuationItemOut) -> float:
        return _weight_pct(value_of(item) or 0, total_value_jpy)

    # ---- Concentration ---------------------------------------------------

    sorted_by_value = sorted(items, key=lambda item: (-(value_of(item) or 0), item.collection_item_id))
    top1 = sorted_by_value[:1]
    top5 = sorted_by_value[:5]
    top10 = sorted_by_value[:10]

    largest_single_card_weight_pct = weight_of(top1[0]) if top1 else 0.0
    top_5_weight_pct = _weight_pct(sum(value_of(i) or 0 for i in top5), total_value_jpy)
    top_10_weight_pct = _weight_pct(sum(value_of(i) or 0 for i in top10), total_value_jpy)

    by_set_exposure = _build_exposure(
        ((item.set_code, item.set_code, item) for item in items), selected_values, total_value_jpy
    )
    by_rarity_exposure = _build_exposure(
        ((item.rarity, item.rarity, item) for item in items), selected_values, total_value_jpy
    )
    by_variant_exposure = _build_exposure(
        ((item.variant or "none", item.variant or "None", item) for item in items),
        selected_values,
        total_value_jpy,
    )
    by_language_exposure = _build_exposure(
        ((item.language, item.language, item) for item in items), selected_values, total_value_jpy
    )
    by_tag_exposure = _build_exposure(
        ((tag.slug, tag.name, item) for item in items for tag in item.tags), selected_values, total_value_jpy
    )
    by_group_exposure = _build_exposure(
        ((group.slug, group.name, item) for item in items for group in item.groups),
        selected_values,
        total_value_jpy,
    )

    largest_set_weight_pct = max((e.portfolio_weight_pct for e in by_set_exposure), default=0.0)
    largest_rarity_weight_pct = max((e.portfolio_weight_pct for e in by_rarity_exposure), default=0.0)

    concentration_score = 0
    concentration_warnings: list[str] = []
    if largest_single_card_weight_pct >= 40:
        concentration_score += 15
        concentration_warnings.append(
            f"Largest single card is {largest_single_card_weight_pct}% of portfolio value."
        )
    elif largest_single_card_weight_pct >= 25:
        concentration_score += 10
        concentration_warnings.append(
            f"Largest single card is {largest_single_card_weight_pct}% of portfolio value."
        )

    if top_5_weight_pct >= 80:
        concentration_score += 15
        concentration_warnings.append(f"Top 5 cards represent {top_5_weight_pct}% of portfolio value.")
    elif top_5_weight_pct >= 60:
        concentration_score += 10
        concentration_warnings.append(f"Top 5 cards represent {top_5_weight_pct}% of portfolio value.")

    if largest_set_weight_pct >= 50:
        concentration_score += 5
        concentration_warnings.append(f"Largest set represents {largest_set_weight_pct}% of portfolio value.")

    if largest_rarity_weight_pct >= 50:
        concentration_score += 5
        concentration_warnings.append(
            f"Largest rarity represents {largest_rarity_weight_pct}% of portfolio value."
        )

    concentration_score = min(concentration_score, CONCENTRATION_MAX)

    top_cards_out = [
        _to_card_out(
            item,
            value_of(item),
            weight_of(item),
            ["high_single_card_concentration"] if weight_of(item) >= 25 else [],
        )
        for item in top5
    ]

    concentration = PortfolioRiskConcentrationOut(
        score=concentration_score,
        level=_risk_level(concentration_score, CONCENTRATION_MAX),
        warnings=concentration_warnings,
        top_cards=top_cards_out,
        top_sets=by_set_exposure[:LIST_LIMIT],
        top_rarities=by_rarity_exposure[:LIST_LIMIT],
    )

    # ---- Data quality ------------------------------------------------------

    missing_price_items = [item for item in items if value_of(item) is None]
    missing_cost_basis_items = [item for item in items if item.cost_basis_jpy is None]

    now_naive = _naive(datetime.now(timezone.utc))
    stale_entries: list[tuple[PortfolioValuationItemOut, str, datetime]] = []
    for item in items:
        for obs, source_label, hours in (
            (item.latest_prices.yuyutei_sell, "Yuyu-Tei sell", STALE_HOURS_BY_SOURCE["yuyutei"]),
            (item.latest_prices.yuyutei_buy, "Yuyu-Tei buy", STALE_HOURS_BY_SOURCE["yuyutei"]),
            (item.latest_prices.snkrdunk_floor, "SNKRDUNK floor", STALE_HOURS_BY_SOURCE["snkrdunk"]),
        ):
            if obs is None:
                continue
            age = now_naive - _naive(obs.observed_at)
            if age > timedelta(hours=hours):
                stale_entries.append((item, source_label, obs.observed_at))
                break  # one stale flag per item is enough to count it once

    missing_price_count = len(missing_price_items)
    missing_cost_basis_count = len(missing_cost_basis_items)
    stale_price_count = len(stale_entries)

    missing_price_pct = _pct(missing_price_count, total_items) or 0.0
    missing_cost_basis_pct = _pct(missing_cost_basis_count, total_items) or 0.0
    stale_price_pct = _pct(stale_price_count, total_items) or 0.0

    data_quality_score = 0
    data_quality_warnings: list[str] = []
    if missing_price_pct >= 40:
        data_quality_score += 15
        data_quality_warnings.append(f"{missing_price_pct}% of owned items have no current market price.")
    elif missing_price_pct >= 20:
        data_quality_score += 10
        data_quality_warnings.append(f"{missing_price_pct}% of owned items have no current market price.")

    if missing_cost_basis_pct >= 40:
        data_quality_score += 10
        data_quality_warnings.append(f"{missing_cost_basis_pct}% of owned items have no recorded cost basis.")
    elif missing_cost_basis_pct >= 20:
        data_quality_score += 5
        data_quality_warnings.append(f"{missing_cost_basis_pct}% of owned items have no recorded cost basis.")

    if stale_price_pct >= 20:
        data_quality_score += 5
        data_quality_warnings.append(f"{stale_price_pct}% of owned items have stale price data.")

    data_quality_score = min(data_quality_score, DATA_QUALITY_MAX)

    missing_prices_out = [
        _to_data_quality_card_out(
            item, value_of(item), weight_of(item), "No current market price available",
            _latest_observed_at(item), "fix_missing_prices",
        )
        for item in sorted(missing_price_items, key=lambda i: (-(i.cost_basis_jpy or 0), i.collection_item_id))
    ][:DETAIL_LIST_LIMIT]

    missing_cost_basis_out = [
        _to_data_quality_card_out(
            item, value_of(item), weight_of(item), "No purchase price recorded",
            _latest_observed_at(item), "fix_cost_basis",
        )
        for item in sorted(missing_cost_basis_items, key=lambda i: (-(value_of(i) or 0), i.collection_item_id))
    ][:DETAIL_LIST_LIMIT]

    stale_prices_out = [
        _to_data_quality_card_out(
            item, value_of(item), weight_of(item), f"{source_label} price is stale",
            observed_at, "review_stale_prices",
        )
        for item, source_label, observed_at in sorted(stale_entries, key=lambda t: (t[2], t[0].collection_item_id))
    ][:DETAIL_LIST_LIMIT]

    data_quality = PortfolioRiskDataQualityOut(
        score=data_quality_score,
        level=_risk_level(data_quality_score, DATA_QUALITY_MAX),
        warnings=data_quality_warnings,
        missing_prices=missing_prices_out,
        missing_cost_basis=missing_cost_basis_out,
        stale_prices=stale_prices_out,
    )

    # ---- Liquidity proxy -----------------------------------------------

    priced_items: list[PortfolioValuationItemOut] = []
    wide_spread_entries: list[tuple[PortfolioValuationItemOut, float]] = []
    for item in items:
        sell = item.latest_prices.yuyutei_sell
        buy = item.latest_prices.yuyutei_buy
        if sell is None or buy is None:
            continue
        priced_items.append(item)
        spread_pct = _pct(sell.price_jpy - buy.price_jpy, sell.price_jpy)
        if spread_pct is not None and spread_pct >= WIDE_SPREAD_THRESHOLD_PCT:
            wide_spread_entries.append((item, spread_pct))

    wide_spread_count = len(wide_spread_entries)
    wide_spread_share_pct = _pct(wide_spread_count, len(priced_items)) or 0.0

    snkrdunk_items = [item for item in items if item.latest_prices.snkrdunk_floor is not None]
    low_listing_items = [
        item for item in snkrdunk_items if item.latest_prices.snkrdunk_floor.listing_count in (0, None)
    ]
    low_listing_share_pct = _pct(len(low_listing_items), len(snkrdunk_items)) or 0.0

    floor_missing_items = [
        item
        for item in items
        if item.latest_prices.snkrdunk_floor is None and item.latest_prices.yuyutei_sell is not None
    ]
    floor_missing_share_pct = _pct(len(floor_missing_items), total_items) or 0.0

    liquidity_score = 0
    liquidity_warnings: list[str] = []
    if wide_spread_share_pct >= 20:
        liquidity_score += 10
        liquidity_warnings.append(
            f"Yuyu-Tei buy/sell spread is 45%+ for {wide_spread_share_pct}% of priced items."
        )
    if low_listing_share_pct >= 30:
        liquidity_score += 5
        liquidity_warnings.append(
            f"SNKRDUNK listing count is 0 or unavailable for {low_listing_share_pct}% of cards with SNKRDUNK data."
        )
    if floor_missing_share_pct >= 30:
        liquidity_score += 5
        liquidity_warnings.append(
            f"SNKRDUNK floor is missing (Yuyu-Tei sell exists) for {floor_missing_share_pct}% of items."
        )
    liquidity_score = min(liquidity_score, LIQUIDITY_MAX)

    wide_spread_cards_out = [
        _to_liquidity_card_out(item, value_of(item), weight_of(item), spread_pct, [])
        for item, spread_pct in sorted(wide_spread_entries, key=lambda t: (-t[1], t[0].collection_item_id))
    ][:DETAIL_LIST_LIMIT]

    low_listing_warnings_by_item: dict[int, list[str]] = {}
    for item in low_listing_items:
        low_listing_warnings_by_item.setdefault(item.collection_item_id, []).append(
            "zero_or_missing_listing_count"
        )
    for item in floor_missing_items:
        low_listing_warnings_by_item.setdefault(item.collection_item_id, []).append("snkrdunk_floor_missing")

    low_listing_items_by_id = {item.collection_item_id: item for item in low_listing_items + floor_missing_items}
    low_listing_cards_out = [
        _to_liquidity_card_out(item, value_of(item), weight_of(item), None, low_listing_warnings_by_item[item_id])
        for item_id, item in sorted(low_listing_items_by_id.items())
    ][:DETAIL_LIST_LIMIT]

    liquidity_proxy = PortfolioRiskLiquidityProxyOut(
        score=liquidity_score,
        level=_risk_level(liquidity_score, LIQUIDITY_MAX),
        warnings=liquidity_warnings,
        wide_spread_cards=wide_spread_cards_out,
        low_listing_cards=low_listing_cards_out,
    )

    # ---- Grading exposure ------------------------------------------------

    item_ids = {item.collection_item_id for item in items}
    submissions_by_item = get_submissions_for_items(db, item_ids)
    today = date.today()

    active_entries: list[tuple[PortfolioValuationItemOut, GradingSubmission, bool]] = []
    overdue_entries: list[tuple[PortfolioValuationItemOut, GradingSubmission]] = []
    for item in items:
        latest = latest_submission(submissions_by_item, item.collection_item_id)
        if latest is None:
            continue
        overdue = (
            latest.expected_return_date is not None
            and latest.submission_status not in ("received", "cancelled")
            and latest.expected_return_date < today
        )
        if latest.submission_status in ACTIVE_GRADING_STATUSES:
            active_entries.append((item, latest, overdue))
        if overdue:
            overdue_entries.append((item, latest))

    active_grading_cost_basis_jpy = sum(item.cost_basis_jpy or 0 for item, _, _ in active_entries)
    active_cost_share_pct = _pct(active_grading_cost_basis_jpy, total_cost_basis_jpy) or 0.0

    grading_score = 0
    grading_warnings: list[str] = []
    if active_cost_share_pct >= 20:
        grading_score += 10
        grading_warnings.append(
            f"Active grading submissions represent {active_cost_share_pct}% of portfolio cost basis."
        )
    if overdue_entries:
        grading_score += 5
        grading_warnings.append(f"{len(overdue_entries)} grading submission(s) are overdue for return.")
    grading_score = min(grading_score, GRADING_MAX)

    sorted_active_entries = sorted(
        active_entries, key=lambda t: (-(t[0].cost_basis_jpy or 0), t[0].collection_item_id)
    )
    active_grading_items_out = [
        _to_grading_card_out(item, value_of(item), weight_of(item), submission, overdue)
        for item, submission, overdue in sorted_active_entries[:DETAIL_LIST_LIMIT]
    ]
    high_cost_pending_items_out = [
        _to_grading_card_out(item, value_of(item), weight_of(item), submission, overdue)
        for item, submission, overdue in sorted_active_entries[:LIST_LIMIT]
    ]

    grading_exposure = PortfolioRiskGradingExposureOut(
        score=grading_score,
        level=_risk_level(grading_score, GRADING_MAX),
        warnings=grading_warnings,
        active_grading_items=active_grading_items_out,
        high_cost_pending_items=high_cost_pending_items_out,
    )

    # ---- Wishlist overlap --------------------------------------------------

    owned_card_ids = {item.card_id for item in items}
    wishlist_items = get_wishlist_items(db, user_id, limit=1_000_000, offset=0).items

    grail_high_not_purchased = [
        w
        for w in wishlist_items
        if w.card_id in owned_card_ids and w.priority in HIGH_PRIORITY_WISHLIST and w.status not in ("purchased", "removed")
    ]
    fulfilled_not_updated = [
        w for w in wishlist_items if w.acquired_quantity >= w.desired_quantity and w.status in ("watching", "target_hit")
    ]

    wishlist_score = 0
    wishlist_warnings: list[str] = []
    if grail_high_not_purchased:
        wishlist_score += 5
        wishlist_warnings.append(
            f"{len(grail_high_not_purchased)} owned card(s) are still grail/high wishlist items not marked purchased."
        )
    if fulfilled_not_updated:
        wishlist_score += 5
        wishlist_warnings.append(
            f"{len(fulfilled_not_updated)} wishlist item(s) have their desired quantity fulfilled but status not updated."
        )
    wishlist_score = min(wishlist_score, WISHLIST_MAX)

    owned_wishlist_map: dict[int, WishlistItemOut] = {}
    for w in grail_high_not_purchased + fulfilled_not_updated:
        owned_wishlist_map.setdefault(w.id, w)
    owned_wishlist_items_out = [
        _to_wishlist_card_out(w) for w in sorted(owned_wishlist_map.values(), key=lambda w: w.id)
    ][:DETAIL_LIST_LIMIT]

    wishlist_overlap = PortfolioRiskWishlistOverlapOut(
        score=wishlist_score,
        level=_risk_level(wishlist_score, WISHLIST_MAX),
        warnings=wishlist_warnings,
        owned_wishlist_items=owned_wishlist_items_out,
    )

    # ---- Overall + recommendation flags -------------------------------

    risk_score = min(
        concentration_score + data_quality_score + liquidity_score + grading_score + wishlist_score,
        TOTAL_MAX,
    )
    risk_level = _risk_level(risk_score, TOTAL_MAX)

    flags: list[PortfolioRiskFlagOut] = []

    if largest_single_card_weight_pct >= 25:
        flags.append(
            PortfolioRiskFlagOut(
                flag_type="high_concentration",
                severity="critical" if largest_single_card_weight_pct >= 40 else "warning",
                message=f"Largest single card is {largest_single_card_weight_pct}% of portfolio value.",
                related_cards=[top1[0].card_code] if top1 else [],
                suggested_action="review_concentration",
            )
        )

    if top_5_weight_pct >= 60:
        flags.append(
            PortfolioRiskFlagOut(
                flag_type="high_concentration",
                severity="critical" if top_5_weight_pct >= 80 else "warning",
                message=f"Top 5 cards represent {top_5_weight_pct}% of portfolio value.",
                related_cards=[i.card_code for i in top5],
                suggested_action="review_concentration",
            )
        )

    if largest_set_weight_pct >= 50:
        top_set = max(by_set_exposure, key=lambda e: e.portfolio_weight_pct)
        flags.append(
            PortfolioRiskFlagOut(
                flag_type="high_set_concentration",
                severity="warning",
                message=f"Set {top_set.label} represents {largest_set_weight_pct}% of portfolio value.",
                related_cards=[],
                suggested_action="review_concentration",
            )
        )

    if largest_rarity_weight_pct >= 50:
        top_rarity = max(by_rarity_exposure, key=lambda e: e.portfolio_weight_pct)
        flags.append(
            PortfolioRiskFlagOut(
                flag_type="high_rarity_concentration",
                severity="warning",
                message=f"Rarity {top_rarity.label} represents {largest_rarity_weight_pct}% of portfolio value.",
                related_cards=[],
                suggested_action="review_concentration",
            )
        )

    if missing_price_count > 0:
        flags.append(
            PortfolioRiskFlagOut(
                flag_type="missing_prices",
                severity="critical" if missing_price_pct >= 40 else "warning",
                message=f"{missing_price_count} owned item(s) have no current market price.",
                related_cards=[i.card_code for i in missing_price_items[:5]],
                suggested_action="fix_missing_prices",
            )
        )

    if missing_cost_basis_count > 0:
        flags.append(
            PortfolioRiskFlagOut(
                flag_type="missing_cost_basis",
                severity="critical" if missing_cost_basis_pct >= 40 else "warning",
                message=f"{missing_cost_basis_count} owned item(s) have no recorded purchase price.",
                related_cards=[i.card_code for i in missing_cost_basis_items[:5]],
                suggested_action="fix_cost_basis",
            )
        )

    if stale_price_count > 0:
        flags.append(
            PortfolioRiskFlagOut(
                flag_type="stale_prices",
                severity="warning",
                message=f"{stale_price_count} owned item(s) have stale price data.",
                related_cards=[e[0].card_code for e in stale_entries[:5]],
                suggested_action="review_stale_prices",
            )
        )

    if wide_spread_count > 0:
        flags.append(
            PortfolioRiskFlagOut(
                flag_type="wide_spread",
                severity="warning",
                message=f"{wide_spread_count} owned item(s) have a Yuyu-Tei buy/sell spread of 45% or more.",
                related_cards=[e[0].card_code for e in wide_spread_entries[:5]],
                suggested_action="review_wide_spreads",
            )
        )

    if low_listing_cards_out:
        flags.append(
            PortfolioRiskFlagOut(
                flag_type="low_liquidity",
                severity="warning",
                message=f"{len(low_listing_cards_out)} owned item(s) show low SNKRDUNK listing liquidity.",
                related_cards=[c.card_code for c in low_listing_cards_out[:5]],
                suggested_action="review_wide_spreads",
            )
        )

    if active_cost_share_pct >= 20:
        flags.append(
            PortfolioRiskFlagOut(
                flag_type="grading_exposure",
                severity="critical" if active_cost_share_pct >= 40 else "warning",
                message=f"Active grading submissions represent {active_cost_share_pct}% of portfolio cost basis.",
                related_cards=[i.card_code for i, _, _ in sorted_active_entries[:5]],
                suggested_action="review_grading_exposure",
            )
        )

    if overdue_entries:
        flags.append(
            PortfolioRiskFlagOut(
                flag_type="overdue_grading",
                severity="warning",
                message=f"{len(overdue_entries)} grading submission(s) are overdue for return.",
                related_cards=[i.card_code for i, _ in overdue_entries[:5]],
                suggested_action="review_grading_exposure",
            )
        )

    if owned_wishlist_items_out:
        flags.append(
            PortfolioRiskFlagOut(
                flag_type="wishlist_overlap",
                severity="warning",
                message=f"{len(owned_wishlist_items_out)} wishlist item(s) need a status update.",
                related_cards=[c.card_code for c in owned_wishlist_items_out[:5]],
                suggested_action="update_wishlist_status",
            )
        )

    summary = PortfolioRiskSummaryOut(
        risk_score=risk_score,
        risk_level=risk_level,
        total_value_jpy=total_value_jpy,
        total_cost_basis_jpy=total_cost_basis_jpy,
        largest_single_card_weight_pct=largest_single_card_weight_pct,
        top_5_weight_pct=top_5_weight_pct,
        top_10_weight_pct=top_10_weight_pct,
        largest_set_weight_pct=largest_set_weight_pct,
        largest_rarity_weight_pct=largest_rarity_weight_pct,
        missing_price_count=missing_price_count,
        missing_cost_basis_count=missing_cost_basis_count,
        stale_price_count=stale_price_count,
        wide_spread_count=wide_spread_count,
        active_grading_count=len(active_entries),
        wishlist_overlap_count=len(owned_wishlist_map),
    )

    risk_breakdown = PortfolioRiskBreakdownOut(
        concentration=concentration,
        data_quality=data_quality,
        liquidity_proxy=liquidity_proxy,
        grading_exposure=grading_exposure,
        wishlist_overlap=wishlist_overlap,
    )

    exposures = PortfolioRiskExposuresOut(
        by_set=by_set_exposure,
        by_rarity=by_rarity_exposure,
        by_variant=by_variant_exposure,
        by_language=by_language_exposure,
        by_tag=by_tag_exposure,
        by_group=by_group_exposure,
    )

    return PortfolioRiskOut(
        summary=summary,
        risk_breakdown=risk_breakdown,
        exposures=exposures,
        recommendation_flags=flags,
    )
