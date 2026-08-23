"""Print-specific official metadata: the four fields, and what they refuse to be.

`official_rarity`, `official_block_icon`, `official_name` and
`official_effect_text` record what Bandai publishes for one exact
printing/occurrence. Two things are load-bearing here and are tested directly
rather than implied:

  * **They are not identity.** They are absent from
    uq_card_prints_active_verified_identity and from the verified CHECK, so a
    metadata difference can never create, merge or split a print. The planner
    test at the bottom of this file is the one that matters: a catalogue that
    disagrees with Atlas on rarity still resolves to `no_change`.
  * **Comparison against CanonicalCard is language-gated.** Only the
    canonical name columns are language-tagged, so only the name can be held
    against them; effect text, rarity and block icon are
    `language_not_comparable`, never a difference. Comparing a stored print
    value against the catalogue occurrence it came from is same-language by
    construction and is unaffected.
  * **They are verbatim.** Bandai's own inconsistencies - a hiragana ぺ where
    every sibling has katakana ペ, a 'ドン‼' where a sibling writes 'ドン!!' -
    survive storage unchanged. The formatting/material distinction is a
    question asked at comparison time, never a normalisation applied on the
    way in.

Hermetic: in-memory sqlite, entries constructed here. Nothing reaches the
network, a real database, or the local snapshot.
"""

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.models import CanonicalCard, CardPrint, ReleaseProduct
from app.services.official_cardlist import OfficialCardEntry, RawField
from app.services.official_snapshot import normalize_for_comparison
from app.services.print_import_planner import (
    CREATE_CARD_PRINT,
    FLAG_METADATA_DIFFERS,
    FLAG_METADATA_MISSING,
    FLAG_RARITY_DIFFERS_BY_PRINTING,
    METADATA_DIFFERS,
    METADATA_EXACT_MATCH,
    METADATA_FIELDS,
    METADATA_FORMATTING_ONLY,
    METADATA_MATCHES,
    METADATA_LANGUAGE_NOT_COMPARABLE,
    METADATA_MATERIAL,
    METADATA_MISSING,
    METADATA_NOT_COMPARABLE,
    METADATA_NOT_POPULATED,
    OUTCOME_NO_CHANGE,
    OfficialMetadata,
    PrintImportPlanner,
    compare_metadata,
    compare_metadata_to_canonical,
)

CARDLIST = "https://www.onepiece-cardgame.com/images/cardlist/card"
DIGEST = "a" * 64

# --- values taken verbatim from the 2026-08-22 JP corpus ---------------------
#
# EB01-056 is the single material card-name difference in the whole corpus:
# EB-01 publishes a hiragana ぺ, OP-10 a katakana ペ. NFKC does not fold the
# two, which is exactly why it classifies as material rather than formatting.
NAME_TYPO = "シャーロット・フランぺ"      # as published in EB-01 - hiragana ぺ
NAME_CORRECT = "シャーロット・フランペ"   # as published in OP-10 - katakana ペ

# The common formatting-only effect difference: U+203C against two ASCII
# exclamation marks, which NFKC folds together.
EFFECT_DOUBLE_EXCL = "【ドン‼×2】【アタック時】相手のキャラ1枚までを、このターン中、パワー-3000。"
EFFECT_ASCII_EXCL = "【ドン!!×2】【アタック時】相手のキャラ1枚までを、このターン中、パワー-3000。"

# The OP05-074 shape: one occurrence spells out the 【ブロッカー】 reminder text
# and another omits it. Different words, not different glyphs.
EFFECT_WITH_REMINDER = "【ブロッカー】(相手のアタックの後、このカードをレストにし、アタックの対象をこのカードにできる)"
EFFECT_WITHOUT_REMINDER = "【ブロッカー】"


