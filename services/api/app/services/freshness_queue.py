"""Opt-in PostgreSQL planning, claiming and source admission.

Each public call belongs in a short caller-owned transaction. Commit before
network I/O. Admit each request before dispatch; write results and complete in
one transaction. Only explicit opt-in adapters call this module.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
from uuid import uuid4

from opcg_source_identity import canonical_source_listing_identity
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    CardPrint,
    FreshnessAttempt,
    FreshnessPriceState,
    FreshnessWork,
    PriceObservation,
    RawSnapshot,
    Source,
    SourceCardMapping,
    SourceDispatchBudget,
)
from app.services.freshness_policy import (
    LANE_CYCLE,
    FreshnessPolicy,
    UTCClock,
    require_utc,
    utc_now,
)

OUTCOMES = frozenset(
    {
        "captured",
        "no_listing",
        "identity_refusal",
        "transient_failure",
        "source_denial",
        "discovery_progress",
        "completed",
    }
)
SUCCESS = frozenset({"captured", "no_listing", "discovery_progress", "completed"})


@dataclass(frozen=True)
class PriceCategory:
    """Existing writer's evidence signature; this does not define grade semantics."""

    price_type: str
    condition_label: str | None = None


@dataclass(frozen=True)
class Claim:
    work_id: int
    claim_token: str
    expires_at: datetime
    kind: str
    source_card_mapping_id: int | None
    card_print_id: int | None
    scope_key: str | None
    resume_cursor: dict | None
    price_categories: tuple[str, ...]
    reserved_request_cost: int


def _eligible_mapping(db: Session, mapping_id: int) -> SourceCardMapping:
    # Mirrors the existing approved collection gates. It does not replace the
    # collector's own identity/artwork verification before writing prices.
    row = db.execute(
        select(SourceCardMapping, Source.name)
        .join(
            Source,
            Source.id == SourceCardMapping.source_id,
        )
        .join(CardPrint, CardPrint.id == SourceCardMapping.card_print_id)
        .where(
            SourceCardMapping.id == mapping_id,
            SourceCardMapping.is_active.is_(True),
            SourceCardMapping.superseded_at.is_(None),
            SourceCardMapping.review_status == "approved",
            CardPrint.is_active.is_(True),
            CardPrint.verification_status == "verified",
        )
        .execution_options(populate_existing=True)
    ).one_or_none()
    if row is None or (row[1] == "snkrdunk" and not row[0].manual_verified):
        raise ValueError("refresh requires a current approved exact-print mapping")
    mapping, source_name = row
    identity = canonical_source_listing_identity(source_name, mapping.source_url)
    if not identity or identity != mapping.canonical_source_listing_identity:
        raise ValueError(
            "refresh requires established canonical source-product identity"
        )
    return mapping


