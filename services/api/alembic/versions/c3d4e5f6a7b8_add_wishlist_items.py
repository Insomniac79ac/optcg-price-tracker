"""add wishlist_items

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-20 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    No partial-unique-index enforcement of (user_id, card_id,
    preferred_condition, preferred_source) WHERE status != 'removed' - both
    preferred_condition and preferred_source are nullable, and standard SQL
    unique indexes treat NULL as distinct from any other NULL, so such an
    index would silently fail to catch the common case where both are unset.
    Duplicate prevention is enforced in the service layer instead (see
    app/services/wishlist.py), which handles the NULL case correctly.
    """
    op.create_table(
        'wishlist_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('card_id', sa.Integer(), nullable=False),
        sa.Column('priority', sa.String(length=16), server_default='medium', nullable=False),
        sa.Column('status', sa.String(length=16), server_default='watching', nullable=False),
        sa.Column('target_buy_price_jpy', sa.Integer(), nullable=True),
        sa.Column('max_buy_price_jpy', sa.Integer(), nullable=True),
        sa.Column('preferred_condition', sa.String(length=64), nullable=True),
        sa.Column('preferred_source', sa.String(length=64), nullable=True),
        sa.Column('desired_quantity', sa.Integer(), server_default='1', nullable=False),
        sa.Column('acquired_quantity', sa.Integer(), server_default='0', nullable=False),
        sa.Column('acquired_collection_item_id', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['card_id'], ['cards.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(
            ['acquired_collection_item_id'], ['collection_items.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'grail')",
            name='ck_wishlist_items_priority',
        ),
        sa.CheckConstraint(
            "status IN ('watching', 'target_hit', 'purchased', 'passed', 'removed')",
            name='ck_wishlist_items_status',
        ),
    )
    op.create_index('ix_wishlist_items_user_id', 'wishlist_items', ['user_id'])
    op.create_index('ix_wishlist_items_card_id', 'wishlist_items', ['card_id'])
    op.create_index('ix_wishlist_items_priority', 'wishlist_items', ['priority'])
    op.create_index('ix_wishlist_items_status', 'wishlist_items', ['status'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_wishlist_items_status', table_name='wishlist_items')
    op.drop_index('ix_wishlist_items_priority', table_name='wishlist_items')
    op.drop_index('ix_wishlist_items_card_id', table_name='wishlist_items')
    op.drop_index('ix_wishlist_items_user_id', table_name='wishlist_items')
    op.drop_table('wishlist_items')
