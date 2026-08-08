"""app.services.market_index - Market Index v1 (see docs/market_index.md
for the product rules asserted here) - and the two routes that expose it,
GET /cards/{id}/market-index and GET /cards/catalogue."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models import Card, PriceObservation, Source
from app.services.market_index import (
    SNKRDUNK_FLOOR_MAX_AGE_DAYS,
    SNKRDUNK_SOLD_WINDOW_DAYS,
    YUYUTEI_SELL_MAX_AGE_DAYS,
    get_market_index_for_card,
    get_market_index_for_cards,
)

NOW = datetime.now(timezone.utc)


def make_card(db_session, **overrides) -> Card:
    fields = dict(card_code="OP01-001", set_code="OP01", rarity="L", language="jp")
    fields.update(overrides)
    card = Card(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_source(db_session, name: str) -> Source:
    source = db_session.query(Source).filter_by(name=name).one_or_none()
    if source is not None:
        return source
    source = Source(name=name, base_url=f"https://{name}.example.com")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def add_obs(db_session, card, source, **kwargs) -> PriceObservation:
    obs = PriceObservation(card_id=card.id, source_id=source.id, **kwargs)
    db_session.add(obs)
    db_session.commit()
    db_session.refresh(obs)
    return obs


def yuyutei_sell(db_session, card, yuyutei, *, price_jpy, days_ago=0, stock_status="in_stock"):
    return add_obs(
        db_session, card, yuyutei,
        price_type="sell", price_jpy=price_jpy,
        observed_at=NOW - timedelta(days=days_ago), stock_status=stock_status,
    )


def yuyutei_buy(db_session, card, yuyutei, *, price_jpy, days_ago=0):
    return add_obs(
        db_session, card, yuyutei,
        price_type="buy", price_jpy=price_jpy,
        observed_at=NOW - timedelta(days=days_ago), stock_status="in_stock",
    )


def snkrdunk_sold(db_session, card, snkrdunk, *, price_jpy, days_ago=0):
    return add_obs(
        db_session, card, snkrdunk,
        price_type="sold", price_jpy=price_jpy, observed_at=NOW - timedelta(days=days_ago),
    )


def snkrdunk_floor(db_session, card, snkrdunk, *, price_jpy, days_ago=0):
    return add_obs(
        db_session, card, snkrdunk,
        price_type="floor", price_jpy=price_jpy, observed_at=NOW - timedelta(days=days_ago),
    )


def find(values, source, reference_type):
    return next(v for v in values if v.source == source and v.reference_type == reference_type)


# --- Yuyu-Tei ---------------------------------------------------------------


def test_fresh_in_stock_sell_is_eligible(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    sell = find(index.source_values, "yuyutei", "retail_sell")
    assert sell.eligible is True
    assert sell.value_jpy == 1200
    assert sell.stale is False


def test_out_of_stock_sell_is_eligible(db_session):
    """Product decision: stock has no effect on Yuyu-Tei eligibility - only
    freshness (see test_stale_sell_is_excluded) and identity/price
    validation upstream govern whether a sell observation counts."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, stock_status="out_of_stock")

    index = get_market_index_for_card(db_session, card.id)

    sell = find(index.source_values, "yuyutei", "retail_sell")
    assert sell.eligible is True
    assert sell.value_jpy == 1200
    assert sell.ineligible_reason is None


def test_in_stock_and_out_of_stock_are_identically_eligible(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, stock_status="out_of_stock")
    index_out_of_stock = get_market_index_for_card(db_session, card.id)

    other_card = make_card(db_session, card_code="OP01-002")
    yuyutei_sell(db_session, other_card, yuyutei, price_jpy=1200, stock_status="in_stock")
    index_in_stock = get_market_index_for_card(db_session, other_card.id)

    sell_out = find(index_out_of_stock.source_values, "yuyutei", "retail_sell")
    sell_in = find(index_in_stock.source_values, "yuyutei", "retail_sell")
    assert sell_out.eligible == sell_in.eligible is True
    assert index_out_of_stock.coverage_status == index_in_stock.coverage_status == "limited"


