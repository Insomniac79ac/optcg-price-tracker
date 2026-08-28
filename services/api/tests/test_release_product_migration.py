"""Verifies the b6e3a9c15d47_add_release_products migration declares the
expected tables/columns/constraints and stays a single Alembic head, without
needing a live Postgres - same op.*-patching technique as
test_canonical_cards_migration.py. The migration's data effects (seed +
backfill) are proven against a real database in
test_release_product_migration_postgres.py."""

import importlib.util
import re
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
MIGRATION_PATH = VERSIONS_DIR / "b6e3a9c15d47_add_release_products.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("release_products_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade():
    module = _load_migration()
    captured = {
        "create_table": [],
        "create_index": [],
        "add_column": [],
        "create_foreign_key": [],
    }

    def fake_create_table(name, *columns, **kwargs):
        captured["create_table"].append({"name": name, "columns": columns, "kwargs": kwargs})

    def fake_create_index(name, table_name, columns, **kwargs):
        captured["create_index"].append(
            {"name": name, "table_name": table_name, "columns": columns, "kwargs": kwargs}
        )

    def fake_add_column(table_name, column, **kwargs):
        captured["add_column"].append({"table_name": table_name, "column": column})

    def fake_create_foreign_key(name, source, referent, local_cols, remote_cols, **kwargs):
        captured["create_foreign_key"].append(
            {
                "name": name,
                "source": source,
                "referent": referent,
                "local_cols": local_cols,
                "remote_cols": remote_cols,
                "kwargs": kwargs,
            }
        )

    with (
        patch("alembic.op.create_table", side_effect=fake_create_table),
        patch("alembic.op.create_index", side_effect=fake_create_index),
        patch("alembic.op.add_column", side_effect=fake_add_column),
        patch("alembic.op.create_foreign_key", side_effect=fake_create_foreign_key),
        patch.object(module, "_seed_and_backfill"),
    ):
        module.upgrade()

    return captured


def _table(captured, name):
    return next(t for t in captured["create_table"] if t["name"] == name)


def _column_names(table):
    return [c.name for c in table["columns"] if isinstance(c, sa.Column)]


def _checks(table):
    return {
        c.name: str(c.sqltext)
        for c in table["columns"]
        if isinstance(c, sa.CheckConstraint)
    }


def test_revision_follows_the_previous_head():
    module = _load_migration()

    assert module.revision == "b6e3a9c15d47"
    assert module.down_revision == "a9c4e17b6d52"


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
    # in the chain either as that head or as an ancestor of it.
    assert len(heads) == 1, f"expected a single head, found {heads}"
    assert "b6e3a9c15d47" in revisions
    assert heads == ["b6e3a9c15d47"] or "b6e3a9c15d47" in downs


def test_release_products_table_columns():
    table = _table(_run_upgrade(), "release_products")

    assert set(_column_names(table)) == {
        "id",
        "source_catalogue",
        "official_code",
        "display_name",
        "first_seen_name",
        "source_series_id",
        "source_url",
        "verification_status",
        "created_at",
        "updated_at",
    }


def test_release_products_nullability_and_widths():
    table = _table(_run_upgrade(), "release_products")
    columns = {c.name: c for c in table["columns"] if isinstance(c, sa.Column)}

    assert columns["source_catalogue"].nullable is False
    assert columns["source_catalogue"].type.length == 16
    assert columns["official_code"].nullable is True
    assert columns["official_code"].type.length == 32
    assert columns["display_name"].nullable is False
    assert columns["display_name"].type.length == 255
    assert columns["first_seen_name"].nullable is False
    assert columns["source_series_id"].nullable is False
    assert columns["source_series_id"].type.length == 16
    assert columns["source_url"].nullable is False
    assert columns["source_url"].type.length == 1024
    assert columns["verification_status"].nullable is False


def test_release_products_check_constraints():
    checks = _checks(_table(_run_upgrade(), "release_products"))

    for name in (
        "ck_release_products_source_catalogue_not_blank",
        "ck_release_products_display_name_not_blank",
        "ck_release_products_first_seen_name_not_blank",
        "ck_release_products_source_series_id_not_blank",
        "ck_release_products_source_url_not_blank",
        "ck_release_products_official_code_not_blank",
        "ck_release_products_verification_status",
    ):
        assert name in checks

    assert "official_code IS NULL OR" in checks["ck_release_products_official_code_not_blank"]
    status = checks["ck_release_products_verification_status"]
    for value in ("verified", "unverified", "needs_review"):
        assert value in status


