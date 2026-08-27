"""What happens when SNKRDUNK republishes its sitemap between two runs.

THE INVARIANT UNDER TEST, and the only one that matters here:

    a persisted checkpoint must never cause a newly published listing to be
    silently skipped because old positions were reused against a changed list.

Replaying URLs is acceptable and cheap - candidates upsert on `source_url`.
Skipping one is silent and permanent, so every ambiguous case resolves towards
replay.

The pre-fix implementation failed this. Measured 2026-08-27 on shard
[100,200,300,400,500,600,700], anchor 400 consumed to radius 2: inserting 350
before the anchor left 350 fetched by neither run, and deleting 300 left 100
fetched by neither. Those two cases are the first tests below.
"""

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from worker.adapters.snkrdunk_anchor_plan import locate_anchors
from worker.adapters.snkrdunk_sitemap import CrawlBounds, SnkrdunkSitemapSource
from worker.jobs.discover_snkrdunk_sitemap import run_anchor_discovery
from worker.jobs.snkrdunk_checkpoint import (
    AnchorProgress,
    DiscoveryCheckpoint,
    load_latest_checkpoint,
    reconcile_with_sitemap,
    shard_digest,
)
from worker.models import Base, SnkrdunkCandidate, SnkrdunkDiscoveryRun

INDEX = "https://snkrdunk.com/en/sitemap/sitemap-index-en-product-trading-card-single.xml"
SHARDS = ["https://snkrdunk.com/en/sitemap/shard-0.xml",
          "https://snkrdunk.com/en/sitemap/shard-1.xml"]

BASE_IDS = list(range(9000, 9080, 2))   # gaps, so an insertion can land mid-window
ANCHOR_ID = 9020


def url(n: int) -> str:
    return f"https://snkrdunk.com/en/trading-cards/{n}"


def open_session(db_path):
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def make_source(shard0_ids, shard1_ids=(), fetched=None, max_urls=7):
    def handler(request: httpx.Request) -> httpx.Response:
        u = str(request.url)
        if u == INDEX:
            body = "".join(f"<sitemap><loc>{s}</loc></sitemap>" for s in SHARDS)
            return httpx.Response(200, text=f"<sitemapindex>{body}</sitemapindex>")
        if u in SHARDS:
            ids = shard0_ids if u == SHARDS[0] else shard1_ids
            body = "".join(f"<url><loc>{url(n)}</loc></url>" for n in ids)
            return httpx.Response(200, text=f"<urlset>{body}</urlset>")
        if fetched is not None:
            fetched.append(u)
        n = int(u.rsplit("/", 1)[-1])
        title = f"Card {n} L [OP01-{n % 1000:03d}] (Booster Pack ROMANCE DAWN)"
        return httpx.Response(200, text=f"<html><head><title>{title} | SNKRDUNK</title></head></html>")

    return SnkrdunkSitemapSource(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        bounds=CrawlBounds(max_urls_inspected=max_urls, max_candidates=99, request_delay_ms=0),
        sleep_fn=lambda _s: None,
        monotonic_fn=lambda: 0.0,
    )


def new_run(db) -> SnkrdunkDiscoveryRun:
    run = SnkrdunkDiscoveryRun(seed_url=INDEX, status="running")
    db.add(run)
    db.commit()
    return run


def two_runs(db_path, before_ids, after_ids, max_urls=7):
    """Run A over `before_ids`, then run B over `after_ids`, sharing the db.

    Returns (fetched_a, fetched_b, summary_b).
    """
    a: list[str] = []
    db1 = open_session(db_path)
    run_anchor_discovery(db1, [url(ANCHOR_ID)],
                         source=make_source(before_ids, fetched=a, max_urls=max_urls),
                         run=new_run(db1))
    db1.close()

    b: list[str] = []
    db2 = open_session(db_path)
    summary, _ = run_anchor_discovery(
        db2, [url(ANCHOR_ID)],
        source=make_source(after_ids, fetched=b, max_urls=max_urls),
        run=new_run(db2))
    db2.close()
    return a, b, summary


def never_fetched(after_ids, a, b):
    seen = set(a) | set(b)
    return [n for n in after_ids if url(n) not in seen]


# --- the two cases that failed before the fix --------------------------------


def test_a_listing_inserted_before_the_anchor_is_not_skipped(tmp_path):
    """The exact case that failed before the fix: a listing published INSIDE a
    window an old radius claimed was already walked."""
    new_id = ANCHOR_ID - 1               # sorts immediately before the anchor
    after = sorted(BASE_IDS + [new_id])
    assert new_id not in BASE_IDS, "test setup: the id must be genuinely new"
    a, b, summary = two_runs(tmp_path / "d.sqlite", BASE_IDS, after, max_urls=11)
    assert url(new_id) in set(a) | set(b), "a newly published listing was SKIPPED"
    assert summary.changed_shards, "the shard change should have been detected"
    assert ANCHOR_ID in summary.invalidated_anchors


def test_a_listing_removed_before_the_anchor_does_not_strand_its_neighbours(tmp_path):
    after = [n for n in BASE_IDS if n != ANCHOR_ID - 10]
    a, b, _ = two_runs(tmp_path / "d.sqlite", BASE_IDS, after, max_urls=99)
    assert never_fetched(after, a, b) == [], "delisting stranded a still-published listing"


def test_a_reordered_shard_strands_nothing(tmp_path):
    after = list(reversed(BASE_IDS))
    a, b, _ = two_runs(tmp_path / "d.sqlite", BASE_IDS, after, max_urls=99)
    assert never_fetched(after, a, b) == []


