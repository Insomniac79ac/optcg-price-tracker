from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# What kind of evidence an alias is. The distinction is the whole point of
# the table: a storefront's spelling must never be presentable as a Bandai
# name, which is the failure mode behind the 2026-08-10 fabricated-evidence
# incident. Mirrors the three fields the collector's ReleaseReference already
# keeps separate (services/snkrdunk_collector/.../release_reference.py).
ALIAS_KINDS = (
    # What Bandai publishes for this product. The authority.
    "bandai_official",
    # An additional rendering Bandai ITSELF publishes. Needs its own Bandai
    # source URL. Empty today.
    "bandai_additional",
    # How a source/storefront writes it - nomenclature, never a Bandai name.
    "source_rendering",
)


class ReleaseProductAlias(Base):
    """One recorded name for a ReleaseProduct, with its provenance.

    Evidence/provenance only. An alias is **never** promoted to the product's
    `display_name` by virtue of existing - in particular a `source_rendering`
    (e.g. SNKRDUNK's katakana 'ロマンスドーン' for OP-01, which Bandai titles
    in Latin as 'ROMANCE DAWN') must never become the Bandai display name.
    `display_name` changes only from Bandai evidence, and the superseded name
    is kept here as a `bandai_official` alias so a rename stays auditable.

    Deleted with its product (ON DELETE CASCADE): an alias is a dependent
    record with no meaning of its own - it is a name *of* a product, so it
    cannot outlive one. The cascade is not a licence to delete products:
    card_prints.release_product_id is ON DELETE RESTRICT, so a product any
    print references cannot be deleted at all, and the design rule for a
    withdrawn product is to mark it, never to delete it.

    Nothing reads or writes this table yet.
    """

    __tablename__ = "release_product_aliases"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "alias_kind",
            "alias_name",
            name="uq_release_product_aliases_identity",
        ),
        CheckConstraint(
            "alias_kind IN ('bandai_official', 'bandai_additional', 'source_rendering')",
            name="ck_release_product_aliases_alias_kind",
        ),
        CheckConstraint(
            "trim(alias_name, ' \t\n\r') <> ''",
            name="ck_release_product_aliases_alias_name_not_blank",
        ),
        CheckConstraint(
            "source_url IS NULL OR trim(source_url, ' \t\n\r') <> ''",
            name="ck_release_product_aliases_source_url_not_blank",
        ),
        # A name claimed as Bandai's must cite Bandai. A source_rendering may
        # have no URL: its provenance is the collector's declared reference
        # table, and minting a plausible-looking storefront URL to satisfy a
        # NOT NULL would be fabricating evidence.
        CheckConstraint(
            "alias_kind NOT IN ('bandai_official', 'bandai_additional') OR ("
            "source_url IS NOT NULL AND trim(source_url, ' \t\n\r') <> ''"
            ")",
            name="ck_release_product_aliases_bandai_alias_requires_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("release_products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias_name: Mapped[str] = mapped_column(String(255), nullable=False)
    alias_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
