"""Real PostgreSQL proofs for the collector account tables (S3).

Migration up/down, the model matching the migrated schema, ON DELETE CASCADE
from users, RESTRICT on prints, CHECK constraints, receipt-verified valuation
through the API on JSONB provenance, and a read-only legacy dry run.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from tests.pg_url import admin_url, postgres_unavailable, postgres_url, server_label
from sqlalchemy.orm import sessionmaker

from app.accounts import valuation
from app.accounts.config import FLAG
from app.accounts.migrate_legacy import run as run_legacy_copy
from app.accounts.models import ACCOUNT_TABLES, CollectionEntry
from app.db import Base, get_db
from app.main import app
from app.models import User
from app.services import app_logging, job_locks
from tests._auth_helpers import make_bearer_token
from tests.accounts_helpers import archive_range, at, hold
from tests.test_prints import make_canonical, make_print

PARENT = "6c2242f6f439"
REVISION = "3b7d9c1a5e20"
D = date(2026, 9, 10)


def alembic(url, action, revision):
    result = subprocess.run(
        [sys.executable, "-m", "alembic", action, revision],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, DATABASE_URL=url),
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result


@pytest.fixture(scope="module")
def pg():
    name = "atlas_accounts_" + uuid.uuid4().hex[:10]
    admin = create_engine(admin_url(), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError:
        admin.dispose()
        postgres_unavailable(f"Disposable PostgreSQL unavailable at {server_label()}")
    engine = create_engine(postgres_url(name))
    try:
        result = alembic(postgres_url(name), "upgrade", "head")
        assert result.returncode == 0, result.stdout + result.stderr
        yield engine, postgres_url(name)
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def db(pg, monkeypatch):
    engine, _ = pg
    tables = [n for n in inspect(engine).get_table_names() if n != "alembic_version"]
    with engine.begin() as connection:
        connection.execute(
            text("TRUNCATE " + ",".join(f'"{n}"' for n in tables) + " RESTART IDENTITY CASCADE")
        )
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(job_locks, "SessionLocal", factory)
    monkeypatch.setattr(app_logging, "SessionLocal", factory)
    valuation.clear_receipt_cache()
    with factory() as session:
        session.add(User(google_sub="test-google-sub", email="test@example.com", name="T"))
        session.commit()
        assert session.scalar(select(User.id)) == 1
        yield session
        session.rollback()


def count(db, table, where=""):
    return db.execute(text(f'SELECT count(*) FROM "{table}" {where}')).scalar()


def test_head_is_this_revision_and_tables_are_empty(pg):
    engine, _ = pg
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == REVISION
        names = set(inspect(connection).get_table_names())
        assert set(ACCOUNT_TABLES) <= names
        for table in ACCOUNT_TABLES:
            assert connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar() == 0


def test_models_match_the_migrated_schema(pg):
    engine, _ = pg
    def ours(obj, name, kind, reflected, compare_to):
        table = obj if kind == "table" else getattr(obj, "table", None)
        return table is not None and table.name in ACCOUNT_TABLES

    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True, "include_object": ours}
        )
        diffs = compare_metadata(context, Base.metadata)
    assert diffs == []


def test_downgrade_drops_only_the_empty_new_tables_then_upgrade_restores(pg):
    engine, url = pg
    before = set(inspect(engine).get_table_names())
    result = alembic(url, "downgrade", PARENT)
    assert result.returncode == 0, result.stdout + result.stderr
    after = set(inspect(engine).get_table_names())
    assert before - after == set(ACCOUNT_TABLES)
    assert after - before == set()
    result = alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr
    assert set(inspect(engine).get_table_names()) == before


def test_downgrade_refuses_when_tables_hold_rows(pg, db):
    _, url = pg
    db.execute(text("INSERT INTO user_preferences (user_id) VALUES (1)"))
    db.commit()
    result = alembic(url, "downgrade", PARENT)
    assert result.returncode != 0
    assert "Refusing to drop collector account tables that hold rows: user_preferences" in result.stderr
    assert "user_preferences" in inspect(pg[0]).get_table_names()


def test_deleting_a_user_cascades_to_every_account_table(db):
    canonical = make_canonical(db, card_code="OP01-001")
    printing = make_print(db, canonical, artwork_key="pg-art")
    db.add(User(google_sub="b", email="b@example.com"))
    db.commit()
    for user_id in (1, 2):
        for statement in (
            "INSERT INTO collection_entries (user_id, card_print_id, quantity, resolution) VALUES (:u, :p, 2, 'exact')",
            "INSERT INTO collection_entries (user_id, quantity, resolution, legacy_card_id) VALUES (:u, 1, 'unresolved', 5)",
            "INSERT INTO collection_entry_events (user_id, card_print_id, quantity_before, quantity_after) VALUES (:u, :p, 0, 2)",
            "INSERT INTO watchlist_entries (user_id, card_print_id, resolution, target_jpy) VALUES (:u, :p, 'exact', 100)",
            "INSERT INTO user_preferences (user_id) VALUES (:u)",
            "INSERT INTO collection_value_points (user_id, point_date, methodology_version, value_jpy, priced_cards,"
            " total_cards, priced_entries, total_entries, segment_number) VALUES (:u, '2026-09-10', 1, 500, 2, 3, 1, 2, 1)",
        ):
            db.execute(text(statement), {"u": user_id, "p": printing.id})
    db.commit()
    db.execute(text("DELETE FROM users WHERE id = 1"))
    db.commit()
    for table in ACCOUNT_TABLES:
        assert count(db, table, "WHERE user_id = 1") == 0, table
        assert count(db, table, "WHERE user_id = 2") > 0, table


def test_a_held_print_cannot_be_deleted(db):
    canonical = make_canonical(db, card_code="OP01-001")
    printing = make_print(db, canonical, artwork_key="pg-art")
    db.add(CollectionEntry(user_id=1, card_print_id=printing.id, quantity=1, resolution="exact"))
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(text("DELETE FROM card_prints WHERE id = :p"), {"p": printing.id})
        db.commit()
    db.rollback()


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO collection_entries (user_id, quantity, resolution) VALUES (1, 1, 'exact')",
        "INSERT INTO collection_entries (user_id, card_print_id, quantity, resolution) VALUES (1, :p, 1, 'unresolved')",
        "INSERT INTO collection_entries (user_id, card_print_id, quantity, resolution) VALUES (1, :p, 0, 'exact')",
        "INSERT INTO collection_entries (user_id, card_print_id, quantity, resolution, paid_jpy_per_card) VALUES (1, :p, 1, 'exact', -1)",
        "INSERT INTO watchlist_entries (user_id, card_print_id, resolution, target_jpy) VALUES (1, :p, 'exact', 0)",
        "INSERT INTO watchlist_entries (user_id, resolution) VALUES (1, 'maybe')",
        "INSERT INTO user_preferences (user_id, currency) VALUES (1, 'USD')",
        "INSERT INTO user_preferences (user_id, collection_visibility) VALUES (1, 'public')",
        "INSERT INTO collection_entry_events (user_id, card_print_id, quantity_before, quantity_after) VALUES (1, :p, 2, 2)",
        "INSERT INTO collection_value_points (user_id, point_date, methodology_version, value_jpy, priced_cards,"
        " total_cards, priced_entries, total_entries, segment_number) VALUES (1, '2026-09-10', 1, 0, 0, 3, 0, 2, 1)",
        "INSERT INTO collection_value_points (user_id, point_date, methodology_version, value_jpy, priced_cards,"
        " total_cards, priced_entries, total_entries, segment_number) VALUES (1, '2026-09-10', 1, NULL, 2, 3, 1, 2, 1)",
    ],
)
def test_check_constraints_refuse_invalid_rows(db, statement):
    canonical = make_canonical(db, card_code="OP01-001")
    printing = make_print(db, canonical, artwork_key="pg-art")
    with pytest.raises(IntegrityError):
        db.execute(text(statement), {"p": printing.id})
        db.commit()
    db.rollback()


def test_one_entry_per_user_and_print(db):
    canonical = make_canonical(db, card_code="OP01-001")
    printing = make_print(db, canonical, artwork_key="pg-art")
    db.add(CollectionEntry(user_id=1, card_print_id=printing.id, quantity=1, resolution="exact"))
    db.commit()
    # Unresolved rows (no print) are not limited.
    for _ in range(2):
        db.add(CollectionEntry(user_id=1, card_print_id=None, quantity=1, resolution="unresolved"))
    db.commit()
    db.add(CollectionEntry(user_id=1, card_print_id=printing.id, quantity=1, resolution="exact"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_api_values_and_isolates_users_on_postgres(db, pg, monkeypatch):
    engine, _ = pg
    factory = sessionmaker(bind=engine, autoflush=False)

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setenv(FLAG, "true")
    from app.settings import settings
    from tests._auth_helpers import TEST_API_JWT_SECRET

    monkeypatch.setattr(settings, "API_JWT_SECRET", TEST_API_JWT_SECRET)
    monkeypatch.setitem(app.dependency_overrides, get_db, override)
    a = make_print(db, make_canonical(db, card_code="OP01-001"), artwork_key="pg-a")
    c = make_print(db, make_canonical(db, card_code="OP01-003"), artwork_key="pg-c")
    p = D - timedelta(days=7)
    archive_range(
        db, p, D, lambda day: {a.id: 150 if day == D else 100, c.id: 1600 if day == D else 2000}
    )
    hold(db, 1, a.id, 1, at(p - timedelta(days=1)))
    hold(db, 1, c.id, 2, at(p - timedelta(days=1)))

    client = TestClient(app)
    mine = {"Authorization": f"Bearer {make_bearer_token()}"}
    theirs = {"Authorization": f"Bearer {make_bearer_token(google_sub='pg-other', email='o@example.com')}"}
    body = client.get("/me/collection/value", headers=mine).json()
    assert body["as_of"] == D.isoformat()
    assert body["summary"]["value_jpy"] == 150 + 2 * 1600
    assert body["movers"]["available"] is True
    assert body["movers"]["change_jpy"] == (150 + 3200) - (100 + 4000)
    other = client.get("/me/collection/value", headers=theirs).json()
    assert other["summary"]["total_entries"] == 0 and other["summary"]["value_jpy"] is None

    response = client.post("/me/collection", json={"card_print_id": a.id, "quantity": 4}, headers=theirs)
    assert response.status_code == 201
    entry_id = response.json()["id"]
    assert client.delete(f"/me/collection/{entry_id}", headers=mine).status_code == 404
    assert client.delete("/me?confirm=delete%20my%20account", headers=theirs).status_code == 204
    db.expire_all()
    assert count(db, "users", "WHERE google_sub = 'pg-other'") == 0
    assert count(db, "collection_entries", f"WHERE id = {entry_id}") == 0
    assert count(db, "collection_entries", "WHERE user_id = 1") == 2


def test_legacy_dry_run_is_read_only_on_postgres(db):
    db.commit()
    report = run_legacy_copy(db, write_rows=False)
    assert report["summary"]["collection_items"]["rows"] == 0
    assert report["summary"]["wishlist_items"]["rows"] == 0
    # The dry run's transaction refused writes and was rolled back.
    db.execute(text("SET TRANSACTION READ ONLY"))
    with pytest.raises(Exception):
        db.execute(text("INSERT INTO user_preferences (user_id) VALUES (1)"))
    db.rollback()
    assert count(db, "collection_entries") == count(db, "watchlist_entries") == 0


# Every column that identifies a user, discovered from the live schema rather
# than a hand-kept list: any column named user_id plus any foreign key to users.
USER_COLUMNS_SQL = """
SELECT table_name, column_name FROM information_schema.columns
 WHERE table_schema = 'public' AND column_name = 'user_id'
