import pytest

from app.services import cache as cache_module
from app.settings import settings


@pytest.fixture(autouse=True)
def _cache_memory_backend(monkeypatch):
    """conftest's _cache_disabled_by_default turns caching off for every
    other test - this file explicitly re-enables it (memory backend, so no
    real Redis is needed) to exercise real cache behavior."""
    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "CACHE_BACKEND", "memory")
    cache_module.reset_state_for_tests()
    yield
    cache_module.reset_state_for_tests()


# --- cache service unit tests ----------------------------------------------


def test_set_get_cache_roundtrip():
    cache_module.set_cache("k1", {"a": 1}, 60)
    assert cache_module.get_cache("k1") == {"a": 1}


def test_get_cache_miss_returns_none():
    assert cache_module.get_cache("does-not-exist") is None


def test_delete_cache_removes_key():
    cache_module.set_cache("k2", {"a": 1}, 60)
    cache_module.delete_cache("k2")
    assert cache_module.get_cache("k2") is None


def test_delete_cache_prefix_removes_matching_keys_only():
    cache_module.set_cache("dashboard:overview:1", {"a": 1}, 60)
    cache_module.set_cache("dashboard:overview:2", {"a": 2}, 60)
    cache_module.set_cache("wishlist_summary:1", {"a": 3}, 60)

    deleted = cache_module.delete_cache_prefix("dashboard")

    assert deleted == 2
    assert cache_module.get_cache("dashboard:overview:1") is None
    assert cache_module.get_cache("dashboard:overview:2") is None
    assert cache_module.get_cache("wishlist_summary:1") == {"a": 3}


def test_get_or_set_cache_reports_hit_and_miss():
    calls = []

    def factory():
        calls.append(1)
        return {"computed": True}

    value1, hit1 = cache_module.get_or_set_cache("k3", 60, factory)
    value2, hit2 = cache_module.get_or_set_cache("k3", 60, factory)

    assert value1 == {"computed": True}
    assert value2 == {"computed": True}
    assert hit1 is False
    assert hit2 is True
    assert len(calls) == 1


def test_cache_disabled_never_stores(monkeypatch):
    monkeypatch.setattr(settings, "CACHE_ENABLED", False)
    cache_module.set_cache("k4", {"a": 1}, 60)
    assert cache_module.get_cache("k4") is None


def test_backend_failure_does_not_crash(monkeypatch):
    """A backend whose get/set explicitly raise must never propagate - the
    cache degrades to uncached rather than crashing the caller."""

    class ExplodingBackend:
        def get(self, key):
            raise RuntimeError("boom")

        def set(self, key, value, ttl_seconds):
            raise RuntimeError("boom")

        def delete(self, key):
            raise RuntimeError("boom")

        def delete_prefix(self, prefix):
            raise RuntimeError("boom")

        def count_keys(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(cache_module, "_active_backend", lambda: ExplodingBackend())

    assert cache_module.get_cache("k5") is None
    cache_module.set_cache("k5", {"a": 1}, 60)  # must not raise
    cache_module.delete_cache("k5")  # must not raise
    assert cache_module.delete_cache_prefix("k5") == 0
    assert cache_module.cache_stats()["keys"] == 0


def test_serialization_failure_does_not_crash():
    """An unserializable value (e.g. a raw object) is a no-op set, not a
    crash - factory()'s return value is still what the caller gets back."""
    value, hit = cache_module.get_or_set_cache("k6", 60, lambda: {"fn": lambda: None})
    assert hit is False
    assert value == {"fn": value["fn"]}
    # Not cached - a second call recomputes rather than hitting a broken entry.
    assert cache_module.get_cache("k6") is None


# --- invalidation ------------------------------------------------------
# The legacy collection, wishlist and grading endpoints (and their HIT/MISS
# tests) were removed in Collector v1 S8.


def test_price_refresh_invalidates_collection_cache(monkeypatch):
    """trigger_price_refresh runs in the API process (see
    app.services.refresh_trigger) even though the actual scraping happens in
    the worker over Celery - this monkeypatches the Celery client so the
    test never attempts a real broker round trip, and just verifies the
    cache invalidation that runs once a real (non-dry-run, non-failed)
    result comes back."""
    from app.services import refresh_trigger

    cache_module.set_cache("collection_valuation:1:raw_market", {"a": 1}, 60)

    class FakeAsyncResult:
        id = "fake-task-id"

        def get(self, timeout):
            return {"id": 1, "status": "completed"}

    class FakeCeleryClient:
        def send_task(self, name, kwargs):
            return FakeAsyncResult()

    monkeypatch.setattr(refresh_trigger, "_celery_client", lambda: FakeCeleryClient())

    refresh_trigger.trigger_price_refresh(source="all", limit=10, dry_run=False)

    assert cache_module.get_cache("collection_valuation:1:raw_market") is None


def test_price_refresh_dry_run_does_not_invalidate(monkeypatch):
    from app.services import refresh_trigger

    cache_module.set_cache("collection_valuation:1:raw_market", {"a": 1}, 60)

    class FakeAsyncResult:
        id = "fake-task-id"

        def get(self, timeout):
            return {"id": 1, "status": "completed"}

    class FakeCeleryClient:
        def send_task(self, name, kwargs):
            return FakeAsyncResult()

    monkeypatch.setattr(refresh_trigger, "_celery_client", lambda: FakeCeleryClient())

    refresh_trigger.trigger_price_refresh(source="all", limit=10, dry_run=True)

    assert cache_module.get_cache("collection_valuation:1:raw_market") == {"a": 1}


# --- admin cache endpoints --------------------------------------------


def test_cache_status_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    raw_client = TestClient(app)
    response = raw_client.get("/admin/cache/status")
    assert response.status_code == 401


def test_cache_clear_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    raw_client = TestClient(app)
    response = raw_client.post("/admin/cache/clear", json={"confirm": "CLEAR"})
    assert response.status_code == 401


def test_cache_clear_requires_confirm_clear(client, db_session):
    response = client.post("/admin/cache/clear", json={"confirm": "nope"})
    assert response.status_code == 400


def test_cache_clear_clears_matching_prefix(client, db_session):
    cache_module.set_cache("dashboard:overview:1", {"a": 1}, 60)
    cache_module.set_cache("wishlist_summary:1", {"a": 2}, 60)

    response = client.post("/admin/cache/clear", json={"prefix": "dashboard", "confirm": "CLEAR"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["deleted_count"] == 1

    assert cache_module.get_cache("dashboard:overview:1") is None
    assert cache_module.get_cache("wishlist_summary:1") == {"a": 2}


def test_cache_status_endpoint_shape(client, db_session):
    response = client.get("/admin/cache/status")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["backend"] == "memory"
    assert set(body["stats"].keys()) == {"keys", "hits", "misses"}
    assert set(body["ttl"].keys()) == {"dashboard", "market", "collection"}


# --- system check -------------------------------------------------------


def test_system_check_warns_when_redis_unavailable_and_cache_enabled(monkeypatch):
    from app.services import system_check as system_check_module

    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "CACHE_BACKEND", "redis")
    monkeypatch.setattr(system_check_module, "redis_ping", lambda: False)

    result = system_check_module._check_cache_backend(None)
    assert result.status == "warning"


def test_system_check_passes_when_redis_reachable(monkeypatch):
    from app.services import system_check as system_check_module

    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "CACHE_BACKEND", "redis")
    monkeypatch.setattr(system_check_module, "redis_ping", lambda: True)

    result = system_check_module._check_cache_backend(None)
    assert result.status == "pass"
