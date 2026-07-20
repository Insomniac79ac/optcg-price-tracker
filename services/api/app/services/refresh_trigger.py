"""Triggers the existing worker `refresh_prices` job via Celery instead of
duplicating any scraping/adapter logic in this service - the API process has
no source adapters (those live in services/worker, a separate deployable with
its own dependencies) and must never attempt scraping directly.

See services/worker/worker/celery_app.py's `run_price_refresh` task, which
wraps the exact same refresh_prices() job used by the manual CLI
(`python -m worker.jobs.refresh_prices`) and the scheduled Yuyu-Tei refresh -
this module only enqueues that task and waits for its result.
"""

from datetime import datetime

from celery import Celery

from app.services.cache import delete_cache_prefix
from app.services.job_locks import LockHeldError
from app.settings import settings

TASK_NAME = "worker.celery_app.run_price_refresh"

# Bounds how long an admin action waits for the worker to finish a refresh
# before giving up - generous enough for a small on-demand `limit`, but short
# enough that a stuck/absent worker surfaces as a clear error rather than a
# hung request.
TRIGGER_TIMEOUT_SECONDS = 25

# See 'Cache invalidation' in docs/operations.md - new price observations
# change nearly every cached read surface in the app. The worker process
# that actually writes price_observations has no access to this cache (it's
# a separate deployable, see the module docstring below), so invalidation
# happens here instead, once the triggering request gets its result back.
_PRICE_REFRESH_CACHE_INVALIDATES = (
    "dashboard",
    "collection_valuation",
    "collection_history",
    "collection_analytics",
    "wishlist_analytics",
    "market_signals",
    "market_signal_events",
    "market_opportunities",
    "market_report",
    "wishlist",
    "wishlist_summary",
    "sell_decisions",
    "buy_decisions",
    "grading_analytics",
)


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

    Raises app.services.job_locks.LockHeldError (a class local to this
    service, not the worker's) if the worker's own 'price_refresh' lock was
    already held - the worker task returns a plain lock_held dict rather
    than raising its own LockHeldError across the Celery result boundary
    (see worker.celery_app._lock_held_result), and this is where that dict
    gets turned back into a proper exception for admin_actions.py to catch.
    """
    client = _celery_client()
    async_result = client.send_task(
        TASK_NAME,
        kwargs={"source": source, "limit": limit, "dry_run": dry_run},
    )
    result = async_result.get(timeout=TRIGGER_TIMEOUT_SECONDS)
    if isinstance(result, dict) and result.get("lock_held"):
        raise LockHeldError(
            result["lock_name"], result["owner_id"], datetime.fromisoformat(result["expires_at"])
        )
    if not dry_run and isinstance(result, dict) and result.get("status") != "failed":
        for prefix in _PRICE_REFRESH_CACHE_INVALIDATES:
            delete_cache_prefix(prefix)
    return async_result.id, result
