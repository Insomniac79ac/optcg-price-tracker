"""Print-centric public read model (see app.api.prints, app.services.
print_pricing/print_market_index/print_catalogue) - proves that two
card_prints bridging through the same legacy card_id (the OP01-013 Sanji
base/parallel case described in the tranche brief) can never contaminate
each other's prices, Market Index, or history, and that the print catalogue
represents each collectible print as its own item.

Five real-shaped prints (Zoro parallel, Law parallel, Sanji parallel, Sanji
base, Ace base) are built here as the test dataset, matching the staging
verified-print set - Sanji base and Sanji parallel deliberately share one
legacy `cards` row (legacy card_id=13-equivalent), exactly like the real
data, so any test passing here only because the fixtures don't collide would
also fail to catch the real contamination bug.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    PriceObservation,
    ReleaseProduct,
    Source,
    SourceCardMapping,
)
from app.services.market_index import INDEX_VERSION
from app.services.source_semantics import SOURCE_SEMANTICS_VERSION

NOW = datetime.now(timezone.utc)


def make_source(db_session, name: str = "yuyutei") -> Source:
    source = db_session.query(Source).filter_by(name=name).one_or_none()
    if source is not None:
        return source
    source = Source(name=name, base_url=f"https://{name}.example.com")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def make_canonical(db_session, **overrides) -> CanonicalCard:
    fields = dict(
        card_code="OP01-013",
        name_en="Sanji",
        original_set_code="OP01",
        rarity="R",
        card_type="Character",
        colors=["red"],
    )
    fields.update(overrides)
    canonical = CanonicalCard(**fields)
    db_session.add(canonical)
    db_session.commit()
    db_session.refresh(canonical)
    return canonical


def make_release_product(db_session, official_code: str = "OP-01") -> ReleaseProduct:
    """A verified print's identity now includes its product, so every print
    fixture needs one - see ck_card_prints_verified_requires_fields."""
    product = (
        db_session.query(ReleaseProduct)
        .filter_by(source_catalogue="bandai_jp", official_code=official_code)
        .one_or_none()
    )
    if product is not None:
        return product
    product = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code=official_code,
        display_name=f"Booster {official_code}",
        first_seen_name=f"Booster {official_code}",
        source_series_id="550101",
        source_url="https://www.onepiece-cardgame.com/products/boosters/op01.php",
        verification_status="verified",
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def make_print(db_session, canonical: CanonicalCard, **overrides) -> CardPrint:
    fields = dict(
        canonical_card_id=canonical.id,
        language="jp",
        treatment="base",
        verification_status="verified",
        release_product_code="OP-01",
        artwork_key="art-1",
        image_url="https://images.example.com/print.jpg",
    )
    # Exact-print identity: product + official artwork variant. Defaulted here
    # (and kept unique per artwork_key) so every existing caller keeps
    # producing a legal verified print.
    fields.setdefault(
        "release_product_id", make_release_product(db_session, overrides.get("release_product_code") or "OP-01").id
    )
    fields.setdefault("official_asset_variant", _variant_for(overrides))
    fields.update(overrides)
    print_row = CardPrint(**fields)
    db_session.add(print_row)
    db_session.commit()
    db_session.refresh(print_row)
    return print_row


# artwork_key -> official_asset_variant, assigned first-seen. Exact-print
# identity now includes the artwork variant, so two fixture siblings of one
# canonical card must not land on the same one. Callers already vary
# artwork_key per print, so keying off it keeps every existing fixture legal
# without touching a single call site. Deterministic and stable: the same key
# always maps to the same variant.
_VARIANTS_BY_ARTWORK_KEY: dict[str, str] = {}


def _variant_for(overrides: dict) -> str:
    key = str(overrides.get("artwork_key") or "art-1")
    if key not in _VARIANTS_BY_ARTWORK_KEY:
        index = len(_VARIANTS_BY_ARTWORK_KEY)
        _VARIANTS_BY_ARTWORK_KEY[key] = "base" if index == 0 else f"p{index}"
    return _VARIANTS_BY_ARTWORK_KEY[key]


def make_legacy_card(db_session, **overrides) -> Card:
    fields = dict(card_code="OP01-013", set_code="OP01", rarity="R", language="jp")
    fields.update(overrides)
    card = Card(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_mapping(db_session, legacy_card: Card, source: Source, card_print: CardPrint, **overrides):
    fields = dict(
        card_id=legacy_card.id,
        source_id=source.id,
        card_print_id=card_print.id,
        source_card_id=f"ext-{card_print.id}",
    )
    fields.update(overrides)
    mapping = SourceCardMapping(**fields)
    db_session.add(mapping)
    db_session.commit()
    db_session.refresh(mapping)
    return mapping


def make_observation(
    db_session,
    legacy_card: Card,
    source: Source,
    mapping: SourceCardMapping | None,
    card_print: CardPrint | None,
    **overrides,
) -> PriceObservation:
    fields = dict(
        card_id=legacy_card.id,
        source_id=source.id,
        price_type="sell",
        price_jpy=1000,
        stock_status="in_stock",
        source_card_mapping_id=mapping.id if mapping is not None else None,
        card_print_id=card_print.id if card_print is not None else None,
    )
    fields.update(overrides)
    obs = PriceObservation(**fields)
    db_session.add(obs)
    db_session.commit()
    db_session.refresh(obs)
    return obs


@pytest.fixture()
def five_prints(db_session):
    """Builds the five-print staging-shaped dataset. Returns a dict of
    everything callers need: prints, their canonical cards, the shared
    legacy card the two Sanji prints bridge through, and the source."""
    source = make_source(db_session)

    zoro_canonical = make_canonical(
        db_session, card_code="OP01-025", name_en="Roronoa Zoro", rarity="SR"
    )
    zoro_legacy = make_legacy_card(db_session, card_code="OP01-025", rarity="SR")
    zoro_parallel = make_print(
        db_session, zoro_canonical, treatment="parallel", artwork_key="zoro-parallel"
    )
    zoro_mapping = make_mapping(db_session, zoro_legacy, source, zoro_parallel)
    make_observation(
        db_session, zoro_legacy, source, zoro_mapping, zoro_parallel,
        price_jpy=3000, stock_status="in_stock", observed_at=NOW,
    )

    law_canonical = make_canonical(
        db_session, card_code="OP01-060", name_en="Trafalgar Law", rarity="SR"
    )
    law_legacy = make_legacy_card(db_session, card_code="OP01-060", rarity="SR")
    law_parallel = make_print(
        db_session, law_canonical, treatment="parallel", artwork_key="law-parallel"
    )
    law_mapping = make_mapping(db_session, law_legacy, source, law_parallel)
    make_observation(
        db_session, law_legacy, source, law_mapping, law_parallel,
        price_jpy=2500, stock_status="in_stock", observed_at=NOW,
    )

    # The critical case: Sanji base and Sanji parallel bridge through the
    # SAME legacy card row, exactly like the real OP01-013 data.
    sanji_canonical = make_canonical(db_session, card_code="OP01-013", name_en="Sanji", rarity="R")
    sanji_legacy = make_legacy_card(db_session, card_code="OP01-013", rarity="R")
    sanji_parallel = make_print(
        db_session, sanji_canonical, treatment="parallel", artwork_key="sanji-parallel"
    )
    sanji_base = make_print(
        db_session, sanji_canonical, treatment="base", artwork_key="sanji-base"
    )
    sanji_parallel_mapping = make_mapping(db_session, sanji_legacy, source, sanji_parallel)
    sanji_base_mapping = make_mapping(db_session, sanji_legacy, source, sanji_base)
    sanji_parallel_obs = make_observation(
        db_session, sanji_legacy, source, sanji_parallel_mapping, sanji_parallel,
        price_jpy=1980, stock_status="out_of_stock", observed_at=NOW,
    )
    sanji_base_obs = make_observation(
        db_session, sanji_legacy, source, sanji_base_mapping, sanji_base,
        price_jpy=120, stock_status="in_stock", observed_at=NOW,
    )

    ace_canonical = make_canonical(db_session, card_code="OP01-002", name_en="Portgas D. Ace", rarity="SR")
    ace_legacy = make_legacy_card(db_session, card_code="OP01-002", rarity="SR")
    ace_base = make_print(db_session, ace_canonical, treatment="base", artwork_key="ace-base")
    ace_mapping = make_mapping(db_session, ace_legacy, source, ace_base)
    make_observation(
        db_session, ace_legacy, source, ace_mapping, ace_base,
        price_jpy=800, stock_status="in_stock", observed_at=NOW,
    )

    return {
        "source": source,
        "sanji_legacy": sanji_legacy,
        "sanji_canonical": sanji_canonical,
        "sanji_parallel": sanji_parallel,
        "sanji_base": sanji_base,
        "sanji_parallel_obs": sanji_parallel_obs,
        "sanji_base_obs": sanji_base_obs,
        "zoro_parallel": zoro_parallel,
        "law_parallel": law_parallel,
        "ace_base": ace_base,
    }


# --- Sanji separation: the core contamination-proof scenario --------------


def test_sanji_parallel_market_index_sees_only_its_own_observation(client, five_prints):
    print_id = five_prints["sanji_parallel"].id
    response = client.get(f"/prints/{print_id}/market-index")
    assert response.status_code == 200
    body = response.json()

    assert body["card_print_id"] == print_id
    yuyutei_sell = next(sv for sv in body["source_values"] if sv["source"] == "yuyutei")
    assert yuyutei_sell["value_jpy"] == 1980
    # Stock has no effect on eligibility (product decision) - the parallel's
    # out-of-stock observation is exactly as eligible as any in-stock one.
    assert yuyutei_sell["eligible"] is True
    assert yuyutei_sell["ineligible_reason"] is None
    assert body["index_value_jpy"] == 1980
    # The base print's 120 JPY must never appear anywhere in the parallel's
    # response.
    assert 120 not in [sv["value_jpy"] for sv in body["source_values"]]


def test_sanji_base_market_index_sees_only_its_own_observation(client, five_prints):
    print_id = five_prints["sanji_base"].id
    response = client.get(f"/prints/{print_id}/market-index")
    assert response.status_code == 200
    body = response.json()

    assert body["card_print_id"] == print_id
    yuyutei_sell = next(sv for sv in body["source_values"] if sv["source"] == "yuyutei")
    assert yuyutei_sell["value_jpy"] == 120
    assert yuyutei_sell["eligible"] is True
    assert body["index_value_jpy"] == 120
    # The parallel's 1,980 JPY must never appear anywhere in the base's
    # response.
    assert 1980 not in [sv["value_jpy"] for sv in body["source_values"]]


def test_sanji_prices_endpoints_are_disjoint(client, five_prints):
    parallel_id = five_prints["sanji_parallel"].id
    base_id = five_prints["sanji_base"].id

    parallel_resp = client.get(f"/prints/{parallel_id}/prices").json()
    base_resp = client.get(f"/prints/{base_id}/prices").json()

    parallel_obs_ids = {o["id"] for o in parallel_resp["observations"]}
    base_obs_ids = {o["id"] for o in base_resp["observations"]}

    assert five_prints["sanji_parallel_obs"].id in parallel_obs_ids
    assert five_prints["sanji_base_obs"].id not in parallel_obs_ids

    assert five_prints["sanji_base_obs"].id in base_obs_ids
    assert five_prints["sanji_parallel_obs"].id not in base_obs_ids

    assert parallel_obs_ids.isdisjoint(base_obs_ids)


def test_sanji_prints_share_legacy_card_but_stay_independent(client, five_prints):
    """Both prints bridge through the exact same legacy card_id - the read
    path must still keep them fully separate."""
    assert five_prints["sanji_parallel_obs"].card_id == five_prints["sanji_base_obs"].card_id

    parallel_index = client.get(f"/prints/{five_prints['sanji_parallel'].id}/market-index").json()
    base_index = client.get(f"/prints/{five_prints['sanji_base'].id}/market-index").json()

    assert parallel_index["index_value_jpy"] != base_index["index_value_jpy"]
    # Both eligible under one-source evidence - stock state has no bearing
    # on coverage/eligibility (product decision).
    assert parallel_index["coverage_status"] == "limited"
    assert base_index["coverage_status"] == "limited"


def test_sanji_prints_are_separate_catalogue_items(client, five_prints):
    response = client.get("/prints", params={"limit": 100})
    assert response.status_code == 200
    items = response.json()["items"]

    sanji_items = [i for i in items if i["card_code"] == "OP01-013"]
    assert len(sanji_items) == 2
    treatments = {i["treatment"] for i in sanji_items}
    assert treatments == {"base", "parallel"}

    parallel_item = next(i for i in sanji_items if i["treatment"] == "parallel")
    base_item = next(i for i in sanji_items if i["treatment"] == "base")
    assert parallel_item["market_index"]["index_value_jpy"] != base_item["market_index"]["index_value_jpy"]


def test_sanji_siblings_resolve_to_each_other(client, five_prints):
    parallel_detail = client.get(f"/prints/{five_prints['sanji_parallel'].id}").json()
    base_detail = client.get(f"/prints/{five_prints['sanji_base'].id}").json()

    assert [s["card_print_id"] for s in parallel_detail["siblings"]] == [five_prints["sanji_base"].id]
    assert [s["card_print_id"] for s in base_detail["siblings"]] == [five_prints["sanji_parallel"].id]


def test_sanji_uses_verified_canonical_metadata_not_legacy(client, five_prints):
    """The legacy Card rows in this fixture were built with rarity="R" too,
    so this specifically checks the response is sourced from CanonicalCard
    (card_code/rarity/card_type), not from the legacy cards table."""
    detail = client.get(f"/prints/{five_prints['sanji_base'].id}").json()
    assert detail["card_code"] == "OP01-013"
    assert detail["rarity"] == "R"
    assert detail["card_type"] == "Character"
    assert detail["name_en"] == "Sanji"


# --- all five prints appear independently ----------------------------------


def test_all_five_prints_appear_independently(client, five_prints):
    response = client.get("/prints", params={"limit": 100})
    items = response.json()["items"]
    assert len(items) == 5

    by_print_id = {i["card_print_id"]: i for i in items}
    assert by_print_id[five_prints["zoro_parallel"].id]["market_index"]["index_value_jpy"] == 3000
    assert by_print_id[five_prints["law_parallel"].id]["market_index"]["index_value_jpy"] == 2500
    assert by_print_id[five_prints["ace_base"].id]["market_index"]["index_value_jpy"] == 800
    assert by_print_id[five_prints["sanji_base"].id]["market_index"]["index_value_jpy"] == 120
    # Out-of-stock but fresh - still eligible (stock has no bearing on
    # eligibility).
    assert by_print_id[five_prints["sanji_parallel"].id]["market_index"]["index_value_jpy"] == 1980


# --- lineage-less legacy observations must never enter print pricing ------


def test_lineageless_observation_never_enters_print_pricing(client, db_session, five_prints):
    legacy = five_prints["sanji_legacy"]
    source = five_prints["source"]
    # A legacy, lineage-less observation sharing the same card_id/source as
    # both Sanji prints - card_print_id/source_card_mapping_id both null.
    stale_mock = PriceObservation(
        card_id=legacy.id,
        source_id=source.id,
        price_type="sell",
        price_jpy=99999,
        stock_status="in_stock",
        observed_at=NOW,
    )
    db_session.add(stale_mock)
    db_session.commit()

    base_index = client.get(f"/prints/{five_prints['sanji_base'].id}/market-index").json()
    parallel_index = client.get(f"/prints/{five_prints['sanji_parallel'].id}/market-index").json()

    values = [sv["value_jpy"] for sv in base_index["source_values"] + parallel_index["source_values"]]
    assert 99999 not in values


# --- sibling print with no observations shows no market data --------------


def test_print_without_observations_shows_no_market_data(client, db_session):
    canonical = make_canonical(
        db_session, card_code="OP01-999", name_en="Test Card Two Prints", rarity="C"
    )
    priced_print = make_print(db_session, canonical, treatment="base", artwork_key="priced")
    unpriced_print = make_print(db_session, canonical, treatment="parallel", artwork_key="unpriced")

    legacy = make_legacy_card(db_session, card_code="OP01-999", rarity="C")
    source = make_source(db_session)
    mapping = make_mapping(db_session, legacy, source, priced_print)
    make_observation(
        db_session, legacy, source, mapping, priced_print,
        price_jpy=500, stock_status="in_stock", observed_at=NOW,
    )

    priced_index = client.get(f"/prints/{priced_print.id}/market-index").json()
    unpriced_index = client.get(f"/prints/{unpriced_print.id}/market-index").json()

    assert priced_index["index_value_jpy"] == 500
    assert unpriced_index["index_value_jpy"] is None
    assert unpriced_index["coverage_status"] == "none"
    assert unpriced_index["source_values"][0]["ineligible_reason"] == "no_observation"

    unpriced_prices = client.get(f"/prints/{unpriced_print.id}/prices").json()
    assert unpriced_prices["observations"] == []
    assert unpriced_prices["series"] == []


# --- price history / trend -------------------------------------------------


def test_single_observation_is_insufficient_history(client, five_prints):
    response = client.get(f"/prints/{five_prints['sanji_base'].id}/prices")
    body = response.json()
    assert len(body["observations"]) == 1

    series = body["series"]
    assert len(series) == 1
    assert series[0]["sufficient_history"] is False
    assert series[0]["change_24h_pct"] is None
    assert series[0]["change_7d_pct"] is None
    assert series[0]["change_30d_pct"] is None


def test_trend_never_fabricates_change_without_a_real_baseline(client, db_session, five_prints):
    print_row = five_prints["sanji_base"]
    legacy = five_prints["sanji_legacy"]
    source = five_prints["source"]
    mapping = make_mapping(
        db_session, legacy, source, print_row, source_card_id="ext-sanji-base-2"
    )
    # A second observation only six hours old - no observation exists at or
    # before any of the 24h/7d/30d cutoffs, so every change must stay null.
    make_observation(
        db_session, legacy, source, mapping, print_row,
        price_jpy=130, stock_status="in_stock",
        observed_at=NOW - timedelta(hours=6),
    )

    response = client.get(f"/prints/{print_row.id}/prices")
    series = response.json()["series"]
    trend = next(s for s in series if s["price_type"] == "sell")
    assert trend["sufficient_history"] is True
    assert trend["change_24h_pct"] is None
    assert trend["change_7d_pct"] is None
    assert trend["change_30d_pct"] is None


def test_stock_transition_alone_never_creates_a_price_trend(client, db_session, five_prints):
    """Two observations 8 days apart with the IDENTICAL price but opposite
    stock_status - a stale->fresh in_stock/out_of_stock flip must never be
    read as a market movement. change_7d_pct must be exactly 0.0 (real,
    price-based "no change"), never null/fabricated by the stock flip."""
    print_row = five_prints["sanji_base"]
    legacy = five_prints["sanji_legacy"]
    source = five_prints["source"]
    mapping = make_mapping(
        db_session, legacy, source, print_row, source_card_id="ext-sanji-base-3"
    )
    make_observation(
        db_session, legacy, source, mapping, print_row,
        price_jpy=120, stock_status="out_of_stock",
        observed_at=NOW - timedelta(days=8),
    )

    response = client.get(f"/prints/{print_row.id}/prices")
    body = response.json()
    prices = [o["price_jpy"] for o in body["observations"]]
    assert prices == [120, 120]  # same price both times, only stock differs

    trend = next(s for s in body["series"] if s["price_type"] == "sell")
    assert trend["change_7d_pct"] == 0.0
    # No observation old enough for a real 30d baseline (8 days < 30) - must
    # stay null, never fabricated as 0.0 just because 7d resolved cleanly.
    assert trend["change_30d_pct"] is None


def test_parallel_and_base_history_are_never_equal(client, five_prints):
    parallel_prices = client.get(f"/prints/{five_prints['sanji_parallel'].id}/prices").json()
    base_prices = client.get(f"/prints/{five_prints['sanji_base'].id}/prices").json()

    parallel_prices_jpy = [o["price_jpy"] for o in parallel_prices["observations"]]
    base_prices_jpy = [o["price_jpy"] for o in base_prices["observations"]]

    assert parallel_prices_jpy != base_prices_jpy
    assert parallel_prices_jpy == [1980]
    assert base_prices_jpy == [120]


# --- stock state / evidence visibility -------------------------------------


def test_out_of_stock_observation_is_visible_and_eligible(client, five_prints):
    """Product decision: Yuyu-Tei stock has no effect on Market Index
    eligibility - an out-of-stock sell observation is both visible evidence
    and a fully eligible index input, identically to an in-stock one."""
    body = client.get(f"/prints/{five_prints['sanji_parallel'].id}/market-index").json()
    sv = next(v for v in body["source_values"] if v["source"] == "yuyutei")
    assert sv["value_jpy"] == 1980
    assert sv["eligible"] is True
    assert sv["ineligible_reason"] is None


def test_in_stock_and_out_of_stock_are_identically_eligible(client, five_prints):
    """Sanji base (in_stock) and Sanji parallel (out_of_stock) - same
    freshness, different stock - both eligible, both coverage=limited."""
    parallel = client.get(f"/prints/{five_prints['sanji_parallel'].id}/market-index").json()
    base = client.get(f"/prints/{five_prints['sanji_base'].id}/market-index").json()

    parallel_sv = next(v for v in parallel["source_values"] if v["source"] == "yuyutei")
    base_sv = next(v for v in base["source_values"] if v["source"] == "yuyutei")

    assert parallel_sv["eligible"] is True
    assert base_sv["eligible"] is True
    assert parallel["coverage_status"] == base["coverage_status"] == "limited"


def test_print_apis_no_longer_expose_stock(client, five_prints):
    """The print-centric public product model does not depend on Yuyu-Tei
    inventory - no response here should carry a stock/inventory field at
    any level (see PrintPriceObservationOut/PrintPriceSeriesTrendOut)."""
    print_id = five_prints["sanji_base"].id

    detail = client.get(f"/prints/{print_id}").json()
    assert "stock_status" not in detail
    assert "stock_status" not in detail["market_index"]
    for sv in detail["market_index"]["source_values"] + detail["market_index"]["auxiliary_values"]:
        assert "stock_status" not in sv

    prices = client.get(f"/prints/{print_id}/prices").json()
    for obs in prices["observations"]:
        assert "stock_status" not in obs
    for series in prices["series"]:
        assert "latest_stock_status" not in series
        assert "stock_status" not in series

    catalogue = client.get("/prints", params={"limit": 100}).json()
    for item in catalogue["items"]:
        assert "stock_status" not in item
        assert "stock_status" not in item["market_index"]


def test_404_for_unknown_print(client, db_session):
    assert client.get("/prints/999999").status_code == 404
    assert client.get("/prints/999999/market-index").status_code == 404
    assert client.get("/prints/999999/prices").status_code == 404


# --- two-source (Yuyu-Tei + SNKRDUNK) print scoping ------------------------
#
# Regression cover for the 2026-08-11 production-report error. The verification
# script used the LEGACY card-keyed helper, which merged Sanji base's Yuyu-Tei
# price with Sanji parallel's SNKRDUNK floor and reported one contaminated
# "card" row. The print endpoints were correct all along, but nothing here
# exercised SNKRDUNK at all - these tests close that gap.


@pytest.fixture
def sanji_two_source(db_session, five_prints):
    """Sanji parallel gets a SNKRDUNK floor; Sanji base deliberately gets
    none - exactly the real production shape (mapping 37 vs mapping 38)."""
    snkrdunk = make_source(db_session, name="snkrdunk")
    legacy = five_prints["sanji_legacy"]
    parallel = five_prints["sanji_parallel"]
    mapping = make_mapping(
        db_session, legacy, snkrdunk, parallel, source_card_id="OP01-013"
    )
    make_observation(
        db_session, legacy, snkrdunk, mapping, parallel,
        price_type="floor", price_jpy=1500, condition_label="D",
        stock_status=None, observed_at=NOW,
    )
    return five_prints


def _sources(client, print_id):
    body = client.get(f"/prints/{print_id}/market-index").json()
    return body, {sv["source"]: sv for sv in body["source_values"]}


def test_snkrdunk_floor_lands_only_on_the_print_it_was_observed_for(
    client, sanji_two_source
):
    _, parallel = _sources(client, sanji_two_source["sanji_parallel"].id)
    _, base = _sources(client, sanji_two_source["sanji_base"].id)

    assert parallel["snkrdunk"]["value_jpy"] == 1500
    assert parallel["snkrdunk"]["eligible"] is True
    # The sibling must not inherit it, despite sharing one legacy card row.
    assert base.get("snkrdunk", {}).get("value_jpy") is None


def test_sibling_prints_report_different_source_counts(client, sanji_two_source):
    parallel_body, _ = _sources(client, sanji_two_source["sanji_parallel"].id)
    base_body, _ = _sources(client, sanji_two_source["sanji_base"].id)

    assert parallel_body["source_count"] == 2
    assert parallel_body["coverage_status"] == "full"
    assert base_body["source_count"] == 1
    assert base_body["coverage_status"] == "limited"


def test_the_contaminated_legacy_pairing_never_appears_on_a_print(
    client, sanji_two_source
):
    """The exact bad row from the production report: the base print's
    Yuyu-Tei value paired with the parallel print's SNKRDUNK floor."""
    base_body, base = _sources(client, sanji_two_source["sanji_base"].id)
    base_yuyutei = base["yuyutei"]["value_jpy"]

    values = {sv["source"]: sv["value_jpy"] for sv in base_body["source_values"]}
    assert not (values.get("yuyutei") == base_yuyutei and values.get("snkrdunk") == 1500)


