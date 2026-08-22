"""rename official_artwork_variant to official_asset_variant, admit the rN family

Two corrections in one migration, because either alone would leave the schema
saying something false.

1. THE NAME. `official_artwork_variant` promised more than the evidence
   supports. The suffix Bandai publishes identifies *which official asset* an
   occurrence carries, not that the artwork differs: the complete 2026-08-22
   JP corpus contains 152 rN assets whose bytes are byte-for-byte identical to
   a base asset. The column becomes `official_asset_variant`.

2. THE GRAMMAR. The old CHECK admitted only `base` and `p<N>`, which was the
   whole published vocabulary when it was written. Measuring the complete JP
   catalogue on 2026-08-22 (4,962 occurrences: base 2,821, p1-p10 1,680,
   r1-r3 461, and nothing else) established a second family, so `r<N>` is
   admitted here - as an *address*, not a meaning.

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

WHAT DOES NOT CHANGE. Not one value. The rename is a rename - no row is
rewritten beyond whatever PostgreSQL does internally for a column rename, and
treatment, artwork_key, release_product_id, release_product_code, image_url,
pricing and mappings are all untouched. The identity index keeps its name, its
active+verified predicate and its column order; the verified check keeps its
requirements. Only the column those two name is spelled differently, and only
the format check admits more.

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

IDENTITY_INDEX = 'uq_card_prints_active_verified_identity'
VERIFIED_CHECK = 'ck_card_prints_verified_requires_fields'

ACTIVE_VERIFIED = "is_active = true AND verification_status = 'verified'"
SQLITE_ACTIVE_VERIFIED = "is_active = 1 AND verification_status = 'verified'"

# PostgreSQL rewrites a constraint's stored parse tree when a column it names
# is renamed, so both checks and the index below would *follow* the rename on
# their own. They are dropped and recreated explicitly anyway, so the contract
# in force afterwards is the text written here rather than something inherited
# implicitly - and so the same steps hold on any engine.


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


# The new vocabulary: base, p<N>, r<N>.
NEW_FORMAT_CHECK_SQL = _format_check(NEW_COLUMN, "'p', 'r'")

# The vocabulary being replaced: base and p<N> only, spelled exactly as
# c2f7b48a91d6 wrote it. Restored verbatim on downgrade, which is precisely
# why a downgrade cannot carry rN data back.
OLD_FORMAT_CHECK_SQL = (
    f"{OLD_COLUMN} IS NULL OR "
    f"{OLD_COLUMN} = 'base' OR ("
    f"substr({OLD_COLUMN}, 1, 1) = 'p' AND "
    f"length({OLD_COLUMN}) >= 2 AND "
    f"substr({OLD_COLUMN}, 2, 1) <> '0' AND "
    f"trim(substr({OLD_COLUMN}, 2), '0123456789') = ''"
    ")"
)


def _verified_check(column: str) -> str:
    """The verified requirements, unchanged except for the column's spelling.

    Kept as one template so the upgrade and downgrade texts cannot drift into
    saying different things about treatment, artwork_key or
    release_product_code - none of which this migration touches.
    """
    return (
        "verification_status <> 'verified' OR ("
        "canonical_card_id IS NOT NULL AND "
        "language IS NOT NULL AND trim(language, ' \t\n\r') <> '' AND "
        "release_product_id IS NOT NULL AND "
        f"{column} IS NOT NULL AND "
        "artwork_key IS NOT NULL AND "
        # treatment stays optional and non-identity; a placeholder on a
        # verified row is still not a classification.
        "(treatment IS NULL OR ("
        "trim(treatment, ' \t\n\r') <> '' AND "
        "lower(trim(treatment, ' \t\n\r')) <> 'unknown'"
        "))"
        ")"
    )


def _identity_columns(column: str) -> list[str]:
    return ['canonical_card_id', 'language', 'release_product_id', column]


def _report(column: str) -> None:
    """Prints the variant distribution, so the rename can be *seen* to preserve it.

    Reads only; the upgrade has nothing to refuse. The new format check admits
    a strict superset of the old one, and the identity index covers the same
    four columns over the same population, so no existing row can fail the
    contract this migration installs.
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


