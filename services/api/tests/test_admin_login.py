"""Router-level tests for POST /auth/admin/verify (app.api.admin_login).
Throttle state (app.core.admin_login_throttle) is exercised against the
same in-memory FakeRedis as tests/test_admin_login_throttle.py rather than
mocked away entirely, so the rate-limiting/lockout tests here cover the
real integration, not just that *some* function was called.
"""

from __future__ import annotations

import time

import pytest
import redis
from fastapi.testclient import TestClient

from app.api import admin_login as admin_login_module
from app.core import admin_login_throttle as throttle
from app.core.admin_password import hash_password
from app.main import app
from app.settings import settings

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "correct horse battery staple long enough"


class FakeRedis:
    """Same minimal fake as tests/test_admin_login_throttle.py - see that
    file for why there's no shared fakeredis dependency yet."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}

    def _live(self, key: str):
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and expires_at <= time.time():
            del self._store[key]
            return None
        return value, expires_at

    def ttl(self, key: str) -> int:
        entry = self._live(key)
        if entry is None:
            return -2
        _value, expires_at = entry
        if expires_at is None:
            return -1
        return max(0, int(expires_at - time.time()) + 1)

    def incr(self, key: str) -> int:
        entry = self._live(key)
        current = int(entry[0]) if entry else 0
        expires_at = entry[1] if entry else None
        new_value = current + 1
        self._store[key] = (str(new_value), expires_at)
        return new_value

    def expire(self, key: str, seconds: int) -> bool:
        entry = self._live(key)
        if entry is None:
            return False
        value, _ = entry
        self._store[key] = (value, time.time() + seconds)
        return True

    def setex(self, key: str, seconds: int, value: str) -> None:
        self._store[key] = (str(value), time.time() + seconds)

    def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                count += 1
        return count


@pytest.fixture()
def raw_client(db_session):
    # db_session isn't used directly - it's a dependency purely for its
    # side effect of creating tables (including app_log_events) on the
    # shared in-memory sqlite engine, same as tests/test_admin_auth.py's
    # raw_client fixture, so record_app_log's own DB writes don't fail.
    return TestClient(app)


@pytest.fixture(autouse=True)
def _throttle_fake_redis(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(throttle, "_get_client", lambda: client)
    throttle.reset_state_for_tests()
    yield
    throttle.reset_state_for_tests()


@pytest.fixture(autouse=True)
def _admin_login_configured(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "ADMIN_LOGIN_EMAIL", ADMIN_EMAIL)
    monkeypatch.setattr(settings, "ADMIN_LOGIN_PASSWORD_HASH", hash_password(ADMIN_PASSWORD))
    monkeypatch.setattr(settings, "ADMIN_LOGIN_MAX_ATTEMPTS", 5)
    monkeypatch.setattr(settings, "ADMIN_LOGIN_WINDOW_SECONDS", 900)
    monkeypatch.setattr(settings, "ADMIN_LOGIN_LOCKOUT_SECONDS", 1800)


@pytest.fixture()
def logged_events(monkeypatch):
    events: list[dict] = []

    def _capture(level, service, event_type, message, *, context=None, **kwargs):
        events.append(
            {"level": level, "service": service, "event_type": event_type, "message": message, "context": context}
        )

    monkeypatch.setattr(admin_login_module, "record_app_log", _capture)
    return events


def _login(raw_client, email=ADMIN_EMAIL, password=ADMIN_PASSWORD, ip=None):
    headers = {"X-Forwarded-For": ip} if ip else None
    return raw_client.post(
        "/auth/admin/verify", json={"email": email, "password": password}, headers=headers
    )


# --- disabled / unconfigured ------------------------------------------------


def test_disabled_returns_generic_unavailable(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_LOGIN_ENABLED", False)

    response = _login(raw_client)

    assert response.status_code == 503
    assert response.json() == {"detail": "Admin login is not available."}


def test_missing_email_config_returns_generic_unavailable(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_LOGIN_EMAIL", None)

    response = _login(raw_client)

    assert response.status_code == 503
    assert response.json() == {"detail": "Admin login is not available."}


def test_missing_hash_config_returns_generic_unavailable(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_LOGIN_PASSWORD_HASH", None)

    response = _login(raw_client)

    assert response.status_code == 503
    assert response.json() == {"detail": "Admin login is not available."}


# --- valid / invalid credentials --------------------------------------------


def test_valid_credentials_returns_minimal_identity(raw_client):
    response = _login(raw_client)

    assert response.status_code == 200
    assert response.json() == {"id": "staging-admin", "email": ADMIN_EMAIL, "role": "admin"}


def test_invalid_email_returns_generic_401(raw_client):
    response = _login(raw_client, email="not-the-admin@example.com")

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password."}


def test_invalid_password_returns_generic_401(raw_client):
    response = _login(raw_client, password="wrong password entirely")

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password."}


def test_unknown_and_wrong_password_responses_are_identical(raw_client):
    unknown_email_response = _login(raw_client, email="nope@example.com")
    wrong_password_response = _login(raw_client, password="totally wrong")

    assert unknown_email_response.status_code == wrong_password_response.status_code == 401
    assert unknown_email_response.json() == wrong_password_response.json()


def test_login_ignores_caller_supplied_x_admin_token(raw_client):
    response = raw_client.post(
        "/auth/admin/verify",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        headers={"X-Admin-Token": "some-random-value-that-is-not-configured"},
    )

    assert response.status_code == 200


def test_login_success_grants_no_other_admin_route_access(raw_client):
    login_response = _login(raw_client)
    assert login_response.status_code == 200

    other_admin_response = raw_client.get("/admin/system-check")

    assert other_admin_response.status_code == 401


# --- throttling --------------------------------------------------------


def test_account_locked_after_max_attempts(raw_client):
    for _ in range(5):
        assert _login(raw_client, password="wrong").status_code == 401

    response = _login(raw_client)  # correct credentials, but now locked out

    assert response.status_code == 429
    assert response.json() == {"detail": "Too many attempts. Try again later."}
    assert "Retry-After" in response.headers


def test_lockout_expires_after_window(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_LOGIN_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "ADMIN_LOGIN_LOCKOUT_SECONDS", 1)
    for _ in range(2):
        _login(raw_client, password="wrong")
    assert _login(raw_client).status_code == 429

    time.sleep(1.2)

    assert _login(raw_client).status_code == 200


def test_successful_login_clears_account_failure_counter(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_LOGIN_MAX_ATTEMPTS", 3)
    # Distinct IPs pre/post-clear - the IP counter is deliberately NOT
    # cleared by a successful login (only the account counter is), so
    # reusing one IP across both halves would trip the IP's own threshold
    # and mask what this test checks: the account counter specifically.
    _login(raw_client, password="wrong", ip="1.1.1.1")
    _login(raw_client, password="wrong", ip="1.1.1.1")

    assert _login(raw_client, ip="1.1.1.1").status_code == 200  # succeeds, clears the counter

    # Two more failures shouldn't lock immediately, since the counter reset.
    _login(raw_client, password="wrong", ip="2.2.2.2")
    response = _login(raw_client, password="wrong", ip="2.2.2.2")
    assert response.status_code == 401  # still just "invalid", not 429


def test_redis_failure_returns_generic_unavailable(raw_client, monkeypatch):
    def _raise(*args, **kwargs):
        raise redis.ConnectionError("simulated outage")

    monkeypatch.setattr(admin_login_module, "check_locked", _raise)

    response = _login(raw_client)

    assert response.status_code == 503
    assert response.json() == {"detail": "Admin login is not available."}


# --- secret leakage ------------------------------------------------------


def test_response_never_contains_password_hash(raw_client, monkeypatch):
    real_hash = hash_password(ADMIN_PASSWORD)
    monkeypatch.setattr(settings, "ADMIN_LOGIN_PASSWORD_HASH", real_hash)

    response = _login(raw_client)

    assert real_hash not in response.text
    assert "$argon2id$" not in response.text


def test_response_never_contains_admin_token(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "super-secret-admin-token-value")

    response = _login(raw_client)

    assert "super-secret-admin-token-value" not in response.text


def test_logs_never_contain_password_or_hash(raw_client, logged_events):
    _login(raw_client, password="wrong")
    _login(raw_client)

    dumped = str(logged_events)
    assert ADMIN_PASSWORD not in dumped
    assert "wrong" not in dumped
    assert "$argon2id$" not in dumped


def test_logs_never_contain_raw_email(raw_client, logged_events):
    _login(raw_client)

    dumped = str(logged_events)
    assert ADMIN_EMAIL not in dumped


def test_success_logs_admin_login_success_event(raw_client, logged_events):
    _login(raw_client)

    event_types = [e["event_type"] for e in logged_events]
    assert "admin_login_success" in event_types


def test_failure_logs_admin_login_failure_event(raw_client, logged_events):
    _login(raw_client, password="wrong")

    event_types = [e["event_type"] for e in logged_events]
    assert "admin_login_failure" in event_types


def test_throttled_logs_admin_login_throttled_event(raw_client, logged_events):
    for _ in range(5):
        _login(raw_client, password="wrong")
    logged_events.clear()

    _login(raw_client)

    event_types = [e["event_type"] for e in logged_events]
    assert "admin_login_throttled" in event_types


# --- GET /auth/admin/status --------------------------------------------


def test_status_reports_enabled_when_configured(raw_client):
    response = raw_client.get("/auth/admin/status")

    assert response.status_code == 200
    assert response.json() == {"enabled": True}


def test_status_reports_disabled_when_flag_off(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_LOGIN_ENABLED", False)

    response = raw_client.get("/auth/admin/status")

    assert response.json() == {"enabled": False}


def test_status_reports_disabled_when_email_missing(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_LOGIN_EMAIL", None)

    response = raw_client.get("/auth/admin/status")

    assert response.json() == {"enabled": False}


def test_status_reveals_no_config_details(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_LOGIN_EMAIL", None)

    response = raw_client.get("/auth/admin/status")

    assert set(response.json().keys()) == {"enabled"}


def test_status_does_not_require_x_admin_token(raw_client):
    response = raw_client.get("/auth/admin/status")

    assert response.status_code == 200
