import pytest

from app.core.rate_limit import classify_route, rate_limit_status, reset_rate_limits
from app.settings import settings


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    reset_rate_limits()
    yield
    reset_rate_limits()


def test_classify_route_groups():
    assert classify_route("/health", "GET") is None
    assert classify_route("/search", "GET") == "search"
    assert classify_route("/search/suggestions", "GET") == "search"
    assert classify_route("/admin/backup/export", "GET") == "import_export"
    assert classify_route("/admin/backup/restore", "POST") == "import_export"
    assert classify_route("/admin/db-backups", "GET") == "import_export"
    assert classify_route("/collection/import.csv", "POST") == "import_export"
    assert classify_route("/wishlist/export.csv", "GET") == "import_export"
    assert classify_route("/admin/system-check", "GET") == "admin"
    assert classify_route("/admin/logs", "POST") == "admin"
    assert classify_route("/snkrdunk/candidates", "GET") == "admin"
    assert classify_route("/cards", "GET") == "public_read"
    assert classify_route("/collection", "GET") == "public_read"
    assert classify_route("/collection", "POST") == "collection_write"
    assert classify_route("/collection/5", "PATCH") == "collection_write"
    assert classify_route("/wishlist", "POST") == "collection_write"
    assert classify_route("/grading/submissions", "POST") == "collection_write"
    assert classify_route("/collector/notes", "POST") == "collection_write"
    assert classify_route("/collector/tags", "POST") is None


def test_public_read_rate_limit_returns_429(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_PUBLIC_READ_PER_5M", 3)

    for _ in range(3):
        response = client.get("/cards")
        assert response.status_code == 200

    response = client.get("/cards")
    assert response.status_code == 429
    body = response.json()
    assert body["detail"] == "Rate limit exceeded"
    assert body["retry_after_seconds"] > 0


def test_admin_rate_limit_returns_429(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ADMIN_PER_5M", 2)

    for _ in range(2):
        response = client.get("/admin/system-check")
        assert response.status_code == 200

    response = client.get("/admin/system-check")
    assert response.status_code == 429


def test_import_export_rate_limit_returns_429(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_IMPORT_EXPORT_PER_10M", 1)

    response = client.get("/admin/db-backups")
    assert response.status_code == 200

    response = client.get("/admin/db-backups")
    assert response.status_code == 429


def test_search_rate_limit_returns_429(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_SEARCH_PER_5M", 2)

    for _ in range(2):
        response = client.get("/search", params={"q": "luffy"})
        assert response.status_code == 200

    response = client.get("/search", params={"q": "luffy"})
    assert response.status_code == 429


def test_collection_write_rate_limit_returns_429(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_COLLECTION_WRITE_PER_5M", 1)
    from app.models import Card

    card = Card(
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        set_code="OP01",
        rarity="L",
        variant="leader",
        language="en",
    )
    db_session.add(card)
    db_session.commit()

    response = client.post("/collection", json={"card_id": card.id, "quantity": 1})
    assert response.status_code == 201

    response = client.post("/collection", json={"card_id": card.id, "quantity": 1})
    assert response.status_code == 429


def test_rate_limit_enabled_false_disables_limits(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr(settings, "RATE_LIMIT_PUBLIC_READ_PER_5M", 1)

    for _ in range(5):
        response = client.get("/cards")
        assert response.status_code == 200


def test_429_response_includes_retry_after_header(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_PUBLIC_READ_PER_5M", 1)

    client.get("/cards")
    response = client.get("/cards")

    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert int(response.headers["Retry-After"]) > 0


def test_rate_limit_headers_present_on_success(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_PUBLIC_READ_PER_5M", 10)

    response = client.get("/cards")

    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "10"
    assert int(response.headers["X-RateLimit-Remaining"]) == 9
    assert "X-RateLimit-Reset" in response.headers
    assert "Retry-After" not in response.headers


def test_rate_limit_status_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain_client = TestClient(app)
    response = plain_client.get("/admin/rate-limit/status")
    assert response.status_code == 401


def test_rate_limit_status_reports_all_groups(client, db_session):
    response = client.get("/admin/rate-limit/status")

    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    groups = {w["group"] for w in data["windows"]}
    assert groups == {"public_read", "collection_write", "admin", "import_export", "search"}


def test_rate_limit_status_reflects_active_keys(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ADMIN_PER_5M", 100)

    client.get("/admin/system-check")

    response = client.get("/admin/rate-limit/status")
    windows = {w["group"]: w for w in response.json()["windows"]}
    assert windows["admin"]["active_keys"] >= 1


def test_rate_limit_status_reports_disabled(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)

    response = client.get("/admin/rate-limit/status")
    assert response.json()["enabled"] is False


def test_repeated_429_logged_at_most_once_per_window(client, db_session, monkeypatch):
    from app.models import AppLogEvent

    monkeypatch.setattr(settings, "RATE_LIMIT_PUBLIC_READ_PER_5M", 1)

    client.get("/cards")
    client.get("/cards")
    client.get("/cards")
    client.get("/cards")

    rate_limit_logs = (
        db_session.query(AppLogEvent).filter(AppLogEvent.event_type == "rate_limit").all()
    )
    assert len(rate_limit_logs) == 1
