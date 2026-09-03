"""Yuyu-Tei sale-price semantics end to end on the API side.

The policy under test, in one sentence: a Yuyu-Tei price that the source
itself displays as a sale is an ORDINARY Market Index contributor that
happens to carry a label. So the load-bearing assertions here are all
negative - the index value, source_count, coverage, confidence and
source_price_range must be provably identical to the same catalogue with the
label removed. `constraint` is the only field allowed to move.

The other half is what NULL means. Every one of the 549 Yuyu-Tei observations
already stored on staging predates promotion_state, including four prints
that demonstrably WERE on sale (a SALE badge on all 105 of their captured
pages). Those rows must not acquire a label retroactively: NULL is "not
determined", never "no promotion" and never "sale".
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
from app.services.market_index import (
    INDEX_VERSION,
    YUYUTEI_SELL_MAX_AGE_DAYS,
    get_market_index_for_card,
)
from app.services.print_market_index import get_market_index_for_print
from app.services.source_semantics import (
    PROMOTION_NONE,
    PROMOTION_SALE,
    SALE_PRICE,
    SNKRDUNK,
    SOURCE_SEMANTICS,
    SOURCE_SEMANTICS_VERSION,
    STORED_FLOOR,
    STORED_SELL,
    YUYUTEI,
    classify_observation,
)
from app.snapshot_market_index import build_snapshot_row

NOW = datetime.now(timezone.utc)


# --- fixtures -------------------------------------------------------------


def make_card(db_session, card_code="OP01-013") -> Card:
    card = Card(card_code=card_code, set_code="OP01", rarity="R", language="jp")
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


def yuyutei_sell(db_session, card, source, *, price_jpy, promotion_state, days_ago=0):
    obs = PriceObservation(
        card_id=card.id,
        source_id=source.id,
        price_type=STORED_SELL,
        price_jpy=price_jpy,
        promotion_state=promotion_state,
        observed_at=NOW - timedelta(days=days_ago),
        stock_status="in_stock",
    )
    db_session.add(obs)
    db_session.commit()
    db_session.refresh(obs)
    return obs


def snkrdunk_floor(db_session, card, source, *, price_jpy, days_ago=0):
    obs = PriceObservation(
        card_id=card.id,
        source_id=source.id,
        price_type=STORED_FLOOR,
        price_jpy=price_jpy,
        observed_at=NOW - timedelta(days=days_ago),
    )
    db_session.add(obs)
    db_session.commit()
    db_session.refresh(obs)
    return obs


def yuyutei_value(index):
    return next(sv for sv in index.source_values if sv.source == YUYUTEI)


def snkrdunk_value(index):
    return next(sv for sv in index.source_values if sv.source == SNKRDUNK)


# --- classifier -----------------------------------------------------------


def test_sale_promotion_state_is_classified_as_sale_price():
    semantics = classify_observation(YUYUTEI, STORED_SELL, 120, promotion_state=PROMOTION_SALE)
    assert semantics.constraint == SALE_PRICE
    assert semantics.constraint == "sale_price"


def test_a_sale_price_is_eligible_and_has_no_ineligible_reason():
    """The whole distinction between `constraint` and `eligible`. A sale price
    is described, never excluded."""
    semantics = classify_observation(YUYUTEI, STORED_SELL, 120, promotion_state=PROMOTION_SALE)
    assert semantics.eligible is True
    assert semantics.ineligible_reason is None


def test_none_promotion_state_is_unconstrained():
    semantics = classify_observation(YUYUTEI, STORED_SELL, 120, promotion_state=PROMOTION_NONE)
    assert semantics.constraint is None
    assert semantics.eligible is True


def test_null_promotion_state_is_unconstrained():
    """Legacy rows. Not determined is classified exactly as ordinary - Atlas
    never claims a promotion it did not observe."""
    semantics = classify_observation(YUYUTEI, STORED_SELL, 120, promotion_state=None)
    assert semantics.constraint is None
    assert semantics.eligible is True


def test_omitting_promotion_state_entirely_matches_the_pre_change_call():
    """Every existing three-argument call site keeps its exact behaviour."""
    assert classify_observation(YUYUTEI, STORED_SELL, 120) == classify_observation(
        YUYUTEI, STORED_SELL, 120, promotion_state=None
    )


def test_no_magnitude_branch_a_sale_price_is_sale_at_any_value():
    """There is no discount threshold and no rule that a sale price must be
    low. The source's displayed state is the entire input."""
    for value in (1, 80, 120, 1000, 148000):
        assert (
            classify_observation(YUYUTEI, STORED_SELL, value, promotion_state=PROMOTION_SALE).constraint
            == SALE_PRICE
        )


