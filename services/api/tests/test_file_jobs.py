from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.env import file_jobs_sync_fallback_effective
from app.main import app
from app.models import Card, CollectionItem, FileJob
from app.services import file_jobs as file_jobs_service
from app.settings import settings
from tests._auth_helpers import TEST_USER_ID, make_bearer_token


@pytest.fixture()
def user_client():
    """Unlike the shared `client` fixture (which sends both a bearer token
    AND X-Admin-Token, since most tests don't care about the distinction),
    GET/POST /file-jobs* treats ANY request carrying a valid X-Admin-Token
    as admin (see app.auth.file_job_access) - so exercising the ordinary
    signed-in-user path (scoped to that user's own jobs) needs a client
    that sends only the bearer token, same as a real non-admin user's
    browser session would."""
    test_client = TestClient(app)
    test_client.headers.update({"Authorization": f"Bearer {make_bearer_token()}"})
    return test_client


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
    fields = dict(card_id=card.id, quantity=1, user_id=TEST_USER_ID)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def upload_collection_import(client, csv_text: str, **params):
    return client.post(
        "/collection/import.csv",
        params=params,
        files={"file": ("collection.csv", csv_text.encode("utf-8"), "text/csv")},
    )


def upload_wishlist_import(client, csv_text: str, **params):
    return client.post(
        "/wishlist/import.csv",
        params=params,
        files={"file": ("wishlist.csv", csv_text.encode("utf-8"), "text/csv")},
    )


# BackgroundTasks run synchronously within Starlette's TestClient (the whole
# ASGI cycle, including any scheduled background task, completes before
# TestClient.post() returns) - so every background-mode assertion below can
# read the job's final state immediately after the creating request, with no
# polling loop needed. This is specific to TestClient; a real deployment's
# client gets its response before the background task runs.


def test_file_jobs_sync_fallback_effective_defaults_to_environment(monkeypatch):
    monkeypatch.setattr(settings, "FILE_JOBS_SYNC_FALLBACK", None)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    assert file_jobs_sync_fallback_effective() is True

    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    assert file_jobs_sync_fallback_effective() is False

    monkeypatch.setattr(settings, "FILE_JOBS_SYNC_FALLBACK", True)
    assert file_jobs_sync_fallback_effective() is True


def test_create_and_get_file_job(db_session):
    job = file_jobs_service.create_file_job(
        db_session, job_type="collection_export", user_id=TEST_USER_ID, dry_run=False
    )
    assert job.id is not None
    assert job.status == "queued"

    fetched = file_jobs_service.get_file_job(db_session, job.id)
    assert fetched is not None
    assert fetched.id == job.id


def test_list_file_jobs_scoped_by_user(db_session):
    file_jobs_service.create_file_job(
        db_session, job_type="collection_export", user_id=1, dry_run=False
    )
    file_jobs_service.create_file_job(
        db_session, job_type="collection_export", user_id=999, dry_run=False
    )

    result = file_jobs_service.list_file_jobs(db_session, user_id=1, admin=False)
    assert result.total == 1
    assert result.jobs[0].user_id == 1

    admin_result = file_jobs_service.list_file_jobs(db_session, admin=True)
    assert admin_result.total == 2


def test_download_not_ready_returns_409(client, db_session):
    job = file_jobs_service.create_file_job(
        db_session, job_type="collection_export", user_id=TEST_USER_ID, dry_run=False
    )
    response = client.get(f"/file-jobs/{job.id}/download")
    assert response.status_code == 409


def test_download_missing_job_returns_404(client, db_session):
    response = client.get("/file-jobs/999999/download")
    assert response.status_code == 404


def test_get_file_job_owned_by_other_user_returns_404(user_client, db_session):
    job = file_jobs_service.create_file_job(
        db_session, job_type="collection_export", user_id=999, dry_run=False
    )
    response = user_client.get(f"/file-jobs/{job.id}")
    assert response.status_code == 404


def test_collection_export_job_creates_downloadable_output(client, db_session):
    card = make_card(db_session)
    make_item(db_session, card)

    create_response = client.post("/collection/export.csv/job", json={})
    assert create_response.status_code == 202
    file_job_id = create_response.json()["file_job_id"]

    status_response = client.get(f"/file-jobs/{file_job_id}")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "success"
    assert body["download_ready"] is True
    assert body["job_type"] == "collection_export"

    download_response = client.get(f"/file-jobs/{file_job_id}/download")
    assert download_response.status_code == 200
    assert download_response.headers["content-type"].startswith("text/csv")
    assert "OP01-001" in download_response.text


