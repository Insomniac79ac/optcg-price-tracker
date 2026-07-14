"""Collector activity timeline: a best-effort, append-only log of notable
actions across collection, wishlist, grading, market signals/reports,
backups, and workflow runs. Recording an event is deliberately isolated from
the caller's own transaction - a failure here is logged and swallowed, never
raised, so a broken activity log can never take down the action that
triggered it. See record_activity_event's docstring for the call contract
this relies on.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Card, CollectorActivityEvent
from app.schemas import CollectorActivityEventOut

logger = logging.getLogger(__name__)


def _naive(dt: datetime) -> datetime:
    """sqlite (used in tests) round-trips DateTime(timezone=True) columns as
    naive datetimes, so any Python-side comparison against a tz-aware
    `datetime.now(timezone.utc)` value needs both sides stripped to naive -
    same approach as app/services/market_signals.py's _naive()."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


# How recently an identical-looking event (same type/links/title) must have
# been recorded for a new call to be treated as an accidental duplicate
# (e.g. a double form submit or a retried request) rather than a genuinely
# new occurrence of the same kind of action.
DUPLICATE_TOLERANCE_SECONDS = 10


def _is_recent_duplicate(
    db: Session,
    *,
    event_type: str,
    event_source: str,
    card_id: int | None,
    collection_item_id: int | None,
    wishlist_item_id: int | None,
    grading_submission_id: int | None,
    market_signal_event_id: int | None,
    market_report_id: int | None,
    market_workflow_run_id: int | None,
    title: str,
) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=DUPLICATE_TOLERANCE_SECONDS)
    existing = db.scalar(
        select(CollectorActivityEvent.id)
        .where(
            CollectorActivityEvent.event_type == event_type,
            CollectorActivityEvent.event_source == event_source,
            CollectorActivityEvent.card_id == card_id,
            CollectorActivityEvent.collection_item_id == collection_item_id,
            CollectorActivityEvent.wishlist_item_id == wishlist_item_id,
            CollectorActivityEvent.grading_submission_id == grading_submission_id,
            CollectorActivityEvent.market_signal_event_id == market_signal_event_id,
            CollectorActivityEvent.market_report_id == market_report_id,
            CollectorActivityEvent.market_workflow_run_id == market_workflow_run_id,
            CollectorActivityEvent.title == title,
            CollectorActivityEvent.created_at >= cutoff,
        )
        .limit(1)
    )
    return existing is not None


