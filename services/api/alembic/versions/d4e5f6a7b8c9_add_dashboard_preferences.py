"""add dashboard_preferences

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-27 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'dashboard_preferences',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('preference_key', sa.String(length=64), nullable=False),
        sa.Column('preference_value_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('preference_key'),
    )
    op.create_index(
        'ix_dashboard_preferences_preference_key', 'dashboard_preferences', ['preference_key'], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_dashboard_preferences_preference_key', table_name='dashboard_preferences')
    op.drop_table('dashboard_preferences')
