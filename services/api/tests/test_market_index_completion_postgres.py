"""Real PostgreSQL proofs for the additive migration and atomic receipt boundary."""

import os
import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app import snapshot_market_index as writer
from app.models import MarketIndexSnapshotCompletion
from app.services import app_logging, job_locks
from app.services.market_index_completion import (
    SnapshotCompletionError,
    verify_market_index_snapshot_completion,
)
from tests.test_snapshot_market_index import catalogue  # noqa: F401

PARENT = "d5f7a9c2e4b6"
REVISION = "e6a8b0c3d5f7"
HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
PREFIX = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/"


def alembic(url, action, revision):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", action, revision],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, DATABASE_URL=url),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="module")
def pg_engine():
    name = "atlas_snapshot_receipt_" + uuid.uuid4().hex[:10]
    admin = create_engine(PREFIX + "postgres", isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError:
        admin.dispose()
        pytest.skip(f"Disposable PostgreSQL unavailable at {HOST}:{PORT}")
    engine = create_engine(PREFIX + name)
    try:
        alembic(PREFIX + name, "upgrade", "head")
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def db_session(pg_engine, monkeypatch):
    tables = [
        name
        for name in inspect(pg_engine).get_table_names()
        if name != "alembic_version"
    ]
    with pg_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE "
                + ",".join('"' + name + '"' for name in tables)
                + " RESTART IDENTITY CASCADE"
            )
        )
    factory = sessionmaker(bind=pg_engine, autoflush=False)
    monkeypatch.setattr(job_locks, "SessionLocal", factory)
    monkeypatch.setattr(app_logging, "SessionLocal", factory)
    with factory() as session:
        yield session
        session.rollback()


def counts(engine):
    with engine.connect() as connection:
        return tuple(
            connection.execute(
                text(
                    "SELECT (SELECT count(*) FROM market_index_snapshots), "
                    "(SELECT count(*) FROM market_index_snapshot_completions)"
                )
            ).one()
        )


def schema_signature(engine):
    with engine.connect() as connection:
        columns = list(connection.execute(text("""
            SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,
                   pg_get_expr(d.adbin,d.adrelid)
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_attribute a ON a.attrelid=c.oid
            LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
            WHERE n.nspname='public' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
              AND c.relname <> 'market_index_snapshot_completions'
            ORDER BY c.relname,a.attnum
        """)))
        constraints = list(connection.execute(text("""
            SELECT c.relname,k.conname,pg_get_constraintdef(k.oid)
            FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relname <> 'market_index_snapshot_completions'
            ORDER BY c.relname,k.conname
        """)))
        indexes = list(connection.execute(text("""
            SELECT tablename,indexname,indexdef FROM pg_indexes
            WHERE schemaname='public' AND tablename <> 'market_index_snapshot_completions'
            ORDER BY tablename,indexname
        """)))
        return columns, constraints, indexes


def test_additive_upgrade_downgrade_upgrade_preserves_existing_schema_and_data(
    pg_engine, db_session, catalogue
):
    db_session.close()
    url = pg_engine.url.render_as_string(hide_password=False)
    alembic(url, "downgrade", PARENT)
    before = schema_signature(pg_engine)
    with pg_engine.connect() as connection:
        tables = inspect(connection).get_table_names()
        count_before = {
            t: connection.scalar(text(f'SELECT count(*) FROM "{t}"')) for t in tables
        }
    for action, revision, exists in [
        ("upgrade", REVISION, True),
        ("downgrade", PARENT, False),
        ("upgrade", REVISION, True),
    ]:
        alembic(url, action, revision)
        inspector = inspect(pg_engine)
        assert inspector.has_table("market_index_snapshot_completions") == exists
        assert schema_signature(pg_engine) == before
        with pg_engine.connect() as connection:
            for table, count in count_before.items():
                assert (
                    connection.scalar(text(f'SELECT count(*) FROM "{table}"')) == count
                )
    columns = {
        c["name"]: c for c in inspector.get_columns("market_index_snapshot_completions")
    }
    assert set(columns) == set(MarketIndexSnapshotCompletion.__table__.columns.keys())
    assert (
        columns["calculated_at"]["type"].timezone
        and columns["completed_at"]["type"].timezone
    )
    assert columns["snapshot_content_digest"]["type"].length == 64
    assert all(not column["nullable"] for column in columns.values())
    assert inspector.get_unique_constraints("market_index_snapshot_completions")[0][
        "column_names"
    ] == ["snapshot_date"]
    assert {
        c["name"]
        for c in inspector.get_check_constraints("market_index_snapshot_completions")
    } == {
        c.name
        for c in MarketIndexSnapshotCompletion.__table__.constraints
        if c.__class__.__name__ == "CheckConstraint"
    }
    assert counts(pg_engine) == (0, 0)


