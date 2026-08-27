"""Resume durability: the property the 4F-2D gate failed on.

Every test here uses a real SQLite file rather than an in-memory database, and
several reopen it through a brand-new Session and engine. That is deliberate:
an in-memory database would let state survive purely because the objects were
still alive, which is exactly the illusion that made the first implementation
look resumable when it was not.
"""

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from worker.adapters.snkrdunk_sitemap import CrawlBounds, SnkrdunkSitemapSource
from worker.job_locks import LockHeldError, acquire_lock
from worker.jobs.discover_snkrdunk_sitemap import (
    DISCOVERY_LOCK,
    run_anchor_discovery,
    run_anchor_discovery_locked,
    run_discovery,
)
from worker.jobs.snkrdunk_checkpoint import (
    CHECKPOINT_VERSION,
    AnchorProgress,
    CheckpointVersionError,
    DiscoveryCheckpoint,
    load_latest_checkpoint,
    save_checkpoint,
)
from worker.models import Base, SnkrdunkCandidate, SnkrdunkDiscoveryRun

INDEX = "https://snkrdunk.com/en/sitemap/sitemap-index-en-product-trading-card-single.xml"
SHARD = "https://snkrdunk.com/en/sitemap/shard-0.xml"

# A small synthetic corpus: every listing is a One Piece card so the tests are
# about resumption, not about parsing (which has its own suite).
LISTINGS = [f"https://snkrdunk.com/en/trading-cards/{9000 + i}" for i in range(60)]
ANCHOR = LISTINGS[30]


def _title(url: str) -> str:
    n = int(url.rsplit("/", 1)[-1]) - 9000
    return f"Card {n} L [OP01-{n:03d}] (Booster Pack ROMANCE DAWN)"


@pytest.fixture()
def db_path(tmp_path):
    """A real on-disk database, so 'fresh process' can be simulated honestly."""
    return tmp_path / "discovery.sqlite"


