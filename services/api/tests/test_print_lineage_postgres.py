"""PostgreSQL-backed coverage for print-lineage behavior that SQLite can't
exercise faithfully - same rationale as test_canonical_cards_postgres.py:
this test suite's SQLite engine never enables PRAGMA foreign_keys, so
neither ON DELETE RESTRICT nor the composite ForeignKeyConstraint on
price_observations would actually be enforced there even if broken.

Points at TEST_POSTGRES_URL (falling back to a local disposable instance on
port 5544) and skips outright if no server answers, so the rest of the
suite (which runs on sqlite) is unaffected."""

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  (registers all models on Base.metadata)
from app.db import Base
from app.models import Card, CanonicalCard, CardPrint, PriceObservation, Source, SourceCardMapping

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

    # Full schema (not just the tables this file touches directly) - several
    # of them (price_observations -> raw_snapshots/snkrdunk_candidates, ...)
    # carry FKs to tables outside this tranche's scope.
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
        card_code="OP01-201",
        name_en="Nico Robin",
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
        language="en",
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
        card_code="OP01-201",
        name_en="Nico Robin",
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


def make_mapping(session, card, source, **overrides) -> SourceCardMapping:
    fields = dict(card_id=card.id, source_id=source.id, source_card_id="ext-1")
    fields.update(overrides)
    mapping = SourceCardMapping(**fields)
    session.add(mapping)
    session.commit()
    session.refresh(mapping)
    return mapping


def make_observation(session, card, source, **overrides) -> PriceObservation:
    fields = dict(card_id=card.id, source_id=source.id, price_type="market", price_jpy=1000)
    fields.update(overrides)
    observation = PriceObservation(**fields)
    session.add(observation)
    session.commit()
    session.refresh(observation)
    return observation


def test_observation_mismatched_mapping_and_print_is_rejected(postgres_session):
    card = make_legacy_card(postgres_session)
    source = make_source(postgres_session)
    canonical_card = make_canonical_card(postgres_session)
    print_a = make_print(postgres_session, canonical_card, treatment="base")
    print_b = make_print(postgres_session, canonical_card, treatment="parallel")
    mapping = make_mapping(postgres_session, card, source, card_print_id=print_a.id)

    with pytest.raises(IntegrityError):
        make_observation(
            postgres_session,
            card,
            source,
            source_card_mapping_id=mapping.id,
            card_print_id=print_b.id,
        )
    postgres_session.rollback()


def test_observation_with_only_source_card_mapping_id_is_rejected(postgres_session):
    card = make_legacy_card(postgres_session)
    source = make_source(postgres_session)
    canonical_card = make_canonical_card(postgres_session)
    print_row = make_print(postgres_session, canonical_card)
    mapping = make_mapping(postgres_session, card, source, card_print_id=print_row.id)

    with pytest.raises(IntegrityError):
        make_observation(postgres_session, card, source, source_card_mapping_id=mapping.id)
    postgres_session.rollback()


def test_observation_with_only_card_print_id_is_rejected(postgres_session):
    card = make_legacy_card(postgres_session)
    source = make_source(postgres_session)
    canonical_card = make_canonical_card(postgres_session)
    print_row = make_print(postgres_session, canonical_card)

    with pytest.raises(IntegrityError):
        make_observation(postgres_session, card, source, card_print_id=print_row.id)
    postgres_session.rollback()


def test_deleting_a_referenced_card_print_is_rejected(postgres_session):
    card = make_legacy_card(postgres_session)
    source = make_source(postgres_session)
    canonical_card = make_canonical_card(postgres_session)
    print_row = make_print(postgres_session, canonical_card)
    mapping = make_mapping(postgres_session, card, source, card_print_id=print_row.id)
    make_observation(
        postgres_session,
        card,
        source,
        source_card_mapping_id=mapping.id,
        card_print_id=print_row.id,
    )

    postgres_session.delete(print_row)
    with pytest.raises(IntegrityError):
        postgres_session.commit()
    postgres_session.rollback()

    reloaded_print = postgres_session.get(CardPrint, print_row.id)
    assert reloaded_print is not None


def test_observation_can_reference_the_same_mapping_and_print(postgres_session):
    card = make_legacy_card(postgres_session)
    source = make_source(postgres_session)
    canonical_card = make_canonical_card(postgres_session)
    print_row = make_print(postgres_session, canonical_card)
    mapping = make_mapping(postgres_session, card, source, card_print_id=print_row.id)

    observation = make_observation(
        postgres_session,
        card,
        source,
        source_card_mapping_id=mapping.id,
        card_print_id=print_row.id,
    )

    assert observation.source_card_mapping_id == mapping.id
    assert observation.card_print_id == print_row.id


def test_legacy_observation_with_both_lineage_fields_null_succeeds(postgres_session):
    card = make_legacy_card(postgres_session)
    source = make_source(postgres_session)

    observation = make_observation(postgres_session, card, source)

    assert observation.source_card_mapping_id is None
    assert observation.card_print_id is None


