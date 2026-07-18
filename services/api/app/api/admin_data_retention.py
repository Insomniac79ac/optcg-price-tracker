from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.db import get_db
from app.schemas import (
    DataRetentionPolicyOut,
    DataRetentionPolicyResponseOut,
    DataRetentionPruneRequestIn,
    DataRetentionPruneResponseOut,
    DataRetentionPruneResultOut,
    DataRetentionPruneSummaryOut,
)
from app.services.data_retention import PruneConfirmationRequired, list_policies, prune_tables

router = APIRouter(
    prefix="/admin/data-retention", tags=["admin"], dependencies=[Depends(require_admin_token)]
)


@router.get("/policy", response_model=DataRetentionPolicyResponseOut)
def data_retention_policy_endpoint():
    return DataRetentionPolicyResponseOut(
        policies=[
            DataRetentionPolicyOut(
                table=p.table,
                retention_days=p.retention_days,
                mode=p.mode,
                protected_records=p.protected_records,
                enabled=p.enabled,
            )
            for p in list_policies()
        ]
    )


@router.post("/prune", response_model=DataRetentionPruneResponseOut)
def data_retention_prune_endpoint(body: DataRetentionPruneRequestIn, db: Session = Depends(get_db)):
    try:
        result = prune_tables(
            db, dry_run=body.dry_run, tables=body.tables, confirm=body.confirm
        )
    except PruneConfirmationRequired as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return DataRetentionPruneResponseOut(
        dry_run=result.dry_run,
        summary=DataRetentionPruneSummaryOut(**result.summary),
        results=[
            DataRetentionPruneResultOut(
                table=r.table,
                retention_days=r.retention_days,
                rows_would_delete=r.rows_would_delete,
                rows_deleted=r.rows_deleted,
                status=r.status,
                warning=r.warning,
            )
            for r in result.results
        ],
    )
