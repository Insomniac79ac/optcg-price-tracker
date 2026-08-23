"""Structural coverage for f2e6b3a71c85, the EXPAND half of the release.

What this migration must be able to say about itself without a database: it
*adds* official_asset_variant rather than renaming official_artwork_variant
(so both application generations can read the schema it leaves behind), it
copies every stored value across, it installs the widened format check before
that copy, and it leaves the identity index, the verified check and the legacy
format check exactly as d4b17c9e2a83 left them - because the application
deployed at the time it runs still depends on all three.

Its downgrade drops the new column, and refuses whenever that column holds
anything the legacy one does not.

The contract half is covered by test_official_asset_variant_cleanup_migration;
live-engine behaviour by the two *_postgres modules.
"""

import importlib.util
import re
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
MIGRATION_PATH = VERSIONS_DIR / "f2e6b3a71c85_generalize_official_asset_variant.py"

OLD_COLUMN = "official_artwork_variant"
NEW_COLUMN = "official_asset_variant"

IDENTITY_INDEX = "uq_card_prints_active_verified_identity"
VERIFIED_CHECK = "ck_card_prints_verified_requires_fields"
OLD_FORMAT_CHECK = "ck_card_prints_official_artwork_variant_format"
NEW_FORMAT_CHECK = "ck_card_prints_official_asset_variant_format"