def test_print_index_is_keyed_by_card_print_id_not_card_id(client, sanji_two_source):
    """Both Sanji prints bridge through one legacy card_id. If the index were
    card-keyed, these two responses would be identical."""
    parallel_body, _ = _sources(client, sanji_two_source["sanji_parallel"].id)
    base_body, _ = _sources(client, sanji_two_source["sanji_base"].id)

    assert parallel_body["card_print_id"] != base_body["card_print_id"]
    assert parallel_body["index_value_jpy"] != base_body["index_value_jpy"]


def test_snkrdunk_floor_is_reported_as_a_listing_not_a_sale(client, sanji_two_source):
    _, parallel = _sources(client, sanji_two_source["sanji_parallel"].id)
    assert parallel["snkrdunk"]["reference_type"] == "listing_floor"
    assert parallel["snkrdunk"]["evidence_type"] == "listing"


def test_legacy_card_endpoint_does_merge_siblings_which_is_why_prints_exist(
    client, sanji_two_source
):
    """Documents the LEGACY behaviour deliberately kept for backward
    compatibility (see app.api.cards.get_card_market_index's docstring), and
    proves the fixture above is a genuine contamination trap rather than a
    dataset that could never collide.

    The legacy card row bridges both Sanji prints, so its card-keyed index
    pairs the BASE print's Yuyu-Tei price with the PARALLEL print's SNKRDUNK
    floor - the exact merged row that appeared in the 2026-08-11 production
    report. Nothing here asserts that merging is desirable; it asserts that
    it happens, so any future change that silently "fixes" the legacy path
    surfaces here instead of in a production report.
    """
    legacy_id = sanji_two_source["sanji_legacy"].id
    body = client.get(f"/cards/{legacy_id}/market-index").json()
    values = {sv["source"]: sv["value_jpy"] for sv in body["source_values"]}

    assert values.get("snkrdunk") == 1500  # came from the PARALLEL print

    parallel_body, _ = _sources(client, sanji_two_source["sanji_parallel"].id)
    base_body, _ = _sources(client, sanji_two_source["sanji_base"].id)
    parallel_yuyutei = next(
        sv["value_jpy"] for sv in parallel_body["source_values"] if sv["source"] == "yuyutei"
    )
    base_yuyutei = next(
        sv["value_jpy"] for sv in base_body["source_values"] if sv["source"] == "yuyutei"
    )
    # The merged row cannot equal both siblings at once - it is one print's
    # Yuyu-Tei value beside the other print's SNKRDUNK floor.
    assert base_yuyutei != parallel_yuyutei
    assert values.get("yuyutei") in {base_yuyutei, parallel_yuyutei}


