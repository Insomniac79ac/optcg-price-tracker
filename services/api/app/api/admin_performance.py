from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.schemas import (
    PerformanceDatabaseCountsOut,
    PerformanceIndexAuditSummaryOut,
    PerformanceSummaryOut,
    SlowRequestOut,
)
from app.services.performance import build_performance_summary

router = APIRouter(
    prefix="/admin/performance", tags=["admin", "performance"], dependencies=[Depends(require_admin_token)]
)


@router.get("/summary", response_model=PerformanceSummaryOut)
def performance_summary_endpoint(db: Session = Depends(get_db)):
    summary = build_performance_summary(db)

    return PerformanceSummaryOut(
        status=summary.status,
        database=PerformanceDatabaseCountsOut(**summary.database),
        latest_slow_requests=[
            SlowRequestOut(created_at=e.created_at, message=e.message, context=e.context_json)
            for e in summary.latest_slow_requests
        ],
        index_audit=PerformanceIndexAuditSummaryOut(**summary.index_audit),
    )
