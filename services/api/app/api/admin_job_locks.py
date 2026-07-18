from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.schemas import (
    JobLockCleanupResponseOut,
    JobLockForceReleaseRequestIn,
    JobLockForceReleaseResponseOut,
    JobLockListOut,
    JobLockOut,
)
from app.services.job_locks import (
    LOCK_NAMES,
    force_release_expired_locks,
    force_release_lock,
    get_active_locks,
)

router = APIRouter(
    prefix="/admin/job-locks", tags=["admin", "job-locks"], dependencies=[Depends(require_admin_token)]
)

FORCE_RELEASE_CONFIRM_PHRASE = "RELEASE"


def _to_out(lock) -> JobLockOut:
    return JobLockOut(
        lock_name=lock.lock_name,
        owner_id=lock.owner_id,
        acquired_at=lock.acquired_at,
        expires_at=lock.expires_at,
        status=lock.status,
        metadata=lock.metadata_json,
    )


@router.get("", response_model=JobLockListOut)
def list_job_locks(db: Session = Depends(get_db)):
    return JobLockListOut(locks=[_to_out(lock) for lock in get_active_locks()])


@router.post("/cleanup-expired", response_model=JobLockCleanupResponseOut)
def cleanup_expired_job_locks(db: Session = Depends(get_db)):
    count = force_release_expired_locks()
    return JobLockCleanupResponseOut(cleaned_up_count=count)


@router.post("/{lock_name}/force-release", response_model=JobLockForceReleaseResponseOut)
def force_release_job_lock(
    lock_name: str, body: JobLockForceReleaseRequestIn, db: Session = Depends(get_db)
):
    if lock_name not in LOCK_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown lock_name: {lock_name}")
    if body.confirm != FORCE_RELEASE_CONFIRM_PHRASE:
        raise HTTPException(
            status_code=400,
            detail=f"Force release requires confirm={FORCE_RELEASE_CONFIRM_PHRASE!r}.",
        )

    released_lock = force_release_lock(lock_name)
    return JobLockForceReleaseResponseOut(released=released_lock is not None, lock_name=lock_name)
