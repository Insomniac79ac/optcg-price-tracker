from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.admin_logs import app_log_to_out
from app.auth import require_admin_token
from app.db import get_db
from app.schemas import ReleaseReadinessOut, ReleaseStatusOut, SystemCheckResponseOut
from app.services.release_status import build_release_status

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_token)]
)


@router.get("/release-status", response_model=ReleaseStatusOut)
def release_status_endpoint(db: Session = Depends(get_db)):
    status = build_release_status(db)

    return ReleaseStatusOut(
        version=status.version,
        git_commit=status.git_commit,
        build_time=status.build_time,
        app_env=status.app_env,
        latest_market_workflow_run=status.latest_market_workflow_run,
        latest_system_check=SystemCheckResponseOut(**status.latest_system_check),
        latest_backup=status.latest_backup,
        latest_error=app_log_to_out(status.latest_error) if status.latest_error is not None else None,
        release_readiness=ReleaseReadinessOut(**status.release_readiness),
    )
