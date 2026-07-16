from fastapi import APIRouter, Depends

from app.auth import require_admin_token
from app.schemas import DbBackupFileOut, DbBackupListOut
from app.services.db_backups import list_db_backups
from app.settings import settings

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_token)]
)


@router.get("/db-backups", response_model=DbBackupListOut)
def list_db_backups_endpoint():
    backups = list_db_backups(settings.DB_BACKUP_DIR)
    return DbBackupListOut(
        backup_dir=settings.DB_BACKUP_DIR,
        backups=[
            DbBackupFileOut(
                filename=b.filename, size_bytes=b.size_bytes, created_at=b.created_at
            )
            for b in backups
        ],
    )
