"""Runs c7e91a4d2b60 for real on throwaway PostgreSQL databases.

Covers what only a live engine can prove: that dropping NOT NULL leaves every
existing rarity byte-identical, that the blank-guard CHECK and the rarity index
survive and still refuse '' while permitting NULL, that the downgrade refuses
BEFORE any DDL when a row is NULL - leaving schema, revision and data exactly
as they were - and that it succeeds and round-trips when the data can
represent NOT NULL.

The fixture data is staging-shaped: 15 canonical cards carrying the six rarity
values canonical staging actually holds, as read read-only on 2026-08-24.

Never touches canonical staging. Skips when no server answers."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError

REPO_ROOT = Path(__file__).resolve().parents[1]

HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
ADMIN_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/postgres"

PREVIOUS_HEAD = "a9f31c7d5b64"
THIS_REVISION = "c7e91a4d2b60"

RARITY_CHECK = "ck_canonical_cards_rarity_not_blank"
RARITY_INDEX = "ix_canonical_cards_rarity"
# PostgreSQL 17+ materialises a column's NOT NULL as a pg_constraint row.
# Dropping it is the one and only catalogue change this migration makes.
NOT_NULL_CONSTRAINT = "canonical_cards_rarity_not_null"

# The six rarity values canonical staging's 15 canonical cards actually carry,
# spread across them the way the real rows are.
STAGING_CARDS = (
    ("OP01-001", "OP-01", "L"), ("OP01-002", "OP-01", "L"), ("OP01-013", "OP-01", "SR"),
    ("OP02-013", "OP-02", "SR"), ("OP03-001", "OP-03", "L"), ("OP03-013", "OP-03", "SR"),
    ("OP03-099", "OP-03", "SEC"), ("OP04-001", "OP-04", "L"), ("OP04-006", "OP-04", "C"),
    ("OP04-007", "OP-04", "UC"), ("OP04-024", "OP-04", "R"), ("OP04-044", "OP-04", "SR"),
    ("OP04-083", "OP-04", "R"), ("OP04-090", "OP-04", "C"), ("OP04-118", "OP-04", "SEC"),
)


def _alembic(url: str, *args: str, expect_success: bool = True):
    env = dict(os.environ)
    env["DATABASE_URL"] = url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    output = result.stdout + result.stderr
    if expect_success:
        assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{output}"
    else:
        assert result.returncode != 0, f"alembic {' '.join(args)} unexpectedly succeeded:\n{output}"
    return output


class _Database:
    """A throwaway database seeded to a chosen state."""

    def __init__(self, name: str):
        self.name = name
        self.url = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/{name}"
        self.admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with self.admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        self.engine = create_engine(self.url)

    def close(self):
        self.engine.dispose()
        with self.admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)'))
        self.admin.dispose()


def _new_database(name: str) -> _Database:
    try:
        return _Database(name)
    except OperationalError:
        pytest.skip(f"No PostgreSQL server reachable at {HOST}:{PORT}")


def _seed_staging_shape(db: _Database) -> None:
    """The 15 staging canonical cards, at the revision before this one."""
    _alembic(db.url, "upgrade", PREVIOUS_HEAD)
    with db.engine.begin() as conn:
        for card_code, set_code, rarity in STAGING_CARDS:
            conn.execute(
                text(
                    "INSERT INTO canonical_cards "
                    "(card_code, name_jp, original_set_code, rarity, card_type) "
                    "VALUES (:code, :name, :set_code, :rarity, 'Character')"
                ),
                {"code": card_code, "name": f"テスト{card_code}",
                 "set_code": set_code, "rarity": rarity},
            )


def _rarity_fingerprint(conn) -> str:
    return conn.execute(
        text(
            "SELECT md5(string_agg(card_code || '=' || coalesce(rarity, '<NULL>'), "
            "',' ORDER BY card_code)) FROM canonical_cards"
        )
    ).scalar_one()


def _rarity_column(conn) -> tuple:
    return conn.execute(
        text(
            "SELECT data_type, character_maximum_length, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_name = 'canonical_cards' AND column_name = 'rarity'"
        )
    ).one()


def _revision(conn) -> str:
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _constraints(conn) -> dict:
    return dict(
        conn.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'canonical_cards'::regclass ORDER BY conname"
            )
        ).all()
    )


def _indexes(conn) -> dict:
    return dict(
        conn.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'canonical_cards' ORDER BY indexname"
            )
        ).all()
    )


@pytest.fixture(scope="module")
def migrated():
    """The staging-shaped 15, upgraded across this revision."""
    db = _new_database("opcg_test_rarity_nullable_ok")
    _seed_staging_shape(db)
    with db.engine.connect() as conn:
        before = {
            "rarities": _rarity_fingerprint(conn),
            "count": conn.execute(text("SELECT count(*) FROM canonical_cards")).scalar_one(),
            "column": _rarity_column(conn),
            "constraints": _constraints(conn),
            "indexes": _indexes(conn),
        }
    output = _alembic(db.url, "upgrade", THIS_REVISION)
    try:
        yield db, before, output
    finally:
        db.close()


# --- what the upgrade changes, and what it must not -------------------------


def test_the_column_becomes_nullable_and_nothing_else_about_it_moves(migrated):
    db, before, _ = migrated

    with db.engine.connect() as conn:
        after = _rarity_column(conn)

    data_type, length, is_nullable, default = after
    assert before["column"][2] == "NO"
    assert is_nullable == "YES"
    # Type, width and the absence of a default are all unchanged.
    assert (data_type, length, default) == (
        before["column"][0], before["column"][1], before["column"][2 + 1],
    )
    assert default is None


def test_every_existing_rarity_value_survives_byte_identical(migrated):
    db, before, _ = migrated

    with db.engine.connect() as conn:
        assert _rarity_fingerprint(conn) == before["rarities"]
        assert conn.execute(
            text("SELECT count(*) FROM canonical_cards")
        ).scalar_one() == before["count"]
        # And not one row was quietly turned into a NULL.
        assert conn.execute(
            text("SELECT count(*) FROM canonical_cards WHERE rarity IS NULL")
        ).scalar_one() == 0


def test_the_upgrade_reports_that_it_wrote_nothing(migrated):
    _, _, output = migrated

    assert "no row was read, written or backfilled" in output


def test_the_only_constraint_that_moves_is_rarity_s_own_not_null(migrated):
    """PostgreSQL 17+ exposes NOT NULL as a pg_constraint row, so dropping it
    is visible here - and it is the ONLY difference. Every CHECK, the unique
    constraint on card_code, and every other column's NOT NULL survive."""
    db, before, _ = migrated

    with db.engine.connect() as conn:
        after = _constraints(conn)

    removed = set(before["constraints"]) - set(after)
    added = set(after) - set(before["constraints"])
    assert added == set()
    assert removed == {NOT_NULL_CONSTRAINT}, removed
    # Everything that remains is byte-identical to what was there before.
    assert after == {
        k: v for k, v in before["constraints"].items() if k != NOT_NULL_CONSTRAINT
    }
    # Named explicitly: the blank guard is what keeps '' out, and it stays.
    assert RARITY_CHECK in after
    assert "ck_canonical_cards_original_set_code_not_blank" in after
    assert "uq_canonical_cards_card_code" in after