def entry(
    *,
    entry_id="OP01-001",
    card_code="OP01-001",
    image=f"{CARDLIST}/OP01-001.png?260821",
    name="ロロノア・ゾロ",
    rarity="L",
    category="LEADER",
    block="1",
    text=EFFECT_ASCII_EXCL,
    products=("ROMANCE DAWN【OP-01】",),
) -> OfficialCardEntry:
    """One catalogue occurrence, with the two published blocks that matter."""
    fields = []
    if block is not None:
        fields.append(RawField(name="block", label="ブロック アイコン", value=block))
    if text is not None:
        fields.append(RawField(name="text", label="テキスト", value=text))
    return OfficialCardEntry(
        entry_id=entry_id,
        card_code=card_code,
        rarity=rarity,
        category=category,
        card_name=name,
        image_url=image,
        product_names=products,
        fields=tuple(fields),
    )


@pytest.fixture()
def op01(db_session) -> ReleaseProduct:
    product = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code="OP-01",
        display_name="ブースターパック ROMANCE DAWN【OP-01】",
        first_seen_name="ブースターパック ROMANCE DAWN【OP-01】",
        source_series_id="550101",
        source_url="https://www.onepiece-cardgame.com/products/boosters/op01.php",
        verification_status="verified",
    )
    db_session.add(product)
    db_session.commit()
    return product


@pytest.fixture()
def zoro(db_session) -> CanonicalCard:
    card = CanonicalCard(
        card_code="OP01-001",
        name_jp="ロロノア・ゾロ",
        name_en="Roronoa Zoro",
        original_set_code="OP-01",
        rarity="L",
        card_type="Leader",
        effect_text="canonical effect text, deliberately unlike any occurrence",
    )
    db_session.add(card)
    db_session.commit()
    return card


def make_print(db_session, card, product, variant="base", **overrides) -> CardPrint:
    fields = dict(
        canonical_card_id=card.id,
        language="jp",
        treatment="normal",
        release_product_code="OP-01",
        release_product_id=product.id,
        artwork_key=DIGEST,
        official_asset_variant=variant,
        image_url=f"{CARDLIST}/OP01-001.png",
        verification_status="verified",
        is_active=True,
    )
    fields.update(overrides)
    row = CardPrint(**fields)
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def plan_one(session, the_entry, *, digests=None):
    planner = PrintImportPlanner(
        session, digest_provider=(digests or {}).get if digests is not None else None
    )
    return planner.plan_entry(the_entry)


# --- 1. the columns themselves ----------------------------------------------


def test_all_four_fields_are_nullable(db_session, zoro, op01):
    """The migration is additive: every row that predates it carries NULL, and
    a verified print must still be insertable without any of them."""
    row = make_print(db_session, zoro, op01)

    for name in METADATA_FIELDS:
        assert getattr(row, name) is None
    assert row.verification_status == "verified"


@pytest.mark.parametrize("name", METADATA_FIELDS)
def test_each_field_is_nullable_in_the_real_schema(name):
    column = CardPrint.__table__.columns[name]
    assert column.nullable is True
    # No server_default either: a default would write a value nobody published.
    assert column.server_default is None


def test_a_verified_print_does_not_require_the_metadata(db_session, zoro, op01):
    """Deliberately NOT part of ck_card_prints_verified_requires_fields yet.

    Every verified row on staging predates these columns; requiring them now
    would make the check unsatisfiable for data that is already correct.
    """
    row = make_print(db_session, zoro, op01, official_rarity=None)

    assert row.verification_status == "verified"
    assert row.official_rarity is None


def test_the_metadata_is_absent_from_the_exact_print_identity():
    index = next(
        i for i in CardPrint.__table__.indexes
        if i.name == "uq_card_prints_active_verified_identity"
    )
    identity = {c.name for c in index.columns}

    assert identity == {
        "canonical_card_id", "language", "release_product_id", "official_asset_variant",
    }
    assert identity.isdisjoint(METADATA_FIELDS)


def test_the_metadata_is_absent_from_the_verified_check():
    check = next(
        c for c in CardPrint.__table__.constraints
        if getattr(c, "name", None) == "ck_card_prints_verified_requires_fields"
    )
    text = str(check.sqltext)

    for name in METADATA_FIELDS:
        assert name not in text


