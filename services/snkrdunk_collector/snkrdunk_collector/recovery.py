"""Explicit singleton, one-shot source recovery. No automatic retry or unpause."""

import argparse
import json
import os
from sqlalchemy import select
from app.models import FreshnessWork
from app.services.freshness_policy import utc_now
from app.services.freshness_integration import Attempt, CaptureResult
from app.services.source_recovery import (
    claim_source_recovery,
    resume_after_recovery,
    resume_after_network_recovery,
)
from snkrdunk_collector.db import SessionLocal
from snkrdunk_collector.run_lock import (
    collection_lock,
    pinned_session,
    assert_lock_owned,
)


def run_recovery(
    source_id,
    mapping_id,
    denial_attempt_id,
    *,
    request_bound=600,
    session_factory=SessionLocal,
    runner=None,
    lock_factory=collection_lock,
):
    from snkrdunk_collector.collect import run_one_mapping_detailed

    with session_factory() as probe:
        engine = probe.get_bind()
    with lock_factory(engine) as lock:
        if not lock.acquired:
            return {"status": "singleton_contended", "resumed": False}
        with pinned_session(lock, session_factory) as session:
            return consume_recovery(
                session,
                source_id,
                mapping_id,
                denial_attempt_id,
                request_bound=request_bound,
                runner=runner,
            )


def consume_recovery(
    session,
    source_id,
    mapping_id,
    denial_attempt_id,
    *,
    request_bound=600,
    runner=None,
    owner="snkrdunk-explicit-recovery",
    network_repair_of=None,
):
    from snkrdunk_collector.collect import run_one_mapping_detailed

    assert_lock_owned(session)
    claim = claim_source_recovery(
        session,
        source_id,
        mapping_id,
        denial_attempt_id,
        owner,
        request_bound=request_bound,
        network_repair_of=network_repair_of,
    )
    session.commit()
    if claim is None:
        return {"status": "recovery_not_admitted", "resumed": False}
    attempt = Attempt(session, claim, ownership_check=assert_lock_owned)
    try:
        (runner or run_one_mapping_detailed)(
            session, mapping_id, validate_only=True, freshness=attempt
        )
    except Exception as exc:
        session.rollback()
        attempt.result = CaptureResult(
            "source_denial" if attempt.denied else "transient_failure",
            raw_snapshot_id=attempt.raw_snapshot_id,
            failure=type(exc).__name__,
        )
    if attempt.result is None:
        attempt.result = CaptureResult(
            "source_denial" if attempt.denied else "transient_failure",
            raw_snapshot_id=attempt.raw_snapshot_id,
            failure="required product evidence unavailable",
        )
    settled = attempt.finish(attempt.result)
    resumed = False
    if settled and attempt.result.outcome == "completed":
        assert_lock_owned(session)
        if (attempt.result.resume_cursor or {}).get("source_access_verified"):
            resume_after_network_recovery(session, claim.claim_token)
        else:
            resume_after_recovery(session, claim.claim_token)
        assert_lock_owned(session)
        session.commit()
        resumed = True
    return {
        "status": attempt.result.outcome,
        "resumed": resumed,
        "work_id": claim.work_id,
        "request_cost": attempt.charged_cost,
        "product_snapshot_id": attempt.raw_snapshot_id,
        "failure_counts": dict(attempt.health),
    }


def main():
    if (
        os.environ.get("RAILWAY_PROJECT_ID") != "c613898d-bf03-43a6-8813-761f72e1c00a"
        or os.environ.get("RAILWAY_ENVIRONMENT_ID")
        != "05d1eac2-510d-4bd3-999e-fea9ead766b7"
    ):
        raise SystemExit(
            "Explicit recovery is restricted to the pinned staging environment"
        )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", type=int, required=True)
    parser.add_argument("--mapping-id", type=int, required=True)
    parser.add_argument("--denial-attempt-id", type=int, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            run_recovery(args.source_id, args.mapping_id, args.denial_attempt_id)
        )
    )


def consume_planned_recovery(session, source_id, *, runner=None):
    """Serve only an explicitly authorized, unattempted current intent."""
    work = session.scalar(
        select(FreshnessWork)
        .where(
            FreshnessWork.source_id == source_id,
            FreshnessWork.kind == "validation",
            FreshnessWork.scope_key.like("source-recovery:snkrdunk:%"),
            FreshnessWork.state == "pending",
            FreshnessWork.attempt_count == 0,
            FreshnessWork.next_due_at <= utc_now(),
        )
        .order_by(FreshnessWork.id)
        .limit(1)
    )
    if (
        work is None
        or (work.resume_cursor or {}).get("scheduled_recovery_authorized") is not True
    ):
        return None
    cursor, bound = work.resume_cursor, work.estimated_request_cost
    from app.services.operational_health_runtime import execution

    with execution(
        session,
        source_id,
        "snkrdunk-recovery",
        max_work=1,
        runtime_seconds=240,
        singleton="held",
    ) as telemetry:
        result = consume_recovery(
            session,
            source_id,
            cursor["mapping_id"],
            cursor["recovery_denial_attempt_id"],
            request_bound=bound,
            runner=runner,
            owner=telemetry["owner"] if telemetry else "snkrdunk-recovery",
            network_repair_of=cursor.get("network_repair_of"),
        )
        if telemetry:
            telemetry["stopped_reason"] = "recovery_" + result["status"]
            for field, count in result.get("failure_counts", {}).items():
                telemetry[field] += count
        print(json.dumps({"event": "scheduled_source_recovery", **result}), flush=True)
        return result


if __name__ == "__main__":
    main()
