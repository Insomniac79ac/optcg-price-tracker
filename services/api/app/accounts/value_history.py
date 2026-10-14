"""Recorded collection value history (PLAN sections B3, C3, C4; S4).

Two parts:

* ``run_stage``: the daily stage. After the Market Index receipt gate (and
  after Market Value and the Card Pirate Index), it writes one
  ``collection_value_points`` row per user holding at least one exact card,
  for the receipted day only. Insert-only: ``ON CONFLICT DO NOTHING`` and then
  every stored field is compared with the recomputed draft, like the Market
  Value writer. It owns its job lock, session and transaction, so nothing it
  does can change or block the earlier stages. A missed day stays missing
  (a break); nothing is backfilled.
* Reads: 7D/30D/ALL change chained from the stored daily steps, and the
  day-one preview (current cards over archived values, derived on read and
  never stored).

Per-card values and comparability come from ``app.accounts.valuation``
(``load_day_values`` and ``endpoint_step``), which is the Market Value usable
value: positive archived Market Index values on receipted days only, Yuyu-Tei
sale prices never included, no forward fill. The 80% comparable-value guard
applies at both ends of every step; there is no minimum card count (owner
decision Q4).

Holdings for a day are read from the ledger as of that day's receipt
``completed_at``, the moment its prices became final. The cutoff is in the
past when the stage runs, so a rerun computes the same rows; a change made
later that evening belongs to the next day.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Literal

from sqlalchemy import inspect, select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.accounts import valuation
from app.accounts.models import CollectionEntryEvent, CollectionValuePoint
from app.models.market_index_snapshot_completion import MarketIndexSnapshotCompletion
from app.services.job_locks import with_job_lock
from app.services.market_index_completion import utc
from app.services.market_value import CALCULATION_DECIMAL_PRECISION

LOCK_NAME = "collection_value_history"
METHODOLOGY_VERSION = 1
PREVIEW_DAYS = 30
HISTORY_WINDOWS: dict[str, int | None] = {"7d": 7, "30d": 30, "all": None}
HistoryWindow = Literal["7d", "30d", "all"]

PUBLISHABLE = "publishable"
PRIOR_DAY_MISSING = "prior_day_missing"

# Every stored column the stage derives; compared on conflict.
DRAFT_FIELDS = (
    "user_id",
    "point_date",
    "methodology_version",
    "value_jpy",
    "priced_cards",
    "total_cards",
    "priced_entries",
    "total_entries",
    "prior_point_date",
    "comparable_cards",
    "prior_comparable_jpy",
    "current_comparable_jpy",
    "step_publishable",
    "step_reason",
    "segment_number",
)


class StageAbort(RuntimeError):
    """A fail-closed refusal. The transaction is rolled back."""


class CollectionValuePointConflict(StageAbort):
    def __init__(self, key: tuple[int, date, int], fields: tuple[str, ...]):
        super().__init__(f"stored collection value point {key} differs in {', '.join(fields)}")


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------


def receipt_cutoff(db: Session, day: date) -> datetime | None:
    completed = db.scalar(
        select(MarketIndexSnapshotCompletion.completed_at).where(
            MarketIndexSnapshotCompletion.snapshot_date == day
        )
    )
    return utc(completed) if completed is not None else None


def holdings_by_user(db: Session, cutoff: datetime) -> dict[int, dict[int, int]]:
    """Exact prints held by every user at ``cutoff`` (quantity > 0 only)."""
    latest: dict[int, dict[int, int]] = defaultdict(dict)
    for event in db.execute(
        select(
            CollectionEntryEvent.user_id,
            CollectionEntryEvent.card_print_id,
            CollectionEntryEvent.quantity_after,
        )
        .where(CollectionEntryEvent.occurred_at < cutoff)
        .order_by(CollectionEntryEvent.occurred_at, CollectionEntryEvent.id)
    ):
        latest[event.user_id][event.card_print_id] = event.quantity_after
    held = {
        user_id: {print_id: qty for print_id, qty in prints.items() if qty > 0}
        for user_id, prints in latest.items()
    }
    return {user_id: prints for user_id, prints in held.items() if prints}


# --------------------------------------------------------------------------
# Daily point (pure)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PointDraft:
    user_id: int
    point_date: date
    methodology_version: int
    value_jpy: int | None
    priced_cards: int
    total_cards: int
    priced_entries: int
    total_entries: int
    prior_point_date: date | None
    comparable_cards: int | None
    prior_comparable_jpy: int | None
    current_comparable_jpy: int | None
    step_publishable: bool
    step_reason: str
    segment_number: int

    @property
    def key(self) -> tuple[int, date, int]:
        return (self.user_id, self.point_date, self.methodology_version)

    def values(self) -> dict:
        return {name: getattr(self, name) for name in DRAFT_FIELDS}


def build_point(
    *,
    user_id: int,
    day: date,
    held: dict[int, int],
    values: dict[int, valuation.ArchivedValue],
    prior: tuple[dict[int, int], dict[int, valuation.ArchivedValue]] | None,
    previous_point: tuple[date, int] | None,
) -> PointDraft:
    """One user's point for ``day``.

    ``prior`` is the holdings and values on ``day - 1`` when that day is a
    verified receipted day, else None (the step is a break). ``previous_point``
    is the user's latest stored ``(point_date, segment_number)`` before ``day``.
    """
    priced_cards = priced_entries = value = 0
    for print_id, quantity in held.items():
        archived = values.get(print_id)
        if archived is not None and archived.value_jpy is not None:
            priced_cards += quantity
            priced_entries += 1
            value += quantity * archived.value_jpy

    prior_day = day - timedelta(days=1)
    if prior is None:
        step = None
        publishable, reason = False, PRIOR_DAY_MISSING
    else:
        step = valuation.endpoint_step(
            prior_date=prior_day,
            current_date=day,
            prior_held=prior[0],
            current_held=held,
            prior_values=prior[1],
            current_values=values,
        )
        publishable, reason = step.available, step.reason or PUBLISHABLE

    if previous_point is None:
        segment = 1
    elif publishable and previous_point[0] == prior_day:
        segment = previous_point[1]
    else:
        segment = previous_point[1] + 1

    has_comparable = step is not None and step.prior_comparable_jpy > 0
    return PointDraft(
        user_id=user_id,
        point_date=day,
        methodology_version=METHODOLOGY_VERSION,
        value_jpy=value if priced_cards else None,
        priced_cards=priced_cards,
        total_cards=sum(held.values()),
        priced_entries=priced_entries,
        total_entries=len(held),
        prior_point_date=prior_day if step is not None else None,
        comparable_cards=step.comparable_cards if step is not None else None,
        prior_comparable_jpy=step.prior_comparable_jpy if has_comparable else None,
        current_comparable_jpy=step.current_comparable_jpy if has_comparable else None,
        step_publishable=publishable,
        step_reason=reason,
        segment_number=segment,
    )


# --------------------------------------------------------------------------
# Daily stage
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class StageResult:
    point_date: date
    users: int
    inserted: int
    existing: int


def _configure_transaction(db: Session) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ WRITE"))
    if db.scalar(text("SHOW transaction_isolation")) != "repeatable read":
        raise StageAbort("PostgreSQL did not enable REPEATABLE READ")


def _insert_statement(db: Session, values: dict):
    table = CollectionValuePoint.__table__
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(table).values(**values)
    elif dialect == "sqlite":
        statement = sqlite_insert(table).values(**values)
    else:
        raise StageAbort("collection value history supports PostgreSQL and test SQLite")
    return statement.on_conflict_do_nothing().returning(table.c.user_id)


def _stored(db: Session, draft: PointDraft) -> CollectionValuePoint | None:
    return db.scalar(
        select(CollectionValuePoint).where(
            CollectionValuePoint.user_id == draft.user_id,
            CollectionValuePoint.point_date == draft.point_date,
            CollectionValuePoint.methodology_version == draft.methodology_version,
        )
    )


def _previous_points(db: Session, day: date) -> dict[int, tuple[date, int]]:
    latest: dict[int, tuple[date, int]] = {}
    for row in db.execute(
        select(
            CollectionValuePoint.user_id,
            CollectionValuePoint.point_date,
            CollectionValuePoint.segment_number,
        )
        .where(
            CollectionValuePoint.point_date < day,
            CollectionValuePoint.methodology_version == METHODOLOGY_VERSION,
        )
        .order_by(CollectionValuePoint.point_date)
    ):
        latest[row.user_id] = (row.point_date, row.segment_number)
    return latest


def plan_points(db: Session, day: date) -> list[PointDraft]:
    """Drafts for every user holding an exact card at ``day``'s receipt cutoff."""
    if not valuation.is_verified_day(db, day):
        raise StageAbort(f"{day} has no verified completion receipt")
    cutoff = receipt_cutoff(db, day)
    holdings = holdings_by_user(db, cutoff)
    if not holdings:
        return []
    prior_day = day - timedelta(days=1)
    prior_cutoff = (
        receipt_cutoff(db, prior_day) if valuation.is_verified_day(db, prior_day) else None
    )
    prior_holdings = holdings_by_user(db, prior_cutoff) if prior_cutoff is not None else {}
    ids = {pid for held in holdings.values() for pid in held}
    values = valuation.load_day_values(db, day, ids)
    prior_ids = ids | {pid for held in prior_holdings.values() for pid in held}
    prior_values = (
        valuation.load_day_values(db, prior_day, prior_ids) if prior_cutoff is not None else {}
    )
    previous = _previous_points(db, day)
    return [
        build_point(
            user_id=user_id,
            day=day,
            held=held,
            values=values,
            prior=(
                (prior_holdings.get(user_id, {}), prior_values)
                if prior_cutoff is not None
                else None
            ),
            previous_point=previous.get(user_id),
        )
        for user_id, held in sorted(holdings.items())
    ]


