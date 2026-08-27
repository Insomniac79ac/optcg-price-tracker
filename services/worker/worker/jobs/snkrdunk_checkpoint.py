"""Durable resume state for bounded SNKRDUNK discovery.

WHY THIS EXISTS. Discovery's first cut returned its cursor and anchor progress
to the caller and nothing wrote them anywhere. That survives a function call and
nothing else: a fresh process, a Railway restart, or a killed container all
began again from the same offsets. Resume state has to live in the database or
it is not resume state.

WHERE IT LIVES. `snkrdunk_discovery_runs.resume_state_json`, one nullable JSON
column added by migration 8c31a5f0d2b7. That table already records exactly one
row per discovery run, so "where this run got to" belongs on it.

WHY THE CHECKPOINT CARRIES SITEMAP DIGESTS
------------------------------------------
Progress is stored as POSITIONS - an anchor's ring radius, a sequential shard
offset - and a position only means something against the list it was measured
in. SNKRDUNK republishes its sitemap (the shards carry a `lastmod` date), so
between two runs a listing can be inserted, delisted, or moved.

Demonstrated on 2026-08-27 against the pre-fix implementation, shard
[100,200,300,400,500,600,700] with anchor 400 consumed to radius 2:

    insert 350 before the anchor -> listing 350 was NEVER fetched by either run
    delete 300 before the anchor -> listing 100 was NEVER fetched by either run

A newly published listing silently skipped is exactly the failure this project
cannot accept: it would sit unpriced forever with nothing to indicate why.

THE FIX, and it is deliberately blunt. Each shard's URL list is digested, and
the digests are stored beside the progress. On the next run the digests are
recomputed; any shard whose content changed at all has the progress that
depended on it discarded, so that region is walked again from the start.

Replaying URLs is cheap and idempotent - candidates upsert on `source_url` -
whereas skipping one is silent and permanent. So the trade is made entirely in
favour of replay, and no attempt is made to work out *which* offsets a change
did or did not disturb. That cleverness is where the bugs would live.

WHAT IT DELIBERATELY DOES NOT HOLD. No HTML, no listing bodies, no secrets, no
array of URLs or offsets. One radius plus one shard index per anchor, one
SHA-256 digest per shard, and a two-integer sequential cursor: roughly 900
bytes for the six anchors and nine shards in use, and it does not grow with the
number of URLs inspected.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from worker.models import SnkrdunkDiscoveryRun

# Bump only alongside a reader that understands the new shape. Version 1 -
# which had no shard digests - is deliberately NOT readable here: without
# digests there is no way to tell whether its positions are still valid, and
# assuming they are is the bug this version exists to fix.
CHECKPOINT_VERSION = 2

# The FULL SHA-256, not a prefix. Resume safety rests entirely on noticing that
# a shard moved: a collision here would preserve positional progress against a
# list that had actually changed, and the consequence is a newly published
# listing skipped silently and permanently. There are nine shards, so the whole
# digest costs a few hundred bytes - nothing worth trading a correctness path
# for.


class CheckpointVersionError(Exception):
    """A persisted checkpoint this build cannot read.

    Raised rather than swallowed. Treating it as "no progress" would silently
    refetch the whole corpus; falling back to an OLDER checkpoint would be
    worse still, since the newest row is the one that describes reality.
    """


def shard_digest(urls: list[str]) -> str:
    """Content identity of one sitemap shard.

    Order-sensitive and length-sensitive, so an insertion, a deletion and a
    reordering all change it. Computed from the URL list already in memory -
    no extra request, and nothing is stored but the digest itself: never the
    URLs it was computed from.
    """
    hasher = hashlib.sha256()
    for url in urls:
        hasher.update(url.encode("utf-8"))
        # The separator is what makes the digest length-sensitive as well as
        # content-sensitive: without it, ["ab","c"] and ["a","bc"] would hash
        # identically.
        hasher.update(b"\n")
    return hasher.hexdigest()


@dataclass(frozen=True)
class AnchorProgress:
    """How far one anchor has been walked, and where it was when measured.

    `shard` is stored because an anchor can move between shards; a radius
    measured in shard 0 means nothing once the listing is published in shard 1.
    """

    radius: int
    shard: int


@dataclass
class DiscoveryCheckpoint:
    """Compact, versioned, provenance-carrying resume state."""

    anchor_progress: dict[int, AnchorProgress] = field(default_factory=dict)
    shard_digests: dict[int, str] = field(default_factory=dict)
    sequential_shard_index: int = 0
    sequential_url_offset: int = 0

    def radii(self) -> dict[int, int]:
        """Just the radii, as `plan_rings` wants them."""
        return {aid: p.radius for aid, p in self.anchor_progress.items()}

    def as_dict(self) -> dict:
        return {
            "version": CHECKPOINT_VERSION,
            # JSON has no integer keys; parsed back to ints on load.
            "anchor_progress": {
                str(aid): [p.radius, p.shard]
                for aid, p in sorted(self.anchor_progress.items())
            },
            "shard_digests": {str(k): v for k, v in sorted(self.shard_digests.items())},
            "sequential": {
                "shard_index": self.sequential_shard_index,
                "url_offset": self.sequential_url_offset,
            },
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "DiscoveryCheckpoint":
        if not data:
            return cls()
        version = data.get("version")
        if version != CHECKPOINT_VERSION:
            raise CheckpointVersionError(
                f"unreadable discovery checkpoint version {version!r} "
                f"(this build reads {CHECKPOINT_VERSION}); refusing to guess"
            )
        try:
            progress = {
                int(aid): AnchorProgress(radius=int(v[0]), shard=int(v[1]))
                for aid, v in (data.get("anchor_progress") or {}).items()
            }
            digests = {int(k): str(v) for k, v in (data.get("shard_digests") or {}).items()}
            seq = data.get("sequential") or {}
            return cls(
                anchor_progress=progress,
                shard_digests=digests,
                sequential_shard_index=int(seq.get("shard_index", 0)),
                sequential_url_offset=int(seq.get("url_offset", 0)),
            )
        except (TypeError, ValueError, IndexError, KeyError, AttributeError) as exc:
            raise CheckpointVersionError(f"malformed discovery checkpoint: {exc}") from exc


@dataclass
class Reconciliation:
    """What the sitemap's current state did to the stored progress."""

    checkpoint: DiscoveryCheckpoint
    invalidated_anchors: list[int] = field(default_factory=list)
    changed_shards: list[int] = field(default_factory=list)
    sequential_reset: bool = False

    @property
    def anything_invalidated(self) -> bool:
        return bool(self.invalidated_anchors or self.sequential_reset)


