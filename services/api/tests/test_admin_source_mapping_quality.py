from datetime import datetime, timedelta, timezone

from app.models import Card, PriceObservation, Source, SourceCardMapping
from tests.test_source_mappings import (
    make_card,
    make_mapping,
    make_print,
    make_print_authoritative_mapping,
    make_source,
)


def test_quality_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain_client = TestClient(app)
    response = plain_client.get("/admin/source-mappings/quality")
    assert response.status_code == 401


def test_quality_empty_mappings_works(client, db_session):
    response = client.get("/admin/source-mappings/quality")
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total_mappings"] == 0
    assert body["items"] == []


def test_quality_detects_low_confidence_mapping(client, db_session):
    source = make_source(db_session, "snkrdunk")
    card = make_card(db_session, card_code="OP01-001", variant=None)
    make_mapping(
        db_session, card, source,
        source_card_id="unrelated-listing-id",
        source_url="https://snkrdunk.example/unrelated",
    )

    response = client.get("/admin/source-mappings/quality")
    body = response.json()
    assert body["summary"]["low_confidence_count"] >= 1
    item = body["items"][0]
    assert "low_confidence" in item["issue_types"]


def test_quality_detects_duplicate_source_url(client, db_session):
    source = make_source(db_session, "snkrdunk")
    card = make_card(db_session, card_code="OP01-001", variant=None)
    make_mapping(
        db_session, card, source,
        source_card_id="OP01-001",
        source_url="https://snkrdunk.example/op01-001",
    )
    make_mapping(
        db_session, card, source,
        source_card_id="OP01-001",
        source_url="https://snkrdunk.example/OP01-001 ",
    )

    response = client.get("/admin/source-mappings/quality")
    body = response.json()
    assert body["summary"]["duplicate_source_url_count"] == 2
    assert all("duplicate_source_url" in i["issue_types"] for i in body["items"])


def test_quality_detects_stale_mapping(client, db_session):
    source = make_source(db_session, "snkrdunk")
    card = make_card(db_session, card_code="OP01-001", variant=None)
    old = datetime.now(timezone.utc) - timedelta(days=200)
    make_mapping(
        db_session, card, source,
        source_card_id="OP01-001",
        created_at=old,
    )

    response = client.get("/admin/source-mappings/quality")
    body = response.json()
    item = body["items"][0]
    assert "stale_mapping" in item["issue_types"]


