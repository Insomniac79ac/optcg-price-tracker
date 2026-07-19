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
from app.services.cache import delete_cache_prefix
from app.services.data_retention import PruneConfirmationRequired, list_policies, prune_tables

router = APIRouter(
    prefix="/admin/data-retention", tags=["admin"], dependencies=[Depends(require_admin_token)]
)

# Prunable tables that back a cached endpoint's data - see 'Cache
# invalidation' in docs/operations.md. Pruning any of these (a real, non-dry
# run that actually deleted rows) can change what the corresponding cached
# response would return, so those prefixes are invalidated after the fact.
_PRUNE_CACHE_PREFIXES_BY_TABLE = {
    "market_intelligence_reports": ("dashboard", "market_report", "market_reports"),
    "portfolio_valuation_snapshots": ("dashboard", "collection_history"),
    "price_observations": ("dashboard", "collection_valuation", "market_signals", "market_opportunities"),
    "market_signal_events": ("dashboard", "market_signals", "market_signal_events"),
}


def _file_jobs_policy() -> DataRetentionPolicyOut:
    """file_jobs isn't wired into the generic prune_tables() engine above -
    unlike every other prunable table, cleaning it up must also delete the
    job's input/output files on disk (see
    app.services.file_jobs.cleanup_old_file_jobs), not just the DB row, and
    prune_tables()'s generic apply step only ever does a bare `DELETE ...
    WHERE id IN (...)`. This entry is informational only (see 'Large
    import/export jobs' in docs/operations.md); the actual mechanism is
    POST /admin/file-jobs/cleanup, not POST /admin/data-retention/prune."""
    return DataRetentionPolicyOut(
        table="file_jobs",
        retention_days=7,
        mode="see POST /admin/file-jobs/cleanup (deletes rows and their input/output files together)",
        protected_records="queued/running jobs are never pruned",
        enabled=True,
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
        + [_file_jobs_policy()]
    )


@router.post("/prune", response_model=DataRetentionPruneResponseOut)
def data_retention_prune_endpoint(body: DataRetentionPruneRequestIn, db: Session = Depends(get_db)):
    try:
        result = prune_tables(
            db, dry_run=body.dry_run, tables=body.tables, confirm=body.confirm
        )
    except PruneConfirmationRequired as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not result.dry_run:
        invalidated: set[str] = set()
        for r in result.results:
            if r.rows_deleted > 0:
                invalidated.update(_PRUNE_CACHE_PREFIXES_BY_TABLE.get(r.table, ()))
        for prefix in invalidated:
            delete_cache_prefix(prefix)

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
