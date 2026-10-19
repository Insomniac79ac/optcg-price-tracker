"""ORM for the generic source-record and splice tables (migration 7a52e9b48e8a).

Kept outside app.models on purpose (package docstring). The `grade_key` column added to
price_observations by the same migration is deliberately not on the shared PriceObservation model:
that file is a runtime input of both existing collectors (plan §2.1, §2.7). New-source writers use
`price_observation_grade_keys` below, a lightweight table definition of just the columns they set.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

GROUP_KINDS = ("pack", "deck", "promo", "series", "other")
LISTING_KINDS = ("plain", "parallel", "special", "foil", "graded", "sealed", "unknown")
MATCH_STATUSES = ("pending", "exact", "manual", "quarantined", "refused")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class SourceProductGroup(Base):
    """A list page grouping on a source: a CardRush pack group or a Dorasuta `sid` series."""

    __tablename__ = "source_product_groups"
    __table_args__ = (
        UniqueConstraint("source_id", "group_key", name="uq_source_product_groups_source_key"),
        CheckConstraint(_in("kind", GROUP_KINDS), name="ck_source_product_groups_kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False)
    group_key: Mapped[str] = mapped_column(String(128), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    release_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("release_products.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SourceProduct(Base):
    """One product id on a source, with its verbatim name and the identity outcome."""

    __tablename__ = "source_products"
    __table_args__ = (
        UniqueConstraint("source_id", "source_product_key", name="uq_source_products_source_key"),
        UniqueConstraint("canonical_listing_identity", name="uq_source_products_listing_identity"),
        CheckConstraint(_in("listing_kind", LISTING_KINDS), name="ck_source_products_listing_kind"),
        CheckConstraint(_in("match_status", MATCH_STATUSES), name="ck_source_products_match_status"),
        # A print is attached exactly when the outcome is exact or manual.
        CheckConstraint(
            "(match_status IN ('exact', 'manual')) = (card_print_id IS NOT NULL)",
            name="ck_source_products_print_iff_matched",
        ),
        CheckConstraint(
            "(match_status IN ('quarantined', 'refused')) = (refusal_code IS NOT NULL)",
            name="ck_source_products_refusal_iff_unmatched",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False)
    source_product_key: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_listing_identity: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    group_keys: Mapped[list] = mapped_column(JSON, nullable=False, server_default="[]")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    rarity: Mapped[str | None] = mapped_column(String(16), nullable=True)
    variant_markers: Mapped[list] = mapped_column(JSON, nullable=False, server_default="[]")
    qualifier: Mapped[str | None] = mapped_column(String(64), nullable=True)
    listing_kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default="unknown")
    match_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    refusal_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    card_print_id: Mapped[int | None] = mapped_column(
        ForeignKey("card_prints.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SourceProductVariant(Base):
    """Product x grade_key: the last price, stock and sale flag seen on a list page."""

    __tablename__ = "source_product_variants"
    __table_args__ = (
        UniqueConstraint("source_product_id", "grade_key", name="uq_source_product_variants_product_grade"),
        # PostgreSQL regex; SQLite test databases created from the ORM skip it.
        CheckConstraint(
            r"grade_key ~ '^(raw:(A|A-|B|C|D|damaged|play)|graded:(unknown|[A-Z]{2,8}:[0-9]{1,2}(\.5)?([:]flawed)?))$'",
            name="ck_source_product_variants_grade_key",
        ).ddl_if(dialect="postgresql"),
        CheckConstraint("last_price_jpy IS NULL OR last_price_jpy > 0", name="ck_source_product_variants_price"),
        CheckConstraint("stock IS NULL OR stock >= 0", name="ck_source_product_variants_stock"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_product_id: Mapped[int] = mapped_column(
        ForeignKey("source_products.id", ondelete="RESTRICT"), nullable=False
    )
    grade_key: Mapped[str] = mapped_column(String(32), nullable=False)
    last_price_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    on_sale: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_raw_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_snapshots.id", ondelete="RESTRICT"), nullable=True, index=True
    )


class SourceVariantRendering(Base):
    """A reviewed marker text on one source and the official variant or artwork rule it means.

    Manual entries only: nothing derives a rendering from data.
    """

    __tablename__ = "source_variant_renderings"
    __table_args__ = (
        UniqueConstraint("source_id", "marker_text", name="uq_source_variant_renderings_source_marker"),
        CheckConstraint(
            "official_asset_variant IS NOT NULL OR artwork_rule IS NOT NULL",
            name="ck_source_variant_renderings_has_meaning",
        ),
        CheckConstraint(
            "length(trim(reviewed_by)) > 0", name="ck_source_variant_renderings_reviewed_by"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False)
    marker_text: Mapped[str] = mapped_column(String(128), nullable=False)
    official_asset_variant: Mapped[str | None] = mapped_column(String(16), nullable=True)
    artwork_rule: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_by: Mapped[str] = mapped_column(String(128), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class MarketIndexSplice(Base):
    """One approved source cutover (Q6 splice; plan §2.6). Inert until a row exists; each row is RED."""

    __tablename__ = "market_index_splices"
    __table_args__ = (
        UniqueConstraint("splice_date", name="uq_market_index_splices_date"),
        UniqueConstraint("to_semantics_version", name="uq_market_index_splices_to_version"),
        CheckConstraint(
            "to_semantics_version = from_semantics_version + 1",
            name="ck_market_index_splices_one_version_step",
        ),
        CheckConstraint("length(trim(approved_by)) > 0", name="ck_market_index_splices_approved_by"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    splice_date: Mapped[date] = mapped_column(Date, nullable=False)
    from_semantics_version: Mapped[int] = mapped_column(Integer, nullable=False)
    to_semantics_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_added: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MarketIndexSpliceSnapshot(Base):
    """The old-basis Market Index row for one print on a splice day (market_index_snapshots keeps
    its one row per print and day, on the new basis)."""

    __tablename__ = "market_index_splice_snapshots"
    __table_args__ = (
        UniqueConstraint("splice_id", "card_print_id", name="uq_market_index_splice_snapshots_print"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    splice_id: Mapped[int] = mapped_column(
        ForeignKey("market_index_splices.id", ondelete="RESTRICT"), nullable=False
    )
    card_print_id: Mapped[int] = mapped_column(
        ForeignKey("card_prints.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    index_value_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calculation_method: Mapped[str] = mapped_column(String(64), nullable=False)
    source_count: Mapped[int] = mapped_column(Integer, nullable=False)
    coverage_status: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    index_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_semantics_version: Mapped[int] = mapped_column(Integer, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Old-basis source_values, the same shape as market_index_snapshots.provenance.
    provenance: Mapped[dict] = mapped_column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)


# The new-source writer's view of price_observations: only the columns it sets, on a private
# MetaData so it never joins Base.metadata (create_all and model parity stay as they are).
price_observation_grade_keys = Table(
    "price_observations",
    MetaData(),
    Column("id", Integer, primary_key=True),
    Column("grade_key", String(32), nullable=True),
)

TABLES = (
    "source_product_groups",
    "source_products",
    "source_product_variants",
    "source_variant_renderings",
    "market_index_splices",
    "market_index_splice_snapshots",
)
