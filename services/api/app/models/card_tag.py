from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CardTag(Base):
    __tablename__ = "card_tags"
    __table_args__ = (
        UniqueConstraint("card_id", "tag_id", name="uq_card_tags_card_tag"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), index=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("collector_tags.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
