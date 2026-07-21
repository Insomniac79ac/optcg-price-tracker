import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.schemas import (
    BackupExportJobRequestIn,
    BackupRestoreResponseOut,
    BackupValidateResponseOut,
    FileJobCreatedOut,
)
from app.services.activity_timeline import record_activity_event
from app.services.app_logging import log_exception, record_app_log
from app.services.backup import (
    RESTORE_MODES,
    RestoreConfirmationRequired,
    export_backup,
    export_filename,
    restore_backup,
    validate_backup,
)
from app.services.file_jobs import create_file_job, dispatch_file_job

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
    include_logs: bool = Query(default=False),
    include_validation_reports: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    try:
        backup = export_backup(
            db,
            include_prices=include_prices,
            include_raw_snapshots=include_raw_snapshots,
            include_refresh_runs=include_refresh_runs,
            include_logs=include_logs,
            include_validation_reports=include_validation_reports,
        )
    except Exception as exc:
        log_exception(
            "api", "backup", "Backup export failed.", exc,
            context={
                "include_prices": include_prices,
                "include_raw_snapshots": include_raw_snapshots,
                "include_refresh_runs": include_refresh_runs,
                "include_logs": include_logs,
                "include_validation_reports": include_validation_reports,
            },
        )
        raise

    filename = export_filename()
    return Response(
        content=json.dumps(backup, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/export/job", response_model=FileJobCreatedOut, status_code=202)
def export_backup_job_endpoint(
    body: BackupExportJobRequestIn, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    """Generates the backup JSON in the background - poll GET
    /file-jobs/{id} and download via GET /file-jobs/{id}/download once
    status=success. Admin-only (no user_id) - see app.auth.file_job_access."""
    job = create_file_job(
        db,
        job_type="backup_export",
        dry_run=False,
        params={
            "include_prices": body.include_prices,
            "include_raw_snapshots": body.include_raw_snapshots,
            "include_refresh_runs": body.include_refresh_runs,
            "include_logs": body.include_logs,
            "include_validation_reports": body.include_validation_reports,
        },
    )
    dispatch_file_job(job.id, background_tasks)
    return FileJobCreatedOut(file_job_id=job.id, status=job.status)


@router.post("/validate", response_model=BackupValidateResponseOut)
async def validate_backup_endpoint(file: UploadFile = File(...)):
    backup = _load_json_upload(await file.read())
    result = validate_backup(backup)

    if not result.valid:
        record_app_log(
            "warning",
            "api",
            "backup",
            "Backup validation failed.",
            context={"errors": result.errors, "warnings": result.warnings},
        )

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

    if not dry_run:
        counts = ", ".join(
            f"{action}: {sum(by_table.values())}" for action, by_table in result.summary.items()
        )
        if result.valid and not result.errors:
            record_activity_event(
                db,
                event_type="backup_restored",
                event_source="backup",
                title=f"Backup restored (mode: {mode})",
                message=counts or None,
                payload={"mode": mode, "summary": result.summary},
            )
            record_app_log(
                "info",
                "api",
                "restore",
                f"Backup restored (mode={mode}).",
                context={"mode": mode, "summary": result.summary, "warnings": result.warnings},
            )
        else:
            record_app_log(
                "error",
                "api",
                "restore",
                f"Backup restore failed (mode={mode}).",
                context={"mode": mode, "errors": result.errors, "warnings": result.warnings},
            )

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
