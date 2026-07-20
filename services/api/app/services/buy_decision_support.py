"""Buy decision support: deterministic scoring that flags wishlist cards
worth reviewing to buy, waiting on, skipping, or monitoring - see GET
/analytics/buy-decisions.

Builds entirely on top of app.services.wishlist.get_wishlist_items (target
price/gap resolution, current-price fallback order, owned-quantity/tag
lookups), app.services.opportunity_scoring.get_opportunities (market signal
context), and app.services.collector.get_groups_for_cards - this module only
combines and scores what those services already compute. It never re-derives
a price or an opportunity score, and every scoring rule below is a fixed,
deterministic point value - there is no AI/LLM involvement and nothing here
places or automates an actual purchase.

Design note on the "market opportunity score >= 70" bonus: the spec lists it
as a single, unqualified bullet, but its own worked example (target hit +
grail priority + SNKRDUNK-below-Yuyu-Tei = 40+25+20 = 85, matching the
example's score exactly) only reconciles if that bonus does *not* fire, even
though the example's `related_opportunity_score` (informational, any related
opportunity) is 75 - and its `related_signal_types` is empty. The reading
that reproduces both of those exactly is scoring off a *buy-specific*
opportunity score - the max score among this card's opportunities whose
suggested_action is "review_buy_opportunity" - kept separate from the
general `related_opportunity_score` shown in the response, which covers
every related opportunity regardless of type. A sell-oriented or
momentum-oriented signal on a card isn't evidence for buying it, so gating
the bonus (and related_signal_types) this way also matches the feature's own
intent, not just the arithmetic.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.pagination import pagination_response
from app.schemas import (
    BuyDecisionAction,
    BuyDecisionCandidateOut,
    BuyDecisionLatestPricesOut,
    BuyDecisionMarketContextOut,
    BuyDecisionPriorityFilter,
    BuyDecisionSummaryOut,
    BuyDecisionSupportOut,
    BuySourcePreference,
    OpportunityOut,
    WishlistItemOut,
)
from app.services.collector import get_groups_for_cards
from app.services.opportunity_scoring import get_opportunities
from app.services.wishlist import compute_gap_to_target, compute_target_hit, get_wishlist_items

HIGH_PRIORITY_SCORE = {"grail": 25, "high": 15, "medium": 5}
HIGH_PRIORITY_REASON = {
    "grail": "Grail priority",
    "high": "High priority",
    "medium": "Medium priority",
}

GRAIL_KEYWORDS = ("grail",)
AVOID_SKIP_KEYWORDS = ("avoid", "skip")


def _pct(numerator: int, denominator: int) -> float | None:
    """Same rounding/None-on-zero-denominator convention duplicated across
    every analytics service in this app - a generic percent-rounding
    utility, not a valuation formula."""
    if not denominator:
        return None
    return round(numerator / denominator * 100, 2)


def _gap_to_max(
    current_price_jpy: int | None, max_buy_price_jpy: int | None
) -> tuple[int | None, float | None]:
    """Same shape as app.services.wishlist.compute_gap_to_target but against
    max_buy_price_jpy instead of target_buy_price_jpy - no equivalent helper
    exists yet for "max" since only wishlist_analytics/wishlist needed
    target-price gaps before this feature."""
    if current_price_jpy is None or max_buy_price_jpy is None:
        return None, None
    gap_jpy = current_price_jpy - max_buy_price_jpy
    gap_pct = _pct(gap_jpy, max_buy_price_jpy)
    return gap_jpy, gap_pct


def _resolve_current_price(
    item: WishlistItemOut, source_preference: BuySourcePreference
) -> tuple[int | None, str | None]:
    """auto reuses the wishlist item's own already-resolved preferred price
    (preferred_source first, then SNKRDUNK floor, then Yuyu-Tei sell - see
    app.services.wishlist.resolve_preferred_current_price, which computed
    this field on `item` already) rather than re-deriving that fallback
    order. snkrdunk/yuyutei force a specific series regardless of the
    item's own preferred_source."""
    if source_preference == "auto":
        return item.preferred_current_price_jpy, item.preferred_current_price_source
    if source_preference == "snkrdunk":
        floor = item.latest_prices.snkrdunk_floor
        return (floor, "snkrdunk_floor") if floor is not None else (None, None)
    sell = item.latest_prices.yuyutei_sell
    return (sell, "yuyutei_sell") if sell is not None else (None, None)


