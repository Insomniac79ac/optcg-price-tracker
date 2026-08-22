"""What identifies an exact print, now that the identity is active.

    (canonical_card_id, language, release_product_id, official_artwork_variant)

for active, verified prints. treatment is NOT in it - it is editable Atlas
descriptive metadata, and Bandai publishes no such property. Neither is
release_product_code (absent for uncoded limited products) nor artwork_key
(evidence of the bytes, not identity).

These are model/DB-contract tests on sqlite; the same behaviour is proven
against a real PostgreSQL in test_exact_print_identity_migration_postgres.py."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import CanonicalCard, CardPrint, ReleaseProduct


def _card(db_session, card_code="OP01-001") -> CanonicalCard:
    card = CanonicalCard(
        card_code=card_code,
        name_en=f"Card {card_code}",
        original_set_code="OP-01",
        rarity="R",
        card_type="Character",
    )
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def _product(db_session, official_code="OP-01") -> ReleaseProduct:
    product = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code=official_code,
        display_name=f"Booster {official_code}",
        first_seen_name=f"Booster {official_code}",
        source_series_id="550101",
        source_url=f"https://www.onepiece-cardgame.com/products/boosters/{official_code}.php",
        verification_status="verified",
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def _print(db_session, card, product, **overrides) -> CardPrint:
    fields = dict(
        canonical_card_id=card.id,
        language="jp",
        treatment="normal",
        release_product_id=product.id if product is not None else None,
        official_artwork_variant="base",
        artwork_key="sha-256-of-the-artwork",
        verification_status="verified",
        is_active=True,
    )
    fields.update(overrides)
    print_row = CardPrint(**fields)
    db_session.add(print_row)
    db_session.commit()
    db_session.refresh(print_row)
    return print_row


# --- A. treatment is not identity ----------------------------------------


def test_same_identity_different_treatment_is_rejected(db_session):
    """The core of the change: two printings that differ only by an Atlas
    label are the same physical print, and the database now says so."""
    card, product = _card(db_session), _product(db_session)
    _print(db_session, card, product, treatment="normal", artwork_key="sha-a")

    with pytest.raises(IntegrityError):
        _print(db_session, card, product, treatment="parallel", artwork_key="sha-b")


def test_same_identity_with_null_and_non_null_treatment_is_rejected(db_session):
    """NULL treatment is not an escape hatch from identity either."""
    card, product = _card(db_session), _product(db_session)
    _print(db_session, card, product, treatment=None, artwork_key="sha-a")

    with pytest.raises(IntegrityError):
        _print(db_session, card, product, treatment="parallel", artwork_key="sha-b")


def test_same_identity_with_different_artwork_keys_is_still_rejected(db_session):
    """artwork_key is evidence, not identity - it cannot separate two prints
    that are otherwise the same printing."""
    card, product = _card(db_session), _product(db_session)
    _print(db_session, card, product, artwork_key="sha-first")

    with pytest.raises(IntegrityError):
        _print(db_session, card, product, artwork_key="sha-second")


def test_same_identity_with_different_release_product_codes_is_rejected(db_session):
    """release_product_code is a decorative label now; the product FK is what
    counts."""
    card, product = _card(db_session), _product(db_session)
    _print(db_session, card, product, release_product_code="OP-01", artwork_key="sha-a")

    with pytest.raises(IntegrityError):
        _print(db_session, card, product, release_product_code="EB-01", artwork_key="sha-b")


# --- B. genuine siblings ---------------------------------------------------


def test_base_and_p1_of_one_product_are_both_allowed(db_session):
    card, product = _card(db_session), _product(db_session)

    base = _print(db_session, card, product, official_artwork_variant="base", artwork_key="sha-a")
    p1 = _print(db_session, card, product, official_artwork_variant="p1", artwork_key="sha-b")

    assert {base.official_artwork_variant, p1.official_artwork_variant} == {"base", "p1"}


def test_the_same_artwork_in_two_products_is_allowed(db_session):
    """A reprint: same card, same artwork variant, different product."""
    card = _card(db_session)
    first, second = _product(db_session, "OP-01"), _product(db_session, "EB-01")

    a = _print(db_session, card, first, artwork_key="sha-a")
    b = _print(db_session, card, second, artwork_key="sha-b")

    assert a.release_product_id != b.release_product_id


def test_two_languages_of_one_printing_are_allowed(db_session):
    card, product = _card(db_session), _product(db_session)

    jp = _print(db_session, card, product, language="jp", artwork_key="sha-jp")
    en = _print(db_session, card, product, language="en", artwork_key="sha-en")

    assert (jp.language, en.language) == ("jp", "en")


def test_an_inactive_duplicate_does_not_collide(db_session):
    """The index covers the active+verified population only, exactly as
    before - a retired row does not block its replacement."""
    card, product = _card(db_session), _product(db_session)
    _print(db_session, card, product, is_active=False, artwork_key="sha-old")

    live = _print(db_session, card, product, artwork_key="sha-new")

    assert live.is_active is True


def test_an_unverified_duplicate_does_not_collide(db_session):
    card, product = _card(db_session), _product(db_session)
    _print(
        db_session, card, product, verification_status="unverified",
        official_artwork_variant=None, artwork_key=None,
    )

    verified = _print(db_session, card, product)

    assert verified.verification_status == "verified"


# --- C. what a verified print must carry ----------------------------------


def test_verified_with_null_treatment_is_accepted(db_session):
    card, product = _card(db_session), _product(db_session)

    print_row = _print(db_session, card, product, treatment=None)

    assert print_row.treatment is None
    assert print_row.verification_status == "verified"


def test_verified_without_release_product_id_is_rejected(db_session):
    card = _card(db_session)

    with pytest.raises(IntegrityError):
        _print(db_session, card, None)


def test_verified_without_official_artwork_variant_is_rejected(db_session):
    card, product = _card(db_session), _product(db_session)

    with pytest.raises(IntegrityError):
        _print(db_session, card, product, official_artwork_variant=None)


def test_verified_without_release_product_code_is_accepted(db_session):
    """Uncoded limited/promotional products are legitimate - their prints
    have a product FK and an artwork variant, and no code."""
    card, product = _card(db_session), _product(db_session)

    print_row = _print(db_session, card, product, release_product_code=None)

    assert print_row.release_product_code is None
    assert print_row.verification_status == "verified"


def test_verified_without_artwork_key_is_still_rejected(db_session):
    """artwork_key stopped being identity but remains required evidence: a
    verified print asserts its artwork was actually checked."""
    card, product = _card(db_session), _product(db_session)

    with pytest.raises(IntegrityError):
        _print(db_session, card, product, artwork_key=None)


@pytest.mark.parametrize("placeholder", ["", "   ", "unknown", "UNKNOWN", " Unknown "])
def test_verified_rejects_a_placeholder_treatment(db_session, placeholder):
    """NULL says "unclassified" honestly; a placeholder pretends."""
    card, product = _card(db_session), _product(db_session)

    with pytest.raises(IntegrityError):
        _print(db_session, card, product, treatment=placeholder)


# --- D. non-verified states keep their freedom ----------------------------


@pytest.mark.parametrize("status", ["unverified", "needs_review"])
def test_unresolved_prints_may_leave_every_identity_field_null(db_session, status):
    card = _card(db_session)

    print_row = _print(
        db_session, card, None, verification_status=status, treatment=None,
        official_artwork_variant=None, artwork_key=None, release_product_code=None,
    )

    assert print_row.release_product_id is None
    assert print_row.official_artwork_variant is None
    assert print_row.artwork_key is None
    assert print_row.treatment is None


@pytest.mark.parametrize("status", ["unverified", "needs_review"])
def test_unresolved_prints_may_still_park_unknown_in_treatment(db_session, status):
    """The pre-existing safe state for a print being worked out - untouched
    by this tranche."""
    card = _card(db_session)

    print_row = _print(
        db_session, card, None, verification_status=status, treatment="unknown",
        official_artwork_variant=None, artwork_key=None,
    )

    assert print_row.treatment == "unknown"


def test_promotion_to_verified_requires_the_identity_fields(db_session):
    card, product = _card(db_session), _product(db_session)
    print_row = _print(
        db_session, card, None, verification_status="unverified", treatment=None,
        official_artwork_variant=None, artwork_key=None,
    )

    print_row.verification_status = "verified"
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    print_row = db_session.get(CardPrint, print_row.id)
    print_row.release_product_id = product.id
    print_row.official_artwork_variant = "base"
    print_row.artwork_key = "sha-256-of-the-artwork"
    print_row.verification_status = "verified"
    db_session.commit()

    assert db_session.get(CardPrint, print_row.id).verification_status == "verified"
