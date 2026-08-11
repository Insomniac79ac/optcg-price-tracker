"""`python -m snkrdunk_collector.collect --approved-mappings` - discovers
every eligible approved SNKRDUNK mapping from the database and processes
them one at a time, sequentially, in one bounded batch. Mirrors
services/yuyutei_collector/yuyutei_collector/batch.py's structure and
safety contract exactly.

Selection (see select_eligible_mappings): a mapping is eligible only if its
source is "snkrdunk", it is active and review_status="approved", it carries
a card_print_id (an exact-print mapping, never a legacy-card-only one), and
that card_print is itself active and verification_status="verified".
Nothing here is hardcoded per card/mapping id - eligibility is entirely a
database query, so a newly approved+verified mapping is picked up
automatically and a rejected/unverified one drops out automatically (see
the legacy-mapping quarantine this batch mode was built alongside).

Sequencing and safety (see run_batch):
- one mapping is fully resolved (written, mapping-level failure, or
  operational error) before the next mapping's first request is made -
  never parallel SNKRDUNK requests.
- a conservative fixed delay (settings.SNKRDUNK_REQUEST_DELAY_MS) separates
  the end of one mapping and the start of the next.
- a mapping-level outcome (validation failure, identity mismatch, artwork
  mismatch, operational error) records a failed mapping and moves on to the
  next one - it never contaminates another mapping/print.
- a source-wide denial signal (HTTP 403/429, or the challenge/CAPTCHA
  classification - see collect.SOURCE_DENIAL_CLASSIFICATIONS) stops the
  remainder of the batch immediately; every mapping not yet attempted is
  recorded as skipped, never attempted. Earlier valid writes in the same
  batch are preserved (each mapping already committed its own transaction).
- the whole batch is bounded by one wall-clock budget
  (settings.BATCH_TOTAL_TIMEOUT_S), checked before each mapping starts.
- every mapping id is deduplicated before processing and only ever passed to
  run_one_mapping_detailed once per batch_run_id.

`--mapping-ids` (see collect.main) narrows the eligible set to specific ids.
`--validate-only` runs the identical navigation/extraction/lineage checks
without writing anything, same as the single-mapping CLI.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from snkrdunk_collector.browser import log_event
from snkrdunk_collector.collect import MappingOutcome, run_one_mapping_detailed
from snkrdunk_collector.config import settings
from snkrdunk_collector.db import SessionLocal
from snkrdunk_collector.models import CardPrint, Source, SourceCardMapping

SNKRDUNK_SOURCE_NAME = "snkrdunk"


def select_eligible_mappings(
    session: Session,
    limit: int | None = None,
    mapping_ids: list[int] | None = None,
    require_approved: bool = True,
) -> list[SourceCardMapping]:
    """Every approved, manually-verified, active, verified-print SNKRDUNK
    mapping - discovered from current database state, never a hardcoded id
    list. Deterministic order (mapping id ascending) so repeated calls
    against unchanged state always select mappings in the same sequence.

    manual_verified=True is required in addition to review_status="approved"
    as defense-in-depth: a mapping must never enter production collection on
    review_status alone (see the 2026-08-10 incident where mappings were
    marked approved without going through real verification).

    require_approved=False drops the review_status/manual_verified/print-
    verification_status gate so an explicit `mapping_ids` list can target
    not-yet-approved mappings for a pre-approval identity/artwork
    re-verification pass - see run_batch's own require_approved docstring
    for the validate_only-only restriction this must always be paired with.
    Still requires an active mapping linked to an active exact print; never
    a legacy card-only mapping."""
    stmt = (
        select(SourceCardMapping)
        .join(Source, Source.id == SourceCardMapping.source_id)
        .join(CardPrint, CardPrint.id == SourceCardMapping.card_print_id)
        .where(
            Source.name == SNKRDUNK_SOURCE_NAME,
            SourceCardMapping.is_active.is_(True),
            SourceCardMapping.card_print_id.is_not(None),
            CardPrint.is_active.is_(True),
        )
        .order_by(SourceCardMapping.id.asc())
    )
    if require_approved:
        stmt = stmt.where(
            SourceCardMapping.review_status == "approved",
            SourceCardMapping.manual_verified.is_(True),
            CardPrint.verification_status == "verified",
        )
    if mapping_ids is not None:
        stmt = stmt.where(SourceCardMapping.id.in_(mapping_ids))
    mappings = list(session.scalars(stmt).all())
    if limit is not None:
        mappings = mappings[:limit]
    return mappings


@dataclass
class BatchResult:
    batch_run_id: str
    status: str  # "success" | "partial_failure" | "source_wide_failure"
    exit_code: int
    started_at: str
    finished_at: str
    mappings_selected: list[int] = field(default_factory=list)
    results: list[MappingOutcome] = field(default_factory=list)
    stopped_reason: str | None = None


def _mapping_delay_s() -> float:
    return max(0, settings.SNKRDUNK_REQUEST_DELAY_MS) / 1000.0


def run_batch(
    limit: int | None = None,
    mapping_ids: list[int] | None = None,
    validate_only: bool = False,
    require_approved: bool = True,
    session_factory=SessionLocal,
    mapping_runner=run_one_mapping_detailed,
    mapping_selector=select_eligible_mappings,
) -> BatchResult:
    """Runs one bounded batch over every eligible mapping (or, if
    `mapping_ids` is given, the subset of the eligible set matching those
    ids). `session_factory`/`mapping_runner`/`mapping_selector` are
    overridable purely for offline testing - production callers
    (collect.main()) never pass them.

    require_approved=False (only ever paired with validate_only=True - see
    collect.main()'s --allow-unapproved) targets not-yet-approved mappings
    for identity/artwork re-verification without ever writing a row; this
    combination is enforced here too, independent of the CLI, because
    run_batch is a public function other callers could reach directly."""
    if not require_approved and not validate_only:
        raise ValueError("require_approved=False must always be paired with validate_only=True.")
    batch_run_id = uuid.uuid4().hex[:12]
    started_at = datetime.now(timezone.utc)
    log_event("batch_start", batch_run_id=batch_run_id, started_at=started_at.isoformat())

    session = session_factory()
    results: list[MappingOutcome] = []
    stopped_reason: str | None = None
    selected_ids: list[int] = []

    try:
        eligible = mapping_selector(session, limit=limit, mapping_ids=mapping_ids, require_approved=require_approved)
        seen: set[int] = set()
        selected: list[SourceCardMapping] = []
        for mapping in eligible:
            if mapping.id in seen:
                continue
            seen.add(mapping.id)
            selected.append(mapping)
        selected_ids = [m.id for m in selected]

        log_event(
            "batch_mappings_selected",
            batch_run_id=batch_run_id,
            mapping_ids=selected_ids,
            count=len(selected_ids),
        )

        batch_deadline_at = time.monotonic() + settings.BATCH_TOTAL_TIMEOUT_S
        for index, mapping in enumerate(selected):
            if time.monotonic() >= batch_deadline_at:
                stopped_reason = "batch_total_timeout_exceeded"
                log_event(
                    "batch_watchdog_triggered",
                    batch_run_id=batch_run_id,
                    label="batch_total",
                    remaining_mapping_ids=[m.id for m in selected[index:]],
                )
                break

            outcome = mapping_runner(session, mapping.id, validate_only=validate_only, batch_run_id=batch_run_id)
            results.append(outcome)
            log_event(
                "batch_mapping_result",
                batch_run_id=batch_run_id,
                mapping_id=mapping.id,
                stage=outcome.stage,
                written=outcome.written,
                would_write=outcome.would_write,
                floor_unavailable=outcome.floor_unavailable,
                source_denied=outcome.source_denied,
                reasons=outcome.reasons,
                identity_verified=outcome.identity_verified,
                identity_reasons=outcome.identity_reasons,
                identity_classification=outcome.identity_classification,
                card_code_authority=outcome.card_code_authority,
                card_code_evidence_type=outcome.card_code_evidence_type,
                release_name_matched_via=outcome.release_name_match_authority,
            )

            if outcome.source_denied:
                stopped_reason = f"source_denied:{outcome.classification}"
                break

            is_last = index == len(selected) - 1
            if not is_last:
                time.sleep(_mapping_delay_s())
    finally:
        session.close()

    attempted_ids = {r.mapping_id for r in results}
    skipped_ids = [mid for mid in selected_ids if mid not in attempted_ids]
    if skipped_ids:
        log_event(
            "batch_mappings_skipped",
            batch_run_id=batch_run_id,
            mapping_ids=skipped_ids,
            reason=stopped_reason,
        )

    # What counts as a mapping having succeeded.
    #
    # A validate-only run persists nothing by design, so it is judged by
    # identity verification. A production run is judged by "did this mapping
    # reach a legitimate resting state?" - which means EITHER a row was
    # written, OR the print was fully verified and simply has no listing
    # right now (floor_unavailable). A verified print whose A-D chips are all
    # 出品待ち is not a failure: there is nothing to record, and reporting it
    # as one would make a healthy batch look broken and train operators to
    # ignore a non-zero exit.
    #
    # Non-zero stays reserved for genuine failures: source-wide denial,
    # identity/artwork/release mismatch, operational errors and write
    # failures. Those all leave written=False AND floor_unavailable=False.
    def _resolved_ok(result) -> bool:
        if validate_only:
            return result.identity_verified
        return result.written or result.floor_unavailable

    failures = [r for r in results if not _resolved_ok(r)]

    if any(r.source_denied for r in results):
        status, exit_code = "source_wide_failure", 1
    elif stopped_reason is not None or failures:
        status, exit_code = "partial_failure", 2
    else:
        status, exit_code = "success", 0

    finished_at = datetime.now(timezone.utc)
    log_event(
        "batch_complete",
        batch_run_id=batch_run_id,
        status=status,
        exit_code=exit_code,
        mappings_selected=len(selected_ids),
        mappings_attempted=len(results),
        mappings_written=sum(1 for r in results if r.written),
        mappings_would_write=sum(1 for r in results if r.would_write),
        mappings_identity_verified=sum(1 for r in results if r.identity_verified),
        mappings_floor_unavailable=sum(1 for r in results if r.floor_unavailable),
        mappings_failed=len(failures),
        failed_mapping_ids=[r.mapping_id for r in failures],
        mappings_skipped=len(skipped_ids),
        validate_only=validate_only,
        stopped_reason=stopped_reason,
        finished_at=finished_at.isoformat(),
    )

    return BatchResult(
        batch_run_id=batch_run_id,
        status=status,
        exit_code=exit_code,
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
        mappings_selected=selected_ids,
        results=results,
        stopped_reason=stopped_reason,
    )
