"""Owner plan A (2026-10-28): with one membership on every day, the frozen-membership
builder reproduces the legacy single-digest builder exactly, field for field. This is
what lets every day published before the ledger verify against its rebuilt membership."""

from app.services import market_value_membership as membership
from app.services.market_value_replay import (
    FrozenReplayInput,
    build_frozen_point_drafts,
    build_market_value_point_drafts,
    load_market_value_replay_input,
)
from tests._market_value_ranking_helpers import AS_OF, seed_rankings
from tests.test_market_value_persistence import replay_fixture


def _single_membership(loaded):
    frozen = membership.FrozenMembership(
        loaded.catalogue_membership_revision,
        loaded.active_prints,
        tuple(
            membership.CodedRelease(row.release_product_id, row.official_code)
            for row in loaded.coded_releases
        ),
    )
    days = tuple(day for day in loaded.archive_dates if loaded.observations_by_date[day])
    return FrozenReplayInput(
        archive_dates=days,
        observations_by_date={day: loaded.observations_by_date[day] for day in days},
        memberships={day: frozen for day in days},
    )


def test_synthetic_replay_fixture_is_reproduced_exactly():
    for release_id in (None, 7):
        loaded = replay_fixture() if release_id is None else replay_fixture(release_product_id=release_id)
        legacy = build_market_value_point_drafts(loaded)
        assert legacy and build_frozen_point_drafts(_single_membership(loaded)) == legacy


def test_multi_release_catalogue_is_reproduced_exactly(db_session):
    seed_rankings(db_session)
    loaded = load_market_value_replay_input(db_session, through=AS_OF, include_current=False)
    legacy = build_market_value_point_drafts(loaded)
    assert len({row.release_product_id for row in legacy}) > 2
    assert build_frozen_point_drafts(_single_membership(loaded)) == legacy
