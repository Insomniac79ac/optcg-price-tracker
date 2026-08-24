"""make canonical_cards.rarity nullable

WHY. `canonical_cards.rarity` was created NOT NULL by a4d6b1c8f3e2 on the
assumption that rarity is a property of a card. The complete 2026-08-22 JP
corpus disproves that: Bandai publishes rarity per ENTRY, and 4962 occurrences
across 2695 card codes show the same code published at different rarities in
different products (OP02-013 is 'SR' in OP-02 and 'SPカード' in its OP-08
reprint). For 49 codes the catalogue does not settle a single card-level value
at all - 31 appear only as reprints, so no original printing is present to read
one from, and 18 have several occurrences under their own set that disagree.

A NOT NULL column forced a choice between inventing a value and refusing the
card. The importer chose to refuse, which left 122 exact prints unimportable
for a reason that was about a summary column rather than about the prints. This
revision removes the forced choice: the column becomes optional, and NULL means
"the catalogue does not establish one card-level rarity", which is the truth.

WHAT REPLACES IT. `card_prints.official_rarity` (added by b8d5f1c40e73) is the
authoritative Bandai-published rarity for one exact printing, and every print
carries its own. `canonical_cards.rarity` is demoted to optional summary
metadata: not authoritative for a physical printing, not identity-bearing, and
not required to create a canonical card.

WHAT THIS DOES NOT DO. No UPDATE, no INSERT, no backfill, no default, no
value rewritten. Existing rarity values are left exactly as they are. The
column is not dropped and the blank-guard CHECK is not touched -
`trim(NULL, ' \t\n\r') <> ''` evaluates to NULL, which a CHECK treats as
satisfied, so the constraint keeps refusing '' and '   ' while permitting NULL
on both PostgreSQL and SQLite (verified 2026-08-24 on PG 18 and sqlite3).
`ix_canonical_cards_rarity` is left in place; a b-tree index over a nullable
column is exactly what the rarity filter still needs.

THE DOWNGRADE IS FAIL-CLOSED. Restoring NOT NULL is only representable when
every row already has a rarity. If any row is NULL the downgrade raises before
a single DDL statement is emitted, so the schema, the revision and the data are
left exactly as they were. It will not invent a value to make itself succeed -
'Unknown', '-' and "the most common rarity for that code" are all fabrications
that would be indistinguishable from evidence afterwards. Resolve the NULLs
deliberately, or stay on this revision.

Revision ID: c7e91a4d2b60
Revises: a9f31c7d5b64
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e91a4d2b60'
down_revision: Union[str, Sequence[str], None] = 'a9f31c7d5b64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = 'canonical_cards'
COLUMN = 'rarity'


def _preflight_downgrade() -> None:
    """NOT NULL is restorable only if the data already satisfies it.

    Alembic runs a migration inside one transaction on PostgreSQL, so raising
    here rolls back to exactly the schema and data that were there before.
    The alternative - letting the ALTER fail on its own - would report a bare
    constraint violation naming no row; this names the card codes an operator
    has to decide about.
    """
    bind = op.get_bind()
    missing = bind.execute(
        sa.text(f"SELECT count(*) FROM {TABLE} WHERE {COLUMN} IS NULL")
    ).scalar_one()
    if not missing:
        total = bind.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one()
        print(
            f'[{revision}] downgrade preflight OK - all {total} canonical_cards row(s) '
            f'carry a {COLUMN}, so NOT NULL is representable'
        )
        return

    codes = ', '.join(
        card_code
        for (card_code,) in bind.execute(
            sa.text(
                f"SELECT card_code FROM {TABLE} WHERE {COLUMN} IS NULL "
                "ORDER BY card_code LIMIT 21"
            )
        ).all()[:20]
    )
    suffix = '' if missing <= 20 else f' (+{missing - 20} more)'
    raise RuntimeError(
        f"[{revision}] ABORTED - {missing} canonical_cards row(s) have {COLUMN} IS NULL, "
        f"so NOT NULL cannot be restored. Nothing is invented here: the catalogue does "
        f"not publish one card-level rarity for these codes, and writing 'Unknown' or a "
        f"most-common value would be indistinguishable from evidence afterwards. Each "
        f"print's own official_rarity is already stored on card_prints. Resolve these "
        f"deliberately or stay on {revision}: {codes}{suffix}"
    )


def upgrade() -> None:
    # No preflight: dropping NOT NULL widens what the column accepts, so every
    # row that is representable now stays representable. Nothing is read and
    # nothing is written.
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            COLUMN,
            existing_type=sa.String(length=32),
            nullable=True,
        )
    print(
        f'[{revision}] {TABLE}.{COLUMN} is now nullable; no row was read, '
        f'written or backfilled'
    )


def downgrade() -> None:
    _preflight_downgrade()
    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column(
            COLUMN,
            existing_type=sa.String(length=32),
            nullable=False,
        )
