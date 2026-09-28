"""Add empty snapshot completion evidence; never certify historical rows.

Revision ID: e6a8b0c3d5f7
Revises: d5f7a9c2e4b6
"""

from alembic import op
import sqlalchemy as sa

revision: str = "e6a8b0c3d5f7"
down_revision: str | None = "d5f7a9c2e4b6"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "market_index_snapshot_completions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_print_count", sa.Integer(), nullable=False),
        sa.Column("snapshot_row_count", sa.Integer(), nullable=False),
        sa.Column("selected_print_ids_digest", sa.String(64), nullable=False),
        sa.Column("snapshot_content_digest", sa.String(64), nullable=False),
        sa.Column("digest_version", sa.Integer(), nullable=False),
        sa.Column("index_version", sa.Integer(), nullable=False),
        sa.Column("source_semantics_version", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(128), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("receipt_kind", sa.String(16), nullable=False),
        sa.UniqueConstraint("snapshot_date", name="uq_market_index_completion_date"),
        sa.CheckConstraint(
            "expected_print_count > 0 AND snapshot_row_count = expected_print_count",
            name="ck_market_index_completion_counts",
        ),
        sa.CheckConstraint(
            "index_version > 0 AND source_semantics_version > 0",
            name="ck_market_index_completion_versions",
        ),
        sa.CheckConstraint(
            "digest_version = 1", name="ck_market_index_completion_digest_version"
        ),
        sa.CheckConstraint(
            "length(selected_print_ids_digest) = 64 AND length(snapshot_content_digest) = 64",
            name="ck_market_index_completion_digest_length",
        ),
        sa.CheckConstraint(
            "length(trim(run_id)) > 0", name="ck_market_index_completion_run_id"
        ),
        sa.CheckConstraint(
            "receipt_kind = 'atomic'", name="ck_market_index_completion_kind"
        ),
        sa.CheckConstraint(
            "completed_at >= calculated_at", name="ck_market_index_completion_time"
        ),
    )


def downgrade() -> None:
    op.drop_table("market_index_snapshot_completions")
