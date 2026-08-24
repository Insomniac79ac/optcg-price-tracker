"""Structural coverage for d1c48b7f36ae_make_canonical_original_set_code_nullable.

What this migration must be able to say about itself without a database: it
alters exactly one column on exactly one table, it writes no data at all - no
UPDATE, no INSERT, no backfill, no server default - and its downgrade refuses
before emitting DDL when the data cannot represent NOT NULL.

The live-engine behaviour, including the fail-closed downgrade against real
rows, is in test_canonical_original_set_code_nullable_migration_postgres.
"""

import importlib.util
import re
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
MIGRATION_PATH = VERSIONS_DIR / "d1c48b7f36ae_make_canonical_original_set_code_nullable.py"

REVISION = "d1c48b7f36ae"
DOWN_REVISION = "c7e91a4d2b60"

# Everything this migration is forbidden from touching. Named explicitly so a
# future edit that quietly widens its scope fails here rather than in staging.
UNTOUCHABLE = (
    "ck_canonical_cards_original_set_code_not_blank",
    "ck_canonical_cards_rarity_not_blank",
    "ck_canonical_cards_card_type_not_blank",
    "ck_canonical_cards_requires_a_name",
    "uq_canonical_cards_card_code",
    "ix_canonical_cards_original_set_code",
    "card_prints",
    "release_product_id",
)

# A promo has no original set. Any of these would assert a set membership
# Bandai does not publish, and would then be read back as evidence by the
# baseline rules in print_import_planner.


