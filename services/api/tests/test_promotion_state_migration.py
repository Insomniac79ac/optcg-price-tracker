"""The c4a7e9d15b83 promotion_state migration: it must add exactly a nullable
column and a CHECK, and it must touch no existing row.

Same technique as test_market_index_snapshot_migration.py - op.* is patched to
record what it was called with instead of executing DDL, so no live Postgres
is needed. The migration and app.models.price_observation are two independent
declarations of one column, and the suite's other schema assertions all run
against Base.metadata.create_all (the model), so a migration that silently
disagreed with the model would otherwise be caught nowhere.

The no-backfill assertions are the point of the file. 549 Yuyu-Tei
observations already exist, four prints' worth of them demonstrably captured
while the source displayed a SALE badge. Setting every row to 'none' would be
false, and setting those four to 'sale' would claim Atlas classified them at
capture time when it did not. Leaving them NULL is the only honest answer, so
a migration that grew an UPDATE would be a correctness bug, not a style one.
"""

import importlib.util
from pathlib import Path

from app.models import PriceObservation

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "c4a7e9d15b83_add_price_observation_promotion_state.py"
)

EXPECTED_CHECK = "promotion_state IS NULL OR promotion_state IN ('none', 'sale')"


def _load_migration():
    spec = importlib.util.spec_from_file_location("promotion_state_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _capture(direction: str) -> dict:
    """Run upgrade() or downgrade() with every op.* the migration could use
    replaced by a recorder. Anything it calls that is NOT recorded here raises
    AttributeError, so a newly added data-migration call cannot pass silently."""
    module = _load_migration()
    captured = {
        "add_column": [],
        "drop_column": [],
        "create_check_constraint": [],
        "drop_constraint": [],
        "execute": [],
        "bulk_insert": [],
        "get_bind": [],
    }

    module.op.add_column = lambda table, column, **kw: captured["add_column"].append((table, column))
    module.op.drop_column = lambda table, column, **kw: captured["drop_column"].append((table, column))
    module.op.create_check_constraint = lambda name, table, condition, **kw: captured[
        "create_check_constraint"
    ].append((name, table, condition))
    module.op.drop_constraint = lambda name, table, **kw: captured["drop_constraint"].append((name, table))
    # The three ways a data migration could reach existing rows. Recorded so
    # the assertions below can prove none of them was used.
    module.op.execute = lambda *a, **kw: captured["execute"].append(a)
    module.op.bulk_insert = lambda *a, **kw: captured["bulk_insert"].append(a)
    module.op.get_bind = lambda *a, **kw: captured["get_bind"].append(a) or None

    getattr(module, direction)()
    return captured


# --- revision chain ---------------------------------------------------------


def test_migration_extends_the_current_head():
    module = _load_migration()
    assert module.revision == "c4a7e9d15b83"
    assert module.down_revision == "b7d31e5c9a24"


# --- upgrade shape ----------------------------------------------------------


def test_upgrade_adds_one_nullable_column_to_price_observations():
    captured = _capture("upgrade")
    assert len(captured["add_column"]) == 1
    table, column = captured["add_column"][0]
    assert table == "price_observations"
    assert column.name == "promotion_state"
    assert column.nullable is True


def test_the_column_is_a_bounded_string():
    """Unbounded text would accept anything the CHECK later has to reject; the
    length is part of the contract, not incidental."""
    _table, column = _capture("upgrade")["add_column"][0]
    assert column.type.length == 16


def test_upgrade_adds_the_vocabulary_check():
    captured = _capture("upgrade")
    assert len(captured["create_check_constraint"]) == 1
    name, table, condition = captured["create_check_constraint"][0]
    assert name == "ck_price_observations_promotion_state"
    assert table == "price_observations"
    assert condition == EXPECTED_CHECK


def test_the_check_permits_null():
    """NULL is the state every pre-existing row carries and the state an
    indeterminate page produces. A NOT NULL-style rule would break both."""
    assert "IS NULL" in EXPECTED_CHECK


# --- the model and the migration agree --------------------------------------


def test_the_model_declares_the_same_column():
    column = PriceObservation.__table__.columns["promotion_state"]
    assert column.nullable is True
    assert column.type.length == 16


def test_the_model_declares_the_same_check():
    constraint = next(
        c
        for c in PriceObservation.__table__.constraints
        if c.name == "ck_price_observations_promotion_state"
    )
    assert str(constraint.sqltext) == EXPECTED_CHECK


# --- no backfill ------------------------------------------------------------


def test_upgrade_runs_no_data_migration():
    """The assertion this file exists for: no UPDATE, no INSERT, no connection
    obtained. Historical observations keep exactly the values they had, which
    for promotion_state means NULL - "not determined"."""
    captured = _capture("upgrade")
    assert captured["execute"] == []
    assert captured["bulk_insert"] == []
    assert captured["get_bind"] == []


def test_the_migration_source_contains_no_write_statement():
    """A textual backstop against a future edit that reaches rows through a
    path this file does not patch (raw sqlalchemy, a session, a helper)."""
    source = MIGRATION_PATH.read_text()
    body = source.split('"""', 2)[-1].upper()  # skip the docstring
    for statement in ("UPDATE ", "INSERT ", "DELETE ", "SET PROMOTION_STATE"):
        assert statement not in body, statement


# --- downgrade --------------------------------------------------------------


def test_downgrade_removes_both_objects_and_nothing_else():
    captured = _capture("downgrade")
    assert captured["drop_constraint"] == [
        ("ck_price_observations_promotion_state", "price_observations")
    ]
    assert captured["drop_column"] == [("price_observations", "promotion_state")]
    assert captured["execute"] == []


def test_downgrade_drops_the_constraint_before_the_column():
    """Order matters on Postgres: dropping the column first leaves the CHECK
    referring to a column that no longer exists."""
    module = _load_migration()
    order = []
    module.op.drop_constraint = lambda *a, **kw: order.append("constraint")
    module.op.drop_column = lambda *a, **kw: order.append("column")
    module.downgrade()
    assert order == ["constraint", "column"]
