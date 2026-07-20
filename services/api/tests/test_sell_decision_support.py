from datetime import datetime, timezone

import pytest

from app.models import (
    Card,
    CollectionItem,
    CollectionItemGroup,
    CollectionItemTag,
    CollectorGroup,
    CollectorTag,
    GradingSubmission,
    PriceObservation,
    Source,
    WishlistItem,
)
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


def make_item(db_session, card: Card, **overrides) -> CollectionItem:
    fields = dict(card_id=card.id, quantity=1, user_id=TEST_USER_ID)
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


def make_tag(db_session, item: CollectionItem, name: str) -> CollectorTag:
    tag = CollectorTag(user_id=TEST_USER_ID, name=name, slug=name.lower().replace(" ", "-"))
    db_session.add(tag)
    db_session.commit()
    db_session.add(CollectionItemTag(collection_item_id=item.id, tag_id=tag.id))
    db_session.commit()
    return tag


def make_group(db_session, item: CollectionItem, name: str) -> CollectorGroup:
    group = CollectorGroup(user_id=TEST_USER_ID, name=name, slug=name.lower().replace(" ", "-"))
    db_session.add(group)
    db_session.commit()
    db_session.add(CollectionItemGroup(collection_item_id=item.id, group_id=group.id))
    db_session.commit()
    return group


def by_card_code(candidates: list[dict]) -> dict:
    return {c["card_code"]: c for c in candidates}


def test_empty_collection_works(client, db_session):
    response = client.get("/analytics/sell-decisions")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {
        "total_candidates": 0,
        "review_sell_count": 0,
        "hold_count": 0,
        "grade_first_count": 0,
        "missing_data_count": 0,
        "monitor_count": 0,
        "total_potential_sale_value_jpy": 0,
        "total_unrealized_pnl_jpy": 0,
        "average_score": 0.0,
    }
    assert body["candidates"] == []
    assert body["pagination"]["total"] == 0


def test_missing_cost_basis_returns_missing_data(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
    make_item(db_session, card, purchase_price_jpy=None)

    response = client.get("/analytics/sell-decisions")

    candidate = response.json()["candidates"][0]
    assert candidate["cost_basis_jpy"] is None
    assert candidate["recommended_action"] == "missing_data"
    assert "Missing cost basis" in candidate["warnings"]


def test_missing_current_value_returns_missing_data(client, db_session):
    card = make_card(db_session)
    make_item(db_session, card, purchase_price_jpy=1000)  # no price observations at all

    response = client.get("/analytics/sell-decisions")

    candidate = response.json()["candidates"][0]
    assert candidate["current_value_jpy"] is None
    assert candidate["recommended_action"] == "missing_data"
    assert "Missing current value" in candidate["warnings"]


def test_active_grading_returns_grade_first(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=5000)
    item = make_item(db_session, card, purchase_price_jpy=4000)
    make_submission(db_session, item, submission_status="submitted")

    response = client.get("/analytics/sell-decisions")

    candidate = response.json()["candidates"][0]
    assert candidate["recommended_action"] == "grade_first"
    assert candidate["grading"]["has_active_grading"] is True
    assert candidate["grading"]["latest_status"] == "submitted"


def test_above_target_sell_returns_review_sell(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=15000)
    make_item(db_session, card, purchase_price_jpy=8000, target_sell_price_jpy=14000)

    response = client.get("/analytics/sell-decisions")

    candidate = response.json()["candidates"][0]
    assert candidate["above_target_sell"] is True
    assert candidate["recommended_action"] == "review_sell"
    assert "Above target sell price" in candidate["score_reasons"]


def test_worked_score_example_matches_spec(client, db_session):
    """End-to-end golden test: above target sell (+35), P/L 87.5% -> only the
    >=50% tier (+20), SNKRDUNK floor 15.38% above Yuyu-Tei sell (+15),
    Yuyu-Tei spread 15.38% compressed (+15) => 85, matching the worked
    example in the feature spec."""
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei = make_source(db_session, "yuyutei")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=15000)
    add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=13000)
    add_observation(db_session, card, yuyutei, price_type="buy", price_jpy=11000)
    make_item(db_session, card, purchase_price_jpy=8000, target_sell_price_jpy=14000)

    response = client.get("/analytics/sell-decisions")

    candidate = response.json()["candidates"][0]
    assert candidate["score"] == 85
    assert candidate["unrealized_pnl_pct"] == 87.5
    assert candidate["market_context"]["yuyutei_spread_pct"] == 15.38
    assert candidate["market_context"]["snkrdunk_vs_yuyutei_sell_gap_pct"] == 15.38


