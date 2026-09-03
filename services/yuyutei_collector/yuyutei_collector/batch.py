"""`python -m yuyutei_collector.collect --approved-mappings` - discovers every
eligible approved Yuyu-Tei mapping from the database and processes them one
at a time, sequentially, in one bounded batch.

Selection (see select_eligible_mappings): a mapping is eligible only if its
source is "yuyutei", it is active and review_status="approved", it carries a
card_print_id (an exact-print mapping, never a legacy-card-only one), and
that card_print is itself active and verification_status="verified". Nothing
here is hardcoded per card/mapping id - eligibility is entirely a database
query, so a newly approved+verified mapping is picked up automatically and a
demoted/unverified one drops out automatically.

Sequencing and safety (see run_batch):
- one mapping is fully resolved (written, mapping-level failure, or
  operational error) before the next mapping's first request is made - never
  parallel Yuyu-Tei requests.
- a conservative fixed delay (settings.YUYUTEI_REQUEST_DELAY_MS) separates
  the end of one mapping and the start of the next.
- a mapping-level outcome (validation failure, identity mismatch, price/
  stock disagreement, operational error) records a failed mapping and moves
  on to the next one.
- a source-wide denial signal (HTTP 403, or the challenge/CAPTCHA/429
  classification - see collect.SOURCE_DENIAL_CLASSIFICATIONS) stops the
  remainder of the batch immediately; every mapping not yet attempted is
  recorded as skipped, never attempted.
- the whole batch is bounded by one wall-clock budget
  (settings.BATCH_TOTAL_TIMEOUT_S), checked before each mapping starts -
  deliberately a plain monotonic-clock check rather than nesting another
  signal-based deadline() (see browser.deadline) around the loop: each
  mapping already runs inside its own per-mapping deadline, and that
  per-mapping deadline's own except-clause (see collect.
  run_one_mapping_detailed) unconditionally catches DeadlineExceeded - a
  nested batch-level deadline() firing mid-mapping would be silently
  absorbed there as an ordinary per-mapping operational_error instead of
  stopping the batch. The explicit check here has no such ambiguity.
- every mapping id is deduplicated before processing and only ever passed to
  run_one_mapping_detailed once per batch_run_id - a local control-flow bug
  (e.g. the same id appearing twice in the selected set) cannot produce two
  observations for one mapping in one run. A future day's batch still
  creates new observations as normal; nothing here deduplicates across runs.

`--mapping-ids` (see collect.main) narrows the eligible set to specific ids -
a runtime argument for one-off operational batches (e.g. validating or
writing a freshly-approved group of mappings without also touching every
other already-collected mapping), never a hardcoded id list in this module.
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

from yuyutei_collector.browser import log_event
from yuyutei_collector.collect import MappingOutcome, run_one_mapping_detailed
from yuyutei_collector import telemetry
from yuyutei_collector.config import settings
from yuyutei_collector.db import SessionLocal
from yuyutei_collector.models import CardPrint, Source, SourceCardMapping

YUYUTEI_SOURCE_NAME = "yuyutei"


def select_eligible_mappings(
    session: Session, limit: int | None = None, mapping_ids: list[int] | None = None
) -> list[SourceCardMapping]:
    """Every approved, active, verified-print Yuyu-Tei mapping - discovered
    from current database state, never a hardcoded id list. Deterministic
    order (mapping id ascending) so repeated calls against unchanged state
    always select mappings in the same sequence.

    `mapping_ids`, when given, narrows the result to just those ids - it
    never widens or bypasses eligibility (an id outside the eligible set is
    silently excluded, not force-included). Meant for one-off operational
    batches (e.g. a filtered manual run right after approving a batch of new
    mappings) - a runtime argument the caller supplies, never a hardcoded id
    list in this function itself."""
    stmt = (
        select(SourceCardMapping)
        .join(Source, Source.id == SourceCardMapping.source_id)
        .join(CardPrint, CardPrint.id == SourceCardMapping.card_print_id)
        .where(
            Source.name == YUYUTEI_SOURCE_NAME,
            SourceCardMapping.is_active.is_(True),
            SourceCardMapping.review_status == "approved",
            SourceCardMapping.card_print_id.is_not(None),
            CardPrint.is_active.is_(True),
            CardPrint.verification_status == "verified",
        )
        .order_by(SourceCardMapping.id.asc())
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
    return max(0, settings.YUYUTEI_REQUEST_DELAY_MS) / 1000.0


# MappingOutcome.stage already IS the telemetry vocabulary for every outcome a
# real collection can reach - the two were defined from the same list - so this
# is a projection, not a translation. "validated_only" has no counterpart by
# design (see record_telemetry in run_batch), and any unexpected stage is
# passed through so the database's CHECK rejects it loudly rather than this
# function quietly relabelling it as something valid.
def _record(call, *args, **kwargs) -> None:
    """Every telemetry call from this module goes through here.

    telemetry.* already swallows its own failures and returns a bool, so this
    is deliberate belt and braces: it makes "a telemetry problem cannot reach
    the pricing job" true at the CALL SITE, independent of the recorder
    keeping its contract. Nothing else in run_batch is wrapped - collector
    errors keep propagating exactly as they did.
    """
    try:
        call(*args, **kwargs)
    except Exception:  # noqa: BLE001 - a telemetry bug must not stop collection
        log_event("telemetry_call_failed", call=getattr(call, "__name__", str(call)))


def _attempt_telemetry(outcome) -> dict:
    """The outcome as this batch already computed it, expressed in the
    telemetry column names. Reads only; invents nothing."""
    return {
        "status": outcome.stage,
        "failure_stage": outcome.failure_stage,
        "failure_reason": "; ".join(outcome.reasons) if outcome.reasons else None,
        "source_denied": outcome.source_denied,
        # Only a written outcome carries one, and it is the id the writer
        # actually committed - never reconstructed by a lookup here.
        "price_observation_id": outcome.observation_id if outcome.written else None,
    }


def run_batch(
    limit: int | None = None,
    mapping_ids: list[int] | None = None,
    validate_only: bool = False,
    session_factory=SessionLocal,
    mapping_runner=run_one_mapping_detailed,
    mapping_selector=select_eligible_mappings,
) -> BatchResult:
    """Runs one bounded batch over every eligible mapping (or, if
    `mapping_ids` is given, the subset of the eligible set matching those
    ids - see select_eligible_mappings). `session_factory`/`mapping_runner`/
    `mapping_selector` are overridable purely for offline testing (see
    tests/test_batch.py) - production callers (collect.main()) never pass
    them."""
    # A validate-only run navigates but writes nothing - no observation, no
    # snapshot - so it records no attempt history either. Its stage
    # ("validated_only") has no telemetry status by design: inventing one would
    # put dry runs into the same table operators read to find out why real
    # collection produced nothing.
    record_telemetry = not validate_only

    batch_run_id = uuid.uuid4().hex[:12]
    started_at = datetime.now(timezone.utc)
    log_event("batch_start", batch_run_id=batch_run_id, started_at=started_at.isoformat())

    session = session_factory()
    results: list[MappingOutcome] = []
    stopped_reason: str | None = None
    selected_ids: list[int] = []

    try:
        eligible = mapping_selector(session, limit=limit, mapping_ids=mapping_ids)
        # Dedupe defensively, preserving order - a single mapping id must
        # never be handed to mapping_runner twice within one batch_run_id,
        # regardless of what the selector returns.
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

        # Durable population, written before any navigation, so a process that
        # dies on its first mapping still leaves a record of what it meant to
        # do. Best-effort by construction: telemetry.* returns False rather
        # than raising, and nothing below reads the result.
        if record_telemetry and selected:
            _record(
                telemetry.record_selected_batch,
                batch_run_id,
                selected[0].source_id,
                selected_ids,
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

            # Immediately before this mapping does any work - never for the
            # mappings still queued behind it.
            if record_telemetry:
                _record(telemetry.mark_attempt_started, batch_run_id, mapping.id)

            outcome = mapping_runner(
                session, mapping.id, validate_only=validate_only, batch_run_id=batch_run_id
            )
            results.append(outcome)
            log_event(
                "batch_mapping_result",
                batch_run_id=batch_run_id,
                mapping_id=mapping.id,
                stage=outcome.stage,
                written=outcome.written,
                source_denied=outcome.source_denied,
                reasons=outcome.reasons,
            )
            # Recorded BEFORE the source-denial break below, so the mapping
            # that was actually denied keeps its own real terminal outcome
            # instead of being swept into the skipped set with the rest.
            if record_telemetry:
                _record(
                    telemetry.finish_attempt,
                    batch_run_id,
                    mapping.id,
                    **_attempt_telemetry(outcome),
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
        # Terminal, but never started: these mappings were selected and the
        # batch stopped before reaching them. finish_attempt does not invent a
        # started_at, so started_at stays NULL and the row says exactly that.
        if record_telemetry:
            denied = bool(stopped_reason) and stopped_reason.startswith("source_denied")
            for mapping_id in skipped_ids:
                _record(
                    telemetry.finish_attempt,
                    batch_run_id,
                    mapping_id,
                    "skipped",
                    failure_reason=stopped_reason,
                    source_denied=denied,
                )

    if any(r.source_denied for r in results):
        status, exit_code = "source_wide_failure", 1
    elif stopped_reason is not None or any(not r.written for r in results):
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
        mappings_skipped=len(skipped_ids),
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