# --- constrained SNKRDUNK floors stay print-scoped (Task 1C-2B) -------------
#
# Source semantics is applied inside a per-source resolver, which runs once per
# print. These prove that stays true: a constrained floor on one print must not
# suppress - or leak its constraint onto - its sibling, even though the two
# bridge through one legacy card row.


@pytest.fixture
def sanji_constrained_floor(db_session, five_prints):
    """Sanji parallel gets a SNKRDUNK floor at the platform minimum (¥1,000 -
    constrained); Sanji base gets an unconstrained ¥1,500 one. Deliberately
    the opposite verdict on each sibling, so any leakage flips an assertion."""
    snkrdunk = make_source(db_session, name="snkrdunk")
    legacy = five_prints["sanji_legacy"]
    parallel = five_prints["sanji_parallel"]
    base = five_prints["sanji_base"]

    parallel_mapping = make_mapping(
        db_session, legacy, snkrdunk, parallel, source_card_id="snkr-OP01-013-parallel"
    )
    base_mapping = make_mapping(
        db_session, legacy, snkrdunk, base, source_card_id="snkr-OP01-013-base"
    )
    make_observation(
        db_session, legacy, snkrdunk, parallel_mapping, parallel,
        price_type="floor", price_jpy=1000, condition_label="D",
        stock_status=None, observed_at=NOW,
    )
    make_observation(
        db_session, legacy, snkrdunk, base_mapping, base,
        price_type="floor", price_jpy=1500, condition_label="D",
        stock_status=None, observed_at=NOW,
    )
    return five_prints


