"""Verifies the a4d6b1c8f3e2_add_canonical_cards_and_card_prints migration
defines the expected columns/constraints, without needing a live Postgres
connection - same technique as test_alert_rules_migration.py: `upgrade()`'s
op.* calls are patched to record what they were called with instead of
executing DDL."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "a4d6b1c8f3e2_add_canonical_cards_and_card_prints.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("canonical_cards_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade():
    module = _load_migration()
    captured = {"create_table": [], "create_index": []}

    def fake_create_table(name, *columns, **kwargs):
        captured["create_table"].append({"name": name, "columns": columns, "kwargs": kwargs})

    def fake_create_index(name, table_name, columns, **kwargs):
        captured["create_index"].append(
            {"name": name, "table_name": table_name, "columns": columns, "kwargs": kwargs}
        )

    with (
        patch("alembic.op.create_table", side_effect=fake_create_table),
        patch("alembic.op.create_index", side_effect=fake_create_index),
    ):
        module.upgrade()

    return captured


def _table(captured, name):
    return next(t for t in captured["create_table"] if t["name"] == name)


def _column_names(table):
    return [c.name for c in table["columns"] if hasattr(c, "name")]


def test_canonical_cards_table_has_required_columns():
    captured = _run_upgrade()
    table = _table(captured, "canonical_cards")

    expected = {
        "id",
        "card_code",
        "name_en",
        "name_jp",
        "original_set_code",
        "rarity",
        "card_type",
        "colors",
        "cost",
        "power",
        "counter",
        "attribute",
        "effect_text",
        "trigger_text",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(set(_column_names(table)))


def test_canonical_cards_card_code_is_unique_and_not_null():
    captured = _run_upgrade()
    table = _table(captured, "canonical_cards")

    card_code = next(c for c in table["columns"] if getattr(c, "name", None) == "card_code")
    assert card_code.nullable is False

    unique_constraints = [
        c for c in table["columns"] if type(c).__name__ == "UniqueConstraint"
    ]
    assert any("card_code" in uc._pending_colargs for uc in unique_constraints)


def test_card_prints_table_has_required_columns():
    captured = _run_upgrade()
    table = _table(captured, "card_prints")

    expected = {
        "id",
        "canonical_card_id",
        "language",
        "treatment",
        "release_product_code",
        "artwork_key",
        "image_url",
        "artist",
        "verification_status",
        "is_active",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(set(_column_names(table)))


def test_card_prints_treatment_and_canonical_card_id_not_nullable():
    captured = _run_upgrade()
    table = _table(captured, "card_prints")

    columns_by_name = {c.name: c for c in table["columns"] if hasattr(c, "name")}
    assert columns_by_name["treatment"].nullable is False
    assert columns_by_name["canonical_card_id"].nullable is False
    assert columns_by_name["release_product_code"].nullable is True
    assert columns_by_name["artwork_key"].nullable is True


def test_canonical_cards_identity_fields_not_nullable():
    captured = _run_upgrade()
    table = _table(captured, "canonical_cards")

    columns_by_name = {c.name: c for c in table["columns"] if hasattr(c, "name")}
    assert columns_by_name["original_set_code"].nullable is False
    assert columns_by_name["rarity"].nullable is False
    assert columns_by_name["card_type"].nullable is False
    assert columns_by_name["name_en"].nullable is True
    assert columns_by_name["name_jp"].nullable is True
    assert columns_by_name["colors"].nullable is True


def test_canonical_cards_has_identity_check_constraints():
    captured = _run_upgrade()
    table = _table(captured, "canonical_cards")

    check_constraints = {
        c.name: str(c.sqltext)
        for c in table["columns"]
        if type(c).__name__ == "CheckConstraint"
    }
    assert "trim(original_set_code" in check_constraints["ck_canonical_cards_original_set_code_not_blank"]
    assert "trim(rarity" in check_constraints["ck_canonical_cards_rarity_not_blank"]
    assert "trim(card_type" in check_constraints["ck_canonical_cards_card_type_not_blank"]
    name_condition = check_constraints["ck_canonical_cards_requires_a_name"]
    assert "name_en" in name_condition
    assert "name_jp" in name_condition


def test_canonical_cards_card_code_has_no_redundant_index():
    captured = _run_upgrade()
    index_names = {i["name"] for i in captured["create_index"] if i["table_name"] == "canonical_cards"}
    assert "ix_canonical_cards_card_code" not in index_names


def test_card_prints_has_verified_requires_fields_check_constraint():
    captured = _run_upgrade()
    table = _table(captured, "card_prints")

    check_constraints = {
        c.name: str(c.sqltext)
        for c in table["columns"]
        if type(c).__name__ == "CheckConstraint"
    }
    assert "ck_card_prints_verified_requires_fields" in check_constraints
    condition = check_constraints["ck_card_prints_verified_requires_fields"]
    assert "lower(trim(treatment, ' \t\n\r')) <> 'unknown'" in condition
    assert "release_product_code IS NOT NULL" in condition
    assert "artwork_key IS NOT NULL" in condition


def test_card_prints_rejects_fake_default_values():
    captured = _run_upgrade()
    table = _table(captured, "card_prints")

    check_constraints = {
        c.name: str(c.sqltext)
        for c in table["columns"]
        if type(c).__name__ == "CheckConstraint"
    }
    assert "'original'" in check_constraints["ck_card_prints_no_fake_release_product_code"]
    assert "'original'" in check_constraints["ck_card_prints_no_fake_artwork_key"]


def test_card_prints_has_partial_unique_index_on_active_verified_prints():
    captured = _run_upgrade()
    index = next(
        i for i in captured["create_index"] if i["name"] == "uq_card_prints_active_verified_identity"
    )

    assert index["columns"] == [
        "canonical_card_id",
        "language",
        "treatment",
        "release_product_code",
        "artwork_key",
    ]
    assert index["kwargs"]["unique"] is True
    where_clause = str(index["kwargs"]["postgresql_where"])
    assert "is_active" in where_clause
    assert "verification_status = 'verified'" in where_clause


def test_card_prints_foreign_key_restricts_deletion_of_canonical_cards():
    captured = _run_upgrade()
    table = _table(captured, "card_prints")

    fks = [c for c in table["columns"] if type(c).__name__ == "ForeignKeyConstraint"]
    assert len(fks) == 1
    fk = fks[0]
    assert fk.ondelete == "RESTRICT"
    assert [col for col in fk.column_keys] == ["canonical_card_id"]


def test_downgrade_drops_both_tables_in_dependency_order():
    module = _load_migration()
    dropped = []

    with patch("alembic.op.drop_table", side_effect=lambda name: dropped.append(name)):
        module.downgrade()

    assert dropped == ["card_prints", "canonical_cards"]
