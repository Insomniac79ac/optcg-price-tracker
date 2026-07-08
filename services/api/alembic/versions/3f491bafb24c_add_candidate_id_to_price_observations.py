"""add candidate_id to price_observations

Revision ID: 3f491bafb24c
Revises: 2acfab78d531
Create Date: 2026-07-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f491bafb24c'
down_revision: Union[str, Sequence[str], None] = '2acfab78d531'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('price_observations', sa.Column('candidate_id', sa.Integer(), nullable=True))
    op.create_index(
        op.f('ix_price_observations_candidate_id'), 'price_observations', ['candidate_id'], unique=False
    )
    op.create_foreign_key(
        'price_observations_candidate_id_fkey',
        'price_observations', 'snkrdunk_candidates',
        ['candidate_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('price_observations_candidate_id_fkey', 'price_observations', type_='foreignkey')
    op.drop_index(op.f('ix_price_observations_candidate_id'), table_name='price_observations')
    op.drop_column('price_observations', 'candidate_id')
