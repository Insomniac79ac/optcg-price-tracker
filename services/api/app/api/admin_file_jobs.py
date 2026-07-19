from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.schemas import FileJobCleanupRequestIn, FileJobCleanupResponseOut
from app.services.file_jobs import CleanupConfirmationRequired, cleanup_old_file_jobs

router = APIRouter(
    prefix="/admin/file-jobs", tags=["admin", "file-jobs"], dependencies=[Depends(require_admin_token)]
)


@router.post("/cleanup", response_model=FileJobCleanupResponseOut)
def cleanup_file_jobs_endpoint(body: FileJobCleanupRequestIn, db: Session = Depends(get_db)):
    try:
        result = cleanup_old_file_jobs(
            db, older_than_days=body.older_than_days, dry_run=body.dry_run, confirm=body.confirm
        )
    except CleanupConfirmationRequired as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return FileJobCleanupResponseOut(
        dry_run=result.dry_run,
        older_than_days=result.older_than_days,
        would_delete=result.would_delete,
        deleted=result.deleted,
    )