def reconcile_with_sitemap(
    checkpoint: DiscoveryCheckpoint,
    anchors,
    shard_listing_urls: dict[int, list[str]],
) -> Reconciliation:
    """Drop any progress whose shard has changed since it was recorded.

    Returns a checkpoint safe to plan against, plus what was discarded. A
    dropped anchor simply starts from ring 0 again: URLs it already saw are
    replayed (idempotent) and any newly published neighbour is now reachable.
    """
    current = {index: shard_digest(urls) for index, urls in shard_listing_urls.items()}
    changed = [i for i, d in current.items() if checkpoint.shard_digests.get(i) != d]

    kept: dict[int, AnchorProgress] = {}
    invalidated: list[int] = []
    by_id = {a.listing_id: a for a in anchors}
    for anchor_id, progress in checkpoint.anchor_progress.items():
        anchor = by_id.get(anchor_id)
        if anchor is None:
            # Not located this run - keep the record untouched rather than
            # discarding progress for an anchor that may simply be absent from
            # the batch. It is re-validated the next time it is located.
            kept[anchor_id] = progress
            continue
        if anchor.shard_index != progress.shard or anchor.shard_index in changed:
            invalidated.append(anchor_id)
            continue
        kept[anchor_id] = progress

    sequential_offset = checkpoint.sequential_url_offset
    sequential_reset = False
    if checkpoint.sequential_shard_index in changed and sequential_offset != 0:
        # The offset counts into a list that no longer exists. Restart this
        # shard rather than trust a position measured against different content.
        sequential_offset = 0
        sequential_reset = True

    return Reconciliation(
        checkpoint=DiscoveryCheckpoint(
            anchor_progress=kept,
            shard_digests=current,
            sequential_shard_index=checkpoint.sequential_shard_index,
            sequential_url_offset=sequential_offset,
        ),
        invalidated_anchors=sorted(invalidated),
        changed_shards=sorted(changed),
        sequential_reset=sequential_reset,
    )


def load_latest_checkpoint(db: Session) -> DiscoveryCheckpoint:
    """The newest applicable checkpoint - or an explicit failure.

    THE RULE, stated once so it cannot drift:

        1. select the newest run row (started_at desc, id desc) whose
           resume_state_json is non-NULL - whatever its status;
        2. parse and validate it;
        3. valid   -> use it;
        4. corrupt or unknown version -> raise.

    Step 1 is not "the newest COMPLETED run": a process killed mid-run leaves
    its best checkpoint on a row still marked `running`, holding strictly more
    progress than the last completed one.

    Step 4 never falls back to an older row. An older checkpoint is stale by
    definition - the newest one describes work that actually happened - so
    quietly resuming from it would redo real work while looking healthy.

    Rows with NULL state are skipped, not treated as empty progress, which is
    what keeps rows written before the migration harmless.
    """
    row = db.scalars(
        select(SnkrdunkDiscoveryRun)
        .where(SnkrdunkDiscoveryRun.resume_state_json.is_not(None))
        .order_by(
            SnkrdunkDiscoveryRun.started_at.desc(),
            SnkrdunkDiscoveryRun.id.desc(),
        )
        .limit(1)
    ).first()
    if row is None:
        return DiscoveryCheckpoint()
    return DiscoveryCheckpoint.from_dict(row.resume_state_json)


def save_checkpoint(
    db: Session, run: SnkrdunkDiscoveryRun, checkpoint: DiscoveryCheckpoint
) -> None:
    """Write the checkpoint onto this run.

    Assignment is whole-object, never an in-place mutation of the loaded dict:
    SQLAlchemy tracks a plain JSON column by identity, so mutating it emits no
    UPDATE at all and the checkpoint would silently never persist.

    The caller commits. Candidates for the work this checkpoint describes must
    already be in the same transaction, so committing makes both durable
    together - a checkpoint can never become durable ahead of its candidates.
    """
    run.resume_state_json = checkpoint.as_dict()
