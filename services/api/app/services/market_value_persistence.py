"""Deterministic append-only persistence for already-derived Market Value points.

This module never calculates a basket, chooses release membership, reads a
source, or commits a transaction.  The replay adapter supplies immutable
``MarketValuePointDraft`` values; this layer sorts them, inserts with
``ON CONFLICT DO NOTHING``, and then proves that every stored logical point is
byte-for-value equivalent to the deterministic draft.  A natural-key conflict
with different contents is an integrity error, never an upsert.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.market_value_point import MarketValuePoint


@dataclass(frozen=True, slots=True)
class MarketValuePointDraft:
    scope_kind: str
    release_product_id: int | None
    methodology_version: int
    point_date: date
    tracked_value_jpy: int | None
    priced_print_count: int
    total_physical_print_count: int
    prior_point_date: date | None
    step_days: int | None
    prior_tracked_value_jpy: int | None
    prior_priced_print_count: int | None
    prior_total_physical_print_count: int | None
    comparable_print_count: int | None
    prior_comparable_value_jpy: int | None
    current_comparable_value_jpy: int | None
    step_ratio: Decimal | None
    segment_number: int
    performance_factor: Decimal
    step_publication_eligible: bool | None
    publication_reasons: str | None
    membership_revision: str
    prior_version_pairs: str | None
    current_version_pairs: str

    def __post_init__(self) -> None:
        if self.scope_kind == "overall":
            if self.release_product_id is not None:
                raise ValueError("overall draft cannot carry release_product_id")
        elif self.scope_kind == "release":
            if self.release_product_id is None or self.release_product_id <= 0:
                raise ValueError("release draft requires positive release_product_id")
        else:
            raise ValueError("scope_kind must be 'overall' or 'release'")
        if self.methodology_version <= 0:
            raise ValueError("methodology_version must be positive")
        if not self.membership_revision.strip():
            raise ValueError("membership_revision cannot be blank")

    @property
    def natural_key(self) -> tuple[str, int | None, int, date]:
        return (
            self.scope_kind,
            self.release_product_id,
            self.methodology_version,
            self.point_date,
        )

    def values(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in PERSISTED_VALUE_COLUMNS}


PERSISTED_VALUE_COLUMNS = tuple(MarketValuePointDraft.__dataclass_fields__)


def version_pairs_text(pairs: Iterable[tuple[int, int]]) -> str:
    """Canonical compact representation of exact (index, semantics) pairs."""
    return ",".join(f"{index}:{semantics}" for index, semantics in sorted(set(pairs)))


def publication_reasons_text(reasons: Iterable[object]) -> str:
    """Preserve A2 reason order without inventing another vocabulary."""
    values = [getattr(reason, "value", str(reason)) for reason in reasons]
    if not values:
        raise ValueError("a movement step must carry at least one publication reason")
    return "|".join(values)


def _sort_key(draft: MarketValuePointDraft) -> tuple[object, ...]:
    return (
        draft.scope_kind,
        draft.release_product_id or 0,
        draft.methodology_version,
        draft.point_date,
    )


def _natural_key_predicate(draft: MarketValuePointDraft):
    clauses = (
        MarketValuePoint.scope_kind == draft.scope_kind,
        MarketValuePoint.methodology_version == draft.methodology_version,
        MarketValuePoint.point_date == draft.point_date,
    )
    if draft.release_product_id is None:
        return (*clauses, MarketValuePoint.release_product_id.is_(None))
    return (*clauses, MarketValuePoint.release_product_id == draft.release_product_id)


def _draft_from_row(row: MarketValuePoint) -> MarketValuePointDraft:
    return MarketValuePointDraft(
        **{name: getattr(row, name) for name in PERSISTED_VALUE_COLUMNS}
    )


def _field_mismatches(
    expected: MarketValuePointDraft, actual: MarketValuePointDraft
) -> tuple[str, ...]:
    return tuple(
        name
        for name in PERSISTED_VALUE_COLUMNS
        if getattr(expected, name) != getattr(actual, name)
    )


class MarketValuePointConflictError(RuntimeError):
    def __init__(
        self,
        natural_key: tuple[str, int | None, int, date],
        mismatched_fields: tuple[str, ...],
    ) -> None:
        self.natural_key = natural_key
        self.mismatched_fields = mismatched_fields
        super().__init__(
            "market value point conflict for "
            f"{natural_key}: {', '.join(mismatched_fields)}"
        )


@dataclass(frozen=True, slots=True)
class MarketValueWriteResult:
    inserted: int
    existing: int
    verified: int


def _insert_statement(db: Session, values: dict[str, object]):
    dialect = db.get_bind().dialect.name
    table = MarketValuePoint.__table__
    if dialect == "postgresql":
        statement = postgresql_insert(table).values(**values)
    elif dialect == "sqlite":
        # SQLite support keeps ordinary unit fixtures useful; all schema,
        # Numeric and constraint guarantees are proved separately on Postgres.
        statement = sqlite_insert(table).values(**values)
    else:
        raise RuntimeError(
            "market value append-only writer supports PostgreSQL and test SQLite"
        )
    return statement.on_conflict_do_nothing().returning(table.c.id)


def persist_market_value_points(
    db: Session, drafts: Iterable[MarketValuePointDraft]
) -> MarketValueWriteResult:
    """Insert deterministic drafts, verifying every insert or conflict.

    The caller owns commit/rollback.  A savepoint ensures a conflicting point
    cannot leave earlier rows from the same call pending in the transaction.
    """
    ordered = tuple(sorted(drafts, key=_sort_key))
    keys = [draft.natural_key for draft in ordered]
    if len(keys) != len(set(keys)):
        raise ValueError("market value draft batch contains duplicate natural keys")

    inserted = 0
    existing = 0
    verified = 0
    with db.begin_nested():
        for draft in ordered:
            inserted_id = db.execute(
                _insert_statement(db, draft.values())
            ).scalar_one_or_none()
            if inserted_id is None:
                existing += 1
            else:
                inserted += 1

            stored = db.scalar(
                select(MarketValuePoint).where(*_natural_key_predicate(draft))
            )
            if stored is None:
                raise RuntimeError(
                    f"inserted/conflicting point disappeared for {draft.natural_key}"
                )
            mismatches = _field_mismatches(draft, _draft_from_row(stored))
            if mismatches:
                raise MarketValuePointConflictError(draft.natural_key, mismatches)
            verified += 1

    return MarketValueWriteResult(
        inserted=inserted, existing=existing, verified=verified
    )


@dataclass(frozen=True, slots=True)
class MarketValueVerificationMismatch:
    natural_key: tuple[str, int | None, int, date]
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MarketValueVerificationResult:
    expected: int
    persisted: int
    verified: int
    missing_keys: tuple[tuple[str, int | None, int, date], ...]
    unexpected_keys: tuple[tuple[str, int | None, int, date], ...]
    mismatches: tuple[MarketValueVerificationMismatch, ...]

    @property
    def ok(self) -> bool:
        return not self.missing_keys and not self.unexpected_keys and not self.mismatches


def verify_market_value_points(
    db: Session,
    expected_drafts: Iterable[MarketValuePointDraft],
    *,
    exact_archive: bool = False,
    through: date | None = None,
) -> MarketValueVerificationResult:
    """Compare recomputed drafts to stored rows by natural key, never by id.

    The default preserves the focused A3A comparison over the expected
    scopes/date range.  ``exact_archive=True`` is the operator-writer gate: it
    compares against every stored point through the requested cutoff (or the
    whole table without one), so obsolete scopes and stray dates cannot hide
    outside an expected draft's range.
    """
    expected_rows = tuple(sorted(expected_drafts, key=_sort_key))
    expected = {draft.natural_key: draft for draft in expected_rows}
    if len(expected) != len(expected_rows):
        raise ValueError("market value verification contains duplicate expected keys")
    if through is not None and any(row.point_date > through for row in expected_rows):
        raise ValueError("market value verification received a point after cutoff")
    if not expected and not exact_archive:
        return MarketValueVerificationResult(0, 0, 0, (), (), ())

    if exact_archive:
        statement = select(MarketValuePoint)
        if through is not None:
            statement = statement.where(MarketValuePoint.point_date <= through)
    else:
        versions = sorted({draft.methodology_version for draft in expected_rows})
        first_date = min(draft.point_date for draft in expected_rows)
        last_date = max(draft.point_date for draft in expected_rows)
        overall_expected = any(
            draft.scope_kind == "overall" for draft in expected_rows
        )
        release_ids = sorted(
            {
                draft.release_product_id
                for draft in expected_rows
                if draft.release_product_id is not None
            }
        )
        scope_clauses = []
        if overall_expected:
            scope_clauses.append(
                (MarketValuePoint.scope_kind == "overall")
                & MarketValuePoint.release_product_id.is_(None)
            )
        if release_ids:
            scope_clauses.append(
                (MarketValuePoint.scope_kind == "release")
                & MarketValuePoint.release_product_id.in_(release_ids)
            )
        scope_filter = scope_clauses[0]
        for clause in scope_clauses[1:]:
            scope_filter = scope_filter | clause
        statement = select(MarketValuePoint).where(
            MarketValuePoint.methodology_version.in_(versions),
            MarketValuePoint.point_date >= first_date,
            MarketValuePoint.point_date <= last_date,
            scope_filter,
        )

    persisted_rows = tuple(
        db.scalars(
            statement.order_by(
                MarketValuePoint.scope_kind,
                MarketValuePoint.release_product_id,
                MarketValuePoint.methodology_version,
                MarketValuePoint.point_date,
            )
        )
    )
    actual = {
        draft.natural_key: draft
        for draft in (_draft_from_row(row) for row in persisted_rows)
    }
    missing = tuple(sorted(set(expected) - set(actual), key=str))
    unexpected = tuple(sorted(set(actual) - set(expected), key=str))
    mismatches = tuple(
        MarketValueVerificationMismatch(key, fields)
        for key in sorted(set(expected) & set(actual), key=str)
        if (fields := _field_mismatches(expected[key], actual[key]))
    )
    return MarketValueVerificationResult(
        expected=len(expected),
        persisted=len(actual),
        verified=len(expected) - len(missing) - len(mismatches),
        missing_keys=missing,
        unexpected_keys=unexpected,
        mismatches=mismatches,
    )


__all__ = [
    "MarketValuePointConflictError",
    "MarketValuePointDraft",
    "MarketValueVerificationMismatch",
    "MarketValueVerificationResult",
    "MarketValueWriteResult",
    "persist_market_value_points",
    "publication_reasons_text",
    "verify_market_value_points",
    "version_pairs_text",
]
