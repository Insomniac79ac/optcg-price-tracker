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


@pytest.fixture()
def seeded(db_session):
    source = Source(name="snkrdunk", base_url="https://snkrdunk.com")
    db_session.add(source)
    card = Card(
        card_code="OP01-001", name_en="Monkey D. Luffy", name_jp="モンキー・D・ルフィ",
        set_code="OP01", rarity="L", variant="base", language="jp",
        character="Luffy", card_type="Leader", color="Red",
    )
    other_card = Card(
        card_code="OP01-013", name_en="Roronoa Zoro", name_jp="ロロノア・ゾロ",
        set_code="OP01", rarity="SR", variant="base", language="jp",
    )
    db_session.add_all([card, other_card])
    db_session.flush()

    # Approval now names an exact printing, so the fixture supplies one per
    # card code. One active verified print each, so the card code alone
    # identifies it and these tests stay about the review workflow rather than
    # the ambiguity rules (test_exact_print_approval.py owns those).
    product = ReleaseProduct(
        source_catalogue="jp",
        official_code="OP01",
        display_name="OP-01",
        first_seen_name="OP-01",
        source_series_id="OP01",
        source_url="https://example.test/OP-01",
        verification_status="verified",
    )
    db_session.add(product)
    db_session.flush()

    prints = {}
    for code, name_en, name_jp, rarity in (
        ("OP01-001", "Monkey D. Luffy", "モンキー・D・ルフィ", "L"),
        ("OP01-013", "Roronoa Zoro", "ロロノア・ゾロ", "SR"),
    ):
        canonical = CanonicalCard(
            card_code=code, name_en=name_en, name_jp=name_jp,
            card_type="Character", rarity=rarity,
        )
        db_session.add(canonical)
        db_session.flush()
        row = CardPrint(
            canonical_card_id=canonical.id,
            language="jp",
            release_product_code="OP01",
            release_product_id=product.id,
            artwork_key=f"sha256:{code}-base",
            official_asset_variant="base",
            verification_status="verified",
            is_active=True,
        )
        db_session.add(row)
        db_session.flush()
        prints[code] = row

    db_session.commit()
    db_session.refresh(card)
    db_session.refresh(other_card)
    return {
        "source": source,
        "card": card,
        "other_card": other_card,
        "print": prints["OP01-001"],
        "other_print": prints["OP01-013"],
    }


@pytest.fixture()
def strong_candidate(db_session, seeded):
    candidate = SnkrdunkCandidate(
        source_url="https://snkrdunk.com/en/trading-cards/900004",
        title="OP01-001 モンキー・D・ルフィ L",
        normalized_title="OP01-001 モンキー・D・ルフィ L",
        raw_text="Luffy",
        detected_card_code="OP01-001",
        detected_set_code="OP01",
        detected_rarity="L",
        match_status="unmatched",
    )
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


@pytest.fixture()
def weak_candidate(db_session, seeded):
    candidate = SnkrdunkCandidate(
        source_url="https://snkrdunk.com/en/trading-cards/900005",
        title="謎のリスティング",
        normalized_title="謎のリスティング",
        match_status="unmatched",
    )
    db_session.add(candidate)
    db_session.commit()
    db_session.refresh(candidate)
    return candidate


def test_get_matches_returns_ranked_matches(client, strong_candidate, seeded):
    response = client.get(f"/admin/snkrdunk-candidates/{strong_candidate.id}/matches")
    assert response.status_code == 200
    body = response.json()
    assert body["candidate"]["id"] == strong_candidate.id
    assert len(body["matches"]) >= 1
    top = body["matches"][0]
    assert top["card_code"] == "OP01-001"
    assert top["score"] >= 90
    assert top["confidence_label"] == "exact"
    assert "explanation" in top
    assert "positive" in top["explanation"]


def test_get_matches_404_for_missing_candidate(client, db_session):
    response = client.get("/admin/snkrdunk-candidates/999999/matches")
    assert response.status_code == 404


def test_rematch_updates_candidate_best_match_fields(client, db_session, strong_candidate, seeded):
    response = client.post(f"/admin/snkrdunk-candidates/{strong_candidate.id}/rematch")
    assert response.status_code == 200
    body = response.json()
    assert body["candidate"]["match_status"] == "suggested"

    db_session.refresh(strong_candidate)
    assert strong_candidate.match_status == "suggested"
    assert strong_candidate.best_match_card_id == seeded["card"].id
    assert strong_candidate.best_match_score >= 90
    assert strong_candidate.best_match_confidence_label == "exact"
    assert strong_candidate.match_explanation_json is not None


def test_rematch_weak_candidate_remains_unmatched(client, db_session, weak_candidate):
    response = client.post(f"/admin/snkrdunk-candidates/{weak_candidate.id}/rematch")
    assert response.status_code == 200
    body = response.json()
    assert body["candidate"]["match_status"] == "unmatched"
    assert body["matches"] == []

    db_session.refresh(weak_candidate)
    assert weak_candidate.match_status == "unmatched"
    assert weak_candidate.best_match_card_id is None


