"""Builds one deterministic market intelligence report from data already
computed elsewhere - ranked opportunities (worker/opportunity_scoring.py),
portfolio valuation, collection records, and persisted market_signal_events.
Mirrors services/api/app/services/market_report.py's formulas and JSON shape
exactly (the worker has no shared code with the api service - see
worker/models.py, which already duplicates the api's ORM models
table-for-table). No LLM, no new price collection - this only aggregates
and ranks what refresh_prices/collection tracking/opportunity scoring have
already stored.
"""

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from worker.models import (
    Card,
    CollectionItem,
    MarketIntelligenceReport,
    MarketSignalEvent,
    PriceObservation,
    Source,
)
from worker.opportunity_scoring import get_opportunities

# Large enough to cover every currently active signal event in one page - the
# report needs the complete ranked set to pick top-5/top-per-category from,
# not a paginated slice of it.
REPORT_OPPORTUNITY_LIMIT = 10_000

TOP_N_OVERALL = 5

YUYUTEI_SELL = ("yuyutei", "sell")
YUYUTEI_BUY = ("yuyutei", "buy")
SNKRDUNK_FLOOR = ("snkrdunk", "floor")


def _portfolio_snapshot(db: Session) -> dict[str, Any]:
    """Mirrors worker/portfolio_valuation.py's summary formula (which itself
    mirrors services/api/app/services/portfolio_valuation.py) without
    persisting a new snapshot row - refresh_prices.py already creates one
    per refresh, and this must not create a second."""
    items = db.scalars(select(CollectionItem)).all()
    if not items:
        return {
            "total_cost_basis_jpy": 0,
            "retail_value_jpy": 0,
            "liquidation_value_jpy": 0,
            "market_floor_value_jpy": 0,
            "pnl_vs_market_floor_jpy": 0,
            "pnl_vs_market_floor_pct": 0.0,
            "items_missing_cost_basis": 0,
            "items_missing_prices": 0,
            "cards_above_target_sell": 0,
        }

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
    retail_value_total = 0
    liquidation_value_total = 0
    floor_value_total = 0
    items_missing_cost_basis = 0
    items_missing_prices = 0
    cards_above_target_sell = 0

    for item in items:
        card_latest = latest_by_card.get(item.card_id, {})
        yuyutei_sell_obs = card_latest.get(YUYUTEI_SELL)
        yuyutei_buy_obs = card_latest.get(YUYUTEI_BUY)
        snkrdunk_floor_obs = card_latest.get(SNKRDUNK_FLOOR)
        quantity = item.quantity

        cost_basis_jpy = (
            item.purchase_price_jpy * quantity if item.purchase_price_jpy is not None else None
        )
        if cost_basis_jpy is None:
            items_missing_cost_basis += 1
        else:
            total_cost_basis_jpy += cost_basis_jpy

        if yuyutei_sell_obs is not None:
            retail_value_total += yuyutei_sell_obs.price_jpy * quantity
        if yuyutei_buy_obs is not None:
            liquidation_value_total += yuyutei_buy_obs.price_jpy * quantity
        if snkrdunk_floor_obs is not None:
            floor_value_total += snkrdunk_floor_obs.price_jpy * quantity

        # "Missing prices" means no price data at all from any source -
        # distinct from items_missing_cost_basis (which is about the user's
        # own purchase price, not market data).
        if yuyutei_sell_obs is None and yuyutei_buy_obs is None and snkrdunk_floor_obs is None:
            items_missing_prices += 1

        if (
            item.target_sell_price_jpy is not None
            and snkrdunk_floor_obs is not None
            and snkrdunk_floor_obs.price_jpy >= item.target_sell_price_jpy
        ):
            cards_above_target_sell += 1

    pnl_vs_market_floor_jpy = floor_value_total - total_cost_basis_jpy
    pnl_vs_market_floor_pct = (
        round(pnl_vs_market_floor_jpy / total_cost_basis_jpy * 100, 2)
        if total_cost_basis_jpy
        else 0.0
    )

    return {
        "total_cost_basis_jpy": total_cost_basis_jpy,
        "retail_value_jpy": retail_value_total,
        "liquidation_value_jpy": liquidation_value_total,
        "market_floor_value_jpy": floor_value_total,
        "pnl_vs_market_floor_jpy": pnl_vs_market_floor_jpy,
        "pnl_vs_market_floor_pct": pnl_vs_market_floor_pct,
        "items_missing_cost_basis": items_missing_cost_basis,
        "items_missing_prices": items_missing_prices,
        "cards_above_target_sell": cards_above_target_sell,
    }


