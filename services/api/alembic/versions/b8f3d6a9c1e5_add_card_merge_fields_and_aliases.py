"""add card merge fields and card_aliases table

Revision ID: b8f3d6a9c1e5
Revises: a3c8f1e4b7d2
Create Date: 2026-07-20 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8f3d6a9c1e5'
down_revision: Union[str, Sequence[str], None] = 'a3c8f1e4b7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'cards', sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true')
    )
    op.add_column(
        'cards', sa.Column('merged_into_card_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_cards_merged_into_card_id_cards',
        'cards', 'cards',
        ['merged_into_card_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        op.f('ix_cards_merged_into_card_id'), 'cards', ['merged_into_card_id'], unique=False
    )
    op.create_index(op.f('ix_cards_is_active'), 'cards', ['is_active'], unique=False)
    op.add_column('cards', sa.Column('merged_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('cards', sa.Column('merge_notes', sa.Text(), nullable=True))

    op.create_table(
        'card_aliases',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('card_id', sa.Integer(), nullable=False),
        sa.Column('alias_type', sa.String(length=32), nullable=False),
        sa.Column('alias_value', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['card_id'], ['cards.id'], ondelete='CASCADE'),
        sa.CheckConstraint(
            "alias_type IN ('old_card_code', 'old_name_en', 'old_name_jp', "
            "'source_title', 'merged_card_code')",
            name='ck_card_aliases_alias_type',
        ),
    )
    op.create_index(op.f('ix_card_aliases_card_id'), 'card_aliases', ['card_id'], unique=False)
    op.create_index(op.f('ix_card_aliases_alias_type'), 'card_aliases', ['alias_type'], unique=False)
    op.create_index(op.f('ix_card_aliases_alias_value'), 'card_aliases', ['alias_value'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('card_aliases')
    op.drop_index(op.f('ix_cards_is_active'), table_name='cards')
    op.drop_index(op.f('ix_cards_merged_into_card_id'), table_name='cards')
    op.drop_constraint('fk_cards_merged_into_card_id_cards', 'cards', type_='foreignkey')
    op.drop_column('cards', 'merge_notes')
    op.drop_column('cards', 'merged_at')
    op.drop_column('cards', 'merged_into_card_id')
    op.drop_column('cards', 'is_active')