def test_yuyutei_buy_ignores_promotion_state():
    """Dealer buy is auxiliary_only and displays no promotion, so it is not
    configured promotion-aware and a stray value there changes nothing."""
    assert classify_observation(YUYUTEI, "buy", 60, promotion_state=PROMOTION_SALE).constraint is None


def test_an_unconfigured_source_ignores_promotion_state():
    """promotion_state is a column every source shares. Only a pair declared
    promotion_aware may be relabelled by it."""
    assert (
        classify_observation("cardrush", STORED_SELL, 120, promotion_state=PROMOTION_SALE).constraint
        is None
    )


# --- SNKRDUNK is untouched ------------------------------------------------


def test_snkrdunk_semantics_are_unchanged_at_and_around_the_floor():
    assert classify_observation(SNKRDUNK, STORED_FLOOR, 1000).constraint == "platform_floor"
    assert classify_observation(SNKRDUNK, STORED_FLOOR, 999).constraint == "below_platform_minimum"
    assert classify_observation(SNKRDUNK, STORED_FLOOR, 1500).constraint is None


def test_snkrdunk_is_not_promotion_aware():
    """The collector does not record promotion state for SNKRDUNK, so no
    value in that column may alter how a SNKRDUNK observation is described."""
    assert SOURCE_SEMANTICS[SNKRDUNK][STORED_FLOOR].promotion_aware is False
    for state in (PROMOTION_SALE, PROMOTION_NONE, None):
        assert classify_observation(SNKRDUNK, STORED_FLOOR, 1500, promotion_state=state).constraint is None
        assert classify_observation(SNKRDUNK, STORED_FLOOR, 1000, promotion_state=state).constraint == (
            "platform_floor"
        )


# --- the resolver ---------------------------------------------------------


def test_sale_observation_surfaces_the_constraint_and_still_contributes(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, YUYUTEI)
    yuyutei_sell(db_session, card, yuyutei, price_jpy=120, promotion_state=PROMOTION_SALE)

    index = get_market_index_for_card(db_session, card.id)
    value = yuyutei_value(index)

    assert value.constraint == SALE_PRICE
    assert value.eligible is True
    assert value.contributes_to_index is True
    assert value.ineligible_reason is None
    assert value.reference_type == "retail_sell"
    assert value.value_jpy == 120


def test_a_stale_sale_observation_keeps_its_sale_label_but_stops_contributing(db_session):
    """The two fields answer different questions, and staleness moves only one.

    `sale_price` DESCRIBES the observation - it is still, factually, a price
    the source displayed as a sale, and that does not stop being true when the
    observation gets old. `stale` DETERMINES whether it may feed the index.
    So the descriptive constraint must survive an exclusion it did not cause,
    and the exclusion must report its own reason rather than the label's."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, YUYUTEI)
    yuyutei_sell(
        db_session, card, yuyutei, price_jpy=120, promotion_state=PROMOTION_SALE,
        days_ago=YUYUTEI_SELL_MAX_AGE_DAYS + 1,
    )

    value = yuyutei_value(get_market_index_for_card(db_session, card.id))

    # The raw number is untouched - it is still the current sale price that
    # was observed, not a fallback, not a former price, not None.
    assert value.value_jpy == 120
    assert value.constraint == SALE_PRICE
    assert value.eligible is False
    assert value.contributes_to_index is False
    assert value.ineligible_reason == "stale"
    assert value.stale is True


def test_a_stale_sale_observation_alone_yields_no_index_but_stays_visible(db_session):
    """With no other contributor the index goes empty - and the Yuyu-Tei value
    is still emitted, with its real number and its label, so a collector can
    see exactly what Atlas knows and why it is not publishing a figure."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, YUYUTEI)
    yuyutei_sell(
        db_session, card, yuyutei, price_jpy=120, promotion_state=PROMOTION_SALE,
        days_ago=YUYUTEI_SELL_MAX_AGE_DAYS + 1,
    )

    index = get_market_index_for_card(db_session, card.id)

    assert index.source_count == 0
    assert index.index_value_jpy is None
    assert index.coverage_status == "none"
    assert index.confidence == "low"
    # Nothing admissible, so there is no disagreement to report.
    assert index.source_price_range is None

    # The raw source value survives an empty index rather than disappearing
    # with it.
    value = yuyutei_value(index)
    assert value.value_jpy == 120
    assert value.constraint == SALE_PRICE
    assert value.reference_type == "retail_sell"


