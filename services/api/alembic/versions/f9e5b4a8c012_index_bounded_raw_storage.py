"""Index bounded RAW storage admission and dictionary scope; no evidence edits.

Revision ID: f9e5b4a8c012
Revises: e8c2d4f6a901
"""

from alembic import op
import sqlalchemy as sa

revision: str = "f9e5b4a8c012"
down_revision: str | None = "e8c2d4f6a901"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_raw_dictionary_created", "raw_snapshot_dictionaries", ["created_at"]
    )
    # Hash keeps long URLs below PostgreSQL's btree entry limit. The writer also
    # compares the complete URL, so a hash collision can never cross identities.
    # No raw body predicate: building this index never reads retained TOAST bodies.
    op.create_index(
        "ix_raw_snapshot_dictionary_scope",
        "raw_snapshots",
        ["source_id", "parser_version", sa.text("md5(source_url)"), "id"],
        postgresql_where=sa.text("http_status = 200"),
    )


def downgrade():
    # Compatible rollback retains e8 representation dependencies and all bodies.
    op.drop_index("ix_raw_snapshot_dictionary_scope", table_name="raw_snapshots")
    op.drop_index("ix_raw_dictionary_created", table_name="raw_snapshot_dictionaries")
