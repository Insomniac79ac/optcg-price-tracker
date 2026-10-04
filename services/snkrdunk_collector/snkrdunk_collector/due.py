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
                    else "absent"
                    if not conditions
                    and extraction["raw"]["condition_container"].get("category_labels_complete")
                    else "parsing_failure"
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


def review_capture(session, mapping, holder, attempt):
    """Fresh identity evidence only. Never writes a price or clears quarantine."""
    from datetime import timedelta
    from app.models import CardPrint, CanonicalCard
    from snkrdunk_collector.card_code_authority import resolve_expected_card_code
    from snkrdunk_collector.release_identity import resolve_release_identity
    from snkrdunk_collector.writer import validate_identity

    card_print = session.get(CardPrint, mapping.card_print_id)
    canonical = session.get(CanonicalCard, card_print.canonical_card_id) if card_print else None
    reasons = validate_identity(
        mapping, card_print, canonical, holder["product_classification"],
        holder["extraction"], holder["artwork_comparison"],
        card_code_authority=resolve_expected_card_code(session, card_print),
        release=resolve_release_identity(session, card_print),
        allow_approved_missing_artwork=False,
    )
    return CaptureResult(
        "completed", raw_snapshot_id=attempt.raw_snapshot_id,
        resume_cursor={"version": 1, "mapping_id": mapping.id,
                       "identity_confirmed": not reasons, "reasons": reasons,
                       "artwork": holder["artwork_comparison"]},
        next_due_at=attempt.clock() + timedelta(hours=24),
    )


def run_identity_review(session, claim, *, freshness):
    from types import SimpleNamespace
    from app.models import FreshnessWork
    from snkrdunk_collector.collect import run_one_mapping_detailed
    work = session.get(FreshnessWork, claim.work_id)
    prefix = "quarantine-review:"
    scope = work.scope_key or ""
    def refused(reason):
        freshness.result = CaptureResult("identity_refusal", failure=reason)
        return SimpleNamespace(source_denied=False, stage="validation_failed", reasons=[reason])
    if not scope.startswith(prefix) or not scope[len(prefix):].isdigit():
        return refused("unsupported identity validation scope")
    mapping_id = int(scope[len(prefix):])
    quarantined = session.scalar(select(FreshnessWork).where(
        FreshnessWork.kind == "refresh",
        FreshnessWork.source_card_mapping_id == mapping_id,
        FreshnessWork.source_id == work.source_id,
        FreshnessWork.state == "blocked",
    ))
    if quarantined is None:
        return refused("identity review requires an existing quarantined mapping")
    return run_one_mapping_detailed(session, mapping_id, freshness=freshness)


def run_due(
    *,
    chunk_size=70,
    session_factory=SessionLocal,
    runner=None,
    lock_factory=collection_lock
):
    from snkrdunk_collector.collect import run_one_mapping_detailed

    with session_factory() as probe:
        engine = probe.get_bind()
    with lock_factory(engine) as lock:
        if not lock.acquired:
            return []
        with pinned_session(lock, session_factory) as session:
            assert_lock_owned(session)
            source_id = session.scalar(
                select(Source.id).where(Source.name == "snkrdunk")
            )
            return drain(
                session,
                source_id,
                "snkrdunk-due",
                runner or run_one_mapping_detailed,
                runtime_seconds=settings.BATCH_TOTAL_TIMEOUT_S,
                mapping_seconds=settings.TOTAL_RUN_TIMEOUT_S,
                chunk_size=chunk_size,
                # Repeated chunks must share the existing per-execution ceiling.
                max_products=settings.BATCH_MAX_MAPPINGS_PER_RUN,
                validation_runner=run_identity_review,
                delay_seconds=max(0, settings.SNKRDUNK_REQUEST_DELAY_MS) / 1000,
                ownership_check=assert_lock_owned,
            )
