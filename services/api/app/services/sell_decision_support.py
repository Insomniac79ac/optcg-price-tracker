"""Sell decision support: deterministic scoring that flags owned cards worth
reviewing to sell, holding, grading first, or monitoring - see GET
/analytics/sell-decisions.

Builds entirely on top of app.services.portfolio_valuation.get_portfolio_valuation
(current value/cost basis/P&L/grading/tags/groups), app.services.
opportunity_scoring.get_opportunities (market signal scores), and
app.services.wishlist.get_wishlist_items (wishlist overlap) - this module
only combines and scores what those services already compute. It never
re-derives a price, a valuation, or an opportunity score, and every scoring
rule below is a fixed, deterministic point value - there is no AI/LLM
involvement and nothing here places or automates an actual sale.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.pagination import pagination_response
from app.models import CollectionItem
from app.schemas import (
    OpportunityOut,
    PortfolioValuationItemOut,
    SellDecisionAction,
    SellDecisionCandidateOut,
    SellDecisionGradingOut,
    SellDecisionLatestPricesOut,
    SellDecisionMarketContextOut,
    SellDecisionSummaryOut,
    SellDecisionSupportOut,
    SellDecisionWishlistOverlapOut,
    ValuationMode,
    WishlistItemOut,
)
from app.services.opportunity_scoring import get_opportunities
from app.services.portfolio_valuation import get_portfolio_valuation
from app.services.wishlist import get_wishlist_items

# Submitted-but-not-back-in-hand grading statuses - a card can't be safely
# evaluated as a sell candidate while any of these is in progress, since its
# final graded value/cost isn't known yet. Matches the exact status list the
# spec calls out for the grade_first action.
ACTIVE_GRADING_STATUSES = ("planned", "preparing", "submitted", "grading", "shipped_back")

HIGH_PRIORITY_WISHLIST = ("grail", "high")

# Substring checks against free-text tag/group names a collector chose
# themselves - not an enum, so these only ever match a fragment the user
# actually typed (e.g. a tag literally named "Flip", "Long-term hold").
FLIP_SELL_KEYWORDS = ("flip", "sell")
LONG_TERM_HOLD_KEYWORDS = ("long-term", "hold")

_WISHLIST_PRIORITY_RANK = {"grail": 3, "high": 2, "medium": 1, "low": 0}

SCORE_MIN = 0
SCORE_MAX = 100


def _pct(numerator: int, denominator: int) -> float | None:
    """Same rounding/None-on-zero-denominator convention duplicated across
    every analytics service in this app (portfolio_valuation.py,
    collection_analytics.py, wishlist_analytics.py) - a generic
    percent-rounding utility, not a valuation formula."""
    if not denominator:
        return None
    return round(numerator / denominator * 100, 2)


def _current_value_and_basis(
    item: PortfolioValuationItemOut, valuation_mode: ValuationMode
) -> tuple[int | None, str | None]:
    """Picks which already-computed value app.services.portfolio_valuation
    attached to this item counts as "the" current value - same mode switch
    as collection_analytics._selected_value_jpy. graded_adjusted's own
    value/basis already encodes the graded-value-then-SNKRDUNK-then-Yuyu-Tei
    fallback; raw_market mode applies the same SNKRDUNK-then-Yuyu-Tei order
    directly off the raw valuations block (portfolio_valuation's own
    _resolve_current_value does the same lookup but returns "market_floor"/
    "retail" literals - basis names are kept as "snkrdunk_floor"/
    "yuyutei_sell" here to match graded_adjusted's literal set)."""
    if valuation_mode == "graded_adjusted":
        return item.graded_adjusted.value_jpy, item.graded_adjusted.basis
    if item.valuations.market_floor_value_jpy is not None:
        return item.valuations.market_floor_value_jpy, "snkrdunk_floor"
    if item.valuations.retail_value_jpy is not None:
        return item.valuations.retail_value_jpy, "yuyutei_sell"
    return None, None


def _best_wishlist_item_by_card(wishlist_items: list[WishlistItemOut]) -> dict[int, WishlistItemOut]:
    """One representative (highest-priority, first-seen) non-removed
    wishlist entry per card - same simplification as
    app.services.opportunity_scoring._best_wishlist_item_by_card, duplicated
    here (that helper is private to its module) rather than re-deriving
    wishlist priority ranking."""
    best: dict[int, WishlistItemOut] = {}
    for item in wishlist_items:
        if item.status == "removed":
            continue
        current = best.get(item.card_id)
        if current is None or (
            _WISHLIST_PRIORITY_RANK.get(item.priority, 0) > _WISHLIST_PRIORITY_RANK.get(current.priority, 0)
        ):
            best[item.card_id] = item
    return best


def _name_matches(names: list[str], keywords: tuple[str, ...]) -> bool:
    return any(keyword in name.lower() for name in names for keyword in keywords)


def _score_candidate(
    *,
    item: PortfolioValuationItemOut,
    status: str,
    current_value_jpy: int | None,
    unrealized_pnl_pct: float | None,
    yuyutei_spread_pct: float | None,
    snkrdunk_vs_yuyutei_sell_gap_pct: float | None,
    has_review_sell_opportunity: bool,
    related_opportunity_score: int | None,
    wishlist_priority: str | None,
    tag_names: list[str],
    group_names: list[str],
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if item.flags.above_target_sell:
        score += 35
        reasons.append("Above target sell price")

    if unrealized_pnl_pct is not None and unrealized_pnl_pct >= 50:
        score += 20
        reasons.append("Unrealized P/L above 50%")
    if unrealized_pnl_pct is not None and unrealized_pnl_pct >= 100:
        score += 30
        reasons.append("Unrealized P/L above 100%")

    if snkrdunk_vs_yuyutei_sell_gap_pct is not None and snkrdunk_vs_yuyutei_sell_gap_pct >= 10:
        score += 15
        reasons.append("SNKRDUNK floor above Yuyu-Tei sell by 10%+")

    if yuyutei_spread_pct is not None and yuyutei_spread_pct <= 20:
        score += 15
        reasons.append("Compressed Yuyu-Tei spread")

    if has_review_sell_opportunity:
        score += 25
        reasons.append("Market signal suggests reviewing a sell")

    if related_opportunity_score is not None and related_opportunity_score >= 70:
        score += 15
        reasons.append("High related market opportunity score")

    if status == "sell":
        score += 20
        reasons.append("Marked for sell")

    if _name_matches(tag_names, FLIP_SELL_KEYWORDS):
        score += 10
        reasons.append("Tagged for flip/sell")

    if item.grading.has_grading_submission and item.grading.latest_status in ACTIVE_GRADING_STATUSES:
        score -= 25
        reasons.append("Grading in progress")

    if item.grading.latest_status == "received" and item.grading.graded_value_jpy is not None:
        score += 10
        reasons.append("Graded value available")

    if item.cost_basis_jpy is None:
        score -= 20
        reasons.append("Missing cost basis")

    if current_value_jpy is None:
        score -= 30
        reasons.append("Missing current value")

    if wishlist_priority in HIGH_PRIORITY_WISHLIST:
        score -= 10
        reasons.append("Also wishlisted at grail/high priority")

    if _name_matches(tag_names, LONG_TERM_HOLD_KEYWORDS) or _name_matches(
        group_names, LONG_TERM_HOLD_KEYWORDS
    ):
        score -= 15
        reasons.append("Tagged/grouped as long-term hold")

    return max(SCORE_MIN, min(SCORE_MAX, score)), reasons


def _recommended_action(
    *,
    missing_cost_basis: bool,
    missing_current_value: bool,
    has_active_grading: bool,
    above_target_sell: bool,
    score: int,
    long_term_hold: bool,
    wishlist_high_priority: bool,
) -> SellDecisionAction:
    # First-match-wins, same convention as
    # app.services.opportunity_scoring._category_for - the order below is
    # the priority order the spec lists the action rules in.
    if missing_current_value or missing_cost_basis:
        return "missing_data"
    if has_active_grading:
        return "grade_first"
    if above_target_sell or score >= 70:
        return "review_sell"
    if long_term_hold or wishlist_high_priority or score < 35:
        return "hold"
    return "monitor"


def _opportunities_by_card(
    db: Session, card_ids: set[int]
) -> dict[int, list[OpportunityOut]]:
    opportunities = get_opportunities(db, owned=True, limit=1_000_000, offset=0).opportunities
    by_card: dict[int, list[OpportunityOut]] = {}
    for opp in opportunities:
        if opp.card_id is not None and opp.card_id in card_ids:
            by_card.setdefault(opp.card_id, []).append(opp)
    return by_card


def get_sell_decision_support(
    db: Session,
    *,
    user_id: int,
    valuation_mode: ValuationMode = "raw_market",
    include_sold: bool = False,
    min_score: int | None = None,
    action: SellDecisionAction | None = None,
    limit: int = 100,
    offset: int = 0,
) -> SellDecisionSupportOut:
    status_by_item_id = dict(
        db.execute(
            select(CollectionItem.id, CollectionItem.status).where(CollectionItem.user_id == user_id)
        ).all()
    )

    # Always fetched in graded_adjusted mode - same convention as
    # collection_analytics.get_collection_analytics - so both the raw
    # (market_floor/retail) and graded-adjusted figures are populated on
    # every item regardless of the caller's requested valuation_mode.
    portfolio = get_portfolio_valuation(db, user_id=user_id, valuation_mode="graded_adjusted")

    items = [
        item
        for item in portfolio.items
        if include_sold or status_by_item_id.get(item.collection_item_id) != "sold"
    ]

    card_ids = {item.card_id for item in items}
    wishlist_by_card = _best_wishlist_item_by_card(
        get_wishlist_items(db, user_id, limit=1_000_000, offset=0).items
    )
    opportunities_by_card = _opportunities_by_card(db, card_ids)

    candidates: list[SellDecisionCandidateOut] = []

    for item in items:
        status = status_by_item_id.get(item.collection_item_id, "hold")

        current_value_jpy, current_value_basis = _current_value_and_basis(item, valuation_mode)

        cost_basis_jpy = item.cost_basis_jpy
        if current_value_jpy is not None and cost_basis_jpy is not None:
            unrealized_pnl_jpy = current_value_jpy - cost_basis_jpy
            unrealized_pnl_pct = _pct(unrealized_pnl_jpy, cost_basis_jpy)
        else:
            unrealized_pnl_jpy = unrealized_pnl_pct = None

        yuyutei_sell = (
            item.latest_prices.yuyutei_sell.price_jpy if item.latest_prices.yuyutei_sell is not None else None
        )
        yuyutei_buy = (
            item.latest_prices.yuyutei_buy.price_jpy if item.latest_prices.yuyutei_buy is not None else None
        )
        snkrdunk_floor = (
            item.latest_prices.snkrdunk_floor.price_jpy
            if item.latest_prices.snkrdunk_floor is not None
            else None
        )

        yuyutei_spread_pct = (
            _pct(yuyutei_sell - yuyutei_buy, yuyutei_sell)
            if yuyutei_sell is not None and yuyutei_buy is not None
            else None
        )
        snkrdunk_vs_yuyutei_sell_gap_pct = (
            _pct(snkrdunk_floor - yuyutei_sell, yuyutei_sell)
            if snkrdunk_floor is not None and yuyutei_sell is not None
            else None
        )

        card_opportunities = opportunities_by_card.get(item.card_id, [])
        related_opportunity_score = (
            max(opp.score for opp in card_opportunities) if card_opportunities else None
        )
        related_signal_types = sorted({opp.signal_type for opp in card_opportunities})
        has_review_sell_opportunity = any(
            opp.suggested_action == "review_sell_opportunity" for opp in card_opportunities
        )

        wishlist_item = wishlist_by_card.get(item.card_id)
        wishlist_priority = wishlist_item.priority if wishlist_item is not None else None
        wishlist_status = wishlist_item.status if wishlist_item is not None else None

        tag_names = [tag.name for tag in item.tags]
        group_names = [group.name for group in item.groups]

        has_active_grading = (
            item.grading.has_grading_submission and item.grading.latest_status in ACTIVE_GRADING_STATUSES
        )
        long_term_hold = _name_matches(tag_names, LONG_TERM_HOLD_KEYWORDS) or _name_matches(
            group_names, LONG_TERM_HOLD_KEYWORDS
        )

        score, score_reasons = _score_candidate(
            item=item,
            status=status,
            current_value_jpy=current_value_jpy,
            unrealized_pnl_pct=unrealized_pnl_pct,
            yuyutei_spread_pct=yuyutei_spread_pct,
            snkrdunk_vs_yuyutei_sell_gap_pct=snkrdunk_vs_yuyutei_sell_gap_pct,
            has_review_sell_opportunity=has_review_sell_opportunity,
            related_opportunity_score=related_opportunity_score,
            wishlist_priority=wishlist_priority,
            tag_names=tag_names,
            group_names=group_names,
        )

        recommended_action = _recommended_action(
            missing_cost_basis=cost_basis_jpy is None,
            missing_current_value=current_value_jpy is None,
            has_active_grading=has_active_grading,
            above_target_sell=item.flags.above_target_sell,
            score=score,
            long_term_hold=long_term_hold,
            wishlist_high_priority=wishlist_priority in HIGH_PRIORITY_WISHLIST,
        )

        warnings: list[str] = []
        if cost_basis_jpy is None:
            warnings.append("Missing cost basis")
        if current_value_jpy is None:
            warnings.append("Missing current value")

        candidates.append(
            SellDecisionCandidateOut(
                collection_item_id=item.collection_item_id,
                card_id=item.card_id,
                card_code=item.card_code,
                name_en=item.name_en,
                name_jp=item.name_jp,
                set_code=item.set_code,
                rarity=item.rarity,
                variant=item.variant,
                language=item.language,
                quantity=item.quantity,
                status=status,
                condition_label=item.condition_label,
                score=score,
                recommended_action=recommended_action,
                current_value_jpy=current_value_jpy,
                current_value_basis=current_value_basis,
                cost_basis_jpy=cost_basis_jpy,
                unrealized_pnl_jpy=unrealized_pnl_jpy,
                unrealized_pnl_pct=unrealized_pnl_pct,
                target_sell_price_jpy=item.target_sell_price_jpy,
                above_target_sell=item.flags.above_target_sell,
                latest_prices=SellDecisionLatestPricesOut(
                    yuyutei_sell=yuyutei_sell, yuyutei_buy=yuyutei_buy, snkrdunk_floor=snkrdunk_floor
                ),
                market_context=SellDecisionMarketContextOut(
                    yuyutei_spread_pct=yuyutei_spread_pct,
                    snkrdunk_vs_yuyutei_sell_gap_pct=snkrdunk_vs_yuyutei_sell_gap_pct,
                    related_opportunity_score=related_opportunity_score,
                    related_signal_types=related_signal_types,
                ),
                grading=SellDecisionGradingOut(
                    has_active_grading=has_active_grading,
                    latest_status=item.grading.latest_status,
                    final_grade=item.grading.final_grade,
                    graded_value_jpy=item.grading.graded_value_jpy,
                ),
                wishlist_overlap=SellDecisionWishlistOverlapOut(
                    is_on_wishlist=wishlist_item is not None,
                    priority=wishlist_priority,
                    status=wishlist_status,
                ),
                tags=tag_names,
                groups=group_names,
                score_reasons=score_reasons,
                warnings=warnings,
            )
        )

    if min_score is not None:
        candidates = [c for c in candidates if c.score >= min_score]
    if action is not None:
        candidates = [c for c in candidates if c.recommended_action == action]

    candidates.sort(key=lambda c: (-c.score, c.collection_item_id))

    total_candidates = len(candidates)
    total_potential_sale_value_jpy = sum(
        c.current_value_jpy or 0 for c in candidates if c.recommended_action == "review_sell"
    )
    total_unrealized_pnl_jpy = sum(c.unrealized_pnl_jpy or 0 for c in candidates)
    average_score = (
        round(sum(c.score for c in candidates) / total_candidates, 1) if total_candidates else 0.0
    )

    summary = SellDecisionSummaryOut(
        total_candidates=total_candidates,
        review_sell_count=sum(1 for c in candidates if c.recommended_action == "review_sell"),
        hold_count=sum(1 for c in candidates if c.recommended_action == "hold"),
        grade_first_count=sum(1 for c in candidates if c.recommended_action == "grade_first"),
        missing_data_count=sum(1 for c in candidates if c.recommended_action == "missing_data"),
        monitor_count=sum(1 for c in candidates if c.recommended_action == "monitor"),
        total_potential_sale_value_jpy=total_potential_sale_value_jpy,
        total_unrealized_pnl_jpy=total_unrealized_pnl_jpy,
        average_score=average_score,
    )

    page = candidates[offset : offset + limit]

    return SellDecisionSupportOut(
        summary=summary,
        candidates=page,
        limit=limit,
        offset=offset,
        pagination=pagination_response(page, total_candidates, limit, offset),
    )
