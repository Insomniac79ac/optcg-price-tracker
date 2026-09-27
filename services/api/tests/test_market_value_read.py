from datetime import date, timedelta
from decimal import Decimal, localcontext

import pytest
from sqlalchemy import select

from app.models.market_value_point import MarketValuePoint
from app.services.market_value import PublicationReason
from app.services.market_value_read import (
    MarketValueUnavailableError,
    _movement,
    _series,
    get_market_value,
    list_market_value_releases,
)
from tests._market_value_read_helpers import END, frozen_census, points, release, seed


def test_frozen_sep26_census(db_session):
    frozen_census(db_session)
    overall = get_market_value(db_session)
    assert overall.as_of == END
    assert overall.tracked_value.value_jpy == 262279
    assert overall.tracked_value.priced_print_count == 639
    assert overall.tracked_value.total_physical_print_count == 4316
    assert overall.tracked_value.is_partial is True
    assert overall.movement.available is True
    assert abs(overall.movement.pct - Decimal("-3.943982")) < Decimal("0.000001")
    assert get_market_value(db_session, window="30d").movement.available is False
    for release_id, value, priced, physical in [
        (174, 480, 4, 154),
        (186, 14780, 20, 169),
    ]:
        for window in ("7d", "30d"):
            row = get_market_value(
                db_session, release_product_id=release_id, window=window
            )
            assert row.as_of == END
            assert row.tracked_value.value_jpy == value
            assert row.tracked_value.priced_print_count == priced
            assert row.tracked_value.total_physical_print_count == physical
            assert row.movement.available is False
            assert row.movement.fraction is row.movement.pct is None
    summaries = list_market_value_releases(db_session).items
    assert len(summaries) == 59
    assert sum(row.seven_day.available for row in summaries) == 9
    assert sum(row.thirty_day.available for row in summaries) == 0
    assert (
        next(
            row for row in summaries if row.release_code == "OP-09"
        ).tracked_value.value_jpy
        is None
    )


@pytest.mark.parametrize("window,number", [("7d", 8), ("30d", 31), ("all", 37)])
def test_windows_end_at_persisted_date_not_wall_clock(db_session, window, number):
    seed(db_session, count=37)
    result = get_market_value(db_session, window=window)
    assert result.as_of == END
    assert len(result.series) == number
    assert result.series[0].date == END - timedelta(days=number - 1)
    assert result.movement.from_date == result.series[0].date
    assert result.movement.to_date == END
    assert result.movement.available is True
    assert result.movement.pct == Decimal(0)  # A proven quiet span really is zero.


@pytest.mark.parametrize("window", ["7d", "30d", "all"])
def test_single_point_never_claims_flat_movement(db_session, window):
    seed(db_session, count=1)
    result = get_market_value(db_session, window=window)
    assert result.movement.available is False
    assert result.movement.pct is result.movement.fraction is None
    assert result.movement.reason == "insufficient_window_continuity"


@pytest.mark.parametrize("offset", range(8))
def test_every_required_date_is_required(offset):
    rows = points(count=8)
    # A missing final day changes as_of; remove it but retain the requested
    # window's required start check, so the shorter history is still refused.
    del rows[offset]
    result = _movement(rows, "7d")
    assert result.available is False
    assert result.pct is result.fraction is None
    assert result.reason == "insufficient_window_continuity"


