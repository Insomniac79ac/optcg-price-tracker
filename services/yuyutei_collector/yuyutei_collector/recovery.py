"""One scheduled Yuyu-Tei source probe per owner approval. No retry, no timer.

Owner decision 2026-10-26 (perfectionist). After a challenge page paused every shard, the
owner approves `ops-write yuyu-source-probe`, which records one authorized validation scope
(app.services.source_recovery.plan_yuyu_probe). Every scheduled shard turn first calls
serve_planned_probe: it closes leftover probes, and when an authorized probe is due it claims
it (one winner across shards), runs one metered product capture of the chosen mapping from
this collector's own network - the network Yuyu-Tei challenged - validates identity exactly as
a capture would but writes no price, and settles the attempt. Only a completed,
identity-verified HTTP 200 capture clears the pause (resume_after_yuyu_probe); a challenge
settles as source_denial and the pause stays. Ordinary checks resume on the following turns.
The probe turn is recorded as its own execution (operational health), max_work 1.
"""

import json
from datetime import timedelta

from app.services.freshness_integration import AdmissionStopped, Attempt, CaptureResult
from app.services.source_recovery import (
    YUYU_PROBE_MAX_LEASE,
    claim_yuyu_probe,
    close_yuyu_probe,
    resume_after_yuyu_probe,
    yuyu_probe_ready,
)


def serve_planned_probe(session, source_id, *, runner, shard_index, mapping_seconds, execution=None):
    """Serve the one authorized probe in its own execution, or return None (ordinary work)."""
    ready = yuyu_probe_ready(session, source_id)
    session.commit()  # leftover probes closed whether or not one is due
    if not ready:
        return None
    if execution is None:
        from app.services.operational_health_runtime import execution
    owner = f"yuyutei-probe-{shard_index}"
    with execution(session, source_id, owner, shard=shard_index, max_work=1,
                   runtime_seconds=mapping_seconds + 60, singleton="not_required") as telemetry:
        return consume_planned_probe(
            session, source_id, runner=runner, owner=telemetry["owner"] if telemetry else owner,
            # As ordinary claims (mapping time + 60s); a longer setting is capped, and a
            # capture that outruns the lease fails closed (expired, then closed).
            lease=min(timedelta(seconds=mapping_seconds + 60), YUYU_PROBE_MAX_LEASE), telemetry=telemetry,
        )


def consume_planned_probe(session, source_id, *, runner, owner, lease, telemetry=None):
    """Claim, run and settle the one authorized probe, or return None when there is none."""
    claim = claim_yuyu_probe(session, source_id, owner, lease=lease)
    session.commit()
    if claim is None:
        if telemetry is not None:
            telemetry["stopped_reason"] = "source_probe_not_claimed"
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
    challenged = bool(
        attempt.denied
        or getattr(outcome, "source_denied", False)
        or getattr(attempt, "source_optional_denials", 0)
    )
    if attempt.result is None:
        session.rollback()
        attempt.result = CaptureResult(
            "source_denial" if challenged else "transient_failure",
            failure=";".join(filter(None, [attempt.stopped, *getattr(outcome, "reasons", [])])),
            raw_snapshot_id=getattr(outcome, "raw_snapshot_id", None),
        )
    if attempt.result.raw_snapshot_id is None:
        attempt.result.raw_snapshot_id = attempt.raw_snapshot_id
    resumed, refusal = False, None
    try:
        settled = attempt.finish(attempt.result)
        if settled and attempt.result.outcome == "completed" and not challenged:
            resume_after_yuyu_probe(session, claim.claim_token)
            session.commit()
            resumed = True
    except Exception as exc:  # noqa: BLE001 - fails closed: the pause stays
        session.rollback()
        refusal = f"{type(exc).__name__}: {exc}"[:300]
    try:
        # One-shot either way: the probe is closed so it is never served again. A
        # challenge is marked on the probe itself, so the cool-down applies even
        # when its attempt could not settle.
        close_yuyu_probe(
            session, claim.work_id, challenged=challenged,
            reason="probe resumed the source" if resumed
            else "probe met a challenge" if challenged else None,
        )
        session.commit()
    except Exception as exc:  # noqa: BLE001 - a still-claimed probe expires and is closed next turn
        session.rollback()
        refusal = refusal or f"close: {type(exc).__name__}"
    if telemetry is not None:
        for field, count in attempt.health.items():
            telemetry[field] += count
        if getattr(outcome, "classification", None) == "challenge_or_captcha":
            telemetry["challenge"] += 1
        telemetry["stopped_reason"] = (
            "source_probe_resumed" if resumed
            else "source_denial" if challenged else "source_probe_failed"
        )
    result = {
        "status": attempt.result.outcome,
        "resumed": resumed,
        "challenged": challenged,
        "work_id": claim.work_id,
        "mapping_id": claim.resume_cursor["mapping_id"],
        "request_cost": attempt.charged_cost,
        "product_snapshot_id": attempt.result.raw_snapshot_id,
        "failure": attempt.result.failure,
        "resume_refused": refusal,
    }
    print(json.dumps({"event": "scheduled_source_probe", **result}), flush=True)
    return result
