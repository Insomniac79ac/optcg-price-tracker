"""add app_log_events table

Revision ID: a1c9e4d7f2b6
Revises: b3d5e9f2c7a1
Create Date: 2026-07-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c9e4d7f2b6'
down_revision: Union[str, Sequence[str], None] = 'b3d5e9f2c7a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'app_log_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('level', sa.String(length=16), nullable=False),
        sa.Column('service', sa.String(length=32), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('context_json', sa.JSON(), nullable=True),
        sa.Column('traceback', sa.Text(), nullable=True),
        sa.Column('related_run_id', sa.Integer(), nullable=True),
        sa.Column('related_entity_type', sa.String(length=64), nullable=True),
        sa.Column('related_entity_id', sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "level IN ('debug', 'info', 'warning', 'error', 'critical')",
            name='ck_app_log_events_level',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_app_log_events_created_at', 'app_log_events', ['created_at'])
    op.create_index('ix_app_log_events_level', 'app_log_events', ['level'])
    op.create_index('ix_app_log_events_service', 'app_log_events', ['service'])
    op.create_index('ix_app_log_events_event_type', 'app_log_events', ['event_type'])
    op.create_index(
        'ix_app_log_events_related_entity',
        'app_log_events',
        ['related_entity_type', 'related_entity_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_app_log_events_related_entity', table_name='app_log_events')
    op.drop_index('ix_app_log_events_event_type', table_name='app_log_events')
    op.drop_index('ix_app_log_events_service', table_name='app_log_events')
    op.drop_index('ix_app_log_events_level', table_name='app_log_events')
    op.drop_index('ix_app_log_events_created_at', table_name='app_log_events')
    op.drop_table('app_log_events')
