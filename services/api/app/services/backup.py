from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.orm import Session

from app.models import (
    AlertRule,
    AnalyticsDigestReport,
    AppLogEvent,
    CanonicalCard,
    Card,
    CardAlias,
    CardPirateIndexPoint,
    CardPrint,
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
    ImportValidationReport,
    MarketIntelligenceReport,
    MarketIndexSnapshot,
    MarketReportDigestSend,
    MarketSignalEvent,
    MarketWorkflowRun,
    PortfolioValuationSnapshot,
    PriceObservation,
    PriceRefreshRun,
    RawSnapshot,
    ReleaseProduct,
    ReleaseProductAlias,
    SavedView,
    SearchHistory,
    SnkrdunkCandidate,
    SnkrdunkDiscoveryRun,
    Source,
    SourceCardMapping,
    SourceCollectionAttempt,
    User,
    WishlistItem,
    YuyuteiCandidate,
    YuyuteiDiscoveryRun,
)
from app.services.job_locks import with_job_lock

# Bumped 1 -> 2 when collector tags/groups tables were added, 2 -> 3 when
# grading_submissions was added, 3 -> 4 when users was added (and
# collector_tags/collector_groups/collection_items became user-scoped), 4 -> 5
# when wishlist_items was added, 5 -> 6 when dashboard_preferences was added,
# 6 -> 7 when collector_notes/collector_activity_events (missed when those
# tables were first added) and search_history were added, 7 -> 8 when
# analytics_digest_reports was added, 8 -> 9 when card_aliases was added
# (alongside cards.is_active/merged_into_card_id/merged_at/merge_notes -
# plain new columns on an existing required table, so no version bump was
# needed for those), 9 -> 10 when import_validation_reports was added, and
# 10 -> 11 when saved_views was added, and 11 -> 12 when the selective JSON
# backup adopted the complete exact-print pricing identity/provenance chain.
# The pre-v12 additions became required tables (import_validation_reports is
# the one exception, kept optional alongside app_log_events). The v12 market
# tables follow the explicit include flags in BACKUP_REGISTRY. An archive from
# an earlier version is never silently reinterpreted under this contract.
BACKUP_VERSION = 12
APP_NAME = "opcg-price-tracker"


@dataclass(frozen=True)
class BackupTableSpec:
    """One authoritative declaration of backup coverage and ordering.

    ``include_flag`` is a metadata/export option name. ``None`` means the
    table is required in every current-version archive. Tuple order is the
    FK-safe insert order; replace deletion uses its reverse.
    """

    name: str
    model: type
    include_flag: str | None = None


BACKUP_REGISTRY: tuple[BackupTableSpec, ...] = (
    BackupTableSpec("users", User),
    BackupTableSpec("cards", Card),
    BackupTableSpec("card_aliases", CardAlias),
    BackupTableSpec("canonical_cards", CanonicalCard),
    BackupTableSpec("release_products", ReleaseProduct),
    BackupTableSpec("sources", Source),
    BackupTableSpec("release_product_aliases", ReleaseProductAlias),
    BackupTableSpec("card_prints", CardPrint),
    BackupTableSpec("collector_tags", CollectorTag),
    BackupTableSpec("collector_groups", CollectorGroup),
    BackupTableSpec("alert_rules", AlertRule),
    BackupTableSpec("portfolio_valuation_snapshots", PortfolioValuationSnapshot),
    BackupTableSpec("price_refresh_runs", PriceRefreshRun, "include_refresh_runs"),
    BackupTableSpec("raw_snapshots", RawSnapshot, "include_raw_snapshots"),
    BackupTableSpec("snkrdunk_discovery_runs", SnkrdunkDiscoveryRun),
    BackupTableSpec("snkrdunk_candidates", SnkrdunkCandidate),
    BackupTableSpec("yuyutei_discovery_runs", YuyuteiDiscoveryRun),
    BackupTableSpec("yuyutei_candidates", YuyuteiCandidate),
    BackupTableSpec("source_card_mappings", SourceCardMapping),
    BackupTableSpec("collection_items", CollectionItem),
    BackupTableSpec("wishlist_items", WishlistItem),
    BackupTableSpec("card_tags", CardTag),
    BackupTableSpec("collection_item_tags", CollectionItemTag),
    BackupTableSpec("collection_item_groups", CollectionItemGroup),
    BackupTableSpec("grading_submissions", GradingSubmission),
    BackupTableSpec("price_observations", PriceObservation, "include_prices"),
    BackupTableSpec("source_collection_attempts", SourceCollectionAttempt, "include_prices"),
    BackupTableSpec("market_index_snapshots", MarketIndexSnapshot, "include_prices"),
    BackupTableSpec("card_pirate_index_points", CardPirateIndexPoint, "include_prices"),
    BackupTableSpec("market_intelligence_reports", MarketIntelligenceReport),
    BackupTableSpec("market_signal_events", MarketSignalEvent),
    BackupTableSpec("market_report_digest_sends", MarketReportDigestSend),
    BackupTableSpec("market_workflow_runs", MarketWorkflowRun),
    BackupTableSpec("analytics_digest_reports", AnalyticsDigestReport),
    BackupTableSpec("collector_notes", CollectorNote),
    BackupTableSpec("collector_activity_events", CollectorActivityEvent),
    BackupTableSpec("dashboard_preferences", DashboardPreference),
    BackupTableSpec("search_history", SearchHistory),
    BackupTableSpec("app_log_events", AppLogEvent, "include_logs"),
    BackupTableSpec(
        "import_validation_reports", ImportValidationReport, "include_validation_reports"
    ),
    BackupTableSpec("saved_views", SavedView),
)

