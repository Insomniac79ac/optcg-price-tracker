"""add collector_notes and collector_activity_events

Revision ID: a2f4c8e1b6d9
Revises: d4e5f6a7b8c9
Create Date: 2026-07-14 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2f4c8e1b6d9'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'collector_notes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('note_type', sa.String(length=32), server_default='general', nullable=False),
        sa.Column('card_id', sa.Integer(), nullable=True),
        sa.Column('collection_item_id', sa.Integer(), nullable=True),
        sa.Column('wishlist_item_id', sa.Integer(), nullable=True),
        sa.Column('grading_submission_id', sa.Integer(), nullable=True),
        sa.Column('market_signal_event_id', sa.Integer(), nullable=True),
        sa.Column('market_report_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('pinned', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "note_type IN ('general', 'collection', 'wishlist', 'grading', "
            "'market_signal', 'opportunity', 'card', 'backup', 'report')",
            name='ck_collector_notes_note_type',
        ),
        sa.ForeignKeyConstraint(['card_id'], ['cards.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['collection_item_id'], ['collection_items.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['wishlist_item_id'], ['wishlist_items.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(
            ['grading_submission_id'], ['grading_submissions.id'], ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(
            ['market_signal_event_id'], ['market_signal_events.id'], ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(
            ['market_report_id'], ['market_intelligence_reports.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_collector_notes_note_type', 'collector_notes', ['note_type'])
    op.create_index('ix_collector_notes_card_id', 'collector_notes', ['card_id'])
    op.create_index('ix_collector_notes_collection_item_id', 'collector_notes', ['collection_item_id'])
    op.create_index('ix_collector_notes_wishlist_item_id', 'collector_notes', ['wishlist_item_id'])
    op.create_index(
        'ix_collector_notes_grading_submission_id', 'collector_notes', ['grading_submission_id']
    )
    op.create_index(
        'ix_collector_notes_market_signal_event_id', 'collector_notes', ['market_signal_event_id']
    )
    op.create_index('ix_collector_notes_market_report_id', 'collector_notes', ['market_report_id'])
    op.create_index('ix_collector_notes_pinned', 'collector_notes', ['pinned'])

    op.create_table(
        'collector_activity_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('event_source', sa.String(length=32), nullable=False),
        sa.Column('card_id', sa.Integer(), nullable=True),
        sa.Column('collection_item_id', sa.Integer(), nullable=True),
        sa.Column('wishlist_item_id', sa.Integer(), nullable=True),
        sa.Column('grading_submission_id', sa.Integer(), nullable=True),
        sa.Column('market_signal_event_id', sa.Integer(), nullable=True),
        sa.Column('market_report_id', sa.Integer(), nullable=True),
        sa.Column('market_workflow_run_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('payload_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['card_id'], ['cards.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['collection_item_id'], ['collection_items.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['wishlist_item_id'], ['wishlist_items.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(
            ['grading_submission_id'], ['grading_submissions.id'], ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(
            ['market_signal_event_id'], ['market_signal_events.id'], ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(
            ['market_report_id'], ['market_intelligence_reports.id'], ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(
            ['market_workflow_run_id'], ['market_workflow_runs.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_collector_activity_events_created_at', 'collector_activity_events', ['created_at'])
    op.create_index('ix_collector_activity_events_event_type', 'collector_activity_events', ['event_type'])
    op.create_index(
        'ix_collector_activity_events_event_source', 'collector_activity_events', ['event_source']
    )
    op.create_index('ix_collector_activity_events_card_id', 'collector_activity_events', ['card_id'])
    op.create_index(
        'ix_collector_activity_events_collection_item_id',
        'collector_activity_events',
        ['collection_item_id'],
    )
    op.create_index(
        'ix_collector_activity_events_wishlist_item_id',
        'collector_activity_events',
        ['wishlist_item_id'],
    )
    op.create_index(
        'ix_collector_activity_events_grading_submission_id',
        'collector_activity_events',
        ['grading_submission_id'],
    )
    op.create_index(
        'ix_collector_activity_events_market_signal_event_id',
        'collector_activity_events',
        ['market_signal_event_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('collector_activity_events')
    op.drop_table('collector_notes')
