"""Verifies the default alert_rules seeded by the
b7d3e1f9a2c4_add_portfolio_alert_rule_types migration, without needing a
live Postgres connection - `upgrade()`'s op.* calls are patched to record
what they were called with instead of executing DDL/DML."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "b7d3e1f9a2c4_add_portfolio_alert_rule_types.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "portfolio_alert_rule_types_migration", MIGRATION_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seeded_rules_by_type() -> dict[str, dict]:
    module = _load_migration()
    captured: dict[str, list] = {}

    def fake_bulk_insert(table, rows):
        captured["rows"] = rows

    with (
        patch("alembic.op.drop_constraint"),
        patch("alembic.op.create_check_constraint"),
        patch("alembic.op.bulk_insert", side_effect=fake_bulk_insert),
    ):
        module.upgrade()

    return {row["rule_type"]: row for row in captured["rows"]}


def test_default_owned_card_above_target_sell_rule_exists():
    rules = _seeded_rules_by_type()

    rule = rules["owned_card_above_target_sell"]
    assert rule["is_active"] is True
    assert rule["threshold_pct"] is None


def test_default_owned_card_below_cost_basis_rule_exists_inactive():
    rules = _seeded_rules_by_type()

    rule = rules["owned_card_below_cost_basis"]
    assert rule["is_active"] is False
    assert rule["threshold_pct"] == 15.0


def test_default_portfolio_value_change_pct_rule_exists_inactive():
    rules = _seeded_rules_by_type()

    rule = rules["portfolio_value_change_pct"]
    assert rule["is_active"] is False
    assert rule["threshold_pct"] == 10.0
