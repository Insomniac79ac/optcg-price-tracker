import pytest
from pydantic import ValidationError

from app.config_check import validate_config
from app.env import get_app_env, is_production_environment
from app.settings import Settings, settings


def test_config_passes_in_development(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "APP_ENV", None)
    monkeypatch.setattr(settings, "ADMIN_TOKEN", None)

    result = validate_config()

    assert result.ok is True
    assert result.errors == []
    assert result.app_env == "development"


def test_config_passes_when_environment_unset_and_admin_token_missing(monkeypatch):
    # Missing ENVIRONMENT/APP_ENV defaults to development for reporting - an
    # unconfigured local/test box should not be treated as production.
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "APP_ENV", None)
    monkeypatch.setattr(settings, "ADMIN_TOKEN", None)

    result = validate_config()

    assert result.ok is True
    assert result.app_env == "development"


def test_config_fails_in_production_without_admin_token(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "APP_ENV", None)
    monkeypatch.setattr(settings, "ADMIN_TOKEN", None)

    result = validate_config()

    assert result.ok is False
    assert any("ADMIN_TOKEN" in error for error in result.errors)


def test_config_passes_in_production_with_admin_token(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "APP_ENV", None)
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "secret-token")

    result = validate_config()

    assert result.ok is True
    assert result.errors == []


def test_config_fails_when_app_env_is_production_without_admin_token(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "ADMIN_TOKEN", None)

    result = validate_config()

    assert result.ok is False


def test_get_app_env_defaults_to_development_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "APP_ENV", None)

    assert get_app_env() == "development"


def test_is_production_environment_true_only_for_production(monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "APP_ENV", None)
    assert is_production_environment() is True

    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")
    assert is_production_environment() is False


def test_database_url_must_not_be_blank():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, DATABASE_URL="")


def test_redis_url_must_not_be_blank():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, REDIS_URL="")
