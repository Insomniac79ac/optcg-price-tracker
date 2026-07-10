from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

COLLECTION_ITEM_STATUSES = ("hold", "watch", "sell", "sold", "grading")


class CollectionItem(Base):
    __tablename__ = "collection_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('hold', 'watch', 'sell', 'sold', 'grading')",
            name="ck_collection_items_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    condition_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    purchase_price_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    purchase_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_sell_price_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default="hold", server_default="hold", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
