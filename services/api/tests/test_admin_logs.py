from app.services.app_logging import record_app_log


def test_list_logs_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain_client = TestClient(app)
    response = plain_client.get("/admin/logs")
    assert response.status_code == 401


def test_list_logs_returns_empty_summary_with_no_data(client, db_session):
    response = client.get("/admin/logs")

    assert response.status_code == 200
    data = response.json()
    assert data["summary"]["total_logs"] == 0
    assert data["logs"] == []


def test_list_logs_filters_by_level(client, db_session):
    record_app_log("info", "api", "startup", "info message")
    record_app_log("error", "worker", "price_refresh", "error message")

    response = client.get("/admin/logs", params={"level": "error"})

    data = response.json()
    assert data["summary"]["total_logs"] == 1
    assert len(data["logs"]) == 1
    assert data["logs"][0]["level"] == "error"


def test_list_logs_filters_by_service(client, db_session):
    record_app_log("info", "api", "startup", "api message")
    record_app_log("info", "worker", "price_refresh", "worker message")

    response = client.get("/admin/logs", params={"service": "worker"})

    data = response.json()
    assert data["summary"]["total_logs"] == 1
    assert data["logs"][0]["service"] == "worker"


def test_list_logs_filters_by_event_type(client, db_session):
    record_app_log("info", "api", "startup", "startup message")
    record_app_log("info", "api", "backup", "backup message")

    response = client.get("/admin/logs", params={"event_type": "backup"})

    data = response.json()
    assert data["summary"]["total_logs"] == 1
    assert data["logs"][0]["event_type"] == "backup"


def test_list_logs_filters_by_search_query(client, db_session):
    record_app_log("info", "api", "startup", "Yuyu-Tei refresh failed")
    record_app_log("info", "api", "startup", "unrelated message")

    response = client.get("/admin/logs", params={"q": "yuyu-tei"})

    data = response.json()
    assert data["summary"]["total_logs"] == 1
    assert "Yuyu-Tei" in data["logs"][0]["message"]


def test_list_logs_summary_counts_by_level(client, db_session):
    record_app_log("warning", "api", "startup", "w1")
    record_app_log("error", "api", "startup", "e1")
    record_app_log("critical", "api", "startup", "c1")

    response = client.get("/admin/logs")

    summary = response.json()["summary"]
    assert summary["warning_count"] == 1
    assert summary["error_count"] == 1
    assert summary["critical_count"] == 1
    assert summary["total_logs"] == 3


def test_list_logs_rejects_invalid_level(client, db_session):
    response = client.get("/admin/logs", params={"level": "not-a-level"})
    assert response.status_code == 400


def test_get_log_detail_works(client, db_session):
    record_app_log(
        "error",
        "worker",
        "price_refresh",
        "detail test",
        context={"foo": "bar"},
        related_run_id=5,
        related_entity_type="price_refresh_run",
        related_entity_id=5,
    )
    list_response = client.get("/admin/logs")
    log_id = list_response.json()["logs"][0]["id"]

    response = client.get(f"/admin/logs/{log_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == log_id
    assert data["message"] == "detail test"
    assert data["context"] == {"foo": "bar"}
    assert data["related_run_id"] == 5


def test_get_log_detail_404_for_missing_id(client, db_session):
    response = client.get("/admin/logs/999999")
    assert response.status_code == 404


def test_prune_dry_run_does_not_delete(client, db_session):
    record_app_log("info", "api", "startup", "test")

    response = client.post("/admin/logs/prune", json={"older_than_days": 30, "dry_run": True})

    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert data["deleted"] == 0
    assert client.get("/admin/logs").json()["summary"]["total_logs"] == 1


def test_prune_actual_deletes_older_logs(client, db_session):
    import datetime as dt

    from app.models import AppLogEvent

    old = AppLogEvent(level="info", service="api", event_type="startup", message="old")
    db_session.add(old)
    db_session.commit()
    db_session.execute(
        AppLogEvent.__table__.update()
        .where(AppLogEvent.id == old.id)
        .values(created_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=60))
    )
    db_session.commit()

    response = client.post("/admin/logs/prune", json={"older_than_days": 30, "dry_run": False})

    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is False
    assert data["deleted"] == 1
    assert client.get("/admin/logs").json()["summary"]["total_logs"] == 0


def test_prune_refuses_less_than_min_days_without_confirm(client, db_session):
    response = client.post("/admin/logs/prune", json={"older_than_days": 3, "dry_run": True})
    assert response.status_code == 400


def test_prune_allows_less_than_min_days_with_confirm(client, db_session):
    response = client.post(
        "/admin/logs/prune",
        json={"older_than_days": 3, "dry_run": True, "confirm": "PRUNE"},
    )
    assert response.status_code == 200
