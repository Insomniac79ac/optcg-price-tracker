from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.schemas import DbIndexAuditResponseOut, DbIndexAuditSummaryOut, DbIndexCheckOut
from app.services.db_index_audit import audit_summary, run_db_index_audit

router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_token)]
)


@router.get("/db-index-audit", response_model=DbIndexAuditResponseOut)
def db_index_audit_endpoint(db: Session = Depends(get_db)):
    checks = run_db_index_audit(db)
    summary = audit_summary(checks)

    return DbIndexAuditResponseOut(
        summary=DbIndexAuditSummaryOut(**summary),
        checks=[
            DbIndexCheckOut(
                table=c.table, index=c.index, status=c.status, severity=c.severity, message=c.message
            )
            for c in checks
        ],
    )