MODEL_BY_TABLE: dict[str, type] = {spec.name: spec.model for spec in BACKUP_REGISTRY}
TABLE_INSERT_ORDER: tuple[str, ...] = tuple(spec.name for spec in BACKUP_REGISTRY)
REQUIRED_TABLES: tuple[str, ...] = tuple(
    spec.name for spec in BACKUP_REGISTRY if spec.include_flag is None
)
OPTIONAL_TABLES: tuple[str, ...] = tuple(
    spec.name for spec in BACKUP_REGISTRY if spec.include_flag is not None
)

RAW_PROVENANCE_INCLUDED = "included"
RAW_PROVENANCE_OMITTED = "intentionally_omitted"
BACKUP_METADATA_FLAGS: tuple[str, ...] = tuple(
    dict.fromkeys(
        flag
        for spec in BACKUP_REGISTRY
        if (flag := spec.include_flag) is not None
    )
)

# Optional tables whose existing rows can be deleted, nulled, or block a
# replace restore when required identity parents are replaced. app_log_events
# has only plain related_* integers, so omitting it carries no such FK risk.
CASCADE_RISK_OPTIONAL_TABLES: tuple[str, ...] = (
    "price_observations",
    "source_collection_attempts",
    "market_index_snapshots",
    "raw_snapshots",
    "price_refresh_runs",
)

RESTORE_MODES = ("merge", "replace")

RESTORE_CONFIRM_PHRASE = "RESTORE"


def backup_registry_errors() -> list[str]:
    """Return declaration/FK-order drift in the authoritative registry."""
    errors: list[str] = []
    names = [spec.name for spec in BACKUP_REGISTRY]
    if len(names) != len(set(names)):
        errors.append("backup registry contains duplicate table names")

    order = {name: index for index, name in enumerate(names)}
    for spec in BACKUP_REGISTRY:
        model_table = spec.model.__table__
        if model_table.name != spec.name:
            errors.append(
                f"registry name {spec.name!r} does not match model table {model_table.name!r}"
            )
        for foreign_key in model_table.foreign_keys:
            parent = foreign_key.column.table.name
            if parent == spec.name:
                continue  # Restore defers registered self-references separately.
            if parent not in order:
                errors.append(
                    f"{spec.name}.{foreign_key.parent.name} references unregistered table {parent}"
                )
            elif order[parent] >= order[spec.name]:
                errors.append(
                    f"{spec.name}.{foreign_key.parent.name} must follow parent table {parent}"
                )
    return errors


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        # Preserve NUMERIC precision while keeping the archive strict JSON.
        return str(value)
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
            elif py_type is Decimal:
                value = Decimal(value)
        converted[name] = value
    return converted