def test_a_constrained_floor_does_not_constrain_its_sibling_print(
    client, sanji_constrained_floor
):
    _, parallel = _sources(client, sanji_constrained_floor["sanji_parallel"].id)
    _, base = _sources(client, sanji_constrained_floor["sanji_base"].id)

    assert parallel["snkrdunk"]["value_jpy"] == 1000
    assert parallel["snkrdunk"]["constraint"] == "platform_floor"
    assert parallel["snkrdunk"]["eligible"] is False

    # The sibling's own floor is above the minimum and entirely unaffected.
    assert base["snkrdunk"]["value_jpy"] == 1500
    assert base["snkrdunk"]["constraint"] is None
    assert base["snkrdunk"]["eligible"] is True


def test_a_constrained_floor_does_not_alter_a_sibling_index(
    client, sanji_constrained_floor
):
    """The parallel loses its SNKRDUNK contribution and falls back to its
    Yuyu-Tei value alone; the base keeps both sources."""
    parallel_body, _ = _sources(client, sanji_constrained_floor["sanji_parallel"].id)
    base_body, _ = _sources(client, sanji_constrained_floor["sanji_base"].id)

    assert parallel_body["index_value_jpy"] == 1980  # Yuyu-Tei only
    assert parallel_body["source_count"] == 1
    assert parallel_body["coverage_status"] == "limited"

    assert base_body["index_value_jpy"] == 810  # midpoint of 120 and 1500
    assert base_body["source_count"] == 2
    assert base_body["coverage_status"] == "full"


