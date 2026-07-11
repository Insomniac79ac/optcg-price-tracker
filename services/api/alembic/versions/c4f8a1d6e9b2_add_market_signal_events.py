"""add market_signal_events table

Revision ID: c4f8a1d6e9b2
Revises: b7d3e1f9a2c4
Create Date: 2026-07-12 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4f8a1d6e9b2'
down_revision: Union[str, Sequence[str], None] = 'b7d3e1f9a2c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'market_signal_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('signal_type', sa.String(length=64), nullable=False),
        sa.Column('dedupe_key', sa.String(length=255), nullable=False),
        sa.Column('card_id', sa.Integer(), nullable=True),
        sa.Column('collection_item_id', sa.Integer(), nullable=True),
        sa.Column('severity', sa.String(length=16), server_default='info', nullable=False),
        sa.Column('suggested_action', sa.String(length=32), nullable=True),
        sa.Column('status', sa.String(length=16), server_default='open', nullable=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('seen_count', sa.Integer(), server_default='1', nullable=False),
        sa.Column('last_payload_json', sa.JSON(), nullable=True),
        sa.Column('dismissed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "status IN ('open', 'watching', 'dismissed', 'resolved')",
            name='ck_market_signal_events_status',
        ),
        sa.ForeignKeyConstraint(['card_id'], ['cards.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(
            ['collection_item_id'], ['collection_items.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dedupe_key'),
    )
    op.create_index(
        'ix_market_signal_events_signal_type', 'market_signal_events', ['signal_type']
    )
    op.create_index('ix_market_signal_events_status', 'market_signal_events', ['status'])
    op.create_index('ix_market_signal_events_card_id', 'market_signal_events', ['card_id'])
    op.create_index(
        'ix_market_signal_events_last_seen_at', 'market_signal_events', ['last_seen_at']
    )
    op.create_index(
        'ix_market_signal_events_suggested_action',
        'market_signal_events',
        ['suggested_action'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_market_signal_events_suggested_action', table_name='market_signal_events')
    op.drop_index('ix_market_signal_events_last_seen_at', table_name='market_signal_events')
    op.drop_index('ix_market_signal_events_card_id', table_name='market_signal_events')
    op.drop_index('ix_market_signal_events_status', table_name='market_signal_events')
    op.drop_index('ix_market_signal_events_signal_type', table_name='market_signal_events')
    op.drop_table('market_signal_events')
