"""Read-path readiness for a future card_prints.treatment = NULL.

The real column is still NOT NULL and this tranche adds no migration, so the
future state is reproduced here in an isolated SQLite engine whose DDL is a
copy of the app's own metadata with that one column made nullable. Nothing
about app.models or the real schema changes - SQLAlchemy's `nullable` flag is
DDL-only, so the ORM writes a None happily once the database allows it.

What must hold when that day comes: no crash, no synthetic facet, no invented
label - and today's non-null rows must behave exactly as they do now."""

import pytest
from sqlalchemy import MetaData, create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import CanonicalCard, CardPrint
from app.schemas import CardPrintSiblingOut, PrintCatalogueFacetsOut, PrintCatalogueItemOut
from app.services.print_catalogue import (
    get_print_catalogue_facets,
    list_print_catalogue,
)


@pytest.fixture()
def future_session():
    """A database shaped like the one a later phase will produce: identical
    to the app's metadata except card_prints.treatment is nullable."""
    future_metadata = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(future_metadata)

    card_prints = future_metadata.tables["card_prints"]
    card_prints.c.treatment.nullable = True
    # ck_card_prints_verified_requires_fields still demands a non-null,
    # non-"unknown" treatment on a verified print. Relaxing it is a later
    # phase's migration, not this tranche's - dropping it from this *copied*
    # metadata is how the fixture reaches the future state without touching
    # the real constraint, which test_the_real_schema_is_untouched pins.
    for constraint in list(card_prints.constraints):
        if constraint.name == "ck_card_prints_verified_requires_fields":
            card_prints.constraints.discard(constraint)

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    future_metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _card(session, card_code: str) -> CanonicalCard:
    card = CanonicalCard(
        card_code=card_code,
        name_en=f"Card {card_code}",
        original_set_code="OP-01",
        rarity="R",
        card_type="Character",
    )
    session.add(card)
    session.commit()
    session.refresh(card)
    return card


def _print(session, card: CanonicalCard, treatment, **overrides) -> CardPrint:
    fields = dict(
        canonical_card_id=card.id,
        language="jp",
        treatment=treatment,
        verification_status="verified",
        release_product_code="OP-01",
        artwork_key=f"art-{card.card_code}-{treatment}",
        image_url=f"https://images.example.com/{card.card_code}.png",
    )
    fields.update(overrides)
    print_row = CardPrint(**fields)
    session.add(print_row)
    session.commit()
    session.refresh(print_row)
    return print_row


def _population(session):
    """One card with three printings: normal, parallel, and unclassified."""
    card = _card(session, "OP01-013")
    return {
        "normal": _print(session, card, "normal"),
        "parallel": _print(session, card, "parallel"),
        "unclassified": _print(session, card, None),
    }


def test_the_future_database_really_accepts_a_null_treatment(future_session):
    prints = _population(future_session)

    stored = future_session.get(CardPrint, prints["unclassified"].id)
    assert stored.treatment is None
    assert stored.verification_status == "verified"


def test_null_treatment_never_enters_the_facets(future_session):
    _population(future_session)

    facets = get_print_catalogue_facets(future_session)

    assert facets.treatments == ["normal", "parallel"]
    assert None not in facets.treatments
    # And no synthetic bucket was invented to stand in for it.
    assert not any(
        value.lower() in {"unclassified", "other", "unknown", "none", ""}
        for value in facets.treatments
    )


def test_facets_stay_a_list_of_strings(future_session):
    _population(future_session)

    facets = get_print_catalogue_facets(future_session)

    PrintCatalogueFacetsOut.model_validate(facets.model_dump())
    assert all(isinstance(value, str) for value in facets.treatments)


def test_catalogue_listing_does_not_crash_and_orders_null_last(future_session):
    prints = _population(future_session)

    items, total = list_print_catalogue(future_session, sort="card_code", limit=50, offset=0)

    assert total == 3
    ordered_ids = [item.card_print_id for item in items]
    assert ordered_ids == [
        prints["normal"].id,
        prints["parallel"].id,
        prints["unclassified"].id,
    ], "an unclassified print must sort after its classified siblings, deterministically"
    assert items[-1].treatment is None


def test_treatment_filter_only_ever_returns_that_explicit_value(future_session):
    prints = _population(future_session)

    for value in ("normal", "parallel"):
        items, total = list_print_catalogue(
            future_session, treatment=value, sort="card_code", limit=50, offset=0
        )
        assert total == 1
        assert [item.card_print_id for item in items] == [prints[value].id]
        assert all(item.treatment == value for item in items)


def test_no_filter_value_can_select_the_unclassified_print(future_session):
    """There is no filter string that returns a NULL-treatment row - it is
    reachable only by not filtering on treatment at all."""
    _population(future_session)

    for value in ("", "null", "none", "unclassified", "other"):
        items, _ = list_print_catalogue(
            future_session, treatment=value or None, sort="card_code", limit=50, offset=0
        )
        if value:
            assert items == []
        else:
            assert len(items) == 3


def test_other_sorts_tolerate_a_null_treatment(future_session):
    _population(future_session)

    for sort in ("name", "updated", "index_desc", "index_asc"):
        items, total = list_print_catalogue(future_session, sort=sort, limit=50, offset=0)
        assert total == 3
        assert len(items) == 3


def test_catalogue_item_serializes_a_null_treatment(future_session):
    _population(future_session)

    items, _ = list_print_catalogue(future_session, sort="card_code", limit=50, offset=0)
    payload = [PrintCatalogueItemOut.model_validate(item.model_dump()).model_dump() for item in items]

    assert payload[-1]["treatment"] is None
    assert [row["treatment"] for row in payload] == ["normal", "parallel", None]


def test_sibling_schema_serializes_a_null_treatment():
    sibling = CardPrintSiblingOut(
        card_print_id=7,
        treatment=None,
        language="jp",
        verification_status="verified",
        image_url=None,
    )

    assert sibling.model_dump()["treatment"] is None


def test_ordering_sql_states_nulls_last_explicitly():
    """sqlite and PostgreSQL disagree on where NULLs land by default, so the
    ordering must say which it wants rather than inherit the engine's."""
    from app.services.print_catalogue import CardPrint as CatalogueCardPrint

    compiled = str(
        select(CatalogueCardPrint.id)
        .order_by(CatalogueCardPrint.treatment.asc().nulls_last())
        .compile()
    )
    assert "NULLS LAST" in compiled


def test_the_real_schema_is_untouched_by_this_tranche():
    """The fixture above simulates a future database. The real one must not
    have moved: treatment is still NOT NULL, the verified-requires-fields
    check still names it, and the verified unique index still keys on it."""
    card_prints = Base.metadata.tables["card_prints"]

    assert card_prints.c.treatment.nullable is False

    check = next(
        c
        for c in card_prints.constraints
        if c.name == "ck_card_prints_verified_requires_fields"
    )
    assert "treatment IS NOT NULL" in str(check.sqltext)

    index = next(
        i for i in card_prints.indexes if i.name == "uq_card_prints_active_verified_identity"
    )
    assert [c.name for c in index.columns] == [
        "canonical_card_id",
        "language",
        "treatment",
        "release_product_code",
        "artwork_key",
    ]