def test_a_constrained_sibling_floor_never_appears_on_the_other_print(
    client, sanji_constrained_floor
):
    """The 2026-08-11 contamination shape, retested with the new field: the
    constrained ¥1,000 must appear on exactly one print."""
    parallel_body, _ = _sources(client, sanji_constrained_floor["sanji_parallel"].id)
    base_body, _ = _sources(client, sanji_constrained_floor["sanji_base"].id)

    constrained = [
        sv for body in (parallel_body, base_body) for sv in body["source_values"]
        if sv["constraint"] == "platform_floor"
    ]
    assert len(constrained) == 1
    assert constrained[0]["value_jpy"] == 1000


# --- ruleset version metadata on the print-keyed payload (Task 1C-2C) -------


def test_print_index_reports_the_source_semantics_version(client, sanji_constrained_floor):
    """B: the print-keyed payload carries the same authoritative constant as
    the card-keyed one - both are built from one shared construction path, so
    they cannot report different rulesets for the same observation."""
    parallel_id = sanji_constrained_floor["sanji_parallel"].id
    body = client.get(f"/prints/{parallel_id}/market-index").json()

    assert body["source_semantics_version"] == SOURCE_SEMANTICS_VERSION
    assert body["index_version"] == INDEX_VERSION
    for value in body["source_values"] + body["auxiliary_values"]:
        assert "source_semantics_version" not in value


