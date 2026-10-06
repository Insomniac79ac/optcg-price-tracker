"""One metered diagnostic attempt per retained SNKRDUNK denial.

Ordinary dispatch remains paused throughout. This is an explicit operator path,
not a periodic retry or alternate source session/egress. A fresh required denial
revokes the diagnostic grant immediately. No mapping or price writer lives here.
"""

from copy import deepcopy
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select
from app.models import FreshnessAttempt, FreshnessWork, RawSnapshot, Source
from app.services import freshness_queue as queue
from app.services.freshness_policy import utc_now, require_utc
from opcg_source_identity import canonical_source_listing_identity

MAX_RECOVERY_REQUESTS = 600


def latest_denial_id(db, source_id):
    return db.scalar(
        select(FreshnessAttempt.id)
        .join(FreshnessWork, FreshnessWork.id == FreshnessAttempt.work_id)
        .where(
            FreshnessWork.source_id == source_id,
            FreshnessAttempt.outcome == "source_denial",
        )
        .order_by(FreshnessAttempt.id.desc())
        .limit(1)
    )


def permitted_recovery_request(db, budget, work):
    cursor = work.resume_cursor or {}
    denial_id = cursor.get("recovery_denial_attempt_id")
    if (
        not budget.enabled
        or budget.pause_reason != "source_denial"
        or budget.paused_until is not None
        or work.kind != "validation"
        or work.scope_key != f"source-recovery:snkrdunk:{denial_id}"
        or cursor.get("required_denial")
        or work.attempt_count != 1
        or not 1 <= work.estimated_request_cost <= MAX_RECOVERY_REQUESTS
        or db.scalar(select(Source.name).where(Source.id == work.source_id))
        != "snkrdunk"
        or denial_id != latest_denial_id(db, work.source_id)
    ):
        return False
    mapping = queue._eligible_mapping(db, cursor.get("mapping_id"))
    return (
        mapping.source_id == work.source_id
        and mapping.card_print_id == cursor.get("card_print_id")
        and mapping.canonical_source_listing_identity == cursor.get("product_identity")
    )


def claim_source_recovery(
    db,
    source_id,
    mapping_id,
    denial_attempt_id,
    owner,
    *,
    request_bound,
    lease=timedelta(minutes=4),
    clock=utc_now,
):
    """Reserve exactly once while keeping the source-wide pause in place."""
    if (
        not owner
        or len(owner) > 128
        or type(request_bound) is not int
        or not 1 <= request_bound <= MAX_RECOVERY_REQUESTS
        or not timedelta(0) < lease <= timedelta(minutes=5)
    ):
        raise ValueError(
            "bounded recovery owner, request reservation and lease required"
        )
    budget = queue._budget(db, source_id)
    now = require_utc(clock())
    queue._roll_window(budget, now)
    queue._recover_expired(db, budget, now)
    if (
        not budget.enabled
        or budget.pause_reason != "source_denial"
        or budget.paused_until is not None
        or db.scalar(select(Source.name).where(Source.id == source_id)) != "snkrdunk"
        or denial_attempt_id != latest_denial_id(db, source_id)
    ):
        raise ValueError("current retained SNKRDUNK source denial required")
    denial_work = db.scalar(
        select(FreshnessWork)
        .join(FreshnessAttempt, FreshnessAttempt.work_id == FreshnessWork.id)
        .where(FreshnessAttempt.id == denial_attempt_id)
    )
    if denial_work.kind != "refresh":
        raise ValueError("a refused recovery probe cannot authorize another probe")
    if (
        budget.reserved_requests
        or budget.request_limit - budget.used_requests < request_bound
    ):
        return None
    scope = f"source-recovery:snkrdunk:{denial_attempt_id}"
    if (
        db.scalar(
            select(FreshnessWork.id).where(
                FreshnessWork.source_id == source_id, FreshnessWork.scope_key == scope
            )
        )
        is not None
    ):
        return None  # Never replay, retry after expiry, or rotate mapping/session.
    mapping = queue._eligible_mapping(db, mapping_id)
    if mapping.source_id != source_id:
        raise ValueError("recovery mapping belongs to another source")
    work = queue.plan_validation(
        db, source_id, scope, due_at=now, estimated_request_cost=request_bound
    )
    cursor = {
        "version": 1,
        "recovery_denial_attempt_id": denial_attempt_id,
        "mapping_id": mapping.id,
        "card_print_id": mapping.card_print_id,
        "product_identity": mapping.canonical_source_listing_identity,
    }
    work.resume_cursor = cursor
    token = str(uuid4())
    work.state, work.claim_token, work.claimed_by = "claimed", token, owner
    work.claimed_at, work.claim_expires_at = now, now + lease
    work.attempt_count = 1
    budget.reserved_requests += request_bound
    budget.claim_sequence += 1
    work.last_claim_sequence, work.updated_at = budget.claim_sequence, now
    db.add(
        FreshnessAttempt(
            work_id=work.id,
            claim_token=token,
            claimed_by=owner,
            claimed_at=now,
            reserved_request_cost=request_bound,
            request_costs=[],
        )
    )
    db.flush()
    return queue.Claim(
        work.id,
        token,
        now + lease,
        "validation",
        None,
        None,
        scope,
        deepcopy(cursor),
        (),
        request_bound,
    )


def resume_after_recovery(db, token, *, clock=utc_now):
    """Clear only this retained pause after a settled, exact product validation."""
    budget, work, attempt = queue._locked_claim(db, token)
    cursor = work.resume_cursor or {}
    if not permitted_recovery_request(db, budget, work):
        raise ValueError("recovery authority no longer current")
    snapshot = (
        db.get(RawSnapshot, attempt.raw_snapshot_id)
        if attempt.raw_snapshot_id is not None
        else None
    )
    if (
        attempt.outcome != "completed"
        or attempt.finished_at is None
        or not cursor.get("identity_verified")
        or not cursor.get("required_product_verified")
        or cursor.get("raw_outcome") not in {"listed", "no_listing"}
        or snapshot is None
        or snapshot.source_id != work.source_id
        or snapshot.http_status != 200
        or canonical_source_listing_identity("snkrdunk", snapshot.source_url)
        != cursor["product_identity"]
        or not attempt.started_at <= snapshot.fetched_at <= attempt.finished_at
        or budget.reserved_requests != 0
        or attempt.actual_request_cost != sum(attempt.request_costs)
    ):
        raise ValueError(
            "settled current exact product evidence required before resume"
        )
    now = require_utc(clock())
    if not attempt.finished_at <= now <= attempt.finished_at + timedelta(minutes=5):
        raise ValueError("recovery evidence is no longer current")
    budget.pause_reason, budget.paused_until = None, None
    db.flush()