def test_high_pnl_increases_score(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    low_pnl_card = make_card(db_session, card_code="OP01-001")
    high_pnl_card = make_card(db_session, card_code="OP01-002")
    add_observation(db_session, low_pnl_card, snkrdunk, price_type="floor", price_jpy=12000)
    add_observation(db_session, high_pnl_card, snkrdunk, price_type="floor", price_jpy=21000)
    make_item(db_session, low_pnl_card, purchase_price_jpy=10000)  # +20% pnl
    make_item(db_session, high_pnl_card, purchase_price_jpy=10000)  # +110% pnl

    response = client.get("/analytics/sell-decisions")

    candidates = by_card_code(response.json()["candidates"])
    low = candidates["OP01-001"]
    high = candidates["OP01-002"]
    assert "Unrealized P/L above 50%" not in low["score_reasons"]
    assert "Unrealized P/L above 50%" in high["score_reasons"]
    assert "Unrealized P/L above 100%" in high["score_reasons"]
    assert high["score"] - low["score"] == 50


def test_compressed_yuyutei_spread_increases_score(client, db_session):
    yuyutei = make_source(db_session, "yuyutei")
    compressed_card = make_card(db_session, card_code="OP01-001")
    wide_card = make_card(db_session, card_code="OP01-002")
    add_observation(db_session, compressed_card, yuyutei, price_type="sell", price_jpy=10000)
    add_observation(db_session, compressed_card, yuyutei, price_type="buy", price_jpy=9000)  # 10% spread
    add_observation(db_session, wide_card, yuyutei, price_type="sell", price_jpy=10000)
    add_observation(db_session, wide_card, yuyutei, price_type="buy", price_jpy=5000)  # 50% spread
    make_item(db_session, compressed_card, purchase_price_jpy=9000)
    make_item(db_session, wide_card, purchase_price_jpy=9000)

    response = client.get("/analytics/sell-decisions")

    candidates = by_card_code(response.json()["candidates"])
    assert "Compressed Yuyu-Tei spread" in candidates["OP01-001"]["score_reasons"]
    assert "Compressed Yuyu-Tei spread" not in candidates["OP01-002"]["score_reasons"]
    assert candidates["OP01-001"]["score"] - candidates["OP01-002"]["score"] == 15


def test_snkrdunk_above_yuyutei_sell_increases_score(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei = make_source(db_session, "yuyutei")
    strong_gap_card = make_card(db_session, card_code="OP01-001")
    weak_gap_card = make_card(db_session, card_code="OP01-002")
    add_observation(db_session, strong_gap_card, yuyutei, price_type="sell", price_jpy=10000)
    add_observation(db_session, strong_gap_card, snkrdunk, price_type="floor", price_jpy=12000)  # 20% gap
    add_observation(db_session, weak_gap_card, yuyutei, price_type="sell", price_jpy=10000)
    add_observation(db_session, weak_gap_card, snkrdunk, price_type="floor", price_jpy=10200)  # 2% gap
    make_item(db_session, strong_gap_card, purchase_price_jpy=9000)
    make_item(db_session, weak_gap_card, purchase_price_jpy=9000)

    response = client.get("/analytics/sell-decisions")

    candidates = by_card_code(response.json()["candidates"])
    assert "SNKRDUNK floor above Yuyu-Tei sell by 10%+" in candidates["OP01-001"]["score_reasons"]
    assert "SNKRDUNK floor above Yuyu-Tei sell by 10%+" not in candidates["OP01-002"]["score_reasons"]
    assert candidates["OP01-001"]["score"] - candidates["OP01-002"]["score"] == 15


def test_long_term_hold_tag_reduces_score_and_action(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    plain_card = make_card(db_session, card_code="OP01-001")
    tagged_card = make_card(db_session, card_code="OP01-002")
    add_observation(db_session, plain_card, snkrdunk, price_type="floor", price_jpy=21000)
    add_observation(db_session, tagged_card, snkrdunk, price_type="floor", price_jpy=21000)
    make_item(db_session, plain_card, purchase_price_jpy=10000)
    tagged_item = make_item(db_session, tagged_card, purchase_price_jpy=10000)
    make_tag(db_session, tagged_item, "Long-term hold")

    response = client.get("/analytics/sell-decisions")

    candidates = by_card_code(response.json()["candidates"])
    plain = candidates["OP01-001"]
    tagged = candidates["OP01-002"]
    assert "Tagged/grouped as long-term hold" in tagged["score_reasons"]
    assert plain["score"] - tagged["score"] == 15
    assert plain["recommended_action"] == "monitor"
    assert tagged["recommended_action"] == "hold"


def test_wishlist_grail_overlap_reduces_score_and_action(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    plain_card = make_card(db_session, card_code="OP01-001")
    wishlisted_card = make_card(db_session, card_code="OP01-002")
    add_observation(db_session, plain_card, snkrdunk, price_type="floor", price_jpy=21000)
    add_observation(db_session, wishlisted_card, snkrdunk, price_type="floor", price_jpy=21000)
    make_item(db_session, plain_card, purchase_price_jpy=10000)
    make_item(db_session, wishlisted_card, purchase_price_jpy=10000)
    db_session.add(
        WishlistItem(user_id=TEST_USER_ID, card_id=wishlisted_card.id, priority="grail", status="watching")
    )
    db_session.commit()

    response = client.get("/analytics/sell-decisions")

    candidates = by_card_code(response.json()["candidates"])
    plain = candidates["OP01-001"]
    wishlisted = candidates["OP01-002"]
    assert "Also wishlisted at grail/high priority" in wishlisted["score_reasons"]
    assert wishlisted["wishlist_overlap"] == {
        "is_on_wishlist": True, "priority": "grail", "status": "watching",
    }
    assert plain["score"] - wishlisted["score"] == 10
    assert wishlisted["recommended_action"] == "hold"


def test_sold_items_excluded_by_default(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
    make_item(db_session, card, purchase_price_jpy=500, status="sold")

    response = client.get("/analytics/sell-decisions")

    assert response.json()["summary"]["total_candidates"] == 0


def test_include_sold_includes_sold_items(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
    make_item(db_session, card, purchase_price_jpy=500, status="sold")

    response = client.get("/analytics/sell-decisions", params={"include_sold": "true"})

    body = response.json()
    assert body["summary"]["total_candidates"] == 1
    assert body["candidates"][0]["status"] == "sold"


def test_valuation_mode_graded_adjusted_uses_graded_value(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session)
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=10000)
    item = make_item(db_session, card, purchase_price_jpy=5000)
    make_submission(
        db_session, item, submission_status="received", graded_value_jpy=20000, final_grade="PSA 10",
    )

    raw_response = client.get("/analytics/sell-decisions", params={"valuation_mode": "raw_market"})
    raw_candidate = raw_response.json()["candidates"][0]
    assert raw_candidate["current_value_jpy"] == 10000
    assert raw_candidate["current_value_basis"] == "snkrdunk_floor"

    graded_response = client.get(
        "/analytics/sell-decisions", params={"valuation_mode": "graded_adjusted"}
    )
    graded_candidate = graded_response.json()["candidates"][0]
    assert graded_candidate["current_value_jpy"] == 20000
    assert graded_candidate["current_value_basis"] == "graded_value"
    assert graded_candidate["grading"]["graded_value_jpy"] == 20000


def test_pagination_works(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    for i in range(3):
        card = make_card(db_session, card_code=f"OP01-{i:03d}")
        add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
        make_item(db_session, card, purchase_price_jpy=500)

    first_page = client.get("/analytics/sell-decisions", params={"limit": 2, "offset": 0}).json()
    assert len(first_page["candidates"]) == 2
    assert first_page["pagination"]["total"] == 3
    assert first_page["pagination"]["has_next"] is True
    assert first_page["pagination"]["has_previous"] is False

    second_page = client.get("/analytics/sell-decisions", params={"limit": 2, "offset": 2}).json()
    assert len(second_page["candidates"]) == 1
    assert second_page["pagination"]["has_next"] is False
    assert second_page["pagination"]["has_previous"] is True


def test_cache_invalidates_after_collection_write(client, db_session):
    card = make_card(db_session)

    first = client.get("/analytics/sell-decisions")
    assert first.headers["X-Cache"] == "MISS"
    second = client.get("/analytics/sell-decisions")
    assert second.headers["X-Cache"] == "HIT"

    response = client.post("/collection", json={"card_id": card.id})
    assert response.status_code == 201

    third = client.get("/analytics/sell-decisions")
    assert third.headers["X-Cache"] == "MISS"
    assert third.json()["summary"]["total_candidates"] == 1
