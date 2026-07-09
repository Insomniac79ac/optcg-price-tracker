"""replace source_card_mappings unique constraint with source_id+source_url

Revision ID: ff75028d733f
Revises: 3f491bafb24c
Create Date: 2026-07-08 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff75028d733f'
down_revision: Union[str, Sequence[str], None] = '3f491bafb24c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_constraints = {
        c["name"] for c in inspector.get_unique_constraints("source_card_mappings")
    }
    if "uq_source_card_mappings_card_source" in existing_constraints:
        op.drop_constraint(
            "uq_source_card_mappings_card_source", "source_card_mappings", type_="unique"
        )

    # The dropped unique constraint also served as the (card_id, source_id)
    # index; replace it with an explicit non-unique composite index so lookups
    # by card_id + source_id stay indexed now that the pair is no longer unique.
    op.create_index(
        "ix_source_card_mappings_card_id_source_id",
        "source_card_mappings",
        ["card_id", "source_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_source_card_mappings_source_url",
        "source_card_mappings",
        ["source_id", "source_url"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "uq_source_card_mappings_source_url", "source_card_mappings", type_="unique"
    )
    op.drop_index(
        "ix_source_card_mappings_card_id_source_id", table_name="source_card_mappings"
    )
    op.create_unique_constraint(
        "uq_source_card_mappings_card_source",
        "source_card_mappings",
        ["card_id", "source_id"],
    )
