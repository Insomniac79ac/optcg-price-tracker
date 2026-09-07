"""The Card Pirate Index v1 estimator and chain-linker.

Every test here cites the section of `docs/card_pirate_index.md` it enforces.
The document is authoritative; if one of these ever has to be relaxed to make
the code pass, the code is wrong.

The two golden tests are the spine of the file:

  * `test_worked_example_*` reproduces section 18's five-card illustration,
    including the levels 1006.5795 and 1018.0851 and the mover counts.
  * `test_recomputed_staging_series_*` reproduces section 17.1 - the four real
    staging days, 1000.0000 -> 1000.8409 -> 1000.9577 -> 1000.9577, with the
    exact 12-decimal step returns.

If the estimator ever drifts, one of those two fails with a number a reviewer
can compare against the document by eye.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.services.card_pirate_index import (
    BASE_VALUE,
    BREAK_SNAPSHOT_GAP,
    CHANGE_UNAVAILABLE_NO_CONTINUITY,
    CHANGE_UNAVAILABLE_NO_POINT,
    METHODOLOGY_VERSION,
    MIN_CONSTITUENTS,
    SCOPE_OVERALL,
    SCOPE_SET,
    UNPUBLISHABLE_INSUFFICIENT_CONSTITUENTS,
    UNPUBLISHABLE_MIXED_VERSION_DAY,
    ConstituentObservation,
    PointDraft,
    SnapshotDay,
    build_points,
    chain,
    compute_change,
    compute_step,
)
from app.services.print_series import (
    BREAK_INDEX_VERSION_CHANGE,
    BREAK_SOURCE_SEMANTICS_VERSION_CHANGE,
)

YUYU = frozenset({("yuyutei", "sell")})
SNKR = frozenset({("snkrdunk", "transaction_median")})


def obs(print_id, value, *, iv=3, ssv=2, contributors=YUYU):
    return ConstituentObservation(
        card_print_id=print_id,
        index_value_jpy=value,
        index_version=iv,
        source_semantics_version=ssv,
        contributors=contributors,
    )


def day(d, rows):
    return SnapshotDay(point_date=d, observations=tuple(rows))


def flat_panel(n, *, value=100, iv=3, ssv=2, start=0):
    """`n` prints all at the same price - the base a sparse market provides."""
    return [obs(i, value, iv=iv, ssv=ssv) for i in range(start, start + n)]


D3, D4, D5, D6 = (date(2026, 9, d) for d in (3, 4, 5, 6))


# --- golden: the section 18 worked example ----------------------------------
#
# A JPY 80 (C) . B 3,000 (R) . C 66,000 (SP manga) . D 30 (C) . E 12,900 (L).
# Five cards, so these exercise compute_step/chain directly rather than
# build_points - MIN_CONSTITUENTS would (correctly) refuse to publish them.

A, B, C, D, E, F = 1, 2, 3, 4, 5, 6

WORKED_DAY_0 = day(D3, [obs(A, 80), obs(B, 3000), obs(C, 66000), obs(D, 30), obs(E, 12900)])
WORKED_DAY_1 = day(D4, [obs(A, 80), obs(B, 3300), obs(C, 62000), obs(D, 30), obs(E, 12900)])
# D drops out (aged past YUYUTEI_SELL_MAX_AGE_DAYS), F enters at JPY 500.
WORKED_DAY_2 = day(D5, [obs(A, 80), obs(B, 3300), obs(C, 62000), obs(E, 13500), obs(F, 500)])


def test_worked_example_day_1_matches_the_document():
    step = compute_step(WORKED_DAY_0, WORKED_DAY_1)
    assert step.constituent_count == 5
    assert step.step_log_return == Decimal("0.006557964565")
    assert chain(BASE_VALUE, step.step_log_return) == Decimal("1006.5795")
    assert step.capped_count == 0


def test_worked_example_day_2_matches_the_document():
    """F's JPY 500 arriving moves the index by exactly nothing, and D's
    departure moves it by exactly nothing. Only prints priced at BOTH ends of
    the step move the level - the whole chain-link property."""
    step_1 = compute_step(WORKED_DAY_0, WORKED_DAY_1)
    level_1 = chain(BASE_VALUE, step_1.step_log_return)

    step_2 = compute_step(WORKED_DAY_1, WORKED_DAY_2)
    assert step_2.constituent_count == 4
    assert WORKED_DAY_2.eligible_print_count == 5
    assert (step_2.movers_up, step_2.movers_down, step_2.movers_flat) == (1, 0, 3)
    assert step_2.capped_count == 0
    assert step_2.step_log_return == Decimal("0.011365593519")
    assert chain(level_1, step_2.step_log_return) == Decimal("1018.0851")


def test_worked_example_is_not_a_median():
    """The degeneracy, in five cards: the median of the day-1 returns is
    exactly zero, and publishing it would be a permanently flat line."""
    step = compute_step(WORKED_DAY_0, WORKED_DAY_1)
    assert step.step_log_return > 0
    assert step.movers_flat == 3  # a median of five would sit on a flat card


# --- golden: the section 17.1 recomputed staging series ---------------------


def staging_panel(n, overrides):
    rows = [obs(i, 100) for i in range(n)]
    for print_id, value in overrides.items():
        rows[print_id] = obs(print_id, value)
    return rows


# print 0 is OP01-047 SR (14,000 -> 17,000 on 09-04); print 1 is OP01-051 SR
# (6,000 -> 6,200 on 09-05). Everything else is flat, as staging really was.
STAGING_DAYS = [
    day(D3, staging_panel(231, {0: 14000, 1: 6000})),
    day(D4, staging_panel(281, {0: 17000, 1: 6000})),
    day(D5, staging_panel(296, {0: 17000, 1: 6200})),
    day(D6, staging_panel(297, {0: 17000, 1: 6200})),
]

STAGING_EXPECTED = [
    # point_date, level, step, n, up, down, flat, eligible
    (D3, "1000.0000", None, 0, None, None, None, 231),
    (D4, "1000.8409", "0.000840502227", 231, 1, 0, 230, 281),
    (D5, "1000.9577", "0.000116689761", 281, 1, 0, 280, 296),
    (D6, "1000.9577", "0", 296, 0, 0, 296, 297),
]


def test_recomputed_staging_series_matches_the_document():
    points = build_points(STAGING_DAYS).points
    assert len(points) == len(STAGING_EXPECTED)
    for point, (d, level, step, n, up, down, flat, eligible) in zip(
        points, STAGING_EXPECTED
    ):
        assert point.point_date == d
        assert point.index_value == Decimal(level)
        if step is None:
            assert point.chain_link_log_return is None
        else:
            assert point.chain_link_log_return == Decimal(step)
        assert point.constituent_count == n
        assert (point.movers_up, point.movers_down, point.movers_flat) == (
            up, down, flat
        )
        assert point.eligible_print_count == eligible
        assert point.capped_count in (0, None)


def test_recomputed_staging_cumulative_change_follows_the_change_rule():
    """Cumulative change over the four real staging days: +0.095770 %.

    Computed from the two PUBLISHED levels - `(1000.9577 / 1000.0000 - 1) x
    100` - exactly as section 5.6 rule 4 requires, and matching section 17.1.

    An earlier draft of section 17.1 reported +0.095765 %, which comes from
    the pre-quantized internal chain value 1000.9576502... That value is never
    published, never stored, and never an endpoint of a change calculation:
    section 8.4 stores the level as Numeric(12,4), and the carry rule turns on
    a base row's level being EXACTLY its source point's, so the published
    4-decimal level is the only level the index has. The document has since
    been corrected; this test pins the rule either way.
    """
    points = list(build_points(STAGING_DAYS).points)
    change = compute_change(points)
    assert change.absolute == Decimal("0.9577")  # section 17.1, exactly
    assert change.pct == Decimal("0.095770")  # section 5.6 rule 4
    assert change.from_date == D3
    assert change.to_date == D6
    assert change.spans_break is False


# --- the base ---------------------------------------------------------------


def test_first_publishable_day_opens_at_1000():
    series = build_points([day(D3, flat_panel(50))])
    (point,) = series.points
    assert point.is_base is True
    assert point.index_value == Decimal("1000.0000")
    assert point.carried_from_key is None
    assert point.methodology_version == METHODOLOGY_VERSION
    # Section 5.1 rule 5 - a base row has no step and therefore no breadth.
    assert point.prior_point_date is None
    assert point.step_days is None
    assert point.chain_link_log_return is None
    assert point.constituent_count == 0
    assert point.movers_up is None


def test_base_value_carries_the_column_scale():
    assert str(BASE_VALUE) == "1000.0000"


# --- ordinary steps ---------------------------------------------------------


def test_all_flat_day_publishes_a_zero_step():
    """A genuinely quiet day is real information, not an absence. The level
    must not move, and the point must still publish."""
    series = build_points([day(D3, flat_panel(50)), day(D4, flat_panel(50))])
    second = series.points[1]
    assert second.chain_link_log_return == Decimal(0)
    assert second.index_value == Decimal("1000.0000")
    assert (second.movers_up, second.movers_down, second.movers_flat) == (0, 0, 50)
    assert second.capped_count == 0


def test_single_mover_among_many_flats():
    before = flat_panel(50)
    after = flat_panel(50)
    after[0] = obs(0, 110)  # 100 -> 110
    series = build_points([day(D3, before), day(D4, after)])
    point = series.points[1]
    assert (point.movers_up, point.movers_down, point.movers_flat) == (1, 0, 49)
    expected = (Decimal("1.1").ln() / Decimal(50)).quantize(Decimal("0.000000000001"))
    assert point.chain_link_log_return == expected
    assert point.index_value > Decimal("1000.0000")


def test_negative_move_lowers_the_level():
    before = flat_panel(50)
    after = flat_panel(50)
    after[0] = obs(0, 90)
    series = build_points([day(D3, before), day(D4, after)])
    point = series.points[1]
    assert (point.movers_up, point.movers_down, point.movers_flat) == (0, 1, 49)
    assert point.chain_link_log_return < 0
    assert point.index_value < Decimal("1000.0000")


def test_movers_always_reconcile_with_constituent_count():
    before = flat_panel(60)
    after = flat_panel(60)
    for i in range(5):
        after[i] = obs(i, 130)
    for i in range(5, 12):
        after[i] = obs(i, 70)
    series = build_points([day(D3, before), day(D4, after)])
    point = series.points[1]
    assert point.movers_up == 5
    assert point.movers_down == 7
    assert point.movers_flat == 48
    assert (
        point.movers_up + point.movers_down + point.movers_flat
        == point.constituent_count
    )


# --- the cap ----------------------------------------------------------------


def test_up_move_is_capped_at_ln_1_25():
    before = flat_panel(50)
    after = flat_panel(50)
    after[0] = obs(0, 1000)  # +900 %, far past the cap
    step = compute_step(day(D3, before), day(D4, after))
    assert step.capped_count == 1
    cap = Decimal("1.25").ln()
    assert step.step_log_return == (cap / Decimal(50)).quantize(
        Decimal("0.000000000001")
    )


def test_a_move_exactly_at_the_cap_is_not_counted_as_capped():
    """+25 % is the boundary and is representable exactly: 100 -> 125 gives
    r = ln(1.25), which is the cap, not beyond it."""
    before = flat_panel(50)
    after = flat_panel(50)
    after[0] = obs(0, 125)
    step = compute_step(day(D3, before), day(D4, after))
    assert step.capped_count == 0
    assert step.movers_up == 1


def test_down_move_is_capped_at_minus_ln_1_25():
    """The cap is log-symmetric, so the downward bound in price terms is
    -20 % (ratio 0.8), not -25 %."""
    before = flat_panel(50)
    after = flat_panel(50)
    after[0] = obs(0, 1)
    step = compute_step(day(D3, before), day(D4, after))
    assert step.capped_count == 1
    cap = Decimal("1.25").ln()
    assert step.step_log_return == (-cap / Decimal(50)).quantize(
        Decimal("0.000000000001")
    )


def test_multiple_capped_constituents_are_all_counted():
    before = flat_panel(50)
    after = flat_panel(50)
    for i in range(4):
        after[i] = obs(i, 1000)
    for i in range(4, 7):
        after[i] = obs(i, 1)
    step = compute_step(day(D3, before), day(D4, after))
    assert step.capped_count == 7
    assert step.movers_up == 4
    assert step.movers_down == 3


def test_capping_never_changes_a_sign():
    before = flat_panel(50)
    after = flat_panel(50)
    after[0] = obs(0, 100000)
    step = compute_step(day(D3, before), day(D4, after))
    assert step.movers_down == 0
    assert step.step_log_return > 0


# --- coverage churn ---------------------------------------------------------


def test_entrant_contributes_nothing_on_its_first_day():
    before = flat_panel(50)
    after = flat_panel(50) + [obs(999, 5000)]
    series = build_points([day(D3, before), day(D4, after)])
    point = series.points[1]
    assert point.constituent_count == 50
    assert point.eligible_print_count == 51
    assert point.index_value == Decimal("1000.0000")


def test_leaver_contributes_nothing_and_cannot_move_the_level():
    before = flat_panel(50)
    after = flat_panel(49)
    series = build_points([day(D3, before), day(D4, after)])
    point = series.points[1]
    assert point.constituent_count == 49
    assert point.eligible_print_count == 49
    assert point.index_value == Decimal("1000.0000")


def test_a_large_entrant_cohort_moves_the_level_by_exactly_nothing():
    """The 09-04 staging cohort was 50 prints. Under a level-based or
    sum-based index it alone would have manufactured an enormous fake move."""
    before = flat_panel(50)
    after = flat_panel(50) + [obs(500 + i, 60000) for i in range(50)]
    series = build_points([day(D3, before), day(D4, after)])
    assert series.points[1].index_value == Decimal("1000.0000")


def test_no_forward_fill_when_a_print_disappears_and_returns():
    """A print absent on D is absent from that step. When it comes back it
    steps from the day it actually reappears against, never from a carried
    forward value."""
    d3 = flat_panel(50)
    d4 = flat_panel(50)[1:]          # print 0 gone
    d5 = flat_panel(50)              # print 0 back, unchanged
    series = build_points([day(D3, d3), day(D4, d4), day(D5, d5)])
    assert series.points[1].constituent_count == 49
    assert series.points[2].constituent_count == 49  # print 0 has no D4 value
    assert series.points[2].eligible_print_count == 50


# --- eligibility guards -----------------------------------------------------


def test_version_mismatch_excludes_the_print_not_the_day():
    before = flat_panel(50)
    after = flat_panel(50)
    after[0] = obs(0, 200, iv=4)  # this print alone moved version
    after[0] = ConstituentObservation(0, 200, 4, 2, YUYU)
    # Give the rest of the day the same pair so the DAY is not mixed.
    after = [ConstituentObservation(o.card_print_id, o.index_value_jpy, 4, 2, YUYU)
             for o in after]
    step = compute_step(day(D3, before), day(D4, after))
    assert step.constituent_count == 0
    assert step.excluded_version_mismatch == 50


def test_contributor_set_churn_excludes_the_print():
    """A print that lost a Yuyu-Tei retail price and gained a SNKRDUNK floor
    keeps source_count = 1 while the number underneath switches instrument."""
    before = flat_panel(50)
    after = flat_panel(50)
    after[0] = obs(0, 100, contributors=SNKR)
    step = compute_step(day(D3, before), day(D4, after))
    assert step.constituent_count == 49
    assert step.excluded_contributor_churn == 1


def test_unprovable_contributor_set_fails_closed():
    """None means 'cannot prove comparability', never 'did not contribute'."""
    before = flat_panel(50)
    after = flat_panel(50)
    after[0] = obs(0, 100, contributors=None)
    step = compute_step(day(D3, before), day(D4, after))
    assert step.constituent_count == 49
    assert step.excluded_contributor_churn == 1


def test_observation_from_snapshot_row_reuses_the_shared_helper():
    o = ConstituentObservation.from_snapshot_row(
        card_print_id=1, index_value_jpy=100, index_version=3,
        source_semantics_version=2,
        provenance={"source_values": [
            {"source": "yuyutei", "reference_type": "sell",
             "contributes_to_index": True, "value_jpy": 100},
            {"source": "snkrdunk", "reference_type": "listing_floor",
             "contributes_to_index": False, "value_jpy": 120},
        ]},
    )
    assert o.contributors == frozenset({("yuyutei", "sell")})


def test_observation_without_provenance_fails_closed():
    o = ConstituentObservation.from_snapshot_row(
        card_print_id=1, index_value_jpy=100, index_version=3,
        source_semantics_version=2, provenance=None,
    )
    assert o.contributors is None


# --- unpublishable days -----------------------------------------------------


def test_below_minimum_constituents_is_unpublishable():
    n = MIN_CONSTITUENTS - 1
    series = build_points([day(D3, flat_panel(n)), day(D4, flat_panel(n))])
    point = series.points[1]
    assert point.index_value is None
    assert point.unpublishable_reason == UNPUBLISHABLE_INSUFFICIENT_CONSTITUENTS
    # Breadth is still reported: n < 30 is a real measurement, not an absence.
    assert point.constituent_count == n
    assert point.movers_flat == n


def test_exactly_minimum_constituents_publishes():
    n = MIN_CONSTITUENTS
    series = build_points([day(D3, flat_panel(n)), day(D4, flat_panel(n))])
    assert series.points[1].index_value == Decimal("1000.0000")


def test_mixed_version_day_is_unpublishable_and_reports_no_breadth():
    rows = flat_panel(50)
    rows[0] = obs(0, 100, iv=4)
    series = build_points([day(D3, flat_panel(50)), day(D4, rows)])
    point = series.points[1]
    assert point.unpublishable_reason == UNPUBLISHABLE_MIXED_VERSION_DAY
    assert point.index_value is None
    assert point.constituent_count == 0
    assert point.movers_up is None


def test_mixed_version_day_does_not_become_the_chain_anchor():
    """A mixed day has no single version pair, so the next day must compare
    against the last clean day rather than against the mixed one."""
    clean = flat_panel(50)
    mixed = flat_panel(50)
    mixed[0] = obs(0, 100, iv=4)
    later = flat_panel(50)
    later[0] = obs(0, 110)
    series = build_points([day(D3, clean), day(D4, mixed), day(D5, later)])
    third = series.points[2]
    assert third.prior_point_date == D3
    assert third.step_days == 2
    assert third.constituent_count == 50


def test_unpublishable_day_still_anchors_the_next_step():
    """An insufficient-constituents day is a real, single-version day. The
    next step compares against the values actually observed there."""
    small = flat_panel(MIN_CONSTITUENTS - 1)
    series = build_points([
        day(D3, flat_panel(50)),
        day(D4, small),
        day(D5, flat_panel(50)),
    ])
    assert series.points[1].unpublishable_reason is not None
    assert series.points[2].prior_point_date == D4
    assert series.points[2].step_days == 1


# --- gaps -------------------------------------------------------------------


def test_multi_day_gap_records_step_days_and_emits_a_break():
    series = build_points([day(D3, flat_panel(50)), day(D6, flat_panel(50))])
    point = series.points[1]
    assert point.step_days == 3
    assert point.prior_point_date == D3
    gaps = [b for b in series.breaks if b.reason == BREAK_SNAPSHOT_GAP]
    assert [(b.at, b.step_days) for b in gaps] == [(D6, 3)]


def test_a_gap_is_a_real_return_not_an_interpolation():
    before = flat_panel(50)
    after = flat_panel(50)
    after[0] = obs(0, 110)
    series = build_points([day(D3, before), day(D6, after)])
    point = series.points[1]
    assert point.step_days == 3
    # One three-day return, NOT three one-day returns.
    assert point.chain_link_log_return == (
        Decimal("1.1").ln() / Decimal(50)
    ).quantize(Decimal("0.000000000001"))


def test_a_day_with_nothing_valued_produces_no_row():
    series = build_points([
        day(D3, flat_panel(50)),
        day(D4, []),
        day(D5, flat_panel(50)),
    ])
    assert [p.point_date for p in series.points] == [D3, D5]


# --- version boundaries: carry vs reset -------------------------------------


def test_version_boundary_carries_the_level_and_does_not_reset_to_1000():
    before = flat_panel(50)
    moved = flat_panel(50)
    moved[0] = obs(0, 110)
    after = [ConstituentObservation(o.card_print_id, o.index_value_jpy, 4, 2, YUYU)
             for o in moved]
    series = build_points([day(D3, before), day(D4, moved), day(D5, after)])

    step_point = series.points[1]
    carried = series.points[2]
    assert carried.is_base is True
    assert carried.carried_from_key == D4
    assert carried.index_value == step_point.index_value  # identical, not 1000
    assert carried.index_value != BASE_VALUE
    # Section 5.1 rule 5: the boundary itself has no calculated return.
    assert carried.chain_link_log_return is None
    assert carried.prior_point_date is None
    assert carried.step_days is None
    assert carried.constituent_count == 0


def test_two_versions_moving_at_one_boundary_emit_two_breaks():
    before = flat_panel(50)
    after = [ConstituentObservation(o.card_print_id, o.index_value_jpy, 4, 3, YUYU)
             for o in flat_panel(50)]
    series = build_points([day(D3, before), day(D4, after)])
    reasons = sorted(b.reason for b in series.breaks)
    assert reasons == sorted(
        [BREAK_INDEX_VERSION_CHANGE, BREAK_SOURCE_SEMANTICS_VERSION_CHANGE]
    )
    assert {b.at for b in series.breaks} == {D4}
    assert all(b.carried is True for b in series.breaks)


def test_no_return_is_calculated_across_a_boundary():
    """Even a huge apparent move across a version change produces no step -
    the largest apparent moves in the real archive are version artefacts."""
    before = flat_panel(50, value=120)
    after = [ConstituentObservation(o.card_print_id, 1310, 4, 2, YUYU)
             for o in flat_panel(50)]
    series = build_points([day(D3, before), day(D4, after)])
    boundary = series.points[1]
    assert boundary.is_base is True
    assert boundary.chain_link_log_return is None
    assert boundary.index_value == BASE_VALUE  # carried from the base itself


def test_the_chain_continues_normally_after_a_carry():
    v3 = flat_panel(50)
    v4 = [ConstituentObservation(o.card_print_id, o.index_value_jpy, 4, 2, YUYU)
          for o in flat_panel(50)]
    v4_moved = [ConstituentObservation(o.card_print_id, o.index_value_jpy, 4, 2, YUYU)
                for o in flat_panel(50)]
    v4_moved[0] = ConstituentObservation(0, 110, 4, 2, YUYU)
    series = build_points([day(D3, v3), day(D4, v4), day(D5, v4_moved)])
    after_carry = series.points[2]
    assert after_carry.is_base is False
    assert after_carry.prior_point_date == D4
    assert after_carry.index_value > Decimal("1000.0000")


# --- change across breaks (section 5.6) -------------------------------------


def test_change_spanning_a_carry_is_published_with_spans_break():
    v3 = flat_panel(50)
    moved = flat_panel(50)
    moved[0] = obs(0, 110)
    v4 = [ConstituentObservation(o.card_print_id, o.index_value_jpy, 4, 2, YUYU)
          for o in moved]
    series = build_points([day(D3, v3), day(D4, moved), day(D5, v4)])
    change = compute_change(list(series.points))
    assert change.unavailable_reason is None
    assert change.spans_break is True
    assert change.pct > 0


def test_change_across_a_reset_is_withheld():
    """Section 5.6 rule 5. A reset is an initial base that is not the chain's
    first point, and there is no carried continuity across it."""
    points = [
        PointDraft(SCOPE_OVERALL, "", 1, 3, 2, D3, Decimal("1000.0000"), True,
                   None, None, None, None, 0, 50, None, None, None, None, None),
        PointDraft(SCOPE_OVERALL, "", 1, 3, 2, D4, Decimal("1010.0000"), False,
                   None, D3, 1, Decimal("0.01"), 50, 50, 1, 0, 49, 0, None),
        # a RESET: initial base, mid-chain
        PointDraft(SCOPE_OVERALL, "", 1, 4, 2, D5, Decimal("1000.0000"), True,
                   None, None, None, None, 0, 50, None, None, None, None, None),
    ]
    change = compute_change(points)
    assert change.absolute is None
    assert change.pct is None
    assert change.unavailable_reason == CHANGE_UNAVAILABLE_NO_CONTINUITY


def test_change_with_no_published_point_is_withheld():
    points = [
        PointDraft(SCOPE_OVERALL, "", 1, 3, 2, D3, None, False, None, None,
                   None, None, 0, 50, None, None, None, None,
                   UNPUBLISHABLE_MIXED_VERSION_DAY),
    ]
    change = compute_change(points)
    assert change.pct is None
    assert change.unavailable_reason == CHANGE_UNAVAILABLE_NO_POINT


def test_change_never_substitutes_the_base_value():
    change = compute_change([])
    assert change.absolute is None and change.pct is None
    assert change.from_date is None and change.to_date is None


def test_spans_break_is_a_property_of_the_span_not_the_window():
    v3 = flat_panel(50)
    v4 = [ConstituentObservation(o.card_print_id, o.index_value_jpy, 4, 2, YUYU)
          for o in flat_panel(50)]
    v4b = [ConstituentObservation(o.card_print_id, o.index_value_jpy, 4, 2, YUYU)
           for o in flat_panel(50)]
    series = build_points([day(D3, v3), day(D4, v4), day(D5, v4b)])
    points = list(series.points)
    assert compute_change(points).spans_break is True
    # A window that starts after the boundary crosses nothing.
    assert compute_change(points, window_start=D5).spans_break is False


# --- scopes -----------------------------------------------------------------


def test_sub_index_scope_opens_its_own_base_on_its_own_first_day():
    """A set scope starting later than the overall series still opens at 1000
    with no carry - which is why 'initial' is recorded explicitly rather than
    inferred from 'earliest row'."""
    series = build_points(
        [day(D5, flat_panel(40)), day(D6, flat_panel(40))],
        scope_kind=SCOPE_SET,
        scope_key="OP-01",
    )
    base = series.points[0]
    assert base.scope_kind == SCOPE_SET
    assert base.scope_key == "OP-01"
    assert base.point_date == D5
    assert base.index_value == BASE_VALUE
    assert base.carried_from_key is None


def test_scope_below_minimum_reports_insufficient_constituents_from_data():
    series = build_points(
        [day(D3, flat_panel(10)), day(D4, flat_panel(10))],
        scope_kind=SCOPE_SET,
        scope_key="OP-03",
    )
    assert series.points[1].unpublishable_reason == (
        UNPUBLISHABLE_INSUFFICIENT_CONSTITUENTS
    )


# --- sparse history ---------------------------------------------------------


def test_a_single_day_of_history_is_just_a_base():
    series = build_points([day(D3, flat_panel(50))])
    assert len(series.points) == 1
    assert series.points[0].is_base is True
    change = compute_change(list(series.points))
    assert change.pct == Decimal("0.000000")
    assert change.from_date == change.to_date == D3


def test_empty_history_produces_no_points():
    series = build_points([])
    assert series.points == ()
    assert series.breaks == ()


# --- determinism ------------------------------------------------------------


def test_input_order_does_not_affect_the_result():
    """Nothing may depend on the order rows arrive in - not day order, and
    not observation order within a day."""
    shuffled_days = list(reversed(STAGING_DAYS))
    shuffled_rows = [
        SnapshotDay(d.point_date, tuple(reversed(d.observations)))
        for d in shuffled_days
    ]
    a = build_points(STAGING_DAYS).points
    b = build_points(shuffled_rows).points
    assert [_signature(p) for p in a] == [_signature(p) for p in b]


def test_two_independent_builds_are_identical():
    a = build_points(STAGING_DAYS).points
    b = build_points(STAGING_DAYS).points
    assert [_signature(p) for p in a] == [_signature(p) for p in b]


def _signature(point):
    """Everything a rebuild must reproduce. No ids, no clocks."""
    return (
        point.natural_key,
        point.index_version,
        point.source_semantics_version,
        None if point.index_value is None else str(point.index_value),
        point.is_base,
        point.carried_from_key,
        point.prior_point_date,
        point.step_days,
        None
        if point.chain_link_log_return is None
        else str(point.chain_link_log_return.normalize()),
        point.constituent_count,
        point.eligible_print_count,
        point.movers_up,
        point.movers_down,
        point.movers_flat,
        point.capped_count,
        point.unpublishable_reason,
    )


def test_no_binary_float_reaches_a_level_or_a_step():
    for point in build_points(STAGING_DAYS).points:
        assert point.index_value is None or isinstance(point.index_value, Decimal)
        assert point.chain_link_log_return is None or isinstance(
            point.chain_link_log_return, Decimal
        )


def test_levels_and_steps_carry_the_column_precision():
    for point in build_points(STAGING_DAYS).points:
        if point.index_value is not None:
            assert point.index_value.as_tuple().exponent == -4
        if point.chain_link_log_return is not None:
            assert point.chain_link_log_return.as_tuple().exponent == -12


def test_chain_uses_the_published_prior_level():
    """Chaining from the published (quantized) level rather than an unrounded
    running total is what makes a carried base's value EXACTLY equal to its
    source's, which the composite foreign key requires."""
    level = chain(Decimal("1000.0000"), Decimal("0.000840502227"))
    assert level == Decimal("1000.8409")
    assert chain(level, Decimal("0.000116689761")) == Decimal("1000.9577")


# --- what must never appear -------------------------------------------------


def test_the_rejected_estimators_are_absent_from_the_implementation():
    """Section 2: no median, no winsorization, no trimming, no weighting.

    Checks EXECUTABLE CODE only - identifiers and literals - not comments or
    docstrings, which legitimately name the rejected estimators in order to
    explain why they were rejected. Tokenizing rather than grepping is what
    makes that distinction; a plain substring search would either fail on the
    explanations or have to be loosened until it proved nothing.
    """
    import io
    import pathlib
    import tokenize

    import app.services.card_pirate_index as module

    source = pathlib.Path(module.__file__).read_text()
    code_tokens = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE):
            continue
        if token.type == tokenize.STRING:
            continue  # docstrings and messages
        code_tokens.append(token.string.lower())
    body = " ".join(code_tokens)

    for forbidden in (
        "median", "winsor", "percentile", "trimmed", "trim", "market_cap",
        "weighted", "weight",
    ):
        assert forbidden not in body, f"{forbidden!r} appears in executable code"
