from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SourceCardMapping(Base):
    __tablename__ = "source_card_mappings"
    __table_args__ = (
        UniqueConstraint("card_id", "source_id", name="uq_source_card_mappings_card_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    source_card_id: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    manual_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