def test_print_catalogue_items_report_the_source_semantics_version(client, five_prints):
    catalogue = client.get("/prints", params={"limit": 100}).json()

    assert catalogue["items"]
    for item in catalogue["items"]:
        assert item["market_index"]["source_semantics_version"] == SOURCE_SEMANTICS_VERSION


def test_version_metadata_did_not_move_any_print_pricing_value(
    client, sanji_constrained_floor
):
    """C/D on the print path: the constrained parallel and its unconstrained
    sibling produce exactly the results Task 1C-2B established."""
    parallel_body, parallel = _sources(client, sanji_constrained_floor["sanji_parallel"].id)
    base_body, base = _sources(client, sanji_constrained_floor["sanji_base"].id)

    assert parallel_body["index_value_jpy"] == 1980
    assert parallel_body["source_count"] == 1
    assert parallel_body["coverage_status"] == "limited"
    assert parallel["snkrdunk"]["value_jpy"] == 1000
    assert parallel["snkrdunk"]["constraint"] == "platform_floor"
    assert parallel["snkrdunk"]["eligible"] is False

    assert base_body["index_value_jpy"] == 810
    assert base_body["source_count"] == 2
    assert base_body["coverage_status"] == "full"
    assert base["snkrdunk"]["value_jpy"] == 1500
    assert base["snkrdunk"]["constraint"] is None
    assert base["snkrdunk"]["eligible"] is True

    # ...and both still report the ruleset that produced them.
    assert parallel_body["source_semantics_version"] == SOURCE_SEMANTICS_VERSION
    assert base_body["source_semantics_version"] == SOURCE_SEMANTICS_VERSION


