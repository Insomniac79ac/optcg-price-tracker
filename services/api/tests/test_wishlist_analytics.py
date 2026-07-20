from datetime import datetime, timezone

import pytest

from app.models import Card, CollectionItem, PriceObservation, Source, WishlistItem
from app.services import cache as cache_module
from app.settings import settings


@pytest.fixture(autouse=True)
def _cache_memory_backend(monkeypatch):
    """conftest's _cache_disabled_by_default turns caching off for every
    other test - this file explicitly re-enables it (memory backend, so no
    real Redis is needed) to exercise the endpoint's real cache behavior."""
    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "CACHE_BACKEND", "memory")
    cache_module.reset_state_for_tests()
    yield
    cache_module.reset_state_for_tests()


def make_card(db_session, **overrides) -> Card:
    fields = dict(
        card_code="OP01-001", name_en="Monkey D. Luffy", name_jp="モンキー・D・ルフィ",
        set_code="OP01", rarity="L", variant="leader", language="en",
    )
    fields.update(overrides)
    card = Card(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_source(db_session, name: str) -> Source:
    existing = db_session.query(Source).filter_by(name=name).one_or_none()
    if existing is not None:
        return existing
    source = Source(name=name, base_url=f"https://{name}.example.com")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def add_observation(db_session, card, source, *, price_type, price_jpy, **kwargs):
    obs = PriceObservation(
        card_id=card.id, source_id=source.id, price_type=price_type, price_jpy=price_jpy,
        observed_at=kwargs.pop("observed_at", None) or datetime.now(timezone.utc), **kwargs,
    )
    db_session.add(obs)
    db_session.commit()
    return obs


def make_wishlist_item(client, card_id: int, **overrides) -> dict:
    body = {"card_id": card_id}
    body.update(overrides)
    response = client.post("/wishlist", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def by_key(entries: list[dict]) -> dict:
    return {e["key"]: e for e in entries}


def test_analytics_empty_wishlist_works(client, db_session):
    response = client.get("/analytics/wishlist")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {
        "total_items": 0,
        "watching_count": 0,
        "target_hit_count": 0,
        "purchased_count": 0,
        "passed_count": 0,
        "grail_count": 0,
        "high_priority_count": 0,
        "owned_already_count": 0,
        "total_target_budget_jpy": 0,
        "total_max_budget_jpy": 0,
        "total_current_price_jpy": 0,
        "budget_gap_to_target_jpy": 0,
        "budget_gap_to_max_jpy": 0,
        "average_target_price_jpy": 0,
        "median_target_price_jpy": 0,
    }
    for key in (
        "by_priority", "by_status", "by_set", "by_rarity", "by_preferred_source",
        "by_preferred_condition",
    ):
        assert body["breakdowns"][key] == []
    assert body["target_hits"] == []
    for key in (
        "grail_targets", "high_priority_targets", "best_gap_to_target", "largest_budget_items",
        "already_owned",
    ):
        assert body["budget_plan"][key] == []
    assert body["price_coverage"] == {
        "items_with_current_price": 0,
        "items_missing_current_price": 0,
        "coverage_pct": 0.0,
    }


def test_analytics_summary_counts_work(client, db_session):
    card1 = make_card(db_session, card_code="OP01-001")
    card2 = make_card(db_session, card_code="OP01-002")
    card3 = make_card(db_session, card_code="OP01-003")

    make_wishlist_item(client, card1.id, priority="grail", target_buy_price_jpy=1000)
    make_wishlist_item(client, card2.id, priority="high", target_buy_price_jpy=2000)
    item3 = make_wishlist_item(client, card3.id, priority="medium")
    client.patch(f"/wishlist/{item3['id']}", json={"status": "passed"})

    response = client.get("/analytics/wishlist")

    summary = response.json()["summary"]
    assert summary["total_items"] == 3
    assert summary["watching_count"] == 2
    assert summary["passed_count"] == 1
    assert summary["grail_count"] == 1
    assert summary["high_priority_count"] == 1


def test_removed_excluded_by_default(client, db_session):
    card = make_card(db_session)
    item = make_wishlist_item(client, card.id)
    assert client.delete(f"/wishlist/{item['id']}").status_code == 200

    default_response = client.get("/analytics/wishlist")
    assert default_response.json()["summary"]["total_items"] == 0

    included_response = client.get("/analytics/wishlist", params={"include_removed": "true"})
    body = included_response.json()
    assert body["summary"]["total_items"] == 1
    assert "removed" in by_key(body["breakdowns"]["by_status"])


def test_purchased_excluded_by_default(client, db_session):
    card = make_card(db_session)
    item = make_wishlist_item(client, card.id)
    assert client.patch(f"/wishlist/{item['id']}", json={"status": "purchased"}).status_code == 200

    default_response = client.get("/analytics/wishlist")
    assert default_response.json()["summary"]["total_items"] == 0

    included_response = client.get("/analytics/wishlist", params={"include_purchased": "true"})
    body = included_response.json()
    assert body["summary"]["total_items"] == 1
    assert body["summary"]["purchased_count"] == 1


def test_priority_breakdown_works(client, db_session):
    card1 = make_card(db_session, card_code="OP01-001")
    card2 = make_card(db_session, card_code="OP01-002")
    make_wishlist_item(client, card1.id, priority="grail", target_buy_price_jpy=1000)
    make_wishlist_item(client, card2.id, priority="grail", target_buy_price_jpy=3000)

    response = client.get("/analytics/wishlist")

    breakdown = by_key(response.json()["breakdowns"]["by_priority"])
    assert breakdown["grail"]["label"] == "Grail"
    assert breakdown["grail"]["item_count"] == 2
    assert breakdown["grail"]["target_budget_jpy"] == 4000


def test_status_breakdown_works(client, db_session):
    card1 = make_card(db_session, card_code="OP01-001")
    card2 = make_card(db_session, card_code="OP01-002")
    make_wishlist_item(client, card1.id)
    item2 = make_wishlist_item(client, card2.id)
    client.patch(f"/wishlist/{item2['id']}", json={"status": "passed"})

    response = client.get("/analytics/wishlist")

    breakdown = by_key(response.json()["breakdowns"]["by_status"])
    assert breakdown["watching"]["item_count"] == 1
    assert breakdown["watching"]["label"] == "Watching"
    assert breakdown["passed"]["item_count"] == 1
    assert breakdown["passed"]["label"] == "Passed"


def test_set_breakdown_works(client, db_session):
    card1 = make_card(db_session, card_code="OP01-001", set_code="OP01")
    card2 = make_card(db_session, card_code="OP02-001", set_code="OP02")
    make_wishlist_item(client, card1.id, target_buy_price_jpy=1000)
    make_wishlist_item(client, card2.id, target_buy_price_jpy=2000)

    response = client.get("/analytics/wishlist")

    breakdown = by_key(response.json()["breakdowns"]["by_set"])
    assert set(breakdown.keys()) == {"OP01", "OP02"}
    assert breakdown["OP01"]["target_budget_jpy"] == 1000
    assert breakdown["OP02"]["target_budget_jpy"] == 2000


def test_target_budget_calculation_uses_remaining_quantity(client, db_session):
    card = make_card(db_session)
    item = make_wishlist_item(
        client, card.id, target_buy_price_jpy=1000, desired_quantity=3,
    )
    db_item = db_session.get(WishlistItem, item["id"])
    db_item.acquired_quantity = 1
    db_session.commit()

    response = client.get("/analytics/wishlist")

    # remaining_quantity = max(3 - 1, 0) = 2 -> target budget = 1000 * 2
    assert response.json()["summary"]["total_target_budget_jpy"] == 2000


def test_target_hit_items_returned(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=900)
    make_wishlist_item(client, card.id, target_buy_price_jpy=1000)

    response = client.get("/analytics/wishlist")

    body = response.json()
    assert body["summary"]["target_hit_count"] == 1
    assert len(body["target_hits"]) == 1
    hit = body["target_hits"][0]
    assert hit["target_hit"] is True
    assert hit["preferred_current_price_jpy"] == 900
    assert hit["gap_to_target_jpy"] == -100


def test_price_coverage_works(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card1 = make_card(db_session, card_code="OP01-001")
    card2 = make_card(db_session, card_code="OP01-002")
    add_observation(db_session, card1, snkrdunk, price_type="floor", price_jpy=500)
    make_wishlist_item(client, card1.id)
    make_wishlist_item(client, card2.id)  # no price observation at all

    response = client.get("/analytics/wishlist")

    coverage = response.json()["price_coverage"]
    assert coverage["items_with_current_price"] == 1
    assert coverage["items_missing_current_price"] == 1
    assert coverage["coverage_pct"] == 50.0


def test_budget_plan_sections_populate_correctly(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    grail_card = make_card(db_session, card_code="OP01-001")
    high_card = make_card(db_session, card_code="OP01-002")
    owned_card = make_card(db_session, card_code="OP01-003")

    make_wishlist_item(client, grail_card.id, priority="grail", target_buy_price_jpy=5000)
    make_wishlist_item(client, high_card.id, priority="high", target_buy_price_jpy=3000)

    owned_item = make_wishlist_item(client, owned_card.id, target_buy_price_jpy=1000)
    db_session.add(
        CollectionItem(user_id=1, card_id=owned_card.id, quantity=2, status="hold")
    )
    db_session.commit()

    add_observation(db_session, grail_card, snkrdunk, price_type="floor", price_jpy=4900)

    response = client.get("/analytics/wishlist")
    body = response.json()

    assert [t["card_code"] for t in body["budget_plan"]["grail_targets"]] == ["OP01-001"]
    assert [t["card_code"] for t in body["budget_plan"]["high_priority_targets"]] == ["OP01-002"]
    assert body["budget_plan"]["largest_budget_items"][0]["card_code"] == "OP01-001"
    assert [t["card_code"] for t in body["budget_plan"]["already_owned"]] == ["OP01-003"]
    assert body["budget_plan"]["already_owned"][0]["owned_quantity"] == 2
    assert body["budget_plan"]["best_gap_to_target"][0]["card_code"] == "OP01-001"
    assert owned_item["card_id"] == owned_card.id


def test_cache_invalidates_after_wishlist_write(client, db_session):
    card = make_card(db_session)

    first = client.get("/analytics/wishlist")
    assert first.headers["X-Cache"] == "MISS"
    second = client.get("/analytics/wishlist")
    assert second.headers["X-Cache"] == "HIT"

    response = client.post("/wishlist", json={"card_id": card.id})
    assert response.status_code == 201

    third = client.get("/analytics/wishlist")
    assert third.headers["X-Cache"] == "MISS"
    assert third.json()["summary"]["total_items"] == 1
