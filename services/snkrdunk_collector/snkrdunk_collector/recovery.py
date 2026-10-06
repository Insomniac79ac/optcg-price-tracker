"""Explicit singleton, one-shot source recovery. No automatic retry or unpause."""

import argparse
import json
import os
from app.services.freshness_integration import Attempt, CaptureResult
from app.services.source_recovery import claim_source_recovery, resume_after_recovery
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
    lock_factory=collection_lock
):
    from snkrdunk_collector.collect import run_one_mapping_detailed

    with session_factory() as probe:
        engine = probe.get_bind()
    with lock_factory(engine) as lock:
        if not lock.acquired:
            return {"status": "singleton_contended", "resumed": False}
        with pinned_session(lock, session_factory) as session:
            assert_lock_owned(session)
            claim = claim_source_recovery(
                session,
                source_id,
                mapping_id,
                denial_attempt_id,
                "snkrdunk-explicit-recovery",
                request_bound=request_bound,
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


if __name__ == "__main__":
    main()