def test_official_code_has_no_shape_regex():
    """Real Bandai codes include composites such as OP14-EB04; a format
    check would reject them."""
    checks = _checks(_table(_run_upgrade(), "release_products"))

    joined = " ".join(checks.values()).lower()
    assert "~" not in joined
    assert "similar to" not in joined
    assert "like" not in joined


def test_official_code_is_unique_per_catalogue_and_not_globally():
    index = next(
        i
        for i in _run_upgrade()["create_index"]
        if i["name"] == "uq_release_products_catalogue_official_code"
    )

    assert index["table_name"] == "release_products"
    assert index["columns"] == ["source_catalogue", "official_code"]
    assert index["kwargs"]["unique"] is True
    assert "official_code IS NOT NULL" in str(index["kwargs"]["postgresql_where"])


def test_no_global_unique_on_official_code_or_names():
    captured = _run_upgrade()
    table = _table(captured, "release_products")

    uniques = [c for c in table["columns"] if isinstance(c, sa.UniqueConstraint)]
    assert uniques == []

    for index in captured["create_index"]:
        if index["table_name"] == "release_products" and index["kwargs"].get("unique"):
            assert index["columns"] == ["source_catalogue", "official_code"]


def test_release_product_aliases_table():
    captured = _run_upgrade()
    table = _table(captured, "release_product_aliases")

    assert set(_column_names(table)) == {
        "id",
        "product_id",
        "alias_name",
        "alias_kind",
        "source_url",
        "created_at",
    }

    checks = _checks(table)
    assert "ck_release_product_aliases_alias_kind" in checks
    assert "ck_release_product_aliases_alias_name_not_blank" in checks
    assert "ck_release_product_aliases_bandai_alias_requires_source" in checks
    for kind in ("bandai_official", "bandai_additional", "source_rendering"):
        assert kind in checks["ck_release_product_aliases_alias_kind"]

    # An unbound UniqueConstraint keeps its column names in _pending_colargs;
    # .columns only populates once it is attached to a Table. The real column
    # list is re-checked against a live schema in
    # test_release_product_migration_postgres.py.
    uniques = [c for c in table["columns"] if isinstance(c, sa.UniqueConstraint)]
    assert len(uniques) == 1
    assert uniques[0].name == "uq_release_product_aliases_identity"
    assert list(uniques[0]._pending_colargs) == ["product_id", "alias_kind", "alias_name"]

    fks = [c for c in table["columns"] if isinstance(c, sa.ForeignKeyConstraint)]
    assert len(fks) == 1
    assert fks[0].ondelete == "CASCADE"


def test_card_prints_gains_a_nullable_indexed_restrict_fk():
    captured = _run_upgrade()

    added = next(c for c in captured["add_column"] if c["table_name"] == "card_prints")
    assert added["column"].name == "release_product_id"
    assert added["column"].nullable is True

    index = next(
        i for i in captured["create_index"] if i["name"] == "ix_card_prints_release_product_id"
    )
    assert index["columns"] == ["release_product_id"]

    fk = next(
        f
        for f in captured["create_foreign_key"]
        if f["name"] == "fk_card_prints_release_product_id_release_products"
    )
    assert fk["source"] == "card_prints"
    assert fk["referent"] == "release_products"
    assert fk["local_cols"] == ["release_product_id"]
    assert fk["kwargs"]["ondelete"] == "RESTRICT"


def test_migration_does_not_touch_release_product_code():
    source = MIGRATION_PATH.read_text(encoding="utf-8")

    assert "drop_column('card_prints', 'release_product_code')" not in source
    assert "alter_column('card_prints', 'release_product_code'" not in source


def test_seed_products_carry_bandai_evidence():
    module = _load_migration()

    assert module.SOURCE_CATALOGUE == "bandai_jp"
    assert [p["official_code"] for p in module.SEED_PRODUCTS] == ["OP-01", "OP-02", "OP-03", "OP-04"]

    for product in module.SEED_PRODUCTS:
        assert product["source_url"].startswith("https://www.onepiece-cardgame.com/products/")
        assert product["source_series_id"].isdigit()
        # The published title is kept verbatim, code bracket and all.
        assert f"【{product['official_code']}】" in product["display_name"]


