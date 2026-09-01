from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# What Atlas can say about a discovered Yuyu-Tei product from its printed card
# code ALONE. Every value here is a statement about catalogue cardinality, not
# a matching decision, and none of them creates a source_card_mappings row.
#
# unmatched: the parsed code matches no canonical_cards row - or no code could
#   be parsed from the listing at all. Nothing to attach it to.
# family_matched: the canonical card exists, but the code does not identify one
#   exact printing. matched_card_print_id stays NULL: with 2+ active prints
#   sharing the code there is no non-arbitrary way to pick one, and picking a
#   "representative" is exactly the error this vocabulary exists to prevent.
#   Also used when the family exists with ZERO active prints - the family is
#   known, an exact print still is not.
# print_matched: exactly one active card_print carries that code, so the print
#   is implied by the code with no judgement involved. matched_card_print_id
#   points at it. This is still NOT an approval and still NOT a mapping.
# identity_conflict: the catalogue contradicted its own uniqueness invariant
#   (uq_canonical_cards_card_code) and returned more than one canonical card
#   for one code. Canonical identity is then unprovable, so discovery fails
#   closed rather than choosing: no print id, and a reason in
#   match_explanation_json. Defensive - it should be unreachable.
MATCH_STATUSES = ("unmatched", "family_matched", "print_matched", "identity_conflict")


class YuyuteiCandidate(Base):
    """One Yuyu-Tei product observed on a category listing page.

    IDENTITY IS COMPOSITE, AND THAT IS MEASURED, NOT DEFENSIVE. Yuyu-Tei's
    numeric product id is unique within a category slug and NOT across the
    site: ids 10152/10153/10154 exist in both `op01` and `op13` and denote
    different cards. `product_id` alone would therefore collapse unrelated
    products into one row, so the natural key is (set_slug, product_id).

    EVERY FIELD IS LISTING-DERIVED. Nothing here requires a product-page fetch;
    the category page carries the code, rarity token, JP name, price, stock
    state and artwork URL. A candidate is evidence of what the source displayed
    - it is never a price observation and never a mapping.

    SOURCE TEXT IS KEPT VERBATIM. name_jp retains Yuyu-Tei's own variant
    annotations - パラレル, スーパーパラレル, レッドスーパーパラレル, 刻印なし -
    and raw_listing_text keeps the whole listing row. Those annotations are the
    only listing-level evidence that distinguishes the 2+ prints behind a
    family_matched code, so normalising them away here would destroy the input
    the later exact-print matcher needs.
    """

    __tablename__ = "yuyutei_candidates"
    __table_args__ = (
        # The authoritative source identity. NOT product_id alone.
        UniqueConstraint("set_slug", "product_id", name="uq_yuyutei_candidates_set_slug_product"),
        CheckConstraint(
            "match_status IN ('unmatched', 'family_matched', 'print_matched', "
            "'identity_conflict')",
            name="ck_yuyutei_candidates_match_status",
        ),
        # Makes "pick a representative printing" unrepresentable rather than
        # merely discouraged: only the one status that means "the code implies
        # exactly one active print" may carry a print id.
        CheckConstraint(
            "matched_card_print_id IS NULL OR match_status = 'print_matched'",
            name="ck_yuyutei_candidates_print_requires_print_matched",
        ),
        CheckConstraint(
            "availability IS NULL OR availability IN ('in_stock', 'out_of_stock', "
            "'unknown_present_marker')",
            name="ck_yuyutei_candidates_availability",
        ),
        # A price is a positive integer number of yen or it is absent. 0 and
        # negatives are parse failures, not prices.
        CheckConstraint(
            "price_jpy IS NULL OR price_jpy > 0",
            name="ck_yuyutei_candidates_price_positive",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    discovery_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("yuyutei_discovery_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # --- source identity ---
    set_slug: Mapped[str] = mapped_column(String(32), index=True)
    product_id: Mapped[str] = mapped_column(String(32))
    source_url: Mapped[str] = mapped_column(String(1024))

    # --- listing-derived facts ---
    detected_card_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    detected_rarity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name_jp: Mapped[str | None] = mapped_column(String(512), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    price_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    availability: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # The whole listing row as displayed, unnormalised - the audit trail behind
    # every parsed field above, and the evidence a human approver reads.
    raw_listing_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- catalogue classification (never a mapping) ---
    match_status: Mapped[str] = mapped_column(
        String(32), default="unmatched", server_default="unmatched", index=True
    )
    # FK to card_prints, the exact-print table - NOT to legacy `cards`, whose
    # ids live in a different namespace (snkrdunk_candidates.matched_card_id
    # predates exact-print identity and points at the old one).
    matched_card_print_id: Mapped[int | None] = mapped_column(
        ForeignKey("card_prints.id", ondelete="SET NULL"), nullable=True
    )
    # Why this status was reached: the canonical card id, how many active
    # prints share the code, and for family_matched, which prints they are.
    # Written for a human reviewer and for the later matcher; never queried on.
    match_explanation_json: Mapped[dict | None] = mapped_column(
        MutableDict.as_mutable(JSON), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
