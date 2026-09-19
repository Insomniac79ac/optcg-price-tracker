"""Real PostgreSQL upgrade/downgrade coverage for revision f4c8a2d91b60."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError


ROOT = Path(__file__).resolve().parents[1]
HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
DATABASE = "opcg_test_source_mapping_proposals"
ADMIN_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/postgres"
DATABASE_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
PREVIOUS = "e3a7c5d9b102"
REVISION = "f4c8a2d91b60"


def _alembic(*args):
    env = {**os.environ, "DATABASE_URL": DATABASE_URL}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="module")
def migration_engine():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{DATABASE}"'))
            conn.execute(text(f'CREATE DATABASE "{DATABASE}"'))
    except OperationalError:
        admin.dispose()
        pytest.skip(f"No disposable PostgreSQL at {HOST}:{PORT}")
    engine = create_engine(DATABASE_URL)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)'))
        admin.dispose()


def test_upgrade_and_downgrade_source_scoped_alias_and_proposal_schema(migration_engine):
    _alembic("upgrade", PREVIOUS)
    _alembic("upgrade", REVISION)
    inspector = inspect(migration_engine)
    assert "source_id" in {c["name"] for c in inspector.get_columns("release_product_aliases")}
    assert "source_mapping_proposal_groups" in inspector.get_table_names()
    assert "source_mapping_proposal_alternatives" in inspector.get_table_names()
    indexes = {row["name"] for row in inspector.get_indexes("release_product_aliases")}
    assert "uq_release_product_aliases_source_identity" in indexes

    with migration_engine.connect() as conn:
        assert conn.scalar(text(
            "SELECT count(*) FROM release_product_aliases a JOIN sources s "
            "ON s.id = a.source_id WHERE a.alias_kind = 'source_rendering' "
            "AND s.name = 'snkrdunk'"
        )) == conn.scalar(text(
            "SELECT count(*) FROM release_product_aliases WHERE alias_kind = 'source_rendering'"
        ))
        assert conn.scalar(text("SELECT count(*) FROM source_mapping_proposal_groups")) == 0
        assert conn.scalar(text("SELECT count(*) FROM source_card_mappings")) == 0
        assert conn.scalar(text("SELECT count(*) FROM price_observations")) == 0

    _alembic("downgrade", PREVIOUS)
    inspector = inspect(migration_engine)
    assert "source_id" not in {c["name"] for c in inspector.get_columns("release_product_aliases")}
    assert "source_mapping_proposal_groups" not in inspector.get_table_names()
    _alembic("upgrade", REVISION)
