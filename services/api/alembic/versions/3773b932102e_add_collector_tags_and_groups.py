"""add collector tags and groups

Revision ID: 3773b932102e
Revises: f1a4c9d7b2e8
Create Date: 2026-07-13 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3773b932102e'
down_revision: Union[str, Sequence[str], None] = 'f1a4c9d7b2e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'collector_tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('color', sa.String(length=16), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('slug'),
    )
    op.create_index('ix_collector_tags_slug', 'collector_tags', ['slug'])

    op.create_table(
        'collector_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
        sa.UniqueConstraint('slug'),
    )
    op.create_index('ix_collector_groups_slug', 'collector_groups', ['slug'])

    op.create_table(
        'card_tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('card_id', sa.Integer(), nullable=False),
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['card_id'], ['cards.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['collector_tags.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('card_id', 'tag_id', name='uq_card_tags_card_tag'),
    )
    op.create_index('ix_card_tags_card_id', 'card_tags', ['card_id'])
    op.create_index('ix_card_tags_tag_id', 'card_tags', ['tag_id'])

    op.create_table(
        'collection_item_tags',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('collection_item_id', sa.Integer(), nullable=False),
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['collection_item_id'], ['collection_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['collector_tags.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('collection_item_id', 'tag_id', name='uq_collection_item_tags_item_tag'),
    )
    op.create_index('ix_collection_item_tags_collection_item_id', 'collection_item_tags', ['collection_item_id'])
    op.create_index('ix_collection_item_tags_tag_id', 'collection_item_tags', ['tag_id'])

    op.create_table(
        'collection_item_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('collection_item_id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['collection_item_id'], ['collection_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['group_id'], ['collector_groups.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('collection_item_id', 'group_id', name='uq_collection_item_groups_item_group'),
    )
    op.create_index('ix_collection_item_groups_collection_item_id', 'collection_item_groups', ['collection_item_id'])
    op.create_index('ix_collection_item_groups_group_id', 'collection_item_groups', ['group_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_collection_item_groups_group_id', table_name='collection_item_groups')
    op.drop_index('ix_collection_item_groups_collection_item_id', table_name='collection_item_groups')
    op.drop_table('collection_item_groups')

    op.drop_index('ix_collection_item_tags_tag_id', table_name='collection_item_tags')
    op.drop_index('ix_collection_item_tags_collection_item_id', table_name='collection_item_tags')
    op.drop_table('collection_item_tags')

    op.drop_index('ix_card_tags_tag_id', table_name='card_tags')
    op.drop_index('ix_card_tags_card_id', table_name='card_tags')
    op.drop_table('card_tags')

    op.drop_index('ix_collector_groups_slug', table_name='collector_groups')
    op.drop_table('collector_groups')

    op.drop_index('ix_collector_tags_slug', table_name='collector_tags')
    op.drop_table('collector_tags')