def test_quality_detects_inactive_with_recent_price(client, db_session):
    source = make_source(db_session, "snkrdunk")
    card = make_card(db_session, card_code="OP01-001", variant=None)
    mapping = make_mapping(db_session, card, source, source_card_id="OP01-001", is_active=False)
    db_session.add(
        PriceObservation(
            card_id=card.id,
            source_id=source.id,
            price_type="floor",
            price_jpy=1000,
            observed_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
    )
    db_session.commit()

    response = client.get("/admin/source-mappings/quality")
    body = response.json()
    item = next(i for i in body["items"] if i["mapping_id"] == mapping.id)
    assert "inactive_with_recent_price" in item["issue_types"]


def test_quality_detects_active_without_recent_price(client, db_session):
    source = make_source(db_session, "snkrdunk")
    card = make_card(db_session, card_code="OP01-001", variant=None)
    mapping = make_mapping(db_session, card, source, source_card_id="OP01-001", is_active=True)

    response = client.get("/admin/source-mappings/quality")
    body = response.json()
    item = next(i for i in body["items"] if i["mapping_id"] == mapping.id)
    assert "active_without_recent_price" in item["issue_types"]


def test_recheck_quality_dry_run_does_not_write(client, db_session):
    source = make_source(db_session, "snkrdunk")
    card = make_card(db_session, card_code="OP01-001", variant=None)
    mapping = make_mapping(db_session, card, source, source_card_id="OP01-001")

    response = client.post("/admin/source-mappings/recheck-quality", json={"dry_run": True})
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["summary"]["would_update"] == 1
    assert body["summary"]["updated"] == 0

    db_session.refresh(mapping)
    assert mapping.match_confidence_label is None
    assert mapping.last_match_checked_at is None


def test_recheck_quality_real_run_updates_confidence_fields(client, db_session):
    source = make_source(db_session, "snkrdunk")
    card = make_card(db_session, card_code="OP01-001", variant=None)
    mapping = make_mapping(db_session, card, source, source_card_id="OP01-001")

    response = client.post("/admin/source-mappings/recheck-quality", json={"dry_run": False})
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is False
    assert body["summary"]["updated"] == 1

    db_session.refresh(mapping)
    assert mapping.match_confidence_label is not None
    assert mapping.match_explanation_json is not None
    assert mapping.last_match_checked_at is not None


def test_bulk_update_approve(client, db_session):
    source = make_source(db_session, "snkrdunk")
    card = make_card(db_session, card_code="OP01-001", variant=None)
    # A bulk approve is an approval, so the row has to name an exact print
    # like any other - see tests/test_legacy_mapping_approval_guard.py.
    print_row = make_print(db_session)
    mapping = make_mapping(
        db_session, card, source, source_card_id="OP01-001",
        review_status="needs_review", is_active=False, manual_verified=False,
        card_print_id=print_row.id,
    )

    response = client.post(
        "/admin/source-mappings/bulk-update",
        json={"mapping_ids": [mapping.id], "action": "approve", "review_notes": "bulk reviewed"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["results"] == [{"mapping_id": mapping.id, "ok": True, "error": None}]

    db_session.refresh(mapping)
    assert mapping.review_status == "approved"
    assert mapping.is_active is True
    assert mapping.manual_verified is True
    assert mapping.last_verified_at is not None
    assert mapping.review_notes == "bulk reviewed"


def test_bulk_update_reject(client, db_session):
    source = make_source(db_session, "snkrdunk")
    card = make_card(db_session, card_code="OP01-001", variant=None)
    mapping = make_mapping(db_session, card, source, source_card_id="OP01-001")

    response = client.post(
        "/admin/source-mappings/bulk-update",
        json={"mapping_ids": [mapping.id], "action": "reject"},
    )
    assert response.status_code == 200

    db_session.refresh(mapping)
    assert mapping.review_status == "rejected"
    assert mapping.is_active is False
    # Never deletes.
    assert db_session.get(SourceCardMapping, mapping.id) is not None


def test_bulk_update_deactivate_and_activate(client, db_session):
    source = make_source(db_session, "snkrdunk")
    card = make_card(db_session, card_code="OP01-001", variant=None)
    mapping = make_mapping(db_session, card, source, source_card_id="OP01-001", is_active=True)

    response = client.post(
        "/admin/source-mappings/bulk-update",
        json={"mapping_ids": [mapping.id], "action": "deactivate"},
    )
    assert response.status_code == 200
    db_session.refresh(mapping)
    assert mapping.is_active is False

    response = client.post(
        "/admin/source-mappings/bulk-update",
        json={"mapping_ids": [mapping.id], "action": "activate"},
    )
    assert response.status_code == 200
    db_session.refresh(mapping)
    assert mapping.is_active is True


def test_bulk_update_unknown_id_reports_error_without_failing_others(client, db_session):
    source = make_source(db_session, "snkrdunk")
    card = make_card(db_session, card_code="OP01-001", variant=None)
    mapping = make_mapping(db_session, card, source, source_card_id="OP01-001")

    response = client.post(
        "/admin/source-mappings/bulk-update",
        json={"mapping_ids": [mapping.id, 999999], "action": "mark_verified"},
    )
    assert response.status_code == 200
    results = {r["mapping_id"]: r for r in response.json()["results"]}
    assert results[mapping.id]["ok"] is True
    assert results[999999]["ok"] is False
    assert results[999999]["error"] == "not found"


def test_replace_card_updates_mapping_and_reruns_confidence(client, db_session):
    source = make_source(db_session, "snkrdunk")
    wrong_card = make_card(db_session, card_code="OP01-013", name_en="Roronoa Zoro", variant=None)
    right_card = make_card(db_session, card_code="OP01-001", variant=None)
    mapping = make_mapping(db_session, wrong_card, source, source_card_id="OP01-001")

    response = client.post(
        f"/admin/source-mappings/{mapping.id}/replace-card",
        json={"card_id": right_card.id, "review_notes": "Corrected card mapping", "approve": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["card_id"] == right_card.id
    assert body["review_status"] == "approved"
    assert body["match_confidence"] is not None

    db_session.refresh(mapping)
    assert mapping.card_id == right_card.id
    assert mapping.manual_verified is True
    assert mapping.match_confidence_label is not None


def test_suggested_cards_returns_ranked_matches(client, db_session):
    source = make_source(db_session, "snkrdunk")
    card = make_card(db_session, card_code="OP01-001", variant=None)
    mapping = make_mapping(db_session, card, source, source_card_id="OP01-001")

    response = client.get(f"/admin/source-mappings/{mapping.id}/suggested-cards")
    assert response.status_code == 200
    body = response.json()
    assert body["mapping_id"] == mapping.id
    assert len(body["matches"]) >= 1
    assert body["matches"][0]["card_code"] == "OP01-001"


def test_quality_reports_a_mapping_with_no_legacy_card_instead_of_dropping_it(client, db_session):
    """The quality report joins `cards` too. A print-authoritative mapping
    (card_id NULL since c9f31e2a7d04) must still be assessed - and reported as
    missing its legacy reference - rather than vanish from the report or blow
    up in db.get(Card, None)."""
    source = make_source(db_session, "snkrdunk")
    mapping = make_print_authoritative_mapping(db_session, source)

    response = client.get("/admin/source-mappings/quality")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total_mappings"] == 1
    item = body["items"][0]
    assert item["mapping_id"] == mapping.id
    assert item["card_id"] is None
    assert item["card_code"] is None
    assert "missing_card_reference" in item["issue_types"]