def test_two_prints_may_carry_identical_metadata_and_stay_distinct(db_session, zoro, op01):
    """Metadata equality is not identity equality. base and p1 of one product
    publish the same rarity and text and remain two printings."""
    shared = dict(
        official_rarity="L", official_block_icon="1",
        official_name="ロロノア・ゾロ", official_effect_text=EFFECT_ASCII_EXCL,
    )
    base = make_print(db_session, zoro, op01, "base", artwork_key="a" * 64, **shared)
    p1 = make_print(db_session, zoro, op01, "p1", artwork_key="b" * 64, **shared)

    assert base.id != p1.id
    assert base.official_rarity == p1.official_rarity == "L"


def test_metadata_disagreeing_with_the_canonical_card_is_storable(db_session, zoro, op01):
    """A printing republished under another set's rarity is still that
    printing. The row records 'SPカード' while CanonicalCard says 'L', and
    nothing rejects it."""
    row = make_print(db_session, zoro, op01, official_rarity="SPカード")

    assert zoro.rarity == "L"
    assert row.official_rarity == "SPカード"


# --- 2. verbatim storage ------------------------------------------------------


def test_japanese_text_round_trips_unchanged(db_session, zoro, op01):
    row = make_print(
        db_session, zoro, op01,
        official_rarity="SPカード",
        official_name="ロロノア・ゾロ",
        official_effect_text=EFFECT_WITH_REMINDER,
    )
    db_session.expire_all()
    reloaded = db_session.get(CardPrint, row.id)

    assert reloaded.official_rarity == "SPカード"
    assert reloaded.official_name == "ロロノア・ゾロ"
    assert reloaded.official_effect_text == EFFECT_WITH_REMINDER


def test_a_bandai_typo_is_preserved_exactly(db_session, zoro, op01):
    """EB01-056's hiragana ぺ. Atlas records what the source says; correcting
    it would destroy the evidence that the source is inconsistent."""
    row = make_print(db_session, zoro, op01, official_name=NAME_TYPO)
    db_session.expire_all()
    reloaded = db_session.get(CardPrint, row.id)

    assert reloaded.official_name == NAME_TYPO
    assert reloaded.official_name != NAME_CORRECT
    # The two differ in exactly one character, and it is not a fold NFKC does.
    assert normalize_for_comparison(NAME_TYPO) != normalize_for_comparison(NAME_CORRECT)


def test_the_double_exclamation_glyph_is_stored_as_published(db_session, zoro, op01):
    """'ドン‼' is U+203C. It is stored as U+203C, not silently expanded - the
    fold happens only when a difference is being classified."""
    row = make_print(db_session, zoro, op01, official_effect_text=EFFECT_DOUBLE_EXCL)
    db_session.expire_all()

    stored = db_session.get(CardPrint, row.id).official_effect_text
    assert "‼" in stored
    assert stored == EFFECT_DOUBLE_EXCL
    assert stored != EFFECT_ASCII_EXCL


def test_the_block_icon_keeps_bandais_textual_vocabulary(db_session, zoro, op01):
    """The corpus publishes '1'-'5' and also 'X'. The column is text, so 'X'
    survives instead of forcing an invented numeric meaning."""
    for value in ("1", "2", "3", "4", "5", "X"):
        row = make_print(
            db_session, zoro, op01, variant=f"p{ord(value) % 90 + 1}",
            artwork_key=value * 64, official_block_icon=value,
        )
        assert row.official_block_icon == value


# --- 3. the comparison rule ---------------------------------------------------


def _meta(**overrides) -> OfficialMetadata:
    fields = dict(
        official_rarity="L", official_block_icon="1",
        official_name="ロロノア・ゾロ", official_effect_text=EFFECT_ASCII_EXCL,
    )
    fields.update(overrides)
    return OfficialMetadata(**fields)


def test_identical_metadata_compares_as_an_exact_match():
    result = compare_metadata(_meta(), _meta())

    assert result.status == METADATA_MATCHES
    assert set(result.fields.values()) == {METADATA_EXACT_MATCH}
    assert result.differences == ()


