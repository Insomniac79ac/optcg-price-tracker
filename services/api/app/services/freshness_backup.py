"""Selective backup compatibility for dormant scheduling state."""

from copy import deepcopy
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer

from app.models import (
    FreshnessAttempt,
    FreshnessPriceState,
    FreshnessWork,
    SourceDispatchBudget,
)

MODELS = (SourceDispatchBudget, FreshnessWork, FreshnessPriceState, FreshnessAttempt)
TABLES = tuple(model.__tablename__ for model in MODELS)


def omit_unexported_references(
    tables: dict, *, include_prices: bool, include_raw_snapshots: bool
) -> dict:
    counts = {"observation_references_nullified": 0, "raw_references_nullified": 0}
    if not include_prices:
        for row in tables.get("freshness_price_states", []):
            if row.get("last_observation_id") is not None:
                row["last_observation_id"] = None
                counts["observation_references_nullified"] += 1
    if not include_raw_snapshots:
        for row in tables.get("freshness_attempts", []):
            if row.get("raw_snapshot_id") is not None:
                row["raw_snapshot_id"] = None
                counts["raw_references_nullified"] += 1
    return counts


def validate_references(tables: dict) -> list[str]:
    errors = []
    for model in MODELS:
        for row in tables.get(model.__tablename__, []):
            for column in model.__table__.columns:
                value = row.get(column.name)
                invalid = value is None and not column.nullable
                if value is not None:
                    if isinstance(column.type, Boolean):
                        invalid = type(value) is not bool
                    elif isinstance(column.type, Integer):
                        invalid = type(value) is not int
                    elif isinstance(column.type, DateTime):
                        try:
                            parsed = datetime.fromisoformat(value)
                            invalid = (
                                parsed.tzinfo is None
                                or parsed.utcoffset().total_seconds() != 0
                            )
                        except (TypeError, ValueError):
                            invalid = True
                if invalid:
                    errors.append(
                        f"{model.__tablename__}[id={row['id']}] has invalid {column.name}"
                    )
            if model is FreshnessAttempt:
                outcomes = row.get("category_outcomes")
                if outcomes is not None and (
                    not isinstance(outcomes, dict)
                    or any(
                        not isinstance(key, str)
                        or not key
                        or len(key) > 32
                        or not isinstance(value, str)
                        or value
                        not in {"captured", "no_listing", "absent", "parsing_failure"}
                        for key, value in outcomes.items()
                    )
                ):
                    errors.append(
                        f"freshness_attempts[id={row['id']}] has invalid category_outcomes"
                    )
                costs = row.get("request_costs")
                if not isinstance(costs, list) or any(
                    type(cost) is not int or cost <= 0 for cost in costs
                ):
                    errors.append(
                        f"freshness_attempts[id={row['id']}] has invalid request_costs"
                    )
    if errors:
        return errors
    for model in MODELS:
        table = model.__table__
        for constraint in table.foreign_key_constraints:
            parent = constraint.referred_table.name
            parent_fields = [element.column.name for element in constraint.elements]
            child_fields = [element.parent.name for element in constraint.elements]
            parent_keys = {
                tuple(row.get(field) for field in parent_fields)
                for row in tables.get(parent, [])
            }
            for row in tables.get(table.name, []):
                values = tuple(row.get(field) for field in child_fields)
                if (
                    all(value is not None for value in values)
                    and values not in parent_keys
                ):
                    errors.append(
                        f"{table.name}[id={row['id']}] has missing or inconsistent {parent} lineage"
                    )
    return errors


def prepare_restore(tables: dict, now: datetime) -> tuple[dict, list[str]]:
    """Restoring an archive must not resurrect dispatch permissions or owners.

    Preserve cursors and deadlines. Charge outstanding reservations
    conservatively and fence every restored active token. Re-enabling source
    admission is a separate, explicit operator action after reconciliation.
    """
    if not any(tables.get(name) for name in TABLES):
        return tables, []
    restored = dict(tables)
    for name in TABLES:
        if name in tables:
            restored[name] = deepcopy(tables[name])
    for row in restored.get("source_dispatch_budgets", []):
        row["enabled"] = False
        row["used_requests"] += row["reserved_requests"]
        row["reserved_requests"] = 0
    for row in restored.get("freshness_work", []):
        if row["state"] == "claimed":
            row["state"] = "pending"
            for field in (
                "claim_token",
                "claimed_by",
                "claimed_at",
                "claim_expires_at",
            ):
                row[field] = None
            row["last_outcome"] = "expired"
            row["last_failure"] = "claim invalidated by backup restore"
            row["last_failure_at"] = now.isoformat()
    for row in restored.get("freshness_attempts", []):
        if row.get("outcome") is None:
            row["outcome"] = "expired"
            row["finished_at"] = now.isoformat()
            row["actual_request_cost"] = None
            row["charged_request_cost"] = row["reserved_request_cost"]
            row["result_digest"] = None
    return restored, [
        "Restored freshness budgets are disabled and active claim tokens are invalidated; review limits, pauses and cursors before explicitly enabling admission."
    ]
