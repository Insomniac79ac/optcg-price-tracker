from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.schemas import CardAuditReportOut
from app.services.card_audit import run_card_audit

router = APIRouter(
    prefix="/admin/card-audit", tags=["admin"], dependencies=[Depends(require_admin_token)]
)


@router.get("", response_model=CardAuditReportOut)
def get_card_audit(db: Session = Depends(get_db)) -> CardAuditReportOut:
    report = run_card_audit(db)
    return CardAuditReportOut.model_validate(report.to_dict())
