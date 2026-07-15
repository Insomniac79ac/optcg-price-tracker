def test_env_check_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain_client = TestClient(app)
    response = plain_client.get("/admin/env-check")
    assert response.status_code == 401


def test_env_check_returns_expected_shape(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")

    response = client.get("/admin/env-check")

    assert response.status_code == 200
    data = response.json()
    assert data["app_env"] == "development"
    assert data["status"] in ("ok", "warning", "critical")
    assert isinstance(data["checks"], list)
    assert len(data["checks"]) > 0
    assert isinstance(data["warnings"], list)
    assert isinstance(data["errors"], list)

    for check in data["checks"]:
        assert set(check.keys()) == {"name", "status", "severity", "message"}
        assert check["status"] in ("pass", "warning", "fail")
        assert check["severity"] in ("info", "warning", "critical")

    names = {c["name"] for c in data["checks"]}
    assert "admin_token_present" in names
    assert "database_url_present" in names
    assert "redis_url_present" in names
    assert "scraping_mode_valid" in names


def test_env_check_reports_ok_for_valid_production_config(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ADMIN_TOKEN", "a" * 40)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://opcg:real-password@postgres:5432/opcg")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")

    response = client.get("/admin/env-check")

    data = response.json()
    assert data["status"] == "ok"
    assert data["errors"] == []


def test_env_check_reports_critical_in_production_with_bad_config(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ADMIN_TOKEN", "local-dev-admin-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://opcg:opcg@postgres:5432/opcg")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")

    response = client.get("/admin/env-check")

    data = response.json()
    assert data["status"] == "critical"
    assert data["app_env"] == "production"
    assert len(data["errors"]) > 0
