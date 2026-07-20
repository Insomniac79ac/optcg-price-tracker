from datetime import date, datetime, timedelta, timezone

import pytest

from app.models import Card, CollectionItem, GradingSubmission, PriceObservation, Source, WishlistItem
from app.services import cache as cache_module
from app.services.portfolio_risk import _risk_level
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


def make_wishlist_item(db_session, card: Card, **overrides) -> WishlistItem:
    fields = dict(user_id=TEST_USER_ID, card_id=card.id)
    fields.update(overrides)
    item = WishlistItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def by_card_code(entries: list[dict]) -> dict:
    return {e["card_code"]: e for e in entries}


def test_empty_collection_returns_low_risk(client, db_session):
    response = client.get("/analytics/portfolio-risk")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["risk_score"] == 0
    assert body["summary"]["risk_level"] == "low"
    assert body["summary"]["total_value_jpy"] == 0
    assert body["summary"]["total_cost_basis_jpy"] == 0
    for key in ("concentration", "data_quality", "liquidity_proxy", "grading_exposure", "wishlist_overlap"):
        breakdown = body["risk_breakdown"][key]
        assert breakdown["score"] == 0
        assert breakdown["level"] == "low"
    for key in ("by_set", "by_rarity", "by_variant", "by_language", "by_tag", "by_group"):
        assert body["exposures"][key] == []
    assert body["recommendation_flags"] == []


