"""Builds one deterministic market intelligence report from data the app
already computes elsewhere - ranked opportunities (opportunity_scoring),
portfolio valuation, collection records, and persisted market_signal_events.
No LLM, no new price collection: this only aggregates and ranks what
refresh_prices/collection tracking/opportunity scoring have already stored.
"""

from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CollectionItem, MarketIntelligenceReport, MarketSignalEvent
from app.schemas import (
    MarketReportCollectionQualityOut,
    MarketReportOpportunitySummaryOut,
    MarketReportPayloadOut,
    MarketReportPortfolioSnapshotOut,
    MarketReportSignalEventSummaryOut,
    MarketReportSummaryOut,
    MarketReportTopOpportunitiesOut,
    OpportunityOut,
)
from app.services.opportunity_scoring import get_opportunities
from app.services.portfolio_valuation import get_portfolio_valuation

# Large enough to cover every currently active signal event in one page - the
# report needs the complete ranked set to pick top-5/top-per-category from,
# not a paginated slice of it.
REPORT_OPPORTUNITY_LIMIT = 10_000

TOP_N_OVERALL = 5


def _collection_quality(db: Session) -> MarketReportCollectionQualityOut:
    items = db.scalars(select(CollectionItem)).all()

    missing_purchase_price_count = sum(1 for i in items if i.purchase_price_jpy is None)
    missing_condition_count = sum(1 for i in items if i.condition_label is None)
    missing_target_sell_count = sum(1 for i in items if i.target_sell_price_jpy is None)

    return MarketReportCollectionQualityOut(
        missing_purchase_price_count=missing_purchase_price_count,
        missing_condition_count=missing_condition_count,
        missing_target_sell_count=missing_target_sell_count,
        total_quality_issues=(
            missing_purchase_price_count + missing_condition_count + missing_target_sell_count
        ),
    )


def _signal_event_summary(db: Session) -> MarketReportSignalEventSummaryOut:
    events = db.scalars(select(MarketSignalEvent)).all()

    signal_type_counts: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    for event in events:
        signal_type_counts[event.signal_type] = signal_type_counts.get(event.signal_type, 0) + 1
        if event.suggested_action:
            action_counts[event.suggested_action] = action_counts.get(event.suggested_action, 0) + 1

    return MarketReportSignalEventSummaryOut(
        open_events=sum(1 for e in events if e.status == "open"),
        watching_events=sum(1 for e in events if e.status == "watching"),
        dismissed_events=sum(1 for e in events if e.status == "dismissed"),
        resolved_events=sum(1 for e in events if e.status == "resolved"),
        most_common_signal_type=(
            max(signal_type_counts, key=signal_type_counts.get) if signal_type_counts else None
        ),
        most_common_suggested_action=(
            max(action_counts, key=action_counts.get) if action_counts else None
        ),
    )


def _deterministic_summary_lines(
    top_opportunities: MarketReportTopOpportunitiesOut,
    portfolio_snapshot: MarketReportPortfolioSnapshotOut,
    has_collection_items: bool,
    cards_above_target_sell: int,
    opportunity_summary: MarketReportOpportunitySummaryOut,
) -> list[str]:
    lines: list[str] = []

    if top_opportunities.top_5:
        top = top_opportunities.top_5[0]
        label = top.card_code or "an unlisted card"
        lines.append(f"Top ranked opportunity: {label} with score {top.score}.")
    else:
        lines.append("No ranked opportunities found.")

    # An empty collection legitimately has a market_floor_value_jpy of 0, not
    # None - guard on has_collection_items too, or this line would report a
    # meaningless "¥0" for a portfolio that doesn't exist yet.
    if has_collection_items and portfolio_snapshot.market_floor_value_jpy is not None:
        lines.append(
            f"Portfolio market floor value: ¥{portfolio_snapshot.market_floor_value_jpy:,}."
        )

    if cards_above_target_sell > 0:
        noun = "card" if cards_above_target_sell == 1 else "cards"
        lines.append(f"{cards_above_target_sell} owned {noun} are above target sell.")

    data_quality_count = opportunity_summary.by_category.get("data_quality", 0)
    if data_quality_count > 0:
        noun = "issue" if data_quality_count == 1 else "issues"
        lines.append(f"{data_quality_count} data quality {noun} need review.")

    return lines


