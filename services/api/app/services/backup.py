from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.orm import Session

from app.models import (
    AlertRule,
    AnalyticsDigestReport,
    AppLogEvent,
    Card,
    CardTag,
    CollectionItem,
    CollectionItemGroup,
    CollectionItemTag,
    CollectorActivityEvent,
    CollectorGroup,
    CollectorNote,
    CollectorTag,
    DashboardPreference,
    GradingSubmission,
    MarketIntelligenceReport,
    MarketReportDigestSend,
    MarketSignalEvent,
    MarketWorkflowRun,
    PortfolioValuationSnapshot,
    PriceObservation,
    PriceRefreshRun,
    RawSnapshot,
    SearchHistory,
    Source,
    SourceCardMapping,
    User,
    WishlistItem,
)
from app.services.job_locks import with_job_lock

# Bumped 1 -> 2 when collector tags/groups tables were added, 2 -> 3 when
# grading_submissions was added, 3 -> 4 when users was added (and
# collector_tags/collector_groups/collection_items became user-scoped), 4 -> 5
# when wishlist_items was added, 5 -> 6 when dashboard_preferences was added,
# 6 -> 7 when collector_notes/collector_activity_events (missed when those
# tables were first added) and search_history were added, and 7 -> 8 when
# analytics_digest_reports was added - these all became required tables, so a
# backup from before any of these changes predates them entirely. Rejecting
# with an explicit version mismatch is clearer than a generic "missing
# required table" error.
BACKUP_VERSION = 8
APP_NAME = "opcg-price-tracker"

# Registration order doubles as FK-safe insert order (parents before
# children) - restore/replace delete order is simply this reversed. Adding a
# new backed-up table means adding one entry here, in a position after
# whatever it references.
MODEL_BY_TABLE: dict[str, type] = {
    "users": User,
    "cards": Card,
    "sources": Source,
    "collector_tags": CollectorTag,
    "collector_groups": CollectorGroup,
    "alert_rules": AlertRule,
    "portfolio_valuation_snapshots": PortfolioValuationSnapshot,
    "price_refresh_runs": PriceRefreshRun,
    "raw_snapshots": RawSnapshot,
    "source_card_mappings": SourceCardMapping,
    "collection_items": CollectionItem,
    "wishlist_items": WishlistItem,
    "card_tags": CardTag,
    "collection_item_tags": CollectionItemTag,
    "collection_item_groups": CollectionItemGroup,
    "grading_submissions": GradingSubmission,
    "price_observations": PriceObservation,
    "market_intelligence_reports": MarketIntelligenceReport,
    "market_signal_events": MarketSignalEvent,
    "market_report_digest_sends": MarketReportDigestSend,
    "market_workflow_runs": MarketWorkflowRun,
    "analytics_digest_reports": AnalyticsDigestReport,
    "collector_notes": CollectorNote,
    "collector_activity_events": CollectorActivityEvent,
    "dashboard_preferences": DashboardPreference,
    "search_history": SearchHistory,
    "app_log_events": AppLogEvent,
}

TABLE_INSERT_ORDER: tuple[str, ...] = tuple(MODEL_BY_TABLE.keys())

REQUIRED_TABLES: tuple[str, ...] = (
    "users",
    "cards",
    "sources",
    "source_card_mappings",
    "collection_items",
    "alert_rules",
    "portfolio_valuation_snapshots",
    "market_signal_events",
    "market_intelligence_reports",
    "market_report_digest_sends",
    "market_workflow_runs",
    "analytics_digest_reports",
    "collector_tags",
    "collector_groups",
    "card_tags",
    "collection_item_tags",
    "collection_item_groups",
    "grading_submissions",
    "wishlist_items",
    "dashboard_preferences",
    "collector_notes",
    "collector_activity_events",
    "search_history",
)

OPTIONAL_TABLES: tuple[str, ...] = (
    "price_observations",
    "raw_snapshots",
    "price_refresh_runs",
    "app_log_events",
)

