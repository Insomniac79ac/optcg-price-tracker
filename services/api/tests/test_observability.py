from app.services.app_logging import record_app_log


def test_observability_summary_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain_client = TestClient(app)
    response = plain_client.get("/admin/observability/summary")
    assert response.status_code == 401


def test_observability_summary_works_with_empty_data(client, db_session):
    response = client.get("/admin/observability/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["last_24h"] == {"critical": 0, "error": 0, "warning": 0, "info": 0}
    assert data["latest_error"] is None
    assert data["latest_market_workflow_run"] is None
    assert data["latest_price_refresh_run"] is None
    assert data["latest_backup"] is None
    assert data["latest_system_check_status"] in ("ok", "warning", "critical")


def test_observability_summary_reports_critical_status_on_critical_log(client, db_session):
    record_app_log("critical", "api", "startup", "refused to start")

    response = client.get("/admin/observability/summary")

    data = response.json()
    assert data["status"] == "critical"
    assert data["last_24h"]["critical"] == 1
    assert data["latest_error"]["message"] == "refused to start"


def test_observability_summary_reports_warning_status_on_error_log(client, db_session):
    record_app_log("error", "worker", "price_refresh", "refresh failed")

    response = client.get("/admin/observability/summary")

    data = response.json()
    assert data["status"] == "warning"
    assert data["last_24h"]["error"] == 1
