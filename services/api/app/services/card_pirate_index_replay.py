"""Card Pirate Index replay and verification - the database edges.

Two entry points over one pure core (`app.services.card_pirate_index`):

  * `replay_scope`  reads `market_index_snapshots`, rebuilds a scope's whole
                    series, and INSERTs the points that are missing. Nothing
                    else writes to `card_pirate_index_points`.
  * `verify_scope`  reads both, recomputes from the archive, and REPORTS every
                    difference. It never writes.

WHY A REPLAY IS LEGITIMATE HERE AND FORBIDDEN FOR THE SIBLING TABLE
--------------------------------------------------------------------
`market_index_snapshots` cannot be backfilled: a past Market Index is not
computable, because `_compute_index_fields` applies freshness windows relative
to the `now` it is handed. This table has no such dependency. Its inputs are
the immutable, already-archived `index_value_jpy` values, so a point is a pure,
deterministic, idempotent function of rows that can never change. A
reconstruction here reproduces exactly what the job would have written; a
reconstruction there would claim Atlas showed a value it demonstrably never
showed. See methodology section 8.2.

THERE IS NO REPAIR PATH, ON PURPOSE
------------------------------------
`verify_scope` reports discrepancies and returns them. It has no UPDATE, no
DELETE and no "fix" flag, and neither does `replay_scope`: replay only INSERTs
rows that do not exist, via ON CONFLICT DO NOTHING on the natural key. A
mismatch between the archive and a stored point is evidence of a bug, and the
correct response is to investigate it, not to overwrite the record of what was
published. That is the same reasoning `market_index_snapshot.py` already
applies to itself: "the first snapshot of a day is the one Atlas stands
behind."

NATURAL IDENTITY, NEVER SURROGATE IDS
--------------------------------------
Surrogate ids are not stable across a rebuild - measured on PostgreSQL 18.6,
the same three logical points came back as 7, 8, 9 instead of 1, 2, 3, while
the natural key was identical. So every comparison in this module keys on
`(scope_kind, scope_key, methodology_version, point_date)`, and a carry is
compared by the TARGET'S point_date resolved through the reference, never by
the integer itself. `calculated_at` and `created_at` are likewise never
compared: neither is reproducible.

INSERTION ORDER IS A REQUIREMENT
---------------------------------
The carry foreign key is immediate and non-deferrable, so a carried base can
only be inserted after its target exists. `replay_scope` therefore writes in
ascending `point_date` and resolves each carry against ids it has just seen. A
partial replay whose carry target is missing fails closed and loudly rather
than writing a dangling reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.card_pirate_index_point import CardPirateIndexPoint
from app.models.market_index_snapshot import MarketIndexSnapshot
from app.services.card_pirate_index import (
    METHODOLOGY_VERSION,
    SCOPE_OVERALL,
    ConstituentObservation,
    PointDraft,
    ScopeSeries,
    SnapshotDay,
    build_points,
)

# The fields a rebuild reproduces, and therefore the fields verification
# compares. Deliberately excludes `id`, `carried_from_point_id`,
# `calculated_at` and `created_at`: the first two are surrogates that move
# under a rebuild, the last two are clocks that cannot be reproduced at all.
# The carry is compared separately, by resolved natural key.
COMPARED_FIELDS = (
    "index_version",
    "source_semantics_version",
    "index_value",
    "is_base",
    "prior_point_date",
    "step_days",
    "chain_link_log_return",
    "constituent_count",
    "eligible_print_count",
    "movers_up",
    "movers_down",
    "movers_flat",
    "capped_count",
    "unpublishable_reason",
)


# --- reading the archive ----------------------------------------------------


def load_snapshot_days(
    db: Session,
    *,
    start: date | None = None,
    end: date | None = None,
    card_print_ids: list[int] | None = None,
) -> list[SnapshotDay]:
    """Every valued snapshot row, grouped into ordered days.

    Only `index_value_jpy IS NOT NULL` rows are loaded: a NULL value is
    `coverage_status='none'`, which is an absence. Absences are never carried
    forward, so they are simply not here.

    `card_print_ids` is how a sub-index scope is expressed - a filter on the
    constituent set and nothing else. There is no source name, rarity, price
    floor or set code in this query, which is what makes a sub-index a GROUP
    BY rather than a rewrite (section 14).
    """
    stmt = select(
        MarketIndexSnapshot.snapshot_date,
        MarketIndexSnapshot.card_print_id,
        MarketIndexSnapshot.index_value_jpy,
        MarketIndexSnapshot.index_version,
        MarketIndexSnapshot.source_semantics_version,
        MarketIndexSnapshot.provenance,
    ).where(MarketIndexSnapshot.index_value_jpy.is_not(None))

    if start is not None:
        stmt = stmt.where(MarketIndexSnapshot.snapshot_date >= start)
    if end is not None:
        stmt = stmt.where(MarketIndexSnapshot.snapshot_date <= end)
    if card_print_ids is not None:
        if not card_print_ids:
            return []
        stmt = stmt.where(MarketIndexSnapshot.card_print_id.in_(card_print_ids))

    # Explicitly ordered. Nothing downstream may depend on the database's
    # natural row order, and build_points re-sorts anyway - belt and braces,
    # because a silent ordering dependency is exactly the kind of bug that
    # only shows up once the table is large enough to be scanned differently.
    stmt = stmt.order_by(
        MarketIndexSnapshot.snapshot_date, MarketIndexSnapshot.card_print_id
    )

    grouped: dict[date, list[ConstituentObservation]] = {}
    for row in db.execute(stmt):
        grouped.setdefault(row.snapshot_date, []).append(
            ConstituentObservation.from_snapshot_row(
                card_print_id=row.card_print_id,
                index_value_jpy=row.index_value_jpy,
                index_version=row.index_version,
                source_semantics_version=row.source_semantics_version,
                provenance=row.provenance,
            )
        )

    return [
        SnapshotDay(
            point_date=day,
            observations=tuple(
                sorted(rows, key=lambda o: o.card_print_id)
            ),
        )
        for day, rows in sorted(grouped.items())
    ]


def build_scope_series(
    db: Session,
    *,
    scope_kind: str = SCOPE_OVERALL,
    scope_key: str = "",
    start: date | None = None,
    end: date | None = None,
    card_print_ids: list[int] | None = None,
) -> ScopeSeries:
    """Read the archive and rebuild one scope's series. Reads only."""
    days = load_snapshot_days(
        db, start=start, end=end, card_print_ids=card_print_ids
    )
    return build_points(days, scope_kind=scope_kind, scope_key=scope_key)