def write_points(db: Session, drafts: list[PointDraft]) -> tuple[int, int]:
    """Insert-only; every conflict must match the draft exactly."""
    inserted = existing = 0
    with db.begin_nested():
        for draft in drafts:
            if db.execute(_insert_statement(db, draft.values())).scalar_one_or_none() is None:
                existing += 1
            else:
                inserted += 1
            stored = _stored(db, draft)
            if stored is None:
                raise StageAbort(f"collection value point {draft.key} disappeared")
            different = tuple(
                name for name in DRAFT_FIELDS if getattr(stored, name) != getattr(draft, name)
            )
            if different:
                raise CollectionValuePointConflict(draft.key, different)
    return inserted, existing


def run_stage(db: Session, day: date, *, skip_lock: bool = False) -> StageResult:
    """Write ``day``'s points in one transaction under this stage's own lock."""
    with with_job_lock(LOCK_NAME, metadata={"point_date": str(day)}, skip_lock=skip_lock):
        try:
            _configure_transaction(db)
            if not inspect(db.connection()).has_table(CollectionValuePoint.__tablename__):
                raise StageAbort("collection_value_points is absent")
            drafts = plan_points(db, day)
            inserted, existing = write_points(db, drafts)
            db.commit()
        except Exception:
            db.rollback()
            raise
    return StageResult(point_date=day, users=len(drafts), inserted=inserted, existing=existing)