def export_backup(
    db: Session,
    *,
    include_prices: bool = False,
    include_raw_snapshots: bool = False,
    include_refresh_runs: bool = False,
    include_logs: bool = False,
    include_validation_reports: bool = False,
) -> dict[str, Any]:
    include_flags = {
        "include_prices": include_prices,
        "include_raw_snapshots": include_raw_snapshots,
        "include_refresh_runs": include_refresh_runs,
        "include_logs": include_logs,
        "include_validation_reports": include_validation_reports,
    }

    tables: dict[str, list[dict[str, Any]]] = {}
    omitted_raw_references = {
        "price_observation_references_nullified": 0,
        "source_collection_attempt_references_nullified": 0,
    }
    raw_reference_counters = {
        "price_observations": "price_observation_references_nullified",
        "source_collection_attempts": "source_collection_attempt_references_nullified",
    }
    for spec in BACKUP_REGISTRY:
        table = spec.name
        if spec.include_flag is not None and not include_flags[spec.include_flag]:
            continue
        rows = db.scalars(select(spec.model).order_by(spec.model.id)).all()
        serialized_rows = [_serialize_row(row) for row in rows]
        if not include_raw_snapshots and table in raw_reference_counters:
            counter = raw_reference_counters[table]
            for row in serialized_rows:
                if row.get("raw_snapshot_id") is not None:
                    omitted_raw_references[counter] += 1
                    row["raw_snapshot_id"] = None
        tables[table] = serialized_rows

    return {
        "metadata": {
            "app": APP_NAME,
            "backup_version": BACKUP_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "include_prices": include_prices,
            "include_raw_snapshots": include_raw_snapshots,
            "include_refresh_runs": include_refresh_runs,
            "include_logs": include_logs,
            "include_validation_reports": include_validation_reports,
            "raw_snapshot_provenance": {
                "mode": (
                    RAW_PROVENANCE_INCLUDED
                    if include_raw_snapshots
                    else RAW_PROVENANCE_OMITTED
                ),
                **omitted_raw_references,
            },
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
        return ValidationResult(
            valid=False,
            backup_version=None,
            errors=["Backup must be a JSON object"],
        )

    metadata = backup.get("metadata")
    backup_version: int | None = None
    include_flags: dict[str, bool] = {}
    if not isinstance(metadata, dict):
        errors.append("metadata is missing or not an object")
    else:
        if metadata.get("app") != APP_NAME:
            errors.append(f"metadata.app must be {APP_NAME!r}")
        backup_version = metadata.get("backup_version")
        if backup_version is None:
            errors.append("metadata.backup_version is missing")
        elif backup_version != BACKUP_VERSION:
            errors.append(
                f"Unsupported backup_version {backup_version!r}; expected {BACKUP_VERSION}"
            )
        if backup_version == BACKUP_VERSION:
            for flag in BACKUP_METADATA_FLAGS:
                value = metadata.get(flag)
                if not isinstance(value, bool):
                    errors.append(f"metadata.{flag} must be a boolean")
                else:
                    include_flags[flag] = value

            raw_provenance = metadata.get("raw_snapshot_provenance")
            if not isinstance(raw_provenance, dict):
                errors.append("metadata.raw_snapshot_provenance is missing or not an object")
            else:
                expected_mode = (
                    RAW_PROVENANCE_INCLUDED
                    if include_flags.get("include_raw_snapshots") is True
                    else RAW_PROVENANCE_OMITTED
                )
                if raw_provenance.get("mode") != expected_mode:
                    errors.append(
                        "metadata.raw_snapshot_provenance.mode does not match "
                        "metadata.include_raw_snapshots"
                    )
                for count_name in (
                    "price_observation_references_nullified",
                    "source_collection_attempt_references_nullified",
                ):
                    count = raw_provenance.get(count_name)
                    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                        errors.append(
                            f"metadata.raw_snapshot_provenance.{count_name} "
                            "must be a non-negative integer"
                        )
                    elif include_flags.get("include_raw_snapshots") is True and count != 0:
                        errors.append(
                            f"metadata.raw_snapshot_provenance.{count_name} must be 0 "
                            "when raw snapshots are included"
                        )
                    elif include_flags.get("include_prices") is False and count != 0:
                        errors.append(
                            f"metadata.raw_snapshot_provenance.{count_name} must be 0 "
                            "when price history is excluded"
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
            row_id = row.get("id")
            if "id" not in row or not isinstance(row_id, int) or isinstance(row_id, bool):
                errors.append(f"{table}[{i}] is missing an integer 'id'")
        integer_ids = [
            row_id
            for row in rows
            if isinstance(row, dict)
            and isinstance((row_id := row.get("id")), int)
            and not isinstance(row_id, bool)
        ]
        duplicate_ids = sorted(
            row_id
            for row_id, count in Counter(integer_ids).items()
            if isinstance(row_id, int) and count > 1
        )
        if duplicate_ids:
            errors.append(f"Table '{table}' contains duplicate id(s): {duplicate_ids}")
        summary[table] = len(rows)
        return rows

    if backup_version == BACKUP_VERSION:
        unknown_tables = sorted(set(tables) - set(TABLE_INSERT_ORDER))
        for table in unknown_tables:
            errors.append(f"Unknown table for backup_version {BACKUP_VERSION}: {table}")

        for spec in BACKUP_REGISTRY:
            expected = spec.include_flag is None or include_flags.get(spec.include_flag) is True
            if expected:
                _check_table(spec.name, required=True)
            elif spec.name in tables:
                errors.append(
                    f"Table '{spec.name}' is present while metadata.{spec.include_flag}=false"
                )
                _check_table(spec.name, required=False)
    else:
        # Old versions are rejected above and are never reinterpreted under
        # the current table contract. Inspect only known tables enough to
        # return useful shape errors without treating the archive as v12.
        for table in TABLE_INSERT_ORDER:
            if table in tables:
                _check_table(table, required=False)

    # FK cross-checks, only meaningful once the basic shape checks passed -
    # otherwise a malformed table (e.g. not a list) would make these crash
    # rather than produce a useful error.
    if not errors:
        card_ids = {row["id"] for row in tables.get("cards", [])}
        canonical_card_ids = {row["id"] for row in tables.get("canonical_cards", [])}
        release_product_ids = {row["id"] for row in tables.get("release_products", [])}
        card_print_ids = {row["id"] for row in tables.get("card_prints", [])}
        source_ids = {row["id"] for row in tables.get("sources", [])}
        raw_snapshot_ids = {row["id"] for row in tables.get("raw_snapshots", [])}
        snkrdunk_run_ids = {row["id"] for row in tables.get("snkrdunk_discovery_runs", [])}
        snkrdunk_candidate_ids = {row["id"] for row in tables.get("snkrdunk_candidates", [])}
        yuyutei_run_ids = {row["id"] for row in tables.get("yuyutei_discovery_runs", [])}

        for i, row in enumerate(tables.get("release_product_aliases", [])):
            if row.get("product_id") not in release_product_ids:
                errors.append(
                    f"release_product_aliases[{i}] references missing product_id "
                    f"{row.get('product_id')!r}"
                )

        for i, row in enumerate(tables.get("card_prints", [])):
            if row.get("canonical_card_id") not in canonical_card_ids:
                errors.append(
                    f"card_prints[{i}] references missing canonical_card_id "
                    f"{row.get('canonical_card_id')!r}"
                )
            product_id = row.get("release_product_id")
            if product_id is not None and product_id not in release_product_ids:
                errors.append(
                    f"card_prints[{i}] references missing release_product_id {product_id!r}"
                )
            if row.get("verification_status") == "verified" and product_id is None:
                errors.append(
                    f"card_prints[{i}] is verified but has no release_product_id"
                )

        for i, row in enumerate(tables.get("raw_snapshots", [])):
            if row.get("source_id") not in source_ids:
                errors.append(
                    f"raw_snapshots[{i}] references missing source_id {row.get('source_id')!r}"
                )

        for i, row in enumerate(tables.get("snkrdunk_candidates", [])):
            run_id = row.get("discovery_run_id")
            if run_id is not None and run_id not in snkrdunk_run_ids:
                errors.append(
                    f"snkrdunk_candidates[{i}] references missing discovery_run_id {run_id!r}"
                )
            for field_name in ("matched_card_id", "best_match_card_id"):
                card_id = row.get(field_name)
                if card_id is not None and card_id not in card_ids:
                    errors.append(
                        f"snkrdunk_candidates[{i}] references missing {field_name} {card_id!r}"
                    )

        for i, row in enumerate(tables.get("yuyutei_candidates", [])):
            run_id = row.get("discovery_run_id")
            if run_id is not None and run_id not in yuyutei_run_ids:
                errors.append(
                    f"yuyutei_candidates[{i}] references missing discovery_run_id {run_id!r}"
                )
            print_id = row.get("matched_card_print_id")
            if print_id is not None and print_id not in card_print_ids:
                errors.append(
                    f"yuyutei_candidates[{i}] references missing matched_card_print_id "
                    f"{print_id!r}"
                )

        for i, row in enumerate(tables.get("collection_items", [])):
            if row.get("card_id") not in card_ids:
                errors.append(
                    f"collection_items[{i}] references missing card_id {row.get('card_id')!r}"
                )

        mappings_by_id: dict[int, dict[str, Any]] = {}
        exact_mapping_count = 0
        legacy_mapping_count = 0
        for i, row in enumerate(tables.get("source_card_mappings", [])):
            mappings_by_id[row["id"]] = row
            if row.get("source_id") not in source_ids:
                errors.append(
                    f"source_card_mappings[{i}] references missing source_id "
                    f"{row.get('source_id')!r}"
                )
            card_id = row.get("card_id")
            print_id = row.get("card_print_id")
            if print_id is not None:
                exact_mapping_count += 1
                if print_id not in card_print_ids:
                    errors.append(
                        f"source_card_mappings[{i}] references missing card_print_id {print_id!r}"
                    )
                if card_id is not None and card_id not in card_ids:
                    errors.append(
                        f"source_card_mappings[{i}] references missing compatibility card_id "
                        f"{card_id!r}"
                    )
            else:
                legacy_mapping_count += 1
                if card_id is None:
                    errors.append(
                        f"source_card_mappings[{i}] has neither exact card_print_id nor "
                        "legacy compatibility card_id"
                    )
                elif card_id not in card_ids:
                    errors.append(
                        f"source_card_mappings[{i}] references missing legacy card_id {card_id!r}"
                    )

        summary["source_card_mappings_exact"] = exact_mapping_count
        summary["source_card_mappings_legacy_compatibility"] = legacy_mapping_count
        if legacy_mapping_count:
            warnings.append(
                f"source_card_mappings contains {legacy_mapping_count} legacy compatibility "
                "record(s) with card_print_id=null; these are restorable but are not modern "
                "exact-pricing lineage"
            )

        observations_by_id: dict[int, dict[str, Any]] = {}
        for i, row in enumerate(tables.get("price_observations", [])):
            observations_by_id[row["id"]] = row
            source_id = row.get("source_id")
            if source_id not in source_ids:
                errors.append(
                    f"price_observations[{i}] references missing source_id {source_id!r}"
                )
            card_id = row.get("card_id")
            if card_id is not None and card_id not in card_ids:
                errors.append(
                    f"price_observations[{i}] references missing compatibility card_id {card_id!r}"
                )
            mapping_id = row.get("source_card_mapping_id")
            print_id = row.get("card_print_id")
            if (mapping_id is None) != (print_id is None):
                errors.append(
                    f"price_observations[{i}] must pair source_card_mapping_id and card_print_id"
                )
            elif mapping_id is not None:
                mapping = mappings_by_id.get(mapping_id)
                if mapping is None:
                    errors.append(
                        f"price_observations[{i}] references missing source_card_mapping_id "
                        f"{mapping_id!r}"
                    )
                else:
                    if mapping.get("card_print_id") != print_id:
                        errors.append(
                            f"price_observations[{i}] card_print_id {print_id!r} does not "
                            f"match source_card_mapping_id {mapping_id!r}"
                        )
                    if mapping.get("source_id") != source_id:
                        errors.append(
                            f"price_observations[{i}] source_id {source_id!r} does not "
                            f"match source_card_mapping_id {mapping_id!r}"
                        )
                if print_id not in card_print_ids:
                    errors.append(
                        f"price_observations[{i}] references missing card_print_id {print_id!r}"
                    )

            candidate_id = row.get("candidate_id")
            if candidate_id is not None and candidate_id not in snkrdunk_candidate_ids:
                errors.append(
                    f"price_observations[{i}] references missing candidate_id {candidate_id!r}"
                )
            snapshot_id = row.get("raw_snapshot_id")
            if snapshot_id is not None and snapshot_id not in raw_snapshot_ids:
                errors.append(
                    f"price_observations[{i}] references missing raw_snapshot_id {snapshot_id!r}"
                )

        for i, row in enumerate(tables.get("source_collection_attempts", [])):
            observation_id = row.get("price_observation_id")
            if observation_id is not None and observation_id not in observations_by_id:
                errors.append(
                    f"source_collection_attempts[{i}] references missing price_observation_id "
                    f"{observation_id!r}"
                )
            snapshot_id = row.get("raw_snapshot_id")
            if snapshot_id is not None and snapshot_id not in raw_snapshot_ids:
                errors.append(
                    f"source_collection_attempts[{i}] references missing raw_snapshot_id "
                    f"{snapshot_id!r}"
                )

        for i, row in enumerate(tables.get("market_index_snapshots", [])):
            print_id = row.get("card_print_id")
            if print_id not in card_print_ids:
                errors.append(
                    f"market_index_snapshots[{i}] references missing card_print_id {print_id!r}"
                )

        card_pirate_points = {
            row["id"]: row for row in tables.get("card_pirate_index_points", [])
        }
        for i, row in enumerate(tables.get("card_pirate_index_points", [])):
            carried_from_id = row.get("carried_from_point_id")
            if carried_from_id is None:
                continue
            carried_from = card_pirate_points.get(carried_from_id)
            if carried_from is None:
                errors.append(
                    f"card_pirate_index_points[{i}] references missing "
                    f"carried_from_point_id {carried_from_id!r}"
                )
                continue
            for field_name in ("scope_kind", "scope_key", "index_value"):
                if row.get(field_name) != carried_from.get(field_name):
                    errors.append(
                        f"card_pirate_index_points[{i}] {field_name} does not match "
                        f"carried_from_point_id {carried_from_id!r}"
                    )

        for i, row in enumerate(tables.get("market_signal_events", [])):
            card_id = row.get("card_id")
            if card_id is not None and card_id not in card_ids:
                errors.append(
                    f"market_signal_events[{i}] references missing card_id {card_id!r}"
                )

        for i, row in enumerate(tables.get("card_aliases", [])):
            if row.get("card_id") not in card_ids:
                errors.append(
                    f"card_aliases[{i}] references missing card_id {row.get('card_id')!r}"
                )

        for i, row in enumerate(tables.get("cards", [])):
            merged_into_card_id = row.get("merged_into_card_id")
            if merged_into_card_id is not None and merged_into_card_id not in card_ids:
                errors.append(
                    f"cards[{i}] references missing merged_into_card_id {merged_into_card_id!r}"
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


# Self-references can point to a higher id that is inserted later in the same
# id-ascending batch. Writing those values immediately would violate the FK.
# Null them for insert/update and apply them after every row in the table
# exists. Card Pirate's composite carry FK uses MATCH SIMPLE, so nulling its
# carried_from_point_id safely defers that complete relationship as well.
_SELF_REFERENTIAL_FK_COLUMN: dict[str, str] = {
    "cards": "merged_into_card_id",
    "card_pirate_index_points": "carried_from_point_id",
}


def _defer_self_referential_fk(
    table: str, kwargs: dict[str, Any], deferred: list[tuple[int, Any]]
) -> None:
    column = _SELF_REFERENTIAL_FK_COLUMN.get(table)
    if column and kwargs.get(column) is not None:
        deferred.append((kwargs["id"], kwargs[column]))
        kwargs[column] = None


def _apply_deferred_self_refs(db: Session, table: str, deferred: list[tuple[int, Any]]) -> None:
    if not deferred:
        return
    model = MODEL_BY_TABLE[table]
    column = _SELF_REFERENTIAL_FK_COLUMN[table]
    for row_id, value in deferred:
        setattr(db.get(model, row_id), column, value)
    db.flush()


def _upsert_rows(db: Session, table: str, rows: list[dict[str, Any]]) -> tuple[int, int]:
    model = MODEL_BY_TABLE[table]
    created = updated = 0
    deferred: list[tuple[int, Any]] = []
    for row in rows:
        kwargs = _deserialize_row(model, row)
        _defer_self_referential_fk(table, kwargs, deferred)
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
    _apply_deferred_self_refs(db, table, deferred)
    return created, updated


def _insert_rows(db: Session, table: str, rows: list[dict[str, Any]]) -> int:
    model = MODEL_BY_TABLE[table]
    deferred: list[tuple[int, Any]] = []
    for row in rows:
        kwargs = _deserialize_row(model, row)
        _defer_self_referential_fk(table, kwargs, deferred)
        db.add(model(**kwargs))
    db.flush()
    _apply_deferred_self_refs(db, table, deferred)
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
                "mode=replace deletes and recreates identity/provenance parents; existing "
                f"rows in {excluded_optional} (not included in this backup) that reference "
                "those parents may be cascade-deleted, have SET NULL references cleared, "
                "or block the restore through RESTRICT constraints because those tables are "
                "not being restored alongside them."
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

    summary: dict[str, dict[str, int]] = {
        "created": {},
        "updated": {},
        "deleted": {},
        "skipped": {},
    }
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
