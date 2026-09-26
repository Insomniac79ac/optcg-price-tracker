"""add market_value_points

One additive, empty table for deterministic Market Value v1 replay.  The
revision does not read or write snapshot/CPI data and does not alter any
existing object.  Its parent is the exact staging head present after PR #19.

Revision ID: d5f7a9c2e4b6
Revises: c4e9a2b7816d
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5f7a9c2e4b6"
down_revision: Union[str, Sequence[str], None] = "c4e9a2b7816d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "market_value_points"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope_kind", sa.String(length=16), nullable=False),
        sa.Column("release_product_id", sa.Integer(), nullable=True),
        sa.Column("methodology_version", sa.Integer(), nullable=False),
        sa.Column("point_date", sa.Date(), nullable=False),
        sa.Column("tracked_value_jpy", sa.BigInteger(), nullable=True),
        sa.Column("priced_print_count", sa.Integer(), nullable=False),
        sa.Column("total_physical_print_count", sa.Integer(), nullable=False),
        sa.Column("prior_point_date", sa.Date(), nullable=True),
        sa.Column("step_days", sa.Integer(), nullable=True),
        sa.Column("prior_tracked_value_jpy", sa.BigInteger(), nullable=True),
        sa.Column("prior_priced_print_count", sa.Integer(), nullable=True),
        sa.Column("prior_total_physical_print_count", sa.Integer(), nullable=True),
        sa.Column("comparable_print_count", sa.Integer(), nullable=True),
        sa.Column("prior_comparable_value_jpy", sa.BigInteger(), nullable=True),
        sa.Column("current_comparable_value_jpy", sa.BigInteger(), nullable=True),
        # No precision/scale is deliberate. A2 emits a 50-significant-digit
        # Decimal, while an open-ended chain has no finite worst-case place
        # count. PostgreSQL's arbitrary-precision NUMERIC preserves it.
        sa.Column("step_ratio", sa.Numeric(), nullable=True),
        sa.Column("segment_number", sa.Integer(), nullable=False),
        sa.Column("performance_factor", sa.Numeric(), nullable=False),
        sa.Column("step_publication_eligible", sa.Boolean(), nullable=True),
        sa.Column("publication_reasons", sa.Text(), nullable=True),
        sa.Column("membership_revision", sa.String(length=160), nullable=False),
        sa.Column("prior_version_pairs", sa.Text(), nullable=True),
        sa.Column("current_version_pairs", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["release_product_id"],
            ["release_products.id"],
            name="fk_market_value_points_release_product_id",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.CheckConstraint(
            "scope_kind IN ('overall', 'release')",
            name="ck_market_value_points_scope_kind",
        ),
        sa.CheckConstraint(
            "(scope_kind = 'overall' AND release_product_id IS NULL) OR "
            "(scope_kind = 'release' AND release_product_id IS NOT NULL)",
            name="ck_market_value_points_scope_identity",
        ),
        sa.CheckConstraint(
            "methodology_version > 0",
            name="ck_market_value_points_methodology_version_positive",
        ),
        sa.CheckConstraint(
            "priced_print_count >= 0 AND total_physical_print_count >= 0 "
            "AND priced_print_count <= total_physical_print_count",
            name="ck_market_value_points_current_counts",
        ),
        sa.CheckConstraint(
            "(priced_print_count = 0 AND tracked_value_jpy IS NULL) OR "
            "(priced_print_count > 0 AND tracked_value_jpy > 0)",
            name="ck_market_value_points_current_value_presence",
        ),
        sa.CheckConstraint(
            "(prior_point_date IS NULL) = (step_days IS NULL) "
            "AND (prior_point_date IS NULL) = "
            "(prior_priced_print_count IS NULL) "
            "AND (prior_point_date IS NULL) = "
            "(prior_total_physical_print_count IS NULL) "
            "AND (prior_point_date IS NULL) = "
            "(comparable_print_count IS NULL) "
            "AND (prior_point_date IS NULL) = "
            "(prior_comparable_value_jpy IS NULL) "
            "AND (prior_point_date IS NULL) = "
            "(current_comparable_value_jpy IS NULL) "
            "AND (prior_point_date IS NULL) = "
            "(step_publication_eligible IS NULL) "
            "AND (prior_point_date IS NULL) = "
            "(publication_reasons IS NULL) "
            "AND (prior_point_date IS NULL) = "
            "(prior_version_pairs IS NULL)",
            name="ck_market_value_points_step_pairing",
        ),
        sa.CheckConstraint(
            "prior_point_date IS NULL OR "
            "(prior_point_date < point_date AND step_days >= 1)",
            name="ck_market_value_points_step_order",
        ),
        sa.CheckConstraint(
            "prior_priced_print_count IS NULL OR "
            "(prior_priced_print_count >= 0 "
            "AND prior_total_physical_print_count >= 0 "
            "AND prior_priced_print_count <= prior_total_physical_print_count)",
            name="ck_market_value_points_prior_counts",
        ),
        sa.CheckConstraint(
            "prior_priced_print_count IS NULL OR "
            "(prior_priced_print_count = 0 AND prior_tracked_value_jpy IS NULL) OR "
            "(prior_priced_print_count > 0 AND prior_tracked_value_jpy > 0)",
            name="ck_market_value_points_prior_value_presence",
        ),
        sa.CheckConstraint(
            "comparable_print_count IS NULL OR "
            "(comparable_print_count >= 0 "
            "AND comparable_print_count <= priced_print_count "
            "AND comparable_print_count <= prior_priced_print_count)",
            name="ck_market_value_points_comparable_counts",
        ),
        sa.CheckConstraint(
            "comparable_print_count IS NULL OR "
            "(comparable_print_count = 0 "
            "AND prior_comparable_value_jpy = 0 "
            "AND current_comparable_value_jpy = 0 "
            "AND step_ratio IS NULL) OR "
            "(comparable_print_count > 0 "
            "AND prior_comparable_value_jpy > 0 "
            "AND current_comparable_value_jpy > 0 "
            "AND step_ratio > 0)",
            name="ck_market_value_points_comparable_value_presence",
        ),
        sa.CheckConstraint(
            "prior_comparable_value_jpy IS NULL OR "
            "(prior_comparable_value_jpy <= COALESCE(prior_tracked_value_jpy, 0) "
            "AND current_comparable_value_jpy <= COALESCE(tracked_value_jpy, 0))",
            name="ck_market_value_points_comparable_values_le_tracked",
        ),
        sa.CheckConstraint(
            "(step_publication_eligible IS NULL) = "
            "(publication_reasons IS NULL)",
            name="ck_market_value_points_publication_pairing",
        ),
        sa.CheckConstraint(
            "step_publication_eligible IS NULL OR "
            "(step_publication_eligible AND publication_reasons = 'publishable') OR "
            "(NOT step_publication_eligible "
            "AND publication_reasons <> 'publishable')",
            name="ck_market_value_points_publication_reason",
        ),
        sa.CheckConstraint(
            "NOT COALESCE(step_publication_eligible, FALSE) OR step_ratio IS NOT NULL",
            name="ck_market_value_points_publishable_has_ratio",
        ),
        sa.CheckConstraint(
            "segment_number >= 0 AND performance_factor > 0",
            name="ck_market_value_points_chain_state",
        ),
        sa.CheckConstraint(
            "prior_point_date IS NOT NULL OR "
            "(segment_number = 0 AND performance_factor = 1 "
            "AND step_ratio IS NULL)",
            name="ck_market_value_points_initial_state",
        ),
        sa.CheckConstraint(
            "step_publication_eligible IS NULL OR step_publication_eligible "
            "OR performance_factor = 1",
            name="ck_market_value_points_break_resets_factor",
        ),
        sa.CheckConstraint(
            "trim(membership_revision, ' \t\n\r') <> ''",
            name="ck_market_value_points_membership_revision_not_blank",
        ),
    )
    # Each unique index is also the exact future range/latest read path. Two
    # indexes are required because PostgreSQL NULL semantics would otherwise
    # permit duplicate Overall natural keys.
    op.create_index(
        "uq_market_value_points_overall_point",
        TABLE,
        ["methodology_version", "point_date"],
        unique=True,
        postgresql_where=sa.text(
            "scope_kind = 'overall' AND release_product_id IS NULL"
        ),
    )
    op.create_index(
        "uq_market_value_points_release_point",
        TABLE,
        ["release_product_id", "methodology_version", "point_date"],
        unique=True,
        postgresql_where=sa.text(
            "scope_kind = 'release' AND release_product_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    # The table is derived entirely from immutable snapshot evidence. This
    # drops only the A3A object and touches no source snapshot or CPI row.
    op.drop_table(TABLE)
