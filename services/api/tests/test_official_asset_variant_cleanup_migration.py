"""Structural coverage for a9f31c7d5b64, the CONTRACT half of the release.

f2e6b3a71c85 left both variant columns in place with identity still enforced
on the legacy one. This revision moves the verified CHECK and the exact-print
identity index onto official_asset_variant and drops
official_artwork_variant - and must be able to say, without a database, that:

  * it refuses before emitting any DDL unless the copy is still faithful,
    every active+verified print carries the new value, and the final key is
    already unique;
  * the check and index it installs are the ones the ORM model declares, with
    the same name, predicate and column order;
  * the old column is dropped last, after nothing names it any more;
  * its downgrade restores the *dual-column* state rather than the pre-expand
    schema, and refuses rN data rather than coercing it.

Live-engine behaviour is in test_asset_variant_release_states_postgres.
"""

import importlib.util
import re
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from app.models import CardPrint

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
MIGRATION_PATH = VERSIONS_DIR / "a9f31c7d5b64_contract_official_asset_variant.py"

OLD_COLUMN = "official_artwork_variant"
NEW_COLUMN = "official_asset_variant"

IDENTITY_INDEX = "uq_card_prints_active_verified_identity"
VERIFIED_CHECK = "ck_card_prints_verified_requires_fields"
OLD_FORMAT_CHECK = "ck_card_prints_official_artwork_variant_format"
NEW_FORMAT_CHECK = "ck_card_prints_official_asset_variant_format"

IDENTITY = ("canonical_card_id", "language", "release_product_id")


def _load_migration():
    spec = importlib.util.spec_from_file_location("asset_variant_cleanup", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _CountingBind:
    """A bind that answers every count with 0 and every listing with nothing -
    i.e. a database on which all three preflight conditions hold."""

    def __init__(self, scalar=0, rows=()):
        self.scalar = scalar
        self.rows = list(rows)
        self.statements: list[str] = []

    def execute(self, statement, *args):
        self.statements.append(re.sub(r"\s+", " ", str(statement)).strip())
        outer = self

        class _Result:
            rowcount = 20

            def scalar_one(inner):
                return outer.scalar

            def all(inner):
                return outer.rows

        return _Result()


def _run(direction: str, *, skip_preflight: bool = True):
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
        patch("alembic.op.create_check_constraint",
              side_effect=lambda name, table, condition, **kw: calls.append(
                  ("create_check_constraint", name, condition))),
        patch("alembic.op.create_index",
              side_effect=lambda name, table, columns, **kw: calls.append(
                  ("create_index", name, tuple(columns), str(kw.get("postgresql_where")),
                   str(kw.get("sqlite_where")), kw.get("unique")))),
        patch("alembic.op.get_bind", return_value=_CountingBind()),
    ]
    if skip_preflight:
        patches.append(patch.object(module, "_preflight_upgrade"))
        patches.append(patch.object(module, "_preflight_downgrade"))

    with ExitStack() as stack:
        for patcher in patches:
            stack.enter_context(patcher)
        getattr(module, direction)()

    return module, calls


# --- placement in history --------------------------------------------------


def test_the_cleanup_follows_the_print_metadata_migration():
    module = _load_migration()

    assert module.revision == "a9f31c7d5b64"
    assert module.down_revision == "b8d5f1c40e73"


