"""Bounded SNKRDUNK discovery: sitemap -> listing evidence -> candidates only.

This is where the pieces meet. It produces `snkrdunk_candidates` rows and
NOTHING else - no source mappings, no approvals, no price observations. The
exact-print gate shipped in 4F-1 remains the only way a candidate becomes a
mapping, and it still requires a human to name the printing.

WHAT LANDS IN WHICH CANDIDATE COLUMN, and why it matters that these are not
interchangeable:

    detected_card_code  the code, from the bracketed token in the title.
    detected_set_code   the RESOLVED Atlas product code, or NULL. Never the
                        card-code prefix: that is the card's original set, not
                        the product this printing shipped in.
    detected_rarity     the raw published token - "L", "L-P", "SEC-SP". This is
                        where parallel-FAMILY evidence lives, descriptively.
    detected_variant    an EXACT official_asset_variant ('base'/'pN'/'rN') read
                        off the image filename, or NULL. Never "P".

No migration was needed for any of it: every field above already exists on the
candidate model, and English listings are excluded at parse time rather than
persisted with a new language column.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from worker.adapters.snkrdunk_anchor_plan import (
    NOTHING_CONSUMED,
    locate_anchors,
    plan_rings,
)
from worker.adapters.snkrdunk_sitemap import (
    CrawlBounds,
    SitemapCursor,
    SnkrdunkSitemapSource,
)
from worker.job_locks import with_job_lock
from worker.jobs.snkrdunk_checkpoint import (
    AnchorProgress,
    DiscoveryCheckpoint,
    load_latest_checkpoint,
    reconcile_with_sitemap,
    save_checkpoint,
)
from worker.matching.non_target_tcg import identify_non_target_tcg
from worker.matching.opcg_normalizer import normalize_title
from worker.matching.snkrdunk_listing_evidence import ListingEvidence, parse_listing
from worker.models import SnkrdunkCandidate, SnkrdunkDiscoveryRun

logger = logging.getLogger(__name__)


@dataclass
class DiscoverySummary:
    """Everything a bounded run did, in the terms the tranche is judged on."""

    urls_inspected: int = 0
    pages_fetched: int = 0
    http_errors: int = 0
    blocked_responses: int = 0
    not_one_piece: int = 0
    # Pages refused because the source's own asset naming identified them as
    # another game. Reported separately from `not_one_piece`, which means only
    # "no card code was found": these DID carry a well-formed code, and
    # collapsing the two would hide a contaminating game behind a parser
    # statistic. No schema work - this summary is returned and logged, never
    # stored.
    non_target_tcg: int = 0
    english_listings_excluded: int = 0
    candidates_inserted: int = 0
    candidates_updated: int = 0
    duplicates_suppressed: int = 0
    with_exact_asset_variant: int = 0
    parallel_family_only: int = 0
    timestamp_images: int = 0
    product_labels_resolved: int = 0
    product_labels_unresolved: int = 0
    stop_reason: str = "not started"
    cursor: dict = field(default_factory=dict)
    card_codes: set[str] = field(default_factory=set)
    unresolved_product_labels: dict[str, int] = field(default_factory=dict)
    english_examples: list[str] = field(default_factory=list)
    non_target_tcg_games: dict[str, int] = field(default_factory=dict)
    non_target_examples: list[str] = field(default_factory=list)
    # Sitemap shards whose content moved since the last run, and the anchors
    # whose progress was discarded as a result. Both are expected to be empty
    # on an ordinary run.
    changed_shards: list[int] = field(default_factory=list)
    invalidated_anchors: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        data = {k: v for k, v in self.__dict__.items()}
        data["card_codes"] = sorted(self.card_codes)
        data["distinct_card_codes"] = len(self.card_codes)
        return data


def evidence_to_candidate_fields(ev: ListingEvidence) -> dict:
    """The candidate row this evidence justifies - and only what it justifies."""
    return {
        "title": ev.title,
        "price_jpy": ev.price_jpy,
        "image_url": ev.image_url,
        "raw_text": ev.raw_text,
        "normalized_title": normalize_title(ev.title),
        "detected_card_code": ev.card_code,
        # Resolved product code or NULL - never the card-code prefix.
        "detected_set_code": ev.resolved_product_code,
        # Raw published token; carries parallel-family evidence descriptively.
        "detected_rarity": ev.rarity_token,
        # Exact asset variant only; NULL when the filename does not name one.
        "detected_variant": ev.asset_variant,
    }


def upsert_candidate_from_evidence(
    db: Session, ev: ListingEvidence, discovery_run_id: int | None = None
) -> tuple[SnkrdunkCandidate, bool]:
    """Insert or refresh one candidate, deduplicated by source_url.

    A prior human match decision is never overwritten here - descriptive
    evidence is refreshed, `match_status` is left alone.
    """
    fields = evidence_to_candidate_fields(ev)
    existing = (
        db.query(SnkrdunkCandidate).filter_by(source_url=ev.source_url).one_or_none()
    )
    if existing is None:
        row = SnkrdunkCandidate(
            source_url=ev.source_url, discovery_run_id=discovery_run_id, **fields
        )
        db.add(row)
        db.flush()
        return row, True

    for key, value in fields.items():
        setattr(existing, key, value)
    if discovery_run_id is not None:
        existing.discovery_run_id = discovery_run_id
    db.flush()
    return existing, False


def _consume(db, pages, summary: DiscoverySummary, discovery_run_id: int | None):
    """Turn fetched pages into candidates. Shared by both entry points so the
    sequential sweep and the anchor plan can never classify evidence
    differently."""
    outcome = None
    for page, outcome in pages:
        if page.http_status != 200 or not page.body:
            summary.http_errors += 1
            continue

        ev = parse_listing(page.url, page.body)

        # ANOTHER GAME'S CARD, established positively from the source's own
        # asset naming - see worker.matching.non_target_tcg. Checked before
        # `is_one_piece` because a Shadowverse code is structurally identical
        # to a One Piece one ([BP08-117]) and so passes that test; the more
        # specific fact is the one worth acting on and reporting. The module
        # answers None for everything it does not positively recognise, so an
        # unfamiliar or future One Piece listing still becomes a candidate.
        foreign_game = identify_non_target_tcg(ev.image_url)
        if foreign_game is not None:
            summary.non_target_tcg += 1
            summary.non_target_tcg_games[foreign_game] = (
                summary.non_target_tcg_games.get(foreign_game, 0) + 1
            )
            if len(summary.non_target_examples) < 10:
                summary.non_target_examples.append(
                    f"{foreign_game}: {ev.card_code} {page.url}"
                )
            continue

        if not ev.is_one_piece:
            summary.not_one_piece += 1
            continue

        # A different catalogue, not an unmatched Japanese card. Counted and
        # reported, never persisted into the JP candidate path.
        if ev.is_english:
            summary.english_listings_excluded += 1
            if len(summary.english_examples) < 10:
                summary.english_examples.append(f"{ev.card_code} {page.url}")
            continue

        summary.card_codes.add(ev.card_code)
        if ev.product_label:
            if ev.resolved_product_code:
                summary.product_labels_resolved += 1
            else:
                summary.product_labels_unresolved += 1
                summary.unresolved_product_labels[ev.product_label] = (
                    summary.unresolved_product_labels.get(ev.product_label, 0) + 1
                )
        if ev.asset_variant:
            summary.with_exact_asset_variant += 1
        elif ev.parallel_family:
            summary.parallel_family_only += 1
        if ev.image_is_timestamp:
            summary.timestamp_images += 1

        _, created = upsert_candidate_from_evidence(db, ev, discovery_run_id)
        if created:
            summary.candidates_inserted += 1
        else:
            summary.candidates_updated += 1
            summary.duplicates_suppressed += 1

    if outcome is not None:
        # ACCUMULATED, not assigned. The anchor path calls this once per ring,
        # so assigning would leave the summary reporting only the final ring -
        # which read as "2 URLs inspected" for a run that fetched eighteen.
        summary.urls_inspected += outcome.urls_inspected
        summary.pages_fetched += outcome.pages_fetched
        summary.blocked_responses += outcome.blocked_responses
        summary.stop_reason = outcome.stop_reason
        if getattr(outcome, "cursor", None) is not None:
            summary.cursor = outcome.cursor.as_dict()
    return summary


def run_discovery(
    db: Session,
    source: SnkrdunkSitemapSource | None = None,
    bounds: CrawlBounds | None = None,
    cursor: SitemapCursor | None = None,
    discovery_run_id: int | None = None,
    commit: bool = True,
) -> DiscoverySummary:
    """One bounded pass. Ends when a cap binds; that is the expected outcome."""
    owns_source = source is None
    source = source or SnkrdunkSitemapSource(bounds=bounds)
    summary = DiscoverySummary()

    try:
        summary = _consume(db, source.crawl(cursor=cursor), summary, discovery_run_id)

        if commit:
            db.commit()
        return summary
    finally:
        if owns_source:
            source.close()


# The lock name discovery takes. Registered in worker.job_locks.LOCK_TTL_SECONDS
# so two executions - manual CLI, Celery task, a retried container - cannot
# interleave and fork the checkpoint history into two divergent lines.
DISCOVERY_LOCK = "snkrdunk_discovery"

# The lock must outlive any legitimate run, or a slow discovery would have its
# lock expire underneath it and a second execution could start and fork the
# checkpoint history. `max_runtime_seconds` caps only the FETCH loop - the
# sitemap index and nine shard downloads happen before it starts - so the TTL
# is derived from the bounds with generous headroom rather than fixed.
LOCK_MARGIN_SECONDS = 300
LOCK_RUNTIME_MULTIPLIER = 2


def discovery_lock_ttl_seconds(bounds: CrawlBounds) -> int:
    """A lock lifetime guaranteed to exceed this run's own runtime cap."""
    return int(bounds.max_runtime_seconds) * LOCK_RUNTIME_MULTIPLIER + LOCK_MARGIN_SECONDS


