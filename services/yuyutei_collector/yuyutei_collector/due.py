"""Opt-in nine-shard consumer of the shared service; no second queue/policy."""

from sqlalchemy import func, or_, select

from app.services.freshness_integration import CaptureResult, drain
from app.services.freshness_policy import utc_now
from app.models import FreshnessWork
from yuyutei_collector.config import settings
from yuyutei_collector.db import SessionLocal
from yuyutei_collector.models import Source
from yuyutei_collector.writer import validate_and_write_observation


def write_capture(session, mapping, holder):
    result = validate_and_write_observation(
        session=session,
        mapping=mapping,
        classification=holder["classification"],
        extraction=holder["extraction"],
        raw_snapshot_id=holder["raw_snapshot_id"],
        use_capture_time=True,
    )
    if result.written:
        return CaptureResult(
            "captured",
            raw_snapshot_id=result.raw_snapshot_id,
            observation_ids={"raw": result.observation_id},
            category_outcomes={"raw": "captured"},
        )
    # Existing Yuyu extraction does not establish explicit no-listing evidence.
    # Missing/ambiguous price must not be upgraded to a successful category check.
    price_failure = all(reason.startswith("price_") for reason in result.reasons)
    return CaptureResult(
        "transient_failure" if price_failure else "identity_refusal",
        failure=";".join(result.reasons),
        category_outcomes={"raw": "parsing_failure"} if price_failure else {},
    )


def run_due(*, shard_index, chunk_size=70, session_factory=SessionLocal, runner=None):
    from yuyutei_collector.collect import run_one_mapping_detailed
    from yuyutei_collector.due_discovery import run_discovery, activate_ready_scopes

    if type(shard_index) is not int or not 0 <= shard_index < 9:
        raise ValueError("due collection requires one of the existing nine shards")
    with session_factory() as session:
        source_id = session.scalar(select(Source.id).where(Source.name == "yuyutei"))
        activate_ready_scopes(session, source_id)
        session.commit()
        now = utc_now()
        repeat_checks_due = session.scalar(
            select(func.count()).select_from(FreshnessWork).where(
                FreshnessWork.source_id == source_id,
                FreshnessWork.kind == "refresh",
                FreshnessWork.state == "pending",
                FreshnessWork.source_card_mapping_id % 9 == shard_index,
                FreshnessWork.last_successfully_checked_at.is_not(None),
                FreshnessWork.next_due_at <= now,
                or_(FreshnessWork.retry_not_before_at.is_(None),
                    FreshnessWork.retry_not_before_at <= now),
            )
        )
        # This is an invocation ceiling, not a reservation or an instruction
        # to fetch. The shared queue still admits only actually due work and
        # applies source budgets, lane fairness, leases and the runtime bound.
        turn_limit = min(70, settings.DUE_COVERAGE_ALLOWANCE + repeat_checks_due)
        return drain(
            session,
            source_id,
            f"yuyutei-due-{shard_index}",
            runner or run_one_mapping_detailed,
            runtime_seconds=settings.BATCH_TOTAL_TIMEOUT_S,
            mapping_seconds=settings.TOTAL_RUN_TIMEOUT_S,
            chunk_size=chunk_size,
            max_products=turn_limit,
            discovery_runner=run_discovery,
            after_capture=lambda db: activate_ready_scopes(db, source_id),
            shard_index=shard_index,
            delay_seconds=max(0, settings.YUYUTEI_REQUEST_DELAY_MS) / 1000,
        )
