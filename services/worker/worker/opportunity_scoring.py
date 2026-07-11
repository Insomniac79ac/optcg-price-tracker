"""Ranks persisted market_signal_events by an opportunity score. Mirrors
services/api/app/services/opportunity_scoring.py's formulas exactly (the
worker has no shared code with the api service - see worker/models.py,
which already duplicates the api's ORM models table-for-table). This copy
returns plain dataclasses instead of the api's Pydantic OpportunityOut,
since the worker only needs this to build market intelligence reports, not
serve an HTTP response - `Opportunity.to_dict()` produces the same JSON
shape as the api's OpportunityOut.model_dump(mode="json") though, so a
report looks identical regardless of which side generated it.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from worker.models import Card, CollectionItem, MarketSignalEvent

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
}


def _category_for(event: MarketSignalEvent, owned_quantity: int) -> str:
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
class Opportunity:
    score: int
    category: str
    event_id: int
    signal_type: str
    status: str
    severity: str
    suggested_action: str | None
    card_id: int | None
    card_code: str | None
    name_en: str | None
    name_jp: str | None
    set_code: str | None
    rarity: str | None
    variant: str | None
    language: str | None
    owned_quantity: int
    message: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    seen_count: int
    score_reasons: list[str]
    last_payload: dict[str, Any] | None = field(default=None)

    def to_dict(self) -> dict[str, Any]:
        """Same JSON shape as the api's OpportunityOut.model_dump(mode='json')."""
        return {
            "score": self.score,
            "category": self.category,
            "event_id": self.event_id,
            "signal_type": self.signal_type,
            "status": self.status,
            "severity": self.severity,
            "suggested_action": self.suggested_action,
            "card_id": self.card_id,
            "card_code": self.card_code,
            "name_en": self.name_en,
            "name_jp": self.name_jp,
            "set_code": self.set_code,
            "rarity": self.rarity,
            "variant": self.variant,
            "language": self.language,
            "owned_quantity": self.owned_quantity,
            "message": self.message,
            "first_seen_at": self.first_seen_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
            "seen_count": self.seen_count,
            "score_reasons": self.score_reasons,
            "last_payload": self.last_payload,
        }


@dataclass
class OpportunitiesSummary:
    total_opportunities: int
    average_score: float
    highest_score: int
    by_category: dict[str, int]


@dataclass
class OpportunitiesResult:
    summary: OpportunitiesSummary
    opportunities: list[Opportunity]


def _score_and_build(event: MarketSignalEvent, card: Card | None, owned_quantity: int) -> Opportunity:
    action = event.suggested_action or "none"
    reasons: list[str] = []

    score = BASE_SCORE_BY_ACTION.get(action, DEFAULT_BASE_SCORE)
    reasons.append(BASE_SCORE_REASON_BY_ACTION.get(action, DEFAULT_BASE_SCORE_REASON))

    signal_modifier = SIGNAL_TYPE_MODIFIERS.get(event.signal_type, 0)
    if signal_modifier:
        score += signal_modifier
        reasons.append(SIGNAL_TYPE_REASONS.get(event.signal_type, event.signal_type))

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

    return Opportunity(
        score=score,
        category=category,
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
        owned_quantity=owned_quantity,
        message=event.message,
        first_seen_at=event.first_seen_at,
        last_seen_at=event.last_seen_at,
        seen_count=event.seen_count,
        score_reasons=reasons,
        last_payload=event.last_payload_json,
    )


def _empty_result() -> OpportunitiesResult:
    return OpportunitiesResult(
        summary=OpportunitiesSummary(
            total_opportunities=0,
            average_score=0,
            highest_score=0,
            by_category={c: 0 for c in CATEGORIES},
        ),
        opportunities=[],
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
) -> OpportunitiesResult:
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
        return _empty_result()

    card_ids = {e.card_id for e in events if e.card_id is not None}
    cards_by_id: dict[int, Card] = {}
    owned_quantities: dict[int, int] = {}
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

    scored = [
        _score_and_build(e, cards_by_id.get(e.card_id), owned_quantities.get(e.card_id, 0))
        for e in events
    ]

    if owned is not None:
        scored = [s for s in scored if (s.owned_quantity > 0) == owned]
    if category is not None:
        scored = [s for s in scored if s.category == category]
    if min_score is not None:
        scored = [s for s in scored if s.score >= min_score]

    scored.sort(key=lambda s: (s.score, s.last_seen_at), reverse=True)

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

    summary = OpportunitiesSummary(
        total_opportunities=total_opportunities,
        average_score=average_score,
        highest_score=highest_score,
        by_category=by_category,
    )

    page = scored[offset : offset + limit]
    return OpportunitiesResult(summary=summary, opportunities=page)
