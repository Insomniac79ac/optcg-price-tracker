"""Triggers the existing worker `run_market_workflow` job via Celery instead
of duplicating any scraping/adapter logic in this service - the API process
has no source adapters (those live in services/worker, a separate deployable
with its own dependencies) and must never attempt scraping directly.

See services/worker/worker/celery_app.py's `run_market_workflow_task`, which
wraps the exact same run_market_workflow() job used by the manual CLI
(`python -m worker.jobs.run_market_workflow`) and the scheduled daily
workflow - this module only enqueues that task and waits for its result.
"""

from celery import Celery

from app.settings import settings

TASK_NAME = "worker.celery_app.run_market_workflow_task"

# The workflow does more work than a bare price refresh (snapshot + report +
# optional Telegram send on top of it), so this allows more headroom than
# refresh_trigger.py's TRIGGER_TIMEOUT_SECONDS before giving up.
TRIGGER_TIMEOUT_SECONDS = 45


def _celery_client() -> Celery:
    return Celery(broker=settings.REDIS_URL, backend=settings.REDIS_URL)


def trigger_market_workflow(
    source: str, limit: int, send_telegram: bool, dry_run: bool
) -> tuple[str, dict]:
    """Enqueues worker.celery_app.run_market_workflow_task and blocks
    (bounded by TRIGGER_TIMEOUT_SECONDS) until it finishes, so callers get a
    concrete market_workflow_run_id back rather than just a pending job.
    Raises on timeout or broker connection failure - callers turn that into
    an HTTP error instead of hanging indefinitely.

    Returns (celery_task_id, result_dict) where result_dict is the
    dataclasses.asdict() of the worker's MarketWorkflowResult.
    """
    client = _celery_client()
    async_result = client.send_task(
        TASK_NAME,
        kwargs={
            "source": source,
            "limit": limit,
            "send_telegram": send_telegram,
            "dry_run": dry_run,
        },
    )
    result = async_result.get(timeout=TRIGGER_TIMEOUT_SECONDS)
    return async_result.id, result