def record_activity_event(
    db: Session,
    *,
    event_type: str,
    event_source: str,
    title: str,
    message: str | None = None,
    payload: dict | None = None,
    card_id: int | None = None,
    collection_item_id: int | None = None,
    wishlist_item_id: int | None = None,
    grading_submission_id: int | None = None,
    market_signal_event_id: int | None = None,
    market_report_id: int | None = None,
    market_workflow_run_id: int | None = None,
) -> CollectorActivityEvent | None:
    """Records one activity event and commits it on its own, independent of
    whatever transaction the caller was using.

    Call this AFTER the main action has already been committed (or is about
    to be committed and cannot fail), and gather any values you need from
    rows you're about to delete beforehand - never rely on this function to
    participate in or protect the caller's own transaction.

    Best-effort: any exception (bad session state, DB error, etc.) is caught,
    logged as a warning, and swallowed - this never raises, so a broken
    activity log can never fail the action that triggered it. Returns the
    created (or matched, if this looks like a near-duplicate) event, or None
    if recording failed.
    """
    try:
        if _is_recent_duplicate(
            db,
            event_type=event_type,
            event_source=event_source,
            card_id=card_id,
            collection_item_id=collection_item_id,
            wishlist_item_id=wishlist_item_id,
            grading_submission_id=grading_submission_id,
            market_signal_event_id=market_signal_event_id,
            market_report_id=market_report_id,
            market_workflow_run_id=market_workflow_run_id,
            title=title,
        ):
            return None

        event = CollectorActivityEvent(
            event_type=event_type,
            event_source=event_source,
            title=title,
            message=message,
            payload_json=payload,
            card_id=card_id,
            collection_item_id=collection_item_id,
            wishlist_item_id=wishlist_item_id,
            grading_submission_id=grading_submission_id,
            market_signal_event_id=market_signal_event_id,
            market_report_id=market_report_id,
            market_workflow_run_id=market_workflow_run_id,
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return event
    except Exception:
        logger.warning(
            "Failed to record activity event (event_type=%s, event_source=%s)",
            event_type,
            event_source,
            exc_info=True,
        )
        db.rollback()
        return None


def activity_event_to_out(
    event: CollectorActivityEvent, card: Card | None = None
) -> CollectorActivityEventOut:
    return CollectorActivityEventOut(
        id=event.id,
        event_type=event.event_type,
        event_source=event.event_source,
        card_id=event.card_id,
        card_code=card.card_code if card is not None else None,
        name_en=card.name_en if card is not None else None,
        name_jp=card.name_jp if card is not None else None,
        collection_item_id=event.collection_item_id,
        wishlist_item_id=event.wishlist_item_id,
        grading_submission_id=event.grading_submission_id,
        market_signal_event_id=event.market_signal_event_id,
        market_report_id=event.market_report_id,
        market_workflow_run_id=event.market_workflow_run_id,
        title=event.title,
        message=event.message,
        created_at=event.created_at,
        payload=event.payload_json,
    )


def _cards_by_id(db: Session, events: list[CollectorActivityEvent]) -> dict[int, Card]:
    card_ids = {e.card_id for e in events if e.card_id is not None}
    if not card_ids:
        return {}
    return {c.id: c for c in db.scalars(select(Card).where(Card.id.in_(card_ids))).all()}


@dataclass
class ActivityListResult:
    events: list[CollectorActivityEventOut]
    total_events: int
    by_source: dict[str, int] = field(default_factory=dict)
    by_type: dict[str, int] = field(default_factory=dict)


def list_activity_events(
    db: Session,
    *,
    event_source: str | None = None,
    event_type: str | None = None,
    card_id: int | None = None,
    collection_item_id: int | None = None,
    wishlist_item_id: int | None = None,
    grading_submission_id: int | None = None,
    market_signal_event_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> ActivityListResult:
    filters = []
    if event_source is not None:
        filters.append(CollectorActivityEvent.event_source == event_source)
    if event_type is not None:
        filters.append(CollectorActivityEvent.event_type == event_type)
    if card_id is not None:
        filters.append(CollectorActivityEvent.card_id == card_id)
    if collection_item_id is not None:
        filters.append(CollectorActivityEvent.collection_item_id == collection_item_id)
    if wishlist_item_id is not None:
        filters.append(CollectorActivityEvent.wishlist_item_id == wishlist_item_id)
    if grading_submission_id is not None:
        filters.append(CollectorActivityEvent.grading_submission_id == grading_submission_id)
    if market_signal_event_id is not None:
        filters.append(CollectorActivityEvent.market_signal_event_id == market_signal_event_id)

    all_matching = db.scalars(
        select(CollectorActivityEvent)
        .where(*filters)
        .order_by(CollectorActivityEvent.created_at.desc(), CollectorActivityEvent.id.desc())
    ).all()

    by_source: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for e in all_matching:
        by_source[e.event_source] = by_source.get(e.event_source, 0) + 1
        by_type[e.event_type] = by_type.get(e.event_type, 0) + 1

    page = list(all_matching[offset : offset + limit])
    cards_by_id = _cards_by_id(db, page)
    events_out = [activity_event_to_out(e, cards_by_id.get(e.card_id)) for e in page]

    return ActivityListResult(
        events=events_out,
        total_events=len(all_matching),
        by_source=by_source,
        by_type=by_type,
    )


@dataclass
class ActivitySummaryResult:
    today_count: int
    last_7d_count: int
    last_30d_count: int
    by_source: dict[str, int] = field(default_factory=dict)
    recent_events: list[CollectorActivityEventOut] = field(default_factory=list)


RECENT_EVENTS_LIMIT = 5


def get_activity_summary(db: Session) -> ActivitySummaryResult:
    now = datetime.now(timezone.utc)
    today_start = _naive(now.replace(hour=0, minute=0, second=0, microsecond=0))
    cutoff_7d = _naive(now - timedelta(days=7))
    cutoff_30d = _naive(now - timedelta(days=30))

    all_events = db.scalars(select(CollectorActivityEvent)).all()

    today_count = sum(1 for e in all_events if _naive(e.created_at) >= today_start)
    last_7d_count = sum(1 for e in all_events if _naive(e.created_at) >= cutoff_7d)
    last_30d_count = sum(1 for e in all_events if _naive(e.created_at) >= cutoff_30d)

    by_source: dict[str, int] = {}
    for e in all_events:
        by_source[e.event_source] = by_source.get(e.event_source, 0) + 1

    recent = db.scalars(
        select(CollectorActivityEvent)
        .order_by(CollectorActivityEvent.created_at.desc(), CollectorActivityEvent.id.desc())
        .limit(RECENT_EVENTS_LIMIT)
    ).all()
    cards_by_id = _cards_by_id(db, list(recent))
    recent_events = [activity_event_to_out(e, cards_by_id.get(e.card_id)) for e in recent]

    return ActivitySummaryResult(
        today_count=today_count,
        last_7d_count=last_7d_count,
        last_30d_count=last_30d_count,
        by_source=by_source,
        recent_events=recent_events,
    )


def get_recent_activity_events(
    db: Session, limit: int = RECENT_EVENTS_LIMIT
) -> list[CollectorActivityEventOut]:
    """Used by the dashboard's recent_activity widget."""
    events = db.scalars(
        select(CollectorActivityEvent)
        .order_by(CollectorActivityEvent.created_at.desc(), CollectorActivityEvent.id.desc())
        .limit(limit)
    ).all()
    cards_by_id = _cards_by_id(db, list(events))
    return [activity_event_to_out(e, cards_by_id.get(e.card_id)) for e in events]
