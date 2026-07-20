from datetime import datetime, timezone

import pytest

from app.models import Card, CollectionItem, MarketSignalEvent, PriceObservation, Source, WishlistItem
from app.services import cache as cache_module
from app.settings import settings

TEST_USER_ID = 1


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


def make_signal_event(db_session, card, *, signal_type, suggested_action=None, dedupe_key=None, **overrides):
    now = datetime.now(timezone.utc)
    event = MarketSignalEvent(
        signal_type=signal_type,
        dedupe_key=dedupe_key or f"{signal_type}:{card.id}",
        card_id=card.id,
        suggested_action=suggested_action,
        status=overrides.pop("status", "open"),
        first_seen_at=now,
        last_seen_at=now,
        **overrides,
    )
    db_session.add(event)
    db_session.commit()
    return event


def by_card_code(candidates: list[dict]) -> dict:
    return {c["card_code"]: c for c in candidates}


def test_empty_wishlist_works(client, db_session):
    response = client.get("/analytics/buy-decisions")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {
        "total_candidates": 0,
        "review_buy_count": 0,
        "wait_count": 0,
        "skip_count": 0,
        "missing_data_count": 0,
        "monitor_count": 0,
        "target_hit_count": 0,
        "total_target_budget_jpy": 0,
        "total_current_cost_jpy": 0,
        "budget_gap_jpy": 0,
        "average_score": 0.0,
    }
    assert body["candidates"] == []
    assert body["pagination"]["total"] == 0


def test_target_hit_returns_review_buy(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=900)
    make_wishlist_item(client, card.id, target_buy_price_jpy=1000)

    response = client.get("/analytics/buy-decisions")

    candidate = response.json()["candidates"][0]
    assert candidate["target_hit"] is True
    assert candidate["recommended_action"] == "review_buy"
    assert "Wishlist target hit" in candidate["score_reasons"]


def test_worked_score_example_matches_spec(client, db_session):
    """End-to-end golden test: target hit (+40), grail priority (+25),
    SNKRDUNK floor 25% below Yuyu-Tei sell (+20) => 85, matching the worked
    example in the feature spec. Yuyu-Tei spread is 25% (not compressed, no
    bonus), and no opportunity/signal/tag data is present."""
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei = make_source(db_session, "yuyutei")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=900)
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1200)
    add_observation(db_session, card, yuyutei, price_type="buy", price_jpy=900)
    make_wishlist_item(
        client, card.id, priority="grail", target_buy_price_jpy=1000, max_buy_price_jpy=1500,
    )

    response = client.get("/analytics/buy-decisions")

    candidate = response.json()["candidates"][0]
    assert candidate["score"] == 85
    assert candidate["current_price_jpy"] == 900
    assert candidate["current_price_source"] == "snkrdunk_floor"
    assert candidate["gap_to_target_jpy"] == -100
    assert candidate["gap_to_target_pct"] == -10.0
    assert candidate["gap_to_max_jpy"] == -600
    assert candidate["gap_to_max_pct"] == -40.0
    assert candidate["market_context"]["snkrdunk_vs_yuyutei_sell_gap_pct"] == -25.0
    assert candidate["market_context"]["yuyutei_spread_pct"] == 25.0
    assert candidate["recommended_action"] == "review_buy"


