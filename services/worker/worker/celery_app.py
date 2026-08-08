import logging
from dataclasses import asdict
from datetime import timedelta

from celery import Celery
from celery.schedules import crontab

from worker.app_logging import record_app_log
from worker.data_retention import CONFIRM_PHRASE, prune_tables
from worker.db import SessionLocal
from worker.env_validation import validate_environment
from worker.job_locks import LockHeldError, with_job_lock
from worker.jobs.check_alerts import check_alerts
from worker.jobs.refresh_prices import refresh_prices
from worker.jobs.run_market_workflow import run_market_workflow
from worker.settings import Settings, settings

logger = logging.getLogger(__name__)


def _lock_held_result(exc: LockHeldError) -> dict:
    """Plain-dict sentinel (JSON-serializable, no custom exception class) for
    a Celery task result when its job's own lock acquisition fails - letting
    a custom exception cross the Celery result-backend boundary is fragile
    (the API service can't import worker.job_locks.LockHeldError to
    reconstruct it), so the lock conflict is reported as data instead. See
    app.services.refresh_trigger/market_workflow_trigger, which turn this
    back into an app.services.job_locks.LockHeldError (a *different* class,
    local to the api service) for admin_actions.py to turn into a 409."""
    return {
        "lock_held": True,
        "lock_name": exc.lock_name,
        "owner_id": exc.owner_id,
        "expires_at": exc.expires_at.isoformat(),
    }

# Fail fast and loud, same as the API (see app/main.py): a misconfigured
# production deployment should never come up processing jobs or scheduling
# them. Runs once, at process import - both `celery -A worker.celery_app
# worker` and `celery -A worker.celery_app beat` import this module, so this
# covers both entry points, including the MARKET_WORKFLOW_* schedule vars
# beat reads below in _build_beat_schedule. Development only warns (see
# worker/env_validation.py's rule 2) so local defaults keep working.
_env_report = validate_environment()
for _warning in _env_report.warnings:
    logger.warning("env validation warning: %s", _warning)
if not _env_report.ok:
    raise RuntimeError(
        "Invalid production environment configuration - refusing to start worker/beat: "
        + "; ".join(_env_report.errors)
    )

# Scheduled runs cover more mappings per pass than the manual CLI's default
# (--limit 10), since they run unattended every PRICE_REFRESH_INTERVAL_HOURS
# rather than being kicked off on demand.
SCHEDULED_YUYUTEI_REFRESH_LIMIT = 100


def _build_beat_schedule(current_settings: Settings) -> dict:
    """Split out from module-level construction so tests can exercise the
    MARKET_WORKFLOW_ENABLED on/off branch directly, without needing to
    reimport this module under different environment variables."""
    schedule: dict = {}

    if current_settings.LEGACY_PRICE_REFRESH_ENABLED:
        schedule["refresh-yuyutei-prices"] = {
            "task": "worker.celery_app.refresh_yuyutei_prices",
            "schedule": timedelta(hours=current_settings.PRICE_REFRESH_INTERVAL_HOURS),
        }

    if current_settings.MARKET_WORKFLOW_ENABLED:
        schedule["run-market-workflow"] = {
            "task": "worker.celery_app.run_market_workflow_task",
            "schedule": crontab(
                hour=current_settings.MARKET_WORKFLOW_HOUR_UTC,
                minute=current_settings.MARKET_WORKFLOW_MINUTE_UTC,
            ),
            "kwargs": {
                "source": current_settings.MARKET_WORKFLOW_SOURCE,
                "limit": current_settings.MARKET_WORKFLOW_LIMIT,
                "send_telegram": current_settings.MARKET_WORKFLOW_SEND_TELEGRAM,
                "dry_run": False,
            },
        }

    if current_settings.DATA_RETENTION_ENABLED:
        schedule["prune-data-retention"] = {
            "task": "worker.celery_app.prune_data_retention_task",
            "schedule": crontab(
                hour=current_settings.DATA_RETENTION_HOUR_UTC,
                minute=current_settings.DATA_RETENTION_MINUTE_UTC,
            ),
        }

    return schedule


