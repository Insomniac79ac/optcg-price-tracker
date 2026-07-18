from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import require_current_user
from app.core.pagination import pagination_response
from app.db import get_db
from app.models import User
from app.models.collector_activity_event import EVENT_SOURCES
from app.schemas import (
    CollectorActivityListOut,
    CollectorActivityListSummaryOut,
    CollectorActivitySummaryOut,
)
from app.services.activity_timeline import get_activity_summary, list_activity_events

router = APIRouter(prefix="/collector/activity", tags=["collector-activity"])


@router.get("", response_model=CollectorActivityListOut)
def list_activity(
    event_source: str | None = Query(default=None, description=f"One of {EVENT_SOURCES}"),
    event_type: str | None = None,
    card_id: int | None = None,
    collection_item_id: int | None = None,
    wishlist_item_id: int | None = None,
    grading_submission_id: int | None = None,
    market_signal_event_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(require_current_user),
):
    result = list_activity_events(
        db,
        event_source=event_source,
        event_type=event_type,
        card_id=card_id,
        collection_item_id=collection_item_id,
        wishlist_item_id=wishlist_item_id,
        grading_submission_id=grading_submission_id,
        market_signal_event_id=market_signal_event_id,
        limit=limit,
        offset=offset,
    )
    return CollectorActivityListOut(
        summary=CollectorActivityListSummaryOut(
            total_events=result.total_events,
            by_source=result.by_source,
            by_type=result.by_type,
        ),
        events=result.events,
        limit=limit,
        offset=offset,
        pagination=pagination_response(result.events, result.total_events, limit, offset),
    )


@router.get("/summary", response_model=CollectorActivitySummaryOut)
def activity_summary(
    db: Session = Depends(get_db),
    _user: User = Depends(require_current_user),
):
    result = get_activity_summary(db)
    return CollectorActivitySummaryOut(
        today_count=result.today_count,
        last_7d_count=result.last_7d_count,
        last_30d_count=result.last_30d_count,
        by_source=result.by_source,
        recent_events=result.recent_events,
    )
