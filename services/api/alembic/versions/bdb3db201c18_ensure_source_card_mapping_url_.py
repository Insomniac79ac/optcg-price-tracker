"""ensure source_card_mappings unique(source_id, source_url), drop unique(card_id, source_id)

Idempotent by design: earlier attempts at this change may have partially
applied (or never applied) depending on which environment ran them, so every
statement here explicitly checks catalog state first rather than assuming a
particular starting point.

Revision ID: bdb3db201c18
Revises: ff75028d733f
Create Date: 2026-07-09 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'bdb3db201c18'
down_revision: Union[str, Sequence[str], None] = 'ff75028d733f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "ALTER TABLE source_card_mappings "
        "DROP CONSTRAINT IF EXISTS uq_source_card_mappings_card_source"
    )

    # (card_id, source_id) lookups still need an index now that the pair is
    # no longer required to be unique.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_source_card_mappings_card_id_source_id "
        "ON source_card_mappings (card_id, source_id)"
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_source_card_mappings_source_url'
            ) THEN
                ALTER TABLE source_card_mappings
                ADD CONSTRAINT uq_source_card_mappings_source_url
                UNIQUE (source_id, source_url);
            END IF;
        END$$;
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "ALTER TABLE source_card_mappings "
        "DROP CONSTRAINT IF EXISTS uq_source_card_mappings_source_url"
    )
    op.execute(
        "DROP INDEX IF EXISTS ix_source_card_mappings_card_id_source_id"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_source_card_mappings_card_source'
            ) THEN
                ALTER TABLE source_card_mappings
                ADD CONSTRAINT uq_source_card_mappings_card_source
                UNIQUE (card_id, source_id);
            END IF;
        END$$;
        """
    )
