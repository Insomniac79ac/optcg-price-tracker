"""Mutual-exclusion locks for background jobs/admin actions that must never
run concurrently - price refresh, market workflow, portfolio/market-signal
snapshots, report generation, Telegram digest sends, data retention pruning,
and backup restore. See 'Worker job concurrency locking' in
docs/operations.md, GET /admin/job-locks, and app.models.job_lock.JobLock.

Design notes (read before changing acquire/release):

- Every function here opens and commits its own short-lived session (via
  app.db.SessionLocal) rather than taking the caller's db session - same
  reasoning as app.services.app_logging.record_app_log: a lock's
  acquire/release must commit immediately regardless of what the caller's
  own transaction does next. Sharing the caller's session would be actively
  harmful here, not just unnecessary - SQLAlchemy's default
  expire_on_commit=True means every commit() on a session expires *every*
  object loaded in it, not just the ones that commit touched. A caller that
  acquires a lock, does its work, gets back a freshly-committed-and-refreshed
  object (e.g. generate_market_report's MarketIntelligenceReport), and only
  reads its attributes *after* the lock releases would see release_lock's
  own commit silently expire that object out from under it - and if the
  caller has since closed its own session (a common CLI pattern: commit,
  close, then print), that expiry surfaces as a confusing
  DetachedInstanceError far from its actual cause. Keeping locks on a fully
  separate session sidesteps this class of bug entirely.

- Acquisition is non-blocking and fails clean: if a lock is already held and
  not expired, acquire_lock raises LockHeldError immediately rather than
  waiting for it to free up. Every caller in this codebase acquires at most
  one NEW lock at a time (a job either holds none yet, or already holds a
  *different*-named lock and is acquiring another distinct one, e.g.
  run_market_workflow holding market_workflow while refresh_prices acquires
  price_refresh beneath it) - since acquisition never blocks, there is no
  circular-wait condition and therefore no deadlock is possible, regardless
  of nesting order. This is what lets every job/endpoint listed in
  docs/operations.md acquire its own lock unconditionally, with no
  "skip if already inside an outer lock" special-casing anywhere.

- acquire_lock is atomic via a single UPDATE's WHERE clause (a
  compare-and-swap on the existing row's status/expires_at) with an INSERT
  fallback (relying on the unique index on lock_name) for the "no row yet"
  case. Both Postgres and SQLite execute a single UPDATE/INSERT statement
  atomically, and Postgres additionally serializes concurrent UPDATEs
  against the same row via its normal row lock - no SELECT ... FOR UPDATE or
  dialect-specific upsert is needed for this to be race-free. A
  compare-and-swap that matches zero rows is not an error and never rolls
  back - it just means "no unexpired active lock currently blocks us",
  which the code below re-checks with a plain SELECT.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.models.job_lock import JobLock
from app.services.app_logging import record_app_log

logger = logging.getLogger(__name__)

# Lock names and their TTLs - see 'Worker job concurrency locking' in
# docs/operations.md for what each one guards and why its TTL is sized the
# way it is (roughly: a generous multiple of how long that job normally
# takes, so a merely-slow run is never mistaken for a crashed one).
LOCK_TTL_SECONDS: dict[str, int] = {
    "price_refresh": 30 * 60,
    "market_workflow": 60 * 60,
    "portfolio_snapshot": 10 * 60,
    "market_signal_snapshot": 10 * 60,
    "market_report_generation": 10 * 60,
    "telegram_market_digest": 5 * 60,
    "data_retention_prune": 30 * 60,
    "backup_restore": 60 * 60,
}

LOCK_NAMES = tuple(LOCK_TTL_SECONDS.keys())


def make_owner_id(lock_name: str) -> str:
    """Builds a unique-per-run owner id, e.g. 'market_workflow:3f1e...'."""
    return f"{lock_name}:{uuid.uuid4()}"


def default_ttl_seconds(lock_name: str) -> int:
    return LOCK_TTL_SECONDS.get(lock_name, 30 * 60)


class LockHeldError(Exception):
    """Raised by acquire_lock when lock_name is already held by another
    still-live owner. Carries enough of the existing lock's state for a
    caller to build a 409 response or a CLI error message without a second
    query."""

    def __init__(self, lock_name: str, owner_id: str, expires_at: datetime):
        self.lock_name = lock_name
        self.owner_id = owner_id
        self.expires_at = expires_at
        super().__init__(
            f"Job already running: {lock_name} (held by {owner_id}, expires {expires_at.isoformat()})"
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _naive(dt: datetime) -> datetime:
    """Strips tzinfo if present. SQLite (used in tests) returns naive
    datetimes even for DateTime(timezone=True) columns, while Postgres
    (production) returns timezone-aware ones - comparing a loaded
    JobLock.expires_at against datetime.now(timezone.utc) directly would
    raise TypeError under SQLite. Normalizing both sides to naive before
    comparing works correctly under either dialect, since every datetime
    this app stores is UTC regardless of whether the driver labels it as
    such (same pattern as app.services.market_signals._naive)."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


