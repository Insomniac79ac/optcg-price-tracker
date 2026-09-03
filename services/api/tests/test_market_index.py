"""app.services.market_index - Market Index v1 (see docs/market_index.md
for the product rules asserted here) - and the two routes that expose it,
GET /cards/{id}/market-index and GET /cards/catalogue."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models import Card, PriceObservation, Source
from app.services.market_index import (
    CALCULATION_METHOD,
    INDEX_VERSION,
    SNKRDUNK_FLOOR_MAX_AGE_DAYS,
    SNKRDUNK_SOLD_MIN_SAMPLE,
    SNKRDUNK_SOLD_WINDOW_DAYS,
    YUYUTEI_SELL_MAX_AGE_DAYS,
    _compute_index_fields,
    _SourceValue,
    get_market_index_for_card,
    get_market_index_for_cards,
)
from app.services.source_semantics import SOURCE_SEMANTICS, SOURCE_SEMANTICS_VERSION

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


# _compute_index_fields works on the same naive-UTC instant the resolvers use.
NAIVE_NOW = NOW.replace(tzinfo=None)


def _source_value(
    source: str,
    reference_type: str,
    evidence_type: str,
    value_jpy: int | None,
    *,
    eligible: bool = True,
    fallback_used: bool = False,
    stale: bool = False,
    constraint: str | None = None,
    ineligible_reason: str | None = None,
    sample_size: int | None = None,
) -> _SourceValue:
    """A source value built directly, for the combination-step tests that must
    not depend on a resolver existing for the source in question.

    The whole extensibility claim of v3 is that _compute_index_fields is
    source-agnostic - it consults no name, no reference_type and no evidence
    type. A test that can only construct values for sources with resolvers
    could never demonstrate that; one that hands the function an invented
    marketplace can."""
    return _SourceValue(
        source=source,
        reference_type=reference_type,
        evidence_type=evidence_type,
        value_jpy=value_jpy,
        observed_at=NAIVE_NOW - timedelta(days=1),
        sample_size=sample_size,
        stale=stale,
        eligible=eligible,
        fallback_used=fallback_used,
        ineligible_reason=ineligible_reason,
        constraint=constraint,
    )


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


def test_retail_sell_and_an_eligible_listing_floor_average(db_session):
    """The three-version history of one fixture, in one place.

    v1 published 1350 and called it full/high. v2 published 1200 and called it
    limited/medium - the floor carried fallback_used=true and stood aside. v3
    publishes 1350 again, but for a different reason than v1 did: not because
    the two values are interchangeable, but because both are eligible
    market-facing evidence and Market Index is their consensus. The floor is
    still labelled a listing rather than a sale; what it is no longer is
    weightless."""
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

    floor = find(index.source_values, "snkrdunk", "listing_floor")
    assert floor.value_jpy == 1500
    assert floor.eligible is True
    assert floor.contributes_to_index is True
    # Provenance survives and still says what kind of evidence this is - it
    # simply no longer decides the arithmetic.
    assert floor.fallback_used is True
    assert floor.reference_type == "listing_floor"
    assert floor.evidence_type == "listing"


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
    assert body["index_version"] == 3
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


# --- Source semantics: SNKRDUNK platform floor (Task 1C-2B) ------------------
#
# The product rule: a SNKRDUNK floor at or below the platform's minimum
# permitted listing price is not market evidence, so it must not contribute to
# the index - while its raw number stays visible with a `constraint` telling
# the client why it is not counted. The threshold itself lives only in
# app.services.source_semantics; nothing below hard-codes it, it is read from
# SOURCE_SEMANTICS so a rule change moves these tests with it.

PLATFORM_MINIMUM = SOURCE_SEMANTICS["snkrdunk"]["floor"].platform_minimum_jpy


def test_yuyutei_sell_is_untouched_by_snkrdunk_semantics(db_session):
    """A: the constrained-source rule is SNKRDUNK's floor rule, not a global
    price threshold - a Yuyu-Tei sell below it is ordinary market evidence."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=580, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    sell = find(index.source_values, "yuyutei", "retail_sell")
    assert sell.value_jpy == 580
    assert sell.eligible is True
    assert sell.constraint is None
    assert sell.ineligible_reason is None
    assert index.index_value_jpy == 580


def test_floor_well_above_the_minimum_is_unconstrained(db_session):
    """B: ¥1,500."""
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500, days_ago=1)

    snk = find(get_market_index_for_card(db_session, card.id).source_values,
               "snkrdunk", "listing_floor")
    assert snk.value_jpy == 1500
    assert snk.constraint is None
    assert snk.eligible is True
    assert snk.ineligible_reason is None


def test_floor_one_yen_above_the_minimum_is_unconstrained(db_session):
    """C: ¥1,001 - the first value the platform minimum does not explain."""
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=PLATFORM_MINIMUM + 1, days_ago=1)

    snk = find(get_market_index_for_card(db_session, card.id).source_values,
               "snkrdunk", "listing_floor")
    assert snk.value_jpy == 1001
    assert snk.constraint is None
    assert snk.eligible is True


def test_floor_exactly_at_the_minimum_is_constrained_and_ineligible(db_session):
    """D: ¥1,000 - the platform minimum itself, the single most common stored
    floor value in production."""
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=PLATFORM_MINIMUM, days_ago=1)

    snk = find(get_market_index_for_card(db_session, card.id).source_values,
               "snkrdunk", "listing_floor")
    assert snk.value_jpy == 1000  # D: the raw observed number is preserved
    assert snk.constraint == "platform_floor"
    assert snk.eligible is False
    assert snk.ineligible_reason == "platform_floor"
    assert snk.stale is False  # not disqualified by any pre-existing rule


def test_constrained_floor_keeps_its_raw_value_and_timestamp(db_session):
    """The value is excluded from the index, never blanked - a collector must
    still be able to see what SNKRDUNK actually reports."""
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    observation = snkrdunk_floor(db_session, card, snkrdunk, price_jpy=PLATFORM_MINIMUM, days_ago=1)

    snk = find(get_market_index_for_card(db_session, card.id).source_values,
               "snkrdunk", "listing_floor")
    assert snk.value_jpy == observation.price_jpy
    assert snk.observed_at is not None
    assert snk.reference_type == "listing_floor"
    assert snk.evidence_type == "listing"
    assert snk.fallback_used is True


