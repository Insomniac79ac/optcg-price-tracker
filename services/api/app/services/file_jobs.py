"""Background file-job lifecycle (create/start/progress/complete/fail/list/
get/cancel/cleanup) plus the actual processing logic for every job type -
see 'Large import/export jobs' in docs/operations.md and GET/POST
/file-jobs*, /collection/import.csv?background=true, /collection/export.csv/
job, /wishlist/import.csv?background=true, /wishlist/export.csv/job, and
POST /admin/backup/export/job.

Why processing runs in this API service, not services/worker: the worker
deployable has its own, much smaller SQLAlchemy model set (no WishlistItem,
CollectorTag/CollectorGroup, GradingSubmission, User, ...) and no per-user
auth concept - it exists to run source-adapter/scraping-adjacent jobs
against the same Postgres database, not to duplicate this service's CSV/
backup business logic (tag/group assignment, upsert matching, the ~20-table
backup export/restore registry). Re-implementing all of that in worker
would mean maintaining two divergent copies of the same behavior for a
feature that isn't scraping-related at all. Processing instead runs via
FastAPI BackgroundTasks, in this same process, after the request that
created the job returns its 202 - see dispatch_file_job(). Whether that
happens synchronously (blocking the creating request - the sync-fallback/
dev path) or truly in the background (BackgroundTasks, so the 202 returns
immediately - the production default) is controlled by
app.env.file_jobs_sync_fallback_effective(); both paths call the exact same
process_file_job().

Cancellation is checked once, immediately before a job's real work begins,
for every job type - and additionally between output chunks for the export
job types, which are implemented here as row-streaming generators (see
app.services.collection_csv.iter_collection_csv_rows). Collection/wishlist
CSV *import* and backup export are each a single well-tested, atomic
all-or-nothing call into existing service code (import_collection_csv,
export_backup) - restructuring those into a chunked/resumable form just to
support mid-operation cancellation was judged out of proportion for this
feature (see 'if practical' in the task spec); once one of those calls has
started, a cancel request against a 'running' job is recorded but only
takes effect on the job's next natural checkpoint, if any.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.env import file_jobs_sync_fallback_effective
from app.models import FileJob
from app.models.file_job import FILE_JOB_TYPES
from app.services import collection_csv, file_job_storage, wishlist_csv
from app.services.app_logging import record_app_log
from app.services.backup import export_backup
from app.services.backup import export_filename as backup_export_filename
from app.services.collection_csv import import_collection_csv
from app.services.wishlist_csv import import_wishlist_csv

TERMINAL_STATUSES = ("success", "failed", "cancelled")

# How often (in rows) a background export checks for a cancellation request
# between chunks - see module docstring.
CANCEL_CHECK_INTERVAL_ROWS = 200

CLEANUP_CONFIRM_PHRASE = "CLEANUP"


class JobNotCancellable(ValueError):
    pass


class CleanupConfirmationRequired(ValueError):
    pass


class _JobCancelled(Exception):
    """Internal control-flow signal only - never escapes process_file_job."""


# --- lifecycle -------------------------------------------------------------


def create_file_job(
    db: Session,
    *,
    job_type: str,
    user_id: int | None = None,
    original_filename: str | None = None,
    input_file_path: str | None = None,
    dry_run: bool = True,
    mode: str | None = None,
    params: dict[str, Any] | None = None,
) -> FileJob:
    """Creates a job in status='queued'. `params` (job-type-specific inputs
    that don't have their own column - e.g. a backup_export job's
    include_prices/include_raw_snapshots/include_refresh_runs/include_logs
    flags) is stashed under summary_json['job_params'] until processing
    starts, at which point it's read once and summary_json is overwritten
    with the real result summary."""
    if job_type not in FILE_JOB_TYPES:
        raise ValueError(f"job_type must be one of {FILE_JOB_TYPES}")

    job = FileJob(
        job_type=job_type,
        status="queued",
        user_id=user_id,
        original_filename=original_filename,
        input_file_path=input_file_path,
        dry_run=dry_run,
        mode=mode,
        summary_json={"job_params": params} if params else None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    record_app_log(
        "info",
        "api",
        "file_job_created",
        f"File job #{job.id} created ({job_type}).",
        context={"file_job_id": job.id, "job_type": job_type, "dry_run": dry_run, "mode": mode},
        related_entity_type="file_job",
        related_entity_id=job.id,
    )
    return job


def start_file_job(db: Session, job_id: int) -> FileJob:
    job = db.get(FileJob, job_id)
    if job is None:
        raise ValueError(f"file_job {job_id} not found")
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)

    record_app_log(
        "info",
        "api",
        "file_job_started",
        f"File job #{job.id} started ({job.job_type}).",
        context={"file_job_id": job.id, "job_type": job.job_type},
        related_entity_type="file_job",
        related_entity_id=job.id,
    )
    return job


def update_file_job_progress(
    db: Session, job_id: int, *, current: int, total: int | None = None
) -> None:
    """Lightweight, unlogged - see module docstring on why lifecycle
    transitions are logged but progress updates are not (same reasoning as
    app.services.cache not logging every hit/miss)."""
    job = db.get(FileJob, job_id)
    if job is None:
        return
    job.progress_current = current
    if total is not None:
        job.progress_total = total
    db.commit()


def complete_file_job(
    db: Session,
    job_id: int,
    *,
    output_file_path: str | None = None,
    output_filename: str | None = None,
    content_type: str | None = None,
    summary: dict[str, Any] | None = None,
    errors: list[Any] | None = None,
    warnings: list[Any] | None = None,
) -> FileJob:
    job = db.get(FileJob, job_id)
    if job is None:
        raise ValueError(f"file_job {job_id} not found")

    job.status = "success"
    job.finished_at = datetime.now(timezone.utc)
    if output_file_path is not None:
        job.output_file_path = output_file_path
    if output_filename is not None:
        job.output_filename = output_filename
    if content_type is not None:
        job.content_type = content_type
    job.summary_json = summary
    job.errors_json = errors
    job.warnings_json = warnings
    db.commit()
    db.refresh(job)

    record_app_log(
        "info",
        "api",
        "file_job_success",
        f"File job #{job.id} succeeded ({job.job_type}).",
        context={"file_job_id": job.id, "job_type": job.job_type, "summary": summary},
        related_entity_type="file_job",
        related_entity_id=job.id,
    )
    return job


def fail_file_job(
    db: Session, job_id: int, *, error: str, warnings: list[Any] | None = None
) -> FileJob:
    job = db.get(FileJob, job_id)
    if job is None:
        raise ValueError(f"file_job {job_id} not found")

    job.status = "failed"
    job.finished_at = datetime.now(timezone.utc)
    job.errors_json = [{"error": error}]
    job.warnings_json = warnings
    db.commit()
    db.refresh(job)

    record_app_log(
        "error",
        "api",
        "file_job_failed",
        f"File job #{job.id} failed ({job.job_type}): {error}",
        context={"file_job_id": job.id, "job_type": job.job_type, "error": error},
        related_entity_type="file_job",
        related_entity_id=job.id,
    )
    return job


def request_cancel_file_job(db: Session, job_id: int) -> FileJob:
    """If queued, cancels immediately. If running, records the request in
    summary_json (checked at the job's next cancellation checkpoint - see
    module docstring) without changing its status yet. Raises
    JobNotCancellable for a job already in a terminal state."""
    job = db.get(FileJob, job_id)
    if job is None:
        raise ValueError(f"file_job {job_id} not found")

    if job.status == "queued":
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)
        record_app_log(
            "info",
            "api",
            "file_job_cancelled",
            f"File job #{job.id} cancelled (was queued).",
            context={"file_job_id": job.id, "job_type": job.job_type},
            related_entity_type="file_job",
            related_entity_id=job.id,
        )
        return job

    if job.status == "running":
        summary = dict(job.summary_json or {})
        summary["cancel_requested"] = True
        job.summary_json = summary
        db.commit()
        db.refresh(job)
        return job

    raise JobNotCancellable(f"file_job {job_id} is already {job.status!r} and cannot be cancelled")


def _cancel_requested(db: Session, job_id: int) -> bool:
    """Fresh (non-ORM-cached) read of just the columns cancellation cares
    about - a plain column SELECT within the same open transaction sees any
    other session's already-committed changes under Postgres's default READ
    COMMITTED isolation, so this correctly observes a cancel request made by
    a different request's session while this one is mid-job."""
    row = db.execute(
        select(FileJob.status, FileJob.summary_json).where(FileJob.id == job_id)
    ).first()
    if row is None:
        return True
    status, summary_json = row
    if status == "cancelled":
        return True
    return bool((summary_json or {}).get("cancel_requested"))


