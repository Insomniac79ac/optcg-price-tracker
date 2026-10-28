"""Frozen Market Value membership migration (owner plan A, 2026-10-28): disposable PostgreSQL."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import uuid

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db import Base
from app.services import market_value_membership as membership
from tests.pg_url import admin_url, postgres_unavailable, postgres_url, server_label

PARENT = "7a52e9b48e8a"
REVISION = "001d92ba8eb9"
API_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = API_ROOT / f"alembic/versions/{REVISION}_add_market_value_memberships.py"


def _migration():
    spec = importlib.util.spec_from_file_location(f"migration_{REVISION}", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def alembic(url, action, revision):
    return subprocess.run(
        [sys.executable, "-m", "alembic", action, revision],
        cwd=API_ROOT,
        env=dict(os.environ, DATABASE_URL=url),
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_revision_extends_the_new_sources_head():
    module = _migration()
    assert (module.revision, module.down_revision) == (REVISION, PARENT)


def test_collectors_do_not_load_the_new_tables():
    assert "market_value_membership" not in (API_ROOT / "app/models/__init__.py").read_text()


@pytest.fixture(scope="module")
def pg():
    name = "mv_membership_" + uuid.uuid4().hex[:10]
    admin = create_engine(admin_url(), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError:
        admin.dispose()
        postgres_unavailable(f"Disposable PostgreSQL unavailable at {server_label()}")
    engine = create_engine(postgres_url(name))
    try:
        result = alembic(postgres_url(name), "upgrade", REVISION)
        assert result.returncode == 0, result.stdout + result.stderr
        yield engine, postgres_url(name)
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def test_tables_exist_empty_and_match_the_models(pg):
    engine, _ = pg
    assert set(membership.TABLES) <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION
        for table in membership.TABLES:
            assert connection.scalar(text(f'SELECT count(*) FROM "{table}"')) == 0

    def ours(obj, name, kind, reflected, compare_to):
        table = obj if kind == "table" else getattr(obj, "table", None)
        return table is not None and table.name in membership.TABLES

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True, "include_object": ours})
        assert compare_metadata(context, Base.metadata) == []


def test_constraints(pg):
    engine, _ = pg
    with engine.connect() as connection:
        for bad in (
            "INSERT INTO market_value_memberships (revision, origin, print_count, release_count) VALUES (' ', 'publication', 1, 0)",
            "INSERT INTO market_value_memberships (revision, origin, print_count, release_count) VALUES ('r', 'other', 1, 0)",
            "INSERT INTO market_value_memberships (revision, origin, print_count, release_count) VALUES ('r', 'publication', 0, 0)",
            "INSERT INTO market_value_membership_prints VALUES (999, 999, 999)",
        ):
            savepoint = connection.begin_nested()
            with pytest.raises(IntegrityError):
                connection.execute(text(bad))
            savepoint.rollback()
        connection.execute(text(
            "INSERT INTO market_value_memberships (revision, origin, print_count, release_count) VALUES ('r', 'publication', 1, 0)"
        ))
        savepoint = connection.begin_nested()
        with pytest.raises(IntegrityError):
            connection.execute(text(
                "INSERT INTO market_value_memberships (revision, origin, print_count, release_count) VALUES ('r', 'publication', 1, 0)"
            ))
        savepoint.rollback()
        connection.rollback()


def test_downgrade_removes_only_the_new_tables(pg):
    _, url = pg
    result = alembic(url, "downgrade", PARENT)
    assert result.returncode == 0, result.stdout + result.stderr
    engine = create_engine(url)
    try:
        names = set(inspect(engine).get_table_names())
        assert not set(membership.TABLES) & names and "market_value_points" in names
    finally:
        engine.dispose()
    assert alembic(url, "upgrade", REVISION).returncode == 0
