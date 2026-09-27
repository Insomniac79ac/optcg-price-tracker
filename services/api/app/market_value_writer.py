"""Operator-safe Market Value archive writer.

This command is deliberately not scheduled.  It turns the existing A2 replay
adapter and A3A append-only persistence layer into three explicit operations:

* ``--dry-run`` plans a complete archive and proves existing rows are a clean
  prefix/subset, under a server-enforced read-only transaction on PostgreSQL;
* ``--verify`` requires the persisted archive to match the deterministic plan
  exactly and writes nothing;
* ``--write`` holds its own job lock and performs load, derive, append-only
  persistence, and exact verification in one REPEATABLE READ transaction.

There is no methodology here.  Point values come only from
``app.services.market_value`` via ``market_value_replay`` and are written only
through ``persist_market_value_points``.  The module has no default write mode.
"""

from __future__ import annotations

import argparse
import sys
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.market_value_point import MarketValuePoint
from app.services.job_locks import LockHeldError, with_job_lock
from app.services.market_value import METHODOLOGY_VERSION
from app.services.market_value_persistence import (
    MarketValuePointDraft,
    MarketValueVerificationResult,
    MarketValueWriteResult,
    persist_market_value_points,
    verify_market_value_points,
)
from app.services.market_value_replay import (
    MarketValueReplayInput,
    build_market_value_point_drafts,
    load_market_value_replay_input,
)


LOCK_NAME = "market_value_writer"
Mode = Literal["dry-run", "verify", "write"]


class WriterAbort(RuntimeError):
    """A fail-closed refusal.  The caller rolls the transaction back."""


@dataclass(frozen=True, slots=True)
class MarketValueWriterPlan:
    through: date | None
    drafts: tuple[MarketValuePointDraft, ...]
    verification: MarketValueVerificationResult
    overall_points: int
    release_points: int
    scope_count: int
    first_date: date | None
    last_date: date | None
    membership_revision: str
    methodology_version: int

    @property
    def expected_points(self) -> int:
        return len(self.drafts)

    @property
    def already_present(self) -> int:
        return self.verification.verified

    @property
    def to_insert(self) -> int:
        return len(self.verification.missing_keys)


@dataclass(frozen=True, slots=True)
class MarketValueWriterResult:
    mode: Mode
    plan: MarketValueWriterPlan
    inserted: int
    existing: int
    verification: MarketValueVerificationResult

    @property
    def ok(self) -> bool:
        if self.mode == "verify":
            return self.verification.ok
        return not self.verification.unexpected_keys and not self.verification.mismatches

    def report_lines(self) -> list[str]:
        cutoff = str(self.plan.through) if self.plan.through is not None else "none"
        if self.mode == "verify":
            return [
                f"mode: {self.mode}",
                f"archive_cutoff: {cutoff}",
                f"expected: {self.verification.expected}",
                f"persisted: {self.verification.persisted}",
                f"verified: {self.verification.verified}",
                f"missing: {len(self.verification.missing_keys)}",
                f"unexpected: {len(self.verification.unexpected_keys)}",
                f"mismatched: {len(self.verification.mismatches)}",
            ]
        return [
            f"mode: {self.mode}",
            f"archive_cutoff: {cutoff}",
            f"expected_points: {self.plan.expected_points}",
            f"inserted: {self.inserted}",
            f"existing: {self.existing}",
            f"verified: {self.verification.verified}",
            f"to_insert: {self.plan.to_insert if self.mode == 'dry-run' else 0}",
            f"overall_points: {self.plan.overall_points}",
            f"release_points: {self.plan.release_points}",
            f"scope_count: {self.plan.scope_count}",
            f"first_date: {self.plan.first_date}",
            f"last_date: {self.plan.last_date}",
            f"membership_revision: {self.plan.membership_revision}",
            f"methodology_version: {self.plan.methodology_version}",
        ]


def _configure_transaction(db: Session, mode: Mode) -> None:
    """Make the transaction policy the first PostgreSQL statement."""
    if db.get_bind().dialect.name != "postgresql":
        return
    if mode in ("dry-run", "verify"):
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        if db.scalar(text("SHOW transaction_read_only")) != "on":
            raise WriterAbort("PostgreSQL did not enforce a read-only transaction")
    else:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ WRITE"))
        if db.scalar(text("SHOW transaction_isolation")) != "repeatable read":
            raise WriterAbort("PostgreSQL did not enable REPEATABLE READ")
        if db.scalar(text("SHOW transaction_read_only")) != "off":
            raise WriterAbort("PostgreSQL did not enable a writable transaction")


