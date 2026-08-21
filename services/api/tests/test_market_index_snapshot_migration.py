"""Verifies the a9c4e17b6d52_add_market_index_snapshots migration defines the
same table the ORM model declares, without needing a live Postgres connection -
same technique as test_print_lineage_migration.py: op.* calls are patched to
record what they were called with instead of executing DDL.

This exists because the migration and app.models.market_index_snapshot are two
independent declarations of one table. The suite's other schema assertions run
against Base.metadata.create_all (the model), so a migration that silently
disagreed with the model - a missing CHECK, a CASCADE where the model says
RESTRICT - would not be caught anywhere else.
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.models.market_index_snapshot import MarketIndexSnapshot

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "a9c4e17b6d52_add_market_index_snapshots.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("market_index_snapshot_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade():
    module = _load_migration()
    captured = {"create_table": [], "create_index": []}

    def fake_create_table(table_name, *columns, **kwargs):
        captured["create_table"].append({"table_name": table_name, "columns": columns})

    def fake_create_index(name, table_name, columns, **kwargs):
        captured["create_index"].append(
            {"name": name, "table_name": table_name, "columns": columns}
        )

    module.op.create_table = fake_create_table
    module.op.create_index = fake_create_index
    module.upgrade()
    return captured


def _run_downgrade():
    module = _load_migration()
    captured = {"drop_table": [], "drop_index": []}

    module.op.drop_table = lambda table_name, **kw: captured["drop_table"].append(table_name)
    module.op.drop_index = lambda name, **kw: captured["drop_index"].append(name)
    module.downgrade()
    return captured


def _table(captured):
    assert len(captured["create_table"]) == 1
    return captured["create_table"][0]


def _elements(captured):
    return _table(captured)["columns"]


def _columns(captured):
    return {c.name: c for c in _elements(captured) if isinstance(c, sa.Column)}


def _constraints(captured, kind):
    return [c for c in _elements(captured) if isinstance(c, kind)]


def test_revision_chain():
    module = _load_migration()

    assert module.revision == "a9c4e17b6d52"
    assert module.down_revision == "d7e2b9f4a1c3"


def test_creates_market_index_snapshots_table():
    captured = _run_upgrade()

    assert _table(captured)["table_name"] == "market_index_snapshots"


def test_migration_columns_match_the_model():
    captured = _run_upgrade()

    assert set(_columns(captured)) == {c.name for c in MarketIndexSnapshot.__table__.columns}


def test_nullability_matches_the_model():
    captured = _run_upgrade()
    migration_columns = _columns(captured)

    for model_column in MarketIndexSnapshot.__table__.columns:
        if model_column.primary_key:
            continue
        assert (
            migration_columns[model_column.name].nullable == model_column.nullable
        ), f"{model_column.name} nullability differs between migration and model"


def test_nullable_columns_are_exactly_the_optional_ones():
    captured = _run_upgrade()

    nullable = {name for name, c in _columns(captured).items() if c.nullable}
    assert nullable == {
        "index_value_jpy",
        "source_price_range_low_jpy",
        "source_price_range_high_jpy",
        "freshest_eligible_source_at",
        "stalest_eligible_source_at",
    }


def test_provenance_is_jsonb_on_postgres():
    captured = _run_upgrade()
    provenance = _columns(captured)["provenance"]

    assert provenance.nullable is False
    dialect_type = provenance.type.dialect_impl(postgresql.dialect())
    assert isinstance(dialect_type, postgresql.JSONB)


def test_unique_constraint_is_print_plus_date():
    captured = _run_upgrade()
    uniques = _constraints(captured, sa.UniqueConstraint)

    assert len(uniques) == 1
    assert uniques[0].name == "uq_market_index_snapshots_print_date"
    # The constraint is unbound here (create_table was patched, so it was never
    # attached to a Table), which leaves .columns empty - the column names it
    # was constructed with live in _pending_colargs until binding.
    assert uniques[0]._pending_colargs == ["card_print_id", "snapshot_date"]


def test_card_print_foreign_key_restricts():
    captured = _run_upgrade()
    fks = _constraints(captured, sa.ForeignKeyConstraint)

    assert len(fks) == 1
    assert fks[0].column_keys == ["card_print_id"]
    assert [e._get_colspec() for e in fks[0].elements] == ["card_prints.id"]
    assert fks[0].ondelete == "RESTRICT"


def test_check_constraints_present():
    captured = _run_upgrade()
    checks = {c.name: str(c.sqltext) for c in _constraints(captured, sa.CheckConstraint)}

    assert set(checks) == {
        "ck_market_index_snapshots_coverage_status",
        "ck_market_index_snapshots_confidence",
        "ck_market_index_snapshots_value_presence",
        "ck_market_index_snapshots_range_pairing",
        "ck_market_index_snapshots_range_order",
    }
    assert "full" in checks["ck_market_index_snapshots_coverage_status"]
    assert "limited" in checks["ck_market_index_snapshots_coverage_status"]
    assert "none" in checks["ck_market_index_snapshots_coverage_status"]
    assert "high" in checks["ck_market_index_snapshots_confidence"]
    assert "medium" in checks["ck_market_index_snapshots_confidence"]
    assert "low" in checks["ck_market_index_snapshots_confidence"]
    assert (
        checks["ck_market_index_snapshots_value_presence"]
        == "(index_value_jpy IS NULL) = (coverage_status = 'none')"
    )
    assert checks["ck_market_index_snapshots_range_pairing"] == (
        "(source_price_range_low_jpy IS NULL) = (source_price_range_high_jpy IS NULL)"
    )
    assert checks["ck_market_index_snapshots_range_order"] == (
        "source_price_range_low_jpy IS NULL "
        "OR source_price_range_low_jpy <= source_price_range_high_jpy"
    )


def test_migration_check_constraints_match_the_model():
    """The migration and the model each declare their own CHECK constraints -
    this is what keeps the two from drifting apart."""
    captured = _run_upgrade()
    migration_checks = {
        c.name: str(c.sqltext) for c in _constraints(captured, sa.CheckConstraint)
    }
    model_checks = {
        c.name: str(c.sqltext)
        for c in MarketIndexSnapshot.__table__.constraints
        if isinstance(c, sa.CheckConstraint)
    }

    assert migration_checks == model_checks


def test_creates_the_read_path_index():
    captured = _run_upgrade()
    indexes = {i["name"]: i["columns"] for i in captured["create_index"]}

    assert indexes["ix_market_index_snapshots_print_calculated"] == [
        "card_print_id",
        "calculated_at",
    ]
    assert all(i["table_name"] == "market_index_snapshots" for i in captured["create_index"])


def test_downgrade_drops_only_what_upgrade_created():
    upgraded = _run_upgrade()
    downgraded = _run_downgrade()

    assert downgraded["drop_table"] == ["market_index_snapshots"]
    assert set(downgraded["drop_index"]) == {i["name"] for i in upgraded["create_index"]}


def test_migration_touches_no_other_table():
    captured = _run_upgrade()

    assert {t["table_name"] for t in captured["create_table"]} == {"market_index_snapshots"}
    assert {i["table_name"] for i in captured["create_index"]} == {"market_index_snapshots"}
