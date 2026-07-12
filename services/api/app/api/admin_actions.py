from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.schemas import (
    AdminFullMarketRefreshRequest,
    AdminFullMarketRefreshResponse,
    AdminGenerateMarketReportResponse,
    AdminMarketSignalSnapshotCounts,
    AdminRefreshPricesRequest,
    AdminRefreshPricesResponse,
    AdminSendMarketReportDigestRequest,
    AdminSendMarketReportDigestResponse,
    AdminSnapshotMarketSignalsResponse,
    AdminSnapshotPortfolioResponse,
)
from app.services.market_report import generate_market_report
from app.services.market_signal_events import snapshot_market_signals
from app.services.refresh_trigger import trigger_price_refresh
from app.services.telegram_market_digest import send_market_report_digest
from app.snapshot_portfolio_valuation import snapshot_portfolio_valuation

router = APIRouter(
    prefix="/admin/actions", tags=["admin"], dependencies=[Depends(require_admin_token)]
)

# Matches worker.jobs.refresh_prices.SUPPORTED_SOURCES - kept as a separate
# literal here rather than imported, since the API service does not (and must
# not) depend on the worker package.
SOURCE_VALUES = ("all", "yuyutei", "snkrdunk")

# Matches the manual CLI's default (python -m worker.jobs.refresh_prices).
DEFAULT_REFRESH_LIMIT = 10

# Admin endpoint response only ever needs a short preview, not the full
# message - the raw message_text is available via the digest send row/CLI.
MESSAGE_PREVIEW_LENGTH = 300


def _message_preview(text: str | None) -> str | None:
    if text is None:
        return None
    if len(text) <= MESSAGE_PREVIEW_LENGTH:
        return text
    return text[:MESSAGE_PREVIEW_LENGTH] + "…"


def _validate_source(source: str) -> None:
    if source not in SOURCE_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid source. Must be one of {list(SOURCE_VALUES)}",
        )


@router.post("/refresh-prices", response_model=AdminRefreshPricesResponse)
def refresh_prices_action(body: AdminRefreshPricesRequest):
    _validate_source(body.source)
    limit = body.limit if body.limit is not None else DEFAULT_REFRESH_LIMIT

    try:
        job_id, result = trigger_price_refresh(
            source=body.source, limit=limit, dry_run=body.dry_run
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to trigger price refresh: {exc}"
        ) from exc

    return AdminRefreshPricesResponse(
        run_id=result.get("id"),
        job_id=job_id,
        status=result.get("status"),
        warnings=[],
    )


@router.post("/snapshot-portfolio", response_model=AdminSnapshotPortfolioResponse)
def snapshot_portfolio_action(db: Session = Depends(get_db)):
    snapshot = snapshot_portfolio_valuation(db)
    return AdminSnapshotPortfolioResponse(snapshot_id=snapshot.id)


@router.post("/snapshot-market-signals", response_model=AdminSnapshotMarketSignalsResponse)
def snapshot_market_signals_action(db: Session = Depends(get_db)):
    result = snapshot_market_signals(db)
    return AdminSnapshotMarketSignalsResponse(
        created_count=result.created,
        updated_count=result.updated,
        resolved_count=result.resolved,
    )


@router.post("/generate-market-report", response_model=AdminGenerateMarketReportResponse)
def generate_market_report_action(db: Session = Depends(get_db)):
    report = generate_market_report(db)
    return AdminGenerateMarketReportResponse(report_id=report.id)


@router.post("/full-market-refresh", response_model=AdminFullMarketRefreshResponse)
def full_market_refresh_action(
    body: AdminFullMarketRefreshRequest, db: Session = Depends(get_db)
):
    _validate_source(body.source)
    limit = body.limit if body.limit is not None else DEFAULT_REFRESH_LIMIT

    try:
        job_id, result = trigger_price_refresh(
            source=body.source, limit=limit, dry_run=body.dry_run
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to trigger price refresh: {exc}"
        ) from exc

    warnings: list[str] = []
    if result.get("status") == "failed":
        warnings.append(f"Price refresh failed: {result.get('error_message')}")

    portfolio_snapshot_id: int | None = None
    created = updated = resolved = 0
    market_report_id: int | None = None

    # Steps 2-4 are independent, best-effort follow-ups to the price refresh -
    # a failure in any one of them must never take down the others or fail
    # this endpoint outright, since the refresh itself already succeeded.
    if not body.dry_run:
        try:
            portfolio_snapshot_id = snapshot_portfolio_valuation(db).id
        except Exception as exc:
            db.rollback()
            warnings.append(f"Portfolio snapshot failed: {exc}")

        try:
            signal_result = snapshot_market_signals(db)
            created, updated, resolved = (
                signal_result.created,
                signal_result.updated,
                signal_result.resolved,
            )
        except Exception as exc:
            db.rollback()
            warnings.append(f"Market signal snapshot failed: {exc}")

        try:
            market_report_id = generate_market_report(db).id
        except Exception as exc:
            db.rollback()
            warnings.append(f"Market report generation failed: {exc}")

        # Best-effort notification on top of a successful report generation -
        # a Telegram outage must never take down (or roll back) the refresh
        # itself. Skipped digests (no Telegram config, or already sent) are
        # normal, silent outcomes, not warnings.
        if market_report_id is not None:
            try:
                digest_result = send_market_report_digest(db, dry_run=False, force=False)
                if digest_result is not None and digest_result.status == "failed":
                    warnings.append(
                        f"Market report digest failed: {digest_result.error_message}"
                    )
            except Exception as exc:
                db.rollback()
                warnings.append(f"Market report digest failed: {exc}")

    return AdminFullMarketRefreshResponse(
        price_refresh_run_id=result.get("id"),
        portfolio_snapshot_id=portfolio_snapshot_id,
        market_signal_snapshot=AdminMarketSignalSnapshotCounts(
            created=created, updated=updated, resolved=resolved
        ),
        market_report_id=market_report_id,
        dry_run=body.dry_run,
        warnings=warnings,
    )


@router.post("/send-market-report-digest", response_model=AdminSendMarketReportDigestResponse)
def send_market_report_digest_action(
    body: AdminSendMarketReportDigestRequest, db: Session = Depends(get_db)
):
    result = send_market_report_digest(db, dry_run=body.dry_run, force=body.force)

    if result is None:
        return AdminSendMarketReportDigestResponse(
            report_id=None,
            status=None,
            sent=False,
            skipped_reason="No market report found.",
            message_preview=None,
        )

    return AdminSendMarketReportDigestResponse(
        report_id=result.report_id,
        status=result.status,
        sent=result.sent,
        skipped_reason=result.skipped_reason,
        message_preview=_message_preview(result.message_text),
    )
