import hmac

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import require_admin_token
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
    "/admin/backup/export",
    "/admin/db-index-audit",
    "/admin/performance/summary",
    "/admin/data-retention/policy",
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



def _configured_token(monkeypatch, token="secret-token"):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", token)
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "APP_ENV", None)


def test_admin_endpoint_rejects_different_length_token(raw_client, monkeypatch):
    _configured_token(monkeypatch)

    response = raw_client.get(
        "/admin/refresh-runs", headers={"X-Admin-Token": "secret-token-extra"}
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Admin token required"}


def test_admin_endpoint_rejects_empty_token(raw_client, monkeypatch):
    _configured_token(monkeypatch)

    response = raw_client.get("/admin/refresh-runs", headers={"X-Admin-Token": ""})

    assert response.status_code == 401
    assert response.json() == {"detail": "Admin token required"}


def test_require_admin_token_rejects_non_ascii_value(monkeypatch):
    _configured_token(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        require_admin_token(x_admin_token="spカード")

    assert exc.value.status_code == 401
    assert exc.value.detail == "Admin token required"


def test_require_admin_token_rejects_empty_presented_value(monkeypatch):
    _configured_token(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        require_admin_token(x_admin_token="")

    assert exc.value.status_code == 401
    assert exc.value.detail == "Admin token required"


def test_empty_admin_token_config_rejected_outside_development(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "APP_ENV", None)

    response = raw_client.get(
        "/admin/refresh-runs", headers={"X-Admin-Token": ""}
    )

    assert response.status_code == 500
    assert response.status_code != 200


def test_admin_token_decision_uses_standard_library_compare(raw_client, monkeypatch):
    _configured_token(monkeypatch)
    presented = "secret-token"
    calls = []
    real_compare = hmac.compare_digest

    def record(left, right):
        calls.append((left, right))
        return real_compare(left, right)

    monkeypatch.setattr("app.auth.hmac.compare_digest", record)
    recorded = raw_client.get(
        "/admin/refresh-runs", headers={"X-Admin-Token": presented}
    )
    assert recorded.status_code == 200
    assert calls == [(presented.encode("utf-8"), b"secret-token")]

    monkeypatch.setattr("app.auth.hmac.compare_digest", lambda left, right: False)
    accepted = raw_client.get(
        "/admin/refresh-runs", headers={"X-Admin-Token": "secret-token"}
    )
    assert accepted.status_code == 401
    assert accepted.json() == {"detail": "Admin token required"}

    monkeypatch.setattr("app.auth.hmac.compare_digest", lambda left, right: True)
    rejected = raw_client.get(
        "/admin/refresh-runs", headers={"X-Admin-Token": "wrong-token"}
    )
    assert rejected.status_code == 200
