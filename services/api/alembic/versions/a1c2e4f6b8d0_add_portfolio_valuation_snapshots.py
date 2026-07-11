"""add portfolio_valuation_snapshots table

Revision ID: a1c2e4f6b8d0
Revises: 29b59c22e9fb
Create Date: 2026-07-11 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c2e4f6b8d0'
down_revision: Union[str, Sequence[str], None] = '29b59c22e9fb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'portfolio_valuation_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('total_items', sa.Integer(), nullable=False),
        sa.Column('total_quantity', sa.Integer(), nullable=False),
        sa.Column('total_cost_basis_jpy', sa.Integer(), nullable=True),
        sa.Column('retail_value_jpy', sa.Integer(), nullable=True),
        sa.Column('liquidation_value_jpy', sa.Integer(), nullable=True),
        sa.Column('market_floor_value_jpy', sa.Integer(), nullable=True),
        sa.Column('pnl_vs_retail_jpy', sa.Integer(), nullable=True),
        sa.Column('pnl_vs_liquidation_jpy', sa.Integer(), nullable=True),
        sa.Column('pnl_vs_market_floor_jpy', sa.Integer(), nullable=True),
        sa.Column('items_missing_yuyutei_sell', sa.Integer(), nullable=False),
        sa.Column('items_missing_yuyutei_buy', sa.Integer(), nullable=False),
        sa.Column('items_missing_snkrdunk_floor', sa.Integer(), nullable=False),
        sa.Column('items_missing_cost_basis', sa.Integer(), nullable=False),
        sa.Column('cards_above_target_sell', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_portfolio_valuation_snapshots_created_at'),
        'portfolio_valuation_snapshots',
        ['created_at'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f('ix_portfolio_valuation_snapshots_created_at'),
        table_name='portfolio_valuation_snapshots',
    )
    op.drop_table('portfolio_valuation_snapshots')