# Subset of OPTIONAL_TABLES that references cards/sources by FK, so
# mode=replace's cascade-delete warning below only applies to these -
# app_log_events has no FK to cards/sources (its related_* fields are plain
# integers, not real FKs; see app.models.app_log_event), so leaving it out of
# a replace restore carries no cascade risk worth warning about.
CASCADE_RISK_OPTIONAL_TABLES: tuple[str, ...] = (
    "price_observations",
    "raw_snapshots",
    "price_refresh_runs",
)

RESTORE_MODES = ("merge", "replace")

RESTORE_CONFIRM_PHRASE = "RESTORE"


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _serialize_row(instance: Any) -> dict[str, Any]:
    mapper = inspect(instance).mapper
    return {col.name: _serialize_value(getattr(instance, col.name)) for col in mapper.columns}


def _deserialize_row(model: type, row: dict[str, Any]) -> dict[str, Any]:
    mapper = inspect(model)
    converted: dict[str, Any] = {}
    for col in mapper.columns:
        name = col.name
        if name not in row:
            continue
        value = row[name]
        if value is not None and isinstance(value, str):
            try:
                py_type = col.type.python_type
            except NotImplementedError:
                py_type = None
            if py_type is datetime:
                value = datetime.fromisoformat(value)
            elif py_type is date:
                value = date.fromisoformat(value)
        converted[name] = value
    return converted


def export_backup(
    db: Session,
    *,
    include_prices: bool = False,
    include_raw_snapshots: bool = False,
    include_refresh_runs: bool = False,
    include_logs: bool = False,
) -> dict[str, Any]:
    include_flags = {
        "price_observations": include_prices,
        "raw_snapshots": include_raw_snapshots,
        "price_refresh_runs": include_refresh_runs,
        "app_log_events": include_logs,
    }

    tables: dict[str, list[dict[str, Any]]] = {}
    for table in TABLE_INSERT_ORDER:
        if table in OPTIONAL_TABLES and not include_flags[table]:
            continue
        model = MODEL_BY_TABLE[table]
        rows = db.scalars(select(model).order_by(model.id)).all()
        tables[table] = [_serialize_row(row) for row in rows]

    return {
        "metadata": {
            "app": APP_NAME,
            "backup_version": BACKUP_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "include_prices": include_prices,
            "include_raw_snapshots": include_raw_snapshots,
            "include_refresh_runs": include_refresh_runs,
            "include_logs": include_logs,
        },
        "tables": tables,
    }


def export_filename(now: datetime | None = None) -> str:
    ts = now or datetime.now(timezone.utc)
    return f"opcg_backup_{ts.strftime('%Y%m%d_%H%M%S')}.json"


