from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CollectionItemTag(Base):
    __tablename__ = "collection_item_tags"
    __table_args__ = (
        UniqueConstraint(
            "collection_item_id", "tag_id", name="uq_collection_item_tags_item_tag"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_item_id: Mapped[int] = mapped_column(
        ForeignKey("collection_items.id", ondelete="CASCADE"), index=True
    )
    tag_id: Mapped[int] = mapped_column(
        ForeignKey("collector_tags.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