def test_seed_aliases_are_evidence_backed_and_kind_separated():
    module = _load_migration()
    by_kind = {}
    for code, name, kind, url in module.SEED_ALIASES:
        by_kind.setdefault(kind, []).append((code, name, url))

    # Every Bandai-claimed name cites a Bandai URL.
    for code, name, url in by_kind["bandai_official"]:
        assert url is not None and "onepiece-cardgame.com" in url

    # The one storefront rendering the repo actually holds, kept out of the
    # Bandai kinds and never given an invented URL.
    assert by_kind["source_rendering"] == [("OP-01", "ロマンスドーン", None)]
    assert "bandai_additional" not in by_kind

    # No duplicate (product, kind, name) in the seed data itself.
    keys = [(code, kind, name) for code, name, kind, _ in module.SEED_ALIASES]
    assert len(keys) == len(set(keys))


def test_seed_names_match_the_collectors_release_reference():
    """The collector's RELEASE_REFERENCES is the repository's existing
    authority for release names - the seed must not invent different ones.

    Asserted seed -> reference, which is what that sentence actually says.
    The reverse (every reference code must appear in this seed) cannot hold:
    this migration is an applied historical artifact that seeded the four
    products existing when it was written, while RELEASE_REFERENCES keeps
    growing as releases are established from Bandai evidence - EB-01 was
    added from the repo's frozen bandai_jp catalogue snapshot. Requiring
    equality would mean editing already-applied migration history every time
    a release is added, so instead every seeded code is checked strictly
    against the reference, and any reference this seed predates still has to
    satisfy the same "cites Bandai" invariant.
    """
    import sys

    collector_path = (
        Path(__file__).resolve().parents[3] / "services" / "snkrdunk_collector"
    )
    sys.path.insert(0, str(collector_path))
    try:
        from snkrdunk_collector.release_reference import RELEASE_REFERENCES
    finally:
        sys.path.remove(str(collector_path))

    module = _load_migration()
    official = {
        code: name for code, name, kind, _ in module.SEED_ALIASES if kind == "bandai_official"
    }
    renderings = {
        code: name for code, name, kind, _ in module.SEED_ALIASES if kind == "source_rendering"
    }

    # Every code this migration seeds must be one the collector knows, and
    # must agree with it exactly - name, citation, and storefront rendering.
    for code, name in official.items():
        reference = RELEASE_REFERENCES[code]
        assert name == reference.bandai_official_name
        product = next(p for p in module.SEED_PRODUCTS if p["official_code"] == code)
        assert product["source_url"] == reference.source_url
    for code, rendering in renderings.items():
        assert rendering in RELEASE_REFERENCES[code].snkrdunk_renderings

    # References added after this migration are legitimate, but must still be
    # Bandai-attested - the seed is not the only thing forbidden to invent.
    for code, reference in RELEASE_REFERENCES.items():
        if code in official:
            continue
        assert "onepiece-cardgame.com" in reference.source_url
        assert reference.bandai_official_name


def test_downgrade_removes_everything_it_added():
    module = _load_migration()
    dropped = {"table": [], "column": [], "index": [], "constraint": []}

    with (
        patch("alembic.op.drop_table", side_effect=lambda n, **k: dropped["table"].append(n)),
        patch(
            "alembic.op.drop_column", side_effect=lambda t, c, **k: dropped["column"].append((t, c))
        ),
        patch("alembic.op.drop_index", side_effect=lambda n, **k: dropped["index"].append(n)),
        patch(
            "alembic.op.drop_constraint",
            side_effect=lambda n, t, **k: dropped["constraint"].append((n, t)),
        ),
    ):
        module.downgrade()

    assert set(dropped["table"]) == {"release_products", "release_product_aliases"}
    assert dropped["column"] == [("card_prints", "release_product_id")]
    assert set(dropped["index"]) >= {
        "ix_card_prints_release_product_id",
        "uq_release_products_catalogue_official_code",
        "ix_release_products_source_catalogue",
        "ix_release_product_aliases_product_id",
    }
    assert dropped["constraint"] == [
        ("fk_card_prints_release_product_id_release_products", "card_prints")
    ]