def _require_schema(db: Session) -> None:
    if not inspect(db.connection()).has_table(MarketValuePoint.__tablename__):
        raise WriterAbort(
            "market_value_points is absent; apply the reviewed Alembic migration "
            "before using this command"
        )


def _require_supported_methodology(db: Session) -> None:
    versions = tuple(
        db.scalars(
            select(MarketValuePoint.methodology_version)
            .distinct()
            .order_by(MarketValuePoint.methodology_version)
        )
    )
    unexpected = tuple(version for version in versions if version != METHODOLOGY_VERSION)
    if unexpected:
        raise WriterAbort(
            "market_value_points contains unsupported methodology version(s): "
            + ", ".join(str(version) for version in unexpected)
        )


def _validate_release_identity(loaded: MarketValueReplayInput) -> None:
    print_ids = [row.card_print_id for row in loaded.active_prints]
    if len(print_ids) != len(set(print_ids)):
        raise WriterAbort("active catalogue contains duplicate card_print identities")
    if any(row.release_product_id <= 0 for row in loaded.active_prints):
        raise WriterAbort("active catalogue contains an invalid release_product_id")

    release_ids = [row.release_product_id for row in loaded.coded_releases]
    if len(release_ids) != len(set(release_ids)):
        raise WriterAbort("active coded releases contain duplicate identities")
    if any(
        row.release_product_id <= 0
        or not row.official_code.strip()
        or row.active_physical_print_count <= 0
        for row in loaded.coded_releases
    ):
        raise WriterAbort("active coded release identity is invalid")

    actual_counts: dict[int, int] = {}
    for row in loaded.active_prints:
        actual_counts[row.release_product_id] = (
            actual_counts.get(row.release_product_id, 0) + 1
        )
    for release in loaded.coded_releases:
        if actual_counts.get(release.release_product_id) != (
            release.active_physical_print_count
        ):
            raise WriterAbort(
                "active coded release count disagrees with CardPrint.release_product_id "
                f"for release_product_id={release.release_product_id}"
            )


def _build_plan(db: Session, through: date | None) -> MarketValueWriterPlan:
    _require_schema(db)
    _require_supported_methodology(db)
    loaded = load_market_value_replay_input(
        db, through=through, include_current=False
    )
    _validate_release_identity(loaded)
    drafts = build_market_value_point_drafts(loaded)

    keys = [draft.natural_key for draft in drafts]
    if len(keys) != len(set(keys)):
        raise WriterAbort("deterministic replay produced duplicate natural keys")
    if any(draft.methodology_version != METHODOLOGY_VERSION for draft in drafts):
        raise WriterAbort("deterministic replay produced an unsupported methodology")
    if through is not None and any(draft.point_date > through for draft in drafts):
        raise WriterAbort("deterministic replay produced a point after the cutoff")

    verification = verify_market_value_points(
        db, drafts, exact_archive=True, through=through
    )
    overall_points = sum(row.scope_kind == "overall" for row in drafts)
    release_points = len(drafts) - overall_points
    return MarketValueWriterPlan(
        through=through,
        drafts=drafts,
        verification=verification,
        overall_points=overall_points,
        release_points=release_points,
        scope_count=1 + len(loaded.coded_releases),
        first_date=loaded.archive_dates[0] if loaded.archive_dates else None,
        last_date=loaded.archive_dates[-1] if loaded.archive_dates else None,
        membership_revision=loaded.catalogue_membership_revision,
        methodology_version=METHODOLOGY_VERSION,
    )


def _natural_key_sample(keys: tuple[object, ...]) -> str:
    rendered = ", ".join(str(key) for key in keys[:5])
    if len(keys) > 5:
        rendered += f", ... ({len(keys)} total)"
    return rendered


