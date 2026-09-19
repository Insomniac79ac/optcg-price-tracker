"""Durable, collector-inert exact-print mapping proposals.

Candidates describe what a source exposed.  These rows describe what the
current resolver can prove from that evidence.  SourceCardMapping remains the
only collector-facing pricing lineage and is deliberately not created here.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


RESOLUTION_STATUSES = (
    "exact",
    "ambiguous",
    "unresolved_identity",
    "release_unresolved",
    "conflict",
    "stale",
    "superseded",
)
REVIEW_STATUSES = ("pending", "approved", "rejected")
CANDIDATE_TYPES = ("yuyutei_candidate", "snkrdunk_candidate")


class SourceMappingProposalGroup(Base):
    __tablename__ = "source_mapping_proposal_groups"
    __table_args__ = (
        CheckConstraint(
            "resolution_status IN ('exact', 'ambiguous', 'unresolved_identity', "
            "'release_unresolved', 'conflict', 'stale', 'superseded')",
            name="ck_mapping_proposal_groups_resolution_status",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected')",
            name="ck_mapping_proposal_groups_review_status",
        ),
        CheckConstraint(
            "source_candidate_type IN ('yuyutei_candidate', 'snkrdunk_candidate')",
            name="ck_mapping_proposal_groups_candidate_type",
        ),
        CheckConstraint(
            "length(evidence_digest) = 64",
            name="ck_mapping_proposal_groups_digest_length",
        ),
        UniqueConstraint(
            "source_id",
            "canonical_source_listing_identity",
            "resolver_version",
            "evidence_digest",
            name="uq_mapping_proposal_groups_evidence_version",
        ),
        Index(
            "uq_mapping_proposal_groups_current_listing",
            "source_id",
            "canonical_source_listing_identity",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
            sqlite_where=text("superseded_at IS NULL"),
        ),
        Index(
            "ix_mapping_proposal_groups_release_status",
            "release_product_id",
            "resolution_status",
        ),
        Index(
            "ix_mapping_proposal_groups_candidate",
            "source_candidate_type",
            "source_candidate_id",
        ),
        Index(
            "ix_mapping_proposal_groups_result_mapping",
            "resulting_source_card_mapping_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    canonical_source_listing_identity: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_candidate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_candidate_id: Mapped[int] = mapped_column(nullable=False)
    canonical_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("canonical_cards.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    release_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("release_products.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    resolution_status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    review_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending", index=True
    )
    resolver_version: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_summary_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    resolution_reasons_json: Mapped[list] = mapped_column(JSON, nullable=False)
    resulting_source_card_mapping_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_card_mappings.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    alternatives: Mapped[list["SourceMappingProposalAlternative"]] = relationship(
        back_populates="group", cascade="all, delete-orphan", order_by="SourceMappingProposalAlternative.id"
    )


class SourceMappingProposalAlternative(Base):
    __tablename__ = "source_mapping_proposal_alternatives"
    __table_args__ = (
        UniqueConstraint(
            "proposal_group_id",
            "card_print_id",
            name="uq_mapping_proposal_alternatives_group_print",
        ),
        CheckConstraint(
            "review_disposition IN ('pending', 'approved', 'rejected')",
            name="ck_mapping_proposal_alternatives_review_disposition",
        ),
        Index(
            "ix_mapping_proposal_alternatives_print_recommended",
            "card_print_id",
            "recommended",
        ),
        Index("ix_mapping_proposal_alternatives_group", "proposal_group_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_group_id: Mapped[int] = mapped_column(
        ForeignKey("source_mapping_proposal_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    card_print_id: Mapped[int] = mapped_column(
        ForeignKey("card_prints.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    recommended: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    supporting_evidence_json: Mapped[list] = mapped_column(JSON, nullable=False)
    missing_evidence_json: Mapped[list] = mapped_column(JSON, nullable=False)
    conflict_reasons_json: Mapped[list] = mapped_column(JSON, nullable=False)
    review_disposition: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending", index=True
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    group: Mapped[SourceMappingProposalGroup] = relationship(back_populates="alternatives")
