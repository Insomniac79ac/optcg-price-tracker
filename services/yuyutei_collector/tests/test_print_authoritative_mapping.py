"""The collector must work against a mapping that names a printing and no
legacy card.

WHY THIS FILE EXISTS. The Yuyu-Tei approval path creates mappings with
`card_print_id` set and `card_id` NULL - there is nothing to derive a legacy
card from (`card_prints` links only to `canonical_cards`, and `cards` holds 25
rows against 4,316 prints). The real schema has allowed that since
c9f31e2a7d04, but this service's ORM mirror declared BOTH `card_id` columns
NOT NULL and pointed a four-column composite FK at a parent key that does not
exist. None of it emits DDL against the real database, so production was never
affected - but it meant this service's own tests could not construct the exact
row shape the approval path now produces, and so could never have caught a
real incompatibility. These tests close that blind spot.

Everything here runs against Base.metadata on SQLite, which is what the rest
of this service's tests use, so the constraints asserted are the mirror's own -
which is the point: the mirror is the thing under test.
"""

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from yuyutei_collector import models as collector_models
from yuyutei_collector.batch import select_eligible_mappings
from yuyutei_collector.db import Base
from yuyutei_collector.models import (
    CanonicalCard,
    CardPrint,
    PriceObservation,
    RawSnapshot,
    Source,
    SourceCardMapping,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    db = Session()
    yield db
    db.close()


def make_print(db, card_code="OP01-001", *, active=True, verified=True):
    canonical = CanonicalCard(card_code=card_code)
    db.add(canonical)
    db.flush()
    row = CardPrint(
        canonical_card_id=canonical.id,
        treatment="parallel",
        verification_status="verified" if verified else "unverified",
        is_active=active,
    )
    db.add(row)
    db.flush()
    return row


def make_source(db):
    source = Source(name="yuyutei", base_url="https://yuyu-tei.jp")
    db.add(source)
    db.flush()
    return source


def print_authoritative_mapping(db, source, card_print, product_id="10151"):
    """Exactly what app.services.yuyutei_candidate_approval writes: the print,
    the displayed card code, the product URL - and no legacy card."""
    mapping = SourceCardMapping(
        card_id=None,
        source_id=source.id,
        card_print_id=card_print.id,
        source_card_id="OP01-001",
        source_url=f"https://yuyu-tei.jp/sell/opc/card/op01/{product_id}",
        is_active=True,
        review_status="approved",
    )
    db.add(mapping)
    db.flush()
    return mapping


# --------------------------------------------------------------------------
# The mirror can represent the row at all
# --------------------------------------------------------------------------


def test_a_mapping_with_no_legacy_card_can_be_stored(session):
    source = make_source(session)
    card_print = make_print(session)
    mapping = print_authoritative_mapping(session, source, card_print)
    session.commit()

    stored = session.scalars(select(SourceCardMapping)).one()
    assert stored.id == mapping.id
    assert stored.card_id is None
    assert stored.card_print_id == card_print.id


@pytest.mark.parametrize(
    "table,column",
    [
        ("source_card_mappings", "card_id"),
        ("source_card_mappings", "card_print_id"),
        ("price_observations", "card_id"),
        ("price_observations", "card_print_id"),
    ],
)
def test_the_mirror_agrees_with_the_api_on_nullability(session, table, column):
    """Pinned explicitly rather than left implicit in the model text: these
    four are the columns a print-authoritative mapping actually depends on,
    and every one of them is nullable in the API-owned schema."""
    columns = {c["name"]: c for c in inspect(session.get_bind()).get_columns(table)}
    assert columns[column]["nullable"] is True, f"{table}.{column} must be nullable"


def test_the_composite_lineage_key_excludes_the_legacy_card(session):
    """card_id in the key would switch the whole FK off under MATCH SIMPLE for
    exactly the rows it exists to police - see the API model's comment."""
    fk = next(
        c
        for c in PriceObservation.__table__.constraints
        if getattr(c, "name", None) == "fk_price_observations_mapping_print_source"
    )
    assert [c.name for c in fk.columns] == [
        "source_card_mapping_id",
        "card_print_id",
        "source_id",
    ]
    assert "card_id" not in {c.name for c in fk.columns}
    # And the parent key it points at exists, so the constraint is real rather
    # than merely declared.
    parent = {
        tuple(sorted(col.name for col in c.columns))
        for c in SourceCardMapping.__table__.constraints
        if getattr(c, "name", None) == "uq_source_card_mappings_print_lineage_identity"
    }
    assert parent == {("card_print_id", "id", "source_id")}


# --------------------------------------------------------------------------
# The collector's own eligibility query accepts it
# --------------------------------------------------------------------------


def test_the_batch_selects_a_print_authoritative_mapping(session):
    source = make_source(session)
    card_print = make_print(session)
    mapping = print_authoritative_mapping(session, source, card_print)
    session.commit()

    selected = select_eligible_mappings(session)
    assert [m.id for m in selected] == [mapping.id]
    # Loading it must not require the legacy pointer - the mirror used to type
    # this column non-optional, which is what made the shape unrepresentable.
    assert selected[0].card_id is None
    assert selected[0].source_card_id == "OP01-001"


def test_eligibility_still_excludes_a_mapping_with_no_print(session):
    """The fidelity fix must not widen what gets priced: a legacy card-only
    mapping is still ineligible, exactly as before."""
    source = make_source(session)
    session.add(
        SourceCardMapping(
            card_id=None,
            source_id=source.id,
            card_print_id=None,
            source_card_id="OP01-001",
            source_url="https://yuyu-tei.jp/sell/opc/card/op01/10001",
            is_active=True,
            review_status="approved",
        )
    )
    session.commit()

    assert select_eligible_mappings(session) == []


@pytest.mark.parametrize(
    "field,value",
    [("is_active", False), ("review_status", "needs_review"), ("review_status", "rejected")],
)
def test_eligibility_is_unchanged_for_every_other_reason(session, field, value):
    source = make_source(session)
    card_print = make_print(session)
    mapping = print_authoritative_mapping(session, source, card_print)
    setattr(mapping, field, value)
    session.commit()

    assert select_eligible_mappings(session) == []


@pytest.mark.parametrize("active,verified", [(False, True), (True, False)])
def test_eligibility_still_requires_an_active_verified_print(session, active, verified):
    source = make_source(session)
    card_print = make_print(session, active=active, verified=verified)
    print_authoritative_mapping(session, source, card_print)
    session.commit()

    assert select_eligible_mappings(session) == []


# --------------------------------------------------------------------------
# An observation can be written for it
# --------------------------------------------------------------------------


def test_an_observation_can_be_written_with_a_null_card_id(session):
    """The write path copies `card_id=mapping.card_id` straight through
    (writer.py), so a print-authoritative mapping produces a NULL here. Under
    the old mirror this raised IntegrityError and no test could reach it."""
    source = make_source(session)
    card_print = make_print(session)
    mapping = print_authoritative_mapping(session, source, card_print)
    snapshot = RawSnapshot(
        source_id=source.id,
        source_url=mapping.source_url,
        http_status=200,
        content_hash="a" * 64,
        raw_content="<html></html>",
    )
    session.add(snapshot)
    session.flush()

    session.add(
        PriceObservation(
            card_id=mapping.card_id,
            source_id=mapping.source_id,
            price_type="sell",
            price_jpy=12800,
            stock_status="in_stock",
            raw_snapshot_id=snapshot.id,
            source_card_mapping_id=mapping.id,
            card_print_id=mapping.card_print_id,
        )
    )
    session.commit()

    observation = session.scalars(select(PriceObservation)).one()
    assert observation.card_id is None
    assert observation.card_print_id == card_print.id
    assert observation.source_card_mapping_id == mapping.id


def test_the_lineage_pair_invariant_is_enforced(session):
    """Half a lineage - a mapping id with no print, or a print with no mapping
    - is what the real CHECK forbids, and the mirror now forbids it too."""
    source = make_source(session)
    card_print = make_print(session)
    mapping = print_authoritative_mapping(session, source, card_print)
    session.commit()

    session.add(
        PriceObservation(
            card_id=None,
            source_id=source.id,
            price_type="sell",
            price_jpy=100,
            source_card_mapping_id=mapping.id,
            card_print_id=None,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_a_legacy_observation_carrying_neither_lineage_field_is_still_allowed(session):
    source = make_source(session)
    session.add(
        PriceObservation(
            card_id=None,
            source_id=source.id,
            price_type="sell",
            price_jpy=100,
            source_card_mapping_id=None,
            card_print_id=None,
        )
    )
    session.commit()
    assert session.scalars(select(PriceObservation)).one().card_print_id is None


# --------------------------------------------------------------------------
# The mirror still writes no DDL of its own against the real database
# --------------------------------------------------------------------------


def test_the_mirror_declares_no_migration(session):
    """This service owns no migrations - the API emits every table's DDL. The
    mirror is a read/write view onto them, so a change here must never be
    mistaken for a schema change."""
    import pathlib

    # parents[1] is services/yuyutei_collector - the service root, not the
    # whole services/ tree, which of course contains the API's migrations.
    service_root = pathlib.Path(collector_models.__file__).resolve().parents[1]
    assert service_root.name == "yuyutei_collector"
    assert not (service_root / "alembic").exists()
    assert not list(service_root.rglob("versions/*.py"))
