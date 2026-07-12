"""Triggers the existing worker `refresh_prices` job via Celery instead of
duplicating any scraping/adapter logic in this service - the API process has
no source adapters (those live in services/worker, a separate deployable with
its own dependencies) and must never attempt scraping directly.

See services/worker/worker/celery_app.py's `run_price_refresh` task, which
wraps the exact same refresh_prices() job used by the manual CLI
(`python -m worker.jobs.refresh_prices`) and the scheduled Yuyu-Tei refresh -
this module only enqueues that task and waits for its result.
"""

from celery import Celery

from app.settings import settings

TASK_NAME = "worker.celery_app.run_price_refresh"

# Bounds how long an admin action waits for the worker to finish a refresh
# before giving up - generous enough for a small on-demand `limit`, but short
# enough that a stuck/absent worker surfaces as a clear error rather than a
# hung request.
TRIGGER_TIMEOUT_SECONDS = 25


def _celery_client() -> Celery:
    return Celery(broker=settings.REDIS_URL, backend=settings.REDIS_URL)


def trigger_price_refresh(source: str, limit: int, dry_run: bool) -> tuple[str, dict]:
    """Enqueues worker.celery_app.run_price_refresh and blocks (bounded by
    TRIGGER_TIMEOUT_SECONDS) until it finishes, so callers get a concrete
    run_id back rather than just a pending job. Raises on timeout or broker
    connection failure - callers turn that into an HTTP error instead of
    hanging indefinitely.

    Returns (celery_task_id, result_dict) where result_dict is the
    dataclasses.asdict() of the worker's RefreshRunSummary.
    """
    client = _celery_client()
    async_result = client.send_task(
        TASK_NAME,
        kwargs={"source": source, "limit": limit, "dry_run": dry_run},
    )
    result = async_result.get(timeout=TRIGGER_TIMEOUT_SECONDS)
    return async_result.id, result