def _process_ring(db, source, urls, summary, run) -> None:
    """Fetch one ring's URLs and persist any candidates they yield.

    Leaves the transaction OPEN. The caller commits, which is what makes the
    candidates and the checkpoint that describes them durable together.
    """
    _consume(db, source.crawl_urls(list(urls)), summary, run.id if run else None)


def run_anchor_discovery(
    db: Session,
    anchor_urls: list[str],
    source: SnkrdunkSitemapSource | None = None,
    bounds: CrawlBounds | None = None,
    checkpoint: DiscoveryCheckpoint | None = None,
    run: SnkrdunkDiscoveryRun | None = None,
    commit_every_rings: int = 4,
) -> tuple[DiscoverySummary, DiscoveryCheckpoint]:
    """Discovery seeded from listings Atlas already maps - the default strategy.

    Measured on 2026-08-27: a cold sequential sweep found 0 One Piece listings
    in 60 URLs, a stratified sample across all nine shards found 6 in 108
    (5.6%), and windows around already-mapped listings found 23 in 36 (64%).

    RESUMPTION. `checkpoint` defaults to the latest readable one in the
    database, so an ordinary call continues wherever the last run - completed
    or killed - actually got to.

    ORDERING, which is the whole point of the ring granularity: a ring's URLs
    are fetched, their candidates written, the checkpoint advanced to that
    ring, and only then is the transaction committed. Candidates and checkpoint
    therefore become durable in the same commit. A crash before that commit
    rolls back both, so the ring is replayed - and replay is harmless because
    candidates upsert on source_url. A ring is never skipped.
    """
    owns_source = source is None
    source = source or SnkrdunkSitemapSource(bounds=bounds)
    summary = DiscoverySummary()
    checkpoint = checkpoint if checkpoint is not None else load_latest_checkpoint(db)

    try:
        shards = source.shard_urls()
        if not shards:
            summary.stop_reason = "no sitemap shards available"
            return summary, checkpoint

        # Locating anchors costs the sitemap index plus one request per shard -
        # never a listing page, however large the corpus.
        shard_listing_urls = {i: source.listing_urls_in_shard(u) for i, u in enumerate(shards)}
        anchors = locate_anchors(anchor_urls, shard_listing_urls)
        if not anchors:
            summary.stop_reason = "no anchors located; use run_discovery for a cold sweep"
            return summary, checkpoint

        # A stored radius is a POSITION, and a position only means anything
        # against the list it was measured in. Any shard whose content moved
        # has its progress discarded here, so a newly published listing can
        # never be skipped just because an old offset said it had been passed.
        reconciliation = reconcile_with_sitemap(checkpoint, anchors, shard_listing_urls)
        checkpoint = reconciliation.checkpoint
        summary.changed_shards = reconciliation.changed_shards
        summary.invalidated_anchors = reconciliation.invalidated_anchors

        rings = plan_rings(
            anchors, shard_listing_urls, checkpoint.radii(),
            source.bounds.max_urls_inspected,
        )
        if not rings:
            summary.stop_reason = "anchor windows exhausted"
            return summary, checkpoint

        by_shard = {a.listing_id: a.shard_index for a in anchors}
        since_commit = 0
        for ring in rings:
            _process_ring(db, source, ring.urls, summary, run)
            # Advance only after this ring's candidates are in the transaction.
            checkpoint.anchor_progress[ring.anchor_listing_id] = AnchorProgress(
                radius=ring.radius, shard=by_shard[ring.anchor_listing_id]
            )
            if run is not None:
                save_checkpoint(db, run, checkpoint)
            since_commit += 1
            if since_commit >= commit_every_rings:
                db.commit()
                since_commit = 0

        if run is not None:
            save_checkpoint(db, run, checkpoint)
        db.commit()
        summary.stop_reason = summary.stop_reason or "plan exhausted"
        return summary, checkpoint
    finally:
        if owns_source:
            source.close()


def run_anchor_discovery_locked(
    db: Session,
    anchor_urls: list[str],
    **kwargs,
) -> tuple[DiscoverySummary, DiscoveryCheckpoint]:
    """`run_anchor_discovery` under the shared advisory lock.

    Reuses worker.job_locks - the same non-blocking JobLock table that guards
    price_refresh and market_workflow - rather than inventing a scheduler. A
    second execution raises LockHeldError instead of waiting, so two runs can
    never advance the checkpoint concurrently and split its history.
    """
    bounds = kwargs.get("bounds")
    source = kwargs.get("source")
    effective = bounds or (source.bounds if source is not None else CrawlBounds())
    with with_job_lock(
        db, DISCOVERY_LOCK, ttl_seconds=discovery_lock_ttl_seconds(effective)
    ):
        return run_anchor_discovery(db, anchor_urls, **kwargs)
