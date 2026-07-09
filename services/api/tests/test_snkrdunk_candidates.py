import pytest

from app.models import Card, SnkrdunkCandidate, Source, SourceCardMapping
from app.seed import DEMO_CARDS, SOURCES


@pytest.fixture()
def seeded_db(db_session):
    for data in SOURCES:
        db_session.add(Source(**data))
    for data in DEMO_CARDS:
        db_session.add(Card(**data))
    db_session.commit()
    return db_session


@pytest.fixture()
def candidate(seeded_db):
    row = SnkrdunkCandidate(
        source_url="https://snkrdunk.com/cards/example-1",
        title="OP01-001 Monkey D. Luffy L",
        price_jpy=1500,
        listing_count=3,
        condition_label="near_mint",
        detected_card_code="OP01-001",
        match_status="needs_review",
    )
    seeded_db.add(row)
    seeded_db.commit()
    seeded_db.refresh(row)
    return row


def test_list_candidates_empty(client, seeded_db):
    response = client.get("/snkrdunk/candidates")
    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "total": 0, "limit": 100, "offset": 0}


def test_list_candidates_returns_seeded_candidate(client, candidate):
    response = client.get("/snkrdunk/candidates")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == candidate.id
    assert item["source_url"] == candidate.source_url
    assert item["match_status"] == "needs_review"
    assert item["matched_card"] is None


def test_list_candidates_filters_by_status(client, candidate):
    response = client.get("/snkrdunk/candidates", params={"status": "pending"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []

    response = client.get("/snkrdunk/candidates", params={"status": "needs_review"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1


def test_list_candidates_rejects_invalid_status(client, candidate):
    response = client.get("/snkrdunk/candidates", params={"status": "bogus"})
    assert response.status_code == 400


def test_list_candidates_pagination(client, seeded_db):
    for i in range(5):
        seeded_db.add(
            SnkrdunkCandidate(
                source_url=f"https://snkrdunk.com/cards/example-{i}",
                title=f"Candidate {i}",
            )
        )
    seeded_db.commit()

    response = client.get("/snkrdunk/candidates", params={"limit": 2, "offset": 0})
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2

    response = client.get("/snkrdunk/candidates", params={"limit": 2, "offset": 4})
    body = response.json()
    assert len(body["items"]) == 1


def test_get_candidate_returns_candidate(client, candidate):
    response = client.get(f"/snkrdunk/candidates/{candidate.id}")
    assert response.status_code == 200
    assert response.json()["id"] == candidate.id


def test_get_candidate_not_found(client, seeded_db):
    response = client.get("/snkrdunk/candidates/999999")
    assert response.status_code == 404


def test_match_candidate_creates_mapping(client, candidate, seeded_db):
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()

    response = client.post(
        f"/snkrdunk/candidates/{candidate.id}/match",
        json={"card_id": luffy.id, "manual_verified": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["match_status"] == "auto_matched"
    assert body["matched_card_id"] == luffy.id
    assert body["match_confidence"] == 1.0
    assert body["matched_card"]["id"] == luffy.id

    seeded_db.expire_all()
    updated = seeded_db.get(SnkrdunkCandidate, candidate.id)
    assert updated.match_status == "auto_matched"
    assert updated.matched_card_id == luffy.id
    assert updated.match_confidence == 1.0

    snkrdunk_source = seeded_db.query(Source).filter_by(name="snkrdunk").one()
    mapping = (
        seeded_db.query(SourceCardMapping)
        .filter_by(card_id=luffy.id, source_id=snkrdunk_source.id)
        .one()
    )
    assert mapping.manual_verified is True
    assert mapping.source_url == candidate.source_url


def test_match_candidate_updates_existing_mapping(client, candidate, seeded_db):
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()
    snkrdunk_source = seeded_db.query(Source).filter_by(name="snkrdunk").one()

    existing = SourceCardMapping(
        card_id=luffy.id,
        source_id=snkrdunk_source.id,
        source_card_id="OP01-001",
        source_url="https://snkrdunk.com/cards/old-url",
        match_confidence=0.6,
        manual_verified=False,
    )
    seeded_db.add(existing)
    seeded_db.commit()

    response = client.post(
        f"/snkrdunk/candidates/{candidate.id}/match",
        json={"card_id": luffy.id, "manual_verified": True},
    )
    assert response.status_code == 200

    mappings = (
        seeded_db.query(SourceCardMapping)
        .filter_by(card_id=luffy.id, source_id=snkrdunk_source.id)
        .all()
    )
    assert len(mappings) == 1
    assert mappings[0].source_url == candidate.source_url
    assert mappings[0].match_confidence == 1.0
    assert mappings[0].manual_verified is True


def test_match_candidate_card_not_found(client, candidate):
    response = client.post(
        f"/snkrdunk/candidates/{candidate.id}/match",
        json={"card_id": 999999, "manual_verified": True},
    )
    assert response.status_code == 404


def test_match_candidate_not_found(client, seeded_db):
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()
    response = client.post(
        "/snkrdunk/candidates/999999/match",
        json={"card_id": luffy.id, "manual_verified": True},
    )
    assert response.status_code == 404


def test_reject_candidate(client, candidate, seeded_db):
    response = client.post(f"/snkrdunk/candidates/{candidate.id}/reject")
    assert response.status_code == 200
    assert response.json()["match_status"] == "rejected"

    seeded_db.expire_all()
    updated = seeded_db.get(SnkrdunkCandidate, candidate.id)
    assert updated.match_status == "rejected"


def test_reject_candidate_not_found(client, seeded_db):
    response = client.post("/snkrdunk/candidates/999999/reject")
    assert response.status_code == 404