def test_the_metadata_migration_still_sits_on_the_expand_migration():
    """The order the release depends on: expand, then metadata, then contract."""
    metadata = (VERSIONS_DIR / "b8d5f1c40e73_add_print_official_metadata.py").read_text(
        encoding="utf-8"
    )

    assert re.search(r"^revision: str = 'b8d5f1c40e73'", metadata, re.M)
    assert re.search(r"^down_revision: [^=]*= 'f2e6b3a71c85'", metadata, re.M)

    # And it is still metadata-only. Its docstring names the variant columns
    # to say it leaves them alone, so the check is on what it *does*: four
    # added columns, none of them a variant column, and no other DDL.
    spec = importlib.util.spec_from_file_location(
        "print_metadata_migration",
        VERSIONS_DIR / "b8d5f1c40e73_add_print_official_metadata.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert [name for name, _ in module.COLUMNS] == [
        "official_rarity", "official_block_icon", "official_name", "official_effect_text",
    ]
    body = metadata.split("def upgrade()")[1].split("def downgrade()")[0]
    assert body.count("op.add_column") == 1  # one call, over the four columns
    assert "op.drop_column" not in body
    # Neither direction touches an index, a constraint or an existing column.
    for forbidden in ("op.create_index", "op.drop_index", "op.alter_column",
                      "op.drop_constraint", "op.create_check_constraint"):
        assert forbidden not in metadata


# --- the upgrade -----------------------------------------------------------


def test_the_upgrade_moves_identity_then_drops_the_legacy_column():
    module, calls = _run("upgrade")

    assert [c[0] for c in calls] == [
        "drop_constraint",   # verified check, naming the legacy column
        "drop_index",        # identity index, indexing the legacy column
        "drop_constraint",   # legacy format check
        "create_check_constraint",
        "create_index",
        "drop_column",       # legacy column, last, once nothing names it
    ]
    assert [c[1] for c in calls] == [
        VERIFIED_CHECK, IDENTITY_INDEX, OLD_FORMAT_CHECK,
        VERIFIED_CHECK, IDENTITY_INDEX, OLD_COLUMN,
    ]


def test_the_upgrade_never_touches_the_new_format_check_or_any_value():
    module, calls = _run("upgrade")
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    upgrade_body = source.split("def upgrade()")[1].split("def downgrade()")[0]

    assert NEW_FORMAT_CHECK not in str(calls)
    for forbidden in ("UPDATE card_prints", "INSERT INTO", "DELETE FROM"):
        assert forbidden not in upgrade_body


def test_the_identity_index_keeps_its_name_columns_and_predicate():
    module, calls = _run("upgrade")
    index = next(c for c in calls if c[0] == "create_index")

    assert index[1] == IDENTITY_INDEX
    assert index[2] == IDENTITY + (NEW_COLUMN,)
    assert index[3] == "is_active = true AND verification_status = 'verified'"
    assert index[4] == "is_active = 1 AND verification_status = 'verified'"
    assert index[5] is True


def test_the_index_matches_the_model_exactly():
    """The migration and the ORM must not be able to disagree about identity."""
    module, calls = _run("upgrade")
    index = next(c for c in calls if c[0] == "create_index")

    model_index = next(
        i for i in CardPrint.__table__.indexes if i.name == IDENTITY_INDEX
    )
    assert tuple(c.name for c in model_index.columns) == index[2]


def test_the_verified_check_only_changes_the_columns_spelling():
    module, calls = _run("upgrade")

    new = module._verified_check(NEW_COLUMN)
    old = module._verified_check(OLD_COLUMN)
    assert new.replace(NEW_COLUMN, OLD_COLUMN) == old

    for requirement in (
        "canonical_card_id IS NOT NULL",
        "release_product_id IS NOT NULL",
        f"{NEW_COLUMN} IS NOT NULL",
        "artwork_key IS NOT NULL",
    ):
        assert requirement in new
    # treatment stays optional and non-identity; release_product_code stays out.
    assert "treatment IS NOT NULL" not in new
    assert "release_product_code" not in new


def test_the_verified_check_matches_the_model_exactly():
    module, calls = _run("upgrade")
    emitted = next(
        c for c in calls
        if c[0] == "create_check_constraint" and c[1] == VERIFIED_CHECK
    )

    model_check = next(
        c for c in CardPrint.__table__.constraints
        if getattr(c, "name", None) == VERIFIED_CHECK
    )
    assert emitted[2] == str(model_check.sqltext)