def _require_coherent_extension(plan: MarketValueWriterPlan) -> None:
    verification = plan.verification
    if verification.unexpected_keys:
        raise WriterAbort(
            "persisted archive contains unexpected natural keys: "
            + _natural_key_sample(verification.unexpected_keys)
        )
    if verification.mismatches:
        detail = tuple(
            (mismatch.natural_key, mismatch.fields)
            for mismatch in verification.mismatches
        )
        raise WriterAbort(
            "persisted archive conflicts with deterministic replay: "
            + _natural_key_sample(detail)
        )


def _execute(db: Session, *, mode: Mode, through: date | None) -> MarketValueWriterResult:
    try:
        _configure_transaction(db, mode)
        plan = _build_plan(db, through)

        if mode == "verify":
            verification = plan.verification
            db.rollback()
            return MarketValueWriterResult(
                mode=mode,
                plan=plan,
                inserted=0,
                existing=verification.verified,
                verification=verification,
            )

        _require_coherent_extension(plan)
        if mode == "dry-run":
            db.rollback()
            return MarketValueWriterResult(
                mode=mode,
                plan=plan,
                inserted=0,
                existing=plan.already_present,
                verification=plan.verification,
            )

        write_result: MarketValueWriteResult = persist_market_value_points(
            db, plan.drafts
        )
        final = verify_market_value_points(
            db, plan.drafts, exact_archive=True, through=through
        )
        if not final.ok:
            raise WriterAbort(
                "post-write verification failed: "
                f"missing={len(final.missing_keys)} "
                f"unexpected={len(final.unexpected_keys)} "
                f"mismatched={len(final.mismatches)}"
            )
        if write_result.verified != final.expected:
            raise WriterAbort(
                "persistence verification count disagrees with exact archive verification"
            )
        db.commit()
        return MarketValueWriterResult(
            mode=mode,
            plan=plan,
            inserted=write_result.inserted,
            existing=write_result.existing,
            verification=final,
        )
    except Exception:
        db.rollback()
        raise


def run_writer(
    db: Session,
    *,
    mode: Mode,
    through: date | None = None,
    skip_lock: bool = False,
) -> MarketValueWriterResult:
    """Run one explicit mode. ``skip_lock`` is for isolated tests only."""
    if mode not in ("dry-run", "verify", "write"):
        raise ValueError(f"unsupported market value writer mode: {mode}")
    lock = (
        with_job_lock(
            LOCK_NAME,
            metadata={"mode": mode, "through": str(through) if through else None},
        )
        if mode == "write" and not skip_lock
        else nullcontext()
    )
    with lock:
        return _execute(db, mode=mode, through=through)


def _date_argument(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}; expected YYYY-MM-DD"
        ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.market_value_writer",
        description=(
            "Dry-run, verify, or explicitly seed the deterministic Market "
            "Value archive. No mode is implicit."
        ),
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true", help="Plan only; write nothing.")
    modes.add_argument("--verify", action="store_true", help="Require an exact persisted replay.")
    modes.add_argument(
        "--write",
        action="store_true",
        help="Persist and verify atomically under the Market Value writer lock.",
    )
    parser.add_argument(
        "--through",
        type=_date_argument,
        metavar="YYYY-MM-DD",
        help="Read and persist archive points only through this UTC date.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    mode: Mode = "dry-run" if args.dry_run else "verify" if args.verify else "write"
    db = SessionLocal()
    try:
        try:
            result = run_writer(db, mode=mode, through=args.through)
        except LockHeldError as exc:
            print(
                f"ABORTED, nothing written: writer lock held by {exc.owner_id} "
                f"until {exc.expires_at.isoformat()}",
                file=sys.stderr,
            )
            return 2
        except Exception as exc:
            print(f"ABORTED, nothing written: {exc}", file=sys.stderr)
            return 1

        for line in result.report_lines():
            print(line)
        if not result.ok:
            verification = result.verification
            if verification.missing_keys:
                print(
                    "missing keys: " + _natural_key_sample(verification.missing_keys),
                    file=sys.stderr,
                )
            if verification.unexpected_keys:
                print(
                    "unexpected keys: "
                    + _natural_key_sample(verification.unexpected_keys),
                    file=sys.stderr,
                )
            if verification.mismatches:
                detail = tuple(
                    (item.natural_key, item.fields)
                    for item in verification.mismatches
                )
                print(
                    "mismatched keys: " + _natural_key_sample(detail),
                    file=sys.stderr,
                )
        return 0 if result.ok else 1
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
