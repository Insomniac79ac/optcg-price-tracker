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
MISSING_ARTWORK_REASONS = frozenset(
    {
        "artwork_not_confirmed_match:placeholder_image_url",
        "no_raw_condition_price_available",
    }
)


def _network_repair_basis(db, source_id, cursor, now=None):
    """One explicitly authorized repair of a settled, non-denial refusal.

    This authorizes a fresh ordinary capture, never clears a pause using old
    evidence. A refused repair cannot itself authorize another repair.
    """
    parent_id = cursor.get("network_repair_of")
    if type(parent_id) is not int or parent_id <= 0:
        raise ValueError("explicit identity-only repair basis required")
    parent = db.get(FreshnessWork, parent_id)
    denial_id = cursor.get("recovery_denial_attempt_id")
    if (
        parent is None
        or parent.source_id != source_id
        or parent.kind != "validation"
        or parent.state != "blocked"
        or parent.scope_key != f"source-recovery:snkrdunk:{denial_id}"
        or parent.attempt_count != 1
        or (parent.resume_cursor or {}).get("required_denial")
        or any(
            (parent.resume_cursor or {}).get(key) != cursor.get(key)
            for key in ("mapping_id", "card_print_id", "product_identity")
        )
        or not set((parent.last_failure or "").split(";")) <= MISSING_ARTWORK_REASONS
        or "artwork_not_confirmed_match:placeholder_image_url"
        not in (parent.last_failure or "")
    ):
        raise ValueError("only the original missing-artwork refusal permits repair")
    attempt = db.scalar(
        select(FreshnessAttempt)
        .where(FreshnessAttempt.work_id == parent.id)
        .order_by(FreshnessAttempt.id.desc())
        .limit(1)
    )
    snapshot = (
        db.get(RawSnapshot, attempt.raw_snapshot_id)
        if attempt and attempt.raw_snapshot_id
        else None
    )
    if (
        attempt is None
        or attempt.outcome != "identity_refusal"
        or attempt.finished_at is None
        or snapshot is None
        or (
            now is not None
            and not attempt.finished_at
            <= now
            <= attempt.finished_at + timedelta(hours=24)
        )
        or snapshot.source_id != source_id
        or snapshot.http_status != 200
        or canonical_source_listing_identity("snkrdunk", snapshot.source_url)
        != cursor.get("product_identity")
        or not attempt.started_at <= snapshot.fetched_at <= attempt.finished_at
        or not attempt.actual_request_cost
        or attempt.actual_request_cost != sum(attempt.request_costs)
        or attempt.actual_request_cost != attempt.charged_request_cost
    ):
        raise ValueError(
            "settled retained successful product capture required for repair"
        )
    return parent


