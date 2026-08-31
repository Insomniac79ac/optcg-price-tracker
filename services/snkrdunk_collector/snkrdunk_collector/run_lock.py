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
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import text

# Fixed, arbitrary, and never reused: the key two concurrent write-capable
# SNKRDUNK collection runs contend on. Advisory-lock keys share one namespace
# per database, so this must not collide with canonical_import_apply's
# IMPORT_LOCK_KEY (0x0A71A510).
COLLECTION_LOCK_KEY = 0x0A71A5_20  # "atlas" + snkrdunk collection

SKIPPED_LOCKED = "another_run_holds_the_collection_lock"


@dataclass
class LockState:
    """Whether this run may proceed, and why not when it may not."""

    acquired: bool
    reason: str | None = None
    # True when the backend cannot provide advisory locks (sqlite in the
    # offline tests). Recorded so a caller can tell "no contention possible"
    # apart from "we really took the lock".
    unsupported: bool = False


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
        try:
            yield LockState(acquired=True)
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
