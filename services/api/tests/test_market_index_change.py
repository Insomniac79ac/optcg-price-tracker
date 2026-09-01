"""The strict seven-day Market Index movement contract.

Almost every test here asserts a REFUSAL. That is the point of the contract:
the easy part is dividing two numbers, and the whole design question is which
pairs of numbers are honestly comparable at all. Each null case below is a way
a percentage would have described something other than a price movement.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models import CanonicalCard, CardPrint, MarketIndexSnapshot, ReleaseProduct
from app.schemas import MarketIndexSourceValueOut, PrintMarketIndexOut
from app.services.market_index_change import (
    COMPARISON_WINDOW_DAYS,
    eligible_contributor_set,
    get_index_change_7d_for_prints,
)

TODAY = date(2026, 9, 1)
BASELINE_DATE = TODAY - timedelta(days=COMPARISON_WINDOW_DAYS)

YUYUTEI = ("yuyutei", "retail_sell")
SNKRDUNK = ("snkrdunk", "listing_floor")


def source_value(
    source: str = "yuyutei",
    reference_type: str = "retail_sell",
    value_jpy: int | None = 1000,
    eligible: bool = True,
    **overrides,
) -> MarketIndexSourceValueOut:
    return MarketIndexSourceValueOut(
        source=source,
        reference_type=reference_type,
        evidence_type=overrides.pop("evidence_type", "listing"),
        value_jpy=value_jpy,
        observed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        sample_size=None,
        stale=False,
        eligible=eligible,
        fallback_used=False,
        ineligible_reason=overrides.pop("ineligible_reason", None),
        constraint=overrides.pop("constraint", None),
    )


def live_index(
    card_print_id: int = 1,
    index_value_jpy: int | None = 1100,
    source_values: list[MarketIndexSourceValueOut] | None = None,
    index_version: int = 1,
    source_semantics_version: int = 1,
) -> PrintMarketIndexOut:
    values = source_values if source_values is not None else [source_value()]
    return PrintMarketIndexOut(
        card_print_id=card_print_id,
        index_version=index_version,
        source_semantics_version=source_semantics_version,
        index_value_jpy=index_value_jpy,
        calculation_method="test",
        source_count=len([v for v in values if v.eligible and v.value_jpy is not None]),
        coverage_status="limited",
        confidence="medium",
        source_values=values,
        auxiliary_values=[],
        freshest_observation_at=None,
        stalest_eligible_source_at=None,
        stale_sources=[],
        calculated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )


def provenance_for(*pairs: tuple[str, str], eligible: bool = True, value_jpy: int | None = 1000):
    """A provenance archive exactly as snapshot_market_index writes it: plain
    dicts from `model_dump(mode="json")`, not models."""
    return {
        "source_values": [
            source_value(source=s, reference_type=r, eligible=eligible, value_jpy=value_jpy).model_dump(
                mode="json"
            )
            for s, r in pairs
        ],
        "auxiliary_values": [],
    }


def insert_snapshot(
    db_session,
    card_print_id: int,
    *,
    index_value_jpy: int | None = 1000,
    snapshot_date: date = BASELINE_DATE,
    provenance=None,
    index_version: int = 1,
    source_semantics_version: int = 1,
) -> MarketIndexSnapshot:
    row = MarketIndexSnapshot(
        card_print_id=card_print_id,
        calculated_at=datetime.combine(snapshot_date, datetime.min.time(), timezone.utc),
        snapshot_date=snapshot_date,
        index_value_jpy=index_value_jpy,
        calculation_method="test",
        source_count=1,
        # ck_market_index_snapshots_value_presence ties these together:
        # (index_value_jpy IS NULL) = (coverage_status = 'none').
        coverage_status="none" if index_value_jpy is None else "limited",
        confidence="medium",
        index_version=index_version,
        source_semantics_version=source_semantics_version,
        provenance=provenance if provenance is not None else provenance_for(YUYUTEI),
    )
    db_session.add(row)
    db_session.flush()
    return row


def change_for(db_session, index: PrintMarketIndexOut) -> float | None:
    result = get_index_change_7d_for_prints(
        db_session, {index.card_print_id: index}, today=TODAY
    )
    return result[index.card_print_id]


# --------------------------------------------------------------------------
# The comparison itself
# --------------------------------------------------------------------------


def test_exact_baseline_and_same_contributors_yields_a_percentage(db_session):
    insert_snapshot(db_session, 1, index_value_jpy=1000, provenance=provenance_for(YUYUTEI))
    assert change_for(db_session, live_index(1, 1100)) == pytest.approx(10.0)


def test_reports_a_rise(db_session):
    insert_snapshot(db_session, 1, index_value_jpy=1000)
    assert change_for(db_session, live_index(1, 1250)) == pytest.approx(25.0)


def test_reports_a_fall(db_session):
    insert_snapshot(db_session, 1, index_value_jpy=1000)
    assert change_for(db_session, live_index(1, 800)) == pytest.approx(-20.0)


def test_a_genuine_zero_survives_as_zero_not_null(db_session):
    # "unchanged" and "not comparable" are different facts and must never
    # collapse into the same value.
    insert_snapshot(db_session, 1, index_value_jpy=1000)
    result = change_for(db_session, live_index(1, 1000))
    assert result == 0.0
    assert result is not None


def test_two_source_index_compares_when_both_contributors_match(db_session):
    insert_snapshot(db_session, 1, index_value_jpy=2000, provenance=provenance_for(YUYUTEI, SNKRDUNK))
    index = live_index(
        1,
        1800,
        [source_value(*YUYUTEI), source_value(*SNKRDUNK)],
    )
    assert change_for(db_session, index) == pytest.approx(-10.0)


# --------------------------------------------------------------------------
# Missing or unusable baseline
# --------------------------------------------------------------------------


def test_no_snapshot_at_all_is_null(db_session):
    assert change_for(db_session, live_index(1, 1100)) is None


def test_a_snapshot_on_a_neighbouring_date_is_not_used(db_session):
    # Exact calendar-date match only: no nearest-date search, no tolerance.
    insert_snapshot(db_session, 1, snapshot_date=BASELINE_DATE - timedelta(days=1))
    insert_snapshot(db_session, 1, snapshot_date=BASELINE_DATE + timedelta(days=1))
    assert change_for(db_session, live_index(1, 1100)) is None


def test_baseline_null_index_is_null(db_session):
    insert_snapshot(db_session, 1, index_value_jpy=None)
    assert change_for(db_session, live_index(1, 1100)) is None


def test_baseline_zero_is_null(db_session):
    # Not a denominator, and not an infinite rise.
    insert_snapshot(db_session, 1, index_value_jpy=0)
    assert change_for(db_session, live_index(1, 1100)) is None


def test_current_null_index_is_null(db_session):
    insert_snapshot(db_session, 1, index_value_jpy=1000)
    assert change_for(db_session, live_index(1, None)) is None


# --------------------------------------------------------------------------
# Ruleset drift
# --------------------------------------------------------------------------


def test_index_version_mismatch_is_null(db_session):
    insert_snapshot(db_session, 1, index_value_jpy=1000, index_version=1)
    assert change_for(db_session, live_index(1, 1100, index_version=2)) is None


def test_source_semantics_version_mismatch_is_null(db_session):
    insert_snapshot(db_session, 1, index_value_jpy=1000, source_semantics_version=1)
    assert change_for(db_session, live_index(1, 1100, source_semantics_version=2)) is None


# --------------------------------------------------------------------------
# Composition changes - the reason this contract is strict
# --------------------------------------------------------------------------


def test_same_source_count_but_different_source_identity_is_null(db_session):
    # Both ends have exactly one contributor. source_count equality would call
    # this comparable; it is a retail asking price replaced by a platform
    # listing floor.
    insert_snapshot(db_session, 1, index_value_jpy=1000, provenance=provenance_for(YUYUTEI))
    index = live_index(1, 1100, [source_value(*SNKRDUNK)])
    assert index.source_count == 1
    assert change_for(db_session, index) is None


def test_same_source_but_different_reference_type_is_null(db_session):
    insert_snapshot(
        db_session, 1, index_value_jpy=1000, provenance=provenance_for(("snkrdunk", "listing_floor"))
    )
    index = live_index(1, 1100, [source_value("snkrdunk", "transaction_median")])
    assert change_for(db_session, index) is None


def test_contributor_added_is_null(db_session):
    insert_snapshot(db_session, 1, index_value_jpy=1000, provenance=provenance_for(YUYUTEI))
    index = live_index(1, 1100, [source_value(*YUYUTEI), source_value(*SNKRDUNK)])
    assert change_for(db_session, index) is None


def test_contributor_removed_is_null(db_session):
    insert_snapshot(db_session, 1, index_value_jpy=1000, provenance=provenance_for(YUYUTEI, SNKRDUNK))
    index = live_index(1, 1100, [source_value(*YUYUTEI)])
    assert change_for(db_session, index) is None


def test_historical_ineligible_contributor_is_excluded_from_the_set(db_session):
    # The archive holds every source_value, eligible or not. Only the eligible
    # ones ever counted toward the index, so only they define comparability.
    archive = provenance_for(YUYUTEI)
    archive["source_values"].append(
        source_value(*SNKRDUNK, eligible=False, constraint="platform_floor").model_dump(mode="json")
    )
    insert_snapshot(db_session, 1, index_value_jpy=1000, provenance=archive)

    index = live_index(1, 1100, [source_value(*YUYUTEI)])
    assert change_for(db_session, index) == pytest.approx(10.0)


def test_current_ineligible_contributor_is_excluded_from_the_set(db_session):
    insert_snapshot(db_session, 1, index_value_jpy=1000, provenance=provenance_for(YUYUTEI))
    index = live_index(
        1,
        1100,
        [source_value(*YUYUTEI), source_value(*SNKRDUNK, eligible=False, constraint="platform_floor")],
    )
    assert change_for(db_session, index) == pytest.approx(10.0)


def test_a_valueless_contributor_is_excluded_from_the_set(db_session):
    insert_snapshot(db_session, 1, index_value_jpy=1000, provenance=provenance_for(YUYUTEI))
    index = live_index(1, 1100, [source_value(*YUYUTEI), source_value(*SNKRDUNK, value_jpy=None)])
    assert change_for(db_session, index) == pytest.approx(10.0)


def test_empty_contributor_set_on_either_side_is_null(db_session):
    # Two indices resting on no eligible evidence are not "the same
    # composition" - there is nothing to compare.
    insert_snapshot(
        db_session, 1, index_value_jpy=1000, provenance={"source_values": [], "auxiliary_values": []}
    )
    assert change_for(db_session, live_index(1, 1100, [])) is None


# --------------------------------------------------------------------------
# Damaged provenance
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provenance",
    [
        # NOTE: provenance=None is absent on purpose - the column is NOT NULL,
        # so no writer can produce it. The code still guards it (see
        # test_non_dict_provenance_is_refused) for a hand-edited row.
        {},
        {"auxiliary_values": []},
        {"source_values": None},
        {"source_values": "not-a-list"},
        {"source_values": [{"source": "yuyutei"}]},
        {"source_values": [{"source": "yuyutei", "reference_type": "retail_sell"}]},
        {"source_values": ["not-a-dict"]},
        {"source_values": [{"source": 1, "reference_type": 2, "eligible": True, "value_jpy": 5}]},
    ],
)
def test_unreadable_provenance_is_null(db_session, provenance):
    insert_snapshot(db_session, 1, index_value_jpy=1000, provenance=provenance)
    assert change_for(db_session, live_index(1, 1100)) is None


def test_non_dict_provenance_is_refused(db_session):
    # Unreachable through the writer (NOT NULL column), asserted at the unit
    # level so the defensive guard cannot be deleted as dead code.
    from app.services.market_index_change import _change_for

    row = insert_snapshot(db_session, 1, index_value_jpy=1000)
    row.provenance = None
    assert _change_for(row, live_index(1, 1100)) is None


def test_eligible_contributor_set_distinguishes_unreadable_from_empty():
    # None means "cannot prove"; an empty set means "nothing contributed".
    # Collapsing them would let a damaged archive compare equal to a real
    # no-evidence index.
    assert eligible_contributor_set("nonsense") is None
    assert eligible_contributor_set([{"source": "y"}]) is None
    assert eligible_contributor_set([]) == set()


# --------------------------------------------------------------------------
# Batching
# --------------------------------------------------------------------------


def test_returns_exactly_one_entry_per_requested_print(db_session):
    insert_snapshot(db_session, 1, index_value_jpy=1000)
    # print 2 has no baseline at all; print 3 has one on the wrong date
    insert_snapshot(db_session, 3, snapshot_date=BASELINE_DATE - timedelta(days=2))

    indexes = {i: live_index(i, 1100) for i in (1, 2, 3)}
    result = get_index_change_7d_for_prints(db_session, indexes, today=TODAY)

    assert set(result) == {1, 2, 3}
    assert result[1] == pytest.approx(10.0)
    assert result[2] is None
    assert result[3] is None


def test_issues_one_query_for_the_whole_page(db_session):
    from sqlalchemy import event

    for i in range(1, 11):
        insert_snapshot(db_session, i, index_value_jpy=1000)
    indexes = {i: live_index(i, 1100) for i in range(1, 11)}

    statements: list[str] = []

    def record(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", record)
    try:
        result = get_index_change_7d_for_prints(db_session, indexes, today=TODAY)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", record)

    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
    assert len(selects) == 1, f"expected one batched SELECT, got {len(selects)}"
    assert len(result) == 10
    assert all(v == pytest.approx(10.0) for v in result.values())


def test_no_prints_requested_issues_no_query(db_session):
    assert get_index_change_7d_for_prints(db_session, {}, today=TODAY) == {}


def test_a_snapshot_for_another_print_is_never_borrowed(db_session):
    insert_snapshot(db_session, 99, index_value_jpy=1000)
    result = get_index_change_7d_for_prints(db_session, {1: live_index(1, 1100)}, today=TODAY)
    assert result == {1: None}


# --------------------------------------------------------------------------
# Catalogue integration
# --------------------------------------------------------------------------


def test_catalogue_item_exposes_the_field_without_changing_existing_ones(db_session):
    """The field rides on the existing payload; nothing else moves."""
    from app.services.print_catalogue import list_print_catalogue

    product = ReleaseProduct(
        source_catalogue="bandai",
        official_code="OP-01",
        display_name="OP-01",
        first_seen_name="OP-01",
        source_series_id="op01",
        source_url="https://example.test/op01",
    )
    db_session.add(product)
    db_session.flush()
    canonical = CanonicalCard(
        card_code="OP01-001", name_en="Test", name_jp=None, card_type="Leader", rarity="L"
    )
    db_session.add(canonical)
    db_session.flush()
    print_row = CardPrint(
        canonical_card_id=canonical.id,
        language="jp",
        treatment="normal",
        release_product_id=product.id,
        release_product_code="OP-01",
        # Unverified keeps the fixture minimal: ck_card_prints_verified_requires_fields
        # demands artwork/image evidence this test has no use for, and the
        # catalogue filters on is_active only.
        verification_status="unverified",
        is_active=True,
    )
    db_session.add(print_row)
    db_session.flush()

    items, total = list_print_catalogue(db_session, limit=10, offset=0)

    assert total == 1
    item = items[0]
    # Present, and null here because this print has no snapshot at all.
    assert item.market_index_change_7d_pct is None
    # The fields the catalogue already promised are untouched.
    assert item.card_print_id == print_row.id
    assert item.card_code == "OP01-001"
    assert item.market_index is not None
    assert item.source_coverage == []
