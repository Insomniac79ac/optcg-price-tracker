"""Opt-in nine-shard consumer of the shared service; no second queue/policy."""

from sqlalchemy import select

from app.services.freshness_integration import CaptureResult, drain
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

    if type(shard_index) is not int or not 0 <= shard_index < 9:
        raise ValueError("due collection requires one of the existing nine shards")
    with session_factory() as session:
        source_id = session.scalar(select(Source.id).where(Source.name == "yuyutei"))
        return drain(
            session,
            source_id,
            f"yuyutei-due-{shard_index}",
            runner or run_one_mapping_detailed,
            runtime_seconds=settings.BATCH_TOTAL_TIMEOUT_S,
            mapping_seconds=settings.TOTAL_RUN_TIMEOUT_S,
            chunk_size=chunk_size,
            shard_index=shard_index,
            delay_seconds=max(0, settings.YUYUTEI_REQUEST_DELAY_MS) / 1000,
        )
