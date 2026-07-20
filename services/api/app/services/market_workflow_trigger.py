"""Triggers the existing worker `run_market_workflow` job via Celery instead
of duplicating any scraping/adapter logic in this service - the API process
has no source adapters (those live in services/worker, a separate deployable
with its own dependencies) and must never attempt scraping directly.

See services/worker/worker/celery_app.py's `run_market_workflow_task`, which
wraps the exact same run_market_workflow() job used by the manual CLI
(`python -m worker.jobs.run_market_workflow`) and the scheduled daily
workflow - this module only enqueues that task and waits for its result.
"""

from datetime import datetime

from celery import Celery

from app.services.cache import delete_cache_prefix
from app.services.job_locks import LockHeldError
from app.settings import settings

TASK_NAME = "worker.celery_app.run_market_workflow_task"

# The full workflow does everything a price refresh + portfolio snapshot +
# market signal snapshot + report generation would - see 'Cache
# invalidation' in docs/operations.md - so this invalidates the union of
# all of those prefixes rather than duplicating each step's own list.
_MARKET_WORKFLOW_CACHE_INVALIDATES = (
    "dashboard",
    "collection_valuation",
    "collection_history",
    "collection_analytics",
    "wishlist_analytics",
    "market_signals",
    "market_signal_events",
    "market_opportunities",
    "market_report",
    "market_reports",
    "wishlist",
    "wishlist_summary",
    "sell_decisions",
    "buy_decisions",
)

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

    Raises app.services.job_locks.LockHeldError if the worker's own
    'market_workflow' lock was already held - see
    app.services.refresh_trigger.trigger_price_refresh's docstring for why
    this is translated from a plain dict rather than a raised exception
    crossing the Celery result boundary.
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
    if isinstance(result, dict) and result.get("lock_held"):
        raise LockHeldError(
            result["lock_name"], result["owner_id"], datetime.fromisoformat(result["expires_at"])
        )
    if not dry_run and isinstance(result, dict) and result.get("status") != "failed":
        for prefix in _MARKET_WORKFLOW_CACHE_INVALIDATES:
            delete_cache_prefix(prefix)
    return async_result.id, result
