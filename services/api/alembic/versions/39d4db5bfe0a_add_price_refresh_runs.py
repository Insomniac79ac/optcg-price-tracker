"""add price_refresh_runs table

Revision ID: 39d4db5bfe0a
Revises: bdb3db201c18
Create Date: 2026-07-10 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '39d4db5bfe0a'
down_revision: Union[str, Sequence[str], None] = 'bdb3db201c18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'price_refresh_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=32), server_default='running', nullable=False),
        sa.Column('scraping_mode', sa.String(length=16), nullable=False),
        sa.Column('source_filter', sa.String(length=32), nullable=True),
        sa.Column('limit_count', sa.Integer(), nullable=False),
        sa.Column('dry_run', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('mappings_checked', sa.Integer(), server_default='0', nullable=False),
        sa.Column('snapshots_created', sa.Integer(), server_default='0', nullable=False),
        sa.Column('observations_parsed', sa.Integer(), server_default='0', nullable=False),
        sa.Column('observations_inserted', sa.Integer(), server_default='0', nullable=False),
        sa.Column('observations_skipped_duplicate', sa.Integer(), server_default='0', nullable=False),
        sa.Column('mappings_failed', sa.Integer(), server_default='0', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'completed_with_warnings', 'failed')",
            name='ck_price_refresh_runs_status',
        ),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('price_refresh_runs')
