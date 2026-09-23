"""Enforce one current mapping per non-NULL canonical source listing.

The two historical SNKRDUNK duplicates were superseded in a separate,
audited staging data transaction before this schema-only revision.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "f2c7d91b6a40"
down_revision: str = "b8e04219d6c3"
branch_labels = None
depends_on = None

TABLE = "source_card_mappings"
INDEX = "uq_mapping_current_canonical_listing_identity"
PREDICATE = "superseded_at IS NULL AND canonical_source_listing_identity IS NOT NULL"


def upgrade():
    op.create_index(
        INDEX,
        TABLE,
        ["source_id", "canonical_source_listing_identity"],
        unique=True,
        postgresql_where=sa.text(PREDICATE),
    )


def downgrade():
    op.drop_index(INDEX, table_name=TABLE)