@dataclass
class ValidationResult:
    valid: bool
    backup_version: int | None
    summary: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def validate_backup(backup: Any) -> ValidationResult:
    """Validates a backup's *internal* consistency - required tables present,
    row shapes sane, and FK references resolve within the backup's own data.
    Does not touch the database and never writes anything."""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(backup, dict):
        return ValidationResult(valid=False, backup_version=None, errors=["Backup must be a JSON object"])

    metadata = backup.get("metadata")
    backup_version: int | None = None
    if not isinstance(metadata, dict):
        errors.append("metadata is missing or not an object")
    else:
        backup_version = metadata.get("backup_version")
        if backup_version is None:
            errors.append("metadata.backup_version is missing")
        elif backup_version != BACKUP_VERSION:
            errors.append(
                f"Unsupported backup_version {backup_version!r}; expected {BACKUP_VERSION}"
            )

    tables = backup.get("tables")
    if not isinstance(tables, dict):
        errors.append("tables is missing or not an object")
        tables = {}

    summary: dict[str, int] = {}

    def _check_table(table: str, required: bool) -> list[dict[str, Any]] | None:
        if table not in tables:
            if required:
                errors.append(f"Missing required table: {table}")
            return None
        rows = tables[table]
        if not isinstance(rows, list):
            errors.append(f"Table '{table}' must be a list of rows")
            return None
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append(f"{table}[{i}] must be an object")
                continue
            if "id" not in row or not isinstance(row.get("id"), int):
                errors.append(f"{table}[{i}] is missing an integer 'id'")
        summary[table] = len(rows)
        return rows

    for table in REQUIRED_TABLES:
        _check_table(table, required=True)
    for table in OPTIONAL_TABLES:
        if table in tables:
            _check_table(table, required=False)

    # FK cross-checks, only meaningful once the basic shape checks passed -
    # otherwise a malformed table (e.g. not a list) would make these crash
    # rather than produce a useful error.
    if not errors:
        card_ids = {row["id"] for row in tables.get("cards", [])}
        source_ids = {row["id"] for row in tables.get("sources", [])}

        for i, row in enumerate(tables.get("collection_items", [])):
            if row.get("card_id") not in card_ids:
                errors.append(
                    f"collection_items[{i}] references missing card_id {row.get('card_id')!r}"
                )

        for i, row in enumerate(tables.get("source_card_mappings", [])):
            if row.get("card_id") not in card_ids:
                errors.append(
                    f"source_card_mappings[{i}] references missing card_id {row.get('card_id')!r}"
                )
            if row.get("source_id") not in source_ids:
                errors.append(
                    f"source_card_mappings[{i}] references missing source_id {row.get('source_id')!r}"
                )

        for i, row in enumerate(tables.get("market_signal_events", [])):
            card_id = row.get("card_id")
            if card_id is not None and card_id not in card_ids:
                errors.append(
                    f"market_signal_events[{i}] references missing card_id {card_id!r}"
                )

    return ValidationResult(
        valid=len(errors) == 0,
        backup_version=backup_version,
        summary=summary,
        warnings=warnings,
        errors=errors,
    )


def _included_tables(tables: dict[str, Any]) -> list[str]:
    return [t for t in TABLE_INSERT_ORDER if t in tables]


def _table_count(db: Session, table: str) -> int:
    model = MODEL_BY_TABLE[table]
    return db.scalar(select(func.count()).select_from(model)) or 0


def _existing_ids(db: Session, table: str, ids: set[int]) -> set[int]:
    if not ids:
        return set()
    model = MODEL_BY_TABLE[table]
    return set(db.scalars(select(model.id).where(model.id.in_(ids))).all())


def _upsert_rows(db: Session, table: str, rows: list[dict[str, Any]]) -> tuple[int, int]:
    model = MODEL_BY_TABLE[table]
    created = updated = 0
    for row in rows:
        kwargs = _deserialize_row(model, row)
        row_id = kwargs.get("id")
        existing = db.get(model, row_id)
        if existing is not None:
            for k, v in kwargs.items():
                if k == "id":
                    continue
                setattr(existing, k, v)
            updated += 1
        else:
            db.add(model(**kwargs))
            created += 1
    db.flush()
    return created, updated


def _insert_rows(db: Session, table: str, rows: list[dict[str, Any]]) -> int:
    model = MODEL_BY_TABLE[table]
    for row in rows:
        db.add(model(**_deserialize_row(model, row)))
    db.flush()
    return len(rows)


def _delete_all(db: Session, table: str) -> int:
    model = MODEL_BY_TABLE[table]
    count = _table_count(db, table)
    db.execute(delete(model))
    return count


def _reset_sequence(db: Session, table: str) -> None:
    # Table names are drawn exclusively from MODEL_BY_TABLE's fixed keys
    # (never from request/backup-file content), so this interpolation is not
    # attacker-controlled - it's the same trust boundary as any other
    # hardcoded identifier in this module.
    if db.get_bind().dialect.name != "postgresql":
        return
    seq_name = db.execute(
        text("SELECT pg_get_serial_sequence(:table, 'id')"), {"table": table}
    ).scalar()
    if seq_name is None:
        return
    db.execute(
        text(f"SELECT setval(:seq, COALESCE((SELECT MAX(id) FROM {table}), 1), true)"),
        {"seq": seq_name},
    )


