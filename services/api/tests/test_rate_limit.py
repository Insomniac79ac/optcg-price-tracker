import jwt
import pytest

from app.accounts.config import FLAG
import re

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


def test_a_client_header_cannot_name_a_collectors_bucket(client, db_session, monkeypatch):
    import hashlib

    monkeypatch.setenv(FLAG, "true")
    monkeypatch.setattr(settings, "RATE_LIMIT_COLLECTION_WRITE_PER_5M", 1)
    victim_key = "user:" + hashlib.sha256(b"user-a").hexdigest()[:32]

    client_supplied = {"Authorization": "Bearer junk", "X-Real-IP": victim_key}
    client.put("/me/preferences", json={}, headers=client_supplied)
    client.put("/me/preferences", json={}, headers=client_supplied)

    assert client.put("/me/preferences", json={"currency": "JPY"}, headers=_bearer("user-a")).status_code == 200


# --- client key and status counts ---------------------------------------


def _counts():
    status = rate_limit_status()
    return status["platform_header_requests"], status["unverified_requests"], status["mismatch_requests"]


def test_other_forwarding_headers_do_not_change_the_client_key(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_PUBLIC_READ_PER_5M", 2)

    client.get("/cards", headers={"X-Real-IP": "203.0.113.5", "X-Forwarded-For": "198.51.100.1"})
    client.get("/cards", headers={"X-Real-IP": "203.0.113.5", "X-Forwarded-For": "203.0.113.9, 10.0.0.1"})
    third = client.get("/cards", headers={"X-Real-IP": "203.0.113.5", "X-Forwarded-For": "198.51.100.2"})

    assert third.status_code == 429
    assert client.get("/cards", headers={"X-Real-IP": "203.0.113.6"}).status_code == 200


def test_missing_client_header_outside_development_uses_the_shared_unverified_key(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_PUBLIC_READ_PER_5M", 1)

    client.get("/cards", headers={"X-Forwarded-For": "198.51.100.1"})
    second = client.get("/cards", headers={"X-Forwarded-For": "198.51.100.2"})

    assert second.status_code == 429
    assert client.get("/cards", headers={"X-Real-IP": "203.0.113.5"}).status_code == 200


def test_ipv6_addresses_in_one_slash_64_share_a_key(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_PUBLIC_READ_PER_5M", 1)

    client.get("/cards", headers={"X-Real-IP": "2001:db8:1:2::1"})

    assert client.get("/cards", headers={"X-Real-IP": "2001:db8:1:2::99"}).status_code == 429
    assert client.get("/cards", headers={"X-Real-IP": "2001:db8:1:3::1"}).status_code == 200


def test_rate_limit_log_hashes_the_client_key(client, db_session, monkeypatch):
    from app.models import AppLogEvent

    monkeypatch.setattr(settings, "RATE_LIMIT_PUBLIC_READ_PER_5M", 1)
    headers = {"X-Real-IP": "203.0.113.77"}

    client.get("/cards", headers=headers)
    assert client.get("/cards", headers=headers).status_code == 429

    logs = db_session.query(AppLogEvent).filter(AppLogEvent.event_type == "rate_limit").all()
    assert len(logs) == 1
    for event in db_session.query(AppLogEvent).all():
        text = f"{event.message} {event.context_json}"
        assert "203.0.113.77" not in text
        assert "ip:203.0.113.77" not in text
    assert re.search(r"from ip:[0-9a-f]{16}\.", logs[0].message)


def test_unverified_key_is_logged_once_per_window(client, db_session, monkeypatch):
    from app.models import AppLogEvent

    client.get("/cards")
    client.get("/cards")

    logs = (
        db_session.query(AppLogEvent)
        .filter(AppLogEvent.event_type == "rate_limit_unverified_client")
        .all()
    )
    assert len(logs) == 1
    assert "ip:unverified" in logs[0].message


def test_status_counts_a_platform_header_request(client, db_session):
    before = _counts()

    client.get("/cards", headers={"X-Real-IP": "203.0.113.5"})

    after = _counts()
    assert after[0] == before[0] + 1
    assert after[1] == before[1]
    assert after[2] == before[2]


@pytest.mark.parametrize("headers", [{}, {"X-Real-IP": "1.2.3.4:80"}, {"X-Real-IP": "a, b"}])
def test_status_counts_a_shared_unverified_request(client, db_session, headers):
    before = _counts()

    client.get("/cards", headers=headers)

    after = _counts()
    assert after[1] == before[1] + 1
    assert after[0] == before[0]
    assert after[2] == before[2]


def test_status_counts_a_header_mismatch(client, db_session):
    before = _counts()
    client.get("/cards", headers={"X-Real-IP": "203.0.113.5", "X-Forwarded-For": "198.51.100.1"})
    after = _counts()
    assert after[0] == before[0] + 1
    assert after[2] == before[2] + 1

    # Equal parsed addresses with different IPv6 text are not a mismatch.
    client.get(
        "/cards",
        headers={"X-Real-IP": "2001:db8::1", "X-Forwarded-For": "2001:0db8:0:0:0:0:0:1, 10.0.0.1"},
    )
    last = _counts()
    assert last[0] == after[0] + 1
    assert last[2] == after[2]
    assert last[1] == before[1]


def test_status_counts_while_the_limiter_is_disabled(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    before = _counts()

    client.get("/cards", headers={"X-Real-IP": "203.0.113.5"})

    assert _counts()[0] == before[0] + 1


def test_status_does_not_count_an_exempt_path(client, db_session):
    before = _counts()

    client.get("/health")

    assert _counts() == before


def test_status_counts_reset_with_the_limiter(client, db_session):
    client.get("/cards")
    reset_rate_limits()

    assert _counts() == (0, 0, 0)


def test_rate_limit_status_rejects_a_wrong_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    response = TestClient(app).get("/admin/rate-limit/status", headers={"X-Admin-Token": "wrong-token"})
    assert response.status_code == 401


def test_status_counts_contain_no_addresses(client, db_session):
    client.get("/cards", headers={"X-Real-IP": "203.0.113.5", "X-Forwarded-For": "198.51.100.1"})
    client.get("/cards", headers={"X-Real-IP": "2001:db8:1:2::1"})
    client.get("/cards")

    response = client.get("/admin/rate-limit/status", headers={"X-Real-IP": "203.0.113.5"})

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "enabled",
        "windows",
        "started_at",
        "platform_header_requests",
        "unverified_requests",
        "mismatch_requests",
    }
    for window in data["windows"]:
        assert set(window) == {"group", "limit", "window_seconds", "active_keys"}
    for name in ("platform_header_requests", "unverified_requests", "mismatch_requests"):
        assert isinstance(data[name], int)
    from datetime import datetime

    assert datetime.fromisoformat(data["started_at"]).tzinfo is not None
    # The timestamp is the only field with colons; check everything else.
    body = response.text.replace(data["started_at"], "")
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", body)
    assert not re.search(r"[0-9a-fA-F]{1,4}::|::[0-9a-fA-F]{1,4}|(?:[0-9a-fA-F]{1,4}:){2,}[0-9a-fA-F]{1,4}", body)
    assert not re.search(r"[0-9a-f]{32}|[0-9a-f]{64}", body)