def test_the_final_schema_has_no_trace_of_the_legacy_column():
    """What the ORM says the table is, after this migration: the legacy column
    is gone from the model, so it must be gone from the database too."""
    assert OLD_COLUMN not in CardPrint.__table__.columns
    assert NEW_COLUMN in CardPrint.__table__.columns
    assert not any(
        getattr(c, "name", None) == OLD_FORMAT_CHECK for c in CardPrint.__table__.constraints
    )


# --- the preflight ---------------------------------------------------------


def test_the_preflight_runs_before_any_ddl():
    body = MIGRATION_PATH.read_text(encoding="utf-8").split("def upgrade()")[1]

    assert body.index("_preflight_upgrade()") < body.index("op.drop_constraint")
    assert body.index("_preflight_upgrade()") < body.index("op.drop_column")


def test_the_preflight_refuses_rather_than_repairing():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    preflight = source.split("def _preflight_upgrade")[1].split("def _preflight_downgrade")[0]

    assert preflight.count("RuntimeError") == 3
    assert preflight.count("ABORTED") == 3
    for forbidden in ("UPDATE ", "DELETE ", "INSERT "):
        assert forbidden not in preflight.upper().replace("ABORTED", "")


def test_the_preflight_checks_all_three_conditions():
    module = _load_migration()
    bind = _CountingBind()

    with patch("alembic.op.get_bind", return_value=bind):
        module._preflight_upgrade()  # every count 0 - must not raise

    joined = " ".join(bind.statements)
    # 1. the copy is still faithful
    assert f"{NEW_COLUMN} IS DISTINCT FROM {OLD_COLUMN}" in joined
    # 2. every active+verified row carries the new value
    assert f"is_active = true AND verification_status = 'verified' AND {NEW_COLUMN} IS NULL" \
        in joined
    # 3. the final key is unique over the population the index covers
    assert f"canonical_card_id, language, release_product_id, {NEW_COLUMN}" in joined
    assert "HAVING count(*) > 1" in joined


def test_the_preflight_aborts_on_a_divergence_between_the_columns():
    module = _load_migration()
    bind = _CountingBind(scalar=2, rows=[(41, "base", "p1"), (42, "p1", None)])

    with patch("alembic.op.get_bind", return_value=bind):
        try:
            module._preflight_upgrade()
        except RuntimeError as exc:
            message = str(exc)
        else:
            raise AssertionError("expected the preflight to refuse diverged columns")

    assert "ABORTED" in message
    assert "2 card_prints row(s) disagree" in message
    assert "id=41" in message and "id=42" in message


def test_the_preflight_aborts_when_a_verified_print_has_no_asset_variant():
    module = _load_migration()
    calls = {"n": 0}

    class _Bind(_CountingBind):
        def execute(self, statement, *args):
            calls["n"] += 1
            sql = re.sub(r"\s+", " ", str(statement))
            # The first condition passes; the second finds two NULL rows.
            self.scalar = 0 if "IS DISTINCT FROM" in sql else 2
            self.rows = [(7,), (9,)]
            return super().execute(statement, *args)

    with patch("alembic.op.get_bind", return_value=_Bind()):
        try:
            module._preflight_upgrade()
        except RuntimeError as exc:
            message = str(exc)
        else:
            raise AssertionError("expected the preflight to refuse a NULL asset variant")

    assert "ABORTED" in message
    assert f"2 active+verified card_prints row(s) have no {NEW_COLUMN}" in message
    assert "Nothing will be guessed" in message
    assert "id=7" in message and "id=9" in message


def test_the_preflight_aborts_on_a_duplicate_final_identity():
    module = _load_migration()

    class _Bind(_CountingBind):
        def execute(self, statement, *args):
            sql = re.sub(r"\s+", " ", str(statement))
            duplicate_query = "HAVING count(*) > 1" in sql
            self.scalar = 3 if duplicate_query else 0
            self.rows = [(1, "jp", 5, "base", 2)] if duplicate_query else []
            return super().execute(statement, *args)

    with patch("alembic.op.get_bind", return_value=_Bind()):
        try:
            module._preflight_upgrade()
        except RuntimeError as exc:
            message = str(exc)
        else:
            raise AssertionError("expected the preflight to refuse duplicate identities")

    assert "ABORTED" in message
    assert "3 duplicate identity group(s)" in message
    assert "canonical_card=1 language=jp release_product=5" in message