UNION
SELECT kcu.table_name, kcu.column_name
  FROM information_schema.table_constraints tc
  JOIN information_schema.key_column_usage kcu
    ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
  JOIN information_schema.constraint_column_usage ccu
    ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
 WHERE tc.constraint_type = 'FOREIGN KEY' AND ccu.table_name = 'users'
 ORDER BY 1, 2
"""


def test_after_delete_me_no_table_carries_the_users_id(db, pg, monkeypatch, tmp_path):
    from app.models import (
        Card,
        CollectionItem,
        CollectorGroup,
        CollectorTag,
        FileJob,
        SavedView,
        SearchHistory,
        WishlistItem,
    )
    from app.settings import settings
    from tests._auth_helpers import TEST_API_JWT_SECRET

    engine, _ = pg
    factory = sessionmaker(bind=engine, autoflush=False)

    def override():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setenv(FLAG, "true")
    monkeypatch.setattr(settings, "API_JWT_SECRET", TEST_API_JWT_SECRET)
    monkeypatch.setattr(settings, "FILE_JOB_STORAGE_DIR", str(tmp_path))
    monkeypatch.setitem(app.dependency_overrides, get_db, override)

    with engine.connect() as connection:
        user_columns = [tuple(r) for r in connection.execute(text(USER_COLUMNS_SQL))]
    # A new table that stores a user id must be added to this test and to
    # delete_account deliberately.
    assert sorted({table for table, _ in user_columns}) == sorted({
        "collection_entries", "collection_entry_events", "collection_items",
        "collection_value_points", "collector_groups", "collector_tags", "file_jobs",
        "saved_views", "search_history", "user_preferences", "watchlist_entries",
        "wishlist_items",
    })

    printing = make_print(db, make_canonical(db, card_code="OP01-001"), artwork_key="pg-sweep")
    legacy = Card(card_code="OP01-001", set_code="OP01", rarity="R", language="jp")
    db.add(legacy)
    db.add(User(google_sub="keep", email="keep@example.com"))
    db.commit()
    keep = db.scalar(select(User.id).where(User.google_sub == "keep"))
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "mine.csv").write_text("my collection")
    (tmp_path / "output" / "keep.csv").write_text("their collection")
    for user_id in (1, keep):
        mine = user_id == 1
        db.add_all([
            CollectionItem(user_id=user_id, card_id=legacy.id, quantity=1),
            WishlistItem(user_id=user_id, card_id=legacy.id),
            CollectorTag(user_id=user_id, name="t", slug=f"t{user_id}"),
            CollectorGroup(user_id=user_id, name="g", slug=f"g{user_id}"),
            SavedView(user_id=user_id, name="v", route_path="/cards", view_type="cards"),
            SearchHistory(user_id=user_id, query="luffy"),
            FileJob(user_id=user_id, job_type="collection_export", status="success",
                    output_file_path="output/mine.csv" if mine else "output/keep.csv"),
            CollectionEntry(user_id=user_id, card_print_id=printing.id, quantity=1, resolution="exact"),
        ])
        db.commit()
        for statement in (
            "INSERT INTO collection_entry_events (user_id, card_print_id, quantity_before, quantity_after) VALUES (:u, :p, 0, 1)",
            "INSERT INTO watchlist_entries (user_id, card_print_id, resolution) VALUES (:u, :p, 'exact')",
            "INSERT INTO user_preferences (user_id) VALUES (:u)",
            "INSERT INTO collection_value_points (user_id, point_date, methodology_version, value_jpy, priced_cards,"
            " total_cards, priced_entries, total_entries, segment_number) VALUES (:u, '2026-09-10', 1, 5, 1, 1, 1, 1, 1)",
        ):
            db.execute(text(statement), {"u": user_id, "p": printing.id})
        db.commit()
    db.add(FileJob(user_id=None, job_type="backup_export", status="success"))  # admin job
    db.commit()
    # Every user-bearing table really holds a row for the user before deletion.
    for table, column in user_columns:
        assert count(db, table, f'WHERE "{column}" = 1') > 0, table

    response = TestClient(app).delete(
        "/me?confirm=delete%20my%20account",
        headers={"Authorization": f"Bearer {make_bearer_token()}"},
    )
    assert response.status_code == 204

    db.expire_all()
    assert count(db, "users", "WHERE id = 1") == 0
    for table, column in user_columns:
        assert count(db, table, f'WHERE "{column}" = 1') == 0, table
        assert count(db, table, f'WHERE "{column}" = {keep}') > 0, table
    assert count(db, "file_jobs", "WHERE user_id IS NULL") == 1  # admin job untouched
    assert not (tmp_path / "output" / "mine.csv").exists()
    assert (tmp_path / "output" / "keep.csv").read_text() == "their collection"