def test_staleness_treats_a_sale_observation_exactly_like_an_ordinary_one(db_session):
    """The sale label must not change WHEN an observation goes stale, only how
    it is described once it has."""
    numbers = {}
    for state in (PROMOTION_SALE, PROMOTION_NONE):
        card = make_card(db_session, card_code=f"OP01-stale-{state}")
        yuyutei = make_source(db_session, YUYUTEI)
        yuyutei_sell(
            db_session, card, yuyutei, price_jpy=120, promotion_state=state,
            days_ago=YUYUTEI_SELL_MAX_AGE_DAYS + 1,
        )
        index = get_market_index_for_card(db_session, card.id)
        numbers[state] = _index_numbers(index)
        assert yuyutei_value(index).stale is True

    assert numbers[PROMOTION_SALE] == numbers[PROMOTION_NONE]


def test_legacy_null_observation_behaves_exactly_as_it_did_before_this_tranche(db_session):
    """The staging case: 549 rows written before the column existed, four of
    them known to have been on sale. None may acquire a label, and none may
    produce a different number than it did yesterday.

    The numeric expectations below are the pre-tranche values verbatim - a
    single fresh Yuyu-Tei sell of 120 has always resolved to index 120,
    source_count 1, limited/medium, no range."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, YUYUTEI)
    yuyutei_sell(db_session, card, yuyutei, price_jpy=120, promotion_state=None)

    index = get_market_index_for_card(db_session, card.id)
    value = yuyutei_value(index)

    assert value.constraint is None
    assert value.eligible is True
    assert value.contributes_to_index is True
    assert value.ineligible_reason is None
    assert value.value_jpy == 120

    assert index.index_value_jpy == 120
    assert index.source_count == 1
    assert index.coverage_status == "limited"
    assert index.confidence == "medium"
    assert index.source_price_range is None


def test_a_null_observation_is_numerically_identical_to_a_none_observation(db_session):
    """"Not determined" and "determined, no promotion" must differ in nothing
    a collector can see except that neither carries a label - the point being
    that legacy rows are not penalised for predating the column."""
    numbers = {}
    for label, state in (("null", None), ("none", PROMOTION_NONE)):
        card = make_card(db_session, card_code=f"OP01-null-{label}")
        yuyutei = make_source(db_session, YUYUTEI)
        yuyutei_sell(db_session, card, yuyutei, price_jpy=120, promotion_state=state)
        index = get_market_index_for_card(db_session, card.id)
        numbers[label] = _index_numbers(index)
        assert yuyutei_value(index).constraint is None

    assert numbers["null"] == numbers["none"]


def test_none_observation_reports_no_constraint(db_session):
    card = make_card(db_session)
    yuyutei = make_source(db_session, YUYUTEI)
    yuyutei_sell(db_session, card, yuyutei, price_jpy=120, promotion_state=PROMOTION_NONE)

    assert yuyutei_value(get_market_index_for_card(db_session, card.id)).constraint is None


# --- the numbers do not move ----------------------------------------------


def _index_numbers(index):
    """Every numeric/derived field the sale label must NOT be able to touch."""
    return {
        "index_value_jpy": index.index_value_jpy,
        "source_count": index.source_count,
        "coverage_status": index.coverage_status,
        "confidence": index.confidence,
        "calculation_method": index.calculation_method,
        "index_version": index.index_version,
        "source_price_range": (
            None
            if index.source_price_range is None
            else (index.source_price_range.low_jpy, index.source_price_range.high_jpy)
        ),
        "contributes": [sv.contributes_to_index for sv in index.source_values],
        "eligible": [sv.eligible for sv in index.source_values],
        "values": [sv.value_jpy for sv in index.source_values],
    }


@pytest.mark.parametrize(
    "snkrdunk_price",
    [
        None,  # Yuyu-Tei alone - the four staging sale prints' actual shape
        1000,  # SNKRDUNK at its platform floor: present, admissible-blocked
        1500,  # SNKRDUNK eligible: two admissible values, a real range
    ],
)
def test_sale_metadata_moves_no_index_field(db_session, snkrdunk_price):
    """Run the identical catalogue twice - once labelled sale, once not - and
    require every number to match. This is the central claim of the policy."""
    numbers = {}
    for state in (PROMOTION_SALE, PROMOTION_NONE):
        card = make_card(db_session, card_code=f"OP01-{state}")
        yuyutei = make_source(db_session, YUYUTEI)
        yuyutei_sell(db_session, card, yuyutei, price_jpy=120, promotion_state=state)
        if snkrdunk_price is not None:
            snkrdunk = make_source(db_session, SNKRDUNK)
            snkrdunk_floor(db_session, card, snkrdunk, price_jpy=snkrdunk_price)
        numbers[state] = _index_numbers(get_market_index_for_card(db_session, card.id))

    assert numbers[PROMOTION_SALE] == numbers[PROMOTION_NONE]


def test_sale_price_participates_in_source_price_range_normally(db_session):
    """Not merely "unchanged" - present. The range is built from admissible
    values, and a sale price is admissible."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, YUYUTEI)
    snkrdunk = make_source(db_session, SNKRDUNK)
    yuyutei_sell(db_session, card, yuyutei, price_jpy=120, promotion_state=PROMOTION_SALE)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1500)

    index = get_market_index_for_card(db_session, card.id)

    assert index.source_price_range is not None
    assert (index.source_price_range.low_jpy, index.source_price_range.high_jpy) == (120, 1500)


