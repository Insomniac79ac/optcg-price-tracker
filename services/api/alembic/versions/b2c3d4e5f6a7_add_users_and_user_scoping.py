"""add users table and user_id scoping to collection_items/collector_tags/collector_groups

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-16 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    This adds a hard (NOT NULL) `user_id` FK to collection_items,
    collector_tags, and collector_groups. There is no backfill path for
    existing ownerless rows - any environment with real data in these three
    tables must truncate them (collection_item_tags, collection_item_groups,
    grading_submissions, collection_items, collector_tags, collector_groups,
    in that FK-safe order) before running this migration. This is acceptable
    for this project's current dev/test data, which is being intentionally
    wiped as part of this change.
    """
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('google_sub', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('avatar_url', sa.String(length=1024), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_users_google_sub', 'users', ['google_sub'], unique=True)
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    op.add_column('collection_items', sa.Column('user_id', sa.Integer(), nullable=False))
    op.create_index('ix_collection_items_user_id', 'collection_items', ['user_id'])
    op.create_foreign_key(
        'fk_collection_items_user_id_users',
        'collection_items', 'users', ['user_id'], ['id'], ondelete='CASCADE',
    )

    op.add_column('collector_tags', sa.Column('user_id', sa.Integer(), nullable=False))
    op.create_index('ix_collector_tags_user_id', 'collector_tags', ['user_id'])
    op.create_foreign_key(
        'fk_collector_tags_user_id_users',
        'collector_tags', 'users', ['user_id'], ['id'], ondelete='CASCADE',
    )
    op.drop_constraint('collector_tags_name_key', 'collector_tags', type_='unique')
    op.drop_constraint('collector_tags_slug_key', 'collector_tags', type_='unique')
    op.create_unique_constraint(
        'uq_collector_tags_user_name', 'collector_tags', ['user_id', 'name']
    )
    op.create_unique_constraint(
        'uq_collector_tags_user_slug', 'collector_tags', ['user_id', 'slug']
    )

    op.add_column('collector_groups', sa.Column('user_id', sa.Integer(), nullable=False))
    op.create_index('ix_collector_groups_user_id', 'collector_groups', ['user_id'])
    op.create_foreign_key(
        'fk_collector_groups_user_id_users',
        'collector_groups', 'users', ['user_id'], ['id'], ondelete='CASCADE',
    )
    op.drop_constraint('collector_groups_name_key', 'collector_groups', type_='unique')
    op.drop_constraint('collector_groups_slug_key', 'collector_groups', type_='unique')
    op.create_unique_constraint(
        'uq_collector_groups_user_name', 'collector_groups', ['user_id', 'name']
    )
    op.create_unique_constraint(
        'uq_collector_groups_user_slug', 'collector_groups', ['user_id', 'slug']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_collector_groups_user_slug', 'collector_groups', type_='unique')
    op.drop_constraint('uq_collector_groups_user_name', 'collector_groups', type_='unique')
    op.create_unique_constraint('collector_groups_slug_key', 'collector_groups', ['slug'])
    op.create_unique_constraint('collector_groups_name_key', 'collector_groups', ['name'])
    op.drop_constraint('fk_collector_groups_user_id_users', 'collector_groups', type_='foreignkey')
    op.drop_index('ix_collector_groups_user_id', table_name='collector_groups')
    op.drop_column('collector_groups', 'user_id')

    op.drop_constraint('uq_collector_tags_user_slug', 'collector_tags', type_='unique')
    op.drop_constraint('uq_collector_tags_user_name', 'collector_tags', type_='unique')
    op.create_unique_constraint('collector_tags_slug_key', 'collector_tags', ['slug'])
    op.create_unique_constraint('collector_tags_name_key', 'collector_tags', ['name'])
    op.drop_constraint('fk_collector_tags_user_id_users', 'collector_tags', type_='foreignkey')
    op.drop_index('ix_collector_tags_user_id', table_name='collector_tags')
    op.drop_column('collector_tags', 'user_id')

    op.drop_constraint('fk_collection_items_user_id_users', 'collection_items', type_='foreignkey')
    op.drop_index('ix_collection_items_user_id', table_name='collection_items')
    op.drop_column('collection_items', 'user_id')

    op.drop_index('ix_users_email', table_name='users')
    op.drop_index('ix_users_google_sub', table_name='users')
    op.drop_table('users')
