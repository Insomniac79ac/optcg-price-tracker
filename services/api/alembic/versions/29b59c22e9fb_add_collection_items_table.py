"""add collection_items table

Revision ID: 29b59c22e9fb
Revises: 6f620e0225e2
Create Date: 2026-07-10 15:25:16.021456

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '29b59c22e9fb'
down_revision: Union[str, Sequence[str], None] = '6f620e0225e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'collection_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('card_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), server_default='1', nullable=False),
        sa.Column('condition_label', sa.String(length=64), nullable=True),
        sa.Column('purchase_price_jpy', sa.Integer(), nullable=True),
        sa.Column('purchase_date', sa.Date(), nullable=True),
        sa.Column('purchase_source', sa.String(length=255), nullable=True),
        sa.Column('target_sell_price_jpy', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=32), server_default='hold', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['card_id'], ['cards.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "status IN ('hold', 'watch', 'sell', 'sold', 'grading')",
            name='ck_collection_items_status',
        ),
    )
    op.create_index('ix_collection_items_card_id', 'collection_items', ['card_id'])
    op.create_index('ix_collection_items_status', 'collection_items', ['status'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_collection_items_status', table_name='collection_items')
    op.drop_index('ix_collection_items_card_id', table_name='collection_items')
    op.drop_table('collection_items')
