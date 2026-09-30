"""Durable category retry gates, separate from evidence freshness.

Revision ID: c4e8a1d7b902
Revises: 9d2b7a1c4e60
"""

from alembic import op
import sqlalchemy as sa

revision: str = "c4e8a1d7b902"
down_revision: str | None = "9d2b7a1c4e60"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "freshness_price_states",
        sa.Column("consecutive_failures", sa.Integer(), nullable=True),
    )
    op.add_column(
        "freshness_price_states",
        sa.Column("retry_not_before_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_freshness_price_failure_streak",
        "freshness_price_states",
        "consecutive_failures IS NULL OR consecutive_failures BETWEEN 0 AND 8",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_freshness_price_failure_streak", "freshness_price_states", type_="check"
    )
    op.drop_column("freshness_price_states", "retry_not_before_at")
    op.drop_column("freshness_price_states", "consecutive_failures")