# --------------------------------------------------------------------------
# Reads: recorded 7D / 30D / ALL
# --------------------------------------------------------------------------


def percent_from_ratio(numerator: int, denominator: int) -> str:
    """``100 * (n / d - 1)`` with two decimals, divided once."""
    with localcontext() as context:
        context.prec = CALCULATION_DECIMAL_PRECISION
        value = (Decimal(numerator) / Decimal(denominator) - 1) * 100
        return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))


@dataclass(frozen=True)
class RecordedChange:
    window: str
    available: bool
    reason: str | None
    from_date: date | None
    to_date: date | None
    change_pct: str | None = None
    missing_dates: tuple[date, ...] = ()
    failed_step_date: date | None = None


def list_points(db: Session, user_id: int) -> list[CollectionValuePoint]:
    return list(
        db.scalars(
            select(CollectionValuePoint)
            .where(
                CollectionValuePoint.user_id == user_id,
                CollectionValuePoint.methodology_version == METHODOLOGY_VERSION,
            )
            .order_by(CollectionValuePoint.point_date)
        )
    )


def recorded_change(
    points: list[CollectionValuePoint] | list[PointDraft],
    window: HistoryWindow,
    as_of: date | None,
) -> RecordedChange:
    """Chain the stored daily steps over the window ending on ``as_of``.

    Every day in the window must have a point whose step is publishable and
    compares with the day before; otherwise the window is unavailable with a
    reason, never 0%. Integer products of Q and P, divided once.
    """
    if as_of is None:
        return RecordedChange(window, False, "no_prices_yet", None, None)
    if not points:
        return RecordedChange(window, False, "not_enough_history", None, as_of)
    days = HISTORY_WINDOWS[window]
    start = points[0].point_date if days is None else as_of - timedelta(days=days)
    if start >= as_of or start < points[0].point_date:
        return RecordedChange(window, False, "not_enough_history", start, as_of)
    by_date = {point.point_date: point for point in points}
    span = [start + timedelta(days=offset) for offset in range((as_of - start).days + 1)]
    missing = tuple(day for day in span if day not in by_date)
    if missing:
        return RecordedChange(
            window, False, "history_missing", start, as_of, missing_dates=missing
        )
    numerator = denominator = 1
    for day in span[1:]:
        point = by_date[day]
        if not point.step_publishable or point.prior_point_date != day - timedelta(days=1):
            return RecordedChange(
                window,
                False,
                point.step_reason if not point.step_publishable else PRIOR_DAY_MISSING,
                start,
                as_of,
                failed_step_date=day,
            )
        if not point.prior_comparable_jpy or not point.current_comparable_jpy:
            return RecordedChange(
                window, False, "invalid_step_evidence", start, as_of, failed_step_date=day
            )
        numerator *= point.current_comparable_jpy
        denominator *= point.prior_comparable_jpy
    return RecordedChange(
        window, True, None, start, as_of, change_pct=percent_from_ratio(numerator, denominator)
    )


