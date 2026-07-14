"""Collector dashboard personalization: a single global layout/visibility
preference (dashboard_preferences.main_dashboard - not per-user, matching
this table's schema) plus one compact "overview" payload that assembles
already-existing widgets from the collection/wishlist/grading/market-signal
subsystems. No new calculations - every widget just re-packages a call into
an existing service (portfolio_valuation, wishlist, grading,
opportunity_scoring, market_signal_events) so formulas never drift from
their single source of truth.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Card,
    CollectionItem,
    DashboardPreference,
    MarketIntelligenceReport,
    MarketSignalEvent,
    MarketWorkflowRun,
    PortfolioValuationSnapshot,
    PriceRefreshRun,
)
from app.models.dashboard_preference import MAIN_DASHBOARD_KEY
from app.schemas import (
    BackupStatusWidgetOut,
    CollectionQualityWidgetOut,
    DashboardOverviewOut,
    DashboardPreferencesOut,
    DashboardPreferencesUpdateIn,
    DashboardWidgetsOut,
    DataFreshnessWidgetOut,
    GradingStatusWidgetOut,
    MarketReportWidgetOut,
    PortfolioChartPointOut,
    PortfolioChartWidgetOut,
    PortfolioSummaryWidgetOut,
    RecentActivityWidgetOut,
    RecentSignalEventsWidgetOut,
    TopOpportunitiesWidgetOut,
    WishlistTargetsWidgetOut,
    WorkflowStatusWidgetOut,
)
from app.services.activity_timeline import get_recent_activity_events
from app.services.grading import build_grading_summary
from app.services.market_signal_events import event_to_out, owned_quantity_for_card
from app.services.market_signals import get_market_signals
from app.services.opportunity_scoring import get_opportunities
from app.services.portfolio_valuation import get_portfolio_valuation
from app.services.wishlist import get_wishlist_items, get_wishlist_summary

ALLOWED_WIDGET_IDS = (
    "portfolio_summary",
    "portfolio_chart",
    "wishlist_targets",
    "top_opportunities",
    "grading_status",
    "market_report",
    "collection_quality",
    "recent_signal_events",
    "data_freshness",
    "backup_status",
    "workflow_status",
    "recent_activity",
)

ALLOWED_TIMEFRAMES = ("7d", "30d", "90d", "all")

TIMEFRAME_DAYS: dict[str, int | None] = {"7d": 7, "30d": 30, "90d": 90, "all": None}

DEFAULT_PREFERENCES: dict = {
    "layout": [
        "portfolio_summary",
        "wishlist_targets",
        "top_opportunities",
        "grading_status",
        "market_report",
        "collection_quality",
        "recent_signal_events",
        "data_freshness",
        "recent_activity",
    ],
    "hidden_widgets": [],
    "pinned_cards": [],
    "default_timeframe": "30d",
    "show_raw_market_value": True,
    "show_graded_adjusted_value": True,
    "show_wishlist_budget": True,
    "show_grading_costs": True,
}


class DashboardValidationError(ValueError):
    pass


def get_or_create_preferences(db: Session) -> DashboardPreference:
    pref = db.scalar(
        select(DashboardPreference).where(DashboardPreference.preference_key == MAIN_DASHBOARD_KEY)
    )
    if pref is not None:
        return pref
    pref = DashboardPreference(
        preference_key=MAIN_DASHBOARD_KEY, preference_value_json=dict(DEFAULT_PREFERENCES)
    )
    db.add(pref)
    db.commit()
    db.refresh(pref)
    return pref


def _validate_widget_ids(field_name: str, values: list[str]) -> None:
    invalid = sorted({v for v in values if v not in ALLOWED_WIDGET_IDS})
    if invalid:
        raise DashboardValidationError(
            f"{field_name} contains invalid widget id(s): {invalid}. "
            f"Must be one of {list(ALLOWED_WIDGET_IDS)}"
        )


def _validate_pinned_cards(db: Session, card_ids: list[int]) -> None:
    if not card_ids:
        return
    existing = set(db.scalars(select(Card.id).where(Card.id.in_(card_ids))).all())
    missing = [cid for cid in card_ids if cid not in existing]
    if missing:
        raise DashboardValidationError(f"pinned_cards references missing card id(s): {missing}")


def update_preferences(db: Session, updates: DashboardPreferencesUpdateIn) -> DashboardPreference:
    """Raises DashboardValidationError on any invalid field - callers convert
    this to an HTTP 400. Merges only the fields the caller actually set
    (exclude_unset), leaving everything else as-is - a PATCH, not a PUT."""
    pref = get_or_create_preferences(db)
    data = updates.model_dump(exclude_unset=True)

    if "layout" in data:
        _validate_widget_ids("layout", data["layout"])
    if "hidden_widgets" in data:
        _validate_widget_ids("hidden_widgets", data["hidden_widgets"])
    if "pinned_cards" in data:
        _validate_pinned_cards(db, data["pinned_cards"])

    value = dict(pref.preference_value_json)
    value.update(data)
    pref.preference_value_json = value

    db.commit()
    db.refresh(pref)
    return pref


def _build_portfolio_summary(db: Session, user_id: int) -> PortfolioSummaryWidgetOut:
    valuation = get_portfolio_valuation(db, user_id=user_id, valuation_mode="graded_adjusted")
    s = valuation.summary
    return PortfolioSummaryWidgetOut(
        total_cost_basis_jpy=s.total_cost_basis_jpy,
        market_floor_value_jpy=s.market_floor_value_jpy,
        graded_adjusted_value_jpy=s.graded_adjusted_value_jpy,
        pnl_vs_market_floor_jpy=s.pnl_vs_market_floor_jpy,
        pnl_vs_market_floor_pct=s.pnl_vs_market_floor_pct,
        pnl_vs_graded_adjusted_jpy=s.pnl_vs_graded_adjusted_jpy,
        pnl_vs_graded_adjusted_pct=s.pnl_vs_graded_adjusted_pct,
    )


def _build_portfolio_chart(db: Session, timeframe: str) -> PortfolioChartWidgetOut:
    days = TIMEFRAME_DAYS.get(timeframe, 30)
    filters = []
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        filters.append(PortfolioValuationSnapshot.created_at >= cutoff)

    snapshots = db.scalars(
        select(PortfolioValuationSnapshot)
        .where(*filters)
        .order_by(PortfolioValuationSnapshot.created_at.asc())
    ).all()
    points = [
        PortfolioChartPointOut(
            created_at=s.created_at,
            market_floor_value_jpy=s.market_floor_value_jpy,
            graded_adjusted_value_jpy=s.graded_adjusted_value_jpy,
        )
        for s in snapshots
    ]
    return PortfolioChartWidgetOut(timeframe=timeframe, points=points)


def _build_wishlist_targets(db: Session, user_id: int) -> WishlistTargetsWidgetOut:
    response = get_wishlist_items(db, user_id, target_hit=True, limit=1_000_000, offset=0)
    items = [i for i in response.items if i.priority in ("high", "grail")]
    summary = get_wishlist_summary(db, user_id)
    return WishlistTargetsWidgetOut(
        items=items,
        total_target_hit=len(items),
        total_target_budget_jpy=summary.total_target_budget_jpy,
        total_max_budget_jpy=summary.total_max_budget_jpy,
    )


def _build_top_opportunities(db: Session) -> TopOpportunitiesWidgetOut:
    response = get_opportunities(db, limit=5, offset=0)
    return TopOpportunitiesWidgetOut(opportunities=response.opportunities)


def _build_grading_status(db: Session, user_id: int) -> GradingStatusWidgetOut:
    summary = build_grading_summary(db, user_id=user_id)
    submitted_or_grading = summary.by_status.get("submitted", 0) + summary.by_status.get("grading", 0)
    return GradingStatusWidgetOut(
        total_submissions=summary.total_submissions,
        submitted_or_grading_count=submitted_or_grading,
        received_count=summary.by_status.get("received", 0),
        total_grading_cost_jpy=summary.total_grading_cost_jpy,
    )


def _build_market_report(db: Session) -> MarketReportWidgetOut:
    report = db.scalar(
        select(MarketIntelligenceReport).order_by(
            MarketIntelligenceReport.created_at.desc(), MarketIntelligenceReport.id.desc()
        )
    )
    if report is None:
        return MarketReportWidgetOut(
            report_id=None,
            report_date=None,
            total_opportunities=None,
            highest_score=None,
            deterministic_summary_lines=[],
        )

    payload = report.report_payload_json or {}
    lines = payload.get("deterministic_summary_lines") or []
    return MarketReportWidgetOut(
        report_id=report.id,
        report_date=report.report_date,
        total_opportunities=report.total_opportunities,
        highest_score=report.highest_score,
        deterministic_summary_lines=list(lines[:3]),
    )


def _build_collection_quality(db: Session, user_id: int) -> CollectionQualityWidgetOut:
    items = db.scalars(
        select(CollectionItem).where(CollectionItem.user_id == user_id)
    ).all()
    return CollectionQualityWidgetOut(
        missing_purchase_price_count=sum(1 for i in items if i.purchase_price_jpy is None),
        missing_condition_count=sum(1 for i in items if i.condition_label is None),
        missing_target_sell_count=sum(1 for i in items if i.target_sell_price_jpy is None),
    )


def _build_recent_signal_events(db: Session) -> RecentSignalEventsWidgetOut:
    events = db.scalars(
        select(MarketSignalEvent)
        .where(MarketSignalEvent.status.in_(("open", "watching")))
        .order_by(MarketSignalEvent.last_seen_at.desc())
        .limit(5)
    ).all()

    card_ids = {e.card_id for e in events if e.card_id is not None}
    cards_by_id: dict[int, Card] = {}
    if card_ids:
        cards_by_id = {c.id: c for c in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()}

    out_events = [
        event_to_out(e, cards_by_id.get(e.card_id), owned_quantity_for_card(db, e.card_id))
        for e in events
    ]
    return RecentSignalEventsWidgetOut(events=out_events)


def _build_data_freshness(db: Session) -> DataFreshnessWidgetOut:
    """"Existing data health" doesn't exist as its own module in this app -
    falls back to the latest price-refresh-run info, plus the same
    missing/stale price counts already surfaced by market_signals.py (not
    recomputed here)."""
    signals = get_market_signals(db, limit=1)
    missing_count = signals.summary.by_signal_type.get("missing_recent_price", 0)
    stale_count = signals.summary.by_signal_type.get("stale_mapping_price", 0)

    latest_run = db.scalar(
        select(PriceRefreshRun).order_by(PriceRefreshRun.started_at.desc(), PriceRefreshRun.id.desc())
    )
    return DataFreshnessWidgetOut(
        latest_refresh_at=latest_run.finished_at if latest_run is not None else None,
        latest_refresh_status=latest_run.status if latest_run is not None else None,
        missing_recent_price_count=missing_count,
        stale_mapping_price_count=stale_count,
    )


def _build_backup_status() -> BackupStatusWidgetOut:
    """No backup-history table exists in this app (backups are export-on-
    demand, not persisted) - always reports untracked rather than fabricating
    a timestamp."""
    return BackupStatusWidgetOut(tracked=False, last_backup_at=None, message="No backup status tracked yet")


def _build_workflow_status(db: Session) -> WorkflowStatusWidgetOut:
    run = db.scalar(
        select(MarketWorkflowRun).order_by(
            MarketWorkflowRun.started_at.desc(), MarketWorkflowRun.id.desc()
        )
    )
    if run is None:
        return WorkflowStatusWidgetOut(
            run_id=None, status=None, market_report_id=None, telegram_digest_status=None, finished_at=None
        )
    return WorkflowStatusWidgetOut(
        run_id=run.id,
        status=run.status,
        market_report_id=run.market_report_id,
        telegram_digest_status=run.telegram_digest_status,
        finished_at=run.finished_at,
    )


def _build_recent_activity(db: Session) -> RecentActivityWidgetOut:
    return RecentActivityWidgetOut(events=get_recent_activity_events(db))


def build_overview(db: Session, user_id: int) -> DashboardOverviewOut:
    pref = get_or_create_preferences(db)
    preferences_out = DashboardPreferencesOut(**pref.preference_value_json)

    widgets = DashboardWidgetsOut(
        portfolio_summary=_build_portfolio_summary(db, user_id),
        portfolio_chart=_build_portfolio_chart(db, preferences_out.default_timeframe),
        wishlist_targets=_build_wishlist_targets(db, user_id),
        top_opportunities=_build_top_opportunities(db),
        grading_status=_build_grading_status(db, user_id),
        market_report=_build_market_report(db),
        collection_quality=_build_collection_quality(db, user_id),
        recent_signal_events=_build_recent_signal_events(db),
        data_freshness=_build_data_freshness(db),
        backup_status=_build_backup_status(),
        workflow_status=_build_workflow_status(db),
        recent_activity=_build_recent_activity(db),
    )
    return DashboardOverviewOut(preferences=preferences_out, widgets=widgets)
