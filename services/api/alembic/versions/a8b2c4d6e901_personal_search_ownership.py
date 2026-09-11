"""Add owners to search history and saved views, preserving legacy NULL owners.

Revision ID: a8b2c4d6e901
Revises: c9d2f47a6b31
"""
from alembic import op
import sqlalchemy as sa

revision = "a8b2c4d6e901"
down_revision = "c9d2f47a6b31"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("search_history", "saved_views"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(f"fk_{table}_user_id", "users", ["user_id"], ["id"], ondelete="SET NULL")
            batch.create_index(f"ix_{table}_user_id", ["user_id"])
    with op.batch_alter_table("saved_views") as batch:
        batch.drop_constraint("uq_saved_views_route_type_name", type_="unique")
        batch.create_unique_constraint("uq_saved_views_owner_route_type_name", ["user_id", "route_path", "view_type", "name"])


def downgrade():
    # Restoring global uniqueness can conflict with legitimate per-user names.
    # Fail before any DDL, preserving every row rather than renaming/deleting it.
    conflict = op.get_bind().execute(sa.text(
        "SELECT 1 FROM saved_views GROUP BY route_path, view_type, name HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if conflict:
        raise RuntimeError("Cannot downgrade: saved-view names overlap across owners; no data changed")
    with op.batch_alter_table("saved_views") as batch:
        batch.drop_constraint("uq_saved_views_owner_route_type_name", type_="unique")
        batch.create_unique_constraint("uq_saved_views_route_type_name", ["route_path", "view_type", "name"])
    for table in ("search_history", "saved_views"):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_user_id")
            batch.drop_constraint(f"fk_{table}_user_id", type_="foreignkey")
            batch.drop_column("user_id")
