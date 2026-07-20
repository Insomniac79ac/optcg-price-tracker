"""add card catalog metadata fields

Revision ID: c732eaf8e4bb
Revises: c699d532e4cc
Create Date: 2026-07-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c732eaf8e4bb'
down_revision: Union[str, Sequence[str], None] = 'c699d532e4cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('cards', sa.Column('release_date', sa.Date(), nullable=True))
    op.add_column('cards', sa.Column('artist', sa.String(length=255), nullable=True))
    op.add_column('cards', sa.Column('character', sa.String(length=255), nullable=True))
    op.add_column('cards', sa.Column('color', sa.String(length=64), nullable=True))
    op.add_column('cards', sa.Column('card_type', sa.String(length=64), nullable=True))
    op.add_column('cards', sa.Column('cost', sa.Integer(), nullable=True))
    op.add_column('cards', sa.Column('power', sa.Integer(), nullable=True))
    op.add_column('cards', sa.Column('counter', sa.Integer(), nullable=True))
    op.add_column('cards', sa.Column('attribute', sa.String(length=64), nullable=True))
    op.add_column('cards', sa.Column('effect_text', sa.Text(), nullable=True))
    op.add_column('cards', sa.Column('trigger_text', sa.Text(), nullable=True))
    op.add_column('cards', sa.Column('notes', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('cards', 'notes')
    op.drop_column('cards', 'trigger_text')
    op.drop_column('cards', 'effect_text')
    op.drop_column('cards', 'attribute')
    op.drop_column('cards', 'counter')
    op.drop_column('cards', 'power')
    op.drop_column('cards', 'cost')
    op.drop_column('cards', 'card_type')
    op.drop_column('cards', 'color')
    op.drop_column('cards', 'character')
    op.drop_column('cards', 'artist')
    op.drop_column('cards', 'release_date')