def test_a_formatting_only_effect_difference_is_classified_as_such():
    """The 103-card-code case: 'ドン‼' against 'ドン!!'."""
    result = compare_metadata(
        _meta(official_effect_text=EFFECT_DOUBLE_EXCL),
        _meta(official_effect_text=EFFECT_ASCII_EXCL),
    )

    assert result.fields["official_effect_text"] == METADATA_FORMATTING_ONLY
    assert result.status == METADATA_DIFFERS
    assert result.formatting_only_fields == ("official_effect_text",)
    assert result.material_fields == ()


def test_a_material_effect_difference_is_classified_as_such():
    """The 30-card-code case: OP05-074, where one occurrence carries the
    【ブロッカー】 reminder text and another does not."""
    result = compare_metadata(
        _meta(official_effect_text=EFFECT_WITHOUT_REMINDER),
        _meta(official_effect_text=EFFECT_WITH_REMINDER),
    )

    assert result.fields["official_effect_text"] == METADATA_MATERIAL
    assert result.material_fields == ("official_effect_text",)


def test_the_material_name_difference_is_not_folded_away():
    result = compare_metadata(
        _meta(official_name=NAME_TYPO), _meta(official_name=NAME_CORRECT)
    )

    assert result.fields["official_name"] == METADATA_MATERIAL


def test_a_null_field_reports_missing_rather_than_differing():
    """NULL is not a disagreement. Reporting one would claim Atlas holds a
    value that contradicts the catalogue, when Atlas holds nothing."""
    result = compare_metadata(_meta(official_rarity=None), _meta(official_rarity="SPカード"))

    assert result.fields["official_rarity"] == METADATA_NOT_POPULATED
    assert result.status == METADATA_MISSING
    # Missing wins over differing even when another field genuinely differs.
    mixed = compare_metadata(
        _meta(official_rarity=None, official_block_icon="1"),
        _meta(official_rarity="SPカード", official_block_icon="X"),
    )
    assert mixed.status == METADATA_MISSING
    assert mixed.fields["official_block_icon"] == METADATA_MATERIAL


# --- 3b. the cross-language rule ----------------------------------------------
#
# CanonicalCard is Atlas's normalised, language-independent identity, and only
# its name columns are language-tagged. Comparing a Japanese published value
# against an untagged canonical column would report a translation as a data
# conflict, so those pairs are `language_not_comparable` instead.


def test_effect_text_is_not_comparable_against_the_canonical_card(zoro):
    """The correction this rule exists for. CanonicalCard.effect_text carries
    no language tag and today holds English; the JP catalogue publishes
    Japanese. That pair is two languages, not a material difference."""
    result = compare_metadata_to_canonical(_meta(), zoro, "jp")

    assert result.fields["official_effect_text"] == METADATA_LANGUAGE_NOT_COMPARABLE
    assert "official_effect_text" not in result.material_fields
    assert "official_effect_text" not in result.formatting_only_fields
    # And no difference is reported for it either.
    assert not any("official_effect_text" in d for d in result.differences)


def test_rarity_and_block_icon_have_no_language_matched_counterpart(zoro):
    """CanonicalCard.rarity is one vocabulary shared across languages - the JP
    catalogue publishes 'SPカード' where the canonical row records 'SP' - and
    there is no canonical block-icon column at all."""
    result = compare_metadata_to_canonical(_meta(official_rarity="SPカード"), zoro, "jp")

    assert result.fields["official_rarity"] == METADATA_LANGUAGE_NOT_COMPARABLE
    assert result.fields["official_block_icon"] == METADATA_LANGUAGE_NOT_COMPARABLE
    assert result.material_fields == ()


def test_the_name_is_compared_against_the_column_for_this_language(zoro):
    """name_jp and name_en are language-tagged, so the name is the one field
    a JP print can be held against - and EB01-056's ぺ is a real JP-against-JP
    disagreement, which still classifies as material."""
    assert zoro.name_jp == "ロロノア・ゾロ"
    matching = compare_metadata_to_canonical(_meta(), zoro, "jp")
    assert matching.fields["official_name"] == METADATA_EXACT_MATCH
    assert matching.status == METADATA_MATCHES

    differing = compare_metadata_to_canonical(_meta(official_name=NAME_TYPO), zoro, "jp")
    assert differing.fields["official_name"] == METADATA_MATERIAL
    assert differing.status == METADATA_DIFFERS


