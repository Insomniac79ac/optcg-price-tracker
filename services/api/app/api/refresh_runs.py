from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.models.price_refresh_run import RUN_STATUSES, PriceRefreshRun
from app.schemas import PriceRefreshRunListOut, PriceRefreshRunOut

router = APIRouter(
    prefix="/admin/refresh-runs", tags=["admin"], dependencies=[Depends(require_admin_token)]
)


@router.get("", response_model=PriceRefreshRunListOut)
def list_refresh_runs(
    status: str | None = Query(default=None),
    source_filter: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if status is not None and status not in RUN_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of {list(RUN_STATUSES)}",
        )

    filters = []
    if status is not None:
        filters.append(PriceRefreshRun.status == status)
    if source_filter is not None:
        filters.append(PriceRefreshRun.source_filter == source_filter)

    total = db.scalar(
        select(func.count()).select_from(PriceRefreshRun).where(*filters)
    ) or 0

    runs = db.scalars(
        select(PriceRefreshRun)
        .where(*filters)
        .order_by(PriceRefreshRun.started_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    return PriceRefreshRunListOut(
        items=[PriceRefreshRunOut.model_validate(run) for run in runs],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{run_id}", response_model=PriceRefreshRunOut)
def get_refresh_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(PriceRefreshRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Refresh run not found")
    return PriceRefreshRunOut.model_validate(run)
