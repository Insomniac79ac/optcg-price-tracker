"""Real additive upgrade/downgrade on a uniquely named local disposable DB."""

import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from app.db import Base

PREVIOUS = "e6a8b0c3d5f7"
REVISION = "9d2b7a1c4e60"
API_ROOT = Path(__file__).resolve().parents[1]
TABLES = (
    "source_dispatch_budgets",
    "freshness_work",
    "freshness_price_states",
    "freshness_attempts",
)


def test_additive_migration_upgrade_downgrade_and_model_parity():
    url = make_url(
        os.environ.get(
            "TEST_POSTGRES_URL",
            "postgresql+psycopg://opcg:opcg@localhost:5544/opcg_test",
        )
    )
    if url.host not in {"localhost", "127.0.0.1"} or url.database != "opcg_test":
        pytest.skip("requires local disposable PostgreSQL")
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    name = "freshness_migration_" + uuid4().hex[:12]
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError:
        admin.dispose()
        pytest.skip("disposable PostgreSQL is unavailable")
    target = url.set(database=name)
    engine = create_engine(target)

    def migrate(*args):
        env = dict(
            os.environ, DATABASE_URL=target.render_as_string(hide_password=False)
        )
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=API_ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=300,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    def schema():
        inspector = inspect(engine)
        return {
            table: [
                (c["name"], str(c["type"]), c["nullable"])
                for c in inspector.get_columns(table)
            ]
            for table in inspector.get_table_names()
        }

    try:
        migrate("upgrade", PREVIOUS)
        before = schema()
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO sources (name,base_url) VALUES ('fixture','https://example.test')"
                )
            )
        migrate("upgrade", REVISION)
        after = schema()
        assert set(after) - set(before) == set(TABLES)
        assert {name: after[name] for name in before} == before
        with engine.connect() as conn:
            assert (
                conn.scalar(text("SELECT name FROM sources WHERE name='fixture'"))
                == "fixture"
            )
            for table in TABLES:
                assert conn.scalar(text(f'SELECT count(*) FROM "{table}"')) == 0
            context = MigrationContext.configure(
                conn,
                opts={
                    "include_object": lambda obj, name, kind, reflected, compared: kind
                    != "table"
                    or name in TABLES,
                },
            )
            assert compare_metadata(context, Base.metadata) == []
        inspector = inspect(engine)
        for table in TABLES:
            expected = {
                c.name
                for c in Base.metadata.tables[table].constraints
                if c.__class__.__name__ == "CheckConstraint"
            }
            assert {
                c["name"] for c in inspector.get_check_constraints(table)
            } == expected
        migrate("downgrade", PREVIOUS)
        assert schema() == before
        with engine.connect() as conn:
            assert (
                conn.scalar(text("SELECT name FROM sources WHERE name='fixture'"))
                == "fixture"
            )
        migrate("upgrade", REVISION)
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM freshness_work")) == 0
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
