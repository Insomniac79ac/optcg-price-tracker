"""Runs d4b17c9e2a83 for real on throwaway PostgreSQL databases.

Covers what only a live engine can prove: the final DDL, the identity
behaviour under it, that both preflights refuse the data they must refuse,
and - most importantly - that a refused run leaves NO partial DDL behind,
because a half-applied identity transition is the failure mode this migration
is shaped to avoid.

The fixture data is staging-shaped: 20 active+verified jp prints across
OP-01 x4, OP-02 x1, OP-03 x5, OP-04 x10, with treatments 13 normal / 7
parallel and artwork variants base=13 / p1=5 / p2=2, matching the canonical
staging database as read read-only on 2026-08-22.

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

PREVIOUS_HEAD = "c2f7b48a91d6"
THIS_REVISION = "d4b17c9e2a83"

CARD_LIST = "https://www.onepiece-cardgame.com/images/cardlist/card"

# (card_code, release_product_code, treatment, artwork basename)
STAGING_PRINTS = (
    ("OP01-001", "OP-01", "parallel", "OP01-001_p2.png"),
    ("OP01-002", "OP-01", "parallel", "OP01-002_p1.png"),
    ("OP01-013", "OP-01", "parallel", "OP01-013_p2.png"),
    ("OP01-013", "OP-01", "normal", "OP01-013.png"),
    ("OP02-013", "OP-02", "normal", "OP02-013.png"),
    ("OP03-001", "OP-03", "parallel", "OP03-001_p1.png"),
    ("OP03-001", "OP-03", "normal", "OP03-001.png"),
    ("OP03-013", "OP-03", "parallel", "OP03-013_p1.png"),
    ("OP03-013", "OP-03", "normal", "OP03-013.png"),
    ("OP03-099", "OP-03", "normal", "OP03-099.png"),
    ("OP04-001", "OP-04", "parallel", "OP04-001_p1.png"),
    ("OP04-001", "OP-04", "normal", "OP04-001.png"),
    ("OP04-044", "OP-04", "parallel", "OP04-044_p1.png"),
    ("OP04-044", "OP-04", "normal", "OP04-044.png"),
    ("OP04-083", "OP-04", "normal", "OP04-083.png"),
    ("OP04-007", "OP-04", "normal", "OP04-007.png"),
    ("OP04-090", "OP-04", "normal", "OP04-090.png"),
    ("OP04-118", "OP-04", "normal", "OP04-118.png"),
    ("OP04-024", "OP-04", "normal", "OP04-024.png"),
    ("OP04-006", "OP-04", "normal", "OP04-006.png"),
)

ROW_FINGERPRINT = (
    "SELECT md5(string_agg("
    "id || '|' || canonical_card_id || '|' || language || '|' || coalesce(treatment, '~') || "
    "'|' || coalesce(release_product_code, '') || '|' || coalesce(release_product_id::text, '') "
    "|| '|' || coalesce(artwork_key, '') || '|' || coalesce(official_artwork_variant, '') || "
    "'|' || coalesce(image_url, '') || '|' || verification_status || '|' || is_active, "
    "',' ORDER BY id)) FROM card_prints"
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


def _identity_state(conn) -> dict:
    return {
        "treatment_nullable": conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'card_prints' AND column_name = 'treatment'"
            )
        ).scalar_one(),
        "index": conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'uq_card_prints_active_verified_identity'"
            )
        ).scalar_one(),
        "verified_check": conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_card_prints_verified_requires_fields'"
            )
        ).scalar_one(),
    }


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


def _seed_staging_shape(db: _Database, *, skip_variant_for: str | None = None,
                        duplicate_identity: bool = False) -> None:
    _alembic(db.url, "upgrade", PREVIOUS_HEAD)
    with db.engine.begin() as conn:
        card_ids: dict[str, int] = {}
        for card_code, product_code, treatment, basename in STAGING_PRINTS:
            if card_code not in card_ids:
                card_ids[card_code] = conn.execute(
                    text(
                        "INSERT INTO canonical_cards "
                        "(card_code, name_en, original_set_code, rarity, card_type) "
                        "VALUES (:code, :name, :set_code, 'R', 'Character') RETURNING id"
                    ),
                    {"code": card_code, "name": f"Card {card_code}", "set_code": product_code},
                ).scalar_one()
            variant = "base" if "_p" not in basename else "p" + basename.split("_p")[1][:-4]
            if skip_variant_for == card_code and variant != "base":
                variant = None
            if duplicate_identity and card_code == "OP01-013":
                # Two prints of one card, same product, same artwork variant:
                # identical under the new key, distinct under the old one.
                variant = "base"
            conn.execute(
                text(
                    "INSERT INTO card_prints (canonical_card_id, language, treatment, "
                    "release_product_code, artwork_key, official_artwork_variant, image_url, "
                    "verification_status, is_active, release_product_id) VALUES (:card_id, 'jp', "
                    ":treatment, :code, :artwork_key, :variant, :image_url, 'verified', true, "
                    "(SELECT rp.id FROM release_products rp WHERE rp.source_catalogue = "
                    "'bandai_jp' AND rp.official_code = :product_lookup))"
                ),
                {
                    "card_id": card_ids[card_code],
                    "treatment": treatment,
                    "code": product_code,
                    "product_lookup": product_code,
                    "artwork_key": f"sha-{basename}",
                    "variant": variant,
                    "image_url": f"{CARD_LIST}/{basename}?260630",
                },
            )


@pytest.fixture(scope="module")
def migrated():
    """The happy path: staging-shaped data, upgraded."""
    db = _new_database("opcg_test_identity_ok")
    _seed_staging_shape(db)

    with db.engine.connect() as conn:
        before = {
            "fingerprint": conn.execute(text(ROW_FINGERPRINT)).scalar_one(),
            "count": conn.execute(text("SELECT count(*) FROM card_prints")).scalar_one(),
            "state": _identity_state(conn),
        }
    output = _alembic(db.url, "upgrade", THIS_REVISION)
    try:
        yield db, before, output
    finally:
        db.close()


# --- the current 20 prints ------------------------------------------------


def test_preflight_reports_the_twenty_prints(migrated):
    _, _, output = migrated

    assert "preflight OK - 20 active+verified card_prints" in output
    assert "ABORTED" not in output


def test_no_row_was_rewritten(migrated):
    db, before, _ = migrated

    with db.engine.connect() as conn:
        assert conn.execute(text(ROW_FINGERPRINT)).scalar_one() == before["fingerprint"]
        assert conn.execute(text("SELECT count(*) FROM card_prints")).scalar_one() == 20
        assert before["count"] == 20


def test_treatments_products_and_variants_are_untouched(migrated):
    db, _, _ = migrated

    with db.engine.connect() as conn:
        treatments = conn.execute(
            text("SELECT treatment, count(*) FROM card_prints GROUP BY 1 ORDER BY 1")
        ).fetchall()
        variants = conn.execute(
            text("SELECT official_artwork_variant, count(*) FROM card_prints GROUP BY 1 ORDER BY 1")
        ).fetchall()
        products = conn.execute(
            text(
                "SELECT rp.official_code, count(*) FROM card_prints cp "
                "JOIN release_products rp ON rp.id = cp.release_product_id GROUP BY 1 ORDER BY 1"
            )
        ).fetchall()

    assert [tuple(r) for r in treatments] == [("normal", 13), ("parallel", 7)]
    assert [tuple(r) for r in variants] == [("base", 13), ("p1", 5), ("p2", 2)]
    assert [tuple(r) for r in products] == [("OP-01", 4), ("OP-02", 1), ("OP-03", 5), ("OP-04", 10)]


def test_the_final_schema(migrated):
    db, _, _ = migrated

    with db.engine.connect() as conn:
        state = _identity_state(conn)

    assert state["treatment_nullable"] == "YES"
    assert (
        "btree (canonical_card_id, language, release_product_id, official_artwork_variant)"
        in state["index"]
    )
    assert "WHERE ((is_active = true) AND ((verification_status)::text = 'verified'::text))" in (
        state["index"]
    )
    for gone in ("treatment,", "release_product_code", "artwork_key"):
        assert gone not in state["index"].split("WHERE")[0]

    check = state["verified_check"]
    assert "release_product_id IS NOT NULL" in check
    assert "official_artwork_variant IS NOT NULL" in check
    assert "artwork_key IS NOT NULL" in check
    assert "release_product_code" not in check


def test_a_future_verified_row_with_null_treatment_is_accepted(migrated):
    db, _, _ = migrated

    with db.engine.begin() as conn:
        card_id = conn.execute(
            text(
                "INSERT INTO canonical_cards (card_code, name_en, original_set_code, rarity, "
                "card_type) VALUES ('OP05-001', 'Future', 'OP-05', 'R', 'Character') RETURNING id"
            )
        ).scalar_one()
        print_id = conn.execute(
            text(
                "INSERT INTO card_prints (canonical_card_id, language, treatment, artwork_key, "
                "official_artwork_variant, verification_status, is_active, release_product_id) "
                "VALUES (:card_id, 'jp', NULL, 'sha-future', 'base', 'verified', true, "
                "(SELECT id FROM release_products ORDER BY id LIMIT 1)) RETURNING id"
            ),
            {"card_id": card_id},
        ).scalar_one()

    with db.engine.connect() as conn:
        row = conn.execute(
            text("SELECT treatment, verification_status FROM card_prints WHERE id = :id"),
            {"id": print_id},
        ).one()
    assert row.treatment is None
    assert row.verification_status == "verified"

    # ... and it takes part in identity like any other row.
    with pytest.raises(IntegrityError) as excinfo, db.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO card_prints (canonical_card_id, language, treatment, artwork_key, "
                "official_artwork_variant, verification_status, is_active, release_product_id) "
                "VALUES (:card_id, 'jp', 'parallel', 'sha-dup', 'base', 'verified', true, "
                "(SELECT id FROM release_products ORDER BY id LIMIT 1))"
            ),
            {"card_id": card_id},
        )
    assert "uq_card_prints_active_verified_identity" in str(excinfo.value)

    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM card_prints WHERE canonical_card_id = :id"), {"id": card_id})
        conn.execute(text("DELETE FROM canonical_cards WHERE id = :id"), {"id": card_id})


# --- fail-closed preflights ------------------------------------------------


def test_upgrade_aborts_when_a_verified_print_has_no_artwork_variant():
    db = _new_database("opcg_test_identity_missing_variant")
    try:
        _seed_staging_shape(db, skip_variant_for="OP01-001")
        with db.engine.connect() as conn:
            before = _identity_state(conn)

        output = _alembic(db.url, "upgrade", THIS_REVISION, expect_success=False)

        assert "ABORTED" in output
        assert "official_artwork_variant" in output
        with db.engine.connect() as conn:
            after = _identity_state(conn)
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        # No partial DDL: the whole identity transition rolled back.
        assert after == before
        assert after["treatment_nullable"] == "NO"
        assert revision == PREVIOUS_HEAD
    finally:
        db.close()


def test_upgrade_aborts_when_a_verified_print_has_no_product():
    db = _new_database("opcg_test_identity_missing_product")
    try:
        _seed_staging_shape(db)
        with db.engine.begin() as conn:
            conn.execute(
                text("UPDATE card_prints SET release_product_id = NULL WHERE id = "
                     "(SELECT min(id) FROM card_prints)")
            )
        with db.engine.connect() as conn:
            before = _identity_state(conn)

        output = _alembic(db.url, "upgrade", THIS_REVISION, expect_success=False)

        assert "ABORTED" in output
        assert "release_product_id" in output
        with db.engine.connect() as conn:
            assert _identity_state(conn) == before
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == PREVIOUS_HEAD
    finally:
        db.close()


def test_upgrade_aborts_on_a_pre_existing_duplicate_identity():
    db = _new_database("opcg_test_identity_duplicate")
    try:
        _seed_staging_shape(db, duplicate_identity=True)
        with db.engine.connect() as conn:
            before = _identity_state(conn)

        output = _alembic(db.url, "upgrade", THIS_REVISION, expect_success=False)

        assert "ABORTED" in output
        assert "duplicate group" in output
        # Nothing was deduplicated, deactivated or rewritten.
        with db.engine.connect() as conn:
            assert _identity_state(conn) == before
            assert conn.execute(text("SELECT count(*) FROM card_prints")).scalar_one() == 20
            assert conn.execute(
                text("SELECT count(*) FROM card_prints WHERE is_active")
            ).scalar_one() == 20
    finally:
        db.close()


# --- downgrade -------------------------------------------------------------


def test_downgrade_restores_the_previous_contract_on_compatible_data():
    db = _new_database("opcg_test_identity_downgrade_ok")
    try:
        _seed_staging_shape(db)
        with db.engine.connect() as conn:
            before = _identity_state(conn)
            fingerprint = conn.execute(text(ROW_FINGERPRINT)).scalar_one()
        _alembic(db.url, "upgrade", THIS_REVISION)

        output = _alembic(db.url, "downgrade", PREVIOUS_HEAD)

        assert "downgrade preflight OK" in output
        with db.engine.connect() as conn:
            assert _identity_state(conn) == before
            assert conn.execute(text(ROW_FINGERPRINT)).scalar_one() == fingerprint
            # The infrastructure this migration activates is left in place.
            assert conn.execute(text("SELECT count(*) FROM release_products")).scalar_one() == 4
            assert conn.execute(
                text("SELECT count(official_artwork_variant) FROM card_prints")
            ).scalar_one() == 20
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == PREVIOUS_HEAD
    finally:
        db.close()


def test_downgrade_aborts_when_a_row_has_a_null_treatment():
    db = _new_database("opcg_test_identity_downgrade_blocked")
    try:
        _seed_staging_shape(db)
        _alembic(db.url, "upgrade", THIS_REVISION)
        with db.engine.begin() as conn:
            conn.execute(
                text("UPDATE card_prints SET treatment = NULL WHERE id = "
                     "(SELECT min(id) FROM card_prints)")
            )
        with db.engine.connect() as conn:
            before = _identity_state(conn)
            fingerprint = conn.execute(text(ROW_FINGERPRINT)).scalar_one()

        output = _alembic(db.url, "downgrade", PREVIOUS_HEAD, expect_success=False)

        assert "DOWNGRADE ABORTED" in output
        assert "treatment IS NULL" in output
        assert "cannot be invented" in output
        with db.engine.connect() as conn:
            # No partial DDL and no coerced data.
            assert _identity_state(conn) == before
            assert conn.execute(text(ROW_FINGERPRINT)).scalar_one() == fingerprint
            assert conn.execute(
                text("SELECT count(*) FROM card_prints WHERE treatment IS NULL")
            ).scalar_one() == 1
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == THIS_REVISION
    finally:
        db.close()