app = Celery("worker", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
app.conf.timezone = "UTC"
app.conf.beat_schedule = _build_beat_schedule(settings)


@app.task(name="worker.celery_app.refresh_yuyutei_prices")
def refresh_yuyutei_prices(limit: int = SCHEDULED_YUYUTEI_REFRESH_LIMIT) -> dict:
    """Scheduled Yuyu-Tei price refresh, run every PRICE_REFRESH_INTERVAL_HOURS
    hours by Celery Beat. Delegates to the same refresh_prices() job logic as
    the manual `python -m worker.jobs.refresh_prices --source yuyutei`
    command - this task does not set or override SCRAPING_MODE or
    YUYUTEI_REQUEST_DELAY_MS, both of which come from settings/environment
    exactly like the manual command does, so live vs. mock behavior and rate
    limiting stay identical between the two entry points."""
    logger.info("SCRAPING_MODE=%s", settings.SCRAPING_MODE)
    logger.info("source_filter=yuyutei")
    logger.info("limit=%s", limit)
    logger.info("dry_run=false")

    db = SessionLocal()
    try:
        try:
            summary = refresh_prices(limit=limit, db=db, source="yuyutei")
        except LockHeldError as exc:
            logger.warning("Scheduled Yuyu-Tei refresh skipped: %s", exc)
            return _lock_held_result(exc)
        try:
            check_alerts(db)
        except Exception:
            # Alerting must never take down the scheduled refresh itself.
            logger.exception("check_alerts failed after refresh run %s.", summary.id)
    finally:
        db.close()

    for line in summary.report_lines():
        logger.info(line)

    return asdict(summary)


@app.task(name="worker.celery_app.run_market_workflow_task")
def run_market_workflow_task(
    source: str = "yuyutei",
    limit: int | None = None,
    send_telegram: bool = False,
    dry_run: bool = False,
) -> dict:
    """Runs the full market intelligence workflow (see
    worker/jobs/run_market_workflow.py): refresh prices, snapshot the
    portfolio and market signals, generate a report, and optionally send a
    Telegram digest. Scheduled daily by Celery Beat when
    MARKET_WORKFLOW_ENABLED is true (see _build_beat_schedule above), and
    also triggered on demand by the API's
    POST /admin/actions/run-market-workflow via Celery send_task."""
    db = SessionLocal()
    try:
        try:
            result = run_market_workflow(
                db, source=source, limit=limit, send_telegram=send_telegram, dry_run=dry_run
            )
        except LockHeldError as exc:
            logger.warning("Market workflow run skipped: %s", exc)
            return _lock_held_result(exc)
    finally:
        db.close()

    return asdict(result)


@app.task(name="worker.celery_app.run_price_refresh")
def run_price_refresh(source: str = "all", limit: int = 10, dry_run: bool = False) -> dict:
    """On-demand price refresh triggered by the API's admin actions endpoints
    (POST /admin/actions/refresh-prices and /admin/actions/full-market-refresh)
    via Celery send_task. Delegates to the same refresh_prices() job logic as
    the scheduled Yuyu-Tei task and the manual CLI - this task exists only to
    let source/limit/dry_run be chosen per-request instead of hardcoded to the
    Yuyu-Tei schedule."""
    logger.info("SCRAPING_MODE=%s", settings.SCRAPING_MODE)
    logger.info("source_filter=%s", source)
    logger.info("limit=%s", limit)
    logger.info("dry_run=%s", dry_run)

    db = SessionLocal()
    try:
        try:
            summary = refresh_prices(limit=limit, db=db, source=source, dry_run=dry_run)
        except LockHeldError as exc:
            logger.warning("On-demand price refresh skipped: %s", exc)
            return _lock_held_result(exc)
        if not dry_run:
            try:
                check_alerts(db)
            except Exception:
                # Alerting must never take down an otherwise-successful refresh.
                logger.exception("check_alerts failed after refresh run %s.", summary.id)
    finally:
        db.close()

    for line in summary.report_lines():
        logger.info(line)

    return asdict(summary)


@app.task(name="worker.celery_app.prune_data_retention_task")
def prune_data_retention_task() -> dict:
    """Scheduled data retention prune - runs daily by Celery Beat when
    DATA_RETENTION_ENABLED is true (see _build_beat_schedule above and "Data
    retention and pruning" in docs/operations.md). Always runs with
    dry_run=False, confirmed internally - this task exists specifically to
    apply the policy unattended; use the admin UI/CLI (POST
    /admin/data-retention/prune, python -m app.prune_data_retention) for a
    preview first. Never raises - a failure here must not take down beat or
    any other scheduled job, it's recorded as an app_log_events row instead
    (see worker.data_retention.prune_tables for the per-table policy, same
    logic as app.services.data_retention on the api service)."""
    db = None
    try:
        db = SessionLocal()
        with with_job_lock(db, "data_retention_prune"):
            result = prune_tables(db, dry_run=False, confirm=CONFIRM_PHRASE)
    except LockHeldError as exc:
        # Another prune (scheduled or manual, on either service) is already
        # running - not a failure, just skip this tick.
        logger.warning("Scheduled data retention prune skipped: %s", exc)
        return {"status": "skipped", "reason": "lock_held", **_lock_held_result(exc)}
    except Exception as exc:  # noqa: BLE001 - must never fail beat/worker itself
        logger.exception("Scheduled data retention prune failed.")
        record_app_log(
            "error",
            "worker",
            "data_retention_prune_failed",
            f"Scheduled data retention prune failed: {exc}",
        )
        return {"status": "failed", "error": str(exc)}
    finally:
        if db is not None:
            db.close()

    summary = result.summary
    results = [asdict(r) for r in result.results]
    record_app_log(
        "warning" if summary["warnings"] else "info",
        "worker",
        "data_retention_prune",
        f"Scheduled data retention prune: {summary['total_rows_deleted']} row(s) deleted "
        f"across {summary['tables_checked']} table(s), {summary['warnings']} warning(s).",
        context={"summary": summary, "results": results},
    )
    return {"summary": summary, "results": results}
