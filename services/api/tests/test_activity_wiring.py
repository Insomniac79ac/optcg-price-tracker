"""Confirms that record_activity_event actually gets called from the admin
endpoints it is still wired into (app/services/activity_timeline.py). The
legacy collection, wishlist and grading endpoints and the /collector/activity
reader were removed in Collector v1 S8, so the rows are read directly.
"""

import json
from datetime import datetime, timezone

from app.models import CollectorActivityEvent
from app.services.backup import BACKUP_VERSION, REQUIRED_TABLES


def event_types(db_session) -> list[str]:
    return [e.event_type for e in db_session.query(CollectorActivityEvent).all()]


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
            "include_logs": False,
            "include_validation_reports": False,
            "raw_snapshot_provenance": {
                "mode": "intentionally_omitted",
                "price_observation_references_nullified": 0,
                "source_collection_attempt_references_nullified": 0,
            },
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
    assert response.json()["valid"] is True

    assert "backup_restored" in event_types(db_session)


def test_restore_dry_run_records_no_activity(client, db_session):
    backup = empty_backup()

    response = upload_restore(client, backup, dry_run="true", mode="merge")
    assert response.status_code == 200, response.text

    assert event_types(db_session) == []