@pytest.mark.parametrize(
    "reason", [r.value for r in PublicationReason if r.value != "publishable"]
)
def test_every_persisted_publication_failure_invalidates_span(reason):
    result = _movement(points(breaks={END - timedelta(days=3): reason}), "7d")
    assert result.available is False
    assert result.reason == reason
    assert result.pct is result.fraction is None


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ({"segment_number": 9}, "segment_break"),
        (
            {"prior_point_date": END - timedelta(days=2)},
            "insufficient_window_continuity",
        ),
        ({"step_days": 2}, "insufficient_window_continuity"),
        ({"performance_factor": Decimal(0)}, "invalid_chain_evidence"),
        ({"prior_comparable_value_jpy": 0}, "invalid_chain_evidence"),
        ({"current_comparable_value_jpy": -1}, "invalid_chain_evidence"),
        ({"step_ratio": None}, "invalid_chain_evidence"),
        ({"methodology_version": 2}, "invalid_chain_evidence"),
    ],
)
def test_inconsistent_chain_fails_closed(mutation, reason):
    rows = points()
    for field, value in mutation.items():
        setattr(rows[-1], field, value)
    assert _movement(rows, "7d").reason == reason


def test_unknown_reason_never_leaks_internal_text():
    result = _movement(points(breaks={END: "internal-secret|something"}), "7d")
    assert result.reason == "invalid_chain_evidence"


def test_break_before_window_does_not_invalidate_valid_span(db_session):
    seed(
        db_session, count=31, breaks={END - timedelta(days=7): "index_version_changed"}
    )
    result = get_market_value(db_session)
    assert result.movement.available is True
    assert result.series[0].performance_pct is None  # Reset 1 is not daily 0%.
    assert result.series[1].performance_pct == 0
    assert get_market_value(db_session, window="30d").movement.available is False


def test_chart_rebases_stored_factors_and_never_raw_sums():
    rows = points()
    rows[0].performance_factor = Decimal("1.25")
    for row in rows[1:]:
        row.performance_factor = Decimal("1.50")
        row.tracked_value_jpy = 999999
    chart = _series(rows)
    assert chart[0].performance_pct == 0
    assert chart[-1].performance_pct == Decimal(20)
    assert _movement(rows, "7d").pct == 0  # Stored comparable evidence is flat.


def test_chart_never_connects_to_later_segment_or_across_missing_date():
    rows = points(breaks={END - timedelta(days=3): "insufficient_physical_coverage"})
    chart = _series(rows)
    assert all(row.performance_pct == 0 for row in chart[:4])
    assert all(row.performance_pct is None for row in chart[4:])
    rows = points()
    del rows[3]
    chart = _series(rows)
    assert all(row.performance_pct is None for row in chart[3:])


def test_no_price_rows_keep_null_values_and_performance(db_session):
    seed(
        db_session,
        value=0,
        priced=0,
        physical=154,
        breaks={
            END - timedelta(days=n): "non_positive_comparable_value" for n in range(7)
        },
    )
    result = get_market_value(db_session)
    assert result.tracked_value.value_jpy is None
    assert result.tracked_value.is_partial is True
    assert result.tracked_value.physical_coverage_pct == 0
    assert all(point.performance_pct is None for point in result.series)
    assert result.movement.pct is None


def test_empty_population_has_undefined_coverage(db_session):
    seed(db_session, count=1, value=0, priced=0, physical=0)
    assert get_market_value(db_session).tracked_value.physical_coverage_pct is None


def test_unknown_methodology_never_mixes_into_v1(db_session):
    seed(db_session)
    seed(db_session, end=END + timedelta(days=10), methodology_version=2, value=999999)
    result = get_market_value(db_session, window="all")
    assert result.as_of == END
    assert result.methodology_version == 1
    assert result.tracked_value.value_jpy == 30000


def test_only_unsupported_methodology_is_unavailable(db_session):
    seed(db_session, methodology_version=2)
    with pytest.raises(MarketValueUnavailableError):
        get_market_value(db_session)


def test_release_order_uses_official_dates_and_same_day_fallback(db_session):
    seed(db_session)
    for release_id, code, released in [
        (999, "OP-99", date(2020, 1, 1)),
        (1, "OP-01", date(2025, 1, 1)),
        (3, "OP-03", None),
        (2, "OP-02", date(2025, 1, 1)),
    ]:
        release(db_session, release_id, code, released)
        seed(db_session, release_id=release_id, value=release_id * 1000)
    result = list_market_value_releases(db_session)
    assert [row.release_product_id for row in result.items] == [1, 2, 999, 3]
    assert result.ordering_basis == "released_on_desc_then_deterministic_fallback"


