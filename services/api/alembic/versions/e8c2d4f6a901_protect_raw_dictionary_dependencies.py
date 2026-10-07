"""Protect lossless RAW dictionary dependencies without rewriting evidence.

Revision ID: e8c2d4f6a901
Revises: c4e8a1d7b902
"""

from alembic import op
import sqlalchemy as sa

revision = "e8c2d4f6a901"
down_revision = "c4e8a1d7b902"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "raw_snapshot_dictionaries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("base_snapshot_id", sa.Integer(), nullable=False),
        sa.Column("original_sha256", sa.String(64), nullable=False),
        sa.Column("base_sha256", sa.String(64), nullable=False),
        sa.Column("original_bytes", sa.Integer(), nullable=False),
        sa.Column("encoded_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expanded_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["id"], ["raw_snapshots.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["base_snapshot_id"], ["raw_snapshots.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "base_snapshot_id < id", name="ck_raw_dictionary_older_base"
        ),
        sa.CheckConstraint(
            "original_bytes BETWEEN 1 AND 8388608 AND encoded_bytes > 0",
            name="ck_raw_dictionary_bounds",
        ),
    )
    op.create_index(
        "ix_raw_dictionary_base", "raw_snapshot_dictionaries", ["base_snapshot_id"]
    )


def downgrade():
    # Application rollback leaves dependency protection installed. Schema
    # reversal is allowed only for a never-used, empty representation ledger.
    bind = op.get_bind()
    if bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM raw_snapshot_dictionaries)")
    ).scalar():
        raise RuntimeError("retain used RAW dependency protection during rollback")
    op.drop_index("ix_raw_dictionary_base", table_name="raw_snapshot_dictionaries")
    op.drop_table("raw_snapshot_dictionaries")
