"""Confirms that record_activity_event actually gets called from the action
endpoints it was wired into (app/services/activity_timeline.py), by hitting
those endpoints and checking /collector/activity afterwards. Endpoint-level
correctness for collection/wishlist/grading/backup/admin-actions has its own
dedicated test file - this only checks the activity side effect.
"""

import json
from datetime import datetime, timezone

from app.models import Card, CollectionItem
from app.services.backup import BACKUP_VERSION, REQUIRED_TABLES


def make_card(db_session, **overrides) -> Card:
    fields = dict(
        card_code="OP01-001",
        name_en="Monkey D. Luffy",
        name_jp="モンキー・D・ルフィ",
        set_code="OP01",
        rarity="L",
        variant="leader",
        language="en",
    )
    fields.update(overrides)
    card = Card(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_item(db_session, card: Card, **overrides) -> CollectionItem:
    fields = dict(card_id=card.id, quantity=1, user_id=1)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def event_types(client) -> list[str]:
    response = client.get("/collector/activity", params={"limit": 500})
    assert response.status_code == 200
    return [e["event_type"] for e in response.json()["events"]]


# --- collection --------------------------------------------------------


def test_creating_collection_item_records_activity(client, db_session):
    card = make_card(db_session)

    response = client.post(
        "/collection", json={"card_id": card.id, "quantity": 1, "status": "hold"}
    )
    assert response.status_code == 201

    assert "collection_item_added" in event_types(client)


def test_changing_collection_item_status_records_activity(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, status="hold")

    response = client.patch(f"/collection/{item.id}", json={"status": "sold"})
    assert response.status_code == 200

    assert "collection_item_status_changed" in event_types(client)


def test_updating_collection_item_without_status_change_records_nothing(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card, status="hold", quantity=1)

    response = client.patch(f"/collection/{item.id}", json={"quantity": 2})
    assert response.status_code == 200

    assert event_types(client) == []


def test_deleting_collection_item_records_activity(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)

    response = client.delete(f"/collection/{item.id}")
    assert response.status_code == 204

    assert "collection_item_removed" in event_types(client)


# --- wishlist ------------------------------------------------------------


def test_creating_wishlist_item_records_activity(client, db_session):
    card = make_card(db_session)

    response = client.post("/wishlist", json={"card_id": card.id})
    assert response.status_code == 201

    assert "wishlist_item_added" in event_types(client)


def test_deleting_wishlist_item_records_activity(client, db_session):
    card = make_card(db_session)
    created = client.post("/wishlist", json={"card_id": card.id}).json()

    response = client.delete(f"/wishlist/{created['id']}")
    assert response.status_code == 200

    assert "wishlist_item_removed" in event_types(client)


def test_marking_wishlist_item_purchased_records_activity(client, db_session):
    card = make_card(db_session)
    collection_item = make_item(db_session, card)
    created = client.post("/wishlist", json={"card_id": card.id}).json()

    response = client.post(
        f"/wishlist/{created['id']}/mark-purchased",
        json={"collection_item_id": collection_item.id, "acquired_quantity": 1},
    )
    assert response.status_code == 200

    assert "wishlist_item_purchased" in event_types(client)


def test_converting_wishlist_item_records_activity(client, db_session):
    card = make_card(db_session)
    created = client.post("/wishlist", json={"card_id": card.id}).json()

    response = client.post(
        f"/wishlist/{created['id']}/convert-to-collection",
        json={"quantity": 1, "status": "hold"},
    )
    assert response.status_code == 200

    assert "wishlist_item_converted" in event_types(client)


# --- grading ---------------------------------------------------------------


def test_creating_grading_submission_records_activity(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)

    response = client.post(
        "/grading/submissions",
        json={"collection_item_id": item.id, "grading_company": "PSA"},
    )
    assert response.status_code == 201

    assert "grading_submission_created" in event_types(client)


def test_changing_grading_submission_status_records_activity(client, db_session):
    card = make_card(db_session)
    item = make_item(db_session, card)
    created = client.post(
        "/grading/submissions",
        json={
            "collection_item_id": item.id,
            "grading_company": "PSA",
            "submission_status": "planned",
        },
    ).json()

    response = client.patch(
        f"/grading/submissions/{created['id']}", json={"submission_status": "submitted"}
    )
    assert response.status_code == 200

    assert "grading_submission_status_changed" in event_types(client)


# --- admin actions -----------------------------------------------------


def test_snapshot_market_signals_records_activity(client, db_session):
    response = client.post("/admin/actions/snapshot-market-signals")
    assert response.status_code == 200

    assert "market_signal_snapshot" in event_types(client)


def test_generate_market_report_records_activity(client, db_session):
    response = client.post("/admin/actions/generate-market-report")
    assert response.status_code == 200

    assert "market_report_generated" in event_types(client)


# --- backup restore ------------------------------------------------------


def empty_backup(**table_overrides) -> dict:
    tables = {t: [] for t in REQUIRED_TABLES}
    tables.update(table_overrides)
    return {
        "metadata": {
            "app": "opcg-price-tracker",
            "backup_version": BACKUP_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "include_prices": False,
            "include_raw_snapshots": False,
            "include_refresh_runs": False,
        },
        "tables": tables,
    }


def upload_restore(client, backup: dict, **params):
    payload = json.dumps(backup).encode("utf-8")
    return client.post(
        "/admin/backup/restore",
        params=params,
        files={"file": ("backup.json", payload, "application/json")},
    )


def test_restore_records_activity_when_not_dry_run(client, db_session):
    backup = empty_backup(
        cards=[
            {
                "id": 1,
                "card_code": "OP01-001",
                "name_en": None,
                "name_jp": None,
                "set_code": "OP01",
                "rarity": "L",
                "variant": None,
                "language": "en",
                "image_url": None,
            }
        ]
    )

    response = upload_restore(client, backup, dry_run="false", mode="merge", confirm="RESTORE")
    assert response.status_code == 200, response.text

    assert "backup_restored" in event_types(client)


def test_restore_dry_run_records_no_activity(client, db_session):
    backup = empty_backup()

    response = upload_restore(client, backup, dry_run="true", mode="merge")
    assert response.status_code == 200, response.text

    assert event_types(client) == []
