"""Explicit raw-only planner used by the staging rollout; never enables budgets."""

from sqlalchemy import select

from app.models import (
    CardPrint,
    FreshnessPriceState,
    FreshnessWork,
    PriceObservation,
    RawSnapshot,
    Source,
    SourceCardMapping,
)
from app.services.freshness_policy import FreshnessPolicy
from app.services.freshness_queue import PriceCategory, plan_refresh


def seed_raw_work(session, *, request_bounds, quarantine_mapping_ids=()):
    """Idempotently represent eligible mappings without inventing successful checks.

    Existing claims, deadlines, retries, interest and quarantine remain intact.
    Historical accepted captures may initialize a NEW work row only. Raw sale
    observations remain internal evidence; this changes no public price reader.
    """
    if set(request_bounds) != {"yuyutei", "snkrdunk"} or any(
        type(v) is not int or v < 1 for v in request_bounds.values()
    ):
        raise ValueError("explicit positive request bounds required for both sources")
    if (
        session.scalar(
            select(FreshnessPriceState.id)
            .where(FreshnessPriceState.price_category != "raw")
            .limit(1)
        )
        is not None
    ):
        raise ValueError("non-raw demand requires separate reconciliation")
    existing = {
        w.source_card_mapping_id: w
        for w in session.scalars(
            select(FreshnessWork).where(FreshnessWork.kind == "refresh")
        )
    }
    mappings = session.execute(
        select(SourceCardMapping, Source.name)
        .join(Source, Source.id == SourceCardMapping.source_id)
        .join(CardPrint, CardPrint.id == SourceCardMapping.card_print_id)
        .where(
            Source.name.in_(request_bounds),
            SourceCardMapping.is_active.is_(True),
            SourceCardMapping.superseded_at.is_(None),
            SourceCardMapping.review_status == "approved",
            CardPrint.is_active.is_(True),
            CardPrint.verification_status == "verified",
        )
        .order_by(SourceCardMapping.id)
    ).all()
    latest = {
        o.source_card_mapping_id: o
        for o in session.scalars(
            select(PriceObservation)
            .where(PriceObservation.price_type.in_(["sell", "floor"]))
            .distinct(PriceObservation.source_card_mapping_id)
            .order_by(
                PriceObservation.source_card_mapping_id,
                PriceObservation.observed_at.desc(),
                PriceObservation.id.desc(),
            )
        )
    }
    policy = FreshnessPolicy()
    counts = {
        "represented": 0,
        "created": 0,
        "initialized_from_capture": 0,
        "blocked": 0,
    }
    for mapping, source in mappings:
        if source == "snkrdunk" and not mapping.manual_verified:
            continue
        previous = existing.get(mapping.id)
        work = plan_refresh(
            session,
            mapping.id,
            {"raw": PriceCategory("sell" if source == "yuyutei" else "floor")},
            high_interest=previous.high_interest if previous else False,
            estimated_request_cost=request_bounds[source],
        )
        counts["represented"] += 1
        if previous is None:
            counts["created"] += 1
            obs = latest.get(mapping.id)
            snapshot = (
                session.get(RawSnapshot, obs.raw_snapshot_id)
                if obs and obs.raw_snapshot_id
                else None
            )
            if (
                obs
                and snapshot
                and snapshot.http_status == 200
                and obs.card_print_id == mapping.card_print_id
                and obs.source_id == snapshot.source_id == mapping.source_id
                and snapshot.fetched_at <= obs.observed_at
            ):
                state = session.scalar(
                    select(FreshnessPriceState).where(
                        FreshnessPriceState.work_id == work.id,
                        FreshnessPriceState.price_category == "raw",
                    )
                )
                checked = snapshot.fetched_at
                state.last_successfully_checked_at = checked
                state.last_valid_price_observed_at = obs.observed_at
                state.last_observation_id = obs.id
                state.availability = "listed"
                state.next_due_at = policy.next_due(
                    checked, high_interest=work.high_interest
                )
                work.last_successfully_checked_at = checked
                work.next_due_at = state.next_due_at
                work.lane = "high" if work.high_interest else "ordinary"
                counts["initialized_from_capture"] += 1
        if mapping.id in quarantine_mapping_ids and work.state != "claimed":
            work.state = "blocked"
            work.last_failure = "Existing confirmed identity-validation refusal; explicit review required"
            counts["blocked"] += 1
    session.flush()
    return counts
