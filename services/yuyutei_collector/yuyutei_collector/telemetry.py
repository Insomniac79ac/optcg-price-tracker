"""Durable telemetry and raw-evidence lineage for collector attempts.

Attempt population/start/finish telemetry remains best-effort: those functions
return a bool and raise nothing. ``persist_response_snapshot`` is deliberately
different. Raw source evidence is now a prerequisite for a price observation,
so that function either commits the snapshot plus its attempt link or raises a
typed error that makes collection fail closed.

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

The raw snapshot and attempt link share one short transaction. It commits before
classification, parsing, validation, or observation writing begins, so none of
those later paths can roll the evidence back.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from yuyutei_collector.db import SessionLocal
from yuyutei_collector.models import (
    MAX_FAILURE_REASON_LENGTH,
    RawSnapshot,
    STATUS_SELECTED,
    SourceCollectionAttempt,
)

logger = logging.getLogger(__name__)


class RawSnapshotPersistenceError(RuntimeError):
    """A response body could not be committed with its attempt lineage."""


@dataclass(frozen=True)
class RawSnapshotPersistenceResult:
    raw_snapshot_id: int
    created: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def persist_response_snapshot(
    *,
    bind,
    source_id: int,
    source_url: str,
    http_status: int | None,
    raw_content: str,
    parser_version: str,
    batch_run_id: str | None,
    source_card_mapping_id: int,
) -> RawSnapshotPersistenceResult:
    """Commit one fetched body and link it to its attempt before parsing.

    ``bind`` comes from the caller session, but this function deliberately
    creates and commits its own Session. The caller's later rollback can then
    remove a partial observation without removing the source evidence.

    For a batch attempt, the existing attempt row is locked before inspecting
    its nullable snapshot link. A repeated call for the same
    ``(batch_run_id, mapping_id)`` returns the already-linked snapshot only when
    it describes the identical response; it never inserts a duplicate. A
    different response under the same attempt identity is a conflict and fails
    closed rather than silently choosing either payload.

    The standalone mapping CLI has no attempt ledger row by design, so a
    ``batch_run_id`` of ``None`` persists the snapshot without an attempt link.
    Each standalone invocation calls this boundary once.
    """
    content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
    stored_status = http_status if http_status is not None else 0
    evidence_session = Session(bind=bind, autoflush=False, future=True)
    try:
        created = False
        snapshot_id: int | None = None
        with evidence_session.begin():
            attempt = None
            if batch_run_id is not None:
                attempt = evidence_session.execute(
                    select(SourceCollectionAttempt)
                    .where(
                        SourceCollectionAttempt.batch_run_id == batch_run_id,
                        SourceCollectionAttempt.source_card_mapping_id
                        == source_card_mapping_id,
                    )
                    .with_for_update()
                ).scalar_one_or_none()
                if attempt is None:
                    raise RawSnapshotPersistenceError("attempt_not_found")

                if attempt.raw_snapshot_id is not None:
                    snapshot = evidence_session.get(RawSnapshot, attempt.raw_snapshot_id)
                    if snapshot is None:
                        raise RawSnapshotPersistenceError("attempt_snapshot_missing")
                    same_response = (
                        snapshot.source_id == source_id
                        and snapshot.source_url == source_url
                        and snapshot.http_status == stored_status
                        and snapshot.content_hash == content_hash
                        and snapshot.raw_content == raw_content
                        and snapshot.parser_version == parser_version
                    )
                    if not same_response:
                        raise RawSnapshotPersistenceError("attempt_snapshot_conflict")
                    snapshot_id = snapshot.id

            if snapshot_id is None:
                snapshot = RawSnapshot(
                    source_id=source_id,
                    source_url=source_url,
                    fetched_at=_now(),
                    http_status=stored_status,
                    content_hash=content_hash,
                    raw_content=raw_content,
                    parser_version=parser_version,
                )
                evidence_session.add(snapshot)
                evidence_session.flush()
                snapshot_id = snapshot.id
                created = True
                if attempt is not None:
                    attempt.raw_snapshot_id = snapshot_id

        # The transaction context has committed both rows before this result is
        # made visible to the parser.
        assert snapshot_id is not None
        return RawSnapshotPersistenceResult(raw_snapshot_id=snapshot_id, created=created)
    except RawSnapshotPersistenceError as exc:
        _stdout_fallback(
            "persist_response_snapshot",
            batch_run_id=batch_run_id,
            source_card_mapping_id=source_card_mapping_id,
            failure_code=str(exc),
        )
        raise
    except Exception as exc:
        code = f"database_error:{type(exc).__name__}"
        logger.warning(
            "persist_response_snapshot: failed for batch=%s mapping=%s.",
            batch_run_id,
            source_card_mapping_id,
            exc_info=True,
        )
        _stdout_fallback(
            "persist_response_snapshot",
            batch_run_id=batch_run_id,
            source_card_mapping_id=source_card_mapping_id,
            failure_code=code,
        )
        raise RawSnapshotPersistenceError(code) from exc
    finally:
        evidence_session.close()


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
    started_at: datetime | None = None,
) -> bool:
    """Stamp started_at for one mapping - the moment processing actually began,
    as distinct from selected_at.

    Updates the row record_selected_batch already wrote, and only that: this
    table is batch-scoped, so an attempt exists exactly when it was part of a
    recorded population. With no such row there is nothing to start, and the
    call declines rather than conjuring an attempt with no position in any run.
    """
    return _update(
        operation="mark_attempt_started",
        batch_run_id=batch_run_id,
        source_card_mapping_id=source_card_mapping_id,
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
    failure_stage: str | None = None,
    failure_reason: str | None = None,
    source_denied: bool = False,
    price_observation_id: int | None = None,
    raw_snapshot_id: int | None = None,
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
    there is no flag to make it. See _update for why the escape hatch was
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
    if raw_snapshot_id is not None:
        values["raw_snapshot_id"] = raw_snapshot_id
    if started_at is not None:
        values["started_at"] = started_at
    return _update(
        operation="finish_attempt",
        batch_run_id=batch_run_id,
        source_card_mapping_id=source_card_mapping_id,
        values=values,
    )


def _update(
    *,
    operation: str,
    batch_run_id: str,
    source_card_mapping_id: int,
    values: dict,
) -> bool:
    """Update the row for this (run, mapping). Never inserts one.

    record_selected_batch is this table's only INSERT, which is what makes the
    table batch-scoped: a row exists exactly when its mapping was part of a
    recorded population. An earlier draft inserted a row here when none was
    found, to support a standalone caller, and left selection_ordinal NULL to
    describe it - but that path was never reachable from run_batch (which
    supplies no source_id), and selection_ordinal is now NOT NULL, so it could
    only ever have failed. Declining is the honest version of what it already
    did.

    The unique constraint on (batch_run_id, source_card_mapping_id) is what
    makes the lookup safe: there is at most one row to find.

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
            logger.warning(
                "%s: no selected attempt row for batch=%s mapping=%s - nothing to update.",
                operation, batch_run_id, source_card_mapping_id,
            )
            _stdout_fallback(
                operation,
                batch_run_id=batch_run_id,
                source_card_mapping_id=source_card_mapping_id,
                refused="no_selected_row",
            )
            return False

        if _is_terminal(row):
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
