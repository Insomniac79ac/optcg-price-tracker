"""The per-source `source_dispatch_budgets` row (plan §2.4).

Same open/closed rule as app.services.freshness_queue (restated, not imported: that module is a
runtime input of both existing collectors and its helpers are private). A source is open only when
its row is enabled and either carries no pause reason or a pause that has expired. A stop-rule
denial pauses it indefinitely (`source_denial`, no end time); only the owner reopens it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SourceDispatchBudget

PAUSE_SOURCE_DENIAL = "source_denial"


class BudgetClosed(RuntimeError):
    """No budget row, disabled, paused, or not enough requests left in the window."""


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _locked(db: Session, source_id: int) -> SourceDispatchBudget:
    budget = db.scalar(
        select(SourceDispatchBudget)
        .where(SourceDispatchBudget.source_id == source_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if budget is None:
        raise BudgetClosed("source request limit is unconfigured; no run")
    return budget


def is_open(budget: SourceDispatchBudget, now: datetime) -> bool:
    if not budget.enabled:
        return False
    if budget.paused_until is not None:
        return _utc(budget.paused_until) <= now
    return budget.pause_reason is None


@dataclass
class Reservation:
    source_id: int
    planned: int


def reserve(db: Session, source_id: int, planned: int, *, now: datetime) -> Reservation:
    """Reserve `planned` requests for one run, or BudgetClosed. Flushes; the caller commits."""
    if planned <= 0:
        raise ValueError("a run plans at least one request")
    budget = _locked(db, source_id)
    if not is_open(budget, now):
        raise BudgetClosed(f"source is closed ({budget.pause_reason or 'disabled'})")
    elapsed = (now - _utc(budget.window_started_at)).total_seconds()
    if elapsed >= budget.window_seconds:
        windows = int(elapsed // budget.window_seconds)
        budget.window_started_at = _utc(budget.window_started_at) + timedelta(seconds=windows * budget.window_seconds)
        budget.used_requests = 0
    if budget.used_requests + budget.reserved_requests + planned > budget.request_limit:
        raise BudgetClosed(
            f"{planned} requests do not fit: {budget.used_requests} used and {budget.reserved_requests} "
            f"reserved of {budget.request_limit}"
        )
    budget.reserved_requests += planned
    db.flush()
    return Reservation(source_id, planned)


def settle(db: Session, reservation: Reservation, used: int) -> None:
    """Release the reservation and charge what was actually requested. Flushes."""
    budget = _locked(db, reservation.source_id)
    budget.reserved_requests = max(0, budget.reserved_requests - reservation.planned)
    budget.used_requests += used
    db.flush()


def pause_for_denial(db: Session, source_id: int) -> None:
    budget = _locked(db, source_id)
    budget.pause_reason, budget.paused_until = PAUSE_SOURCE_DENIAL, None
    db.flush()
