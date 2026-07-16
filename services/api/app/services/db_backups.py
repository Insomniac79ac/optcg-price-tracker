"""Read-only listing of Postgres backup files created by
scripts/db_backup.sh, for GET /admin/db-backups. Never reads backup
contents - only filesystem metadata (filename, size, mtime) - so it can't
leak database rows through the admin API.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

BACKUP_GLOB = "opcg_db_backup_*.sql.gz"


@dataclass
class BackupFile:
    filename: str
    size_bytes: int
    created_at: datetime


def list_db_backups(backup_dir: str) -> list[BackupFile]:
    """Lists backup files in backup_dir, newest first. Returns an empty list
    if the directory doesn't exist - a fresh deployment with no backups yet
    isn't an error."""
    dir_path = Path(backup_dir)
    if not dir_path.is_dir():
        return []

    backups = [
        BackupFile(
            filename=path.name,
            size_bytes=path.stat().st_size,
            created_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
        )
        for path in dir_path.glob(BACKUP_GLOB)
        if path.is_file()
    ]
    backups.sort(key=lambda b: b.created_at, reverse=True)
    return backups