# Process-local dedupe of "lock acquire failed" log rows: repeated failed
# attempts against the *same* still-active holder (e.g. a beat schedule
# firing every few minutes while a slow job is still running) only log once,
# so a long-running job doesn't flood app_log_events with one row per retry.
# Single-instance only, same limitation as app.core.rate_limit - a failed
# attempt against a *new* holder (the lock changed hands) always logs again.
_last_logged_conflict_owner: dict[str, str] = {}


def _log_acquire_failed(lock_name: str, requesting_owner_id: str, existing: JobLock) -> None:
    if _last_logged_conflict_owner.get(lock_name) == existing.owner_id:
        return
    _last_logged_conflict_owner[lock_name] = existing.owner_id
    record_app_log(
        "warning",
        "api",
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
    lock_name: str,
    owner_id: str,
    ttl_seconds: int,
    *,
    metadata: dict[str, Any] | None = None,
) -> JobLock:
    """Atomically acquires lock_name for owner_id. Raises LockHeldError if an
    active, unexpired lock is already held by someone else. metadata_json
    must never contain secrets - it goes straight into app_log_events/GET
    /admin/job-locks; keep it to small, non-sensitive identifiers (source,
    limit, dry_run, ...). Returns a detached JobLock snapshot (its own
    session is already closed by the time this returns) - every attribute
    is already loaded, so reading them afterward is safe; just don't expect
    lazy-loading or further ORM behavior from the returned object."""
    now = _utcnow()
    expires_at = now + timedelta(seconds=ttl_seconds)

    db = SessionLocal()
    try:
        # Compare-and-swap: only flips a row to active if it is currently
        # NOT an unexpired active lock (i.e. it's released/expired, or it's
        # active but its TTL has already lapsed). rowcount == 1 means we won
        # the race.
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
            db.expunge(lock)
            _last_logged_conflict_owner.pop(lock_name, None)
            record_app_log(
                "info",
                "api",
                "lock_acquired",
                f"Lock '{lock_name}' acquired by {owner_id}.",
                context={
                    "lock_name": lock_name, "owner_id": owner_id, "expires_at": expires_at.isoformat()
                },
            )
            return lock

        # rowcount == 0 isn't an error - it just means no row currently
        # matches the compare-and-swap predicate (either an active unexpired
        # lock is held by someone else, or no row for lock_name exists yet).
        existing = db.scalar(select(JobLock).where(JobLock.lock_name == lock_name))

        if existing is not None:
            # Someone else holds an active, unexpired lock - fail clean.
            _log_acquire_failed(lock_name, owner_id, existing)
            raise LockHeldError(lock_name, existing.owner_id, existing.expires_at)

        # No row exists yet for this lock_name - try to insert one. A
        # concurrent caller may win this race; the unique index on
        # lock_name makes that safe (IntegrityError => we lost, fail clean).
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
                # Extremely unlikely (would mean the row vanished again
                # between our failed insert and this re-read) - surface a
                # generic conflict rather than crash.
                raise LockHeldError(lock_name, "unknown", now) from None
            _log_acquire_failed(lock_name, owner_id, existing)
            raise LockHeldError(lock_name, existing.owner_id, existing.expires_at) from None

        # db.commit() just expired every attribute on `lock` (expire_on_commit,
        # same as everywhere else in this module) - refresh before expunging,
        # or the detached object would be both expired *and* sessionless,
        # unable to reload any attribute a caller reads afterward.
        db.refresh(lock)
        db.expunge(lock)
        _last_logged_conflict_owner.pop(lock_name, None)
        record_app_log(
            "info",
            "api",
            "lock_acquired",
            f"Lock '{lock_name}' acquired by {owner_id}.",
            context={"lock_name": lock_name, "owner_id": owner_id, "expires_at": expires_at.isoformat()},
        )
        return lock
    finally:
        db.close()


