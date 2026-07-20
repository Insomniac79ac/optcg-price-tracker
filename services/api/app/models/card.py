from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        UniqueConstraint(
            "card_code", "set_code", "rarity", "variant", "language",
            name="uq_cards_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_code: Mapped[str] = mapped_column(String(64), index=True)
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name_jp: Mapped[str | None] = mapped_column(String(255), nullable=True)
    set_code: Mapped[str] = mapped_column(String(32), index=True)
    rarity: Mapped[str] = mapped_column(String(32), index=True)
    variant: Mapped[str | None] = mapped_column(String(64), nullable=True)
    language: Mapped[str] = mapped_column(String(8), index=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Catalog-enrichment fields (see app.services.card_catalog_import) - all
    # nullable, since the vast majority of existing rows were created before
    # any of this metadata was ever collected.
    release_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    artist: Mapped[str | None] = mapped_column(String(255), nullable=True)
    character: Mapped[str | None] = mapped_column(String(255), nullable=True)
    color: Mapped[str | None] = mapped_column(String(64), nullable=True)
    card_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    power: Mapped[int | None] = mapped_column(Integer, nullable=True)
    counter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attribute: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effect_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Card identity merge (see app.services.card_identity_merge and GET/POST
    # /admin/cards/duplicates|merge*) - is_active=false + merged_into_card_id
    # marks this row as folded into another canonical card. A merged card is
    # NEVER deleted: its price/collection/wishlist/grading/tag/note history
    # stays attached to its own id unless explicitly reassigned by a merge
    # (see that module's execute_card_merge). merged_into_card_id has no
    # ondelete behavior of its own beyond SET NULL, since the target of a
    # merge is itself never deleted either.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)
    merged_into_card_id: Mapped[int | None] = mapped_column(
        ForeignKey("cards.id", ondelete="SET NULL"), nullable=True, index=True
    )
    merged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merge_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