def test_grail_priority_increases_score(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    low_card = make_card(db_session, card_code="OP01-001")
    grail_card = make_card(db_session, card_code="OP01-002")
    add_observation(db_session, low_card, snkrdunk, price_type="floor", price_jpy=2000)
    add_observation(db_session, grail_card, snkrdunk, price_type="floor", price_jpy=2000)
    make_wishlist_item(client, low_card.id, priority="low", target_buy_price_jpy=1000)
    make_wishlist_item(client, grail_card.id, priority="grail", target_buy_price_jpy=1000)

    response = client.get("/analytics/buy-decisions")

    candidates = by_card_code(response.json()["candidates"])
    assert "Grail priority" in candidates["OP01-002"]["score_reasons"]
    assert candidates["OP01-002"]["score"] - candidates["OP01-001"]["score"] == 25


def test_high_priority_increases_score(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    low_card = make_card(db_session, card_code="OP01-001")
    high_card = make_card(db_session, card_code="OP01-002")
    add_observation(db_session, low_card, snkrdunk, price_type="floor", price_jpy=2000)
    add_observation(db_session, high_card, snkrdunk, price_type="floor", price_jpy=2000)
    make_wishlist_item(client, low_card.id, priority="low", target_buy_price_jpy=1000)
    make_wishlist_item(client, high_card.id, priority="high", target_buy_price_jpy=1000)

    response = client.get("/analytics/buy-decisions")

    candidates = by_card_code(response.json()["candidates"])
    assert "High priority" in candidates["OP01-002"]["score_reasons"]
    assert candidates["OP01-002"]["score"] - candidates["OP01-001"]["score"] == 15


def test_snkrdunk_below_yuyutei_sell_increases_score(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei = make_source(db_session, "yuyutei")
    strong_gap_card = make_card(db_session, card_code="OP01-001")
    weak_gap_card = make_card(db_session, card_code="OP01-002")
    add_observation(db_session, strong_gap_card, yuyutei, price_type="sell", price_jpy=1000)
    add_observation(db_session, strong_gap_card, snkrdunk, price_type="floor", price_jpy=800)  # 20% below
    add_observation(db_session, weak_gap_card, yuyutei, price_type="sell", price_jpy=1000)
    add_observation(db_session, weak_gap_card, snkrdunk, price_type="floor", price_jpy=980)  # 2% below
    make_wishlist_item(client, strong_gap_card.id, priority="low", target_buy_price_jpy=1000)
    make_wishlist_item(client, weak_gap_card.id, priority="low", target_buy_price_jpy=1000)

    response = client.get("/analytics/buy-decisions")

    candidates = by_card_code(response.json()["candidates"])
    assert "SNKRDUNK floor below Yuyu-Tei sell" in candidates["OP01-001"]["score_reasons"]
    assert "SNKRDUNK floor below Yuyu-Tei sell" not in candidates["OP01-002"]["score_reasons"]
    assert candidates["OP01-001"]["score"] - candidates["OP01-002"]["score"] == 20


def test_price_down_signals_increase_score(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    plain_card = make_card(db_session, card_code="OP01-001")
    dropping_card = make_card(db_session, card_code="OP01-002")
    add_observation(db_session, plain_card, snkrdunk, price_type="floor", price_jpy=2000)
    add_observation(db_session, dropping_card, snkrdunk, price_type="floor", price_jpy=2000)
    make_wishlist_item(client, plain_card.id, priority="low", target_buy_price_jpy=1000)
    make_wishlist_item(client, dropping_card.id, priority="low", target_buy_price_jpy=1000)
    make_signal_event(
        db_session, dropping_card, signal_type="price_down_7d", suggested_action="monitor_drop",
    )
    make_signal_event(
        db_session, dropping_card, signal_type="price_down_30d", suggested_action="monitor_drop",
    )

    response = client.get("/analytics/buy-decisions")

    candidates = by_card_code(response.json()["candidates"])
    dropping = candidates["OP01-002"]
    plain = candidates["OP01-001"]
    assert "Price down over 7 days" in dropping["score_reasons"]
    assert "Price down over 30 days" in dropping["score_reasons"]
    assert dropping["score"] - plain["score"] == 25


def test_missing_price_returns_missing_data(client, db_session):
    card = make_card(db_session)
    make_wishlist_item(client, card.id, target_buy_price_jpy=1000)  # no price observations at all

    response = client.get("/analytics/buy-decisions")

    candidate = response.json()["candidates"][0]
    assert candidate["current_price_jpy"] is None
    assert candidate["recommended_action"] == "missing_data"
    assert "Missing current price" in candidate["warnings"]


def test_above_max_buy_price_returns_wait(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1600)
    make_wishlist_item(
        client, card.id, priority="low", target_buy_price_jpy=1000, max_buy_price_jpy=1500,
    )

    response = client.get("/analytics/buy-decisions")

    candidate = response.json()["candidates"][0]
    assert candidate["target_hit"] is False
    assert candidate["recommended_action"] == "wait"


def test_purchased_excluded_by_default(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
    item = make_wishlist_item(client, card.id, target_buy_price_jpy=1000)
    db_item = db_session.get(WishlistItem, item["id"])
    db_item.status = "purchased"
    db_session.commit()

    response = client.get("/analytics/buy-decisions")

    assert response.json()["summary"]["total_candidates"] == 0


def test_include_purchased_includes_purchased_but_action_skip(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
    item = make_wishlist_item(client, card.id, target_buy_price_jpy=1000)
    db_item = db_session.get(WishlistItem, item["id"])
    db_item.status = "purchased"
    db_session.commit()

    response = client.get("/analytics/buy-decisions", params={"include_purchased": "true"})

    body = response.json()
    assert body["summary"]["total_candidates"] == 1
    assert body["candidates"][0]["status"] == "purchased"
    assert body["candidates"][0]["recommended_action"] == "skip"


def test_fulfilled_owned_quantity_excluded_by_default(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
    make_wishlist_item(client, card.id, target_buy_price_jpy=1000, desired_quantity=1)
    db_session.add(CollectionItem(user_id=TEST_USER_ID, card_id=card.id, quantity=1, status="hold"))
    db_session.commit()

    response = client.get("/analytics/buy-decisions")

    assert response.json()["summary"]["total_candidates"] == 0


def test_include_owned_includes_owned_fulfilled_items(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
    make_wishlist_item(client, card.id, target_buy_price_jpy=1000, desired_quantity=1)
    db_session.add(CollectionItem(user_id=TEST_USER_ID, card_id=card.id, quantity=1, status="hold"))
    db_session.commit()

    response = client.get("/analytics/buy-decisions", params={"include_owned": "true"})

    body = response.json()
    assert body["summary"]["total_candidates"] == 1
    assert body["candidates"][0]["owned_quantity"] == 1
    assert body["candidates"][0]["remaining_quantity"] == 0


def test_source_preference_snkrdunk_uses_snkrdunk_floor(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei = make_source(db_session, "yuyutei")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=900)
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1200)
    make_wishlist_item(client, card.id, target_buy_price_jpy=1000)

    response = client.get("/analytics/buy-decisions", params={"source_preference": "snkrdunk"})

    candidate = response.json()["candidates"][0]
    assert candidate["current_price_jpy"] == 900
    assert candidate["current_price_source"] == "snkrdunk_floor"


def test_source_preference_yuyutei_uses_yuyutei_sell(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei = make_source(db_session, "yuyutei")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=900)
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1200)
    make_wishlist_item(client, card.id, target_buy_price_jpy=1000)

    response = client.get("/analytics/buy-decisions", params={"source_preference": "yuyutei"})

    candidate = response.json()["candidates"][0]
    assert candidate["current_price_jpy"] == 1200
    assert candidate["current_price_source"] == "yuyutei_sell"


def test_pagination_works(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    for i in range(3):
        card = make_card(db_session, card_code=f"OP01-{i:03d}")
        add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
        make_wishlist_item(client, card.id, target_buy_price_jpy=1000)

    first_page = client.get("/analytics/buy-decisions", params={"limit": 2, "offset": 0}).json()
    assert len(first_page["candidates"]) == 2
    assert first_page["pagination"]["total"] == 3
    assert first_page["pagination"]["has_next"] is True
    assert first_page["pagination"]["has_previous"] is False

    second_page = client.get("/analytics/buy-decisions", params={"limit": 2, "offset": 2}).json()
    assert len(second_page["candidates"]) == 1
    assert second_page["pagination"]["has_next"] is False
    assert second_page["pagination"]["has_previous"] is True


def test_cache_invalidates_after_wishlist_write(client, db_session):
    card = make_card(db_session)

    first = client.get("/analytics/buy-decisions")
    assert first.headers["X-Cache"] == "MISS"
    second = client.get("/analytics/buy-decisions")
    assert second.headers["X-Cache"] == "HIT"

    response = client.post("/wishlist", json={"card_id": card.id})
    assert response.status_code == 201

    third = client.get("/analytics/buy-decisions")
    assert third.headers["X-Cache"] == "MISS"
    assert third.json()["summary"]["total_candidates"] == 1
