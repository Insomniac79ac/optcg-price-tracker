"""add market_workflow_runs table

Revision ID: f1a4c9d7b2e8
Revises: e5f2b8a1c3d6
Create Date: 2026-07-12 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a4c9d7b2e8'
down_revision: Union[str, Sequence[str], None] = 'e5f2b8a1c3d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'market_workflow_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=16), server_default='running', nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('limit', sa.Integer(), nullable=True),
        sa.Column('send_telegram', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('price_refresh_run_id', sa.Integer(), nullable=True),
        sa.Column('portfolio_snapshot_id', sa.Integer(), nullable=True),
        sa.Column('market_report_id', sa.Integer(), nullable=True),
        sa.Column('signal_events_created', sa.Integer(), server_default='0', nullable=False),
        sa.Column('signal_events_updated', sa.Integer(), server_default='0', nullable=False),
        sa.Column('signal_events_resolved', sa.Integer(), server_default='0', nullable=False),
        sa.Column('telegram_digest_status', sa.String(length=16), nullable=True),
        sa.Column('warnings_json', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'partial_success', 'failed')",
            name='ck_market_workflow_runs_status',
        ),
        sa.ForeignKeyConstraint(
            ['price_refresh_run_id'], ['price_refresh_runs.id'], ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(
            ['portfolio_snapshot_id'], ['portfolio_valuation_snapshots.id'], ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(
            ['market_report_id'], ['market_intelligence_reports.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_market_workflow_runs_started_at', 'market_workflow_runs', ['started_at']
    )
    op.create_index('ix_market_workflow_runs_status', 'market_workflow_runs', ['status'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_market_workflow_runs_status', table_name='market_workflow_runs')
    op.drop_index('ix_market_workflow_runs_started_at', table_name='market_workflow_runs')
    op.drop_table('market_workflow_runs')
