"""add card image provenance fields

Revision ID: f35ff2f33090
Revises: e7a1c4d9b2f6
Create Date: 2026-07-27 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f35ff2f33090'
down_revision: Union[str, Sequence[str], None] = 'e7a1c4d9b2f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cards', sa.Column('image_source', sa.String(length=32), nullable=True))
    op.add_column('cards', sa.Column('image_source_url', sa.String(length=1024), nullable=True))
    op.add_column(
        'cards', sa.Column('image_last_verified_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column('cards', sa.Column('image_status', sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column('cards', 'image_status')
    op.drop_column('cards', 'image_last_verified_at')
    op.drop_column('cards', 'image_source_url')
    op.drop_column('cards', 'image_source')