# --- writing (INSERT only) --------------------------------------------------


@dataclass
class ReplayResult:
    scope_kind: str
    scope_key: str
    computed: int
    inserted: int
    already_present: int

    @property
    def is_noop(self) -> bool:
        return self.inserted == 0


def replay_scope(
    db: Session,
    *,
    scope_kind: str = SCOPE_OVERALL,
    scope_key: str = "",
    start: date | None = None,
    end: date | None = None,
    card_print_ids: list[int] | None = None,
    calculated_at: datetime | None = None,
    dry_run: bool = False,
) -> tuple[ReplayResult, ScopeSeries]:
    """Rebuild a scope and insert the points that are missing.

    Idempotent: ON CONFLICT DO NOTHING on the natural key, so a second run
    inserts nothing and rewrites no carry. It NEVER updates. If a stored point
    disagrees with the rebuild, this function leaves it exactly as it is -
    `verify_scope` is what surfaces the disagreement, and a human decides.

    `dry_run` computes and reports without touching the session at all.
    """
    # THE CHAIN IS A FUNCTION OF THE WHOLE HISTORY, so `start` filters what is
    # WRITTEN, never what is computed. Building from a windowed archive would
    # make the window's first day look like the scope's first day, and
    # build_points would open an INITIAL base at 1000 there - fabricating a
    # reset, inventing a discontinuity the market never had, and silently
    # destroying the carry the methodology requires. Compute from the
    # beginning; restrict only the write.
    series = build_scope_series(
        db,
        scope_kind=scope_kind,
        scope_key=scope_key,
        end=end,
        card_print_ids=card_print_ids,
    )
    if dry_run:
        return (
            ReplayResult(scope_kind, scope_key, len(series.points), 0, 0),
            series,
        )

    stamp = calculated_at or datetime.now(timezone.utc)

    # Ids of points already stored for this scope, keyed by date. A carry may
    # legitimately point at a row written by an earlier run.
    existing_ids: dict[date, int] = {
        row.point_date: row.id
        for row in db.execute(
            select(CardPirateIndexPoint.point_date, CardPirateIndexPoint.id).where(
                CardPirateIndexPoint.scope_kind == scope_kind,
                CardPirateIndexPoint.scope_key == scope_key,
                CardPirateIndexPoint.methodology_version == METHODOLOGY_VERSION,
            )
        )
    }

    inserted = 0
    already = 0
    # Ascending point_date: the carry FK is immediate, so a target must exist
    # before the row referencing it is written.
    for draft in sorted(series.points, key=lambda p: p.point_date):
        if start is not None and draft.point_date < start:
            # Outside the write window. Its id is still needed, because a
            # later carry may point at it - and if it was never stored, the
            # carry below fails closed rather than writing a dangling
            # reference.
            continue
        carried_id = None
        if draft.carried_from_key is not None:
            carried_id = existing_ids.get(draft.carried_from_key)
            if carried_id is None:
                raise ValueError(
                    "carry target missing for "
                    f"{scope_kind}/{scope_key or '-'} {draft.point_date}: "
                    f"no stored point on {draft.carried_from_key}. "
                    "Replay the range containing it first."
                )

        if draft.point_date in existing_ids:
            already += 1
            continue

        values = _draft_to_values(draft, carried_id, stamp)
        stmt = (
            _insert_for(db)(CardPirateIndexPoint)
            .values(**values)
            .on_conflict_do_nothing(index_elements=_NATURAL_KEY_ELEMENTS)
            .returning(CardPirateIndexPoint.id)
        )
        new_id = db.execute(stmt).scalar_one_or_none()
        if new_id is None:
            # Another writer got there first. Re-read rather than assume.
            new_id = db.execute(
                select(CardPirateIndexPoint.id).where(
                    CardPirateIndexPoint.scope_kind == scope_kind,
                    CardPirateIndexPoint.scope_key == scope_key,
                    CardPirateIndexPoint.methodology_version
                    == draft.methodology_version,
                    CardPirateIndexPoint.point_date == draft.point_date,
                )
            ).scalar_one()
            already += 1
        else:
            inserted += 1
        existing_ids[draft.point_date] = new_id

    return (
        ReplayResult(scope_kind, scope_key, len(series.points), inserted, already),
        series,
    )


