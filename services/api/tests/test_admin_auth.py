import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.settings import settings

ADMIN_PATHS = [
    "/admin/refresh-runs",
    "/admin/alert-events",
    "/admin/alert-rules",
    "/admin/card-audit",
    "/admin/source-mappings",
    "/snkrdunk/candidates",
    "/admin/env-check",
    "/admin/system-check",
    "/admin/release-status",
    "/admin/db-backups",
    "/admin/logs",
    "/admin/observability/summary",
    "/admin/rate-limit/status",
    "/admin/market-workflow-runs",
    "/admin/backup/export",
]


@pytest.fixture()
def raw_client(db_session):
    """A TestClient without the `client` fixture's default X-Admin-Token
    header, so these tests fully control what (if anything) is sent."""
    return TestClient(app)


@pytest.mark.parametrize("path", ADMIN_PATHS)
def test_admin_endpoint_rejects_missing_token(raw_client, monkeypatch, path):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "secret-token")
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "APP_ENV", None)

    response = raw_client.get(path)

    assert response.status_code == 401


@pytest.mark.parametrize("path", ADMIN_PATHS)
def test_admin_endpoint_rejects_invalid_token(raw_client, monkeypatch, path):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "secret-token")
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "APP_ENV", None)

    response = raw_client.get(path, headers={"X-Admin-Token": "wrong-token"})

    assert response.status_code == 401


@pytest.mark.parametrize("path", ADMIN_PATHS)
def test_admin_endpoint_accepts_valid_token(raw_client, monkeypatch, path):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "secret-token")
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "APP_ENV", None)

    response = raw_client.get(path, headers={"X-Admin-Token": "secret-token"})

    assert response.status_code == 200


def test_missing_admin_token_config_rejected_outside_development(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", None)
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "APP_ENV", None)

    response = raw_client.get("/admin/refresh-runs")

    assert response.status_code == 500


def test_missing_admin_token_config_rejected_in_non_development_environment(
    raw_client, monkeypatch
):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", None)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "APP_ENV", None)

    response = raw_client.get("/admin/refresh-runs")

    assert response.status_code == 500


def test_missing_admin_token_config_allowed_when_environment_is_development(
    raw_client, monkeypatch
):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", None)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "APP_ENV", None)

    response = raw_client.get("/admin/refresh-runs")

    assert response.status_code == 200


def test_missing_admin_token_config_allowed_when_app_env_is_development(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", None)
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "APP_ENV", "development")

    response = raw_client.get("/admin/refresh-runs")

    assert response.status_code == 200


def test_non_admin_endpoint_does_not_require_token(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "secret-token")
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "APP_ENV", None)

    response = raw_client.get("/health")

    assert response.status_code == 200
