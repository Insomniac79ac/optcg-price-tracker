"""Plan at most one bounded published discovery intent per scheduled turn.

Planning writes one pending discovery row through the shared queue and nothing
else; the existing claim, admission, retention and result fences do the work.
Every guard fails closed: a skipped turn plans nothing and is retried later.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models import (
    FreshnessAttempt,
    FreshnessWork,
    SourceCardMapping,
    SourceDispatchBudget,
)
from app.services.freshness_policy import require_utc
from app.services.freshness_queue import plan_discovery_scope
from opcg_source_identity import canonical_source_listing_identity

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


def _anchors(session, source_id, previous):
    rows = session.scalars(
        select(SourceCardMapping)
        .where(
            SourceCardMapping.source_id == source_id,
            SourceCardMapping.is_active.is_(True),
            SourceCardMapping.superseded_at.is_(None),
            SourceCardMapping.review_status == "approved",
            SourceCardMapping.manual_verified.is_(True),
        )
        .order_by(SourceCardMapping.id)
    ).all()
    used = {}
    for work in previous:
        for mapping_id in (work.resume_cursor or {}).get("anchor_mapping_ids", []):
            used[mapping_id] = used.get(mapping_id, 0) + 1
    # Least used first; one mapping per listing identity, as intent() requires.
    chosen, identities = [], set()
    for row in sorted(rows, key=lambda m: (used.get(m.id, 0), m.id)):
        identity = canonical_source_listing_identity("snkrdunk", row.source_url)
        if not identity or identity in identities:
            continue
        identities.add(identity)
        chosen.append(row.id)
    return chosen, len(identities)


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
    anchors, pool = _anchors(session, source_id, previous)
    if not anchors:
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
        "anchor_mapping_ids": anchors[:MAX_ANCHORS],
        "radius_start": 1,
        "radius_end": RADIUS_END,
        "max_products": MAX_PRODUCTS,
        "anchor_pool_size": pool,
        "planned_by": "snkrdunk-due auto-v1",
    }
    return work, None