# The natural key, named as columns rather than as a constraint name. Both
# dialects accept index_elements; SQLite has no ON CONFLICT ON CONSTRAINT at
# all, so naming the columns is what lets one code path serve the Postgres
# deployment and the SQLite test suite without a second implementation.
_NATURAL_KEY_ELEMENTS = ("scope_kind", "scope_key", "methodology_version", "point_date")


def _insert_for(db: Session):
    """The dialect's INSERT construct, so ON CONFLICT DO NOTHING compiles.

    The generic `sqlalchemy.insert` has no `on_conflict_do_nothing`, and the
    PostgreSQL construct does not compile on SQLite. Selecting on the bound
    dialect keeps the idempotency contract identical on both.
    """
    name = db.get_bind().dialect.name
    if name == "sqlite":
        return sqlite_insert
    return pg_insert


def _draft_to_values(
    draft: PointDraft, carried_id: int | None, stamp: datetime
) -> dict:
    return {
        "scope_kind": draft.scope_kind,
        "scope_key": draft.scope_key,
        "methodology_version": draft.methodology_version,
        "index_version": draft.index_version,
        "source_semantics_version": draft.source_semantics_version,
        "point_date": draft.point_date,
        "index_value": draft.index_value,
        "is_base": draft.is_base,
        "carried_from_point_id": carried_id,
        "prior_point_date": draft.prior_point_date,
        "step_days": draft.step_days,
        "chain_link_log_return": draft.chain_link_log_return,
        "constituent_count": draft.constituent_count,
        "eligible_print_count": draft.eligible_print_count,
        "movers_up": draft.movers_up,
        "movers_down": draft.movers_down,
        "movers_flat": draft.movers_flat,
        "capped_count": draft.capped_count,
        "unpublishable_reason": draft.unpublishable_reason,
        "calculated_at": stamp,
    }


# --- verification (reads only) ----------------------------------------------

DISCREPANCY_MISSING_POINT = "missing_point"
DISCREPANCY_UNEXPECTED_POINT = "unexpected_point"
DISCREPANCY_FIELD_MISMATCH = "field_mismatch"
DISCREPANCY_CARRY_TARGET_MISSING = "carry_target_missing"
DISCREPANCY_CARRY_WRONG_SCOPE = "carry_wrong_scope"
DISCREPANCY_CARRY_LEVEL_MISMATCH = "carry_level_mismatch"
DISCREPANCY_CARRY_NOT_INCREASING = "carry_not_increasing"
DISCREPANCY_CARRY_CYCLE = "carry_cycle"
DISCREPANCY_INCONSISTENT_UNPUBLISHABLE = "inconsistent_unpublishable_state"


