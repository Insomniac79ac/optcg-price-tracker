import statistics
from datetime import datetime, timezone

import pytest

from app.models import (
    Card,
    CollectionItem,
    CollectorGroup,
    CollectorTag,
    GradingSubmission,
    PriceObservation,
    Source,
    WishlistItem,
)
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


def make_item(db_session, card: Card, **overrides) -> CollectionItem:
    fields = dict(card_id=card.id, quantity=1, user_id=1)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


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


def make_submission(db_session, item: CollectionItem, **overrides) -> GradingSubmission:
    fields = dict(collection_item_id=item.id, grading_company="PSA", submission_status="planned")
    fields.update(overrides)
    submission = GradingSubmission(**fields)
    db_session.add(submission)
    db_session.commit()
    db_session.refresh(submission)
    return submission


def by_key(entries: list[dict]) -> dict:
    return {e["key"]: e for e in entries}


def test_analytics_empty_collection_works(client, db_session):
    response = client.get("/analytics/collection")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {
        "total_items": 0,
        "total_quantity": 0,
        "total_cost_basis_jpy": 0,
        "raw_market_floor_value_jpy": 0,
        "graded_adjusted_value_jpy": 0,
        "unrealized_pnl_jpy": 0,
        "unrealized_pnl_pct": 0.0,
        "items_missing_cost_basis": 0,
        "items_missing_market_price": 0,
        "owned_unique_cards": 0,
        "wishlist_unique_cards": 0,
        "grading_active_count": 0,
    }
    for key in (
        "by_set", "by_rarity", "by_variant", "by_language", "by_status", "by_tag", "by_group",
        "by_grading_status",
    ):
        assert body["breakdowns"][key] == []
    assert body["concentration"] == {
        "top_5_cards_by_value": [],
        "top_10_cards_value_pct": 0.0,
        "largest_single_card_value_pct": 0.0,
        "largest_set_exposure": None,
        "largest_rarity_exposure": None,
    }
    assert body["cost_basis"] == {
        "items_with_cost_basis": 0,
        "items_without_cost_basis": 0,
        "average_cost_basis_jpy": 0,
        "median_cost_basis_jpy": 0,
        "highest_cost_basis_items": [],
    }
    assert body["valuation_quality"] == {
        "items_with_yuyutei_sell": 0,
        "items_with_yuyutei_buy": 0,
        "items_with_snkrdunk_floor": 0,
        "items_using_graded_value": 0,
        "items_using_raw_fallback": 0,
        "coverage_pct": 0.0,
    }


