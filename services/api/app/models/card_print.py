from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

VERIFICATION_STATUSES = ("verified", "unverified", "needs_review")


class CardPrint(Base):
    """One printing of a CanonicalCard, identified by the product it shipped
    in and the official artwork it carries.

    Exact-print identity is
    `(canonical_card_id, language, release_product_id, official_artwork_variant)`
    for active, verified prints - see the uq_card_prints_active_verified_identity
    index. `treatment` is deliberately NOT part of it: it is editable Atlas
    descriptive metadata ("normal", "parallel", ...), never a physical
    property Bandai publishes, so a verified print may carry NULL there when
    Atlas has not classified it.

    A print starts life `unverified` with its identity fields null. The
    ck_card_prints_verified_requires_fields check is what forces
    release_product_id, official_artwork_variant and artwork_key to be filled
    in before it can be marked `verified`. release_product_code is NOT
    required: Bandai ships uncoded limited/promotional products, and those
    prints are legitimate.

    Guessed placeholder values (e.g. 'original', '', 'unknown') are rejected
    by the ck_card_prints_no_fake_* constraints - a print with an unknown
    product, artwork or treatment must stay null there, not fake it."""

    __tablename__ = "card_prints"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('verified', 'unverified', 'needs_review')",
            name="ck_card_prints_verification_status",
        ),
        # What a verified print must be able to prove about itself: which
        # printing it is (product + official artwork, the identity fields
        # below), and the digest of the artwork that was checked. treatment
        # is absent on purpose - it is not identity - and so is
        # release_product_code, because uncoded limited products exist.
        CheckConstraint(
            "verification_status <> 'verified' OR ("
            "canonical_card_id IS NOT NULL AND "
            "language IS NOT NULL AND trim(language, ' \t\n\r') <> '' AND "
            "release_product_id IS NOT NULL AND "
            "official_artwork_variant IS NOT NULL AND "
            "artwork_key IS NOT NULL AND "
            # treatment is optional, but on a verified print a placeholder is
            # still not a classification - NULL says "unclassified" honestly.
            # Scoped to verified rows exactly as before: an unverified print
            # may still park 'unknown' here while it is being worked out.
            "(treatment IS NULL OR ("
            "trim(treatment, ' \t\n\r') <> '' AND "
            "lower(trim(treatment, ' \t\n\r')) <> 'unknown'"
            "))"
            ")",
            name="ck_card_prints_verified_requires_fields",
        ),
        CheckConstraint(
            "release_product_code IS NULL OR ("
            "trim(release_product_code, ' \t\n\r') <> '' AND "
            "lower(trim(release_product_code, ' \t\n\r')) <> 'original'"
            ")",
            name="ck_card_prints_no_fake_release_product_code",
        ),
        CheckConstraint(
            "artwork_key IS NULL OR ("
            "trim(artwork_key, ' \t\n\r') <> '' AND "
            "lower(trim(artwork_key, ' \t\n\r')) <> 'original'"
            ")",
            name="ck_card_prints_no_fake_artwork_key",
        ),
        # official_artwork_variant is either absent or exactly 'base' or
        # 'p<N>' with N a positive integer and no leading zero. Expressed with
        # substr/length/trim rather than a regex so one constraint holds on
        # both PostgreSQL and the sqlite the test suite runs on - Postgres'
        # `~` and sqlite's GLOB have no common spelling. trim(x, '0123456789')
        # emptying out is what proves "digits only".
        CheckConstraint(
            "official_artwork_variant IS NULL OR "
            "official_artwork_variant = 'base' OR ("
            "substr(official_artwork_variant, 1, 1) = 'p' AND "
            "length(official_artwork_variant) >= 2 AND "
            "substr(official_artwork_variant, 2, 1) <> '0' AND "
            "trim(substr(official_artwork_variant, 2), '0123456789') = ''"
            ")",
            name="ck_card_prints_official_artwork_variant_format",
        ),
        # Exact-print identity. Neither treatment (editorial), nor
        # release_product_code (absent for uncoded products), nor artwork_key
        # (evidence, not identity) appears here. The verified check above
        # forbids a NULL in either identity field, so PostgreSQL's
        # multiple-NULLs-are-distinct rule cannot weaken this index.
        Index(
            "uq_card_prints_active_verified_identity",
            "canonical_card_id",
            "language",
            "release_product_id",
            "official_artwork_variant",
            unique=True,
            postgresql_where=text("is_active = true AND verification_status = 'verified'"),
            sqlite_where=text("is_active = 1 AND verification_status = 'verified'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_card_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_cards.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    # Editable Atlas descriptive metadata, NOT identity. NULL means Atlas
    # has not classified this printing; no synthetic "other" value exists.
    treatment: Mapped[str | None] = mapped_column(String(64), nullable=True)
    release_product_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Dormant lineage FK to the first-class product entity (release_products).
    # Nullable on purpose: a print whose product is unknown or not yet
    # resolved must have a safe state, and the backfill leaves an unexpected
    # release_product_code NULL here rather than guessing a product.
    # release_product_code above is NOT replaced by this - it stays the join
    # key the SNKRDUNK collector's RELEASE_REFERENCES uses today.
    release_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("release_products.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    artwork_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Which official Bandai artwork this print carries - 'base' for CODE.png,
    # 'pN' for CODE_pN.png - parsed from the official asset address only (see
    # app.services.official_artwork_variant). It says nothing about parallel/
    # manga/special/alt-art/rarity, and treatment must never be inferred from
    # it.
    #
    # Identity-bearing evidence: it is the artwork component of the intended
    # future dedupe key (canonical_card_id, language, release_product_id,
    # official_artwork_variant). This tranche only records it - the verified
    # unique index above is unchanged and still keyed on treatment and
    # artwork_key, and nothing reads this column yet.
    #
    # Nullable because an unresolved or future asset must have a safe state:
    # no image, a non-Card-List address, or a basename that does not name
    # this print's own card all leave it NULL rather than guessed.
    official_artwork_variant: Mapped[str | None] = mapped_column(String(16), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    artist: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unverified", server_default="unverified"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Reverse side of SourceCardMapping.card_print - not eagerly loaded and
    # not accessed by any existing code path. No delete cascade: deleting a
    # CardPrint with mappings attached is rejected outright by the
    # ON DELETE RESTRICT on source_card_mappings.card_print_id.
    source_card_mappings: Mapped[list["SourceCardMapping"]] = relationship(
        "SourceCardMapping",
        back_populates="card_print",
        foreign_keys="SourceCardMapping.card_print_id",
    )
