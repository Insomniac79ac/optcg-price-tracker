"""add print-specific official metadata to card_prints

Four nullable columns recording what Bandai publishes for one exact printing:
official_rarity, official_block_icon, official_name, official_effect_text.

WHY THESE FOUR. The boundary was measured, not chosen. Across the complete
2026-08-22 JP corpus - 4,962 occurrences over 2,823 card codes - these are the
only published fields that materially vary between occurrences of one card
code:

    rarity        122 card codes vary materially
    block icon     17
    effect text    30 material (a further 103 differ only in formatting)
    card name       1 material (a further 18 differ only in formatting)

and these do not vary at all, anywhere in that corpus:

    color, cost, counter, attribute, feature, category, power

An invariant field given a print-level column could only ever repeat what
CanonicalCard already holds, so none is added here.

WHY `official_name` AND NOT `official_name_jp`. card_prints already carries
`language`, so the language of a published name is a property of the row and
not something a column name needs to repeat. One column holds
'モンキー・D・ルフィ' on a JP print and 'Monkey.D.Luffy' on an EN one; a
per-language column would have to be added again for every language Atlas
ever ingests, and every row would carry NULLs for the languages it is not.

WHY `official_*` AND NOT AN OVERRIDE. These store the published value itself,
not a difference from CanonicalCard. If Bandai publishes 'SR' for a printing
then official_rarity is 'SR' even when CanonicalCard.rarity is also 'SR'. The
question the columns exist to answer is "what does Bandai publish for this
exact printing?", and a diff-only column cannot answer it without a join plus
a convention about what NULL means. CanonicalCard stays the normalised,
shared card identity and is not touched by this migration.

WHAT THIS MIGRATION DOES NOT DO. It adds four columns and nothing else. No
backfill, no UPDATE, no INSERT, no network access, and no dependence on any
local snapshot file - the numbers above are provenance recorded in this
docstring, never something read at migration time. The exact-print unique
index, the verified-print CHECK, official_asset_variant, treatment,
artwork_key, release_product_id and release_product_code are all untouched.

NOT REQUIRED FOR `verified`. Deliberately. Every verified row that exists
today predates these columns and would fail instantly if the check demanded
them. Making them required is a decision for after an importer populates
them, and it is a separate migration.

Revision ID: b8d5f1c40e73
Revises: f2e6b3a71c85
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8d5f1c40e73'
down_revision: Union[str, Sequence[str], None] = 'f2e6b3a71c85'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = 'card_prints'

# (name, type). Types match the conventions the neighbouring canonical columns
# already use: rarity String(32) as CanonicalCard.rarity, name String(255) as
# CanonicalCard.name_jp, effect text Text as CanonicalCard.effect_text.
#
# official_block_icon is String(8) rather than Integer because the source
# vocabulary is textual: the corpus publishes '1'-'5' and also 'X' (27
# occurrences). An integer column would have to invent a meaning for 'X' or
# discard it, and this migration's whole purpose is to preserve what Bandai
# published.
COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ('official_rarity', sa.String(length=32)),
    ('official_block_icon', sa.String(length=8)),
    ('official_name', sa.String(length=255)),
    ('official_effect_text', sa.Text()),
)


def upgrade() -> None:
    """Upgrade schema."""
    for name, type_ in COLUMNS:
        # Nullable with no server_default: an added column is NULL on every
        # existing row, and NULL is the honest state - "Atlas has not yet
        # populated authoritative print-specific metadata". A default would
        # write a value nobody published.
        op.add_column(TABLE, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Drops only these four columns. Nothing else in this table was changed on
    # the way up, so nothing else is restored on the way down.
    for name, _ in reversed(COLUMNS):
        op.drop_column(TABLE, name)
