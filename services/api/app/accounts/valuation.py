"""Collection value from the archived Market Index (PLAN sections C1, C2, C4).

Per-card value on day *d* is ``market_index_snapshots.index_value_jpy`` for that
exact print on *d*, positive only, on a day with a verified completion receipt:
the same usable value Market Value reads. That archive already excludes Yuyu-Tei
sale prices and never substitutes a struck price; this module adds no fallback
of its own: no forward fill, no nearest date, no live price, no other source.

Rules carried into every result:

* An unresolved entry, or an exact entry with no positive value, is unpriced.
  It is counted in coverage and never contributes 0 to a sum.
* When nothing is priced the value is ``None`` ("No prices yet"), never 0.
* Movers compare only units held at both endpoints, so adding or removing
  cards is never a gain or a loss. Comparability reuses the Market Value rule
  (same index and source-semantics versions, same non-empty contributor set),
  and the 80% comparable-value guard applies at both ends. There is no minimum
  card count for a personal collection (owner decision Q4).

Recorded 7D/30D/ALL history (C3) is S4 and is not computed here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.models import CollectionEntry, CollectionEntryEvent
from app.models.card_print import CardPrint
from app.models.market_index_snapshot import MarketIndexSnapshot
from app.models.market_index_snapshot_completion import MarketIndexSnapshotCompletion
from app.models.release_product import ReleaseProduct
from app.services.market_index_change import eligible_contributor_set
from app.services.market_index_completion import verify_market_index_snapshot_completion
from app.services.market_value import (
    CALCULATION_DECIMAL_PRECISION,
    MIN_COMPARABLE_VALUE_FRACTION,
    MarketValueObservation,
    MarketValueScope,
    _comparability_reason,
)

WINDOWS = {"7d": 7, "30d": 30}
_OVERALL = MarketValueScope.overall()

# Receipts are immutable once written, so a positive verification is reusable
# for the life of the process. Failures are never cached.
_VERIFIED: set[tuple[date, int, str]] = set()


def clear_receipt_cache() -> None:
    _VERIFIED.clear()


def _ratio(numerator: int, denominator: int) -> Decimal:
    with localcontext() as context:
        context.prec = CALCULATION_DECIMAL_PRECISION
        return Decimal(numerator) / Decimal(denominator)


def percent_text(numerator: int, denominator: int) -> str | None:
    """``100 * n / d`` as text with two decimals; None when undefined."""
    if denominator == 0:
        return None
    with localcontext() as context:
        context.prec = CALCULATION_DECIMAL_PRECISION
        value = Decimal(100) * Decimal(numerator) / Decimal(denominator)
        return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))


def change_percent_text(prior: int, current: int) -> str | None:
    return percent_text(current - prior, prior) if prior > 0 else None


# --------------------------------------------------------------------------
# Receipted days and archived values
# --------------------------------------------------------------------------


def receipt_dates(db: Session) -> tuple[date, ...]:
    """Every day that has a completion receipt row, oldest first."""
    return tuple(
        db.scalars(
            select(MarketIndexSnapshotCompletion.snapshot_date).order_by(
                MarketIndexSnapshotCompletion.snapshot_date
            )
        )
    )


def is_verified_day(db: Session, day: date) -> bool:
    receipt = db.execute(
        select(
            MarketIndexSnapshotCompletion.id,
            MarketIndexSnapshotCompletion.snapshot_content_digest,
        ).where(MarketIndexSnapshotCompletion.snapshot_date == day)
    ).first()
    if receipt is None:
        return False
    key = (day, receipt.id, receipt.snapshot_content_digest)
    if key in _VERIFIED:
        return True
    evidence = verify_market_index_snapshot_completion(db, day)
    reasons = set(evidence.failure_reasons)
    # The producer being active only matters for the day it is writing. A
    # receipt is inserted atomically with its rows, so an earlier receipted
    # day is complete whatever today's run is doing.
    if reasons == {"snapshot_in_progress"} and day < datetime.now(timezone.utc).date():
        reasons = set()
    if reasons:
        return False
    _VERIFIED.add(key)
    return True


def latest_verified_day(db: Session, dates: tuple[date, ...] | None = None) -> date | None:
    for day in reversed(dates if dates is not None else receipt_dates(db)):
        if is_verified_day(db, day):
            return day
    return None


@dataclass(frozen=True)
class ArchivedValue:
    observation: MarketValueObservation

    @property
    def value_jpy(self) -> int | None:
        """Positive archived value, else None (unpriced). Never 0."""
        value = self.observation.value_jpy
        return value if value is not None and value > 0 else None


def load_day_values(db: Session, day: date, print_ids: Iterable[int]) -> dict[int, ArchivedValue]:
    """Archived values for these prints on one day.

    Same print eligibility as the Market Value adapter: active, verified,
    Japanese, with an authoritative release. Anything else is simply absent,
    which every caller treats as unpriced.
    """
    ids = sorted(set(print_ids))
    if not ids:
        return {}
    rows = db.execute(
        select(
            MarketIndexSnapshot.card_print_id,
            MarketIndexSnapshot.index_value_jpy,
            MarketIndexSnapshot.index_version,
            MarketIndexSnapshot.source_semantics_version,
            MarketIndexSnapshot.provenance,
            CardPrint.release_product_id,
        )
        .join(CardPrint, CardPrint.id == MarketIndexSnapshot.card_print_id)
        .where(
            MarketIndexSnapshot.snapshot_date == day,
            MarketIndexSnapshot.card_print_id.in_(ids),
            CardPrint.is_active.is_(True),
            CardPrint.verification_status == "verified",
            CardPrint.language == "jp",
            CardPrint.release_product_id.is_not(None),
        )
    ).all()
    values = {}
    for row in rows:
        source_values = row.provenance.get("source_values") if isinstance(row.provenance, dict) else None
        contributors = eligible_contributor_set(source_values)
        values[row.card_print_id] = ArchivedValue(
            MarketValueObservation(
                card_print_id=row.card_print_id,
                value_jpy=row.index_value_jpy,
                index_version=row.index_version,
                source_semantics_version=row.source_semantics_version,
                contributors=frozenset(contributors) if contributors is not None else None,
                release_product_id=row.release_product_id,
            )
        )
    return values


def _end_of_day(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone.utc)


def holdings_at(db: Session, user_id: int, day: date) -> dict[int, int]:
    """Quantity of each exact print held at the end of ``day`` (UTC), from the ledger."""
    held: dict[int, int] = {}
    for event in db.execute(
        select(CollectionEntryEvent.card_print_id, CollectionEntryEvent.quantity_after)
        .where(
            CollectionEntryEvent.user_id == user_id,
            CollectionEntryEvent.occurred_at < _end_of_day(day),
        )
        .order_by(CollectionEntryEvent.occurred_at, CollectionEntryEvent.id)
    ):
        held[event.card_print_id] = event.quantity_after
    return {print_id: quantity for print_id, quantity in held.items() if quantity > 0}


# --------------------------------------------------------------------------
# C2: current value and coverage
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class EntryValue:
    entry_id: int
    card_print_id: int | None
    quantity: int
    value_per_card_jpy: int | None
    value_jpy: int | None
    status: str  # "priced" | "no_price" | "unresolved"


@dataclass(frozen=True)
class Coverage:
    value_jpy: int | None
    priced_cards: int
    total_cards: int
    priced_entries: int
    total_entries: int
    unresolved_entries: int

    @property
    def coverage_pct(self) -> str | None:
        return percent_text(self.priced_cards, self.total_cards)


def value_entries(
    entries: Iterable[CollectionEntry], values: dict[int, ArchivedValue]
) -> tuple[list[EntryValue], Coverage]:
    rows: list[EntryValue] = []
    total_value = priced_cards = total_cards = priced_entries = total_entries = unresolved = 0
    for entry in entries:
        total_entries += 1
        total_cards += entry.quantity
        if entry.card_print_id is None:
            unresolved += 1
            rows.append(EntryValue(entry.id, None, entry.quantity, None, None, "unresolved"))
            continue
        archived = values.get(entry.card_print_id)
        per_card = archived.value_jpy if archived is not None else None
        if per_card is None:
            rows.append(
                EntryValue(entry.id, entry.card_print_id, entry.quantity, None, None, "no_price")
            )
            continue
        priced_entries += 1
        priced_cards += entry.quantity
        total_value += per_card * entry.quantity
        rows.append(
            EntryValue(
                entry.id,
                entry.card_print_id,
                entry.quantity,
                per_card,
                per_card * entry.quantity,
                "priced",
            )
        )
    coverage = Coverage(
        value_jpy=total_value if priced_cards else None,
        priced_cards=priced_cards,
        total_cards=total_cards,
        priced_entries=priced_entries,
        total_entries=total_entries,
        unresolved_entries=unresolved,
    )
    return rows, coverage


# --------------------------------------------------------------------------
# C4: movers and the endpoint step
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Mover:
    card_print_id: int
    units: int
    prior_value_per_card_jpy: int
    current_value_per_card_jpy: int
    delta_jpy: int
    change_pct: str | None
    contribution_pct_points: str | None


@dataclass(frozen=True)
class EndpointStep:
    """Comparable units held at both ends of a window, valued at both ends."""

    available: bool
    reason: str | None
    prior_date: date | None
    current_date: date | None
    prior_priced_jpy: int | None = None
    current_priced_jpy: int | None = None
    comparable_cards: int = 0
    prior_comparable_jpy: int = 0
    current_comparable_jpy: int = 0
    movers: tuple[Mover, ...] = ()
    exclusions: tuple[tuple[str, int], ...] = ()
    missing_dates: tuple[date, ...] = field(default_factory=tuple)

    @property
    def change_jpy(self) -> int | None:
        return self.current_comparable_jpy - self.prior_comparable_jpy if self.available else None

    @property
    def change_pct(self) -> str | None:
        if not self.available:
            return None
        return change_percent_text(self.prior_comparable_jpy, self.current_comparable_jpy)


def _priced_sum(held: dict[int, int], values: dict[int, ArchivedValue]) -> int:
    return sum(
        quantity * values[print_id].value_jpy
        for print_id, quantity in held.items()
        if print_id in values and values[print_id].value_jpy is not None
    )


def endpoint_step(
    *,
    prior_date: date,
    current_date: date,
    prior_held: dict[int, int],
    current_held: dict[int, int],
    prior_values: dict[int, ArchivedValue],
    current_values: dict[int, ArchivedValue],
    restrict_to: set[int] | None = None,
) -> EndpointStep:
    """Pure: P, Q and per-version impact over units held at both endpoints."""
    if restrict_to is not None:
        prior_held = {k: v for k, v in prior_held.items() if k in restrict_to}
        current_held = {k: v for k, v in current_held.items() if k in restrict_to}
    prior_priced = _priced_sum(prior_held, prior_values)
    current_priced = _priced_sum(current_held, current_values)

    exclusions: dict[str, int] = defaultdict(int)
    comparable: list[tuple[int, int, int, int]] = []
    for print_id in sorted(set(prior_held) | set(current_held)):
        units = min(prior_held.get(print_id, 0), current_held.get(print_id, 0))
        if units == 0:
            exclusions["entrant" if print_id not in prior_held else "leaver"] += 1
            continue
        before = prior_values.get(print_id)
        after = current_values.get(print_id)
        reason = _comparability_reason(
            before.observation if before else None,
            after.observation if after else None,
            scope=_OVERALL,
        )
        if reason is not None:
            exclusions[reason] += 1
            continue
        comparable.append((print_id, units, before.value_jpy, after.value_jpy))

    P = sum(units * prior for _, units, prior, _ in comparable)
    Q = sum(units * current for _, units, _, current in comparable)
    common = dict(
        prior_date=prior_date,
        current_date=current_date,
        prior_priced_jpy=prior_priced or None,
        current_priced_jpy=current_priced or None,
        comparable_cards=sum(units for _, units, _, _ in comparable),
        prior_comparable_jpy=P,
        current_comparable_jpy=Q,
        exclusions=tuple(sorted(exclusions.items())),
    )
    if P <= 0:
        return EndpointStep(available=False, reason="no_comparable_cards", **common)
    if (
        _ratio(P, prior_priced) < MIN_COMPARABLE_VALUE_FRACTION
        or _ratio(Q, current_priced) < MIN_COMPARABLE_VALUE_FRACTION
    ):
        return EndpointStep(
            available=False, reason="insufficient_comparable_value_coverage", **common
        )
    movers = tuple(
        sorted(
            (
                Mover(
                    card_print_id=print_id,
                    units=units,
                    prior_value_per_card_jpy=prior,
                    current_value_per_card_jpy=current,
                    delta_jpy=units * (current - prior),
                    change_pct=change_percent_text(prior, current),
                    contribution_pct_points=percent_text(units * (current - prior), P),
                )
                for print_id, units, prior, current in comparable
            ),
            key=lambda mover: (-abs(mover.delta_jpy), mover.card_print_id),
        )
    )
    return EndpointStep(available=True, reason=None, movers=movers, **common)


def _unavailable(reason: str, prior: date | None, current: date | None, **extra) -> EndpointStep:
    return EndpointStep(available=False, reason=reason, prior_date=prior, current_date=current, **extra)


@dataclass(frozen=True)
class WindowInputs:
    """Holdings and archived values at both ends of one window, loaded once."""

    prior_date: date
    current_date: date
    prior_held: dict[int, int]
    current_held: dict[int, int]
    prior_values: dict[int, ArchivedValue]
    current_values: dict[int, ArchivedValue]

    def step(self, restrict_to: set[int] | None = None) -> EndpointStep:
        return endpoint_step(
            prior_date=self.prior_date,
            current_date=self.current_date,
            prior_held=self.prior_held,
            current_held=self.current_held,
            prior_values=self.prior_values,
            current_values=self.current_values,
            restrict_to=restrict_to,
        )


def load_window(
    db: Session,
    user_id: int,
    *,
    as_of: date | None,
    window_days: int,
    dates: tuple[date, ...],
) -> WindowInputs | EndpointStep:
    """Inputs for the window ending on ``as_of``, or why it is unavailable.

    Unavailable, with a reason, when either end is not a verified receipted day
    or any day in between has no receipt: a gap breaks the window exactly as it
    breaks the Market chart. Never reported as 0%.
    """
    if as_of is None:
        return _unavailable("no_prices_yet", None, None)
    prior = as_of - timedelta(days=window_days)
    if not dates or prior < dates[0]:
        return _unavailable("not_enough_price_history", prior, as_of)
    receipted = set(dates)
    missing = tuple(
        prior + timedelta(days=offset)
        for offset in range(window_days + 1)
        if prior + timedelta(days=offset) not in receipted
    )
    if missing:
        return _unavailable("prices_missing", prior, as_of, missing_dates=missing)
    if not is_verified_day(db, prior):
        return _unavailable("prices_missing", prior, as_of, missing_dates=(prior,))

    prior_held = holdings_at(db, user_id, prior)
    current_held = holdings_at(db, user_id, as_of)
    ids = set(prior_held) | set(current_held)
    return WindowInputs(
        prior_date=prior,
        current_date=as_of,
        prior_held=prior_held,
        current_held=current_held,
        prior_values=load_day_values(db, prior, ids),
        current_values=load_day_values(db, as_of, ids),
    )


def window_step(window: WindowInputs | EndpointStep, restrict_to: set[int] | None = None) -> EndpointStep:
    return window.step(restrict_to) if isinstance(window, WindowInputs) else window


# --------------------------------------------------------------------------
# C4: by release, what you paid
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ReleaseShare:
    release_product_id: int | None
    official_code: str | None
    display_name: str | None
    value_jpy: int | None
    priced_cards: int
    total_cards: int
    share_pct: str | None
    step: EndpointStep


def by_release(
    db: Session,
    *,
    entries: list[CollectionEntry],
    values: dict[int, ArchivedValue],
    total_value: int | None,
    window: WindowInputs | EndpointStep,
) -> list[ReleaseShare]:
    """Group current exact entries by authoritative ``CardPrint.release_product_id``.

    Never by card-code prefix. Unresolved entries have no print and are not
    assigned to any release.
    """
    exact = [entry for entry in entries if entry.card_print_id is not None]
    if not exact:
        return []
    release_of = dict(
        db.execute(
            select(CardPrint.id, CardPrint.release_product_id).where(
                CardPrint.id.in_({entry.card_print_id for entry in exact})
            )
        ).all()
    )
    groups: dict[int | None, list[CollectionEntry]] = defaultdict(list)
    for entry in exact:
        groups[release_of.get(entry.card_print_id)].append(entry)
    releases = {
        row.id: row
        for row in db.execute(
            select(ReleaseProduct.id, ReleaseProduct.official_code, ReleaseProduct.display_name).where(
                ReleaseProduct.id.in_([key for key in groups if key is not None])
            )
        )
    }
    shares = []
    for release_id, members in groups.items():
        _, coverage = value_entries(members, values)
        step = window_step(window, {entry.card_print_id for entry in members})
        release = releases.get(release_id)
        shares.append(
            ReleaseShare(
                release_product_id=release_id,
                official_code=release.official_code if release else None,
                display_name=release.display_name if release else None,
                value_jpy=coverage.value_jpy,
                priced_cards=coverage.priced_cards,
                total_cards=coverage.total_cards,
                share_pct=(
                    percent_text(coverage.value_jpy, total_value)
                    if coverage.value_jpy is not None and total_value
                    else None
                ),
                step=step,
            )
        )
    return sorted(shares, key=lambda share: (-(share.value_jpy or 0), share.official_code or "~"))


@dataclass(frozen=True)
class PaidSummary:
    """Only entries with BOTH a price paid and a price today; coverage stated."""

    cards_with_paid: int
    cards_compared: int
    total_cards: int
    paid_jpy: int | None
    priced_today_jpy: int | None

    @property
    def change_pct(self) -> str | None:
        if self.paid_jpy is None or self.priced_today_jpy is None:
            return None
        return change_percent_text(self.paid_jpy, self.priced_today_jpy)


def paid_summary(entries: list[CollectionEntry], values: dict[int, ArchivedValue]) -> PaidSummary:
    paid = today = compared = with_paid = total = 0
    for entry in entries:
        total += entry.quantity
        if entry.paid_jpy_per_card is None:
            continue
        with_paid += entry.quantity
        archived = values.get(entry.card_print_id) if entry.card_print_id is not None else None
        if archived is None or archived.value_jpy is None:
            continue
        compared += entry.quantity
        paid += entry.paid_jpy_per_card * entry.quantity
        today += archived.value_jpy * entry.quantity
    return PaidSummary(
        cards_with_paid=with_paid,
        cards_compared=compared,
        total_cards=total,
        paid_jpy=paid if compared else None,
        priced_today_jpy=today if compared else None,
    )
