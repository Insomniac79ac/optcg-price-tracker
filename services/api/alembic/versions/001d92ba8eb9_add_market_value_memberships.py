"""add frozen Market Value membership tables (owner plan A, 2026-10-28)

Revision ID: 001d92ba8eb9
Revises: 7a52e9b48e8a

Additive only: three new, empty, append-only tables. No existing table, row or
constraint changes. Market Value publication then verifies every published day
against the membership frozen with it, instead of today's catalogue.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "001d92ba8eb9"
down_revision: Union[str, Sequence[str], None] = "7a52e9b48e8a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_value_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.String(length=160), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("print_count", sa.Integer(), nullable=False),
        sa.Column("release_count", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("trim(revision, ' \t\n\r') <> ''", name="ck_market_value_memberships_revision_not_blank"),
        sa.CheckConstraint("origin IN ('legacy_rebuilt', 'publication', 'recovery')", name="ck_market_value_memberships_origin"),
        sa.CheckConstraint("print_count > 0 AND release_count >= 0", name="ck_market_value_memberships_counts"),
        sa.PrimaryKeyConstraint("id", name="pk_market_value_memberships"),
        sa.UniqueConstraint("revision", name="uq_market_value_memberships_revision"),
    )
    op.create_table(
        "market_value_membership_prints",
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("card_print_id", sa.Integer(), nullable=False),
        sa.Column("release_product_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["membership_id"], ["market_value_memberships.id"], ondelete="RESTRICT",
                                name="fk_market_value_membership_prints_membership_id"),
        sa.ForeignKeyConstraint(["card_print_id"], ["card_prints.id"], ondelete="RESTRICT",
                                name="fk_market_value_membership_prints_card_print_id"),
        sa.ForeignKeyConstraint(["release_product_id"], ["release_products.id"], ondelete="RESTRICT",
                                name="fk_market_value_membership_prints_release_product_id"),
        sa.PrimaryKeyConstraint("membership_id", "card_print_id", name="pk_market_value_membership_prints"),
    )
    op.create_index(
        "ix_market_value_membership_prints_release",
        "market_value_membership_prints",
        ["membership_id", "release_product_id"],
    )
    op.create_table(
        "market_value_membership_releases",
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("release_product_id", sa.Integer(), nullable=False),
        sa.Column("official_code", sa.String(length=64), nullable=False),
        sa.CheckConstraint("trim(official_code, ' \t\n\r') <> ''",
                           name="ck_market_value_membership_releases_code_not_blank"),
        sa.ForeignKeyConstraint(["membership_id"], ["market_value_memberships.id"], ondelete="RESTRICT",
                                name="fk_market_value_membership_releases_membership_id"),
        sa.ForeignKeyConstraint(["release_product_id"], ["release_products.id"], ondelete="RESTRICT",
                                name="fk_market_value_membership_releases_release_product_id"),
        sa.PrimaryKeyConstraint("membership_id", "release_product_id", name="pk_market_value_membership_releases"),
    )


def downgrade() -> None:
    op.drop_table("market_value_membership_releases")
    op.drop_index("ix_market_value_membership_prints_release", table_name="market_value_membership_prints")
    op.drop_table("market_value_membership_prints")
    op.drop_table("market_value_memberships")
