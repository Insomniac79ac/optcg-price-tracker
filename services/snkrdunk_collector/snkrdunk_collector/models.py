"""Minimal ORM mappings onto tables owned by services/api/app/models - this
service only reads Card/Source/CardPrint/SourceCardMapping and writes
RawSnapshot/PriceObservation, so only the columns it actually touches are
declared here. Consistent with services/yuyutei_collector/yuyutei_collector/
models.py and services/worker/worker/models.py, which each independently
declare their own minimal subset of the same physical tables rather than
importing app.models directly - each Railway service ships its own
dependency-isolated image.

CardPrint carries image_url/artwork_key/language in addition to what
yuyutei_collector's CardPrint declares - this collector verifies exact
artwork (perceptual hash against the print's own official Bandai
image_url) and page language, neither of which yuyutei_collector needs.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from snkrdunk_collector.db import Base


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_code: Mapped[str] = mapped_column(String(64))
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    base_url: Mapped[str] = mapped_column(String(512))


class CanonicalCard(Base):
    """The print's own canonical identity - the authority for the name and
    set a verified card_print represents. Deliberately preferred over cards.*
    for verification: cards.rarity carries display variants (e.g. "Parallel"
    on the OP01-002 row) rather than the true rarity token a SNKRDUNK title
    shows. Read-only here - services/api/app/models owns these rows.

    `rarity` is the card-LEVEL summary and is nullable by design: the same
    card code is published at different rarities in different products, so
    where the catalogue establishes no single value it stores none. It is the
    fallback for the identity check, not its first authority - see
    CardPrint.official_rarity and writer._authoritative_rarity."""

    __tablename__ = "canonical_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    card_code: Mapped[str] = mapped_column(String(64))
    name_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name_jp: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rarity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    original_set_code: Mapped[str | None] = mapped_column(String(32), nullable=True)


class CardPrint(Base):
    """Read-only lookup - this service never creates or verifies prints
    (see services/api/app/models/card_print.py, which owns that)."""

    __tablename__ = "card_prints"

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_card_id: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(8))
    # Optional at the runtime type layer so a future NULL loads instead of
    # tripping the mapper. The API owns the column and it is still NOT NULL
    # in the database - this mirror emits no DDL.
    treatment: Mapped[str | None] = mapped_column(String(64), nullable=True)
    release_product_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # THE AUTHORITATIVE PRODUCT LINK, and the reason release verification no
    # longer stops at `release_product_code`. Bandai ships products with no
    # code at all (promotional, limited and event products), so a code-keyed
    # check can never cover them; the surrogate id can, and it is already a
    # component of the live exact-print identity. Nullable because an
    # unresolved product must have a safe state - and a verified print with a
    # NULL here fails release verification closed rather than being waved
    # through. See release_identity.py.
    release_product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artwork_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Bandai's published rarity for THIS catalogue entry, and the authority
    # the identity check compares a page's rarity token against. Preferred
    # over canonical_cards.rarity, which is a card-level summary the
    # catalogue may not establish at all (see writer._authoritative_rarity).
    official_rarity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SourceCardMapping(Base):
    __tablename__ = "source_card_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULLABLE, matching the owning model (services/api/app/models/
    # source_card_mapping.py). Every print-authoritative mapping has
    # card_id NULL - the exact-print identity lives in card_print_id - so a
    # non-nullable mirror contradicted every row this collector actually
    # reads. The mirror emits no DDL against the real database; the type is
    # what the mapper and offline tests see.
    card_id: Mapped[int | None] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), nullable=True
    )
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    card_print_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_card_id: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean)
    review_status: Mapped[str] = mapped_column(String(32))
    manual_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # Set after every real collection attempt, whatever the outcome, so the
    # batch scheduler can drain never-collected mappings first and then the
    # stalest. NULL = never attempted. Never written by a validate-only run.
    last_collection_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RawSnapshot(Base):
    __tablename__ = "raw_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    source_url: Mapped[str] = mapped_column(String(1024))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    http_status: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_content: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str | None] = mapped_column(String(32), nullable=True)


class PriceObservation(Base):
    __tablename__ = "price_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_card_mapping_id", "card_print_id", "card_id", "source_id"],
            [
                "source_card_mappings.id",
                "source_card_mappings.card_print_id",
                "source_card_mappings.card_id",
                "source_card_mappings.source_id",
            ],
            ondelete="RESTRICT",
            name="fk_price_observations_mapping_print_card_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    card_id: Mapped[int] = mapped_column(ForeignKey("cards.id", ondelete="CASCADE"))
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    price_type: Mapped[str] = mapped_column(String(32))
    price_jpy: Mapped[int] = mapped_column(Integer)
    condition_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stock_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    listing_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    source_card_mapping_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    card_print_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ReleaseProduct(Base):
    """Read-only mirror of the API-owned `release_products` row.

    THE AUTHORITY FOR WHICH PRODUCT A PRINT BELONGS TO. Before this, the
    collector answered that question from a five-entry hardcoded table keyed
    on `release_product_code`, which meant every uncoded product and every
    product past EB-01 failed release verification closed - 20 of the 30
    mappings in the 2026-08-31 canary. The catalogue already holds the answer;
    this mirror lets the collector read it instead of re-declaring it.

    `official_code` is nullable ON PURPOSE and must never be synthesised: an
    invented code is indistinguishable from a published one once written down.
    Uncoded products are identified by this row's own id.
    """

    __tablename__ = "release_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_catalogue: Mapped[str] = mapped_column(String(16))
    official_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    display_name: Mapped[str] = mapped_column(String(255))
    first_seen_name: Mapped[str] = mapped_column(String(255))
    source_series_id: Mapped[str] = mapped_column(String(16))
    verification_status: Mapped[str] = mapped_column(String(16))


class ReleaseProductAlias(Base):
    """Read-only mirror of `release_product_aliases` - the names a product is
    published or rendered under.

    `alias_kind` separates authorities and must stay separated: a
    `bandai_official` / `bandai_additional` row is a name Bandai publishes,
    while a `source_rendering` row is a storefront's own spelling. A match
    against the latter is still a match, but the audit record has to be able
    to say which one answered - see release_identity.classify_match.
    """

    __tablename__ = "release_product_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    alias_name: Mapped[str] = mapped_column(String(255))
    alias_kind: Mapped[str] = mapped_column(String(32))
