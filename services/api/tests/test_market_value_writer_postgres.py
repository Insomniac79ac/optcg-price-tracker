"""Market Value writer transaction and lock proofs on disposable PostgreSQL."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app import market_value_writer as writer
from app.models.market_value_point import MarketValuePoint
from app.services import app_logging, job_locks
from app.services.job_locks import LockHeldError, acquire_lock, release_lock
from tests.test_market_value_persistence import replay_fixture


API_ROOT = Path(__file__).resolve().parents[1]
HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
PREFIX = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/"
ADMIN_URL = PREFIX + "postgres"
RELEASE_ID = 700001


def _alembic(url: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_ROOT,
        env=dict(os.environ, DATABASE_URL=url),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="module")
def pg_engine():
    name = "atlas_market_value_writer_" + uuid.uuid4().hex[:10]
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError:
        admin.dispose()
        pytest.skip(f"Disposable PostgreSQL unavailable at {HOST}:{PORT}")

    engine = create_engine(PREFIX + name)
    try:
        _alembic(PREFIX + name)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO release_products (
                        id, source_catalogue, official_code, display_name,
                        first_seen_name, source_series_id, source_url,
                        verification_status
                    ) VALUES (
                        :id, 'bandai_jp', 'OP-TEST', 'Test release',
                        'Test release', 'test-release',
                        'https://example.test/release', 'verified'
                    )
                    """
                ),
                {"id": RELEASE_ID},
            )
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def pg_session(pg_engine, monkeypatch):
    with pg_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE market_value_points, job_locks, app_log_events "
                "RESTART IDENTITY"
            )
        )
    factory = sessionmaker(bind=pg_engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(job_locks, "SessionLocal", factory)
    monkeypatch.setattr(app_logging, "SessionLocal", factory)
    monkeypatch.setattr(
        writer,
        "load_market_value_replay_input",
        lambda _db, *, through=None, include_current=True: replay_fixture(
            release_product_id=RELEASE_ID
        ),
    )
    with Session(pg_engine) as session:
        yield session
        session.rollback()


def _count(engine) -> int:
    with Session(engine) as fresh:
        return fresh.scalar(select(func.count()).select_from(MarketValuePoint))


@pytest.mark.parametrize("mode", ["dry-run", "verify"])
def test_read_modes_are_server_enforced_repeatable_read_only(
    pg_session, monkeypatch, mode
):
    real_loader = writer.load_market_value_replay_input

    def asserting_loader(db, **kwargs):
        assert db.scalar(text("SHOW transaction_read_only")) == "on"
        assert db.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        return real_loader(db, **kwargs)

    monkeypatch.setattr(writer, "load_market_value_replay_input", asserting_loader)
    result = writer.run_writer(pg_session, mode=mode)
    assert result.mode == mode


def test_initial_seed_and_rerun_commit_only_after_exact_verification(
    pg_session, pg_engine, monkeypatch
):
    real_verify = writer.verify_market_value_points
    saw_uncommitted_rows = []

    def observing_verify(db, drafts, **kwargs):
        result = real_verify(db, drafts, **kwargs)
        if db.scalar(select(func.count()).select_from(MarketValuePoint)) == 6:
            saw_uncommitted_rows.append(result.ok)
        return result

    monkeypatch.setattr(writer, "verify_market_value_points", observing_verify)
    first = writer.run_writer(pg_session, mode="write", skip_lock=True)
    assert (first.inserted, first.existing, first.verification.verified) == (6, 0, 6)
    assert saw_uncommitted_rows[-1] is True
    assert _count(pg_engine) == 6

    second = writer.run_writer(pg_session, mode="write", skip_lock=True)
    assert (second.inserted, second.existing, second.verification.verified) == (0, 6, 6)
    assert _count(pg_engine) == 6


def test_conflict_rolls_back_rows_inserted_earlier_in_same_transaction(
    pg_session, pg_engine, monkeypatch
):
    drafts = writer.build_market_value_point_drafts(
        replay_fixture(release_product_id=RELEASE_ID)
    )
    conflict = drafts[3]
    values = conflict.values()
    values["tracked_value_jpy"] += 1
    pg_session.add(MarketValuePoint(**values))
    pg_session.commit()

    # Model a conflict appearing after planning but before the append loop.
    # Persistence encounters it after earlier sorted Overall rows and its
    # savepoint plus the writer's outer rollback must remove all of them.
    monkeypatch.setattr(writer, "_require_coherent_extension", lambda _plan: None)
    with pytest.raises(Exception, match="market value point conflict"):
        writer.run_writer(pg_session, mode="write", skip_lock=True)

    with Session(pg_engine) as fresh:
        rows = tuple(fresh.scalars(select(MarketValuePoint)))
    assert len(rows) == 1
    assert rows[0].scope_kind == "release"
    assert rows[0].tracked_value_jpy == values["tracked_value_jpy"]


def test_failed_post_write_verification_rolls_back_initial_seed(
    pg_session, pg_engine, monkeypatch
):
    real_verify = writer.verify_market_value_points
    calls = 0

    def fail_commit_gate(db, drafts, **kwargs):
        nonlocal calls
        calls += 1
        result = real_verify(db, drafts, **kwargs)
        if calls == 2:
            return replace(result, missing_keys=(drafts[0].natural_key,))
        return result

    monkeypatch.setattr(writer, "verify_market_value_points", fail_commit_gate)
    with pytest.raises(writer.WriterAbort, match="post-write verification failed"):
        writer.run_writer(pg_session, mode="write", skip_lock=True)
    assert _count(pg_engine) == 0


def test_held_market_value_lock_refuses_write_without_touching_points(
    pg_session, pg_engine
):
    owner = "market-value-writer-test-holder"
    acquire_lock(writer.LOCK_NAME, owner, 300)
    try:
        with pytest.raises(LockHeldError) as exc_info:
            writer.run_writer(pg_session, mode="write")
        assert exc_info.value.lock_name == writer.LOCK_NAME
        assert _count(pg_engine) == 0
    finally:
        release_lock(writer.LOCK_NAME, owner)


def test_read_modes_do_not_touch_job_lock_table(pg_session, pg_engine):
    for mode in ("dry-run", "verify"):
        writer.run_writer(pg_session, mode=mode)
    with Session(pg_engine) as fresh:
        assert fresh.scalar(text("SELECT count(*) FROM job_locks")) == 0
