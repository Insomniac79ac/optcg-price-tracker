"""Opt-in nine-shard consumer of the shared service; no second queue/policy."""

import functools

from sqlalchemy import select

from app.services.freshness_integration import CaptureResult, drain
from yuyutei_collector.browser import log_event
from yuyutei_collector.config import settings
from yuyutei_collector.db import SessionLocal
from yuyutei_collector.models import Source
from yuyutei_collector.due_discovery import run_discovery
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


def _discovery_outside_turn(turn, *args, **kwargs):
    # Discovery starts its own sync Playwright, which cannot start while the
    # turn's is running in this thread; the next capture warms up afresh.
    turn.discard("discovery")
    return run_discovery(*args, **kwargs)


def run_due(*, shard_index, chunk_size=70, session_factory=SessionLocal, runner=None):
    from yuyutei_collector.collect import run_one_mapping_detailed

    if type(shard_index) is not int or not 0 <= shard_index < 9:
        raise ValueError("due collection requires one of the existing nine shards")
    # One warmed browser per scheduled turn (unless a caller supplies its own
    # runner). Closed however the turn ends, including deadline paths.
    turn = None
    if runner is None:
        from yuyutei_collector.browser import TurnBrowser

        turn = TurnBrowser()
        runner = functools.partial(run_one_mapping_detailed, turn=turn)
    discovery_runner = run_discovery if turn is None else functools.partial(
        _discovery_outside_turn, turn)
    try:
        with session_factory() as session:
            source_id = session.scalar(select(Source.id).where(Source.name == "yuyutei"))
            return drain(
                session,
                source_id,
                f"yuyutei-due-{shard_index}",
                runner,
                runtime_seconds=settings.BATCH_TOTAL_TIMEOUT_S,
                mapping_seconds=settings.TOTAL_RUN_TIMEOUT_S,
                chunk_size=chunk_size,
                max_work=settings.DUE_MAX_PRODUCTS_PER_RUN,
                discovery_runner=discovery_runner,
                shard_index=shard_index,
                delay_seconds=max(0, settings.YUYUTEI_REQUEST_DELAY_MS) / 1000,
            )
    finally:
        if turn is not None:
            log_event("turn_browser_summary", shard_index=shard_index,
                      launches=turn.launches, warmups=turn.warmups)
            turn.close()
