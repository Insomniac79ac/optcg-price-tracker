"""Current-state market analytics (see app.services.market_analytics).

The invariants under test are about HONESTY, not arithmetic: a constrained
¥1,000 platform-floor listing is observed but never priced, a missing value is
never 0, a percentile over too few points is null with a reason rather than a
number, and every count is reachable by a source this build has never heard of
without a line of source-specific code.

Fixtures are built from the same factories as test_prints.py so the data shape
matches the real print-centric model - exact prints, a shared legacy card, and
observations scoped by card_print_id.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.services.market_analytics as market_analytics
from app.models import CardPrint, Source
from app.services.rarity_facets import ALIAS_MEMBERS, SP_CARD
from app.services.source_semantics import classify_observation
from app.services.market_analytics import (
    MIN_PERCENTILE_CONSTITUENTS,
    PRICE_BUCKETS,
    BasisError,
    parse_price_basis,
    percentile,
)

from test_prints import (  # noqa: F401  (fixtures are used by name)
    NOW,
    five_prints,
    make_canonical,
    make_legacy_card,
    make_mapping,
    make_observation,
    make_print,
    make_source,
)

# The SNKRDUNK platform minimum, as data. Nothing in the module under test
# looks at this number - it is classified by app.services.source_semantics -
# and these tests would pass unchanged if the platform raised it tomorrow.
PLATFORM_FLOOR_JPY = 1000


def overview(client, **params):
    response = client.get("/analytics/market/overview", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def bases(client):
    response = client.get("/analytics/market/bases")
    assert response.status_code == 200, response.text
    return {b["key"]: b for b in response.json()["bases"]}


# --- A. Market Index basis --------------------------------------------------


def test_market_index_is_the_default_basis(client, five_prints):
    body = overview(client)
    assert body["price_basis"] == "market_index"
    assert body["kind"] == "market_index"
    assert body["source"] is None
    # Scope is the whole active catalogue when nothing is filtered.
    assert body["scope"]["active_prints"] == 5
    assert body["coverage"]["usable_priced_prints"] >= 1


def test_market_index_reports_no_observed_or_constrained_count(client, five_prints):
    """Null, not 0. The index is derived from sources rather than observed and
    carries no constraint of its own, so both counts have no answer - and 0
    would be a claim that it does."""
    coverage = overview(client)["coverage"]
    assert coverage["observed_prints"] is None
    assert coverage["excluded_constrained_prints"] is None


# --- B/C. source bases ------------------------------------------------------


def test_yuyutei_basis_reports_its_own_instrument(client, five_prints):
    body = overview(client, price_basis="source:yuyutei")
    assert body["kind"] == "source"
    assert body["source"] == "yuyutei"
    # The public vocabulary, never the stored price_type.
    assert body["reference_type"] == "retail_sell"
    assert body["evidence_type"] == "listing"
    assert body["index_composition"] is None
    assert body["coverage"]["usable_priced_prints"] == 5


def test_snkrdunk_basis_reports_its_own_instrument(client, db_session, five_prints):
    snkrdunk = make_source(db_session, name="snkrdunk")
    legacy = five_prints["sanji_legacy"]
    parallel = five_prints["sanji_parallel"]
    mapping = make_mapping(db_session, legacy, snkrdunk, parallel, source_card_id="snk-1")
    make_observation(
        db_session, legacy, snkrdunk, mapping, parallel,
        price_type="floor", price_jpy=4020, stock_status=None, observed_at=NOW,
    )

    body = overview(client, price_basis="source:snkrdunk")
    assert body["reference_type"] == "listing_floor"
    assert body["evidence_type"] == "listing"
    assert body["coverage"]["observed_prints"] == 1
    assert body["coverage"]["usable_priced_prints"] == 1
    assert body["current_price"]["median_jpy"] == 4020


# --- D. the constrained ¥1,000 case ----------------------------------------


def test_platform_floor_is_observed_but_never_priced(client, db_session, five_prints):
    """The tranche's central honesty rule.

    A ¥1,000 platform-minimum listing is a real observation - the mapping
    works and the collector ran - so it counts as observed. It is not a market
    price, so it must not reach usable, the median, or any bucket.
    """
    snkrdunk = make_source(db_session, name="snkrdunk")
    legacy = five_prints["sanji_legacy"]
    base = five_prints["sanji_base"]
    mapping = make_mapping(db_session, legacy, snkrdunk, base, source_card_id="snk-floor")
    make_observation(
        db_session, legacy, snkrdunk, mapping, base,
        price_type="floor", price_jpy=PLATFORM_FLOOR_JPY, stock_status=None, observed_at=NOW,
    )

    body = overview(client, price_basis="source:snkrdunk")
    coverage = body["coverage"]
    assert coverage["observed_prints"] == 1
    assert coverage["excluded_constrained_prints"] == 1
    assert coverage["usable_priced_prints"] == 0

    price = body["current_price"]
    assert price["constituent_count"] == 0
    assert price["median_jpy"] is None
    assert price["unavailable_reason"] == "no_usable_prices"
    # And it is nowhere in the distribution.
    assert sum(b["count"] for b in body["distribution"]) == 0
    assert PLATFORM_FLOOR_JPY not in [b["lower_jpy"] for b in body["distribution"] if b["count"]]


def test_constrained_value_never_reaches_the_market_index_either(client, db_session, five_prints):
    snkrdunk = make_source(db_session, name="snkrdunk")
    canonical = make_canonical(db_session, card_code="OP09-001", name_en="Floor Only", rarity="C")
    print_row = make_print(db_session, canonical, treatment="base", artwork_key="floor-only")
    legacy = make_legacy_card(db_session, card_code="OP09-001", rarity="C")
    mapping = make_mapping(db_session, legacy, snkrdunk, print_row, source_card_id="snk-only")
    make_observation(
        db_session, legacy, snkrdunk, mapping, print_row,
        price_type="floor", price_jpy=PLATFORM_FLOOR_JPY, stock_status=None, observed_at=NOW,
    )

    index_body = overview(client)
    # The print is in scope and counted as active, but it is NOT priced.
    assert index_body["scope"]["active_prints"] == 6
    assert print_row.id is not None
    # The floor-only print adds an active print but no priced one.
    assert index_body["coverage"]["usable_priced_prints"] == 5


def test_an_eligible_constraint_is_never_counted_as_excluded(client, db_session, five_prints):
    """A `sale_price` observation is constrained AND usable.

    This is the distinction the field name exists for. A promotional price is
    a real price a collector can pay today - source_semantics keeps it
    eligible on purpose - so it must count as usable and must NOT appear as
    impaired coverage. Reading `constraint` alone would have reported the
    opposite.
    """
    before = overview(client, price_basis="source:yuyutei")
    band_before = next(b for b in before["distribution"] if b["lower_jpy"] == 300)["count"]
    usable_before = before["coverage"]["usable_priced_prints"]

    legacy = five_prints["sanji_legacy"]
    source = five_prints["source"]
    canonical = make_canonical(db_session, card_code="OP07-005", name_en="On Sale", rarity="C")
    print_row = make_print(db_session, canonical, treatment="base", artwork_key="on-sale")
    mapping = make_mapping(db_session, legacy, source, print_row, source_card_id="sale-1")
    make_observation(
        db_session, legacy, source, mapping, print_row,
        price_jpy=450, stock_status="in_stock", observed_at=NOW, promotion_state="sale",
    )

    # First prove the fixture really produced the constrained-BUT-ELIGIBLE
    # verdict, so this test cannot pass vacuously on an unconstrained row.
    semantics = classify_observation("yuyutei", "sell", 450, promotion_state="sale")
    assert semantics.constraint == "sale_price"
    assert semantics.eligible is True

    body = overview(client, price_basis="source:yuyutei")
    coverage = body["coverage"]
    # It is observed, it is usable, and it is NOT excluded.
    assert coverage["excluded_constrained_prints"] == 0
    assert coverage["usable_priced_prints"] == usable_before + 1
    # And its price really did enter the statistics: ¥450 lands in ¥300-999.
    band = next(b for b in body["distribution"] if b["lower_jpy"] == 300)
    assert band["count"] == band_before + 1


def test_excluded_and_usable_are_disjoint(client, db_session, five_prints):
    """The property a client depends on to render coverage as parts of a
    whole: nothing may be counted in both."""
    snkrdunk = make_source(db_session, name="snkrdunk")
    legacy = five_prints["sanji_legacy"]
    base = five_prints["sanji_base"]
    parallel = five_prints["sanji_parallel"]
    floor_map = make_mapping(db_session, legacy, snkrdunk, base, source_card_id="dj-floor")
    make_observation(
        db_session, legacy, snkrdunk, floor_map, base,
        price_type="floor", price_jpy=PLATFORM_FLOOR_JPY, stock_status=None, observed_at=NOW,
    )
    good_map = make_mapping(db_session, legacy, snkrdunk, parallel, source_card_id="dj-good")
    make_observation(
        db_session, legacy, snkrdunk, good_map, parallel,
        price_type="floor", price_jpy=8800, stock_status=None, observed_at=NOW,
    )

    coverage = overview(client, price_basis="source:snkrdunk")["coverage"]
    assert coverage["observed_prints"] == 2
    assert coverage["usable_priced_prints"] == 1
    assert coverage["excluded_constrained_prints"] == 1
    # Disjoint, and together they account for everything observed.
    assert (
        coverage["usable_priced_prints"] + coverage["excluded_constrained_prints"]
        == coverage["observed_prints"]
    )


# --- E. missing never becomes zero ------------------------------------------


def test_empty_scope_returns_nulls_and_reasons_never_zero(client, five_prints):
    """A filter that matches nothing must not answer '¥0'."""
    body = overview(client, rarity="NOT-A-RARITY")
    assert body["scope"]["active_prints"] == 0
    assert body["coverage"]["usable_priced_prints"] == 0
    # 0/0 is not 0% - it is no answer at all.
    assert body["coverage"]["coverage_pct"] is None
    price = body["current_price"]
    assert price["median_jpy"] is None and price["p10_jpy"] is None and price["p90_jpy"] is None
    assert price["unavailable_reason"] == "no_usable_prices"
    assert all(b["count"] == 0 for b in body["distribution"])


def test_unpriced_prints_are_unavailable_not_zero_yen(client, five_prints):
    body = overview(client)
    coverage = body["coverage"]
    assert coverage["unavailable_prints"] == (
        body["scope"]["active_prints"] - coverage["usable_priced_prints"]
    )
    # No bucket may absorb an unpriced print as if it cost nothing.
    assert sum(b["count"] for b in body["distribution"]) == coverage["usable_priced_prints"]


# --- F. observed but nothing usable ----------------------------------------


def test_source_with_observations_but_no_usable_values_is_unavailable(
    client, db_session, five_prints
):
    snkrdunk = make_source(db_session, name="snkrdunk")
    legacy = five_prints["sanji_legacy"]
    base = five_prints["sanji_base"]
    mapping = make_mapping(db_session, legacy, snkrdunk, base, source_card_id="snk-f")
    make_observation(
        db_session, legacy, snkrdunk, mapping, base,
        price_type="floor", price_jpy=PLATFORM_FLOOR_JPY, stock_status=None, observed_at=NOW,
    )

    body = overview(client, price_basis="source:snkrdunk")
    assert body["available"] is False
    assert body["unavailable_reason"] == "no_usable_prices_in_scope"
    # Observed is still truthfully 1: the platform DID report.
    assert body["coverage"]["observed_prints"] == 1


# --- G. unknown source ------------------------------------------------------


def test_unknown_source_is_answered_not_404(client, five_prints):
    """'Atlas does not price with that' is an answer, and every count stays a
    truthful zero rather than an error page."""
    body = overview(client, price_basis="source:cardmarket")
    assert body["available"] is False
    assert body["unavailable_reason"] == "source_not_configured"
    assert body["source"] == "cardmarket"
    assert body["reference_type"] is None and body["evidence_type"] is None
    assert body["coverage"]["usable_priced_prints"] == 0
    assert body["current_price"]["median_jpy"] is None


@pytest.mark.parametrize("bad", ["", "source:", "movers", "market_index:yuyutei", "source"])
def test_malformed_price_basis_is_rejected(client, five_prints, bad):
    if bad == "":
        # Empty means "unspecified", which defaults rather than errors.
        assert overview(client, price_basis=bad)["price_basis"] == "market_index"
        return
    assert client.get("/analytics/market/overview", params={"price_basis": bad}).status_code == 400


def test_basis_grammar_matches_the_series_endpoint():
    assert parse_price_basis(None).key == "market_index"
    assert parse_price_basis("source:anything").source_name == "anything"
    with pytest.raises(BasisError):
        parse_price_basis("yuyutei")


# --- H/I/J. filters ---------------------------------------------------------


def test_set_filter_narrows_the_scope(client, five_prints):
    all_prints = overview(client)["scope"]["active_prints"]
    filtered = overview(client, set="OP-01")
    assert 0 < filtered["scope"]["active_prints"] <= all_prints
    assert filtered["scope"]["set"] == "OP-01"


def test_rarity_filter_narrows_the_scope(client, five_prints):
    body = overview(client, rarity="SR")
    assert body["scope"]["rarity"] == "SR"
    assert body["scope"]["active_prints"] >= 1
    assert body["scope"]["active_prints"] < overview(client)["scope"]["active_prints"]


def test_filters_compose(client, five_prints):
    body = overview(client, set="OP-01", rarity="SR")
    assert body["scope"]["set"] == "OP-01" and body["scope"]["rarity"] == "SR"


# --- K. percentile behaviour ------------------------------------------------


def test_percentile_method_is_linear_interpolation():
    """R type 7 / numpy `linear`, stated so two clients cannot disagree."""
    values = [10, 20, 30, 40, 50]
    assert percentile(values, 0.5) == 30
    assert percentile(values, 0.10) == 14  # rank 0.4 between 10 and 20
    assert percentile(values, 0.90) == 46  # rank 3.6 between 40 and 50
    assert percentile([7], 0.10) == 7
    assert percentile([], 0.5) is None


def test_percentiles_are_withheld_below_the_constituent_floor(client, db_session, five_prints):
    # A narrowed scope, so the sample is genuinely too small for a decile.
    body = overview(client, price_basis="source:yuyutei", rarity="SR")
    count = body["current_price"]["constituent_count"]
    assert 0 < count < MIN_PERCENTILE_CONSTITUENTS
    # The median still stands - with n>=1 it is a real statement.
    assert body["current_price"]["median_jpy"] is not None
    assert body["current_price"]["p10_jpy"] is None
    assert body["current_price"]["p90_jpy"] is None
    assert body["current_price"]["unavailable_reason"] == "insufficient_constituents"


def test_percentiles_appear_once_there_are_enough_constituents(client, db_session, five_prints):
    """Same endpoint, same basis - only the constituent count changes."""
    legacy = five_prints["sanji_legacy"]
    source = five_prints["source"]
    for i in range(MIN_PERCENTILE_CONSTITUENTS):
        canonical = make_canonical(
            db_session, card_code=f"OP08-{i:03d}", name_en=f"Filler {i}", rarity="C"
        )
        print_row = make_print(db_session, canonical, treatment="base", artwork_key=f"fill-{i}")
        mapping = make_mapping(db_session, legacy, source, print_row, source_card_id=f"fill-{i}")
        make_observation(
            db_session, legacy, source, mapping, print_row,
            price_jpy=100 * (i + 1), stock_status="in_stock", observed_at=NOW,
        )

    price = overview(client, price_basis="source:yuyutei")["current_price"]
    assert price["constituent_count"] >= MIN_PERCENTILE_CONSTITUENTS
    assert price["p10_jpy"] is not None and price["p90_jpy"] is not None
    assert price["unavailable_reason"] is None
    assert price["p10_jpy"] <= price["median_jpy"] <= price["p90_jpy"]


# --- L. distribution integrity ---------------------------------------------


def test_distribution_total_equals_constituent_count(client, db_session, five_prints):
    snkrdunk = make_source(db_session, name="snkrdunk")
    legacy = five_prints["sanji_legacy"]
    parallel = five_prints["sanji_parallel"]
    mapping = make_mapping(db_session, legacy, snkrdunk, parallel, source_card_id="snk-dist")
    # A deliberately expensive card, to prove one SP cannot move the bands.
    make_observation(
        db_session, legacy, snkrdunk, mapping, parallel,
        price_type="floor", price_jpy=66000, stock_status=None, observed_at=NOW,
    )

    for basis in ("market_index", "source:yuyutei", "source:snkrdunk"):
        body = overview(client, price_basis=basis)
        total = sum(b["count"] for b in body["distribution"])
        assert total == body["current_price"]["constituent_count"], basis


def test_bucket_boundaries_are_fixed_and_server_defined(client, db_session, five_prints):
    """One ¥66,000 card must not redefine the bands for the commons beneath
    it, so the boundaries are identical with and without it."""
    before = [(b["lower_jpy"], b["upper_jpy"]) for b in overview(client)["distribution"]]

    snkrdunk = make_source(db_session, name="snkrdunk")
    legacy = five_prints["sanji_legacy"]
    parallel = five_prints["sanji_parallel"]
    mapping = make_mapping(db_session, legacy, snkrdunk, parallel, source_card_id="snk-sp")
    make_observation(
        db_session, legacy, snkrdunk, mapping, parallel,
        price_type="floor", price_jpy=66000, stock_status=None, observed_at=NOW,
    )

    after = [(b["lower_jpy"], b["upper_jpy"]) for b in overview(client)["distribution"]]
    assert before == after == [(low, high) for low, high, _ in PRICE_BUCKETS]
    # Top band is open-ended so nothing can fall outside the distribution.
    assert after[-1][1] is None


# --- M. Market Index composition -------------------------------------------


def test_index_composition_counts_single_and_multi_source_prints(client, db_session, five_prints):
    snkrdunk = make_source(db_session, name="snkrdunk")
    legacy = five_prints["sanji_legacy"]
    base = five_prints["sanji_base"]  # already has a Yuyu-Tei sell price
    mapping = make_mapping(db_session, legacy, snkrdunk, base, source_card_id="snk-multi")
    make_observation(
        db_session, legacy, snkrdunk, mapping, base,
        price_type="floor", price_jpy=5000, stock_status=None, observed_at=NOW,
    )

    composition = overview(client)["index_composition"]
    assert composition["multi_source_prints"] == 1
    assert composition["single_source_prints"] >= 1
    # The concept does not exist for a single platform.
    assert overview(client, price_basis="source:yuyutei")["index_composition"] is None


# --- N/O. genericity --------------------------------------------------------


def test_bases_are_derived_not_listed(client, db_session, five_prints):
    make_source(db_session, name="snkrdunk")
    listed = bases(client)
    assert "market_index" in listed
    assert listed["source:yuyutei"]["reference_type"] == "retail_sell"
    assert listed["source:snkrdunk"]["reference_type"] == "listing_floor"
    # No display label is served - wording stays in the single frontend
    # vocabulary (see MarketAnalyticsBasisOut).
    assert "label" not in listed["market_index"]


def test_auxiliary_instrument_can_never_become_a_basis(client, db_session, five_prints):
    """Yuyu-Tei's dealer buy is read and reported, but it is not a primary
    instrument, so it produces no basis key and the yuyutei basis keeps
    describing the retail instrument."""
    legacy = five_prints["sanji_legacy"]
    source = five_prints["source"]
    base = five_prints["sanji_base"]
    mapping = make_mapping(db_session, legacy, source, base, source_card_id="yuyu-buy")
    make_observation(
        db_session, legacy, source, mapping, base,
        price_type="buy", price_jpy=60, stock_status="in_stock", observed_at=NOW,
    )

    listed = bases(client)
    assert not any(key.endswith(":buy") or "buy" in key for key in listed)
    assert listed["source:yuyutei"]["reference_type"] == "retail_sell"
    # The dealer-buy number never enters the retail basis' statistics.
    body = overview(client, price_basis="source:yuyutei")
    assert 60 not in [body["current_price"]["median_jpy"], body["current_price"]["p10_jpy"]]


def test_unconfigured_source_row_yields_no_basis(client, db_session, five_prints):
    """A source that exists in the table but has no configured primary
    instrument is not offered - and nothing here needed its name to decide."""
    db_session.add(Source(name="cardrush", base_url="https://cardrush.example.com"))
    db_session.commit()
    assert "source:cardrush" not in bases(client)


def test_analytics_module_names_no_source_and_no_price_type():
    """The genericity guard, in the same shape test_prints.py already uses for
    the pricing endpoints.

    A rule like `if source == "snkrdunk"` or a VALID_SOURCES tuple is what the
    print-centric services were built to eliminate; this asserts the analytics
    layer never reintroduces one. Docstrings are stripped first because they
    are where these names SHOULD appear - the module explains at length which
    vocabulary is which.
    """
    import ast

    source = Path(market_analytics.__file__).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body[0].value.value = ""
    stripped = ast.unparse(tree)

    for banned in ("yuyutei", "snkrdunk", "VALID_SOURCES", "VALID_PRICE_TYPES"):
        assert banned not in stripped, f"{banned} appears in executable analytics code"
    # The stored price_type vocabulary must not be restated here either.
    for stored in ('"sell"', '"floor"', '"sold"', '"buy"', "'sell'", "'floor'"):
        assert stored not in stripped, f"stored price_type {stored} appears in analytics code"


def test_future_source_flows_through_with_no_code_change(client, db_session, five_prints, monkeypatch):
    """A hypothetical configured source reaches every count without a branch.

    Registered exactly as a real one would be - a `sources` row plus an entry
    in the instrument registry - and then asserted through the public endpoint.
    Nothing in app.services.market_analytics is touched.
    """
    from app.services import source_instruments

    db_session.add(Source(name="mercado", base_url="https://mercado.example.com"))
    db_session.commit()
    mercado = db_session.query(Source).filter_by(name="mercado").one()

    registry = dict(source_instruments.SOURCE_INSTRUMENTS)
    registry[("mercado", "ask")] = source_instruments.SourceInstrument(
        reference_type="marketplace_ask",
        evidence_type=source_instruments.EVIDENCE_LISTING,
        role=source_instruments.ROLE_PRIMARY,
    )
    monkeypatch.setattr(source_instruments, "SOURCE_INSTRUMENTS", registry)

    listed = bases(client)
    assert listed["source:mercado"]["reference_type"] == "marketplace_ask"
    assert listed["source:mercado"]["evidence_type"] == "listing"

    body = overview(client, price_basis="source:mercado")
    assert body["source"] == "mercado"
    assert body["reference_type"] == "marketplace_ask"
    # No observations yet, so it is honestly unavailable rather than ¥0.
    assert body["coverage"]["usable_priced_prints"] == 0
    assert body["current_price"]["median_jpy"] is None
    assert mercado.id is not None


# --- query shape ------------------------------------------------------------


def test_query_count_is_o1_in_catalogue_size(client, db_session, five_prints):
    """The N+1 guard, for every endpoint shape.

    QUERY BUDGET, as measured and reconciled:

      core aggregation (every request, every basis)             8
        1  scope        scoped_print_ids - card_prints JOIN canonical_cards
        2  narrowing    prints_with_observations - DISTINCT card_print_id
        3-8 index       get_market_index_for_prints: two latest-price fetches,
                        two `sources` lookups, one source-id lookup and one
                        recent-sold window fetch
      + basis discovery
        source:<name>   +2  (grouped observed count, source-existence check) = 10
        market_index    +0                                                   =  8
        /bases          +1  (enumerate `sources`)                            =  9
      + filter metadata +0  (set/rarity are WHERE clauses on query 1)

    The point is not the number - a legitimate extra query may be added. The
    point is that NONE of them is per-print, which is what this asserts by
    growing the catalogue and demanding the count not move.
    """
    from sqlalchemy import event

    legacy = five_prints["sanji_legacy"]
    source = five_prints["source"]
    make_source(db_session, name="snkrdunk")
    engine = db_session.get_bind()

    shapes = {
        "overview/market_index": ("/analytics/market/overview", {}),
        "overview/source": ("/analytics/market/overview", {"price_basis": "source:yuyutei"}),
        "overview/set-filter": ("/analytics/market/overview", {"set": "OP-01"}),
        "overview/rarity-filter": ("/analytics/market/overview", {"rarity": "SR"}),
        "bases": ("/analytics/market/bases", {}),
    }

    def count_queries(path, params):
        seen = []
        listener = lambda *a, **k: seen.append(1)  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            response = client.get(path, params=params)
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        assert response.status_code == 200, response.text
        return len(seen)

    small = {name: count_queries(*shape) for name, shape in shapes.items()}
    small_scope = client.get("/analytics/market/overview").json()["scope"]["active_prints"]

    for i in range(60):
        canonical = make_canonical(
            db_session, card_code=f"QQ{i:04d}", name_en=f"Bulk {i}", rarity="C"
        )
        print_row = make_print(db_session, canonical, treatment="base", artwork_key=f"qq-{i}")
        mapping = make_mapping(db_session, legacy, source, print_row, source_card_id=f"qq-{i}")
        make_observation(
            db_session, legacy, source, mapping, print_row,
            price_jpy=100 + i, stock_status="in_stock", observed_at=NOW,
        )

    large_scope = client.get("/analytics/market/overview").json()["scope"]["active_prints"]
    assert large_scope > small_scope * 10

    for name, shape in shapes.items():
        assert count_queries(*shape) == small[name], f"{name} query count grew with catalogue size"


def test_bases_query_count_is_o1_in_number_of_sources(client, db_session, five_prints):
    """Adding a source must not add a query.

    `list_bases` iterates sources in Python over indexes it already fetched,
    so a tenth platform costs the same round trips as a second one. Without
    this, the natural implementation - resolve each basis separately - would
    have been O(sources) and nobody would have noticed until Card Rush shipped.
    """
    from sqlalchemy import event

    engine = db_session.get_bind()

    def count_queries():
        seen = []
        listener = lambda *a, **k: seen.append(1)  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            response = client.get("/analytics/market/bases")
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        assert response.status_code == 200
        return len(seen)

    before = count_queries()
    for name in ("alpha", "beta", "gamma", "delta"):
        db_session.add(Source(name=name, base_url=f"https://{name}.example.com"))
    db_session.commit()
    assert count_queries() == before


# --- display vocabulary and access control ----------------------------------


def test_no_display_vocabulary_is_served_or_declared(client, db_session, five_prints):
    """The API must never grow a second set of collector-facing words.

    Platform and instrument wording lives in exactly one place -
    apps/web/src/lib/prints.ts `sourceDisplayName` and
    apps/web/src/lib/sourceEvidence.ts `instrumentLabel` - and every collector
    surface renders through it. A server-authored "Yuyu-Tei" here would be the
    second copy, and the two would disagree the first time either changed;
    that drift is exactly what put two different names for one reading on the
    print page before Analytics 0C removed it.

    So the identity fields (`source`, `reference_type`, `evidence_type`) are
    served and nothing else. Bucket labels are deliberately NOT covered by
    this rule: a price band is a server-defined range, not a platform's name,
    and the brief asks for the boundaries to come from the API.
    """
    make_source(db_session, name="snkrdunk")

    identity_fields = {"key", "kind", "source", "reference_type", "evidence_type"}
    for basis in bases(client).values():
        assert identity_fields <= set(basis)
        assert "label" not in basis
        assert "display_name" not in basis

    body = overview(client, price_basis="source:yuyutei")
    assert "label" not in body and "display_name" not in body
    assert body["source"] == "yuyutei"  # the raw identity, not a rendering

    # No display-name table may appear in the analytics modules either. The
    # hyphenated/spaced forms are the give-away: they are words for humans,
    # which is the frontend's job.
    from app.api import analytics as analytics_api

    for module in (market_analytics, analytics_api):
        code = Path(module.__file__).read_text()
        executable = "\n".join(
            line for line in code.splitlines() if not line.strip().startswith("#")
        )
        for rendering in ('"Yuyu-Tei"', '"SNKRDUNK"', '"Market Index"', "DISPLAY_NAME"):
            assert rendering not in executable, f"{rendering} looks like display vocabulary"


def test_market_analytics_is_public_like_the_rest_of_the_pricing_surface(client, five_prints):
    """Unauthenticated, and deliberately so.

    The access-control split in this app is by DATA SUBJECT, not by router
    prefix: app.api.prints and app.api.market carry no auth at all because
    they describe the catalogue, while the holdings endpoints in this same
    router (collection, wishlist, buy/sell decisions, grading, portfolio risk)
    require a user because they describe what one person owns.
    /analytics/digest/latest is already ungated here for the same reason.

    Every number these two endpoints return is an aggregate of what
    GET /prints and GET /prints/{id}/market-index already serve to anyone, so
    gating them would lock a door in a building with no walls - and would keep
    the market landscape out of the public product it is being built for.
    """
    from app.api import analytics as analytics_api
    from app.api import prints as prints_api
    from app.auth import require_current_user

    def guarded(router, path):
        route = next(r for r in router.routes if r.path == path)
        return any(
            dep.call is require_current_user for dep in route.dependant.dependencies
        )

    # Wiring, not status codes: the shared test client carries a token, so a
    # 200 here would prove nothing about whether the route is gated.
    assert not guarded(analytics_api.router, "/analytics/market/bases")
    assert not guarded(analytics_api.router, "/analytics/market/overview")
    # The precedent these two follow: the catalogue pricing surface.
    assert not any(
        guarded(prints_api.router, route.path) for route in prints_api.router.routes
    )
    # And the holdings endpoints in this SAME router stay gated, which is what
    # makes the split data-subject-shaped rather than prefix-shaped.
    assert guarded(analytics_api.router, "/analytics/collection")
    assert guarded(analytics_api.router, "/analytics/portfolio-risk")


# --- filter vocabulary (GET /analytics/market/filters) ----------------------
#
# The contract these all circle is ONE sentence: an option this endpoint
# offers must be an option `/analytics/market/overview` accepts, and a slice
# the overview can express must be offered. Everything below is a way for that
# to be false.


def filters(client):
    response = client.get("/analytics/market/filters")
    assert response.status_code == 200, response.text
    return response.json()


def test_set_options_match_the_overview_filter_vocabulary(client, db_session, five_prints):
    """Every offered set selects at least one print THROUGH THE OVERVIEW.

    Not "is a plausible set code" and not "is in the database" - the option is
    fed straight back into `?set=` and the resulting scope must be non-empty.
    This is what would have caught the legacy /cards/catalogue vocabulary,
    whose `set_code` is `OP01` where this filter wants `OP-01`: every option
    would have scoped to zero prints.
    """
    make_print(
        db_session,
        make_canonical(db_session, card_code="EB01-001", name_en="Oden", rarity="L"),
        release_product_code="EB-02",
        artwork_key="oden-eb",
    )

    options = filters(client)["sets"]
    assert options, "no set options offered for a populated catalogue"

    for option in options:
        scope = overview(client, set=option["value"])["scope"]
        assert scope["set"] == option["value"]
        assert scope["active_prints"] > 0, f"set option {option['value']!r} selects nothing"


def test_every_set_in_scope_is_offered(client, db_session, five_prints):
    """The other direction: a set a print actually carries must be selectable.

    Without this, an endpoint returning `[]` would pass the test above
    vacuously - no option, no broken option.
    """
    make_print(
        db_session,
        make_canonical(db_session, card_code="EB01-001", name_en="Oden", rarity="L"),
        release_product_code="EB-02",
        artwork_key="oden-eb",
    )

    offered = {option["value"] for option in filters(client)["sets"]}
    in_catalogue = {
        row.release_product_code
        for row in db_session.query(CardPrint).filter(CardPrint.is_active.is_(True))
        if row.release_product_code is not None
    }
    assert in_catalogue <= offered


def test_rarity_options_match_the_overview_filter_vocabulary(client, five_prints):
    """Same round trip for rarity, which has the extra hazard of alias folding:
    `SPカード` and `SP P` are offered once as `SP CARD`, and that single option
    has to reach both stored tokens through `?rarity=`."""
    options = filters(client)["rarities"]
    assert options

    for option in options:
        scope = overview(client, rarity=option["value"])["scope"]
        assert scope["rarity"] == option["value"]
        assert scope["active_prints"] > 0, f"rarity option {option['value']!r} selects nothing"


def test_aliased_rarity_is_offered_once_and_reaches_every_stored_token(client, db_session):
    """The alias case end to end, because it is the one place where "distinct
    values" and "values the filter accepts" genuinely disagree.

    Two prints carrying the two stored spellings of one collector concept must
    produce ONE option whose scope covers BOTH prints - not two options, and
    not one option that reaches half the population."""
    for i, token in enumerate(ALIAS_MEMBERS[SP_CARD]):
        canonical = make_canonical(
            db_session, card_code=f"OP01-1{i:02d}", name_en=f"Special {i}", rarity=token
        )
        make_print(db_session, canonical, artwork_key=f"sp-{i}")

    offered = [option["value"] for option in filters(client)["rarities"]]
    assert offered.count(SP_CARD) == 1
    for member in ALIAS_MEMBERS[SP_CARD]:
        assert member not in offered, f"stored token {member!r} offered alongside its alias"

    assert overview(client, rarity=SP_CARD)["scope"]["active_prints"] == len(
        ALIAS_MEMBERS[SP_CARD]
    )


def test_duplicates_are_removed(client, db_session, five_prints):
    """Many prints share a set and a rarity; the control offers each once."""
    for i in range(6):
        canonical = make_canonical(
            db_session, card_code=f"OP01-2{i:02d}", name_en=f"Dupe {i}", rarity="C"
        )
        make_print(db_session, canonical, release_product_code="OP-01", artwork_key=f"dupe-{i}")

    body = filters(client)
    for key in ("sets", "rarities"):
        values = [option["value"] for option in body[key]]
        assert len(values) == len(set(values)), f"{key} contains duplicates: {values}"


def test_inactive_prints_contribute_no_options(client, db_session, five_prints):
    """An option is a filter a collector can select, and the overview counts
    ACTIVE prints only - so a set that exists solely on retired prints would be
    a control that scopes to zero."""
    retired_canonical = make_canonical(
        db_session, card_code="ZZ01-001", name_en="Retired", rarity="C"
    )
    make_print(
        db_session,
        retired_canonical,
        release_product_code="ZZ-99",
        artwork_key="retired",
        is_active=False,
        verification_status="unverified",
    )

    offered = {option["value"] for option in filters(client)["sets"]}
    assert "ZZ-99" not in offered
    assert overview(client, set="ZZ-99")["scope"]["active_prints"] == 0


def test_ordering_is_deterministic_and_sorted(client, db_session, five_prints):
    """Sorted, and stable across requests - a control whose options reshuffle
    between two loads is one a collector cannot learn."""
    for code in ("OP-05", "EB-02", "PRB-01"):
        canonical = make_canonical(
            db_session, card_code=f"{code}-x", name_en=f"Card {code}", rarity="R"
        )
        make_print(db_session, canonical, release_product_code=code, artwork_key=f"ord-{code}")

    first = filters(client)
    second = filters(client)
    assert first == second

    for key in ("sets", "rarities"):
        values = [option["value"] for option in first[key]]
        assert values == sorted(values), f"{key} is not sorted: {values}"


def test_a_future_set_appears_with_no_code_change(client, db_session, five_prints):
    """The genericity property, stated as the thing that actually happens: a
    release product nobody has heard of ships, and the control offers it the
    day its first active print exists. No allowlist, no release, no edit."""
    before = {option["value"] for option in filters(client)["sets"]}
    assert "QQ-01" not in before

    canonical = make_canonical(
        db_session, card_code="QQ01-001", name_en="Future Set Card", rarity="SEC"
    )
    make_print(db_session, canonical, release_product_code="QQ-01", artwork_key="future-set")

    after = {option["value"] for option in filters(client)["sets"]}
    assert "QQ-01" in after
    assert before < after
    assert overview(client, set="QQ-01")["scope"]["active_prints"] == 1


def test_labels_never_diverge_from_values(client, five_prints):
    """`label` is the published token, not a second server-authored wording.

    The moment these differ, the same set has two names that can drift - the
    defect MarketAnalyticsBasisOut refuses to introduce for platforms. The
    field exists so a client never has to DERIVE a label from an identifier,
    not so the server can invent one."""
    body = filters(client)
    for key in ("sets", "rarities"):
        for option in body[key]:
            assert option["label"] == option["value"]
            assert option["value"].strip() != ""


def test_null_release_product_invents_no_option(client, db_session, five_prints):
    """A print with no release product contributes nothing - no "Unknown"
    bucket, because selecting one could not be expressed as a `?set=` value."""
    canonical = make_canonical(db_session, card_code="NN01-001", name_en="No Product", rarity="C")
    make_print(
        db_session,
        canonical,
        release_product_code=None,
        release_product_id=None,
        artwork_key="no-product",
        verification_status="unverified",
    )

    values = [option["value"] for option in filters(client)["sets"]]
    assert all(value is not None and value != "" for value in values)
    assert not any(
        value.lower() in {"unknown", "none", "null", "other"} for value in values
    )


def test_filters_query_count_is_o1_in_catalogue_size(client, db_session, five_prints):
    """Two DISTINCT scans, whether the catalogue holds five prints or sixty-five.

    This is the guard against the implementation this endpoint exists to
    replace: anything that enumerates prints to collect their set codes would
    grow here, and so would a per-option round trip validating each one.
    """
    from sqlalchemy import event

    engine = db_session.get_bind()

    def count_queries():
        seen = []
        listener = lambda *a, **k: seen.append(1)  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            response = client.get("/analytics/market/filters")
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        assert response.status_code == 200, response.text
        return len(seen)

    small = count_queries()
    small_scope = client.get("/analytics/market/overview").json()["scope"]["active_prints"]

    for i in range(60):
        canonical = make_canonical(
            db_session, card_code=f"RR{i:04d}", name_en=f"Bulk {i}", rarity="C"
        )
        make_print(
            db_session,
            canonical,
            release_product_code="OP-01" if i % 2 else "OP-05",
            artwork_key=f"rr-{i}",
        )

    large_scope = client.get("/analytics/market/overview").json()["scope"]["active_prints"]
    assert large_scope > small_scope * 10
    assert count_queries() == small, "filters query count grew with catalogue size"


def test_filters_are_public(client, five_prints):
    """Unauthenticated, like /market/bases and /market/overview beside it -
    these are the set codes already printed on every public tile."""
    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app

    anonymous = TestClient(fastapi_app)
    response = anonymous.get("/analytics/market/filters")
    assert response.status_code == 200, response.text
    assert "sets" in response.json()


def test_filters_declare_no_display_vocabulary(client, five_prints):
    """No collector-facing wording beyond the catalogue's own tokens - the same
    rule test_no_display_vocabulary_is_served_or_declared keeps for bases."""
    body = filters(client)
    serialized = str(body)
    for word in ("Booster", "Extra Booster", "Starter Deck", "Promo", "Common", "Rare"):
        assert word not in serialized, f"server-authored display wording {word!r} in filters"