def test_the_indexes_come_through_untouched(migrated):
    db, before, _ = migrated

    with db.engine.connect() as conn:
        assert _indexes(conn) == before["indexes"]
    assert RARITY_INDEX in before["indexes"]


def test_null_is_now_accepted_and_blank_is_still_refused(migrated):
    """The blank guard is the whole reason the CHECK is left alone: NULL means
    'the catalogue establishes none', while '' is a value pretending to be
    one. `trim(NULL) <> ''` is NULL, which a CHECK treats as satisfied."""
    db, _, _ = migrated

    with db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO canonical_cards "
                "(card_code, name_jp, original_set_code, rarity, card_type) "
                "VALUES ('EB03-003', 'ウタ', 'EB-03', NULL, 'Character')"
            )
        )
    with db.engine.connect() as conn:
        assert conn.execute(
            text("SELECT rarity FROM canonical_cards WHERE card_code = 'EB03-003'")
        ).scalar_one() is None

    for blank in ("", "   "):
        with pytest.raises(IntegrityError):
            with db.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO canonical_cards "
                        "(card_code, name_jp, original_set_code, rarity, card_type) "
                        "VALUES ('EB03-018', 'x', 'EB-03', :r, 'Character')"
                    ),
                    {"r": blank},
                )


def test_the_index_still_serves_a_rarity_filter_with_nulls_present(migrated):
    """A b-tree over a nullable column is exactly what the catalogue filter
    needs: an equality match never returns the NULL rows."""
    db, _, _ = migrated

    with db.engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM canonical_cards WHERE rarity = 'SR'")
        ).scalar_one() == 4
        assert conn.execute(
            text("SELECT count(*) FROM canonical_cards WHERE rarity IS NULL")
        ).scalar_one() == 1


