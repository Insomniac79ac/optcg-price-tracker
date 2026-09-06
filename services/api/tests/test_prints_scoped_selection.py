"""`GET /prints?set=&price_basis=` - scoped catalogue selection.

WHAT THIS EXISTS TO PREVENT. Before these parameters, a client that wanted the
prints of one set priced by one platform had exactly two options, and both were
defects. It could send `?set=OP-01`, which the endpoint SILENTLY IGNORED -
answering 200 with the entire 4,316-print catalogue, so the page looked scoped
and was not. Or it could page the whole catalogue and filter in the browser,
which is 44 requests to find the 4 prints SNKRDUNK prices in OP-01.

The second half is the harder one, and most of this file is about it. A basis
filter that is merely *approximate* is worse than none: showing a Yuyu-Tei
price under a SNKRDUNK heading, or a ¥1,000 platform floor as if it were a
market price, tells a collector something false about a platform they
explicitly selected. So the tests below pin the two properties that make the
filter honest - no cross-source substitution, and no constrained reading - and
pin them through the SAME rule the market overview counts with
(app.services.price_basis.usable_basis_value), so the strip of cards under a
chart cannot disagree with the chart.
"""

from sqlalchemy import event

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

# The SNKRDUNK platform minimum, as data. Nothing under test looks at this
# number - source_semantics classifies it - so these tests would pass unchanged
# if the platform raised it tomorrow.
PLATFORM_FLOOR_JPY = 1000