def _load_migration():
    spec = importlib.util.spec_from_file_location("canonical_set_code_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(direction: str, *, null_rows: int = 0, total_rows: int = 15):
    """Records the DDL one direction emits, in order.

    Every op the migration could plausibly call is patched, not only the one
    it does, so a step it is not supposed to take shows up as an unexpected
    entry rather than silently executing against nothing. `null_rows` is what
    the downgrade preflight's count query is told it found.
    """
    module = _load_migration()
    calls: list[tuple] = []

    def record(name):
        def handler(*args, **kwargs):
            calls.append((name, *args))
            return MagicMock()
        return handler

    scalars = iter([null_rows, total_rows])
    bind = MagicMock()

    def execute(clause, *args, **kwargs):
        result = MagicMock()
        result.scalar_one.side_effect = lambda: next(scalars)
        result.all.return_value = [("P-014",), ("P-107",)]
        return result

    bind.execute.side_effect = execute

    with ExitStack() as stack:
        for op_name in (
            "add_column", "drop_column", "alter_column", "create_index", "drop_index",
            "create_check_constraint", "drop_constraint", "create_table", "drop_table",
            "execute", "bulk_insert", "rename_table",
        ):
            stack.enter_context(patch(f"alembic.op.{op_name}", side_effect=record(op_name)))
        stack.enter_context(patch("alembic.op.get_bind", return_value=bind))
        # batch_alter_table proxies to the same ops, so the recorder sees the
        # alter_column either way.
        stack.enter_context(
            patch("alembic.op.batch_alter_table", side_effect=lambda *a, **k: _FakeBatch(calls, a))
        )
        getattr(module, direction)()

    return calls


class _FakeBatch:
    """Stands in for op.batch_alter_table's context manager."""

    def __init__(self, calls, args):
        self._calls = calls
        self._table = args[0] if args else None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def alter_column(self, column, **kwargs):
        self._calls.append(("alter_column", self._table, column, kwargs))


# --- chain position ---------------------------------------------------------


def test_the_revision_sits_on_the_rarity_nullable_head():
    module = _load_migration()

    assert module.revision == REVISION
    assert module.down_revision == DOWN_REVISION


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
    assert len(heads) == 1, f"expected a single head, found {heads}"
    assert REVISION in revisions
    assert heads == [REVISION] or REVISION in downs


# --- what upgrade does ------------------------------------------------------


def test_upgrade_alters_exactly_one_column_on_one_table():
    calls = _run("upgrade")

    assert [c[0] for c in calls] == ["alter_column"]
    _, table, column, kwargs = calls[0]
    assert table == "canonical_cards"
    assert column == "original_set_code"
    assert kwargs["nullable"] is True


def test_upgrade_writes_no_data_and_supplies_no_default():
    """The whole point: existing values are left exactly as they are.

    A backfill or a server_default would put a value nobody published onto
    every row, and afterwards nothing could tell it apart from evidence.
    """
    calls = _run("upgrade")

    assert not [c for c in calls if c[0] in ("execute", "bulk_insert")]
    assert "server_default" not in calls[0][3]
    assert calls[0][3].get("existing_type").length == 32


def test_upgrade_touches_nothing_else():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    body = source.split("def upgrade()")[1].split("def downgrade()")[0]

    for name in UNTOUCHABLE:
        assert name not in body, f"upgrade must not touch {name}"
    for forbidden in ("UPDATE", "INSERT", "DELETE", "COALESCE"):
        assert forbidden not in body.upper(), f"upgrade must not contain {forbidden}"


def test_no_synthetic_set_code_can_be_written():
    """The migration has no mechanism to put a value in the column at all.

    Checked as an absence of capability rather than by scanning for the
    strings 'P' / 'PROMO' / 'PR': those legitimately appear in the downgrade's
    refusal message, which names them precisely in order to refuse them. What
    matters is that neither direction emits a data statement or a default, so
    there is nowhere for any value - invented or not - to come from.
    """
    for direction in ("upgrade", "downgrade"):
        calls = _run(direction)
        assert [c[0] for c in calls] == ["alter_column"], direction
        assert "server_default" not in calls[0][3], direction
        assert set(calls[0][3]) <= {"existing_type", "nullable"}, direction


def test_the_refusal_names_the_inventions_it_will_not_make():
    """An operator hitting the refusal must be told why 'P' is not the answer,
    or they will simply write it themselves."""
    with pytest.raises(RuntimeError) as excinfo:
        _run("downgrade", null_rows=31)

    message = str(excinfo.value)
    for named in ("'P'", "'PROMO'", "'PR'"):
        assert named in message, named
    assert "distribution product" in message


def test_the_migration_reads_no_file_and_opens_no_socket():
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    for forbidden in ("requests", "urllib", "httpx", "socket", "open(", "Path("):
        assert forbidden not in source


# --- what downgrade does ----------------------------------------------------


def test_downgrade_restores_not_null_when_the_data_allows_it():
    calls = _run("downgrade", null_rows=0)

    assert [c[0] for c in calls] == ["alter_column"]
    _, table, column, kwargs = calls[0]
    assert (table, column) == ("canonical_cards", "original_set_code")
    assert kwargs["nullable"] is False


def test_downgrade_aborts_before_any_ddl_when_a_set_code_is_null():
    """Fail-closed. The preflight runs first, so a refusal leaves the schema,
    the revision and the data exactly as they were."""
    with pytest.raises(RuntimeError) as excinfo:
        _run("downgrade", null_rows=31)

    message = str(excinfo.value)
    assert REVISION in message
    assert "31 canonical_cards row(s)" in message
    # It names the codes an operator has to decide about.
    assert "P-014" in message


def test_downgrade_never_invents_a_value():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    body = source.split("def _preflight_downgrade()")[1].split("def upgrade()")[0]

    # It counts and it names. It does not write.
    assert "UPDATE" not in body.upper()
    assert "INSERT" not in body.upper()
    assert "COALESCE" not in body.upper()
    assert "SELECT count(*)" in body


def test_the_refusal_explains_where_the_real_product_evidence_lives():
    """A refusal that does not say what to do instead gets worked around."""
    with pytest.raises(RuntimeError) as excinfo:
        _run("downgrade", null_rows=1)

    assert "release_product_id" in str(excinfo.value)
