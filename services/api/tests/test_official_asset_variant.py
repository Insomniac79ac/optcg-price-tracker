"""The official-asset-variant parsing contract, and the database constraint
that guards the column it feeds.

official_asset_variant records *which official Bandai asset* a print carries -
'base' for CODE.png, 'pN' for CODE_pN.png, 'rN' for CODE_rN.png. It is derived
from the official asset address and nothing else: never from treatment, never
from artwork_key (which stays the SHA-256 evidence anchor for the bytes),
never from a source mapping.

"Asset", not "artwork", on purpose. The suffix identifies the official
occurrence; it does not promise the artwork differs. The complete 2026-08-22
JP corpus (4,962 occurrences: base 2,821, p1-p10 1,680, r1-r3 461, nothing
else) contains 152 rN assets that are byte-for-byte identical to a base asset.
Identical bytes may still be distinct print identities - which is exactly why
artwork_key is evidence and the asset variant is identity."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import CanonicalCard, CardPrint, ReleaseProduct
from app.services.official_asset_variant import parse_official_asset_variant

CARD_LIST = "https://www.onepiece-cardgame.com/images/cardlist/card"

# A real SHA-256 shaped artwork_key, to keep the two fields visibly distinct.
SHA256_KEY = "ef20a8a51391e53f4a3fe71251d20a9dfe3d59dc65a4217a6c9b2eefaff2db2b"
OTHER_SHA256_KEY = "12b26ad2b7e72ae8eb2695de73902c0d7e724c34fc8a02c1af7beeb1e5df755f"


# --- parsing --------------------------------------------------------------


@pytest.mark.parametrize(
    "image_url,card_code,expected",
    [
        # The shapes the published catalogue actually serves.
        (f"{CARD_LIST}/OP01-001.png?260630", "OP01-001", "base"),
        (f"{CARD_LIST}/OP01-001_p2.png?260630", "OP01-001", "p2"),
        (f"{CARD_LIST}/OP04-001_p1.png", "OP04-001", "p1"),
        (f"{CARD_LIST}/OP01-001_p10.png", "OP01-001", "p10"),
        (f"{CARD_LIST}/OP01-001_p12.png", "OP01-001", "p12"),
        # The r family, measured across the whole JP catalogue on 2026-08-22.
        # r1-r3 is the entire observed range; the grammar admits any positive
        # N because the numbering is Bandai's to extend, not Atlas's to cap.
        (f"{CARD_LIST}/OP01-120_r1.png?260821", "OP01-120", "r1"),
        (f"{CARD_LIST}/OP05-074_r2.png", "OP05-074", "r2"),
        (f"{CARD_LIST}/OP05-119_r3.png", "OP05-119", "r3"),
        (f"{CARD_LIST}/OP01-001_r10.png", "OP01-001", "r10"),
        # Multi-digit beyond p12 is equally fine - String(16) is the only cap.
        (f"{CARD_LIST}/OP01-001_p101.png", "OP01-001", "p101"),
        # A bare basename with no directory at all still parses.
        ("OP03-013_p1.png", "OP03-013", "p1"),
    ],
)
def test_official_addresses_parse(image_url, card_code, expected):
    assert parse_official_asset_variant(image_url, card_code) == expected


@pytest.mark.parametrize(
    "query",
    ["", "?260630", "?260631", "?v=2&cache=bust", "#fragment"],
)
def test_query_string_and_fragment_are_ignored(query):
    """Bandai's cache buster changes without the asset changing, so it can
    never be allowed to affect identity evidence."""
    assert parse_official_asset_variant(f"{CARD_LIST}/OP01-013_p2.png{query}", "OP01-013") == "p2"
    assert parse_official_asset_variant(f"{CARD_LIST}/OP01-120_r1.png{query}", "OP01-120") == "r1"


@pytest.mark.parametrize(
    "prefix",
    [
        "https://www.onepiece-cardgame.com/images/cardlist/card",
        "https://asia-en.onepiece-cardgame.com/images/cardlist/card",
        "https://cdn.example.test/mirror/deep/path",
        "http://localhost:8000/static",
    ],
)
def test_only_the_basename_matters_not_the_host_or_path(prefix):
    assert parse_official_asset_variant(f"{prefix}/OP01-001_p2.png", "OP01-001") == "p2"


@pytest.mark.parametrize(
    "image_url,card_code",
    [
        # A different card's asset - a wrong image, not a variant. This is the
        # single most important thing the parser refuses to paper over.
        (f"{CARD_LIST}/OP01-002_p1.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-002_r1.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-002.png", "OP01-001"),
        # The code must be the whole stem, not a prefix of a longer one.
        (f"{CARD_LIST}/OP01-0011.png", "OP01-001"),
        # Unsupported suffixes are never guessed at.
        (f"{CARD_LIST}/OP01-001_p.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_px.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_p1a.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_parallel.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001-p1.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_P1.png", "OP01-001"),
        # The same refusals for the r family - admitting rN widened the
        # vocabulary by one letter, not by a set of spellings.
        (f"{CARD_LIST}/OP01-001_r.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_rx.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_r1a.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_reprint.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001-r1.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_R1.png", "OP01-001"),
        # Letters the catalogue has never published. A new family is
        # unrecognised evidence a human must look at - exactly what _rN was
        # before it was measured - not something to parse optimistically.
        (f"{CARD_LIST}/OP01-001_s1.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_a1.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_x2.png", "OP01-001"),
        # N must be a positive integer with no leading zero.
        (f"{CARD_LIST}/OP01-001_p0.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_p01.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_p-1.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_r0.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_r01.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_r001.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_r-1.png", "OP01-001"),
        # Non-ASCII digits are digits to str.isdigit(); they are not codes.
        (f"{CARD_LIST}/OP01-001_p١.png", "OP01-001"),
        # Not an official Card List asset.
        (f"{CARD_LIST}/OP01-001.webp", "OP01-001"),
        (f"{CARD_LIST}/OP01-001", "OP01-001"),
        (f"{CARD_LIST}/", "OP01-001"),
        # Nothing to parse.
        (None, "OP01-001"),
        ("", "OP01-001"),
        (f"{CARD_LIST}/OP01-001.png", None),
        (f"{CARD_LIST}/OP01-001.png", ""),
    ],
)
def test_unresolvable_addresses_return_none(image_url, card_code):
    assert parse_official_asset_variant(image_url, card_code) is None


def test_variant_does_not_depend_on_artwork_key():
    """artwork_key is the SHA-256 of the bytes; the variant is the address.
    Re-hashing the same asset cannot move a print to another variant."""
    url = f"{CARD_LIST}/OP04-001_p1.png?260630"

    assert parse_official_asset_variant(url, "OP04-001") == "p1"
    # The parser has no artwork_key parameter at all - the strongest possible
    # statement that one cannot influence the other.
    assert parse_official_asset_variant.__code__.co_varnames[:2] == ("image_url", "card_code")


def test_variant_does_not_depend_on_treatment():
    """Two prints of one card: Bandai gives them identical everything except
    the asset address, and 'normal'/'parallel' is Atlas's own editorial
    label. The label cannot be an input, and the variant is not that label."""
    base = parse_official_asset_variant(f"{CARD_LIST}/OP01-013.png?260630", "OP01-013")
    parallel = parse_official_asset_variant(f"{CARD_LIST}/OP01-013_p2.png?260630", "OP01-013")

    assert (base, parallel) == ("base", "p2")
    assert "parallel" not in {base, parallel}


# --- database constraint --------------------------------------------------


def _release_product(db_session) -> ReleaseProduct:
    product = (
        db_session.query(ReleaseProduct)
        .filter_by(source_catalogue="bandai_jp", official_code="OP-01")
        .one_or_none()
    )
    if product is not None:
        return product
    product = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code="OP-01",
        display_name="Booster OP-01",
        first_seen_name="Booster OP-01",
        source_series_id="550101",
        source_url="https://www.onepiece-cardgame.com/products/boosters/op01.php",
        verification_status="verified",
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def _print(db_session, variant, card_code="OP01-001", **overrides):
    card = CanonicalCard(
        card_code=card_code,
        name_en="Monkey D. Luffy",
        original_set_code="OP-01",
        rarity="L",
        card_type="Leader",
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)

    fields = dict(
        canonical_card_id=card.id,
        language="jp",
        treatment="normal",
        release_product_code="OP-01",
        release_product_id=_release_product(db_session).id,
        artwork_key=SHA256_KEY,
        image_url=f"{CARD_LIST}/{card_code}.png?260630",
        verification_status="verified",
        official_asset_variant=variant,
    )
    fields.update(overrides)
    print_row = CardPrint(**fields)
    db_session.add(print_row)
    db_session.commit()
    db_session.refresh(print_row)
    return print_row


@pytest.mark.parametrize(
    "variant", ["base", "p1", "p2", "p10", "p12", "p101", "r1", "r2", "r3", "r10"]
)
def test_valid_variants_are_accepted(db_session, variant):
    assert _print(db_session, variant).official_asset_variant == variant


def test_null_is_accepted_on_an_unresolved_print(db_session):
    """NULL is still the safe state - but only while the print is not yet
    verified. See test_a_verified_print_now_requires_a_variant."""
    print_row = _print(db_session, None, verification_status="unverified")

    assert print_row.official_asset_variant is None


@pytest.mark.parametrize(
    "variant",
    [
        "", "   ", "\t", "parallel", "_p1", "P1", "p", "p0", "p01", "p-1", "p1a", "foo", "BASE",
        # The r family gets exactly the same refusals as the p family.
        "R1", "r", "r0", "r01", "r-1", "r1a", "_r1", "reprint",
        # Letters Bandai has never published stay outside the vocabulary.
        "s1", "a1", "x2",
    ],
)
def test_invalid_variants_are_rejected(db_session, variant):
    with pytest.raises(IntegrityError):
        _print(db_session, variant)


def test_a_verified_print_now_requires_a_variant(db_session):
    """Phase 3 recorded this evidence without gating on it. The identity
    activation gates on it: a verified print must name its official artwork,
    because that is half of what identifies the printing."""
    with pytest.raises(IntegrityError):
        _print(db_session, None, verification_status="verified")


def test_changing_artwork_key_alone_does_not_change_the_variant(db_session):
    print_row = _print(db_session, "p1")

    print_row.artwork_key = OTHER_SHA256_KEY
    db_session.commit()
    db_session.refresh(print_row)

    assert print_row.artwork_key == OTHER_SHA256_KEY
    assert print_row.official_asset_variant == "p1"


def test_changing_the_image_url_query_string_does_not_change_the_variant(db_session):
    print_row = _print(db_session, "p2")

    print_row.image_url = f"{CARD_LIST}/OP01-001_p2.png?999999"
    db_session.commit()
    db_session.refresh(print_row)

    assert print_row.official_asset_variant == "p2"
    assert parse_official_asset_variant(print_row.image_url, "OP01-001") == "p2"


def test_the_variant_is_now_part_of_the_verified_identity(db_session):
    """Phase 3 recorded this evidence; the identity activation put it in the
    key. treatment, release_product_code and artwork_key are all out of it."""
    index = next(
        i
        for i in CardPrint.__table__.indexes
        if i.name == "uq_card_prints_active_verified_identity"
    )

    assert [c.name for c in index.columns] == [
        "canonical_card_id",
        "language",
        "release_product_id",
        "official_asset_variant",
    ]


# --- the r family as identity, never as meaning ---------------------------
#
# The three cases below are the ones measured in the complete 2026-08-22 JP
# corpus: OP01-120, OP05-074 and OP05-119 each publish both `_r1` and `_r2`
# inside PRB-01, with distinct official entry ids, distinct asset addresses
# and distinct SHA-256 digests. Before rN was part of the vocabulary all three
# collapsed to a NULL variant and collided under the exact-print key.


def _second_release_product(db_session) -> ReleaseProduct:
    product = (
        db_session.query(ReleaseProduct)
        .filter_by(source_catalogue="bandai_jp", official_code="PRB-01")
        .one_or_none()
    )
    if product is not None:
        return product
    product = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code="PRB-01",
        display_name="ONE PIECE CARD THE BEST",
        first_seen_name="ONE PIECE CARD THE BEST",
        source_series_id="550301",
        source_url="https://www.onepiece-cardgame.com/products/",
        verification_status="verified",
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def _card(db_session, card_code) -> CanonicalCard:
    card = CanonicalCard(
        card_code=card_code,
        name_en=card_code,
        original_set_code="PRB-01",
        rarity="SEC",
        card_type="Character",
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def _print_on(db_session, card, variant, product, *, artwork_key=SHA256_KEY, treatment="normal"):
    row = CardPrint(
        canonical_card_id=card.id,
        language="jp",
        treatment=treatment,
        release_product_id=product.id,
        artwork_key=artwork_key,
        image_url=f"{CARD_LIST}/{card.card_code}"
        + ("" if variant == "base" else f"_{variant}")
        + ".png?260821",
        verification_status="verified",
        official_asset_variant=variant,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


@pytest.mark.parametrize("card_code", ["OP01-120", "OP05-074", "OP05-119"])
def test_r1_and_r2_in_one_product_are_two_identities(db_session, card_code):
    """The three real collision cases. Same card, same product, same rarity,
    same treatment - only the official asset address differs, and that alone
    is enough to make them two printings rather than one."""
    card = _card(db_session, card_code)
    product = _second_release_product(db_session)

    r1 = _print_on(db_session, card, "r1", product, artwork_key=SHA256_KEY)
    r2 = _print_on(db_session, card, "r2", product, artwork_key=OTHER_SHA256_KEY)

    assert r1.id != r2.id
    assert (r1.official_asset_variant, r2.official_asset_variant) == ("r1", "r2")
    assert r1.release_product_id == r2.release_product_id
    assert r1.canonical_card_id == r2.canonical_card_id


@pytest.mark.parametrize("card_code", ["OP01-120", "OP05-074", "OP05-119"])
def test_collapsing_rn_to_none_is_what_would_have_collided(db_session, card_code):
    """The counterfactual, stated as a test: without the suffix these two rows
    are the same identity, so the unique index refuses the second."""
    card = _card(db_session, card_code)
    product = _second_release_product(db_session)

    first = _print_on(db_session, card, "r1", product)
    card_id, product_id = first.canonical_card_id, first.release_product_id

    duplicate = CardPrint(
        canonical_card_id=card_id,
        language="jp",
        treatment="parallel",
        release_product_id=product_id,
        artwork_key=OTHER_SHA256_KEY,
        image_url=f"{CARD_LIST}/{card_code}_r2.png?260821",
        verification_status="verified",
        official_asset_variant="r1",  # the same asset address as the first row
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_identical_artwork_key_does_not_collapse_base_and_rn(db_session):
    """152 rN assets in the JP corpus are byte-for-byte identical to a base
    asset. artwork_key is SHA-256 evidence, not identity, so equal bytes must
    leave two distinct printings standing."""
    card = _card(db_session, "OP01-120")
    product = _second_release_product(db_session)

    base = _print_on(db_session, card, "base", product, artwork_key=SHA256_KEY)
    r1 = _print_on(db_session, card, "r1", product, artwork_key=SHA256_KEY)

    assert base.artwork_key == r1.artwork_key == SHA256_KEY
    assert base.id != r1.id
    assert {base.official_asset_variant, r1.official_asset_variant} == {"base", "r1"}


def test_the_same_rn_in_two_products_stays_distinct_through_the_product_id(db_session):
    """The suffix numbering spans products, so r1 is unique only *within* one.
    release_product_id is what keeps two r1 printings apart."""
    card = _card(db_session, "OP01-120")

    first = _print_on(db_session, card, "r1", _release_product(db_session))
    second = _print_on(db_session, card, "r1", _second_release_product(db_session))

    assert first.id != second.id
    assert first.official_asset_variant == second.official_asset_variant == "r1"
    assert first.release_product_id != second.release_product_id


@pytest.mark.parametrize("variant", ["base", "p1", "r1", "r2", "r3"])
def test_the_variant_never_determines_a_treatment(db_session, variant):
    """rN is an address, not a classification. A verified print carrying any
    variant may have NULL treatment - the strongest possible statement that
    the suffix does not imply parallel, manga, special, alt-art or rarity."""
    card = _card(db_session, f"OP01-{variant}")
    product = _second_release_product(db_session)

    row = _print_on(db_session, card, variant, product, treatment=None)

    assert row.treatment is None
    assert row.official_asset_variant == variant
    assert row.verification_status == "verified"


def test_the_parser_gives_the_r_family_no_treatment_vocabulary():
    """Whatever the suffix is, the parser's whole output vocabulary is the
    address grammar - no treatment word can ever come out of it."""
    outputs = {
        parse_official_asset_variant(f"{CARD_LIST}/OP01-120{suffix}.png?260821", "OP01-120")
        for suffix in ("", "_p1", "_p5", "_r1", "_r2", "_r3")
    }

    assert outputs == {"base", "p1", "p5", "r1", "r2", "r3"}
    assert not outputs & {"normal", "parallel", "manga", "special", "alt-art", "SEC", "SR"}
