"""Structural coverage for b8d5f1c40e73_add_print_official_metadata.

What this migration must be able to say about itself without a database: it
adds exactly four nullable columns and touches nothing else, it writes no
data, it reads no file and opens no socket, and its downgrade drops exactly
the four columns it added and nothing more.

The live-engine behaviour is in test_print_official_metadata_migration_postgres.
"""

import importlib.util
import re
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa

from app.models import CardPrint
from app.services.print_import_planner import METADATA_FIELDS

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
MIGRATION_PATH = VERSIONS_DIR / "b8d5f1c40e73_add_print_official_metadata.py"

EXPECTED_COLUMNS = (
    "official_rarity",
    "official_block_icon",
    "official_name",
    "official_effect_text",
)

# Everything this migration is forbidden from touching. Named explicitly so a
# future edit that quietly widens its scope fails here.
UNTOUCHABLE = (
    "uq_card_prints_active_verified_identity",
    "ck_card_prints_verified_requires_fields",
    "ck_card_prints_official_asset_variant_format",
    "official_asset_variant",
    "treatment",
    "artwork_key",
    "release_product_id",
    "release_product_code",
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("print_metadata_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(direction: str) -> list[tuple]:
    """Records the DDL one direction emits, in order.

    Every op the migration could plausibly call is patched, not just the two
    it does - so a step it is not supposed to take shows up as an unexpected
    entry rather than silently executing against nothing.
    """
    module = _load_migration()
    calls: list[tuple] = []

    def record(name):
        def handler(*args, **kwargs):
            calls.append((name, *args))
        return handler

    with ExitStack() as stack:
        for op_name in (
            "add_column", "drop_column", "alter_column", "create_index", "drop_index",
            "create_check_constraint", "drop_constraint", "create_table", "drop_table",
            "execute", "bulk_insert", "rename_table",
        ):
            stack.enter_context(patch(f"alembic.op.{op_name}", side_effect=record(op_name)))
        getattr(module, direction)()

    return calls


# --- chain position ---------------------------------------------------------


def test_the_revision_sits_on_the_asset_variant_head():
    module = _load_migration()

    assert module.revision == "b8d5f1c40e73"
    assert module.down_revision == "f2e6b3a71c85"


def test_migration_history_has_exactly_one_head():
    revisions: set[str] = set()
    downs: set[str] = set()
    for path in VERSIONS_DIR.glob("*.py"):
        source = path.read_text()
        revision = re.search(r"^revision: str = ['\"]([^'\"]+)", source, re.M)
        if revision:
            revisions.add(revision.group(1))
        down = re.search(r"^down_revision[^=]*= ['\"]([^'\"]+)", source, re.M)
        if down:
            downs.add(down.group(1))

    heads = sorted(rev for rev in revisions if rev not in downs)
    # One head, whatever the latest revision happens to be - this migration is
    # in the chain either as that head or as an ancestor of it (a9f31c7d5b64,
    # the asset-variant contract migration, now follows it).
    assert len(heads) == 1, f"expected a single head, found {heads}"
    assert "b8d5f1c40e73" in revisions
    assert heads == ["b8d5f1c40e73"] or "b8d5f1c40e73" in downs


# --- what upgrade does ------------------------------------------------------


def test_upgrade_adds_exactly_the_four_columns():
    calls = _run("upgrade")

    assert [c[0] for c in calls] == ["add_column"] * 4
    assert [c[1] for c in calls] == ["card_prints"] * 4
    assert tuple(c[2].name for c in calls) == EXPECTED_COLUMNS


def test_every_added_column_is_nullable_with_no_server_default():
    """A default would write a value nobody published, on every existing row."""
    for _, _, column in _run("upgrade"):
        assert column.nullable is True, column.name
        assert column.server_default is None, column.name


def test_the_column_types_match_the_declared_conventions():
    types = {c[2].name: c[2].type for c in _run("upgrade")}

    assert isinstance(types["official_rarity"], sa.String)
    assert types["official_rarity"].length == 32
    assert isinstance(types["official_block_icon"], sa.String)
    assert types["official_block_icon"].length == 8
    assert isinstance(types["official_name"], sa.String)
    assert types["official_name"].length == 255
    # Text, not a bounded String - and specifically not a String subclass with
    # a length, which is what an accidental `String()` would look like here.
    assert isinstance(types["official_effect_text"], sa.Text)
    assert getattr(types["official_effect_text"], "length", None) is None


def test_the_block_icon_column_is_textual_not_numeric():
    """The corpus publishes '1'-'5' and also 'X'. An integer column would have
    to invent a meaning for 'X' or discard those 27 occurrences."""
    types = {c[2].name: c[2].type for c in _run("upgrade")}

    assert not isinstance(types["official_block_icon"], (sa.Integer, sa.SmallInteger))


def test_upgrade_touches_nothing_else():
    calls = _run("upgrade")
    emitted = " ".join(str(part) for call in calls for part in call)

    for name in UNTOUCHABLE:
        assert name not in emitted, f"upgrade touched {name}"


# --- what downgrade does ----------------------------------------------------


def test_downgrade_drops_exactly_the_four_columns():
    calls = _run("downgrade")

    assert [c[0] for c in calls] == ["drop_column"] * 4
    assert [c[1] for c in calls] == ["card_prints"] * 4
    assert set(c[2] for c in calls) == set(EXPECTED_COLUMNS)


def test_downgrade_is_the_exact_inverse_of_upgrade():
    added = [c[2].name for c in _run("upgrade")]
    dropped = [c[2] for c in _run("downgrade")]

    assert dropped == list(reversed(added))


def test_downgrade_touches_nothing_else():
    calls = _run("downgrade")
    emitted = " ".join(str(part) for call in calls for part in call)

    for name in UNTOUCHABLE:
        assert name not in emitted, f"downgrade touched {name}"


# --- what the migration must never do ---------------------------------------


def test_the_migration_writes_no_data():
    """No UPDATE, no INSERT, no DELETE - in either direction, and nowhere in
    the source. A backfill is a separate decision from a schema change."""
    source = MIGRATION_PATH.read_text()
    code = "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
    )

    for statement in ("UPDATE ", "INSERT ", "DELETE ", "update(", "insert(", "delete("):
        assert statement.lower() not in code.lower(), f"migration contains {statement!r}"
    for direction in ("upgrade", "downgrade"):
        assert all(call[0] in ("add_column", "drop_column") for call in _run(direction))


def test_the_migration_performs_no_io():
    """No network, no snapshot file. The corpus numbers in its docstring are
    recorded provenance, not something read at migration time."""
    source = MIGRATION_PATH.read_text()

    for forbidden in (
        "requests", "urllib", "httpx", "socket", "open(", "Path(", "json.load",
        "official_snapshot", "read_text", "glob",
    ):
        assert forbidden not in source, f"migration references {forbidden!r}"


def test_the_migration_does_not_import_application_code():
    """A migration that imports app code silently changes meaning when that
    code changes. This one needs only alembic and sqlalchemy."""
    source = MIGRATION_PATH.read_text()

    assert "from app" not in source
    assert "import app" not in source


# --- agreement with the model ----------------------------------------------


def test_the_model_declares_the_same_four_columns():
    for name in EXPECTED_COLUMNS:
        assert name in CardPrint.__table__.columns
        assert CardPrint.__table__.columns[name].nullable is True


def test_the_planner_and_the_migration_name_the_same_fields():
    """One vocabulary. If a field is added to one and not the other, a write
    step would have a plan value with no column, or a column nothing fills."""
    assert tuple(METADATA_FIELDS) == EXPECTED_COLUMNS


def test_the_model_types_match_the_migration_types():
    for _, _, column in _run("upgrade"):
        model_type = CardPrint.__table__.columns[column.name].type
        assert type(model_type) is type(column.type), column.name
        assert getattr(model_type, "length", None) == getattr(column.type, "length", None)
