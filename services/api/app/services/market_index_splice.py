"""The splice at a source cutover (new-sources plan §2.6; owner decision Q6: splice, not break).

WHAT A SPLICE IS. Adding a source to the Market Index is a SOURCE_SEMANTICS_VERSION step (v -> v+1).
Without a splice every comparison across that day is refused (market_index_change.comparability_refusal)
and every 7D/30D window that crosses it is null for a month. With an approved `market_index_splices` row
for day D, the snapshot job also archives each print's index on the OLD basis on D (the same source
values with the added source left out, combined by the same `_compute_index_fields`), so:

    D-1 -> D   compares old basis to old basis (baseline vs the splice snapshot),
    D   -> D+1 compares new basis to new basis (the ordinary D snapshot vs later),

and a window across D is the product of the two legs. Each leg passes the unchanged comparability
guards on its own, the contributor-set test included; nothing here relaxes them.

INERT. Nothing changes until a splice row exists, and each row is a RED owner decision (D4, C4). With
no row, every function below returns what the caller computed before, and the readers that call into
this module issue no extra query unless the two ends of a comparison already disagree on
source_semantics_version.

RULES (plan §2.6): one splice per source; to_version = from_version + 1 (also a CHECK); at least
MIN_DAYS_BETWEEN_SPLICES days from any other splice, so a 7D window crosses at most one (a 30D window
that crosses two is refused, not chained twice); never on a day with another version change (an
INDEX_VERSION step on D makes the first leg fail its own index_version guard); the date is today or
later, because the old basis can only be archived on the day itself.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timezone
from fractions import Fraction
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MarketIndexSnapshot
from app.schemas import PrintMarketIndexOut
from app.services.market_index import _compute_index_fields, _SourceValue
from app.services.market_index_change import comparability_refusal, snapshot_source_values
from app.source_products.models import MarketIndexSplice, MarketIndexSpliceSnapshot

MIN_DAYS_BETWEEN_SPLICES = 14

REFUSE_NOT_ONE_STEP = "splice_not_one_version_step"
REFUSE_SOURCE_ALREADY_SPLICED = "source_already_spliced"
REFUSE_TOO_CLOSE = "splice_within_14_days_of_another"
REFUSE_IN_THE_PAST = "splice_date_in_the_past"
REFUSE_VERSION_ORDER = "splice_does_not_continue_the_last_version"
REFUSE_BLANK_APPROVER = "splice_approver_blank"


class SpliceRefused(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


@dataclass(frozen=True)
class Splice:
    """A projection of one market_index_splices row, so the rules are testable without a database."""

    id: int
    splice_date: date
    from_version: int
    to_version: int
    source_added: str

    @classmethod
    def from_row(cls, row: MarketIndexSplice) -> "Splice":
        return cls(row.id, row.splice_date, row.from_semantics_version, row.to_semantics_version, row.source_added)


def check_new_splice(
    existing: Sequence[Splice],
    *,
    splice_date: date,
    from_version: int,
    to_version: int,
    source_added: str,
    approved_by: str,
    today: date,
) -> None:
    """Raise SpliceRefused unless a new splice may be recorded. Writes nothing."""
    if not approved_by.strip():
        raise SpliceRefused(REFUSE_BLANK_APPROVER, "A splice is an owner decision and names who approved it.")
    if to_version != from_version + 1:
        raise SpliceRefused(REFUSE_NOT_ONE_STEP, f"{from_version} -> {to_version} is not one version step.")
    if splice_date < today:
        raise SpliceRefused(REFUSE_IN_THE_PAST, "The old basis can only be archived on the splice day itself.")
    if any(s.source_added == source_added for s in existing):
        raise SpliceRefused(REFUSE_SOURCE_ALREADY_SPLICED, f"{source_added} already has a splice.")
    for other in existing:
        if abs((other.splice_date - splice_date).days) < MIN_DAYS_BETWEEN_SPLICES:
            raise SpliceRefused(
                REFUSE_TOO_CLOSE, f"{other.splice_date} is within {MIN_DAYS_BETWEEN_SPLICES} days of {splice_date}."
            )
    if existing:
        last = max(existing, key=lambda s: s.splice_date)
        if splice_date < last.splice_date or from_version != last.to_version:
            raise SpliceRefused(
                REFUSE_VERSION_ORDER, f"The last splice ends at version {last.to_version} on {last.splice_date}."
            )


def load_splices(db: Session) -> tuple[Splice, ...]:
    return tuple(Splice.from_row(r) for r in db.scalars(select(MarketIndexSplice)).all())


def splice_on(splices: Iterable[Splice], day: date) -> Splice | None:
    return next((s for s in splices if s.splice_date == day), None)


def splice_between(
    splices: Iterable[Splice], *, from_version: int, to_version: int, after: date, on_or_before: date
) -> Splice | None:
    """The one splice a comparison from `after` to `on_or_before` crosses, or None (none, or several)."""
    crossed = [s for s in splices if after < s.splice_date <= on_or_before]
    if len(crossed) != 1:
        return None
    splice = crossed[0]
    if (splice.from_version, splice.to_version) != (from_version, to_version):
        return None
    return splice


# --- writing the old basis on the splice day -------------------------------------------------


def _as_source_value(value: Any) -> _SourceValue:
    return _SourceValue(
        source=value.source,
        reference_type=value.reference_type,
        evidence_type=value.evidence_type,
        value_jpy=value.value_jpy,
        observed_at=value.observed_at,
        sample_size=value.sample_size,
        stale=value.stale,
        eligible=value.eligible,
        fallback_used=value.fallback_used,
        ineligible_reason=value.ineligible_reason,
        constraint=value.constraint,
    )


def old_basis_fields(market_index: PrintMarketIndexOut, splice: Splice) -> dict:
    """The print's index on the old basis: the same source values without the added source,
    combined by the unchanged `_compute_index_fields`, labelled with the old semantics version."""
    if market_index.source_semantics_version != splice.to_version:
        raise SpliceRefused(
            REFUSE_VERSION_ORDER,
            f"The live index is version {market_index.source_semantics_version}, the splice ends at {splice.to_version}.",
        )
    kept = [_as_source_value(v) for v in market_index.source_values if v.source != splice.source_added]
    calculated_at = market_index.calculated_at
    naive = calculated_at.astimezone(timezone.utc).replace(tzinfo=None) if calculated_at.tzinfo else calculated_at
    fields = _compute_index_fields(kept, [], naive)
    fields["source_semantics_version"] = splice.from_version
    return fields


def build_splice_snapshot_row(market_index: PrintMarketIndexOut, splice: Splice) -> dict:
    fields = old_basis_fields(market_index, splice)
    calculated_at = fields["calculated_at"]
    return {
        "splice_id": splice.id,
        "card_print_id": market_index.card_print_id,
        "snapshot_date": calculated_at.date(),
        "index_value_jpy": fields["index_value_jpy"],
        "calculation_method": fields["calculation_method"],
        "source_count": fields["source_count"],
        "coverage_status": fields["coverage_status"],
        "confidence": fields["confidence"],
        "index_version": fields["index_version"],
        "source_semantics_version": fields["source_semantics_version"],
        "calculated_at": calculated_at,
        "provenance": {"source_values": [v.model_dump(mode="json") for v in fields["source_values"]]},
    }


def write_splice_snapshots(db: Session, splice: Splice, indexes: Iterable[PrintMarketIndexOut]) -> int:
    """Insert the old-basis rows for the splice day, ignoring prints already written. Flushes only."""
    rows = [build_splice_snapshot_row(mi, splice) for mi in indexes]
    if not rows:
        return 0
    if any(row["snapshot_date"] != splice.splice_date for row in rows):
        raise SpliceRefused(REFUSE_IN_THE_PAST, "Old-basis rows are written only on the splice day.")
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    table = MarketIndexSpliceSnapshot.__table__
    db.execute(dialect_insert(table).values(rows).on_conflict_do_nothing(index_elements=["splice_id", "card_print_id"]))
    db.flush()
    return len(rows)


# --- comparing across a splice ---------------------------------------------------------------


@dataclass(frozen=True)
class IndexPoint:
    """One end of a comparison: an archived snapshot, a splice snapshot or the live index."""

    value_jpy: int | None
    index_version: int
    source_semantics_version: int
    source_values: Any

    @classmethod
    def from_snapshot(cls, row: MarketIndexSnapshot | MarketIndexSpliceSnapshot) -> "IndexPoint":
        return cls(row.index_value_jpy, row.index_version, row.source_semantics_version, snapshot_source_values(row))

    @classmethod
    def from_live(cls, market_index: PrintMarketIndexOut) -> "IndexPoint":
        return cls(
            market_index.index_value_jpy,
            market_index.index_version,
            market_index.source_semantics_version,
            market_index.source_values,
        )


def _refusal(start: IndexPoint, end: IndexPoint) -> str | None:
    return comparability_refusal(
        baseline_value=start.value_jpy,
        baseline_index_version=start.index_version,
        baseline_source_semantics_version=start.source_semantics_version,
        baseline_source_values=start.source_values,
        current_value=end.value_jpy,
        current_index_version=end.index_version,
        current_source_semantics_version=end.source_semantics_version,
        current_source_values=end.source_values,
    )


def spliced_ratio(
    baseline: IndexPoint, old_on_splice: IndexPoint, new_on_splice: IndexPoint, current: IndexPoint
) -> tuple[Fraction | None, str | None]:
    """current / baseline across the splice as an exact ratio, or the refusal of either leg."""
    for start, end in ((baseline, old_on_splice), (new_on_splice, current)):
        refusal = _refusal(start, end)
        if refusal is not None:
            return None, refusal
    return (
        Fraction(old_on_splice.value_jpy, baseline.value_jpy) * Fraction(current.value_jpy, new_on_splice.value_jpy),
        None,
    )


def spliced_percent(
    baseline: IndexPoint, old_on_splice: IndexPoint, new_on_splice: IndexPoint, current: IndexPoint
) -> float | None:
    ratio, _ = spliced_ratio(baseline, old_on_splice, new_on_splice, current)
    return None if ratio is None else float((ratio - 1) * 100)


def splice_points_for_prints(
    db: Session, splice: Splice, print_ids: Sequence[int]
) -> tuple[dict[int, IndexPoint], dict[int, IndexPoint]]:
    """(old basis on D, new basis on D) per print, two queries."""
    old = db.scalars(
        select(MarketIndexSpliceSnapshot).where(
            MarketIndexSpliceSnapshot.splice_id == splice.id,
            MarketIndexSpliceSnapshot.card_print_id.in_(list(print_ids)),
        )
    ).all()
    new = db.scalars(
        select(MarketIndexSnapshot).where(
            MarketIndexSnapshot.card_print_id.in_(list(print_ids)),
            MarketIndexSnapshot.snapshot_date == splice.splice_date,
        )
    ).all()
    return (
        {r.card_print_id: IndexPoint.from_snapshot(r) for r in old},
        {r.card_print_id: IndexPoint.from_snapshot(r) for r in new},
    )


def spliced_ratio_between(
    db: Session, print_id: int, start: MarketIndexSnapshot, end: MarketIndexSnapshot
) -> Fraction | None:
    """end / start for two archived rows of one print across exactly one splice, else None."""
    if start.source_semantics_version == end.source_semantics_version:
        return None
    splices = load_splices(db)
    splice = splice_between(
        splices,
        from_version=start.source_semantics_version,
        to_version=end.source_semantics_version,
        after=start.snapshot_date,
        on_or_before=end.snapshot_date,
    )
    if splice is None:
        return None
    old_on_splice, new_on_splice = splice_points_for_prints(db, splice, [print_id])
    if print_id not in old_on_splice or print_id not in new_on_splice:
        return None
    ratio, _ = spliced_ratio(
        IndexPoint.from_snapshot(start), old_on_splice[print_id], new_on_splice[print_id], IndexPoint.from_snapshot(end)
    )
    return ratio
