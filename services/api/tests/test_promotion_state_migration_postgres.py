"""Runs c4a7e9d15b83 for real on throwaway PostgreSQL databases.

Covers what only a live engine can prove, and what matters most about this
particular migration: that adding promotion_state leaves every existing
price_observations row byte-identical, that the new CHECK genuinely refuses a
value outside {'none', 'sale'} while permitting NULL, that no other constraint
or index on the table moved, and that the downgrade round-trips.

The fixture data is staging-shaped: Yuyu-Tei sell observations for the four
prints that were demonstrably on sale on staging (OP01-013 at 120, OP04-001
and OP04-044 at 80, OP04-090 at 220 - each captured with a SALE badge on every
one of its stored product pages) alongside ordinary Yuyu-Tei sells and
SNKRDUNK floors. Those four are the reason the no-backfill assertion is the
centre of this file: a migration that helpfully guessed would either label
them wrongly or label everything else wrongly, and both are worse than NULL.

Never touches staging. Skips when no server answers.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError

REPO_ROOT = Path(__file__).resolve().parents[1]

HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
ADMIN_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/postgres"

PREVIOUS_HEAD = "b7d31e5c9a24"
THIS_REVISION = "c4a7e9d15b83"

PROMOTION_CHECK = "ck_price_observations_promotion_state"

# (card_code, source, price_type, price_jpy). The first four are the staging
# prints whose pages carried a SALE badge every day from 2026-08-08 to
# 2026-09-01; after this migration every one of them must still read NULL.
STAGING_OBSERVATIONS = (
    ("OP01-013", "yuyutei", "sell", 120),
    ("OP04-001", "yuyutei", "sell", 80),
    ("OP04-044", "yuyutei", "sell", 80),
    ("OP04-090", "yuyutei", "sell", 220),
    ("OP01-001", "yuyutei", "sell", 34800),
    ("OP01-002", "yuyutei", "sell", 12800),
    ("OP03-099", "yuyutei", "sell", 120),
    ("OP01-001", "snkrdunk", "floor", 1000),
    ("OP01-002", "snkrdunk", "floor", 1500),
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
    """Staging-shaped observations, at the revision before this one."""
    _alembic(db.url, "upgrade", PREVIOUS_HEAD)
    with db.engine.begin() as conn:
        for name in ("yuyutei", "snkrdunk"):
            conn.execute(
                text("INSERT INTO sources (name, base_url) VALUES (:n, :u)"),
                {"n": name, "u": f"https://{name}.example.com"},
            )
        for card_code in sorted({row[0] for row in STAGING_OBSERVATIONS}):
            conn.execute(
                text(
                    "INSERT INTO cards (card_code, set_code, rarity, language) "
                    "VALUES (:code, :set_code, 'R', 'jp')"
                ),
                {"code": card_code, "set_code": card_code.split("-")[0]},
            )
        for index, (card_code, source, price_type, price_jpy) in enumerate(STAGING_OBSERVATIONS):
            conn.execute(
                text(
                    "INSERT INTO price_observations "
                    "(card_id, source_id, observed_at, price_type, price_jpy, stock_status) "
                    "VALUES ("
                    "  (SELECT id FROM cards WHERE card_code = :code),"
                    "  (SELECT id FROM sources WHERE name = :source),"
                    "  now() - (:offset || ' days')::interval, :price_type, :price_jpy, 'in_stock')"
                ),
                {
                    "code": card_code, "source": source, "price_type": price_type,
                    "price_jpy": price_jpy, "offset": index,
                },
            )


def _observation_fingerprint(conn) -> str:
    """Every column that existed before the migration, hashed in a stable
    order. If one byte of one row moves, this changes."""
    return conn.execute(
        text(
            "SELECT md5(string_agg("
            "  id || '|' || coalesce(card_id::text, '') || '|' || source_id || '|' ||"
            "  observed_at || '|' || price_type || '|' || price_jpy || '|' ||"
            "  coalesce(condition_label, '') || '|' || coalesce(stock_status, '') || '|' ||"
            "  coalesce(listing_count::text, '') || '|' || coalesce(raw_snapshot_id::text, '') || '|' ||"
            "  coalesce(candidate_id::text, '') || '|' ||"
            "  coalesce(source_card_mapping_id::text, '') || '|' ||"
            "  coalesce(card_print_id::text, ''),"
            "  ',' ORDER BY id)) FROM price_observations"
        )
    ).scalar_one()


def _promotion_column(conn) -> tuple:
    return conn.execute(
        text(
            "SELECT data_type, character_maximum_length, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_name = 'price_observations' AND column_name = 'promotion_state'"
        )
    ).one_or_none()


def _revision(conn) -> str:
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _constraints(conn) -> dict:
    return dict(
        conn.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'price_observations'::regclass ORDER BY conname"
            )
        ).all()
    )


def _indexes(conn) -> dict:
    return dict(
        conn.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'price_observations' ORDER BY indexname"
            )
        ).all()
    )


@pytest.fixture(scope="module")
def migrated():
    """The staging-shaped observations, upgraded across this revision."""
    db = _new_database("opcg_test_promotion_state")
    _seed_staging_shape(db)
    with db.engine.connect() as conn:
        before = {
            "fingerprint": _observation_fingerprint(conn),
            "count": conn.execute(text("SELECT count(*) FROM price_observations")).scalar_one(),
            "column": _promotion_column(conn),
            "constraints": _constraints(conn),
            "indexes": _indexes(conn),
        }
    _alembic(db.url, "upgrade", THIS_REVISION)
    try:
        yield db, before
    finally:
        db.close()


# --- the column the upgrade adds --------------------------------------------


def test_the_column_did_not_exist_before(migrated):
    _db, before = migrated
    assert before["column"] is None


def test_upgrade_adds_a_nullable_varchar_16(migrated):
    db, _before = migrated
    with db.engine.connect() as conn:
        data_type, length, is_nullable, default = _promotion_column(conn)
    assert data_type == "character varying"
    assert length == 16
    assert is_nullable == "YES"
    # No server default: a row that says nothing must land NULL, not 'none'.
    assert default is None


def test_upgrade_reaches_this_revision(migrated):
    db, _before = migrated
    with db.engine.connect() as conn:
        assert _revision(conn) == THIS_REVISION


# --- no backfill: the whole point -------------------------------------------


def test_every_pre_existing_column_is_byte_identical(migrated):
    db, before = migrated
    with db.engine.connect() as conn:
        assert _observation_fingerprint(conn) == before["fingerprint"]
        assert conn.execute(
            text("SELECT count(*) FROM price_observations")
        ).scalar_one() == before["count"]


def test_every_historical_row_reads_null(migrated):
    """Not 'none'. The collector never looked at these pages for a promotion,
    so the honest value is "not determined"."""
    db, _before = migrated
    with db.engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM price_observations WHERE promotion_state IS NOT NULL")
        ).scalar_one() == 0


def test_the_four_known_sale_prints_are_not_retroactively_labelled(migrated):
    """The specific staging rows a well-meaning backfill would have got wrong.
    They WERE on sale; Atlas still must not claim it classified them."""
    db, _before = migrated
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT c.card_code, o.price_jpy, o.promotion_state "
                "FROM price_observations o JOIN cards c ON c.id = o.card_id "
                "WHERE c.card_code IN ('OP01-013', 'OP04-001', 'OP04-044', 'OP04-090') "
                "ORDER BY c.card_code"
            )
        ).all()
    assert [(r[0], r[1]) for r in rows] == [
        ("OP01-013", 120), ("OP04-001", 80), ("OP04-044", 80), ("OP04-090", 220)
    ]
    assert all(r[2] is None for r in rows)


# --- nothing else on the table moved ----------------------------------------


def test_the_only_new_constraint_is_the_promotion_check(migrated):
    db, before = migrated
    with db.engine.connect() as conn:
        after = _constraints(conn)
    assert set(after) - set(before["constraints"]) == {PROMOTION_CHECK}
    assert set(before["constraints"]) - set(after) == set()
    # Every pre-existing constraint kept its exact definition.
    for name, definition in before["constraints"].items():
        assert after[name] == definition


def test_no_index_changed(migrated):
    db, before = migrated
    with db.engine.connect() as conn:
        assert _indexes(conn) == before["indexes"]


# --- the CHECK is real ------------------------------------------------------


def _insert(conn, promotion_state):
    conn.execute(
        text(
            "INSERT INTO price_observations "
            "(card_id, source_id, observed_at, price_type, price_jpy, promotion_state) "
            "VALUES ((SELECT id FROM cards LIMIT 1), (SELECT id FROM sources LIMIT 1), "
            "now(), 'sell', 999, :state)"
        ),
        {"state": promotion_state},
    )


@pytest.mark.parametrize("state", ["sale", "none", None])
def test_the_vocabulary_is_accepted(migrated, state):
    db, _before = migrated
    with db.engine.begin() as conn:
        _insert(conn, state)
        conn.execute(text("DELETE FROM price_observations WHERE price_jpy = 999"))


@pytest.mark.parametrize("state", ["clearance", "SALE", "Sale", "", "true", "discount"])
def test_anything_outside_the_vocabulary_is_refused_by_postgres(migrated, state):
    """Case-sensitive and exact. A string source_semantics has no rule for
    would be silently treated as unconstrained, which is the one failure that
    would be invisible in the published Market Index - so the database refuses
    it rather than the application hoping not to write it."""
    db, _before = migrated
    with pytest.raises(DBAPIError) as excinfo:
        with db.engine.begin() as conn:
            _insert(conn, state)
    assert PROMOTION_CHECK in str(excinfo.value)


# --- downgrade --------------------------------------------------------------


def test_downgrade_round_trips_and_leaves_the_data_untouched():
    db = _new_database("opcg_test_promotion_state_downgrade")
    try:
        _seed_staging_shape(db)
        with db.engine.connect() as conn:
            before = {
                "fingerprint": _observation_fingerprint(conn),
                "constraints": _constraints(conn),
                "indexes": _indexes(conn),
                "revision": _revision(conn),
            }

        _alembic(db.url, "upgrade", THIS_REVISION)
        _alembic(db.url, "downgrade", PREVIOUS_HEAD)

        with db.engine.connect() as conn:
            assert _promotion_column(conn) is None
            assert PROMOTION_CHECK not in _constraints(conn)
            assert _observation_fingerprint(conn) == before["fingerprint"]
            assert _constraints(conn) == before["constraints"]
            assert _indexes(conn) == before["indexes"]
            assert _revision(conn) == before["revision"]
    finally:
        db.close()
