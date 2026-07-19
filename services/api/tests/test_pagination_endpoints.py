"""Cross-cutting coverage for the pagination/response-size work - see
app.core.pagination, app.core.response_size, and 'API pagination and
response size limits' in docs/operations.md. Per-endpoint filter/business
logic already has its own test file (test_market_signals.py,
test_opportunity_scoring.py, test_admin_logs.py, ...); this file only checks
that the shared `pagination` metadata block and response-size guard are
wired in consistently across endpoints, and that export endpoints were left
alone.
"""

from app.models import AppLogEvent


PAGINATION_KEYS = {
    "total",
    "limit",
    "offset",
    "has_next",
    "has_previous",
    "next_offset",
    "previous_offset",
}


def test_market_opportunities_returns_pagination_metadata(client, db_session):
    response = client.get("/market/opportunities")
    assert response.status_code == 200
    data = response.json()
    assert "pagination" in data
    assert set(data["pagination"].keys()) == PAGINATION_KEYS
    assert data["pagination"]["total"] == data["summary"]["total_opportunities"]
    assert data["pagination"]["has_next"] is False
    assert data["pagination"]["has_previous"] is False


def test_market_signals_returns_pagination_metadata(client, db_session):
    response = client.get("/market/signals")
    assert response.status_code == 200
    data = response.json()
    assert "pagination" in data
    assert set(data["pagination"].keys()) == PAGINATION_KEYS
    assert data["pagination"]["total"] == data["summary"]["total_signals"]


def test_market_signal_events_returns_pagination_metadata(client, db_session):
    response = client.get("/market/signal-events")
    assert response.status_code == 200
    data = response.json()
    assert "pagination" in data
    assert set(data["pagination"].keys()) == PAGINATION_KEYS
    assert data["pagination"]["total"] == data["summary"]["total_events"]


def test_admin_logs_returns_pagination_metadata(client, db_session):
    response = client.get("/admin/logs")
    assert response.status_code == 200
    data = response.json()
    assert "pagination" in data
    assert set(data["pagination"].keys()) == PAGINATION_KEYS
    assert data["pagination"]["total"] == data["summary"]["total_logs"]


def test_admin_logs_rejects_limit_over_new_max(client, db_session):
    # Max limit for /admin/logs was tightened from 1000 to 500.
    response = client.get("/admin/logs", params={"limit": 501})
    assert response.status_code == 422


def test_admin_logs_allows_limit_at_new_max(client, db_session):
    response = client.get("/admin/logs", params={"limit": 500})
    assert response.status_code == 200


def test_collector_activity_returns_pagination_metadata(client, db_session):
    response = client.get("/collector/activity")
    assert response.status_code == 200
    data = response.json()
    assert "pagination" in data
    assert set(data["pagination"].keys()) == PAGINATION_KEYS
    assert data["pagination"]["total"] == data["summary"]["total_events"]


def test_search_returns_pagination_metadata(client, db_session):
    response = client.get("/search", params={"q": "anything"})
    assert response.status_code == 200
    data = response.json()
    assert "pagination" in data
    assert set(data["pagination"].keys()) == PAGINATION_KEYS
    assert data["pagination"]["total"] == data["summary"]["total_results"]


def test_admin_db_backups_returns_pagination_metadata(client, db_session):
    response = client.get("/admin/db-backups")
    assert response.status_code == 200
    data = response.json()
    assert "pagination" in data
    assert set(data["pagination"].keys()) == PAGINATION_KEYS


def test_admin_performance_summary_includes_response_size_fields(client, db_session):
    response = client.get("/admin/performance/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["response_size_warnings_last_24h"] == 0
    assert data["slow_requests_last_24h"] == 0
    assert data["largest_recent_responses"] == []


# --- export endpoints are NOT paginated -------------------------------------


def test_collection_export_csv_is_not_paginated(client, db_session):
    response = client.get("/collection/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    # A CSV export response body is not JSON at all, so it can't carry a
    # `pagination` key - this just confirms the endpoint still works.


def test_wishlist_export_csv_is_not_paginated(client, db_session):
    response = client.get("/wishlist/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")


# --- response size header ----------------------------------------------------


def test_health_response_has_size_header(client, db_session):
    response = client.get("/health")
    assert response.status_code == 200
    assert "x-response-size-bytes" in response.headers
    assert int(response.headers["x-response-size-bytes"]) > 0


def test_cards_response_has_size_header(client, db_session):
    response = client.get("/cards")
    assert response.status_code == 200
    assert "x-response-size-bytes" in response.headers
    assert int(response.headers["x-response-size-bytes"]) >= 0


def test_streamed_export_csv_response_has_no_size_header(client, db_session):
    """/collection/export.csv is a genuine StreamingResponse (see 'Large
    import/export jobs' in docs/operations.md) - it has no Content-Length,
    so ResponseSizeMiddleware silently skips the header/warning rather than
    buffering the whole body just to measure it (see its own docstring).
    This documents that trade-off rather than assuming every response gets
    the header."""
    response = client.get("/collection/export.csv")
    assert response.status_code == 200
    assert "x-response-size-bytes" not in response.headers


# --- response size warning logging -------------------------------------------


def test_oversized_response_records_app_log_warning(client, db_session, monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "RESPONSE_SIZE_WARNING_BYTES", 0)

    response = client.get("/health")
    assert response.status_code == 200

    warnings = (
        db_session.query(AppLogEvent)
        .filter(AppLogEvent.event_type == "response_size_warning")
        .all()
    )
    assert len(warnings) >= 1
    assert warnings[0].context_json["method"] == "GET"
    assert warnings[0].context_json["path"] == "/health"
    assert warnings[0].context_json["size_bytes"] > 0


def test_response_size_warning_not_logged_when_disabled(client, db_session, monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "RESPONSE_SIZE_WARNING_BYTES", 0)
    monkeypatch.setattr(settings, "RESPONSE_SIZE_WARNING_ENABLED", False)

    client.get("/health")

    warnings = (
        db_session.query(AppLogEvent)
        .filter(AppLogEvent.event_type == "response_size_warning")
        .all()
    )
    assert warnings == []


def test_response_size_warning_visible_via_admin_logs(client, db_session, monkeypatch):
    from app.settings import settings

    monkeypatch.setattr(settings, "RESPONSE_SIZE_WARNING_BYTES", 0)

    client.get("/health")

    logs_response = client.get("/admin/logs", params={"event_type": "response_size_warning"})
    assert logs_response.status_code == 200
    logs = logs_response.json()["logs"]
    assert len(logs) >= 1
    assert logs[0]["event_type"] == "response_size_warning"
