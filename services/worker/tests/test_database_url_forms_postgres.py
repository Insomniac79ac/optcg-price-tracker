"""Proves worker DATABASE_URL normalization actually connects with the
installed psycopg 3 driver end-to-end, for both the Railway-standard
postgresql:// scheme and the already-normalized postgresql+psycopg://
scheme.

Points at TEST_POSTGRES_URL's server via tests/pg_url.py (creating
opcg_test_a / opcg_test_b there if absent); skips when no server answers,
fails instead under REQUIRE_POSTGRES=1."""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from tests.pg_url import ensure_database, postgres_url

from worker.settings import Settings


FORM_A = postgres_url("opcg_test_a", drivername="postgresql")
FORM_B = postgres_url("opcg_test_b")


def _ensure_database(url: str) -> None:
    # The CI service only creates TEST_POSTGRES_URL's own database; these
    # per-form databases are created on demand rather than assumed.
    ensure_database(make_url(url).database)


@pytest.mark.parametrize("raw_url", [FORM_A, FORM_B], ids=["postgresql", "postgresql+psycopg"])
def test_worker_settings_connect_with_installed_psycopg_driver(raw_url, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _ensure_database(raw_url)

    settings = Settings(_env_file=None, DATABASE_URL=raw_url)
    assert settings.DATABASE_URL.startswith("postgresql+psycopg://")

    engine = create_engine(settings.DATABASE_URL, future=True)
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1
    finally:
        engine.dispose()
