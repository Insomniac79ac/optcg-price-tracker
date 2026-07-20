"""add analytics_digest_reports table

Revision ID: c699d532e4cc
Revises: a3f7c9e1b5d2
Create Date: 2026-07-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c699d532e4cc'
down_revision: Union[str, Sequence[str], None] = 'a3f7c9e1b5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'analytics_digest_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('valuation_mode', sa.String(length=32), nullable=False),
        sa.Column('collection_value_jpy', sa.Integer(), nullable=True),
        sa.Column('graded_adjusted_value_jpy', sa.Integer(), nullable=True),
        sa.Column('portfolio_risk_score', sa.Integer(), nullable=True),
        sa.Column('portfolio_risk_level', sa.String(length=16), nullable=True),
        sa.Column('wishlist_target_hits', sa.Integer(), server_default='0', nullable=False),
        sa.Column('buy_review_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('sell_review_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('grading_roi_jpy', sa.Integer(), nullable=True),
        sa.Column('digest_payload_json', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_analytics_digest_reports_created_at',
        'analytics_digest_reports',
        ['created_at'],
    )
    op.create_index(
        'ix_analytics_digest_reports_valuation_mode',
        'analytics_digest_reports',
        ['valuation_mode'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'ix_analytics_digest_reports_valuation_mode', table_name='analytics_digest_reports'
    )
    op.drop_index(
        'ix_analytics_digest_reports_created_at', table_name='analytics_digest_reports'
    )
    op.drop_table('analytics_digest_reports')
