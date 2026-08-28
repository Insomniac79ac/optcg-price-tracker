"""PostgreSQL-backed coverage for the constraint that c9f31e2a7d04 narrows:
fk_price_observations_mapping_print_source.

This is the half of the tranche SQLite cannot test. The migration drops
card_id from the composite key precisely because PostgreSQL foreign keys
default to MATCH SIMPLE - had card_id stayed in the key, a print-authoritative
observation (card_id NULL) would have skipped the check entirely and could
have named a mapping belonging to another print or another source. So every
mismatch below is asserted with card_id NULL, which is the case the old key
would have let through.

Points at TEST_POSTGRES_URL (falling back to a local disposable instance on
port 5544) and skips outright if no server answers."""

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.db import Base
from app.models import CanonicalCard, Card, CardPrint, PriceObservation, Source, SourceCardMapping

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

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def make_canonical_card(session, **overrides) -> CanonicalCard:
    fields = dict(
        card_code="OP01-401",
        name_en="Sanji",
        original_set_code="OP01",
        rarity="R",
        card_type="Character",
    )
    fields.update(overrides)
    card = CanonicalCard(**fields)
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


def make_print(session, canonical_card, **overrides) -> CardPrint:
    fields = dict(
        canonical_card_id=canonical_card.id,
        language="jp",
        treatment="base",
        verification_status="unverified",
    )
    fields.update(overrides)
    print_row = CardPrint(**fields)
    session.add(print_row)
    session.commit()
    session.refresh(print_row)
    return print_row


def make_legacy_card(session, **overrides) -> Card:
    fields = dict(
        card_code="OP01-401",
        name_en="Sanji",
        set_code="OP01",
        rarity="R",
        language="en",
    )
    fields.update(overrides)
    card = Card(**fields)
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


def make_source(session, **overrides) -> Source:
    fields = dict(name="test-source", base_url="https://example.test")
    fields.update(overrides)
    source = Source(**fields)
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


def make_mapping(session, **overrides) -> SourceCardMapping:
    fields = dict(source_card_id="ext-1")
    fields.update(overrides)
    mapping = SourceCardMapping(**fields)
    session.add(mapping)
    session.commit()
    session.refresh(mapping)
    return mapping


def make_observation(session, **overrides) -> PriceObservation:
    fields = dict(price_type="market", price_jpy=1000)
    fields.update(overrides)
    observation = PriceObservation(**fields)
    session.add(observation)
    session.commit()
    session.refresh(observation)
    return observation


@pytest.fixture()
def lineage(postgres_session):
    """A print-authoritative mapping - no legacy card at all - plus a second
    print and a second source to mismatch against."""
    source = make_source(postgres_session)
    other_source = make_source(postgres_session, name="other-source")
    canonical = make_canonical_card(postgres_session)
    print_a = make_print(postgres_session, canonical, treatment="base")
    print_b = make_print(postgres_session, canonical, treatment="parallel")
    mapping = make_mapping(postgres_session, source_id=source.id, card_print_id=print_a.id)
    assert mapping.card_id is None
    return {
        "session": postgres_session,
        "source": source,
        "other_source": other_source,
        "print_a": print_a,
        "print_b": print_b,
        "mapping": mapping,
    }


def test_null_card_id_observation_matching_its_mapping_is_accepted(lineage):
    """The happy path the tranche exists to permit: a priced row identified
    only by mapping/print/source, with no legacy Card behind it."""
    session = lineage["session"]

    observation = make_observation(
        session,
        source_id=lineage["source"].id,
        source_card_mapping_id=lineage["mapping"].id,
        card_print_id=lineage["print_a"].id,
    )

    assert observation.card_id is None
    assert observation.source_card_mapping_id == lineage["mapping"].id
    assert observation.card_print_id == lineage["print_a"].id


def test_null_card_id_observation_with_wrong_card_print_id_is_rejected(lineage):
    session = lineage["session"]

    with pytest.raises(IntegrityError) as excinfo:
        make_observation(
            session,
            source_id=lineage["source"].id,
            source_card_mapping_id=lineage["mapping"].id,
            card_print_id=lineage["print_b"].id,
        )
    assert "fk_price_observations_mapping_print_source" in str(excinfo.value)
    session.rollback()


def test_null_card_id_observation_with_wrong_source_id_is_rejected(lineage):
    session = lineage["session"]

    with pytest.raises(IntegrityError) as excinfo:
        make_observation(
            session,
            source_id=lineage["other_source"].id,
            source_card_mapping_id=lineage["mapping"].id,
            card_print_id=lineage["print_a"].id,
        )
    assert "fk_price_observations_mapping_print_source" in str(excinfo.value)
    session.rollback()


def test_null_card_id_observation_naming_a_nonexistent_mapping_is_rejected(lineage):
    session = lineage["session"]

    with pytest.raises(IntegrityError) as excinfo:
        make_observation(
            session,
            source_id=lineage["source"].id,
            source_card_mapping_id=lineage["mapping"].id + 10_000,
            card_print_id=lineage["print_a"].id,
        )
    assert "fk_price_observations_mapping_print_source" in str(excinfo.value)
    session.rollback()


def test_null_card_id_observation_with_mapping_but_no_print_is_rejected(lineage):
    """The paired CHECK, not the FK: naming a mapping without naming a print
    is still refused now that card_id is gone from the key."""
    session = lineage["session"]

    with pytest.raises(IntegrityError) as excinfo:
        make_observation(
            session,
            source_id=lineage["source"].id,
            source_card_mapping_id=lineage["mapping"].id,
        )
    assert "ck_price_observations_lineage_paired" in str(excinfo.value)
    session.rollback()


def test_a_mapping_may_carry_no_legacy_card_at_all(lineage):
    """The unique key backing the FK is (id, card_print_id, source_id), so a
    NULL card_id neither blocks the mapping nor disables the key."""
    session = lineage["session"]
    reloaded = session.get(SourceCardMapping, lineage["mapping"].id)

    assert reloaded.card_id is None
    assert reloaded.card_print_id == lineage["print_a"].id
