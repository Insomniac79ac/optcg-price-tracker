import pytest
from pydantic import ValidationError

from app.settings import Settings, normalize_database_url


def test_plain_postgresql_scheme_becomes_psycopg():
    assert (
        normalize_database_url("postgresql://user:pass@host:5432/db")
        == "postgresql+psycopg://user:pass@host:5432/db"
    )


def test_postgres_alias_scheme_becomes_psycopg():
    assert (
        normalize_database_url("postgres://user:pass@host:5432/db")
        == "postgresql+psycopg://user:pass@host:5432/db"
    )


def test_already_psycopg_scheme_is_unchanged():
    url = "postgresql+psycopg://user:pass@host:5432/db"
    assert normalize_database_url(url) == url


def test_query_parameters_are_preserved():
    url = "postgresql://user:pass@host:5432/db?sslmode=require&connect_timeout=10"
    assert normalize_database_url(url) == (
        "postgresql+psycopg://user:pass@host:5432/db?sslmode=require&connect_timeout=10"
    )


def test_url_encoded_special_characters_in_password_are_preserved():
    # %40 = "@", %2F = "/", %23 = "#" - all left byte-for-byte untouched.
    url = "postgresql://user:p%40ss%2Fw%23rd@host:5432/db"
    assert normalize_database_url(url) == (
        "postgresql+psycopg://user:p%40ss%2Fw%23rd@host:5432/db"
    )


def test_unrelated_url_is_not_rewritten():
    for url in (
        "sqlite:///./test.db",
        "mysql+pymysql://user:pass@host/db",
        "redis://redis:6379/0",
        "",
    ):
        assert normalize_database_url(url) == url


def test_normalization_does_not_log_credentials(caplog):
    with caplog.at_level("DEBUG"):
        normalize_database_url("postgresql://user:supersecretpw@host:5432/db")

    assert "supersecretpw" not in caplog.text


def test_settings_database_url_is_normalized_on_construction(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = Settings(_env_file=None, DATABASE_URL="postgresql://opcg:opcg@postgres:5432/opcg")

    assert settings.DATABASE_URL == "postgresql+psycopg://opcg:opcg@postgres:5432/opcg"


def test_settings_database_url_already_psycopg_is_unchanged(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    url = "postgresql+psycopg://opcg:opcg@postgres:5432/opcg"

    settings = Settings(_env_file=None, DATABASE_URL=url)

    assert settings.DATABASE_URL == url


def test_database_url_must_not_be_blank():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, DATABASE_URL="")
