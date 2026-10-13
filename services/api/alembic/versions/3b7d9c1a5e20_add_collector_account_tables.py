"""Add collector account tables (collector v1 S3).

Additive only: five new empty tables owned by ``users`` (ON DELETE CASCADE).
No existing table, row or evidence changes. Downgrade drops exactly these
tables, which hold no data until the feature flag is turned on.

Revision ID: 3b7d9c1a5e20
Revises: 6c2242f6f439
"""

from alembic import op
import sqlalchemy as sa

revision: str = "3b7d9c1a5e20"
down_revision: str | None = "6c2242f6f439"
branch_labels = None
depends_on = None

_RESOLUTION_CHECK = "resolution IN ('exact', 'unresolved')"
_RESOLUTION_PRESENCE = "(resolution = 'exact') = (card_print_id IS NOT NULL)"
_NOTE_LENGTH = "note IS NULL OR length(note) <= 500"


def _timestamps():
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def _owner():
    return sa.Column(
        "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


def _print(nullable):
    return sa.Column(
        "card_print_id",
        sa.Integer(),
        sa.ForeignKey("card_prints.id", ondelete="RESTRICT"),
        nullable=nullable,
    )


def upgrade():
    op.create_table(
        "collection_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        _owner(),
        _print(True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("paid_jpy_per_card", sa.Integer(), nullable=True),
        sa.Column("acquired_on", sa.Date(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("legacy_collection_item_id", sa.Integer(), nullable=True),
        sa.Column("legacy_card_id", sa.Integer(), nullable=True),
        sa.Column("resolution", sa.String(16), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("user_id", "card_print_id", name="uq_collection_entries_user_print"),
        sa.CheckConstraint("quantity >= 1", name="ck_collection_entries_quantity"),
        sa.CheckConstraint(
            "paid_jpy_per_card IS NULL OR paid_jpy_per_card >= 0",
            name="ck_collection_entries_paid",
        ),
        sa.CheckConstraint(_RESOLUTION_CHECK, name="ck_collection_entries_resolution"),
        sa.CheckConstraint(_RESOLUTION_PRESENCE, name="ck_collection_entries_resolution_print"),
        sa.CheckConstraint(_NOTE_LENGTH, name="ck_collection_entries_note_length"),
    )
    op.create_index("ix_collection_entries_user_id", "collection_entries", ["user_id"])
    op.create_index("ix_collection_entries_card_print_id", "collection_entries", ["card_print_id"])
    op.create_index(
        "uq_collection_entries_legacy_item",
        "collection_entries",
        ["legacy_collection_item_id"],
        unique=True,
        postgresql_where=sa.text("legacy_collection_item_id IS NOT NULL"),
    )

    op.create_table(
        "collection_entry_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        _owner(),
        _print(False),
        sa.Column("quantity_before", sa.Integer(), nullable=False),
        sa.Column("quantity_after", sa.Integer(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "quantity_before >= 0 AND quantity_after >= 0 AND quantity_before <> quantity_after",
            name="ck_collection_entry_events_quantities",
        ),
    )
    op.create_index(
        "ix_collection_entry_events_user_print_time",
        "collection_entry_events",
        ["user_id", "card_print_id", "occurred_at"],
    )

    op.create_table(
        "watchlist_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        _owner(),
        _print(True),
        sa.Column("target_jpy", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("legacy_wishlist_item_id", sa.Integer(), nullable=True),
        sa.Column("legacy_card_id", sa.Integer(), nullable=True),
        sa.Column("resolution", sa.String(16), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("user_id", "card_print_id", name="uq_watchlist_entries_user_print"),
        sa.CheckConstraint("target_jpy IS NULL OR target_jpy > 0", name="ck_watchlist_entries_target"),
        sa.CheckConstraint(_RESOLUTION_CHECK, name="ck_watchlist_entries_resolution"),
        sa.CheckConstraint(_RESOLUTION_PRESENCE, name="ck_watchlist_entries_resolution_print"),
        sa.CheckConstraint(_NOTE_LENGTH, name="ck_watchlist_entries_note_length"),
    )
    op.create_index("ix_watchlist_entries_user_id", "watchlist_entries", ["user_id"])
    op.create_index("ix_watchlist_entries_card_print_id", "watchlist_entries", ["card_print_id"])
    op.create_index(
        "uq_watchlist_entries_legacy_item",
        "watchlist_entries",
        ["legacy_wishlist_item_id"],
        unique=True,
        postgresql_where=sa.text("legacy_wishlist_item_id IS NOT NULL"),
    )

    op.create_table(
        "user_preferences",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("currency", sa.String(3), nullable=False, server_default="JPY"),
        sa.Column("collection_visibility", sa.String(16), nullable=False, server_default="private"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("currency IN ('JPY')", name="ck_user_preferences_currency"),
        sa.CheckConstraint(
            "collection_visibility IN ('private')", name="ck_user_preferences_visibility"
        ),
    )

    op.create_table(
        "collection_value_points",
        _owner(),
        sa.Column("point_date", sa.Date(), nullable=False),
        sa.Column("methodology_version", sa.Integer(), nullable=False),
        sa.Column("value_jpy", sa.BigInteger(), nullable=True),
        sa.Column("priced_cards", sa.Integer(), nullable=False),
        sa.Column("total_cards", sa.Integer(), nullable=False),
        sa.Column("priced_entries", sa.Integer(), nullable=False),
        sa.Column("total_entries", sa.Integer(), nullable=False),
        sa.Column("prior_point_date", sa.Date(), nullable=True),
        sa.Column("comparable_cards", sa.Integer(), nullable=True),
        sa.Column("prior_comparable_jpy", sa.BigInteger(), nullable=True),
        sa.Column("current_comparable_jpy", sa.BigInteger(), nullable=True),
        sa.Column("step_publishable", sa.Boolean(), nullable=True),
        sa.Column("step_reason", sa.String(64), nullable=True),
        sa.Column("segment_number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "point_date", "methodology_version", name="pk_collection_value_points"
        ),
        sa.CheckConstraint(
            "priced_cards >= 0 AND priced_cards <= total_cards "
            "AND priced_entries >= 0 AND priced_entries <= total_entries",
            name="ck_collection_value_points_counts",
        ),
        sa.CheckConstraint(
            "(value_jpy IS NULL) = (priced_cards = 0) AND (value_jpy IS NULL OR value_jpy > 0)",
            name="ck_collection_value_points_value",
        ),
        sa.CheckConstraint(
            "methodology_version > 0", name="ck_collection_value_points_methodology"
        ),
        sa.CheckConstraint("segment_number >= 1", name="ck_collection_value_points_segment"),
    )


_TABLES = (
    "collection_value_points",
    "user_preferences",
    "watchlist_entries",
    "collection_entry_events",
    "collection_entries",
)


def downgrade():
    # The rollback contract is "drop the new EMPTY tables". Once collectors have
    # data here, dropping it is deleting user data: a human decision, not a
    # rollback. Refuse rather than destroy.
    bind = op.get_bind()
    occupied = [
        name
        for name in _TABLES
        if bind.execute(sa.text(f'SELECT EXISTS (SELECT 1 FROM "{name}")')).scalar()
    ]
    if occupied:
        raise RuntimeError(
            "Refusing to drop collector account tables that hold rows: " + ", ".join(occupied)
        )
    op.drop_table("collection_value_points")
    op.drop_table("user_preferences")
    op.drop_index("uq_watchlist_entries_legacy_item", table_name="watchlist_entries")
    op.drop_index("ix_watchlist_entries_card_print_id", table_name="watchlist_entries")
    op.drop_index("ix_watchlist_entries_user_id", table_name="watchlist_entries")
    op.drop_table("watchlist_entries")
    op.drop_index("ix_collection_entry_events_user_print_time", table_name="collection_entry_events")
    op.drop_table("collection_entry_events")
    op.drop_index("uq_collection_entries_legacy_item", table_name="collection_entries")
    op.drop_index("ix_collection_entries_card_print_id", table_name="collection_entries")
    op.drop_index("ix_collection_entries_user_id", table_name="collection_entries")
    op.drop_table("collection_entries")
