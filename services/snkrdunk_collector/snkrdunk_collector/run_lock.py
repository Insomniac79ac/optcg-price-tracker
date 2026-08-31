"""One write-capable SNKRDUNK collection run at a time, per database.

WHY A LOCK AT ALL. Collection is about to run more than once a day (the fair
scheduler drains a bounded slice per run), and two overlapping write-capable
runs would both select the stalest mappings, both fetch them, and both append
observations - doubling load on the source and writing duplicate history for
the same instant. The fair ordering also degrades: two runs stamping the same
slice makes the second run's work invisible in the queue.

WHY A POSTGRES ADVISORY LOCK, AND NOT A TABLE. A lock row needs a schema, a
release path, and - because a crashed run cannot clean up after itself - a
staleness/TTL rule, which is exactly the kind of thing that is wrong at 3am
when a run took 40 minutes instead of 25. Postgres ties a session-scoped
advisory lock to the CONNECTION: when the owning connection goes away, for any
reason at all, the lock is gone with it. No TTL, no reaper, no migration.
`canonical_import_apply` already uses this mechanism for the same purpose.

WHY A DEDICATED CONNECTION, AND NOT THE WORK SESSION. That module can use
`pg_try_advisory_xact_lock` because its apply is one transaction. This batch
is not: it commits per mapping (see batch._record_attempt), so a
transaction-scoped lock would be released at the first commit and the rest of
the run would be unprotected. The session-scoped variant survives commits -
but the work Session returns its connection to the pool and may later be
handed a DIFFERENT one, which would strand the lock on an idle pooled
connection while the run kept going. Measured 2026-08-31: it happened to keep
the same backend pid only because the pool was idle, which is luck and not a
guarantee.

So the lock lives on its own connection, checked out for exactly the lifetime
of the run and used for nothing else. That makes the ownership question
trivial: the run holds the lock for as long as it holds that connection, and
the connection dying - normal exit, exception, kill -9, network loss - is what
releases it.

NON-BLOCKING ON PURPOSE. A second run is told that another run owns the lock
and exits cleanly, rather than queueing behind it. A queued collector would
still be waiting when the next cron fires, and the pile-up is the failure this
prevents.

Validate-only runs are deliberately NOT locked: they persist nothing (no
stamps, no snapshots, no observations), so two of them cannot corrupt each
other, and an operator must always be able to inspect what the scheduler would
do while a real run is in progress.

WHY HOLDING THE LOCK IS NOT ENOUGH ON ITS OWN. Everything above assumes that
"the connection that took the lock" stays the same physical backend for the
whole run. It does not, and the way it fails is silent. Measured against
PostgreSQL 18.6 on 2026-08-31:

    original backend pid: 87
    <connection dropped>
    session.rollback()          # the defensive path in batch._record_attempt
    backend pid now:      88    # SQLAlchemy transparently reconnected
    advisory lock held:   0     # the new backend owns nothing
    -> the run kept writing, and a competing run could take the lock

A checked-out Connection that loses its server refuses further use with
PendingRollbackError, but a rollback() clears that state and the NEXT use
procures a brand-new DBAPI connection. `_record_attempt` rolls back on any
exception by design (stamping must never fail a mapping that collected
correctly), so the collector contained the exact gesture that turns a dead
lock connection into a live unlocked one.

So this module does two things, not one:

1. PINS the work Session to the lock-owning connection (`pinned_session`), so
   the advisory lock and every stamp, snapshot and observation share one
   physical backend. `pg_advisory_lock` is session-scoped, not
   transaction-scoped, so commit-per-mapping does not release it - verified,
   the lock survives each commit and a competing run is still refused.

2. VERIFIES ownership fail-closed immediately before every mutation
   (`assert_lock_owned`), because of the reconnect above. The check is not
   `SELECT 1`: it asks the backend for its own pid AND whether that pid still
   holds this advisory lock, and compares the pid to the one recorded at
   acquisition. A connection that reconnected successfully but owns no lock
   fails both halves and is reported as LockLost.

Because the Session is pinned, the check runs on the very connection that is
about to write, so "the backend we verified" and "the backend that writes" are
the same one by construction - not an inference across two connections. It
also means the check needs nothing but the Session, which is why writer.py can
guard its inserts without having a lock object threaded into it.

LockLost aborts the run. It is never caught-and-continued and the lock is
never silently reacquired mid-run: a run that has lost ownership has no claim
on the next mapping either. A later, separate invocation acquires normally.

There is deliberately NO heartbeat. Every mutation boundary is already
verified, and a periodic ping would only widen the window it appears to close:
between two heartbeats the answer is stale, and the mutation is what actually
needs the guarantee.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

# Fixed, arbitrary, and never reused: the key two concurrent write-capable
# SNKRDUNK collection runs contend on. Advisory-lock keys share one namespace
# per database, so this must not collide with canonical_import_apply's
# IMPORT_LOCK_KEY (0x0A71A510).
COLLECTION_LOCK_KEY = 0x0A71A5_20  # "atlas" + snkrdunk collection

SKIPPED_LOCKED = "another_run_holds_the_collection_lock"
LOCK_LOST = "collection_lock_lost"

# pg_locks splits a bigint advisory key into two int4 columns.
_LOCK_CLASSID = (COLLECTION_LOCK_KEY >> 32) & 0xFFFFFFFF
_LOCK_OBJID = COLLECTION_LOCK_KEY & 0xFFFFFFFF

# Key under which a pinned Session records the backend pid that owned the lock
# when it was handed out. Deliberately on Session.info (plain Python state
# owned by the Session) and NOT on Connection.info: a reconnect procures a new
# DBAPI connection with a FRESH info dict, so a connection-scoped marker would
# vanish exactly when it is needed and the check would silently no-op.
LOCK_PID_INFO_KEY = "snkrdunk_collection_lock_pid"

# Asks the backend who it is and whether it still owns this lock, in one round
# trip. Both halves matter: a reconnected backend answers with a different pid
# AND owns nothing, and either alone is enough to fail closed.
_OWNERSHIP_SQL = text(
    """
    SELECT pg_backend_pid() AS pid,
           EXISTS (
               SELECT 1 FROM pg_locks
                WHERE locktype = 'advisory'
                  AND classid = :classid
                  AND objid = :objid
                  AND pid = pg_backend_pid()
                  AND granted
           ) AS owns
    """
)


class LockLost(RuntimeError):
    """Ownership of the collection lock could not be re-established at a
    mutation boundary.

    Raised instead of writing. Never caught-and-continued: the run stops, the
    mapping in hand is not stamped or written, and no attempt is made to
    reacquire - another run may already be working under this lock.
    """


@dataclass
class LockState:
    """Whether this run may proceed, and why not when it may not."""

    acquired: bool
    reason: str | None = None
    # True when the backend cannot provide advisory locks (sqlite in the
    # offline tests). Recorded so a caller can tell "no contention possible"
    # apart from "we really took the lock".
    unsupported: bool = False
    # The lock-owning connection and the backend pid that took the lock. Both
    # None on the unsupported/validate-only paths, where there is no lock to
    # pin to and nothing to verify.
    connection: object | None = None
    backend_pid: int | None = None


def pinned_session(lock: LockState, session_factory) -> Session:
    """The Session a real run must do all of its work through.

    When a lock is genuinely held, the Session is bound to the lock-OWNING
    connection, so stamps, snapshots and observations execute on the same
    backend that holds the advisory lock. `join_transaction_mode` is
    "control_fully" because the lock connection has no open transaction (the
    acquisition committed, which a session-scoped advisory lock survives), so
    the Session may drive commit/rollback normally and commit-per-mapping is
    preserved exactly.

    On the unsupported (sqlite) and validate-only paths there is no lock
    connection, so the caller's own factory is used unchanged and the Session
    carries no pid marker - which is what makes `assert_lock_owned` a no-op
    for them.
    """
    if lock.connection is None:
        return session_factory()
    session = Session(
        bind=lock.connection,
        autoflush=False,
        join_transaction_mode="control_fully",
    )
    session.info[LOCK_PID_INFO_KEY] = lock.backend_pid
    return session


def assert_lock_owned(session) -> None:
    """Fail closed unless this Session's backend still owns the lock.

    Called immediately before every mutation boundary. A Session with no pid
    marker is not a locked run (validate-only, or a backend without advisory
    locks) and passes untouched, so those paths behave exactly as before.

    Any failure to get a clean answer is itself a lock loss: if the connection
    is dead or its transaction is poisoned we cannot claim ownership, and the
    safe reading of "I don't know" is "I don't have it".
    """
    expected_pid = session.info.get(LOCK_PID_INFO_KEY)
    if expected_pid is None:
        return
    try:
        pid, owns = session.execute(
            _OWNERSHIP_SQL, {"classid": _LOCK_CLASSID, "objid": _LOCK_OBJID}
        ).one()
    except Exception as exc:
        raise LockLost(
            f"{LOCK_LOST}: the lock connection could not be interrogated "
            f"({type(exc).__name__}: {exc})"
        ) from exc
    if pid != expected_pid:
        raise LockLost(
            f"{LOCK_LOST}: backend changed under this run "
            f"(acquired on pid {expected_pid}, now pid {pid}) - the connection "
            f"was replaced and the new one holds no lock"
        )
    if not owns:
        raise LockLost(
            f"{LOCK_LOST}: backend pid {pid} no longer holds the advisory lock"
        )


@contextmanager
def collection_lock(engine, *, enabled: bool = True):
    """Hold the single-run lock for the duration of the block.

    `enabled=False` (a validate-only run) yields an acquired state without
    taking anything, so the caller needs no second code path.

    On a backend without advisory locks the lock is skipped and reported as
    unsupported rather than refused: the offline test suite runs on sqlite,
    where two concurrent collectors are not a real condition, and failing
    closed there would only make the tests lie about production.
    """
    if not enabled:
        yield LockState(acquired=True)
        return

    dialect = getattr(getattr(engine, "dialect", None), "name", None)
    if dialect != "postgresql":
        yield LockState(acquired=True, unsupported=True)
        return

    connection = engine.connect()
    try:
        acquired = connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": COLLECTION_LOCK_KEY}
        ).scalar_one()
        if not acquired:
            yield LockState(acquired=False, reason=SKIPPED_LOCKED)
            return
        backend_pid = connection.execute(text("SELECT pg_backend_pid()")).scalar_one()
        # End the acquisition transaction so the pinned Session starts from a
        # clean connection and can drive commit/rollback itself. A
        # session-scoped advisory lock is NOT released by COMMIT, so the lock
        # outlives this - that is the whole reason the session-scoped variant
        # is used here rather than the xact-scoped one.
        connection.commit()
        try:
            yield LockState(
                acquired=True, connection=connection, backend_pid=backend_pid
            )
        finally:
            # Best-effort explicit release. If this cannot run - the process
            # died, the connection dropped - Postgres releases the lock when
            # the connection ends, which is the property this design is built
            # on. The explicit unlock only returns the connection to the pool
            # in a clean state sooner.
            try:
                connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": COLLECTION_LOCK_KEY}
                )
                connection.commit()
            except Exception:
                pass
    finally:
        connection.close()
