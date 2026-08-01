from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CanonicalCard(Base):
    """A single card identity independent of print/treatment/language - see
    card_print.CardPrint for the individual printings (base, parallel,
    reprints, ...) that share this identity. Additive alongside the existing
    `cards` table (app.models.card.Card); nothing reads or writes this table
    yet."""

    __tablename__ = "canonical_cards"
    # trim(x, ' \t\n\r') is the two-argument form both SQLite and
    # PostgreSQL accept (Postgres aliases it to btrim); plain trim(x) only
    # strips spaces on either engine, so it would let tab/newline-only
    # values slip past a "whitespace-only" check.
    __table_args__ = (
        UniqueConstraint("card_code", name="uq_canonical_cards_card_code"),
        CheckConstraint(
            "trim(original_set_code, ' \t\n\r') <> ''",
            name="ck_canonical_cards_original_set_code_not_blank",
        ),
        CheckConstraint(
            "trim(rarity, ' \t\n\r') <> ''",
            name="ck_canonical_cards_rarity_not_blank",
        ),
        CheckConstraint(
            "trim(card_type, ' \t\n\r') <> ''",
            name="ck_canonical_cards_card_type_not_blank",
        ),
        CheckConstraint(
            "(name_en IS NOT NULL AND trim(name_en, ' \t\n\r') <> '') OR "
            "(name_jp IS NOT NULL AND trim(name_jp, ' \t\n\r') <> '')",
            name="ck_canonical_cards_requires_a_name",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name_jp: Mapped[str | None] = mapped_column(String(255), nullable=True)
    original_set_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    rarity: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    card_type: Mapped[str] = mapped_column(String(64), nullable=False)
    colors: Mapped[list[str] | None] = mapped_column(MutableList.as_mutable(JSON), nullable=True)
    cost: Mapped[int | None] = mapped_column(Integer, nullable=True)
    power: Mapped[int | None] = mapped_column(Integer, nullable=True)
    counter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attribute: Mapped[str | None] = mapped_column(String(64), nullable=True)
    effect_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