@dataclass(frozen=True)
class Discrepancy:
    kind: str
    scope_kind: str
    scope_key: str
    point_date: date | None
    field: str | None = None
    stored: object = None
    expected: object = None
    detail: str | None = None

    def __str__(self) -> str:
        where = f"{self.scope_kind}/{self.scope_key or '-'} {self.point_date}"
        if self.field is not None:
            return (
                f"{self.kind}: {where} {self.field}: "
                f"stored={self.stored!r} expected={self.expected!r}"
            )
        return f"{self.kind}: {where} {self.detail or ''}".rstrip()


@dataclass
class VerifyResult:
    scope_kind: str
    scope_key: str
    stored_points: int
    expected_points: int
    discrepancies: list[Discrepancy]

    @property
    def ok(self) -> bool:
        return not self.discrepancies


def verify_scope(
    db: Session,
    *,
    scope_kind: str = SCOPE_OVERALL,
    scope_key: str = "",
    start: date | None = None,
    end: date | None = None,
    card_print_ids: list[int] | None = None,
) -> VerifyResult:
    """Replay the archive and report every way the stored points differ.

    WRITES NOTHING. There is no repair flag and no UPDATE anywhere below: a
    mismatch is a bug alarm, and overwriting the row would destroy the
    evidence that something went wrong.

    Two independent families of check run here:

      1. REBUILD EQUALITY - every stored point must equal the point a fresh
         replay produces, compared by natural key and by the COMPARED_FIELDS
         list. Surrogate ids and clocks are excluded because they are not
         reproducible.
      2. CHAIN INTEGRITY - checks that hold on the stored rows alone,
         regardless of what a rebuild says: a carry must resolve, stay in
         scope, match its source's level exactly, move strictly forward in
         time, and never close a cycle. These are the guarantees the schema
         cannot make (section 8.6 finding 4), so they are made here instead.
    """
    # Same rule as replay: the rebuild spans the whole history, and start/end
    # narrow only what is COMPARED. Verifying against a windowed rebuild would
    # report a fabricated initial base as correct.
    expected = build_scope_series(
        db,
        scope_kind=scope_kind,
        scope_key=scope_key,
        end=end,
        card_print_ids=card_print_ids,
    )
    expected_points = list(expected.points)
    if start is not None:
        expected_points = [p for p in expected_points if p.point_date >= start]
    expected_by_date = {p.point_date: p for p in expected_points}

    stored_rows = list(
        db.scalars(
            select(CardPirateIndexPoint)
            .where(
                CardPirateIndexPoint.scope_kind == scope_kind,
                CardPirateIndexPoint.scope_key == scope_key,
                CardPirateIndexPoint.methodology_version == METHODOLOGY_VERSION,
            )
            .order_by(CardPirateIndexPoint.point_date)
        )
    )
    if start is not None:
        stored_rows = [r for r in stored_rows if r.point_date >= start]
    if end is not None:
        stored_rows = [r for r in stored_rows if r.point_date <= end]

    stored_by_date = {r.point_date: r for r in stored_rows}
    discrepancies: list[Discrepancy] = []

    def flag(kind, point_date, **kw):
        discrepancies.append(
            Discrepancy(
                kind=kind,
                scope_kind=scope_kind,
                scope_key=scope_key,
                point_date=point_date,
                **kw,
            )
        )

    # --- 1. rebuild equality, keyed on natural identity ---
    for point_date in sorted(set(expected_by_date) - set(stored_by_date)):
        flag(DISCREPANCY_MISSING_POINT, point_date, detail="replay produced a point that is not stored")
    for point_date in sorted(set(stored_by_date) - set(expected_by_date)):
        flag(
            DISCREPANCY_UNEXPECTED_POINT,
            point_date,
            detail="stored point that a replay does not produce",
        )

    for point_date in sorted(set(expected_by_date) & set(stored_by_date)):
        want = expected_by_date[point_date]
        have = stored_by_date[point_date]
        for name in COMPARED_FIELDS:
            expected_value = getattr(want, name)
            stored_value = getattr(have, name)
            if not _values_equal(stored_value, expected_value):
                flag(
                    DISCREPANCY_FIELD_MISMATCH,
                    point_date,
                    field=name,
                    stored=stored_value,
                    expected=expected_value,
                )

        # The value/reason biconditional, checked on the stored row itself
        # rather than inferred from the rebuild - a row can be internally
        # inconsistent in a way that happens to match on both halves.
        if (have.index_value is None) != (have.unpublishable_reason is not None):
            flag(
                DISCREPANCY_INCONSISTENT_UNPUBLISHABLE,
                point_date,
                detail=(
                    f"index_value={have.index_value!r} "
                    f"unpublishable_reason={have.unpublishable_reason!r}"
                ),
            )

    # --- 2. chain integrity, on the stored rows alone ---
    _verify_carry_chain(db, stored_rows, flag)

    return VerifyResult(
        scope_kind=scope_kind,
        scope_key=scope_key,
        stored_points=len(stored_rows),
        expected_points=len(expected_points),
        discrepancies=discrepancies,
    )


