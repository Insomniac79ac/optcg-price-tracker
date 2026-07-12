from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.models import MarketWorkflowRun
from app.schemas import MarketWorkflowRunListOut, MarketWorkflowRunOut

router = APIRouter(
    prefix="/admin/market-workflow-runs",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)

STATUS_VALUES = ("running", "success", "partial_success", "failed")


def _to_out(run: MarketWorkflowRun) -> MarketWorkflowRunOut:
    return MarketWorkflowRunOut(
        id=run.id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status,
        source=run.source,
        limit=run.limit,
        send_telegram=run.send_telegram,
        price_refresh_run_id=run.price_refresh_run_id,
        portfolio_snapshot_id=run.portfolio_snapshot_id,
        market_report_id=run.market_report_id,
        signal_events_created=run.signal_events_created,
        signal_events_updated=run.signal_events_updated,
        signal_events_resolved=run.signal_events_resolved,
        telegram_digest_status=run.telegram_digest_status,
        warnings=run.warnings_json or [],
        error_message=run.error_message,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


@router.get("", response_model=MarketWorkflowRunListOut)
def list_market_workflow_runs(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if status is not None and status not in STATUS_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of {list(STATUS_VALUES)}",
        )

    filters = []
    if status is not None:
        filters.append(MarketWorkflowRun.status == status)

    total = db.scalar(
        select(func.count()).select_from(MarketWorkflowRun).where(*filters)
    ) or 0

    runs = db.scalars(
        select(MarketWorkflowRun)
        .where(*filters)
        .order_by(MarketWorkflowRun.started_at.desc(), MarketWorkflowRun.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return MarketWorkflowRunListOut(
        items=[_to_out(run) for run in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{run_id}", response_model=MarketWorkflowRunOut)
def get_market_workflow_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(MarketWorkflowRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Market workflow run not found")
    return _to_out(run)
