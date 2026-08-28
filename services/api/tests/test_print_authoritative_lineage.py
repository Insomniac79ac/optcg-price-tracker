"""Coverage for c9f31e2a7d04, which demotes `card_id` from identity to legacy
compatibility on both source_card_mappings and price_observations.

What SQLite can prove faithfully is exactly the nullability contract and the
both-null-or-both-set pairing CHECK: a mapping or observation may now carry no
legacy Card at all, while legacy rows that do carry one stay valid untouched.

What it cannot prove lives in test_print_authoritative_lineage_postgres.py -
this suite's SQLite engine never enables PRAGMA foreign_keys, so the composite
FK that keeps a NULL-card_id observation pinned to its mapping's print and
source would silently pass here even if it had been switched off. That FK is
the whole point of the migration (see its docstring on MATCH SIMPLE), so it is
proven against a real server, not here."""

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import CanonicalCard, Card, CardPrint, PriceObservation, Source, SourceCardMapping


def make_canonical_card(db_session, **overrides) -> CanonicalCard:
    fields = dict(
        card_code="OP01-301",
        name_en="Trafalgar Law",
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
        language="jp",
        treatment="base",
        # Unverified keeps this fixture minimal: the constraints under test
        # are the lineage ones, not ck_card_prints_verified_requires_fields.
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
        card_code="OP01-301",
        name_en="Trafalgar Law",
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


def make_mapping(db_session, **overrides) -> SourceCardMapping:
    fields = dict(source_card_id="ext-1")
    fields.update(overrides)
    mapping = SourceCardMapping(**fields)
    db_session.add(mapping)
    db_session.commit()
    db_session.refresh(mapping)
    return mapping


def make_observation(db_session, **overrides) -> PriceObservation:
    fields = dict(price_type="market", price_jpy=1000)
    fields.update(overrides)
    observation = PriceObservation(**fields)
    db_session.add(observation)
    db_session.commit()
    db_session.refresh(observation)
    return observation


# --- source_card_mappings: card_id is now optional -------------------------


def test_legacy_mapping_with_card_id_and_no_print_stays_valid(db_session):
    """The 74 mappings that exist today are card_id-only. Nothing about this
    migration may invalidate them."""
    card = make_legacy_card(db_session)
    source = make_source(db_session)

    mapping = make_mapping(db_session, card_id=card.id, source_id=source.id)

    assert mapping.card_id == card.id
    assert mapping.card_print_id is None


def test_print_authoritative_mapping_with_no_legacy_card_is_valid(db_session):
    source = make_source(db_session)
    print_row = make_print(db_session, make_canonical_card(db_session))

    mapping = make_mapping(db_session, source_id=source.id, card_print_id=print_row.id)

    assert mapping.card_id is None
    assert mapping.card_print_id == print_row.id


# --- price_observations: card_id is now optional ---------------------------


def test_legacy_observation_with_card_id_and_no_lineage_stays_valid(db_session):
    card = make_legacy_card(db_session)
    source = make_source(db_session)

    observation = make_observation(db_session, card_id=card.id, source_id=source.id)

    assert observation.card_id == card.id
    assert observation.source_card_mapping_id is None
    assert observation.card_print_id is None


def test_print_authoritative_observation_with_no_legacy_card_is_valid(db_session):
    source = make_source(db_session)
    print_row = make_print(db_session, make_canonical_card(db_session))
    mapping = make_mapping(db_session, source_id=source.id, card_print_id=print_row.id)

    observation = make_observation(
        db_session,
        source_id=source.id,
        source_card_mapping_id=mapping.id,
        card_print_id=print_row.id,
    )

    assert observation.card_id is None
    assert observation.source_card_mapping_id == mapping.id
    assert observation.card_print_id == print_row.id
    assert observation.source_id == source.id


def test_null_card_id_does_not_exempt_an_observation_from_the_paired_check(db_session):
    """Dropping card_id from the FK must not have loosened the CHECK as well:
    naming a mapping without naming a print is still rejected, card_id or no
    card_id."""
    source = make_source(db_session)
    print_row = make_print(db_session, make_canonical_card(db_session))
    mapping = make_mapping(db_session, source_id=source.id, card_print_id=print_row.id)

    with pytest.raises(IntegrityError):
        make_observation(db_session, source_id=source.id, source_card_mapping_id=mapping.id)
