from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.schemas import (
    CatalogOperationsSummaryOut,
    SystemCheckResponseOut,
    SystemCheckResultOut,
    SystemCheckSummaryOut,
)
from app.services.app_logging import record_app_log
from app.services.system_check import (
    build_catalog_operations_summary,
    overall_status,
    run_system_check,
)

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_token)]
)


@router.get("/system-check", response_model=SystemCheckResponseOut)
def system_check_endpoint(db: Session = Depends(get_db)):
    checks = run_system_check(db)

    checks_passed = sum(1 for c in checks if c.status == "pass")
    warnings = sum(1 for c in checks if c.status == "warning")
    critical = sum(1 for c in checks if c.status == "fail")
    status = overall_status(checks)

    if status == "critical":
        failed = [c.name for c in checks if c.status == "fail"]
        record_app_log(
            "error",
            "api",
            "system_check",
            f"system-check reported critical status ({len(failed)} failed check(s)).",
            context={"failed_checks": failed},
        )

    return SystemCheckResponseOut(
        status=status,
        summary=SystemCheckSummaryOut(
            checks_total=len(checks),
            checks_passed=checks_passed,
            warnings=warnings,
            critical=critical,
        ),
        checks=[
            SystemCheckResultOut(
                name=c.name, status=c.status, severity=c.severity, message=c.message
            )
            for c in checks
        ],
        catalog_operations=CatalogOperationsSummaryOut(
            **build_catalog_operations_summary(db)
        ),
    )