def build_report_payload(db: Session) -> MarketReportPayloadOut:
    """Pure, deterministic computation - no persistence. Safe to call
    repeatedly (e.g. for GET /market/report/latest to be re-derivable) and
    safe on an empty collection or empty opportunity set."""
    opportunities_response = get_opportunities(db, limit=REPORT_OPPORTUNITY_LIMIT)
    opp_summary = opportunities_response.summary
    all_opportunities = opportunities_response.opportunities

    total_opportunities = opp_summary.total_opportunities
    highest_score = opp_summary.highest_score if total_opportunities else None
    average_score = opp_summary.average_score if total_opportunities else None

    opportunity_summary = MarketReportOpportunitySummaryOut(
        total_opportunities=total_opportunities,
        highest_score=highest_score,
        average_score=average_score,
        by_category=dict(opp_summary.by_category),
    )

    def _first_of_category(category: str) -> OpportunityOut | None:
        return next((o for o in all_opportunities if o.category == category), None)

    top_opportunities = MarketReportTopOpportunitiesOut(
        top_5=all_opportunities[:TOP_N_OVERALL],
        top_buy=_first_of_category("buy"),
        top_sell=_first_of_category("sell"),
        top_momentum=_first_of_category("momentum"),
        top_drop=_first_of_category("drop"),
        top_owned=_first_of_category("owned"),
        top_data_quality=_first_of_category("data_quality"),
    )

    valuation = get_portfolio_valuation(db)
    portfolio_summary = valuation.summary
    # "Missing prices" here means no price data at all from any source -
    # distinct from the per-source missing_yuyutei_sell/buy/snkrdunk_floor
    # counts, which count items missing just one of the three.
    items_missing_prices = sum(
        1
        for item in valuation.items
        if item.flags.missing_yuyutei_sell
        and item.flags.missing_yuyutei_buy
        and item.flags.missing_snkrdunk_floor
    )

    portfolio_snapshot = MarketReportPortfolioSnapshotOut(
        total_cost_basis_jpy=portfolio_summary.total_cost_basis_jpy,
        retail_value_jpy=portfolio_summary.retail_value_jpy,
        liquidation_value_jpy=portfolio_summary.liquidation_value_jpy,
        market_floor_value_jpy=portfolio_summary.market_floor_value_jpy,
        pnl_vs_market_floor_jpy=portfolio_summary.pnl_vs_market_floor_jpy,
        pnl_vs_market_floor_pct=portfolio_summary.pnl_vs_market_floor_pct,
        items_missing_cost_basis=portfolio_summary.items_missing_cost_basis,
        items_missing_prices=items_missing_prices,
    )

    collection_quality = _collection_quality(db)
    signal_event_summary = _signal_event_summary(db)

    summary = MarketReportSummaryOut(
        total_opportunities=total_opportunities,
        highest_score=highest_score,
        average_score=average_score,
    )

    deterministic_summary_lines = _deterministic_summary_lines(
        top_opportunities=top_opportunities,
        portfolio_snapshot=portfolio_snapshot,
        has_collection_items=len(valuation.items) > 0,
        cards_above_target_sell=portfolio_summary.cards_above_target_sell,
        opportunity_summary=opportunity_summary,
    )

    return MarketReportPayloadOut(
        summary=summary,
        portfolio_snapshot=portfolio_snapshot,
        opportunity_summary=opportunity_summary,
        top_opportunities=top_opportunities,
        collection_quality=collection_quality,
        signal_event_summary=signal_event_summary,
        deterministic_summary_lines=deterministic_summary_lines,
    )


def _opportunity_json(opportunity: OpportunityOut | None) -> dict | None:
    return opportunity.model_dump(mode="json") if opportunity is not None else None


def generate_market_report(
    db: Session, report_date: date | None = None
) -> MarketIntelligenceReport:
    payload = build_report_payload(db)
    effective_date = report_date or datetime.now(timezone.utc).date()

    report = MarketIntelligenceReport(
        report_date=effective_date,
        total_opportunities=payload.summary.total_opportunities,
        highest_score=payload.summary.highest_score,
        average_score=payload.summary.average_score,
        buy_opportunities_count=payload.opportunity_summary.by_category.get("buy", 0),
        sell_opportunities_count=payload.opportunity_summary.by_category.get("sell", 0),
        momentum_count=payload.opportunity_summary.by_category.get("momentum", 0),
        drop_count=payload.opportunity_summary.by_category.get("drop", 0),
        data_quality_count=payload.opportunity_summary.by_category.get("data_quality", 0),
        owned_count=payload.opportunity_summary.by_category.get("owned", 0),
        portfolio_market_floor_value_jpy=payload.portfolio_snapshot.market_floor_value_jpy,
        portfolio_retail_value_jpy=payload.portfolio_snapshot.retail_value_jpy,
        portfolio_liquidation_value_jpy=payload.portfolio_snapshot.liquidation_value_jpy,
        portfolio_pnl_vs_market_floor_jpy=payload.portfolio_snapshot.pnl_vs_market_floor_jpy,
        top_buy_json=_opportunity_json(payload.top_opportunities.top_buy),
        top_sell_json=_opportunity_json(payload.top_opportunities.top_sell),
        top_momentum_json=_opportunity_json(payload.top_opportunities.top_momentum),
        top_drop_json=_opportunity_json(payload.top_opportunities.top_drop),
        top_owned_json=_opportunity_json(payload.top_opportunities.top_owned),
        top_data_quality_json=_opportunity_json(payload.top_opportunities.top_data_quality),
        report_payload_json=payload.model_dump(mode="json"),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report
