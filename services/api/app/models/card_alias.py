from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ALIAS_TYPES = (
    "old_card_code",
    "old_name_en",
    "old_name_jp",
    "source_title",
    "merged_card_code",
)


class CardAlias(Base):
    """A historical identity value for a card - kept so an old card_code/name
    a source listing or a merged-away duplicate used can still be found. See
    app.services.card_identity_merge.execute_card_merge, which populates
    old_name_en/old_name_jp/merged_card_code aliases on the surviving target
    card when a duplicate is merged into it."""

    __tablename__ = "card_aliases"
    __table_args__ = (
        CheckConstraint(
            "alias_type IN ('old_card_code', 'old_name_en', 'old_name_jp', "
            "'source_title', 'merged_card_code')",
            name="ck_card_aliases_alias_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    alias_type: Mapped[str] = mapped_column(String(32), index=True)
    alias_value: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
