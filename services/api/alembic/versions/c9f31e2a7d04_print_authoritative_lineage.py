"""make print lineage authoritative and legacy card_id optional

Revision ID: c9f31e2a7d04
Revises: 8c31a5f0d2b7
Create Date: 2026-08-28 07:10:00.000000

WHAT THIS CHANGES, AND WHY IT IS THE WHOLE POINT.

b858237e3706 added print lineage *alongside* the legacy `cards` pointer and
tied the two together: an observation's composite FK carried card_id, so every
priced row had to name a legacy Card as well as an exact print. That was the
right shape while print lineage was additive. It is the wrong shape now,
because the legacy table cannot describe the catalogue: 25 rows over 21 card
codes against 4,281 active verified prints over 2,710 codes. 98.6% of prints
have no legacy Card at all, and several codes that do exist carry contradictory
rows (OP01-013 appears twice under different character names). Requiring a
legacy Card per priced print therefore means either duplicating the catalogue
into a table whose identity columns are demonstrably unreliable, or never
pricing anything outside the original 21 codes.

So card_id stops being part of identity. It becomes what it actually is: a
legacy compatibility pointer, present on old rows, optional on new ones.

THE FK NARROWS, AND THAT MAKES IT STRONGER, NOT WEAKER. The old constraint
was (source_card_mapping_id, card_print_id, card_id, source_id). Postgres
foreign keys default to MATCH SIMPLE: if ANY referencing column is NULL the
row is not checked at all. Once card_id is nullable, a print-authoritative
observation - card_id NULL, mapping and print populated - would slip past the
old FK entirely and could name a mapping belonging to another source or
another print. Dropping card_id from the key is what keeps those rows
enforced. Nothing else is relaxed: mapping, print and source must still agree
with the mapping row, and ck_price_observations_lineage_paired still forbids
naming a mapping without a print.

NO BACKFILL, IN EITHER DIRECTION. Existing values are untouched; every current
row keeps the card_id it has, and all 74 mappings / 642 observations remain
valid unchanged. This migration only widens what is permitted.

NOT ADDING canonical_card_id. It is reachable from card_print_id through
CardPrint, and storing it again would create a second copy of the same fact to
keep in step - the exact failure this migration exists to end.

DOWNGRADE IS HONEST ABOUT ITS LIMIT. Restoring NOT NULL cannot invent a legacy
Card for a row that never had one, so the downgrade refuses with a clear
message if any print-authoritative row exists rather than backfilling a
plausible-looking card_id. Over staging-shaped data, where no such row exists,
it round-trips cleanly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c9f31e2a7d04"
down_revision: Union[str, Sequence[str], None] = "8c31a5f0d2b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # The FK first: it depends on the unique constraint below, and the new
    # narrower key has to exist before the new FK can reference it.
    op.drop_constraint(
        "fk_price_observations_mapping_print_card_source",
        "price_observations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_source_card_mappings_lineage_identity",
        "source_card_mappings",
        type_="unique",
    )

    # Legacy compatibility only, on both tables. No backfill, no default:
    # existing values stay exactly as they are.
    op.alter_column(
        "source_card_mappings",
        "card_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        "price_observations",
        "card_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    # The print-authoritative key. Same role as the one it replaces - it
    # exists solely so price_observations can carry the composite FK below -
    # and is still not a uniqueness rule on any column individually, since id
    # is already the primary key.
    op.create_unique_constraint(
        "uq_source_card_mappings_print_lineage_identity",
        "source_card_mappings",
        ["id", "card_print_id", "source_id"],
    )
    op.create_foreign_key(
        "fk_price_observations_mapping_print_source",
        "price_observations",
        "source_card_mappings",
        ["source_card_mapping_id", "card_print_id", "source_id"],
        ["id", "card_print_id", "source_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    """Downgrade schema.

    Refuses rather than inventing legacy identity - see the module docstring.
    """
    bind = op.get_bind()
    for table in ("source_card_mappings", "price_observations"):
        orphaned = bind.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE card_id IS NULL")
        ).scalar_one()
        if orphaned:
            raise RuntimeError(
                f"Cannot downgrade: {orphaned} row(s) in {table} have card_id IS NULL. "
                "Restoring NOT NULL would require inventing a legacy cards row for each, "
                "which is precisely the guess this lineage model exists to avoid. "
                "Resolve or remove those rows first."
            )

    op.drop_constraint(
        "fk_price_observations_mapping_print_source",
        "price_observations",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_source_card_mappings_print_lineage_identity",
        "source_card_mappings",
        type_="unique",
    )

    op.alter_column(
        "price_observations",
        "card_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "source_card_mappings",
        "card_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.create_unique_constraint(
        "uq_source_card_mappings_lineage_identity",
        "source_card_mappings",
        ["id", "card_print_id", "card_id", "source_id"],
    )
    op.create_foreign_key(
        "fk_price_observations_mapping_print_card_source",
        "price_observations",
        "source_card_mappings",
        ["source_card_mapping_id", "card_print_id", "card_id", "source_id"],
        ["id", "card_print_id", "card_id", "source_id"],
        ondelete="RESTRICT",
    )
