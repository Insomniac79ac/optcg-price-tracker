from app.models import Card, Source, SourceCardMapping
from app.seed import DEMO_CARDS, DEMO_MAPPINGS, SOURCES, seed


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
