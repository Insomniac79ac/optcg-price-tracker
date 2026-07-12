import logging
from dataclasses import asdict
from datetime import timedelta

from celery import Celery

from worker.db import SessionLocal
from worker.jobs.check_alerts import check_alerts
from worker.jobs.refresh_prices import refresh_prices
from worker.settings import settings

logger = logging.getLogger(__name__)

# Scheduled runs cover more mappings per pass than the manual CLI's default
# (--limit 10), since they run unattended every PRICE_REFRESH_INTERVAL_HOURS
# rather than being kicked off on demand.
SCHEDULED_YUYUTEI_REFRESH_LIMIT = 100

app = Celery("worker", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
app.conf.timezone = "UTC"
app.conf.beat_schedule = {
    "refresh-yuyutei-prices": {
        "task": "worker.celery_app.refresh_yuyutei_prices",
        "schedule": timedelta(hours=settings.PRICE_REFRESH_INTERVAL_HOURS),
    },
}


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
