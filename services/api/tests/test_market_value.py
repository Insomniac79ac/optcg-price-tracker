"""Frozen methodology tests for the A2 monetary basket engine."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from app.services.market_value import (
    CALCULATION_DECIMAL_PRECISION,
    MarketValueDay,
    MarketValueObservation,
    MarketValueScope,
    PublicationReason,
    TrackedValueStatus,
    compute_monetary_step,
    current_tracked_value,
    evaluate_market_value_publication,
    evaluate_market_value_window,
    replay_market_value,
)
from app.services.market_value_replay import (
    ActiveCodedRelease,
    ActivePrintIdentity,
    MarketValueReplayInput,
    scope_replay_days,
)

CONTRIBUTORS = frozenset({("yuyutei", "retail_ask")})
START = date(2026, 9, 18)


def observation(
    print_id: int,
    value: int | None,
    *,
    release_id: int = 1,
    index_version: int = 3,
    semantics_version: int = 2,
    contributors: frozenset[tuple[str, str]] | None = CONTRIBUTORS,
) -> MarketValueObservation:
    return MarketValueObservation(
        card_print_id=print_id,
        value_jpy=value,
        index_version=index_version,
        source_semantics_version=semantics_version,
        contributors=contributors,
        release_product_id=release_id,
    )


def day(
    offset: int,
    rows: list[MarketValueObservation],
    *,
    total: int,
    revision: str = "membership-v1",
) -> MarketValueDay:
    return MarketValueDay(
        point_date=START + timedelta(days=offset),
        observations=tuple(rows),
        total_physical_print_count=total,
        membership_revision=revision,
    )


def stable_rows(
    count: int,
    *,
    value: int = 100,
    release_id: int = 1,
    index_version: int = 3,
) -> list[MarketValueObservation]:
    return [
        observation(
            print_id,
            value,
            release_id=release_id,
            index_version=index_version,
        )
        for print_id in range(1, count + 1)
    ]


def decision(
    prior_rows: list[MarketValueObservation],
    current_rows: list[MarketValueObservation],
    *,
    total: int,
    scope: MarketValueScope | None = None,
):
    resolved_scope = scope or MarketValueScope.release(1)
    step = compute_monetary_step(
        day(0, prior_rows, total=total),
        day(1, current_rows, total=total),
        scope=resolved_scope,
    )
    return step, evaluate_market_value_publication(step, scope=resolved_scope)


def test_current_tracked_value_is_literal_partial_jpy_sum() -> None:
    result = current_tracked_value(
        [observation(3, 300), observation(1, 100), observation(2, None)],
        total_physical_print_count=4,
        scope=MarketValueScope.release(1),
    )
    assert result.value_jpy == 400
    assert result.priced_print_count == 2
    assert result.physical_coverage_fraction == Decimal("0.5")
    assert result.status is TrackedValueStatus.PARTIAL
    assert result.is_partial is True
    assert result.headline_eligible is False


def test_no_usable_prices_is_null_not_zero() -> None:
    result = current_tracked_value(
        [observation(1, None), observation(2, 0), observation(3, -5)],
        total_physical_print_count=3,
        scope=MarketValueScope.overall(),
    )
    assert result.value_jpy is None
    assert result.priced_print_count == 0
    assert result.status is TrackedValueStatus.NO_PRICES


def test_one_physical_print_cannot_be_counted_twice() -> None:
    with pytest.raises(ValueError, match="duplicate card_print_id"):
        current_tracked_value(
            [observation(1, 100), observation(1, 100)],
            total_physical_print_count=2,
            scope=MarketValueScope.overall(),
        )


def test_expensive_print_naturally_has_more_basket_weight() -> None:
    step, _ = decision(
        [observation(1, 100), observation(2, 100_000)],
        [observation(1, 200), observation(2, 100_000)],
        total=2,
    )
    with localcontext() as context:
        context.prec = CALCULATION_DECIMAL_PRECISION
        expected_ratio = Decimal(100_200) / Decimal(100_100)
    assert step.ratio == expected_ratio
    precision = Decimal("0.000000000000000000000001")
    assert step.return_fraction.quantize(precision) == (
        Decimal(100) / Decimal(100_100)
    ).quantize(precision)
    assert step.return_fraction != Decimal("0.5")
    assert sum(
        row.percentage_point_contribution for row in step.contributions
    ).quantize(precision) == step.return_pct.quantize(
        precision
    )


def test_expensive_entrant_changes_sum_but_not_appreciation() -> None:
    prior = stable_rows(40, value=1)
    current = stable_rows(40, value=1) + [observation(41, 100_000)]
    step, publication = decision(prior, current, total=100)
    assert step.prior_tracked.value_jpy == 40
    assert step.current_tracked.value_jpy == 100_040
    assert step.return_fraction == Decimal(0)
    assert ("entrant", 1) in step.exclusion_counts
    assert publication.publishable is False
    assert PublicationReason.INSUFFICIENT_COMPARABLE_VALUE_COVERAGE in (
        publication.reasons
    )


def test_expensive_leaver_changes_sum_but_not_market_decline() -> None:
    prior = stable_rows(40, value=1) + [observation(41, 100_000)]
    current = stable_rows(40, value=1)
    step, publication = decision(prior, current, total=100)
    assert step.prior_tracked.value_jpy == 100_040
    assert step.current_tracked.value_jpy == 40
    assert step.return_fraction == Decimal(0)
    assert ("leaver", 1) in step.exclusion_counts
    assert publication.publishable is False


def test_stable_comparable_panel_increasing_ten_percent_reports_ten_percent() -> None:
    step, publication = decision(
        stable_rows(40, value=100), stable_rows(40, value=110), total=100
    )
    assert step.return_fraction == Decimal("0.10")
    assert publication.publishable is True


def test_reentry_does_not_bridge_absent_day() -> None:
    days = (
        day(0, stable_rows(40), total=100),
        day(1, stable_rows(39), total=100),
        day(2, stable_rows(40), total=100),
    )
    leaving = compute_monetary_step(days[0], days[1], scope=MarketValueScope.release(1))
    returning = compute_monetary_step(days[1], days[2], scope=MarketValueScope.release(1))
    assert ("leaver", 1) in leaving.exclusion_counts
    assert ("entrant", 1) in returning.exclusion_counts
    assert returning.comparable_print_count == 39


def test_contributor_churn_excludes_transition() -> None:
    changed = observation(
        1, 100, contributors=frozenset({("snkrdunk", "listing_floor")})
    )
    step, _ = decision(stable_rows(40), [changed, *stable_rows(40)[1:]], total=100)
    assert step.comparable_print_count == 39
    assert ("contributor_set_changed", 1) in step.exclusion_counts


@pytest.mark.parametrize("contributors", [None, frozenset()])
def test_missing_or_empty_contributor_identity_fails_closed(
    contributors: frozenset[tuple[str, str]] | None,
) -> None:
    current = [observation(1, 100, contributors=contributors), *stable_rows(40)[1:]]
    step, _ = decision(stable_rows(40), current, total=100)
    assert step.comparable_print_count == 39
    assert ("contributor_set_unavailable", 1) in step.exclusion_counts


@pytest.mark.parametrize(
    ("field", "expected_exclusion", "expected_publication"),
    [
        ("index", "index_version_changed", PublicationReason.INDEX_VERSION_CHANGED),
        (
            "semantics",
            "source_semantics_version_changed",
            PublicationReason.SOURCE_SEMANTICS_VERSION_CHANGED,
        ),
    ],
)
def test_version_changes_break_comparability(
    field: str,
    expected_exclusion: str,
    expected_publication: PublicationReason,
) -> None:
    current = [
        observation(
            print_id,
            100,
            index_version=4 if field == "index" else 3,
            semantics_version=3 if field == "semantics" else 2,
        )
        for print_id in range(1, 41)
    ]
    step, publication = decision(stable_rows(40), current, total=100)
    assert (expected_exclusion, 40) in step.exclusion_counts
    assert expected_publication in publication.reasons


def test_zero_and_negative_values_never_enter_comparable_panel() -> None:
    prior = stable_rows(40) + [observation(41, 0), observation(42, -10)]
    current = stable_rows(40) + [observation(41, 10), observation(42, 10)]
    step, _ = decision(prior, current, total=100)
    assert step.comparable_print_count == 40
    assert ("entrant", 2) in step.exclusion_counts


def test_input_order_does_not_change_step_or_contribution_order() -> None:
    prior = stable_rows(40)
    current = stable_rows(40, value=105)
    forward, _ = decision(prior, current, total=100)
    reverse, _ = decision(list(reversed(prior)), list(reversed(current)), total=100)
    assert forward == reverse
    assert [row.card_print_id for row in forward.contributions] == list(range(1, 41))


def test_outputs_do_not_depend_on_process_decimal_precision() -> None:
    days = tuple(
        day(offset, stable_rows(10, value=100 + offset), total=10)
        for offset in range(8)
    )
    with localcontext() as context:
        context.prec = 9
        low_precision = evaluate_market_value_window(
            days, scope=MarketValueScope.release(1), window_days=7
        )
    with localcontext() as context:
        context.prec = 40
        high_precision = evaluate_market_value_window(
            days, scope=MarketValueScope.release(1), window_days=7
        )
    assert low_precision == high_precision
    assert low_precision.movement_fraction == Decimal("0.07")


def test_small_release_near_complete_gate_passes() -> None:
    _, publication = decision(stable_rows(12), stable_rows(12), total=15)
    assert publication.publishable is True
    assert publication.required_comparable_prints_current == 12
    assert publication.required_physical_fraction_current == Decimal("0.80")


def test_small_release_below_near_complete_gate_fails() -> None:
    _, publication = decision(stable_rows(11), stable_rows(11), total=15)
    assert publication.publishable is False
    assert PublicationReason.INSUFFICIENT_COMPARABLE_PRINTS in publication.reasons
    assert PublicationReason.INSUFFICIENT_PHYSICAL_COVERAGE in publication.reasons


def test_large_release_count_without_percentage_fails() -> None:
    _, publication = decision(stable_rows(30), stable_rows(30), total=170)
    assert publication.publishable is False
    assert PublicationReason.INSUFFICIENT_PHYSICAL_COVERAGE in publication.reasons


def test_large_release_count_and_percentage_pass() -> None:
    _, publication = decision(stable_rows(40), stable_rows(40), total=100)
    assert publication.publishable is True


def test_release_with_fewer_than_ten_physical_prints_never_publishes() -> None:
    _, publication = decision(stable_rows(9), stable_rows(9), total=9)
    assert publication.publishable is False
    assert PublicationReason.INSUFFICIENT_COMPARABLE_PRINTS in publication.reasons


@pytest.mark.parametrize(("priced", "total"), [(4, 154), (20, 169)])
def test_sparse_op05_and_op17_shaped_releases_fail(priced: int, total: int) -> None:
    _, publication = decision(stable_rows(priced), stable_rows(priced), total=total)
    assert publication.publishable is False
    assert PublicationReason.INSUFFICIENT_COMPARABLE_PRINTS in publication.reasons
    assert PublicationReason.INSUFFICIENT_PHYSICAL_COVERAGE in publication.reasons


def test_comparable_value_share_blocks_many_cheap_comparables() -> None:
    prior = stable_rows(40, value=1) + [observation(41, 10_000)]
    current = stable_rows(40, value=1) + [
        observation(
            41,
            10_000,
            contributors=frozenset({("snkrdunk", "listing_floor")}),
        )
    ]
    step, publication = decision(prior, current, total=100)
    assert step.comparable_print_count == 40
    assert step.comparable_prior_value_fraction < Decimal("0.80")
    assert PublicationReason.INSUFFICIENT_COMPARABLE_VALUE_COVERAGE in (
        publication.reasons
    )


def test_seven_day_window_requires_and_compounds_every_daily_step() -> None:
    days = tuple(
        day(offset, stable_rows(10, value=100 + offset), total=10)
        for offset in range(8)
    )
    result = evaluate_market_value_window(
        days, scope=MarketValueScope.release(1), window_days=7
    )
    assert result.available is True
    assert result.movement_fraction == Decimal(107) / Decimal(100) - Decimal(1)
    assert len(result.steps) == 7
    assert all(decision.publishable for decision in result.decisions)


def test_window_with_missing_intermediate_day_is_unavailable_not_zero() -> None:
    days = tuple(
        day(offset, stable_rows(10), total=10)
        for offset in (0, 1, 2, 4, 5, 6, 7)
    )
    result = evaluate_market_value_window(
        days,
        scope=MarketValueScope.release(1),
        window_days=7,
        end_date=START + timedelta(days=7),
    )
    assert result.available is False
    assert result.movement_fraction is None
    assert result.primary_reason is PublicationReason.INSUFFICIENT_WINDOW_CONTINUITY


def test_window_does_not_skip_an_invalid_intermediate_step() -> None:
    days = [day(offset, stable_rows(40), total=100) for offset in range(8)]
    days[4] = day(
        4,
        [
            observation(
                print_id,
                100,
                contributors=frozenset({("snkrdunk", "listing_floor")}),
            )
            for print_id in range(1, 41)
        ],
        total=100,
    )
    result = evaluate_market_value_window(
        days, scope=MarketValueScope.release(1), window_days=7
    )
    assert result.available is False
    assert result.movement_fraction is None
    assert PublicationReason.NON_POSITIVE_COMPARABLE_VALUE in result.reasons


def test_thirty_day_is_unavailable_when_only_seven_days_exist() -> None:
    days = tuple(day(offset, stable_rows(10), total=10) for offset in range(8))
    result = evaluate_market_value_window(
        days, scope=MarketValueScope.release(1), window_days=30
    )
    assert result.available is False
    assert result.movement_pct is None


def test_release_membership_revision_breaks_release_but_not_overall() -> None:
    prior = day(0, stable_rows(40), total=100, revision="before")
    current = day(1, stable_rows(40), total=100, revision="after")
    release_step = compute_monetary_step(
        prior, current, scope=MarketValueScope.release(1)
    )
    overall_step = compute_monetary_step(
        prior, current, scope=MarketValueScope.overall()
    )
    assert evaluate_market_value_publication(
        release_step, scope=MarketValueScope.release(1)
    ).primary_reason is PublicationReason.MEMBERSHIP_REVISION_CHANGED
    assert evaluate_market_value_publication(
        overall_step, scope=MarketValueScope.overall()
    ).publishable is False  # 40 is below Overall's independent 300-print gate.
    assert PublicationReason.MEMBERSHIP_REVISION_CHANGED not in (
        evaluate_market_value_publication(
            overall_step, scope=MarketValueScope.overall()
        ).reasons
    )


def test_replay_is_deterministic_and_resets_after_a_break() -> None:
    days = (
        day(0, stable_rows(40), total=100),
        day(1, stable_rows(40, value=110), total=100),
        day(2, stable_rows(40, value=120), total=100, revision="membership-v2"),
    )
    first = replay_market_value(days, scope=MarketValueScope.release(1))
    second = replay_market_value(reversed(days), scope=MarketValueScope.release(1))
    assert first == second
    assert first[1].performance_factor == Decimal("1.1")
    assert first[2].performance_factor == Decimal(1)
    assert first[2].break_reason is PublicationReason.MEMBERSHIP_REVISION_CHANGED


def test_release_scope_uses_release_product_id_for_mixed_code_print() -> None:
    # Staging print 3686 is the known EB04-007 p2 printing physically issued
    # in OP-17. There is deliberately no card-code field in this contract.
    loaded = MarketValueReplayInput(
        catalogue_membership_revision="catalogue-v1",
        archive_dates=(START,),
        observations_by_date={
            START: (
                observation(3686, 500, release_id=186),
                observation(10, 100, release_id=173),
            )
        },
        active_prints=(
            ActivePrintIdentity(3686, 186),
            ActivePrintIdentity(10, 173),
        ),
        coded_releases=(ActiveCodedRelease(186, "OP-17", 1),),
        current_observations=(),
        current_as_of=datetime(2026, 9, 18, tzinfo=timezone.utc),
    )
    projected = scope_replay_days(
        loaded,
        scope=MarketValueScope.release(186),
        total_physical_print_count=1,
    )
    assert [row.card_print_id for row in projected[0].observations] == [3686]


def _distributed_rows(
    release_id: int,
    priced: int,
    total_value: int,
    *,
    index_version: int,
) -> list[MarketValueObservation]:
    if priced == 0:
        return []
    quotient, remainder = divmod(total_value, priced)
    return [
        observation(
            release_id * 10_000 + offset,
            quotient + (1 if offset <= remainder else 0),
            release_id=release_id,
            index_version=index_version,
        )
        for offset in range(1, priced + 1)
    ]


def test_frozen_a1_release_census_has_nine_7d_and_zero_30d_qualifiers() -> None:
    fixture_path = (
        Path(__file__).parent / "fixtures" / "market_value_a1_release_coverage.json"
    )
    fixture = json.loads(fixture_path.read_text())
    end = date.fromisoformat(fixture["audit_date"])
    start = end - timedelta(days=30)
    seven_day_qualifiers: list[str] = []
    thirty_day_qualifiers: list[str] = []

    for release in fixture["releases"]:
        days = []
        for offset in range(31):
            point_date = start + timedelta(days=offset)
            # The audited 2026-09-02 -> 03 ruleset transition is inside 30D
            # and outside 7D. It is enough to force a truthful segment break.
            index_version = 2 if point_date <= date(2026, 9, 2) else 3
            days.append(
                MarketValueDay(
                    point_date=point_date,
                    observations=tuple(
                        _distributed_rows(
                            release["id"],
                            release["priced"],
                            release["value_jpy"],
                            index_version=index_version,
                        )
                    ),
                    total_physical_print_count=release["physical"],
                    membership_revision="a1-current-corrected-membership",
                )
            )
        scope = MarketValueScope.release(release["id"])
        if evaluate_market_value_window(
            days, scope=scope, window_days=7, end_date=end
        ).available:
            seven_day_qualifiers.append(release["code"])
        if evaluate_market_value_window(
            days, scope=scope, window_days=30, end_date=end
        ).available:
            thirty_day_qualifiers.append(release["code"])

    assert len(fixture["releases"]) == 59
    assert seven_day_qualifiers == [
        "EB-01",
        "EB-02",
        "EB-03",
        "EB-04",
        "OP-01",
        "OP-02",
        "OP-03",
        "OP-04",
        "OP-13",
    ]
    assert len(seven_day_qualifiers) == fixture["expected_7d_qualifiers"]
    assert len(thirty_day_qualifiers) == fixture["expected_30d_qualifiers"]