def test_rematch_does_not_overwrite_matched_status(client, db_session, strong_candidate, seeded):
    strong_candidate.match_status = "matched"
    strong_candidate.matched_card_id = seeded["card"].id
    db_session.commit()

    response = client.post(f"/admin/snkrdunk-candidates/{strong_candidate.id}/rematch")
    assert response.status_code == 200
    assert response.json()["candidate"]["match_status"] == "matched"

    db_session.refresh(strong_candidate)
    assert strong_candidate.match_status == "matched"
    # best_match_* informational fields are still refreshed.
    assert strong_candidate.best_match_card_id == seeded["card"].id


def test_rematch_all_dry_run_does_not_write(client, db_session, strong_candidate, seeded):
    response = client.post(
        "/admin/snkrdunk-candidates/rematch-all",
        json={"status": "all", "limit": 100, "dry_run": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["would_update"] == 1
    assert body["updated"] == 0
    assert body["suggested"] == 1

    db_session.refresh(strong_candidate)
    assert strong_candidate.match_status == "unmatched"
    assert strong_candidate.best_match_card_id is None


def test_rematch_all_real_run_updates_candidates(client, db_session, strong_candidate, seeded):
    response = client.post(
        "/admin/snkrdunk-candidates/rematch-all",
        json={"status": "all", "limit": 100, "dry_run": False},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is False
    assert body["would_update"] == 1
    assert body["updated"] == 1
    assert body["suggested"] == 1

    db_session.refresh(strong_candidate)
    assert strong_candidate.match_status == "suggested"
    assert strong_candidate.best_match_card_id == seeded["card"].id


def test_approve_match_creates_source_mapping_with_review_fields(client, db_session, strong_candidate, seeded):
    response = client.post(
        f"/admin/snkrdunk-candidates/{strong_candidate.id}/approve-match",
        json={
            "card_id": seeded["card"].id,
            "card_print_id": seeded["print"].id,
            "review_notes": "looks right",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["match_status"] == "matched"
    assert body["matched_card_id"] == seeded["card"].id

    db_session.refresh(strong_candidate)
    assert strong_candidate.match_status == "matched"
    assert strong_candidate.matched_card_id == seeded["card"].id

    mapping = (
        db_session.query(SourceCardMapping)
        .filter_by(card_id=seeded["card"].id, source_id=seeded["source"].id)
        .one()
    )
    # The mapping stores the JP page the collector must fetch for a jp
    # print, not the English mirror discovery walked - see
    # app.services.snkrdunk_urls. The candidate keeps its own URL.
    assert mapping.source_url == "https://snkrdunk.com/apparels/900004"
    assert strong_candidate.source_url == "https://snkrdunk.com/en/trading-cards/900004"
    assert mapping.manual_verified is True
    assert mapping.review_status == "approved"
    assert mapping.is_active is True
    assert mapping.match_confidence == 93.0
    assert mapping.review_notes == "looks right"
    assert mapping.card_print_id == seeded["print"].id


def test_approve_match_refuses_a_print_the_source_code_contradicts(
    client, db_session, strong_candidate, seeded
):
    """An operator may still overrule the scorer's suggestion, but not the
    source's own card code.

    Before the exact-print gate this wrote a mapping for whatever card the
    operator named, with no reference to what the listing said. The listing
    here reports OP01-001; approving a printing of OP01-013 against it would
    be asserting a fact the evidence contradicts.
    """
    response = client.post(
        f"/admin/snkrdunk-candidates/{strong_candidate.id}/approve-match",
        json={
            "card_id": seeded["other_card"].id,
            "card_print_id": seeded["other_print"].id,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "card_code_mismatch"
    assert db_session.query(SourceCardMapping).count() == 0


def test_approve_match_404_for_missing_card(client, strong_candidate, seeded):
    response = client.post(
        f"/admin/snkrdunk-candidates/{strong_candidate.id}/approve-match",
        json={"card_id": 999999, "card_print_id": strong_candidate.id},
    )
    assert response.status_code == 404


def test_reject_match_does_not_create_mapping(client, db_session, strong_candidate, seeded):
    response = client.post(
        f"/admin/snkrdunk-candidates/{strong_candidate.id}/reject-match",
        json={"review_notes": "wrong card"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["match_status"] == "rejected"

    db_session.refresh(strong_candidate)
    assert strong_candidate.match_status == "rejected"
    assert db_session.query(SourceCardMapping).count() == 0


def test_reject_match_does_not_delete_existing_mapping(client, db_session, strong_candidate, seeded):
    mapping = SourceCardMapping(
        card_id=seeded["card"].id,
        source_id=seeded["source"].id,
        source_card_id="OP01-001",
        source_url="https://snkrdunk.com/en/trading-cards/900003",
    )
    db_session.add(mapping)
    db_session.commit()

    response = client.post(f"/admin/snkrdunk-candidates/{strong_candidate.id}/reject-match", json={})
    assert response.status_code == 200

    assert db_session.query(SourceCardMapping).count() == 1
