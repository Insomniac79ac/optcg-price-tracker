from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PriceObservation(Base):
    __tablename__ = "price_observations"
    __table_args__ = (
        # Backs the latest-price-per-(card, source, price_type) window-
        # function query in app.services.latest_prices - see that module's
        # docstring. Column order matters: (card_id, source_id, price_type)
        # is the partition key, observed_at last so the same index also
        # serves ORDER BY observed_at DESC within each partition.
        Index(
            "ix_price_observations_card_source_type_observed",
            "card_id",
            "source_id",
            "price_type",
            "observed_at",
        ),
        # Backs "latest observation(s) for one source across all cards"
        # queries (e.g. a per-source freshness/staleness sweep) that don't
        # filter by card_id at all.
        Index("ix_price_observations_source_observed", "source_id", "observed_at"),
        # Pins an observation to the exact print, legacy card, and source its
        # source_card_mapping was made against - source_card_mappings.
        # card_print_id/card_id/source_id can each differ per mapping, so a
        # narrower FK couldn't catch a mismatch between the observation's own
        # card_id/source_id and the mapping it claims to use. Composite by
        # design, not independent FKs (see
        # uq_source_card_mappings_lineage_identity).
        ForeignKeyConstraint(
            ["source_card_mapping_id", "card_print_id", "card_id", "source_id"],
            [
                "source_card_mappings.id",
                "source_card_mappings.card_print_id",
                "source_card_mappings.card_id",
                "source_card_mappings.source_id",
            ],
            ondelete="RESTRICT",
            name="fk_price_observations_mapping_print_card_source",
        ),
        # Legacy observations carry neither lineage field; print-linked ones
        # must carry both together, never just one.
        CheckConstraint(
            "(source_card_mapping_id IS NULL AND card_print_id IS NULL) OR "
            "(source_card_mapping_id IS NOT NULL AND card_print_id IS NOT NULL)",
            name="ck_price_observations_lineage_paired",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    price_type: Mapped[str] = mapped_column(String(32), index=True)
    price_jpy: Mapped[int] = mapped_column(Integer)
    condition_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stock_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    listing_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("snkrdunk_candidates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Additive print lineage alongside the legacy card_id/source_id above -
    # nothing reads or writes these yet. Both nullable so every existing
    # observation stays valid as legacy (untagged) lineage; the pair is
    # enforced together by ck_price_observations_lineage_paired and their
    # mutual consistency by fk_price_observations_mapping_print above. No
    # single-column ForeignKey() here - the composite constraint is the only
    # FK tying these two columns to source_card_mappings.
    source_card_mapping_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    card_print_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # Read-only convenience accessor for the composite lineage FK above -
    # viewonly because the pairing is already fully owned by the plain
    # columns plus fk_price_observations_mapping_print_card_source/
    # ck_price_observations_lineage_paired; a writable relationship here
    # would offer a second, redundant way to set the same columns.
    # Not accessed by any existing code path, so this doesn't change current
    # loading or write behaviour, and (being viewonly) can never cascade a
    # delete. foreign_keys is explicit because card_id/source_id each also
    # carry their own single-column ForeignKey to cards/sources, so the join
    # here would otherwise be ambiguous.
    source_card_mapping: Mapped["SourceCardMapping | None"] = relationship(
        "SourceCardMapping",
        primaryjoin=(
            "and_(PriceObservation.source_card_mapping_id == SourceCardMapping.id, "
            "PriceObservation.card_print_id == SourceCardMapping.card_print_id, "
            "PriceObservation.card_id == SourceCardMapping.card_id, "
            "PriceObservation.source_id == SourceCardMapping.source_id)"
        ),
        foreign_keys=(
            "[PriceObservation.source_card_mapping_id, PriceObservation.card_print_id, "
            "PriceObservation.card_id, PriceObservation.source_id]"
        ),
        viewonly=True,
    )
