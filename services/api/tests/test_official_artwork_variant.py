"""The official-artwork-variant parsing contract, and the database constraint
that guards the column it feeds.

official_artwork_variant records *which official Bandai artwork* a print
carries - 'base' for CODE.png, 'pN' for CODE_pN.png. It is derived from the
official asset address and nothing else: never from treatment, never from
artwork_key (which stays the SHA-256 evidence anchor for the bytes), never
from a source mapping."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import CanonicalCard, CardPrint, ReleaseProduct
from app.services.official_artwork_variant import parse_official_artwork_variant

CARD_LIST = "https://www.onepiece-cardgame.com/images/cardlist/card"

# A real SHA-256 shaped artwork_key, to keep the two fields visibly distinct.
SHA256_KEY = "ef20a8a51391e53f4a3fe71251d20a9dfe3d59dc65a4217a6c9b2eefaff2db2b"
OTHER_SHA256_KEY = "12b26ad2b7e72ae8eb2695de73902c0d7e724c34fc8a02c1af7beeb1e5df755f"


# --- parsing --------------------------------------------------------------


@pytest.mark.parametrize(
    "image_url,card_code,expected",
    [
        # The four shapes the brief names.
        (f"{CARD_LIST}/OP01-001.png?260630", "OP01-001", "base"),
        (f"{CARD_LIST}/OP01-001_p2.png?260630", "OP01-001", "p2"),
        (f"{CARD_LIST}/OP04-001_p1.png", "OP04-001", "p1"),
        (f"{CARD_LIST}/OP01-001_p12.png", "OP01-001", "p12"),
        # Multi-digit beyond p12 is equally fine - String(16) is the only cap.
        (f"{CARD_LIST}/OP01-001_p101.png", "OP01-001", "p101"),
        # A bare basename with no directory at all still parses.
        ("OP03-013_p1.png", "OP03-013", "p1"),
    ],
)
def test_official_addresses_parse(image_url, card_code, expected):
    assert parse_official_artwork_variant(image_url, card_code) == expected


@pytest.mark.parametrize(
    "query",
    ["", "?260630", "?260631", "?v=2&cache=bust", "#fragment"],
)
def test_query_string_and_fragment_are_ignored(query):
    """Bandai's cache buster changes without the artwork changing, so it can
    never be allowed to affect identity evidence."""
    assert parse_official_artwork_variant(f"{CARD_LIST}/OP01-013_p2.png{query}", "OP01-013") == "p2"


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
    assert parse_official_artwork_variant(f"{prefix}/OP01-001_p2.png", "OP01-001") == "p2"


@pytest.mark.parametrize(
    "image_url,card_code",
    [
        # A different card's asset - a wrong image, not a variant. This is the
        # single most important thing the parser refuses to paper over.
        (f"{CARD_LIST}/OP01-002_p1.png", "OP01-001"),
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
        # N must be a positive integer with no leading zero.
        (f"{CARD_LIST}/OP01-001_p0.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_p01.png", "OP01-001"),
        (f"{CARD_LIST}/OP01-001_p-1.png", "OP01-001"),
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
    assert parse_official_artwork_variant(image_url, card_code) is None


def test_variant_does_not_depend_on_artwork_key():
    """artwork_key is the SHA-256 of the bytes; the variant is the address.
    Re-hashing the same asset cannot move a print to another variant."""
    url = f"{CARD_LIST}/OP04-001_p1.png?260630"

    assert parse_official_artwork_variant(url, "OP04-001") == "p1"
    # The parser has no artwork_key parameter at all - the strongest possible
    # statement that one cannot influence the other.
    assert parse_official_artwork_variant.__code__.co_varnames[:2] == ("image_url", "card_code")


def test_variant_does_not_depend_on_treatment():
    """Two prints of one card: Bandai gives them identical everything except
    the asset address, and 'normal'/'parallel' is Atlas's own editorial
    label. The label cannot be an input, and the variant is not that label."""
    base = parse_official_artwork_variant(f"{CARD_LIST}/OP01-013.png?260630", "OP01-013")
    parallel = parse_official_artwork_variant(f"{CARD_LIST}/OP01-013_p2.png?260630", "OP01-013")

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
        official_artwork_variant=variant,
    )
    fields.update(overrides)
    print_row = CardPrint(**fields)
    db_session.add(print_row)
    db_session.commit()
    db_session.refresh(print_row)
    return print_row


@pytest.mark.parametrize("variant", ["base", "p1", "p2", "p10", "p12", "p101"])
def test_valid_variants_are_accepted(db_session, variant):
    assert _print(db_session, variant).official_artwork_variant == variant


def test_null_is_accepted_on_an_unresolved_print(db_session):
    """NULL is still the safe state - but only while the print is not yet
    verified. See test_a_verified_print_now_requires_a_variant."""
    print_row = _print(db_session, None, verification_status="unverified")

    assert print_row.official_artwork_variant is None


@pytest.mark.parametrize(
    "variant",
    ["", "   ", "\t", "parallel", "_p1", "P1", "p", "p0", "p01", "p-1", "p1a", "foo", "BASE"],
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
    assert print_row.official_artwork_variant == "p1"


def test_changing_the_image_url_query_string_does_not_change_the_variant(db_session):
    print_row = _print(db_session, "p2")

    print_row.image_url = f"{CARD_LIST}/OP01-001_p2.png?999999"
    db_session.commit()
    db_session.refresh(print_row)

    assert print_row.official_artwork_variant == "p2"
    assert parse_official_artwork_variant(print_row.image_url, "OP01-001") == "p2"


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
        "official_artwork_variant",
    ]
