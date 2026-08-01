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
    """One printing (language/treatment/product) of a CanonicalCard. A print
    starts life `unverified` with release_product_code/artwork_key left
    null - see the ck_card_prints_verified_requires_fields check constraint,
    which is what actually forces those two fields (and a non-'unknown'
    treatment) to be filled in before a print can be marked `verified`.
    Guessed placeholder values (e.g. 'original' or '') for those two fields
    are rejected by the ck_card_prints_no_fake_* constraints instead - a
    print with unknown product/artwork must stay null there, not fake it."""

    __tablename__ = "card_prints"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('verified', 'unverified', 'needs_review')",
            name="ck_card_prints_verification_status",
        ),
        CheckConstraint(
            "verification_status <> 'verified' OR ("
            "treatment IS NOT NULL AND trim(treatment, ' \t\n\r') <> '' AND "
            "lower(trim(treatment, ' \t\n\r')) <> 'unknown' AND "
            "release_product_code IS NOT NULL AND "
            "artwork_key IS NOT NULL"
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
        Index(
            "uq_card_prints_active_verified_identity",
            "canonical_card_id",
            "language",
            "treatment",
            "release_product_code",
            "artwork_key",
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
    treatment: Mapped[str] = mapped_column(String(64), nullable=False)
    release_product_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artwork_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
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