def test_stale_sell_is_excluded(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=YUYUTEI_SELL_MAX_AGE_DAYS + 1)

    index = get_market_index_for_card(db_session, card.id)

    sell = find(index.source_values, "yuyutei", "retail_sell")
    assert sell.eligible is False
    assert sell.stale is True
    assert "yuyutei" in index.stale_sources


def test_buy_is_auxiliary_only(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_buy(db_session, card, yuyutei, price_jpy=800)

    index = get_market_index_for_card(db_session, card.id)

    assert all(v.reference_type != "dealer_buy" for v in index.source_values)
    buy = find(index.auxiliary_values, "yuyutei", "dealer_buy")
    assert buy.value_jpy == 800
    assert buy.eligible is False


def test_buy_never_changes_index_value(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200)

    without_buy = get_market_index_for_card(db_session, card.id).index_value_jpy

    yuyutei_buy(db_session, card, yuyutei, price_jpy=1_000_000)  # absurd value

    with_buy = get_market_index_for_card(db_session, card.id).index_value_jpy

    assert without_buy == with_buy == 1200


# --- SNKRDUNK ----------------------------------------------------------------


def test_three_sold_observations_produce_their_median(db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    for price in (1000, 1200, 1400):
        snkrdunk_sold(db_session, card, snkrdunk, price_jpy=price, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    snk = find(index.source_values, "snkrdunk", "transaction_median")
    assert snk.value_jpy == 1200
    assert snk.evidence_type == "transaction"
    assert snk.sample_size == 3
    assert snk.eligible is True
    assert snk.fallback_used is False


def test_more_than_three_observations_produce_correct_median(db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    for price in (1000, 1100, 1200, 1300, 1900):
        snkrdunk_sold(db_session, card, snkrdunk, price_jpy=price, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    snk = find(index.source_values, "snkrdunk", "transaction_median")
    assert snk.value_jpy == 1200
    assert snk.sample_size == 5


def test_even_count_median_rounds_half_up(db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    for price in (1400, 1400, 1400, 1400, 1450, 1450, 1450, 1450):
        snkrdunk_sold(db_session, card, snkrdunk, price_jpy=price, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    snk = find(index.source_values, "snkrdunk", "transaction_median")
    # median of the two middle values (1400, 1450) is 1425.0 exactly - not a
    # .5 case itself, but exercises the even-count averaging path used by
    # the documented rounding policy.
    assert snk.value_jpy == 1425


def test_sold_observations_outside_30_days_are_excluded(db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    for price in (1000, 1200, 1400):
        snkrdunk_sold(db_session, card, snkrdunk, price_jpy=price, days_ago=SNKRDUNK_SOLD_WINDOW_DAYS + 1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    snk = find(index.source_values, "snkrdunk", "listing_floor")
    assert snk.fallback_used is True
    assert snk.value_jpy == 1500


def test_fewer_than_three_sold_triggers_floor_fallback(db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    snkrdunk_sold(db_session, card, snkrdunk, price_jpy=1000, days_ago=1)
    snkrdunk_sold(db_session, card, snkrdunk, price_jpy=1100, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    snk = find(index.source_values, "snkrdunk", "listing_floor")
    assert snk.value_jpy == 1500
    assert snk.fallback_used is True
    assert snk.evidence_type == "listing"
    assert snk.eligible is True


def test_fresh_floor_is_eligible_as_fallback(db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    snk = find(index.source_values, "snkrdunk", "listing_floor")
    assert snk.eligible is True
    assert snk.stale is False


def test_stale_floor_is_excluded(db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500, days_ago=SNKRDUNK_FLOOR_MAX_AGE_DAYS + 1)

    index = get_market_index_for_card(db_session, card.id)

    snk = find(index.source_values, "snkrdunk", "listing_floor")
    assert snk.eligible is False
    assert snk.stale is True
    assert "snkrdunk" in index.stale_sources


def test_floor_is_marked_listing_based(db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    snk = find(index.source_values, "snkrdunk", "listing_floor")
    assert snk.evidence_type == "listing"


def test_floor_is_never_transaction_evidence(db_session):
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    snkrdunk_sold(db_session, card, snkrdunk, price_jpy=1000, days_ago=1)  # only 1, < min sample
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    for value in index.source_values:
        if value.reference_type == "listing_floor":
            assert value.evidence_type != "transaction"


# --- Index combination --------------------------------------------------------


def test_two_source_midpoint(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500)

    index = get_market_index_for_card(db_session, card.id)

    assert index.index_value_jpy == 1350
    assert index.coverage_status == "full"
    assert index.confidence == "high"
    assert index.source_count == 2


def test_midpoint_ending_in_half_rounds_half_up(db_session):
    """Reproduces the real staging card whose SNKRDUNK sold median (1425)
    and Yuyu-Tei sell (1200) land exactly on a .5 midpoint (1312.5) -
    documented rounding policy is round-half-up, so this must be 1313, not
    1312 (Python's built-in round() would give 1312 via round-half-to-even -
    this asserts the module does NOT use that)."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200)
    for price in (1400, 1400, 1400, 1400, 1450, 1450, 1450, 1450):
        snkrdunk_sold(db_session, card, snkrdunk, price_jpy=price, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    assert index.index_value_jpy == 1313


def test_one_source_limited_coverage(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200)

    index = get_market_index_for_card(db_session, card.id)

    assert index.index_value_jpy == 1200
    assert index.coverage_status == "limited"
    assert index.confidence == "medium"
    assert index.source_count == 1


def test_zero_source_unavailable_state(db_session):
    card = make_card(db_session)

    index = get_market_index_for_card(db_session, card.id)

    assert index.index_value_jpy is None
    assert index.coverage_status == "none"
    assert index.confidence == "low"
    assert index.source_count == 0


def test_freshest_and_stalest_timestamps_are_accurate(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=3)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    assert index.freshest_observation_at is not None
    assert index.stalest_eligible_source_at is not None
    assert index.stalest_eligible_source_at <= index.freshest_observation_at


def test_calculated_at_is_utc(db_session):
    card = make_card(db_session)
    index = get_market_index_for_card(db_session, card.id)
    assert index.calculated_at.tzinfo is not None
    assert index.calculated_at.utcoffset().total_seconds() == 0


def test_stable_output_ordering(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500)

    first = get_market_index_for_card(db_session, card.id)
    second = get_market_index_for_card(db_session, card.id)

    assert [v.source for v in first.source_values] == [v.source for v in second.source_values]
    assert [v.reference_type for v in first.source_values] == [
        v.reference_type for v in second.source_values
    ]


def test_no_mutation_of_stored_observations(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    obs = yuyutei_sell(db_session, card, yuyutei, price_jpy=1200)

    get_market_index_for_card(db_session, card.id)

    db_session.refresh(obs)
    assert obs.price_jpy == 1200
    assert obs.stock_status == "in_stock"


def test_batch_query_does_not_scale_with_card_count(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    card_ids = []
    for i in range(5):
        card = make_card(db_session, card_code=f"OP01-{i:03d}")
        yuyutei_sell(db_session, card, yuyutei, price_jpy=1000 + i)
        snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500 + i)
        # Captured as a plain int now, not read off `card` later - every
        # subsequent commit() in this loop expires all ORM objects in the
        # session (SQLAlchemy's default expire_on_commit), so a later
        # `card.id` access would trigger its own lazy-reload SELECT per
        # card - a test artifact that would masquerade as the very N+1 this
        # test exists to catch.
        card_ids.append(card.id)

    counts = {"n": 0}

    def _count(*args, **kwargs):
        counts["n"] += 1

    from sqlalchemy import event

    # Bound to the session's own engine (db_session.get_bind()) rather than
    # importing it from tests.conftest - see tests/_auth_helpers.py's
    # docstring for why `from tests.conftest import ...` is unsafe here (it
    # re-executes conftest.py as a second module, pointing the app at a
    # second, tables-less in-memory engine).
    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", _count)
    try:
        counts["n"] = 0
        get_market_index_for_cards(db_session, [card_ids[0]])
        one_card_queries = counts["n"]

        counts["n"] = 0
        get_market_index_for_cards(db_session, card_ids)
        five_card_queries = counts["n"]
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert five_card_queries == one_card_queries


# --- API ------------------------------------------------------------------


def test_market_index_endpoint_valid_card(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200)

    response = client.get(f"/cards/{card.id}/market-index")

    assert response.status_code == 200
    body = response.json()
    assert body["card_id"] == card.id
    assert body["index_value_jpy"] == 1200
    assert body["coverage_status"] == "limited"
    assert body["index_version"] == 1
    assert body["calculation_method"] == "median_of_sources"


def test_market_index_endpoint_missing_card(client, db_session):
    response = client.get("/cards/999999/market-index")
    assert response.status_code == 404


def test_market_index_endpoint_public_access(db_session):
    card = make_card(db_session)
    anon_client = TestClient(app)  # no Authorization/X-Admin-Token headers
    response = anon_client.get(f"/cards/{card.id}/market-index")
    assert response.status_code == 200


def test_market_index_endpoint_no_secrets_in_response(client, db_session):
    card = make_card(db_session)
    response = client.get(f"/cards/{card.id}/market-index")
    body_text = response.text.lower()
    assert "admin_token" not in body_text
    assert "password" not in body_text
    assert "secret" not in body_text


def test_catalogue_endpoint_returns_market_index_per_item(client, db_session):
    yuyutei = make_source(db_session, "yuyutei")
    make_source(db_session, "snkrdunk")
    card_a = make_card(db_session, card_code="OP01-001")
    card_b = make_card(db_session, card_code="OP01-002")
    yuyutei_sell(db_session, card_a, yuyutei, price_jpy=1200)

    response = client.get("/cards/catalogue")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    by_code = {item["card_code"]: item for item in body["items"]}
    assert by_code["OP01-001"]["market_index"]["index_value_jpy"] == 1200
    assert by_code["OP01-002"]["market_index"]["index_value_jpy"] is None
    assert "pagination" in body


def test_catalogue_endpoint_pagination(client, db_session):
    for i in range(3):
        make_card(db_session, card_code=f"OP01-{i:03d}")

    response = client.get("/cards/catalogue", params={"limit": 2, "offset": 0})
    body = response.json()
    assert len(body["items"]) == 2
    assert body["pagination"]["has_next"] is True

    response2 = client.get("/cards/catalogue", params={"limit": 2, "offset": 2})
    body2 = response2.json()
    assert len(body2["items"]) == 1
    assert body2["pagination"]["has_next"] is False


def test_catalogue_endpoint_index_sort_places_unavailable_last(client, db_session):
    yuyutei = make_source(db_session, "yuyutei")
    priced = make_card(db_session, card_code="OP01-001")
    unpriced = make_card(db_session, card_code="OP01-002")
    yuyutei_sell(db_session, priced, yuyutei, price_jpy=1200)

    response = client.get("/cards/catalogue", params={"sort": "index_desc"})
    codes = [item["card_code"] for item in response.json()["items"]]
    assert codes == ["OP01-001", "OP01-002"]

    response_asc = client.get("/cards/catalogue", params={"sort": "index_asc"})
    codes_asc = [item["card_code"] for item in response_asc.json()["items"]]
    assert codes_asc == ["OP01-001", "OP01-002"]
