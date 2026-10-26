"""One scheduled Yuyu-Tei source probe per owner-approved denial. No retry, no timer.

Owner decision 2026-10-26 (perfectionist). After a challenge page paused every shard, the
owner approves `ops-write yuyu-source-probe`, which records one authorized validation scope
(app.services.source_recovery.plan_yuyu_probe). The next scheduled shard turn calls
consume_planned_probe before its ordinary work: it claims that scope (one winner across
shards), runs one metered product capture of the chosen mapping from this collector's own
network - the network Yuyu-Tei challenged - validates identity exactly as a capture would but
writes no price, and settles the attempt. Only a completed, identity-verified HTTP 200 capture
clears the pause (resume_after_yuyu_probe); a challenge settles as source_denial and the pause
stays. Ordinary checks resume on the following scheduled turns.
"""

import json

from app.services.freshness_integration import AdmissionStopped, Attempt, CaptureResult
from app.services.source_recovery import claim_yuyu_probe, resume_after_yuyu_probe


def consume_planned_probe(session, source_id, *, runner, owner):
    """Serve the one authorized probe, or return None when there is none."""
    claim = claim_yuyu_probe(session, source_id, owner)
    session.commit()
    if claim is None:
        return None
    attempt = Attempt(session, claim)
    outcome = None
    try:
        outcome = runner(session, claim.resume_cursor["mapping_id"], freshness=attempt, probe=True)
    except AdmissionStopped as exc:
        session.rollback()
        attempt.result = CaptureResult(
            "source_denial" if attempt.denied else "transient_failure",
            failure=str(exc), raw_snapshot_id=attempt.raw_snapshot_id,
        )
    except Exception as exc:  # noqa: BLE001 - settle the attempt, never leave it claimed
        session.rollback()
        attempt.result = CaptureResult(
            "source_denial" if attempt.denied else "transient_failure",
            failure=type(exc).__name__, raw_snapshot_id=attempt.raw_snapshot_id,
        )
    if attempt.result is None:
        session.rollback()
        attempt.result = CaptureResult(
            "source_denial" if attempt.denied or getattr(outcome, "source_denied", False)
            else "transient_failure",
            failure=";".join(filter(None, [attempt.stopped, *getattr(outcome, "reasons", [])])),
            raw_snapshot_id=getattr(outcome, "raw_snapshot_id", None),
        )
    if attempt.result.raw_snapshot_id is None:
        attempt.result.raw_snapshot_id = attempt.raw_snapshot_id
    settled = attempt.finish(attempt.result)
    resumed = False
    if settled and attempt.result.outcome == "completed":
        resume_after_yuyu_probe(session, claim.claim_token)
        session.commit()
        resumed = True
    result = {
        "status": attempt.result.outcome,
        "resumed": resumed,
        "work_id": claim.work_id,
        "mapping_id": claim.resume_cursor["mapping_id"],
        "request_cost": attempt.charged_cost,
        "product_snapshot_id": attempt.result.raw_snapshot_id,
        "failure": attempt.result.failure,
    }
    print(json.dumps({"event": "scheduled_source_probe", **result}), flush=True)
    return result
