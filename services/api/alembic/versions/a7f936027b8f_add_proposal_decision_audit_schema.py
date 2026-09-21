"""add proposal decision audit schema

Revision ID: a7f936027b8f
Revises: f4c8a2d91b60

The migration is additive and data-preserving. Existing pending proposal rows
naturally receive NULL decision fields; no proposal, alternative, mapping, or
candidate row is backfilled or otherwise changed.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7f936027b8f"
down_revision: Union[str, Sequence[str], None] = "f4c8a2d91b60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


GROUP_TABLE = "source_mapping_proposal_groups"
ALTERNATIVE_TABLE = "source_mapping_proposal_alternatives"


def upgrade() -> None:
    op.add_column(
        GROUP_TABLE,
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        GROUP_TABLE,
        sa.Column("reviewed_by", sa.String(length=255), nullable=True),
    )
    op.add_column(
        GROUP_TABLE,
        sa.Column("review_notes", sa.Text(), nullable=True),
    )
    op.add_column(
        GROUP_TABLE,
        sa.Column("selected_alternative_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        GROUP_TABLE,
        sa.Column(
            "decision_basis_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_unique_constraint(
        "uq_mapping_proposal_alternatives_id_group",
        ALTERNATIVE_TABLE,
        ["id", "proposal_group_id"],
    )
    op.create_foreign_key(
        "fk_mapping_proposal_groups_selected_alternative_same_group",
        GROUP_TABLE,
        ALTERNATIVE_TABLE,
        ["selected_alternative_id", "id"],
        ["id", "proposal_group_id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_check_constraint(
        "ck_mapping_proposal_groups_decision_lifecycle",
        GROUP_TABLE,
        "(review_status = 'pending' AND "
        "reviewed_at IS NULL AND reviewed_by IS NULL AND review_notes IS NULL AND "
        "selected_alternative_id IS NULL AND decision_basis_updated_at IS NULL AND "
        "resulting_source_card_mapping_id IS NULL) OR "
        "(review_status = 'approved' AND "
        "reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND "
        "length(trim(reviewed_by, ' \t\n\r')) > 0 AND "
        "selected_alternative_id IS NOT NULL AND "
        "decision_basis_updated_at IS NOT NULL AND "
        "resulting_source_card_mapping_id IS NOT NULL) OR "
        "(review_status = 'rejected' AND "
        "reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND "
        "length(trim(reviewed_by, ' \t\n\r')) > 0 AND review_notes IS NOT NULL AND "
        "length(trim(review_notes, ' \t\n\r')) > 0 AND "
        "selected_alternative_id IS NULL AND "
        "decision_basis_updated_at IS NOT NULL AND "
        "resulting_source_card_mapping_id IS NULL)",
    )
    op.create_index(
        "uq_mapping_proposal_alternatives_one_approved_per_group",
        ALTERNATIVE_TABLE,
        ["proposal_group_id"],
        unique=True,
        postgresql_where=sa.text("review_disposition = 'approved'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_mapping_proposal_alternatives_one_approved_per_group",
        table_name=ALTERNATIVE_TABLE,
    )
    op.drop_constraint(
        "ck_mapping_proposal_groups_decision_lifecycle",
        GROUP_TABLE,
        type_="check",
    )
    op.drop_constraint(
        "fk_mapping_proposal_groups_selected_alternative_same_group",
        GROUP_TABLE,
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_mapping_proposal_alternatives_id_group",
        ALTERNATIVE_TABLE,
        type_="unique",
    )
    op.drop_column(GROUP_TABLE, "decision_basis_updated_at")
    op.drop_column(GROUP_TABLE, "selected_alternative_id")
    op.drop_column(GROUP_TABLE, "review_notes")
    op.drop_column(GROUP_TABLE, "reviewed_by")
    op.drop_column(GROUP_TABLE, "reviewed_at")
