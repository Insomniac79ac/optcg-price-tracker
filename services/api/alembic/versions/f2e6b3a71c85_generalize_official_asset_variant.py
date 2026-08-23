"""add official_asset_variant alongside official_artwork_variant (expand phase)

The EXPAND half of an expand/deploy/contract release. This migration adds the
new column, teaches it the wider vocabulary and copies every existing value
into it - and deliberately changes nothing else, so a database that has run it
still satisfies the application that is deployed right now.

WHY NOT A RENAME. An earlier draft of this revision renamed
official_artwork_variant to official_asset_variant in one step. That is safe
only if the schema and the application change at the same instant, and they
cannot: a migration runs before the new code is live, so between the two there
is a window in which the deployed application queries a column that no longer
exists. Every read of card_prints in that window would fail. Splitting the
change in two removes the window entirely - after this migration BOTH columns
exist, the old application keeps using the old one, and a9f31c7d5b64 removes
the old one only once the new application is confirmed healthy.

1. THE NAME. `official_artwork_variant` promised more than the evidence
   supports. The suffix Bandai publishes identifies *which official asset* an
   occurrence carries, not that the artwork differs: the complete 2026-08-22
   JP corpus contains 152 rN assets whose bytes are byte-for-byte identical to
   a base asset. The new column is `official_asset_variant`.

2. THE GRAMMAR. The old CHECK admitted only `base` and `p<N>`, which was the
   whole published vocabulary when it was written. Measuring the complete JP
   catalogue on 2026-08-22 (4,962 occurrences: base 2,821, p1-p10 1,680,
   r1-r3 461, and nothing else) established a second family, so `r<N>` is
   admitted on the new column - as an *address*, not a meaning.

WHAT rN BUYS. Three cards publish both `_r1` and `_r2` inside one product:
OP01-120, OP05-074 and OP05-119, all in PRB-01. Their entries carry distinct
official entry ids, distinct asset addresses and distinct SHA-256 digests, so
they are genuinely different printings. Without rN in the vocabulary all three
collapse to a NULL variant and collide under the exact-print key; with it, all
three resolve and the corpus has no suffix-induced collision left.

WHAT rN DOES NOT BUY. No human treatment meaning whatsoever. rN says nothing
about parallel, manga, special, alt-art or rarity, and `treatment` must never
be inferred from it - every one of the 459 rN assets whose card also has a
base sibling carries the *same* rarity as that sibling. Identical image bytes
may still be distinct print identities: `artwork_key` stays SHA-256 evidence
and is deliberately not identity.

WHAT THIS MIGRATION DELIBERATELY LEAVES ALONE. The identity machinery the
deployed application relies on:

    ck_card_prints_verified_requires_fields   still names official_artwork_variant
    uq_card_prints_active_verified_identity   still indexes official_artwork_variant
    ck_card_prints_official_artwork_variant_format   still in force, unchanged

plus treatment, artwork_key, release_product_id, release_product_code,
image_url, pricing and mappings. The old column keeps its old CHECK and stays
the column identity is enforced on until the contract migration says otherwise.

WHY THE COPY IS SAFE. The new format CHECK is created *before* the backfill on
purpose. Every value the old column can legally hold - NULL, 'base', 'p<N>' -
is admitted by the new one, so a copy that violates it is impossible; if one
somehow did, this migration would fail loudly rather than write it. No value
is guessed: rows whose old column is NULL stay NULL in the new column, and the
number of values actually copied is printed so the copy can be *seen* to be
complete.

Revision ID: f2e6b3a71c85
Revises: d4b17c9e2a83
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2e6b3a71c85'
down_revision: Union[str, Sequence[str], None] = 'd4b17c9e2a83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_COLUMN = 'official_artwork_variant'
NEW_COLUMN = 'official_asset_variant'

OLD_FORMAT_CHECK = 'ck_card_prints_official_artwork_variant_format'
NEW_FORMAT_CHECK = 'ck_card_prints_official_asset_variant_format'

# Named here only to say, in one place, that this migration does not touch
# them. They keep naming OLD_COLUMN until a9f31c7d5b64 contracts the schema.
IDENTITY_INDEX = 'uq_card_prints_active_verified_identity'
VERIFIED_CHECK = 'ck_card_prints_verified_requires_fields'


def _format_check(column: str, letters: str) -> str:
    """Either absent, or exactly 'base' or '<letter><N>' with N a positive
    integer and no leading zero.

    substr/length/trim rather than a regex, so one constraint holds on both
    PostgreSQL and the sqlite the test suite builds its schema on - Postgres'
    `~` and sqlite's GLOB have no common spelling. trim(x, '0123456789')
    emptying out is what proves "digits only".
    """
    return (
        f"{column} IS NULL OR "
        f"{column} = 'base' OR ("
        f"substr({column}, 1, 1) IN ({letters}) AND "
        f"length({column}) >= 2 AND "
        f"substr({column}, 2, 1) <> '0' AND "
        f"trim(substr({column}, 2), '0123456789') = ''"
        ")"
    )


# The new vocabulary on the new column: base, p<N>, r<N>. A strict superset of
# what the old column admits, which is what makes the backfill total.
NEW_FORMAT_CHECK_SQL = _format_check(NEW_COLUMN, "'p', 'r'")

# The vocabulary the OLD column keeps, spelled exactly as c2f7b48a91d6 wrote
# it. Reproduced here only so the relationship between the two is readable in
# one place - this migration neither drops nor recreates it.
OLD_FORMAT_CHECK_SQL = (
    f"{OLD_COLUMN} IS NULL OR "
    f"{OLD_COLUMN} = 'base' OR ("
    f"substr({OLD_COLUMN}, 1, 1) = 'p' AND "
    f"length({OLD_COLUMN}) >= 2 AND "
    f"substr({OLD_COLUMN}, 2, 1) <> '0' AND "
    f"trim(substr({OLD_COLUMN}, 2), '0123456789') = ''"
    ")"
)


def _report(column: str) -> None:
    """Prints one column's variant distribution, so the copy can be *seen*.

    Reads only. Printed for both columns after the backfill, where the two
    distributions being identical is the evidence that nothing was lost.
    """
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            f"SELECT coalesce({column}, '<null>') AS v, count(*) FROM card_prints "
            "GROUP BY 1 ORDER BY 1"
        )
    ).all()
    total = sum(count for _, count in rows)
    distribution = ', '.join(f'{variant}={count}' for variant, count in rows)
    print(
        f'[{revision}] {total} card_prints rows, {column} distribution: '
        f'{distribution or "<no rows>"}'
    )


def _backfill() -> int:
    """Copies every non-NULL old value into the new column. Returns the count.

    Verbatim, one column to the other - no translation, no defaulting, no
    guessing. A row whose old column is NULL is left NULL: NULL means "Atlas
    has not established which official asset this print carries", and writing
    'base' over it would manufacture identity evidence nobody published.
    """
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            f"UPDATE card_prints SET {NEW_COLUMN} = {OLD_COLUMN} "
            f"WHERE {OLD_COLUMN} IS NOT NULL"
        )
    )
    return result.rowcount


def _preflight_downgrade() -> None:
    """Refuses to drop the new column while it holds anything the old one does not.

    Going back is lossless exactly when the new column is still a faithful
    copy: every row where the two disagree - an rN value the old vocabulary
    has no room for, or a value written to one column and not the other -
    would be destroyed by the drop. So this aborts and names the rows instead
    of discarding them.
    """
    bind = op.get_bind()

    diverged = bind.execute(
        sa.text(
            f"SELECT count(*) FROM card_prints "
            f"WHERE {NEW_COLUMN} IS DISTINCT FROM {OLD_COLUMN}"
        )
    ).scalar_one()

    if diverged:
        rows = bind.execute(
            sa.text(
                f"SELECT id, {OLD_COLUMN}, {NEW_COLUMN} FROM card_prints "
                f"WHERE {NEW_COLUMN} IS DISTINCT FROM {OLD_COLUMN} ORDER BY id LIMIT 20"
            )
        ).all()
        detail = ', '.join(
            f'id={row_id} {OLD_COLUMN}={old!r} {NEW_COLUMN}={new!r}'
            for row_id, old, new in rows
        )
        suffix = '' if diverged <= 20 else f' (+{diverged - 20} more)'
        raise RuntimeError(
            f"[{revision}] DOWNGRADE ABORTED - {diverged} card_prints row(s) hold a "
            f"{NEW_COLUMN} the legacy {OLD_COLUMN} does not carry, so dropping the new "
            "column would destroy them. Nothing here will rewrite an rN value to 'base' "
            "(that would merge distinct printings) or to NULL (that would strip a "
            f"verified print of its identity evidence). Resolve these first: {detail}{suffix}"
        )

    print(
        f'[{revision}] downgrade preflight OK - {NEW_COLUMN} is a faithful copy of '
        f'{OLD_COLUMN} on every row'
    )


def upgrade() -> None:
    """Upgrade schema."""
    _report(OLD_COLUMN)

    # 1. The new column, nullable and empty. Nothing names it yet, so adding
    #    it cannot affect a single query the deployed application runs.
    op.add_column('card_prints', sa.Column(NEW_COLUMN, sa.String(length=16), nullable=True))

    # 2. The widened vocabulary, installed BEFORE the copy so the copy is
    #    checked by it rather than trusted.
    op.create_check_constraint(NEW_FORMAT_CHECK, 'card_prints', NEW_FORMAT_CHECK_SQL)

    # 3. The copy. The only write this migration performs, and it reads its
    #    values from the column beside it - never from a default.
    copied = _backfill()
    print(f'[{revision}] copied {copied} {OLD_COLUMN} value(s) into {NEW_COLUMN}')

    # 4. Both distributions, which must now be identical.
    _report(OLD_COLUMN)
    _report(NEW_COLUMN)

    # NOT TOUCHED, deliberately: ck_card_prints_verified_requires_fields and
    # uq_card_prints_active_verified_identity both still name OLD_COLUMN, and
    # the old format check is still in force. That is what keeps the currently
    # deployed application working against this schema.


def downgrade() -> None:
    """Downgrade schema."""
    _preflight_downgrade()

    op.drop_constraint(NEW_FORMAT_CHECK, 'card_prints', type_='check')
    op.drop_column('card_prints', NEW_COLUMN)
