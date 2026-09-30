from datetime import datetime, timedelta, timezone

import pytest

from app.services.freshness_policy import FreshnessPolicy, derived_freshness

T0 = datetime(2026, 9, 30, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("source", ["yuyutei", "snkrdunk"])
@pytest.mark.parametrize("category", ["raw", "psa10"])
@pytest.mark.parametrize("high,target", [(False, 24), (True, 4)])
def test_same_policy_across_sources_and_grade(source, category, high, target):
    policy = FreshnessPolicy(headroom=timedelta(minutes=30))
    assert policy.next_due(T0, high_interest=high) == T0 + timedelta(
        hours=target, minutes=-30
    )
    assert policy.is_fresh(
        T0,
        high_interest=high,
        clock=lambda: T0 + timedelta(hours=target) - timedelta(microseconds=1),
    )
    assert not policy.is_fresh(
        T0, high_interest=high, clock=lambda: T0 + timedelta(hours=target)
    )


def test_derived_inputs_not_recalculation_time_and_coverage_separate():
    now = T0 + timedelta(hours=25)
    result = derived_freshness(
        [T0, now], expected_count=3, high_interest=False, clock=lambda: now
    )
    assert result.status == "stale"
    assert result.oldest_input_at == T0
    assert not result.coverage_complete
    assert (
        derived_freshness(
            [None, now], expected_count=2, high_interest=False, clock=lambda: now
        ).status
        == "unknown"
    )
    assert (
        derived_freshness(
            [T0],
            expected_count=1,
            high_interest=False,
            historical=True,
            clock=lambda: now,
        ).status
        == "historical"
    )


def test_utc_and_headroom_are_strict():
    with pytest.raises(ValueError):
        FreshnessPolicy(headroom=timedelta(hours=4))
    with pytest.raises(ValueError):
        FreshnessPolicy().is_fresh(T0.replace(tzinfo=None), high_interest=False)


def test_future_and_unknown_evidence_cannot_be_fresh():
    policy = FreshnessPolicy()
    assert policy.verdict(None, high_interest=False, clock=lambda: T0) == "unknown"
    assert not policy.is_fresh(
        T0 + timedelta(seconds=1), high_interest=False, clock=lambda: T0
    )
    assert (
        derived_freshness(
            [T0, T0 + timedelta(seconds=1)],
            expected_count=2,
            high_interest=False,
            clock=lambda: T0,
        ).status
        == "unknown"
    )
    assert (
        derived_freshness(
            [T0], expected_count=2, high_interest=False, clock=lambda: T0
        ).status
        == "fresh"
    )  # partial coverage, fresh contributors
    assert (
        policy.verdict(T0, high_interest=False, historical=True, clock=lambda: T0)
        == "historical"
    )
    with pytest.raises(ValueError):
        FreshnessPolicy(headroom=timedelta(0))