def test_floor_below_the_minimum_is_excluded_under_its_own_reason(db_session):
    """E: ¥999 - excluded like the floor itself, but not described as it.
    SNKRDUNK documents ¥1,000 as its minimum, so a lower value contradicts the
    source contract and fails closed (Task 1C-2D)."""
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=PLATFORM_MINIMUM - 1, days_ago=1)

    snk = find(get_market_index_for_card(db_session, card.id).source_values,
               "snkrdunk", "listing_floor")
    assert snk.value_jpy == 999  # raw value untouched
    assert snk.constraint == "below_platform_minimum"
    assert snk.eligible is False
    assert snk.ineligible_reason == "below_platform_minimum"


def test_a_far_below_minimum_floor_is_excluded_the_same_way(db_session):
    """¥1 - nothing depends on proximity to the minimum, and an extractor
    error cannot set a card's Market Index to ¥1."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    snk = find(index.source_values, "snkrdunk", "listing_floor")
    assert snk.value_jpy == 1
    assert snk.constraint == "below_platform_minimum"
    assert snk.eligible is False
    # The remaining eligible source carries the index; ¥1 never touches it.
    assert index.index_value_jpy == 1200
    assert index.source_count == 1


def test_the_two_constrained_reasons_are_distinguishable_through_the_api(
    client, db_session
):
    """A client must be able to tell "this is the platform floor" from "this
    value should not exist" - they warrant different copy."""
    at_floor = make_card(db_session, card_code="OP01-100")
    below = make_card(db_session, card_code="OP01-101")
    snkrdunk = make_source(db_session, "snkrdunk")
    snkrdunk_floor(db_session, at_floor, snkrdunk, price_jpy=PLATFORM_MINIMUM, days_ago=1)
    snkrdunk_floor(db_session, below, snkrdunk, price_jpy=PLATFORM_MINIMUM - 1, days_ago=1)

    at_floor_body = client.get(f"/cards/{at_floor.id}/market-index").json()
    below_body = client.get(f"/cards/{below.id}/market-index").json()

    at_floor_value = next(sv for sv in at_floor_body["source_values"] if sv["source"] == "snkrdunk")
    below_value = next(sv for sv in below_body["source_values"] if sv["source"] == "snkrdunk")

    assert at_floor_value["constraint"] == "platform_floor"
    assert below_value["constraint"] == "below_platform_minimum"
    assert at_floor_value["constraint"] != below_value["constraint"]
    # Both raw values survive to the client.
    assert (at_floor_value["value_jpy"], below_value["value_jpy"]) == (1000, 999)


def test_a_below_minimum_only_card_has_no_index(db_session):
    """All-ineligible behaviour is unchanged by the new reason: an anomalous
    value is not evidence, so the honest answer stays "unavailable"."""
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=PLATFORM_MINIMUM - 1, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    assert index.index_value_jpy is None
    assert index.source_count == 0
    assert index.coverage_status == "none"
    assert index.confidence == "low"
    snk = find(index.source_values, "snkrdunk", "listing_floor")
    assert snk.value_jpy == 999  # still reported


def test_stale_reason_still_wins_over_below_platform_minimum(db_session):
    """ineligible_reason precedence is unchanged by the new verdict: a
    pre-existing rule keeps the reason, the semantic verdict stays in
    `constraint`."""
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    snkrdunk_floor(
        db_session, card, snkrdunk,
        price_jpy=PLATFORM_MINIMUM - 1, days_ago=SNKRDUNK_FLOOR_MAX_AGE_DAYS + 1,
    )

    snk = find(get_market_index_for_card(db_session, card.id).source_values,
               "snkrdunk", "listing_floor")
    assert snk.stale is True
    assert snk.ineligible_reason == "stale"
    assert snk.constraint == "below_platform_minimum"
    assert snk.eligible is False


