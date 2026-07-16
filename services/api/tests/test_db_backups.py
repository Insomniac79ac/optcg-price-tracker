from app.services.db_backups import list_db_backups
from app.settings import settings


def test_list_db_backups_returns_empty_for_missing_dir(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert list_db_backups(str(missing)) == []


def test_list_db_backups_ignores_non_matching_files(tmp_path):
    (tmp_path / "opcg_db_backup_20260101_000000.sql.gz").write_bytes(b"x")
    (tmp_path / "not-a-backup.txt").write_bytes(b"x")
    (tmp_path / "opcg_db_backup_20260101_000000.sql.gz.partial").write_bytes(b"x")

    backups = list_db_backups(str(tmp_path))

    assert [b.filename for b in backups] == ["opcg_db_backup_20260101_000000.sql.gz"]


def test_list_db_backups_sorts_newest_first(tmp_path):
    older = tmp_path / "opcg_db_backup_20260101_000000.sql.gz"
    newer = tmp_path / "opcg_db_backup_20260102_000000.sql.gz"
    older.write_bytes(b"x")
    newer.write_bytes(b"xx")
    newer_mtime = older.stat().st_mtime + 60
    import os

    os.utime(newer, (newer_mtime, newer_mtime))

    backups = list_db_backups(str(tmp_path))

    assert [b.filename for b in backups] == [newer.name, older.name]
    assert backups[0].size_bytes == 2


def test_db_backups_endpoint_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain_client = TestClient(app)
    response = plain_client.get("/admin/db-backups")
    assert response.status_code == 401


def test_db_backups_endpoint_returns_empty_list_for_missing_dir(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DB_BACKUP_DIR", str(tmp_path / "no-backups-yet"))

    response = client.get("/admin/db-backups")

    assert response.status_code == 200
    data = response.json()
    assert data["backups"] == []
    assert data["backup_dir"] == str(tmp_path / "no-backups-yet")


def test_db_backups_endpoint_lists_backups(client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DB_BACKUP_DIR", str(tmp_path))
    (tmp_path / "opcg_db_backup_20260101_000000.sql.gz").write_bytes(b"backup-contents")

    response = client.get("/admin/db-backups")

    assert response.status_code == 200
    data = response.json()
    assert len(data["backups"]) == 1
    backup = data["backups"][0]
    assert backup["filename"] == "opcg_db_backup_20260101_000000.sql.gz"
    assert backup["size_bytes"] == len(b"backup-contents")
    assert "created_at" in backup
