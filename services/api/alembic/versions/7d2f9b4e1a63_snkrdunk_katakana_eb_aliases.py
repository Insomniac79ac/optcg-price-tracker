"""Record three SNKRDUNK katakana Extra Booster names as source renderings.

Frozen input: docs/evidence/snkrdunk-katakana-eb-aliases-2026-11-19.json. SNKRDUNK
writes EB-02, EB-03 and EB-04 in katakana, so the release gate refuses every listing
of those releases for a name Bandai never published. Each name is added as
`source_rendering` for the snkrdunk source with no Bandai URL (never a Bandai name),
the same way OP-01 `ロマンスドーン` is seeded in b6e3a9c15d47. Only an existing
bandai_jp product with the official code receives a row; nothing is updated or deleted
on upgrade, and a row that already exists is left alone. Downgrade removes exactly
these rows.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "7d2f9b4e1a63"
down_revision: str = "cb7419af37e9"
branch_labels = None
depends_on = None

# (official code of the bandai_jp release product, SNKRDUNK katakana rendering)
SOURCE_RENDERINGS = (
    ("EB-04", "エッグヘッドクライシス"),
    ("EB-03", "ワンピース ヒロインズエディション"),
    ("EB-02", "アニメ 25th コレクション"),
)


def upgrade():
    for code, name in SOURCE_RENDERINGS:
        op.execute(
            sa.text(
                "INSERT INTO release_product_aliases (product_id, alias_name, alias_kind, source_url, source_id) "
                "SELECT p.id, :name, 'source_rendering', NULL, s.id "
                "FROM release_products p, sources s "
                "WHERE p.source_catalogue = 'bandai_jp' AND p.official_code = :code AND s.name = 'snkrdunk' "
                "AND NOT EXISTS (SELECT 1 FROM release_product_aliases a "
                "WHERE a.source_id = s.id AND a.alias_name = :name AND a.alias_kind = 'source_rendering')"
            ).bindparams(name=name, code=code)
        )


def downgrade():
    for code, name in SOURCE_RENDERINGS:
        op.execute(
            sa.text(
                "DELETE FROM release_product_aliases WHERE alias_kind = 'source_rendering' AND alias_name = :name "
                "AND source_url IS NULL AND source_id = (SELECT id FROM sources WHERE name = 'snkrdunk') "
                "AND product_id IN (SELECT id FROM release_products "
                "WHERE source_catalogue = 'bandai_jp' AND official_code = :code)"
            ).bindparams(name=name, code=code)
        )
