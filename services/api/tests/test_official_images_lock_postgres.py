"""The official image mirror run lock against a real PostgreSQL server.

Skipped when no server is reachable (same TEST_POSTGRES_* settings as the
other *_postgres tests). The lock uses no schema, so the maintenance database
is enough.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app import mirror_official_images as cli
from app.official_images.lock import LOCK_KEY, mirror_run_lock

HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/postgres"


@pytest.fixture
def engine():
    engine = create_engine(URL, future=True)
    try:
        with engine.connect():
            pass
    except OperationalError:
        engine.dispose()
        pytest.skip(f"No PostgreSQL server reachable at {HOST}:{PORT}")
    yield engine
    engine.dispose()


def _held(engine) -> int:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = :key"),
            {"key": LOCK_KEY},
        ).scalar_one()


def test_second_run_is_refused_while_the_first_holds_the_lock(engine):
    with mirror_run_lock(engine) as first:
        assert first is True
        assert _held(engine) == 1
        with mirror_run_lock(engine) as second:
            assert second is False
    assert _held(engine) == 0
    with mirror_run_lock(engine) as again:
        assert again is True


def test_lock_is_released_when_the_run_raises(engine):
    with pytest.raises(RuntimeError):
        with mirror_run_lock(engine) as acquired:
            assert acquired is True
            raise RuntimeError("run failed")
    assert _held(engine) == 0


def test_cli_exits_3_and_fetches_nothing_while_locked(engine, monkeypatch):
    monkeypatch.setattr(cli, "engine", engine)
    monkeypatch.setattr(cli, "_write", lambda args: pytest.fail("must not run while locked"))
    with mirror_run_lock(engine) as held:
        assert held is True
        assert cli.main(["--write", "--quiet"]) == 3
