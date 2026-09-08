"""The daily Card Pirate Index writer - one shot, forward only, insert only.

WHAT THIS MODULE IS
-------------------
The scheduled job that keeps `card_pirate_index_points` level with
`market_index_snapshots`. It answers exactly one question - "which days does
the archive now support that the table does not yet hold?" - and then hands
the answer to the committed replay machinery.

WHAT IT DELIBERATELY IS NOT
---------------------------
It contains no estimator. There is no step calculation, no cap, no chaining,
no change math, no contributor-eligibility rule and no methodology constant
anywhere below. Every one of those lives in `app.services.card_pirate_index`
and reaches the database through `app.services.card_pirate_index_replay`. A
second implementation of any of them would be a second methodology, and the
whole point of freezing METHODOLOGY_VERSION = 1 is that there is only one.

Concretely, this module's entire contribution is:

  * WHERE the chain starts        -> `V1_OVERALL_SEED.history_start`, read, never derived
  * WHERE the writing starts      -> the day after the persisted head
  * WHETHER writing is allowed    -> `verify_scope` must already pass
  * WHETHER the write survives    -> `verify_scope` must still pass, in-transaction
  * WHAT the transaction boundary is

THE HEAD IS THE ONLY PLACE IT WRITES
------------------------------------
`replay_scope` on its own would happily fill a hole anywhere in the series,
because a hole is simply a date it computed and did not find stored. That is
correct behaviour for an operator-driven replay and wrong for an unattended
daily job: a hole BEHIND the head means either the archive changed under a
published point or a previous run wrote a partial day, and both of those are
alarms a human must look at, not gaps to paper over at 20:05 UTC. So the
writer refuses to run at all unless the persisted range already verifies
clean, and then writes strictly after the head via `start=`.

That refusal is the same reasoning `verify_scope` already applies to a value
mismatch: "a mismatch between the archive and a stored point is evidence of a
bug, and the correct response is to investigate it, not to overwrite the
record of what was published." A silently backfilled hole is the same class of
event, so it gets the same treatment.

NO FORWARD-FILL, NO FABRICATION
-------------------------------
The writer never invents a date. It writes the days `build_points` produced,
and `build_points` produces a point only for an archive day that actually has
valued snapshots (`if not day.observations: continue`). A day the Market Index
job never archived is simply not in the series, so a missed archive day stays
a real gap in the record - rendered as `step_days > 1` and a `snapshot_gap`
break - rather than becoming a flat repeat of yesterday.

Equally, being offline for a week is not a reset. The chain is always built
from `history_start`, so a catch-up run reproduces exactly the points the
daily runs would have written, in ascending date order, carries intact.

TRANSACTION BOUNDARY
--------------------
One transaction for the whole run: plan, pre-verify, insert, prove the
pre-existing rows are byte-identical, re-verify the whole scope, commit. Any
failure anywhere raises and rolls back, so a refused run leaves the database
exactly as it found it. The verification that authorises the commit reads
through the same uncommitted session, so it is checking the rows that are
about to become permanent, not the ones that were there before.

READ-ONLY PATHS TAKE NO LOCK
----------------------------
`--dry-run` and `--verify` never touch the job-lock table. That is not an
oversight: acquiring a lock is a write, and these two paths exist precisely so
they can be pointed at a `SET TRANSACTION READ ONLY` session against canonical
staging. Only the write path locks.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.card_pirate_index_point import CardPirateIndexPoint
from app.models.market_index_snapshot import MarketIndexSnapshot
from app.services.card_pirate_index import (
    V1_OVERALL_SEED,
    ScopeSeries,
    SeedSpec,
)
from app.services.card_pirate_index_replay import (
    DISCREPANCY_MISSING_POINT,
    Discrepancy,
    VerifyResult,
    build_scope_series,
    replay_scope,
    verify_scope,
)
from app.services.job_locks import LockHeldError, with_job_lock

# Matches `market_index_snapshot` at 600 s (methodology section 15, step 7).
# The two jobs run back to back in one container, so the index job's lock is
# held for the tail of the same window the snapshot job's was.
LOCK_NAME = "card_pirate_index"


class WriterAbort(RuntimeError):
    """The run refused to proceed. The transaction is rolled back by the
    caller, so nothing was written.

    Every raise site below is a fail-closed decision, never a partial success:
    there is no "wrote some points then noticed a problem" outcome, because
    the only commit in this module is the last statement of the write path.
    """


# --- the plan ---------------------------------------------------------------


@dataclass(frozen=True)
class PlannedPoint:
    """One point the run intends to write, in reportable form.

    A flattened projection of a `PointDraft`, carrying the carry by DATE
    rather than by id - the same natural-identity rule the replay module
    follows, and for the same reason: the id does not exist yet.
    """

    point_date: date
    index_value: Decimal | None
    is_base: bool
    carried_from_point_date: date | None
    prior_point_date: date | None
    step_days: int | None
    chain_link_log_return: Decimal | None
    constituent_count: int
    eligible_print_count: int
    unpublishable_reason: str | None

    def report_line(self) -> str:
        if self.unpublishable_reason is not None:
            return f"  {self.point_date}  UNPUBLISHABLE  {self.unpublishable_reason}"
        shape = "base" if self.is_base else "step"
        carry = (
            f" carried_from={self.carried_from_point_date}"
            if self.carried_from_point_date is not None
            else ""
        )
        return (
            f"  {self.point_date}  {self.index_value}  {shape}{carry}"
            f"  n={self.constituent_count}/{self.eligible_print_count}"
            f"  step_days={self.step_days}"
        )


@dataclass(frozen=True)
class WriterPlan:
    scope_kind: str
    scope_key: str
    methodology_version: int
    history_start: date
    latest_persisted_point_date: date | None
    latest_archive_day: date | None
    stored_point_count: int
    planned: tuple[PlannedPoint, ...]

    @property
    def first_write_date(self) -> date | None:
        return self.planned[0].point_date if self.planned else None

    def report_lines(self) -> list[str]:
        lines = [
            f"scope: {self.scope_kind}/{self.scope_key or '-'} "
            f"methodology_version={self.methodology_version}",
            f"history_start: {self.history_start}",
            f"stored_points: {self.stored_point_count}",
            f"latest_persisted_point: {self.latest_persisted_point_date}",
            f"latest_archive_day: {self.latest_archive_day}",
            f"planned_inserts: {len(self.planned)}",
        ]
        lines.extend(p.report_line() for p in self.planned)
        return lines


@dataclass(frozen=True)
class WriterRunResult:
    plan: WriterPlan
    dry_run: bool
    inserted: int
    persisted_verified: bool
    extension: "ExtensionResult"

    @property
    def verified(self) -> bool:
        """Both subjects clean: the rows that exist AND the rows that are
        about to. Kept as a derived property rather than a stored flag so the
        two can never be reported as one number that hides which failed."""
        return self.persisted_verified and self.extension.ok

    def report_lines(self) -> list[str]:
        lines = [
            *self.plan.report_lines(),
            f"dry_run: {self.dry_run}",
            f"inserted: {self.inserted}",
            f"persisted_verified: {self.persisted_verified}",
            f"planned_extension_verified: {self.extension.ok}",
        ]
        lines.extend(f"  {d}" for d in self.extension.discrepancies)
        return lines


# --- reads ------------------------------------------------------------------


def _stored_rows(db: Session, seed: SeedSpec) -> list[tuple]:
    """Every stored row for the scope, ACROSS ALL methodology versions.

    Deliberately not filtered to the seed's version: a row under a different
    methodology_version for the same scope is exactly the inconsistency this
    job must refuse on, and a filtered query would hide it.
    """
    return list(
        db.execute(
            select(
                CardPirateIndexPoint.point_date,
                CardPirateIndexPoint.methodology_version,
            )
            .where(
                CardPirateIndexPoint.scope_kind == seed.scope_kind,
                CardPirateIndexPoint.scope_key == seed.scope_key,
            )
            .order_by(CardPirateIndexPoint.point_date)
        )
    )


def _latest_archive_day(db: Session) -> date | None:
    """The newest day the archive can actually contribute to a chain.

    `index_value_jpy IS NOT NULL` matches `load_snapshot_days` exactly. A day
    of nothing but `coverage_status='none'` rows is an absence, not a day, and
    treating it as the archive head would make the writer report a target it
    can never reach.
    """
    return db.scalar(
        select(func.max(MarketIndexSnapshot.snapshot_date)).where(
            MarketIndexSnapshot.index_value_jpy.is_not(None)
        )
    )


def _to_planned(draft) -> PlannedPoint:
    return PlannedPoint(
        point_date=draft.point_date,
        index_value=draft.index_value,
        is_base=draft.is_base,
        carried_from_point_date=draft.carried_from_key,
        prior_point_date=draft.prior_point_date,
        step_days=draft.step_days,
        chain_link_log_return=draft.chain_link_log_return,
        constituent_count=draft.constituent_count,
        eligible_print_count=draft.eligible_print_count,
        unpublishable_reason=draft.unpublishable_reason,
    )


def plan_write(
    db: Session, seed: SeedSpec = V1_OVERALL_SEED
) -> tuple[WriterPlan, ScopeSeries]:
    """Decide what this run would write. READS ONLY - no INSERT, no lock.

    Fails closed, before anything is written, on:

      * a stored point under a different methodology_version for this scope
      * a stored point earlier than the scope's declared history_start
      * an archive that no longer reaches the persisted head
      * any discrepancy at all between the persisted range and a fresh replay,
        which covers a hole behind the head, a point the archive does not
        produce, a changed field, and every carry-chain violation

    The last one is the important one, and it is `verify_scope` unmodified.
    The writer does not get its own, weaker, opinion about whether the stored
    series is sound.
    """
    stored = _stored_rows(db, seed)
    scope_label = f"{seed.scope_kind}/{seed.scope_key or '-'}"

    wrong_version = sorted(
        {row.methodology_version for row in stored}
        - {seed.methodology_version}
    )
    if wrong_version:
        raise WriterAbort(
            f"{scope_label}: stored points exist under methodology_version(s) "
            f"{wrong_version}, but this writer only serves "
            f"methodology_version={seed.methodology_version}. Refusing to "
            "write beside a series it does not understand."
        )

    before_history = [
        row.point_date for row in stored if row.point_date < seed.history_start
    ]
    if before_history:
        raise WriterAbort(
            f"{scope_label}: stored point(s) {before_history} predate "
            f"history_start={seed.history_start}. The persisted series is not "
            "the series this seed describes."
        )

    latest_persisted = stored[-1].point_date if stored else None
    latest_archive = _latest_archive_day(db)

    if latest_persisted is not None and (
        latest_archive is None or latest_archive < latest_persisted
    ):
        raise WriterAbort(
            f"{scope_label}: the archive reaches {latest_archive} but a point "
            f"is stored for {latest_persisted}. The history required to "
            "reconstruct the persisted series is unavailable."
        )

    # The chain is always built from history_start over the WHOLE archive.
    # Narrowing it to the tail would make the first day of the window look
    # like the first day of the series and open a fabricated base at 1000.
    series = build_scope_series(
        db,
        scope_kind=seed.scope_kind,
        scope_key=seed.scope_key,
        history_start=seed.history_start,
    )

    if latest_persisted is not None:
        # `end=latest_persisted` truncates the archive at the head, which is
        # sound because the chain is causal: a day's point is a function of
        # days at or before it, so removing later days cannot change an
        # earlier point. What it does do is stop tomorrow's absence from being
        # reported as today's discrepancy.
        reconciliation = verify_scope(
            db,
            scope_kind=seed.scope_kind,
            scope_key=seed.scope_key,
            history_start=seed.history_start,
            end=latest_persisted,
        )
        if not reconciliation.ok:
            raise WriterAbort(
                f"{scope_label}: the persisted series through {latest_persisted} "
                "does not reconcile with a replay of the archive. No point is "
                "written and nothing is repaired - investigate:\n  "
                + "\n  ".join(str(d) for d in reconciliation.discrepancies)
            )

    planned = tuple(
        _to_planned(draft)
        for draft in sorted(series.points, key=lambda p: p.point_date)
        if latest_persisted is None or draft.point_date > latest_persisted
    )

    plan = WriterPlan(
        scope_kind=seed.scope_kind,
        scope_key=seed.scope_key,
        methodology_version=seed.methodology_version,
        history_start=seed.history_start,
        latest_persisted_point_date=latest_persisted,
        latest_archive_day=latest_archive,
        stored_point_count=len(stored),
        planned=planned,
    )
    return plan, series


# --- verifying an extension that does not exist yet -------------------------
#
# TWO VERIFICATIONS, TWO SUBJECTS, DELIBERATELY NOT MERGED.
#
#   `verify_persisted`          judges ROWS THAT EXIST, against a replay of the
#                               archive. It is the replay module's
#                               `verify_scope`, untouched: a stored point that
#                               disagrees with the archive is a bug alarm, and
#                               nothing here may soften that.
#
#   `verify_planned_extension`  judges ROWS THAT DO NOT EXIST YET, against the
#                               invariants the schema and the carry key will
#                               apply the instant they are inserted.
#
# They are separate because "the archive supports a day that is not stored" is
# a DIFFERENT FACT depending on which side of the head it falls on. Behind the
# head it is a hole - evidence something went wrong. Ahead of the head it is
# simply work not done yet, which is the normal state of affairs every day
# between 20:00 UTC and the moment the job runs. Collapsing the two would
# either make a routine pending write look like corruption (which is what the
# CLI used to do) or make a real hole look routine (which would be far worse).
#
# The reclassification below therefore happens at the REPORTING layer, over
# `verify_persisted`'s untouched output, and only for the exact dates the
# current plan intends to write.

EXTENSION_ALREADY_STORED = "planned_point_already_stored"
EXTENSION_NOT_AFTER_HEAD = "planned_point_not_after_head"
EXTENSION_OUT_OF_ORDER = "planned_points_out_of_order"
EXTENSION_BEYOND_ARCHIVE = "planned_point_beyond_archive"
EXTENSION_CARRY_UNRESOLVABLE = "planned_carry_target_unresolvable"
EXTENSION_CARRY_LEVEL_MISMATCH = "planned_carry_level_mismatch"
EXTENSION_CARRY_NOT_INCREASING = "planned_carry_not_increasing"
EXTENSION_INCONSISTENT_UNPUBLISHABLE = "planned_inconsistent_unpublishable_state"
EXTENSION_BASE_SHAPE = "planned_base_shape"
EXTENSION_STEP_SHAPE = "planned_step_shape"


@dataclass
class ExtensionResult:
    """What a dry run can prove about points it is not writing."""

    scope_kind: str
    scope_key: str
    planned_points: int
    discrepancies: list[Discrepancy]

    @property
    def ok(self) -> bool:
        return not self.discrepancies


def verify_planned_extension(
    db: Session, plan: WriterPlan, seed: SeedSpec = V1_OVERALL_SEED
) -> ExtensionResult:
    """Check the planned points against every rule the database will apply.

    WRITES NOTHING, and is not a second estimator: it never recomputes a level
    or a return. It asks only whether the drafts the committed estimator
    produced are internally coherent and insertable -

      * strictly after the head, strictly ascending, not already stored, and
        never beyond the archive that has to support them;
      * carrying only from a point that exists (stored, or earlier in this
        same plan), strictly earlier in time, at an EXACTLY equal level -
        which is what `uq_cpi_points_carry_target` and the composite foreign
        key enforce at INSERT time;
      * obeying the value/reason biconditional and the base/step shape rules
        that `ck_cpi_points_*` enforce.

    This is what makes a dry run worth running: the failures it catches are
    exactly the ones that would otherwise surface as an IntegrityError
    part-way through a real write.
    """
    scope_label = f"{seed.scope_kind}/{seed.scope_key or '-'}"
    discrepancies: list[Discrepancy] = []

    def flag(kind, point_date, **kw):
        discrepancies.append(
            Discrepancy(
                kind=kind,
                scope_kind=seed.scope_kind,
                scope_key=seed.scope_key,
                point_date=point_date,
                **kw,
            )
        )

    # Levels a carry may legitimately resolve against: everything already
    # stored, plus the planned points walked so far. A catch-up spanning two
    # version boundaries really can carry from a row this same run is about to
    # write, so the map grows as the walk proceeds.
    levels: dict[date, Decimal | None] = {
        row.point_date: row.index_value
        for row in db.execute(
            select(
                CardPirateIndexPoint.point_date, CardPirateIndexPoint.index_value
            ).where(
                CardPirateIndexPoint.scope_kind == seed.scope_kind,
                CardPirateIndexPoint.scope_key == seed.scope_key,
            )
        )
    }

    previous: date | None = None
    for point in plan.planned:
        if point.point_date in levels:
            flag(
                EXTENSION_ALREADY_STORED,
                point.point_date,
                detail=f"{scope_label} already holds this date",
            )
        if (
            plan.latest_persisted_point_date is not None
            and point.point_date <= plan.latest_persisted_point_date
        ):
            flag(
                EXTENSION_NOT_AFTER_HEAD,
                point.point_date,
                detail=(
                    "this job writes forward only; the head is "
                    f"{plan.latest_persisted_point_date}"
                ),
            )
        if previous is not None and point.point_date <= previous:
            flag(
                EXTENSION_OUT_OF_ORDER,
                point.point_date,
                detail=f"does not follow {previous}",
            )
        if (
            plan.latest_archive_day is not None
            and point.point_date > plan.latest_archive_day
        ):
            flag(
                EXTENSION_BEYOND_ARCHIVE,
                point.point_date,
                detail=(
                    "no archived snapshot day supports this point "
                    f"(archive reaches {plan.latest_archive_day})"
                ),
            )

        if (point.index_value is None) != (point.unpublishable_reason is not None):
            flag(
                EXTENSION_INCONSISTENT_UNPUBLISHABLE,
                point.point_date,
                detail=(
                    f"index_value={point.index_value!r} "
                    f"unpublishable_reason={point.unpublishable_reason!r}"
                ),
            )

        if point.is_base:
            # Section 5.1 rule 5: a base has no prior point, no step and no
            # breadth of its own.
            if (
                point.prior_point_date is not None
                or point.step_days is not None
                or point.chain_link_log_return is not None
                or point.constituent_count != 0
            ):
                flag(
                    EXTENSION_BASE_SHAPE,
                    point.point_date,
                    detail=(
                        f"prior_point_date={point.prior_point_date} "
                        f"step_days={point.step_days} "
                        f"return={point.chain_link_log_return} "
                        f"n={point.constituent_count}"
                    ),
                )
        elif point.unpublishable_reason is None:
            # A published step must say what it stepped from and by how much.
            if (
                point.prior_point_date is None
                or point.step_days is None
                or point.step_days < 1
                or point.chain_link_log_return is None
            ):
                flag(
                    EXTENSION_STEP_SHAPE,
                    point.point_date,
                    detail=(
                        f"prior_point_date={point.prior_point_date} "
                        f"step_days={point.step_days} "
                        f"return={point.chain_link_log_return}"
                    ),
                )

        # Registered BEFORE the carry is resolved, so a point carrying from
        # its own date is diagnosed as "not strictly earlier" - which is what
        # it is - rather than as an unresolvable target, which would be a
        # confusing way to describe a row pointing at itself.
        levels[point.point_date] = point.index_value

        if point.carried_from_point_date is not None:
            target_date = point.carried_from_point_date
            if target_date not in levels:
                flag(
                    EXTENSION_CARRY_UNRESOLVABLE,
                    point.point_date,
                    detail=(
                        f"no point on {target_date} is stored or planned "
                        "before this one"
                    ),
                )
            else:
                if target_date >= point.point_date:
                    flag(
                        EXTENSION_CARRY_NOT_INCREASING,
                        point.point_date,
                        detail=(
                            f"carry target {target_date} is not strictly "
                            f"earlier than {point.point_date}"
                        ),
                    )
                if levels[target_date] != point.index_value:
                    flag(
                        EXTENSION_CARRY_LEVEL_MISMATCH,
                        point.point_date,
                        stored=levels[target_date],
                        expected=point.index_value,
                    )

        previous = point.point_date

    return ExtensionResult(
        scope_kind=seed.scope_kind,
        scope_key=seed.scope_key,
        planned_points=len(plan.planned),
        discrepancies=discrepancies,
    )


# --- the guard that makes "insert only" a runtime fact ----------------------

_FINGERPRINT_COLUMNS = (
    CardPirateIndexPoint.id,
    CardPirateIndexPoint.scope_kind,
    CardPirateIndexPoint.scope_key,
    CardPirateIndexPoint.methodology_version,
    CardPirateIndexPoint.index_version,
    CardPirateIndexPoint.source_semantics_version,
    CardPirateIndexPoint.point_date,
    CardPirateIndexPoint.index_value,
    CardPirateIndexPoint.is_base,
    CardPirateIndexPoint.carried_from_point_id,
    CardPirateIndexPoint.prior_point_date,
    CardPirateIndexPoint.step_days,
    CardPirateIndexPoint.chain_link_log_return,
    CardPirateIndexPoint.constituent_count,
    CardPirateIndexPoint.eligible_print_count,
    CardPirateIndexPoint.movers_up,
    CardPirateIndexPoint.movers_down,
    CardPirateIndexPoint.movers_flat,
    CardPirateIndexPoint.capped_count,
    CardPirateIndexPoint.unpublishable_reason,
    CardPirateIndexPoint.calculated_at,
    CardPirateIndexPoint.created_at,
)


def _fingerprint(db: Session, seed: SeedSpec) -> dict[date, tuple]:
    """Every column of every stored row for the scope, keyed by date.

    A CORE select, not an ORM one, so it always hits the database rather than
    handing back whatever the identity map is holding - which is the only way
    a before/after comparison inside one session proves anything.

    `id`, `calculated_at` and `created_at` ARE included here, unlike in
    `COMPARED_FIELDS`. That list answers "does this row match a rebuild?", and
    those three are unreproducible so they are excluded from it. This one
    answers a different question - "is this row the same row it was ninety
    milliseconds ago?" - where an id or a clock changing is precisely the
    evidence wanted.
    """
    return {
        row.point_date: tuple(row)
        for row in db.execute(
            select(*_FINGERPRINT_COLUMNS).where(
                CardPirateIndexPoint.scope_kind == seed.scope_kind,
                CardPirateIndexPoint.scope_key == seed.scope_key,
            )
        )
    }


def _assert_prior_rows_untouched(
    db: Session, seed: SeedSpec, before: dict[date, tuple]
) -> None:
    """Prove, in-transaction, that no pre-existing row was updated or deleted.

    Append-only is a convention that the schema cannot enforce (methodology
    R10). It is enforced here, at the moment it matters, against the actual
    rows: every date present before the write must still be present, with a
    byte-identical tuple. A run that somehow rewrote history aborts and rolls
    back instead of committing it.
    """
    after = _fingerprint(db, seed)

    deleted = sorted(set(before) - set(after))
    if deleted:
        raise WriterAbort(
            f"{seed.scope_kind}/{seed.scope_key or '-'}: pre-existing point(s) "
            f"{deleted} disappeared during the write. Rolling back."
        )

    changed = sorted(d for d, row in before.items() if after[d] != row)
    if changed:
        raise WriterAbort(
            f"{seed.scope_kind}/{seed.scope_key or '-'}: pre-existing point(s) "
            f"{changed} were modified during the write. This job only ever "
            "inserts. Rolling back."
        )


# --- entry points -----------------------------------------------------------


def verify_persisted(
    db: Session, seed: SeedSpec = V1_OVERALL_SEED
) -> VerifyResult:
    """Replay the whole scope and report every discrepancy. Writes nothing.

    Distinct from the pre-write reconciliation inside `plan_write`, which
    stops at the persisted head: this one compares against the full archive,
    so a day the archive supports and the table does not shows up as
    `missing_point` - which is the operator's cue that a write is due.
    """
    return verify_scope(
        db,
        scope_kind=seed.scope_kind,
        scope_key=seed.scope_key,
        history_start=seed.history_start,
    )


@dataclass(frozen=True)
class PersistedReview:
    """`verify_persisted`'s findings, split by what they actually mean.

    `verify_persisted` compares the stored points against the WHOLE archive,
    so on any day after the Market Index job has archived and before the index
    job has run, it correctly reports `missing_point` for the day that is
    about to be written. That is not a defect in the persisted series, and
    reporting it as one made the verification command contradict the dry run
    standing right next to it - the dry run said "1 planned insert, all
    checks pass" while the verifier exited 1.

    So the split happens here, over untouched output: a `missing_point` for a
    date THE CURRENT PLAN INTENDS TO WRITE is pending work; everything else is
    a fault. Nothing is discarded - both lists are reported - and because
    every planned date is strictly after the head by construction, a hole
    behind the head can never land in `pending`.
    """

    verify: VerifyResult
    pending: tuple[date, ...]
    faults: tuple[Discrepancy, ...]

    @property
    def ok(self) -> bool:
        """True when the rows that EXIST are sound. Says nothing about
        whether work is outstanding - that is `pending`."""
        return not self.faults

    def report_lines(self) -> list[str]:
        lines = [
            f"scope: {self.verify.scope_kind}/{self.verify.scope_key or '-'}",
            f"stored_points: {self.verify.stored_points}",
            f"expected_points: {self.verify.expected_points}",
            f"persisted_faults: {len(self.faults)}",
            f"pending_inserts: {len(self.pending)}",
        ]
        lines.extend(f"  FAULT {d}" for d in self.faults)
        lines.extend(f"  pending {d} (planned, not yet written)" for d in self.pending)
        return lines


def review_persisted(
    db: Session, seed: SeedSpec = V1_OVERALL_SEED
) -> tuple[PersistedReview, WriterPlan]:
    """Verify the stored scope and separate pending work from real faults.

    Raises `WriterAbort` for the states `plan_write` refuses on - a foreign
    methodology version, a point before `history_start`, an archive that no
    longer reaches the head, or any discrepancy in the persisted range. Those
    are faults too; they simply fail loudly enough not to need classifying.
    """
    plan, _ = plan_write(db, seed)
    verify = verify_persisted(db, seed)

    planned_dates = {point.point_date for point in plan.planned}
    pending: list[date] = []
    faults: list[Discrepancy] = []
    for discrepancy in verify.discrepancies:
        if (
            discrepancy.kind == DISCREPANCY_MISSING_POINT
            and discrepancy.point_date in planned_dates
        ):
            pending.append(discrepancy.point_date)
        else:
            faults.append(discrepancy)

    return (
        PersistedReview(
            verify=verify, pending=tuple(pending), faults=tuple(faults)
        ),
        plan,
    )


def run_writer(
    db: Session,
    *,
    seed: SeedSpec = V1_OVERALL_SEED,
    dry_run: bool = False,
    calculated_at: datetime | None = None,
    skip_lock: bool = False,
) -> WriterRunResult:
    """Bring the persisted scope level with the archive. One shot.

    Idempotent by construction: the plan is "dates after the head", so a
    second run in the same minute finds an empty plan and writes nothing.
    """
    if dry_run:
        plan, _ = plan_write(db, seed)
        extension = verify_planned_extension(db, plan, seed)
        # Discard whatever the read queries left on the session. A --dry-run
        # cannot leave a write behind even if this function grows one later.
        db.rollback()
        return WriterRunResult(
            plan=plan,
            dry_run=True,
            inserted=0,
            persisted_verified=True,
            extension=extension,
        )

    with with_job_lock(LOCK_NAME, skip_lock=skip_lock):
        return _run_write_locked(db, seed=seed, calculated_at=calculated_at)


def _run_write_locked(
    db: Session, *, seed: SeedSpec, calculated_at: datetime | None
) -> WriterRunResult:
    try:
        before = _fingerprint(db, seed)
        plan, _ = plan_write(db, seed)

        extension = verify_planned_extension(db, plan, seed)

        if not plan.planned:
            # Nothing the archive supports is missing. The pre-write
            # reconciliation in plan_write already passed, so the scope is
            # known good; there is simply no work.
            db.rollback()
            return WriterRunResult(
                plan=plan,
                dry_run=False,
                inserted=0,
                persisted_verified=True,
                extension=extension,
            )

        # Refuse BEFORE the first INSERT rather than discovering the same
        # problem as an IntegrityError half-way through the day's write. The
        # rollback would be equally clean either way; failing here is simply
        # the version an operator can read.
        if not extension.ok:
            raise WriterAbort(
                f"{seed.scope_kind}/{seed.scope_key or '-'}: the planned "
                "extension is not insertable. Nothing written:\n  "
                + "\n  ".join(str(d) for d in extension.discrepancies)
            )

        # ASCENDING, FROM THE DAY AFTER THE HEAD. `history_start` still builds
        # the chain from the beginning - `start` only bounds the write - so a
        # carry landing in this window resolves against a row an earlier run
        # already stored, and fails closed if it does not.
        result, _ = replay_scope(
            db,
            scope_kind=seed.scope_kind,
            scope_key=seed.scope_key,
            history_start=seed.history_start,
            start=plan.first_write_date,
            calculated_at=calculated_at or datetime.now(timezone.utc),
        )

        expected = len(plan.planned)
        if result.inserted != expected or result.already_present != 0:
            raise WriterAbort(
                f"{seed.scope_kind}/{seed.scope_key or '-'}: planned "
                f"{expected} insert(s) after {plan.latest_persisted_point_date} "
                f"but replay inserted {result.inserted} and found "
                f"{result.already_present} already present. Rolling back."
            )

        _assert_prior_rows_untouched(db, seed, before)

        # The commit gate. Reads through the same uncommitted transaction, so
        # it is judging the rows that are about to become permanent.
        final = verify_persisted(db, seed)
        if not final.ok:
            raise WriterAbort(
                f"{seed.scope_kind}/{seed.scope_key or '-'}: verification of "
                "the written series failed. Rolling back:\n  "
                + "\n  ".join(str(d) for d in final.discrepancies)
            )

        db.commit()
        return WriterRunResult(
            plan=plan,
            dry_run=False,
            inserted=result.inserted,
            persisted_verified=True,
            extension=extension,
        )
    except Exception:
        db.rollback()
        raise


# --- CLI --------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.card_pirate_index_writer",
        description=(
            "Write the Card Pirate Index points the archive now supports and "
            "the table does not yet hold. Forward only, insert only, and it "
            "refuses to run at all if the persisted series does not already "
            "reconcile with a replay."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Plan and reconcile, report the points that would be written, and "
            "write nothing. Takes no job lock, so it is safe against a "
            "read-only session."
        ),
    )
    mode.add_argument(
        "--verify",
        action="store_true",
        help=(
            "Replay the whole scope and report how the stored points differ "
            "from it. Writes nothing and takes no job lock. Exits 1 on a fault "
            "in the STORED series; a day the archive supports that this run "
            "would write is reported as pending, not as a fault."
        ),
    )
    parser.add_argument(
        "--skip-lock",
        action="store_true",
        help=(
            "Skip the card_pirate_index concurrency lock. Test/dev only - "
            "never use in production."
        ),
    )
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        try:
            if args.verify:
                review, _ = review_persisted(db)
                for line in review.report_lines():
                    print(line)
                # Exit 0 with work outstanding: the STORED series is sound,
                # and "the day has not been written yet" is the normal state
                # between the snapshot job and this one. A fault in what is
                # already published is the only thing that is an error here.
                return 0 if review.ok else 1

            run = run_writer(db, dry_run=args.dry_run, skip_lock=args.skip_lock)
        except LockHeldError as exc:
            print(f"Job already running: {exc.lock_name}", file=sys.stderr)
            return 2
        except WriterAbort as exc:
            print(f"ABORTED, nothing written: {exc}", file=sys.stderr)
            return 1

        for line in run.report_lines():
            print(line)
        # A dry run that planned a coherent extension off a clean persisted
        # prefix is a SUCCESS, not a warning. Only a real problem - which by
        # here means the planned extension failed its own checks - is non-zero.
        return 0 if run.verified else 1
    finally:
        db.close()


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