@dataclass
class RestoreResult:
    dry_run: bool
    mode: str
    valid: bool
    backup_version: int | None = None
    summary: dict[str, dict[str, int]] = field(
        default_factory=lambda: {"created": {}, "updated": {}, "deleted": {}, "skipped": {}}
    )
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    preview: dict[str, dict[str, int]] = field(default_factory=dict)


class RestoreConfirmationRequired(ValueError):
    pass


def restore_backup(
    db: Session,
    backup: Any,
    *,
    dry_run: bool = True,
    mode: str = "merge",
    confirm: str | None = None,
    skip_lock: bool = False,
) -> RestoreResult:
    """Acquires the 'backup_restore' concurrency lock for the call (including
    dry_run, so a preview can't race a real restore) - shared by
    app/restore_backup.py's CLI and POST /admin/backup/restore. skip_lock is
    test/dev-CLI only. See 'Worker job concurrency locking' in
    docs/operations.md."""
    with with_job_lock("backup_restore", skip_lock=skip_lock):
        return _restore_backup_locked(db, backup, dry_run=dry_run, mode=mode, confirm=confirm)


def _restore_backup_locked(
    db: Session,
    backup: Any,
    *,
    dry_run: bool = True,
    mode: str = "merge",
    confirm: str | None = None,
) -> RestoreResult:
    if mode not in RESTORE_MODES:
        raise ValueError(f"mode must be one of {RESTORE_MODES}")

    if mode == "replace" and not dry_run and confirm != RESTORE_CONFIRM_PHRASE:
        raise RestoreConfirmationRequired(
            f"mode=replace with dry_run=false requires confirm={RESTORE_CONFIRM_PHRASE}"
        )

    validation = validate_backup(backup)
    if not validation.valid:
        return RestoreResult(
            dry_run=dry_run,
            mode=mode,
            valid=False,
            backup_version=validation.backup_version,
            warnings=validation.warnings,
            errors=validation.errors,
        )

    tables = backup["tables"]
    included = _included_tables(tables)
    warnings = list(validation.warnings)

    if mode == "replace":
        excluded_optional = [t for t in CASCADE_RISK_OPTIONAL_TABLES if t not in included]
        if excluded_optional:
            warnings.append(
                "mode=replace deletes and recreates 'cards'/'sources' rows; any existing "
                f"rows in {excluded_optional} (not included in this backup) that reference "
                "those cards/sources may be cascade-deleted by the database's own foreign "
                "key constraints, since those tables are not being restored alongside them."
            )

    if dry_run:
        preview: dict[str, dict[str, int]] = {}
        for table in included:
            rows = tables[table]
            if mode == "replace":
                preview[table] = {
                    "would_delete": _table_count(db, table),
                    "would_create": len(rows),
                }
            else:
                ids = {row["id"] for row in rows}
                existing_ids = _existing_ids(db, table, ids)
                preview[table] = {
                    "would_update": len(existing_ids),
                    "would_create": len(rows) - len(existing_ids),
                }
        return RestoreResult(
            dry_run=True,
            mode=mode,
            valid=True,
            backup_version=validation.backup_version,
            warnings=warnings,
            preview=preview,
        )

    summary: dict[str, dict[str, int]] = {"created": {}, "updated": {}, "deleted": {}, "skipped": {}}
    try:
        if mode == "replace":
            for table in reversed(included):
                summary["deleted"][table] = _delete_all(db, table)
            for table in included:
                summary["created"][table] = _insert_rows(db, table, tables[table])
        else:
            for table in included:
                created, updated = _upsert_rows(db, table, tables[table])
                summary["created"][table] = created
                summary["updated"][table] = updated

        for table in included:
            _reset_sequence(db, table)

        db.commit()
    except Exception as exc:
        db.rollback()
        return RestoreResult(
            dry_run=False,
            mode=mode,
            valid=False,
            backup_version=validation.backup_version,
            warnings=warnings,
            errors=[f"Restore failed and was rolled back: {exc}"],
        )

    return RestoreResult(
        dry_run=False,
        mode=mode,
        valid=True,
        backup_version=validation.backup_version,
        summary=summary,
        warnings=warnings,
    )