def test_list_retains_sparse_older_scopes_and_uses_own_as_of(db_session):
    seed(db_session)
    release(db_session)
    seed(
        db_session,
        release_id=174,
        count=1,
        end=END - timedelta(days=50),
        value=480,
        priced=4,
        physical=154,
    )
    result = list_market_value_releases(db_session).items
    assert len(result) == 1
    assert result[0].as_of == END - timedelta(days=50)
    assert result[0].seven_day.available is False


def test_uncoded_release_is_addressable_but_not_in_coded_list(db_session):
    seed(db_session)
    release(db_session, code=None)
    seed(db_session, release_id=174)
    assert get_market_value(db_session, release_product_id=174).release_code is None
    assert list_market_value_releases(db_session).items == []


@pytest.mark.parametrize(
    "product_overrides,physical",
    [
        ({"source_catalogue": "bandai_en"}, 300),
        ({"verification_status": "unverified"}, 300),
        ({}, 0),
    ],
)
def test_list_excludes_out_of_scope_or_inactive_persisted_products(
    db_session, product_overrides, physical
):
    seed(db_session)
    release(db_session, **product_overrides)
    seed(
        db_session,
        release_id=174,
        count=1,
        physical=physical,
        priced=physical,
        value=100 if physical else 0,
    )
    assert list_market_value_releases(db_session).items == []


def test_decimal_arithmetic_is_independent_of_ambient_precision():
    rows = points(last_pair=(30000, 27001))
    with localcontext() as context:
        context.prec = 6
        low = (_movement(rows, "7d"), _series(rows))
    with localcontext() as context:
        context.prec = 70
        high = (_movement(rows, "7d"), _series(rows))
    assert low == high
    assert isinstance(high[0].fraction, Decimal)


def test_persisted_chain_matches_a2_exact_window_oracle(db_session):
    from dataclasses import replace
    from app.services.market_value import MarketValueScope, evaluate_market_value_window
    from app.services.market_value_replay import (
        build_market_value_point_drafts,
        scope_replay_days,
    )
    from tests.test_market_value_persistence import replay_fixture

    original = replay_fixture(release_product_id=174)
    dates = tuple(END - timedelta(days=n) for n in reversed(range(31)))
    observations = {
        day: tuple(
            replace(row, value_jpy=100 + offset)
            for row in original.current_observations
        )
        for offset, day in enumerate(dates)
    }
    fixture = replace(original, archive_dates=dates, observations_by_date=observations)
    release(db_session)
    db_session.add_all(
        [
            MarketValuePoint(**draft.values())
            for draft in build_market_value_point_drafts(fixture)
        ]
    )
    db_session.commit()
    for release_id in (None, 174):
        scope = (
            MarketValueScope.overall()
            if release_id is None
            else MarketValueScope.release(release_id)
        )
        days = scope_replay_days(fixture, scope=scope, total_physical_print_count=300)
        for window in (7, 30):
            expected = evaluate_market_value_window(
                days, scope=scope, window_days=window
            )
            result = get_market_value(
                db_session, release_product_id=release_id, window=f"{window}d"
            )
            assert result.movement.fraction == expected.movement_fraction
            assert result.movement.pct == expected.movement_pct
            assert result.movement.available == expected.available


def test_read_service_does_not_autoflush_pending_changes(db_session):
    seed(db_session)
    row = db_session.scalar(
        select(MarketValuePoint).where(MarketValuePoint.point_date == END)
    )
    row.tracked_value_jpy = 77777
    db_session.autoflush = True
    get_market_value(db_session)
    assert row in db_session.dirty
    db_session.rollback()
    assert get_market_value(db_session).tracked_value.value_jpy == 30000
