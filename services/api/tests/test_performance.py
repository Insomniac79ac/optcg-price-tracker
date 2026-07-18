"""GET /admin/db-index-audit, GET /admin/performance/summary, and the
X-Process-Time-Ms timing header - see app.services.db_index_audit,
app.services.performance, app.core.request_timing."""


def test_db_index_audit_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain_client = TestClient(app)
    response = plain_client.get("/admin/db-index-audit")
    assert response.status_code == 401


def test_db_index_audit_returns_checks(client, db_session):
    response = client.get("/admin/db-index-audit")

    assert response.status_code == 200
    data = response.json()

    summary = data["summary"]
    assert summary["total_checks"] > 0
    assert summary["total_checks"] == summary["passed"] + summary["warnings"] + summary["critical"]

    assert len(data["checks"]) == summary["total_checks"]
    for check in data["checks"]:
        assert check["status"] in ("pass", "warning", "critical")
        assert check["severity"] in ("warning", "critical")
        assert check["table"]
        assert check["index"]
        assert check["message"]

    # The composite index backing app.services.latest_prices' window-function
    # query is the highest-value check this audit runs - it must exist (the
    # in-memory test DB is created from the current models, which declare
    # it), and it must be marked critical.
    price_composite = next(
        c
        for c in data["checks"]
        if c["index"] == "ix_price_observations_card_source_type_observed"
    )
    assert price_composite["status"] == "pass"
    assert price_composite["severity"] == "critical"


def test_performance_summary_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain_client = TestClient(app)
    response = plain_client.get("/admin/performance/summary")
    assert response.status_code == 401


def test_performance_summary_works_with_empty_data(client, db_session):
    response = client.get("/admin/performance/summary")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] in ("ok", "warning", "critical")
    assert data["database"] == {
        "price_observations_count": 0,
        "raw_snapshots_count": 0,
        "market_signal_events_count": 0,
        "collector_activity_events_count": 0,
        "app_log_events_count": 0,
    }
    assert data["latest_slow_requests"] == []
    assert data["index_audit"]["warnings"] >= 0
    assert data["index_audit"]["critical"] >= 0


def test_performance_summary_reports_table_counts(client, db_session):
    from app.models import Card, PriceObservation, Source

    card = Card(card_code="OP01-001", set_code="OP01", rarity="L", language="en")
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    source = Source(name="yuyutei", base_url="https://example.com")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)

    db_session.add(
        PriceObservation(
            card_id=card.id, source_id=source.id, price_type="sell", price_jpy=1000
        )
    )
    db_session.commit()

    response = client.get("/admin/performance/summary")
    assert response.status_code == 200
    assert response.json()["database"]["price_observations_count"] == 1


def test_response_includes_process_time_header(client, db_session):
    response = client.get("/health")

    assert "x-process-time-ms" in response.headers
    assert float(response.headers["x-process-time-ms"]) >= 0


def test_slow_request_is_logged_when_over_threshold(client, db_session, monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "SLOW_REQUEST_MS", -1)  # every request counts as slow

    response = client.get("/health")
    assert response.status_code == 200

    logs_response = client.get("/admin/logs", params={"event_type": "slow_request"})
    assert logs_response.status_code == 200
    logs = logs_response.json()["logs"]
    assert len(logs) >= 1
    assert logs[0]["event_type"] == "slow_request"
    assert "GET" in logs[0]["message"]


def test_slow_request_not_logged_when_disabled(client, db_session, monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "SLOW_REQUEST_MS", -1)
    monkeypatch.setattr(settings, "SLOW_REQUEST_LOGGING_ENABLED", False)

    client.get("/health")

    logs_response = client.get("/admin/logs", params={"event_type": "slow_request"})
    assert logs_response.json()["logs"] == []
