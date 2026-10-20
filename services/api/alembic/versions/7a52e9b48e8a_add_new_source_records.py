"""add generic new-source records, grade_key and splice tables (new-sources plan S1)

Revision ID: 7a52e9b48e8a
Revises: 3b7d9c1a5e20

Additive only. No existing row is changed or backfilled: price_observations.grade_key is a new
nullable column (NULL for every Yuyu-Tei and SNKRDUNK row), its CHECKs are added NOT VALID and then
validated, and the proposal-group candidate-type CHECK is widened, never narrowed. The `dorasuta`
and `cardrush` source rows are inert: no collector writes for them until its own rollout, and the
public-series guard registers them before any price row exists (plan S2).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "7a52e9b48e8a"
down_revision: Union[str, Sequence[str], None] = "3b7d9c1a5e20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Restated from app.source_products.grade_keys.SQL_PATTERN (tests hold them equal).
GRADE_KEY_PATTERN = r"^(raw:(A|A-|B|C|D|damaged|play)|graded:(unknown|[A-Z]{2,8}:[0-9]{1,2}(\.5)?([:]flawed)?))$"
NEW_SOURCES = (("dorasuta", "https://dorasuta.jp"), ("cardrush", "https://www.cardrush-op.jp"))
OLD_CANDIDATE_TYPES = "source_candidate_type IN ('yuyutei_candidate', 'snkrdunk_candidate')"
NEW_CANDIDATE_TYPES = (
    "source_candidate_type IN ('yuyutei_candidate', 'snkrdunk_candidate', 'source_product')"
)


def _timestamps():
    return (
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def upgrade() -> None:
    for name, base_url in NEW_SOURCES:
        op.execute(
            sa.text(
                "INSERT INTO sources (name, base_url) SELECT :name, :base_url "
                "WHERE NOT EXISTS (SELECT 1 FROM sources WHERE name = :name)"
            ).bindparams(name=name, base_url=base_url)
        )

    op.add_column("price_observations", sa.Column("grade_key", sa.String(length=32), nullable=True))
    # NOT VALID then VALIDATE: no long lock on the largest table; every existing row is NULL.
    op.execute(
        "ALTER TABLE price_observations ADD CONSTRAINT ck_price_observations_grade_key "
        f"CHECK (grade_key IS NULL OR grade_key ~ '{GRADE_KEY_PATTERN}') NOT VALID"
    )
    # PSA10 is OFF (decision N10): graded keys live in source_product_variants only.
    op.execute(
        "ALTER TABLE price_observations ADD CONSTRAINT ck_price_observations_grade_key_raw_only "
        "CHECK (grade_key IS NULL OR grade_key LIKE 'raw:%') NOT VALID"
    )
    op.execute("ALTER TABLE price_observations VALIDATE CONSTRAINT ck_price_observations_grade_key")
    op.execute("ALTER TABLE price_observations VALIDATE CONSTRAINT ck_price_observations_grade_key_raw_only")

    op.drop_constraint(
        "ck_mapping_proposal_groups_candidate_type", "source_mapping_proposal_groups", type_="check"
    )
    op.create_check_constraint(
        "ck_mapping_proposal_groups_candidate_type", "source_mapping_proposal_groups", NEW_CANDIDATE_TYPES
    )

    op.create_table(
        "source_product_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("group_key", sa.String(length=128), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "release_product_id",
            sa.Integer(),
            sa.ForeignKey("release_products.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        *_timestamps(),
        sa.UniqueConstraint("source_id", "group_key", name="uq_source_product_groups_source_key"),
        sa.CheckConstraint(
            "kind IN ('pack', 'deck', 'promo', 'series', 'other')", name="ck_source_product_groups_kind"
        ),
    )
    op.create_index(
        "ix_source_product_groups_release_product_id", "source_product_groups", ["release_product_id"]
    )

    op.create_table(
        "source_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_product_key", sa.String(length=64), nullable=False),
        sa.Column("canonical_listing_identity", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("group_keys", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("parsed_code", sa.String(length=32), nullable=True),
        sa.Column("rarity", sa.String(length=16), nullable=True),
        sa.Column("variant_markers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("qualifier", sa.String(length=64), nullable=True),
        sa.Column("listing_kind", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("match_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("refusal_code", sa.String(length=64), nullable=True),
        sa.Column(
            "card_print_id", sa.Integer(), sa.ForeignKey("card_prints.id", ondelete="RESTRICT"), nullable=True
        ),
        *_timestamps(),
        sa.UniqueConstraint("source_id", "source_product_key", name="uq_source_products_source_key"),
        sa.UniqueConstraint("canonical_listing_identity", name="uq_source_products_listing_identity"),
        sa.CheckConstraint(
            "listing_kind IN ('plain', 'parallel', 'special', 'foil', 'graded', 'sealed', 'unknown')",
            name="ck_source_products_listing_kind",
        ),
        sa.CheckConstraint(
            "match_status IN ('pending', 'exact', 'manual', 'quarantined', 'refused')",
            name="ck_source_products_match_status",
        ),
        sa.CheckConstraint(
            "(match_status IN ('exact', 'manual')) = (card_print_id IS NOT NULL)",
            name="ck_source_products_print_iff_matched",
        ),
        sa.CheckConstraint(
            "(match_status IN ('quarantined', 'refused')) = (refusal_code IS NOT NULL)",
            name="ck_source_products_refusal_iff_unmatched",
        ),
    )
    op.create_index("ix_source_products_parsed_code", "source_products", ["parsed_code"])
    op.create_index("ix_source_products_card_print_id", "source_products", ["card_print_id"])

    op.create_table(
        "source_product_variants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_product_id",
            sa.Integer(),
            sa.ForeignKey("source_products.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("grade_key", sa.String(length=32), nullable=False),
        sa.Column("last_price_jpy", sa.Integer(), nullable=True),
        sa.Column("stock", sa.Integer(), nullable=True),
        sa.Column("on_sale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_raw_snapshot_id",
            sa.Integer(),
            sa.ForeignKey("raw_snapshots.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "source_product_id", "grade_key", name="uq_source_product_variants_product_grade"
        ),
        sa.CheckConstraint(f"grade_key ~ '{GRADE_KEY_PATTERN}'", name="ck_source_product_variants_grade_key"),
        sa.CheckConstraint(
            "last_price_jpy IS NULL OR last_price_jpy > 0", name="ck_source_product_variants_price"
        ),
        sa.CheckConstraint("stock IS NULL OR stock >= 0", name="ck_source_product_variants_stock"),
    )
    op.create_index(
        "ix_source_product_variants_last_raw_snapshot_id", "source_product_variants", ["last_raw_snapshot_id"]
    )

    op.create_table(
        "source_variant_renderings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("marker_text", sa.String(length=128), nullable=False),
        sa.Column("official_asset_variant", sa.String(length=16), nullable=True),
        sa.Column("artwork_rule", sa.String(length=64), nullable=True),
        sa.Column("reviewed_by", sa.String(length=128), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("source_id", "marker_text", name="uq_source_variant_renderings_source_marker"),
        sa.CheckConstraint(
            "official_asset_variant IS NOT NULL OR artwork_rule IS NOT NULL",
            name="ck_source_variant_renderings_has_meaning",
        ),
        sa.CheckConstraint("length(trim(reviewed_by)) > 0", name="ck_source_variant_renderings_reviewed_by"),
    )

    op.create_table(
        "market_index_splices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("splice_date", sa.Date(), nullable=False),
        sa.Column("from_semantics_version", sa.Integer(), nullable=False),
        sa.Column("to_semantics_version", sa.Integer(), nullable=False),
        sa.Column("source_added", sa.String(length=64), nullable=False),
        sa.Column("approved_by", sa.String(length=128), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("splice_date", name="uq_market_index_splices_date"),
        sa.UniqueConstraint("to_semantics_version", name="uq_market_index_splices_to_version"),
        sa.CheckConstraint(
            "to_semantics_version = from_semantics_version + 1",
            name="ck_market_index_splices_one_version_step",
        ),
        sa.CheckConstraint("length(trim(approved_by)) > 0", name="ck_market_index_splices_approved_by"),
    )

    op.create_table(
        "market_index_splice_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "splice_id", sa.Integer(), sa.ForeignKey("market_index_splices.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "card_print_id", sa.Integer(), sa.ForeignKey("card_prints.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("index_value_jpy", sa.Integer(), nullable=True),
        sa.Column("calculation_method", sa.String(length=64), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("coverage_status", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("index_version", sa.Integer(), nullable=False),
        sa.Column("source_semantics_version", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        # The old-basis source_values, same shape as market_index_snapshots.provenance, so the
        # contributor-set guard can check the leg that ends on the splice day.
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("splice_id", "card_print_id", name="uq_market_index_splice_snapshots_print"),
    )
    op.create_index(
        "ix_market_index_splice_snapshots_card_print_id", "market_index_splice_snapshots", ["card_print_id"]
    )


def downgrade() -> None:
    # Refuses (foreign keys, CHECK) rather than discard new-source evidence: the tables must be
    # empty and no proposal group may use the widened candidate type.
    for table in (
        "market_index_splice_snapshots",
        "market_index_splices",
        "source_variant_renderings",
        "source_product_variants",
        "source_products",
        "source_product_groups",
    ):
        op.execute(
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {table}) THEN "
            f"RAISE EXCEPTION '{table} is not empty; refusing to drop new-source evidence'; END IF; END $$"
        )
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM price_observations WHERE grade_key IS NOT NULL) THEN "
        "RAISE EXCEPTION 'price_observations.grade_key is in use; refusing to drop it'; END IF; END $$"
    )
    op.drop_index("ix_market_index_splice_snapshots_card_print_id", table_name="market_index_splice_snapshots")
    op.drop_table("market_index_splice_snapshots")
    op.drop_table("market_index_splices")
    op.drop_table("source_variant_renderings")
    op.drop_index("ix_source_product_variants_last_raw_snapshot_id", table_name="source_product_variants")
    op.drop_table("source_product_variants")
    op.drop_index("ix_source_products_card_print_id", table_name="source_products")
    op.drop_index("ix_source_products_parsed_code", table_name="source_products")
    op.drop_table("source_products")
    op.drop_index("ix_source_product_groups_release_product_id", table_name="source_product_groups")
    op.drop_table("source_product_groups")
    op.drop_constraint(
        "ck_mapping_proposal_groups_candidate_type", "source_mapping_proposal_groups", type_="check"
    )
    op.create_check_constraint(
        "ck_mapping_proposal_groups_candidate_type", "source_mapping_proposal_groups", OLD_CANDIDATE_TYPES
    )
    op.drop_constraint("ck_price_observations_grade_key_raw_only", "price_observations", type_="check")
    op.drop_constraint("ck_price_observations_grade_key", "price_observations", type_="check")
    op.drop_column("price_observations", "grade_key")
    # The dorasuta and cardrush source rows stay: other rows may reference them by then, and an
    # inert source row changes nothing.
