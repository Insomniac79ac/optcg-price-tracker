from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.schemas import (
    AdminFullMarketRefreshRequest,
    AdminFullMarketRefreshResponse,
    AdminRefreshPricesRequest,
    AdminRefreshPricesResponse,
    AdminSnapshotPortfolioResponse,
)
from app.services.activity_timeline import record_activity_event
from app.services.job_locks import LockHeldError, with_job_lock
from app.services.refresh_trigger import trigger_price_refresh
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


@router.post("/full-market-refresh", response_model=AdminFullMarketRefreshResponse)
def full_market_refresh_action(
    body: AdminFullMarketRefreshRequest, db: Session = Depends(get_db)
):
    """Triggers a price refresh and, unless dry-run, a portfolio valuation
    snapshot, synchronously. Holds the 'market_workflow' lock for the whole
    request so two full refreshes never overlap; the price refresh and the
    snapshot each also take their own distinct-named lock (see
    app.services.job_locks's module docstring for why that nesting is
    deadlock-free). The market signal, market report and digest steps that
    used to follow were removed with the legacy market workflow (Collector
    v1 S1)."""
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

    # Best-effort follow-up to the price refresh: a snapshot failure must
    # never fail this endpoint outright, since the refresh itself succeeded.
    if not body.dry_run:
        try:
            portfolio_snapshot_id = snapshot_portfolio_valuation(db).id
        except Exception as exc:
            db.rollback()
            warnings.append(f"Portfolio snapshot failed: {exc}")

    if not body.dry_run:
        record_activity_event(
            db,
            event_type="full_market_refresh",
            event_source="workflow",
            title="Full market refresh completed" if not warnings else "Full market refresh completed with warnings",
            message="; ".join(warnings) if warnings else None,
            payload={
                "price_refresh_run_id": result.get("id"),
                "portfolio_snapshot_id": portfolio_snapshot_id,
            },
        )

    return AdminFullMarketRefreshResponse(
        price_refresh_run_id=result.get("id"),
        portfolio_snapshot_id=portfolio_snapshot_id,
        dry_run=body.dry_run,
        warnings=warnings,
    )
