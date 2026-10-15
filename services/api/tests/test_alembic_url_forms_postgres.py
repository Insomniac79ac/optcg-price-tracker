"""Proves Alembic's env.py (which reads settings.DATABASE_URL, same as
app.db) upgrades to and inspects a single head against a disposable Postgres
for both the Railway-standard postgresql:// scheme and the already-normalized
postgresql+psycopg:// scheme. Does not change migration history - only runs
existing migrations against throwaway databases.

Runs `alembic` as a subprocess per URL form (rather than in-process) because
app.settings.settings is a module-level singleton read once at import time -
an in-process run would silently reuse whichever DATABASE_URL happened to be
set when app.settings was first imported in this test session, not the one
each parametrized case actually sets. A fresh subprocess re-reads the env var
correctly every time.

Points at TEST_POSTGRES_URL's server via tests/pg_url.py (creating
opcg_test_a / opcg_test_b there if absent); skips when no server answers,
fails instead under REQUIRE_POSTGRES=1."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from tests.pg_url import ensure_database, postgres_url

REPO_ROOT = Path(__file__).resolve().parents[1]


FORM_A = postgres_url("opcg_test_a", drivername="postgresql")
FORM_B = postgres_url("opcg_test_b")


def _ensure_database(url: str) -> None:
    # The CI service only creates TEST_POSTGRES_URL's own database; these
    # per-form databases are created on demand rather than assumed.
    ensure_database(make_url(url).database)


def _run_alembic(*args: str, database_url: str) -> str:
    env = dict(os.environ)
    env["DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"alembic {' '.join(args)} failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    return result.stdout


@pytest.mark.parametrize("raw_url", [FORM_A, FORM_B], ids=["postgresql", "postgresql+psycopg"])
def test_alembic_current_and_heads_agree_for_both_url_forms(raw_url):
    psycopg_url = raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
    _ensure_database(psycopg_url)

    _run_alembic("upgrade", "head", database_url=raw_url)

    current_output = _run_alembic("current", database_url=raw_url)
    heads_output = _run_alembic("heads", database_url=raw_url)

    assert "(head)" in current_output
    current_rev = current_output.strip().splitlines()[-1].split()[0]
    heads_rev = heads_output.strip().splitlines()[-1].split()[0]
    assert current_rev == heads_rev

    engine = create_engine(psycopg_url)
    try:
        with engine.connect() as conn:
            db_rev = conn.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar()
    finally:
        engine.dispose()
    assert db_rev == current_rev
