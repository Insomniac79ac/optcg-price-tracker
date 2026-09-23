"""Disposable PostgreSQL proof of the final current-listing boundary."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.test_mapping_listing_foundation_postgres import pg_connection  # noqa: F401


def _migration(connection, filename, module_name):
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    return module


def _base(connection):
    connection.execute(text("CREATE TABLE sources (id integer PRIMARY KEY, name text NOT NULL)"))
    connection.execute(text("""
        CREATE TABLE source_card_mappings (
            id integer PRIMARY KEY, source_id integer NOT NULL REFERENCES sources(id),
            source_url varchar(1024), is_active boolean NOT NULL DEFAULT true,
            review_status text NOT NULL DEFAULT 'approved', updated_at timestamptz DEFAULT now()
        )
    """))
    connection.execute(text("INSERT INTO sources VALUES (1,'yuyutei'),(2,'snkrdunk')"))
    return _migration(connection, "b8e04219d6c3_mapping_listing_identity.py", "foundation_index_test")


def _insert(connection, id_, source, url, identity, *, review="approved"):
    connection.execute(text("""
        INSERT INTO source_card_mappings
          (id, source_id, source_url, canonical_source_listing_identity, review_status)
        VALUES (:id, :source, :url, :identity, :review)
    """), dict(id=id_, source=source, url=url, identity=identity, review=review))


def _supersede(connection, old, current):
    connection.execute(text("""
        UPDATE source_card_mappings
        SET superseded_at = now(), superseded_by_mapping_id = :current,
            supersession_reason = 'Explicit historical correction', is_active = false
        WHERE id = :old
    """), dict(old=old, current=current))


def test_index_refuses_unrepaired_duplicate_current_rows(pg_connection):
    c = pg_connection
    foundation = _base(c)
    foundation.upgrade()
    _insert(c, 12, 2, "https://snkrdunk.com/en/trading-cards/104428", "104428")
    _insert(c, 35, 2, "https://snkrdunk.com/apparels/104428", "104428")
    final = _migration(c, "f2c7d91b6a40_unique_current_listing_identity.py", "final_index_test")
    with pytest.raises(IntegrityError), c.begin_nested():
        final.upgrade()


def test_unique_current_lifecycle_and_fixture_shape(pg_connection):
    c = pg_connection
    foundation = _base(c)
    foundation.upgrade()
    for id_, source, url, identity in (
        (12, 2, "https://snkrdunk.com/en/trading-cards/104428?q=1", "104428"),
        (35, 2, "https://snkrdunk.com/apparels/104428", "104428"),
        (16, 2, "https://snkrdunk.com/en/trading-cards/93522?q=1", "93522"),
        (36, 2, "https://snkrdunk.com/apparels/93522", "93522"),
        (90, 1, "https://yuyu-tei.jp/sell/opc/card/st11/10004", "st11:10004"),
    ):
        _insert(c, id_, source, url, identity)
    _supersede(c, 12, 35)
    _supersede(c, 16, 36)
    final = _migration(c, "f2c7d91b6a40_unique_current_listing_identity.py", "final_index_test")
    before = c.execute(text("SELECT id, source_id, source_url, canonical_source_listing_identity, superseded_at, superseded_by_mapping_id, supersession_reason, is_active, review_status FROM source_card_mappings ORDER BY id")).all()
    final.upgrade()
    after = c.execute(text("SELECT id, source_id, source_url, canonical_source_listing_identity, superseded_at, superseded_by_mapping_id, supersession_reason, is_active, review_status FROM source_card_mappings ORDER BY id")).all()
    assert before == after
    index = c.execute(text("""
        SELECT i.indisunique, i.indisvalid, pg_get_expr(i.indpred, i.indrelid) AS predicate,
               pg_get_indexdef(i.indexrelid) AS definition
        FROM pg_index i JOIN pg_class idx ON idx.oid = i.indexrelid
        WHERE idx.relname = 'uq_mapping_current_canonical_listing_identity'
    """)).mappings().one()
    assert index["indisunique"] and index["indisvalid"]
    assert "superseded_at IS NULL" in index["predicate"]
    assert "canonical_source_listing_identity IS NOT NULL" in index["predicate"]
    assert "(source_id, canonical_source_listing_identity)" in index["definition"]

    # A second current URL spelling for the same numeric SNKRDUNK listing fails.
    with pytest.raises(IntegrityError), c.begin_nested():
        _insert(c, 101, 2, "https://snkrdunk.com/en/trading-cards/104428?q=2", "104428")
    # Historical rows coexist with the one current row, including two old rows.
    _insert(c, 102, 2, "https://snkrdunk.com/en/trading-cards/104428?q=3", None)
    _supersede(c, 102, 35)
    c.execute(text("UPDATE source_card_mappings SET canonical_source_listing_identity='104428' WHERE id=102"))
    assert c.scalar(text("SELECT count(*) FROM source_card_mappings WHERE source_id=2 AND canonical_source_listing_identity='104428'")) == 3
    with pytest.raises(IntegrityError), c.begin_nested():
        _insert(c, 103, 1, "https://yuyu-tei.jp/sell/opc/card/st11/10004?x=1", "st11:10004")

    # NULL identities remain a separate, non-unique diagnostic population.
    _insert(c, 110, 2, "https://unsupported.test/old-one", None)
    _insert(c, 111, 2, "https://unsupported.test/old-two", None)
    _insert(c, 120, 2, "https://snkrdunk.com/apparels/120", "120", review="rejected")
    with pytest.raises(IntegrityError), c.begin_nested():
        _insert(c, 121, 2, "https://snkrdunk.com/en/trading-cards/120", "120")

    # A successor can take an identity only within an explicit lifecycle step.
    _insert(c, 200, 2, "https://snkrdunk.com/apparels/200", "200")
    _insert(c, 201, 2, None, None)
    _supersede(c, 200, 201)
    c.execute(text("UPDATE source_card_mappings SET source_url='https://snkrdunk.com/en/trading-cards/200', canonical_source_listing_identity='200' WHERE id=201"))
    assert c.scalar(text("SELECT id FROM source_card_mappings WHERE source_id=2 AND canonical_source_listing_identity='200' AND superseded_at IS NULL")) == 201
    assert c.scalar(text("SELECT count(*) FROM (SELECT 1 FROM source_card_mappings WHERE superseded_at IS NULL AND canonical_source_listing_identity IS NOT NULL GROUP BY source_id, canonical_source_listing_identity HAVING count(*) > 1) d")) == 0


def test_stale_writer_loses_race_without_partial_mapping(pg_connection):
    c = pg_connection
    _base(c).upgrade()
    _migration(c, "f2c7d91b6a40_unique_current_listing_identity.py", "final_race_test").upgrade()
    schema = c.scalar(text("SELECT current_schema()"))
    c.commit()
    with c.engine.connect() as stale_writer:
        stale_writer.execute(text(f'SET search_path TO "{schema}"'))
        assert stale_writer.scalar(text("SELECT count(*) FROM source_card_mappings WHERE source_id=2 AND canonical_source_listing_identity='104428'")) == 0
        _insert(c, 35, 2, "https://snkrdunk.com/apparels/104428", "104428")
        c.commit()
        with pytest.raises(IntegrityError):
            _insert(stale_writer, 12, 2, "https://snkrdunk.com/en/trading-cards/104428", "104428")
        stale_writer.rollback()
    assert c.scalar(text("SELECT count(*) FROM source_card_mappings WHERE source_id=2 AND canonical_source_listing_identity='104428'")) == 1
    assert c.scalar(text("SELECT id FROM source_card_mappings WHERE source_id=2 AND canonical_source_listing_identity='104428'")) == 35