def test_an_unchanged_sitemap_does_not_trigger_a_replay(tmp_path):
    """The safety mechanism must not fire on an ordinary run - otherwise every
    run would restart and no progress would ever be made."""
    a, b, summary = two_runs(tmp_path / "d.sqlite", BASE_IDS, BASE_IDS, max_urls=7)
    assert summary.changed_shards == []
    assert summary.invalidated_anchors == []
    assert set(a).isdisjoint(b), "unchanged sitemap must not refetch"


# --- reconciliation unit behaviour -------------------------------------------


def _anchors(shard0, shard1=()):
    listings = {0: [url(n) for n in shard0], 1: [url(n) for n in shard1]}
    return locate_anchors([url(ANCHOR_ID)], listings), listings


def test_progress_is_discarded_when_its_shard_changes():
    anchors, listings = _anchors(BASE_IDS)
    stale = DiscoveryCheckpoint(
        anchor_progress={ANCHOR_ID: AnchorProgress(5, 0)},
        shard_digests={0: "0" * 64, 1: shard_digest([])},
    )
    result = reconcile_with_sitemap(stale, anchors, listings)
    assert result.invalidated_anchors == [ANCHOR_ID]
    assert result.checkpoint.radii() == {}
    assert 0 in result.changed_shards


def test_progress_is_kept_when_the_shard_is_byte_identical():
    anchors, listings = _anchors(BASE_IDS)
    good = DiscoveryCheckpoint(
        anchor_progress={ANCHOR_ID: AnchorProgress(5, 0)},
        shard_digests={i: shard_digest(u) for i, u in listings.items()},
    )
    result = reconcile_with_sitemap(good, anchors, listings)
    assert result.invalidated_anchors == []
    assert result.checkpoint.radii() == {ANCHOR_ID: 5}


def test_an_anchor_that_moved_shard_has_its_progress_discarded():
    """A radius measured in shard 0 means nothing once the listing is published
    in shard 1, even if that shard's own digest happened to match."""
    anchors, listings = _anchors([n for n in BASE_IDS if n != ANCHOR_ID], [ANCHOR_ID])
    stale = DiscoveryCheckpoint(
        anchor_progress={ANCHOR_ID: AnchorProgress(5, 0)},   # recorded in shard 0
        shard_digests={i: shard_digest(u) for i, u in listings.items()},
    )
    result = reconcile_with_sitemap(stale, anchors, listings)
    assert result.invalidated_anchors == [ANCHOR_ID]


def test_the_sequential_cursor_restarts_a_shard_whose_contents_changed():
    _, listings = _anchors(BASE_IDS)
    stale = DiscoveryCheckpoint(
        shard_digests={0: "0" * 64},
        sequential_shard_index=0,
        sequential_url_offset=25,
    )
    result = reconcile_with_sitemap(stale, [], listings)
    assert result.sequential_reset is True
    assert result.checkpoint.sequential_url_offset == 0


def test_the_sequential_cursor_is_left_alone_when_its_shard_is_unchanged():
    _, listings = _anchors(BASE_IDS)
    good = DiscoveryCheckpoint(
        shard_digests={i: shard_digest(u) for i, u in listings.items()},
        sequential_shard_index=0,
        sequential_url_offset=25,
    )
    result = reconcile_with_sitemap(good, [], listings)
    assert result.sequential_reset is False
    assert result.checkpoint.sequential_url_offset == 25


def test_an_anchor_not_located_this_run_keeps_its_record():
    """Absent from this batch is not the same as invalidated - it is
    re-validated the next time it is actually located."""
    _, listings = _anchors(BASE_IDS)
    keep = DiscoveryCheckpoint(
        anchor_progress={555555: AnchorProgress(9, 0)},
        shard_digests={i: shard_digest(u) for i, u in listings.items()},
    )
    result = reconcile_with_sitemap(keep, [], listings)
    assert result.checkpoint.radii() == {555555: 9}


# --- the digest itself --------------------------------------------------------


def test_the_digest_detects_insertion_deletion_and_reordering():
    base = [url(n) for n in BASE_IDS]
    assert shard_digest(base) == shard_digest(list(base))
    assert shard_digest(base) != shard_digest(base + [url(1)])
    assert shard_digest(base) != shard_digest(base[:-1])
    assert shard_digest(base) != shard_digest(list(reversed(base)))
    assert shard_digest([]) == shard_digest([])


def test_the_digest_is_a_full_sha256():
    """Not a prefix: a collision here would preserve positional progress
    against a shard that had actually changed, and skip a new listing."""
    import hashlib

    assert len(shard_digest([url(n) for n in BASE_IDS])) == 64
    assert len(shard_digest([])) == 64
    assert shard_digest([]) == hashlib.sha256(b"").hexdigest()
    one = url(9000)
    assert shard_digest([one]) == hashlib.sha256((one + "\n").encode()).hexdigest()


def test_the_digest_is_length_sensitive_not_just_content_sensitive():
    """The newline separator is what stops ['ab','c'] and ['a','bc'] colliding."""
    assert shard_digest(["ab", "c"]) != shard_digest(["a", "bc"])


def test_the_checkpoint_stays_small_with_a_full_shard_set(tmp_path):
    """Nine shards and six anchors - the real deployment shape."""
    import json

    checkpoint = DiscoveryCheckpoint(
        anchor_progress={93522 + i: AnchorProgress(120, i % 9) for i in range(6)},
        shard_digests={i: shard_digest([url(x) for x in range(i, i + 50)]) for i in range(9)},
        sequential_shard_index=3,
        sequential_url_offset=987654,
    )
    payload = json.dumps(checkpoint.as_dict())
    assert len(payload) < 1200, f"payload grew to {len(payload)} bytes"
    assert "http" not in payload and "<html" not in payload
