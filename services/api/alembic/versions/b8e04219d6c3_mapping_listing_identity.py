"""Canonical listing identity and historical mapping supersession foundation.

No unique-current index and no supersession/data repair in this revision.
"""
from alembic import op
import sqlalchemy as sa
from opcg_source_identity import canonical_source_listing_identity

revision = "b8e04219d6c3"
down_revision = "a7f936027b8f"
branch_labels = None
depends_on = None
TABLE = "source_card_mappings"


def upgrade():
    op.add_column(TABLE, sa.Column("canonical_source_listing_identity", sa.String(1024), nullable=True))
    op.add_column(TABLE, sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("superseded_by_mapping_id", sa.Integer(), nullable=True))
    op.add_column(TABLE, sa.Column("supersession_reason", sa.Text(), nullable=True))
    op.create_foreign_key("fk_mapping_superseded_by", TABLE, TABLE, ["superseded_by_mapping_id"], ["id"], ondelete="RESTRICT")
    op.create_check_constraint("ck_mapping_no_self_supersession", TABLE, "superseded_by_mapping_id IS NULL OR superseded_by_mapping_id <> id")
    op.create_check_constraint(
        "ck_mapping_supersession_lifecycle", TABLE,
        "(superseded_at IS NULL AND superseded_by_mapping_id IS NULL AND supersession_reason IS NULL) OR "
        "(superseded_at IS NOT NULL AND superseded_by_mapping_id IS NOT NULL AND "
        "supersession_reason IS NOT NULL AND length(trim(supersession_reason, ' \t\n\r')) > 0 AND is_active = false)",
    )
    op.create_index("ix_mapping_current_listing", TABLE, ["source_id", "canonical_source_listing_identity", "superseded_at"], unique=False)
    connection = op.get_bind()
    rows = connection.execute(sa.text(
        "SELECT m.id, m.source_url, s.name FROM source_card_mappings m JOIN sources s ON s.id=m.source_id"
    )).mappings().all()
    for row in rows:
        identity = canonical_source_listing_identity(row["name"], row["source_url"])
        if identity is not None:
            # Text SQL deliberately bypasses ORM updated_at/onupdate hooks.
            connection.execute(sa.text(
                "UPDATE source_card_mappings SET canonical_source_listing_identity=:identity WHERE id=:id"
            ), {"identity": identity, "id": row["id"]})


def downgrade():
    op.drop_index("ix_mapping_current_listing", table_name=TABLE)
    op.drop_constraint("ck_mapping_supersession_lifecycle", TABLE, type_="check")
    op.drop_constraint("ck_mapping_no_self_supersession", TABLE, type_="check")
    op.drop_constraint("fk_mapping_superseded_by", TABLE, type_="foreignkey")
    for name in ("supersession_reason", "superseded_by_mapping_id", "superseded_at", "canonical_source_listing_identity"):
        op.drop_column(TABLE, name)
