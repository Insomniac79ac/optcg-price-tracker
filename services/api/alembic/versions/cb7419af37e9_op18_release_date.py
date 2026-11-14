"""Date the OP-18 JP release product from the official Bandai product page.

Frozen input: docs/evidence/op18-release-date-2026-11-12.json. Same pattern as
c4e9a2b7816d: catalogue + official code is the match, only an existing undated
product is updated, nothing is inserted or deleted. Before the OP-18 import has
created the product this revision changes no rows, so it is applied through the
apply-migration runbook only after the import.
"""

from datetime import date

from alembic import op
import sqlalchemy as sa

revision: str = "cb7419af37e9"
down_revision: str = "001d92ba8eb9"
branch_labels = None
depends_on = None

# (source catalogue, official code, authoritative date, accepted classification)
ACCEPTED_RELEASE_DATES = (
    ("bandai_jp", "OP-18", "2026-11-21", "DATE_VERIFIED_SINGLE_SOURCE"),
)


def _products():
    return sa.table(
        "release_products",
        sa.column("source_catalogue", sa.String(16)),
        sa.column("official_code", sa.String(32)),
        sa.column("released_on", sa.Date()),
        sa.column("release_date_source", sa.String(32)),
    )


def upgrade():
    # A Core table has no application onupdate hooks: updated_at is preserved.
    products = _products()
    for catalogue, code, released_on, source in ACCEPTED_RELEASE_DATES:
        op.execute(
            products.update()
            .where(
                products.c.source_catalogue == catalogue,
                products.c.official_code == code,
                products.c.released_on.is_(None),
            )
            .values(released_on=date.fromisoformat(released_on), release_date_source=source)
        )


def downgrade():
    products = _products()
    for catalogue, code, released_on, source in ACCEPTED_RELEASE_DATES:
        op.execute(
            products.update()
            .where(
                products.c.source_catalogue == catalogue,
                products.c.official_code == code,
                products.c.released_on == date.fromisoformat(released_on),
                products.c.release_date_source == source,
            )
            .values(released_on=None, release_date_source=None)
        )
