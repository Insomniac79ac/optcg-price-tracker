from fastapi import APIRouter, Depends

from app.auth import require_admin_token
from app.core.env_validation import overall_status, validate_environment
from app.schemas import EnvCheckResponseOut, EnvCheckResultOut
from app.services.app_logging import record_app_log

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_token)]
)


@router.get("/env-check", response_model=EnvCheckResponseOut)
def env_check_endpoint():
    report = validate_environment()
    status = overall_status(report.checks)

    if status == "critical":
        record_app_log(
            "error",
            "api",
            "env_validation",
            f"env-check reported critical status ({len(report.errors)} error(s)).",
            context={"app_env": report.app_env, "errors": report.errors, "warnings": report.warnings},
        )

    return EnvCheckResponseOut(
        status=status,
        app_env=report.app_env,
        checks=[
            EnvCheckResultOut(name=c.name, status=c.status, severity=c.severity, message=c.message)
            for c in report.checks
        ],
        warnings=report.warnings,
        errors=report.errors,
    )