# --- the downgrade ---------------------------------------------------------


def test_the_downgrade_restores_the_dual_column_state():
    """Not the pre-expand schema: official_asset_variant and its format check
    stay, because f2e6b3a71c85's own downgrade is what removes them."""
    module, calls = _run("downgrade")

    assert [c[0] for c in calls] == [
        "add_column",              # the legacy column back
        "create_check_constraint",  # its legacy format check
        "drop_index",
        "drop_constraint",
        "create_check_constraint",  # verified check, naming the legacy column
        "create_index",             # identity back on the legacy column
    ]
    assert calls[0] == ("add_column", OLD_COLUMN, "VARCHAR(16)", True)
    assert calls[1][1] == OLD_FORMAT_CHECK
    assert [c for c in calls if c[0] == "drop_column"] == []
    assert NEW_FORMAT_CHECK not in str(calls)

    index = next(c for c in calls if c[0] == "create_index")
    assert index[1] == IDENTITY_INDEX
    assert index[2] == IDENTITY + (OLD_COLUMN,)
    assert index[3] == "is_active = true AND verification_status = 'verified'"


def test_the_downgrade_copies_back_before_installing_the_legacy_check():
    body = MIGRATION_PATH.read_text(encoding="utf-8").split("def downgrade()")[1]

    assert body.index("op.add_column") < body.index("UPDATE card_prints")
    assert body.index("UPDATE card_prints") < body.index("OLD_FORMAT_CHECK_SQL")
    assert "SET {OLD_COLUMN} = {NEW_COLUMN}" in body
    # Copied, never invented: no literal variant value anywhere in the copy.
    assert "'base'" not in body
    assert "coalesce" not in body.lower()


def test_the_legacy_format_check_text_is_preserved_verbatim():
    """The downgrade must restore what c2f7b48a91d6 actually wrote, not a
    paraphrase of it."""
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


def test_the_downgrade_preflight_runs_before_any_ddl():
    body = MIGRATION_PATH.read_text(encoding="utf-8").split("def downgrade()")[1]

    assert body.index("_preflight_downgrade()") < body.index("op.add_column")


def test_the_downgrade_aborts_on_rn_data():
    module = _load_migration()
    bind = _CountingBind(scalar=2, rows=[(41, "r1"), (42, "r2")])

    with patch("alembic.op.get_bind", return_value=bind):
        try:
            module._preflight_downgrade()
        except RuntimeError as exc:
            message = str(exc)
        else:
            raise AssertionError("expected the downgrade preflight to refuse rN data")

    assert "DOWNGRADE ABORTED" in message
    assert "2 card_prints row(s) carry an rN" in message
    assert "would merge distinct printings" in message
    assert "id=41" in message and "id=42" in message


def test_the_downgrade_aborts_when_a_verified_print_has_no_asset_variant():
    module = _load_migration()

    class _Bind(_CountingBind):
        def execute(self, statement, *args):
            sql = re.sub(r"\s+", " ", str(statement))
            self.scalar = 0 if "LIKE 'r%'" in sql else 1
            self.rows = [(13,)]
            return super().execute(statement, *args)

    with patch("alembic.op.get_bind", return_value=_Bind()):
        try:
            module._preflight_downgrade()
        except RuntimeError as exc:
            message = str(exc)
        else:
            raise AssertionError("expected the downgrade preflight to refuse a NULL variant")

    assert "DOWNGRADE ABORTED" in message
    assert f"have no {NEW_COLUMN} to copy back" in message
    assert "id=13" in message


def test_the_downgrade_preflight_passes_on_base_and_pn_data():
    module = _load_migration()

    with patch("alembic.op.get_bind", return_value=_CountingBind()):
        module._preflight_downgrade()  # must not raise
