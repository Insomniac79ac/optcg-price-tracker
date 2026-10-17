"""Per-user reads and writes for /me. Every query is scoped by ``user_id``.

A row owned by someone else is indistinguishable from a missing row (404), so
one user can never learn whether another user's entry id exists.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts.models import (
    CollectionEntry,
    CollectionEntryEvent,
    CollectionValuePoint,
    UserPreferences,
    WatchlistEntry,
)
from app.accounts.schemas import acquired_on_error
from app.models.canonical_card import CanonicalCard
from app.models.card_print import CardPrint
from app.models.file_job import FileJob
from app.models.release_product import ReleaseProduct
from app.models.saved_view import SavedView
from app.models.search_history import SearchHistory
from app.models.user import User
from app.services import file_job_storage

DEFAULT_PREFERENCES = {"currency": "JPY", "collection_visibility": "private"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def require_collectable_print(db: Session, card_print_id: int) -> CardPrint:
    """Only an existing, active print can be added. Identity is never inferred."""
    printing = db.get(CardPrint, card_print_id)
    if printing is None or not printing.is_active:
        raise HTTPException(status_code=404, detail="Card version not found")
    return printing


def print_summaries(db: Session, print_ids: set[int]) -> dict[int, dict[str, Any]]:
    if not print_ids:
        return {}
    rows = db.execute(
        select(
            CardPrint.id,
            CardPrint.treatment,
            CardPrint.official_asset_variant,
            CardPrint.release_product_id,
            CanonicalCard.card_code,
            CanonicalCard.name_en,
            CanonicalCard.name_jp,
            ReleaseProduct.official_code,
            ReleaseProduct.display_name,
        )
        .join(CanonicalCard, CanonicalCard.id == CardPrint.canonical_card_id)
        .outerjoin(ReleaseProduct, ReleaseProduct.id == CardPrint.release_product_id)
        .where(CardPrint.id.in_(print_ids))
    ).all()
    return {
        row.id: {
            "card_print_id": row.id,
            "card_code": row.card_code,
            "name_en": row.name_en,
            "name_jp": row.name_jp,
            "treatment": row.treatment,
            "official_asset_variant": row.official_asset_variant,
            "release_product_id": row.release_product_id,
            "release_code": row.official_code,
            "release_name": row.display_name,
        }
        for row in rows
    }


# --------------------------------------------------------------------------
# Collection
# --------------------------------------------------------------------------


def list_collection(db: Session, user_id: int) -> list[CollectionEntry]:
    return list(
        db.scalars(
            select(CollectionEntry)
            .where(CollectionEntry.user_id == user_id)
            .order_by(CollectionEntry.created_at, CollectionEntry.id)
        )
    )


def get_collection_entry(db: Session, user_id: int, entry_id: int) -> CollectionEntry:
    entry = db.scalar(
        select(CollectionEntry).where(
            CollectionEntry.id == entry_id, CollectionEntry.user_id == user_id
        )
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Collection entry not found")
    return entry


def record_quantity_change(
    db: Session, *, user_id: int, card_print_id: int | None, before: int, after: int
) -> None:
    """Ledger row for an exact print. Unresolved rows are not holdings of any print."""
    if card_print_id is None or before == after:
        return
    db.add(
        CollectionEntryEvent(
            user_id=user_id,
            card_print_id=card_print_id,
            quantity_before=before,
            quantity_after=after,
            occurred_at=_now(),
        )
    )


def add_collection_entry(db: Session, user_id: int, data: dict[str, Any]) -> CollectionEntry:
    require_collectable_print(db, data["card_print_id"])
    existing = db.scalar(
        select(CollectionEntry.id).where(
            CollectionEntry.user_id == user_id,
            CollectionEntry.card_print_id == data["card_print_id"],
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="This card version is already in your collection")
    entry = CollectionEntry(user_id=user_id, resolution="exact", **data)
    db.add(entry)
    record_quantity_change(
        db, user_id=user_id, card_print_id=entry.card_print_id, before=0, after=entry.quantity
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="This card version is already in your collection"
        ) from exc
    db.refresh(entry)
    return entry


def update_collection_entry(
    db: Session, user_id: int, entry_id: int, changes: dict[str, Any]
) -> CollectionEntry:
    entry = get_collection_entry(db, user_id, entry_id)
    if "quantity" in changes and changes["quantity"] is None:
        raise HTTPException(status_code=422, detail="quantity cannot be null; remove the entry instead")
    if "acquired_on" in changes and changes["acquired_on"] != entry.acquired_on:
        error = acquired_on_error(changes["acquired_on"])
        if error:
            raise HTTPException(status_code=422, detail=error)
    before = entry.quantity
    for key, value in changes.items():
        setattr(entry, key, value)
    record_quantity_change(
        db, user_id=user_id, card_print_id=entry.card_print_id, before=before, after=entry.quantity
    )
    db.commit()
    db.refresh(entry)
    return entry


def remove_collection_entry(db: Session, user_id: int, entry_id: int) -> None:
    entry = get_collection_entry(db, user_id, entry_id)
    record_quantity_change(
        db, user_id=user_id, card_print_id=entry.card_print_id, before=entry.quantity, after=0
    )
    db.delete(entry)
    db.commit()


# --------------------------------------------------------------------------
# Watchlist
# --------------------------------------------------------------------------


def list_watchlist(db: Session, user_id: int) -> list[WatchlistEntry]:
    return list(
        db.scalars(
            select(WatchlistEntry)
            .where(WatchlistEntry.user_id == user_id)
            .order_by(WatchlistEntry.created_at, WatchlistEntry.id)
        )
    )


def get_watchlist_entry(db: Session, user_id: int, entry_id: int) -> WatchlistEntry:
    entry = db.scalar(
        select(WatchlistEntry).where(WatchlistEntry.id == entry_id, WatchlistEntry.user_id == user_id)
    )
    if entry is None:
        raise HTTPException(status_code=404, detail="Watchlist entry not found")
    return entry


def add_watchlist_entry(db: Session, user_id: int, data: dict[str, Any]) -> WatchlistEntry:
    require_collectable_print(db, data["card_print_id"])
    existing = db.scalar(
        select(WatchlistEntry.id).where(
            WatchlistEntry.user_id == user_id,
            WatchlistEntry.card_print_id == data["card_print_id"],
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="You are already watching this card version")
    entry = WatchlistEntry(user_id=user_id, resolution="exact", **data)
    db.add(entry)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="You are already watching this card version"
        ) from exc
    db.refresh(entry)
    return entry


def update_watchlist_entry(
    db: Session, user_id: int, entry_id: int, changes: dict[str, Any]
) -> WatchlistEntry:
    entry = get_watchlist_entry(db, user_id, entry_id)
    for key, value in changes.items():
        setattr(entry, key, value)
    db.commit()
    db.refresh(entry)
    return entry


def remove_watchlist_entry(db: Session, user_id: int, entry_id: int) -> None:
    db.delete(get_watchlist_entry(db, user_id, entry_id))
    db.commit()


# --------------------------------------------------------------------------
# Preferences
# --------------------------------------------------------------------------


def get_preferences(db: Session, user_id: int) -> dict[str, str]:
    row = db.get(UserPreferences, user_id)
    if row is None:
        return dict(DEFAULT_PREFERENCES)
    return {"currency": row.currency, "collection_visibility": row.collection_visibility}


def put_preferences(db: Session, user_id: int, values: dict[str, str]) -> dict[str, str]:
    row = db.get(UserPreferences, user_id)
    if row is None:
        row = UserPreferences(user_id=user_id)
        db.add(row)
    row.currency = values["currency"]
    row.collection_visibility = values["collection_visibility"]
    db.commit()
    return get_preferences(db, user_id)


# --------------------------------------------------------------------------
# Export and deletion
# --------------------------------------------------------------------------

COLLECTION_EXPORT_FIELDS = (
    "id",
    "card_print_id",
    "resolution",
    "quantity",
    "paid_jpy_per_card",
    "acquired_on",
    "note",
    "legacy_card_id",
    "created_at",
    "updated_at",
)
WATCHLIST_EXPORT_FIELDS = (
    "id",
    "card_print_id",
    "resolution",
    "target_jpy",
    "note",
    "legacy_card_id",
    "created_at",
    "updated_at",
)
EVENT_EXPORT_FIELDS = ("card_print_id", "quantity_before", "quantity_after", "occurred_at")
VALUE_POINT_EXPORT_FIELDS = (
    "point_date",
    "methodology_version",
    "value_jpy",
    "priced_cards",
    "total_cards",
)

# Rows delete_account also removes (security audit 2026-10-16, F5), so the
# export covers everything we store. File jobs list metadata only: storage
# paths are internal, and the files themselves are the user's own uploads
# and earlier exports.
SAVED_VIEW_EXPORT_FIELDS = (
    "name",
    "description",
    "route_path",
    "view_type",
    "scope",
    "filters_json",
    "sort_json",
    "columns_json",
    "density",
    "is_default",
    "pinned",
    "last_used_at",
    "usage_count",
    "notes",
    "created_at",
    "updated_at",
)
SEARCH_HISTORY_EXPORT_FIELDS = ("query", "result_count", "created_at")
FILE_JOB_EXPORT_FIELDS = (
    "job_type",
    "status",
    "original_filename",
    "output_filename",
    "mode",
    "dry_run",
    "created_at",
    "started_at",
    "finished_at",
)


def _plain(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _rows(objects, fields) -> list[dict[str, Any]]:
    return [{name: _plain(getattr(obj, name)) for name in fields} for obj in objects]


def export_account(db: Session, user: User) -> dict[str, Any]:
    """Everything stored about this user, generated on request; nothing is kept."""
    events = db.scalars(
        select(CollectionEntryEvent)
        .where(CollectionEntryEvent.user_id == user.id)
        .order_by(CollectionEntryEvent.occurred_at, CollectionEntryEvent.id)
    )
    points = db.scalars(
        select(CollectionValuePoint)
        .where(CollectionValuePoint.user_id == user.id)
        .order_by(CollectionValuePoint.point_date, CollectionValuePoint.methodology_version)
    )
    saved_views = db.scalars(
        select(SavedView).where(SavedView.user_id == user.id).order_by(SavedView.created_at, SavedView.id)
    )
    searches = db.scalars(
        select(SearchHistory)
        .where(SearchHistory.user_id == user.id)
        .order_by(SearchHistory.created_at, SearchHistory.id)
    )
    file_jobs = db.scalars(
        select(FileJob).where(FileJob.user_id == user.id).order_by(FileJob.created_at, FileJob.id)
    )
    return {
        "format": "card-pirate-account-export-v1",
        "exported_at": _now().isoformat(),
        "currency": "JPY",
        "profile": {
            "email": user.email,
            "name": user.name,
            "avatar_url": user.avatar_url,
            "member_since": _plain(user.created_at),
        },
        "preferences": get_preferences(db, user.id),
        "collection": _rows(list_collection(db, user.id), COLLECTION_EXPORT_FIELDS),
        "collection_history": _rows(events, EVENT_EXPORT_FIELDS),
        "watchlist": _rows(list_watchlist(db, user.id), WATCHLIST_EXPORT_FIELDS),
        "collection_value_points": _rows(points, VALUE_POINT_EXPORT_FIELDS),
        "saved_views": _rows(saved_views, SAVED_VIEW_EXPORT_FIELDS),
        "search_history": _rows(searches, SEARCH_HISTORY_EXPORT_FIELDS),
        "file_jobs": _rows(file_jobs, FILE_JOB_EXPORT_FIELDS),
    }


def export_csv(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(fields), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def delete_account(db: Session, user_id: int) -> None:
    """Delete the user and everything they own.

    The database cascade removes every collector-account table and the legacy
    CASCADE tables (collection_items, wishlist_items, collector_tags,
    collector_groups and their children). Rows that would otherwise survive
    are deleted explicitly first:

    * ``saved_views`` and ``search_history`` reference users with SET NULL,
      which would keep the rows (the plan said CASCADE; the schema says SET NULL);
    * ``file_jobs`` carries ``user_id`` with no foreign key at all. A user's jobs
      are their own legacy collection/wishlist CSV imports and exports; admin
      backup jobs have no user. Their stored input/output files hold the user's
      data, so they are deleted too, after the commit, exactly as
      ``cleanup_old_file_jobs`` does.

    The account tables are also deleted explicitly so the result does not depend
    on the database enforcing foreign keys (SQLite in tests does not by default).
    """
    job_files = [
        path
        for row in db.execute(
            select(FileJob.input_file_path, FileJob.output_file_path).where(FileJob.user_id == user_id)
        )
        for path in row
        if path
    ]
    for model in (
        CollectionEntryEvent,
        CollectionValuePoint,
        CollectionEntry,
        WatchlistEntry,
        UserPreferences,
        SavedView,
        SearchHistory,
        FileJob,
    ):
        db.execute(delete(model).where(model.user_id == user_id))
    db.execute(delete(User).where(User.id == user_id))
    db.commit()
    for path in job_files:
        file_job_storage.delete_file(path)
