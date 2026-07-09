"""add alert_events and alert_rules tables

Revision ID: 32bd832a93c7
Revises: 39d4db5bfe0a
Create Date: 2026-07-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '32bd832a93c7'
down_revision: Union[str, Sequence[str], None] = '39d4db5bfe0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'alert_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('rule_type', sa.String(length=32), nullable=False),
        sa.Column('source_name', sa.String(length=64), nullable=True),
        sa.Column('price_type', sa.String(length=32), nullable=True),
        sa.Column('threshold_pct', sa.Float(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.CheckConstraint(
            "rule_type IN ('price_change_pct', 'yuyutei_buy_change_pct', "
            "'stock_status_change', 'refresh_failed')",
            name='ck_alert_rules_rule_type',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table(
        'alert_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('event_type', sa.String(length=32), nullable=False),
        sa.Column('card_id', sa.Integer(), nullable=True),
        sa.Column('source_id', sa.Integer(), nullable=True),
        sa.Column('price_observation_id', sa.Integer(), nullable=True),
        sa.Column('refresh_run_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('dedupe_key', sa.String(length=255), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=32), server_default='pending', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.CheckConstraint(
            "event_type IN ('price_up', 'price_down', 'yuyutei_buy_up', 'stock_out', "
            "'refresh_failed')",
            name='ck_alert_events_event_type',
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'skipped_duplicate')",
            name='ck_alert_events_status',
        ),
        sa.ForeignKeyConstraint(['card_id'], ['cards.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(
            ['price_observation_id'], ['price_observations.id'], ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(
            ['refresh_run_id'], ['price_refresh_runs.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_alert_events_created_at', 'alert_events', ['created_at'])
    op.create_index('ix_alert_events_card_id', 'alert_events', ['card_id'])
    op.create_index('ix_alert_events_source_id', 'alert_events', ['source_id'])
    op.create_index('ix_alert_events_refresh_run_id', 'alert_events', ['refresh_run_id'])
    op.create_index('ix_alert_events_dedupe_key', 'alert_events', ['dedupe_key'])

    alert_rules_table = sa.table(
        'alert_rules',
        sa.column('name', sa.String),
        sa.column('rule_type', sa.String),
        sa.column('source_name', sa.String),
        sa.column('price_type', sa.String),
        sa.column('threshold_pct', sa.Float),
        sa.column('is_active', sa.Boolean),
    )
    op.bulk_insert(
        alert_rules_table,
        [
            {
                'name': 'Yuyu-Tei buy price up 10%',
                'rule_type': 'yuyutei_buy_change_pct',
                'source_name': 'yuyutei',
                'price_type': 'buy',
                'threshold_pct': 10.0,
                'is_active': True,
            },
            {
                'name': 'SNKRDUNK floor price down 10%',
                'rule_type': 'price_change_pct',
                'source_name': 'snkrdunk',
                'price_type': 'floor',
                'threshold_pct': -10.0,
                'is_active': True,
            },
            {
                'name': 'Refresh failed',
                'rule_type': 'refresh_failed',
                'source_name': None,
                'price_type': None,
                'threshold_pct': None,
                'is_active': True,
            },
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('alert_events')
    op.drop_table('alert_rules')
