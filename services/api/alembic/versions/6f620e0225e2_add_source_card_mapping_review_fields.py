"""add source_card_mappings review fields (is_active, review_status, review_notes, last_verified_at)

Revision ID: 6f620e0225e2
Revises: 32bd832a93c7
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6f620e0225e2'
down_revision: Union[str, Sequence[str], None] = '32bd832a93c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'source_card_mappings',
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    )
    op.add_column(
        'source_card_mappings',
        sa.Column('review_status', sa.String(length=32), server_default='approved', nullable=False),
    )
    op.add_column(
        'source_card_mappings',
        sa.Column('review_notes', sa.Text(), nullable=True),
    )
    op.add_column(
        'source_card_mappings',
        sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        'ck_source_card_mappings_review_status',
        'source_card_mappings',
        "review_status IN ('approved', 'needs_review', 'rejected')",
    )
    op.create_index(
        'ix_source_card_mappings_is_active', 'source_card_mappings', ['is_active'],
    )
    op.create_index(
        'ix_source_card_mappings_review_status', 'source_card_mappings', ['review_status'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_source_card_mappings_review_status', table_name='source_card_mappings')
    op.drop_index('ix_source_card_mappings_is_active', table_name='source_card_mappings')
    op.drop_constraint(
        'ck_source_card_mappings_review_status', 'source_card_mappings', type_='check',
    )
    op.drop_column('source_card_mappings', 'last_verified_at')
    op.drop_column('source_card_mappings', 'review_notes')
    op.drop_column('source_card_mappings', 'review_status')
    op.drop_column('source_card_mappings', 'is_active')