def _load_migration():
    spec = importlib.util.spec_from_file_location("asset_variant_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(direction: str, *, skip_preflight: bool = True):
    """Records the DDL one direction emits, in order."""
    module = _load_migration()
    calls: list[tuple] = []

    patches = [
        patch("alembic.op.add_column",
              side_effect=lambda table, column, **kw: calls.append(
                  ("add_column", column.name, str(column.type), column.nullable))),
        patch("alembic.op.drop_column",
              side_effect=lambda table, name, **kw: calls.append(("drop_column", name))),
        patch("alembic.op.drop_index",
              side_effect=lambda name, **kw: calls.append(("drop_index", name))),
        patch("alembic.op.drop_constraint",
              side_effect=lambda name, table, **kw: calls.append(("drop_constraint", name))),
        patch("alembic.op.alter_column",
              side_effect=lambda table, name, **kw: calls.append(
                  ("alter_column", name, kw.get("new_column_name")))),
        patch("alembic.op.create_check_constraint",
              side_effect=lambda name, table, condition, **kw: calls.append(
                  ("create_check_constraint", name, condition))),
        patch("alembic.op.create_index",
              side_effect=lambda name, table, columns, **kw: calls.append(
                  ("create_index", name, tuple(columns), str(kw.get("postgresql_where"))))),
        patch.object(module, "_report"),
        patch.object(module, "_backfill", return_value=20),
    ]
    if skip_preflight:
        patches.append(patch.object(module, "_preflight_downgrade"))

    with ExitStack() as stack:
        for patcher in patches:
            stack.enter_context(patcher)
        getattr(module, direction)()

    return module, calls


# --- placement in history --------------------------------------------------


def test_revision_follows_the_identity_activation():
    module = _load_migration()

    assert module.revision == "f2e6b3a71c85"
    assert module.down_revision == "d4b17c9e2a83"


def test_migration_history_still_has_exactly_one_head():
    revisions = {}
    downs = set()
    for path in VERSIONS_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        rev = re.search(r"^revision(?::\s*str)?\s*=\s*['\"]([^'\"]+)", source, re.M)
        down = re.search(
            r"^down_revision(?::[^=]*)?\s*=\s*(?:['\"]([^'\"]+)['\"]|None)", source, re.M
        )
        if rev:
            revisions[rev.group(1)] = path.name
            if down and down.group(1):
                downs.add(down.group(1))

    heads = sorted(rev for rev in revisions if rev not in downs)
    # One head, whatever the latest revision happens to be - this migration is
    # in the chain either as that head or as an ancestor of it. Pinning the
    # head to this revision would make every later migration fail here.
    assert len(heads) == 1, f"expected a single head, got {heads}"
    assert "f2e6b3a71c85" in revisions
    assert heads == ["f2e6b3a71c85"] or "f2e6b3a71c85" in downs


# --- expand, not rename ----------------------------------------------------


def test_upgrade_adds_the_column_and_never_renames_or_drops_one():
    """The whole point of the expand phase. A rename would remove the column
    the currently deployed application queries, and a drop-and-add would
    discard every stored variant."""
    module, calls = _run("upgrade")

    added = [c for c in calls if c[0] == "add_column"]
    assert added == [("add_column", NEW_COLUMN, "VARCHAR(16)", True)]
    assert [c for c in calls if c[0] == "alter_column"] == []
    assert [c for c in calls if c[0] == "drop_column"] == []

    source = MIGRATION_PATH.read_text(encoding="utf-8")
    upgrade_body = source.split("def upgrade()")[1].split("def downgrade()")[0]
    assert "new_column_name" not in source
    # The upgrade drops nothing; only the downgrade removes what it added.
    assert "op.drop_column" not in upgrade_body
    # The only write is the backfill; nothing inserts or deletes.
    for forbidden in ("INSERT INTO", "DELETE FROM"):
        assert forbidden not in source


def test_the_upgrade_touches_nothing_the_deployed_application_depends_on():
    """The compatibility guarantee, asserted as an absence: the expand phase
    drops nothing at all, so every constraint and index the old application
    relies on is still in force afterwards."""
    module, calls = _run("upgrade")

    assert [c for c in calls if c[0].startswith("drop_")] == []
    assert [c for c in calls if c[0] == "create_index"] == []
    assert [c[1] for c in calls if c[0] == "create_check_constraint"] == [NEW_FORMAT_CHECK]
    # Named in the migration only to say they are left alone.
    assert module.IDENTITY_INDEX == IDENTITY_INDEX
    assert module.VERIFIED_CHECK == VERIFIED_CHECK


def test_the_upgrade_order_checks_the_copy_rather_than_trusting_it():
    """The format check must exist before the backfill runs, so a value the
    new vocabulary does not admit fails loudly instead of being written."""
    module, calls = _run("upgrade")
    order = [c[0] for c in calls]

    assert order == ["add_column", "create_check_constraint"]

    body = MIGRATION_PATH.read_text(encoding="utf-8").split("def upgrade()")[1]
    assert body.index("create_check_constraint") < body.index("_backfill()")
    assert body.index("op.add_column") < body.index("create_check_constraint")


def test_the_backfill_copies_verbatim_and_guesses_nothing():
    """The statement itself, not a paraphrase of it: one column into the
    other, only where a value exists, with no literal anywhere in it."""
    module = _load_migration()
    executed: list[str] = []

    class _Bind:
        def execute(self, statement, *args):
            executed.append(re.sub(r"\s+", " ", str(statement)).strip())

            class _Result:
                rowcount = 20

            return _Result()

    with patch("alembic.op.get_bind", return_value=_Bind()):
        assert module._backfill() == 20

    assert executed == [
        f"UPDATE card_prints SET {NEW_COLUMN} = {OLD_COLUMN} "
        f"WHERE {OLD_COLUMN} IS NOT NULL"
    ]
    statement = executed[0]
    assert "'base'" not in statement
    assert "coalesce" not in statement.lower()


def test_the_upgrade_reports_how_many_values_it_copied():
    module = _load_migration()
    body = MIGRATION_PATH.read_text(encoding="utf-8").split("def upgrade()")[1]

    assert "copied = _backfill()" in body
    assert "copied" in body.split("print(")[1]


# --- the widened format check ----------------------------------------------


def test_the_new_format_check_admits_exactly_base_p_and_r():
    module, calls = _run("upgrade")
    emitted = next(
        c for c in calls
        if c[0] == "create_check_constraint" and c[1] == NEW_FORMAT_CHECK
    )
    condition = emitted[2]

    assert f"{NEW_COLUMN} IS NULL" in condition
    assert f"{NEW_COLUMN} = 'base'" in condition
    assert f"substr({NEW_COLUMN}, 1, 1) IN ('p', 'r')" in condition
    # No leading zero, digits only - unchanged from the p-only rule.
    assert f"substr({NEW_COLUMN}, 2, 1) <> '0'" in condition
    assert f"trim(substr({NEW_COLUMN}, 2), '0123456789') = ''" in condition
    # A closed set, not "any letter".
    assert "IN ('p', 'r', " not in condition


def test_the_new_format_check_matches_the_model_exactly():
    from app.models import CardPrint

    module, calls = _run("upgrade")
    emitted = next(
        c for c in calls
        if c[0] == "create_check_constraint" and c[1] == NEW_FORMAT_CHECK
    )

    model_check = next(
        c for c in CardPrint.__table__.constraints
        if getattr(c, "name", None) == NEW_FORMAT_CHECK
    )
    assert emitted[2] == str(model_check.sqltext)


def test_the_new_vocabulary_is_a_superset_of_the_one_being_copied_from():
    """Why the backfill cannot fail the check installed above it: every shape
    the legacy column admits - NULL, 'base', 'p<N>' - the new one admits too."""
    module = _load_migration()

    new_rule = module.NEW_FORMAT_CHECK_SQL.replace(NEW_COLUMN, "X")
    old_rule = module.OLD_FORMAT_CHECK_SQL.replace(OLD_COLUMN, "X")

    # Identical rule, except that the leading letter set is widened.
    assert new_rule.replace("IN ('p', 'r')", "= 'p'") == old_rule


def test_the_old_format_check_text_is_preserved_verbatim():
    """The legacy CHECK stays in force through the expand phase, so what this
    migration writes down about it must be what c2f7b48a91d6 actually wrote."""
    module = _load_migration()
    original = (VERSIONS_DIR / "c2f7b48a91d6_add_official_artwork_variant.py").read_text(
        encoding="utf-8"
    )

    def normalise(sql: str) -> str:
        return re.sub(r"\s+", " ", sql).strip()

    original_sql = normalise(
        "".join(re.findall(r'"([^"]*)"', original.split("VARIANT_FORMAT_CHECK = (")[1]
                           .split(")\nVARIANT_FORMAT_CHECK_NAME")[0]))
    )
    assert normalise(module.OLD_FORMAT_CHECK_SQL) == original_sql


# --- the downgrade ---------------------------------------------------------


def test_downgrade_removes_only_what_the_upgrade_added():
    module, up = _run("upgrade")
    _, down = _run("downgrade")

    assert [c[0] for c in down] == ["drop_constraint", "drop_column"]
    assert [c[1] for c in down] == [NEW_FORMAT_CHECK, NEW_COLUMN]
    # Nothing else is disturbed: the identity index and the verified check
    # were never dropped on the way up, so they are not recreated here.
    assert [c for c in down if c[0] in ("create_index", "create_check_constraint")] == []


def test_the_downgrade_preflight_refuses_rather_than_repairing():
    """It must abort, and it must not contain a repair for what it found."""
    module = _load_migration()
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    preflight = source.split("def _preflight_downgrade")[1].split("def upgrade")[0]
    assert "RuntimeError" in preflight
    assert "DOWNGRADE ABORTED" in preflight
    for forbidden in ("UPDATE ", "DELETE ", "INSERT "):
        assert forbidden not in preflight.upper().replace("DOWNGRADE ABORTED", "")


def test_downgrade_runs_its_preflight_before_any_ddl():
    """A refusal must leave the schema untouched, so the preflight cannot be
    allowed to run after the first drop."""
    module = _load_migration()
    body = MIGRATION_PATH.read_text(encoding="utf-8").split("def downgrade()")[1]

    assert body.index("_preflight_downgrade()") < body.index("op.drop_constraint")
    assert body.index("_preflight_downgrade()") < body.index("op.drop_column")


def test_downgrade_aborts_when_the_columns_disagree():
    """rN is the case that matters - the legacy column has no spelling for it,
    so dropping the new column would destroy the value."""
    module = _load_migration()

    class _Bind:
        def execute(self, statement, *args):
            class _Result:
                def scalar_one(inner):
                    return 2

                def all(inner):
                    return [(41, None, "r1"), (42, "base", "r2")]

            return _Result()

    with patch("alembic.op.get_bind", return_value=_Bind()):
        try:
            module._preflight_downgrade()
        except RuntimeError as exc:
            message = str(exc)
        else:
            raise AssertionError("expected the preflight to refuse diverged data")

    assert "DOWNGRADE ABORTED" in message
    assert "2 card_prints row(s)" in message
    assert "id=41" in message and "id=42" in message
    assert "would merge distinct printings" in message


def test_downgrade_preflight_passes_when_the_copy_is_still_faithful():
    module = _load_migration()

    class _Bind:
        def execute(self, statement, *args):
            class _Result:
                def scalar_one(inner):
                    return 0

                def all(inner):
                    return []

            return _Result()

    with patch("alembic.op.get_bind", return_value=_Bind()):
        module._preflight_downgrade()  # must not raise