def test_wishlist_export_job_creates_downloadable_output(client, db_session):
    from app.models import WishlistItem

    card = make_card(db_session)
    db_session.add(WishlistItem(card_id=card.id, user_id=TEST_USER_ID, priority="medium", status="watching"))
    db_session.commit()

    create_response = client.post("/wishlist/export.csv/job", json={})
    assert create_response.status_code == 202
    file_job_id = create_response.json()["file_job_id"]

    status_response = client.get(f"/file-jobs/{file_job_id}")
    assert status_response.json()["status"] == "success"

    download_response = client.get(f"/file-jobs/{file_job_id}/download")
    assert download_response.status_code == 200
    assert "OP01-001" in download_response.text


def test_background_collection_import_creates_job_and_applies_rows(client, db_session):
    make_card(db_session, card_code="OP01-001")
    csv_text = "card_code,quantity\nOP01-001,3\n"

    response = upload_collection_import(client, csv_text, dry_run=False, mode="upsert", background=True)
    assert response.status_code == 202
    file_job_id = response.json()["file_job_id"]

    status_response = client.get(f"/file-jobs/{file_job_id}")
    body = status_response.json()
    assert body["status"] == "success"
    assert body["job_type"] == "collection_import"
    assert body["summary"]["created"] == 1

    item = db_session.query(CollectionItem).filter(CollectionItem.user_id == TEST_USER_ID).one()
    assert item.quantity == 3


def test_background_wishlist_import_creates_job(client, db_session):
    make_card(db_session, card_code="OP01-001")
    csv_text = "card_code\nOP01-001\n"

    response = upload_wishlist_import(client, csv_text, dry_run=False, mode="upsert", background=True)
    assert response.status_code == 202
    file_job_id = response.json()["file_job_id"]

    status_response = client.get(f"/file-jobs/{file_job_id}")
    body = status_response.json()
    assert body["status"] == "success"
    assert body["job_type"] == "wishlist_import"
    assert body["summary"]["created"] == 1


def test_background_import_bad_csv_marks_job_failed(client, db_session):
    csv_text = "not_a_valid_column\nfoo\n"
    response = upload_collection_import(client, csv_text, dry_run=False, mode="upsert", background=True)
    assert response.status_code == 202
    file_job_id = response.json()["file_job_id"]

    status_response = client.get(f"/file-jobs/{file_job_id}")
    body = status_response.json()
    assert body["status"] == "failed"
    assert body["errors"] is not None


