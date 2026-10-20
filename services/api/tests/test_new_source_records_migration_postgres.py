"""Migration 7a52e9b48e8a (new-sources plan S1): additive tables, grade_key, splice tables."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import uuid

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db import Base
from app.source_products import grade_keys
from app.source_products import models as source_models
from tests.pg_url import admin_url, postgres_unavailable, postgres_url, server_label

PARENT = "3b7d9c1a5e20"
REVISION = "7a52e9b48e8a"
API_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = API_ROOT / "alembic/versions/7a52e9b48e8a_add_new_source_records.py"


def _migration():
    spec = importlib.util.spec_from_file_location("migration_7a52e9b48e8a", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def alembic(url, action, revision):
    return subprocess.run(
        [sys.executable, "-m", "alembic", action, revision],
        cwd=API_ROOT,
        env=dict(os.environ, DATABASE_URL=url),
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_revision_extends_the_accounts_head():
    module = _migration()
    assert module.revision == REVISION
    assert module.down_revision == PARENT


def test_migration_restates_the_grade_key_pattern():
    assert _migration().GRADE_KEY_PATTERN == grade_keys.SQL_PATTERN


@pytest.mark.parametrize(
    "key, valid",
    [
        ("raw:A", True), ("raw:A-", True), ("raw:damaged", True), ("raw:play", True),
        ("graded:PSA:10", True), ("graded:BGS:9.5", True), ("graded:PSA:10:flawed", True),
        ("graded:unknown", True), ("raw:E", False), ("raw:a", False), ("graded:psa:10", False),
        ("graded:PSA:10.0", False), ("graded:PSA", False), ("PSA10", False), ("", False),
    ],
)
def test_grade_key_vocabulary(key, valid):
    assert grade_keys.is_valid(key) is valid


def test_graded_helper_falls_back_to_unknown():
    assert grade_keys.graded("psa", "10") == "graded:PSA:10"
    assert grade_keys.graded("PSA", "10", flawed=True) == "graded:PSA:10:flawed"
    assert grade_keys.graded("PSA", "ten") == grade_keys.GRADED_UNKNOWN
    assert grade_keys.graded(None, "10") == grade_keys.GRADED_UNKNOWN
    with pytest.raises(ValueError):
        grade_keys.raw("E")


def test_existing_collectors_do_not_load_the_new_tables():
    import app.models  # noqa: F401

    assert "app.source_products" not in (API_ROOT / "app/models/__init__.py").read_text()
    assert "grade_key" not in (API_ROOT / "app/models/price_observation.py").read_text()


@pytest.fixture(scope="module")
def pg():
    name = "new_source_records_" + uuid.uuid4().hex[:10]
    admin = create_engine(admin_url(), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError:
        admin.dispose()
        postgres_unavailable(f"Disposable PostgreSQL unavailable at {server_label()}")
    engine = create_engine(postgres_url(name))
    try:
        result = alembic(postgres_url(name), "upgrade", REVISION)
        assert result.returncode == 0, result.stdout + result.stderr
        yield engine, postgres_url(name)
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


def _seed(connection):
    """One source, release-free print and raw snapshot to hang rows on."""
    source_id = connection.scalar(text("SELECT id FROM sources WHERE name = 'dorasuta'"))
    card = connection.scalar(text(
        "INSERT INTO canonical_cards (card_code, card_type, name_jp) VALUES ('OP01-001', 'LEADER', 'x') RETURNING id"
    ))
    print_id = connection.scalar(text(
        "INSERT INTO card_prints (canonical_card_id, language) VALUES (:c, 'ja') RETURNING id"
    ), {"c": card})
    raw_id = connection.scalar(text(
        "INSERT INTO raw_snapshots (source_id, source_url, fetched_at, http_status, content_hash, raw_content) "
        "VALUES (:s, 'https://dorasuta.jp/x', now(), 200, repeat('a', 64), '<html></html>') RETURNING id"
    ), {"s": source_id})
    return source_id, print_id, raw_id


def test_tables_and_seeded_sources(pg):
    engine, _ = pg
    names = set(inspect(engine).get_table_names())
    assert set(source_models.TABLES) <= names
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION
        rows = dict(connection.execute(text(
            "SELECT name, base_url FROM sources WHERE name IN ('dorasuta', 'cardrush')"
        )).all())
        assert rows == {"dorasuta": "https://dorasuta.jp", "cardrush": "https://www.cardrush-op.jp"}
        for table in source_models.TABLES:
            assert connection.scalar(text(f'SELECT count(*) FROM "{table}"')) == 0
    columns = {c["name"]: c for c in inspect(engine).get_columns("price_observations")}
    assert columns["grade_key"]["nullable"] is True


def test_models_match_the_migrated_schema(pg):
    engine, _ = pg

    def ours(obj, name, kind, reflected, compare_to):
        table = obj if kind == "table" else getattr(obj, "table", None)
        return table is not None and table.name in source_models.TABLES

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True, "include_object": ours})
        assert compare_metadata(context, Base.metadata) == []


def test_grade_key_checks_on_price_observations(pg):
    engine, _ = pg
    with engine.connect() as connection:
        source_id, _, _ = _seed(connection)
        insert = text(
            "INSERT INTO price_observations (source_id, price_type, price_jpy, observed_at, grade_key) "
            "VALUES (:s, 'sell', 100, now(), :g)"
        )
        connection.execute(insert, {"s": source_id, "g": None})
        connection.execute(insert, {"s": source_id, "g": "raw:A"})
        for bad in ("graded:PSA:10", "raw:E", "A"):
            savepoint = connection.begin_nested()
            with pytest.raises(IntegrityError):
                connection.execute(insert, {"s": source_id, "g": bad})
            savepoint.rollback()
        connection.rollback()


def test_source_product_constraints(pg):
    engine, _ = pg
    with engine.connect() as connection:
        source_id, print_id, raw_id = _seed(connection)
        product = text(
            "INSERT INTO source_products (source_id, source_product_key, canonical_listing_identity, url, name, "
            "match_status, refusal_code, card_print_id, listing_kind) "
            "VALUES (:s, :k, :i, 'https://dorasuta.jp/p', 'n', :m, :r, :p, 'plain') RETURNING id"
        )
        exact = connection.scalar(product, {"s": source_id, "k": "1", "i": "dorasuta:1", "m": "exact", "r": None, "p": print_id})
        connection.scalar(product, {"s": source_id, "k": "2", "i": "dorasuta:2", "m": "quarantined", "r": "no_code", "p": None})
        for bad in (
            {"k": "3", "i": "dorasuta:3", "m": "exact", "r": None, "p": None},  # exact without a print
            {"k": "4", "i": "dorasuta:4", "m": "pending", "r": None, "p": print_id},  # print without a match
            {"k": "5", "i": "dorasuta:5", "m": "refused", "r": None, "p": None},  # refused without a code
            {"k": "1", "i": "dorasuta:6", "m": "pending", "r": None, "p": None},  # duplicate product key
        ):
            savepoint = connection.begin_nested()
            with pytest.raises(IntegrityError):
                connection.scalar(product, {"s": source_id, **bad})
            savepoint.rollback()
        variant = text(
            "INSERT INTO source_product_variants (source_product_id, grade_key, last_price_jpy, stock, last_seen_at, "
            "last_raw_snapshot_id) VALUES (:p, :g, :price, 1, now(), :raw)"
        )
        connection.execute(variant, {"p": exact, "g": "raw:A", "price": 1200, "raw": raw_id})
        connection.execute(variant, {"p": exact, "g": "graded:PSA:10", "price": 50000, "raw": raw_id})
        for bad in ({"g": "raw:A", "price": 1}, {"g": "raw:Z", "price": 1}, {"g": "raw:B", "price": 0}):
            savepoint = connection.begin_nested()
            with pytest.raises(IntegrityError):
                connection.execute(variant, {"p": exact, "raw": raw_id, **bad})
            savepoint.rollback()
        connection.rollback()


def test_widened_candidate_type_and_splice_step(pg):
    engine, _ = pg
    with engine.connect() as connection:
        check = connection.scalar(text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_mapping_proposal_groups_candidate_type'"
        ))
        assert "source_product" in check and "yuyutei_candidate" in check and "snkrdunk_candidate" in check
        splice = text(
            "INSERT INTO market_index_splices (splice_date, from_semantics_version, to_semantics_version, "
            "source_added, approved_by, approved_at) VALUES ('2026-11-01', 3, :to, 'dorasuta', 'owner', now())"
        )
        savepoint = connection.begin_nested()
        with pytest.raises(IntegrityError):
            connection.execute(splice, {"to": 5})
        savepoint.rollback()
        connection.execute(splice, {"to": 4})
        connection.rollback()


def test_downgrade_refuses_rows_then_drops_only_the_new_objects(pg):
    engine, url = pg
    with engine.begin() as connection:
        source_id, _, _ = _seed(connection)
        connection.execute(text(
            "INSERT INTO source_product_groups (source_id, group_key, url, title, kind) "
            "VALUES (:s, 'sid:1', 'https://dorasuta.jp/g', 't', 'series')"
        ), {"s": source_id})
    result = alembic(url, "downgrade", PARENT)
    assert result.returncode != 0
    assert "refusing to drop new-source evidence" in result.stdout + result.stderr
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM source_product_groups"))
    before = set(inspect(engine).get_table_names())
    result = alembic(url, "downgrade", PARENT)
    assert result.returncode == 0, result.stdout + result.stderr
    after = set(inspect(engine).get_table_names())
    assert before - after == set(source_models.TABLES)
    assert "grade_key" not in {c["name"] for c in inspect(engine).get_columns("price_observations")}
    with engine.connect() as connection:
        check = connection.scalar(text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_mapping_proposal_groups_candidate_type'"
        ))
        assert "source_product" not in check
    result = alembic(url, "upgrade", REVISION)
    assert result.returncode == 0, result.stdout + result.stderr
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM sources WHERE name = 'dorasuta'")) == 1
