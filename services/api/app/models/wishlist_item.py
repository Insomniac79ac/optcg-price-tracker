from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

WISHLIST_PRIORITIES = ("low", "medium", "high", "grail")
WISHLIST_STATUSES = ("watching", "target_hit", "purchased", "passed", "removed")


class WishlistItem(Base):
    __tablename__ = "wishlist_items"
    __table_args__ = (
        CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'grail')",
            name="ck_wishlist_items_priority",
        ),
        CheckConstraint(
            "status IN ('watching', 'target_hit', 'purchased', 'passed', 'removed')",
            name="ck_wishlist_items_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    priority: Mapped[str] = mapped_column(
        String(16), default="medium", server_default="medium", index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), default="watching", server_default="watching", index=True
    )
    target_buy_price_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_buy_price_jpy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preferred_condition: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preferred_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    desired_quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    acquired_quantity: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    acquired_collection_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_items.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