def prints(client, **params):
    response = client.get("/prints", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def codes(body):
    return [i["card_code"] for i in body["items"]]


def print_ids(body):
    return [i["card_print_id"] for i in body["items"]]


def basis_value(item, source_name=None):
    """The number this item carries for one basis, read the way a client would."""
    if source_name is None:
        return item["market_index"]["index_value_jpy"]
    for sv in item["market_index"]["source_values"]:
        if sv["source"] == source_name and sv["eligible"] and sv["value_jpy"] is not None:
            return sv["value_jpy"]
    return None


# --- A. the silent-set bug --------------------------------------------------


def test_set_actually_scopes_results(client, db_session, five_prints):
    """The regression this endpoint shipped with: `?set=` was accepted, ignored,
    and answered 200 with everything."""
    canonical = make_canonical(db_session, card_code="OP05-001", name_en="Other set", rarity="R")
    make_print(db_session, canonical, release_product_code="OP-05", artwork_key="op05-a")

    everything = prints(client, limit=100)
    assert everything["total"] == 6

    scoped = prints(client, set="OP-01", limit=100)
    assert scoped["total"] == 5, "?set= must scope, not be ignored"
    assert all(i["release_product_code"] == "OP-01" for i in scoped["items"])
    assert "OP05-001" not in codes(scoped)


def test_set_uses_the_published_filter_vocabulary(client, db_session, five_prints):
    """The identifiers `/analytics/market/filters` publishes are the ones this
    accepts - `OP-01`, never the legacy `cards.set_code` spelling `OP01`."""
    offered = {o["value"] for o in client.get("/analytics/market/filters").json()["sets"]}
    assert "OP-01" in offered and "OP01" not in offered

    assert prints(client, set="OP-01", limit=100)["total"] == 5
    # The legacy spelling selects nothing rather than quietly meaning the same
    # thing - one vocabulary, not two.
    assert prints(client, set="OP01", limit=100)["total"] == 0


def test_unknown_set_returns_an_empty_page_not_the_catalogue(client, five_prints):
    body = prints(client, set="ZZ-99", limit=100)
    assert body["total"] == 0
    assert body["items"] == []


# --- B. set + rarity + basis intersect --------------------------------------


def test_set_and_rarity_intersect(client, db_session, five_prints):
    common = make_canonical(db_session, card_code="OP01-900", name_en="Common", rarity="C")
    make_print(db_session, common, release_product_code="OP-01", artwork_key="c-1")
    other = make_canonical(db_session, card_code="OP05-900", name_en="Elsewhere", rarity="C")
    make_print(db_session, other, release_product_code="OP-05", artwork_key="c-2")

    both = prints(client, set="OP-01", rarity="C", limit=100)
    assert codes(both) == ["OP01-900"], "must be the intersection, not either filter alone"


def test_set_rarity_and_basis_intersect(client, db_session, five_prints):
    """All three compose into one population - never one filter applied and the
    others quietly dropped."""
    body = prints(client, set="OP-01", rarity="R", price_basis="market_index", limit=100)
    for item in body["items"]:
        assert item["release_product_code"] == "OP-01"
        assert item["rarity"] == "R"
        assert basis_value(item) is not None
    assert body["total"] == len(body["items"])


# --- C. Market Index basis --------------------------------------------------


def test_market_index_basis_returns_only_priced_prints(client, db_session, five_prints):
    """A print with no usable Market Index is absent - not present with a null,
    and certainly not present with a zero."""
    unpriced = make_canonical(db_session, card_code="OP01-777", name_en="Unpriced", rarity="R")
    make_print(db_session, unpriced, release_product_code="OP-01", artwork_key="unpriced-1")

    unfiltered = prints(client, limit=100)
    assert "OP01-777" in codes(unfiltered)

    body = prints(client, price_basis="market_index", limit=100)
    assert "OP01-777" not in codes(body)
    for item in body["items"]:
        value = basis_value(item)
        assert value is not None
        assert value != 0, "a missing price must never be rendered as a zero one"


def test_market_index_basis_total_matches_the_overview(client, five_prints):
    """The strip and the chart must be counting the same prints."""
    overview = client.get("/analytics/market/overview").json()
    body = prints(client, price_basis="market_index", limit=100)
    assert body["total"] == overview["coverage"]["usable_priced_prints"]


# --- D. source basis: no substitution, no constrained reading ---------------


def test_source_basis_returns_only_prints_that_source_prices(client, db_session, five_prints):
    snkrdunk = make_source(db_session, name="snkrdunk")
    legacy = five_prints["sanji_legacy"]
    parallel = five_prints["sanji_parallel"]
    mapping = make_mapping(db_session, legacy, snkrdunk, parallel, source_card_id="snk-1")
    make_observation(
        db_session, legacy, snkrdunk, mapping, parallel,
        price_type="floor", price_jpy=4020, stock_status=None, observed_at=NOW,
    )

    body = prints(client, price_basis="source:snkrdunk", limit=100)
    assert print_ids(body) == [parallel.id]
    assert basis_value(body["items"][0], "snkrdunk") == 4020


def test_source_basis_never_falls_back_to_another_source(client, db_session, five_prints):
    """THE CENTRAL HONESTY PROPERTY. Every one of the five prints has a Yuyu-Tei
    price; only one has a SNKRDUNK price. Under a SNKRDUNK basis the other four
    must be ABSENT - filling them from Yuyu-Tei would tell a collector that the
    platform they selected quotes prices it never quoted."""
    snkrdunk = make_source(db_session, name="snkrdunk")
    legacy = five_prints["sanji_legacy"]
    parallel = five_prints["sanji_parallel"]
    mapping = make_mapping(db_session, legacy, snkrdunk, parallel, source_card_id="snk-1")
    make_observation(
        db_session, legacy, snkrdunk, mapping, parallel,
        price_type="floor", price_jpy=4020, stock_status=None, observed_at=NOW,
    )

    yuyu = prints(client, price_basis="source:yuyutei", limit=100)
    snk = prints(client, price_basis="source:snkrdunk", limit=100)
    assert yuyu["total"] == 5
    assert snk["total"] == 1
    # Not merely fewer - the four Yuyu-priced prints are specifically gone.
    assert set(print_ids(snk)) < set(print_ids(yuyu))
    for item in snk["items"]:
        assert basis_value(item, "snkrdunk") is not None


def test_constrained_platform_floor_does_not_qualify(client, db_session, five_prints):
    """A ¥1,000 SNKRDUNK platform floor is a real integer and NOT a market
    price. It is observed, it is ineligible, and it must not put its print on a
    SNKRDUNK-basis page."""
    snkrdunk = make_source(db_session, name="snkrdunk")
    legacy = five_prints["sanji_legacy"]
    parallel = five_prints["sanji_parallel"]
    mapping = make_mapping(db_session, legacy, snkrdunk, parallel, source_card_id="snk-floor")
    make_observation(
        db_session, legacy, snkrdunk, mapping, parallel,
        price_type="floor", price_jpy=PLATFORM_FLOOR_JPY, stock_status=None, observed_at=NOW,
    )

    body = prints(client, price_basis="source:snkrdunk", limit=100)
    assert body["total"] == 0, "an ineligible constrained reading is not a price"
    assert body["items"] == []

    # And the print is still in the catalogue, and still honestly reports the
    # observation - the filter excluded it, nothing was hidden or rewritten.
    unfiltered = prints(client, limit=100)
    item = next(i for i in unfiltered["items"] if i["card_print_id"] == parallel.id)
    snk_value = next(
        sv for sv in item["market_index"]["source_values"] if sv["source"] == "snkrdunk"
    )
    assert snk_value["value_jpy"] == PLATFORM_FLOOR_JPY
    assert snk_value["eligible"] is False


def test_basis_agrees_with_the_overview_for_a_source(client, db_session, five_prints):
    snkrdunk = make_source(db_session, name="snkrdunk")
    legacy = five_prints["sanji_legacy"]
    for idx, key in enumerate(("sanji_parallel", "zoro_parallel")):
        row = five_prints[key]
        mapping = make_mapping(db_session, legacy, snkrdunk, row, source_card_id=f"snk-{idx}")
        make_observation(
            db_session, legacy, snkrdunk, mapping, row,
            price_type="floor", price_jpy=4020 + idx, stock_status=None, observed_at=NOW,
        )
    overview = client.get(
        "/analytics/market/overview", params={"price_basis": "source:snkrdunk"}
    ).json()
    body = prints(client, price_basis="source:snkrdunk", limit=100)
    assert body["total"] == overview["coverage"]["usable_priced_prints"] == 2


# --- E. genericity ----------------------------------------------------------


def test_a_future_source_is_accepted_with_no_allowlist(client, db_session, five_prints):
    """A platform this build has never heard of is ACCEPTED, not rejected.

    Note what this does and does not claim. `/prints` contains no source
    allowlist and no per-platform branch, so an unheard-of name parses, filters
    and answers 200. It cannot invent VALUES for that platform - those come
    from the resolver layer in app.services.market_index, and a source with no
    registered instrument resolves to nothing there. That is the published
    contract (see the parity assertion below), not a gap in this filter: the
    day a resolver and instrument ship for a new platform, this endpoint needs
    no edit to serve it.
    """
    future = make_source(db_session, name="cardrush")
    legacy = five_prints["sanji_legacy"]
    parallel = five_prints["sanji_parallel"]
    mapping = make_mapping(db_session, legacy, future, parallel, source_card_id="cr-1")
    make_observation(
        db_session, legacy, future, mapping, parallel,
        price_type="sell", price_jpy=7777, stock_status="in_stock", observed_at=NOW,
    )

    response = client.get("/prints", params={"price_basis": "source:cardrush", "limit": 100})
    assert response.status_code == 200, f"no allowlist may reject a new name: {response.text}"


def test_unconfigured_source_matches_the_published_basis_contract(client, db_session, five_prints):
    """An unconfigured platform is not an error here, and this endpoint does not
    invent a rule of its own for it: it reports exactly the population the
    market overview reports for the same basis."""
    future = make_source(db_session, name="cardrush")
    legacy = five_prints["sanji_legacy"]
    parallel = five_prints["sanji_parallel"]
    mapping = make_mapping(db_session, legacy, future, parallel, source_card_id="cr-2")
    make_observation(
        db_session, legacy, future, mapping, parallel,
        price_type="sell", price_jpy=7777, stock_status="in_stock", observed_at=NOW,
    )

    overview = client.get(
        "/analytics/market/overview", params={"price_basis": "source:cardrush"}
    ).json()
    body = prints(client, price_basis="source:cardrush", limit=100)
    assert body["total"] == overview["coverage"]["usable_priced_prints"]
    assert body["items"] == []


def test_never_heard_of_source_returns_an_empty_page(client, five_prints):
    body = prints(client, price_basis="source:nobody_has_this", limit=100)
    assert body["total"] == 0
    assert body["items"] == []


def test_malformed_basis_is_rejected_by_the_published_grammar(client, five_prints):
    for bad in ("nonsense", "source:", "index"):
        response = client.get("/prints", params={"price_basis": bad})
        assert response.status_code == 400, f"{bad!r} should be refused"


def test_no_source_name_or_price_type_appears_in_the_selection_code(client):
    """Structural guard. The filter must decide by resolved eligibility, never
    by naming a platform or reading a stored price_type."""
    from pathlib import Path

    import app.services.price_basis as price_basis
    import app.services.print_catalogue as print_catalogue

    for module in (price_basis, print_catalogue):
        text = Path(module.__file__).read_text().lower()
        body = "\n".join(
            line for line in text.splitlines()
            if not line.lstrip().startswith("#")
        )
        for banned in ("yuyutei", "snkrdunk", "cardrush"):
            assert banned not in body, f"{banned} named in {module.__name__}"
        for banned in ('"sell"', "'sell'", '"floor"', "'floor'"):
            assert banned not in body, f"stored price_type {banned} used in {module.__name__}"


# --- F. ordering and pagination ---------------------------------------------


def test_card_code_asc_is_deterministic(client, five_prints):
    body = prints(client, sort="card_code_asc", limit=100)
    assert codes(body) == sorted(codes(body))
    assert codes(prints(client, sort="card_code_asc", limit=100)) == codes(body)


def test_card_code_asc_is_an_alias_not_a_new_ordering(client, five_prints):
    """Same rows, same sequence as the long-standing `card_code`."""
    assert print_ids(prints(client, sort="card_code_asc", limit=100)) == print_ids(
        prints(client, sort="card_code", limit=100)
    )


def test_pagination_applies_after_filtering(client, db_session, five_prints):
    """Offsets must page the FILTERED population, so no print is skipped or
    repeated across pages, and `total` is what the caller can actually reach."""
    full = prints(client, price_basis="market_index", sort="card_code_asc", limit=100)
    assert full["total"] == 5

    seen = []
    for offset in (0, 2, 4):
        page = prints(
            client, price_basis="market_index", sort="card_code_asc", limit=2, offset=offset
        )
        assert page["total"] == 5
        seen.extend(print_ids(page))
    assert seen == print_ids(full)
    assert len(set(seen)) == len(seen)


def test_limit_bounds_the_strip(client, five_prints):
    body = prints(client, price_basis="market_index", sort="card_code_asc", limit=3)
    assert len(body["items"]) == 3
    assert body["total"] == 5


# --- G. shape and cost ------------------------------------------------------


def test_existing_calls_are_unchanged(client, five_prints):
    """A caller predating these parameters sees exactly what it saw before."""
    before = prints(client, limit=100)
    assert before["total"] == 5
    assert set(before["items"][0]).issuperset(
        {"card_print_id", "card_code", "rarity", "release_product_code", "image_url",
         "display_image", "market_index", "source_coverage"}
    )
    # The item shape is untouched by the new filters.
    filtered = prints(client, set="OP-01", price_basis="market_index", limit=100)
    assert set(filtered["items"][0]) == set(before["items"][0])


def test_query_count_does_not_grow_with_catalogue_size(client, db_session, five_prints):
    """The whole reason this parameter exists. A basis filter that resolved the
    catalogue - or issued one resolver query per print - would grow here."""
    engine = db_session.get_bind()

    def count_queries():
        seen = []
        listener = lambda *a, **k: seen.append(1)  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            response = client.get(
                "/prints",
                params={"set": "OP-01", "price_basis": "market_index",
                        "sort": "card_code_asc", "limit": 6},
            )
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        assert response.status_code == 200, response.text
        return len(seen)

    small = count_queries()
    small_total = prints(client, limit=1)["total"]

    for i in range(60):
        canonical = make_canonical(
            db_session, card_code=f"OP01-B{i:03d}", name_en=f"Bulk {i}", rarity="C"
        )
        make_print(
            db_session, canonical, release_product_code="OP-01", artwork_key=f"bulk-{i}"
        )

    large_total = prints(client, limit=1)["total"]
    assert large_total > small_total * 10
    assert count_queries() == small, "query count grew with catalogue size"
