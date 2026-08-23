"""move identity onto official_asset_variant and drop the legacy column (contract phase)

The CONTRACT half of the expand/deploy/contract release f2e6b3a71c85 started.

f2e6b3a71c85 added official_asset_variant beside official_artwork_variant and
copied every value across, leaving a schema both application generations can
read. This revision finishes the job: it moves the verified CHECK and the
exact-print identity index onto the new column and drops the old one.

WHEN TO RUN THIS. Only after the new application is deployed and confirmed
healthy. Between the two migrations the old column is still what identity is
enforced on, so the previously deployed application keeps working; after this
one the old column is gone and that application would fail. That is intended,
and it is why this is a separate revision rather than the tail of f2e6b3a71c85
- an operator chooses when the old generation stops being supported.

WHAT IT REFUSES TO DO. Everything, unless three things are already true (see
_preflight_upgrade): every non-NULL legacy value equals its new counterpart,
every active+verified print carries a new value, and the final identity key is
already unique over the population the index will cover. Each is checked
before any DDL is emitted, so a refusal leaves the schema exactly as it was.
None of them is repaired here - filling a NULL or deduplicating a collision
would be Atlas inventing identity evidence, which is the one thing this whole
tranche exists to prevent.

WHAT IT DOES NOT TOUCH. treatment, artwork_key, release_product_id,
release_product_code, image_url, the four official_* metadata columns added by
b8d5f1c40e73, pricing, mappings and CanonicalCard. The identity index keeps
its name, its active+verified predicate and its column order; the verified
check keeps its requirements. Only the column those two name changes, and only
because the value in it is provably identical.

THE STAGING ORDER THIS RELEASE MUST BE RUN IN. Each step is finished and
verified before the next one starts; steps A and D are the only two that touch
the database, and only D is irreversible in practice.

    A. Migrate staging to b8d5f1c40e73 (this revision's parent). Both variant
       columns then exist, the legacy one still carries identity, and the
       application deployed at that moment keeps serving - nothing about it
       has changed.
    B. Deploy the new application. It reads and writes official_asset_variant;
       the legacy column is still present and simply goes unused.
    C. Verify: API healthy, print catalogue and card pages rendering, the
       collectors' price runs completing. This is the step that decides
       whether the release continues or is rolled back - rolling back here is
       just redeploying the old application, because the schema still suits it.
    D. Migrate to a9f31c7d5b64 (this revision). The preflight below re-proves
       the two columns still agree before anything is dropped.
    E. Verify again. The legacy column is gone; only the new application works
       from here.

test_asset_variant_release_states_postgres runs exactly this order against a
staging-shaped database, including the old-application checks at step C.

THE DOWNGRADE TARGET IS THE DUAL-COLUMN STATE, not the pre-expand schema. Going
back restores official_artwork_variant beside official_asset_variant and moves
identity back onto the legacy column; f2e6b3a71c85's own downgrade is what
removes the new column afterwards. It refuses when the data cannot be
represented by the legacy column at all - an rN value has no legal spelling
there, and rewriting it to 'base' would merge two distinct printings.

Revision ID: a9f31c7d5b64
Revises: b8d5f1c40e73
Create Date: 2026-08-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9f31c7d5b64'
down_revision: Union[str, Sequence[str], None] = 'b8d5f1c40e73'
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

# The legacy vocabulary, spelled exactly as c2f7b48a91d6 wrote it. Restored
# verbatim on downgrade, which is precisely why a downgrade cannot carry rN
# data back.
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


def _rows(bind, sql: str, limit: int = 20):
    return bind.execute(sa.text(sql)).all()[:limit]


def _preflight_upgrade() -> None:
    """Three conditions, all checked before a single DDL statement is emitted.

    Alembic runs a migration inside one transaction on PostgreSQL, so raising
    here rolls back to exactly the schema and data that were there before.
    """
    bind = op.get_bind()

    # 1. The copy f2e6b3a71c85 made is still faithful. If anything wrote one
    #    column without the other during the deploy window, the two disagree,
    #    and dropping the old one would silently discard the disagreement.
    diverged = bind.execute(
        sa.text(
            f"SELECT count(*) FROM card_prints "
            f"WHERE {OLD_COLUMN} IS NOT NULL AND {NEW_COLUMN} IS DISTINCT FROM {OLD_COLUMN}"
        )
    ).scalar_one()
    if diverged:
        detail = ', '.join(
            f'id={row_id} {OLD_COLUMN}={old!r} {NEW_COLUMN}={new!r}'
            for row_id, old, new in _rows(
                bind,
                f"SELECT id, {OLD_COLUMN}, {NEW_COLUMN} FROM card_prints "
                f"WHERE {OLD_COLUMN} IS NOT NULL AND {NEW_COLUMN} IS DISTINCT FROM {OLD_COLUMN} "
                "ORDER BY id LIMIT 21",
            )
        )
        suffix = '' if diverged <= 20 else f' (+{diverged - 20} more)'
        raise RuntimeError(
            f"[{revision}] ABORTED - {diverged} card_prints row(s) disagree between "
            f"{OLD_COLUMN} and {NEW_COLUMN}. Dropping the legacy column would discard "
            f"the disagreement rather than resolve it. Resolve these first: {detail}{suffix}"
        )

    # 2. Every row the identity index will cover carries the new value. A NULL
    #    here would fail the verified CHECK this migration installs, and there
    #    is no honest value to supply: 'base' is a claim about which official
    #    asset the print carries, not a placeholder.
    missing = bind.execute(
        sa.text(
            f"SELECT count(*) FROM card_prints WHERE {ACTIVE_VERIFIED} "
            f"AND {NEW_COLUMN} IS NULL"
        )
    ).scalar_one()
    if missing:
        detail = ', '.join(
            f'id={row_id}'
            for (row_id,) in _rows(
                bind,
                f"SELECT id FROM card_prints WHERE {ACTIVE_VERIFIED} "
                f"AND {NEW_COLUMN} IS NULL ORDER BY id LIMIT 21",
            )
        )
        suffix = '' if missing <= 20 else f' (+{missing - 20} more)'
        raise RuntimeError(
            f"[{revision}] ABORTED - {missing} active+verified card_prints row(s) have no "
            f"{NEW_COLUMN}, which the verified CHECK installed here requires. Nothing will "
            f"be guessed: establish each print's official asset first: {detail}{suffix}"
        )

    # 3. The final key is already unique over the population the partial index
    #    covers. Creating the index would fail on a duplicate anyway; failing
    #    here names the colliding rows instead of leaving a bare index error.
    duplicates = bind.execute(
        sa.text(
            "SELECT count(*) FROM (SELECT canonical_card_id, language, release_product_id, "
            f"{NEW_COLUMN} FROM card_prints WHERE {ACTIVE_VERIFIED} "
            "GROUP BY 1, 2, 3, 4 HAVING count(*) > 1) d"
        )
    ).scalar_one()
    if duplicates:
        detail = '; '.join(
            f'canonical_card={card} language={language} release_product={product} '
            f'{NEW_COLUMN}={variant!r} x{count}'
            for card, language, product, variant, count in _rows(
                bind,
                "SELECT canonical_card_id, language, release_product_id, "
                f"{NEW_COLUMN}, count(*) FROM card_prints WHERE {ACTIVE_VERIFIED} "
                "GROUP BY 1, 2, 3, 4 HAVING count(*) > 1 ORDER BY 1, 2, 3, 4 LIMIT 21",
            )
        )
        suffix = '' if duplicates <= 20 else f' (+{duplicates - 20} more)'
        raise RuntimeError(
            f"[{revision}] ABORTED - {duplicates} duplicate identity group(s) under "
            f"(canonical_card_id, language, release_product_id, {NEW_COLUMN}) among "
            f"active+verified prints: {detail}{suffix}"
        )

    total = bind.execute(
        sa.text(f"SELECT count(*) FROM card_prints WHERE {ACTIVE_VERIFIED}")
    ).scalar_one()
    print(
        f'[{revision}] preflight OK - {total} active+verified print(s), '
        f'{NEW_COLUMN} populated on all of them, no duplicate identity, '
        f'{OLD_COLUMN} identical wherever set'
    )


def _preflight_downgrade() -> None:
    """Refuses to hand identity back to a column that cannot hold the data.

    Two ways that can be true, and neither has an honest repair:

      * an rN value, which the legacy CHECK has no room for. Rewriting it to
        'base' would merge two distinct printings and NULLing it would strip a
        verified print of its identity evidence.
      * an active+verified row with no asset variant at all, which the legacy
        verified CHECK would reject the moment it is restored.
    """
    bind = op.get_bind()

    r_total = bind.execute(
        sa.text(f"SELECT count(*) FROM card_prints WHERE {NEW_COLUMN} LIKE 'r%'")
    ).scalar_one()
    if r_total:
        detail = ', '.join(
            f'id={row_id} {NEW_COLUMN}={value!r}'
            for row_id, value in _rows(
                bind,
                f"SELECT id, {NEW_COLUMN} FROM card_prints WHERE {NEW_COLUMN} LIKE 'r%' "
                "ORDER BY id LIMIT 21",
            )
        )
        suffix = '' if r_total <= 20 else f' (+{r_total - 20} more)'
        raise RuntimeError(
            f"[{revision}] DOWNGRADE ABORTED - {r_total} card_prints row(s) carry an rN "
            f"asset variant, which {OLD_FORMAT_CHECK} does not admit. Nothing here will "
            "rewrite them to 'base' (that would merge distinct printings) or to NULL "
            "(that would strip a verified print of its identity evidence). Resolve these "
            f"first: {detail}{suffix}"
        )

    missing = bind.execute(
        sa.text(
            f"SELECT count(*) FROM card_prints WHERE {ACTIVE_VERIFIED} "
            f"AND {NEW_COLUMN} IS NULL"
        )
    ).scalar_one()
    if missing:
        detail = ', '.join(
            f'id={row_id}'
            for (row_id,) in _rows(
                bind,
                f"SELECT id FROM card_prints WHERE {ACTIVE_VERIFIED} "
                f"AND {NEW_COLUMN} IS NULL ORDER BY id LIMIT 21",
            )
        )
        suffix = '' if missing <= 20 else f' (+{missing - 20} more)'
        raise RuntimeError(
            f"[{revision}] DOWNGRADE ABORTED - {missing} active+verified card_prints row(s) "
            f"have no {NEW_COLUMN} to copy back, and the restored verified CHECK requires "
            f"{OLD_COLUMN}. Resolve these first: {detail}{suffix}"
        )

    print(
        f'[{revision}] downgrade preflight OK - no rN variant, and every active+verified '
        f'print has a {NEW_COLUMN} the legacy column can hold'
    )


def upgrade() -> None:
    """Upgrade schema."""
    _preflight_upgrade()

    # 1-3. Release the legacy column from everything that names it.
    op.drop_constraint(VERIFIED_CHECK, 'card_prints', type_='check')
    op.drop_index(IDENTITY_INDEX, table_name='card_prints')
    op.drop_constraint(OLD_FORMAT_CHECK, 'card_prints', type_='check')

    # 4. The same verified requirements, now naming the new column.
    op.create_check_constraint(VERIFIED_CHECK, 'card_prints', _verified_check(NEW_COLUMN))

    # 5. The same identity: same index name, same predicate, same column
    #    order, over the column that now holds the value.
    op.create_index(
        IDENTITY_INDEX,
        'card_prints',
        _identity_columns(NEW_COLUMN),
        unique=True,
        postgresql_where=sa.text(ACTIVE_VERIFIED),
        sqlite_where=sa.text(SQLITE_ACTIVE_VERIFIED),
    )

    # 6. Only now, with nothing naming it and its values proven identical, the
    #    legacy column goes.
    op.drop_column('card_prints', OLD_COLUMN)

    print(f'[{revision}] {OLD_COLUMN} dropped; identity now enforced on {NEW_COLUMN}')


def downgrade() -> None:
    """Downgrade schema."""
    _preflight_downgrade()

    # 1. The legacy column back, empty and nullable.
    op.add_column('card_prints', sa.Column(OLD_COLUMN, sa.String(length=16), nullable=True))

    # 2. Copied from the new column, verbatim - the preflight has already
    #    proven every value is one the legacy vocabulary admits.
    bind = op.get_bind()
    copied = bind.execute(
        sa.text(
            f"UPDATE card_prints SET {OLD_COLUMN} = {NEW_COLUMN} "
            f"WHERE {NEW_COLUMN} IS NOT NULL"
        )
    ).rowcount
    print(f'[{revision}] copied {copied} {NEW_COLUMN} value(s) back into {OLD_COLUMN}')

    # 3. The legacy vocabulary, restored verbatim.
    op.create_check_constraint(OLD_FORMAT_CHECK, 'card_prints', OLD_FORMAT_CHECK_SQL)

    # 4-6. Identity back on the legacy column, same name and predicate.
    op.drop_index(IDENTITY_INDEX, table_name='card_prints')
    op.drop_constraint(VERIFIED_CHECK, 'card_prints', type_='check')
    op.create_check_constraint(VERIFIED_CHECK, 'card_prints', _verified_check(OLD_COLUMN))
    op.create_index(
        IDENTITY_INDEX,
        'card_prints',
        _identity_columns(OLD_COLUMN),
        unique=True,
        postgresql_where=sa.text(ACTIVE_VERIFIED),
        sqlite_where=sa.text(SQLITE_ACTIVE_VERIFIED),
    )

    # NEW_COLUMN and its format check stay: this restores the dual-column
    # intermediate state f2e6b3a71c85 created, not the pre-expand schema.
    # Downgrading f2e6b3a71c85 afterwards is what removes the new column.
