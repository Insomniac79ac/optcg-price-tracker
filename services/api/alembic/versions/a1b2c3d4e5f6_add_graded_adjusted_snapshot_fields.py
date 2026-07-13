"""add graded adjusted snapshot fields

Revision ID: a1b2c3d4e5f6
Revises: 69eec76fef67
Create Date: 2026-07-13 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '69eec76fef67'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'portfolio_valuation_snapshots',
        sa.Column('graded_adjusted_value_jpy', sa.Integer(), nullable=True),
    )
    op.add_column(
        'portfolio_valuation_snapshots',
        sa.Column('pnl_vs_graded_adjusted_jpy', sa.Integer(), nullable=True),
    )
    op.add_column(
        'portfolio_valuation_snapshots',
        sa.Column('items_using_graded_value', sa.Integer(), nullable=True),
    )
    op.add_column(
        'portfolio_valuation_snapshots',
        sa.Column('items_using_raw_fallback', sa.Integer(), nullable=True),
    )
    op.add_column(
        'portfolio_valuation_snapshots',
        sa.Column('items_missing_graded_adjusted_value', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('portfolio_valuation_snapshots', 'items_missing_graded_adjusted_value')
    op.drop_column('portfolio_valuation_snapshots', 'items_using_raw_fallback')
    op.drop_column('portfolio_valuation_snapshots', 'items_using_graded_value')
    op.drop_column('portfolio_valuation_snapshots', 'pnl_vs_graded_adjusted_jpy')
    op.drop_column('portfolio_valuation_snapshots', 'graded_adjusted_value_jpy')
