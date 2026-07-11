"""add market_intelligence_reports table

Revision ID: d3a7c5f1b8e4
Revises: c4f8a1d6e9b2
Create Date: 2026-07-12 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3a7c5f1b8e4'
down_revision: Union[str, Sequence[str], None] = 'c4f8a1d6e9b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'market_intelligence_reports',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('report_date', sa.Date(), nullable=False),
        sa.Column('total_opportunities', sa.Integer(), server_default='0', nullable=False),
        sa.Column('highest_score', sa.Integer(), nullable=True),
        sa.Column('average_score', sa.Float(), nullable=True),
        sa.Column('buy_opportunities_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('sell_opportunities_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('momentum_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('drop_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('data_quality_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('owned_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('portfolio_market_floor_value_jpy', sa.Integer(), nullable=True),
        sa.Column('portfolio_retail_value_jpy', sa.Integer(), nullable=True),
        sa.Column('portfolio_liquidation_value_jpy', sa.Integer(), nullable=True),
        sa.Column('portfolio_pnl_vs_market_floor_jpy', sa.Integer(), nullable=True),
        sa.Column('top_buy_json', sa.JSON(), nullable=True),
        sa.Column('top_sell_json', sa.JSON(), nullable=True),
        sa.Column('top_momentum_json', sa.JSON(), nullable=True),
        sa.Column('top_drop_json', sa.JSON(), nullable=True),
        sa.Column('top_owned_json', sa.JSON(), nullable=True),
        sa.Column('top_data_quality_json', sa.JSON(), nullable=True),
        sa.Column('report_payload_json', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_market_intelligence_reports_report_date',
        'market_intelligence_reports',
        ['report_date'],
    )
    op.create_index(
        'ix_market_intelligence_reports_created_at',
        'market_intelligence_reports',
        ['created_at'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        'ix_market_intelligence_reports_created_at', table_name='market_intelligence_reports'
    )
    op.drop_index(
        'ix_market_intelligence_reports_report_date', table_name='market_intelligence_reports'
    )
    op.drop_table('market_intelligence_reports')
