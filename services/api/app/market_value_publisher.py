"""Receipt-gated forward Market Value publication; no historical backfill.

Normal operator path: ``python -m app.market_value_publisher --write``.
``--date`` selects one receipt-backed date; ``--dry-run`` uses the same plan
in a read-only transaction. Historical recovery remains in market_value_writer.
"""

from __future__ import annotations

import argparse
import sys
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.market_value_writer import (
    LOCK_NAME,
    WriterAbort,
    _configure_transaction,
    _date_argument,
    _require_schema,
    _require_supported_methodology,
    _validate_release_identity,
)
from app.models.job_lock import JobLock
from app.models.market_index_snapshot_completion import MarketIndexSnapshotCompletion
from app.models.market_value_point import MarketValuePoint
from app.services.job_locks import LockHeldError, with_job_lock
from app.services.market_index_completion import (
    SnapshotCompletionVerification,
    verify_market_index_snapshot_completion,
)
from app.services.market_value_persistence import (
    MarketValuePointDraft,
    persist_market_value_points,
    verify_market_value_points,
)
from app.services.market_value_replay import (
    build_market_value_point_drafts,
    load_market_value_replay_input,
)

Mode = Literal["dry-run", "write"]


@dataclass(frozen=True)
class ForwardPublicationPlan:
    previous_as_of: date | None
    requested_date: date | None
    publication_dates: tuple[date, ...]
    drafts: tuple[MarketValuePointDraft, ...]
    new_drafts: tuple[MarketValuePointDraft, ...]
    existing_verified: int
    receipts: tuple[SnapshotCompletionVerification, ...]


@dataclass(frozen=True)
class ForwardPublicationResult:
    mode: Mode
    plan: ForwardPublicationPlan
    inserted: int

    def report_lines(self) -> list[str]:
        return [
            "operation: receipt-gated-forward-publication",
            f"mode: {self.mode}",
            f"requested_date: {self.plan.requested_date or 'all-new'}",
            f"previous_as_of: {self.plan.previous_as_of}",
            "publication_dates: "
            + (", ".join(map(str, self.plan.publication_dates)) or "none"),
            f"receipts_verified: {len(self.plan.receipts)}",
            f"existing_verified: {self.plan.existing_verified}",
            f"planned_new_points: {len(self.plan.new_drafts)}",
            f"inserted: {self.inserted}",
        ]


def _guard_snapshot_producer(db: Session, mode: Mode) -> None:
    statement = select(JobLock.status).where(
        JobLock.lock_name == "market_index_snapshot"
    )
    if mode == "write" and db.get_bind().dialect.name == "postgresql":
        # Keep the producer's released row stable through our data commit.
        # Its normal acquire UPDATE cannot pass this shared row lock. NOWAIT
        # refuses a concurrent transition; REPEATABLE READ also refuses a row
        # changed since our snapshot. Never acquire/force-release its job lock.
        statement = statement.with_for_update(read=True, nowait=True)
    status = db.scalar(statement)
    if status == "active":
        raise WriterAbort("snapshot_in_progress")
    if status is None and mode == "write":
        raise WriterAbort(
            "snapshot producer lock row is missing; cannot guard publication"
        )


