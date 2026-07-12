import json

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.schemas import BackupRestoreResponseOut, BackupValidateResponseOut
from app.services.backup import (
    RESTORE_MODES,
    RestoreConfirmationRequired,
    export_backup,
    export_filename,
    restore_backup,
    validate_backup,
)

router = APIRouter(
    prefix="/admin/backup", tags=["admin", "backup"], dependencies=[Depends(require_admin_token)]
)


def _load_json_upload(raw: bytes) -> dict:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"File is not valid UTF-8: {exc}") from exc

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"File is not valid JSON: {exc}") from exc


@router.get("/export")
def export_backup_endpoint(
    include_prices: bool = Query(default=False),
    include_raw_snapshots: bool = Query(default=False),
    include_refresh_runs: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    backup = export_backup(
        db,
        include_prices=include_prices,
        include_raw_snapshots=include_raw_snapshots,
        include_refresh_runs=include_refresh_runs,
    )
    filename = export_filename()
    return Response(
        content=json.dumps(backup, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/validate", response_model=BackupValidateResponseOut)
async def validate_backup_endpoint(file: UploadFile = File(...)):
    backup = _load_json_upload(await file.read())
    result = validate_backup(backup)
    return BackupValidateResponseOut(
        valid=result.valid,
        backup_version=result.backup_version,
        summary=result.summary,
        warnings=result.warnings,
        errors=result.errors,
    )


@router.post("/restore", response_model=BackupRestoreResponseOut)
async def restore_backup_endpoint(
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    mode: str = Query(default="merge"),
    confirm: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if mode not in RESTORE_MODES:
        raise HTTPException(
            status_code=400, detail=f"Invalid mode. Must be one of {list(RESTORE_MODES)}"
        )

    backup = _load_json_upload(await file.read())

    try:
        result = restore_backup(db, backup, dry_run=dry_run, mode=mode, confirm=confirm)
    except RestoreConfirmationRequired as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return BackupRestoreResponseOut(
        dry_run=result.dry_run,
        mode=result.mode,
        valid=result.valid,
        backup_version=result.backup_version,
        summary=result.summary,
        warnings=result.warnings,
        errors=result.errors,
        preview=result.preview,
    )
