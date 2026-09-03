"""Best-effort durable telemetry for collector attempts.

THE ONE RULE. Telemetry must never be capable of breaking pricing collection.
Every function here returns a bool and raises nothing: a telemetry failure
degrades the run to exactly today's behaviour (stdout only), never to a lost
observation. This mirrors services/worker/worker/app_logging.py, whose
record_app_log has held the same contract in production since July.

WHY AN INDEPENDENT SESSION, NOT THE CALLER'S. Two directions matter and only a
separate short-lived session satisfies both:

  * A telemetry failure must not roll back a good observation. Sharing the
    caller's Session would put a failed INSERT inside the pricing
    transaction, and a single constraint violation would take the price down
    with it - the exact inversion of this module's purpose.
  * A rolled-back pricing transaction must still leave the row that explains
    WHY it rolled back. That row cannot live in the transaction it is
    describing.

So each call opens its own Session, commits it, and closes it. That is also
why these functions take ids rather than ORM objects: an instance loaded in
the caller's Session must never be attached to this one.

WHY THE SUBJECT IDS ARE NOT FOREIGN KEYS. source_id and source_card_mapping_id
are plain NOT NULL integers. The repo never hard-deletes either subject -
mappings are retired with is_active = False and admin_card_merge states it
"never hard-deletes a card, a source mapping, a price observation" - so a
delete-coupled FK would buy nothing in production while ensuring that a future
hard delete takes the history with it. Its insert-time half is worse than
useless here: because this module swallows its own failures, a rejected row is
silently LOST, precisely when something unusual is happening and the evidence
matters most. price_observation_id is the exception and keeps its FK with
ON DELETE SET NULL, because observations really are deleted (data_retention
prunes them at 365 days) and a dangling pointer would mislead a later reader.

NOT WIRED IN YET. Nothing in batch.py or collect.py calls these functions; this
tranche adds the storage and the primitive only.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import datetime, timezone

from sqlalchemy import select

from yuyutei_collector.db import SessionLocal
from yuyutei_collector.models import (
    MAX_FAILURE_REASON_LENGTH,
    STATUS_SELECTED,
    SourceCollectionAttempt,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stdout_fallback(operation: str, **fields) -> None:
    """The degraded path. Uses the collector's own one-JSON-object-per-line
    convention so a failed telemetry write is still greppable in Railway logs
    for as long as those survive - which is precisely as long as we could not
    rely on before this table existed."""
    print(
        json.dumps(
            {"event": "telemetry_write_failed", "operation": operation, **fields},
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
    )


def _truncate_reason(reason: str | None) -> str | None:
    """The column is bounded at 500 characters, so a long joined fail_reasons
    list is trimmed here rather than rejected by Postgres. Losing the tail of a
    reason is a far better outcome than losing the whole row."""
    if reason is None:
        return None
    if len(reason) <= MAX_FAILURE_REASON_LENGTH:
        return reason
    return reason[: MAX_FAILURE_REASON_LENGTH - 1] + "…"


def record_selected_batch(
    batch_run_id: str,
    source_id: int,
    mapping_ids: Sequence[int],
    *,
    selected_at: datetime | None = None,
) -> bool:
    """Persist the whole selected population in ONE independent transaction.

    Written before any navigation happens, so the population survives a process
    that dies on its first mapping - which is the case that left the
    2026-09-02 batch's failures unexplainable. Either every row lands or none
    does; a partial population would be worse than none, because a later reader
    could not tell a short list from an aborted write.

    Ordinal is the 1-based position within `mapping_ids`, so execution order is
    durable even for mappings that never run. 1-based because the database
    refuses 0: NULL already means "no position", and a zero would let a missing
    value pass for one.
    """
    if not mapping_ids:
        return True

    when = selected_at or _now()
    session = None
    try:
        session = SessionLocal()
        session.add_all(
            [
                SourceCollectionAttempt(
                    batch_run_id=batch_run_id,
                    source_id=source_id,
                    source_card_mapping_id=mapping_id,
                    selection_ordinal=ordinal,
                    selected_at=when,
                    status=STATUS_SELECTED,
                )
                for ordinal, mapping_id in enumerate(mapping_ids, start=1)
            ]
        )
        session.commit()
        return True
    except Exception:
        logger.warning(
            "record_selected_batch: failed to persist %d selected mappings for batch %s.",
            len(mapping_ids),
            batch_run_id,
            exc_info=True,
        )
        _stdout_fallback(
            "record_selected_batch",
            batch_run_id=batch_run_id,
            source_id=source_id,
            mapping_count=len(mapping_ids),
        )
        return False
    finally:
        if session is not None:
            _close_quietly(session)


def mark_attempt_started(
    batch_run_id: str,
    source_card_mapping_id: int,
    *,
    source_id: int | None = None,
    started_at: datetime | None = None,
) -> bool:
    """Stamp started_at for one mapping - the moment processing actually began,
    as distinct from selected_at.

    Updates the row record_selected_batch already wrote. If there is none (the
    single-mapping CLI path never selects a population) one is inserted, which
    is why `source_id` is accepted: without a prior row there is nothing to
    read it from. selection_ordinal stays NULL there, because a run of one has
    no meaningful position.
    """
    return _upsert(
        operation="mark_attempt_started",
        batch_run_id=batch_run_id,
        source_card_mapping_id=source_card_mapping_id,
        source_id=source_id,
        values={"started_at": started_at or _now()},
    )


# A row is terminal once it carries anything but the initial status. 'selected'
# covers both not-yet-started and in-flight, so it is the only non-terminal one.
def _is_terminal(row) -> bool:
    return row.status != STATUS_SELECTED


def finish_attempt(
    batch_run_id: str,
    source_card_mapping_id: int,
    status: str,
    *,
    source_id: int | None = None,
    failure_stage: str | None = None,
    failure_reason: str | None = None,
    source_denied: bool = False,
    price_observation_id: int | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> bool:
    """Record the outcome of one attempt.

    NEVER invents a started_at. A mapping the batch selected and then skipped
    finishes without having started, and that row must read started_at=NULL,
    finished_at=<when the skip was recorded>. An earlier draft stamped a start
    here to satisfy a "finished implies started" CHECK; both the CHECK and the
    stamp are gone, because the row they produced was a small lie. Callers that
    genuinely know a start time and have not recorded one may pass it.

    An attempt that already reached a terminal status is NOT rewritten, and
    there is no flag to make it. See _upsert for why the escape hatch was
    removed rather than defaulted off.

    `status`, `failure_stage` and `failure_reason` are passed through
    unvalidated: the CHECK constraints in the database are the authority, and
    duplicating that vocabulary as a client-side guard would only create a
    second place for it to drift. An unknown value is rejected by Postgres and
    swallowed here like any other telemetry failure.
    """
    values: dict = {
        "status": status,
        "failure_stage": failure_stage,
        "failure_reason": _truncate_reason(failure_reason),
        "source_denied": source_denied,
        "finished_at": finished_at or _now(),
    }
    if price_observation_id is not None:
        values["price_observation_id"] = price_observation_id
    if started_at is not None:
        values["started_at"] = started_at
    return _upsert(
        operation="finish_attempt",
        batch_run_id=batch_run_id,
        source_card_mapping_id=source_card_mapping_id,
        source_id=source_id,
        values=values,
    )


def _upsert(
    *,
    operation: str,
    batch_run_id: str,
    source_card_mapping_id: int,
    source_id: int | None,
    values: dict,
) -> bool:
    """Update the row for this (run, mapping), inserting one if it is absent.

    The unique constraint on (batch_run_id, source_card_mapping_id) is what
    makes this safe: there is at most one row to find, so 'update else insert'
    cannot silently fan out into duplicate histories.

    TERMINAL ROWS ARE IMMUTABLE HERE, unconditionally. An outcome is recorded
    once; a second write is either a bug in the wiring or a retry, and either
    would quietly replace the real reason a mapping failed with a later,
    blander one. That is the exact failure this table exists to prevent, so the
    refusal is not something a caller may switch off: an earlier draft took an
    `allow_terminal_overwrite` flag, and a forensic record with a documented
    bypass is one bad call site away from not being a forensic record.

    A repeated IDENTICAL finish is refused too. Treating it as a harmless
    no-op would mean reading the values to decide, which is the beginning of a
    merge policy; and a duplicate finish is a wiring bug worth surfacing rather
    than absorbing.

    Correcting a row, if that is ever needed, will be designed deliberately -
    with its own audit trail - rather than inherited from a boolean default.
    """
    session = None
    try:
        session = SessionLocal()
        row = session.execute(
            select(SourceCollectionAttempt).where(
                SourceCollectionAttempt.batch_run_id == batch_run_id,
                SourceCollectionAttempt.source_card_mapping_id == source_card_mapping_id,
            )
        ).scalar_one_or_none()

        if row is None:
            if source_id is None:
                # Nothing to attach the row to and no honest way to guess the
                # source. Refuse rather than invent one.
                raise ValueError(
                    "no existing attempt row and no source_id supplied for "
                    f"batch_run_id={batch_run_id} mapping={source_card_mapping_id}"
                )
            row = SourceCollectionAttempt(
                batch_run_id=batch_run_id,
                source_id=source_id,
                source_card_mapping_id=source_card_mapping_id,
                selection_ordinal=None,
                status=STATUS_SELECTED,
            )
            session.add(row)

        elif _is_terminal(row):
            logger.warning(
                "%s: refusing to overwrite terminal attempt (batch=%s mapping=%s status=%s).",
                operation, batch_run_id, source_card_mapping_id, row.status,
            )
            _stdout_fallback(
                operation,
                batch_run_id=batch_run_id,
                source_card_mapping_id=source_card_mapping_id,
                refused="already_terminal",
                existing_status=row.status,
            )
            return False

        for key, value in values.items():
            setattr(row, key, value)

        session.commit()
        return True
    except Exception:
        logger.warning(
            "%s: failed to persist attempt telemetry (batch=%s mapping=%s).",
            operation,
            batch_run_id,
            source_card_mapping_id,
            exc_info=True,
        )
        _stdout_fallback(
            operation,
            batch_run_id=batch_run_id,
            source_card_mapping_id=source_card_mapping_id,
            values=values,
        )
        return False
    finally:
        if session is not None:
            _close_quietly(session)


def _close_quietly(session) -> None:
    """Even teardown must not raise into collection code."""
    try:
        session.close()
    except Exception:  # pragma: no cover - defensive
        logger.warning("telemetry: session close failed.", exc_info=True)