def test_concentration_detects_largest_single_card(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    big_card = make_card(db_session, card_code="OP01-001", set_code="OP01", rarity="L")
    add_observation(db_session, big_card, snkrdunk, price_type="floor", price_jpy=5000)
    make_item(db_session, big_card, purchase_price_jpy=1000)

    for i in range(4):
        small_card = make_card(
            db_session, card_code=f"OP02-{i:03d}", set_code="OP02", rarity="R"
        )
        add_observation(db_session, small_card, snkrdunk, price_type="floor", price_jpy=100)
        make_item(db_session, small_card, purchase_price_jpy=50)

    response = client.get("/analytics/portfolio-risk")

    body = response.json()
    assert body["summary"]["largest_single_card_weight_pct"] == 92.59
    concentration = body["risk_breakdown"]["concentration"]
    assert concentration["score"] >= 15
    assert any("Largest single card" in w for w in concentration["warnings"])
    assert concentration["top_cards"][0]["card_code"] == "OP01-001"
    flag_types = [f["flag_type"] for f in body["recommendation_flags"]]
    assert "high_concentration" in flag_types


def test_concentration_detects_top_5_exposure(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    for i in range(5):
        card = make_card(db_session, card_code=f"OP01-{i:03d}", set_code=f"SET{i}", rarity=f"R{i}")
        add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1300)
        make_item(db_session, card, purchase_price_jpy=500)
    small_card = make_card(db_session, card_code="OP01-999", set_code="SETX", rarity="RX")
    add_observation(db_session, small_card, snkrdunk, price_type="floor", price_jpy=1000)
    make_item(db_session, small_card, purchase_price_jpy=500)

    response = client.get("/analytics/portfolio-risk")

    body = response.json()
    assert body["summary"]["top_5_weight_pct"] == 86.67
    # No single card reaches the 25% single-card threshold on its own.
    assert body["summary"]["largest_single_card_weight_pct"] < 25
    concentration = body["risk_breakdown"]["concentration"]
    assert any("Top 5 cards" in w for w in concentration["warnings"])
    assert concentration["score"] >= 15


def test_concentration_detects_largest_set_exposure(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    rarities = ["L", "R", "SR", "C", "UC", "L", "R", "SR", "C", "UC"]
    for i in range(10):
        set_code = "OP01" if i < 6 else "OP02"
        card = make_card(
            db_session, card_code=f"OP0{1 if i < 6 else 2}-{i:03d}", set_code=set_code, rarity=rarities[i]
        )
        add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
        make_item(db_session, card, purchase_price_jpy=500)

    response = client.get("/analytics/portfolio-risk")

    body = response.json()
    assert body["summary"]["largest_set_weight_pct"] == 60.0
    assert body["summary"]["largest_single_card_weight_pct"] == 10.0
    assert body["summary"]["top_5_weight_pct"] == 50.0
    concentration = body["risk_breakdown"]["concentration"]
    assert any("Largest set" in w for w in concentration["warnings"])
    assert concentration["score"] >= 5
    flag_types = [f["flag_type"] for f in body["recommendation_flags"]]
    assert "high_set_concentration" in flag_types


def test_missing_prices_increase_data_quality_risk(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    for i in range(3):
        card = make_card(db_session, card_code=f"OP01-{i:03d}")
        add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
        make_item(db_session, card, purchase_price_jpy=500)
    for i in range(2):
        card = make_card(db_session, card_code=f"OP02-{i:03d}")
        make_item(db_session, card, purchase_price_jpy=500)

    response = client.get("/analytics/portfolio-risk")

    body = response.json()
    assert body["summary"]["missing_price_count"] == 2
    data_quality = body["risk_breakdown"]["data_quality"]
    assert data_quality["score"] >= 15
    assert {c["card_code"] for c in data_quality["missing_prices"]} == {"OP02-000", "OP02-001"}
    assert data_quality["missing_prices"][0]["suggested_action"] == "fix_missing_prices"
    flag_types = [f["flag_type"] for f in body["recommendation_flags"]]
    assert "missing_prices" in flag_types


def test_missing_cost_basis_increases_data_quality_risk(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    for i in range(3):
        card = make_card(db_session, card_code=f"OP01-{i:03d}")
        add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
        make_item(db_session, card, purchase_price_jpy=500)
    for i in range(2):
        card = make_card(db_session, card_code=f"OP03-{i:03d}")
        add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
        make_item(db_session, card, purchase_price_jpy=None)

    response = client.get("/analytics/portfolio-risk")

    body = response.json()
    assert body["summary"]["missing_cost_basis_count"] == 2
    data_quality = body["risk_breakdown"]["data_quality"]
    assert data_quality["score"] >= 10
    assert len(data_quality["missing_cost_basis"]) == 2
    assert data_quality["missing_cost_basis"][0]["suggested_action"] == "fix_cost_basis"


def test_stale_prices_increase_data_quality_risk(client, db_session):
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    stale_card = make_card(db_session, card_code="OP01-999")
    add_observation(
        db_session, stale_card, yuyutei, price_type="sell", price_jpy=1000,
        observed_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )
    add_observation(db_session, stale_card, snkrdunk, price_type="floor", price_jpy=1000)
    make_item(db_session, stale_card, purchase_price_jpy=500)

    for i in range(4):
        card = make_card(db_session, card_code=f"OP02-{i:03d}")
        add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
        make_item(db_session, card, purchase_price_jpy=500)

    response = client.get("/analytics/portfolio-risk")

    body = response.json()
    assert body["summary"]["stale_price_count"] == 1
    data_quality = body["risk_breakdown"]["data_quality"]
    assert data_quality["score"] >= 5
    assert data_quality["stale_prices"][0]["card_code"] == "OP01-999"
    assert "stale" in data_quality["stale_prices"][0]["issue"].lower()
    flag_types = [f["flag_type"] for f in body["recommendation_flags"]]
    assert "stale_prices" in flag_types


def test_wide_yuyutei_spread_increases_liquidity_risk(client, db_session):
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")

    wide_card = make_card(db_session, card_code="OP01-999")
    add_observation(db_session, wide_card, yuyutei, price_type="sell", price_jpy=1000)
    add_observation(db_session, wide_card, yuyutei, price_type="buy", price_jpy=500)
    add_observation(db_session, wide_card, snkrdunk, price_type="floor", price_jpy=1000)
    make_item(db_session, wide_card, purchase_price_jpy=500)

    for i in range(4):
        card = make_card(db_session, card_code=f"OP02-{i:03d}")
        add_observation(db_session, card, yuyutei, price_type="sell", price_jpy=1000)
        add_observation(db_session, card, yuyutei, price_type="buy", price_jpy=950)
        add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
        make_item(db_session, card, purchase_price_jpy=500)

    response = client.get("/analytics/portfolio-risk")

    body = response.json()
    assert body["summary"]["wide_spread_count"] == 1
    liquidity = body["risk_breakdown"]["liquidity_proxy"]
    assert liquidity["score"] >= 10
    assert liquidity["wide_spread_cards"][0]["card_code"] == "OP01-999"
    assert liquidity["wide_spread_cards"][0]["spread_pct"] == 50.0
    flag_types = [f["flag_type"] for f in body["recommendation_flags"]]
    assert "wide_spread" in flag_types


def test_missing_snkrdunk_listing_data_increases_liquidity_risk(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")

    for i in range(2):
        card = make_card(db_session, card_code=f"OP01-{i:03d}")
        add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000, listing_count=None)
        make_item(db_session, card, purchase_price_jpy=500)

    for i in range(3):
        card = make_card(db_session, card_code=f"OP02-{i:03d}")
        add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000, listing_count=5)
        make_item(db_session, card, purchase_price_jpy=500)

    response = client.get("/analytics/portfolio-risk")

    body = response.json()
    liquidity = body["risk_breakdown"]["liquidity_proxy"]
    assert liquidity["score"] >= 5
    low_listing_codes = {c["card_code"] for c in liquidity["low_listing_cards"]}
    assert {"OP01-000", "OP01-001"} <= low_listing_codes
    flag_types = [f["flag_type"] for f in body["recommendation_flags"]]
    assert "low_liquidity" in flag_types


def test_active_grading_cost_exposure_increases_grading_risk(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    other_card = make_card(db_session, card_code="OP01-001")
    add_observation(db_session, other_card, snkrdunk, price_type="floor", price_jpy=800)
    make_item(db_session, other_card, purchase_price_jpy=800)

    grading_card = make_card(db_session, card_code="OP01-002")
    add_observation(db_session, grading_card, snkrdunk, price_type="floor", price_jpy=200)
    grading_item = make_item(db_session, grading_card, purchase_price_jpy=200)
    make_submission(db_session, grading_item, submission_status="submitted")

    response = client.get("/analytics/portfolio-risk")

    body = response.json()
    assert body["summary"]["active_grading_count"] == 1
    grading = body["risk_breakdown"]["grading_exposure"]
    assert grading["score"] >= 10
    assert grading["active_grading_items"][0]["card_code"] == "OP01-002"
    flag_types = [f["flag_type"] for f in body["recommendation_flags"]]
    assert "grading_exposure" in flag_types


def test_overdue_grading_increases_grading_risk(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    other_card = make_card(db_session, card_code="OP01-001")
    add_observation(db_session, other_card, snkrdunk, price_type="floor", price_jpy=9000)
    make_item(db_session, other_card, purchase_price_jpy=9000)

    grading_card = make_card(db_session, card_code="OP01-002")
    add_observation(db_session, grading_card, snkrdunk, price_type="floor", price_jpy=1000)
    grading_item = make_item(db_session, grading_card, purchase_price_jpy=1000)
    make_submission(
        db_session, grading_item, submission_status="submitted",
        expected_return_date=date.today() - timedelta(days=5),
    )

    response = client.get("/analytics/portfolio-risk")

    body = response.json()
    grading = body["risk_breakdown"]["grading_exposure"]
    assert grading["score"] >= 5
    assert any("overdue" in w.lower() for w in grading["warnings"])
    item = next(i for i in grading["active_grading_items"] if i["card_code"] == "OP01-002")
    assert item["overdue"] is True
    flag_types = [f["flag_type"] for f in body["recommendation_flags"]]
    assert "overdue_grading" in flag_types


def test_wishlist_overlap_increases_risk(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    owned_card = make_card(db_session, card_code="OP01-001")
    add_observation(db_session, owned_card, snkrdunk, price_type="floor", price_jpy=1000)
    make_item(db_session, owned_card, purchase_price_jpy=500)
    make_wishlist_item(db_session, owned_card, priority="grail", status="watching")

    fulfilled_card = make_card(db_session, card_code="OP01-002")
    make_wishlist_item(
        db_session, fulfilled_card, priority="low", status="watching",
        desired_quantity=1, acquired_quantity=1,
    )

    response = client.get("/analytics/portfolio-risk")

    body = response.json()
    assert body["summary"]["wishlist_overlap_count"] == 2
    wishlist_overlap = body["risk_breakdown"]["wishlist_overlap"]
    assert wishlist_overlap["score"] == 10
    codes = {c["card_code"] for c in wishlist_overlap["owned_wishlist_items"]}
    assert codes == {"OP01-001", "OP01-002"}
    flag_types = [f["flag_type"] for f in body["recommendation_flags"]]
    assert "wishlist_overlap" in flag_types


def test_risk_level_thresholds_work():
    assert _risk_level(0, 100) == "low"
    assert _risk_level(24, 100) == "low"
    assert _risk_level(25, 100) == "medium"
    assert _risk_level(49, 100) == "medium"
    assert _risk_level(50, 100) == "high"
    assert _risk_level(74, 100) == "high"
    assert _risk_level(75, 100) == "critical"
    assert _risk_level(100, 100) == "critical"


def test_include_sold_works(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card1 = make_card(db_session, card_code="OP01-001")
    card2 = make_card(db_session, card_code="OP01-002")
    add_observation(db_session, card1, snkrdunk, price_type="floor", price_jpy=1000)
    add_observation(db_session, card2, snkrdunk, price_type="floor", price_jpy=500)
    make_item(db_session, card1, purchase_price_jpy=500, status="hold")
    make_item(db_session, card2, purchase_price_jpy=200, status="sold")

    default_response = client.get("/analytics/portfolio-risk")
    assert default_response.json()["summary"]["total_value_jpy"] == 1000

    included_response = client.get("/analytics/portfolio-risk", params={"include_sold": "true"})
    assert included_response.json()["summary"]["total_value_jpy"] == 1500


def test_valuation_mode_graded_adjusted_works(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session, card_code="OP01-001")
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
    item = make_item(db_session, card, purchase_price_jpy=600)
    make_submission(
        db_session, item, submission_status="received", final_grade="10", graded_value_jpy=9000,
    )

    raw_response = client.get("/analytics/portfolio-risk", params={"valuation_mode": "raw_market"})
    assert raw_response.json()["summary"]["total_value_jpy"] == 1000

    graded_response = client.get(
        "/analytics/portfolio-risk", params={"valuation_mode": "graded_adjusted"}
    )
    assert graded_response.json()["summary"]["total_value_jpy"] == 9000


def test_endpoint_cache_invalidates_after_collection_write(client, db_session):
    card = make_card(db_session)

    first = client.get("/analytics/portfolio-risk")
    assert first.headers["X-Cache"] == "MISS"
    second = client.get("/analytics/portfolio-risk")
    assert second.headers["X-Cache"] == "HIT"

    response = client.post("/collection", json={"card_id": card.id, "quantity": 1, "status": "hold"})
    assert response.status_code == 201

    third = client.get("/analytics/portfolio-risk")
    assert third.headers["X-Cache"] == "MISS"
    assert third.json()["summary"]["total_cost_basis_jpy"] == 0