# --------------------------------------------------------------------------
# Reads: day-one preview (derived on read, never stored)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PreviewPoint:
    date: date
    value_jpy: int | None
    priced_cards: int
    step_publishable: bool | None
    step_reason: str | None


@dataclass(frozen=True)
class Preview:
    from_date: date | None
    to_date: date | None
    total_cards: int
    points: tuple[PreviewPoint, ...]
    change: RecordedChange


def preview(
    db: Session,
    *,
    current_held: dict[int, int],
    as_of: date | None,
    dates: tuple[date, ...],
) -> Preview:
    """How the cards held now would have moved over the last 30 days.

    Today's holdings at every archived day, so only prices move. A day without
    a verified receipt is absent from the series (the line breaks there), and
    the change is chained with the same step rule as the recorded history.
    This is a preview: it is not the collection's recorded history.
    """
    total = sum(current_held.values())
    if as_of is None or not current_held:
        reason = "no_prices_yet" if as_of is None else "no_cards"
        return Preview(None, as_of, total, (), RecordedChange("30d", False, reason, None, as_of))
    start = as_of - timedelta(days=PREVIEW_DAYS)
    receipted = set(dates)
    drafts: list[PointDraft] = []
    points: list[PreviewPoint] = []
    previous: tuple[date, dict[int, valuation.ArchivedValue]] | None = None
    for offset in range(PREVIEW_DAYS + 1):
        day = start + timedelta(days=offset)
        if day not in receipted or not valuation.is_verified_day(db, day):
            continue
        values = valuation.load_day_values(db, day, current_held)
        adjacent = previous is not None and previous[0] == day - timedelta(days=1)
        draft = build_point(
            user_id=0,
            day=day,
            held=current_held,
            values=values,
            prior=(current_held, previous[1]) if adjacent else None,
            previous_point=None,
        )
        drafts.append(draft)
        first = not points
        points.append(
            PreviewPoint(
                date=day,
                value_jpy=draft.value_jpy,
                priced_cards=draft.priced_cards,
                step_publishable=None if first else draft.step_publishable,
                step_reason=None if first else draft.step_reason,
            )
        )
        previous = (day, values)
    change = recorded_change(drafts, "30d", as_of)
    if change.reason == "not_enough_history" and dates and dates[0] < start:
        # The archive reaches back further: an early day is missing, not new.
        span = {start + timedelta(days=offset) for offset in range(PREVIEW_DAYS + 1)}
        missing = tuple(sorted(span - {draft.point_date for draft in drafts}))
        change = RecordedChange("30d", False, "history_missing", start, as_of, missing_dates=missing)
    return Preview(start, as_of, total, tuple(points), change)
