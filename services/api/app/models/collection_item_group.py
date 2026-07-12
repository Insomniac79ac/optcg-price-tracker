from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CollectionItemGroup(Base):
    __tablename__ = "collection_item_groups"
    __table_args__ = (
        UniqueConstraint(
            "collection_item_id", "group_id", name="uq_collection_item_groups_item_group"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_item_id: Mapped[int] = mapped_column(
        ForeignKey("collection_items.id", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("collector_groups.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
