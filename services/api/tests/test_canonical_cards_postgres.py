"""PostgreSQL-backed coverage for behavior that SQLite can't exercise
faithfully - here, ON DELETE RESTRICT on card_prints.canonical_card_id.
SQLite's FK enforcement doesn't reliably distinguish RESTRICT from
NO ACTION across driver versions, so this needs a real Postgres to prove
the deletion is actually rejected at the database level.

Points at TEST_POSTGRES_URL (falling back to a local disposable instance
on port 5544 - see docs/ui/ATLAS_LOOP.md-adjacent verification notes for
how that instance was started) and skips outright if no server answers,
so the rest of the suite (which runs on sqlite) is unaffected."""

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import CanonicalCard, CardPrint, ReleaseProduct

TEST_POSTGRES_URL = os.environ.get(
    "TEST_POSTGRES_URL", "postgresql+psycopg://opcg:opcg@localhost:5544/opcg_test"
)


@pytest.fixture()
def postgres_session():
    engine = create_engine(TEST_POSTGRES_URL)
    try:
        with engine.connect():
            pass
    except OperationalError:
        engine.dispose()
        pytest.skip(f"No PostgreSQL server reachable at {TEST_POSTGRES_URL}")

    # release_products is created alongside them only because card_prints
    # now carries a (dormant, nullable) FK to it - this test is still about
    # ON DELETE RESTRICT on canonical_card_id.
    Base.metadata.create_all(
        bind=engine,
        tables=[ReleaseProduct.__table__, CanonicalCard.__table__, CardPrint.__table__],
    )
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(
            bind=engine,
            tables=[CardPrint.__table__, CanonicalCard.__table__, ReleaseProduct.__table__],
        )
        engine.dispose()


def test_deleting_canonical_card_with_attached_print_is_rejected(postgres_session):
    card = CanonicalCard(
        card_code="OP01-PG-001",
        name_en="Monkey D. Luffy",
        original_set_code="OP01",
        rarity="L",
        card_type="Leader",
    )
    postgres_session.add(card)
    postgres_session.commit()
    postgres_session.refresh(card)

    print_row = CardPrint(
        canonical_card_id=card.id,
        language="en",
        treatment="base",
        verification_status="unverified",
    )
    postgres_session.add(print_row)
    postgres_session.commit()
    postgres_session.refresh(print_row)

    postgres_session.delete(card)
    with pytest.raises(IntegrityError):
        postgres_session.commit()
    postgres_session.rollback()

    reloaded_card = postgres_session.get(CanonicalCard, card.id)
    reloaded_print = postgres_session.get(CardPrint, print_row.id)
    assert reloaded_card is not None
    assert reloaded_print is not None
    assert reloaded_print.canonical_card_id == reloaded_card.id
