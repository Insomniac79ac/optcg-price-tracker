"""The source cutover splice (new-sources plan §2.6). Synthetic replays only; inert without a row."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction

import pytest

from app.schemas import MarketIndexSourceValueOut, PrintMarketIndexOut
from app.services import card_pirate_index as cpi
from app.services import market_value as mv
from app.services.market_index_change import (
    NOT_COMPARABLE_CONTRIBUTORS,
    get_index_change_7d_for_prints,
)
from app.services.market_index_splice import (
    REFUSE_BLANK_APPROVER,
    REFUSE_IN_THE_PAST,
    REFUSE_NOT_ONE_STEP,
    REFUSE_SOURCE_ALREADY_SPLICED,
    REFUSE_TOO_CLOSE,
    REFUSE_VERSION_ORDER,
    IndexPoint,
    Splice,
    SpliceRefused,
    build_splice_snapshot_row,
    check_new_splice,
    old_basis_fields,
    splice_between,
    spliced_ratio,
    write_splice_snapshots,
)
from app.source_products.models import MarketIndexSplice, MarketIndexSpliceSnapshot
from app.models import MarketIndexSnapshot

TODAY = date(2026, 11, 20)
SPLICE_DAY = TODAY - timedelta(days=3)
YUYU = ("yuyutei", "retail_sell")
SNKR = ("snkrdunk", "listing_floor")
DORA = ("dorasuta", "retail_sell")


def value(pair, jpy, *, contributes=True):
    return MarketIndexSourceValueOut(
        source=pair[0], reference_type=pair[1], evidence_type="listing", value_jpy=jpy,
        observed_at=datetime(2026, 11, 20, tzinfo=timezone.utc), sample_size=None, stale=False,
        eligible=contributes, fallback_used=False, contributes_to_index=contributes,
    )


def live(values, *, index_value, ssv=4, print_id=1, at=datetime(2026, 11, 20, 1, tzinfo=timezone.utc)):
    return PrintMarketIndexOut(
        card_print_id=print_id, index_version=3, source_semantics_version=ssv, index_value_jpy=index_value,
        calculation_method="median_of_sources", source_count=len(values), coverage_status="full",
        confidence="high", source_values=values, auxiliary_values=[], freshest_observation_at=None,
        stalest_eligible_source_at=None, stale_sources=[], calculated_at=at,
    )


def point(value_jpy, *pairs, ssv=3):
    return IndexPoint(value_jpy, 3, ssv, [value(p, 1).model_dump(mode="json") for p in pairs])


SPLICE = Splice(id=1, splice_date=SPLICE_DAY, from_version=3, to_version=4, source_added="dorasuta")


# --- the rules for recording a splice ----------------------------------------------------------


def _check(existing=(), **kw):
    args = dict(splice_date=TODAY, from_version=3, to_version=4, source_added="dorasuta",
                approved_by="owner", today=TODAY)
    args.update(kw)
    check_new_splice(list(existing), **args)


def test_a_first_splice_one_step_from_today_is_allowed():
    _check()


@pytest.mark.parametrize(
    "kwargs, code",
    [
        ({"to_version": 5}, REFUSE_NOT_ONE_STEP),
        ({"splice_date": TODAY - timedelta(days=1)}, REFUSE_IN_THE_PAST),
        ({"approved_by": "  "}, REFUSE_BLANK_APPROVER),
    ],
)
def test_malformed_splices_are_refused(kwargs, code):
    with pytest.raises(SpliceRefused) as refused:
        _check(**kwargs)
    assert refused.value.code == code


def test_one_splice_per_source_fourteen_days_apart_continuing_the_versions():
    dorasuta = Splice(1, TODAY - timedelta(days=20), 3, 4, "dorasuta")
    with pytest.raises(SpliceRefused) as again:
        _check([dorasuta], from_version=4, to_version=5)
    assert again.value.code == REFUSE_SOURCE_ALREADY_SPLICED
    recent = Splice(1, TODAY - timedelta(days=13), 3, 4, "dorasuta")
    with pytest.raises(SpliceRefused) as close:
        _check([recent], source_added="cardrush", from_version=4, to_version=5)
    assert close.value.code == REFUSE_TOO_CLOSE
    with pytest.raises(SpliceRefused) as order:
        _check([dorasuta], source_added="cardrush", from_version=3, to_version=4)
    assert order.value.code == REFUSE_VERSION_ORDER
    _check([dorasuta], source_added="cardrush", from_version=4, to_version=5)


def test_a_comparison_crosses_exactly_one_matching_splice():
    second = Splice(2, SPLICE_DAY + timedelta(days=14), 4, 5, "cardrush")
    found = splice_between([SPLICE, second], from_version=3, to_version=4,
                           after=SPLICE_DAY - timedelta(days=7), on_or_before=SPLICE_DAY)
    assert found == SPLICE
    assert splice_between([SPLICE, second], from_version=3, to_version=5,
                          after=SPLICE_DAY - timedelta(days=1), on_or_before=second.splice_date) is None
    assert splice_between([SPLICE], from_version=2, to_version=3,
                          after=SPLICE_DAY - timedelta(days=1), on_or_before=TODAY) is None
    assert splice_between([], from_version=3, to_version=4, after=SPLICE_DAY, on_or_before=TODAY) is None


# --- the old basis ------------------------------------------------------------------------------


def test_old_basis_leaves_out_the_added_source_and_keeps_the_combination():
    index = live([value(YUYU, 1000), value(SNKR, 1200), value(DORA, 1600)], index_value=1200)
    fields = old_basis_fields(index, SPLICE)
    assert (fields["index_value_jpy"], fields["source_count"], fields["coverage_status"]) == (1100, 2, "full")
    assert fields["source_semantics_version"] == 3
    assert {v.source for v in fields["source_values"]} == {"yuyutei", "snkrdunk"}
    solo = old_basis_fields(live([value(DORA, 1600)], index_value=1600), SPLICE)
    assert (solo["index_value_jpy"], solo["coverage_status"]) == (None, "none")


def test_old_basis_refuses_a_live_index_on_another_version():
    with pytest.raises(SpliceRefused):
        old_basis_fields(live([value(YUYU, 1000)], index_value=1000, ssv=3), SPLICE)


# --- the two legs -------------------------------------------------------------------------------


def test_a_spliced_ratio_is_the_product_of_two_comparable_legs():
    ratio, refusal = spliced_ratio(point(1000, YUYU, SNKR), point(1100, YUYU, SNKR),
                                   point(1200, YUYU, SNKR, DORA, ssv=4), point(1260, YUYU, SNKR, DORA, ssv=4))
    assert refusal is None and ratio == Fraction(1100, 1000) * Fraction(1260, 1200)


def test_each_leg_keeps_every_guard():
    _, refusal = spliced_ratio(point(1000, YUYU), point(1100, YUYU, SNKR),
                               point(1200, YUYU, SNKR, DORA, ssv=4), point(1260, YUYU, SNKR, DORA, ssv=4))
    assert refusal == NOT_COMPARABLE_CONTRIBUTORS
    _, refusal = spliced_ratio(point(1000, YUYU), point(1100, YUYU),
                               point(1200, YUYU, DORA, ssv=4), point(1260, YUYU, ssv=4))
    assert refusal == NOT_COMPARABLE_CONTRIBUTORS


# --- per-print 7D change ------------------------------------------------------------------------


def _snapshot(db, day, value_jpy, pairs, ssv, print_id=1):
    row = MarketIndexSnapshot(
        card_print_id=print_id, calculated_at=datetime.combine(day, datetime.min.time(), timezone.utc),
        snapshot_date=day, index_value_jpy=value_jpy, calculation_method="test", source_count=len(pairs),
        coverage_status="full", confidence="high", index_version=3, source_semantics_version=ssv,
        provenance={"source_values": [value(p, 1).model_dump(mode="json") for p in pairs]},
    )
    db.add(row)
    db.flush()
    return row


def test_seven_day_change_is_null_across_a_version_step_without_a_splice(db_session):
    _snapshot(db_session, TODAY - timedelta(days=7), 1000, [YUYU], 3)
    current = live([value(YUYU, 1050), value(DORA, 1200)], index_value=1125)
    assert get_index_change_7d_for_prints(db_session, {1: current}, today=TODAY) == {1: None}


def test_seven_day_change_chains_across_a_splice(db_session):
    _snapshot(db_session, TODAY - timedelta(days=7), 1000, [YUYU], 3)
    _snapshot(db_session, SPLICE_DAY, 1150, [YUYU, DORA], 4)
    row = MarketIndexSplice(splice_date=SPLICE_DAY, from_semantics_version=3, to_semantics_version=4,
                            source_added="dorasuta", approved_by="owner", approved_at=datetime.now(timezone.utc))
    db_session.add(row)
    db_session.flush()
    db_session.add(MarketIndexSpliceSnapshot(
        splice_id=row.id, card_print_id=1, snapshot_date=SPLICE_DAY, index_value_jpy=1040,
        calculation_method="median_of_sources", source_count=1, coverage_status="limited", confidence="medium",
        index_version=3, source_semantics_version=3, calculated_at=datetime.now(timezone.utc),
        provenance={"source_values": [value(YUYU, 1040).model_dump(mode="json")]},
    ))
    db_session.flush()
    current = live([value(YUYU, 1050), value(DORA, 1250)], index_value=1150)
    change = get_index_change_7d_for_prints(db_session, {1: current}, today=TODAY)[1]
    assert change == pytest.approx(((1040 / 1000) * (1150 / 1150) - 1) * 100)


def test_writer_archives_old_basis_rows_once(db_session):
    row = MarketIndexSplice(splice_date=date(2026, 11, 20), from_semantics_version=3, to_semantics_version=4,
                            source_added="dorasuta", approved_by="owner", approved_at=datetime.now(timezone.utc))
    db_session.add(row)
    db_session.flush()
    splice = Splice.from_row(row)
    index = live([value(YUYU, 1000), value(DORA, 1600)], index_value=1300)
    assert build_splice_snapshot_row(index, splice)["index_value_jpy"] == 1000
    write_splice_snapshots(db_session, splice, [index])
    write_splice_snapshots(db_session, splice, [index])
    stored = db_session.query(MarketIndexSpliceSnapshot).one()
    assert (stored.index_value_jpy, stored.source_semantics_version) == (1000, 3)
    late = live([value(YUYU, 1000)], index_value=1000, at=datetime(2026, 11, 21, 1, tzinfo=timezone.utc))
    with pytest.raises(SpliceRefused) as refused:
        write_splice_snapshots(db_session, splice, [late])
    assert refused.value.code == REFUSE_IN_THE_PAST


# --- Card Pirate Index --------------------------------------------------------------------------


def _cpi_day(d, value_jpy, ssv, contributors=frozenset({YUYU})):
    return cpi.SnapshotDay(d, tuple(
        cpi.ConstituentObservation(i, value_jpy, 3, ssv, contributors) for i in range(cpi.MIN_CONSTITUENTS)
    ))


def test_cpi_opens_a_segment_at_the_version_step_without_a_splice():
    d0, d1, d2 = (SPLICE_DAY + timedelta(days=n) for n in (-1, 0, 1))
    days = [_cpi_day(d0, 100, 3), _cpi_day(d1, 120, 4, frozenset({YUYU, DORA})),
            _cpi_day(d2, 120, 4, frozenset({YUYU, DORA}))]
    series = cpi.build_points(days)
    assert [b.at for b in series.breaks] == [d1]
    assert series.points[1].is_base and series.points[1].index_value == series.points[0].index_value


def test_cpi_steps_into_the_splice_day_on_the_old_basis():
    d0, d1, d2 = (SPLICE_DAY + timedelta(days=n) for n in (-1, 0, 1))
    new_d1 = _cpi_day(d1, 120, 4, frozenset({YUYU, DORA}))
    old_d1 = _cpi_day(d1, 105, 3)
    days = [_cpi_day(d0, 100, 3), new_d1, _cpi_day(d2, 132, 4, frozenset({YUYU, DORA}))]
    series = cpi.build_points(days, splice_days={d1: old_d1})
    assert series.breaks == ()
    first, spliced, after = series.points
    assert not spliced.is_base and spliced.source_semantics_version == 4
    assert spliced.index_value == cpi.chain(first.index_value, cpi.compute_step(days[0], old_d1).step_log_return)
    assert after.index_value == cpi.chain(spliced.index_value, cpi.compute_step(new_d1, days[2]).step_log_return)


def test_cpi_ignores_a_splice_day_on_the_wrong_versions():
    d0, d1 = SPLICE_DAY - timedelta(days=1), SPLICE_DAY
    days = [_cpi_day(d0, 100, 3), _cpi_day(d1, 120, 5)]
    series = cpi.build_points(days, splice_days={d1: _cpi_day(d1, 105, 3)})
    assert [b.at for b in series.breaks] == [d1]
    assert series.points[1].is_base


# --- Market Value -------------------------------------------------------------------------------


def _mv_day(d, value_jpy, ssv, contributors=frozenset({YUYU})):
    rows = tuple(mv.MarketValueObservation(i, value_jpy, 3, ssv, contributors, release_product_id=1)
                 for i in range(1, 11))
    return mv.MarketValueDay(d, rows, 10, "membership-v1")


def _mv_week():
    start = TODAY - timedelta(days=7)
    days = []
    for n in range(8):
        d = start + timedelta(days=n)
        days.append(_mv_day(d, 100, 3) if d < SPLICE_DAY else _mv_day(d, 130, 4, frozenset({YUYU, DORA})))
    return days, {SPLICE_DAY: _mv_day(SPLICE_DAY, 110, 3)}


def test_market_value_window_is_unavailable_across_a_step_without_a_splice():
    days, _ = _mv_week()
    window = mv.evaluate_market_value_window(days, scope=mv.MarketValueScope.release(1), window_days=7)
    assert not window.available
    assert mv.PublicationReason.SOURCE_SEMANTICS_VERSION_CHANGED in window.reasons


def test_market_value_window_and_replay_chain_across_a_splice():
    days, splice_days = _mv_week()
    scope = mv.MarketValueScope.release(1)
    window = mv.evaluate_market_value_window(days, scope=scope, window_days=7, splice_days=splice_days)
    assert window.available and window.movement_fraction == Decimal("0.1")
    replay = mv.replay_market_value(days, scope=scope, splice_days=splice_days)
    assert all(p.break_reason is None for p in replay)
    assert replay[-1].performance_factor == Decimal("1.1")
    plain = mv.replay_market_value(days, scope=scope)
    assert any(p.break_reason is not None for p in plain)
