"""add release_products, release_product_aliases and card_prints.release_product_id

Phases 1+2 of the release-product foundation: create the product entity and
its alias/evidence table, add a dormant nullable FK on card_prints, seed the
four Bandai JP products currently represented in the data, and backfill the
existing prints onto them.

Additive and reversible. Nothing reads either new table or the new column -
card_prints.release_product_code is untouched and remains the join key the
SNKRDUNK collector's RELEASE_REFERENCES uses today.

Seed provenance (all from Bandai's own Japanese product pages; the series ids
are the ones those pages themselves link to on the JP Card List):
  OP-01  ブースターパック ROMANCE DAWN【OP-01】  series 550101
  OP-02  ブースターパック 頂上決戦【OP-02】       series 550102
  OP-03  ブースターパック 強大な敵【OP-03】       series 550103
  OP-04  ブースターパック 謀略の王国【OP-04】     series 550104
Names are recorded verbatim, not normalized into a shorter label. The alias
rows carry the collector's existing ReleaseReference evidence: the Bandai
official name, and for OP-01 the SNKRDUNK katakana rendering - marked
source_rendering so it can never be mistaken for a Bandai name.

Revision ID: b6e3a9c15d47
Revises: a9c4e17b6d52
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6e3a9c15d47'
down_revision: Union[str, Sequence[str], None] = 'a9c4e17b6d52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SOURCE_CATALOGUE = 'bandai_jp'

# (official_code, display_name, first_seen_name, source_series_id, source_url)
# first_seen_name is deliberately the same verbatim title as display_name at
# creation: it is the evidence that created the row, and it never changes
# again even if Bandai renames the product.
SEED_PRODUCTS: tuple[dict, ...] = (
    {
        'official_code': 'OP-01',
        'display_name': 'ブースターパック ROMANCE DAWN【OP-01】',
        'source_series_id': '550101',
        'source_url': 'https://www.onepiece-cardgame.com/products/boosters/op01.php',
    },
    {
        'official_code': 'OP-02',
        'display_name': 'ブースターパック 頂上決戦【OP-02】',
        'source_series_id': '550102',
        'source_url': 'https://www.onepiece-cardgame.com/products/boosters/op02.php',
    },
    {
        'official_code': 'OP-03',
        'display_name': 'ブースターパック 強大な敵【OP-03】',
        'source_series_id': '550103',
        'source_url': 'https://www.onepiece-cardgame.com/products/boosters/op03.php',
    },
    {
        'official_code': 'OP-04',
        'display_name': 'ブースターパック 謀略の王国【OP-04】',
        'source_series_id': '550104',
        'source_url': 'https://www.onepiece-cardgame.com/products/boosters/op04.php',
    },
)

# (official_code, alias_name, alias_kind, source_url)
# Only names already carried as evidence in the repository's ReleaseReference
# table. additional_official_names is empty there, so nothing of that kind is
# seeded. A source_rendering has no Bandai URL by definition - inventing one
# would be exactly the fabricated evidence this separation exists to prevent.
SEED_ALIASES: tuple[tuple[str, str, str, str | None], ...] = (
    ('OP-01', 'ROMANCE DAWN', 'bandai_official',
     'https://www.onepiece-cardgame.com/products/boosters/op01.php'),
    ('OP-01', 'ロマンスドーン', 'source_rendering', None),
    ('OP-02', '頂上決戦', 'bandai_official',
     'https://www.onepiece-cardgame.com/products/boosters/op02.php'),
    ('OP-03', '強大な敵', 'bandai_official',
     'https://www.onepiece-cardgame.com/products/boosters/op03.php'),
    ('OP-04', '謀略の王国', 'bandai_official',
     'https://www.onepiece-cardgame.com/products/boosters/op04.php'),
)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'release_products',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_catalogue', sa.String(length=16), nullable=False),
        sa.Column('official_code', sa.String(length=32), nullable=True),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('first_seen_name', sa.String(length=255), nullable=False),
        sa.Column('source_series_id', sa.String(length=16), nullable=False),
        sa.Column('source_url', sa.String(length=1024), nullable=False),
        sa.Column(
            'verification_status', sa.String(length=16), server_default='unverified', nullable=False
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "trim(source_catalogue, ' \t\n\r') <> ''",
            name='ck_release_products_source_catalogue_not_blank',
        ),
        sa.CheckConstraint(
            "trim(display_name, ' \t\n\r') <> ''",
            name='ck_release_products_display_name_not_blank',
        ),
        sa.CheckConstraint(
            "trim(first_seen_name, ' \t\n\r') <> ''",
            name='ck_release_products_first_seen_name_not_blank',
        ),
        sa.CheckConstraint(
            "trim(source_series_id, ' \t\n\r') <> ''",
            name='ck_release_products_source_series_id_not_blank',
        ),
        sa.CheckConstraint(
            "trim(source_url, ' \t\n\r') <> ''",
            name='ck_release_products_source_url_not_blank',
        ),
        sa.CheckConstraint(
            "official_code IS NULL OR trim(official_code, ' \t\n\r') <> ''",
            name='ck_release_products_official_code_not_blank',
        ),
        sa.CheckConstraint(
            "verification_status IN ('verified', 'unverified', 'needs_review')",
            name='ck_release_products_verification_status',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_release_products_source_catalogue', 'release_products', ['source_catalogue'])
    # Unique per catalogue, never globally: bandai_jp OP-01 and bandai_en
    # OP-01 are different product records. Partial, so uncoded products are
    # unconstrained here.
    op.create_index(
        'uq_release_products_catalogue_official_code',
        'release_products',
        ['source_catalogue', 'official_code'],
        unique=True,
        postgresql_where=sa.text('official_code IS NOT NULL'),
        sqlite_where=sa.text('official_code IS NOT NULL'),
    )

    op.create_table(
        'release_product_aliases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('alias_name', sa.String(length=255), nullable=False),
        sa.Column('alias_kind', sa.String(length=32), nullable=False),
        sa.Column('source_url', sa.String(length=1024), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "alias_kind IN ('bandai_official', 'bandai_additional', 'source_rendering')",
            name='ck_release_product_aliases_alias_kind',
        ),
        sa.CheckConstraint(
            "trim(alias_name, ' \t\n\r') <> ''",
            name='ck_release_product_aliases_alias_name_not_blank',
        ),
        sa.CheckConstraint(
            "source_url IS NULL OR trim(source_url, ' \t\n\r') <> ''",
            name='ck_release_product_aliases_source_url_not_blank',
        ),
        sa.CheckConstraint(
            "alias_kind NOT IN ('bandai_official', 'bandai_additional') OR ("
            "source_url IS NOT NULL AND trim(source_url, ' \t\n\r') <> ''"
            ")",
            name='ck_release_product_aliases_bandai_alias_requires_source',
        ),
        sa.ForeignKeyConstraint(['product_id'], ['release_products.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'product_id', 'alias_kind', 'alias_name', name='uq_release_product_aliases_identity'
        ),
    )
    op.create_index(
        'ix_release_product_aliases_product_id', 'release_product_aliases', ['product_id']
    )

    op.add_column('card_prints', sa.Column('release_product_id', sa.Integer(), nullable=True))
    op.create_index('ix_card_prints_release_product_id', 'card_prints', ['release_product_id'])
    op.create_foreign_key(
        'fk_card_prints_release_product_id_release_products',
        'card_prints',
        'release_products',
        ['release_product_id'],
        ['id'],
        ondelete='RESTRICT',
    )

    _seed_and_backfill()


def _seed_and_backfill() -> None:
    """Seeds the four bandai_jp products with their evidence-backed aliases,
    then backfills card_prints.release_product_id.

    Fail-closed by construction: the backfill enumerates the four seeded
    codes explicitly and matches release_product_code by exact equality, so a
    code this migration does not know about - a new expansion, a promo, a
    whitespace/case variant - cannot be assigned to any product. Such a row
    keeps release_product_id NULL and is reported below rather than guessed
    at. Nothing here reads or writes treatment, artwork_key, image_url,
    release_product_code, mappings or observations.
    """
    bind = op.get_bind()

    for product in SEED_PRODUCTS:
        bind.execute(
            sa.text(
                'INSERT INTO release_products ('
                'source_catalogue, official_code, display_name, first_seen_name, '
                'source_series_id, source_url, verification_status'
                ') VALUES ('
                ':source_catalogue, :official_code, :display_name, :first_seen_name, '
                ':source_series_id, :source_url, :verification_status)'
            ),
            {
                'source_catalogue': SOURCE_CATALOGUE,
                'official_code': product['official_code'],
                'display_name': product['display_name'],
                # The creating evidence, frozen. Same value as display_name
                # today; display_name may later follow a Bandai rename, this
                # must not.
                'first_seen_name': product['display_name'],
                'source_series_id': product['source_series_id'],
                'source_url': product['source_url'],
                'verification_status': 'verified',
            },
        )

    id_by_code = {
        code: product_id
        for product_id, code in bind.execute(
            sa.text(
                'SELECT id, official_code FROM release_products '
                'WHERE source_catalogue = :catalogue'
            ),
            {'catalogue': SOURCE_CATALOGUE},
        ).fetchall()
    }

    seen_aliases: set[tuple[int, str, str]] = set()
    for code, alias_name, alias_kind, source_url in SEED_ALIASES:
        product_id = id_by_code[code]
        key = (product_id, alias_kind, alias_name)
        if key in seen_aliases:
            continue
        seen_aliases.add(key)
        bind.execute(
            sa.text(
                'INSERT INTO release_product_aliases ('
                'product_id, alias_name, alias_kind, source_url'
                ') VALUES (:product_id, :alias_name, :alias_kind, :source_url)'
            ),
            {
                'product_id': product_id,
                'alias_name': alias_name,
                'alias_kind': alias_kind,
                'source_url': source_url,
            },
        )

    for code, product_id in sorted(id_by_code.items()):
        result = bind.execute(
            sa.text(
                'UPDATE card_prints SET release_product_id = :product_id '
                'WHERE release_product_id IS NULL AND release_product_code = :code'
            ),
            {'product_id': product_id, 'code': code},
        )
        print(f'[{revision}] backfilled {result.rowcount} card_prints rows -> {code}')

    unmapped = bind.execute(
        sa.text(
            'SELECT release_product_code, count(*) FROM card_prints '
            "WHERE is_active = true AND verification_status = 'verified' "
            'AND release_product_id IS NULL GROUP BY release_product_code '
            'ORDER BY release_product_code'
        )
    ).fetchall()
    if unmapped:
        detail = ', '.join(f'{code!r}: {count}' for code, count in unmapped)
        print(
            f'[{revision}] WARNING: {sum(c for _, c in unmapped)} active+verified card_prints '
            f'rows have no release_product_id and were left NULL (not guessed): {detail}. '
            'Seed the missing product(s) in a later migration and backfill explicitly.'
        )
    else:
        print(f'[{revision}] every active+verified card_prints row resolved to a release_product')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'fk_card_prints_release_product_id_release_products', 'card_prints', type_='foreignkey'
    )
    op.drop_index('ix_card_prints_release_product_id', table_name='card_prints')
    op.drop_column('card_prints', 'release_product_id')

    op.drop_index('ix_release_product_aliases_product_id', table_name='release_product_aliases')
    op.drop_table('release_product_aliases')

    op.drop_index('uq_release_products_catalogue_official_code', table_name='release_products')
    op.drop_index('ix_release_products_source_catalogue', table_name='release_products')
    op.drop_table('release_products')