def open_session(db_path):
    """A brand-new engine and Session - nothing shared with any prior caller."""
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def make_source(fetched: list[str] | None = None, fail_on: str | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == INDEX:
            return httpx.Response(200, text=f"<sitemapindex><sitemap><loc>{SHARD}</loc></sitemap></sitemapindex>")
        if url == SHARD:
            body = "".join(f"<url><loc>{u}</loc></url>" for u in LISTINGS)
            return httpx.Response(200, text=f"<urlset>{body}</urlset>")
        if fetched is not None:
            fetched.append(url)
        if fail_on is not None and url == fail_on:
            raise RuntimeError("simulated crash mid-ring")
        return httpx.Response(200, text=f"<html><head><title>{_title(url)} | SNKRDUNK</title></head></html>")

    return SnkrdunkSitemapSource(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        bounds=CrawlBounds(max_urls_inspected=5, max_candidates=50, request_delay_ms=0),
        sleep_fn=lambda _s: None,
        monotonic_fn=lambda: 0.0,
    )


def new_run(db, status="running") -> SnkrdunkDiscoveryRun:
    run = SnkrdunkDiscoveryRun(seed_url=INDEX, status=status)
    db.add(run)
    db.commit()
    return run


# --- A: normal exit, fresh process continues ---------------------------------


def test_a_fresh_process_continues_without_refetching(db_path):
    first_fetched: list[str] = []
    db1 = open_session(db_path)
    run1 = new_run(db1)
    run_anchor_discovery(db1, [ANCHOR], source=make_source(first_fetched), run=run1)
    db1.close()

    second_fetched: list[str] = []
    db2 = open_session(db_path)          # brand-new engine + session
    run2 = new_run(db2)
    run_anchor_discovery(db2, [ANCHOR], source=make_source(second_fetched), run=run2)

    assert first_fetched, "run 1 fetched nothing"
    assert second_fetched, "run 2 fetched nothing - it did not resume"
    assert set(first_fetched).isdisjoint(second_fetched), "run 2 refetched consumed URLs"
    assert db2.query(SnkrdunkCandidate).count() == len(first_fetched) + len(second_fetched)
    db2.close()


# --- B: interrupted run's checkpoint is still used ---------------------------


def test_a_checkpoint_on_an_interrupted_run_is_still_resumed_from(db_path):
    """The most useful checkpoint often sits on a row that never completed."""
    db1 = open_session(db_path)
    # An older COMPLETED run with less progress...
    completed = new_run(db1, status="completed")
    save_checkpoint(db1, completed, DiscoveryCheckpoint(anchor_progress={9030: AnchorProgress(0, 0)}))
    db1.commit()
    # ...and a newer run killed while still 'running', holding more.
    interrupted = new_run(db1, status="running")
    save_checkpoint(db1, interrupted, DiscoveryCheckpoint(anchor_progress={9030: AnchorProgress(7, 0)}))
    db1.commit()
    db1.close()

    db2 = open_session(db_path)
    loaded = load_latest_checkpoint(db2)
    assert loaded.radii() == {9030: 7}, "must not prefer the completed run"
    db2.close()


def test_a_failed_run_checkpoint_is_also_honoured(db_path):
    db = open_session(db_path)
    failed = new_run(db, status="failed")
    save_checkpoint(db, failed, DiscoveryCheckpoint(anchor_progress={9030: AnchorProgress(3, 0)}))
    db.commit()
    assert load_latest_checkpoint(db).radii() == {9030: 3}
    db.close()


# --- C: crash BEFORE the checkpoint commit -----------------------------------


def test_a_crash_before_commit_replays_the_ring_and_does_not_duplicate(db_path):
    """Rolled back together: the ring is replayed, never skipped, and the
    source_url upsert makes the replay idempotent."""
    db1 = open_session(db_path)
    run1 = new_run(db1)
    crashing = make_source(fail_on=LISTINGS[31])
    with pytest.raises(RuntimeError):
        run_anchor_discovery(db1, [ANCHOR], source=crashing, run=run1, commit_every_rings=99)
    db1.rollback()
    # Nothing durable: neither candidates nor a checkpoint.
    assert db1.query(SnkrdunkCandidate).count() == 0
    assert load_latest_checkpoint(db1).radii() == {}
    db1.close()

    replay: list[str] = []
    db2 = open_session(db_path)
    run2 = new_run(db2)
    run_anchor_discovery(db2, [ANCHOR], source=make_source(replay), run=run2)
    assert ANCHOR in replay, "the unpersisted ring must be replayed, not skipped"
    codes = [c.source_url for c in db2.query(SnkrdunkCandidate).all()]
    assert len(codes) == len(set(codes)), "replay must not duplicate candidates"
    db2.close()


def test_replaying_an_already_persisted_url_updates_rather_than_duplicates(db_path):
    db = open_session(db_path)
    run = new_run(db)
    run_anchor_discovery(db, [ANCHOR], source=make_source(), run=run)
    before = db.query(SnkrdunkCandidate).count()
    # Force a replay by resetting only the checkpoint, not the candidates.
    run_anchor_discovery(
        db, [ANCHOR], source=make_source(), run=new_run(db),
        checkpoint=DiscoveryCheckpoint(),
    )
    assert db.query(SnkrdunkCandidate).count() == before, "upsert should have absorbed it"
    db.close()


# --- D: crash AFTER a durable checkpoint -------------------------------------


def test_urls_covered_by_a_durable_checkpoint_are_not_fetched_again(db_path):
    db1 = open_session(db_path)
    run1 = new_run(db1)
    first: list[str] = []
    run_anchor_discovery(db1, [ANCHOR], source=make_source(first), run=run1,
                         commit_every_rings=1)
    db1.close()

    # A hard kill after that commit loses nothing: reopen and continue.
    db2 = open_session(db_path)
    second: list[str] = []
    run_anchor_discovery(db2, [ANCHOR], source=make_source(second), run=new_run(db2))
    assert set(first).isdisjoint(second)
    db2.close()


# --- E: both modes survive a process boundary --------------------------------


def test_the_sequential_fallback_also_resumes_across_processes(db_path):
    db1 = open_session(db_path)
    summary1 = run_discovery(db1, source=make_source())
    cursor1 = summary1.cursor
    assert cursor1["url_offset"] == 5
    run = new_run(db1)
    save_checkpoint(db1, run, DiscoveryCheckpoint(
        sequential_shard_index=cursor1["shard_index"],
        sequential_url_offset=cursor1["url_offset"],
    ))
    db1.commit()
    db1.close()

    db2 = open_session(db_path)
    loaded = load_latest_checkpoint(db2)
    assert loaded.sequential_url_offset == 5
    from worker.adapters.snkrdunk_sitemap import SitemapCursor

    fetched: list[str] = []
    run_discovery(db2, source=make_source(fetched),
                  cursor=SitemapCursor(loaded.sequential_shard_index,
                                       loaded.sequential_url_offset))
    assert fetched == LISTINGS[5:10], "sequential mode must continue, not restart"
    db2.close()


def test_anchor_mode_survives_a_process_boundary(db_path):
    db1 = open_session(db_path)
    run_anchor_discovery(db1, [ANCHOR], source=make_source(), run=new_run(db1))
    progress1 = load_latest_checkpoint(db1).radii()
    db1.close()

    db2 = open_session(db_path)
    assert load_latest_checkpoint(db2).radii() == progress1
    assert progress1, "no anchor progress was persisted at all"
    db2.close()


# --- F: unknown version fails closed -----------------------------------------


def test_an_unknown_checkpoint_version_fails_closed(db_path):
    db = open_session(db_path)
    run = new_run(db)
    run.resume_state_json = {"version": 999, "anchor_progress": {}, "sequential": {}}
    db.commit()
    with pytest.raises(CheckpointVersionError):
        load_latest_checkpoint(db)
    db.close()


def test_a_malformed_payload_fails_closed(db_path):
    db = open_session(db_path)
    run = new_run(db)
    run.resume_state_json = {"version": CHECKPOINT_VERSION,
                             "anchor_progress": {"not-an-int": "nope"},
                             "shard_digests": {}, "sequential": {}}
    db.commit()
    with pytest.raises(CheckpointVersionError):
        load_latest_checkpoint(db)
    db.close()


def test_a_missing_version_fails_closed(db_path):
    db = open_session(db_path)
    run = new_run(db)
    run.resume_state_json = {"anchor_progress": {"1": 2}}
    db.commit()
    with pytest.raises(CheckpointVersionError):
        load_latest_checkpoint(db)
    db.close()


# --- G: legacy NULL rows stay valid ------------------------------------------


def test_rows_written_before_the_column_existed_are_ignored_not_read_as_empty(db_path):
    db = open_session(db_path)
    new_run(db, status="completed")   # resume_state_json stays NULL
    new_run(db, status="failed")
    assert load_latest_checkpoint(db) == DiscoveryCheckpoint()
    # And a real checkpoint on an OLDER row still wins over newer NULL rows.
    older = new_run(db)
    save_checkpoint(db, older, DiscoveryCheckpoint(anchor_progress={42: AnchorProgress(5, 0)}))
    db.commit()
    assert load_latest_checkpoint(db).radii() == {42: 5}
    db.close()


def test_no_runs_at_all_yields_empty_progress(db_path):
    db = open_session(db_path)
    assert load_latest_checkpoint(db) == DiscoveryCheckpoint()
    db.close()


# --- the persisted shape -----------------------------------------------------


def test_the_persisted_payload_is_compact_and_versioned(db_path):
    db = open_session(db_path)
    run = new_run(db)
    save_checkpoint(db, run, DiscoveryCheckpoint(
        anchor_progress={93522: AnchorProgress(24, 0), 94915: AnchorProgress(24, 0)},
        shard_digests={i: f"{i:064x}" for i in range(9)},
        sequential_shard_index=1, sequential_url_offset=1234))
    db.commit()
    payload = db.query(SnkrdunkDiscoveryRun).filter_by(id=run.id).one().resume_state_json
    assert payload["version"] == CHECKPOINT_VERSION
    assert payload["anchor_progress"] == {"93522": [24, 0], "94915": [24, 0]}
    assert len(payload["shard_digests"]) == 9
    assert payload["sequential"] == {"shard_index": 1, "url_offset": 1234}
    # No bodies, no URL arrays, no secrets.
    text = repr(payload)
    assert "http" not in text and "<html" not in text
    assert len(text) < 1200
    db.close()


def test_the_payload_does_not_grow_with_urls_inspected(db_path):
    """One integer per anchor - the size is set by anchor count, not by how
    much of the corpus has been walked."""
    small = DiscoveryCheckpoint(anchor_progress={1: AnchorProgress(1, 0)}).as_dict()
    large = DiscoveryCheckpoint(anchor_progress={1: AnchorProgress(100_000, 0)}).as_dict()
    assert len(repr(large)) - len(repr(small)) < 10


def test_checkpoint_round_trips(db_path):
    c = DiscoveryCheckpoint(anchor_progress={5: AnchorProgress(9, 0)},
                            shard_digests={0: "abc123"},
                            sequential_shard_index=2, sequential_url_offset=7)
    assert DiscoveryCheckpoint.from_dict(c.as_dict()) == c
    assert DiscoveryCheckpoint.from_dict(None) == DiscoveryCheckpoint()


# --- concurrency -------------------------------------------------------------


def test_two_discovery_executions_cannot_overlap(db_path):
    """The shared JobLock is reused - a second execution fails clean rather
    than forking the checkpoint history."""
    db = open_session(db_path)
    acquire_lock(db, DISCOVERY_LOCK, "someone-else", 1800)
    db.commit()
    with pytest.raises(LockHeldError):
        run_anchor_discovery_locked(db, [ANCHOR], source=make_source(), run=new_run(db))
    db.close()


def test_the_lock_is_released_so_the_next_run_can_take_it(db_path):
    db = open_session(db_path)
    run_anchor_discovery_locked(db, [ANCHOR], source=make_source(), run=new_run(db))
    # No LockHeldError: the first run released it.
    run_anchor_discovery_locked(db, [ANCHOR], source=make_source(), run=new_run(db))
    db.close()


# --- F: the newest checkpoint is authoritative, corrupt or not ---------------


def test_a_corrupt_newest_checkpoint_does_not_fall_back_to_an_older_valid_one(db_path):
    """The newest row describes work that actually happened. Quietly resuming
    from an older one would redo real work while looking healthy, so an
    unreadable newest checkpoint is an explicit failure."""
    db = open_session(db_path)
    older = new_run(db, status="completed")
    save_checkpoint(db, older, DiscoveryCheckpoint(
        anchor_progress={9030: AnchorProgress(3, 0)}))
    db.commit()

    newest = new_run(db, status="running")
    newest.resume_state_json = {"version": 99, "anchor_progress": {}}
    db.commit()

    with pytest.raises(CheckpointVersionError):
        load_latest_checkpoint(db)
    db.close()


def test_a_version_1_checkpoint_is_refused_rather_than_trusted(db_path):
    """Version 1 carried no sitemap digests, so there is no way to tell whether
    its positions are still valid. Assuming they are is the bug version 2
    exists to fix."""
    db = open_session(db_path)
    run = new_run(db)
    run.resume_state_json = {"version": 1, "anchor_progress": {"9030": 5},
                             "sequential": {"shard_index": 0, "url_offset": 0}}
    db.commit()
    with pytest.raises(CheckpointVersionError):
        load_latest_checkpoint(db)
    db.close()


def test_a_corrupt_checkpoint_does_not_block_a_newer_valid_one(db_path):
    """Recovery path: once a good checkpoint is written, the corrupt older row
    is simply never consulted again."""
    db = open_session(db_path)
    bad = new_run(db)
    bad.resume_state_json = {"version": 99}
    db.commit()
    good = new_run(db)
    save_checkpoint(db, good, DiscoveryCheckpoint(
        anchor_progress={9030: AnchorProgress(2, 0)}))
    db.commit()
    assert load_latest_checkpoint(db).radii() == {9030: 2}
    db.close()


# --- lock TTL vs runtime -----------------------------------------------------


def test_the_lock_ttl_always_outlives_the_runtime_cap():
    """A lock that expired mid-run would let a second execution start and fork
    the checkpoint history. The TTL is derived from the bounds, so it holds for
    every configuration rather than only the default."""
    from worker.jobs.discover_snkrdunk_sitemap import discovery_lock_ttl_seconds

    for runtime in (1, 30, 300, 900, 3600, 7200, 86400):
        bounds = CrawlBounds(max_runtime_seconds=runtime)
        ttl = discovery_lock_ttl_seconds(bounds)
        assert ttl > runtime, f"ttl {ttl} <= runtime cap {runtime}"
        # Real margin, not a rounding accident: the runtime cap governs only
        # the fetch loop, and the sitemap downloads happen before it starts.
        assert ttl - runtime >= 300, f"insufficient margin at runtime={runtime}"


def test_the_default_bounds_are_covered_by_the_registered_ttl():
    """The statically registered TTL must itself be safe for a default run, so
    a caller that never passes bounds is still protected."""
    from worker.job_locks import default_ttl_seconds
    from worker.jobs.discover_snkrdunk_sitemap import DISCOVERY_LOCK

    assert default_ttl_seconds(DISCOVERY_LOCK) > CrawlBounds().max_runtime_seconds


def test_the_derived_ttl_is_what_the_lock_actually_receives(db_path, monkeypatch):
    """Not merely computed - handed to the acquisition."""
    import worker.jobs.discover_snkrdunk_sitemap as mod
    from worker.jobs.discover_snkrdunk_sitemap import discovery_lock_ttl_seconds

    captured: dict[str, int | None] = {}
    real = mod.with_job_lock

    def spy(db, lock_name, *, ttl_seconds=None, **kw):
        captured["ttl"] = ttl_seconds
        return real(db, lock_name, ttl_seconds=ttl_seconds, **kw)

    monkeypatch.setattr(mod, "with_job_lock", spy)

    db = open_session(db_path)
    source = make_source()
    source.bounds = CrawlBounds(max_runtime_seconds=3600, max_urls_inspected=5,
                                request_delay_ms=0)
    run_anchor_discovery_locked(db, [ANCHOR], source=source, run=new_run(db))

    assert captured["ttl"] == discovery_lock_ttl_seconds(source.bounds)
    assert captured["ttl"] == 3600 * 2 + 300
    db.close()