def test_below_minimum_floor_is_excluded_from_a_print_index(client, db_session, five_prints):
    """The print path shares market_index's resolver, so the Task 1C-2D
    verdict reaches print-keyed payloads too - and a ¥999 SNKRDUNK floor
    cannot drag a print's index below its real Yuyu-Tei evidence."""
    snkrdunk = make_source(db_session, name="snkrdunk")
    legacy = five_prints["sanji_legacy"]
    parallel = five_prints["sanji_parallel"]
    mapping = make_mapping(
        db_session, legacy, snkrdunk, parallel, source_card_id="snkr-below-minimum"
    )
    make_observation(
        db_session, legacy, snkrdunk, mapping, parallel,
        price_type="floor", price_jpy=999, condition_label="D",
        stock_status=None, observed_at=NOW,
    )

    body, sources = _sources(client, parallel.id)

    assert sources["snkrdunk"]["value_jpy"] == 999  # raw value preserved
    assert sources["snkrdunk"]["constraint"] == "below_platform_minimum"
    assert sources["snkrdunk"]["eligible"] is False
    assert body["index_value_jpy"] == 1980  # the Yuyu-Tei value alone
    assert body["source_count"] == 1
    assert body["coverage_status"] == "limited"

    # The sibling, which has no SNKRDUNK observation at all, is untouched.
    base_body, _ = _sources(client, five_prints["sanji_base"].id)
    assert base_body["index_value_jpy"] == 120