def _collection_quality(db: Session) -> dict[str, int]:
    items = db.scalars(select(CollectionItem)).all()

    missing_purchase_price_count = sum(1 for i in items if i.purchase_price_jpy is None)
    missing_condition_count = sum(1 for i in items if i.condition_label is None)
    missing_target_sell_count = sum(1 for i in items if i.target_sell_price_jpy is None)

    return {
        "missing_purchase_price_count": missing_purchase_price_count,
        "missing_condition_count": missing_condition_count,
        "missing_target_sell_count": missing_target_sell_count,
        "total_quality_issues": (
            missing_purchase_price_count + missing_condition_count + missing_target_sell_count
        ),
    }


def _signal_event_summary(db: Session) -> dict[str, Any]:
    events = db.scalars(select(MarketSignalEvent)).all()

    signal_type_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    for event in events:
        signal_type_counts[event.signal_type] = signal_type_counts.get(event.signal_type, 0) + 1
        if event.suggested_action:
            action_counts[event.suggested_action] = action_counts.get(event.suggested_action, 0) + 1

    return {
        "open_events": sum(1 for e in events if e.status == "open"),
        "watching_events": sum(1 for e in events if e.status == "watching"),
        "dismissed_events": sum(1 for e in events if e.status == "dismissed"),
        "resolved_events": sum(1 for e in events if e.status == "resolved"),
        "most_common_signal_type": (
            max(signal_type_counts, key=signal_type_counts.get) if signal_type_counts else None
        ),
        "most_common_suggested_action": (
            max(action_counts, key=action_counts.get) if action_counts else None
        ),
    }


def _deterministic_summary_lines(
    top_5: list,
    portfolio_snapshot: dict[str, Any],
    has_collection_items: bool,
    cards_above_target_sell: int,
    by_category: dict[str, int],
) -> list[str]:
    lines: list[str] = []

    if top_5:
        top = top_5[0]
        label = top.card_code or "an unlisted card"
        lines.append(f"Top ranked opportunity: {label} with score {top.score}.")
    else:
        lines.append("No ranked opportunities found.")

    # An empty collection legitimately has a market_floor_value_jpy of 0, not
    # None - guard on has_collection_items too, or this line would report a
    # meaningless "¥0" for a portfolio that doesn't exist yet.
    if has_collection_items and portfolio_snapshot["market_floor_value_jpy"] is not None:
        lines.append(
            f"Portfolio market floor value: ¥{portfolio_snapshot['market_floor_value_jpy']:,}."
        )

    if cards_above_target_sell > 0:
        noun = "card" if cards_above_target_sell == 1 else "cards"
        lines.append(f"{cards_above_target_sell} owned {noun} are above target sell.")

    data_quality_count = by_category.get("data_quality", 0)
    if data_quality_count > 0:
        noun = "issue" if data_quality_count == 1 else "issues"
        lines.append(f"{data_quality_count} data quality {noun} need review.")

    return lines


