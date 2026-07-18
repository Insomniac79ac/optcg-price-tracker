from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.schemas import (
    LargestResponseOut,
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
        response_size_warnings_last_24h=summary.response_size_warnings_last_24h,
        slow_requests_last_24h=summary.slow_requests_last_24h,
        largest_recent_responses=[
            LargestResponseOut(
                created_at=r.created_at, method=r.method, path=r.path, size_bytes=r.size_bytes
            )
            for r in summary.largest_recent_responses
        ],
    )
