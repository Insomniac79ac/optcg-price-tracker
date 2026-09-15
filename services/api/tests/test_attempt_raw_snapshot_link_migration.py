"""Shape and data-safety checks for the attempt raw-snapshot lineage migration."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "e3a7c5d9b102_link_attempts_to_raw_snapshots.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("attempt_snapshot_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _capture(direction: str):
    module = _load_migration()
    calls = {name: [] for name in (
        "add_column", "drop_column", "create_foreign_key", "drop_constraint",
        "create_index", "drop_index", "execute", "bulk_insert", "get_bind",
    )}
    for name in calls:
        setattr(module.op, name, lambda *args, _name=name, **kwargs: calls[_name].append((args, kwargs)))
    getattr(module, direction)()
    return module, calls


def test_revision_extends_the_current_head():
    module = _load_migration()
    assert module.revision == "e3a7c5d9b102"
    assert module.down_revision == "a8b2c4d6e901"


def test_upgrade_adds_only_nullable_raw_snapshot_lineage():
    module, calls = _capture("upgrade")
    assert len(calls["add_column"]) == 1
    table, column = calls["add_column"][0][0]
    assert table == "source_collection_attempts"
    assert column.name == "raw_snapshot_id"
    assert isinstance(column.type, sa.Integer)
    assert column.nullable is True

    args, kwargs = calls["create_foreign_key"][0]
    assert args == (
        module.FOREIGN_KEY_NAME,
        "source_collection_attempts",
        "raw_snapshots",
        ["raw_snapshot_id"],
        ["id"],
    )
    assert kwargs["ondelete"] == "SET NULL"

    args, _ = calls["create_index"][0]
    assert args == (
        module.INDEX_NAME,
        "source_collection_attempts",
        ["raw_snapshot_id"],
    )


def test_upgrade_does_not_guess_or_backfill_historical_links():
    _, calls = _capture("upgrade")
    assert calls["execute"] == []
    assert calls["bulk_insert"] == []
    assert calls["get_bind"] == []


def test_downgrade_removes_index_then_fk_then_column():
    module, calls = _capture("downgrade")
    assert calls["drop_index"] == [
        ((module.INDEX_NAME,), {"table_name": "source_collection_attempts"})
    ]
    assert calls["drop_constraint"] == [
        (
            (module.FOREIGN_KEY_NAME, "source_collection_attempts"),
            {"type_": "foreignkey"},
        )
    ]
    assert calls["drop_column"] == [
        (("source_collection_attempts", "raw_snapshot_id"), {})
    ]