def test_atomic_visibility_single_commit_and_real_same_day_retry(
    pg_engine, db_session, catalogue, monkeypatch
):
    commits = []
    event.listen(db_session, "after_commit", lambda _: commits.append(True))
    actual_verify = writer.verify_pending_snapshot_completion
    saw_pending = []

    def verify(db, day):
        evidence = actual_verify(db, day)
        if evidence.receipt_exists:
            assert evidence.valid
            assert counts(pg_engine) == (0, 0)  # another connection sees neither
            saw_pending.append(evidence.observed_rows)
        return evidence

    with monkeypatch.context() as patch:
        patch.setattr(writer, "verify_pending_snapshot_completion", verify)
        first = writer.snapshot_market_index(db_session)  # real job lock/sessions
    assert commits == [True] and saw_pending == [4]
    assert first.completion_receipt_created and counts(pg_engine) == (4, 1)
    with Session(pg_engine) as fresh:
        fresh.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        assert verify_market_index_snapshot_completion(fresh, first.snapshot_date).valid
        assert fresh.scalar(text("SHOW transaction_read_only")) == "on"
    second = writer.snapshot_market_index(db_session)
    assert second.completion_status == "verified_existing" and second.rows_created == 0
    assert commits == [True] and counts(pg_engine) == (4, 1)


@pytest.mark.parametrize(
    "stage",
    [
        "calculation",
        "snapshot_insert",
        "after_snapshot_insert",
        "receipt_insert",
        "receipt_constraint",
        "receipt_verify",
    ],
)
def test_any_precommit_failure_rolls_back_both_objects(
    pg_engine, db_session, catalogue, monkeypatch, stage
):
    def fail(*args, **kwargs):
        raise RuntimeError("injected failure")

    if stage == "calculation":
        monkeypatch.setattr(writer, "get_market_index_for_prints", fail)
    elif stage == "snapshot_insert":
        monkeypatch.setattr(writer, "_insert_ignoring_existing", fail)
    elif stage == "after_snapshot_insert":
        original = writer._insert_ignoring_existing

        def inserted(db, rows):
            original(db, rows)
            assert db.scalar(text("SELECT count(*) FROM market_index_snapshots")) == 4
            fail()

        monkeypatch.setattr(writer, "_insert_ignoring_existing", inserted)
    elif stage in ("receipt_insert", "receipt_constraint"):
        original = writer.insert_atomic_completion

        def inserted(db, **kwargs):
            if stage == "receipt_constraint":
                kwargs["run_id"] = ""  # real PostgreSQL CHECK violation
            original(db, **kwargs)
            assert (
                db.scalar(
                    text("SELECT count(*) FROM market_index_snapshot_completions")
                )
                == 1
            )
            fail()

        monkeypatch.setattr(writer, "insert_atomic_completion", inserted)
    else:
        original = writer.verify_pending_snapshot_completion

        def verification(db, day):
            evidence = original(db, day)
            return (
                replace(evidence, failure_reasons=("digest_mismatch",))
                if evidence.receipt_exists
                else evidence
            )

        monkeypatch.setattr(writer, "verify_pending_snapshot_completion", verification)
    with pytest.raises((RuntimeError, SnapshotCompletionError, IntegrityError)):
        writer.snapshot_market_index(db_session)
    assert counts(pg_engine) == (0, 0)
    assert not db_session.in_transaction()


@pytest.mark.parametrize(
    "assignment,reason",
    [
        ("expected_print_count=5,snapshot_row_count=5", "row_count_mismatch"),
        ("snapshot_content_digest='" + "0" * 64 + "'", "digest_mismatch"),
        ("calculated_at=calculated_at-interval '1 second'", "calculated_at_mismatch"),
    ],
)
def test_durable_contradictions_fail_verification_and_retry(
    pg_engine, db_session, catalogue, assignment, reason
):
    result = writer.snapshot_market_index(db_session)
    with pg_engine.begin() as connection:
        connection.execute(
            text("UPDATE market_index_snapshot_completions SET " + assignment)
        )
    with Session(pg_engine) as fresh:
        evidence = verify_market_index_snapshot_completion(fresh, result.snapshot_date)
        assert not evidence.valid and reason in evidence.failure_reasons
    with pytest.raises(SnapshotCompletionError):
        writer.snapshot_market_index(db_session)
    assert counts(pg_engine) == (4, 1)