def _upsert_work(
    db: Session,
    *,
    key: str,
    kind: str,
    source_id: int,
    due: datetime,
    lane: str,
    priority: int,
    cost: int,
    mapping: SourceCardMapping | None = None,
    print_id: int | None = None,
    scope: str | None = None,
    policy: FreshnessPolicy = FreshnessPolicy(),
) -> FreshnessWork:
    if type(cost) is not int or cost < 1 or not 0 <= priority <= 100:
        raise ValueError("cost must be positive and priority in 0..100")
    db.execute(
        insert(FreshnessWork)
        .values(
            work_key=key,
            kind=kind,
            source_id=source_id,
            product_identity=(
                mapping.canonical_source_listing_identity if mapping else None
            ),
            source_card_mapping_id=mapping.id if mapping else None,
            card_print_id=mapping.card_print_id if mapping else print_id,
            scope_key=scope,
            next_due_at=due,
            lane=lane,
            priority=priority,
            estimated_request_cost=cost,
            state="pending",
            attempt_count=0,
            last_claim_sequence=0,
            high_interest=False,
            policy_version=policy.version,
            execution_headroom_seconds=int(policy.headroom.total_seconds()),
        )
        .on_conflict_do_nothing(index_elements=[FreshnessWork.work_key])
    )
    work = db.scalar(
        select(FreshnessWork)
        .where(FreshnessWork.work_key == key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert work is not None
    if work.policy_version != policy.version:
        raise ValueError("unsupported work freshness policy version")
    if mapping and (
        work.source_card_mapping_id != mapping.id
        or work.card_print_id != mapping.card_print_id
    ):
        raise ValueError(
            "product mapping changed; explicit lineage reconciliation required"
        )
    # Replaying a plan must not reset completed progress, a retry delay, or an
    # active claim. Earlier recheck demand is represented by a new category.
    work.priority = max(work.priority, priority)
    work.estimated_request_cost = max(work.estimated_request_cost, cost)
    db.flush()
    return work


def _refresh_retry_gate(work: FreshnessWork, states: list[FreshnessPriceState]) -> None:
    """Keep evidence deadlines visible; dispatch when ANY category is eligible."""
    work.next_due_at = min(require_utc(s.next_due_at) for s in states)
    work.retry_not_before_at = (
        min(
            (
                max(require_utc(s.next_due_at), require_utc(s.retry_not_before_at))
                if s.retry_not_before_at is not None
                else require_utc(s.next_due_at)
            )
            for s in states
        )
        if any(s.retry_not_before_at is not None for s in states)
        else None
    )


def plan_refresh(
    db: Session,
    mapping_id: int,
    price_categories: set[str] | dict[str, PriceCategory],
    *,
    high_interest: bool,
    policy: FreshnessPolicy = FreshnessPolicy(),
    clock: UTCClock = utc_now,
    estimated_request_cost: int = 1,
) -> FreshnessWork:
    if not price_categories or any(not c or len(c) > 32 for c in price_categories):
        raise ValueError("current-price categories required")
    contracts = (
        {category: PriceCategory(category) for category in price_categories}
        if isinstance(price_categories, set)
        else price_categories
    )
    if any(
        not c.price_type
        or len(c.price_type) > 32
        or (c.condition_label is not None and len(c.condition_label) > 64)
        for c in contracts.values()
    ):
        raise ValueError("bounded price evidence signature required")
    mapping = _eligible_mapping(db, mapping_id)
    identity_hash = hashlib.sha256(
        mapping.canonical_source_listing_identity.encode()
    ).hexdigest()
    now = require_utc(clock())
    work = _upsert_work(
        db,
        key=f"refresh:{mapping.source_id}:{identity_hash}",
        kind="refresh",
        source_id=mapping.source_id,
        due=now,
        lane="coverage",
        priority=100 if high_interest else 50,
        cost=estimated_request_cost,
        mapping=mapping,
        policy=policy,
    )
    work.high_interest = (
        high_interest  # authoritative product signal, shared by all categories
    )
    work.priority = 100 if high_interest else 50
    work.policy_version = policy.version
    work.execution_headroom_seconds = int(policy.headroom.total_seconds())
    db.flush()
    for category in sorted(price_categories):
        db.execute(
            insert(FreshnessPriceState)
            .values(
                work_id=work.id,
                price_category=category,
                price_type=contracts[category].price_type,
                condition_label=contracts[category].condition_label,
                next_due_at=now,
                availability="unknown",
            )
            .on_conflict_do_nothing(
                index_elements=[
                    FreshnessPriceState.work_id,
                    FreshnessPriceState.price_category,
                ]
            )
        )
    states = db.scalars(
        select(FreshnessPriceState)
        .where(FreshnessPriceState.work_id == work.id)
        .with_for_update()
    ).all()
    for state in states:
        contract = contracts.get(state.price_category)
        if contract and (state.price_type, state.condition_label) != (
            contract.price_type,
            contract.condition_label,
        ):
            raise ValueError(
                "category evidence signature requires explicit reconciliation"
            )
        due = policy.next_due(
            state.last_successfully_checked_at,
            high_interest=high_interest,
            clock=lambda: now,
        )
        # A priority escalation can bring due work forward; planning never
        # relaxes an outstanding deadline because capacity is insufficient.
        state.next_due_at = min(require_utc(state.next_due_at), due)
        if state.retry_not_before_at is not None:
            # Interest escalation also bounds an existing retry; planning never
            # pushes it later, clears its streak, or changes evidence freshness.
            state.retry_not_before_at = min(
                require_utc(state.retry_not_before_at),
                now
                + policy.retry_interval(
                    absent=True, consecutive_failures=0, high_interest=high_interest
                ),
            )
    _refresh_retry_gate(work, states)
    work.lane = (
        "coverage"
        if work.last_successfully_checked_at is None
        else "high" if high_interest else "ordinary"
    )
    db.flush()
    return work


def _plan_scope(
    db: Session,
    source_id: int,
    scope_key: str,
    kind: str,
    due_at: datetime,
    priority: int,
    estimated_request_cost: int,
) -> FreshnessWork:
    if not scope_key or len(scope_key) > 160:
        raise ValueError("bounded source scope key required")
    return _upsert_work(
        db,
        key=f"{kind}:{source_id}:{scope_key}",
        kind=kind,
        source_id=source_id,
        due=require_utc(due_at),
        lane="discovery",
        priority=priority,
        cost=estimated_request_cost,
        scope=scope_key,
    )


def plan_discovery_scope(
    db: Session,
    source_id: int,
    scope_key: str,
    *,
    due_at: datetime,
    priority: int = 0,
    estimated_request_cost: int = 1,
) -> FreshnessWork:
    return _plan_scope(
        db, source_id, scope_key, "discovery", due_at, priority, estimated_request_cost
    )


def plan_validation(
    db: Session,
    source_id: int,
    scope_key: str,
    *,
    due_at: datetime,
    estimated_request_cost: int = 1,
) -> FreshnessWork:
    return _plan_scope(
        db, source_id, scope_key, "validation", due_at, 10, estimated_request_cost
    )


def plan_print_discovery(
    db: Session,
    source_id: int,
    card_print_id: int,
    *,
    due_at: datetime,
    estimated_request_cost: int = 1,
) -> FreshnessWork:
    return _upsert_work(
        db,
        key=f"print:{source_id}:{card_print_id}",
        kind="print_discovery",
        source_id=source_id,
        due=require_utc(due_at),
        lane="coverage",
        priority=20,
        cost=estimated_request_cost,
        print_id=card_print_id,
    )


def _budget(db: Session, source_id: int) -> SourceDispatchBudget:
    budget = db.scalar(
        select(SourceDispatchBudget)
        .where(SourceDispatchBudget.source_id == source_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if budget is None:
        raise ValueError("source request limit is unconfigured; dispatch refused")
    return budget


def _source_open(budget: SourceDispatchBudget, now: datetime) -> bool:
    if not budget.enabled:
        return False
    if budget.paused_until is not None:
        return require_utc(budget.paused_until) <= now
    return budget.pause_reason is None


def _roll_window(budget: SourceDispatchBudget, now: datetime) -> None:
    elapsed = (now - require_utc(budget.window_started_at)).total_seconds()
    if elapsed >= budget.window_seconds:
        windows = int(elapsed // budget.window_seconds)
        budget.window_started_at += timedelta(seconds=windows * budget.window_seconds)
        budget.used_requests = 0
        # Outstanding reservations survive a window boundary.


def _clear_claim(work: FreshnessWork, now: datetime, *, state: str = "pending") -> None:
    work.state = state
    work.claim_token = work.claimed_by = work.claimed_at = work.claim_expires_at = None
    work.updated_at = now


def _recover_expired(db: Session, budget: SourceDispatchBudget, now: datetime) -> None:
    # Bounded so a large crash backlog cannot create an unbounded transaction.
    expired = db.scalars(
        select(FreshnessWork)
        .where(
            FreshnessWork.source_id == budget.source_id,
            FreshnessWork.state == "claimed",
            FreshnessWork.claim_expires_at <= now,
        )
        .order_by(FreshnessWork.claim_expires_at, FreshnessWork.id)
        .limit(100)
        .with_for_update(skip_locked=True)
    ).all()
    for work in expired:
        attempt = db.scalar(
            select(FreshnessAttempt)
            .where(FreshnessAttempt.claim_token == work.claim_token)
            .with_for_update()
        )
        assert attempt is not None and attempt.outcome is None
        budget.reserved_requests -= attempt.reserved_request_cost
        budget.used_requests += attempt.reserved_request_cost
        attempt.charged_request_cost = attempt.reserved_request_cost
        # Unknown actual cost remains NULL, never reported as a measurement.
        attempt.outcome = "expired"
        attempt.finished_at = now
        _clear_claim(work, now)
        work.last_outcome = "expired"
        work.last_failure = "claim expired; full reservation charged conservatively"
        work.last_failure_at = now
    db.flush()


def claim_due(
    db: Session,
    source_id: int,
    owner: str,
    *,
    limit: int,
    lease: timedelta,
    clock: UTCClock = utc_now,
    yuyutei_shard_index: int | None = None,
    supported_kinds: set[str] | None = None,
) -> list[Claim]:
    """Reserve a processing chunk. The next chunk can be claimed immediately."""
    if not owner or len(owner) > 128 or not 1 <= limit <= 100 or lease <= timedelta(0):
        raise ValueError("invalid owner, batch size or lease")
    if yuyutei_shard_index is not None:
        if (
            not 0 <= yuyutei_shard_index < 9
            or db.scalar(select(Source.name).where(Source.id == source_id)) != "yuyutei"
        ):
            raise ValueError("routing requires an existing Yuyu shard index in 0..8")
    budget = _budget(db, source_id)
    now = require_utc(clock())
    _roll_window(budget, now)
    _recover_expired(db, budget, now)
    if not _source_open(budget, now):
        return []
    claims: list[Claim] = []
    for _ in range(limit):
        remaining = (
            budget.request_limit - budget.used_requests - budget.reserved_requests
        )
        if remaining <= 0:
            break
        base = select(FreshnessWork).where(
            FreshnessWork.source_id == source_id,
            FreshnessWork.state == "pending",
            FreshnessWork.next_due_at <= now,
            FreshnessWork.estimated_request_cost <= remaining,
            or_(
                FreshnessWork.retry_not_before_at.is_(None),
                FreshnessWork.retry_not_before_at <= now,
            ),
        )
        if yuyutei_shard_index is not None:
            # Shards run at different cron times. Another shard's overdue
            # refresh lane must not strand this shard's coverage work until
            # tomorrow. Keep non-refresh lanes visible for shared fairness.
            base = base.where(
                or_(
                    FreshnessWork.kind != "refresh",
                    FreshnessWork.source_card_mapping_id % 9 == yuyutei_shard_index,
                )
            )
        base = (
            base.order_by(
                FreshnessWork.next_due_at,
                FreshnessWork.last_claim_sequence,
                FreshnessWork.priority.desc(),
                FreshnessWork.id,
            )
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        lane = LANE_CYCLE[budget.claim_sequence % len(LANE_CYCLE)]
        work = db.scalar(base.where(FreshnessWork.lane == lane)) or db.scalar(base)
        if work is None:
            break
        # Yield the source-wide lane to its responsible consumer. Filtering
        # before lane selection would silently steal discovery's fair turn.
        if supported_kinds is not None and work.kind not in supported_kinds:
            break
        if (
            yuyutei_shard_index is not None
            and work.kind != "refresh"
            and supported_kinds is None
        ):
            break  # shard consumers must explicitly opt in to discovery
        if yuyutei_shard_index is not None and work.kind == "refresh":
            # A shard may take its own work from the selected source-wide
            # lane, but cannot consume a discovery/coverage turn as refresh.
            # Yield to the appropriate existing worker when it cannot serve
            # that lane; never advance the shared fairness cursor on refusal.
            work = db.scalar(
                base.where(
                    FreshnessWork.lane == work.lane,
                    FreshnessWork.kind == "refresh",
                    FreshnessWork.source_card_mapping_id % 9 == yuyutei_shard_index,
                )
            )
            if work is None:
                break
        if work.kind == "refresh":
            try:
                mapping = _eligible_mapping(db, work.source_card_mapping_id)
                if (
                    mapping.card_print_id != work.card_print_id
                    or mapping.canonical_source_listing_identity
                    != work.product_identity
                ):
                    raise ValueError("planned mapping lineage changed")
            except ValueError as exc:
                work.state = "blocked"
                work.last_failure, work.last_failure_at = str(exc), now
                db.flush()
                continue
        if work.policy_version != FreshnessPolicy.version:
            raise ValueError("unsupported work freshness policy version")
        token = str(uuid4())
        work.state, work.claim_token, work.claimed_by = "claimed", token, owner
        work.claimed_at, work.claim_expires_at = now, now + lease
        work.attempt_count += 1
        budget.reserved_requests += work.estimated_request_cost
        budget.claim_sequence += 1
        work.last_claim_sequence = budget.claim_sequence
        work.updated_at = now
        db.add(
            FreshnessAttempt(
                work_id=work.id,
                claim_token=token,
                claimed_by=owner,
                claimed_at=now,
                reserved_request_cost=work.estimated_request_cost,
                request_costs=[],
            )
        )
        categories = tuple(
            db.scalars(
                select(FreshnessPriceState.price_category)
                .where(FreshnessPriceState.work_id == work.id)
                .order_by(FreshnessPriceState.price_category)
            )
        )
        claims.append(
            Claim(
                work.id,
                token,
                now + lease,
                work.kind,
                work.source_card_mapping_id,
                work.card_print_id,
                work.scope_key,
                deepcopy(work.resume_cursor),
                categories,
                work.estimated_request_cost,
            )
        )
        db.flush()
    return claims


def _locked_claim(
    db: Session, token: str
) -> tuple[SourceDispatchBudget, FreshnessWork, FreshnessAttempt]:
    identity = db.execute(
        select(FreshnessAttempt.work_id, FreshnessWork.source_id)
        .join(FreshnessWork, FreshnessWork.id == FreshnessAttempt.work_id)
        .where(FreshnessAttempt.claim_token == token)
    ).one_or_none()
    if identity is None:
        raise ValueError("unknown claim token")
    budget = _budget(db, identity.source_id)
    work = db.scalar(
        select(FreshnessWork)
        .where(FreshnessWork.id == identity.work_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    attempt = db.scalar(
        select(FreshnessAttempt)
        .where(FreshnessAttempt.claim_token == token)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return budget, work, attempt


def _require_owner(
    work: FreshnessWork, attempt: FreshnessAttempt, now: datetime
) -> None:
    if (
        attempt.outcome is not None
        or work.state != "claimed"
        or work.claim_token != attempt.claim_token
        or require_utc(work.claim_expires_at) <= now
    ):
        raise ValueError("claim ownership expired or replaced")


def lock_for_result(db: Session, token: str, *, clock: UTCClock = utc_now) -> bool:
    """Fence domain writes in the same short transaction as complete_claim.

    False means this delivery already completed: skip the domain writer.
    Keep these locks only for database writes, never for fetching or parsing.
    """
    _, work, attempt = _locked_claim(db, token)
    if attempt.outcome is not None and attempt.outcome != "expired":
        return False
    _require_owner(work, attempt, require_utc(clock()))
    return True


def admit_request(
    db: Session, token: str, *, ordinal: int, cost: int = 1, clock: UTCClock = utc_now
) -> bool:
    """Call before EACH source request, including canaries and validation.

    The same ordinal returns False on replay, so it must not dispatch twice.
    A grant is permission for one bounded request, not a retry permission.
    """
    if type(cost) is not int or cost < 1 or type(ordinal) is not int or ordinal < 1:
        raise ValueError("positive integer request ordinal and cost required")
    budget, work, attempt = _locked_claim(db, token)
    now = require_utc(clock())
    _require_owner(work, attempt, now)
    if not _source_open(budget, now):
        raise ValueError("source paused or disabled; dispatch refused")
    if work.kind == "refresh":
        mapping = _eligible_mapping(db, work.source_card_mapping_id)
        if (
            mapping.card_print_id != work.card_print_id
            or mapping.canonical_source_listing_identity != work.product_identity
        ):
            raise ValueError("planned mapping lineage changed")
    costs = attempt.request_costs
    if ordinal <= len(costs):
        if costs[ordinal - 1] != cost:
            raise ValueError("request ordinal reused with a different cost")
        return False
    if ordinal != len(costs) + 1 or sum(costs) + cost > attempt.reserved_request_cost:
        raise ValueError("request exceeds the reserved upper bound or skips an ordinal")
    attempt.request_costs = costs + [cost]
    if attempt.started_at is None:
        attempt.started_at = now
        work.last_attempted_at = now
    db.flush()
    return True


def _result_digest(**payload) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def pause_source(db: Session, token: str, *, clock: UTCClock = utc_now) -> None:
    """Stop subsequent requests immediately, including helper-page denials."""
    budget, work, attempt = _locked_claim(db, token)
    _require_owner(work, attempt, require_utc(clock()))
    budget.pause_reason, budget.paused_until = "source_denial", None
    db.flush()


def _signature_matches(category, signature, observation):
    actual = (observation.price_type, observation.condition_label)
    # SNKRDUNK's established raw floor writer retains the winning A-D label.
    # A raw wildcard must never accept PSA/BGS/ARS observations.
    if category == "raw" and signature == ("floor", None):
        return actual[0] == "floor" and actual[1] in {None, "A", "B", "C", "D"}
    return actual == signature


def complete_claim(
    db: Session,
    token: str,
    *,
    outcome: str,
    actual_request_cost: int,
    raw_snapshot_id: int | None = None,
    observation_ids: dict[str, int] | None = None,
    no_listing_categories: set[str] | None = None,
    category_outcomes: dict[str, str] | None = None,
    resume_cursor: dict | None = None,
    next_due_at: datetime | None = None,
    failure: str | None = None,
    retry_delay: timedelta = timedelta(minutes=15),
    clock: UTCClock = utc_now,
) -> bool:
    """Validate evidence and complete atomically with the adapter's result writes.

    Replayed identical results are harmless. Expired owners and conflicting
    deliveries cannot mutate the current job. Raw evidence is already durable
    before parsing; producers must roll back result writes on any refusal.
    """
    if (
        outcome not in OUTCOMES
        or type(actual_request_cost) is not int
        or actual_request_cost < 0
        or retry_delay <= timedelta(0)
    ):
        raise ValueError("invalid outcome, cost or retry delay")
    observed_ids, unlisted = observation_ids or {}, no_listing_categories or set()
    if set(observed_ids) & unlisted:
        raise ValueError("a category cannot be both priced and unlisted")
    category_results = category_outcomes or {}
    if any(
        value not in {"captured", "no_listing", "absent", "parsing_failure"}
        for value in category_results.values()
    ):
        raise ValueError("invalid category outcome")
    if any(
        (value == "captured" and key not in observed_ids)
        or (value == "no_listing" and key not in unlisted)
        or (
            value in {"absent", "parsing_failure"}
            and key in set(observed_ids) | unlisted
        )
        for key, value in category_results.items()
    ):
        raise ValueError("category outcome conflicts with evidence")
    due = require_utc(next_due_at) if next_due_at else None
    digest = _result_digest(
        outcome=outcome,
        category_outcomes=category_results,
        actual_request_cost=actual_request_cost,
        raw_snapshot_id=raw_snapshot_id,
        observation_ids=observed_ids,
        no_listing_categories=sorted(unlisted),
        resume_cursor=resume_cursor,
        next_due_at=due.isoformat() if due else None,
        failure=failure,
        retry_seconds=retry_delay.total_seconds(),
    )
    budget, work, attempt = _locked_claim(db, token)
    now = require_utc(clock())
    if attempt.outcome is not None and attempt.outcome != "expired":
        if attempt.result_digest == digest:
            return False
        raise ValueError("conflicting result for completed claim")
    _require_owner(work, attempt, now)
    if attempt.started_at is None and (outcome in SUCCESS or actual_request_cost):
        raise ValueError("source requests must be admitted before completion")
    if work.policy_version != FreshnessPolicy.version:
        raise ValueError("unsupported work freshness policy version")
    policy = FreshnessPolicy(
        headroom=timedelta(seconds=work.execution_headroom_seconds)
    )
    snapshot = (
        db.get(RawSnapshot, raw_snapshot_id) if raw_snapshot_id is not None else None
    )
    if raw_snapshot_id is not None:
        if (
            snapshot is None
            or snapshot.source_id != work.source_id
            or attempt.started_at is None
            or not require_utc(attempt.started_at)
            <= require_utc(snapshot.fetched_at)
            <= now
        ):
            raise ValueError("check requires a new source raw snapshot")
        if db.scalar(
            select(FreshnessAttempt.id).where(
                FreshnessAttempt.raw_snapshot_id == raw_snapshot_id,
                FreshnessAttempt.id != attempt.id,
            )
        ):
            raise ValueError("saved evidence cannot reaffirm a new check")
    has_absence = "absent" in category_results.values()
    if (outcome in SUCCESS or has_absence) and (
        snapshot is None or not 200 <= snapshot.http_status < 300
    ):
        raise ValueError("successful check requires a new successful source capture")
    if outcome == "captured" and (work.kind != "refresh" or not observed_ids):
        raise ValueError("capture requires current refresh observations")
    if outcome != "captured" and observed_ids:
        raise ValueError("only capture may attach observations")
    if work.kind == "refresh":
        if outcome in {"completed", "discovery_progress"} or resume_cursor is not None:
            raise ValueError("refresh cannot complete discovery progress")
        if outcome == "no_listing" and not unlisted:
            raise ValueError("no-listing categories must be explicit")
    elif observed_ids or unlisted:
        raise ValueError(
            "discovery and validation cannot claim approved price evidence"
        )
    if unlisted and outcome not in {"captured", "no_listing"}:
        raise ValueError("failed checks cannot change availability")
    if resume_cursor is not None and (
        not isinstance(resume_cursor, dict)
        or type(resume_cursor.get("version")) is not int
        or resume_cursor["version"] < 1
    ):
        raise ValueError("resume cursor must carry a positive version")
    if outcome == "discovery_progress" and resume_cursor is None:
        raise ValueError("resumable progress requires a cursor")
    if (
        work.kind != "refresh"
        and outcome in {"completed", "no_listing"}
        and (due is None or due <= now)
    ):
        raise ValueError("completed discovery requires a future due time")
    states = db.scalars(
        select(FreshnessPriceState)
        .where(FreshnessPriceState.work_id == work.id)
        .with_for_update()
    ).all()
    if not (set(observed_ids) | unlisted | set(category_results)) <= {
        s.price_category for s in states
    }:
        raise ValueError("result contains an unplanned price category")
    observed: dict[str, PriceObservation] = {}
    signatures = {
        state.price_category: (state.price_type, state.condition_label)
        for state in states
    }
    if work.kind == "refresh" and (outcome in SUCCESS or has_absence):
        mapping = _eligible_mapping(db, work.source_card_mapping_id)
        source_name = db.scalar(select(Source.name).where(Source.id == work.source_id))
        if (
            mapping.card_print_id != work.card_print_id
            or mapping.canonical_source_listing_identity != work.product_identity
        ):
            raise ValueError("planned mapping lineage changed")
        if (
            canonical_source_listing_identity(source_name, snapshot.source_url)
            != work.product_identity
        ):
            raise ValueError("capture does not identify the planned source product")
    if outcome == "captured":
        for category, observation_id in observed_ids.items():
            obs = db.get(PriceObservation, observation_id)
            if (
                obs is None
                or obs.source_id != work.source_id
                or obs.source_card_mapping_id != work.source_card_mapping_id
                or obs.card_print_id != work.card_print_id
                or not _signature_matches(category, signatures[category], obs)
                or obs.raw_snapshot_id != raw_snapshot_id
                or not require_utc(snapshot.fetched_at)
                <= require_utc(obs.observed_at)
                <= now
            ):
                raise ValueError(
                    "observation is not from this new current product capture"
                )
            observed[category] = obs
    # All validation precedes mutation, so a refused result cannot partly settle
    # its reservation if a caller handles the exception within its transaction.
    _roll_window(budget, now)
    budget.reserved_requests -= attempt.reserved_request_cost
    budget.used_requests += actual_request_cost
    attempt.actual_request_cost = attempt.charged_request_cost = actual_request_cost
    attempt.raw_snapshot_id = raw_snapshot_id
    attempt.category_outcomes = category_results
    attempt.finished_at, attempt.outcome, attempt.result_digest = now, outcome, digest
    _clear_claim(
        work, now, state="blocked" if outcome == "identity_refusal" else "pending"
    )
    work.last_outcome = outcome
    if outcome in SUCCESS:
        checked_at = require_utc(snapshot.fetched_at)
        work.last_successfully_checked_at = checked_at
        work.retry_not_before_at = None
        if resume_cursor is not None:
            work.resume_cursor = deepcopy(resume_cursor)
        if work.kind == "refresh":
            for state in states:
                if (
                    state.price_category not in observed
                    and state.price_category not in unlisted
                ):
                    continue  # partial capture/new demand remains due
                state.last_successfully_checked_at = checked_at
                obs = observed.get(state.price_category)
                state.availability = "listed" if obs else "no_listing"
                if obs is not None:
                    # Capture time, never parse/recalculation/publication time.
                    state.last_valid_price_observed_at = checked_at
                    state.last_observation_id = obs.id
                state.next_due_at = policy.next_due(
                    checked_at, high_interest=work.high_interest
                )
            work.lane = "high" if work.high_interest else "ordinary"
        else:
            work.next_due_at = now if outcome == "discovery_progress" else due
    else:
        work.last_failure, work.last_failure_at = (failure or outcome)[:500], now
        # Preserve the overdue deadline; the retry gate is a separate fact.
        work.retry_not_before_at = now + retry_delay
    if work.kind == "refresh" and (
        outcome in SUCCESS or outcome == "transient_failure"
    ):
        for state in states:
            category = state.price_category
            if category in observed or category in unlisted:
                state.consecutive_failures = 0
                state.retry_not_before_at = None
                continue
            result = category_results.get(category)
            if result == "absent":
                # Confident absence resolves parsing uncertainty, not an old
                # price or availability. Keep its original evidence deadline.
                state.consecutive_failures = 0
            elif result == "parsing_failure" or outcome == "transient_failure":
                state.consecutive_failures = min(
                    (state.consecutive_failures or 0) + 1, 8
                )
            else:
                continue  # omitted/new demand retains its own due time and streak
            state.retry_not_before_at = now + policy.retry_interval(
                absent=result == "absent",
                consecutive_failures=state.consecutive_failures,
                high_interest=work.high_interest,
            )
        _refresh_retry_gate(work, states)
    if outcome == "source_denial":
        budget.pause_reason, budget.paused_until = "source_denial", None
    elif actual_request_cost > sum(attempt.request_costs):
        # Never hide an adapter's actual overrun. Account for it, then fail
        # closed until an operator reconciles the source limits.
        budget.pause_reason, budget.paused_until = "request_cost_overrun", None
    db.flush()
    return True
