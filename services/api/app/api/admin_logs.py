from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.models import AppLogEvent
from app.schemas import (
    AppLogEventOut,
    AppLogListOut,
    AppLogPruneRequestIn,
    AppLogPruneResponseOut,
    AppLogSummaryOut,
)
from app.services.app_logging import (
    LOG_LEVELS,
    PruneConfirmationRequired,
    list_app_logs,
    prune_app_logs,
)

router = APIRouter(
    prefix="/admin/logs", tags=["admin", "observability"], dependencies=[Depends(require_admin_token)]
)


def app_log_to_out(log: AppLogEvent) -> AppLogEventOut:
    return AppLogEventOut(
        id=log.id,
        created_at=log.created_at,
        level=log.level,
        service=log.service,
        event_type=log.event_type,
        message=log.message,
        context=log.context_json,
        traceback=log.traceback,
        related_run_id=log.related_run_id,
        related_entity_type=log.related_entity_type,
        related_entity_id=log.related_entity_id,
    )


@router.get("", response_model=AppLogListOut)
def list_logs_endpoint(
    level: str | None = Query(default=None),
    service: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    since_hours: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if level is not None and level not in LOG_LEVELS:
        raise HTTPException(status_code=400, detail=f"Invalid level. Must be one of {list(LOG_LEVELS)}")

    result = list_app_logs(
        db,
        level=level,
        service=service,
        event_type=event_type,
        q=q,
        since_hours=since_hours,
        limit=limit,
        offset=offset,
    )

    return AppLogListOut(
        summary=AppLogSummaryOut(
            total_logs=result.total_logs,
            error_count=result.error_count,
            warning_count=result.warning_count,
            critical_count=result.critical_count,
            by_service=result.by_service,
            by_event_type=result.by_event_type,
        ),
        logs=[app_log_to_out(log) for log in result.logs],
    )


@router.get("/{log_id}", response_model=AppLogEventOut)
def get_log_endpoint(log_id: int, db: Session = Depends(get_db)):
    log = db.get(AppLogEvent, log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="Log event not found")
    return app_log_to_out(log)


@router.post("/prune", response_model=AppLogPruneResponseOut)
def prune_logs_endpoint(body: AppLogPruneRequestIn, db: Session = Depends(get_db)):
    try:
        result = prune_app_logs(
            db, older_than_days=body.older_than_days, dry_run=body.dry_run, confirm=body.confirm
        )
    except PruneConfirmationRequired as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return AppLogPruneResponseOut(
        dry_run=result.dry_run,
        older_than_days=result.older_than_days,
        would_delete=result.would_delete,
        deleted=result.deleted,
    )
