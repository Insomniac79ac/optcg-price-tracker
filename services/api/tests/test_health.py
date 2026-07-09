from fastapi.testclient import TestClient

import app.api.health as health_module
from app.main import app

client = TestClient(app)


def test_health_returns_expected_shape():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"status", "app_env", "database_connected", "redis_connected"}
    assert body["status"] in ("ok", "degraded")


def test_health_reports_database_connected(monkeypatch):
    monkeypatch.setattr(health_module, "check_database_connected", lambda: True)
    monkeypatch.setattr(health_module, "check_redis_connected", lambda: True)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database_connected"] is True
    assert body["redis_connected"] is True


def test_health_reports_database_disconnected(monkeypatch):
    monkeypatch.setattr(health_module, "check_database_connected", lambda: False)
    monkeypatch.setattr(health_module, "check_redis_connected", lambda: False)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database_connected"] is False
    assert body["redis_connected"] is False


def test_health_reports_app_env(monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "APP_ENV", None)
    monkeypatch.setattr(health_module, "check_database_connected", lambda: True)
    monkeypatch.setattr(health_module, "check_redis_connected", lambda: True)

    response = client.get("/health")

    assert response.json()["app_env"] == "development"
