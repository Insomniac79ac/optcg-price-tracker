"""Structural coverage for f2e6b3a71c85_generalize_official_asset_variant.

What this migration must be able to say about itself without a database:
it renames rather than drops-and-adds (so no value can be lost), it keeps the
identity index name/columns/predicate and the verified requirements exactly as
d4b17c9e2a83 left them, it widens the format check to the r family and nothing
else, and its downgrade is the exact inverse of every step - with a preflight
that refuses rN data rather than coercing it.

The live-engine behaviour is in test_official_asset_variant_migration_postgres.
"""

import importlib.util
import re
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from app.models import CardPrint

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
MIGRATION_PATH = VERSIONS_DIR / "f2e6b3a71c85_generalize_official_asset_variant.py"

OLD_COLUMN = "official_artwork_variant"
NEW_COLUMN = "official_asset_variant"


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
        patch("alembic.op.drop_index",
              side_effect=lambda name, **kw: calls.append(("drop_index", name))),
        patch("alembic.op.drop_constraint",
              side_effect=lambda name, table, **kw: calls.append(("drop_constraint", name))),
        patch("alembic.op.alter_column",
              side_effect=lambda table, name, **kw: calls.append(
                  ("alter_column", name, kw.get("new_column_name"), kw.get("existing_nullable")))),
        patch("alembic.op.create_check_constraint",
              side_effect=lambda name, table, condition, **kw: calls.append(
                  ("create_check_constraint", name, condition))),
        patch("alembic.op.create_index",
              side_effect=lambda name, table, columns, **kw: calls.append(
                  ("create_index", name, tuple(columns), str(kw.get("postgresql_where"))))),
        patch.object(module, "_report"),
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


# --- the rename ------------------------------------------------------------


def test_upgrade_renames_the_column_and_never_adds_or_drops_one():
    """A drop-and-add would silently discard every stored variant. Only
    alter_column with new_column_name can carry the values across."""
    module, calls = _run("upgrade")

    renames = [c for c in calls if c[0] == "alter_column"]
    assert renames == [("alter_column", OLD_COLUMN, NEW_COLUMN, True)]

    source = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "op.add_column" not in source
    assert "op.drop_column" not in source
    # ...and nothing writes to card_prints at all.
    for forbidden in ("UPDATE card_prints", "INSERT INTO", "DELETE FROM"):
        assert forbidden not in source


def test_upgrade_releases_then_reinstates_everything_that_names_the_column():
    module, calls = _run("upgrade")
    order = [c[0] for c in calls]

    assert order == [
        "drop_index", "drop_constraint", "drop_constraint",
        "alter_column",
        "create_check_constraint", "create_check_constraint", "create_index",
    ]
    dropped = [c[1] for c in calls if c[0] in ("drop_index", "drop_constraint")]
    assert dropped == [
        "uq_card_prints_active_verified_identity",
        "ck_card_prints_verified_requires_fields",
        "ck_card_prints_official_artwork_variant_format",
    ]


# --- the identity, kept exactly as it was ----------------------------------


def test_the_identity_index_keeps_its_name_columns_and_predicate():
    module, calls = _run("upgrade")
    index = next(c for c in calls if c[0] == "create_index")

    assert index[1] == "uq_card_prints_active_verified_identity"
    assert index[2] == (
        "canonical_card_id", "language", "release_product_id", NEW_COLUMN
    )
    assert index[3] == "is_active = true AND verification_status = 'verified'"


def test_the_index_matches_the_model_exactly():
    """The migration and the ORM must not be able to disagree about identity."""
    module, calls = _run("upgrade")
    index = next(c for c in calls if c[0] == "create_index")

    model_index = next(
        i for i in CardPrint.__table__.indexes
        if i.name == "uq_card_prints_active_verified_identity"
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
        if c[0] == "create_check_constraint" and c[1] == "ck_card_prints_verified_requires_fields"
    )

    model_check = next(
        c for c in CardPrint.__table__.constraints
        if getattr(c, "name", None) == "ck_card_prints_verified_requires_fields"
    )
    assert emitted[2] == str(model_check.sqltext)


# --- the widened format check ----------------------------------------------


def test_the_format_check_is_renamed_and_admits_exactly_p_and_r():
    module, calls = _run("upgrade")
    emitted = next(
        c for c in calls
        if c[0] == "create_check_constraint"
        and c[1] == "ck_card_prints_official_asset_variant_format"
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


def test_the_format_check_matches_the_model_exactly():
    module, calls = _run("upgrade")
    emitted = next(
        c for c in calls
        if c[0] == "create_check_constraint"
        and c[1] == "ck_card_prints_official_asset_variant_format"
    )

    model_check = next(
        c for c in CardPrint.__table__.constraints
        if getattr(c, "name", None) == "ck_card_prints_official_asset_variant_format"
    )
    assert emitted[2] == str(model_check.sqltext)


def test_the_old_format_check_text_is_preserved_verbatim_for_the_downgrade():
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


# --- the downgrade ---------------------------------------------------------


def test_downgrade_is_the_exact_inverse_of_the_upgrade():
    module, up = _run("upgrade")
    _, down = _run("downgrade")

    assert [c[0] for c in down] == [c[0] for c in up]
    assert [c[1] for c in down if c[0] == "alter_column"] == [NEW_COLUMN]
    assert [c[2] for c in down if c[0] == "alter_column"] == [OLD_COLUMN]

    dropped = [c[1] for c in down if c[0] in ("drop_index", "drop_constraint")]
    assert dropped == [
        "uq_card_prints_active_verified_identity",
        "ck_card_prints_verified_requires_fields",
        "ck_card_prints_official_asset_variant_format",
    ]
    created = [c[1] for c in down if c[0] in ("create_check_constraint", "create_index")]
    assert created == [
        "ck_card_prints_official_artwork_variant_format",
        "ck_card_prints_verified_requires_fields",
        "uq_card_prints_active_verified_identity",
    ]
    index = next(c for c in down if c[0] == "create_index")
    assert index[2] == ("canonical_card_id", "language", "release_product_id", OLD_COLUMN)


def test_the_downgrade_preflight_refuses_rn_rather_than_rewriting_it():
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

    assert body.index("_preflight_downgrade()") < body.index("op.drop_index")


def test_downgrade_aborts_when_the_data_carries_an_rn_variant():
    module = _load_migration()

    class _Bind:
        def execute(self, statement, *args):
            sql = str(statement)

            class _Result:
                def scalar_one(inner):
                    return 2

                def all(inner):
                    return [(41, "r1"), (42, "r2")]

            return _Result()

    with patch("alembic.op.get_bind", return_value=_Bind()):
        try:
            module._preflight_downgrade()
        except RuntimeError as exc:
            message = str(exc)
        else:
            raise AssertionError("expected the preflight to refuse rN data")

    assert "DOWNGRADE ABORTED" in message
    assert "2 card_prints row(s) carry an rN" in message
    assert "id=41" in message and "id=42" in message
    assert "would merge distinct printings" in message


def test_downgrade_preflight_passes_when_no_rn_variant_exists():
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
