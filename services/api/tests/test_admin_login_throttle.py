"""Unit tests for app.core.admin_login_throttle against a minimal in-memory
fake of the redis-py client interface it uses (ttl/incr/expire/setex/
delete) - there's no fakeredis dependency or shared Redis test fixture in
this repo yet, so this fake is scoped to exactly the methods the module
calls, with real wall-clock TTL semantics (not a mocked clock) so the
lockout-expiry test exercises the real expiry path, not a stand-in for it.
"""

from __future__ import annotations

import time

import pytest
import redis

from app.core import admin_login_throttle as throttle
from app.settings import settings


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}

    def _live(self, key: str) -> tuple[str, float | None] | None:
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


class ExplodingRedis:
    def __getattr__(self, name):
        def _raise(*args, **kwargs):
            raise redis.ConnectionError("simulated Redis outage")

        return _raise


@pytest.fixture(autouse=True)
def _reset_throttle_state():
    throttle.reset_state_for_tests()
    yield
    throttle.reset_state_for_tests()


@pytest.fixture()
def fake_client(monkeypatch):
    client = FakeRedis()
    monkeypatch.setattr(throttle, "_get_client", lambda: client)
    return client


def test_not_locked_before_threshold(fake_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_LOGIN_MAX_ATTEMPTS", 5)
    for _ in range(4):
        throttle.record_failure("admin@example.com", "1.2.3.4")

    status = throttle.check_locked("admin@example.com", "1.2.3.4")

    assert status.locked is False


def test_locks_account_at_threshold(fake_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_LOGIN_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "ADMIN_LOGIN_LOCKOUT_SECONDS", 1800)
    for _ in range(3):
        throttle.record_failure("admin@example.com", "1.2.3.4")

    status = throttle.check_locked("admin@example.com", "1.2.3.4")

    assert status.locked is True
    assert status.retry_after_seconds > 0


def test_account_lock_effective_even_if_ip_changes(fake_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_LOGIN_MAX_ATTEMPTS", 3)
    for ip in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
        throttle.record_failure("admin@example.com", ip)

    status = throttle.check_locked("admin@example.com", "9.9.9.9")

    assert status.locked is True


def test_ip_lock_independent_of_account(fake_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_LOGIN_MAX_ATTEMPTS", 3)
    for email in ("a@example.com", "b@example.com", "c@example.com"):
        throttle.record_failure(email, "5.5.5.5")

    status = throttle.check_locked("unrelated@example.com", "5.5.5.5")

    assert status.locked is True


def test_lockout_expires_after_window(fake_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_LOGIN_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "ADMIN_LOGIN_LOCKOUT_SECONDS", 1)
    for _ in range(2):
        throttle.record_failure("admin@example.com", "1.2.3.4")
    assert throttle.check_locked("admin@example.com", "1.2.3.4").locked is True

    time.sleep(1.2)

    assert throttle.check_locked("admin@example.com", "1.2.3.4").locked is False


def test_successful_login_clears_account_failure_counter(fake_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_LOGIN_MAX_ATTEMPTS", 3)
    # Different IPs for the pre/post-clear failures - the IP counter is
    # deliberately NOT cleared by clear_account_failures (see
    # test_clear_account_failures_does_not_clear_ip_counter below), so
    # reusing one IP across both halves of this test would trip the IP's
    # own threshold and mask what this test is actually checking: the
    # account counter specifically.
    throttle.record_failure("admin@example.com", "1.1.1.1")
    throttle.record_failure("admin@example.com", "1.1.1.1")

    throttle.clear_account_failures("admin@example.com")

    # One more failure after clearing should not immediately lock (counter
    # restarted from zero, not resumed at 2).
    throttle.record_failure("admin@example.com", "2.2.2.2")
    assert throttle.check_locked("admin@example.com", "2.2.2.2").locked is False


def test_clear_account_failures_does_not_clear_ip_counter(fake_client, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_LOGIN_MAX_ATTEMPTS", 2)
    throttle.record_failure("admin@example.com", "1.2.3.4")
    throttle.record_failure("other@example.com", "1.2.3.4")
    assert throttle.check_locked("admin@example.com", "1.2.3.4").locked is True

    throttle.clear_account_failures("admin@example.com")

    # The IP itself is still locked (from the two distinct-email failures),
    # even though the admin@example.com account counter was just cleared.
    assert throttle.check_locked("someone-else@example.com", "1.2.3.4").locked is True


def test_redis_failure_propagates_from_check_locked(monkeypatch):
    monkeypatch.setattr(throttle, "_get_client", lambda: ExplodingRedis())

    with pytest.raises(redis.RedisError):
        throttle.check_locked("admin@example.com", "1.2.3.4")


def test_redis_failure_propagates_from_record_failure(monkeypatch):
    monkeypatch.setattr(throttle, "_get_client", lambda: ExplodingRedis())

    with pytest.raises(redis.RedisError):
        throttle.record_failure("admin@example.com", "1.2.3.4")


def test_redis_failure_propagates_from_clear_account_failures(monkeypatch):
    monkeypatch.setattr(throttle, "_get_client", lambda: ExplodingRedis())

    with pytest.raises(redis.RedisError):
        throttle.clear_account_failures("admin@example.com")