def _preflight_downgrade() -> None:
    """Refuses to restore the p-only vocabulary over rN data.

    Going back means the old CHECK - which never knew the r family - comes
    back. A row carrying `r1` cannot satisfy it, and there is no honest way to
    make it fit: rewriting it to `base` would merge two distinct printings,
    and NULLing it would strip a verified print of its identity evidence. So
    this aborts and names the rows rather than coercing them.
    """
    bind = op.get_bind()

    r_total = bind.execute(
        sa.text(f"SELECT count(*) FROM card_prints WHERE {NEW_COLUMN} LIKE 'r%'")
    ).scalar_one()

    if r_total:
        r_rows = bind.execute(
            sa.text(
                f"SELECT id, {NEW_COLUMN} FROM card_prints "
                f"WHERE {NEW_COLUMN} LIKE 'r%' ORDER BY id LIMIT 20"
            )
        ).all()
        detail = ', '.join(f'id={row_id} {NEW_COLUMN}={value!r}' for row_id, value in r_rows)
        suffix = '' if r_total <= 20 else f' (+{r_total - 20} more)'
        raise RuntimeError(
            f"[{revision}] DOWNGRADE ABORTED - {r_total} card_prints row(s) carry an rN "
            "asset variant, which the previous CHECK does not admit. Nothing here will "
            "rewrite them to 'base' (that would merge distinct printings) or to NULL "
            "(that would strip a verified print of its identity evidence). Resolve these "
            f"first: {detail}{suffix}"
        )

    print(f'[{revision}] downgrade preflight OK - no rN asset variant in card_prints')


def upgrade() -> None:
    """Upgrade schema."""
    _report(OLD_COLUMN)

    # 1. Release the column from everything that names it. On PostgreSQL these
    #    would follow the rename by themselves; dropping them makes the
    #    post-migration contract explicit rather than inherited.
    op.drop_index(IDENTITY_INDEX, table_name='card_prints')
    op.drop_constraint(VERIFIED_CHECK, 'card_prints', type_='check')
    op.drop_constraint(OLD_FORMAT_CHECK, 'card_prints', type_='check')

    # 2. The rename itself. No value is read, written or rewritten.
    op.alter_column(
        'card_prints', OLD_COLUMN,
        new_column_name=NEW_COLUMN,
        existing_type=sa.String(length=16),
        existing_nullable=True,
    )

    # 3. The widened vocabulary: base, p<N> and now r<N>.
    op.create_check_constraint(NEW_FORMAT_CHECK, 'card_prints', NEW_FORMAT_CHECK_SQL)

    # 4. The same verified requirements, under the new spelling.
    op.create_check_constraint(VERIFIED_CHECK, 'card_prints', _verified_check(NEW_COLUMN))

    # 5. The same identity: same index name, same predicate, same column order.
    op.create_index(
        IDENTITY_INDEX,
        'card_prints',
        _identity_columns(NEW_COLUMN),
        unique=True,
        postgresql_where=sa.text(ACTIVE_VERIFIED),
        sqlite_where=sa.text(SQLITE_ACTIVE_VERIFIED),
    )

    _report(NEW_COLUMN)


def downgrade() -> None:
    """Downgrade schema."""
    _preflight_downgrade()

    op.drop_index(IDENTITY_INDEX, table_name='card_prints')
    op.drop_constraint(VERIFIED_CHECK, 'card_prints', type_='check')
    op.drop_constraint(NEW_FORMAT_CHECK, 'card_prints', type_='check')

    op.alter_column(
        'card_prints', NEW_COLUMN,
        new_column_name=OLD_COLUMN,
        existing_type=sa.String(length=16),
        existing_nullable=True,
    )

    op.create_check_constraint(OLD_FORMAT_CHECK, 'card_prints', OLD_FORMAT_CHECK_SQL)
    op.create_check_constraint(VERIFIED_CHECK, 'card_prints', _verified_check(OLD_COLUMN))
    op.create_index(
        IDENTITY_INDEX,
        'card_prints',
        _identity_columns(OLD_COLUMN),
        unique=True,
        postgresql_where=sa.text(ACTIVE_VERIFIED),
        sqlite_where=sa.text(SQLITE_ACTIVE_VERIFIED),
    )
