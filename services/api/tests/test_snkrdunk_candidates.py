import pytest

from app.models import (
    CanonicalCard,
    Card,
    CardPrint,
    ReleaseProduct,
    SnkrdunkCandidate,
    Source,
    SourceCardMapping,
)
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
def luffy_print(seeded_db):
    """The exact printing OP01-001 approvals now have to name.

    Exactly one active verified print for the code, so the card code alone
    identifies it and these tests stay about the endpoints rather than about
    the ambiguity rules (those live in test_exact_print_approval.py).
    """
    product = ReleaseProduct(
        source_catalogue="jp",
        official_code="OP-01",
        display_name="OP-01",
        first_seen_name="OP-01",
        source_series_id="OP01",
        source_url="https://example.test/OP-01",
        verification_status="verified",
    )
    seeded_db.add(product)
    seeded_db.flush()
    canonical = CanonicalCard(
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        name_jp="モンキー・D・ルフィ",
        card_type="Leader",
        rarity="L",
    )
    seeded_db.add(canonical)
    seeded_db.flush()
    row = CardPrint(
        canonical_card_id=canonical.id,
        language="jp",
        release_product_code="OP-01",
        release_product_id=product.id,
        artwork_key="sha256:OP01-001-base",
        official_asset_variant="base",
        verification_status="verified",
        is_active=True,
    )
    seeded_db.add(row)
    seeded_db.commit()
    seeded_db.refresh(row)
    return row


@pytest.fixture()
def candidate(seeded_db):
    row = SnkrdunkCandidate(
        source_url="https://snkrdunk.com/en/trading-cards/900101",
        title="OP01-001 Monkey D. Luffy L",
        price_jpy=1500,
        listing_count=3,
        condition_label="near_mint",
        detected_card_code="OP01-001",
        match_status="suggested",
    )
    seeded_db.add(row)
    seeded_db.commit()
    seeded_db.refresh(row)
    return row


def test_list_candidates_empty(client, seeded_db):
    response = client.get("/snkrdunk/candidates")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "items": [],
        "total": 0,
        "limit": 100,
        "offset": 0,
        "pagination": {
            "total": 0,
            "limit": 100,
            "offset": 0,
            "has_next": False,
            "has_previous": False,
            "next_offset": None,
            "previous_offset": None,
        },
    }


def test_list_candidates_returns_seeded_candidate(client, candidate):
    response = client.get("/snkrdunk/candidates")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == candidate.id
    assert item["source_url"] == candidate.source_url
    assert item["match_status"] == "suggested"
    assert item["matched_card"] is None


