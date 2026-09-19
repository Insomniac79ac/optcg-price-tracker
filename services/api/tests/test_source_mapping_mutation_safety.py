from datetime import datetime, timezone

from app.models import PriceObservation, SourceCardMapping
from app.services.exact_print_approval import REFUSAL_LEGACY_MAPPING_HAS_NO_PRINT
from tests.exact_reporting_helpers import (
    make_canonical,
    make_compatibility_card,
    make_exact_mapping,
    make_exact_observation,
    make_legacy_mapping,
    make_print,
    make_source,
)


def _mapping_state(mapping: SourceCardMapping) -> dict:
    return {
        "card_id": mapping.card_id,
        "card_print_id": mapping.card_print_id,
        "source_card_id": mapping.source_card_id,
        "source_url": mapping.source_url,
        "is_active": mapping.is_active,
        "review_status": mapping.review_status,
        "manual_verified": mapping.manual_verified,
        "last_verified_at": mapping.last_verified_at,
        "review_notes": mapping.review_notes,
    }


def _make_broken_mapping(db, source, *, suffix: str, active: bool = False):
    mapping = SourceCardMapping(
        card_id=None,
        card_print_id=None,
        source_id=source.id,
        source_card_id=f"broken-{suffix}",
        source_url=f"https://{source.name}.example/broken-{suffix}",
        is_active=active,
        review_status="approved",
        manual_verified=False,
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping


def test_patch_can_activate_operational_exact_mapping(client, db_session):
    source = make_source(db_session)
    print_row = make_print(db_session, make_canonical(db_session, "OP01-101"))
    mapping = make_exact_mapping(
        db_session, print_row, source, is_active=False, review_status="approved"
    )

    response = client.patch(
        f"/admin/source-mappings/{mapping.id}", json={"is_active": True}
    )

    assert response.status_code == 200, response.text
    db_session.refresh(mapping)
    assert mapping.is_active is True
    assert mapping.card_print_id == print_row.id


def test_patch_cannot_newly_activate_legacy_compatibility_mapping(client, db_session):
    source = make_source(db_session)
    mapping = make_legacy_mapping(
        db_session,
        make_compatibility_card(db_session, "OP01-102"),
        source,
        is_active=False,
        review_status="approved",
    )
    before = _mapping_state(mapping)

    response = client.patch(
        f"/admin/source-mappings/{mapping.id}", json={"is_active": True}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == REFUSAL_LEGACY_MAPPING_HAS_NO_PRINT
    db_session.refresh(mapping)
    assert _mapping_state(mapping) == before


def test_patch_cannot_newly_activate_broken_mapping(client, db_session):
    source = make_source(db_session)
    mapping = _make_broken_mapping(db_session, source, suffix="patch")
    before = _mapping_state(mapping)

    response = client.patch(
        f"/admin/source-mappings/{mapping.id}", json={"is_active": True}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "mapping_identity_broken"
    db_session.refresh(mapping)
    assert _mapping_state(mapping) == before


def test_patch_cannot_edit_card_print_id(client, db_session):
    source = make_source(db_session)
    original = make_print(db_session, make_canonical(db_session, "OP01-103"))
    replacement = make_print(db_session, make_canonical(db_session, "OP01-104"))
    mapping = make_exact_mapping(db_session, original, source)

    response = client.patch(
        f"/admin/source-mappings/{mapping.id}",
        json={"card_print_id": replacement.id},
    )

    assert response.status_code == 422
    db_session.refresh(mapping)
    assert mapping.card_print_id == original.id


def test_patch_verification_requires_exact_priceable_lineage(client, db_session):
    source = make_source(db_session)
    print_row = make_print(db_session, make_canonical(db_session, "OP01-114"))
    exact = make_exact_mapping(
        db_session,
        print_row,
        source,
        suffix="patch-verify-exact",
        review_status="needs_review",
        manual_verified=False,
    )
    legacy = make_legacy_mapping(
        db_session,
        make_compatibility_card(db_session, "OP01-115"),
        source,
        manual_verified=False,
    )
    broken = _make_broken_mapping(db_session, source, suffix="patch-verify")

    exact_response = client.patch(
        f"/admin/source-mappings/{exact.id}", json={"manual_verified": True}
    )
    legacy_response = client.patch(
        f"/admin/source-mappings/{legacy.id}", json={"manual_verified": True}
    )
    broken_response = client.patch(
        f"/admin/source-mappings/{broken.id}", json={"manual_verified": True}
    )

    assert exact_response.status_code == 200
    assert legacy_response.status_code == 409
    assert broken_response.status_code == 409
    for mapping in (exact, legacy, broken):
        db_session.refresh(mapping)
    assert exact.manual_verified is True
    assert legacy.manual_verified is False
    assert broken.manual_verified is False


def test_bulk_activate_reports_every_operational_outcome(client, db_session):
    source = make_source(db_session)
    eligible_print = make_print(
        db_session, make_canonical(db_session, "OP01-105")
    )
    exact = make_exact_mapping(
        db_session,
        eligible_print,
        source,
        suffix="bulk-exact",
        is_active=False,
        review_status="approved",
    )
    legacy = make_legacy_mapping(
        db_session,
        make_compatibility_card(db_session, "OP01-106"),
        source,
        is_active=False,
        review_status="approved",
    )
    broken = _make_broken_mapping(db_session, source, suffix="bulk")
    unverified_print = make_print(
        db_session,
        make_canonical(db_session, "OP01-107"),
        verification_status="unverified",
    )
    non_priceable = make_exact_mapping(
        db_session,
        unverified_print,
        source,
        suffix="bulk-unverified",
        is_active=False,
        review_status="approved",
    )

    response = client.post(
        "/admin/source-mappings/bulk-update",
        json={
            "mapping_ids": [exact.id, legacy.id, broken.id, non_priceable.id],
            "action": "activate",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"] == {
        "applied": 1,
        "skipped_legacy_compatibility": 1,
        "skipped_broken": 1,
        "skipped_non_priceable_exact": 1,
        "not_found": 0,
    }
    results = {result["mapping_id"]: result for result in body["results"]}
    assert results[exact.id] == {"mapping_id": exact.id, "ok": True, "error": None}
    assert results[legacy.id]["error"] == "skipped_legacy_compatibility"
    assert results[broken.id]["error"] == "skipped_broken"
    assert results[non_priceable.id]["error"] == "skipped_non_priceable_exact"

    for mapping in (exact, legacy, broken, non_priceable):
        db_session.refresh(mapping)
    assert exact.is_active is True
    assert legacy.is_active is False
    assert broken.is_active is False
    assert non_priceable.is_active is False


def test_bulk_mark_verified_requires_exact_priceable_lineage(client, db_session):
    source = make_source(db_session)
    print_row = make_print(db_session, make_canonical(db_session, "OP01-108"))
    exact = make_exact_mapping(
        db_session,
        print_row,
        source,
        suffix="verify-exact",
        review_status="needs_review",
        manual_verified=False,
    )
    legacy = make_legacy_mapping(
        db_session,
        make_compatibility_card(db_session, "OP01-109"),
        source,
        review_status="approved",
        manual_verified=False,
    )
    broken = _make_broken_mapping(db_session, source, suffix="verify")

    response = client.post(
        "/admin/source-mappings/bulk-update",
        json={
            "mapping_ids": [exact.id, legacy.id, broken.id],
            "action": "mark_verified",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["applied"] == 1
    assert body["summary"]["skipped_legacy_compatibility"] == 1
    assert body["summary"]["skipped_broken"] == 1
    for mapping in (exact, legacy, broken):
        db_session.refresh(mapping)
    assert exact.manual_verified is True
    assert exact.review_status == "needs_review"
    assert legacy.manual_verified is False
    assert broken.manual_verified is False


def test_approved_exact_listing_identity_edit_forces_rereview_and_preserves_history(
    client, db_session
):
    source = make_source(db_session)
    print_row = make_print(db_session, make_canonical(db_session, "OP01-110"))
    verified_at = datetime.now(timezone.utc)
    mapping = make_exact_mapping(
        db_session,
        print_row,
        source,
        suffix="identity-before",
        review_status="approved",
        is_active=True,
        manual_verified=True,
        last_verified_at=verified_at,
    )
    verified_at_before = mapping.last_verified_at
    observation = make_exact_observation(db_session, mapping)
    observation_before = {
        "id": observation.id,
        "source_card_mapping_id": observation.source_card_mapping_id,
        "card_print_id": observation.card_print_id,
        "price_jpy": observation.price_jpy,
        "observed_at": observation.observed_at,
    }

    response = client.patch(
        f"/admin/source-mappings/{mapping.id}",
        json={
            "source_url": "https://yuyutei.example/identity-after",
            "source_card_id": "OP01-110-new-listing",
        },
    )

    assert response.status_code == 200, response.text
    db_session.refresh(mapping)
    db_session.refresh(observation)
    assert mapping.review_status == "needs_review"
    assert mapping.manual_verified is False
    assert mapping.is_active is True
    assert mapping.card_print_id == print_row.id
    assert mapping.last_verified_at == verified_at_before
    assert {
        "id": observation.id,
        "source_card_mapping_id": observation.source_card_mapping_id,
        "card_print_id": observation.card_print_id,
        "price_jpy": observation.price_jpy,
        "observed_at": observation.observed_at,
    } == observation_before
    assert db_session.query(PriceObservation).count() == 1


def test_cosmetic_mapping_edit_does_not_force_rereview(client, db_session):
    source = make_source(db_session)
    print_row = make_print(db_session, make_canonical(db_session, "OP01-111"))
    mapping = make_exact_mapping(
        db_session,
        print_row,
        source,
        review_status="approved",
        manual_verified=True,
    )

    response = client.patch(
        f"/admin/source-mappings/{mapping.id}",
        json={"review_notes": "cosmetic operator note"},
    )

    assert response.status_code == 200, response.text
    db_session.refresh(mapping)
    assert mapping.review_status == "approved"
    assert mapping.manual_verified is True
    assert mapping.review_notes == "cosmetic operator note"


def test_grandfathered_rows_remain_readable_without_mass_mutation(client, db_session):
    source = make_source(db_session)
    blocked = make_legacy_mapping(
        db_session,
        make_compatibility_card(db_session, "OP01-112"),
        source,
        is_active=False,
        review_status="approved",
    )
    untouched = make_legacy_mapping(
        db_session,
        make_compatibility_card(db_session, "OP01-113"),
        source,
        is_active=True,
        review_status="approved",
        manual_verified=True,
    )
    before = {blocked.id: _mapping_state(blocked), untouched.id: _mapping_state(untouched)}

    response = client.patch(
        f"/admin/source-mappings/{blocked.id}", json={"is_active": True}
    )
    listed = client.get("/admin/source-mappings")

    assert response.status_code == 409
    assert listed.status_code == 200
    assert {item["id"] for item in listed.json()["items"]} == {
        blocked.id,
        untouched.id,
    }
    for mapping in (blocked, untouched):
        db_session.refresh(mapping)
        assert _mapping_state(mapping) == before[mapping.id]
