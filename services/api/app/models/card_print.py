from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

VERIFICATION_STATUSES = ("verified", "unverified", "needs_review")


class CardPrint(Base):
    """One printing of a CanonicalCard, identified by the product it shipped
    in and the official artwork it carries.

    Exact-print identity is
    `(canonical_card_id, language, release_product_id, official_asset_variant)`
    for active, verified prints - see the uq_card_prints_active_verified_identity
    index. `treatment` is deliberately NOT part of it: it is editable Atlas
    descriptive metadata ("normal", "parallel", ...), never a physical
    property Bandai publishes, so a verified print may carry NULL there when
    Atlas has not classified it.

    Two printings can share identical image bytes and still be distinct: the
    identity above turns on product and official asset variant, never on
    `artwork_key`. The 2026-08-22 JP corpus contains 152 rN assets that are
    byte-for-byte identical to a base asset, so this is measured behaviour
    rather than a hypothetical.

    `official_rarity`, `official_block_icon`, `official_name` and
    `official_effect_text` record what Bandai publishes for this exact
    printing. They are descriptive, never identity: they are absent from the
    index above and from the verified check below, so populating or changing
    one can never create, merge or split a print.

    A print starts life `unverified` with its identity fields null. The
    ck_card_prints_verified_requires_fields check is what forces
    release_product_id, official_asset_variant and artwork_key to be filled
    in before it can be marked `verified`. release_product_code is NOT
    required: Bandai ships uncoded limited/promotional products, and those
    prints are legitimate.

    Guessed placeholder values (e.g. 'original', '', 'unknown') are rejected
    by the ck_card_prints_no_fake_* constraints - a print with an unknown
    product, artwork or treatment must stay null there, not fake it."""

    __tablename__ = "card_prints"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('verified', 'unverified', 'needs_review')",
            name="ck_card_prints_verification_status",
        ),
        # What a verified print must be able to prove about itself: which
        # printing it is (product + official artwork, the identity fields
        # below), and the digest of the artwork that was checked. treatment
        # is absent on purpose - it is not identity - and so is
        # release_product_code, because uncoded limited products exist.
        CheckConstraint(
            "verification_status <> 'verified' OR ("
            "canonical_card_id IS NOT NULL AND "
            "language IS NOT NULL AND trim(language, ' \t\n\r') <> '' AND "
            "release_product_id IS NOT NULL AND "
            "official_asset_variant IS NOT NULL AND "
            "artwork_key IS NOT NULL AND "
            # treatment is optional, but on a verified print a placeholder is
            # still not a classification - NULL says "unclassified" honestly.
            # Scoped to verified rows exactly as before: an unverified print
            # may still park 'unknown' here while it is being worked out.
            "(treatment IS NULL OR ("
            "trim(treatment, ' \t\n\r') <> '' AND "
            "lower(trim(treatment, ' \t\n\r')) <> 'unknown'"
            "))"
            ")",
            name="ck_card_prints_verified_requires_fields",
        ),
        CheckConstraint(
            "release_product_code IS NULL OR ("
            "trim(release_product_code, ' \t\n\r') <> '' AND "
            "lower(trim(release_product_code, ' \t\n\r')) <> 'original'"
            ")",
            name="ck_card_prints_no_fake_release_product_code",
        ),
        CheckConstraint(
            "artwork_key IS NULL OR ("
            "trim(artwork_key, ' \t\n\r') <> '' AND "
            "lower(trim(artwork_key, ' \t\n\r')) <> 'original'"
            ")",
            name="ck_card_prints_no_fake_artwork_key",
        ),
        # official_asset_variant is either absent or exactly 'base', 'p<N>'
        # or 'r<N>' with N a positive integer and no leading zero. Expressed
        # with substr/length/trim rather than a regex so one constraint holds
        # on both PostgreSQL and the sqlite the test suite runs on - Postgres'
        # `~` and sqlite's GLOB have no common spelling. trim(x, '0123456789')
        # emptying out is what proves "digits only".
        CheckConstraint(
            "official_asset_variant IS NULL OR "
            "official_asset_variant = 'base' OR ("
            "substr(official_asset_variant, 1, 1) IN ('p', 'r') AND "
            "length(official_asset_variant) >= 2 AND "
            "substr(official_asset_variant, 2, 1) <> '0' AND "
            "trim(substr(official_asset_variant, 2), '0123456789') = ''"
            ")",
            name="ck_card_prints_official_asset_variant_format",
        ),
        # Exact-print identity. Neither treatment (editorial), nor
        # release_product_code (absent for uncoded products), nor artwork_key
        # (evidence, not identity) appears here. The verified check above
        # forbids a NULL in either identity field, so PostgreSQL's
        # multiple-NULLs-are-distinct rule cannot weaken this index.
        Index(
            "uq_card_prints_active_verified_identity",
            "canonical_card_id",
            "language",
            "release_product_id",
            "official_asset_variant",
            unique=True,
            postgresql_where=text("is_active = true AND verification_status = 'verified'"),
            sqlite_where=text("is_active = 1 AND verification_status = 'verified'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_card_id: Mapped[int] = mapped_column(
        ForeignKey("canonical_cards.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    # Editable Atlas descriptive metadata, NOT identity. NULL means Atlas
    # has not classified this printing; no synthetic "other" value exists.
    treatment: Mapped[str | None] = mapped_column(String(64), nullable=True)
    release_product_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Dormant lineage FK to the first-class product entity (release_products).
    # Nullable on purpose: a print whose product is unknown or not yet
    # resolved must have a safe state, and the backfill leaves an unexpected
    # release_product_code NULL here rather than guessing a product.
    # release_product_code above is NOT replaced by this - it stays the join
    # key the SNKRDUNK collector's RELEASE_REFERENCES uses today.
    release_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("release_products.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    artwork_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Which official Bandai asset this print carries - 'base' for CODE.png,
    # 'pN' for CODE_pN.png, 'rN' for CODE_rN.png - parsed from the official
    # asset address only (see app.services.official_asset_variant).
    #
    # Named "asset", not "artwork", on purpose: the suffix identifies the
    # official asset, and does NOT promise the artwork differs. 152 rN assets
    # in the 2026-08-22 JP corpus are byte-identical to a base asset.
    #
    # It says nothing about parallel/manga/special/alt-art/rarity, and
    # treatment must never be inferred from it.
    #
    # Identity-bearing evidence: the asset component of the live exact-print
    # key (canonical_card_id, language, release_product_id,
    # official_asset_variant). artwork_key stays the SHA-256 evidence anchor
    # and is deliberately NOT identity - two prints may share it.
    #
    # Nullable because an unresolved or future asset must have a safe state:
    # no image, a non-Card-List address, or a basename that does not name
    # this print's own card all leave it NULL rather than guessed.
    official_asset_variant: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # --- print-specific official metadata -------------------------------
    #
    # The value Bandai publishes for THIS exact printing/occurrence, stored
    # verbatim. Four fields, and only four, because the complete JP corpus of
    # 2026-08-22 (4,962 occurrences, 2,823 card codes) is what decided the
    # boundary: rarity varies materially across 122 card codes, the block icon
    # across 17, effect text across 30, and the card name across exactly 1.
    # color, cost, counter, attribute, feature, category and power do not vary
    # at all in that corpus, so they stay on CanonicalCard - a print-level
    # column for an invariant field would be a column that can only ever
    # repeat what the canonical row already says.
    #
    # These are NOT identity. None of them appears in
    # uq_card_prints_active_verified_identity, none feeds treatment, none
    # feeds source-mapping identity, and none feeds pricing. Two prints may
    # carry identical metadata and stay distinct printings; one print may
    # carry metadata that disagrees with its CanonicalCard and still be the
    # same printing.
    #
    # NULL means Atlas has not yet populated authoritative print-specific
    # metadata for this row. It never means "same as the canonical card", and
    # no fallback value is ever synthesised - a guessed rarity is
    # indistinguishable from a published one once it is written down.
    #
    # Deliberately the published value, not a diff against CanonicalCard: the
    # question these answer is "what does Bandai publish for this exact
    # printing?", and a column that only records differences cannot answer it
    # without a join and a convention about what NULL means.
    #
    # Comparing them against CanonicalCard is meaningful only where the
    # canonical column represents the same language as this print's
    # `language`. name_jp and name_en are language-tagged, so official_name
    # can be held against the matching one; CanonicalCard.effect_text carries
    # no language tag at all and today holds English while the JP Card List
    # publishes Japanese, so comparing those two would classify a translation
    # as a data conflict. Such a pair is `language_not_comparable`, never a
    # formatting or material difference - see
    # print_import_planner.compare_metadata_to_canonical. Comparing two values
    # from the same source and language (a stored official_* against the
    # catalogue occurrence it came from) is unaffected by this.

    # Bandai's rarity for this occurrence. String(32) to match
    # CanonicalCard.rarity, whose vocabulary this shares: the corpus publishes
    # 10 values, the longest being 'SPカード'. Rarity is the most variable of
    # the four because Bandai republishes a card into a later set under that
    # set's rarity.
    official_rarity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Bandai's ブロック アイコン for this occurrence, kept as TEXT and not as an
    # integer on purpose. The corpus publishes '1'-'5' *and* 'X' (27
    # occurrences), so the source vocabulary is textual; storing it as a
    # number would have to invent a meaning for 'X' or drop those rows.
    official_block_icon: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # Bandai's card name for this occurrence, verbatim. Not `official_name_jp`
    # and never paired with an `official_name_en`: this row already carries
    # `language`, so the language of the value is a property of the print, not
    # something the column name has to encode. A JP print holds
    # 'モンキー・D・ルフィ' here and an EN print holds 'Monkey.D.Luffy', both in
    # this one column. String(255) matches the canonical name columns; the
    # longest name in the corpus is 32 characters.
    #
    # Verbatim includes Bandai's mistakes. EB01-056 is published as
    # 'シャーロット・フランぺ' in EB-01 and 'シャーロット・フランペ' in OP-10 - a
    # hiragana ぺ where every other occurrence has katakana ペ. That is the one
    # material name difference in the whole corpus, and it is preserved rather
    # than corrected: Atlas records what the source says, and a silent fix
    # would destroy the evidence that the source is inconsistent.
    official_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Bandai's effect text for this occurrence, verbatim. Text rather than a
    # bounded String, matching CanonicalCard.effect_text.
    #
    # Most differences here are formatting rather than substance: 103 of the
    # 133 card codes whose text varies differ only in characters NFKC folds
    # together - 'ドン‼' against 'ドン!!' being the common one - while 30 differ
    # materially, such as OP05-074, where one occurrence spells out the
    # 【ブロッカー】 reminder text and another omits it. The raw value is stored
    # either way; the formatting/material distinction is a question asked at
    # comparison time (see app.services.official_snapshot.classify_field), not
    # a normalisation baked into the column.
    official_effect_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    artist: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unverified", server_default="unverified"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Reverse side of SourceCardMapping.card_print - not eagerly loaded and
    # not accessed by any existing code path. No delete cascade: deleting a
    # CardPrint with mappings attached is rejected outright by the
    # ON DELETE RESTRICT on source_card_mappings.card_print_id.
    source_card_mappings: Mapped[list["SourceCardMapping"]] = relationship(
        "SourceCardMapping",
        back_populates="card_print",
        foreign_keys="SourceCardMapping.card_print_id",
    )
