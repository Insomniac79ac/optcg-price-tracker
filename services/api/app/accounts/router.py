"""/me: the signed-in collector's own collection, watchlist, preferences and account.

Every route sits behind ``COLLECTOR_ACCOUNTS_ENABLED`` (404 while off, checked
before authentication) and ``require_current_user`` (401 without a valid
bearer token). Every read and write is scoped to that user.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.accounts import service, valuation
from app.accounts.config import require_accounts_enabled
from app.accounts.schemas import (
    CollectionEntryCreateIn,
    CollectionEntryOut,
    CollectionEntryUpdateIn,
    CollectionOut,
    CollectionValueOut,
    CoverageOut,
    MoverOut,
    MoversOut,
    PaidOut,
    PreferencesIn,
    PreferencesOut,
    ReleaseShareOut,
    StepOut,
    WatchlistEntryCreateIn,
    WatchlistEntryOut,
    WatchlistEntryUpdateIn,
    WatchlistOut,
)
from app.auth import require_current_user
from app.db import get_db
from app.models.user import User

router = APIRouter(prefix="/me", tags=["me"], dependencies=[Depends(require_accounts_enabled)])

PRIVATE = {"Cache-Control": "private, no-store"}
MOVERS_PER_DIRECTION = 5


def _private(response: Response) -> None:
    response.headers.update(PRIVATE)


def _coverage(coverage: valuation.Coverage) -> CoverageOut:
    return CoverageOut(
        value_jpy=coverage.value_jpy,
        priced_cards=coverage.priced_cards,
        total_cards=coverage.total_cards,
        priced_entries=coverage.priced_entries,
        total_entries=coverage.total_entries,
        unresolved_entries=coverage.unresolved_entries,
        coverage_pct=coverage.coverage_pct,
    )


def _step(step: valuation.EndpointStep) -> dict:
    return dict(
        available=step.available,
        reason=step.reason,
        from_date=step.prior_date,
        to_date=step.current_date,
        missing_dates=list(step.missing_dates),
        comparable_cards=step.comparable_cards,
        prior_comparable_jpy=step.prior_comparable_jpy if step.available else None,
        current_comparable_jpy=step.current_comparable_jpy if step.available else None,
        change_jpy=step.change_jpy,
        change_pct=step.change_pct,
        exclusions=dict(step.exclusions),
    )


def _mover(mover: valuation.Mover) -> MoverOut:
    return MoverOut(**mover.__dict__)


def _valued_collection(db: Session, user: User):
    entries = service.list_collection(db, user.id)
    dates = valuation.receipt_dates(db)
    as_of = valuation.latest_verified_day(db, dates)
    values = (
        valuation.load_day_values(
            db, as_of, {e.card_print_id for e in entries if e.card_print_id is not None}
        )
        if as_of is not None
        else {}
    )
    rows, coverage = valuation.value_entries(entries, values)
    return entries, dates, as_of, values, rows, coverage


# --------------------------------------------------------------------------
# Collection
# --------------------------------------------------------------------------


def _entry_out(entry, row: valuation.EntryValue, prints: dict) -> CollectionEntryOut:
    return CollectionEntryOut(
        id=entry.id,
        card_print_id=entry.card_print_id,
        resolution=entry.resolution,
        quantity=entry.quantity,
        paid_jpy_per_card=entry.paid_jpy_per_card,
        acquired_on=entry.acquired_on,
        note=entry.note,
        legacy_card_id=entry.legacy_card_id,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        print=prints.get(entry.card_print_id),
        value_status=row.status,
        value_per_card_jpy=row.value_per_card_jpy,
        value_jpy=row.value_jpy,
    )


def _single_entry_out(db: Session, entry) -> CollectionEntryOut:
    as_of = valuation.latest_verified_day(db)
    values = (
        valuation.load_day_values(db, as_of, [entry.card_print_id])
        if as_of is not None and entry.card_print_id is not None
        else {}
    )
    rows, _ = valuation.value_entries([entry], values)
    prints = service.print_summaries(db, {entry.card_print_id} - {None})
    return _entry_out(entry, rows[0], prints)


@router.get("/collection", response_model=CollectionOut)
def get_collection(
    response: Response,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    _private(response)
    entries, _, as_of, _, rows, coverage = _valued_collection(db, user)
    prints = service.print_summaries(db, {e.card_print_id for e in entries} - {None})
    return CollectionOut(
        as_of=as_of,
        summary=_coverage(coverage),
        entries=[_entry_out(entry, row, prints) for entry, row in zip(entries, rows)],
    )


@router.post("/collection", response_model=CollectionEntryOut, status_code=201)
def add_to_collection(
    body: CollectionEntryCreateIn,
    response: Response,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    _private(response)
    entry = service.add_collection_entry(db, user.id, body.model_dump())
    return _single_entry_out(db, entry)


@router.patch("/collection/{entry_id}", response_model=CollectionEntryOut)
def update_collection_entry(
    entry_id: int,
    body: CollectionEntryUpdateIn,
    response: Response,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    _private(response)
    entry = service.update_collection_entry(
        db, user.id, entry_id, body.model_dump(exclude_unset=True)
    )
    return _single_entry_out(db, entry)


@router.delete("/collection/{entry_id}", status_code=204)
def remove_from_collection(
    entry_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    service.remove_collection_entry(db, user.id, entry_id)
    return Response(status_code=204, headers=PRIVATE)


@router.get("/collection/value", response_model=CollectionValueOut)
def get_collection_value(
    response: Response,
    window: Literal["7d", "30d"] = Query(default="7d"),
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """Value today, what moved it, by set, and what you paid (PLAN C2, C4)."""
    _private(response)
    entries, dates, as_of, values, _, coverage = _valued_collection(db, user)
    inputs = valuation.load_window(
        db, user.id, as_of=as_of, window_days=valuation.WINDOWS[window], dates=dates
    )
    step = valuation.window_step(inputs)
    releases = valuation.by_release(
        db, entries=entries, values=values, total_value=coverage.value_jpy, window=inputs
    )
    paid = valuation.paid_summary(entries, values)
    return CollectionValueOut(
        as_of=as_of,
        window=window,
        summary=_coverage(coverage),
        movers=MoversOut(
            **_step(step),
            up=[_mover(m) for m in step.movers if m.delta_jpy > 0][:MOVERS_PER_DIRECTION],
            down=[_mover(m) for m in step.movers if m.delta_jpy < 0][:MOVERS_PER_DIRECTION],
        ),
        by_release=[
            ReleaseShareOut(
                release_product_id=share.release_product_id,
                release_code=share.official_code,
                release_name=share.display_name,
                value_jpy=share.value_jpy,
                priced_cards=share.priced_cards,
                total_cards=share.total_cards,
                share_pct=share.share_pct,
                change=StepOut(**_step(share.step)),
            )
            for share in releases
        ],
        paid=PaidOut(
            cards_with_paid=paid.cards_with_paid,
            cards_compared=paid.cards_compared,
            total_cards=paid.total_cards,
            paid_jpy=paid.paid_jpy,
            priced_today_jpy=paid.priced_today_jpy,
            change_pct=paid.change_pct,
        ),
    )


# --------------------------------------------------------------------------
# Watchlist
# --------------------------------------------------------------------------


def _watch_out(entry, values: dict, prints: dict) -> WatchlistEntryOut:
    if entry.card_print_id is None:
        status, value = "unresolved", None
    else:
        archived = values.get(entry.card_print_id)
        value = archived.value_jpy if archived is not None else None
        status = "priced" if value is not None else "no_price"
    return WatchlistEntryOut(
        id=entry.id,
        card_print_id=entry.card_print_id,
        resolution=entry.resolution,
        target_jpy=entry.target_jpy,
        note=entry.note,
        legacy_card_id=entry.legacy_card_id,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        print=prints.get(entry.card_print_id),
        value_status=status,
        value_jpy=value,
        target_gap_jpy=(
            value - entry.target_jpy if value is not None and entry.target_jpy is not None else None
        ),
    )


def _watch_values(db: Session, entries):
    as_of = valuation.latest_verified_day(db)
    ids = {e.card_print_id for e in entries} - {None}
    values = valuation.load_day_values(db, as_of, ids) if as_of is not None else {}
    return as_of, values, service.print_summaries(db, ids)


@router.get("/watchlist", response_model=WatchlistOut)
def get_watchlist(
    response: Response,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    _private(response)
    entries = service.list_watchlist(db, user.id)
    as_of, values, prints = _watch_values(db, entries)
    return WatchlistOut(as_of=as_of, entries=[_watch_out(e, values, prints) for e in entries])


@router.post("/watchlist", response_model=WatchlistEntryOut, status_code=201)
def add_to_watchlist(
    body: WatchlistEntryCreateIn,
    response: Response,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    _private(response)
    entry = service.add_watchlist_entry(db, user.id, body.model_dump())
    as_of, values, prints = _watch_values(db, [entry])
    return _watch_out(entry, values, prints)


@router.patch("/watchlist/{entry_id}", response_model=WatchlistEntryOut)
def update_watchlist_entry(
    entry_id: int,
    body: WatchlistEntryUpdateIn,
    response: Response,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    _private(response)
    entry = service.update_watchlist_entry(
        db, user.id, entry_id, body.model_dump(exclude_unset=True)
    )
    as_of, values, prints = _watch_values(db, [entry])
    return _watch_out(entry, values, prints)


@router.delete("/watchlist/{entry_id}", status_code=204)
def remove_from_watchlist(
    entry_id: int,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    service.remove_watchlist_entry(db, user.id, entry_id)
    return Response(status_code=204, headers=PRIVATE)


# --------------------------------------------------------------------------
# Preferences, export, account deletion
# --------------------------------------------------------------------------


@router.get("/preferences", response_model=PreferencesOut)
def get_preferences(
    response: Response,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    _private(response)
    return service.get_preferences(db, user.id)


@router.put("/preferences", response_model=PreferencesOut)
def put_preferences(
    body: PreferencesIn,
    response: Response,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    _private(response)
    return service.put_preferences(db, user.id, body.model_dump())


@router.get("/export")
def export_account(
    response: Response,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    response.headers.update(PRIVATE)
    response.headers["Content-Disposition"] = 'attachment; filename="card-pirate-export.json"'
    return service.export_account(db, user)


@router.get("/export/{section}.csv")
def export_section_csv(
    section: Literal["collection", "watchlist"],
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    data = service.export_account(db, user)
    fields = (
        service.COLLECTION_EXPORT_FIELDS
        if section == "collection"
        else service.WATCHLIST_EXPORT_FIELDS
    )
    return Response(
        content=service.export_csv(data[section], fields),
        media_type="text/csv; charset=utf-8",
        headers={
            **PRIVATE,
            "Content-Disposition": f'attachment; filename="card-pirate-{section}.csv"',
        },
    )


@router.delete("", status_code=204)
def delete_account(
    confirm: str = Query(..., description='Must be exactly "delete my account".'),
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """Permanently deletes the account and everything it owns. Not reversible."""
    if confirm != "delete my account":
        return Response(status_code=422, headers=PRIVATE)
    service.delete_account(db, user.id)
    return Response(status_code=204, headers=PRIVATE)
