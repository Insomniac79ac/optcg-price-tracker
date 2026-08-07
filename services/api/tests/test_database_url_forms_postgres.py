"""Proves DATABASE_URL normalization actually connects with the installed
psycopg 3 driver end-to-end, for both the Railway-standard postgresql://
scheme and the already-normalized postgresql+psycopg:// scheme.

Points at TEST_POSTGRES_HOST/TEST_POSTGRES_PORT (defaulting to the same
disposable instance used by test_canonical_cards_postgres.py, localhost:5544)
and skips outright if no server answers, so the rest of the suite is
unaffected."""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.settings import Settings

TEST_POSTGRES_HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
TEST_POSTGRES_PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")

FORM_A = f"postgresql://opcg:opcg@{TEST_POSTGRES_HOST}:{TEST_POSTGRES_PORT}/opcg_test_a"
FORM_B = f"postgresql+psycopg://opcg:opcg@{TEST_POSTGRES_HOST}:{TEST_POSTGRES_PORT}/opcg_test_b"


def _skip_if_unreachable(url: str) -> None:
    try:
        engine = create_engine(url)
        with engine.connect():
            pass
        engine.dispose()
    except OperationalError:
        pytest.skip(f"No PostgreSQL server reachable at {url}")


@pytest.mark.parametrize("raw_url", [FORM_A, FORM_B], ids=["postgresql", "postgresql+psycopg"])
def test_api_settings_connect_with_installed_psycopg_driver(raw_url, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    _skip_if_unreachable(raw_url.replace("postgresql://", "postgresql+psycopg://", 1))

    settings = Settings(_env_file=None, DATABASE_URL=raw_url)
    assert settings.DATABASE_URL.startswith("postgresql+psycopg://")

    engine = create_engine(settings.DATABASE_URL, future=True)
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1
    finally:
        engine.dispose()
