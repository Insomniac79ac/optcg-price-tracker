from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.admin_logs import app_log_to_out
from app.auth import require_admin_token
from app.db import get_db
from app.schemas import ObservabilityLast24hOut, ObservabilitySummaryOut
from app.services.observability import build_observability_summary

router = APIRouter(
    prefix="/admin/observability", tags=["admin", "observability"], dependencies=[Depends(require_admin_token)]
)


@router.get("/summary", response_model=ObservabilitySummaryOut)
def observability_summary_endpoint(db: Session = Depends(get_db)):
    summary = build_observability_summary(db)

    return ObservabilitySummaryOut(
        status=summary.status,
        last_24h=ObservabilityLast24hOut(**summary.last_24h),
        latest_error=app_log_to_out(summary.latest_error) if summary.latest_error is not None else None,
        latest_market_workflow_run=summary.latest_market_workflow_run,
        latest_price_refresh_run=summary.latest_price_refresh_run,
        latest_backup=summary.latest_backup,
        latest_system_check_status=summary.latest_system_check_status,
    )
