from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text, UniqueConstraint, func
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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
