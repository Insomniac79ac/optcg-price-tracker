"""add print lineage to source_card_mappings and price_observations

Revision ID: b858237e3706
Revises: a4d6b1c8f3e2
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b858237e3706'
down_revision: Union[str, Sequence[str], None] = 'a4d6b1c8f3e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'source_card_mappings',
        sa.Column('card_print_id', sa.Integer(), nullable=True),
    )
    op.create_index(
        'ix_source_card_mappings_card_print_id',
        'source_card_mappings',
        ['card_print_id'],
    )
    op.create_foreign_key(
        'fk_source_card_mappings_card_print_id_card_prints',
        'source_card_mappings',
        'card_prints',
        ['card_print_id'],
        ['id'],
        ondelete='RESTRICT',
    )
    op.create_unique_constraint(
        'uq_source_card_mappings_lineage_identity',
        'source_card_mappings',
        ['id', 'card_print_id', 'card_id', 'source_id'],
    )

    op.add_column(
        'price_observations',
        sa.Column('source_card_mapping_id', sa.Integer(), nullable=True),
    )
    op.add_column(
        'price_observations',
        sa.Column('card_print_id', sa.Integer(), nullable=True),
    )
    op.create_index(
        'ix_price_observations_source_card_mapping_id',
        'price_observations',
        ['source_card_mapping_id'],
    )
    op.create_index(
        'ix_price_observations_card_print_id',
        'price_observations',
        ['card_print_id'],
    )
    op.create_foreign_key(
        'fk_price_observations_mapping_print_card_source',
        'price_observations',
        'source_card_mappings',
        ['source_card_mapping_id', 'card_print_id', 'card_id', 'source_id'],
        ['id', 'card_print_id', 'card_id', 'source_id'],
        ondelete='RESTRICT',
    )
    op.create_check_constraint(
        'ck_price_observations_lineage_paired',
        'price_observations',
        "(source_card_mapping_id IS NULL AND card_print_id IS NULL) OR "
        "(source_card_mapping_id IS NOT NULL AND card_print_id IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_price_observations_lineage_paired', 'price_observations', type_='check')
    op.drop_constraint(
        'fk_price_observations_mapping_print_card_source', 'price_observations', type_='foreignkey'
    )
    op.drop_index('ix_price_observations_card_print_id', table_name='price_observations')
    op.drop_index('ix_price_observations_source_card_mapping_id', table_name='price_observations')
    op.drop_column('price_observations', 'card_print_id')
    op.drop_column('price_observations', 'source_card_mapping_id')

    op.drop_constraint('uq_source_card_mappings_lineage_identity', 'source_card_mappings', type_='unique')
    op.drop_constraint(
        'fk_source_card_mappings_card_print_id_card_prints', 'source_card_mappings', type_='foreignkey'
    )
    op.drop_index('ix_source_card_mappings_card_print_id', table_name='source_card_mappings')
    op.drop_column('source_card_mappings', 'card_print_id')
