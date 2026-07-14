"""add search_history

Revision ID: b3d5e9f2c7a1
Revises: a2f4c8e1b6d9
Create Date: 2026-07-14 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3d5e9f2c7a1'
down_revision: Union[str, Sequence[str], None] = 'a2f4c8e1b6d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'search_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('query', sa.String(length=255), nullable=False),
        sa.Column('result_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_search_history_created_at', 'search_history', ['created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('search_history')
