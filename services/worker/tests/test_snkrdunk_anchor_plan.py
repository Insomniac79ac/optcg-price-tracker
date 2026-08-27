"""The anchor plan decides WHERE to look.

Its safety properties: only URLs the publisher listed, whole rings so progress
is describable by one integer per anchor, no refetching, and no anchor starving
the others.
"""

from worker.adapters.snkrdunk_anchor_plan import (
    NOTHING_CONSUMED,
    AnchorPosition,
    listing_id,
    locate_anchors,
    plan_rings,
    ring_offsets,
)


def urls(shard: str, n: int) -> list[str]:
    return [f"https://snkrdunk.com/en/trading-cards/{shard}{i:04d}" for i in range(n)]


SHARDS = {0: urls("1", 200), 1: urls("2", 200)}


def test_listing_id_reads_the_published_url_only():
    assert listing_id("https://snkrdunk.com/en/trading-cards/93522") == 93522
    assert listing_id("https://snkrdunk.com/en/trading-cards/93522?slide=right") == 93522
    assert listing_id("https://snkrdunk.com/en/trading-cards/93522/") == 93522
    assert listing_id("https://snkrdunk.com/en/brands/nike") is None
    assert listing_id("") is None
    assert listing_id(None) is None


def test_anchors_are_located_by_position_in_the_sitemap():
    anchors = locate_anchors([SHARDS[0][50], SHARDS[1][10]], SHARDS)
    assert anchors == [
        AnchorPosition(listing_id(SHARDS[0][50]), 0, 50),
        AnchorPosition(listing_id(SHARDS[1][10]), 1, 10),
    ]


def test_an_anchor_absent_from_the_sitemap_is_simply_not_located():
    assert locate_anchors(["https://snkrdunk.com/en/trading-cards/99999999"], SHARDS) == []


# --- rings -------------------------------------------------------------------


def test_ring_zero_is_the_anchor_itself_and_later_rings_are_pairs():
    a = AnchorPosition(1, 0, 50)
    assert ring_offsets(a, 0, 200) == [50]
    assert ring_offsets(a, 1, 200) == [49, 51]
    assert ring_offsets(a, 5, 200) == [45, 55]


def test_a_ring_at_a_shard_edge_yields_only_the_in_bounds_side():
    a = AnchorPosition(1, 0, 1)
    assert ring_offsets(a, 2, 200) == [3]        # offset -1 is out of bounds
    assert ring_offsets(a, 500, 200) == []       # both sides out of bounds


# --- planning ----------------------------------------------------------------


def test_every_planned_url_comes_from_the_sitemap():
    anchors = locate_anchors([SHARDS[0][50]], SHARDS)
    rings = plan_rings(anchors, SHARDS, {}, max_urls=20)
    planned = [u for r in rings for u in r.urls]
    assert planned
    assert set(planned).issubset(set(SHARDS[0]) | set(SHARDS[1]))


def test_the_batch_never_exceeds_max_urls_and_stops_on_a_ring_boundary():
    anchors = locate_anchors([SHARDS[0][50]], SHARDS)
    rings = plan_rings(anchors, SHARDS, {}, max_urls=5)
    total = sum(len(r.urls) for r in rings)
    assert total <= 5
    # Whole rings only: 1 + 2 + 2 = 5.
    assert [len(r.urls) for r in rings] == [1, 2, 2]


def test_planning_starts_at_the_anchor_and_moves_outward():
    anchors = locate_anchors([SHARDS[0][50]], SHARDS)
    rings = plan_rings(anchors, SHARDS, {}, max_urls=5)
    assert [r.radius for r in rings] == [0, 1, 2]
    assert rings[0].urls == (SHARDS[0][50],)


def test_progress_makes_the_next_batch_continue_rather_than_repeat():
    anchors = locate_anchors([SHARDS[0][50]], SHARDS)
    first = plan_rings(anchors, SHARDS, {}, max_urls=5)
    progress = {r.anchor_listing_id: r.radius for r in first}
    second = plan_rings(anchors, SHARDS, progress, max_urls=5)
    assert [r.radius for r in second] == [3, 4]
    first_urls = {u for r in first for u in r.urls}
    second_urls = {u for r in second for u in r.urls}
    assert first_urls.isdisjoint(second_urls)


def test_several_anchors_are_served_round_robin():
    """One dense region must not starve the others."""
    anchors = locate_anchors([SHARDS[0][50], SHARDS[1][10]], SHARDS)
    rings = plan_rings(anchors, SHARDS, {}, max_urls=6)
    served = {r.anchor_listing_id for r in rings}
    assert len(served) == 2


def test_an_anchor_at_the_shard_start_keeps_expanding_the_other_way():
    """A ring with one side out of bounds is still useful; the anchor must not
    be abandoned just because it sits near an edge."""
    anchors = locate_anchors([SHARDS[0][0]], SHARDS)
    rings = plan_rings(anchors, SHARDS, {}, max_urls=6)
    planned = [u for r in rings for u in r.urls]
    assert len(planned) == 6
    assert all(u in SHARDS[0] for u in planned)


def test_an_exhausted_anchor_stops_producing_rings():
    tiny = {0: urls("1", 3)}
    anchors = locate_anchors([tiny[0][1]], tiny)
    rings = plan_rings(anchors, tiny, {}, max_urls=50)
    planned = [u for r in rings for u in r.urls]
    assert sorted(planned) == sorted(tiny[0]), "the whole tiny shard, once"


def test_no_anchors_means_no_rings():
    assert plan_rings([], SHARDS, {}, max_urls=10) == []


def test_nothing_consumed_sentinel_means_ring_zero_is_next():
    anchors = locate_anchors([SHARDS[0][50]], SHARDS)
    rings = plan_rings(anchors, SHARDS, {anchors[0].listing_id: NOTHING_CONSUMED}, max_urls=1)
    assert rings[0].radius == 0