def _name_matches(names: list[str], keywords: tuple[str, ...]) -> bool:
    return any(keyword in name.lower() for name in names for keyword in keywords)


def _score_candidate(
    *,
    item: WishlistItemOut,
    current_price_jpy: int | None,
    target_hit: bool,
    yuyutei_spread_pct: float | None,
    snkrdunk_vs_yuyutei_sell_gap_pct: float | None,
    has_price_down_7d: bool,
    has_price_down_30d: bool,
    buy_opportunity_score: int | None,
    owned_fulfilled: bool,
    tag_names: list[str],
    group_names: list[str],
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if target_hit:
        score += 40
        reasons.append("Wishlist target hit")

    priority_bonus = HIGH_PRIORITY_SCORE.get(item.priority)
    if priority_bonus:
        score += priority_bonus
        reasons.append(HIGH_PRIORITY_REASON[item.priority])

    if snkrdunk_vs_yuyutei_sell_gap_pct is not None and snkrdunk_vs_yuyutei_sell_gap_pct <= -10:
        score += 20
        reasons.append("SNKRDUNK floor below Yuyu-Tei sell")

    if yuyutei_spread_pct is not None and yuyutei_spread_pct <= 20:
        score += 10
        reasons.append("Compressed Yuyu-Tei spread")

    if has_price_down_7d:
        score += 10
        reasons.append("Price down over 7 days")

    if has_price_down_30d:
        score += 15
        reasons.append("Price down over 30 days")

    if buy_opportunity_score is not None and buy_opportunity_score >= 70:
        score += 15
        reasons.append("High related buy opportunity score")

    if owned_fulfilled:
        score -= 30
        reasons.append("Already owned desired quantity")

    if item.status == "purchased":
        score -= 40
        reasons.append("Already purchased")

    if item.status == "passed":
        score -= 20
        reasons.append("Passed")

    if current_price_jpy is None:
        score -= 35
        reasons.append("Missing current price")

    if item.target_buy_price_jpy is None:
        score -= 10
        reasons.append("Missing target buy price")

    if _name_matches(tag_names, GRAIL_KEYWORDS) or _name_matches(group_names, GRAIL_KEYWORDS):
        score += 10
        reasons.append("Tagged/grouped as grail")

    if _name_matches(tag_names, AVOID_SKIP_KEYWORDS) or _name_matches(group_names, AVOID_SKIP_KEYWORDS):
        score -= 25
        reasons.append("Tagged/grouped avoid/skip")

    return max(0, min(100, score)), reasons


def _recommended_action(
    *,
    missing_current_price: bool,
    status: str,
    include_purchased: bool,
    owned_fulfilled: bool,
    include_owned: bool,
    target_hit: bool,
    score: int,
    current_price_jpy: int | None,
    max_buy_price_jpy: int | None,
) -> BuyDecisionAction:
    # First-match-wins, in the priority order the spec lists the action
    # rules in.
    if missing_current_price:
        return "missing_data"
    if status == "passed" or (status == "purchased" and include_purchased):
        return "skip"
    if owned_fulfilled and not include_owned:
        return "skip"
    if target_hit or score >= 70:
        return "review_buy"
    if max_buy_price_jpy is not None and current_price_jpy is not None and current_price_jpy > max_buy_price_jpy:
        return "wait"
    return "monitor"


def _opportunities_by_card(db: Session, card_ids: set[int]) -> dict[int, list[OpportunityOut]]:
    """Unlike sell_decision_support's equivalent helper, this is not scoped
    to owned=True - wishlist cards are frequently not owned at all (that's
    the point of a buy candidate), so every related opportunity for these
    cards is fetched regardless of ownership."""
    opportunities = get_opportunities(db, limit=1_000_000, offset=0).opportunities
    by_card: dict[int, list[OpportunityOut]] = {}
    for opp in opportunities:
        if opp.card_id is not None and opp.card_id in card_ids:
            by_card.setdefault(opp.card_id, []).append(opp)
    return by_card


def get_buy_decision_support(
    db: Session,
    *,
    user_id: int,
    source_preference: BuySourcePreference = "auto",
    include_owned: bool = False,
    include_purchased: bool = False,
    min_score: int | None = None,
    action: BuyDecisionAction | None = None,
    priority: BuyDecisionPriorityFilter | None = None,
    limit: int = 100,
    offset: int = 0,
) -> BuyDecisionSupportOut:
    all_items = get_wishlist_items(db, user_id, limit=1_000_000, offset=0).items

    # "removed" wishlist entries are a terminal, opted-out state with no
    # corresponding include flag (unlike purchased/owned-fulfilled) - they
    # never surface as buy candidates. Purchased/owned-fulfilled are
    # excluded by default but can be turned back on.
    items = [
        item
        for item in all_items
        if item.status != "removed"
        and (include_purchased or item.status != "purchased")
        and (include_owned or item.owned_quantity < item.desired_quantity)
    ]

    card_ids = {item.card_id for item in items}
    opportunities_by_card = _opportunities_by_card(db, card_ids)
    groups_by_card = get_groups_for_cards(db, card_ids)

    candidates: list[BuyDecisionCandidateOut] = []

    for item in items:
        current_price_jpy, current_price_source = _resolve_current_price(item, source_preference)

        target_hit = compute_target_hit(item.target_buy_price_jpy, current_price_jpy)
        gap_to_target_jpy, gap_to_target_pct = compute_gap_to_target(
            current_price_jpy, item.target_buy_price_jpy
        )
        gap_to_max_jpy, gap_to_max_pct = _gap_to_max(current_price_jpy, item.max_buy_price_jpy)

        yuyutei_sell = item.latest_prices.yuyutei_sell
        yuyutei_buy = item.latest_prices.yuyutei_buy
        snkrdunk_floor = item.latest_prices.snkrdunk_floor

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
        buy_opportunities = [
            opp for opp in card_opportunities if opp.suggested_action == "review_buy_opportunity"
        ]
        buy_opportunity_score = max((opp.score for opp in buy_opportunities), default=None)
        related_signal_types = sorted({opp.signal_type for opp in buy_opportunities})
        has_price_down_7d = any(opp.signal_type == "price_down_7d" for opp in card_opportunities)
        has_price_down_30d = any(opp.signal_type == "price_down_30d" for opp in card_opportunities)

        owned_fulfilled = item.owned_quantity >= item.desired_quantity
        remaining_quantity = max(item.desired_quantity - item.acquired_quantity - item.owned_quantity, 0)

        tag_names = [tag.name for tag in item.tags]
        group_names = [group.name for group in groups_by_card.get(item.card_id, [])]

        score, score_reasons = _score_candidate(
            item=item,
            current_price_jpy=current_price_jpy,
            target_hit=target_hit,
            yuyutei_spread_pct=yuyutei_spread_pct,
            snkrdunk_vs_yuyutei_sell_gap_pct=snkrdunk_vs_yuyutei_sell_gap_pct,
            has_price_down_7d=has_price_down_7d,
            has_price_down_30d=has_price_down_30d,
            buy_opportunity_score=buy_opportunity_score,
            owned_fulfilled=owned_fulfilled,
            tag_names=tag_names,
            group_names=group_names,
        )

        recommended_action = _recommended_action(
            missing_current_price=current_price_jpy is None,
            status=item.status,
            include_purchased=include_purchased,
            owned_fulfilled=owned_fulfilled,
            include_owned=include_owned,
            target_hit=target_hit,
            score=score,
            current_price_jpy=current_price_jpy,
            max_buy_price_jpy=item.max_buy_price_jpy,
        )

        warnings: list[str] = []
        if current_price_jpy is None:
            warnings.append("Missing current price")
        if item.target_buy_price_jpy is None:
            warnings.append("Missing target buy price")

        candidates.append(
            BuyDecisionCandidateOut(
                wishlist_item_id=item.id,
                card_id=item.card_id,
                card_code=item.card_code,
                name_en=item.name_en,
                name_jp=item.name_jp,
                set_code=item.set_code,
                rarity=item.rarity,
                variant=item.variant,
                language=item.language,
                score=score,
                recommended_action=recommended_action,
                priority=item.priority,
                status=item.status,
                desired_quantity=item.desired_quantity,
                owned_quantity=item.owned_quantity,
                remaining_quantity=remaining_quantity,
                target_buy_price_jpy=item.target_buy_price_jpy,
                max_buy_price_jpy=item.max_buy_price_jpy,
                preferred_condition=item.preferred_condition,
                preferred_source=item.preferred_source,
                current_price_jpy=current_price_jpy,
                current_price_source=current_price_source,
                target_hit=target_hit,
                gap_to_target_jpy=gap_to_target_jpy,
                gap_to_target_pct=gap_to_target_pct,
                gap_to_max_jpy=gap_to_max_jpy,
                gap_to_max_pct=gap_to_max_pct,
                latest_prices=BuyDecisionLatestPricesOut(
                    yuyutei_sell=yuyutei_sell, yuyutei_buy=yuyutei_buy, snkrdunk_floor=snkrdunk_floor
                ),
                market_context=BuyDecisionMarketContextOut(
                    snkrdunk_vs_yuyutei_sell_gap_pct=snkrdunk_vs_yuyutei_sell_gap_pct,
                    yuyutei_spread_pct=yuyutei_spread_pct,
                    related_opportunity_score=related_opportunity_score,
                    related_signal_types=related_signal_types,
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
    if priority is not None:
        candidates = [c for c in candidates if c.priority == priority]

    candidates.sort(key=lambda c: (-c.score, c.wishlist_item_id))

    total_candidates = len(candidates)
    total_target_budget_jpy = sum(
        c.target_buy_price_jpy * c.remaining_quantity for c in candidates if c.target_buy_price_jpy is not None
    )
    total_current_cost_jpy = sum(
        c.current_price_jpy * c.remaining_quantity for c in candidates if c.current_price_jpy is not None
    )
    average_score = (
        round(sum(c.score for c in candidates) / total_candidates, 1) if total_candidates else 0.0
    )

    summary = BuyDecisionSummaryOut(
        total_candidates=total_candidates,
        review_buy_count=sum(1 for c in candidates if c.recommended_action == "review_buy"),
        wait_count=sum(1 for c in candidates if c.recommended_action == "wait"),
        skip_count=sum(1 for c in candidates if c.recommended_action == "skip"),
        missing_data_count=sum(1 for c in candidates if c.recommended_action == "missing_data"),
        monitor_count=sum(1 for c in candidates if c.recommended_action == "monitor"),
        target_hit_count=sum(1 for c in candidates if c.target_hit),
        total_target_budget_jpy=total_target_budget_jpy,
        total_current_cost_jpy=total_current_cost_jpy,
        budget_gap_jpy=total_current_cost_jpy - total_target_budget_jpy,
        average_score=average_score,
    )

    page = candidates[offset : offset + limit]

    return BuyDecisionSupportOut(
        summary=summary,
        candidates=page,
        limit=limit,
        offset=offset,
        pagination=pagination_response(page, total_candidates, limit, offset),
    )
