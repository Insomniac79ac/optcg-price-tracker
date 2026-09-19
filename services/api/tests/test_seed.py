from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    ReleaseProduct,
    Source,
    SourceCardMapping,
)
from app.seed import DEMO_CARDS, DEMO_MAPPINGS, DEMO_PRINTS, SOURCES, seed


def test_seed_default_creates_sources_only(db_session, monkeypatch):
    monkeypatch.setattr("app.seed.SessionLocal", lambda: db_session)

    seed()

    sources = db_session.query(Source).all()
    assert {s.name for s in sources} == {s["name"] for s in SOURCES}
    assert db_session.query(Card).count() == 0
    assert db_session.query(SourceCardMapping).count() == 0


def test_seed_default_is_idempotent(db_session, monkeypatch):
    monkeypatch.setattr("app.seed.SessionLocal", lambda: db_session)

    seed()
    seed()

    assert db_session.query(Source).count() == len(SOURCES)


def test_seed_demo_data_creates_demo_cards_and_mappings(db_session, monkeypatch):
    monkeypatch.setattr("app.seed.SessionLocal", lambda: db_session)

    seed(demo_data=True)

    cards = db_session.query(Card).all()
    assert {c.card_code for c in cards} == {c["card_code"] for c in DEMO_CARDS}

    mappings = db_session.query(SourceCardMapping).all()
    assert len(mappings) == len(DEMO_MAPPINGS)
    assert all(mapping.card_print_id is not None for mapping in mappings)
    assert all(mapping.review_status == "approved" for mapping in mappings)

    prints = db_session.query(CardPrint).all()
    assert len(prints) == len(DEMO_PRINTS)
    assert all(card_print.is_active for card_print in prints)
    assert all(card_print.verification_status == "verified" for card_print in prints)
    assert db_session.query(CanonicalCard).count() == len(DEMO_PRINTS)
    assert db_session.query(ReleaseProduct).count() == 1

    for mapping in mappings:
        card_print = db_session.get(CardPrint, mapping.card_print_id)
        assert card_print is not None

    seed(demo_data=True)
    assert db_session.query(Card).count() == len(DEMO_CARDS)
    assert db_session.query(SourceCardMapping).count() == len(DEMO_MAPPINGS)
    assert db_session.query(CardPrint).count() == len(DEMO_PRINTS)
