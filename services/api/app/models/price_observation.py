from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

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
