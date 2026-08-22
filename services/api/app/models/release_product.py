from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.card_print import VERIFICATION_STATUSES

# The authority namespace a product record was published in. NOT a language
# and NOT an inferred market: it names the catalogue that published the
# record, which is the only product-scoping fact that is directly observable.
#
# Bandai runs several catalogues and they do not share a product namespace
# (verified 2026-08-22, see docs/snkrdunk_release_reference.md):
#   - the JP and Asia-EN catalogues both publish OP-01 dated 2022-07-22 while
#     the EN catalogue publishes it dated 2022-12-02 - so language does not
#     identify a product record, and two English catalogues disagree;
#   - EB-04 is a standalone product on JP/Asia-EN but has no standalone EN
#     record at all: those cards ship inside EN products coded OP14-EB04 /
#     OP15-EB04, so a code can be absent, or composite, in another catalogue.
# Only `bandai_jp` is seeded today; the others exist here as vocabulary, not
# as data.
SOURCE_CATALOGUES = ("bandai_jp", "bandai_asia_en", "bandai_en")


class ReleaseProduct(Base):
    """One product record **as published by one authoritative catalogue**.

    Identity is the surrogate `id` and nothing else. No name, and no
    normalization of a name, is ever identity - the repo's own
    normalize_release_text collapses 30 distinct Bandai products into 13 keys
    (measured 2026-08-21), which is why prose cannot key this table.

    Three fields are immutable **by contract** (no database trigger enforces
    it; nothing in this tranche writes to the table at all):

    - `source_catalogue` - which authority published this record. Changing it
      would silently re-namespace the product.
    - `official_code` - once set, frozen. A code is unique only *within* its
      catalogue, never globally.
    - `first_seen_name` - the evidence that created the row. `display_name`
      may be updated when Bandai renames a product; `first_seen_name` keeps
      the rename auditable, and the old name is additionally preserved as a
      `bandai_official` alias (see ReleaseProductAlias).

    Uncoded products (`official_code IS NULL`) are legitimate and numerous -
    Bandai's Card List carried 223 name-only limited/promotional products in
    the 2026-08-21 sample. They are identified by their surrogate id plus the
    frozen `(source_catalogue, source_series_id, first_seen_name, source_url)`
    evidence, never auto-merged by name.

    Nothing reads or writes this table yet: it is dormant infrastructure
    added alongside `card_prints.release_product_id`.
    """

    __tablename__ = "release_products"
    # trim(x, ' \t\n\r') is the two-argument form both SQLite and PostgreSQL
    # accept - plain trim(x) strips only spaces, letting a tab/newline-only
    # value past a "not blank" check. Same convention as canonical_cards.
    __table_args__ = (
        CheckConstraint(
            "trim(source_catalogue, ' \t\n\r') <> ''",
            name="ck_release_products_source_catalogue_not_blank",
        ),
        CheckConstraint(
            "trim(display_name, ' \t\n\r') <> ''",
            name="ck_release_products_display_name_not_blank",
        ),
        CheckConstraint(
            "trim(first_seen_name, ' \t\n\r') <> ''",
            name="ck_release_products_first_seen_name_not_blank",
        ),
        CheckConstraint(
            "trim(source_series_id, ' \t\n\r') <> ''",
            name="ck_release_products_source_series_id_not_blank",
        ),
        CheckConstraint(
            "trim(source_url, ' \t\n\r') <> ''",
            name="ck_release_products_source_url_not_blank",
        ),
        # Either absent or meaningful - never blank. Deliberately no format
        # regex: real Bandai codes include composites such as OP14-EB04, and
        # a shape check would reject them.
        CheckConstraint(
            "official_code IS NULL OR trim(official_code, ' \t\n\r') <> ''",
            name="ck_release_products_official_code_not_blank",
        ),
        CheckConstraint(
            "verification_status IN ('verified', 'unverified', 'needs_review')",
            name="ck_release_products_verification_status",
        ),
        # A code is unique only within the catalogue that published it, so
        # bandai_jp OP-01 and bandai_en OP-01 must be able to coexist as
        # separate rows. A global UNIQUE(official_code) would collide the
        # first time EN data is ingested and silently attach EN prints to a
        # JP product. Partial, so uncoded products are unconstrained here.
        Index(
            "uq_release_products_catalogue_official_code",
            "source_catalogue",
            "official_code",
            unique=True,
            postgresql_where=text("official_code IS NOT NULL"),
            sqlite_where=text("official_code IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_catalogue: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    official_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    first_seen_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_series_id: Mapped[str] = mapped_column(String(16), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unverified", server_default="unverified"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# Re-exported so callers can validate against the same three-state vocabulary
# card_prints uses, rather than a second copy that could drift.
__all__ = ["ReleaseProduct", "SOURCE_CATALOGUES", "VERIFICATION_STATUSES"]
