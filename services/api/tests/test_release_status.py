def test_release_status_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain_client = TestClient(app)
    response = plain_client.get("/admin/release-status")
    assert response.status_code == 401


def test_release_status_returns_version_fields(client, db_session):
    response = client.get("/admin/release-status")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["version"], str) and data["version"]
    assert isinstance(data["git_commit"], str)
    assert isinstance(data["build_time"], str)
    assert isinstance(data["app_env"], str)


def test_release_status_returns_expected_shape(client, db_session):
    response = client.get("/admin/release-status")

    data = response.json()
    assert data["latest_market_workflow_run"] is None
    assert data["latest_backup"] is None
    assert data["latest_error"] is None

    assert data["latest_system_check"]["status"] in ("ok", "warning", "critical")
    assert isinstance(data["latest_system_check"]["checks"], list)

    readiness = data["release_readiness"]
    assert readiness["system_check_status"] in ("ok", "warning", "critical")
    assert readiness["critical_logs_last_24h"] == 0
    assert readiness["latest_backup_available"] is False


def test_release_status_reports_critical_logs(client, db_session):
    from app.services.app_logging import record_app_log

    record_app_log("critical", "api", "startup", "refused to start")

    response = client.get("/admin/release-status")

    data = response.json()
    assert data["release_readiness"]["critical_logs_last_24h"] == 1
    assert data["latest_error"]["message"] == "refused to start"
