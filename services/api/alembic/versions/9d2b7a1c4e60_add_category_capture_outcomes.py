"""Retain independent category results for coalesced product attempts.

Revision ID: 9d2b7a1c4e60
Revises: 7c9e4a12b6d0
"""

from alembic import op
import sqlalchemy as sa

revision: str = "9d2b7a1c4e60"
down_revision: str | None = "7c9e4a12b6d0"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "freshness_attempts", sa.Column("category_outcomes", sa.JSON(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("freshness_attempts", "category_outcomes")
