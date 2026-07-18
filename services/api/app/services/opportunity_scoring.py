"""Ranks persisted market_signal_events by an opportunity score, so review
effort naturally goes toward the cards most worth a second look. Reuses
market_signal_events as the sole source of truth (see
app/services/market_signal_events.py) - this module computes no new prices
and does no scraping, it only weighs and sorts events that already exist.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.pagination import pagination_response
from app.models import Card, CollectionItem, CollectorGroup, CollectorTag, MarketSignalEvent, WishlistItem
from app.schemas import OpportunitiesResponseOut, OpportunitiesSummaryOut, OpportunityOut
from app.services.collector import get_groups_for_cards, get_tags_for_cards
from app.services.grading import build_grading_info, get_submissions_for_cards, latest_submission

# Dismissed/resolved events are noise for a "what should I look at" ranking -
# a user already acted on them or they no longer apply.
INCLUDED_STATUSES = ("open", "watching")

CATEGORIES = ("buy", "sell", "momentum", "drop", "data_quality", "owned")

DATA_QUALITY_ACTIONS = ("review_mapping", "update_prices")

BASE_SCORE_BY_ACTION: dict[str, int] = {
    "review_buy_opportunity": 60,
    "review_sell_opportunity": 65,
    "monitor_momentum": 50,
    "monitor_drop": 45,
    "review_mapping": 30,
    "update_prices": 25,
    "add_collection_target": 20,
    "none": 10,
}

BASE_SCORE_REASON_BY_ACTION: dict[str, str] = {
    "review_buy_opportunity": "buy opportunity base score",
    "review_sell_opportunity": "sell opportunity base score",
    "monitor_momentum": "momentum base score",
    "monitor_drop": "drop base score",
    "review_mapping": "mapping review base score",
    "update_prices": "price update base score",
    "add_collection_target": "collection target base score",
    "none": "baseline score",
}

DEFAULT_BASE_SCORE = 10
DEFAULT_BASE_SCORE_REASON = "baseline score"

SIGNAL_TYPE_MODIFIERS: dict[str, int] = {
    "snkrdunk_floor_below_yuyutei_sell": 20,
    "snkrdunk_floor_above_yuyutei_sell": 15,
    "yuyutei_buy_sell_spread_compressed": 15,
    "yuyutei_buy_sell_spread_wide": 10,
    "price_up_7d": 12,
    "price_up_30d": 10,
    "price_down_7d": 8,
    "price_down_30d": 8,
    "owned_above_target_sell": 25,
    "owned_below_cost_basis": 15,
    "missing_recent_price": -10,
    "stale_mapping_price": -5,
    "wishlist_target_hit": 30,
}

SIGNAL_TYPE_REASONS: dict[str, str] = {
    "snkrdunk_floor_below_yuyutei_sell": "SNKRDUNK floor below Yuyu-Tei sell",
    "snkrdunk_floor_above_yuyutei_sell": "SNKRDUNK floor above Yuyu-Tei sell",
    "yuyutei_buy_sell_spread_compressed": "Yuyu-Tei buy/sell spread compressed",
    "yuyutei_buy_sell_spread_wide": "Yuyu-Tei buy/sell spread wide",
    "price_up_7d": "price up over 7 days",
    "price_up_30d": "price up over 30 days",
    "price_down_7d": "price down over 7 days",
    "price_down_30d": "price down over 30 days",
    "owned_above_target_sell": "owned card above target sell price",
    "owned_below_cost_basis": "owned card below cost basis",
    "missing_recent_price": "missing recent price data",
    "stale_mapping_price": "stale mapping price data",
    "wishlist_target_hit": "wishlist target hit",
}

# Applied to ANY opportunity for a wishlisted card, not just wishlist_target_hit
# signals - a grail/high-priority card is worth surfacing more prominently
# across all its opportunities (e.g. a plain buy-opportunity signal on a
# grail card), not only when its specific target price is hit.
WISHLIST_PRIORITY_MODIFIERS: dict[str, int] = {"grail": 20, "high": 10}


def _category_for(event: MarketSignalEvent, owned_quantity: int) -> str:
    """First-match-wins over the categories in the order given by the spec.
    "owned" is a catch-all for owned cards (or owned_* signal types) that
    didn't already match a more specific action-based category above it -
    most owned_* signals already carry a review_sell_opportunity or
    monitor_drop suggested_action and are categorized by that instead."""
    action = event.suggested_action
    if action == "review_buy_opportunity":
        return "buy"
    if action == "review_sell_opportunity":
        return "sell"
    if action == "monitor_momentum":
        return "momentum"
    if action == "monitor_drop":
        return "drop"
    if action in DATA_QUALITY_ACTIONS:
        return "data_quality"
    if owned_quantity > 0 or event.signal_type.startswith("owned_"):
        return "owned"
    return "other"


def _metric_strength_modifier(last_payload: dict[str, Any] | None) -> tuple[int, str | None]:
    if not last_payload:
        return 0, None
    metrics = last_payload.get("metrics") or {}
    value = metrics.get("gap_pct")
    if value is None:
        value = metrics.get("change_pct")
    if value is None:
        return 0, None

    abs_value = abs(value)
    if abs_value >= 40:
        return 15, f"strong metric movement ({abs_value:.2f}%)"
    if abs_value >= 20:
        return 10, f"notable metric movement ({abs_value:.2f}%)"
    if abs_value >= 10:
        return 5, f"metric movement ({abs_value:.2f}%)"
    return 0, None


@dataclass
class _ScoredEvent:
    event: MarketSignalEvent
    card: Card | None
    owned_quantity: int
    score: int
    category: str
    reasons: list[str]
    wishlist_item: WishlistItem | None = None
    wishlist_target_hit: bool = False


def _score_event(
    event: MarketSignalEvent,
    card: Card | None,
    owned_quantity: int,
    wishlist_item: WishlistItem | None = None,
) -> _ScoredEvent:
    action = event.suggested_action or "none"
    reasons: list[str] = []

    score = BASE_SCORE_BY_ACTION.get(action, DEFAULT_BASE_SCORE)
    reasons.append(BASE_SCORE_REASON_BY_ACTION.get(action, DEFAULT_BASE_SCORE_REASON))

    signal_modifier = SIGNAL_TYPE_MODIFIERS.get(event.signal_type, 0)
    if signal_modifier:
        score += signal_modifier
        reasons.append(SIGNAL_TYPE_REASONS.get(event.signal_type, event.signal_type))

    if wishlist_item is not None:
        wishlist_modifier = WISHLIST_PRIORITY_MODIFIERS.get(wishlist_item.priority, 0)
        if wishlist_modifier:
            score += wishlist_modifier
            reasons.append(f"wishlist priority: {wishlist_item.priority}")

    if owned_quantity > 0:
        score += 10
        reasons.append("owned card")

    if event.seen_count >= 7:
        score += 10
        reasons.append("highly recurring signal")
    elif event.seen_count >= 3:
        score += 5
        reasons.append("recurring signal")

    if event.status == "watching":
        score += 10
        reasons.append("being watched")

    if event.severity == "critical":
        score += 10
        reasons.append("critical severity")
    elif event.severity == "warning":
        score += 5
        reasons.append("warning severity")

    metric_modifier, metric_reason = _metric_strength_modifier(event.last_payload_json)
    if metric_modifier:
        score += metric_modifier
        if metric_reason:
            reasons.append(metric_reason)

    score = max(0, min(100, score))
    category = _category_for(event, owned_quantity)

    return _ScoredEvent(
        event=event,
        card=card,
        owned_quantity=owned_quantity,
        score=score,
        category=category,
        reasons=reasons,
        wishlist_item=wishlist_item,
    )


def _to_out(
    scored: _ScoredEvent,
    tags_by_card: dict[int, list[CollectorTag]],
    groups_by_card: dict[int, list[CollectorGroup]],
    grading_by_card: dict[int, list],
) -> OpportunityOut:
    event = scored.event
    card = scored.card
    # Tags/groups/grading are a collector-organization concept over what's
    # owned - deliberately left empty for unowned cards rather than showing
    # card-level tags regardless of ownership.
    owned = scored.owned_quantity > 0
    tags = tags_by_card.get(event.card_id, []) if owned and event.card_id is not None else []
    groups = groups_by_card.get(event.card_id, []) if owned and event.card_id is not None else []
    grading = (
        build_grading_info(latest_submission(grading_by_card, event.card_id))
        if owned and event.card_id is not None
        else build_grading_info(None)
    )
    return OpportunityOut(
        score=scored.score,
        category=scored.category,
        event_id=event.id,
        signal_type=event.signal_type,
        status=event.status,
        severity=event.severity,
        suggested_action=event.suggested_action,
        card_id=event.card_id,
        card_code=card.card_code if card is not None else None,
        name_en=card.name_en if card is not None else None,
        name_jp=card.name_jp if card is not None else None,
        set_code=card.set_code if card is not None else None,
        rarity=card.rarity if card is not None else None,
        variant=card.variant if card is not None else None,
        language=card.language if card is not None else None,
        owned_quantity=scored.owned_quantity,
        message=event.message,
        first_seen_at=event.first_seen_at,
        last_seen_at=event.last_seen_at,
        seen_count=event.seen_count,
        score_reasons=scored.reasons,
        last_payload=event.last_payload_json,
        tags=tags,
        groups=groups,
        grading=grading,
        wishlist_item_id=scored.wishlist_item.id if scored.wishlist_item is not None else None,
        wishlist_priority=scored.wishlist_item.priority if scored.wishlist_item is not None else None,
        wishlist_target_buy_price_jpy=(
            scored.wishlist_item.target_buy_price_jpy if scored.wishlist_item is not None else None
        ),
        wishlist_target_hit=scored.wishlist_target_hit,
    )


_WISHLIST_PRIORITY_RANK = {"grail": 3, "high": 2, "medium": 1, "low": 0}


def _best_wishlist_item_by_card(wishlist_items: list[WishlistItem]) -> dict[int, WishlistItem]:
    """Picks one representative wishlist item per card (highest priority,
    ties broken by lowest id) - a card can have several non-removed wishlist
    entries (different conditions/sources, or across different people), but
    the opportunities view surfaces just one set of wishlist metadata per
    card, same simplification as market_signals.py's wishlist_target_hit
    signal."""
    best: dict[int, WishlistItem] = {}
    for item in wishlist_items:
        current = best.get(item.card_id)
        if current is None or (
            _WISHLIST_PRIORITY_RANK.get(item.priority, 0)
            > _WISHLIST_PRIORITY_RANK.get(current.priority, 0)
        ):
            best[item.card_id] = item
    return best


def _empty_response(limit: int, offset: int) -> OpportunitiesResponseOut:
    return OpportunitiesResponseOut(
        summary=OpportunitiesSummaryOut(
            total_opportunities=0,
            average_score=0,
            highest_score=0,
            by_category={c: 0 for c in CATEGORIES},
        ),
        opportunities=[],
        limit=limit,
        offset=offset,
        pagination=pagination_response([], 0, limit, offset),
    )


def get_opportunities(
    db: Session,
    category: str | None = None,
    owned: bool | None = None,
    set_code: str | None = None,
    rarity: str | None = None,
    min_score: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> OpportunitiesResponseOut:
    status_filter = MarketSignalEvent.status.in_(INCLUDED_STATUSES)

    query = select(MarketSignalEvent)
    if set_code is not None or rarity is not None:
        card_filters = []
        if set_code is not None:
            card_filters.append(Card.set_code == set_code)
        if rarity is not None:
            card_filters.append(Card.rarity == rarity)
        query = query.join(Card, MarketSignalEvent.card_id == Card.id).where(
            status_filter, *card_filters
        )
    else:
        query = query.where(status_filter)

    events = db.scalars(query).all()
    if not events:
        return _empty_response(limit, offset)

    card_ids = {e.card_id for e in events if e.card_id is not None}
    cards_by_id: dict[int, Card] = {}
    owned_quantities: dict[int, int] = {}
    wishlist_by_card: dict[int, WishlistItem] = {}
    if card_ids:
        cards_by_id = {
            c.id: c for c in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()
        }
        rows = db.execute(
            select(CollectionItem.card_id, func.sum(CollectionItem.quantity))
            .where(CollectionItem.card_id.in_(card_ids))
            .group_by(CollectionItem.card_id)
        ).all()
        owned_quantities = {cid: int(qty or 0) for cid, qty in rows}
        wishlist_by_card = _best_wishlist_item_by_card(
            db.scalars(
                select(WishlistItem).where(
                    WishlistItem.card_id.in_(card_ids), WishlistItem.status != "removed"
                )
            ).all()
        )

    # Not scoped to a single user - this admin-facing ranking view surfaces
    # whichever wishlist item(s) exist for a card across everyone using this
    # deployment, same as owned_quantity's cross-user aggregate above.
    wishlist_target_hit_card_ids = {
        e.card_id for e in events if e.signal_type == "wishlist_target_hit" and e.card_id is not None
    }

    owned_card_ids = {cid for cid, qty in owned_quantities.items() if qty > 0}
    tags_by_card = get_tags_for_cards(db, owned_card_ids)
    groups_by_card = get_groups_for_cards(db, owned_card_ids)
    grading_by_card = get_submissions_for_cards(db, owned_card_ids)

    scored = [
        _score_event(
            e, cards_by_id.get(e.card_id), owned_quantities.get(e.card_id, 0), wishlist_by_card.get(e.card_id)
        )
        for e in events
    ]
    for s in scored:
        s.wishlist_target_hit = s.event.card_id in wishlist_target_hit_card_ids

    if owned is not None:
        scored = [s for s in scored if (s.owned_quantity > 0) == owned]
    if category is not None:
        scored = [s for s in scored if s.category == category]
    if min_score is not None:
        scored = [s for s in scored if s.score >= min_score]

    scored.sort(key=lambda s: (s.score, s.event.last_seen_at), reverse=True)

    total_opportunities = len(scored)
    by_category = {c: 0 for c in CATEGORIES}
    for s in scored:
        if s.category in by_category:
            by_category[s.category] += 1

    average_score = (
        round(sum(s.score for s in scored) / total_opportunities, 1)
        if total_opportunities
        else 0
    )
    highest_score = max((s.score for s in scored), default=0)
    wishlist_target_hit_count = sum(1 for s in scored if s.wishlist_target_hit)

    summary = OpportunitiesSummaryOut(
        total_opportunities=total_opportunities,
        average_score=average_score,
        highest_score=highest_score,
        by_category=by_category,
        wishlist_target_hit_count=wishlist_target_hit_count,
    )

    page = scored[offset : offset + limit]
    page_out = [_to_out(s, tags_by_card, groups_by_card, grading_by_card) for s in page]
    return OpportunitiesResponseOut(
        summary=summary,
        opportunities=page_out,
        limit=limit,
        offset=offset,
        pagination=pagination_response(page_out, total_opportunities, limit, offset),
    )
