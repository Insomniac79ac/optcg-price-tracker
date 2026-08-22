"""Structural coverage for c2f7b48a91d6_add_official_artwork_variant, plus the
parity check that keeps its frozen parser copy honest.

The migration carries its own copy of the parsing rule rather than importing
app.services.official_artwork_variant, because a migration must replay
identically forever while application code is free to evolve. The copy is
only safe if it cannot drift silently - which is what
test_migration_parser_matches_the_application_parser is for."""

import importlib.util
import re
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa

from app.services.official_artwork_variant import parse_official_artwork_variant

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
MIGRATION_PATH = VERSIONS_DIR / "c2f7b48a91d6_add_official_artwork_variant.py"

CARD_LIST = "https://www.onepiece-cardgame.com/images/cardlist/card"


def _load_migration():
    spec = importlib.util.spec_from_file_location("artwork_variant_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade():
    module = _load_migration()
    captured = {"add_column": [], "create_check_constraint": [], "create_index": [], "op_calls": []}

    def fake_add_column(table_name, column, **kwargs):
        captured["add_column"].append({"table_name": table_name, "column": column})

    def fake_create_check_constraint(name, table_name, condition, **kwargs):
        captured["create_check_constraint"].append(
            {"name": name, "table_name": table_name, "condition": condition}
        )

    def fake_create_index(name, table_name, columns, **kwargs):
        captured["create_index"].append({"name": name, "table_name": table_name})

    with (
        patch("alembic.op.add_column", side_effect=fake_add_column),
        patch("alembic.op.create_check_constraint", side_effect=fake_create_check_constraint),
        patch("alembic.op.create_index", side_effect=fake_create_index),
        patch.object(module, "_backfill_official_artwork_variant"),
    ):
        module.upgrade()

    return captured


def test_revision_follows_the_release_product_foundation():
    module = _load_migration()

    assert module.revision == "c2f7b48a91d6"
    assert module.down_revision == "b6e3a9c15d47"


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
    assert heads == ["c2f7b48a91d6"], f"expected a single head, found {heads}"


def test_adds_one_nullable_string16_column():
    captured = _run_upgrade()

    assert len(captured["add_column"]) == 1
    added = captured["add_column"][0]
    assert added["table_name"] == "card_prints"
    assert added["column"].name == "official_artwork_variant"
    assert added["column"].nullable is True
    assert isinstance(added["column"].type, sa.String)
    assert added["column"].type.length == 16


def test_adds_the_format_check_constraint():
    captured = _run_upgrade()

    assert len(captured["create_check_constraint"]) == 1
    constraint = captured["create_check_constraint"][0]
    assert constraint["name"] == "ck_card_prints_official_artwork_variant_format"
    assert constraint["table_name"] == "card_prints"

    condition = constraint["condition"]
    assert "official_artwork_variant IS NULL" in condition
    assert "= 'base'" in condition
    # No regex: Postgres' `~` and sqlite's GLOB share no spelling, so the
    # constraint is expressed with substr/length/trim instead.
    assert "~" not in condition
    assert "GLOB" not in condition.upper()
    assert "SIMILAR TO" not in condition.upper()
    assert "trim(substr(official_artwork_variant, 2), '0123456789') = ''" in condition


def test_creates_no_index_and_touches_no_other_column():
    captured = _run_upgrade()
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert captured["create_index"] == []
    for forbidden in (
        "uq_card_prints_active_verified_identity",
        "drop_index",
        "drop_constraint('ck_card_prints_verified_requires_fields'",
        "alter_column",
    ):
        assert forbidden not in source


def test_backfill_reads_only_the_asset_address_and_writes_only_the_variant():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    backfill = source.split("def _backfill_official_artwork_variant")[1].split("def downgrade")[0]
    # Drop the docstring - it names the untouched fields in prose, and this
    # assertion is about the executable statements.
    code = backfill.split('"""')[2]

    assert "SET official_artwork_variant = :variant" in code
    assert "cp.image_url" in code and "cc.card_code" in code
    # Never derived from treatment, artwork_key or a source mapping.
    for forbidden in ("treatment", "artwork_key", "source_card_mapping", "release_product"):
        assert forbidden not in code.replace("official_artwork_variant", "")


def test_downgrade_drops_only_what_it_added():
    module = _load_migration()
    dropped = {"column": [], "constraint": [], "table": [], "index": []}

    with (
        patch(
            "alembic.op.drop_column", side_effect=lambda t, c, **k: dropped["column"].append((t, c))
        ),
        patch(
            "alembic.op.drop_constraint",
            side_effect=lambda n, t, **k: dropped["constraint"].append((n, t)),
        ),
        patch("alembic.op.drop_table", side_effect=lambda n, **k: dropped["table"].append(n)),
        patch("alembic.op.drop_index", side_effect=lambda n, **k: dropped["index"].append(n)),
    ):
        module.downgrade()

    assert dropped["column"] == [("card_prints", "official_artwork_variant")]
    assert dropped["constraint"] == [
        ("ck_card_prints_official_artwork_variant_format", "card_prints")
    ]
    # ReleaseProduct infrastructure from the previous phase is untouched.
    assert dropped["table"] == []
    assert dropped["index"] == []


PARITY_CASES = [
    (f"{CARD_LIST}/OP01-001.png?260630", "OP01-001"),
    (f"{CARD_LIST}/OP01-001_p2.png?260630", "OP01-001"),
    (f"{CARD_LIST}/OP04-001_p1.png", "OP04-001"),
    (f"{CARD_LIST}/OP01-001_p12.png", "OP01-001"),
    (f"{CARD_LIST}/OP01-001_p101.png", "OP01-001"),
    ("OP03-013_p1.png", "OP03-013"),
    (f"{CARD_LIST}/OP01-001_p2.png#fragment", "OP01-001"),
    (f"{CARD_LIST}/OP01-002_p1.png", "OP01-001"),
    (f"{CARD_LIST}/OP01-0011.png", "OP01-001"),
    (f"{CARD_LIST}/OP01-001_p.png", "OP01-001"),
    (f"{CARD_LIST}/OP01-001_px.png", "OP01-001"),
    (f"{CARD_LIST}/OP01-001_p1a.png", "OP01-001"),
    (f"{CARD_LIST}/OP01-001_P1.png", "OP01-001"),
    (f"{CARD_LIST}/OP01-001-p1.png", "OP01-001"),
    (f"{CARD_LIST}/OP01-001_p0.png", "OP01-001"),
    (f"{CARD_LIST}/OP01-001_p01.png", "OP01-001"),
    (f"{CARD_LIST}/OP01-001_p-1.png", "OP01-001"),
    (f"{CARD_LIST}/OP01-001_p١.png", "OP01-001"),
    (f"{CARD_LIST}/OP01-001.webp", "OP01-001"),
    (f"{CARD_LIST}/OP01-001", "OP01-001"),
    (None, "OP01-001"),
    ("", "OP01-001"),
    (f"{CARD_LIST}/OP01-001.png", None),
    (f"{CARD_LIST}/OP01-001.png", ""),
]


def test_migration_parser_matches_the_application_parser():
    """The migration's frozen copy must agree with app.services case for
    case - otherwise a replayed migration would write different evidence
    than the application's own contract."""
    module = _load_migration()

    for image_url, card_code in PARITY_CASES:
        assert module._parse_variant(image_url, card_code) == parse_official_artwork_variant(
            image_url, card_code
        ), f"disagreement on {image_url!r} / {card_code!r}"
