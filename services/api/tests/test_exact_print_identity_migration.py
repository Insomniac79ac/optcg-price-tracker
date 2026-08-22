"""Structural coverage for d4b17c9e2a83_activate_exact_print_identity.

Unlike the earlier additive migrations this one activates a STRONGER
contract, so what matters structurally is: it replaces exactly the identity
pieces and nothing else, it does the steps in an order that cannot leave a
nullable treatment under an index that still contains it, and both directions
refuse rather than coerce."""

import importlib.util
import re
from pathlib import Path
from unittest.mock import patch

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
MIGRATION_PATH = VERSIONS_DIR / "d4b17c9e2a83_activate_exact_print_identity.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("identity_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _capture(direction: str):
    module = _load_migration()
    calls: list[tuple] = []

    def record(name):
        def fake(*args, **kwargs):
            calls.append((name, args, kwargs))
        return fake

    preflight = "_preflight_upgrade" if direction == "upgrade" else "_preflight_downgrade"
    with (
        patch("alembic.op.drop_constraint", side_effect=record("drop_constraint")),
        patch("alembic.op.create_check_constraint", side_effect=record("create_check_constraint")),
        patch("alembic.op.drop_index", side_effect=record("drop_index")),
        patch("alembic.op.create_index", side_effect=record("create_index")),
        patch("alembic.op.alter_column", side_effect=record("alter_column")),
        patch.object(module, preflight),
    ):
        getattr(module, direction)()

    return module, calls


def test_revision_follows_the_artwork_variant_phase():
    module = _load_migration()

    assert module.revision == "d4b17c9e2a83"
    assert module.down_revision == "c2f7b48a91d6"


def test_migration_history_has_exactly_one_head():
    revisions, downs = {}, set()
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
    assert len(heads) == 1, f"expected a single head, found {heads}"
    assert "d4b17c9e2a83" in revisions
    assert heads == ["d4b17c9e2a83"] or "d4b17c9e2a83" in downs


def test_upgrade_preflights_before_any_ddl():
    """The refusal has to come first, or a rejected database is left with
    half its identity contract removed."""
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    body = source.split("def upgrade()")[1].split("def _backfill")[0].split("def downgrade")[0]

    preflight_at = body.index("_preflight_upgrade()")
    for ddl in ("op.drop_constraint", "op.drop_index", "op.alter_column", "op.create_index"):
        assert preflight_at < body.index(ddl), f"{ddl} runs before the preflight"


def test_upgrade_order_never_leaves_nullable_treatment_under_the_old_index():
    _, calls = _capture("upgrade")
    names = [name for name, _, _ in calls]

    assert names == [
        "drop_constraint",   # old verified check names treatment
        "drop_index",        # old identity index contains treatment
        "alter_column",      # only now can treatment go nullable
        "create_check_constraint",
        "create_index",
    ]


def test_upgrade_replaces_only_the_identity_pieces():
    module, calls = _capture("upgrade")

    dropped_constraints = [args[0] for name, args, _ in calls if name == "drop_constraint"]
    dropped_indexes = [args[0] for name, args, _ in calls if name == "drop_index"]
    altered = [(args[1], kwargs.get("nullable")) for name, args, kwargs in calls
               if name == "alter_column"]

    assert dropped_constraints == ["ck_card_prints_verified_requires_fields"]
    assert dropped_indexes == ["uq_card_prints_active_verified_identity"]
    assert altered == [("treatment", True)]

    source = MIGRATION_PATH.read_text(encoding="utf-8")
    # Nothing else on the table, and no other table, is touched.
    for forbidden in (
        "drop_table",
        "add_column",
        "drop_column",
        "release_products'",
        "ck_card_prints_no_fake_release_product_code",
        "ck_card_prints_no_fake_artwork_key",
        "ck_card_prints_official_artwork_variant_format",
        "ck_card_prints_verification_status",
    ):
        assert f"op.{forbidden}" not in source and f"'{forbidden}'" not in source


def test_new_verified_check_requires_the_identity_fields_and_not_treatment():
    module = _load_migration()
    sql = module.NEW_VERIFIED_CHECK_SQL

    assert "release_product_id IS NOT NULL" in sql
    assert "official_artwork_variant IS NOT NULL" in sql
    assert "canonical_card_id IS NOT NULL" in sql
    assert "language IS NOT NULL" in sql
    # artwork_key stays required as evidence, not as identity.
    assert "artwork_key IS NOT NULL" in sql
    # treatment is never *required*; it only may not be a placeholder.
    assert "treatment IS NOT NULL" not in sql
    assert "treatment IS NULL OR" in sql
    # release_product_code must not be required - uncoded products exist.
    assert "release_product_code" not in sql


def test_new_index_keeps_its_name_and_drops_the_old_columns():
    module, calls = _capture("upgrade")
    name, args, kwargs = next(c for c in calls if c[0] == "create_index")

    assert args[0] == "uq_card_prints_active_verified_identity"
    assert args[1] == "card_prints"
    assert args[2] == [
        "canonical_card_id",
        "language",
        "release_product_id",
        "official_artwork_variant",
    ]
    assert kwargs["unique"] is True
    assert "is_active = true" in str(kwargs["postgresql_where"])
    assert "verification_status = 'verified'" in str(kwargs["postgresql_where"])
    for gone in ("treatment", "release_product_code", "artwork_key"):
        assert gone not in args[2]


def test_downgrade_restores_the_previous_definitions_exactly():
    module, calls = _capture("downgrade")
    names = [name for name, _, _ in calls]

    assert names == [
        "drop_index",
        "drop_constraint",
        "alter_column",
        "create_check_constraint",
        "create_index",
    ]

    altered = [(args[1], kwargs.get("nullable")) for name, args, kwargs in calls
               if name == "alter_column"]
    assert altered == [("treatment", False)]

    check = next(c for c in calls if c[0] == "create_check_constraint")
    assert check[1][2] == module.OLD_VERIFIED_CHECK_SQL
    index = next(c for c in calls if c[0] == "create_index")
    assert index[1][2] == module.OLD_IDENTITY_COLUMNS


def test_downgrade_preflights_before_any_ddl():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    body = source.split("def downgrade()")[1]

    preflight_at = body.index("_preflight_downgrade()")
    for ddl in ("op.drop_index", "op.drop_constraint", "op.alter_column"):
        assert preflight_at < body.index(ddl), f"{ddl} runs before the downgrade preflight"


def test_neither_direction_repairs_data():
    """Both preflights refuse; nothing here writes, deletes or coerces a row."""
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    executable = source.split('"""', 2)[2]  # drop the module docstring

    for forbidden in ("UPDATE card_prints", "DELETE FROM", "INSERT INTO", "coalesce("):
        assert forbidden.lower() not in executable.lower(), forbidden

    assert executable.count("raise RuntimeError") == 2
