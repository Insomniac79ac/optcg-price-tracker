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
        latest_price_refresh_run=summary.latest_price_refresh_run,
        latest_backup=summary.latest_backup,
        latest_system_check_status=summary.latest_system_check_status,
    )


class DeliberateSentryTestError(RuntimeError):
    """Raised only by the endpoint below."""


@router.get("/sentry-test", include_in_schema=False)
def sentry_test_endpoint():
    """Fail on purpose so an operator can confirm API error tracking reaches
    Sentry (Collector v1 S2). Admin-token only, read-only, writes nothing."""
    raise DeliberateSentryTestError("Deliberate Sentry test error (api). Safe to ignore.")
