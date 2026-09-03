"""Read-only queries over source_collection_attempts.

WHY THIS EXISTS. Collector events are stdout prints, and Railway retains them
unevenly - on 2026-09-02 the 214-mapping batch left 23 of 214 mappings with no
retained homepage line and mapping 391 with no retained outcome at all, so its
failure is permanently unexplainable. source_collection_attempts is the durable
answer; this module is how an operator reads it without opening psql.

CONTEXT IS RESOLVED, NEVER FABRICATED. The attempt row stores source_id and
source_card_mapping_id as plain integers with no foreign key, precisely so the
history outlives the rows it describes (mappings are retired with
is_active = False and never hard-deleted, but the table is built to survive one
anyway). That means the joins below are OUTER joins by necessity: when a
mapping has genuinely gone, `mapping_resolved` is False and the print/card
fields are None. The stored ids remain authoritative and are always returned;
nothing here invents a card code for an id it cannot resolve.

READ-ONLY. Nothing in this module writes, and there is no counterpart that
does: telemetry is written exclusively by the collector services.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import (
    CanonicalCard,
    CardPrint,
    Source,
    SourceCardMapping,
    SourceCollectionAttempt,
)

# Mirrors the CHECK constraints in b8e3f1a70d95. Used to reject an unknown
# filter value with a 400 rather than silently returning nothing, which would
# read as "no such attempts" instead of "you asked for a status that cannot
# exist".
STATUSES = (
    "selected",
    "written",
    "validation_failed",
    "no_extraction_attempted",
    "operational_error",
    "mapping_load_failed",
    "skipped",
)

FAILURE_STAGES = (
    "load",
    "browser_launch",
    "homepage",
    "product",
    "extraction",
    "validation",
    "write",
)

# 'selected' is the only non-terminal status - it covers both not-yet-started
# and in-flight (see the model). Everything else is an outcome.
NON_TERMINAL_STATUS = "selected"


@dataclass
class AttemptRow:
    """One attempt plus whatever context could still be resolved for it."""

    attempt: SourceCollectionAttempt
    source_name: str | None
    mapping_resolved: bool
    card_print_id: int | None
    card_code: str | None

    @property
    def duration_seconds(self) -> float | None:
        """Derived at read time from the two stored timestamps - deliberately
        not a column. A skipped attempt has no start, so it has no duration;
        an in-flight one has no finish yet."""
        started = self.attempt.started_at
        finished = self.attempt.finished_at
        if started is None or finished is None:
            return None
        return (finished - started).total_seconds()


@dataclass
class AttemptSummary:
    """Aggregated over the whole FILTERED set, not just the returned page - so
    filtering to one batch_run_id answers 'what happened in that run?' without
    paging through it."""

    total_attempts: int
    started: int
    written: int
    skipped: int
    source_denied: int
    still_selected: int
    by_status: dict[str, int]
    by_failure_stage: dict[str, int]
    earliest_selected_at: datetime | None
    latest_finished_at: datetime | None


@dataclass
class AttemptListResult:
    rows: list[AttemptRow]
    total: int
    summary: AttemptSummary


def _filters(
    *,
    batch_run_id: str | None,
    source_id: int | None,
    source_card_mapping_id: int | None,
    status: str | None,
    failure_stage: str | None,
    source_denied: bool | None,
) -> list:
    clauses = []
    if batch_run_id is not None:
        clauses.append(SourceCollectionAttempt.batch_run_id == batch_run_id)
    if source_id is not None:
        clauses.append(SourceCollectionAttempt.source_id == source_id)
    if source_card_mapping_id is not None:
        clauses.append(
            SourceCollectionAttempt.source_card_mapping_id == source_card_mapping_id
        )
    if status is not None:
        clauses.append(SourceCollectionAttempt.status == status)
    if failure_stage is not None:
        clauses.append(SourceCollectionAttempt.failure_stage == failure_stage)
    if source_denied is not None:
        clauses.append(SourceCollectionAttempt.source_denied.is_(source_denied))
    return clauses


def _with_context(stmt: Select) -> Select:
    """OUTER joins only. A row whose mapping or source has gone must still be
    returned - losing the evidence because its subject was deleted is the
    failure this table exists to prevent."""
    return (
        stmt.outerjoin(Source, Source.id == SourceCollectionAttempt.source_id)
        .outerjoin(
            SourceCardMapping,
            SourceCardMapping.id == SourceCollectionAttempt.source_card_mapping_id,
        )
        .outerjoin(CardPrint, CardPrint.id == SourceCardMapping.card_print_id)
        .outerjoin(CanonicalCard, CanonicalCard.id == CardPrint.canonical_card_id)
    )


def list_collection_attempts(
    db: Session,
    *,
    batch_run_id: str | None = None,
    source_id: int | None = None,
    source_card_mapping_id: int | None = None,
    status: str | None = None,
    failure_stage: str | None = None,
    source_denied: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> AttemptListResult:
    """Attempts matching the filters, newest first, plus a summary of the whole
    filtered set.

    Ordering is selected_at DESC then id DESC: selected_at is NOT NULL on every
    row (started_at is not), and the whole population of one batch shares a
    single selected_at, so id breaks that tie deterministically rather than
    leaving page boundaries to the planner.
    """
    clauses = _filters(
        batch_run_id=batch_run_id,
        source_id=source_id,
        source_card_mapping_id=source_card_mapping_id,
        status=status,
        failure_stage=failure_stage,
        source_denied=source_denied,
    )

    total = (
        db.scalar(
            select(func.count()).select_from(SourceCollectionAttempt).where(*clauses)
        )
        or 0
    )

    stmt = _with_context(
        select(
            SourceCollectionAttempt,
            Source.name,
            SourceCardMapping.id,
            SourceCardMapping.card_print_id,
            CanonicalCard.card_code,
        )
    ).where(*clauses)
    stmt = stmt.order_by(
        SourceCollectionAttempt.selected_at.desc(), SourceCollectionAttempt.id.desc()
    ).limit(limit).offset(offset)

    rows = [
        AttemptRow(
            attempt=attempt,
            source_name=source_name,
            mapping_resolved=mapping_id is not None,
            card_print_id=card_print_id,
            card_code=card_code,
        )
        for attempt, source_name, mapping_id, card_print_id, card_code in db.execute(stmt).all()
    ]

    return AttemptListResult(rows=rows, total=total, summary=_summary(db, clauses, total))


def _summary(db: Session, clauses: list, total: int) -> AttemptSummary:
    by_status = dict(
        db.execute(
            select(SourceCollectionAttempt.status, func.count())
            .where(*clauses)
            .group_by(SourceCollectionAttempt.status)
        ).all()
    )
    by_failure_stage = dict(
        db.execute(
            select(SourceCollectionAttempt.failure_stage, func.count())
            .where(*clauses, SourceCollectionAttempt.failure_stage.is_not(None))
            .group_by(SourceCollectionAttempt.failure_stage)
        ).all()
    )

    started = (
        db.scalar(
            select(func.count())
            .select_from(SourceCollectionAttempt)
            .where(*clauses, SourceCollectionAttempt.started_at.is_not(None))
        )
        or 0
    )
    denied = (
        db.scalar(
            select(func.count())
            .select_from(SourceCollectionAttempt)
            .where(*clauses, SourceCollectionAttempt.source_denied.is_(True))
        )
        or 0
    )
    bounds = db.execute(
        select(
            func.min(SourceCollectionAttempt.selected_at),
            func.max(SourceCollectionAttempt.finished_at),
        ).where(*clauses)
    ).one()

    return AttemptSummary(
        total_attempts=total,
        started=started,
        written=by_status.get("written", 0),
        skipped=by_status.get("skipped", 0),
        source_denied=denied,
        still_selected=by_status.get(NON_TERMINAL_STATUS, 0),
        by_status=by_status,
        by_failure_stage=by_failure_stage,
        earliest_selected_at=bounds[0],
        latest_finished_at=bounds[1],
    )
