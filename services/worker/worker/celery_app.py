import logging
from dataclasses import asdict
from datetime import timedelta

from celery import Celery
from celery.schedules import crontab

from worker.db import SessionLocal
from worker.env_validation import validate_environment
from worker.jobs.check_alerts import check_alerts
from worker.jobs.refresh_prices import refresh_prices
from worker.jobs.run_market_workflow import run_market_workflow
from worker.settings import Settings, settings

logger = logging.getLogger(__name__)

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
    schedule: dict = {
        "refresh-yuyutei-prices": {
            "task": "worker.celery_app.refresh_yuyutei_prices",
            "schedule": timedelta(hours=current_settings.PRICE_REFRESH_INTERVAL_HOURS),
        },
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
        summary = refresh_prices(limit=limit, db=db, source="yuyutei")
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
        result = run_market_workflow(
            db, source=source, limit=limit, send_telegram=send_telegram, dry_run=dry_run
        )
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
        summary = refresh_prices(limit=limit, db=db, source=source, dry_run=dry_run)
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
