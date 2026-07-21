"""Admin CSV import-safety tools: downloadable templates (GET
/admin/import-templates|import-templates/{type}.csv), dry-run validation
(POST /admin/import-validation/{import_type}) and its stored history (GET
/admin/import-validation/reports|reports/{id}) - see
app.services.import_templates/import_validation for the actual template
content and validation rules, and docs/operations.md's "CSV import
validation workflow" for how this fits into a real import.

The validation endpoint never writes imported data anywhere - it only ever
persists one row to import_validation_reports per call, recording what the
validation *found* (never the uploaded file's contents beyond the bounded
preview already in the report payload).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_admin_token
from app.core.pagination import pagination_response
from app.db import get_db
from app.models import ImportValidationReport
from app.schemas import (
    ImportTemplateListOut,
    ImportTemplateOut,
    ImportValidationReportDetailOut,
    ImportValidationReportListOut,
    ImportValidationReportOut,
    ImportValidationResponseOut,
)
from app.services.app_logging import record_app_log
from app.services.import_templates import TEMPLATE_TYPES, generate_template_csv, get_template, list_templates
from app.services.import_validation import IMPORT_TYPES, validate_import_csv

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_token)])


@router.get("/import-templates", response_model=ImportTemplateListOut)
def get_import_templates():
    templates = [
        ImportTemplateOut(
            **template.to_dict(download_url=f"/admin/import-templates/{template.template_type}.csv")
        )
        for template in list_templates()
    ]
    return ImportTemplateListOut(templates=templates)


@router.get("/import-templates/{template_type}.csv")
def download_import_template(template_type: str):
    csv_text = generate_template_csv(template_type)
    if csv_text is None:
        raise HTTPException(
            status_code=404, detail=f"Unknown template_type. Must be one of {list(TEMPLATE_TYPES)}"
        )
    filename = get_template(template_type).filename
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/import-validation/{import_type}", response_model=ImportValidationResponseOut)
async def validate_import_endpoint(
    import_type: str,
    file: UploadFile = File(...),
    strict: bool = Query(default=False),
    max_preview_rows: int = Query(default=100, ge=1, le=1000),
    user_id: int | None = Query(
        default=None,
        description=(
            "Scopes would_update/likely-duplicate detection for collection/wishlist rows "
            "to one user's existing items; ignored for every other import_type. Without it, "
            "collection/wishlist rows are always reported as would_create."
        ),
    ),
    db: Session = Depends(get_db),
):
    if import_type not in IMPORT_TYPES:
        raise HTTPException(
            status_code=404, detail=f"Unknown import_type. Must be one of {list(IMPORT_TYPES)}"
        )

    raw = await file.read()
    result = validate_import_csv(
        db, import_type, raw, strict=strict, max_preview_rows=max_preview_rows, user_id=user_id
    )

    report = ImportValidationReport(
        import_type=import_type,
        filename=file.filename,
        valid=result.valid,
        strict=strict,
        total_rows=result.summary.total_rows,
        valid_rows=result.summary.valid_rows,
        error_rows=result.summary.error_rows,
        warning_rows=result.summary.warning_rows,
        duplicate_rows=result.summary.duplicate_rows,
        report_payload_json=result.to_dict(),
    )
    db.add(report)
    db.commit()

    if not result.valid:
        record_app_log(
            "warning",
            "api",
            "import_validation",
            f"Import validation for {import_type} found {result.summary.error_rows} error row(s).",
            context={
                "import_type": import_type,
                "filename": file.filename,
                "error_rows": result.summary.error_rows,
                "warning_rows": result.summary.warning_rows,
            },
        )

    return ImportValidationResponseOut.model_validate(result.to_dict())


@router.get("/import-validation/reports", response_model=ImportValidationReportListOut)
def list_import_validation_reports(
    import_type: str | None = Query(default=None),
    valid: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    if import_type is not None and import_type not in IMPORT_TYPES:
        raise HTTPException(
            status_code=400, detail=f"Invalid import_type. Must be one of {list(IMPORT_TYPES)}"
        )

    query = select(ImportValidationReport)
    if import_type is not None:
        query = query.where(ImportValidationReport.import_type == import_type)
    if valid is not None:
        query = query.where(ImportValidationReport.valid == valid)

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(
        query.order_by(ImportValidationReport.created_at.desc()).limit(limit).offset(offset)
    ).all()

    return ImportValidationReportListOut(
        reports=[ImportValidationReportOut.model_validate(r) for r in rows],
        pagination=pagination_response(rows, total, limit, offset),
    )


@router.get("/import-validation/reports/{report_id}", response_model=ImportValidationReportDetailOut)
def get_import_validation_report(report_id: int, db: Session = Depends(get_db)):
    report = db.get(ImportValidationReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Import validation report not found")
    return ImportValidationReportDetailOut.model_validate(report)
