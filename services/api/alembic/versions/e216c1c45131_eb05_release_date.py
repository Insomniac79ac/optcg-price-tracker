"""Date the EB-05 JP release product from the official Bandai product page.

Frozen input: docs/evidence/eb05-release-date-2026-11-24.json. Same pattern as
c4e9a2b7816d: catalogue + official code is the match, only an existing undated
product is updated, nothing is inserted or deleted. EB-05 (release product 231)
already exists on staging, so this revision dates it; on a database without the
product it changes no rows. Applied through the apply-migration runbook (owner
approves the dry run and the apply).
"""

from datetime import date

from alembic import op
import sqlalchemy as sa

revision: str = "e216c1c45131"
down_revision: str = "7d2f9b4e1a63"
branch_labels = None
depends_on = None

# (source catalogue, official code, authoritative date, accepted classification)
ACCEPTED_RELEASE_DATES = (
    ("bandai_jp", "EB-05", "2026-10-31", "DATE_VERIFIED_SINGLE_SOURCE"),
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