# --- the downgrade ----------------------------------------------------------


def test_downgrade_refuses_before_any_ddl_when_a_rarity_is_null():
    """Fail-closed, and provably so: schema, revision and data all unchanged
    after the refusal."""
    db = _new_database("opcg_test_rarity_nullable_refuse")
    try:
        _seed_staging_shape(db)
        _alembic(db.url, "upgrade", THIS_REVISION)
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO canonical_cards "
                    "(card_code, name_jp, original_set_code, rarity, card_type) "
                    "VALUES ('EB03-003', 'ウタ', 'EB-03', NULL, 'Character')"
                )
            )
        with db.engine.connect() as conn:
            before = (
                _rarity_column(conn), _revision(conn), _rarity_fingerprint(conn),
                _constraints(conn), _indexes(conn),
            )

        output = _alembic(
            db.url, "downgrade", PREVIOUS_HEAD, expect_success=False
        )

        assert "ABORTED" in output
        assert THIS_REVISION in output
        # It names the row an operator has to decide about, and says where the
        # authoritative per-printing value already lives.
        assert "EB03-003" in output
        assert "official_rarity" in output
        with db.engine.connect() as conn:
            after = (
                _rarity_column(conn), _revision(conn), _rarity_fingerprint(conn),
                _constraints(conn), _indexes(conn),
            )
        assert after == before
        assert after[1] == THIS_REVISION
    finally:
        db.close()


def test_downgrade_succeeds_when_every_rarity_is_present():
    db = _new_database("opcg_test_rarity_nullable_down")
    try:
        _seed_staging_shape(db)
        with db.engine.connect() as conn:
            before_rarities = _rarity_fingerprint(conn)
        _alembic(db.url, "upgrade", THIS_REVISION)

        output = _alembic(db.url, "downgrade", PREVIOUS_HEAD)

        assert "downgrade preflight OK" in output
        with db.engine.connect() as conn:
            assert _rarity_column(conn)[2] == "NO"
            assert _revision(conn) == PREVIOUS_HEAD
            # Values are the ones that were there before the round trip.
            assert _rarity_fingerprint(conn) == before_rarities
    finally:
        db.close()


def test_the_migration_round_trips_without_drift():
    db = _new_database("opcg_test_rarity_nullable_cycle")
    try:
        _seed_staging_shape(db)
        with db.engine.connect() as conn:
            start = (_rarity_column(conn), _constraints(conn), _indexes(conn),
                     _rarity_fingerprint(conn))

        _alembic(db.url, "upgrade", THIS_REVISION)
        _alembic(db.url, "downgrade", PREVIOUS_HEAD)
        with db.engine.connect() as conn:
            back = (_rarity_column(conn), _constraints(conn), _indexes(conn),
                    _rarity_fingerprint(conn))
        assert back == start

        _alembic(db.url, "upgrade", THIS_REVISION)
        with db.engine.connect() as conn:
            assert _rarity_column(conn)[2] == "YES"
            assert _rarity_fingerprint(conn) == start[3]
    finally:
        db.close()