def test_a_sale_price_still_aggregates_with_another_contributor(db_session):
    """Two contributors, median of both - the sale value is not held back
    from the aggregate in any way."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, YUYUTEI)
    snkrdunk = make_source(db_session, SNKRDUNK)
    yuyutei_sell(db_session, card, yuyutei, price_jpy=1200, promotion_state=PROMOTION_SALE)
    for price in (1400, 1400, 1400):
        obs = PriceObservation(
            card_id=card.id, source_id=snkrdunk.id, price_type="sold",
            price_jpy=price, observed_at=NOW - timedelta(days=1),
        )
        db_session.add(obs)
    db_session.commit()

    index = get_market_index_for_card(db_session, card.id)

    assert index.source_count == 2
    assert index.index_value_jpy == 1300
    assert index.coverage_status == "full"
    assert index.confidence == "high"
    assert yuyutei_value(index).contributes_to_index is True


def test_snkrdunk_source_value_is_byte_identical_beside_a_sale_price(db_session):
    """A Yuyu-Tei label must not perturb the other source's reported shape."""
    card = make_card(db_session)
    yuyutei = make_source(db_session, YUYUTEI)
    snkrdunk = make_source(db_session, SNKRDUNK)
    yuyutei_sell(db_session, card, yuyutei, price_jpy=120, promotion_state=PROMOTION_SALE)
    snkrdunk_floor(db_session, card, snkrdunk, price_jpy=1000)

    value = snkrdunk_value(get_market_index_for_card(db_session, card.id))

    assert value.constraint == "platform_floor"
    assert value.ineligible_reason == "platform_floor"
    assert value.eligible is False
    assert value.contributes_to_index is False
    assert value.fallback_used is True


# --- versions -------------------------------------------------------------


