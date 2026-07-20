"""add source mapping confidence fields

Revision ID: a3c8f1e4b7d2
Revises: 67b4f42210ee
Create Date: 2026-07-20 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c8f1e4b7d2'
down_revision: Union[str, Sequence[str], None] = '67b4f42210ee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'source_card_mappings', sa.Column('match_confidence_label', sa.String(length=16), nullable=True)
    )
    op.add_column(
        'source_card_mappings', sa.Column('match_explanation_json', sa.JSON(), nullable=True)
    )
    op.add_column(
        'source_card_mappings',
        sa.Column('last_match_checked_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('source_card_mappings', 'last_match_checked_at')
    op.drop_column('source_card_mappings', 'match_explanation_json')
    op.drop_column('source_card_mappings', 'match_confidence_label')
