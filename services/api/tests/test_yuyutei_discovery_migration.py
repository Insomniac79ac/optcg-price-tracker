"""Verifies b7d31e5c9a24_add_yuyutei_discovery_and_candidates defines the same
two tables the ORM models declare, without needing a live Postgres connection -
same technique as test_market_index_snapshot_migration.py: op.* calls are
patched to record what they were called with instead of executing DDL.

The migration and app.models.yuyutei_* are two independent declarations of one
schema. The rest of the suite runs against Base.metadata.create_all (the
model), so a migration that silently disagreed - a missing CHECK, product_id
unique on its own, a foreign key pointing at legacy `cards` - would not be
caught anywhere else. Those three are exactly the disagreements that would be
unsafe, so they are asserted by name below.
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa

from app.models.yuyutei_candidate import YuyuteiCandidate
from app.models.yuyutei_discovery_run import YuyuteiDiscoveryRun

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "b7d31e5c9a24_add_yuyutei_discovery_and_candidates.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("yuyutei_discovery_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade():
    """Reconstructs each created table as a real sa.Table, so constraints
    resolve their columns exactly as they would against a live metadata."""
    module = _load_migration()
    metadata = sa.MetaData()
    captured = {"create_table": {}, "create_index": []}

    def fake_create_table(table_name, *columns, **kwargs):
        captured["create_table"][table_name] = sa.Table(table_name, metadata, *columns)

    def fake_create_index(name, table_name, columns, **kwargs):
        captured["create_index"].append({"name": name, "table": table_name, "columns": columns})

    module.op.create_table = fake_create_table
    module.op.create_index = fake_create_index
    # op.f() is the naming-convention passthrough; outside a live migration
    # context its proxy is unbound, so stand in with identity.
    module.op.f = lambda name: name
    module.upgrade()
    return captured


def _columns(captured, table):
    return {c.name: c for c in captured["create_table"][table].columns}


def _constraints(captured, table):
    return list(captured["create_table"][table].constraints)


def test_the_migration_chains_onto_the_previous_head():
    module = _load_migration()
    assert module.revision == "b7d31e5c9a24"
    assert module.down_revision == "d7a4c2b91f08"


def test_both_tables_are_created():
    captured = _run_upgrade()
    assert set(captured["create_table"]) == {"yuyutei_discovery_runs", "yuyutei_candidates"}


def test_run_columns_match_the_model():
    captured = _run_upgrade()
    assert set(_columns(captured, "yuyutei_discovery_runs")) == {
        column.name for column in YuyuteiDiscoveryRun.__table__.columns
    }


def test_candidate_columns_match_the_model():
    captured = _run_upgrade()
    assert set(_columns(captured, "yuyutei_candidates")) == {
        column.name for column in YuyuteiCandidate.__table__.columns
    }


def test_source_identity_is_unique_on_the_pair_not_on_product_id():
    captured = _run_upgrade()
    uniques = [
        c for c in _constraints(captured, "yuyutei_candidates") if isinstance(c, sa.UniqueConstraint)
    ]
    assert len(uniques) == 1
    assert [c.name for c in uniques[0].columns] == ["set_slug", "product_id"]

    # And no column-level unique that would accidentally make product_id or
    # source_url globally unique across sets.
    for column in _columns(captured, "yuyutei_candidates").values():
        assert column.unique in (None, False), column.name
    for index in captured["create_index"]:
        assert index.get("columns") != ["product_id"]


def test_the_matched_print_points_at_card_prints_not_legacy_cards():
    captured = _run_upgrade()
    foreign_keys = {
        c.column_keys[0]: c.elements[0]._get_colspec()
        for c in _constraints(captured, "yuyutei_candidates")
        if isinstance(c, sa.ForeignKeyConstraint)
    }
    assert foreign_keys["matched_card_print_id"] == "card_prints.id"
    assert foreign_keys["discovery_run_id"] == "yuyutei_discovery_runs.id"


def test_the_safety_checks_are_present():
    captured = _run_upgrade()
    checks = {
        c.name: str(c.sqltext)
        for c in _constraints(captured, "yuyutei_candidates")
        if isinstance(c, sa.CheckConstraint)
    }
    assert set(checks) == {
        "ck_yuyutei_candidates_match_status",
        "ck_yuyutei_candidates_print_requires_print_matched",
        "ck_yuyutei_candidates_availability",
        "ck_yuyutei_candidates_price_positive",
    }
    # The one that makes "pick a representative printing" unrepresentable.
    assert "print_matched" in checks["ck_yuyutei_candidates_print_requires_print_matched"]
    assert "identity_conflict" in checks["ck_yuyutei_candidates_match_status"]


def test_downgrade_removes_everything_it_created():
    module = _load_migration()
    dropped = {"tables": [], "indexes": []}
    module.op.f = lambda name: name
    module.op.drop_table = lambda name, **kw: dropped["tables"].append(name)
    module.op.drop_index = lambda name, **kw: dropped["indexes"].append(name)
    module.downgrade()

    # Children before parents.
    assert dropped["tables"] == ["yuyutei_candidates", "yuyutei_discovery_runs"]
    assert len(dropped["indexes"]) == 4