def test_constrained_floor_does_not_drag_the_index_down(db_session):
    """F: the mixed case. Two sources present, but only the Yuyu-Tei one is
    real evidence, so the index is that value alone - NOT the midpoint of 580
    and 1000, which is what the pre-1C-2B behaviour produced."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=580, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=PLATFORM_MINIMUM, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    assert index.index_value_jpy == 580
    assert index.source_count == 1
    assert index.coverage_status == "limited"
    assert index.confidence == "medium"

    # The constrained value is excluded from the maths but still reported.
    snk = find(index.source_values, "snkrdunk", "listing_floor")
    assert snk.value_jpy == 1000
    assert snk.constraint == "platform_floor"


def test_all_sources_constrained_leaves_the_index_unavailable(db_session):
    """G: knowingly constrained evidence is not evidence - the honest answer
    is "unavailable", never a Market Index of ¥1,000."""
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=PLATFORM_MINIMUM, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    assert index.index_value_jpy is None
    assert index.source_count == 0
    assert index.coverage_status == "none"
    assert index.confidence == "low"

    # ...and the raw constrained value is still in the payload.
    snk = find(index.source_values, "snkrdunk", "listing_floor")
    assert snk.value_jpy == 1000
    assert snk.constraint == "platform_floor"


def test_stale_reason_still_wins_over_the_semantic_reason(db_session):
    """ineligible_reason precedence: a pre-existing eligibility rule keeps
    ownership of the reason string. A stale ¥1,000 floor is unusable *because
    it is stale*; the semantic verdict rides alongside in `constraint`."""
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    snkrdunk_floor(
        db_session, card, snkrdunk,
        price_jpy=PLATFORM_MINIMUM, days_ago=SNKRDUNK_FLOOR_MAX_AGE_DAYS + 1,
    )

    index = get_market_index_for_card(db_session, card.id)

    snk = find(index.source_values, "snkrdunk", "listing_floor")
    assert snk.stale is True
    assert snk.ineligible_reason == "stale"
    assert snk.constraint == "platform_floor"  # independently visible
    assert snk.eligible is False
    assert "snkrdunk" in index.stale_sources


def test_semantics_never_rescue_a_stale_but_unconstrained_floor(db_session):
    """The other half of "both gates must pass": semantic eligibility does not
    relax the freshness rule for an unconstrained value."""
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    snkrdunk_floor(
        db_session, card, snkrdunk,
        price_jpy=1500, days_ago=SNKRDUNK_FLOOR_MAX_AGE_DAYS + 1,
    )

    snk = find(get_market_index_for_card(db_session, card.id).source_values,
               "snkrdunk", "listing_floor")
    assert snk.constraint is None
    assert snk.eligible is False
    assert snk.ineligible_reason == "stale"


def test_sold_prices_are_never_platform_floor_constrained(db_session):
    """The platform-floor rule is about the minimum permitted *listing* price.
    A completed sale at the same value is a real transaction, so the sold path
    is unchanged - three sales at ¥1,000 still produce a ¥1,000 index."""
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    for _ in range(SNKRDUNK_SOLD_MIN_SAMPLE):
        snkrdunk_sold(db_session, card, snkrdunk, price_jpy=PLATFORM_MINIMUM, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    snk = find(index.source_values, "snkrdunk", "transaction_median")
    assert snk.value_jpy == 1000
    assert snk.eligible is True
    assert snk.constraint is None
    assert index.index_value_jpy == 1000


def test_a_constrained_floor_is_ignored_in_favour_of_enough_sold_data(db_session):
    """The sold branch still wins outright when the sample is there - the
    constrained floor is not even reached."""
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    for price in (1200, 1300, 1400):
        snkrdunk_sold(db_session, card, snkrdunk, price_jpy=price, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=PLATFORM_MINIMUM, days_ago=1)

    snk = find(get_market_index_for_card(db_session, card.id).source_values,
               "snkrdunk", "transaction_median")
    assert snk.reference_type == "transaction_median"
    assert snk.value_jpy == 1300
    assert snk.constraint is None
    assert snk.eligible is True


def test_constraint_is_exposed_through_the_api(client, db_session):
    """The field has to survive schema serialization, not just exist on the
    internal dataclass."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=580, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=PLATFORM_MINIMUM, days_ago=1)

    body = client.get(f"/cards/{card.id}/market-index").json()

    values = {sv["source"]: sv for sv in body["source_values"]}
    assert values["snkrdunk"]["constraint"] == "platform_floor"
    assert values["snkrdunk"]["value_jpy"] == 1000
    assert values["snkrdunk"]["eligible"] is False
    assert values["yuyutei"]["constraint"] is None
    assert body["index_value_jpy"] == 580


def test_constraint_defaults_to_null_for_every_other_value(client, db_session):
    """Backward compatibility: the new field is present and null everywhere it
    does not apply, including auxiliary values."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)
    yuyutei_buy(db_session, card, yuyutei, price_jpy=800, days_ago=1)

    body = client.get(f"/cards/{card.id}/market-index").json()

    for value in body["source_values"] + body["auxiliary_values"]:
        assert value["constraint"] is None


def test_classifier_is_actually_wired_into_the_resolver(db_session, monkeypatch):
    """Proves the production path calls classify_observation rather than
    re-deriving the rule locally: bypass the classifier with an always-
    unconstrained stub and the constrained-price behaviour disappears.

    Without this, every assertion above would still pass if the wiring were
    replaced by a duplicated `price_jpy <= 1000` check in market_index."""
    import app.services.market_index as market_index_module
    from app.services.source_semantics import SourceSemantics

    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=PLATFORM_MINIMUM, days_ago=1)

    monkeypatch.setattr(
        market_index_module, "classify_observation",
        lambda source, price_type, value_jpy: SourceSemantics(),
    )
    bypassed = get_market_index_for_card(db_session, card.id)

    snk = find(bypassed.source_values, "snkrdunk", "listing_floor")
    assert snk.constraint is None
    assert snk.eligible is True
    assert bypassed.index_value_jpy == 1000  # the pre-1C-2B behaviour


# --- Ruleset version metadata (Task 1C-2C) ----------------------------------
#
# A derived index has to say which source-normalisation ruleset produced it,
# so a stored or screenshotted number can later be traced back to the rules
# that interpreted its observations. Purely additive metadata - every
# assertion below also pins the pricing fields, because this must not have
# moved a single one of them.


def test_card_index_reports_the_source_semantics_version(db_session):
    """A: card-keyed responses carry the authoritative constant, not a copy."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    assert index.source_semantics_version == SOURCE_SEMANTICS_VERSION


def test_card_index_endpoint_exposes_the_source_semantics_version(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)

    body = client.get(f"/cards/{card.id}/market-index").json()

    assert body["source_semantics_version"] == SOURCE_SEMANTICS_VERSION
    # Index-level metadata, never per-source - the ruleset describes the whole
    # derived index, not one observation.
    for value in body["source_values"] + body["auxiliary_values"]:
        assert "source_semantics_version" not in value