def _verify_carry_chain(db: Session, stored_rows, flag) -> None:
    """Every carry must resolve, stay in scope, match its source's level,
    move strictly forward, and close no cycle.

    The last two are the checks the schema deliberately does not make. A
    hand-written UPDATE can build a two-row cycle - measured, and it succeeds -
    so cycle detection lives here, in the replay, exactly as the methodology
    document says it must.
    """
    carriers = [r for r in stored_rows if r.carried_from_point_id is not None]
    if not carriers:
        return

    target_ids = {r.carried_from_point_id for r in carriers}
    targets = {
        row.id: row
        for row in db.scalars(
            select(CardPirateIndexPoint).where(
                CardPirateIndexPoint.id.in_(sorted(target_ids))
            )
        )
    }

    for row in carriers:
        target = targets.get(row.carried_from_point_id)
        if target is None:
            flag(
                DISCREPANCY_CARRY_TARGET_MISSING,
                row.point_date,
                detail=f"carried_from_point_id={row.carried_from_point_id} does not resolve",
            )
            continue
        if (target.scope_kind, target.scope_key) != (row.scope_kind, row.scope_key):
            flag(
                DISCREPANCY_CARRY_WRONG_SCOPE,
                row.point_date,
                stored=f"{target.scope_kind}/{target.scope_key or '-'}",
                expected=f"{row.scope_kind}/{row.scope_key or '-'}",
            )
        if not _values_equal(target.index_value, row.index_value):
            flag(
                DISCREPANCY_CARRY_LEVEL_MISMATCH,
                row.point_date,
                stored=row.index_value,
                expected=target.index_value,
            )
        if target.point_date >= row.point_date:
            flag(
                DISCREPANCY_CARRY_NOT_INCREASING,
                row.point_date,
                detail=(
                    f"carry target {target.point_date} is not strictly earlier "
                    f"than {row.point_date}"
                ),
            )

    # Cycle detection by walk, with a visited set per start node. Bounded by
    # the number of carriers, so a cycle terminates instead of hanging.
    by_id = dict(targets)
    for row in stored_rows:
        by_id.setdefault(row.id, row)

    for row in carriers:
        seen = {row.id}
        cursor = by_id.get(row.carried_from_point_id)
        while cursor is not None and cursor.carried_from_point_id is not None:
            if cursor.id in seen:
                flag(
                    DISCREPANCY_CARRY_CYCLE,
                    row.point_date,
                    detail=f"carry chain from {row.point_date} revisits point {cursor.id}",
                )
                break
            seen.add(cursor.id)
            cursor = by_id.get(cursor.carried_from_point_id)


def _values_equal(stored, expected) -> bool:
    """Numeric equality that does not care about trailing-zero shape.

    A Decimal round-tripped through Numeric(18,12) can come back as 0E-12
    where the rebuild produced Decimal('0.000000000000'). Those are the same
    number, and reporting them as a discrepancy would make every all-flat day
    look like a bug.
    """
    if stored is None or expected is None:
        return stored is None and expected is None
    if isinstance(stored, Decimal) and isinstance(expected, Decimal):
        return stored == expected
    return stored == expected


__all__ = [
    "COMPARED_FIELDS",
    "DISCREPANCY_CARRY_CYCLE",
    "DISCREPANCY_CARRY_LEVEL_MISMATCH",
    "DISCREPANCY_CARRY_NOT_INCREASING",
    "DISCREPANCY_CARRY_TARGET_MISSING",
    "DISCREPANCY_CARRY_WRONG_SCOPE",
    "DISCREPANCY_FIELD_MISMATCH",
    "DISCREPANCY_INCONSISTENT_UNPUBLISHABLE",
    "DISCREPANCY_MISSING_POINT",
    "DISCREPANCY_UNEXPECTED_POINT",
    "Discrepancy",
    "ReplayResult",
    "VerifyResult",
    "build_scope_series",
    "load_snapshot_days",
    "replay_scope",
    "verify_scope",
]
