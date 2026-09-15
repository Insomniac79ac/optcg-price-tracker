"""Upgrade/downgrade/re-upgrade the attempt snapshot link on throwaway Postgres."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError


API_ROOT = Path(__file__).resolve().parents[1]
HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
ADMIN_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/postgres"
PREVIOUS_REVISION = "a8b2c4d6e901"
THIS_REVISION = "e3a7c5d9b102"
DATABASE_NAME = "atlas_attempt_raw_link_test"


def _alembic(url: str, *args: str):
    env = dict(os.environ, DATABASE_URL=url)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture()
def database():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{DATABASE_NAME}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{DATABASE_NAME}"'))
    except OperationalError:
        admin.dispose()
        pytest.skip(f"No PostgreSQL server reachable at {HOST}:{PORT}")

    url = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/{DATABASE_NAME}"
    engine = create_engine(url)
    try:
        yield url, engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{DATABASE_NAME}" WITH (FORCE)'))
        admin.dispose()


def test_upgrade_downgrade_reupgrade_preserves_rows_fk_and_index(database):
    url, engine = database
    _alembic(url, "upgrade", PREVIOUS_REVISION)

    with engine.begin() as conn:
        source_id = conn.execute(
            text(
                "INSERT INTO sources (name, base_url)"
                " VALUES ('yuyutei', 'https://yuyu-tei.jp') RETURNING id"
            )
        ).scalar_one()
        snapshot_id = conn.execute(
            text(
                "INSERT INTO raw_snapshots"
                " (source_id, source_url, http_status, content_hash, raw_content, parser_version)"
                " VALUES (:source_id, 'https://yuyu-tei.jp/x', 200, :hash, '<html>x</html>', 'test')"
                " RETURNING id"
            ),
            {"source_id": source_id, "hash": "0" * 64},
        ).scalar_one()
        attempt_id = conn.execute(
            text(
                "INSERT INTO source_collection_attempts"
                " (batch_run_id, source_id, source_card_mapping_id, selection_ordinal)"
                " VALUES ('legacy-run', :source_id, 12345, 1) RETURNING id"
            ),
            {"source_id": source_id},
        ).scalar_one()

    _alembic(url, "upgrade", THIS_REVISION)

    with engine.begin() as conn:
        assert conn.execute(
            text(
                "SELECT raw_snapshot_id FROM source_collection_attempts WHERE id = :id"
            ),
            {"id": attempt_id},
        ).scalar_one() is None
        index_names = set(
            conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes"
                    " WHERE schemaname = current_schema()"
                    " AND tablename = 'source_collection_attempts'"
                )
            ).scalars()
        )
        assert "ix_source_collection_attempts_raw_snapshot_id" in index_names
        fk = conn.execute(
            text(
                "SELECT delete_rule FROM information_schema.referential_constraints"
                " WHERE constraint_schema = current_schema()"
                " AND constraint_name = 'fk_source_collection_attempts_raw_snapshot_id'"
            )
        ).scalar_one()
        assert fk == "SET NULL"
        conn.execute(
            text(
                "UPDATE source_collection_attempts SET raw_snapshot_id = :snapshot_id"
                " WHERE id = :attempt_id"
            ),
            {"snapshot_id": snapshot_id, "attempt_id": attempt_id},
        )

    with pytest.raises(DBAPIError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE source_collection_attempts SET raw_snapshot_id = 999999999"
                    " WHERE id = :attempt_id"
                ),
                {"attempt_id": attempt_id},
            )

    _alembic(url, "downgrade", PREVIOUS_REVISION)
    with engine.connect() as conn:
        columns = set(
            conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns"
                    " WHERE table_schema = current_schema()"
                    " AND table_name = 'source_collection_attempts'"
                )
            ).scalars()
        )
        assert "raw_snapshot_id" not in columns
        assert conn.execute(
            text("SELECT status FROM source_collection_attempts WHERE id = :id"),
            {"id": attempt_id},
        ).scalar_one() == "selected"

    _alembic(url, "upgrade", THIS_REVISION)
    with engine.connect() as conn:
        assert conn.execute(
            text(
                "SELECT raw_snapshot_id FROM source_collection_attempts WHERE id = :id"
            ),
            {"id": attempt_id},
        ).scalar_one() is None
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            THIS_REVISION
        )
