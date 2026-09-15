"""link source collection attempts to raw snapshots

Revision ID: e3a7c5d9b102
Revises: a8b2c4d6e901

Adds only nullable lineage. Existing attempt rows remain NULL: no historical
snapshot relationship is guessed or backfilled.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3a7c5d9b102"
down_revision: Union[str, Sequence[str], None] = "a8b2c4d6e901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FOREIGN_KEY_NAME = "fk_source_collection_attempts_raw_snapshot_id"
INDEX_NAME = "ix_source_collection_attempts_raw_snapshot_id"


def upgrade() -> None:
    op.add_column(
        "source_collection_attempts",
        sa.Column("raw_snapshot_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        FOREIGN_KEY_NAME,
        "source_collection_attempts",
        "raw_snapshots",
        ["raw_snapshot_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        INDEX_NAME,
        "source_collection_attempts",
        ["raw_snapshot_id"],
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="source_collection_attempts")
    op.drop_constraint(
        FOREIGN_KEY_NAME,
        "source_collection_attempts",
        type_="foreignkey",
    )
    op.drop_column("source_collection_attempts", "raw_snapshot_id")
