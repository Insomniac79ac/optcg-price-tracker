"""Add card_print_image_assets: verified R2 copies of official card images.

Additive only: one new empty table. No existing table, row or evidence changes.

Revision ID: 6c2242f6f439
Revises: f9e5b4a8c012
"""

from alembic import op
import sqlalchemy as sa

revision: str = "6c2242f6f439"
down_revision: str | None = "f9e5b4a8c012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "card_print_image_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "card_print_id",
            sa.Integer(),
            sa.ForeignKey("card_prints.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_url", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("object_key", sa.String(255), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("cache_control", sa.String(128), nullable=True),
        sa.Column("verification_method", sa.String(64), nullable=False),
        sa.Column("mirrored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "card_print_id", "source_url", name="uq_card_print_image_assets_print_source"
        ),
        sa.CheckConstraint("length(sha256) = 64", name="ck_card_print_image_assets_sha256"),
        sa.CheckConstraint(
            "byte_size > 0 AND width > 0 AND height > 0",
            name="ck_card_print_image_assets_positive",
        ),
    )
    op.create_index(
        "ix_card_print_image_assets_card_print_id", "card_print_image_assets", ["card_print_id"]
    )
    op.create_index("ix_card_print_image_assets_sha256", "card_print_image_assets", ["sha256"])


def downgrade():
    op.drop_index("ix_card_print_image_assets_sha256", table_name="card_print_image_assets")
    op.drop_index("ix_card_print_image_assets_card_print_id", table_name="card_print_image_assets")
    op.drop_table("card_print_image_assets")
