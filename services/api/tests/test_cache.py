import pytest

from app.models import Card, CollectionItem, GradingSubmission
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


def make_card(db_session, **overrides) -> Card:
    fields = dict(
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        name_jp="モンキー・D・ルフィ",
        set_code="OP01",
        rarity="L",
        variant="leader",
        language="en",
    )
    fields.update(overrides)
    card = Card(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_item(db_session, card: Card, **overrides) -> CollectionItem:
    fields = dict(card_id=card.id, quantity=1, user_id=1)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


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


# --- endpoint caching (HIT/MISS headers) -----------------------------------


def test_dashboard_overview_returns_hit_on_second_request(client, db_session):
    first = client.get("/dashboard/overview")
    assert first.status_code == 200
    assert first.headers["X-Cache"] == "MISS"

    second = client.get("/dashboard/overview")
    assert second.status_code == 200
    assert second.headers["X-Cache"] == "HIT"
    assert second.json() == first.json()


def test_collection_valuation_cache_key_includes_valuation_mode(client, db_session):
    raw = client.get("/collection/valuation", params={"valuation_mode": "raw_market"})
    assert raw.headers["X-Cache"] == "MISS"

    graded = client.get("/collection/valuation", params={"valuation_mode": "graded_adjusted"})
    assert graded.headers["X-Cache"] == "MISS"

    raw_again = client.get("/collection/valuation", params={"valuation_mode": "raw_market"})
    assert raw_again.headers["X-Cache"] == "HIT"

    graded_again = client.get("/collection/valuation", params={"valuation_mode": "graded_adjusted"})
    assert graded_again.headers["X-Cache"] == "HIT"


def test_market_opportunities_cache_key_includes_filters(client, db_session):
    first = client.get("/market/opportunities", params={"category": "buy"})
    assert first.headers["X-Cache"] == "MISS"

    different_filter = client.get("/market/opportunities", params={"category": "sell"})
    assert different_filter.headers["X-Cache"] == "MISS"

    repeat = client.get("/market/opportunities", params={"category": "buy"})
    assert repeat.headers["X-Cache"] == "HIT"


# --- invalidation ------------------------------------------------------


def test_collection_write_invalidates_valuation_cache(client, db_session):
    card = make_card(db_session)

    first = client.get("/collection/valuation")
    assert first.headers["X-Cache"] == "MISS"
    second = client.get("/collection/valuation")
    assert second.headers["X-Cache"] == "HIT"

    response = client.post(
        "/collection",
        json={"card_id": card.id, "quantity": 1, "status": "hold"},
    )
    assert response.status_code == 201

    third = client.get("/collection/valuation")
    assert third.headers["X-Cache"] == "MISS"


def test_wishlist_write_invalidates_wishlist_and_market_cache(client, db_session):
    card = make_card(db_session)

    first = client.get("/wishlist/summary")
    assert first.headers["X-Cache"] == "MISS"
    second = client.get("/wishlist/summary")
    assert second.headers["X-Cache"] == "HIT"

    opp_first = client.get("/market/opportunities")
    assert opp_first.headers["X-Cache"] == "MISS"
    opp_second = client.get("/market/opportunities")
    assert opp_second.headers["X-Cache"] == "HIT"

    response = client.post(
        "/wishlist",
        json={"card_id": card.id, "priority": "medium", "status": "active"},
    )
    assert response.status_code == 201

    third = client.get("/wishlist/summary")
    assert third.headers["X-Cache"] == "MISS"

    opp_third = client.get("/market/opportunities")
    assert opp_third.headers["X-Cache"] == "MISS"


def test_grading_write_invalidates_valuation_cache(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)

    first = client.get("/collection/valuation")
    assert first.headers["X-Cache"] == "MISS"
    second = client.get("/collection/valuation")
    assert second.headers["X-Cache"] == "HIT"

    response = client.post(
        "/grading/submissions",
        json={
            "collection_item_id": item.id,
            "grading_company": "PSA",
            "submission_status": "submitted",
        },
    )
    assert response.status_code == 201

    third = client.get("/collection/valuation")
    assert third.headers["X-Cache"] == "MISS"


def test_price_refresh_invalidates_market_and_collection_cache(monkeypatch):
    """trigger_price_refresh runs in the API process (see
    app.services.refresh_trigger) even though the actual scraping happens in
    the worker over Celery - this monkeypatches the Celery client so the
    test never attempts a real broker round trip, and just verifies the
    cache invalidation that runs once a real (non-dry-run, non-failed)
    result comes back."""
    from app.services import refresh_trigger

    cache_module.set_cache("dashboard:overview:1", {"a": 1}, 60)
    cache_module.set_cache("market_opportunities:x", {"a": 1}, 60)
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

    assert cache_module.get_cache("dashboard:overview:1") is None
    assert cache_module.get_cache("market_opportunities:x") is None
    assert cache_module.get_cache("collection_valuation:1:raw_market") is None


def test_price_refresh_dry_run_does_not_invalidate(monkeypatch):
    from app.services import refresh_trigger

    cache_module.set_cache("dashboard:overview:1", {"a": 1}, 60)

    class FakeAsyncResult:
        id = "fake-task-id"

        def get(self, timeout):
            return {"id": 1, "status": "completed"}

    class FakeCeleryClient:
        def send_task(self, name, kwargs):
            return FakeAsyncResult()

    monkeypatch.setattr(refresh_trigger, "_celery_client", lambda: FakeCeleryClient())

    refresh_trigger.trigger_price_refresh(source="all", limit=10, dry_run=True)

    assert cache_module.get_cache("dashboard:overview:1") == {"a": 1}


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
