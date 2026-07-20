import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.schemas import (
    AdminFullMarketRefreshRequest,
    AdminFullMarketRefreshResponse,
    AdminGenerateAnalyticsDigestRequest,
    AdminGenerateAnalyticsDigestResponse,
    AdminGenerateMarketReportResponse,
    AdminMarketSignalSnapshotCounts,
    AdminRefreshPricesRequest,
    AdminRefreshPricesResponse,
    AdminRunMarketWorkflowRequest,
    AdminRunMarketWorkflowResponse,
    AdminSendMarketReportDigestRequest,
    AdminSendMarketReportDigestResponse,
    AdminSnapshotMarketSignalsResponse,
    AdminSnapshotPortfolioResponse,
)
from app.services.activity_timeline import record_activity_event
from app.services.analytics_digest import NoUsersError, generate_analytics_digest
from app.services.job_locks import LockHeldError, with_job_lock
from app.services.market_report import generate_market_report
from app.services.market_signal_events import snapshot_market_signals
from app.services.market_workflow_trigger import trigger_market_workflow
from app.services.refresh_trigger import trigger_price_refresh
from app.services.telegram_market_digest import send_market_report_digest
from app.snapshot_portfolio_valuation import snapshot_portfolio_valuation

logger = logging.getLogger(__name__)

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


def _try_generate_analytics_digest(db: Session) -> int | None:
    """Best-effort digest generation after a successful non-dry-run market
    workflow - a failure here (including "no user account yet") must never
    fail or roll back, or change the response of, the workflow that already
    succeeded. Per spec this only logs a warning on failure - it does not
    feed into the endpoint's own `warnings` list, which is reserved for
    issues with the price refresh/snapshot/report steps themselves. Returns
    the new report id, or None if generation was skipped/failed."""
    try:
        report = generate_analytics_digest(db)
    except LockHeldError as exc:
        logger.warning(
            "Analytics digest generation skipped after market workflow: %s lock already held.",
            exc.lock_name,
        )
        return None
    except Exception:
        logger.exception("Analytics digest generation failed after market workflow.")
        db.rollback()
        return None
    return report.id


@router.post("/refresh-prices", response_model=AdminRefreshPricesResponse)
def refresh_prices_action(body: AdminRefreshPricesRequest):
    _validate_source(body.source)
    limit = body.limit if body.limit is not None else DEFAULT_REFRESH_LIMIT

    try:
        job_id, result = trigger_price_refresh(
            source=body.source, limit=limit, dry_run=body.dry_run
        )
    except LockHeldError:
        raise
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

    record_activity_event(
        db,
        event_type="market_signal_snapshot",
        event_source="market_signal",
        title="Market signal snapshot taken",
        message=(
            f"Created: {result.created}, updated: {result.updated}, "
            f"resolved: {result.resolved}"
        ),
        payload={"created": result.created, "updated": result.updated, "resolved": result.resolved},
    )

    return AdminSnapshotMarketSignalsResponse(
        created_count=result.created,
        updated_count=result.updated,
        resolved_count=result.resolved,
    )


@router.post("/generate-market-report", response_model=AdminGenerateMarketReportResponse)
def generate_market_report_action(db: Session = Depends(get_db)):
    report = generate_market_report(db)

    record_activity_event(
        db,
        event_type="market_report_generated",
        event_source="market_report",
        title="Market intelligence report generated",
        market_report_id=report.id,
    )

    return AdminGenerateMarketReportResponse(report_id=report.id)


@router.post("/generate-analytics-digest", response_model=AdminGenerateAnalyticsDigestResponse)
def generate_analytics_digest_action(
    body: AdminGenerateAnalyticsDigestRequest, db: Session = Depends(get_db)
):
    try:
        report = generate_analytics_digest(db, valuation_mode=body.valuation_mode)
    except LockHeldError:
        raise
    except NoUsersError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    record_activity_event(
        db,
        event_type="analytics_digest_generated",
        event_source="analytics_digest",
        title="Analytics digest generated",
        payload={
            "report_id": report.id,
            "valuation_mode": report.valuation_mode,
            "portfolio_risk_score": report.portfolio_risk_score,
            "buy_review_count": report.buy_review_count,
            "sell_review_count": report.sell_review_count,
        },
    )

    return AdminGenerateAnalyticsDigestResponse(
        report_id=report.id,
        valuation_mode=report.valuation_mode,
        portfolio_risk_score=report.portfolio_risk_score or 0,
        buy_review_count=report.buy_review_count,
        sell_review_count=report.sell_review_count,
    )