def test_index_version_is_unchanged_and_still_reported(db_session):
    """E: the pre-existing version field keeps its own value and meaning."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    assert index.index_version == INDEX_VERSION
    assert index.calculation_method == CALCULATION_METHOD


def test_the_two_versions_are_independent_fields(db_session, monkeypatch):
    """F: they version different things - the combination algorithm and the
    per-source ruleset - and change on different cadences. Move one and the
    other must not follow, which also proves neither is a baked-in literal."""
    import app.services.market_index as market_index_module

    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)

    monkeypatch.setattr(market_index_module, "SOURCE_SEMANTICS_VERSION", 99)
    index = get_market_index_for_card(db_session, card.id)

    assert index.source_semantics_version == 99
    assert index.index_version == INDEX_VERSION  # unmoved


def test_constrained_pricing_result_is_byte_for_byte_unchanged(client, db_session):
    """C: the mixed constrained case from Task 1C-2B, re-pinned in full. Only
    source_semantics_version is new; every pricing field is as it was."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=580, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=PLATFORM_MINIMUM, days_ago=1)

    body = client.get(f"/cards/{card.id}/market-index").json()

    assert body["index_value_jpy"] == 580
    assert body["source_count"] == 1
    assert body["coverage_status"] == "limited"
    assert body["confidence"] == "medium"
    assert body["index_version"] == INDEX_VERSION
    assert body["calculation_method"] == "median_of_sources"
    assert body["stale_sources"] == []

    values = {sv["source"]: sv for sv in body["source_values"]}
    assert values["snkrdunk"]["value_jpy"] == 1000
    assert values["snkrdunk"]["constraint"] == "platform_floor"
    assert values["snkrdunk"]["eligible"] is False
    assert values["snkrdunk"]["ineligible_reason"] == "platform_floor"
    assert values["yuyutei"]["value_jpy"] == 580
    assert values["yuyutei"]["eligible"] is True
    assert values["yuyutei"]["constraint"] is None

    assert body["source_semantics_version"] == SOURCE_SEMANTICS_VERSION


def test_unconstrained_pricing_result_is_byte_for_byte_unchanged(client, db_session):
    """D: an unconstrained floor beside a retail sell. Source SEMANTICS still
    do nothing to it - eligible, no constraint, raw value intact - which is
    what this test was written to pin, and which is true under v1, v2 and v3
    alike. Only the COMBINATION has moved underneath it (1350 -> 1200 -> 1350),
    and it moved without SOURCE_SEMANTICS_VERSION changing even once: the two
    layers moving independently is exactly the separation the two version
    fields encode."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500, days_ago=1)

    body = client.get(f"/cards/{card.id}/market-index").json()

    assert body["index_value_jpy"] == 1350
    assert body["source_count"] == 2
    assert body["coverage_status"] == "full"
    assert body["confidence"] == "high"
    assert body["index_version"] == INDEX_VERSION

    values = {sv["source"]: sv for sv in body["source_values"]}
    assert values["snkrdunk"]["value_jpy"] == 1500
    assert values["snkrdunk"]["eligible"] is True
    assert values["snkrdunk"]["constraint"] is None
    assert values["snkrdunk"]["contributes_to_index"] is True

    assert body["source_semantics_version"] == SOURCE_SEMANTICS_VERSION


# --- Source price range (Task 2A-2) -----------------------------------------
#
# The index alone cannot express disagreement: with two sources the median is
# their midpoint, and ¥27,350 looks exactly as confident whether the sources
# were ¥24,900/¥29,800 (20% apart) or ¥120/¥1,500 (1150% apart). The range
# reports the spread of the very same values the index was built from.


def test_two_sources_report_their_spread(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=29800, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=24900, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    assert index.source_price_range is not None
    assert index.source_price_range.low_jpy == 24900
    assert index.source_price_range.high_jpy == 29800
    # The RANGE spans admissible evidence, and under v3 the contributors ARE
    # the admissible values - so the index sits inside its own range, which is
    # the relationship a reader naturally assumes and which v2 had broken.
    assert index.index_value_jpy == 27350
    assert index.source_count == 2


def test_range_is_independent_of_source_order(db_session):
    """min/max, not first/last - which source resolves first must not decide
    which end of the range it lands on."""
    ascending = make_card(db_session, card_code="OP01-101")
    descending = make_card(db_session, card_code="OP01-102")
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")

    # Yuyu-Tei cheaper than SNKRDUNK on one card, dearer on the other.
    yuyutei_sell(db_session, ascending, yuyutei, price_jpy=1200, days_ago=1)
    snkrdunk_floor(db_session, ascending, snkrdunk, price_jpy=1800, days_ago=1)
    yuyutei_sell(db_session, descending, yuyutei, price_jpy=1800, days_ago=1)
    snkrdunk_floor(db_session, descending, snkrdunk, price_jpy=1200, days_ago=1)

    first = get_market_index_for_card(db_session, ascending.id).source_price_range
    second = get_market_index_for_card(db_session, descending.id).source_price_range

    assert (first.low_jpy, first.high_jpy) == (1200, 1800)
    assert (second.low_jpy, second.high_jpy) == (1200, 1800)


def test_two_sources_agreeing_exactly_still_report_a_range(db_session):
    """A measured zero spread is a real finding - two independent sources
    landing on the same number is information, not a missing range."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1500, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    assert index.source_price_range is not None
    assert index.source_price_range.low_jpy == 1500
    assert index.source_price_range.high_jpy == 1500
    assert index.index_value_jpy == 1500


def test_single_eligible_source_has_no_range(db_session):
    """One source cannot disagree with itself; "¥1,200 – ¥1,200" would state a
    spread that was never measured."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    assert index.source_price_range is None
    assert index.source_count == 1
    assert index.index_value_jpy == 1200


def test_no_eligible_sources_has_no_range(db_session):
    card = make_card(db_session)

    index = get_market_index_for_card(db_session, card.id)

    assert index.source_price_range is None
    assert index.index_value_jpy is None
    assert index.source_count == 0


def test_constrained_floor_is_excluded_from_the_range(db_session):
    """The whole point: a value the index refused must not silently widen the
    range that describes the index. The raw ¥1,000 stays visible."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=220, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=PLATFORM_MINIMUM, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    assert index.source_price_range is None  # only one eligible source remains
    assert index.index_value_jpy == 220
    snk = find(index.source_values, "snkrdunk", "listing_floor")
    assert snk.value_jpy == 1000
    assert snk.constraint == "platform_floor"


