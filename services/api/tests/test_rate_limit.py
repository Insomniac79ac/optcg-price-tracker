import jwt
import pytest

from app.accounts.config import FLAG
from app.core.rate_limit import classify_route, group_config, rate_limit_status, reset_rate_limits
from app.settings import settings
from tests._auth_helpers import make_bearer_token


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    reset_rate_limits()
    yield
    reset_rate_limits()


def test_classify_route_groups():
    assert classify_route("/health", "GET") is None
    # /search was removed in Collector v1 S1; it is an ordinary (404) read now.
    assert classify_route("/search", "GET") == "public_read"
    assert classify_route("/admin/backup/export", "GET") == "import_export"
    assert classify_route("/admin/backup/restore", "POST") == "import_export"
    assert classify_route("/admin/db-backups", "GET") == "import_export"
    assert classify_route("/admin/system-check", "GET") == "admin"
    assert classify_route("/admin/logs", "POST") == "admin"
    assert classify_route("/snkrdunk/candidates", "GET") == "admin"
    assert classify_route("/cards", "GET") == "public_read"
    assert classify_route("/collector/tags", "POST") is None


# The legacy collection, wishlist, grading and notes routers went in Collector
# v1 S8; their paths are no longer a group of their own.
@pytest.mark.parametrize(
    "path, method",
    [
        ("/collection", "POST"),
        ("/collection/5", "PATCH"),
        ("/wishlist", "POST"),
        ("/grading/submissions", "POST"),
        ("/collector/notes", "POST"),
    ],
)
def test_removed_legacy_write_paths_are_not_a_group(path, method):
    assert classify_route(path, method) is None


@pytest.mark.parametrize(
    "path, method",
    [("/collection/import.csv", "POST"), ("/wishlist/export.csv", "GET")],
)
def test_removed_legacy_csv_paths_are_not_import_export(path, method):
    assert classify_route(path, method) != "import_export"


ME_GROUPS = {
    ("GET", "/me/collection"): "public_read",
    ("POST", "/me/collection"): "collection_write",
    ("PATCH", "/me/collection/{entry_id}"): "collection_write",
    ("DELETE", "/me/collection/{entry_id}"): "collection_write",
    ("GET", "/me/collection/value"): "public_read",
    ("GET", "/me/watchlist"): "public_read",
    ("POST", "/me/watchlist"): "collection_write",
    ("PATCH", "/me/watchlist/{entry_id}"): "collection_write",
    ("DELETE", "/me/watchlist/{entry_id}"): "collection_write",
    ("GET", "/me/profile"): "public_read",
    ("GET", "/me/preferences"): "public_read",
    ("PUT", "/me/preferences"): "collection_write",
    ("GET", "/me/export"): "import_export",
    ("GET", "/me/export/{section}.csv"): "import_export",
    ("DELETE", "/me"): "import_export",
}


def _me_routes():
    from app.main import app

    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path == "/me" or path.startswith("/me/")
        for method in operations
    }


def test_every_me_route_has_its_group():
    # A new /me route must be classified here deliberately, never left uncovered.
    assert _me_routes() == set(ME_GROUPS)
    for (method, path), group in ME_GROUPS.items():
        concrete = path.replace("{entry_id}", "7").replace("{section}", "collection")
        assert classify_route(concrete, method) == group, (method, path)
    assert classify_route("/me/", "DELETE") == "import_export"
    assert classify_route("/me/export/watchlist.csv", "GET") == "import_export"


def test_me_writes_are_stricter_than_reads_and_account_calls_strictest():
    def per_minute(group):
        cfg = group_config(group)
        return cfg.limit / (cfg.window_seconds / 60)

    assert per_minute("collection_write") < per_minute("public_read")
    assert per_minute("import_export") < per_minute("collection_write")


def _bearer(sub):
    return {"Authorization": f"Bearer {make_bearer_token(google_sub=sub, email=f'{sub}@example.com')}"}


def test_me_limits_are_per_collector_not_per_ip(client, db_session, monkeypatch):
    # Every collector reaches /me through the website's server, so one IP
    # bucket would let one collector exhaust the limit for everyone.
    monkeypatch.setenv(FLAG, "true")
    monkeypatch.setattr(settings, "RATE_LIMIT_COLLECTION_WRITE_PER_5M", 2)
    body = {"currency": "JPY"}

    for _ in range(2):
        assert client.put("/me/preferences", json=body, headers=_bearer("user-a")).status_code != 429
    assert client.put("/me/preferences", json=body, headers=_bearer("user-a")).status_code == 429
    # Same IP, another collector: its own bucket.
    assert client.put("/me/preferences", json=body, headers=_bearer("user-b")).status_code != 429


def test_me_reads_do_not_spend_the_shared_public_bucket(client, db_session, monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    monkeypatch.setattr(settings, "RATE_LIMIT_PUBLIC_READ_PER_5M", 2)

    for _ in range(3):
        client.get("/me/profile", headers=_bearer("user-a"))
    assert client.get("/me/profile", headers=_bearer("user-a")).status_code == 429
    assert client.get("/cards").status_code == 200


def test_me_export_and_delete_share_the_strictest_group(client, db_session, monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    monkeypatch.setattr(settings, "RATE_LIMIT_IMPORT_EXPORT_PER_10M", 2)

    assert client.get("/me/export", headers=_bearer("user-a")).status_code == 200
    assert client.get("/me/export/collection.csv", headers=_bearer("user-a")).status_code == 200
    response = client.delete("/me?confirm=delete%20my%20account", headers=_bearer("user-a"))
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    # The account still exists: the 429 came before the route ran.
    assert client.get("/me/profile", headers=_bearer("user-a")).status_code == 200


def test_me_request_without_a_valid_token_is_keyed_by_ip(client, db_session, monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    monkeypatch.setattr(settings, "RATE_LIMIT_COLLECTION_WRITE_PER_5M", 1)
    forged = {"Authorization": "Bearer " + jwt.encode({"sub": "user-a", "email": "a@example.com"}, "wrong", algorithm="HS256")}

    assert client.put("/me/preferences", json={}, headers=forged).status_code == 401
    assert client.put("/me/preferences", json={}, headers={"Authorization": "Bearer junk"}).status_code == 429
    # A forged subject cannot spend (or reach) the real collector's bucket.
    assert client.put("/me/preferences", json={"currency": "JPY"}, headers=_bearer("user-a")).status_code == 200


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


def test_collection_write_rate_limit_returns_429(client, db_session, monkeypatch):
    monkeypatch.setenv(FLAG, "true")
    monkeypatch.setattr(settings, "RATE_LIMIT_COLLECTION_WRITE_PER_5M", 1)

    response = client.post("/me/watchlist", json={})
    assert response.status_code == 422

    response = client.post("/me/watchlist", json={})
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
    assert groups == {"public_read", "collection_write", "admin", "import_export"}


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
