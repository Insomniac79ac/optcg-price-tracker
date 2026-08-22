"""PostgreSQL-backed coverage for release-product behaviour sqlite can't
prove faithfully: real FK enforcement, ON DELETE RESTRICT on
card_prints.release_product_id, and ON DELETE CASCADE on the alias table.
Same pattern (and the same disposable instance on port 5544) as
test_canonical_cards_postgres.py; skips outright if no server answers."""

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import CanonicalCard, CardPrint, ReleaseProduct, ReleaseProductAlias

TEST_POSTGRES_URL = os.environ.get(
    "TEST_POSTGRES_URL", "postgresql+psycopg://opcg:opcg@localhost:5544/opcg_test"
)

TABLES = [
    ReleaseProduct.__table__,
    ReleaseProductAlias.__table__,
    CanonicalCard.__table__,
    CardPrint.__table__,
]


@pytest.fixture()
def postgres_session():
    engine = create_engine(TEST_POSTGRES_URL)
    try:
        with engine.connect():
            pass
    except OperationalError:
        engine.dispose()
        pytest.skip(f"No PostgreSQL server reachable at {TEST_POSTGRES_URL}")

    Base.metadata.create_all(bind=engine, tables=TABLES)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine, tables=list(reversed(TABLES)))
        engine.dispose()


def _product(session, **overrides) -> ReleaseProduct:
    fields = dict(
        source_catalogue="bandai_jp",
        official_code="OP-01",
        display_name="ブースターパック ROMANCE DAWN【OP-01】",
        first_seen_name="ブースターパック ROMANCE DAWN【OP-01】",
        source_series_id="550101",
        source_url="https://www.onepiece-cardgame.com/products/boosters/op01.php",
        verification_status="verified",
    )
    fields.update(overrides)
    product = ReleaseProduct(**fields)
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


def _print(session, product_id=None, card_code="OP01-PG-001") -> CardPrint:
    card = CanonicalCard(
        card_code=card_code,
        name_en="Monkey D. Luffy",
        original_set_code="OP-01",
        rarity="L",
        card_type="Leader",
    )
    session.add(card)
    session.commit()
    session.refresh(card)

    print_row = CardPrint(
        canonical_card_id=card.id,
        language="jp",
        treatment="base",
        release_product_code="OP-01",
        artwork_key="art-pg-1",
        verification_status="verified",
        release_product_id=product_id,
    )
    session.add(print_row)
    session.commit()
    session.refresh(print_row)
    return print_row


def test_jp_and_en_op01_products_can_coexist(postgres_session):
    """The dangerous future case, on a real database: a globally unique
    official_code would reject the second insert and force an importer to
    reuse the JP row for EN prints."""
    jp = _product(postgres_session)
    en = _product(
        postgres_session,
        source_catalogue="bandai_en",
        display_name="BOOSTER PACK -ROMANCE DAWN- [OP-01]",
        first_seen_name="BOOSTER PACK -ROMANCE DAWN- [OP-01]",
        source_series_id="569101",
        source_url="https://en.onepiece-cardgame.com/products/boosters/op01.php",
    )

    assert jp.id != en.id
    codes = postgres_session.execute(
        text(
            "SELECT source_catalogue, official_code FROM release_products "
            "ORDER BY source_catalogue"
        )
    ).fetchall()
    assert codes == [("bandai_en", "OP-01"), ("bandai_jp", "OP-01")]


def test_duplicate_code_within_one_catalogue_is_still_rejected(postgres_session):
    _product(postgres_session)

    with pytest.raises(IntegrityError):
        _product(postgres_session, source_series_id="550199")


def test_two_uncoded_products_do_not_collide_on_null(postgres_session):
    first = _product(postgres_session, official_code=None, source_series_id="550301")
    second = _product(postgres_session, official_code=None, source_series_id="550302")

    assert first.id != second.id


def test_print_referencing_a_missing_product_is_rejected(postgres_session):
    with pytest.raises(IntegrityError):
        _print(postgres_session, product_id=987654)


def test_deleting_a_product_with_an_attached_print_is_rejected(postgres_session):
    product = _product(postgres_session)
    _print(postgres_session, product_id=product.id)

    with pytest.raises(IntegrityError):
        postgres_session.execute(
            text("DELETE FROM release_products WHERE id = :id"), {"id": product.id}
        )
        postgres_session.commit()


def test_deleting_a_product_cascades_to_its_aliases(postgres_session):
    """An alias is a name *of* a product and cannot outlive one. RESTRICT on
    card_prints still means a referenced product can't be deleted at all."""
    product = _product(postgres_session)
    postgres_session.add(
        ReleaseProductAlias(
            product_id=product.id,
            alias_name="ROMANCE DAWN",
            alias_kind="bandai_official",
            source_url="https://www.onepiece-cardgame.com/products/boosters/op01.php",
        )
    )
    postgres_session.commit()

    postgres_session.execute(
        text("DELETE FROM release_products WHERE id = :id"), {"id": product.id}
    )
    postgres_session.commit()

    assert postgres_session.query(ReleaseProductAlias).count() == 0


def test_alias_referencing_a_missing_product_is_rejected(postgres_session):
    with pytest.raises(IntegrityError):
        postgres_session.add(
            ReleaseProductAlias(
                product_id=987654,
                alias_name="ROMANCE DAWN",
                alias_kind="bandai_official",
                source_url="https://www.onepiece-cardgame.com/products/boosters/op01.php",
            )
        )
        postgres_session.commit()
