"""add saved_views table

Revision ID: e7a1c4d9b2f6
Revises: c1a2d3e4f5a6
Create Date: 2026-07-22 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a1c4d9b2f6'
down_revision: Union[str, Sequence[str], None] = 'c1a2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'saved_views',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('route_path', sa.String(length=255), nullable=False),
        sa.Column('view_type', sa.String(length=64), nullable=False),
        sa.Column('scope', sa.String(length=16), server_default='collector', nullable=False),
        sa.Column('filters_json', sa.JSON(), nullable=True),
        sa.Column('sort_json', sa.JSON(), nullable=True),
        sa.Column('columns_json', sa.JSON(), nullable=True),
        sa.Column('density', sa.String(length=16), server_default='compact', nullable=False),
        sa.Column('is_default', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('pinned', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('usage_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('route_path', 'view_type', 'name', name='uq_saved_views_route_type_name'),
        sa.CheckConstraint(
            "scope IN ('collector', 'admin', 'analytics', 'market')",
            name='ck_saved_views_scope',
        ),
        sa.CheckConstraint(
            "density IN ('compact', 'comfortable')",
            name='ck_saved_views_density',
        ),
    )
    op.create_index('ix_saved_views_route_path', 'saved_views', ['route_path'])
    op.create_index('ix_saved_views_view_type', 'saved_views', ['view_type'])
    op.create_index('ix_saved_views_scope', 'saved_views', ['scope'])
    op.create_index('ix_saved_views_is_default', 'saved_views', ['is_default'])
    op.create_index('ix_saved_views_pinned', 'saved_views', ['pinned'])
    op.create_index('ix_saved_views_last_used_at', 'saved_views', ['last_used_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_saved_views_last_used_at', table_name='saved_views')
    op.drop_index('ix_saved_views_pinned', table_name='saved_views')
    op.drop_index('ix_saved_views_is_default', table_name='saved_views')
    op.drop_index('ix_saved_views_scope', table_name='saved_views')
    op.drop_index('ix_saved_views_view_type', table_name='saved_views')
    op.drop_index('ix_saved_views_route_path', table_name='saved_views')
    op.drop_table('saved_views')