def test_direct_collection_export_csv_streams_full_content(client, db_session):
    card = make_card(db_session)
    make_item(db_session, card)
    response = client.get("/collection/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "OP01-001" in response.text


def test_direct_wishlist_export_csv_streams_full_content(client, db_session):
    from app.models import WishlistItem

    card = make_card(db_session)
    db_session.add(WishlistItem(card_id=card.id, user_id=TEST_USER_ID, priority="medium", status="watching"))
    db_session.commit()
    response = client.get("/wishlist/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "OP01-001" in response.text


def test_backup_export_job_requires_admin_token(db_session):
    raw_client = TestClient(app)
    response = raw_client.post("/admin/backup/export/job", json={})
    assert response.status_code == 401


def test_backup_export_job_creates_downloadable_output(client, db_session):
    response = client.post("/admin/backup/export/job", json={"include_prices": False})
    assert response.status_code == 202
    file_job_id = response.json()["file_job_id"]

    status_response = client.get(f"/file-jobs/{file_job_id}")
    body = status_response.json()
    assert body["status"] == "success"
    assert body["job_type"] == "backup_export"

    download_response = client.get(f"/file-jobs/{file_job_id}/download")
    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/json"


def test_cancel_queued_job(client, db_session):
    job = file_jobs_service.create_file_job(
        db_session, job_type="collection_export", user_id=TEST_USER_ID, dry_run=False
    )
    response = client.post(f"/file-jobs/{job.id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_cancel_already_terminal_job_returns_409(client, db_session):
    job = file_jobs_service.create_file_job(
        db_session, job_type="collection_export", user_id=TEST_USER_ID, dry_run=False
    )
    file_jobs_service.complete_file_job(db_session, job.id, summary={"size_bytes": 0})
    response = client.post(f"/file-jobs/{job.id}/cancel")
    assert response.status_code == 409


def test_cleanup_dry_run_does_not_delete(db_session):
    old_cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    job = file_jobs_service.create_file_job(
        db_session, job_type="collection_export", user_id=TEST_USER_ID, dry_run=False
    )
    file_jobs_service.complete_file_job(db_session, job.id, summary={"size_bytes": 0})
    job.finished_at = old_cutoff
    db_session.commit()

    result = file_jobs_service.cleanup_old_file_jobs(db_session, older_than_days=7, dry_run=True)
    assert result.would_delete == 1
    assert result.deleted == 0
    assert file_jobs_service.get_file_job(db_session, job.id) is not None


def test_cleanup_apply_requires_confirm(db_session):
    import pytest

    with pytest.raises(file_jobs_service.CleanupConfirmationRequired):
        file_jobs_service.cleanup_old_file_jobs(db_session, older_than_days=7, dry_run=False, confirm=None)


def test_cleanup_apply_with_confirm_deletes_old_terminal_jobs(client, db_session):
    old_cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    job = file_jobs_service.create_file_job(
        db_session, job_type="collection_export", user_id=TEST_USER_ID, dry_run=False
    )
    job_id = job.id
    file_jobs_service.complete_file_job(db_session, job_id, summary={"size_bytes": 0})
    job.finished_at = old_cutoff
    db_session.commit()

    response = client.post(
        "/admin/file-jobs/cleanup", json={"older_than_days": 7, "dry_run": False, "confirm": "CLEANUP"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] == 1

    # The cleanup endpoint deleted the row via its own (different) session -
    # db_session's identity map still holds the now-stale `job` object, so
    # expire_all() forces a fresh read instead of an ObjectDeletedError from
    # refreshing an identity-mapped instance whose row is gone. job_id was
    # captured above, before expiring - reading job.id afterward would
    # itself trigger the same reload-of-a-deleted-row error.
    db_session.expire_all()
    assert file_jobs_service.get_file_job(db_session, job_id) is None


def test_cleanup_never_deletes_running_jobs(db_session):
    job = file_jobs_service.create_file_job(
        db_session, job_type="collection_export", user_id=TEST_USER_ID, dry_run=False
    )
    file_jobs_service.start_file_job(db_session, job.id)
    old_cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    job.started_at = old_cutoff
    db_session.commit()

    result = file_jobs_service.cleanup_old_file_jobs(db_session, older_than_days=7, dry_run=False, confirm="CLEANUP")
    assert result.deleted == 0
    assert file_jobs_service.get_file_job(db_session, job.id) is not None


def test_system_check_warns_when_file_job_storage_unwritable(client, db_session, monkeypatch):
    from app.services import system_check as system_check_module

    monkeypatch.setattr(system_check_module, "is_storage_writable", lambda: False)

    response = client.get("/admin/system-check")
    assert response.status_code == 200
    checks = {c["name"]: c for c in response.json()["checks"]}
    assert checks["file_job_storage_writable"]["status"] == "warning"


def test_system_check_warns_on_stale_running_file_job(client, db_session):
    job = file_jobs_service.create_file_job(
        db_session, job_type="collection_export", user_id=TEST_USER_ID, dry_run=False
    )
    file_jobs_service.start_file_job(db_session, job.id)
    stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=3)
    job.started_at = stale_cutoff
    db_session.commit()

    response = client.get("/admin/system-check")
    checks = {c["name"]: c for c in response.json()["checks"]}
    assert checks["stale_running_file_jobs"]["status"] == "warning"


def test_performance_summary_includes_file_job_counts(client, db_session):
    file_jobs_service.create_file_job(
        db_session, job_type="collection_export", user_id=TEST_USER_ID, dry_run=False
    )
    response = client.get("/admin/performance/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["file_jobs_by_status"]["queued"] == 1
    assert "stale_running_file_jobs" in body


def test_data_retention_policy_includes_file_jobs(client, db_session):
    response = client.get("/admin/data-retention/policy")
    assert response.status_code == 200
    tables = {p["table"] for p in response.json()["policies"]}
    assert "file_jobs" in tables