def test_observation_correct_mapping_print_but_wrong_source_id_is_rejected(postgres_session):
    card = make_legacy_card(postgres_session)
    source = make_source(postgres_session)
    other_source = make_source(postgres_session, name="other-source")
    canonical_card = make_canonical_card(postgres_session)
    print_row = make_print(postgres_session, canonical_card)
    mapping = make_mapping(postgres_session, card, source, card_print_id=print_row.id)

    with pytest.raises(IntegrityError):
        make_observation(
            postgres_session,
            card,
            other_source,
            source_card_mapping_id=mapping.id,
            card_print_id=print_row.id,
        )
    postgres_session.rollback()


def test_observation_legacy_card_id_no_longer_has_to_match_the_mapping(postgres_session):
    """Deliberately relaxed by c9f31e2a7d04, and the reason the FK narrowed.

    card_id was dropped from the composite key because it is legacy
    compatibility rather than identity, and PostgreSQL FKs are MATCH SIMPLE:
    leaving a nullable card_id in the key would have switched the whole check
    off for print-authoritative rows. The cost is that the lineage FK no
    longer polices card_id - the print and source, which are the identity,
    are still pinned (see the two tests either side of this one)."""
    card = make_legacy_card(postgres_session)
    other_card = make_legacy_card(postgres_session, card_code="OP01-202", name_en="Other Card")
    source = make_source(postgres_session)
    canonical_card = make_canonical_card(postgres_session)
    print_row = make_print(postgres_session, canonical_card)
    mapping = make_mapping(postgres_session, card, source, card_print_id=print_row.id)

    observation = make_observation(
        postgres_session,
        other_card,
        source,
        source_card_mapping_id=mapping.id,
        card_print_id=print_row.id,
    )

    assert observation.card_id == other_card.id
    assert observation.card_print_id == print_row.id


def test_deleting_a_referenced_source_card_mapping_is_rejected(postgres_session):
    card = make_legacy_card(postgres_session)
    source = make_source(postgres_session)
    canonical_card = make_canonical_card(postgres_session)
    print_row = make_print(postgres_session, canonical_card)
    mapping = make_mapping(postgres_session, card, source, card_print_id=print_row.id)
    make_observation(
        postgres_session,
        card,
        source,
        source_card_mapping_id=mapping.id,
        card_print_id=print_row.id,
    )

    postgres_session.delete(mapping)
    with pytest.raises(IntegrityError):
        postgres_session.commit()
    postgres_session.rollback()

    reloaded_mapping = postgres_session.get(SourceCardMapping, mapping.id)
    assert reloaded_mapping is not None


def test_changing_a_used_mappings_card_print_id_is_rejected(postgres_session):
    card = make_legacy_card(postgres_session)
    source = make_source(postgres_session)
    canonical_card = make_canonical_card(postgres_session)
    print_a = make_print(postgres_session, canonical_card, treatment="base")
    print_b = make_print(postgres_session, canonical_card, treatment="parallel")
    mapping = make_mapping(postgres_session, card, source, card_print_id=print_a.id)
    make_observation(
        postgres_session,
        card,
        source,
        source_card_mapping_id=mapping.id,
        card_print_id=print_a.id,
    )

    mapping.card_print_id = print_b.id
    postgres_session.add(mapping)
    with pytest.raises(IntegrityError):
        postgres_session.commit()
    postgres_session.rollback()


def test_changing_a_used_mappings_card_id_is_allowed(postgres_session):
    """Same relaxation as above, from the mapping side: repointing a used
    mapping's legacy card no longer breaks the composite key, because card_id
    is not in it. Repointing its card_print_id or source_id still does - see
    the tests either side."""
    card = make_legacy_card(postgres_session)
    other_card = make_legacy_card(postgres_session, card_code="OP01-203", name_en="Another Card")
    source = make_source(postgres_session)
    canonical_card = make_canonical_card(postgres_session)
    print_row = make_print(postgres_session, canonical_card)
    mapping = make_mapping(postgres_session, card, source, card_print_id=print_row.id)
    make_observation(
        postgres_session,
        card,
        source,
        source_card_mapping_id=mapping.id,
        card_print_id=print_row.id,
    )

    mapping.card_id = other_card.id
    postgres_session.add(mapping)
    postgres_session.commit()

    postgres_session.refresh(mapping)
    assert mapping.card_id == other_card.id
    assert mapping.card_print_id == print_row.id


def test_changing_a_used_mappings_source_id_is_rejected(postgres_session):
    card = make_legacy_card(postgres_session)
    source = make_source(postgres_session)
    other_source = make_source(postgres_session, name="another-source")
    canonical_card = make_canonical_card(postgres_session)
    print_row = make_print(postgres_session, canonical_card)
    mapping = make_mapping(postgres_session, card, source, card_print_id=print_row.id)
    make_observation(
        postgres_session,
        card,
        source,
        source_card_mapping_id=mapping.id,
        card_print_id=print_row.id,
    )

    mapping.source_id = other_source.id
    postgres_session.add(mapping)
    with pytest.raises(IntegrityError):
        postgres_session.commit()
    postgres_session.rollback()
