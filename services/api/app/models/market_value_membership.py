"""Frozen Market Value membership (owner plan A, 2026-10-28).

Every published Market Value point names the membership it was calculated with
(``MarketValuePoint.membership_revision``).  Until now only that digest was
stored, and publication re-derived the membership from today's catalogue, so
any catalogue import made every published day "mismatch".  These append-only
tables keep the membership itself: the active/verified/jp physical prints with
the release each belonged to, and the coded releases that had a scope.  A
published day is verified against its own frozen membership, never today's.

Deliberately not imported by ``app.models`` (no collector imports these).
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

MEMBERSHIP_ORIGINS = ("legacy_rebuilt", "publication", "recovery")


class MarketValueMembership(Base):
    __tablename__ = "market_value_memberships"
    __table_args__ = (
        CheckConstraint(
            "trim(revision, ' \t\n\r') <> ''",
            name="ck_market_value_memberships_revision_not_blank",
        ),
        CheckConstraint(
            "origin IN ('legacy_rebuilt', 'publication', 'recovery')",
            name="ck_market_value_memberships_origin",
        ),
        CheckConstraint(
            "print_count > 0 AND release_count >= 0",
            name="ck_market_value_memberships_counts",
        ),
        UniqueConstraint("revision", name="uq_market_value_memberships_revision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Same vocabulary as MarketValuePoint.membership_revision.
    revision: Mapped[str] = mapped_column(String(160), nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    print_count: Mapped[int] = mapped_column(Integer, nullable=False)
    release_count: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MarketValueMembershipPrint(Base):
    __tablename__ = "market_value_membership_prints"
    __table_args__ = (
        Index(
            "ix_market_value_membership_prints_release",
            "membership_id",
            "release_product_id",
        ),
    )

    membership_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("market_value_memberships.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    card_print_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("card_prints.id", ondelete="RESTRICT"), primary_key=True
    )
    release_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("release_products.id", ondelete="RESTRICT"), nullable=False
    )


class MarketValueMembershipRelease(Base):
    """A coded release that had its own scope under this membership."""

    __tablename__ = "market_value_membership_releases"
    __table_args__ = (
        CheckConstraint(
            "trim(official_code, ' \t\n\r') <> ''",
            name="ck_market_value_membership_releases_code_not_blank",
        ),
    )

    membership_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("market_value_memberships.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    release_product_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("release_products.id", ondelete="RESTRICT"), primary_key=True
    )
    official_code: Mapped[str] = mapped_column(String(64), nullable=False)


__all__ = [
    "MEMBERSHIP_ORIGINS",
    "MarketValueMembership",
    "MarketValueMembershipPrint",
    "MarketValueMembershipRelease",
]
