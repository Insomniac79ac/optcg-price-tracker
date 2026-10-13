"""Collector account tables (PLAN section B1).

Not imported by ``app.models``: collectors import that package. Every table is
owned by one user and is removed with that user (ON DELETE CASCADE on
``users.id``). Prints are referenced with RESTRICT, like the Market Index
archive: a print someone holds is never deleted out from under them.

A row with ``resolution='unresolved'`` came from a legacy row whose card could
not be mapped to exactly one CardPrint. It has no ``card_print_id`` and is never
priced.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

RESOLUTIONS = ("exact", "unresolved")
CURRENCIES = ("JPY",)
VISIBILITIES = ("private",)
NOTE_MAX_LENGTH = 500

_RESOLUTION_CHECK = "resolution IN ('exact', 'unresolved')"
# Both directions in one equality, so neither half can drift.
_RESOLUTION_PRESENCE = "(resolution = 'exact') = (card_print_id IS NOT NULL)"
_NOTE_LENGTH = f"note IS NULL OR length(note) <= {NOTE_MAX_LENGTH}"


class CollectionEntry(Base):
    __tablename__ = "collection_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "card_print_id", name="uq_collection_entries_user_print"),
        CheckConstraint("quantity >= 1", name="ck_collection_entries_quantity"),
        CheckConstraint(
            "paid_jpy_per_card IS NULL OR paid_jpy_per_card >= 0",
            name="ck_collection_entries_paid",
        ),
        CheckConstraint(_RESOLUTION_CHECK, name="ck_collection_entries_resolution"),
        CheckConstraint(_RESOLUTION_PRESENCE, name="ck_collection_entries_resolution_print"),
        CheckConstraint(_NOTE_LENGTH, name="ck_collection_entries_note_length"),
        Index(
            "uq_collection_entries_legacy_item",
            "legacy_collection_item_id",
            unique=True,
            postgresql_where=text("legacy_collection_item_id IS NOT NULL"),
            sqlite_where=text("legacy_collection_item_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    card_print_id: Mapped[int | None] = mapped_column(
        ForeignKey("card_prints.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    paid_jpy_per_card: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acquired_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(String(NOTE_MAX_LENGTH), nullable=True)
    # Plain integers, no foreign keys: the legacy tables are dropped later (S9)
    # and these only make the copy idempotent and traceable.
    legacy_collection_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    legacy_card_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CollectionEntryEvent(Base):
    """Append-only holdings ledger: one row per quantity change of an exact print.

    Adding a card is ``0 -> n``, removing it is ``n -> 0``. History reads the
    quantity held at the end of a day from here, so a card added today is an
    entrant, never a gain.
    """

    __tablename__ = "collection_entry_events"
    __table_args__ = (
        CheckConstraint(
            "quantity_before >= 0 AND quantity_after >= 0 AND quantity_before <> quantity_after",
            name="ck_collection_entry_events_quantities",
        ),
        Index(
            "ix_collection_entry_events_user_print_time",
            "user_id",
            "card_print_id",
            "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    card_print_id: Mapped[int] = mapped_column(
        ForeignKey("card_prints.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_before: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_after: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WatchlistEntry(Base):
    __tablename__ = "watchlist_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "card_print_id", name="uq_watchlist_entries_user_print"),
        CheckConstraint(
            "target_jpy IS NULL OR target_jpy > 0", name="ck_watchlist_entries_target"
        ),
        CheckConstraint(_RESOLUTION_CHECK, name="ck_watchlist_entries_resolution"),
        CheckConstraint(_RESOLUTION_PRESENCE, name="ck_watchlist_entries_resolution_print"),
        CheckConstraint(_NOTE_LENGTH, name="ck_watchlist_entries_note_length"),
        Index(
            "uq_watchlist_entries_legacy_item",
            "legacy_wishlist_item_id",
            unique=True,
            postgresql_where=text("legacy_wishlist_item_id IS NOT NULL"),
            sqlite_where=text("legacy_wishlist_item_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    card_print_id: Mapped[int | None] = mapped_column(
        ForeignKey("card_prints.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    target_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(String(NOTE_MAX_LENGTH), nullable=True)
    legacy_wishlist_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    legacy_card_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolution: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class UserPreferences(Base):
    """No row means defaults. The CHECK lists widen when a choice actually ships."""

    __tablename__ = "user_preferences"
    __table_args__ = (
        CheckConstraint("currency IN ('JPY')", name="ck_user_preferences_currency"),
        CheckConstraint(
            "collection_visibility IN ('private')",
            name="ck_user_preferences_visibility",
        ),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="JPY", server_default="JPY"
    )
    collection_visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="private", server_default="private"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CollectionValuePoint(Base):
    """One recorded collection value per user per completed market day (PLAN C3).

    Created here; written by the S4 daily stage, insert-only. ``value_jpy`` is
    NULL when nothing was priced, never 0.
    """

    __tablename__ = "collection_value_points"
    __table_args__ = (
        PrimaryKeyConstraint(
            "user_id", "point_date", "methodology_version", name="pk_collection_value_points"
        ),
        CheckConstraint(
            "priced_cards >= 0 AND priced_cards <= total_cards "
            "AND priced_entries >= 0 AND priced_entries <= total_entries",
            name="ck_collection_value_points_counts",
        ),
        CheckConstraint(
            "(value_jpy IS NULL) = (priced_cards = 0) AND (value_jpy IS NULL OR value_jpy > 0)",
            name="ck_collection_value_points_value",
        ),
        CheckConstraint("methodology_version > 0", name="ck_collection_value_points_methodology"),
        CheckConstraint("segment_number >= 1", name="ck_collection_value_points_segment"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    point_date: Mapped[date] = mapped_column(Date, nullable=False)
    methodology_version: Mapped[int] = mapped_column(Integer, nullable=False)
    value_jpy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    priced_cards: Mapped[int] = mapped_column(Integer, nullable=False)
    total_cards: Mapped[int] = mapped_column(Integer, nullable=False)
    priced_entries: Mapped[int] = mapped_column(Integer, nullable=False)
    total_entries: Mapped[int] = mapped_column(Integer, nullable=False)
    prior_point_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    comparable_cards: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prior_comparable_jpy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    current_comparable_jpy: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    step_publishable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    step_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    segment_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


ACCOUNT_TABLES = (
    CollectionEntry.__tablename__,
    CollectionEntryEvent.__tablename__,
    WatchlistEntry.__tablename__,
    UserPreferences.__tablename__,
    CollectionValuePoint.__tablename__,
)
