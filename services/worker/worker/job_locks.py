"""Mirrors app.services.job_locks on the api service - same table, same
acquire/release semantics, same LOCK_TTL_SECONDS. Used by
worker.jobs.refresh_prices and worker.jobs.run_market_workflow (manual CLI,
Celery task, and beat-scheduled entry points all go through the same
functions in those modules, so locking here covers all three uniformly).
See 'Worker job concurrency locking' in docs/operations.md.

Acquisition is non-blocking and fails clean (LockHeldError) rather than
waiting - see app.services.job_locks's module docstring for why that makes
nested acquisition (e.g. run_market_workflow holding market_workflow while
refresh_prices acquires price_refresh beneath it) deadlock-free with no
special-casing needed.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from worker.app_logging import record_app_log
from worker.models import JobLock

LOCK_TTL_SECONDS: dict[str, int] = {
    "price_refresh": 30 * 60,
    "market_workflow": 60 * 60,
    "portfolio_snapshot": 10 * 60,
    "market_signal_snapshot": 10 * 60,
    "market_report_generation": 10 * 60,
    "telegram_market_digest": 5 * 60,
    "data_retention_prune": 30 * 60,
    "backup_restore": 60 * 60,
    # Bounded discovery: a run is capped at ~5 minutes of wall clock,
    # so a 30-minute TTL leaves ample slack for a stuck fetch while
    # still releasing on its own after a hard container kill.
    "snkrdunk_discovery": 30 * 60,
}


def make_owner_id(lock_name: str) -> str:
    return f"{lock_name}:{uuid.uuid4()}"


def default_ttl_seconds(lock_name: str) -> int:
    return LOCK_TTL_SECONDS.get(lock_name, 30 * 60)


class LockHeldError(Exception):
    def __init__(self, lock_name: str, owner_id: str, expires_at: datetime):
        self.lock_name = lock_name
        self.owner_id = owner_id
        self.expires_at = expires_at
        super().__init__(
            f"Job already running: {lock_name} (held by {owner_id}, expires {expires_at.isoformat()})"
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Process-local dedupe of "lock acquire failed" log rows - see
# app.services.job_locks._last_logged_conflict_owner for the rationale.
_last_logged_conflict_owner: dict[str, str] = {}


def _log_acquire_failed(lock_name: str, requesting_owner_id: str, existing: JobLock) -> None:
    if _last_logged_conflict_owner.get(lock_name) == existing.owner_id:
        return
    _last_logged_conflict_owner[lock_name] = existing.owner_id
    record_app_log(
        "warning",
        "worker",
        "lock_acquire_failed",
        f"Lock '{lock_name}' already held by {existing.owner_id}, requested by "
        f"{requesting_owner_id}.",
        context={
            "lock_name": lock_name,
            "requesting_owner_id": requesting_owner_id,
            "held_by": existing.owner_id,
            "expires_at": existing.expires_at.isoformat(),
        },
    )


def acquire_lock(
    db: Session,
    lock_name: str,
    owner_id: str,
    ttl_seconds: int,
    *,
    metadata: dict[str, Any] | None = None,
) -> JobLock:
    now = _utcnow()
    expires_at = now + timedelta(seconds=ttl_seconds)

    result = db.execute(
        update(JobLock)
        .where(
            JobLock.lock_name == lock_name,
            (JobLock.status != "active") | (JobLock.expires_at <= now),
        )
        .values(
            owner_id=owner_id,
            acquired_at=now,
            expires_at=expires_at,
            released_at=None,
            status="active",
            metadata_json=metadata,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 1:
        db.commit()
        lock = db.scalar(select(JobLock).where(JobLock.lock_name == lock_name))
        assert lock is not None
        _last_logged_conflict_owner.pop(lock_name, None)
        record_app_log(
            "info",
            "worker",
            "lock_acquired",
            f"Lock '{lock_name}' acquired by {owner_id}.",
            context={"lock_name": lock_name, "owner_id": owner_id, "expires_at": expires_at.isoformat()},
        )
        return lock

    # rowcount == 0 isn't an error - see app.services.job_locks.acquire_lock's
    # matching comment for why no rollback happens here.
    existing = db.scalar(select(JobLock).where(JobLock.lock_name == lock_name))

    if existing is not None:
        _log_acquire_failed(lock_name, owner_id, existing)
        raise LockHeldError(lock_name, existing.owner_id, existing.expires_at)

    lock = JobLock(
        lock_name=lock_name,
        owner_id=owner_id,
        acquired_at=now,
        expires_at=expires_at,
        status="active",
        metadata_json=metadata,
    )
    db.add(lock)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(JobLock).where(JobLock.lock_name == lock_name))
        if existing is None:
            raise LockHeldError(lock_name, "unknown", now) from None
        _log_acquire_failed(lock_name, owner_id, existing)
        raise LockHeldError(lock_name, existing.owner_id, existing.expires_at) from None

    _last_logged_conflict_owner.pop(lock_name, None)
    record_app_log(
        "info",
        "worker",
        "lock_acquired",
        f"Lock '{lock_name}' acquired by {owner_id}.",
        context={"lock_name": lock_name, "owner_id": owner_id, "expires_at": expires_at.isoformat()},
    )
    return lock


def release_lock(db: Session, lock_name: str, owner_id: str) -> bool:
    now = _utcnow()
    result = db.execute(
        update(JobLock)
        .where(JobLock.lock_name == lock_name, JobLock.owner_id == owner_id, JobLock.status == "active")
        .values(status="released", released_at=now, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    released = result.rowcount == 1
    db.commit()

    if released:
        record_app_log(
            "info",
            "worker",
            "lock_released",
            f"Lock '{lock_name}' released by {owner_id}.",
            context={"lock_name": lock_name, "owner_id": owner_id},
        )
    return released


@contextmanager
def with_job_lock(
    db: Session,
    lock_name: str,
    *,
    ttl_seconds: int | None = None,
    metadata: dict[str, Any] | None = None,
    skip_lock: bool = False,
) -> Iterator[str | None]:
    """See app.services.job_locks.with_job_lock. skip_lock exists only for
    test/dev CLI use - it must never be reachable from a Celery task
    triggered by the API or from the beat schedule."""
    if skip_lock:
        yield None
        return

    owner_id = make_owner_id(lock_name)
    acquire_lock(db, lock_name, owner_id, ttl_seconds or default_ttl_seconds(lock_name), metadata=metadata)
    try:
        yield owner_id
    finally:
        release_lock(db, lock_name, owner_id)
