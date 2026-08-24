"""make canonical_cards.original_set_code nullable

WHY. `original_set_code` records the set whose printing established a canonical
card - `OP01-001` -> `OP-01`, read straight out of the card code. That works for
every family Bandai codes with letters AND digits, and the complete 2026-08-22
JP corpus has exactly one family it does not work for:

    ST-*   Starter Deck        ST01-001 -> ST-01
    EB-*   Extra Booster       EB01-012 -> EB-01
    PRB-*  Premium Booster     PRB01-001 -> PRB-01
    OP-*   Booster Pack        OP01-001 -> OP-01
    P-*    PROMO               P-014     -> nothing to read

A promo carries no set number, because a promo has no set. It is distributed
inside other products - P-014 appears in PRB-01, P-084 in OP-17 and ST-25 - but
a DISTRIBUTION PRODUCT is where a printing appeared, not the card's original
set. Writing PRB-01 into `original_set_code` would assert that P-014 is a
PRB-01 card, which Bandai does not publish and which would then be read back as
evidence by the baseline rules in print_import_planner.

With the column NOT NULL the importer had to choose between inventing a value
and refusing the card. It refused, and 60 exact prints across 31 promo codes
went unimported for a reason that was about a summary column rather than about
the prints. This revision removes the forced choice: NULL means "this card has
no original set", which is the truth about a promo.

WHAT REPLACES IT. Nothing needs to. `card_prints.release_product_id` already
records exactly which product each printing appeared in, and that is the
answerable question. The canonical column answers a different one - "which set
is this card from?" - and for a promo the honest answer is "none".

WHAT THIS DOES NOT DO. No UPDATE, no INSERT, no backfill, no default, no value
rewritten. Existing values are left exactly as they are. The column is not
dropped, `ix_canonical_cards_original_set_code` is left in place, and the
blank-guard CHECK is not touched - `trim(NULL, ' \t\n\r') <> ''` evaluates to
NULL, which a CHECK treats as satisfied, so it keeps refusing '' and '   '
while permitting NULL on both PostgreSQL and SQLite. No synthetic value is
introduced anywhere: not 'P', not 'PROMO', not 'PR', and not a distribution
product code.

THE DOWNGRADE IS FAIL-CLOSED, exactly as c7e91a4d2b60's is. Restoring NOT NULL
is only representable when every row already has a set code. If any row is NULL
the downgrade raises before a single DDL statement is emitted, leaving schema,
revision and data exactly as they were. It will not invent a set code to make
itself succeed.

Revision ID: d1c48b7f36ae
Revises: c7e91a4d2b60
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1c48b7f36ae'
down_revision: Union[str, Sequence[str], None] = 'c7e91a4d2b60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = 'canonical_cards'
COLUMN = 'original_set_code'


def _preflight_downgrade() -> None:
    """NOT NULL is restorable only if the data already satisfies it.

    Alembic runs a migration inside one transaction on PostgreSQL, so raising
    here rolls back to exactly the schema and data that were there before.
    Letting the ALTER fail on its own would report a bare constraint violation
    naming no row; this names the card codes an operator has to decide about.
    """
    bind = op.get_bind()
    missing = bind.execute(
        sa.text(f"SELECT count(*) FROM {TABLE} WHERE {COLUMN} IS NULL")
    ).scalar_one()
    if not missing:
        total = bind.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one()
        print(
            f'[{revision}] downgrade preflight OK - all {total} canonical_cards row(s) '
            f'carry an {COLUMN}, so NOT NULL is representable'
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
        f"so NOT NULL cannot be restored. These are promo cards, which have no original "
        f"set: the products they appear in are distribution products, and writing one "
        f"here would assert a set membership Bandai does not publish. 'P', 'PROMO' and "
        f"'PR' are equally inventions. Each printing's actual product is already recorded "
        f"on card_prints.release_product_id. Resolve these deliberately or stay on "
        f"{revision}: {codes}{suffix}"
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
