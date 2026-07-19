from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import FileJobAccess, file_job_access
from app.core.pagination import pagination_response
from app.db import get_db
from app.models import FileJob
from app.models.file_job import FILE_JOB_STATUSES, FILE_JOB_TYPES
from app.schemas import FileJobCancelResponseOut, FileJobListOut, FileJobOut
from app.services.file_job_storage import iter_output_chunks, resolve_path
from app.services.file_jobs import JobNotCancellable, get_file_job, list_file_jobs, request_cancel_file_job

router = APIRouter(prefix="/file-jobs", tags=["file-jobs"])


def _to_out(job: FileJob) -> FileJobOut:
    return FileJobOut(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        original_filename=job.original_filename,
        output_filename=job.output_filename,
        content_type=job.content_type,
        dry_run=job.dry_run,
        mode=job.mode,
        progress_current=job.progress_current,
        progress_total=job.progress_total,
        download_ready=job.status == "success" and job.output_file_path is not None,
        summary=job.summary_json,
        errors=job.errors_json,
        warnings=job.warnings_json,
        started_at=job.started_at,
        finished_at=job.finished_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _get_job_or_404(db: Session, job_id: int, access: FileJobAccess) -> FileJob:
    job = get_file_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="File job not found")
    if not access.is_admin and job.user_id != access.user.id:
        # Same "404, not 403" pattern as e.g. collection._get_item_or_404 -
        # a job owned by someone else must not even be confirmed to exist.
        raise HTTPException(status_code=404, detail="File job not found")
    return job


@router.get("", response_model=FileJobListOut)
def list_file_jobs_endpoint(
    job_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    access: FileJobAccess = Depends(file_job_access),
):
    if job_type is not None and job_type not in FILE_JOB_TYPES:
        raise HTTPException(
            status_code=400, detail=f"Invalid job_type. Must be one of {list(FILE_JOB_TYPES)}"
        )
    if status is not None and status not in FILE_JOB_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"Invalid status. Must be one of {list(FILE_JOB_STATUSES)}"
        )

    result = list_file_jobs(
        db,
        job_type=job_type,
        status=status,
        user_id=None if access.is_admin else access.user.id,
        admin=access.is_admin,
        limit=limit,
        offset=offset,
    )
    jobs_out = [_to_out(j) for j in result.jobs]
    return FileJobListOut(
        jobs=jobs_out,
        total=result.total,
        limit=limit,
        offset=offset,
        pagination=pagination_response(jobs_out, result.total, limit, offset),
    )


@router.get("/{job_id}", response_model=FileJobOut)
def get_file_job_endpoint(
    job_id: int, db: Session = Depends(get_db), access: FileJobAccess = Depends(file_job_access)
):
    job = _get_job_or_404(db, job_id, access)
    return _to_out(job)


@router.get("/{job_id}/download")
def download_file_job_endpoint(
    job_id: int, db: Session = Depends(get_db), access: FileJobAccess = Depends(file_job_access)
):
    job = _get_job_or_404(db, job_id, access)

    if job.status != "success":
        raise HTTPException(
            status_code=409, detail=f"File job is not ready for download (status={job.status})"
        )
    if not job.output_file_path or not resolve_path(job.output_file_path).exists():
        raise HTTPException(status_code=404, detail="Output file is no longer available")

    filename = job.output_filename or f"file_job_{job.id}"
    return StreamingResponse(
        iter_output_chunks(job.output_file_path),
        media_type=job.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{job_id}/cancel", response_model=FileJobCancelResponseOut)
def cancel_file_job_endpoint(
    job_id: int, db: Session = Depends(get_db), access: FileJobAccess = Depends(file_job_access)
):
    _get_job_or_404(db, job_id, access)
    try:
        job = request_cancel_file_job(db, job_id)
    except JobNotCancellable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return FileJobCancelResponseOut(id=job.id, status=job.status)
