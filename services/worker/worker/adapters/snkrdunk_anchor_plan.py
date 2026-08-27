"""Where to look for One Piece listings, given that the sitemap will not say.

MEASURED ON 2026-08-27, and this module exists because of these numbers:

    cold start, shard 0 offset 0, 60 URLs ............  0 One Piece   (0%)
    stratified, 18 windows across all 9 shards, 108 ..  6 One Piece   (5.6%)
    windows around already-mapped listings, 36 ....... 23 One Piece   (64%)

The published sitemap indexes ~270,000 trading-card listings across every card
game, in an order that carries no category. A fresh sequential sweep therefore
finds nothing: the cold-start run inspected sixty pages, spent 105 seconds and
produced zero candidates. Reaching the first known One Piece listing that way
would take ~2,160 requests, and that is only because we already know where it
is.

What the same audit showed is that One Piece listings are CLUSTERED. Every
listing this project has ever mapped sits in shard 0 between offsets 2,160 and
27,898, and windows around them ran at 64% One Piece. So discovery starts from
what is already known and grows outward.

This is not id probing: an anchor is a listing URL Atlas already holds a
mapping for, its POSITION is read out of the publisher's own sitemap, and every
URL fetched is one the publisher lists. No id is ever constructed or guessed.

WHY PROGRESS IS A RING RADIUS AND NOT A SET OF OFFSETS. The first cut recorded
every consumed (shard, offset) pair. That is correct but unbounded - the set
grows by one entry per URL forever, and it has to be written into a database
row after every checkpoint. Instead, each anchor expands as concentric RINGS:
ring `d` is the two offsets exactly `d` either side of the anchor (ring 0 is
the anchor itself). A ring is at most two URLs, so a batch can always stop on a
ring boundary, and the whole of an anchor's progress is then a single integer -
the highest radius fully consumed.

Six anchors cost six integers. That is the entire persisted state, and it does
not grow with the number of URLs inspected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ID_RE = re.compile(r"/(\d+)(?:[/?#].*)?$")

# Nothing consumed yet: ring 0 has not been taken. Chosen over 0 so that
# "consumed ring 0" and "consumed nothing" are distinguishable integers.
NOTHING_CONSUMED = -1


def listing_id(url: str) -> int | None:
    """The numeric id at the end of a listing URL, or None.

    Used only to LOOK UP a URL's position in the published sitemap - never to
    build a URL.
    """
    if not url:
        return None
    match = _ID_RE.search(url.split("?", 1)[0].rstrip("/"))
    return int(match.group(1)) if match else None


@dataclass(frozen=True)
class AnchorPosition:
    """Where an already-known listing sits in the publisher's ordering."""

    listing_id: int
    shard_index: int
    offset: int


@dataclass(frozen=True)
class PlannedRing:
    """One ring of one anchor: at most two URLs, always taken as a unit.

    The unit matters. A batch that stopped halfway through a ring could not be
    described by a single radius, which is what keeps the persisted state one
    integer per anchor.
    """

    anchor_listing_id: int
    radius: int
    urls: tuple[str, ...]


def ring_offsets(anchor: AnchorPosition, radius: int, shard_length: int) -> list[int]:
    """The in-bounds offsets at exactly `radius` from the anchor.

    One offset at radius 0, two thereafter, fewer near a shard edge. Sorted so
    a ring is deterministic run to run.
    """
    if radius == 0:
        return [anchor.offset] if 0 <= anchor.offset < shard_length else []
    candidates = (anchor.offset - radius, anchor.offset + radius)
    return sorted(o for o in candidates if 0 <= o < shard_length)


def locate_anchors(
    anchor_urls: list[str], shard_listing_urls: dict[int, list[str]]
) -> list[AnchorPosition]:
    """Find each anchor's position in the published sitemap.

    `shard_listing_urls` is what the sitemap itself returned, so an anchor that
    is no longer published simply does not appear in the result - it is not
    invented, and it is not probed for. Costs no listing fetches: the shard URL
    lists are already in hand.
    """
    wanted = set()
    for url in anchor_urls:
        lid = listing_id(url)
        if lid is not None:
            wanted.add(lid)

    found: list[AnchorPosition] = []
    for shard_index, urls in shard_listing_urls.items():
        for offset, url in enumerate(urls):
            lid = listing_id(url)
            if lid in wanted:
                found.append(AnchorPosition(lid, shard_index, offset))
    return sorted(found, key=lambda a: (a.shard_index, a.offset))


def plan_rings(
    anchors: list[AnchorPosition],
    shard_listing_urls: dict[int, list[str]],
    progress: dict[int, int],
    max_urls: int,
) -> list[PlannedRing]:
    """The next batch of whole rings to inspect, under `max_urls`.

    Round-robins across anchors so one dense region cannot starve the others -
    the failure mode a single sequential cursor has. A ring is only included if
    it fits entirely, so the caller can always record progress as an exact
    radius.

    Rings that fall entirely outside their shard (both offsets out of bounds)
    are skipped rather than ending that anchor, so an anchor near a shard edge
    keeps expanding in the direction that still has room.
    """
    planned: list[PlannedRing] = []
    budget = max_urls
    # Working copy: the radius each anchor has been planned up to in THIS batch.
    heads = {a.listing_id: progress.get(a.listing_id, NOTHING_CONSUMED) for a in anchors}
    exhausted: set[int] = set()

    while budget > 0 and len(exhausted) < len(anchors):
        progressed = False
        for anchor in anchors:
            if budget <= 0:
                break
            if anchor.listing_id in exhausted:
                continue
            shard = shard_listing_urls.get(anchor.shard_index) or []
            radius = heads[anchor.listing_id] + 1
            # Skip past rings that are entirely out of bounds; stop when no
            # larger radius could ever be in bounds again.
            max_useful = max(anchor.offset, len(shard) - 1 - anchor.offset)
            while radius <= max_useful and not ring_offsets(anchor, radius, len(shard)):
                radius += 1
            if radius > max_useful:
                exhausted.add(anchor.listing_id)
                continue
            offsets = ring_offsets(anchor, radius, len(shard))
            if len(offsets) > budget:
                # Cannot take this ring whole; leave it for the next run.
                exhausted.add(anchor.listing_id)
                continue
            planned.append(
                PlannedRing(
                    anchor_listing_id=anchor.listing_id,
                    radius=radius,
                    urls=tuple(shard[o] for o in offsets),
                )
            )
            heads[anchor.listing_id] = radius
            budget -= len(offsets)
            progressed = True
        if not progressed:
            break

    return planned