def test_a_stale_source_is_excluded_from_the_range(db_session):
    """Same rule via a different exclusion: the range tracks eligibility, not
    the presence of a number."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)
    snkrdunk_floor(
        db_session, card, snkrdunk,
        price_jpy=9999, days_ago=SNKRDUNK_FLOOR_MAX_AGE_DAYS + 1,
    )

    index = get_market_index_for_card(db_session, card.id)

    assert index.source_price_range is None
    snk = find(index.source_values, "snkrdunk", "listing_floor")
    assert snk.value_jpy == 9999 and snk.eligible is False


def test_auxiliary_values_never_enter_the_range(db_session):
    """Yuyu-Tei's dealer buy price is not an index candidate, so it cannot be
    an endpoint of the index's range - even though it is a real JPY value on
    the same card."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)
    yuyutei_buy(db_session, card, yuyutei, price_jpy=300, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1800, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    # ¥300 is the lowest number on the card, and must not be the range's low.
    assert index.source_price_range.low_jpy == 1200
    assert index.source_price_range.high_jpy == 1800
    assert index.auxiliary_values[0].value_jpy == 300


def test_range_endpoints_come_from_the_indexed_values(db_session):
    """Structural guarantee rather than a coincidence of numbers: whatever the
    range reports must be present among the eligible source values."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=580, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    eligible = {sv.value_jpy for sv in index.source_values if sv.eligible}
    assert index.source_price_range.low_jpy in eligible
    assert index.source_price_range.high_jpy in eligible
    assert index.source_price_range.low_jpy <= index.index_value_jpy
    assert index.index_value_jpy <= index.source_price_range.high_jpy


def test_range_is_exposed_through_the_api(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=120, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500, days_ago=1)

    body = client.get(f"/cards/{card.id}/market-index").json()

    assert body["source_price_range"] == {"low_jpy": 120, "high_jpy": 1500}
    # The old staging control case, and the reason v3 keeps the range: two
    # sources genuinely disagree by an order of magnitude here, the index is
    # their midpoint, and the range is what tells a collector the midpoint is
    # sitting between two numbers rather than near either of them. Neither
    # value is discarded to make the headline number look calmer than the
    # evidence is.
    assert body["index_value_jpy"] == 810
    assert body["source_count"] == 2
    assert body["index_version"] == INDEX_VERSION


def test_range_is_null_not_missing_for_a_single_source(client, db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)

    body = client.get(f"/cards/{card.id}/market-index").json()

    assert "source_price_range" in body
    assert body["source_price_range"] is None


def test_adding_the_range_did_not_move_any_index_field(client, db_session):
    """Regression pin: adding source_price_range still moves no index field.

    The expected values below are index v3's - the combination rule is what
    has moved them, twice, and each time in a change that carried a version
    bump. The pin this test exists for is narrower and still holds through
    both: computing a range must not, by itself, disturb the number beside
    it."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500, days_ago=1)

    body = client.get(f"/cards/{card.id}/market-index").json()

    assert body["index_value_jpy"] == 1350
    assert body["source_count"] == 2
    assert body["coverage_status"] == "full"
    assert body["confidence"] == "high"
    assert body["calculation_method"] == "median_of_sources"
    assert body["index_version"] == 3
    assert body["source_semantics_version"] == 2


# --- Market Index v3: multi-source market consensus --------------------------
#
# v1 combined every eligible value as a co-equal addend, which on staging
# published ¥1,310 for a print no source priced above ¥120. v2 read that as an
# evidence-strength problem and gave any `fallback_used` value zero weight
# whenever a non-fallback source was present.
#
# v3 says the diagnosis was wrong. The ¥1,310 defect was an ADMISSIBILITY
# problem - a platform-minimum listing being treated as a price - and the
# platform-floor rule in source_semantics is what actually fixed it. A current
# asking price is weaker and different evidence from a completed sale, but it
# is not worth nothing, and an index that silently drops whole marketplaces is
# not a market consensus.
#
# So: contributors == admissible. `eligible` is the single gate, and
# `contributes_to_index` reports the result rather than applying a second
# filter of its own. The tests below pin both halves - that eligible values now
# all count, and that the admissibility rules which keep junk out are entirely
# untouched.


def test_a_listing_floor_alone_still_contributes(db_session):
    """Unchanged from v2, and for a reason worth keeping: a lone eligible
    listing floor was the one case v2 already let through, so this test passing
    identically across the version boundary shows v3 widened the rule rather
    than rewriting it."""
    card = make_card(db_session)
    snkrdunk = make_source(db_session, "snkrdunk")
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    floor = find(index.source_values, "snkrdunk", "listing_floor")
    assert floor.fallback_used is True
    assert floor.eligible is True
    assert floor.contributes_to_index is True
    assert index.index_value_jpy == 1500
    assert index.source_count == 1
    assert index.coverage_status == "limited"
    assert index.confidence == "medium"


def test_a_single_retail_sell_alone_contributes(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    sell = find(index.source_values, "yuyutei", "retail_sell")
    assert sell.fallback_used is False
    assert sell.contributes_to_index is True
    assert index.index_value_jpy == 1200
    assert index.source_count == 1


def test_two_eligible_asking_sources_both_contribute(db_session):
    """The case the whole v3 change exists for, and the product decision's own
    worked fixture: a Yuyu-Tei retail sell of ¥24,800 beside a SNKRDUNK current
    listing of ¥20,500 is two market-facing prices, and the index is the middle
    of them.

    Both are asking prices rather than completed sales. Neither is therefore
    downgraded relative to the other, and neither is dropped: with only asking
    prices available, the consensus of the asking prices is the honest answer,
    and it is what a collector comparing shops would compute themselves."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=24800, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=20500, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    sell = find(index.source_values, "yuyutei", "retail_sell")
    floor = find(index.source_values, "snkrdunk", "listing_floor")
    assert sell.contributes_to_index is True
    assert floor.contributes_to_index is True
    assert index.index_value_jpy == 22650
    assert index.source_count == 2
    assert index.coverage_status == "full"
    assert index.confidence == "high"
    assert (index.source_price_range.low_jpy, index.source_price_range.high_jpy) == (
        20500,
        24800,
    )


def test_an_extreme_asking_outlier_does_not_drag_a_three_source_median(db_session):
    """Three or more contributors, and the median's whole point.

    Two sources agree at roughly ¥20,000-¥21,000; a third asks ¥250,000, more
    than ten times either. Because the aggregate is a MEDIAN and not a mean,
    the outlier moves the answer by rank alone - it pushes the middle from the
    midpoint of the two sane values to the higher of them, and no further. A
    mean would have published ¥97,167 for a card two of three sources price
    around ¥20,000.

    This is the reason v3 can afford to admit asking prices without also
    needing a weighting scheme: the combination step is already robust to one
    source having an eccentric opinion, and stays robust as sources are added.

    Note the range still reports the ¥250,000 honestly. The index is not
    dragged by it; the collector is not hidden from it."""
    values = [
        _source_value("yuyutei", "retail_sell", "listing", 20500),
        _source_value("snkrdunk", "transaction_median", "transaction", 21000),
        _source_value("cardrush", "retail_sell", "listing", 250000),
    ]

    fields = _compute_index_fields(values, [], NAIVE_NOW)

    assert fields["index_value_jpy"] == 21000
    assert fields["source_count"] == 3
    assert fields["coverage_status"] == "full"
    assert fields["confidence"] == "high"
    assert all(sv.contributes_to_index is True for sv in fields["source_values"])
    # The mean the median is protecting against.
    assert fields["index_value_jpy"] != round((20500 + 21000 + 250000) / 3)
    assert (
        fields["source_price_range"].low_jpy,
        fields["source_price_range"].high_jpy,
    ) == (20500, 250000)


def test_a_generic_third_source_participates_with_no_special_casing(db_session):
    """A source whose name this module has never heard of - no constant, no
    resolver, no entry in any mapping - contributes exactly like the two that
    do have names.

    That is the extensibility claim stated as an executable fact. Card Rush,
    Mercado and Cardmarket are not implemented, and when they are, the
    combination step is not where the work will happen: _compute_index_fields
    reads `eligible` and `value_jpy` and nothing else, so a fourth source is a
    resolver and a line in a loop.

    Built through _compute_index_fields directly rather than through the
    database, because the point is precisely that no resolver needs to exist
    for this to hold."""
    values = [
        _source_value("yuyutei", "retail_sell", "listing", 1000),
        _source_value("snkrdunk", "listing_floor", "listing", 2000, fallback_used=True),
        _source_value("some_future_marketplace", "retail_sell", "listing", 3000),
    ]

    fields = _compute_index_fields(values, [], NAIVE_NOW)

    assert fields["index_value_jpy"] == 2000
    assert fields["source_count"] == 3
    roles = {sv.source: sv.contributes_to_index for sv in fields["source_values"]}
    assert roles == {
        "yuyutei": True,
        "snkrdunk": True,
        "some_future_marketplace": True,
    }


def test_a_transaction_median_beside_retail_sell_aggregates(db_session):
    """A sold median is the strongest thing SNKRDUNK can report, and it
    aggregates with Yuyu-Tei exactly as an eligible listing floor now does -
    which is the point: the combination step never asked what KIND of evidence
    this was, and under v3 it no longer asks anything else either."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)
    for _ in range(SNKRDUNK_SOLD_MIN_SAMPLE):
        snkrdunk_sold(db_session, card, snkrdunk, price_jpy=1500, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    median = find(index.source_values, "snkrdunk", "transaction_median")
    assert median.fallback_used is False
    assert median.contributes_to_index is True
    assert find(index.source_values, "yuyutei", "retail_sell").contributes_to_index is True
    assert index.index_value_jpy == 1350
    assert index.source_count == 2
    assert index.coverage_status == "full"
    assert index.confidence == "high"


def test_a_transaction_median_replaces_its_own_listing_floor(db_session):
    """ONE SOURCE, ONE VOTE - the invariant that makes "contributors ==
    admissible" safe.

    SNKRDUNK here has both a rich sold history AND a live listing floor. It
    reports the sold median only: the floor is not returned as a second
    source_value alongside it, so SNKRDUNK cannot appear twice in the median
    and cannot outvote Yuyu-Tei two-to-one on the strength of having more rows
    in the table.

    Under v2 this was enforced twice over - the resolver returned one value,
    and the role filter would have demoted the floor anyway. v3 removed the
    second belt, so the resolver's either/or is now the only thing standing
    between this fixture and a double-counted marketplace. Hence a test aimed
    squarely at it."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=9000, days_ago=1)
    for _ in range(SNKRDUNK_SOLD_MIN_SAMPLE):
        snkrdunk_sold(db_session, card, snkrdunk, price_jpy=1500, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    snkrdunk_values = [sv for sv in index.source_values if sv.source == "snkrdunk"]
    assert len(snkrdunk_values) == 1
    assert snkrdunk_values[0].reference_type == "transaction_median"
    assert snkrdunk_values[0].value_jpy == 1500

    assert index.source_count == 2
    assert index.index_value_jpy == 1350
    # The ¥9,000 floor is not in the aggregate, and not in the range either -
    # it was never a source_value at all, so nothing had to exclude it.
    assert (index.source_price_range.low_jpy, index.source_price_range.high_jpy) == (
        1200,
        1500,
    )


def test_two_non_fallback_sources_still_produce_full_high(db_session):
    """Nothing about ordinary multi-source aggregation was weakened - the
    ladder still reaches full/high, it just needs contributors to get there."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1000, days_ago=1)
    for price in (2000, 2000, 2000):
        snkrdunk_sold(db_session, card, snkrdunk, price_jpy=price, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    assert index.source_count == 2
    assert index.coverage_status == "full"
    assert index.confidence == "high"
    assert index.index_value_jpy == 1500
    assert index.source_price_range.low_jpy == 1000
    assert index.source_price_range.high_jpy == 2000


def test_a_constrained_listing_floor_enters_neither_range_nor_contributors(db_session):
    """THE REGRESSION THAT MATTERS MOST FOR v3.

    Removing the contributor filter widened what counts. It must not have
    widened what is ADMISSIBLE, and the SNKRDUNK platform-minimum exclusion is
    the rule that was actually doing the work in the ¥1,310 staging defect. A
    listing sitting at the marketplace's own minimum permitted ask is not a
    statement about this card's price, it is a statement about the
    marketplace's rules, and it stays out of the index, out of the range and
    out of the count - while still being shown, with its raw number, so a
    collector can see what SNKRDUNK is displaying."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    minimum = SOURCE_SEMANTICS["snkrdunk"]["floor"].platform_minimum_jpy
    yuyutei_sell(db_session, card, yuyutei, price_jpy=120, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=minimum, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    floor = find(index.source_values, "snkrdunk", "listing_floor")
    assert floor.eligible is False
    assert floor.constraint == "platform_floor"
    assert floor.contributes_to_index is False
    assert floor.value_jpy == minimum  # still shown
    assert index.source_price_range is None
    assert index.index_value_jpy == 120
    assert index.source_count == 1


def test_a_stale_listing_floor_enters_neither_range_nor_contributors(db_session):
    """Freshness is admissibility, and v3 did not touch it. An asking price
    counts because it is what the market is asking NOW; a week-old floor is not
    that, and gains nothing from the contributor rule having relaxed."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=120, days_ago=1)
    snkrdunk_floor(
        db_session, card, snkrdunk, price_jpy=2500,
        days_ago=SNKRDUNK_FLOOR_MAX_AGE_DAYS + 1,
    )

    index = get_market_index_for_card(db_session, card.id)

    floor = find(index.source_values, "snkrdunk", "listing_floor")
    assert floor.eligible is False
    assert floor.stale is True
    assert floor.contributes_to_index is False
    assert index.source_price_range is None
    assert index.index_value_jpy == 120


def test_an_auxiliary_value_enters_neither_range_nor_contributors(db_session):
    """Yuyu-Tei dealer buy is not an index candidate at all. It gets an explicit
    false rather than None: None would mean "unknown", and this is known."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)
    yuyutei_buy(db_session, card, yuyutei, price_jpy=600, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    buy = find(index.auxiliary_values, "yuyutei", "dealer_buy")
    assert buy.contributes_to_index is False
    assert buy.eligible is False
    assert index.source_price_range is None
    assert index.index_value_jpy == 1200
    assert index.source_count == 1


def test_the_range_still_spans_wide_disagreement(db_session):
    """The disagreement must remain visible. Two sources an order of magnitude
    apart still produce a two-endpoint range around the index, which is the
    field that stops ¥1,310 from reading as a confident number."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=120, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=2500, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    assert index.source_price_range.low_jpy == 120
    assert index.source_price_range.high_jpy == 2500
    assert index.index_value_jpy == 1310


def test_the_range_and_the_contributor_set_now_agree(db_session):
    """v2's most confusing published shape is gone.

    Under v2 a two-endpoint range beside `source_count = 1` was correct and
    intended: two values were admissible, one contributed. It was also
    genuinely hard to explain, and it is what forced "Reference only" onto a
    price nothing was wrong with. Under v3 the two sets are one set, so an
    n-endpoint range always describes exactly the n values the index was
    computed from.

    The range's own MEANING is unchanged - the spread of the admissible
    evidence. It is the contributor set that moved to meet it."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=580, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    assert index.source_count == 2
    assert index.coverage_status == "full"
    assert index.confidence == "high"
    assert index.source_price_range is not None
    assert (index.source_price_range.low_jpy, index.source_price_range.high_jpy) == (580, 1500)
    assert index.source_price_range.low_jpy <= index.index_value_jpy
    assert index.index_value_jpy <= index.source_price_range.high_jpy


def test_combination_never_rewrites_a_source_value(db_session):
    """Raw evidence is preserved exactly - value, timestamp, sample size,
    eligibility and semantics all survive the combination step untouched. The
    role field is the only thing the aggregate adds to a source value."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=120, days_ago=1)
    stored = snkrdunk_floor(db_session, card, snkrdunk, price_jpy=2500, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    floor = find(index.source_values, "snkrdunk", "listing_floor")
    assert floor.value_jpy == stored.price_jpy == 2500
    assert floor.observed_at == stored.observed_at
    assert floor.eligible is True
    assert floor.ineligible_reason is None
    assert floor.constraint is None
    assert floor.evidence_type == "listing"
    assert floor.sample_size is None


def test_contributor_role_is_independent_of_source_order(db_session):
    """The rule is a property of each value on its own, not a scan that stops
    at the first match, so which resolver ran first cannot change any value's
    role - and under v3 it cannot even change the median, since min/max and a
    sorted median are both order-independent."""
    card_a = make_card(db_session)
    card_b = make_card(db_session, card_code="OP01-002")
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    for card in (card_a, card_b):
        yuyutei_sell(db_session, card, yuyutei, price_jpy=120, days_ago=1)
        snkrdunk_floor(db_session, card, snkrdunk, price_jpy=2500, days_ago=1)

    indexes = get_market_index_for_cards(db_session, [card_a.id, card_b.id])

    for index in indexes.values():
        roles = {(sv.source, sv.reference_type): sv.contributes_to_index
                 for sv in index.source_values}
        assert roles == {("yuyutei", "retail_sell"): True,
                         ("snkrdunk", "listing_floor"): True}
        assert index.index_value_jpy == 1310

    reversed_roles = get_market_index_for_cards(db_session, [card_b.id, card_a.id])
    assert {k: v.index_value_jpy for k, v in reversed_roles.items()} == \
        {k: v.index_value_jpy for k, v in indexes.items()}


def test_every_current_source_value_carries_an_explicit_role(db_session):
    """None means "this payload predates the field", never "did not
    contribute" - so nothing the current resolver emits may leave it unset."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=120, days_ago=1)
    yuyutei_buy(db_session, card, yuyutei, price_jpy=60, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=2500, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    for sv in list(index.source_values) + list(index.auxiliary_values):
        assert sv.contributes_to_index in (True, False), sv


# --- What `confidence` and `coverage_status` actually claim ------------------
#
# Both are derived from ONE input - the number of contributing source values -
# and are a strict 1:1 relabelling of each other. Neither says anything about
# whether the sources AGREE, and v3 makes that gap wider than it was: an
# eligible current listing now contributes, so "2 sources / full / high" can
# describe two asking prices an order of magnitude apart.
#
# These tests pin that contract as an executable fact rather than a comment, so
# a future reader who is tempted to render "High confidence" beside a price has
# to delete an assertion that says, in so many words, that it would be a lie.
# The field that answers "how far apart are the sources?" is
# source_price_range, and the third test below shows the two moving
# independently.
#
# The correct response to a wide spread is NOT to grade it here. There is no
# calibrated threshold to grade it against, and inventing one would put a
# reliability claim in the payload that no evidence in this repo supports.


def test_wide_disagreement_still_reports_full_high(db_session):
    """A: the ¥120 / ¥2,500 case, which is a real staging shape.

    Two eligible sources disagree by more than 20x. The index is their
    midpoint, and `source_count`, `coverage_status` and `confidence` report
    exactly what they always report for two contributors - because counting is
    all they do. The disagreement is not hidden: it is fully published, in
    source_price_range."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=120, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=2500, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    assert index.index_value_jpy == 1310
    assert index.source_count == 2
    assert index.coverage_status == "full"
    assert index.confidence == "high"

    # ...and the spread that "high" says nothing about.
    assert (index.source_price_range.low_jpy, index.source_price_range.high_jpy) == (
        120,
        2500,
    )
    assert index.source_price_range.high_jpy > 20 * index.source_price_range.low_jpy


def test_exact_agreement_also_reports_full_high(db_session):
    """B: the other end of the same field.

    Two eligible sources report the identical yen figure - as strong an
    agreement as two sources can express - and the verdict is character-for-
    character what the 20x disagreement above produced. Read together with A,
    this is the proof that `confidence` carries no information about
    agreement: both extremes map to the same value."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=24800, days_ago=1)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=24800, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    assert index.index_value_jpy == 24800
    assert index.source_count == 2
    assert index.coverage_status == "full"
    assert index.confidence == "high"

    # A real, measured zero spread - not an absent range.
    assert (index.source_price_range.low_jpy, index.source_price_range.high_jpy) == (
        24800,
        24800,
    )


def test_confidence_is_contributor_count_metadata_and_range_is_independent(db_session):
    """C: the conclusion A and B are evidence for, stated directly.

    Across four fixtures whose spreads run from 1.00x to 20.83x, the
    (source_count, coverage_status, confidence) triple is a pure function of
    the contributor count and NOTHING else, while source_price_range varies
    freely. The two are independent axes and only one of them is about
    agreement.

    Includes a mixed-evidence case (a real sold median beside a retail asking
    price) to pin the other half of the contract: evidence TYPE does not move
    confidence either. A completed sale and a current listing score
    identically."""
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")

    identical = make_card(db_session, card_code="OP01-201")
    yuyutei_sell(db_session, identical, yuyutei, price_jpy=24800, days_ago=1)
    snkrdunk_floor(db_session, identical, snkrdunk, price_jpy=24800, days_ago=1)

    close = make_card(db_session, card_code="OP01-202")
    yuyutei_sell(db_session, close, yuyutei, price_jpy=24800, days_ago=1)
    snkrdunk_floor(db_session, close, snkrdunk, price_jpy=20500, days_ago=1)

    wide = make_card(db_session, card_code="OP01-203")
    yuyutei_sell(db_session, wide, yuyutei, price_jpy=120, days_ago=1)
    snkrdunk_floor(db_session, wide, snkrdunk, price_jpy=2500, days_ago=1)

    sold_median = make_card(db_session, card_code="OP01-204")
    yuyutei_sell(db_session, sold_median, yuyutei, price_jpy=24800, days_ago=1)
    for _ in range(SNKRDUNK_SOLD_MIN_SAMPLE):
        snkrdunk_sold(db_session, sold_median, snkrdunk, price_jpy=20500, days_ago=1)

    indexes = get_market_index_for_cards(
        db_session, [identical.id, close.id, wide.id, sold_median.id]
    )

    verdicts = {
        (idx.source_count, idx.coverage_status, idx.confidence)
        for idx in indexes.values()
    }
    assert verdicts == {(2, "full", "high")}, (
        "confidence/coverage must be a pure function of contributor count"
    )

    spreads = {
        card_id: idx.source_price_range.high_jpy / idx.source_price_range.low_jpy
        for card_id, idx in indexes.items()
    }
    # Four identical verdicts over four materially different spreads.
    assert len(set(round(s, 2) for s in spreads.values())) == 3
    assert round(spreads[identical.id], 2) == 1.00
    assert round(spreads[wide.id], 2) == 20.83

    # Evidence type is likewise invisible to the verdict: the sold-median card
    # contributes a "transaction" and a "listing" and still scores the same as
    # the card contributing two listings.
    evidence = {
        sv.evidence_type
        for sv in indexes[sold_median.id].source_values
        if sv.contributes_to_index
    }
    assert evidence == {"transaction", "listing"}


def test_index_version_is_three_and_source_semantics_version_is_two(db_session):
    """The two version fields move independently, and v3 is the clearest
    demonstration yet: the combination step changed completely while per-source
    interpretation did not change at all.

    Nothing about how a Yuyu-Tei sell price or a SNKRDUNK floor is READ moved
    in v3 - the same thresholds, the same platform-minimum rule, the same
    staleness windows, the same promotion handling. What moved is what happens
    to those readings afterwards. So INDEX_VERSION goes to 3 and
    SOURCE_SEMANTICS_VERSION stays at 2, and the numbers no longer coincide.

    The INDEX_VERSION bump is also what keeps app.services.market_index_change
    honest: it refuses to compare a v2 snapshot against a v3 live value, so the
    7d movement figure goes null for a week rather than reporting a
    methodology change as a price change."""
    assert INDEX_VERSION == 3
    assert SOURCE_SEMANTICS_VERSION == 2

    card = make_card(db_session)
    yuyutei = make_source(db_session, "yuyutei")
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, days_ago=1)

    index = get_market_index_for_card(db_session, card.id)

    assert index.index_version == 3
    assert index.source_semantics_version == 2