def _mark_cancelled(db: Session, job: FileJob) -> None:
    job.status = "cancelled"
    job.finished_at = datetime.now(timezone.utc)
    db.commit()
    record_app_log(
        "info",
        "api",
        "file_job_cancelled",
        f"File job #{job.id} cancelled during processing.",
        context={"file_job_id": job.id, "job_type": job.job_type},
        related_entity_type="file_job",
        related_entity_id=job.id,
    )


# --- list/get ----------------------------------------------------------


@dataclass
class FileJobListResult:
    jobs: list[FileJob]
    total: int


def list_file_jobs(
    db: Session,
    *,
    job_type: str | None = None,
    status: str | None = None,
    user_id: int | None = None,
    admin: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> FileJobListResult:
    """admin=True returns every job regardless of owner (for GET /file-jobs
    via X-Admin-Token, e.g. the /admin/file-jobs page); otherwise results
    are scoped to user_id - see app.api.file_jobs's access-control
    dependency for why this scoping exists at all."""
    filters = []
    if job_type is not None:
        filters.append(FileJob.job_type == job_type)
    if status is not None:
        filters.append(FileJob.status == status)
    if not admin:
        filters.append(FileJob.user_id == user_id)

    total = db.scalar(select(func.count()).select_from(FileJob).where(*filters)) or 0
    jobs = db.scalars(
        select(FileJob)
        .where(*filters)
        .order_by(FileJob.created_at.desc(), FileJob.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return FileJobListResult(jobs=list(jobs), total=total)


def get_file_job(db: Session, job_id: int) -> FileJob | None:
    return db.get(FileJob, job_id)


# --- cleanup -------------------------------------------------------------


@dataclass
class CleanupResult:
    dry_run: bool
    older_than_days: int
    would_delete: int
    deleted: int = 0


def cleanup_old_file_jobs(
    db: Session, *, older_than_days: int = 7, dry_run: bool = True, confirm: str | None = None
) -> CleanupResult:
    """Deletes file_jobs rows (and their input/output files) in a terminal
    status whose finished_at is older than older_than_days. Never touches a
    queued/running job. dry_run=True (the default) only counts what would be
    deleted; dry_run=False requires confirm='CLEANUP'."""
    if not dry_run and confirm != CLEANUP_CONFIRM_PHRASE:
        raise CleanupConfirmationRequired(
            f"dry_run=false requires confirm={CLEANUP_CONFIRM_PHRASE!r}"
        )

    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    candidates = db.scalars(
        select(FileJob).where(
            FileJob.status.in_(TERMINAL_STATUSES),
            FileJob.finished_at.is_not(None),
            FileJob.finished_at < cutoff,
        )
    ).all()

    would_delete = len(candidates)
    if dry_run:
        return CleanupResult(dry_run=True, older_than_days=older_than_days, would_delete=would_delete)

    deleted_count = 0
    for job in candidates:
        file_job_storage.delete_file(job.input_file_path)
        file_job_storage.delete_file(job.output_file_path)
        db.delete(job)
        deleted_count += 1
    db.commit()

    record_app_log(
        "info",
        "api",
        "file_job_cleanup_completed",
        f"File job cleanup: {deleted_count} job(s) older than {older_than_days} day(s) deleted.",
        context={"older_than_days": older_than_days, "deleted_count": deleted_count},
    )
    return CleanupResult(
        dry_run=False, older_than_days=older_than_days, would_delete=would_delete, deleted=deleted_count
    )


# --- dispatch/processing -----------------------------------------------


def dispatch_file_job(job_id: int, background_tasks: Any | None) -> None:
    """Runs process_file_job(job_id) either immediately (sync fallback) or
    via FastAPI BackgroundTasks (so the caller's 202 returns first) - see
    module docstring. `background_tasks` is a fastapi.BackgroundTasks or
    None; typed as Any here so this module doesn't need a hard fastapi
    import solely for a type hint."""
    if background_tasks is not None and not file_jobs_sync_fallback_effective():
        background_tasks.add_task(process_file_job, job_id)
    else:
        process_file_job(job_id)


def process_file_job(job_id: int) -> None:
    """The actual background work for one job - opens its own short-lived
    session (same reasoning as app.services.job_locks/app_logging: this may
    run well after the HTTP request that created the job has closed its own
    session, especially under BackgroundTasks)."""
    db = SessionLocal()
    try:
        job = db.get(FileJob, job_id)
        if job is None or job.status == "cancelled":
            return

        start_file_job(db, job_id)
        db.refresh(job)

        try:
            if _cancel_requested(db, job_id):
                raise _JobCancelled()

            if job.job_type == "collection_import":
                _process_collection_import(db, job)
            elif job.job_type == "wishlist_import":
                _process_wishlist_import(db, job)
            elif job.job_type == "collection_export":
                _process_collection_export(db, job)
            elif job.job_type == "wishlist_export":
                _process_wishlist_export(db, job)
            elif job.job_type == "backup_export":
                _process_backup_export(db, job)
            else:
                # backup_validate/backup_restore are modeled (FILE_JOB_TYPES)
                # for schema completeness but have no create-path yet - see
                # module docstring. A future backup_restore implementation
                # must wrap its work in with_job_lock("backup_restore"),
                # same as POST /admin/backup/restore.
                raise ValueError(
                    f"No background processing implemented for job_type={job.job_type!r}"
                )
        except _JobCancelled:
            db.rollback()
            _mark_cancelled(db, job)
        except Exception as exc:  # noqa: BLE001 - any failure must be recorded, not crash the task
            db.rollback()
            fail_file_job(db, job_id, error=str(exc))
    finally:
        db.close()


def _process_collection_import(db: Session, job: FileJob) -> None:
    assert job.input_file_path is not None
    csv_text = file_job_storage.read_input_text(job.input_file_path)
    result = import_collection_csv(
        db, csv_text, dry_run=job.dry_run, mode=job.mode or "upsert", user_id=job.user_id
    )
    update_file_job_progress(db, job.id, current=result.total_rows, total=result.total_rows)
    if not job.dry_run:
        collection_csv.invalidate_collection_write_caches()

    summary = {
        "total_rows": result.total_rows,
        "valid_rows": result.valid_rows,
        "error_rows": result.error_rows,
        "created": result.created,
        "updated": result.updated,
        "skipped": result.skipped,
        "tags_created": result.tags_created,
        "groups_created": result.groups_created,
    }
    errors = (
        [{"row_number": e.row_number, "card_code": e.card_code, "error": e.error} for e in result.errors]
        or None
    )
    complete_file_job(db, job.id, summary=summary, errors=errors)


def _process_wishlist_import(db: Session, job: FileJob) -> None:
    assert job.input_file_path is not None
    csv_text = file_job_storage.read_input_text(job.input_file_path)
    result = import_wishlist_csv(
        db, csv_text, dry_run=job.dry_run, mode=job.mode or "upsert", user_id=job.user_id
    )
    update_file_job_progress(db, job.id, current=result.total_rows, total=result.total_rows)
    if not job.dry_run:
        wishlist_csv.invalidate_wishlist_write_caches()

    summary = {
        "total_rows": result.total_rows,
        "valid_rows": result.valid_rows,
        "error_rows": result.error_rows,
        "created": result.created,
        "updated": result.updated,
        "skipped": result.skipped,
    }
    errors = (
        [{"row_number": e.row_number, "card_code": e.card_code, "error": e.error} for e in result.errors]
        or None
    )
    complete_file_job(db, job.id, summary=summary, errors=errors)


def _checked_chunks(db: Session, job_id: int, rows: Iterator[str]) -> Iterator[str]:
    for i, chunk in enumerate(rows):
        if i % CANCEL_CHECK_INTERVAL_ROWS == 0 and _cancel_requested(db, job_id):
            raise _JobCancelled()
        yield chunk


def _process_collection_export(db: Session, job: FileJob) -> None:
    assert job.user_id is not None
    output_path = file_job_storage.allocate_output_path(job.id, extension=".csv")
    rows = collection_csv.iter_collection_csv_rows(db, user_id=job.user_id)
    size = file_job_storage.write_output_chunks(output_path, _checked_chunks(db, job.id, rows))
    filename = collection_csv.export_filename()
    complete_file_job(
        db,
        job.id,
        output_file_path=output_path,
        output_filename=filename,
        content_type="text/csv",
        summary={"size_bytes": size},
    )


def _process_wishlist_export(db: Session, job: FileJob) -> None:
    assert job.user_id is not None
    output_path = file_job_storage.allocate_output_path(job.id, extension=".csv")
    rows = wishlist_csv.iter_wishlist_csv_rows(db, user_id=job.user_id)
    size = file_job_storage.write_output_chunks(output_path, _checked_chunks(db, job.id, rows))
    filename = wishlist_csv.export_filename()
    complete_file_job(
        db,
        job.id,
        output_file_path=output_path,
        output_filename=filename,
        content_type="text/csv",
        summary={"size_bytes": size},
    )


def _process_backup_export(db: Session, job: FileJob) -> None:
    params = (job.summary_json or {}).get("job_params", {})
    backup = export_backup(
        db,
        include_prices=params.get("include_prices", False),
        include_raw_snapshots=params.get("include_raw_snapshots", False),
        include_refresh_runs=params.get("include_refresh_runs", False),
        include_logs=params.get("include_logs", False),
    )
    output_path = file_job_storage.allocate_output_path(job.id, extension=".json")
    size = file_job_storage.write_output_text(output_path, json.dumps(backup, indent=2))
    filename = backup_export_filename()
    row_counts = {table: len(rows) for table, rows in backup["tables"].items()}
    complete_file_job(
        db,
        job.id,
        output_file_path=output_path,
        output_filename=filename,
        content_type="application/json",
        summary={"size_bytes": size, "row_counts": row_counts},
    )