def test_an_english_print_is_held_against_name_en(zoro):
    """One column, two languages. `language` on the print decides which
    canonical name the published name is compared against, which is the whole
    reason the column is `official_name` and not `official_name_jp`."""
    english = _meta(official_name="Roronoa Zoro")

    assert (zoro.name_en, zoro.name_jp) == ("Roronoa Zoro", "ロロノア・ゾロ")
    assert compare_metadata_to_canonical(english, zoro, "en").fields[
        "official_name"
    ] == METADATA_EXACT_MATCH
    # The same published value read as a JP print is held against name_jp
    # instead - the column chosen follows the print's language, not the
    # apparent language of the value.
    assert compare_metadata_to_canonical(english, zoro, "jp").fields[
        "official_name"
    ] == METADATA_MATERIAL


def test_a_language_with_no_canonical_name_column_compares_nothing(zoro):
    result = compare_metadata_to_canonical(_meta(), zoro, "fr")

    assert set(result.fields.values()) == {METADATA_LANGUAGE_NOT_COMPARABLE}
    assert result.status == METADATA_NOT_COMPARABLE
    assert result.differences == ()


def test_a_missing_canonical_name_reports_missing_not_differing(db_session):
    """A NULL canonical name is a value Atlas has not written, not a
    disagreement with the catalogue."""
    nameless = CanonicalCard(
        card_code="OP01-999", name_en="Placeholder", name_jp=None,
        original_set_code="OP-01", rarity="L", card_type="Leader",
    )
    db_session.add(nameless)
    db_session.commit()

    result = compare_metadata_to_canonical(_meta(), nameless, "jp")

    assert result.fields["official_name"] == METADATA_NOT_POPULATED
    assert result.status == METADATA_MISSING


def test_the_print_against_catalogue_comparison_is_unaffected(zoro):
    """Same source, same language, so every field stays comparable. The
    language rule governs CanonicalCard comparisons only."""
    result = compare_metadata(
        _meta(official_effect_text=EFFECT_WITHOUT_REMINDER),
        _meta(official_effect_text=EFFECT_WITH_REMINDER),
    )

    assert result.not_comparable_fields == ()
    assert result.fields["official_effect_text"] == METADATA_MATERIAL
    assert METADATA_LANGUAGE_NOT_COMPARABLE not in result.fields.values()


# --- 4. the planner carries the occurrence, not the canonical card ------------


def test_the_planner_carries_the_occurrence_values(db_session, zoro, op01):
    planned = plan_one(
        db_session,
        entry(rarity="SPカード", block="X", name=NAME_TYPO, text=EFFECT_WITH_REMINDER),
        digests={f"{CARDLIST}/OP01-001.png?260821": DIGEST},
    )

    assert planned.official_rarity == "SPカード"
    assert planned.official_block_icon == "X"
    assert planned.official_name == NAME_TYPO
    assert planned.official_effect_text == EFFECT_WITH_REMINDER


def test_the_planner_does_not_read_the_canonical_card_for_metadata(db_session, zoro, op01):
    """CanonicalCard says rarity 'L' and a quite different effect text. The
    plan must report Bandai's occurrence values, not Atlas's normalisation."""
    planned = plan_one(
        db_session,
        entry(rarity="SPカード", text=EFFECT_WITH_REMINDER),
        digests={f"{CARDLIST}/OP01-001.png?260821": DIGEST},
    )

    assert zoro.rarity == "L"
    assert planned.official_rarity == "SPカード"
    assert zoro.effect_text not in (planned.official_effect_text or "")


def test_the_plan_name_and_the_plan_card_name_are_the_same_occurrence_value(db_session, zoro, op01):
    """`official_card_name` predates these columns and `official_name` is
    the column-destined spelling of the same value. They cannot drift."""
    planned = plan_one(db_session, entry(name=NAME_TYPO))

    assert planned.official_name == planned.official_card_name == NAME_TYPO


