from fastapi import APIRouter, Depends, Query

from app.auth import require_admin_token
from app.core.pagination import pagination_response, parse_pagination
from app.schemas import DbBackupFileOut, DbBackupListOut
from app.services.db_backups import list_db_backups
from app.settings import settings

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_token)]
)


@router.get("/db-backups", response_model=DbBackupListOut)
def list_db_backups_endpoint(
    limit: int | None = Query(default=None),
    offset: int | None = Query(default=None),
):
    resolved_limit, resolved_offset = parse_pagination(limit, offset)
    all_backups = list_db_backups(settings.DB_BACKUP_DIR)
    page = all_backups[resolved_offset : resolved_offset + resolved_limit]
    backups_out = [
        DbBackupFileOut(filename=b.filename, size_bytes=b.size_bytes, created_at=b.created_at)
        for b in page
    ]
    return DbBackupListOut(
        backup_dir=settings.DB_BACKUP_DIR,
        backups=backups_out,
        limit=resolved_limit,
        offset=resolved_offset,
        pagination=pagination_response(backups_out, len(all_backups), resolved_limit, resolved_offset),
    )
