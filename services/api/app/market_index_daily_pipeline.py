"""Coordinate one snapshot and its receipt-gated downstream index writers.

This is an opt-in Railway command. Collectors remain separately scheduled.
Each existing writer owns its own transaction and job lock; this module only
orders them, verifies the committed snapshot, and reports independent outcomes.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import select

from app import card_pirate_index_writer, market_value_publisher, snapshot_market_index
from app.db import SessionLocal
from app.models.job_lock import JobLock
from app.services.job_locks import LockHeldError, with_job_lock
from app.services.market_index_completion import (
    utc,
    verify_market_index_snapshot_completion,
)

LOCK_NAME = "market_index_daily_pipeline"


@dataclass(frozen=True)
class Stage:
    status: str
    dates: tuple[date, ...] = ()
    inserted: int = 0
    reason: str | None = None


@dataclass(frozen=True)
class PipelineResult:
    snapshot: Stage
    receipt: Stage
    market_value: Stage
    card_pirate_index: Stage

    @property
    def exit_code(self) -> int:
        statuses = (
            self.snapshot,
            self.receipt,
            self.market_value,
            self.card_pirate_index,
        )
        if any(stage.status == "locked" for stage in statuses):
            return 2
        return 1 if any(stage.status == "failed" for stage in statuses) else 0

    def report(self) -> str:
        return json.dumps(
            {**asdict(self), "exit_code": self.exit_code},
            default=str,
            sort_keys=True,
        )


SKIPPED = Stage("skipped")


def _failure(exc: Exception) -> Stage:
    return Stage(
        "locked" if isinstance(exc, LockHeldError) else "failed", reason=str(exc)
    )


def _guard_producer(db) -> None:
    """Keep the producer's released lock row stable through both downstream jobs.

    PostgreSQL's shared NOWAIT row lock prevents a new producer acquire UPDATE
    until this transaction ends. It is compatible with the forward publisher's
    own shared guard. SQLite tests still check the row's state explicitly.
    """
    statement = select(JobLock.status).where(
        JobLock.lock_name == "market_index_snapshot"
    )
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(read=True, nowait=True)
    status = db.scalar(statement)
    if status != "released":
        raise ValueError(
            "snapshot_in_progress"
            if status == "active"
            else "snapshot producer lock is missing or not released"
        )


def _run_locked() -> PipelineResult:
    try:
        with SessionLocal() as db:
            snapshot = snapshot_market_index.snapshot_market_index(db)
    except Exception as exc:
        return PipelineResult(_failure(exc), SKIPPED, SKIPPED, SKIPPED)

    if (
        snapshot.completion_status == "empty_selection"
        and snapshot.prints_selected == 0
    ):
        return PipelineResult(
            Stage("empty", reason="empty_selection: no receipt or publication"),
            SKIPPED,
            SKIPPED,
            SKIPPED,
        )
    day = snapshot.snapshot_date  # The producer's UTC day, even across midnight.
    snapshot_stage = Stage(
        "no_op" if snapshot.completion_status == "verified_existing" else "succeeded",
        dates=(day,) if day is not None else (),
        inserted=snapshot.rows_created,
    )
    if (
        day is None
        or snapshot.calculated_at is None
        or not snapshot.completion_verified
        or snapshot.completion_status not in ("verified_new", "verified_existing")
    ):
        return PipelineResult(
            snapshot_stage,
            Stage("failed", reason="snapshot returned no verified completion"),
            SKIPPED,
            SKIPPED,
        )

    # A new session and transaction begin after the producer's session closed
    # and its lock was released. The verifier reads durable database evidence.
    try:
        with SessionLocal() as db:
            _guard_producer(db)
            evidence = verify_market_index_snapshot_completion(db, day)
            if not evidence.valid:
                raise ValueError(", ".join(evidence.failure_reasons))
            if (
                evidence.snapshot_date != day
                or evidence.calculated_at != utc(snapshot.calculated_at)
                or evidence.expected_rows != snapshot.prints_selected
            ):
                raise ValueError("committed receipt differs from snapshot result")
            result = _run_downstream(snapshot_stage, Stage("verified", dates=(day,)))
            return result
    except Exception as exc:
        return PipelineResult(snapshot_stage, _failure(exc), SKIPPED, SKIPPED)


def _run_downstream(snapshot_stage: Stage, receipt_stage: Stage) -> PipelineResult:
    try:
        with SessionLocal() as db:
            published = market_value_publisher.run_publisher(db, mode="write")
        market_value_stage = Stage(
            "succeeded" if published.inserted else "no_op",
            dates=published.plan.publication_dates,
            inserted=published.inserted,
        )
    except Exception as exc:
        market_value_stage = _failure(exc)

    try:
        with SessionLocal() as db:
            written = card_pirate_index_writer.run_writer(db)
        if not written.verified:
            raise ValueError("Card Pirate Index extension verification failed")
        cpi_stage = Stage(
            "succeeded" if written.inserted else "no_op",
            dates=tuple(point.point_date for point in written.plan.planned),
            inserted=written.inserted,
        )
    except Exception as exc:
        cpi_stage = _failure(exc)

    return PipelineResult(snapshot_stage, receipt_stage, market_value_stage, cpi_stage)


def run_pipeline() -> PipelineResult:
    try:
        with with_job_lock(LOCK_NAME):
            return _run_locked()
    except Exception as exc:
        return PipelineResult(_failure(exc), SKIPPED, SKIPPED, SKIPPED)


def main() -> int:
    result = run_pipeline()
    print(result.report())
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