def test_an_absent_block_leaves_the_field_null_rather_than_guessed(db_session, zoro, op01):
    planned = plan_one(db_session, entry(block=None, text=None))

    assert planned.official_block_icon is None
    assert planned.official_effect_text is None
    # And the ones the entry does publish are still read.
    assert planned.official_rarity == "L"


def test_an_empty_published_value_is_null_not_an_empty_string(db_session, zoro, op01):
    planned = plan_one(db_session, entry(block="", text=""))

    assert planned.official_block_icon is None
    assert planned.official_effect_text is None


def test_a_dash_is_a_published_value_and_is_kept(db_session, zoro, op01):
    """'-' is what Bandai publishes for "none" and is not the same evidence as
    an absent block."""
    planned = plan_one(db_session, entry(block="-"))

    assert planned.official_block_icon == "-"


# --- 5. metadata never proposes a print --------------------------------------


def test_a_metadata_difference_does_not_create_a_duplicate_print(db_session, zoro, op01):
    """The assertion this whole tranche turns on."""
    existing = make_print(
        db_session, zoro, op01,
        official_rarity="L", official_block_icon="1",
        official_name="ロロノア・ゾロ", official_effect_text=EFFECT_ASCII_EXCL,
    )

    # The difference is in block icon and effect text, which Atlas holds on
    # the print only. Rarity and name are left matching on purpose: those two
    # are also compared against CanonicalCard by a rule that predates this
    # tranche, and the point here is what *metadata* alone does.
    planned = plan_one(
        db_session,
        entry(block="X", text=EFFECT_WITH_REMINDER),
        digests={f"{CARDLIST}/OP01-001.png?260821": DIGEST},
    )

    assert planned.outcome == OUTCOME_NO_CHANGE
    assert planned.creations == ()
    assert CREATE_CARD_PRINT not in planned.creations
    assert planned.existing_card_print_id == existing.id
    assert planned.metadata_status == METADATA_DIFFERS
    assert FLAG_METADATA_DIFFERS in planned.flags
    assert set(planned.metadata_comparison.material_fields) == {
        "official_block_icon", "official_effect_text",
    }


def test_matching_metadata_reports_a_match_and_still_no_change(db_session, zoro, op01):
    make_print(
        db_session, zoro, op01,
        official_rarity="L", official_block_icon="1",
        official_name="ロロノア・ゾロ", official_effect_text=EFFECT_ASCII_EXCL,
    )

    planned = plan_one(
        db_session, entry(), digests={f"{CARDLIST}/OP01-001.png?260821": DIGEST}
    )

    assert planned.outcome == OUTCOME_NO_CHANGE
    assert planned.metadata_status == METADATA_MATCHES
    assert FLAG_METADATA_DIFFERS not in planned.flags
    assert FLAG_METADATA_MISSING not in planned.flags


def test_an_unpopulated_existing_print_reports_missing_metadata(db_session, zoro, op01):
    """What every one of the 20 prints on staging reports today."""
    make_print(db_session, zoro, op01)

    planned = plan_one(
        db_session, entry(), digests={f"{CARDLIST}/OP01-001.png?260821": DIGEST}
    )

    assert planned.outcome == OUTCOME_NO_CHANGE
    assert planned.metadata_status == METADATA_MISSING
    assert FLAG_METADATA_MISSING in planned.flags
    assert set(planned.metadata_comparison.fields.values()) == {METADATA_NOT_POPULATED}


def test_a_formatting_only_difference_also_stays_no_change(db_session, zoro, op01):
    make_print(
        db_session, zoro, op01,
        official_rarity="L", official_block_icon="1",
        official_name="ロロノア・ゾロ", official_effect_text=EFFECT_DOUBLE_EXCL,
    )

    planned = plan_one(
        db_session, entry(text=EFFECT_ASCII_EXCL),
        digests={f"{CARDLIST}/OP01-001.png?260821": DIGEST},
    )

    assert planned.outcome == OUTCOME_NO_CHANGE
    assert planned.creations == ()
    assert planned.metadata_comparison.formatting_only_fields == ("official_effect_text",)


