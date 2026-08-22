import pytest
from sqlalchemy.exc import IntegrityError

from app.models import CanonicalCard, CardPrint, ReleaseProduct


def make_canonical_card(db_session, **overrides) -> CanonicalCard:
    fields = dict(
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        name_jp="モンキー・D・ルフィ",
        original_set_code="OP01",
        rarity="L",
        card_type="Leader",
    )
    fields.update(overrides)
    card = CanonicalCard(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_release_product(db_session, official_code: str = "OP-01") -> ReleaseProduct:
    product = (
        db_session.query(ReleaseProduct)
        .filter_by(source_catalogue="bandai_jp", official_code=official_code)
        .one_or_none()
    )
    if product is not None:
        return product
    product = ReleaseProduct(
        source_catalogue="bandai_jp",
        official_code=official_code,
        display_name=f"Booster {official_code}",
        first_seen_name=f"Booster {official_code}",
        source_series_id="550101",
        source_url="https://www.onepiece-cardgame.com/products/boosters/op01.php",
        verification_status="verified",
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def make_print(db_session, canonical_card, **overrides) -> CardPrint:
    fields = dict(
        canonical_card_id=canonical_card.id,
        language="en",
        treatment="base",
        verification_status="unverified",
    )
    # Exact-print identity is (canonical_card, language, release_product_id,
    # official_asset_variant). Defaulted for verified fixtures unless the
    # test is deliberately exercising their absence.
    if overrides.get("verification_status") == "verified":
        fields.setdefault(
            "release_product_id",
            make_release_product(db_session, overrides.get("release_product_code") or "OP-01").id,
        )
        fields.setdefault("official_asset_variant", _variant_for(overrides))
    fields.update(overrides)
    print_row = CardPrint(**fields)
    db_session.add(print_row)
    db_session.commit()
    db_session.refresh(print_row)
    return print_row


_VARIANTS_BY_ARTWORK_KEY: dict[str, str] = {}


def _variant_for(overrides: dict) -> str:
    """Distinct artwork variant per artwork_key, so two verified siblings of
    one canonical card never collide on the new identity."""
    key = str(overrides.get("artwork_key") or "art-1")
    if key not in _VARIANTS_BY_ARTWORK_KEY:
        index = len(_VARIANTS_BY_ARTWORK_KEY)
        _VARIANTS_BY_ARTWORK_KEY[key] = "base" if index == 0 else f"p{index}"
    return _VARIANTS_BY_ARTWORK_KEY[key]


def test_canonical_card_with_base_and_parallel_prints(db_session):
    card = make_canonical_card(db_session)

    base = make_print(
        db_session,
        card,
        treatment="base",
        release_product_code="OP-01",
        artwork_key="base-art",
        verification_status="verified",
    )
    parallel = make_print(
        db_session,
        card,
        treatment="parallel",
        release_product_code="OP-01",
        artwork_key="parallel-art",
        verification_status="verified",
    )

    assert base.canonical_card_id == card.id
    assert parallel.canonical_card_id == card.id
    assert base.treatment != parallel.treatment


def test_later_reprint_sharing_base_treatment(db_session):
    card = make_canonical_card(db_session)

    make_print(
        db_session,
        card,
        treatment="base",
        release_product_code="OP-01",
        artwork_key="base-art",
        verification_status="verified",
    )
    reprint = make_print(
        db_session,
        card,
        treatment="base",
        release_product_code="EB-01",
        artwork_key="base-art",
        verification_status="verified",
    )

    assert reprint.release_product_code == "EB-01"


def test_multi_colour_canonical_card(db_session):
    card = make_canonical_card(db_session, card_code="OP01-002", colors=["Red", "Green"])

    assert card.colors == ["Red", "Green"]
    assert len(card.colors) > 1


def test_verified_print_requires_non_unknown_treatment(db_session):
    card = make_canonical_card(db_session)

    with pytest.raises(IntegrityError):
        make_print(
            db_session,
            card,
            treatment="unknown",
            release_product_code="OP-01",
            artwork_key="base-art",
            verification_status="verified",
        )


def test_verified_print_does_not_require_release_product_code(db_session):
    """Bandai ships uncoded limited/promotional products, so a print with no
    release code is legitimate. Its product identity comes from
    release_product_id instead - which the verified check does require."""
    card = make_canonical_card(db_session, card_code="OP01-003")

    print_row = make_print(
        db_session,
        card,
        treatment="base",
        release_product_code=None,
        artwork_key="base-art",
        verification_status="verified",
    )

    assert print_row.release_product_code is None
    assert print_row.release_product_id is not None
    assert print_row.official_asset_variant is not None


def test_verified_print_requires_artwork_key(db_session):
    card = make_canonical_card(db_session, card_code="OP01-004")

    with pytest.raises(IntegrityError):
        make_print(
            db_session,
            card,
            treatment="base",
            release_product_code="OP-01",
            artwork_key=None,
            verification_status="verified",
        )


def test_duplicate_verified_print_rejected(db_session):
    card = make_canonical_card(db_session, card_code="OP01-005")

    make_print(
        db_session,
        card,
        treatment="base",
        release_product_code="OP-01",
        artwork_key="base-art",
        verification_status="verified",
    )

    with pytest.raises(IntegrityError):
        make_print(
            db_session,
            card,
            treatment="base",
            release_product_code="OP-01",
            artwork_key="base-art",
            verification_status="verified",
        )


def test_unverified_print_created_without_guessed_values(db_session):
    card = make_canonical_card(db_session)

    print_row = make_print(
        db_session,
        card,
        treatment="unknown",
        release_product_code=None,
        artwork_key=None,
        verification_status="unverified",
    )

    assert print_row.verification_status == "unverified"
    assert print_row.release_product_code is None
    assert print_row.artwork_key is None


def test_fake_release_product_code_rejected(db_session):
    card = make_canonical_card(db_session)

    with pytest.raises(IntegrityError):
        make_print(
            db_session,
            card,
            treatment="unknown",
            release_product_code="original",
            verification_status="unverified",
        )


def test_fake_artwork_key_rejected(db_session):
    card = make_canonical_card(db_session, card_code="OP01-006")

    with pytest.raises(IntegrityError):
        make_print(
            db_session,
            card,
            treatment="unknown",
            artwork_key="",
            verification_status="unverified",
        )


def _reload(db_session, card_id: int) -> CanonicalCard:
    db_session.expunge_all()
    return db_session.get(CanonicalCard, card_id)


def test_colors_append_persists_after_commit_and_reload(db_session):
    card = make_canonical_card(db_session, card_code="OP01-007", colors=["Red"])

    card.colors.append("Green")
    db_session.commit()

    reloaded = _reload(db_session, card.id)
    assert reloaded.colors == ["Red", "Green"]


def test_colors_remove_persists_after_commit_and_reload(db_session):
    card = make_canonical_card(db_session, card_code="OP01-008", colors=["Red", "Green"])

    card.colors.remove("Red")
    db_session.commit()

    reloaded = _reload(db_session, card.id)
    assert reloaded.colors == ["Green"]


def test_colors_item_assignment_persists_after_commit_and_reload(db_session):
    card = make_canonical_card(db_session, card_code="OP01-009", colors=["Red", "Green"])

    card.colors[0] = "Blue"
    db_session.commit()

    reloaded = _reload(db_session, card.id)
    assert reloaded.colors == ["Blue", "Green"]


def test_colors_stays_nullable_without_guessed_default(db_session):
    card = make_canonical_card(db_session, card_code="OP01-010")

    assert card.colors is None


@pytest.mark.parametrize("field", ["original_set_code", "rarity", "card_type"])
def test_canonical_card_identity_field_rejects_null(db_session, field):
    with pytest.raises(IntegrityError):
        make_canonical_card(db_session, card_code="OP01-011", **{field: None})


@pytest.mark.parametrize("field", ["original_set_code", "rarity", "card_type"])
@pytest.mark.parametrize("blank_value", ["", "   ", "\t"])
def test_canonical_card_identity_field_rejects_blank_on_insert(db_session, field, blank_value):
    with pytest.raises(IntegrityError):
        make_canonical_card(db_session, card_code="OP01-012", **{field: blank_value})


def test_canonical_card_requires_at_least_one_name(db_session):
    with pytest.raises(IntegrityError):
        make_canonical_card(db_session, card_code="OP01-013", name_en=None, name_jp=None)


def test_canonical_card_name_en_only_is_sufficient(db_session):
    card = make_canonical_card(db_session, card_code="OP01-014", name_en="Nami", name_jp=None)

    assert card.name_en == "Nami"
    assert card.name_jp is None


def test_canonical_card_name_jp_only_is_sufficient(db_session):
    card = make_canonical_card(db_session, card_code="OP01-015", name_en=None, name_jp="ナミ")

    assert card.name_jp == "ナミ"
    assert card.name_en is None


def test_canonical_card_blank_name_en_does_not_satisfy_name_requirement(db_session):
    with pytest.raises(IntegrityError):
        make_canonical_card(db_session, card_code="OP01-016", name_en="   ", name_jp=None)


@pytest.mark.parametrize("blank_value", ["", "   ", "\t"])
def test_verified_print_rejects_blank_release_product_code_on_insert(db_session, blank_value):
    card = make_canonical_card(db_session, card_code="OP01-017")

    with pytest.raises(IntegrityError):
        make_print(
            db_session,
            card,
            treatment="base",
            release_product_code=blank_value,
            artwork_key="base-art",
            verification_status="verified",
        )


@pytest.mark.parametrize("blank_value", ["", "   ", "\t"])
def test_verified_print_rejects_blank_artwork_key_on_insert(db_session, blank_value):
    card = make_canonical_card(db_session, card_code="OP01-018")

    with pytest.raises(IntegrityError):
        make_print(
            db_session,
            card,
            treatment="base",
            release_product_code="OP-01",
            artwork_key=blank_value,
            verification_status="verified",
        )


@pytest.mark.parametrize("blank_value", ["", "   ", "\t"])
def test_unverified_print_rejects_blank_release_product_code_on_insert(db_session, blank_value):
    card = make_canonical_card(db_session, card_code="OP01-019")

    with pytest.raises(IntegrityError):
        make_print(
            db_session,
            card,
            treatment="base",
            release_product_code=blank_value,
            verification_status="unverified",
        )


@pytest.mark.parametrize("placeholder", ["original", "Original", "ORIGINAL", "  original  ", " OriGinal"])
def test_release_product_code_placeholder_rejected_after_trim_and_casefold(db_session, placeholder):
    card = make_canonical_card(db_session, card_code="OP01-020")

    with pytest.raises(IntegrityError):
        make_print(
            db_session,
            card,
            treatment="base",
            release_product_code=placeholder,
            verification_status="unverified",
        )


@pytest.mark.parametrize("placeholder", ["original", "Original", "ORIGINAL", "  original  "])
def test_artwork_key_placeholder_rejected_after_trim_and_casefold(db_session, placeholder):
    card = make_canonical_card(db_session, card_code="OP01-021")

    with pytest.raises(IntegrityError):
        make_print(
            db_session,
            card,
            treatment="base",
            artwork_key=placeholder,
            verification_status="unverified",
        )


@pytest.mark.parametrize("blank_treatment", ["", "   ", "unknown", "Unknown", " UNKNOWN "])
def test_verified_print_rejects_blank_or_unknown_treatment_on_insert(db_session, blank_treatment):
    card = make_canonical_card(db_session, card_code="OP01-022")

    with pytest.raises(IntegrityError):
        make_print(
            db_session,
            card,
            treatment=blank_treatment,
            release_product_code="OP-01",
            artwork_key="base-art",
            verification_status="verified",
        )


def test_update_transition_to_verified_rejects_blank_release_product_code(db_session):
    card = make_canonical_card(db_session, card_code="OP01-023")
    print_row = make_print(
        db_session,
        card,
        treatment="base",
        release_product_code=None,
        artwork_key=None,
        verification_status="unverified",
    )

    print_row.release_product_code = "   "
    print_row.artwork_key = "base-art"
    print_row.verification_status = "verified"
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_update_transition_to_verified_rejects_blank_artwork_key(db_session):
    card = make_canonical_card(db_session, card_code="OP01-024")
    print_row = make_print(
        db_session,
        card,
        treatment="base",
        release_product_code=None,
        artwork_key=None,
        verification_status="unverified",
    )

    print_row.release_product_code = "OP-01"
    print_row.artwork_key = "\t"
    print_row.verification_status = "verified"
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_update_transition_to_verified_rejects_unknown_treatment(db_session):
    card = make_canonical_card(db_session, card_code="OP01-025")
    print_row = make_print(
        db_session,
        card,
        treatment="unknown",
        release_product_code=None,
        artwork_key=None,
        verification_status="unverified",
    )

    print_row.release_product_code = "OP-01"
    print_row.artwork_key = "base-art"
    print_row.release_product_id = make_release_product(db_session).id
    print_row.official_asset_variant = "base"
    print_row.verification_status = "verified"
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_update_transition_to_verified_succeeds_with_valid_values(db_session):
    card = make_canonical_card(db_session, card_code="OP01-026")
    print_row = make_print(
        db_session,
        card,
        treatment="base",
        release_product_code=None,
        artwork_key=None,
        verification_status="unverified",
    )

    print_row.release_product_code = "OP-01"
    print_row.artwork_key = "base-art"
    print_row.release_product_id = make_release_product(db_session).id
    print_row.official_asset_variant = "base"
    print_row.verification_status = "verified"
    db_session.commit()

    reloaded = _reload(db_session, card.id)
    assert reloaded is not None
