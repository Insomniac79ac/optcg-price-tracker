"""Verifies the b858237e3706_add_print_lineage_to_source_card_ migration
defines the expected columns/constraints/indexes, without needing a live
Postgres connection - same technique as test_canonical_cards_migration.py:
op.* calls are patched to record what they were called with instead of
executing DDL."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "b858237e3706_add_print_lineage_to_source_card_.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("print_lineage_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade():
    module = _load_migration()
    captured = {
        "add_column": [],
        "create_index": [],
        "create_foreign_key": [],
        "create_unique_constraint": [],
        "create_check_constraint": [],
    }

    def fake_add_column(table_name, column, **kwargs):
        captured["add_column"].append({"table_name": table_name, "column": column})

    def fake_create_index(name, table_name, columns, **kwargs):
        captured["create_index"].append(
            {"name": name, "table_name": table_name, "columns": columns, "kwargs": kwargs}
        )

    def fake_create_foreign_key(name, source_table, referent_table, local_cols, remote_cols, **kwargs):
        captured["create_foreign_key"].append(
            {
                "name": name,
                "source_table": source_table,
                "referent_table": referent_table,
                "local_cols": local_cols,
                "remote_cols": remote_cols,
                "kwargs": kwargs,
            }
        )

    def fake_create_unique_constraint(name, table_name, columns, **kwargs):
        captured["create_unique_constraint"].append(
            {"name": name, "table_name": table_name, "columns": columns}
        )

    def fake_create_check_constraint(name, table_name, condition, **kwargs):
        captured["create_check_constraint"].append(
            {"name": name, "table_name": table_name, "condition": str(condition)}
        )

    with (
        patch("alembic.op.add_column", side_effect=fake_add_column),
        patch("alembic.op.create_index", side_effect=fake_create_index),
        patch("alembic.op.create_foreign_key", side_effect=fake_create_foreign_key),
        patch("alembic.op.create_unique_constraint", side_effect=fake_create_unique_constraint),
        patch("alembic.op.create_check_constraint", side_effect=fake_create_check_constraint),
    ):
        module.upgrade()

    return captured


def test_revises_the_canonical_cards_migration():
    module = _load_migration()
    assert module.down_revision == "a4d6b1c8f3e2"


def test_adds_card_print_id_to_source_card_mappings():
    captured = _run_upgrade()
    added = [
        c for c in captured["add_column"] if c["table_name"] == "source_card_mappings"
    ]
    assert len(added) == 1
    column = added[0]["column"]
    assert column.name == "card_print_id"
    assert column.nullable is True


def test_source_card_mappings_card_print_id_is_indexed():
    captured = _run_upgrade()
    index = next(
        i for i in captured["create_index"] if i["name"] == "ix_source_card_mappings_card_print_id"
    )
    assert index["table_name"] == "source_card_mappings"
    assert index["columns"] == ["card_print_id"]


def test_source_card_mappings_card_print_id_has_restrict_foreign_key():
    captured = _run_upgrade()
    fk = next(
        f
        for f in captured["create_foreign_key"]
        if f["name"] == "fk_source_card_mappings_card_print_id_card_prints"
    )
    assert fk["source_table"] == "source_card_mappings"
    assert fk["referent_table"] == "card_prints"
    assert fk["local_cols"] == ["card_print_id"]
    assert fk["remote_cols"] == ["id"]
    assert fk["kwargs"]["ondelete"] == "RESTRICT"


def test_source_card_mappings_has_lineage_identity_unique_constraint():
    captured = _run_upgrade()
    uc = next(
        u
        for u in captured["create_unique_constraint"]
        if u["name"] == "uq_source_card_mappings_lineage_identity"
    )
    assert uc["table_name"] == "source_card_mappings"
    assert uc["columns"] == ["id", "card_print_id", "card_id", "source_id"]


def test_adds_lineage_columns_to_price_observations():
    captured = _run_upgrade()
    added = {
        c["column"].name: c["column"]
        for c in captured["add_column"]
        if c["table_name"] == "price_observations"
    }
    assert set(added) == {"source_card_mapping_id", "card_print_id"}
    assert added["source_card_mapping_id"].nullable is True
    assert added["card_print_id"].nullable is True


def test_price_observations_lineage_columns_are_indexed():
    captured = _run_upgrade()
    index_names = {
        i["name"] for i in captured["create_index"] if i["table_name"] == "price_observations"
    }
    assert "ix_price_observations_source_card_mapping_id" in index_names
    assert "ix_price_observations_card_print_id" in index_names


def test_price_observations_has_composite_foreign_key_not_two_independent_ones():
    captured = _run_upgrade()
    fks = [
        f for f in captured["create_foreign_key"] if f["source_table"] == "price_observations"
    ]
    assert len(fks) == 1
    fk = fks[0]
    assert fk["name"] == "fk_price_observations_mapping_print_card_source"
    assert fk["referent_table"] == "source_card_mappings"
    assert fk["local_cols"] == ["source_card_mapping_id", "card_print_id", "card_id", "source_id"]
    assert fk["remote_cols"] == ["id", "card_print_id", "card_id", "source_id"]
    assert fk["kwargs"]["ondelete"] == "RESTRICT"


def test_price_observations_has_paired_lineage_check_constraint():
    captured = _run_upgrade()
    check = next(
        c
        for c in captured["create_check_constraint"]
        if c["name"] == "ck_price_observations_lineage_paired"
    )
    assert check["table_name"] == "price_observations"
    assert "source_card_mapping_id IS NULL AND card_print_id IS NULL" in check["condition"]
    assert "source_card_mapping_id IS NOT NULL AND card_print_id IS NOT NULL" in check["condition"]


def test_downgrade_drops_new_columns_constraints_and_indexes_cleanly():
    module = _load_migration()
    dropped_constraints = []
    dropped_indexes = []
    dropped_columns = []

    def fake_drop_constraint(name, table_name, type_=None):
        dropped_constraints.append({"name": name, "table_name": table_name, "type_": type_})

    def fake_drop_index(name, table_name=None):
        dropped_indexes.append({"name": name, "table_name": table_name})

    def fake_drop_column(table_name, column_name):
        dropped_columns.append({"table_name": table_name, "column_name": column_name})

    with (
        patch("alembic.op.drop_constraint", side_effect=fake_drop_constraint),
        patch("alembic.op.drop_index", side_effect=fake_drop_index),
        patch("alembic.op.drop_column", side_effect=fake_drop_column),
    ):
        module.downgrade()

    constraint_names = {c["name"] for c in dropped_constraints}
    assert constraint_names == {
        "ck_price_observations_lineage_paired",
        "fk_price_observations_mapping_print_card_source",
        "uq_source_card_mappings_lineage_identity",
        "fk_source_card_mappings_card_print_id_card_prints",
    }

    index_names = {i["name"] for i in dropped_indexes}
    assert index_names == {
        "ix_price_observations_card_print_id",
        "ix_price_observations_source_card_mapping_id",
        "ix_source_card_mappings_card_print_id",
    }

    columns_dropped = {(c["table_name"], c["column_name"]) for c in dropped_columns}
    assert columns_dropped == {
        ("price_observations", "card_print_id"),
        ("price_observations", "source_card_mapping_id"),
        ("source_card_mappings", "card_print_id"),
    }

    # Existing card_id/source_id columns on both tables must never be
    # touched by this tranche's downgrade.
    untouched = {"card_id", "source_id"}
    assert untouched.isdisjoint({c["column_name"] for c in dropped_columns})
