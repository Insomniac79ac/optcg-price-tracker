"""Read-only audit of whether the indexes this app relies on for its
highest-traffic queries (latest-price lookups, market signal/opportunity
filtering, admin log/activity search, ...) actually exist in the connected
database - see GET /admin/db-index-audit. Inspects the live schema via
SQLAlchemy's Inspector (works against both the Postgres this app runs in
production and the SQLite used in tests) rather than trusting that every
migration has been applied - a missing index here means a query that should
hit an index is about to full-table-scan instead, which gets more expensive
as price_observations/raw_snapshots/market_signal_events/
collector_activity_events/app_log_events grow.

A check passes if *some* index or unique constraint on the table has the
required columns as its leading (leftmost) columns, in order. This is only an
ordinary query-access check: it does not prove uniqueness, partial-index
predicates, foreign-key semantics, or identity constraints. The `index` field
on each result is still a specific, meaningful name so a failing check tells
you which access path is missing.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

STATUSES = ("pass", "warning", "critical")
SEVERITIES = ("warning", "critical")

# (table, index_name, required leading columns, severity). severity="critical"
# marks the indexes backing the latest-price window-function queries in
# app.services.latest_prices and the other highest-traffic lookups; anything
# else is "warning" - still worth having as these tables grow, but not an
# immediate query-plan emergency.
REQUIRED_INDEXES: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("cards", "ix_cards_card_code", ("card_code",), "warning"),
    ("cards", "ix_cards_set_code", ("set_code",), "warning"),
    ("cards", "ix_cards_rarity", ("rarity",), "warning"),
    ("cards", "ix_cards_language", ("language",), "warning"),
    ("sources", "ix_sources_name", ("name",), "warning"),
    ("source_card_mappings", "ix_source_card_mappings_card_id", ("card_id",), "warning"),
    (
        "source_card_mappings",
        "ix_source_card_mappings_card_id_source_id",
        ("card_id", "source_id"),
        "warning",
    ),
    (
        "source_card_mappings",
        "ix_source_card_mappings_card_print_id",
        ("card_print_id",),
        "critical",
    ),
    ("source_card_mappings", "ix_source_card_mappings_source_id", ("source_id",), "warning"),
    ("source_card_mappings", "ix_source_card_mappings_source_url", ("source_url",), "warning"),
    ("source_card_mappings", "ix_source_card_mappings_is_active", ("is_active",), "warning"),
    (
        "source_card_mappings",
        "ix_source_card_mappings_review_status",
        ("review_status",),
        "warning",
    ),
    (
        "source_card_mappings",
        "ix_source_card_mappings_collection_order",
        ("last_collection_attempted_at", "id"),
        "warning",
    ),
    ("price_observations", "ix_price_observations_card_id", ("card_id",), "critical"),
    (
        "price_observations",
        "ix_price_observations_source_card_mapping_id",
        ("source_card_mapping_id",),
        "critical",
    ),
    (
        "price_observations",
        "ix_price_observations_card_print_id",
        ("card_print_id",),
        "critical",
    ),
    ("price_observations", "ix_price_observations_source_id", ("source_id",), "critical"),
    ("price_observations", "ix_price_observations_price_type", ("price_type",), "warning"),
    ("price_observations", "ix_price_observations_observed_at", ("observed_at",), "critical"),
    (
        "price_observations",
        "ix_price_observations_card_source_type_observed",
        ("card_id", "source_id", "price_type", "observed_at"),
        "critical",
    ),
    # The exact-print counterpart of the entry above (migration
    # d7e2b9f4a1c3). Critical for the same reason: it backs the print-scoped
    # price reads in app.services.print_pricing/print_market_index, which are
    # what every public /prints surface actually queries - see
    # docs/print_centric_pricing.md.
    (
        "price_observations",
        "ix_price_observations_print_source_type_observed",
        ("card_print_id", "source_id", "price_type", "observed_at"),
        "critical",
    ),
    # 1B-8F1 found no production mapping/time index was warranted. The plain
    # and price-type variants remain deferred; a covering variant is a future
    # scale candidate only and is intentionally absent from this registry.
    (
        "price_observations",
        "ix_price_observations_source_observed",
        ("source_id", "observed_at"),
        "warning",
    ),
    ("raw_snapshots", "ix_raw_snapshots_source_id", ("source_id",), "warning"),
    ("raw_snapshots", "ix_raw_snapshots_fetched_at", ("fetched_at",), "warning"),
    ("raw_snapshots", "ix_raw_snapshots_source_url", ("source_url",), "warning"),
    ("collection_items", "ix_collection_items_card_id", ("card_id",), "warning"),
    ("collection_items", "ix_collection_items_status", ("status",), "warning"),
    ("collection_items", "ix_collection_items_created_at", ("created_at",), "warning"),
    ("wishlist_items", "ix_wishlist_items_card_id", ("card_id",), "warning"),
    ("wishlist_items", "ix_wishlist_items_status", ("status",), "warning"),
    ("wishlist_items", "ix_wishlist_items_priority", ("priority",), "warning"),
    (
        "wishlist_items",
        "ix_wishlist_items_target_buy_price_jpy",
        ("target_buy_price_jpy",),
        "warning",
    ),
    (
        "grading_submissions",
        "ix_grading_submissions_collection_item_id",
        ("collection_item_id",),
        "warning",
    ),
    (
        "grading_submissions",
        "ix_grading_submissions_submission_status",
        ("submission_status",),
        "warning",
    ),
    (
        "grading_submissions",
        "ix_grading_submissions_grading_company",
        ("grading_company",),
        "warning",
    ),
    ("market_signal_events", "ix_market_signal_events_signal_type", ("signal_type",), "warning"),
    ("market_signal_events", "ix_market_signal_events_status", ("status",), "warning"),
    ("market_signal_events", "ix_market_signal_events_card_id", ("card_id",), "warning"),
    (
        "market_signal_events",
        "ix_market_signal_events_suggested_action",
        ("suggested_action",),
        "warning",
    ),
    (
        "market_signal_events",
        "ix_market_signal_events_last_seen_at",
        ("last_seen_at",),
        "warning",
    ),
    (
        "market_intelligence_reports",
        "ix_market_intelligence_reports_report_date",
        ("report_date",),
        "warning",
    ),
    (
        "market_intelligence_reports",
        "ix_market_intelligence_reports_created_at",
        ("created_at",),
        "warning",
    ),
    (
        "portfolio_valuation_snapshots",
        "ix_portfolio_valuation_snapshots_created_at",
        ("created_at",),
        "warning",
    ),
    ("collector_notes", "ix_collector_notes_note_type", ("note_type",), "warning"),
    ("collector_notes", "ix_collector_notes_card_id", ("card_id",), "warning"),
    (
        "collector_notes",
        "ix_collector_notes_collection_item_id",
        ("collection_item_id",),
        "warning",
    ),
    ("collector_notes", "ix_collector_notes_pinned", ("pinned",), "warning"),
    ("collector_notes", "ix_collector_notes_created_at", ("created_at",), "warning"),
    (
        "collector_activity_events",
        "ix_collector_activity_events_event_source",
        ("event_source",),
        "warning",
    ),
    (
        "collector_activity_events",
        "ix_collector_activity_events_event_type",
        ("event_type",),
        "warning",
    ),
    ("collector_activity_events", "ix_collector_activity_events_card_id", ("card_id",), "warning"),
    (
        "collector_activity_events",
        "ix_collector_activity_events_created_at",
        ("created_at",),
        "warning",
    ),
    ("app_log_events", "ix_app_log_events_level", ("level",), "warning"),
    ("app_log_events", "ix_app_log_events_service", ("service",), "warning"),
    ("app_log_events", "ix_app_log_events_event_type", ("event_type",), "warning"),
    ("app_log_events", "ix_app_log_events_created_at", ("created_at",), "warning"),
    ("search_history", "ix_search_history_query", ("query",), "warning"),
    ("search_history", "ix_search_history_created_at", ("created_at",), "warning"),
    ("market_workflow_runs", "ix_market_workflow_runs_status", ("status",), "warning"),
    ("market_workflow_runs", "ix_market_workflow_runs_started_at", ("started_at",), "warning"),
    ("card_prints", "ix_card_prints_canonical_card_id", ("canonical_card_id",), "warning"),
    ("card_prints", "ix_card_prints_release_product_id", ("release_product_id",), "warning"),
    ("card_prints", "ix_card_prints_is_active", ("is_active",), "warning"),
    (
        "market_index_snapshots",
        "uq_market_index_snapshots_print_date",
        ("card_print_id", "snapshot_date"),
        "critical",
    ),
    (
        "market_index_snapshots",
        "ix_market_index_snapshots_print_calculated",
        ("card_print_id", "calculated_at"),
        "critical",
    ),
    (
        "market_index_snapshots",
        "ix_market_index_snapshots_snapshot_date",
        ("snapshot_date",),
        "critical",
    ),
    (
        "card_pirate_index_points",
        "uq_cpi_points_point",
        ("scope_kind", "scope_key", "methodology_version", "point_date"),
        "critical",
    ),
)


INDEX_SCOPE_BY_KEY: dict[tuple[str, str], str] = {
    # Compatibility readers intentionally retain card-level pricing access.
    ("source_card_mappings", "ix_source_card_mappings_card_id"): "legacy_compatibility",
    (
        "source_card_mappings",
        "ix_source_card_mappings_card_id_source_id",
    ): "legacy_compatibility",
    ("price_observations", "ix_price_observations_card_id"): "legacy_compatibility",
    (
        "price_observations",
        "ix_price_observations_card_source_type_observed",
    ): "legacy_compatibility",
    # Exact-print pricing, health, coverage, reporting, and collection access.
    ("source_card_mappings", "ix_source_card_mappings_card_print_id"): "exact_print",
    (
        "source_card_mappings",
        "ix_source_card_mappings_collection_order",
    ): "exact_print",
    (
        "price_observations",
        "ix_price_observations_source_card_mapping_id",
    ): "exact_print",
    ("price_observations", "ix_price_observations_card_print_id"): "exact_print",
    (
        "price_observations",
        "ix_price_observations_print_source_type_observed",
    ): "exact_print",
    ("card_prints", "ix_card_prints_canonical_card_id"): "exact_print",
    ("card_prints", "ix_card_prints_release_product_id"): "exact_print",
    ("card_prints", "ix_card_prints_is_active"): "exact_print",
    # Per-print Market Index storage and lookup access.
    (
        "market_index_snapshots",
        "uq_market_index_snapshots_print_date",
    ): "market_index",
    (
        "market_index_snapshots",
        "ix_market_index_snapshots_print_calculated",
    ): "market_index",
    (
        "market_index_snapshots",
        "ix_market_index_snapshots_snapshot_date",
    ): "market_index",
    # Card Pirate natural-point access path.
    ("card_pirate_index_points", "uq_cpi_points_point"): "card_pirate",
}


# These identity/integrity contracts cannot be proven by the leading-column
# access-path audit. They are intentionally documented for a separate, narrow,
# constraint-aware tranche instead of being registered as ordinary indexes.
CONSTRAINT_AWARE_FOLLOW_UP: tuple[tuple[str, str, str], ...] = (
    (
        "card_prints",
        "uq_card_prints_active_verified_identity",
        "partial unique active/verified CardPrint identity",
    ),
    (
        "source_card_mappings",
        "uq_source_card_mappings_print_lineage_identity",
        "exact-print lineage composite uniqueness",
    ),
    (
        "price_observations",
        "fk_price_observations_mapping_print_source",
        "exact-lineage composite foreign-key target",
    ),
    (
        "card_pirate_index_points",
        "uq_cpi_points_carry_target",
        "Card Pirate carry-chain target uniqueness",
    ),
    (
        "card_pirate_index_points",
        "fk_cpi_points_carried_from",
        "Card Pirate carry-chain referential integrity",
    ),
)


@dataclass
class IndexCheckResult:
    table: str
    index: str
    status: str
    severity: str
    scope: str
    message: str


def _covers(index_columns: list[str], required_columns: tuple[str, ...]) -> bool:
    """Return whether columns provide an ordinary leading-column access path.

    A B-tree index on ``(a, b, c)`` can serve a lookup on ``a`` or ``(a, b)``,
    but not on ``b`` alone. This deliberately says nothing about uniqueness,
    partial predicates, foreign keys, or identity constraints.
    """
    if len(index_columns) < len(required_columns):
        return False
    actual_prefix = tuple(c.lower() for c in index_columns[: len(required_columns)])
    return actual_prefix == tuple(c.lower() for c in required_columns)


def _table_column_sets(inspector, table: str) -> list[list[str]] | None:
    """All indexed/unique column-orderings available on `table` - from both
    regular indexes and unique constraints (a `unique=True` column, or a
    UniqueConstraint, is itself backed by an index the query planner can
    use). Returns None if the table's metadata couldn't be read at all."""
    try:
        column_sets = [ix["column_names"] for ix in inspector.get_indexes(table)]
        column_sets += [uc["column_names"] for uc in inspector.get_unique_constraints(table)]
    except SQLAlchemyError:
        return None
    return [cols for cols in column_sets if cols and all(c is not None for c in cols)]


def run_db_index_audit(db: Session) -> list[IndexCheckResult]:
    inspector = inspect(db.get_bind())
    column_sets_by_table: dict[str, list[list[str]] | None] = {}

    results: list[IndexCheckResult] = []
    for table, index_name, required_columns, severity in REQUIRED_INDEXES:
        scope = INDEX_SCOPE_BY_KEY.get((table, index_name), "shared")
        if table not in column_sets_by_table:
            column_sets_by_table[table] = _table_column_sets(inspector, table)
        column_sets = column_sets_by_table[table]

        if column_sets is None:
            results.append(
                IndexCheckResult(
                    table=table,
                    index=index_name,
                    status=severity,
                    severity=severity,
                    scope=scope,
                    message=f"Could not read index metadata for table '{table}'.",
                )
            )
            continue

        if any(_covers(cols, required_columns) for cols in column_sets):
            results.append(
                IndexCheckResult(
                    table=table,
                    index=index_name,
                    status="pass",
                    severity=severity,
                    scope=scope,
                    message="Index exists.",
                )
            )
        else:
            results.append(
                IndexCheckResult(
                    table=table,
                    index=index_name,
                    status=severity,
                    severity=severity,
                    scope=scope,
                    message=(
                        f"Missing index on {table}({', '.join(required_columns)}) - "
                        f"expected an index named '{index_name}' (or any index/unique "
                        f"constraint with these columns as its leading columns)."
                    ),
                )
            )

    return results


def audit_summary(checks: list[IndexCheckResult]) -> dict[str, int]:
    return {
        "total_checks": len(checks),
        "passed": sum(1 for c in checks if c.status == "pass"),
        "warnings": sum(1 for c in checks if c.status == "warning"),
        "critical": sum(1 for c in checks if c.status == "critical"),
    }