def release_lock(lock_name: str, owner_id: str) -> bool:
    """Releases lock_name, but only if it is currently active and held by
    owner_id - a release from a stale/mismatched owner (e.g. a job that ran
    past its own TTL and got reaped/reacquired by someone else) is a no-op,
    not an error, so a slow job's own cleanup can never steal back a lock
    someone else has legitimately since acquired."""
    now = _utcnow()
    db = SessionLocal()
    try:
        result = db.execute(
            update(JobLock)
            .where(
                JobLock.lock_name == lock_name, JobLock.owner_id == owner_id, JobLock.status == "active"
            )
            .values(status="released", released_at=now, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        released = result.rowcount == 1
        db.commit()
    finally:
        db.close()

    if released:
        record_app_log(
            "info",
            "api",
            "lock_released",
            f"Lock '{lock_name}' released by {owner_id}.",
            context={"lock_name": lock_name, "owner_id": owner_id},
        )
    return released


def force_release_lock(lock_name: str) -> JobLock | None:
    """Admin-only escape hatch (POST /admin/job-locks/{lock_name}/force-release)
    for a lock left behind by a crashed job - releases the active lock for
    lock_name regardless of owner_id. Returns the released row (detached, see
    acquire_lock's docstring), or None if lock_name has no active lock.
    Always records a warning app_log_events row (this is meant to be rare
    and worth a human noticing)."""
    now = _utcnow()
    db = SessionLocal()
    try:
        existing = db.scalar(
            select(JobLock).where(JobLock.lock_name == lock_name, JobLock.status == "active")
        )
        if existing is None:
            return None
        previous_owner_id = existing.owner_id

        db.execute(
            update(JobLock)
            .where(JobLock.id == existing.id, JobLock.status == "active")
            .values(status="released", released_at=now, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        db.commit()
        released_lock = db.scalar(select(JobLock).where(JobLock.id == existing.id))
        assert released_lock is not None
        db.expunge(released_lock)
    finally:
        db.close()

    _last_logged_conflict_owner.pop(lock_name, None)
    record_app_log(
        "warning",
        "api",
        "lock_force_released",
        f"Lock '{lock_name}' force-released (was held by {previous_owner_id}).",
        context={"lock_name": lock_name, "previous_owner_id": previous_owner_id},
    )
    return released_lock


def force_release_expired_locks() -> int:
    """Marks every active-but-expired lock as 'expired' (not 'released' -
    nobody explicitly released these, their TTL just lapsed). Safe to call
    on a schedule or from GET /admin/job-locks's cleanup action; a lock
    already released/expired is left untouched. Returns the number of rows
    updated. This is separate from acquire_lock's own per-lock_name
    compare-and-swap (which already lets a new owner take over an expired
    lock without this ever having run) - it exists so an expired-but-nobody
    has-tried-to-reacquire-it-yet lock doesn't sit around reporting itself as
    'active' in GET /admin/job-locks."""
    now = _utcnow()
    db = SessionLocal()
    try:
        stale = db.scalars(
            select(JobLock).where(JobLock.status == "active", JobLock.expires_at <= now)
        ).all()
        if not stale:
            return 0

        stale_names = [lock.lock_name for lock in stale]
        for lock in stale:
            lock.status = "expired"
            lock.updated_at = now
            _last_logged_conflict_owner.pop(lock.lock_name, None)
        db.commit()
    finally:
        db.close()

    record_app_log(
        "info",
        "api",
        "lock_expired_cleanup",
        f"{len(stale_names)} expired lock(s) marked as expired.",
        context={"lock_names": stale_names},
    )
    return len(stale_names)


def get_active_locks() -> list[JobLock]:
    """Returns detached (see acquire_lock's docstring) JobLock snapshots for
    every currently-active lock."""
    db = SessionLocal()
    try:
        locks = list(
            db.scalars(
                select(JobLock).where(JobLock.status == "active").order_by(JobLock.lock_name)
            ).all()
        )
        db.expunge_all()
        return locks
    finally:
        db.close()


@dataclass
class LockCounts:
    active: int
    expired_active: int


def get_lock_counts() -> LockCounts:
    """Active-lock counts for GET /admin/performance/summary and GET
    /admin/system-check - expired_active is the "expired but nobody has
    cleaned it up yet" count that both of those surfaces warn on."""
    now = _naive(_utcnow())
    active_locks = get_active_locks()
    expired_active = sum(1 for lock in active_locks if _naive(lock.expires_at) <= now)
    return LockCounts(active=len(active_locks), expired_active=expired_active)


@contextmanager
def with_job_lock(
    lock_name: str,
    *,
    ttl_seconds: int | None = None,
    metadata: dict[str, Any] | None = None,
    skip_lock: bool = False,
) -> Iterator[str | None]:
    """Context manager wrapping acquire_lock/release_lock around a block of
    work. Yields the owner_id used (or None if skip_lock=True). Raises
    LockHeldError up front if the lock can't be acquired - skip_lock exists
    only for test/dev CLI use (see docs/operations.md); it must never be
    reachable from an HTTP request.

        with with_job_lock("portfolio_snapshot") as owner_id:
            ... do the work ...
    """
    if skip_lock:
        yield None
        return

    owner_id = make_owner_id(lock_name)
    acquire_lock(lock_name, owner_id, ttl_seconds or default_ttl_seconds(lock_name), metadata=metadata)
    try:
        yield owner_id
    finally:
        release_lock(lock_name, owner_id)