@router.post("/full-market-refresh", response_model=AdminFullMarketRefreshResponse)
def full_market_refresh_action(
    body: AdminFullMarketRefreshRequest, db: Session = Depends(get_db)
):
    """Acquires the 'market_workflow' lock for the whole request - this
    endpoint does the same overall work as POST /admin/actions/run-market-
    workflow (refresh + snapshot + signals + report + optional digest), just
    synchronously in-process instead of via a Celery-dispatched worker job,
    so the two must not be allowed to run concurrently. Each step below
    (price refresh via Celery, then the in-process snapshot/signal/report/
    digest calls) also acquires its own distinct-named lock independently -
    see app.services.job_locks's module docstring for why that nesting is
    always deadlock-free."""
    _validate_source(body.source)
    limit = body.limit if body.limit is not None else DEFAULT_REFRESH_LIMIT

    with with_job_lock(
        "market_workflow", metadata={"source": body.source, "limit": limit, "dry_run": body.dry_run}
    ):
        return _full_market_refresh_locked(body, limit, db)


def _full_market_refresh_locked(
    body: AdminFullMarketRefreshRequest, limit: int, db: Session
) -> AdminFullMarketRefreshResponse:
    try:
        job_id, result = trigger_price_refresh(
            source=body.source, limit=limit, dry_run=body.dry_run
        )
    except LockHeldError:
        raise
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

        # Best-effort, independent of whether the market report step above
        # succeeded - the digest composes from collection/wishlist/buy/sell/
        # grading/portfolio-risk analytics directly, not from the market
        # report row. A failure here is only logged (see
        # _try_generate_analytics_digest), never added to `warnings`.
        _try_generate_analytics_digest(db)

    if not body.dry_run:
        record_activity_event(
            db,
            event_type="full_market_refresh",
            event_source="workflow",
            title="Full market refresh completed" if not warnings else "Full market refresh completed with warnings",
            message="; ".join(warnings) if warnings else None,
            market_report_id=market_report_id,
            payload={
                "price_refresh_run_id": result.get("id"),
                "portfolio_snapshot_id": portfolio_snapshot_id,
                "signal_events_created": created,
                "signal_events_updated": updated,
                "signal_events_resolved": resolved,
            },
        )

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


@router.post("/run-market-workflow", response_model=AdminRunMarketWorkflowResponse)
def run_market_workflow_action(body: AdminRunMarketWorkflowRequest, db: Session = Depends(get_db)):
    _validate_source(body.source)
    limit = body.limit if body.limit is not None else DEFAULT_REFRESH_LIMIT

    try:
        job_id, result = trigger_market_workflow(
            source=body.source,
            limit=limit,
            send_telegram=body.send_telegram,
            dry_run=body.dry_run,
        )
    except LockHeldError:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to trigger market workflow: {exc}"
        ) from exc

    warnings = result.get("warnings") or []

    if not body.dry_run:
        # Best-effort, only after a non-dry-run workflow that didn't
        # outright fail - see app.services.analytics_digest and 'Worker
        # integration' in docs/operations.md's Analytics digest section for
        # why this runs here (in the API process, after the Celery-
        # dispatched worker job returns) rather than inside the worker job
        # itself: the digest composes six API-only analytics services the
        # worker package has no access to. A failure here is only logged
        # (see _try_generate_analytics_digest), never added to `warnings`.
        if result.get("status") != "failed":
            _try_generate_analytics_digest(db)

        record_activity_event(
            db,
            event_type="market_workflow_run",
            event_source="workflow",
            title=f"Market workflow run: {result.get('status')}",
            message="; ".join(warnings) if warnings else None,
            market_report_id=result.get("market_report_id"),
            market_workflow_run_id=result.get("market_workflow_run_id"),
            payload={
                "price_refresh_run_id": result.get("price_refresh_run_id"),
                "portfolio_snapshot_id": result.get("portfolio_snapshot_id"),
                "signal_events_created": result.get("signal_events_created"),
                "signal_events_updated": result.get("signal_events_updated"),
                "signal_events_resolved": result.get("signal_events_resolved"),
            },
        )

    return AdminRunMarketWorkflowResponse(
        market_workflow_run_id=result.get("market_workflow_run_id"),
        status=result.get("status"),
        price_refresh_run_id=result.get("price_refresh_run_id"),
        portfolio_snapshot_id=result.get("portfolio_snapshot_id"),
        market_signal_snapshot=AdminMarketSignalSnapshotCounts(
            created=result.get("signal_events_created") or 0,
            updated=result.get("signal_events_updated") or 0,
            resolved=result.get("signal_events_resolved") or 0,
        ),
        market_report_id=result.get("market_report_id"),
        telegram_digest_status=result.get("telegram_digest_status"),
        warnings=warnings,
    )
