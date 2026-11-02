"""Plan at most one bounded published discovery intent per scheduled turn.

Planning writes one pending discovery row through the shared queue and nothing
else; the existing claim, admission, retention and result fences do the work.
Every guard fails closed: a skipped turn plans nothing and is retried later.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models import (
    CardPrint,
    FreshnessAttempt,
    FreshnessWork,
    ReleaseProduct,
    SnkrdunkCandidate,
    SourceCardMapping,
    SourceDispatchBudget,
)
from app.services.freshness_policy import require_utc
from app.services.freshness_queue import plan_discovery_scope
from opcg_source_identity import canonical_source_listing_identity
from snkrdunk_collector.discovery_seeds import seed_identities, seed_releases

SCOPE_PREFIX = "snkr-published:auto-v1-"
REQUEST_COST = 300
MAX_ANCHORS = 12
RADIUS_END = 48
MAX_PRODUCTS = 20
# Completed scopes are parked 36,500 days out; anything due sooner is open.
OPEN_HORIZON = timedelta(days=365)
RAW_DEMAND_WINDOW = timedelta(minutes=40)
EMPTY_RUN_LIMIT = 3
FAILED_RUN_LIMIT = 2
RECENT_RUNS = 3
STAMP = "%Y%m%dT%H%M%SZ"


def _published(session, source_id):
    return session.scalars(
        select(FreshnessWork)
        .where(
            FreshnessWork.source_id == source_id,
            FreshnessWork.kind == "discovery",
            FreshnessWork.scope_key.like("snkr-published:%"),
        )
        .order_by(FreshnessWork.id.desc())
    ).all()


def _release_key(code):
    return "".join(ch for ch in (code or "").upper() if ch not in "-_ ") or None


def _exhausted(session, previous):
    """(mapping ids, seed identities) whose neighbourhoods a completed full-radius intent emptied.

    neighbours() walks every radius round of every anchor before it stops, so a completed
    intent that inspected fewer products than its bound had no unexcluded neighbour left
    around any of its anchors; exclusions only grow, so those anchors stay spent."""
    mapping_ids, seed_ids = set(), set()
    for work in previous:
        cursor = work.resume_cursor or {}
        if (
            "inspected_identities" not in cursor
            or cursor.get("radius_start") != 1
            or (cursor.get("radius_end") or 0) < RADIUS_END
            or len(cursor["inspected_identities"]) >= (cursor.get("max_products") or 0)
            or _last_outcome(session, work) != "completed"
        ):
            continue
        mapping_ids.update(cursor.get("anchor_mapping_ids", []))
        seed_ids.update(cursor.get("anchor_seed_identities", []))
    return mapping_ids, seed_ids


def _anchors(session, source_id, previous, seeds=None, releases=None):
    """(mapping ids, seed identities, pool size), best first (owner 2026-11-01, perfectionist).

    Order: anchors whose neighbourhoods are not known to be spent; then anchors in a release with
    no SNKRDUNK candidate yet; then seeds before mappings (seeds are the owner-confirmed starting
    points in sets mappings never reached); then least used. A seed whose listing is already an
    approved mapping counts once, as the mapping. An anchor whose release is unknown never gets
    the uncovered-release priority."""
    rows = session.execute(
        select(SourceCardMapping, ReleaseProduct.official_code)
        .outerjoin(CardPrint, CardPrint.id == SourceCardMapping.card_print_id)
        .outerjoin(ReleaseProduct, ReleaseProduct.id == CardPrint.release_product_id)
        .where(
            SourceCardMapping.source_id == source_id,
            SourceCardMapping.is_active.is_(True),
            SourceCardMapping.superseded_at.is_(None),
            SourceCardMapping.review_status == "approved",
            SourceCardMapping.manual_verified.is_(True),
        )
        .order_by(SourceCardMapping.id)
    ).all()
    used, seed_used = {}, {}
    for work in previous:
        cursor = work.resume_cursor or {}
        for mapping_id in cursor.get("anchor_mapping_ids", []):
            used[mapping_id] = used.get(mapping_id, 0) + 1
        for identity in cursor.get("anchor_seed_identities", []):
            seed_used[identity] = seed_used.get(identity, 0) + 1
    spent_mappings, spent_seeds = _exhausted(session, previous)
    covered = {
        _release_key(code)
        for code in session.scalars(select(SnkrdunkCandidate.detected_set_code).distinct())
    }

    def tier(release):
        key = _release_key(release)
        return 0 if key is not None and key not in covered else 1

    # One entry per listing identity, as intent() requires.
    entries, identities = [], set()
    for row, release in rows:
        identity = canonical_source_listing_identity("snkrdunk", row.source_url)
        if not identity or identity in identities:
            continue
        identities.add(identity)
        entries.append(((row.id in spent_mappings, tier(release), 1, used.get(row.id, 0), row.id),
                        ("mapping", row.id)))
    seeds = seed_identities() if seeds is None else seeds
    releases = seed_releases() if releases is None else releases
    for position, identity in enumerate(seeds):
        if identity in identities:
            continue
        identities.add(identity)
        entries.append(((identity in spent_seeds, tier(releases.get(identity)), 0,
                         seed_used.get(identity, 0), position), ("seed", identity)))
    chosen = [entry for _, entry in sorted(entries, key=lambda e: e[0])][:MAX_ANCHORS]
    return ([v for k, v in chosen if k == "mapping"], [v for k, v in chosen if k == "seed"],
            len(identities))


def _planned_at(work):
    stamp = work.scope_key[len(SCOPE_PREFIX) :]
    return datetime.strptime(stamp, STAMP).replace(tzinfo=timezone.utc)


def _last_outcome(session, work):
    return session.scalar(
        select(FreshnessAttempt.outcome)
        .where(FreshnessAttempt.work_id == work.id)
        .order_by(FreshnessAttempt.id.desc())
        .limit(1)
    )


def skip_reason(session, source_id, *, now, interval, previous=None):
    previous = _published(session, source_id) if previous is None else previous
    for work in previous:
        if work.state == "claimed" or (
            work.state == "pending"
            and require_utc(work.next_due_at) < now + OPEN_HORIZON
        ):
            return "discovery_open"
    auto = [w for w in previous if w.scope_key.startswith(SCOPE_PREFIX)]
    if auto and _planned_at(auto[0]) > now - interval:
        return "interval"
    recent = auto[:RECENT_RUNS]
    if (
        sum(_last_outcome(session, w) != "completed" for w in recent)
        >= FAILED_RUN_LIMIT
    ):
        return "recent_failures"
    budget = session.scalar(
        select(SourceDispatchBudget).where(SourceDispatchBudget.source_id == source_id)
    )
    if (
        budget is None
        or not budget.enabled
        or budget.pause_reason is not None
        or (budget.paused_until is not None and require_utc(budget.paused_until) > now)
    ):
        return "source_closed"
    used = budget.used_requests
    if (
        now - require_utc(budget.window_started_at)
    ).total_seconds() >= budget.window_seconds:
        used = 0
    spare = budget.request_limit - used - budget.reserved_requests
    # Observed-cost guard from SNKR_PUBLISHED_DISCOVERY_RECOVERY.md: the next
    # 40 min of RAW demand at the 24h maximum request cost, plus this intent.
    demand = session.scalar(
        select(func.count())
        .select_from(FreshnessWork)
        .where(
            FreshnessWork.source_id == source_id,
            FreshnessWork.kind == "refresh",
            FreshnessWork.state == "pending",
            FreshnessWork.next_due_at <= now + RAW_DEMAND_WINDOW,
        )
    )
    peak = (
        session.scalar(
            select(func.max(FreshnessAttempt.actual_request_cost))
            .join(FreshnessWork, FreshnessWork.id == FreshnessAttempt.work_id)
            .where(
                FreshnessWork.source_id == source_id,
                FreshnessWork.kind == "refresh",
                FreshnessAttempt.finished_at >= now - timedelta(days=1),
            )
        )
        or 0
    )
    if demand * peak + REQUEST_COST > spare:
        return "request_budget"
    return None


def plan_next_discovery(session, source_id, *, now, interval):
    """Return (work, None) when planned, or (None, reason) when skipped."""
    previous = _published(session, source_id)
    reason = skip_reason(
        session, source_id, now=now, interval=interval, previous=previous
    )
    if reason:
        return None, reason
    anchors, seeds, pool = _anchors(session, source_id, previous)
    if not anchors and not seeds:
        return None, "no_anchors"
    auto = [w for w in previous if w.scope_key.startswith(SCOPE_PREFIX)]
    recent = auto[:EMPTY_RUN_LIMIT]
    # Neighbourhoods exhausted: wait until a new anchor is verified.
    if len(recent) == EMPTY_RUN_LIMIT and all(
        not (w.resume_cursor or {}).get("inspected_identities")
        and (w.resume_cursor or {}).get("anchor_pool_size") == pool
        for w in recent
    ):
        return None, "neighbourhoods_exhausted"
    scope = SCOPE_PREFIX + now.strftime(STAMP)
    work = plan_discovery_scope(
        session, source_id, scope, due_at=now, estimated_request_cost=REQUEST_COST
    )
    if work.resume_cursor is not None or work.attempt_count:
        return None, "scope_exists"
    work.resume_cursor = {
        "version": 1,
        "scope_key": scope,
        "explicit_published_discovery": True,
        "anchor_mapping_ids": anchors,
        "anchor_seed_identities": seeds,
        "radius_start": 1,
        "radius_end": RADIUS_END,
        "max_products": MAX_PRODUCTS,
        "anchor_pool_size": pool,
        "planned_by": "snkrdunk-due auto-v1",
    }
    return work, None