def test_source_semantics_version_is_2_and_index_version_is_3(db_session):
    """The sale-price work moved the classification ruleset to 2 and left the
    combination rule alone; index v3 later moved the combination rule and left
    the classification ruleset alone. Neither change touched the other's
    version, which is the entire reason there are two of them.

    This test is the sale-price side of that pair, and its subject has not
    changed: a promotional Yuyu-Tei price is still classified `sale_price`,
    still eligible, still a full participant in the index. Only the number
    beside INDEX_VERSION has moved."""
    assert SOURCE_SEMANTICS_VERSION == 2
    assert INDEX_VERSION == 3

    card = make_card(db_session)
    yuyutei = make_source(db_session, YUYUTEI)
    yuyutei_sell(db_session, card, yuyutei, price_jpy=120, promotion_state=PROMOTION_SALE)

    index = get_market_index_for_card(db_session, card.id)
    assert index.source_semantics_version == 2
    assert index.index_version == 3


# --- API schema -------------------------------------------------------------


def test_the_existing_constraint_field_carries_sale_price_with_no_schema_change(db_session):
    """The assumption the design rests on, verified rather than assumed:
    MarketIndexSourceValueOut already has a nullable `constraint` string, so a
    new value in it needs no schema expansion and no new field."""
    from app.schemas import MarketIndexSourceValueOut

    fields = MarketIndexSourceValueOut.model_fields
    assert "constraint" in fields
    assert not any("promotion" in name for name in fields)

    card = make_card(db_session)
    yuyutei = make_source(db_session, YUYUTEI)
    yuyutei_sell(db_session, card, yuyutei, price_jpy=120, promotion_state=PROMOTION_SALE)

    dumped = yuyutei_value(get_market_index_for_card(db_session, card.id)).model_dump(mode="json")
    assert dumped["constraint"] == "sale_price"
    # The struck former price is not stored and therefore cannot be published.
    assert not any("former" in key or "was" in key for key in dumped)


# --- snapshot provenance ----------------------------------------------------


def test_snapshot_provenance_carries_sale_price(db_session):
    """A v2 snapshot must record that the value behind it was promotional -
    that is how a future reader tells it apart from the 310 v1 rows written
    when the distinction was not knowable."""
    canonical = CanonicalCard(
        card_code="OP01-013", name_en="Sanji", card_type="CHARACTER", rarity="R"
    )
    db_session.add(canonical)
    db_session.commit()
    db_session.refresh(canonical)

    product = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code="OP-01",
        display_name="Booster OP-01",
        first_seen_name="Booster OP-01",
        source_series_id="550101",
        source_url="https://www.onepiece-cardgame.com/products/boosters/op01.php",
        verification_status="verified",
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)

    print_row = CardPrint(
        canonical_card_id=canonical.id, language="jp", treatment="base",
        verification_status="verified", release_product_code="OP-01",
        release_product_id=product.id, artwork_key="art-op01-013",
        official_asset_variant="base",
    )
    db_session.add(print_row)
    db_session.commit()
    db_session.refresh(print_row)

    legacy = make_card(db_session)
    yuyutei = make_source(db_session, YUYUTEI)
    mapping = SourceCardMapping(
        card_id=legacy.id, source_id=yuyutei.id, card_print_id=print_row.id,
        source_card_id="OP01-013",
    )
    db_session.add(mapping)
    db_session.commit()
    db_session.refresh(mapping)

    obs = PriceObservation(
        card_id=legacy.id, source_id=yuyutei.id, price_type=STORED_SELL, price_jpy=120,
        promotion_state=PROMOTION_SALE, observed_at=NOW - timedelta(days=1),
        source_card_mapping_id=mapping.id, card_print_id=print_row.id,
    )
    db_session.add(obs)
    db_session.commit()

    index = get_market_index_for_print(db_session, print_row.id)
    row = build_snapshot_row(index)

    assert row["source_semantics_version"] == 2
    assert row["index_version"] == 3
    assert row["index_value_jpy"] == 120
    yuyu_provenance = next(
        sv for sv in row["provenance"]["source_values"] if sv["source"] == YUYUTEI
    )
    assert yuyu_provenance["constraint"] == "sale_price"
    assert yuyu_provenance["contributes_to_index"] is True
    assert yuyu_provenance["value_jpy"] == 120