def build_report_payload(db: Session) -> dict[str, Any]:
    """Pure, deterministic computation - no persistence. Safe on an empty
    collection or empty opportunity set."""
    result = get_opportunities(db, limit=REPORT_OPPORTUNITY_LIMIT)
    opp_summary = result.summary
    all_opportunities = result.opportunities

    total_opportunities = opp_summary.total_opportunities
    highest_score = opp_summary.highest_score if total_opportunities else None
    average_score = opp_summary.average_score if total_opportunities else None

    opportunity_summary = {
        "total_opportunities": total_opportunities,
        "highest_score": highest_score,
        "average_score": average_score,
        "by_category": dict(opp_summary.by_category),
    }

    def _first_of_category(category: str):
        return next((o for o in all_opportunities if o.category == category), None)

    def _dict_or_none(opportunity):
        return opportunity.to_dict() if opportunity is not None else None

    top_5 = all_opportunities[:TOP_N_OVERALL]
    top_opportunities = {
        "top_5": [o.to_dict() for o in top_5],
        "top_buy": _dict_or_none(_first_of_category("buy")),
        "top_sell": _dict_or_none(_first_of_category("sell")),
        "top_momentum": _dict_or_none(_first_of_category("momentum")),
        "top_drop": _dict_or_none(_first_of_category("drop")),
        "top_owned": _dict_or_none(_first_of_category("owned")),
        "top_data_quality": _dict_or_none(_first_of_category("data_quality")),
    }

    has_collection_items = db.scalar(select(CollectionItem.id).limit(1)) is not None
    portfolio = _portfolio_snapshot(db)
    portfolio_snapshot = {
        "total_cost_basis_jpy": portfolio["total_cost_basis_jpy"],
        "retail_value_jpy": portfolio["retail_value_jpy"],
        "liquidation_value_jpy": portfolio["liquidation_value_jpy"],
        "market_floor_value_jpy": portfolio["market_floor_value_jpy"],
        "pnl_vs_market_floor_jpy": portfolio["pnl_vs_market_floor_jpy"],
        "pnl_vs_market_floor_pct": portfolio["pnl_vs_market_floor_pct"],
        "items_missing_cost_basis": portfolio["items_missing_cost_basis"],
        "items_missing_prices": portfolio["items_missing_prices"],
    }

    collection_quality = _collection_quality(db)
    signal_event_summary = _signal_event_summary(db)

    summary = {
        "total_opportunities": total_opportunities,
        "highest_score": highest_score,
        "average_score": average_score,
    }

    deterministic_summary_lines = _deterministic_summary_lines(
        top_5=top_5,
        portfolio_snapshot=portfolio_snapshot,
        has_collection_items=has_collection_items,
        cards_above_target_sell=portfolio["cards_above_target_sell"],
        by_category=opportunity_summary["by_category"],
    )

    return {
        "summary": summary,
        "portfolio_snapshot": portfolio_snapshot,
        "opportunity_summary": opportunity_summary,
        "top_opportunities": top_opportunities,
        "collection_quality": collection_quality,
        "signal_event_summary": signal_event_summary,
        "deterministic_summary_lines": deterministic_summary_lines,
    }


def generate_market_report(
    db: Session, report_date: date | None = None
) -> MarketIntelligenceReport:
    payload = build_report_payload(db)
    effective_date = report_date or datetime.now(timezone.utc).date()

    by_category = payload["opportunity_summary"]["by_category"]
    portfolio_snapshot = payload["portfolio_snapshot"]
    top_opportunities = payload["top_opportunities"]

    report = MarketIntelligenceReport(
        report_date=effective_date,
        total_opportunities=payload["summary"]["total_opportunities"],
        highest_score=payload["summary"]["highest_score"],
        average_score=payload["summary"]["average_score"],
        buy_opportunities_count=by_category.get("buy", 0),
        sell_opportunities_count=by_category.get("sell", 0),
        momentum_count=by_category.get("momentum", 0),
        drop_count=by_category.get("drop", 0),
        data_quality_count=by_category.get("data_quality", 0),
        owned_count=by_category.get("owned", 0),
        portfolio_market_floor_value_jpy=portfolio_snapshot["market_floor_value_jpy"],
        portfolio_retail_value_jpy=portfolio_snapshot["retail_value_jpy"],
        portfolio_liquidation_value_jpy=portfolio_snapshot["liquidation_value_jpy"],
        portfolio_pnl_vs_market_floor_jpy=portfolio_snapshot["pnl_vs_market_floor_jpy"],
        top_buy_json=top_opportunities["top_buy"],
        top_sell_json=top_opportunities["top_sell"],
        top_momentum_json=top_opportunities["top_momentum"],
        top_drop_json=top_opportunities["top_drop"],
        top_owned_json=top_opportunities["top_owned"],
        top_data_quality_json=top_opportunities["top_data_quality"],
        report_payload_json=payload,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report