def _build_plan(db: Session, requested_date: date | None) -> ForwardPublicationPlan:
    _require_schema(db)
    _require_supported_methodology(db)
    if not inspect(db.connection()).has_table(
        MarketIndexSnapshotCompletion.__tablename__
    ):
        raise WriterAbort("snapshot completion schema is absent")

    published_dates = tuple(
        db.scalars(
            select(MarketValuePoint.point_date)
            .distinct()
            .order_by(MarketValuePoint.point_date)
        )
    )
    latest = published_dates[-1] if published_dates else None
    receipt_dates = tuple(
        db.scalars(
            select(MarketIndexSnapshotCompletion.snapshot_date).order_by(
                MarketIndexSnapshotCompletion.snapshot_date
            )
        )
    )
    if len(receipt_dates) != len(set(receipt_dates)):
        raise WriterAbort("duplicate_receipt")

    if requested_date is not None:
        if requested_date not in receipt_dates:
            raise WriterAbort(f"receipt_missing: {requested_date}")
        if latest is not None and requested_date <= latest:
            if requested_date not in published_dates:
                raise WriterAbort(
                    "requested date is behind the publication head; no backfill"
                )
            new_dates = ()  # verify the immutable prefix, including this receipt
        else:
            new_dates = (requested_date,)
    else:
        new_dates = tuple(
            day for day in receipt_dates if latest is None or day > latest
        )

    # Legacy published history can be receipt-less; it is verified separately
    # against persisted facts below. Every receipt we actually reference,
    # including one on an already published date, must pass the C1B0 gate.
    referenced_dates = set(published_dates) | set(new_dates)
    receipts = []
    for day in receipt_dates:
        if day not in referenced_dates:
            continue
        evidence = verify_market_index_snapshot_completion(db, day)
        if not evidence.valid:
            raise WriterAbort(
                f"invalid snapshot completion for {day}: {evidence.failure_reasons}"
            )
        receipts.append(evidence)

    dates = tuple(sorted(referenced_dates))
    loaded = load_market_value_replay_input(
        db, archive_dates=dates, include_current=False
    )
    _validate_release_identity(loaded)
    if loaded.archive_dates != dates:
        raise WriterAbort("publication dates lack eligible archived snapshot inputs")
    drafts = build_market_value_point_drafts(loaded)
    # The unchanged engine receives only actual publication dates. Its existing
    # gap rule resets movement segments; receipt-less days never bridge a gap.
    historical = tuple(row for row in drafts if row.point_date in published_dates)
    prefix = verify_market_value_points(db, historical, exact_archive=True)
    if not prefix.ok:
        raise WriterAbort(
            "persisted publication history conflicts with deterministic replay: "
            f"missing={len(prefix.missing_keys)} unexpected={len(prefix.unexpected_keys)} "
            f"mismatched={len(prefix.mismatches)}"
        )
    new_drafts = tuple(row for row in drafts if row.point_date in new_dates)
    return ForwardPublicationPlan(
        latest,
        requested_date,
        new_dates,
        drafts,
        new_drafts,
        prefix.verified,
        tuple(receipts),
    )


def run_publisher(
    db: Session,
    *,
    mode: Mode,
    publication_date: date | None = None,
    skip_lock: bool = False,
) -> ForwardPublicationResult:
    """One writer lock and one consistent data transaction; test-only skip_lock.

    Receipts are verified before the SQL date allowlist is loaded, in the same
    REPEATABLE READ transaction as prefix verification, derivation and commit.
    Dry runs are server-enforced read-only and never write job lock metadata.
    """
    if mode not in ("dry-run", "write"):
        raise ValueError(f"unsupported publication mode: {mode}")
    if db.in_transaction():
        raise WriterAbort("forward publication requires a fresh transaction")
    lock = (
        with_job_lock(
            LOCK_NAME,
            metadata={
                "operation": "forward",
                "date": str(publication_date) if publication_date else None,
            },
        )
        if mode == "write" and not skip_lock
        else nullcontext()
    )
    with lock:
        try:
            _configure_transaction(db, mode)
            _guard_snapshot_producer(db, mode)
            plan = _build_plan(db, publication_date)
            if mode == "dry-run" or not plan.new_drafts:
                db.rollback()
                return ForwardPublicationResult(mode, plan, 0)
            result = persist_market_value_points(db, plan.new_drafts)
            verified = verify_market_value_points(db, plan.drafts, exact_archive=True)
            if not verified.ok:
                raise WriterAbort("post-publication verification failed")
            db.commit()
            return ForwardPublicationResult(mode, plan, result.inserted)
        except Exception:
            db.rollback()
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run", action="store_true", help="Verify and plan; write nothing."
    )
    mode.add_argument(
        "--write", action="store_true", help="Append only new receipt-backed dates."
    )
    parser.add_argument(
        "--date", type=_date_argument, help="One completed UTC date; no backfill."
    )
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        try:
            result = run_publisher(
                db,
                mode="write" if args.write else "dry-run",
                publication_date=args.date,
            )
        except LockHeldError as exc:
            print(
                f"ABORTED, nothing published: writer lock held: {exc.lock_name}",
                file=sys.stderr,
            )
            return 2
        except Exception as exc:
            print(f"ABORTED, nothing published: {exc}", file=sys.stderr)
            return 1
        print("\n".join(result.report_lines()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
