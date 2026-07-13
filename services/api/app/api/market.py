from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Card, CollectionItem, MarketIntelligenceReport, MarketSignalEvent
from app.models.market_signal_event import STATUSES as EVENT_STATUSES
from app.schemas import (
    MarketIntelligenceReportListOut,
    MarketIntelligenceReportOut,
    MarketIntelligenceReportSummaryOut,
    MarketMoverOut,
    MarketSignalEventListOut,
    MarketSignalEventOut,
    MarketSignalEventsSummaryOut,
    MarketSignalEventUpdateIn,
    MarketSignalsResponseOut,
    OpportunitiesResponseOut,
)
from app.services.market import get_market_movers
from app.services.market_signal_events import event_to_out, owned_quantity_for_card
from app.services.market_signals import SIGNAL_TYPES, get_market_signals
from app.services.opportunity_scoring import CATEGORIES, get_opportunities

router = APIRouter(prefix="/market", tags=["market"])

VALID_SOURCES = ("yuyutei", "snkrdunk")
VALID_PRICE_TYPES = ("sell", "buy", "floor", "sold")


@router.get("/movers", response_model=list[MarketMoverOut])
def market_movers(
    source: str | None = Query(default=None),
    price_type: str | None = Query(default=None),
    rarity: str | None = Query(default=None),
    variant: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if source is not None and source not in VALID_SOURCES:
        raise HTTPException(
            status_code=400, detail=f"Invalid source. Must be one of {list(VALID_SOURCES)}"
        )
    if price_type is not None and price_type not in VALID_PRICE_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid price_type. Must be one of {list(VALID_PRICE_TYPES)}",
        )

    return get_market_movers(
        db,
        source=source,
        price_type=price_type,
        rarity=rarity,
        variant=variant,
        limit=limit,
        offset=offset,
    )


@router.get("/signals", response_model=MarketSignalsResponseOut)
def market_signals(
    signal_type: str | None = Query(default=None),
    set_code: str | None = Query(default=None),
    rarity: str | None = Query(default=None),
    source: str | None = Query(default=None),
    owned: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if signal_type is not None and signal_type not in SIGNAL_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid signal_type. Must be one of {list(SIGNAL_TYPES)}",
        )
    if source is not None and source not in VALID_SOURCES:
        raise HTTPException(
            status_code=400, detail=f"Invalid source. Must be one of {list(VALID_SOURCES)}"
        )

    return get_market_signals(
        db,
        signal_type=signal_type,
        set_code=set_code,
        rarity=rarity,
        source=source,
        owned=owned,
        limit=limit,
        offset=offset,
    )


def _get_event_or_404(db: Session, event_id: int) -> MarketSignalEvent:
    event = db.get(MarketSignalEvent, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Market signal event not found")
    return event


def _build_event_out(db: Session, event: MarketSignalEvent) -> MarketSignalEventOut:
    card = db.get(Card, event.card_id) if event.card_id is not None else None
    owned_quantity = owned_quantity_for_card(db, event.card_id)
    return event_to_out(event, card, owned_quantity)


@router.get("/signal-events", response_model=MarketSignalEventListOut)
def list_market_signal_events(
    status: str | None = Query(default=None),
    signal_type: str | None = Query(default=None),
    suggested_action: str | None = Query(default=None),
    card_code: str | None = Query(default=None),
    owned: bool | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if status is not None and status not in EVENT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of {list(EVENT_STATUSES)}",
        )

    filters = []
    if status is not None:
        filters.append(MarketSignalEvent.status == status)
    if signal_type is not None:
        filters.append(MarketSignalEvent.signal_type == signal_type)
    if suggested_action is not None:
        filters.append(MarketSignalEvent.suggested_action == suggested_action)

    query = select(MarketSignalEvent)
    if card_code is not None:
        query = query.join(Card, MarketSignalEvent.card_id == Card.id).where(
            Card.card_code == card_code, *filters
        )
    else:
        query = query.where(*filters)

    events = db.scalars(query.order_by(MarketSignalEvent.last_seen_at.desc())).all()

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
        owned_quantities = {card_id: int(qty or 0) for card_id, qty in rows}

    enriched = [
        (event, cards_by_id.get(event.card_id), owned_quantities.get(event.card_id, 0))
        for event in events
    ]

    if owned is not None:
        enriched = [(e, c, q) for (e, c, q) in enriched if (q > 0) == owned]

    by_signal_type: dict[str, int] = {}
    by_suggested_action: dict[str, int] = {}
    open_events = watching_events = dismissed_events = resolved_events = 0
    for event, _card, _qty in enriched:
        by_signal_type[event.signal_type] = by_signal_type.get(event.signal_type, 0) + 1
        if event.suggested_action:
            by_suggested_action[event.suggested_action] = (
                by_suggested_action.get(event.suggested_action, 0) + 1
            )
        if event.status == "open":
            open_events += 1
        elif event.status == "watching":
            watching_events += 1
        elif event.status == "dismissed":
            dismissed_events += 1
        elif event.status == "resolved":
            resolved_events += 1

    summary = MarketSignalEventsSummaryOut(
        total_events=len(enriched),
        open_events=open_events,
        watching_events=watching_events,
        dismissed_events=dismissed_events,
        resolved_events=resolved_events,
        by_signal_type=by_signal_type,
        by_suggested_action=by_suggested_action,
    )

    page = enriched[offset : offset + limit]
    return MarketSignalEventListOut(
        summary=summary,
        events=[event_to_out(event, card, qty) for event, card, qty in page],
    )


@router.get("/signal-events/{event_id}", response_model=MarketSignalEventOut)
def get_market_signal_event(event_id: int, db: Session = Depends(get_db)):
    event = _get_event_or_404(db, event_id)
    return _build_event_out(db, event)


@router.patch("/signal-events/{event_id}", response_model=MarketSignalEventOut)
def update_market_signal_event(
    event_id: int, body: MarketSignalEventUpdateIn, db: Session = Depends(get_db)
):
    event = _get_event_or_404(db, event_id)

    updates = body.model_dump(exclude_unset=True)
    new_status = updates.get("status")
    if new_status is not None and new_status not in EVENT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of {list(EVENT_STATUSES)}",
        )

    now = datetime.now(timezone.utc)
    if "status" in updates and new_status is not None:
        event.status = new_status
        if new_status == "dismissed":
            event.dismissed_at = now
        elif new_status == "resolved":
            event.resolved_at = now
        elif new_status in ("open", "watching"):
            event.dismissed_at = None
            event.resolved_at = None
    if "notes" in updates:
        event.notes = updates["notes"]

    db.commit()
    db.refresh(event)
    return _build_event_out(db, event)


