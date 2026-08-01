"""Coverage for the additive print-lineage columns on source_card_mappings
(card_print_id) and price_observations (source_card_mapping_id,
card_print_id) that SQLite can exercise faithfully - the both-null-or-both-
set pairing is a plain CHECK constraint, which SQLite enforces the same as
PostgreSQL. Scenarios that depend on real foreign-key enforcement (the
mapping/print mismatch, the ON DELETE RESTRICT on a referenced CardPrint)
live in test_print_lineage_postgres.py instead - SQLite doesn't enable FK
enforcement in this test suite (no PRAGMA foreign_keys=ON in app.db/
conftest), so those would silently pass here even if broken."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import CanonicalCard, Card, CardPrint, PriceObservation, Source, SourceCardMapping


def make_canonical_card(db_session, **overrides) -> CanonicalCard:
    fields = dict(
        card_code="OP01-101",
        name_en="Roronoa Zoro",
        original_set_code="OP01",
        rarity="SR",
        card_type="Character",
    )
    fields.update(overrides)
    card = CanonicalCard(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_print(db_session, canonical_card, **overrides) -> CardPrint:
    fields = dict(
        canonical_card_id=canonical_card.id,
        language="en",
        treatment="base",
        verification_status="unverified",
    )
    fields.update(overrides)
    print_row = CardPrint(**fields)
    db_session.add(print_row)
    db_session.commit()
    db_session.refresh(print_row)
    return print_row


def make_legacy_card(db_session, **overrides) -> Card:
    fields = dict(
        card_code="OP01-101",
        name_en="Roronoa Zoro",
        set_code="OP01",
        rarity="SR",
        language="en",
    )
    fields.update(overrides)
    card = Card(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_source(db_session, **overrides) -> Source:
    fields = dict(name="test-source", base_url="https://example.test")
    fields.update(overrides)
    source = Source(**fields)
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def make_mapping(db_session, card, source, **overrides) -> SourceCardMapping:
    fields = dict(
        card_id=card.id,
        source_id=source.id,
        source_card_id="ext-1",
    )
    fields.update(overrides)
    mapping = SourceCardMapping(**fields)
    db_session.add(mapping)
    db_session.commit()
    db_session.refresh(mapping)
    return mapping


def make_observation(db_session, card, source, **overrides) -> PriceObservation:
    fields = dict(
        card_id=card.id,
        source_id=source.id,
        price_type="market",
        price_jpy=1000,
    )
    fields.update(overrides)
    observation = PriceObservation(**fields)
    db_session.add(observation)
    db_session.commit()
    db_session.refresh(observation)
    return observation


def test_legacy_source_card_mapping_keeps_card_print_id_null(db_session):
    card = make_legacy_card(db_session)
    source = make_source(db_session)

    mapping = make_mapping(db_session, card, source)

    assert mapping.card_print_id is None
    assert mapping.card_id == card.id


def test_legacy_price_observation_keeps_both_lineage_fields_null(db_session):
    card = make_legacy_card(db_session)
    source = make_source(db_session)

    observation = make_observation(db_session, card, source)

    assert observation.source_card_mapping_id is None
    assert observation.card_print_id is None
    assert observation.card_id == card.id


def test_mapping_can_reference_a_card_print(db_session):
    card = make_legacy_card(db_session)
    source = make_source(db_session)
    canonical_card = make_canonical_card(db_session)
    print_row = make_print(db_session, canonical_card)

    mapping = make_mapping(db_session, card, source, card_print_id=print_row.id)

    assert mapping.card_print_id == print_row.id
    assert mapping.card_print.id == print_row.id


def test_observation_can_reference_the_same_mapping_and_print(db_session):
    card = make_legacy_card(db_session)
    source = make_source(db_session)
    canonical_card = make_canonical_card(db_session)
    print_row = make_print(db_session, canonical_card)
    mapping = make_mapping(db_session, card, source, card_print_id=print_row.id)

    observation = make_observation(
        db_session,
        card,
        source,
        source_card_mapping_id=mapping.id,
        card_print_id=print_row.id,
    )

    assert observation.source_card_mapping_id == mapping.id
    assert observation.card_print_id == print_row.id


def test_observation_with_only_source_card_mapping_id_is_rejected(db_session):
    card = make_legacy_card(db_session)
    source = make_source(db_session)
    canonical_card = make_canonical_card(db_session)
    print_row = make_print(db_session, canonical_card)
    mapping = make_mapping(db_session, card, source, card_print_id=print_row.id)

    with pytest.raises(IntegrityError):
        make_observation(db_session, card, source, source_card_mapping_id=mapping.id)


def test_observation_with_only_card_print_id_is_rejected(db_session):
    card = make_legacy_card(db_session)
    source = make_source(db_session)
    canonical_card = make_canonical_card(db_session)
    print_row = make_print(db_session, canonical_card)

    with pytest.raises(IntegrityError):
        make_observation(db_session, card, source, card_print_id=print_row.id)
