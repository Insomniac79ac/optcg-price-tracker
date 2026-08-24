from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CanonicalCard(Base):
    """A single card identity independent of print/treatment/language - see
    card_print.CardPrint for the individual printings (base, parallel,
    reprints, ...) that share this identity. Additive alongside the existing
    `cards` table (app.models.card.Card).

    What is identity here is card_code; `rarity` deliberately is not - see the
    column's own note."""

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
    # THE SET THIS CARD IS FROM, or NULL when it is from none.
    #
    # Read straight out of the card code, which encodes the family and the set
    # number. Bandai's families in the complete 2026-08-22 JP corpus:
    #
    #     ST-*   Starter Deck      ST01-001  -> ST-01
    #     EB-*   Extra Booster     EB01-012  -> EB-01
    #     PRB-*  Premium Booster   PRB01-001 -> PRB-01
    #     OP-*   Booster Pack      OP01-001  -> OP-01
    #     P-*    PROMO             P-014     -> NULL
    #
    # A promo carries no set number because a promo has no set. It is
    # DISTRIBUTED inside other products - P-014 in PRB-01, P-084 in OP-17 and
    # ST-25 - but a distribution product is where a printing appeared, not the
    # card's original set. That question is already answered exactly, per
    # printing, by card_prints.release_product_id.
    #
    # NULL is therefore the truthful value, never a stand-in for one. It is
    # never filled from a ReleaseProduct, from PRB/ST/EB membership, from the
    # first or first-fetched occurrence, from source_series_id, from
    # lexicographic order or from creation time; and 'P', 'PROMO' and 'PR' are
    # inventions, not readings. See migration d1c48b7f36ae.
    #
    # The blank-guard CHECK above still applies: NULL is allowed, '' is not.
    original_set_code: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    # OPTIONAL SUMMARY METADATA, NOT AUTHORITATIVE FOR A PRINTING.
    #
    # Bandai publishes rarity per catalogue ENTRY, not per card: the same card
    # code appears at different rarities in different products (OP02-013 is
    # 'SR' in OP-02 and 'SPカード' in its OP-08 reprint). The authoritative
    # value for one exact physical printing is CardPrint.official_rarity, and
    # every print carries its own.
    #
    # This column is what the card's own set published, where the catalogue
    # settles that. NULL where it does not - 49 card codes in the complete
    # 2026-08-22 JP corpus have no single card-level answer (31 appear only as
    # reprints, 18 disagree across occurrences of their own set). NULL is the
    # truthful reading and is never replaced by 'Unknown', '-' or a
    # most-common guess; see migration c7e91a4d2b60.
    #
    # It is not identity-bearing, it is not required to create a canonical
    # card, and it is not an import eligibility requirement. The blank-guard
    # CHECK above still applies: NULL is allowed, '' and '   ' are not.
    rarity: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
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
