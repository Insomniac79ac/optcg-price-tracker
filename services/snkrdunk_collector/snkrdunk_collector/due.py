"""Opt-in shared due-work adapter. Legacy batches never import this module."""

from sqlalchemy import select

from app.services.freshness_integration import CaptureResult, drain
from snkrdunk_collector.config import settings
from snkrdunk_collector.db import SessionLocal
from snkrdunk_collector.models import Source
from snkrdunk_collector.run_lock import (
    collection_lock,
    pinned_session,
    assert_lock_owned,
)
from snkrdunk_collector.writer import validate_and_write_observation


def write_capture(session, mapping, holder, attempt):
    """Reuse the exact-print/artwork/release writer for both category outcomes."""
    from snkrdunk_collector.collect import PARSER_VERSION

    extraction = holder["extraction"]
    psa = extraction["extracted"]["psa10"]
    category_outcomes = {}
    observations, unlisted = {}, set()
    errors = []
    for category in attempt.claim.price_categories:
        if category not in {"raw", "psa10"}:
            raise ValueError("unsupported SNKRDUNK category demand")
        result = validate_and_write_observation(
            session=session,
            mapping=mapping,
            classification=holder["product_classification"],
            extraction=extraction,
            artwork_comparison=holder["artwork_comparison"],
            http_status=holder["product_http_status"],
            raw_html=holder["product_html"],
            source_url=holder["product_final_url"],
            parser_version=PARSER_VERSION,
            raw_snapshot_id=attempt.raw_snapshot_id,
            category=category,
        )
        if result.written:
            observations[category] = result.observation_id
            category_outcomes[category] = "captured"
        elif result.identity_verified and result.reasons == [
            "no_raw_condition_price_available"
        ]:
            if category == "psa10":
                category_outcomes[category] = psa["outcome"]
            else:
                conditions = extraction["extracted"]["conditions"]
                expected = {"A", "B", "C", "D"}
                category_outcomes[category] = (
                    "no_listing"
                    if expected <= conditions.keys()
                    and all(
                        conditions[label]["price_jpy"] is None
                        and conditions[label]["raw_text"] == "出品待ち"
                        for label in expected
                    )
                    else (
                        "absent"
                        if not conditions
                        and extraction["raw"]["condition_container"].get(
                            "category_labels_complete"
                        )
                        else "parsing_failure"
                    )
                )
            if category_outcomes[category] == "no_listing":
                unlisted.add(category)
        else:
            errors.extend(result.reasons)
    if errors:
        # Identity/approval checks are product-wide: no category may publish.
        session.rollback()
        return CaptureResult("identity_refusal", failure=";".join(errors))
    return CaptureResult(
        (
            "captured"
            if observations
            else "no_listing" if unlisted else "transient_failure"
        ),
        raw_snapshot_id=attempt.raw_snapshot_id,
        observation_ids=observations,
        no_listing_categories=unlisted,
        failure=None if observations or unlisted else "category evidence unavailable",
        category_outcomes=category_outcomes,
    )


def run_due(
    *,
    chunk_size=70,
    session_factory=SessionLocal,
    runner=None,
    lock_factory=collection_lock
):
    from snkrdunk_collector.collect import run_one_mapping_detailed
    from snkrdunk_collector.discovery import run_discovery

    with session_factory() as probe:
        engine = probe.get_bind()
    with lock_factory(engine) as lock:
        if not lock.acquired:
            from app.services.operational_health_runtime import execution

            with session_factory() as session:
                source_id = session.scalar(
                    select(Source.id).where(Source.name == "snkrdunk")
                )
                with execution(
                    session,
                    source_id,
                    "snkrdunk-due",
                    max_work=settings.BATCH_MAX_MAPPINGS_PER_RUN,
                    runtime_seconds=settings.BATCH_TOTAL_TIMEOUT_S,
                    singleton="contended",
                ) as telemetry:
                    if telemetry is not None:
                        telemetry["stopped_reason"] = "singleton_contended"
            return []
        with pinned_session(lock, session_factory) as session:
            assert_lock_owned(session)
            source_id = session.scalar(
                select(Source.id).where(Source.name == "snkrdunk")
            )
            from snkrdunk_collector.recovery import consume_planned_recovery
            recovery = consume_planned_recovery(session, source_id, runner=runner)
            if recovery is not None:
                return [recovery]  # ordinary checks resume on the next scheduled turn
            return drain(
                session,
                source_id,
                "snkrdunk-due",
                runner or run_one_mapping_detailed,
                runtime_seconds=settings.BATCH_TOTAL_TIMEOUT_S,
                mapping_seconds=settings.TOTAL_RUN_TIMEOUT_S,
                chunk_size=chunk_size,
                max_work=settings.BATCH_MAX_MAPPINGS_PER_RUN,
                discovery_runner=run_discovery,
                delay_seconds=max(0, settings.SNKRDUNK_REQUEST_DELAY_MS) / 1000,
                ownership_check=assert_lock_owned,
            )
