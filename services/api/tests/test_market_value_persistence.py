from datetime import date, datetime, timezone
from decimal import Decimal

from app.services.backup import BACKUP_REGISTRY, BACKUP_VERSION, export_backup
from app.services.market_value import MarketValueObservation
from app.services.market_value_replay import (
    ActiveCodedRelease,
    ActivePrintIdentity,
    MarketValueReplayInput,
    build_market_value_point_drafts,
)


D1, D2, D3 = (date(2026, 9, day) for day in (24, 25, 26))
AS_OF = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


def replay_fixture(
    *,
    reverse_rows: bool = False,
    release_product_id: int = 7,
    contributor_churn_on_last: bool = False,
) -> MarketValueReplayInput:
    active = tuple(
        ActivePrintIdentity(
            card_print_id=print_id, release_product_id=release_product_id
        )
        for print_id in range(1, 301)
    )
    by_date = {}
    for point_date, value in ((D1, 100), (D2, 110), (D3, 121)):
        rows = tuple(
            MarketValueObservation(
                card_print_id=print_id,
                value_jpy=value,
                index_version=3,
                source_semantics_version=2,
                contributors=(
                    frozenset({("snkrdunk", "floor")})
                    if contributor_churn_on_last and point_date == D3
                    else frozenset({("yuyutei", "sell")})
                ),
                release_product_id=release_product_id,
            )
            for print_id in range(1, 301)
        )
        by_date[point_date] = tuple(reversed(rows)) if reverse_rows else rows
    return MarketValueReplayInput(
        catalogue_membership_revision="current-corrected-card-print-release-v1:test",
        archive_dates=(D3, D1, D2) if reverse_rows else (D1, D2, D3),
        observations_by_date=by_date,
        active_prints=active,
        coded_releases=(
            ActiveCodedRelease(
                release_product_id=release_product_id,
                official_code="OP-XX",
                active_physical_print_count=300,
            ),
        ),
        current_observations=by_date[D3],
        current_as_of=AS_OF,
    )


def test_drafts_are_deterministic_and_keep_sum_separate_from_chain():
    expected = build_market_value_point_drafts(replay_fixture())
    reordered = build_market_value_point_drafts(replay_fixture(reverse_rows=True))

    assert reordered == expected
    assert len(expected) == 6
    overall = [row for row in expected if row.scope_kind == "overall"]
    assert [row.point_date for row in overall] == [D1, D2, D3]
    assert [row.tracked_value_jpy for row in overall] == [30000, 33000, 36300]
    assert [row.performance_factor for row in overall] == [
        Decimal("1"),
        Decimal("1.1"),
        Decimal("1.21"),
    ]
    assert overall[-1].tracked_value_jpy != overall[-1].performance_factor
    assert overall[-1].prior_comparable_value_jpy == 33000
    assert overall[-1].current_comparable_value_jpy == 36300
    assert overall[-1].step_ratio == Decimal("1.1")
    assert overall[-1].publication_reasons == "publishable"
    assert overall[-1].current_version_pairs == "3:2"


def test_unavailable_step_is_null_not_fake_movement():
    before = tuple(
        MarketValueObservation(
            card_print_id=print_id,
            value_jpy=100,
            index_version=3,
            source_semantics_version=2,
            contributors=frozenset({("yuyutei", "sell")}),
            release_product_id=7,
        )
        for print_id in range(1, 6)
    )
    after = tuple(
        MarketValueObservation(
            card_print_id=print_id,
            value_jpy=100,
            index_version=3,
            source_semantics_version=2,
            contributors=frozenset({("snkrdunk", "floor")}),
            release_product_id=7,
        )
        for print_id in range(1, 6)
    )
    loaded = MarketValueReplayInput(
        catalogue_membership_revision="current-corrected-card-print-release-v1:test",
        archive_dates=(D1, D2),
        observations_by_date={D1: before, D2: after},
        active_prints=tuple(
            ActivePrintIdentity(print_id, 7) for print_id in range(1, 6)
        ),
        coded_releases=(ActiveCodedRelease(7, "OP-X", 5),),
        current_observations=after,
        current_as_of=AS_OF,
    )

    points = build_market_value_point_drafts(loaded)
    for row in (point for point in points if point.point_date == D2):
        assert row.step_publication_eligible is False
        assert row.step_ratio is None
        assert row.performance_factor == Decimal("1")
        assert row.publication_reasons != "publishable"
        assert "non_positive_comparable_value" in row.publication_reasons


def test_application_backup_follows_cpi_historical_evidence_policy(db_session):
    registry = {spec.name: spec for spec in BACKUP_REGISTRY}
    assert BACKUP_VERSION == 18
    assert registry["market_value_points"].include_flag == "include_prices"

    without_prices = export_backup(db_session, include_prices=False)
    with_prices = export_backup(db_session, include_prices=True)
    assert "market_value_points" not in without_prices["tables"]
    assert with_prices["tables"]["market_value_points"] == []