def test_legacy_day_remains_receiptless(pg_engine, db_session, catalogue):
    rows = [
        writer.build_snapshot_row(value)
        for value in writer.get_market_index_for_prints(
            db_session, writer.select_snapshottable_print_ids(db_session)
        ).values()
    ]
    writer._insert_ignoring_existing(db_session, rows)
    db_session.commit()
    with Session(pg_engine) as fresh:
        assert verify_market_index_snapshot_completion(
            fresh, rows[0]["snapshot_date"]
        ).failure_reasons == ("receipt_missing",)
    with pytest.raises(SnapshotCompletionError, match="receipt_missing"):
        writer.snapshot_market_index(db_session)
    assert counts(pg_engine) == (4, 0)


@pytest.mark.parametrize(
    "assignment",
    [
        "expected_print_count=0,snapshot_row_count=0",
        "snapshot_row_count=3",
        "index_version=0",
        "digest_version=2",
        "run_id=' '",
        "receipt_kind='legacy'",
        "snapshot_content_digest='short'",
        "completed_at=calculated_at-interval '1 second'",
    ],
)
def test_database_constraints_reject_invalid_receipt(
    pg_engine, db_session, catalogue, assignment
):
    writer.snapshot_market_index(db_session)
    with pytest.raises(IntegrityError), pg_engine.begin() as connection:
        connection.execute(
            text("UPDATE market_index_snapshot_completions SET " + assignment)
        )
    assert counts(pg_engine) == (4, 1)


def test_natural_identity_and_active_producer_gate(pg_engine, db_session, catalogue):
    result = writer.snapshot_market_index(db_session)
    receipt = db_session.scalar(select(MarketIndexSnapshotCompletion))
    duplicate = {
        c.name: getattr(receipt, c.name)
        for c in receipt.__table__.columns
        if c.name != "id"
    }
    db_session.rollback()
    with pytest.raises(IntegrityError), pg_engine.begin() as connection:
        connection.execute(
            MarketIndexSnapshotCompletion.__table__.insert().values(**duplicate)
        )
    owner = "receipt-test-active-producer"
    job_locks.acquire_lock(writer.LOCK_NAME, owner, 300)
    try:
        with Session(pg_engine) as fresh:
            evidence = verify_market_index_snapshot_completion(
                fresh, result.snapshot_date
            )
            assert evidence.failure_reasons == ("snapshot_in_progress",)
    finally:
        job_locks.release_lock(writer.LOCK_NAME, owner)


def test_duplicate_receipt_is_rejected_even_if_constraint_is_bypassed_in_test(
    pg_engine, db_session, catalogue
):
    result = writer.snapshot_market_index(db_session)
    receipt = db_session.scalar(select(MarketIndexSnapshotCompletion))
    values = {
        c.name: getattr(receipt, c.name)
        for c in receipt.__table__.columns
        if c.name != "id"
    }
    # Test-only transactional DDL; rollback restores the real unique constraint.
    db_session.execute(
        text(
            "ALTER TABLE market_index_snapshot_completions DROP CONSTRAINT uq_market_index_completion_date"
        )
    )
    db_session.execute(
        MarketIndexSnapshotCompletion.__table__.insert().values(**values)
    )
    evidence = verify_market_index_snapshot_completion(db_session, result.snapshot_date)
    assert evidence.failure_reasons == ("duplicate_receipt",)
    assert evidence.observed_rows == 4
    db_session.rollback()
    assert counts(pg_engine) == (4, 1)
    assert inspect(pg_engine).get_unique_constraints(
        "market_index_snapshot_completions"
    )[0]["column_names"] == ["snapshot_date"]


def test_postgres_backup_roundtrip_retains_verifiable_receipt(
    pg_engine, db_session, catalogue
):
    from app.services.backup import export_backup, restore_backup

    result = writer.snapshot_market_index(db_session)
    archive = export_backup(db_session, include_prices=True)
    restored = restore_backup(
        db_session,
        archive,
        mode="replace",
        dry_run=False,
        confirm="RESTORE",
        skip_lock=True,
    )
    assert restored.valid, restored.errors
    with Session(pg_engine) as fresh:
        assert verify_market_index_snapshot_completion(
            fresh, result.snapshot_date
        ).valid
        after = export_backup(fresh, include_prices=True)
        assert (
            after["tables"]["market_index_snapshot_completions"]
            == archive["tables"]["market_index_snapshot_completions"]
        )
