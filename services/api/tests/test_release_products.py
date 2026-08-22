"""Model-level coverage for the release-product entity (release_products /
release_product_aliases) and the dormant card_prints.release_product_id FK.

Runs on the suite's in-memory sqlite. Behaviour sqlite cannot prove faithfully
- ON DELETE RESTRICT / CASCADE and FK enforcement generally - lives in
tests/test_release_products_postgres.py instead, same split as
test_canonical_cards_postgres.py."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import CanonicalCard, CardPrint, ReleaseProduct, ReleaseProductAlias
from app.models.release_product import SOURCE_CATALOGUES
from app.models.release_product_alias import ALIAS_KINDS

BANDAI_OP01_URL = "https://www.onepiece-cardgame.com/products/boosters/op01.php"


def make_product(db_session, **overrides) -> ReleaseProduct:
    fields = dict(
        source_catalogue="bandai_jp",
        official_code="OP-01",
        display_name="ブースターパック ROMANCE DAWN【OP-01】",
        first_seen_name="ブースターパック ROMANCE DAWN【OP-01】",
        source_series_id="550101",
        source_url=BANDAI_OP01_URL,
        verification_status="verified",
    )
    fields.update(overrides)
    product = ReleaseProduct(**fields)
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def make_alias(db_session, product, **overrides) -> ReleaseProductAlias:
    fields = dict(
        product_id=product.id,
        alias_name="ROMANCE DAWN",
        alias_kind="bandai_official",
        source_url=BANDAI_OP01_URL,
    )
    fields.update(overrides)
    alias = ReleaseProductAlias(**fields)
    db_session.add(alias)
    db_session.commit()
    db_session.refresh(alias)
    return alias


# --- ReleaseProduct -------------------------------------------------------


def test_coded_jp_product_inserts_with_its_evidence(db_session):
    product = make_product(db_session)

    assert product.id is not None
    assert product.source_catalogue == "bandai_jp"
    assert product.official_code == "OP-01"
    # The authoritative title is stored verbatim, not normalized down to
    # "ROMANCE DAWN" - the short form is evidence, and lives in the alias
    # table rather than replacing the published label.
    assert product.display_name == "ブースターパック ROMANCE DAWN【OP-01】"
    assert product.first_seen_name == product.display_name
    assert product.source_series_id == "550101"
    assert product.created_at is not None


def test_same_official_code_in_same_catalogue_is_rejected(db_session):
    make_product(db_session, official_code="OP-01")

    with pytest.raises(IntegrityError):
        make_product(db_session, official_code="OP-01", source_series_id="550199")


def test_same_official_code_in_a_different_catalogue_is_accepted(db_session):
    """The case a global UNIQUE(official_code) would have made impossible:
    Bandai's JP and EN catalogues both publish OP-01, with different release
    dates (2022-07-22 vs 2022-12-02), so they are different product records."""
    jp = make_product(db_session, source_catalogue="bandai_jp", official_code="OP-01")
    en = make_product(
        db_session,
        source_catalogue="bandai_en",
        official_code="OP-01",
        display_name="BOOSTER PACK -ROMANCE DAWN- [OP-01]",
        first_seen_name="BOOSTER PACK -ROMANCE DAWN- [OP-01]",
        source_series_id="569101",
        source_url="https://en.onepiece-cardgame.com/products/boosters/op01.php",
    )

    assert jp.id != en.id
    assert {p.source_catalogue for p in db_session.query(ReleaseProduct).all()} == {
        "bandai_jp",
        "bandai_en",
    }


def test_multiple_uncoded_products_are_allowed(db_session):
    """Bandai's Card List carries hundreds of name-only limited/promo
    products. The unique index is partial so they never collide on NULL."""
    first = make_product(
        db_session,
        official_code=None,
        display_name="プレミアムカードコレクション 25周年エディション",
        first_seen_name="プレミアムカードコレクション 25周年エディション",
        source_series_id="550301",
        verification_status="needs_review",
    )
    second = make_product(
        db_session,
        official_code=None,
        display_name="週刊少年ジャンプ応募者全員サービス",
        first_seen_name="週刊少年ジャンプ応募者全員サービス",
        source_series_id="550301",
        verification_status="needs_review",
    )

    assert first.id != second.id
    assert db_session.query(ReleaseProduct).filter_by(official_code=None).count() == 2


def test_duplicate_display_names_are_allowed(db_session):
    """Two genuinely different products can share a displayed name - the four
    週刊少年ジャンプ付録 products do. Distinct ids, never a silent merge."""
    first = make_product(
        db_session,
        official_code=None,
        display_name="週刊少年ジャンプ付録",
        first_seen_name="週刊少年ジャンプ付録",
        source_series_id="550301",
    )
    second = make_product(
        db_session,
        official_code=None,
        display_name="週刊少年ジャンプ付録",
        first_seen_name="週刊少年ジャンプ付録",
        source_series_id="550302",
    )

    assert first.id != second.id


def test_composite_official_code_is_representable(db_session):
    """Bandai's EN catalogue really publishes OP14-EB04. A shape regex on
    official_code would have rejected it, so there is none."""
    product = make_product(
        db_session,
        source_catalogue="bandai_en",
        official_code="OP14-EB04",
        display_name="BOOSTER PACK -THE AZURE SEA'S SEVEN- [OP14-EB04]",
        first_seen_name="BOOSTER PACK -THE AZURE SEA'S SEVEN- [OP14-EB04]",
        source_series_id="569114",
        source_url="https://en.onepiece-cardgame.com/cardlist/?series=569114",
    )

    assert product.official_code == "OP14-EB04"


def test_invalid_verification_status_is_rejected(db_session):
    with pytest.raises(IntegrityError):
        make_product(db_session, verification_status="approved")


def test_verification_vocabulary_matches_card_prints(db_session):
    for status in ("verified", "unverified", "needs_review"):
        make_product(db_session, official_code=f"OP-{status[:2]}", verification_status=status)

    assert db_session.query(ReleaseProduct).count() == 3


@pytest.mark.parametrize(
    "field",
    ["source_catalogue", "display_name", "first_seen_name", "source_series_id", "source_url"],
)
@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n"])
def test_blank_required_identity_or_evidence_fields_are_rejected(db_session, field, blank):
    with pytest.raises(IntegrityError):
        make_product(db_session, **{field: blank})


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n"])
def test_blank_official_code_is_rejected_but_null_is_allowed(db_session, blank):
    with pytest.raises(IntegrityError):
        make_product(db_session, official_code=blank)

    db_session.rollback()
    assert make_product(db_session, official_code=None).official_code is None


def test_source_catalogue_vocabulary_is_declared(db_session):
    """source_catalogue is an authority namespace, not a language or an
    inferred market - only the JP catalogue is seeded today."""
    assert SOURCE_CATALOGUES == ("bandai_jp", "bandai_asia_en", "bandai_en")


# --- ReleaseProductAlias --------------------------------------------------


@pytest.mark.parametrize("alias_kind", ALIAS_KINDS)
def test_valid_alias_kinds_are_accepted(db_session, alias_kind):
    product = make_product(db_session)
    source_url = None if alias_kind == "source_rendering" else BANDAI_OP01_URL

    alias = make_alias(
        db_session, product, alias_name=f"name-{alias_kind}", alias_kind=alias_kind,
        source_url=source_url,
    )

    assert alias.alias_kind == alias_kind


def test_invalid_alias_kind_is_rejected(db_session):
    product = make_product(db_session)

    with pytest.raises(IntegrityError):
        make_alias(db_session, product, alias_kind="storefront")


def test_duplicate_product_kind_and_name_is_rejected(db_session):
    product = make_product(db_session)
    make_alias(db_session, product, alias_name="ROMANCE DAWN")

    with pytest.raises(IntegrityError):
        make_alias(db_session, product, alias_name="ROMANCE DAWN")


def test_same_alias_text_on_a_different_product_is_allowed(db_session):
    first = make_product(db_session, official_code="OP-01")
    second = make_product(db_session, official_code="OP-02", source_series_id="550102")

    make_alias(db_session, first, alias_name="ROMANCE DAWN")
    make_alias(db_session, second, alias_name="ROMANCE DAWN")

    assert db_session.query(ReleaseProductAlias).filter_by(alias_name="ROMANCE DAWN").count() == 2


def test_the_same_name_may_be_recorded_under_two_different_kinds(db_session):
    product = make_product(db_session)

    make_alias(db_session, product, alias_name="ROMANCE DAWN", alias_kind="bandai_official")
    make_alias(
        db_session, product, alias_name="ROMANCE DAWN", alias_kind="source_rendering",
        source_url=None,
    )

    assert db_session.query(ReleaseProductAlias).count() == 2


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n"])
def test_blank_alias_name_is_rejected(db_session, blank):
    product = make_product(db_session)

    with pytest.raises(IntegrityError):
        make_alias(db_session, product, alias_name=blank)


def test_a_bandai_alias_must_cite_a_bandai_source(db_session):
    """A name claimed as Bandai's has to carry the URL that attests it -
    the 2026-08-10 incident was evidence asserted without a source."""
    product = make_product(db_session)

    with pytest.raises(IntegrityError):
        make_alias(db_session, product, alias_kind="bandai_official", source_url=None)


def test_a_source_rendering_may_have_no_url(db_session):
    """SNKRDUNK's ロマンスドーン has no Bandai attestation and no recorded
    storefront URL; minting one to satisfy NOT NULL would fabricate
    evidence. The kind, not the URL, is what keeps it out of Bandai names."""
    product = make_product(db_session)

    alias = make_alias(
        db_session, product, alias_name="ロマンスドーン", alias_kind="source_rendering",
        source_url=None,
    )

    assert alias.source_url is None
    assert alias.alias_kind == "source_rendering"
    # Recording it never touches the product's own published label.
    db_session.refresh(product)
    assert product.display_name == "ブースターパック ROMANCE DAWN【OP-01】"


# --- CardPrint.release_product_id ----------------------------------------


def _card(db_session, card_code="OP01-001") -> CanonicalCard:
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
    return card


def test_release_product_id_defaults_to_null(db_session):
    """A print whose product is unknown or unresolved must have a safe
    state - which is why the column stays nullable after the backfill."""
    card = _card(db_session)

    print_row = CardPrint(
        canonical_card_id=card.id, language="jp", treatment="base",
        verification_status="unverified",
    )
    db_session.add(print_row)
    db_session.commit()
    db_session.refresh(print_row)

    assert print_row.release_product_id is None


def test_print_can_reference_a_product_without_losing_its_code(db_session):
    product = make_product(db_session)
    card = _card(db_session)

    print_row = CardPrint(
        canonical_card_id=card.id, language="jp", treatment="base",
        release_product_code="OP-01", artwork_key="art-1",
        official_artwork_variant="base",
        verification_status="verified", release_product_id=product.id,
    )
    db_session.add(print_row)
    db_session.commit()
    db_session.refresh(print_row)

    assert print_row.release_product_id == product.id
    # release_product_code is not replaced by the FK: the SNKRDUNK collector
    # still joins RELEASE_REFERENCES on it.
    assert print_row.release_product_code == "OP-01"