def test_list_candidates_filters_by_status(client, candidate):
    response = client.get("/snkrdunk/candidates", params={"status": "unmatched"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0
    assert body["items"] == []

    response = client.get("/snkrdunk/candidates", params={"status": "suggested"})
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
                source_url=f"https://snkrdunk.com/en/trading-cards/9001{i:02d}",
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


def test_match_candidate_creates_mapping(client, candidate, seeded_db, luffy_print):
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()

    response = client.post(
        f"/snkrdunk/candidates/{candidate.id}/match",
        json={"card_id": luffy.id, "card_print_id": luffy_print.id, "manual_verified": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["match_status"] == "matched"
    assert body["matched_card_id"] == luffy.id
    assert body["match_confidence"] == 1.0
    assert body["matched_card"]["id"] == luffy.id

    seeded_db.expire_all()
    updated = seeded_db.get(SnkrdunkCandidate, candidate.id)
    assert updated.match_status == "matched"
    assert updated.matched_card_id == luffy.id
    assert updated.match_confidence == 1.0

    snkrdunk_source = seeded_db.query(Source).filter_by(name="snkrdunk").one()
    mapping = (
        seeded_db.query(SourceCardMapping)
        .filter_by(card_id=luffy.id, source_id=snkrdunk_source.id)
        .one()
    )
    assert mapping.manual_verified is True
    # The mapping stores the JP page the collector must fetch for a jp
    # print, not the English mirror discovery walked - see
    # app.services.snkrdunk_urls. The candidate keeps its own URL.
    assert mapping.source_url == "https://snkrdunk.com/apparels/900101"
    assert candidate.source_url == "https://snkrdunk.com/en/trading-cards/900101"
    assert mapping.is_active is True
    assert mapping.review_status == "approved"


def test_match_candidate_without_manual_verification_needs_review(
    client, candidate, seeded_db, luffy_print
):
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()

    response = client.post(
        f"/snkrdunk/candidates/{candidate.id}/match",
        json={"card_id": luffy.id, "card_print_id": luffy_print.id, "manual_verified": False},
    )

    assert response.status_code == 200

    snkrdunk_source = seeded_db.query(Source).filter_by(name="snkrdunk").one()
    mapping = (
        seeded_db.query(SourceCardMapping)
        .filter_by(card_id=luffy.id, source_id=snkrdunk_source.id)
        .one()
    )
    assert mapping.manual_verified is False
    assert mapping.is_active is True
    assert mapping.review_status == "needs_review"


def test_match_candidate_updates_the_mapping_for_the_same_listing(
    client, candidate, seeded_db, luffy_print
):
    """Same listing URL -> the same row is updated, never duplicated."""
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()
    snkrdunk_source = seeded_db.query(Source).filter_by(name="snkrdunk").one()

    existing = SourceCardMapping(
        card_id=luffy.id,
        source_id=snkrdunk_source.id,
        source_card_id="OP01-001",
        source_url=candidate.source_url,
        match_confidence=0.6,
        manual_verified=False,
    )
    seeded_db.add(existing)
    seeded_db.commit()

    response = client.post(
        f"/snkrdunk/candidates/{candidate.id}/match",
        json={"card_id": luffy.id, "card_print_id": luffy_print.id, "manual_verified": True},
    )
    assert response.status_code == 200

    mappings = seeded_db.query(SourceCardMapping).filter_by(source_id=snkrdunk_source.id).all()
    assert len(mappings) == 1
    assert mappings[0].id == existing.id
    assert mappings[0].source_url == "https://snkrdunk.com/apparels/900101"
    assert mappings[0].match_confidence == 1.0
    assert mappings[0].manual_verified is True
    assert mappings[0].card_print_id == luffy_print.id


def test_match_candidate_leaves_a_different_listings_mapping_alone(
    client, candidate, seeded_db, luffy_print
):
    """A mapping is per listing, matching the database's own
    UNIQUE (source_id, source_url).

    The lookup used to be keyed on (card_id, source_id), which meant matching
    one listing REWROTE whatever mapping the card already had - silently
    re-pointing a different listing's row at this candidate's URL. Keyed on
    the listing, the two coexist, which is also the only way one card's
    several printings can each carry their own source.
    """
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()
    snkrdunk_source = seeded_db.query(Source).filter_by(name="snkrdunk").one()

    other_listing = SourceCardMapping(
        card_id=luffy.id,
        source_id=snkrdunk_source.id,
        source_card_id="OP01-001",
        source_url="https://snkrdunk.com/en/trading-cards/900002",
        match_confidence=0.6,
        manual_verified=False,
    )
    seeded_db.add(other_listing)
    seeded_db.commit()
    untouched_id = other_listing.id

    response = client.post(
        f"/snkrdunk/candidates/{candidate.id}/match",
        json={"card_id": luffy.id, "card_print_id": luffy_print.id, "manual_verified": True},
    )
    assert response.status_code == 200

    mappings = seeded_db.query(SourceCardMapping).filter_by(source_id=snkrdunk_source.id).all()
    assert len(mappings) == 2
    survivor = next(m for m in mappings if m.id == untouched_id)
    # Untouched, so it keeps the URL it was seeded with - canonicalisation
    # applies to the mapping being approved, never to a bystander row.
    assert survivor.source_url == "https://snkrdunk.com/en/trading-cards/900002"
    assert survivor.match_confidence == 0.6
    assert survivor.manual_verified is False


def test_match_candidate_card_not_found(client, candidate, luffy_print):
    response = client.post(
        f"/snkrdunk/candidates/{candidate.id}/match",
        json={"card_id": 999999, "card_print_id": luffy_print.id, "manual_verified": True},
    )
    assert response.status_code == 404


def test_match_candidate_not_found(client, seeded_db, luffy_print):
    luffy = seeded_db.query(Card).filter_by(card_code="OP01-001").one()
    response = client.post(
        "/snkrdunk/candidates/999999/match",
        json={"card_id": luffy.id, "card_print_id": luffy_print.id, "manual_verified": True},
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