def _recovery_scope(cursor):
    scope = f"source-recovery:snkrdunk:{cursor.get('recovery_denial_attempt_id')}"
    if cursor.get("network_repair_of") is not None:
        scope += f":network-repair:{cursor['network_repair_of']}"
    return scope


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
        or work.scope_key != _recovery_scope(cursor)
        or cursor.get("required_denial")
        or work.attempt_count != 1
        or not 1 <= work.estimated_request_cost <= MAX_RECOVERY_REQUESTS
        or db.scalar(select(Source.name).where(Source.id == work.source_id))
        != "snkrdunk"
        or denial_id != latest_denial_id(db, work.source_id)
    ):
        return False
    if cursor.get("network_repair_of") is not None:
        try:
            _network_repair_basis(db, work.source_id, cursor)
        except ValueError:
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
    network_repair_of=None,
):
    """Reserve exactly once while keeping the source-wide pause in place."""
    if (
        not owner
        or len(owner) > 128
        or type(request_bound) is not int
        or not 1 <= request_bound <= MAX_RECOVERY_REQUESTS
        or type(denial_attempt_id) is not int
        or denial_attempt_id <= 0
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
    if denial_work is None or denial_work.kind != "refresh":
        raise ValueError("a refused recovery probe cannot authorize another probe")
    if (
        budget.reserved_requests
        or budget.request_limit - budget.used_requests < request_bound
    ):
        return None
    mapping = queue._eligible_mapping(db, mapping_id)
    cursor = {
        "version": 1,
        "recovery_denial_attempt_id": denial_attempt_id,
        "mapping_id": mapping.id,
        "card_print_id": mapping.card_print_id,
        "product_identity": mapping.canonical_source_listing_identity,
    }
    if network_repair_of is not None:
        cursor["network_repair_of"] = network_repair_of
        _network_repair_basis(db, source_id, cursor, now)
    scope = _recovery_scope(cursor)
    existing = db.scalar(
        select(FreshnessWork)
        .where(FreshnessWork.source_id == source_id, FreshnessWork.scope_key == scope)
        .with_for_update()
    )
    if existing is not None and not (
        existing.state == "pending"
        and existing.attempt_count == 0
        and existing.next_due_at <= now
        and (existing.resume_cursor or {}).get("scheduled_recovery_authorized") is True
        and existing.resume_cursor.get("mapping_id") == mapping_id
        and existing.estimated_request_cost == request_bound
    ):
        return None  # Never replay, retry after expiry, or rotate mapping/session.
    mapping = queue._eligible_mapping(db, mapping_id)
    if mapping.source_id != source_id:
        raise ValueError("recovery mapping belongs to another source")
    if existing is not None and (
        existing.resume_cursor.get("card_print_id") != mapping.card_print_id
        or existing.resume_cursor.get("product_identity")
        != mapping.canonical_source_listing_identity
    ):
        raise ValueError("planned recovery lineage changed")
    work = existing or queue.plan_validation(
        db, source_id, scope, due_at=now, estimated_request_cost=request_bound
    )
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


def plan_source_recovery(
    db,
    source_id,
    mapping_id,
    denial_attempt_id,
    *,
    request_bound=600,
    clock=utc_now,
    network_repair_of=None,
):
    """Explicit authority to serve one diagnostic at a normal scheduled turn.

    Planning performs no I/O and reserves no requests. Reuse the same authority
    validation as immediate invocation, then leave an unattempted pending scope.
    """
    claim = claim_source_recovery(
        db,
        source_id,
        mapping_id,
        denial_attempt_id,
        "snkrdunk-recovery-planning",
        request_bound=request_bound,
        clock=clock,
        network_repair_of=network_repair_of,
    )
    if claim is None:
        return None
    budget, work, attempt = queue._locked_claim(db, claim.claim_token)
    # No network grant exists: make only the explicit intent durable. The
    # scheduled singleton will issue its own fresh claim/lease and reservation.
    db.delete(attempt)
    budget.reserved_requests -= request_bound
    budget.claim_sequence -= 1
    work.attempt_count = 0
    work.last_claim_sequence = 0
    queue._clear_claim(work, require_utc(clock()))
    work.resume_cursor = {**work.resume_cursor, "scheduled_recovery_authorized": True}
    db.flush()
    return work


def resume_after_network_recovery(db, token, *, clock=utc_now):
    """Fresh source access can recover while missing artwork stays quarantined.

    Only the explicit repair grant may use this path. It never validates a
    CardPrint, reports a RAW check or freshens a price.
    """
    budget, work, attempt = queue._locked_claim(db, token)
    cursor = work.resume_cursor or {}
    snapshot = (
        db.get(RawSnapshot, attempt.raw_snapshot_id)
        if attempt.raw_snapshot_id
        else None
    )
    if (
        cursor.get("network_repair_of") is None
        or not permitted_recovery_request(db, budget, work)
        or attempt.outcome != "completed"
        or attempt.finished_at is None
        or cursor.get("source_access_verified") is not True
        or cursor.get("identity_verified") is not False
        or cursor.get("required_product_verified") is not True
        or cursor.get("raw_outcome") != "quarantined"
        or not set(cursor.get("identity_refusal_reasons") or [])
        <= MISSING_ARTWORK_REASONS
        or "artwork_not_confirmed_match:placeholder_image_url"
        not in (cursor.get("identity_refusal_reasons") or [])
        or snapshot is None
        or snapshot.source_id != work.source_id
        or snapshot.http_status != 200
        or canonical_source_listing_identity("snkrdunk", snapshot.source_url)
        != cursor.get("product_identity")
        or not attempt.started_at <= snapshot.fetched_at <= attempt.finished_at
        or budget.reserved_requests != 0
        or attempt.actual_request_cost != sum(attempt.request_costs)
        or attempt.actual_request_cost != attempt.charged_request_cost
    ):
        raise ValueError("settled explicit network repair proof required")
    now = require_utc(clock())
    if not attempt.finished_at <= now <= attempt.finished_at + timedelta(minutes=5):
        raise ValueError("network recovery evidence is no longer current")
    refresh = db.scalar(
        select(FreshnessWork)
        .where(
            FreshnessWork.source_id == work.source_id,
            FreshnessWork.kind == "refresh",
            FreshnessWork.source_card_mapping_id == cursor["mapping_id"],
        )
        .with_for_update()
    )
    if (
        refresh is None
        or refresh.state == "claimed"
        or refresh.claim_token is not None
        or refresh.card_print_id != cursor["card_print_id"]
        or refresh.product_identity != cursor["product_identity"]
    ):
        raise ValueError("unchanged settled mapping work required for quarantine")
    refresh.state = "blocked"
    refresh.last_failure = "Explicit current product capture: artwork unavailable; identity remains unverified"
    refresh.last_failure_at = now
    refresh.resume_cursor = {
        **(refresh.resume_cursor or {}),
        "identity_quarantine_snapshot_id": snapshot.id,
        "identity_quarantine_recovery_work_id": work.id,
    }
    work.resume_cursor = {**cursor, "quarantined_refresh_work_id": refresh.id}
    budget.pause_reason, budget.paused_until = None, None
    db.flush()
    return work


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