def test_a_proposed_print_has_no_metadata_comparison(db_session, zoro, op01):
    """Nothing to compare against. Reporting 'matches' or 'differs' for a
    print that does not exist would invent a comparison."""
    planned = plan_one(
        db_session, entry(), digests={f"{CARDLIST}/OP01-001.png?260821": DIGEST}
    )

    assert planned.existing_card_print_id is None
    assert planned.metadata_comparison is None
    assert planned.metadata_status is None
    # The published values are carried regardless - they are what a write
    # step would store.
    assert planned.official_rarity == "L"


def test_the_metadata_flags_are_not_blocking(db_session, zoro, op01):
    """They are surfaced, not acted on. A differing print keeps the
    verification status Atlas already holds."""
    make_print(db_session, zoro, op01, official_rarity="L", official_block_icon="1",
               official_name="ロロノア・ゾロ", official_effect_text=EFFECT_ASCII_EXCL)

    planned = plan_one(
        db_session, entry(block="X"),
        digests={f"{CARDLIST}/OP01-001.png?260821": DIGEST},
    )

    assert planned.metadata_status == METADATA_DIFFERS
    assert planned.verification_status == "verified"
    assert planned.outcome == OUTCOME_NO_CHANGE


def test_a_reprint_rarity_difference_is_metadata_and_still_no_change(db_session, zoro):
    """The real 122-card-code shape, and the one place rarity is safe to vary.

    Bandai republishes OP01-001 into a later set under that set's rarity. The
    print lives under the *reprint* product, so the canonical-card rule
    treats the difference as a note about the printing rather than a
    contradiction - and the metadata comparison records it without proposing
    a second print.
    """
    reprint = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code="OP-08",
        display_name="ブースターパック 二つの伝説【OP-08】",
        first_seen_name="ブースターパック 二つの伝説【OP-08】",
        source_series_id="550108",
        source_url="https://www.onepiece-cardgame.com/products/boosters/op08.php",
        verification_status="verified",
    )
    db_session.add(reprint)
    db_session.commit()
    existing = make_print(
        db_session, zoro, reprint, "p3",
        release_product_code="OP-08", official_rarity="L",
        official_block_icon="1", official_name="ロロノア・ゾロ",
        official_effect_text=EFFECT_ASCII_EXCL,
    )

    planned = plan_one(
        db_session,
        entry(
            entry_id="OP01-001_p3", rarity="SPカード",
            image=f"{CARDLIST}/OP01-001_p3.png?260821",
            products=("ブースターパック 二つの伝説【OP-08】",),
        ),
        digests={f"{CARDLIST}/OP01-001_p3.png?260821": DIGEST},
    )

    assert FLAG_RARITY_DIFFERS_BY_PRINTING in planned.flags
    assert planned.outcome == OUTCOME_NO_CHANGE
    assert planned.creations == ()
    assert planned.existing_card_print_id == existing.id
    assert planned.official_rarity == "SPカード"
    assert planned.metadata_comparison.material_fields == ("official_rarity",)


def test_to_dict_exposes_the_four_values_flat(db_session, zoro, op01):
    planned = plan_one(db_session, entry(rarity="SPカード", block="X"))
    document = planned.to_dict()

    assert document["official_rarity"] == "SPカード"
    assert document["official_block_icon"] == "X"
    assert document["metadata_status"] is None
    # The nested structure is present too, so nothing is lost.
    assert document["official_metadata"]["official_rarity"] == "SPカード"


# --- 6. the planner still writes nothing --------------------------------------


def test_planning_metadata_issues_no_writes(db_session, zoro, op01):
    make_print(db_session, zoro, op01, official_rarity="L")
    statements: list[str] = []

    from sqlalchemy import event

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", record)
    try:
        plan_one(
            db_session, entry(rarity="SPカード"),
            digests={f"{CARDLIST}/OP01-001.png?260821": DIGEST},
        )
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", record)

    assert statements, "expected the planner to have queried something"
    for statement in statements:
        first = statement.strip().split(None, 1)[0].upper()
        assert first == "SELECT", f"planner issued a non-SELECT: {statement!r}"
