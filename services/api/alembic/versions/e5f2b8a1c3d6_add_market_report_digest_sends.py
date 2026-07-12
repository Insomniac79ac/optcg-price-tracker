"""add market_report_digest_sends table

Revision ID: e5f2b8a1c3d6
Revises: d3a7c5f1b8e4
Create Date: 2026-07-12 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f2b8a1c3d6'
down_revision: Union[str, Sequence[str], None] = 'd3a7c5f1b8e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'market_report_digest_sends',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('report_id', sa.Integer(), nullable=False),
        sa.Column('destination', sa.String(length=32), server_default='telegram', nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('message_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'skipped', 'failed')",
            name='ck_market_report_digest_sends_status',
        ),
        sa.ForeignKeyConstraint(['report_id'], ['market_intelligence_reports.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'report_id', 'destination', name='uq_market_report_digest_sends_report_destination'
        ),
    )
    op.create_index(
        'ix_market_report_digest_sends_report_id', 'market_report_digest_sends', ['report_id']
    )
    op.create_index(
        'ix_market_report_digest_sends_status', 'market_report_digest_sends', ['status']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_market_report_digest_sends_status', table_name='market_report_digest_sends')
    op.drop_index('ix_market_report_digest_sends_report_id', table_name='market_report_digest_sends')
    op.drop_table('market_report_digest_sends')
