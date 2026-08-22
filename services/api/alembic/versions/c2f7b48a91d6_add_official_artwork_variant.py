"""add card_prints.official_artwork_variant

Phase 3 of exact-print identity: record which official Bandai artwork each
print carries - 'base' for CODE.png, 'pN' for CODE_pN.png - parsed from the
official Card List asset address and nothing else.

Additive and reversible. The column is nullable, nothing reads it, treatment
is untouched, and the verified unique index is unchanged: this migration only
establishes the evidence that a later phase will key exact-print identity on.

The parser below is a frozen copy of app.services.official_artwork_variant.
Migrations must replay identically forever, so this one carries its own
implementation rather than importing application code that may evolve;
tests/test_official_artwork_variant.py asserts the two agree case for case,
so the copy cannot drift unnoticed.

Revision ID: c2f7b48a91d6
Revises: b6e3a9c15d47
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union
from urllib.parse import urlsplit

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2f7b48a91d6'
down_revision: Union[str, Sequence[str], None] = 'b6e3a9c15d47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Either absent, or exactly 'base' or 'p<N>' with N a positive integer and no
# leading zero. substr/length/trim rather than a regex, so the same constraint
# text holds on PostgreSQL and on the sqlite the test suite runs on.
VARIANT_FORMAT_CHECK = (
    "official_artwork_variant IS NULL OR "
    "official_artwork_variant = 'base' OR ("
    "substr(official_artwork_variant, 1, 1) = 'p' AND "
    "length(official_artwork_variant) >= 2 AND "
    "substr(official_artwork_variant, 2, 1) <> '0' AND "
    "trim(substr(official_artwork_variant, 2), '0123456789') = ''"
    ")"
)
VARIANT_FORMAT_CHECK_NAME = 'ck_card_prints_official_artwork_variant_format'


def _parse_variant(image_url: str | None, card_code: str | None) -> str | None:
    """Frozen copy of app.services.official_artwork_variant.
    parse_official_artwork_variant - see this module's docstring."""
    if not image_url or not card_code:
        return None

    basename = urlsplit(image_url.strip()).path.rsplit('/', 1)[-1]
    if not basename.lower().endswith('.png'):
        return None

    stem = basename[: -len('.png')]
    code = card_code.strip()
    if not code:
        return None

    if stem.upper() == code.upper():
        return 'base'

    if len(stem) <= len(code) or stem[: len(code)].upper() != code.upper():
        return None

    remainder = stem[len(code) :]
    if not remainder.startswith('_p'):
        return None

    digits = remainder[len('_p') :]
    if not digits.isdigit() or not digits.isascii():
        return None
    if digits.startswith('0'):
        return None

    return f'p{int(digits)}'


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'card_prints', sa.Column('official_artwork_variant', sa.String(length=16), nullable=True)
    )
    op.create_check_constraint(VARIANT_FORMAT_CHECK_NAME, 'card_prints', VARIANT_FORMAT_CHECK)

    _backfill_official_artwork_variant()


def _backfill_official_artwork_variant() -> None:
    """Derives the variant for every existing print from its own image_url.

    Reads only card_prints.image_url and the print's canonical card code, and
    writes only official_artwork_variant. treatment, artwork_key, image_url,
    release_product_code, release_product_id, mappings and observations are
    untouched.

    Fail-closed: a row whose address is missing, is not an official Card List
    .png, names a different card, or carries an unsupported suffix is left
    NULL and reported. NULL is the safe state - it means "no official artwork
    variant established" - so an unresolved row is never a reason to abort the
    migration, and never a reason to guess.
    """
    bind = op.get_bind()

    rows = bind.execute(
        sa.text(
            'SELECT cp.id, cp.image_url, cc.card_code FROM card_prints cp '
            'JOIN canonical_cards cc ON cc.id = cp.canonical_card_id '
            'ORDER BY cp.id'
        )
    ).fetchall()

    resolved: dict[str, int] = {}
    unresolved: list[tuple[int, str | None]] = []
    for print_id, image_url, card_code in rows:
        variant = _parse_variant(image_url, card_code)
        if variant is None:
            unresolved.append((print_id, image_url))
            continue
        bind.execute(
            sa.text(
                'UPDATE card_prints SET official_artwork_variant = :variant WHERE id = :id'
            ),
            {'variant': variant, 'id': print_id},
        )
        resolved[variant] = resolved.get(variant, 0) + 1

    distribution = ', '.join(f'{variant}={count}' for variant, count in sorted(resolved.items()))
    print(
        f'[{revision}] resolved {sum(resolved.values())}/{len(rows)} card_prints rows'
        f'{" - " + distribution if distribution else ""}'
    )

    if unresolved:
        detail = ', '.join(f'id={print_id} image_url={url!r}' for print_id, url in unresolved[:20])
        suffix = '' if len(unresolved) <= 20 else f' (+{len(unresolved) - 20} more)'
        print(
            f'[{revision}] WARNING: {len(unresolved)} card_prints rows have no resolvable '
            f'official artwork variant and were left NULL (not guessed): {detail}{suffix}'
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(VARIANT_FORMAT_CHECK_NAME, 'card_prints', type_='check')
    op.drop_column('card_prints', 'official_artwork_variant')
