"""One official-image mirror run at a time.

The daily cron and a hand-run backfill must never fetch from Bandai at the
same time: two runs would double the request rate the pacer promises. The
mirror commits once per print, so a transaction-scoped lock would be released
after the first print. This is a session-scoped advisory lock held on its own
connection for the whole run instead. It needs no schema, and Postgres
releases it if the process dies. Non-blocking: a second run is told and exits.
Skipped on engines without advisory locks (sqlite in the unit tests).
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import text
from sqlalchemy.engine import Engine

LOCK_KEY = 0x0FF1C1A1  # "official"; distinct from the import and RAW locks


@contextmanager
def mirror_run_lock(engine: Engine) -> Iterator[bool]:
    """Yield True while this process holds the lock, False if another run does."""
    if engine.dialect.name != "postgresql":
        yield True
        return
    with engine.connect() as connection:
        acquired = connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}
        ).scalar_one()
        # Do not leave the probe's implicit transaction open for the whole run.
        connection.commit()
        if not acquired:
            yield False
            return
        try:
            yield True
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
            connection.commit()