@router.post("/signal-events/{event_id}/dismiss", response_model=MarketSignalEventOut)
def dismiss_market_signal_event(event_id: int, db: Session = Depends(get_db)):
    event = _get_event_or_404(db, event_id)
    event.status = "dismissed"
    event.dismissed_at = datetime.now(timezone.utc)
    event.resolved_at = None
    db.commit()
    db.refresh(event)
    return _build_event_out(db, event)


@router.post("/signal-events/{event_id}/watch", response_model=MarketSignalEventOut)
def watch_market_signal_event(event_id: int, db: Session = Depends(get_db)):
    event = _get_event_or_404(db, event_id)
    event.status = "watching"
    event.dismissed_at = None
    event.resolved_at = None
    db.commit()
    db.refresh(event)
    return _build_event_out(db, event)


@router.post("/signal-events/{event_id}/resolve", response_model=MarketSignalEventOut)
def resolve_market_signal_event(event_id: int, db: Session = Depends(get_db)):
    event = _get_event_or_404(db, event_id)
    event.status = "resolved"
    event.resolved_at = datetime.now(timezone.utc)
    event.dismissed_at = None
    db.commit()
    db.refresh(event)
    return _build_event_out(db, event)


@router.get("/opportunities", response_model=OpportunitiesResponseOut)
def market_opportunities(
    category: str | None = Query(default=None),
    owned: bool | None = Query(default=None),
    set_code: str | None = Query(default=None),
    rarity: str | None = Query(default=None),
    min_score: int | None = Query(default=None, ge=0, le=100),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if category is not None and category not in CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category. Must be one of {list(CATEGORIES)}",
        )

    return get_opportunities(
        db,
        category=category,
        owned=owned,
        set_code=set_code,
        rarity=rarity,
        min_score=min_score,
        limit=limit,
        offset=offset,
    )


def _report_to_out(report: MarketIntelligenceReport) -> MarketIntelligenceReportOut:
    payload = report.report_payload_json
    return MarketIntelligenceReportOut(
        id=report.id,
        created_at=report.created_at,
        report_date=report.report_date,
        summary=payload["summary"],
        portfolio_snapshot=payload["portfolio_snapshot"],
        opportunity_summary=payload["opportunity_summary"],
        top_opportunities=payload["top_opportunities"],
        collection_quality=payload["collection_quality"],
        signal_event_summary=payload["signal_event_summary"],
        deterministic_summary_lines=payload["deterministic_summary_lines"],
        payload=payload,
    )


def _report_to_summary_out(report: MarketIntelligenceReport) -> MarketIntelligenceReportSummaryOut:
    return MarketIntelligenceReportSummaryOut(
        id=report.id,
        created_at=report.created_at,
        report_date=report.report_date,
        total_opportunities=report.total_opportunities,
        highest_score=report.highest_score,
        average_score=report.average_score,
        buy_opportunities_count=report.buy_opportunities_count,
        sell_opportunities_count=report.sell_opportunities_count,
        momentum_count=report.momentum_count,
        drop_count=report.drop_count,
        data_quality_count=report.data_quality_count,
        owned_count=report.owned_count,
        portfolio_market_floor_value_jpy=report.portfolio_market_floor_value_jpy,
        portfolio_retail_value_jpy=report.portfolio_retail_value_jpy,
        portfolio_liquidation_value_jpy=report.portfolio_liquidation_value_jpy,
        portfolio_pnl_vs_market_floor_jpy=report.portfolio_pnl_vs_market_floor_jpy,
    )


@router.get("/report/latest", response_model=MarketIntelligenceReportOut)
def get_latest_market_report(db: Session = Depends(get_db)):
    report = db.scalar(
        select(MarketIntelligenceReport).order_by(
            MarketIntelligenceReport.created_at.desc(), MarketIntelligenceReport.id.desc()
        )
    )
    if report is None:
        raise HTTPException(status_code=404, detail="No market intelligence reports found")
    return _report_to_out(report)


@router.get("/reports", response_model=MarketIntelligenceReportListOut)
def list_market_reports(
    limit: int = Query(default=30, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    total = db.scalar(select(func.count()).select_from(MarketIntelligenceReport)) or 0
    reports = db.scalars(
        select(MarketIntelligenceReport)
        .order_by(MarketIntelligenceReport.created_at.desc(), MarketIntelligenceReport.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return MarketIntelligenceReportListOut(
        reports=[_report_to_summary_out(r) for r in reports],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/reports/{report_id}", response_model=MarketIntelligenceReportOut)
def get_market_report(report_id: int, db: Session = Depends(get_db)):
    report = db.get(MarketIntelligenceReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Market intelligence report not found")
    return _report_to_out(report)