def test_analytics_by_set_works(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card1 = make_card(db_session, card_code="OP01-001", set_code="OP01", rarity="L")
    card2 = make_card(db_session, card_code="OP02-001", set_code="OP02", rarity="R")
    add_observation(db_session, card1, snkrdunk, price_type="floor", price_jpy=1000)
    add_observation(db_session, card2, snkrdunk, price_type="floor", price_jpy=2000)
    make_item(db_session, card1, purchase_price_jpy=500)
    make_item(db_session, card2, purchase_price_jpy=800)

    response = client.get("/analytics/collection")

    assert response.status_code == 200
    breakdown = by_key(response.json()["breakdowns"]["by_set"])
    assert set(breakdown.keys()) == {"OP01", "OP02"}
    assert breakdown["OP01"]["item_count"] == 1
    assert breakdown["OP01"]["cost_basis_jpy"] == 500
    assert breakdown["OP01"]["value_jpy"] == 1000
    assert breakdown["OP01"]["pnl_jpy"] == 500
    assert breakdown["OP01"]["portfolio_weight_pct"] == 33.33
    assert breakdown["OP02"]["value_jpy"] == 2000
    assert breakdown["OP02"]["cost_basis_jpy"] == 800
    assert breakdown["OP02"]["portfolio_weight_pct"] == 66.67


def test_analytics_by_rarity_works(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card1 = make_card(db_session, card_code="OP01-001", set_code="OP01", rarity="L")
    card2 = make_card(db_session, card_code="OP01-002", set_code="OP01", rarity="SR")
    add_observation(db_session, card1, snkrdunk, price_type="floor", price_jpy=1500)
    add_observation(db_session, card2, snkrdunk, price_type="floor", price_jpy=3000)
    make_item(db_session, card1, purchase_price_jpy=1000)
    make_item(db_session, card2, purchase_price_jpy=2000)

    response = client.get("/analytics/collection")

    breakdown = by_key(response.json()["breakdowns"]["by_rarity"])
    assert set(breakdown.keys()) == {"L", "SR"}
    assert breakdown["L"]["value_jpy"] == 1500
    assert breakdown["SR"]["value_jpy"] == 3000
    assert breakdown["L"]["pnl_jpy"] == 500
    assert breakdown["SR"]["pnl_jpy"] == 1000


def test_analytics_by_tag_works(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
    item = make_item(db_session, card, purchase_price_jpy=500)
    tag1 = CollectorTag(user_id=1, name="Foils", slug="foils")
    tag2 = CollectorTag(user_id=1, name="Grail", slug="grail")
    db_session.add_all([tag1, tag2])
    db_session.commit()
    assert client.post(f"/collection/{item.id}/tags/{tag1.id}").status_code == 200
    assert client.post(f"/collection/{item.id}/tags/{tag2.id}").status_code == 200

    response = client.get("/analytics/collection")

    breakdown = by_key(response.json()["breakdowns"]["by_tag"])
    assert set(breakdown.keys()) == {"foils", "grail"}
    # The item belongs to both tags, so its full value counts toward each
    # bucket - tag buckets are not a partition of the portfolio.
    assert breakdown["foils"]["value_jpy"] == 1000
    assert breakdown["grail"]["value_jpy"] == 1000
    assert breakdown["foils"]["label"] == "Foils"


def test_analytics_by_group_works(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=2000)
    item = make_item(db_session, card, purchase_price_jpy=1000)
    group = CollectorGroup(user_id=1, name="Manga wants", slug="manga-wants")
    db_session.add(group)
    db_session.commit()
    assert client.post(f"/collection/{item.id}/groups/{group.id}").status_code == 200

    response = client.get("/analytics/collection")

    breakdown = by_key(response.json()["breakdowns"]["by_group"])
    assert breakdown == {
        "manga-wants": {
            "key": "manga-wants", "label": "Manga wants", "item_count": 1, "quantity": 1,
            "cost_basis_jpy": 1000, "value_jpy": 2000, "pnl_jpy": 1000, "pnl_pct": 100.0,
            "portfolio_weight_pct": 100.0,
        }
    }


def test_valuation_mode_raw_market_works(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
    item = make_item(db_session, card, purchase_price_jpy=600)
    make_submission(
        db_session, item, submission_status="received", final_grade="10", graded_value_jpy=9000,
    )

    response = client.get("/analytics/collection", params={"valuation_mode": "raw_market"})

    body = response.json()
    assert body["summary"]["raw_market_floor_value_jpy"] == 1000
    # graded_adjusted_value_jpy is always populated regardless of mode...
    assert body["summary"]["graded_adjusted_value_jpy"] == 9000
    # ...but unrealized P/L and breakdown values use the raw market figure.
    assert body["summary"]["unrealized_pnl_jpy"] == 1000 - 600
    assert body["breakdowns"]["by_set"][0]["value_jpy"] == 1000


def test_valuation_mode_graded_adjusted_works(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card1 = make_card(db_session, card_code="OP01-001")
    card2 = make_card(db_session, card_code="OP01-002", rarity="SR")
    add_observation(db_session, card1, snkrdunk, price_type="floor", price_jpy=1000)
    item1 = make_item(db_session, card1, purchase_price_jpy=600)
    item2 = make_item(db_session, card2, purchase_price_jpy=300)
    make_submission(
        db_session, item1, submission_status="received", final_grade="10", graded_value_jpy=9000,
    )
    make_submission(db_session, item2, submission_status="grading")

    response = client.get("/analytics/collection", params={"valuation_mode": "graded_adjusted"})

    body = response.json()
    assert body["summary"]["graded_adjusted_value_jpy"] == 9000
    assert body["summary"]["unrealized_pnl_jpy"] == 9000 - (600 + 300)
    assert body["valuation_quality"]["items_using_graded_value"] == 1
    # item2's "grading" submission status is a waiting-return state, so it
    # counts toward active grading regardless of the selected valuation mode.
    assert body["summary"]["grading_active_count"] == 1


def test_sold_items_excluded_by_default(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card1 = make_card(db_session, card_code="OP01-001")
    card2 = make_card(db_session, card_code="OP01-002")
    add_observation(db_session, card1, snkrdunk, price_type="floor", price_jpy=1000)
    add_observation(db_session, card2, snkrdunk, price_type="floor", price_jpy=500)
    make_item(db_session, card1, purchase_price_jpy=500, status="hold")
    make_item(db_session, card2, purchase_price_jpy=200, status="sold")

    response = client.get("/analytics/collection")

    body = response.json()
    assert body["summary"]["total_items"] == 1
    assert body["summary"]["raw_market_floor_value_jpy"] == 1000
    assert "sold" not in by_key(body["breakdowns"]["by_status"])


def test_include_sold_includes_sold_items(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card1 = make_card(db_session, card_code="OP01-001")
    card2 = make_card(db_session, card_code="OP01-002")
    add_observation(db_session, card1, snkrdunk, price_type="floor", price_jpy=1000)
    add_observation(db_session, card2, snkrdunk, price_type="floor", price_jpy=500)
    make_item(db_session, card1, purchase_price_jpy=500, status="hold")
    make_item(db_session, card2, purchase_price_jpy=200, status="sold")

    response = client.get("/analytics/collection", params={"include_sold": "true"})

    body = response.json()
    assert body["summary"]["total_items"] == 2
    assert body["summary"]["raw_market_floor_value_jpy"] == 1500
    sold_bucket = by_key(body["breakdowns"]["by_status"])["sold"]
    assert sold_bucket["value_jpy"] == 500
    assert sold_bucket["cost_basis_jpy"] == 200


def test_concentration_calculations_work(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    cards = [
        make_card(db_session, card_code=f"OP01-{i:03d}", set_code="OP01", rarity="L")
        for i in range(1, 4)
    ]
    values = [5000, 3000, 2000]
    for card, value in zip(cards, values):
        add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=value)
        make_item(db_session, card, purchase_price_jpy=value // 2)

    wishlist_card = make_card(db_session, card_code="OP02-001", set_code="OP02", rarity="R")
    db_session.add(WishlistItem(user_id=1, card_id=wishlist_card.id))
    db_session.commit()

    response = client.get("/analytics/collection")

    body = response.json()
    top5 = body["concentration"]["top_5_cards_by_value"]
    assert [c["value_jpy"] for c in top5] == [5000, 3000, 2000]
    # Only 3 items exist, so "top 10" is the whole portfolio - 100%.
    assert body["concentration"]["top_10_cards_value_pct"] == 100.0
    assert body["concentration"]["largest_single_card_value_pct"] == 50.0
    assert body["concentration"]["largest_set_exposure"]["key"] == "OP01"
    assert body["concentration"]["largest_rarity_exposure"]["key"] == "L"
    assert body["summary"]["wishlist_unique_cards"] == 1


def test_cost_basis_median_works(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    cards = [make_card(db_session, card_code=f"OP01-{i:03d}") for i in range(1, 5)]
    costs = [100, 200, 300, 400]
    for card, cost in zip(cards, costs):
        add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=cost)
        make_item(db_session, card, purchase_price_jpy=cost)

    response = client.get("/analytics/collection")

    cost_basis = response.json()["cost_basis"]
    assert cost_basis["items_with_cost_basis"] == 4
    assert cost_basis["items_without_cost_basis"] == 0
    assert cost_basis["average_cost_basis_jpy"] == round(sum(costs) / 4)
    assert cost_basis["median_cost_basis_jpy"] == round(statistics.median(costs))
    assert [i["cost_basis_jpy"] for i in cost_basis["highest_cost_basis_items"]] == [400, 300, 200, 100]


def test_valuation_quality_coverage_works(client, db_session):
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    card1 = make_card(db_session, card_code="OP01-001")
    card2 = make_card(db_session, card_code="OP01-002")
    add_observation(db_session, card1, snkrdunk, price_type="floor", price_jpy=1000)
    add_observation(db_session, card1, yuyutei, price_type="sell", price_jpy=1200)
    add_observation(db_session, card1, yuyutei, price_type="buy", price_jpy=900)
    # card2 has no price observations at all.
    make_item(db_session, card1, purchase_price_jpy=500)
    make_item(db_session, card2, purchase_price_jpy=500)

    response = client.get("/analytics/collection")

    body = response.json()
    assert body["summary"]["items_missing_market_price"] == 1
    quality = body["valuation_quality"]
    assert quality["items_with_snkrdunk_floor"] == 1
    assert quality["items_with_yuyutei_sell"] == 1
    assert quality["items_with_yuyutei_buy"] == 1
    assert quality["coverage_pct"] == 50.0


def test_endpoint_cache_invalidates_after_collection_write(client, db_session):
    card = make_card(db_session)

    first = client.get("/analytics/collection")
    assert first.headers["X-Cache"] == "MISS"
    second = client.get("/analytics/collection")
    assert second.headers["X-Cache"] == "HIT"

    response = client.post("/collection", json={"card_id": card.id, "quantity": 1, "status": "hold"})
    assert response.status_code == 201

    third = client.get("/analytics/collection")
    assert third.headers["X-Cache"] == "MISS"
    assert third.json()["summary"]["total_items"] == 1