# --- source price range stays print-scoped (Task 2A-2) ---------------------


def test_sibling_prints_get_their_own_source_price_range(client, sanji_two_source):
    """The parallel has two eligible sources and therefore a range; the base
    has only Yuyu-Tei and must not inherit its sibling's spread, even though
    both bridge one legacy card row."""
    parallel_body, _ = _sources(client, sanji_two_source["sanji_parallel"].id)
    base_body, _ = _sources(client, sanji_two_source["sanji_base"].id)

    parallel_yuyutei = next(
        sv["value_jpy"] for sv in parallel_body["source_values"] if sv["source"] == "yuyutei"
    )
    assert parallel_body["source_price_range"] == {
        "low_jpy": min(parallel_yuyutei, 1500),
        "high_jpy": max(parallel_yuyutei, 1500),
    }
    assert base_body["source_count"] == 1
    assert base_body["source_price_range"] is None


def test_a_constrained_sibling_floor_produces_no_range(client, sanji_constrained_floor):
    """The parallel's ¥1,000 floor is excluded by source semantics, so it has
    one eligible source and no range - while the base, whose ¥1,500 floor is
    unconstrained, gets a real one."""
    parallel_body, _ = _sources(client, sanji_constrained_floor["sanji_parallel"].id)
    base_body, _ = _sources(client, sanji_constrained_floor["sanji_base"].id)

    assert parallel_body["source_count"] == 1
    assert parallel_body["source_price_range"] is None

    assert base_body["source_count"] == 2
    assert base_body["source_price_range"] == {"low_jpy": 120, "high_jpy": 1500}
    # ...and the index still sits inside its own range.
    assert (base_body["source_price_range"]["low_jpy"]
            <= base_body["index_value_jpy"]
            <= base_body["source_price_range"]["high_jpy"])


def test_print_catalogue_items_carry_the_range_field(client, sanji_two_source):
    catalogue = client.get("/prints", params={"limit": 100}).json()

    assert catalogue["items"]
    for item in catalogue["items"]:
        mi = item["market_index"]
        assert "source_price_range" in mi
        if mi["source_count"] >= 2:
            assert mi["source_price_range"] is not None
        else:
            assert mi["source_price_range"] is None
