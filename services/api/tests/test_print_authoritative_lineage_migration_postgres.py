"""Runs c9f31e2a7d04 for real on throwaway PostgreSQL databases.

Three things only a live engine can prove, and all three are the migration's
stated contract rather than its DDL:

  * upgrading over legacy (card_id-populated) rows changes no value - the
    migration only widens what is permitted, and there is no backfill in
    either direction;
  * the downgrade round-trips cleanly while every row still has a legacy
    card_id, which is the staging-shaped case;
  * once a print-authoritative row exists it refuses outright rather than
    inventing a legacy `cards` row to satisfy NOT NULL.

Skips when no server answers. Never touches staging."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

REPO_ROOT = Path(__file__).resolve().parents[1]

HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
ADMIN_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/postgres"

PREVIOUS_HEAD = "8c31a5f0d2b7"
THIS_REVISION = "c9f31e2a7d04"

# The two constraints that swap places, plus the paired CHECK that must not.
OLD_UNIQUE = "uq_source_card_mappings_lineage_identity"
NEW_UNIQUE = "uq_source_card_mappings_print_lineage_identity"
OLD_FK = "fk_price_observations_mapping_print_card_source"
NEW_FK = "fk_price_observations_mapping_print_source"
PAIRED_CHECK = "ck_price_observations_lineage_paired"

# Legacy shape: every mapping and observation names a legacy Card, which is
# how all 74 mappings / 642 observations look today.
LEGACY_FINGERPRINT = (
    "SELECT md5("
    "coalesce((SELECT string_agg(id || '|' || coalesce(card_id::text, '~') || '|' || source_id "
    "|| '|' || coalesce(card_print_id::text, '~') || '|' || source_card_id, ',' ORDER BY id) "
    "FROM source_card_mappings), '') || '#' || "
    "coalesce((SELECT string_agg(id || '|' || coalesce(card_id::text, '~') || '|' || source_id "
    "|| '|' || coalesce(source_card_mapping_id::text, '~') || '|' || "
    "coalesce(card_print_id::text, '~') || '|' || price_jpy, ',' ORDER BY id) "
    "FROM price_observations), ''))"
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


def _lineage_state(conn) -> dict:
    """Everything the migration is allowed to move, read back from the
    catalogue rather than from the model definitions."""
    nullability = dict(
        conn.execute(
            text(
                "SELECT table_name || '.' || column_name, is_nullable "
                "FROM information_schema.columns "
                "WHERE column_name = 'card_id' "
                "AND table_name IN ('source_card_mappings', 'price_observations')"
            )
        ).all()
    )
    constraints = dict(
        conn.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = ANY(:names)"
            ),
            {"names": [OLD_UNIQUE, NEW_UNIQUE, OLD_FK, NEW_FK, PAIRED_CHECK]},
        ).all()
    )
    return {"nullability": nullability, "constraints": constraints}


def _revision(conn) -> str:
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


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


def _seed_legacy_rows(db: _Database) -> None:
    """Two mappings and three observations, all carrying a legacy card_id -
    one pre-lineage pair, one print-linked pair, and one untagged legacy
    observation."""
    _alembic(db.url, "upgrade", PREVIOUS_HEAD)
    with db.engine.begin() as conn:
        card_id = conn.execute(
            text(
                "INSERT INTO cards (card_code, name_en, set_code, rarity, language) "
                "VALUES ('OP01-013', 'Nico Robin', 'OP01', 'R', 'en') RETURNING id"
            )
        ).scalar_one()
        source_id = conn.execute(
            text(
                "INSERT INTO sources (name, base_url) "
                "VALUES ('yuyutei', 'https://yuyutei.example') RETURNING id"
            )
        ).scalar_one()
        canonical_id = conn.execute(
            text(
                "INSERT INTO canonical_cards (card_code, name_en, original_set_code, rarity, "
                "card_type) VALUES ('OP01-013', 'Nico Robin', 'OP01', 'R', 'Character') "
                "RETURNING id"
            )
        ).scalar_one()
        print_id = conn.execute(
            text(
                "INSERT INTO card_prints (canonical_card_id, language, treatment, "
                "verification_status, is_active) "
                "VALUES (:card, 'jp', 'normal', 'unverified', true) RETURNING id"
            ),
            {"card": canonical_id},
        ).scalar_one()

        legacy_mapping_id = conn.execute(
            text(
                "INSERT INTO source_card_mappings (card_id, source_id, source_card_id) "
                "VALUES (:card, :source, 'legacy-listing') RETURNING id"
            ),
            {"card": card_id, "source": source_id},
        ).scalar_one()
        print_mapping_id = conn.execute(
            text(
                "INSERT INTO source_card_mappings "
                "(card_id, source_id, card_print_id, source_card_id) "
                "VALUES (:card, :source, :print, 'print-listing') RETURNING id"
            ),
            {"card": card_id, "source": source_id, "print": print_id},
        ).scalar_one()
        assert legacy_mapping_id != print_mapping_id

        conn.execute(
            text(
                "INSERT INTO price_observations (card_id, source_id, price_type, price_jpy) "
                "VALUES (:card, :source, 'market', 1200)"
            ),
            {"card": card_id, "source": source_id},
        )
        conn.execute(
            text(
                "INSERT INTO price_observations (card_id, source_id, price_type, price_jpy, "
                "source_card_mapping_id, card_print_id) "
                "VALUES (:card, :source, 'market', 1300, :mapping, :print)"
            ),
            {
                "card": card_id,
                "source": source_id,
                "mapping": print_mapping_id,
                "print": print_id,
            },
        )
        conn.execute(
            text(
                "INSERT INTO price_observations (card_id, source_id, price_type, price_jpy, "
                "source_card_mapping_id, card_print_id) "
                "VALUES (:card, :source, 'sell', 1400, :mapping, :print)"
            ),
            {
                "card": card_id,
                "source": source_id,
                "mapping": print_mapping_id,
                "print": print_id,
            },
        )


def _add_print_authoritative_rows(db: _Database) -> None:
    """A mapping and an observation with no legacy card at all - only
    possible after the upgrade, and exactly what the downgrade must refuse."""
    with db.engine.begin() as conn:
        source_id = conn.execute(
            text("SELECT id FROM sources ORDER BY id LIMIT 1")
        ).scalar_one()
        print_id = conn.execute(
            text("SELECT id FROM card_prints ORDER BY id LIMIT 1")
        ).scalar_one()
        mapping_id = conn.execute(
            text(
                "INSERT INTO source_card_mappings "
                "(card_id, source_id, card_print_id, source_card_id) "
                "VALUES (NULL, :source, :print, 'print-authoritative') RETURNING id"
            ),
            {"source": source_id, "print": print_id},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO price_observations (card_id, source_id, price_type, price_jpy, "
                "source_card_mapping_id, card_print_id) "
                "VALUES (NULL, :source, 'market', 1500, :mapping, :print)"
            ),
            {"source": source_id, "mapping": mapping_id, "print": print_id},
        )


@pytest.fixture(scope="module")
def upgraded():
    """Legacy-shaped data, upgraded once."""
    db = _new_database("opcg_test_print_lineage_upgrade")
    _seed_legacy_rows(db)
    with db.engine.connect() as conn:
        before = {
            "fingerprint": conn.execute(text(LEGACY_FINGERPRINT)).scalar_one(),
            "state": _lineage_state(conn),
        }
    _alembic(db.url, "upgrade", THIS_REVISION)
    try:
        yield db, before
    finally:
        db.close()


# --- upgrade over legacy rows ----------------------------------------------


def test_upgrade_preserves_every_legacy_value(upgraded):
    db, before = upgraded

    with db.engine.connect() as conn:
        assert conn.execute(text(LEGACY_FINGERPRINT)).scalar_one() == before["fingerprint"]
        assert conn.execute(
            text("SELECT count(*) FROM source_card_mappings WHERE card_id IS NULL")
        ).scalar_one() == 0
        assert conn.execute(
            text("SELECT count(*) FROM price_observations WHERE card_id IS NULL")
        ).scalar_one() == 0
        assert _revision(conn) == THIS_REVISION


def test_upgrade_makes_card_id_nullable_on_both_tables(upgraded):
    db, before = upgraded

    assert before["state"]["nullability"] == {
        "source_card_mappings.card_id": "NO",
        "price_observations.card_id": "NO",
    }
    with db.engine.connect() as conn:
        assert _lineage_state(conn)["nullability"] == {
            "source_card_mappings.card_id": "YES",
            "price_observations.card_id": "YES",
        }


def test_upgrade_swaps_the_composite_key_for_the_print_authoritative_one(upgraded):
    db, before = upgraded

    assert set(before["state"]["constraints"]) == {OLD_UNIQUE, OLD_FK, PAIRED_CHECK}
    with db.engine.connect() as conn:
        constraints = _lineage_state(conn)["constraints"]

    assert set(constraints) == {NEW_UNIQUE, NEW_FK, PAIRED_CHECK}
    assert "(id, card_print_id, source_id)" in constraints[NEW_UNIQUE]
    assert "card_id" not in constraints[NEW_UNIQUE]
    assert "card_id" not in constraints[NEW_FK]
    assert "ON DELETE RESTRICT" in constraints[NEW_FK]
    # The paired CHECK is not part of this tranche and must survive unchanged.
    assert constraints[PAIRED_CHECK] == before["state"]["constraints"][PAIRED_CHECK]


# --- downgrade -------------------------------------------------------------


def test_downgrade_round_trips_while_every_row_has_a_legacy_card_id():
    db = _new_database("opcg_test_print_lineage_downgrade_ok")
    try:
        _seed_legacy_rows(db)
        with db.engine.connect() as conn:
            before = _lineage_state(conn)
            fingerprint = conn.execute(text(LEGACY_FINGERPRINT)).scalar_one()
        _alembic(db.url, "upgrade", THIS_REVISION)

        _alembic(db.url, "downgrade", PREVIOUS_HEAD)

        with db.engine.connect() as conn:
            assert _lineage_state(conn) == before
            assert conn.execute(text(LEGACY_FINGERPRINT)).scalar_one() == fingerprint
            assert _revision(conn) == PREVIOUS_HEAD
    finally:
        db.close()


def test_re_upgrade_after_a_valid_downgrade_succeeds():
    db = _new_database("opcg_test_print_lineage_reupgrade")
    try:
        _seed_legacy_rows(db)
        _alembic(db.url, "upgrade", THIS_REVISION)
        with db.engine.connect() as conn:
            upgraded_state = _lineage_state(conn)
            fingerprint = conn.execute(text(LEGACY_FINGERPRINT)).scalar_one()
        _alembic(db.url, "downgrade", PREVIOUS_HEAD)

        _alembic(db.url, "upgrade", THIS_REVISION)

        with db.engine.connect() as conn:
            assert _lineage_state(conn) == upgraded_state
            assert conn.execute(text(LEGACY_FINGERPRINT)).scalar_one() == fingerprint
            assert _revision(conn) == THIS_REVISION
    finally:
        db.close()


def test_downgrade_refuses_once_a_print_authoritative_row_exists():
    db = _new_database("opcg_test_print_lineage_downgrade_blocked")
    try:
        _seed_legacy_rows(db)
        _alembic(db.url, "upgrade", THIS_REVISION)
        _add_print_authoritative_rows(db)
        with db.engine.connect() as conn:
            before = _lineage_state(conn)
            fingerprint = conn.execute(text(LEGACY_FINGERPRINT)).scalar_one()

        output = _alembic(db.url, "downgrade", PREVIOUS_HEAD, expect_success=False)

        assert "Cannot downgrade" in output
        assert "card_id IS NULL" in output
        assert "source_card_mappings" in output
        with db.engine.connect() as conn:
            # No partial DDL, no invented legacy card, still at this revision.
            assert _lineage_state(conn) == before
            assert conn.execute(text(LEGACY_FINGERPRINT)).scalar_one() == fingerprint
            assert conn.execute(
                text("SELECT count(*) FROM source_card_mappings WHERE card_id IS NULL")
            ).scalar_one() == 1
            assert conn.execute(
                text("SELECT count(*) FROM price_observations WHERE card_id IS NULL")
            ).scalar_one() == 1
            assert _revision(conn) == THIS_REVISION
    finally:
        db.close()
