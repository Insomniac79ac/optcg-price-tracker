"""Persist verified Bandai JP release chronology without changing identity.

Frozen input: docs/evidence/public-ux-1a-release-dates-2026-09-24.json.
Catalogue + official code is the authoritative match; database IDs and names
are not portable lookup keys. New/partial installations update only existing
matching products; the staging operator separately requires the audited 65-row
inventory before applying this revision. No product is inserted or deleted.
"""

from datetime import date

from alembic import op
import sqlalchemy as sa

revision: str = "c4e9a2b7816d"
down_revision: str = "f2c7d91b6a40"
branch_labels = None
depends_on = None

RECEIPT_MAPPING_SHA256 = "313f1d4bd09865d6198bc5949000f38065fce2daea2d723d97aa34e4f1412090"
ARCHIVE_SHA256 = "247eaa5fd75590c49f8323dc0662c54cff91820df5200236ffe21f7616d69e54"

# (source catalogue, official code, authoritative date, accepted classification)
ACCEPTED_RELEASE_DATES = (
    ('bandai_jp', 'OP-01', '2022-07-22', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'OP-02', '2022-11-04', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'OP-03', '2023-02-11', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'OP-04', '2023-05-27', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'OP-05', '2023-08-26', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'OP-06', '2023-11-25', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'OP-07', '2024-02-24', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'OP-08', '2024-05-25', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'OP-09', '2024-08-31', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'OP-10', '2024-11-30', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'OP-11', '2025-03-01', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'OP-12', '2025-05-31', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'OP-13', '2025-08-23', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'OP-14', '2025-11-22', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'OP-15', '2026-02-28', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'OP-16', '2026-05-30', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'OP-17', '2026-08-22', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'EB-01', '2024-01-27', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'EB-02', '2025-01-25', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'EB-03', '2025-10-25', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'EB-04', '2026-01-31', 'DATE_VERIFIED_SINGLE_SOURCE'),
    ('bandai_jp', 'PRB-01', '2024-07-27', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'PRB-02', '2025-07-26', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-01', '2022-07-08', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-02', '2022-07-08', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-03', '2022-07-08', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-04', '2022-07-08', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-05', '2022-08-06', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-06', '2022-09-30', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-07', '2023-01-21', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-08', '2023-03-25', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-09', '2023-03-25', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-10', '2023-07-29', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-11', '2023-10-07', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-12', '2023-10-28', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-13', '2023-12-23', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-14', '2024-04-27', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-15', '2024-07-13', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-16', '2024-07-13', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-17', '2024-07-13', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-18', '2024-07-13', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-19', '2024-07-13', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-20', '2024-07-13', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-21', '2024-12-21', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-22', '2025-04-26', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-23', '2025-06-28', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-24', '2025-06-28', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-25', '2025-06-28', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-26', '2025-06-28', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-27', '2025-06-28', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-28', '2025-06-28', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-29', '2025-12-20', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-30', '2026-04-11', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-31', '2026-07-11', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-32', '2026-07-11', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-33', '2026-07-11', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-34', '2026-07-11', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-35', '2026-07-11', 'DATE_VERIFIED_CORROBORATED'),
    ('bandai_jp', 'ST-36', '2026-07-11', 'DATE_VERIFIED_CORROBORATED'),
)

CONSTRAINTS = {
    "ck_release_products_dated_requires_source": (
        "released_on IS NULL OR (release_date_source IS NOT NULL "
        "AND trim(release_date_source, ' \t\n\r') <> '')"
    ),
    "ck_release_products_release_date_source": (
        "release_date_source IS NULL OR release_date_source IN "
        "('DATE_VERIFIED_CORROBORATED', 'DATE_VERIFIED_SINGLE_SOURCE')"
    ),
}


def upgrade():
    op.add_column("release_products", sa.Column("released_on", sa.Date(), nullable=True))
    op.add_column("release_products", sa.Column("release_date_source", sa.String(32), nullable=True))
    for name, condition in CONSTRAINTS.items():
        op.create_check_constraint(name, "release_products", condition)

    # A Core table has no application onupdate hooks: updated_at is preserved.
    products = sa.table(
        "release_products",
        sa.column("source_catalogue", sa.String(16)),
        sa.column("official_code", sa.String(32)),
        sa.column("released_on", sa.Date()),
        sa.column("release_date_source", sa.String(32)),
    )
    for catalogue, code, released_on, source in ACCEPTED_RELEASE_DATES:
        op.execute(
            products.update()
            .where(products.c.source_catalogue == catalogue, products.c.official_code == code)
            .values(released_on=date.fromisoformat(released_on), release_date_source=source)
        )


def downgrade():
    for name in reversed(CONSTRAINTS):
        op.drop_constraint(name, "release_products", type_="check")
    op.drop_column("release_products", "release_date_source")
    op.drop_column("release_products", "released_on")
