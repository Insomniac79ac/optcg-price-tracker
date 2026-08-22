"""Runs the b6e3a9c15d47 migration for real, on a throwaway PostgreSQL
database seeded to the shape of staging (20 active+verified jp prints across
OP-01 x4, OP-02 x1, OP-03 x5, OP-04 x10 - confirmed against the canonical
staging database on 2026-08-22 through scripts/staging_db_read_check.py's
five fingerprints), and proves:

  * the four products and their aliases are seeded from Bandai evidence,
  * every one of the 20 prints backfills onto the right product,
  * an unexpected release_product_code is left NULL rather than guessed,
  * no pricing/identity field on card_prints is modified,
  * downgrade restores the pre-migration schema exactly.

Alembic is run as a subprocess per database (same reasoning as
test_alembic_url_forms_postgres.py: app.settings.settings is read once at
import time, so an in-process run would reuse a stale DATABASE_URL). Skips
outright when no server answers, and never touches the canonical staging
database - the URL is always a locally created throwaway."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

REPO_ROOT = Path(__file__).resolve().parents[1]

TEST_POSTGRES_HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
TEST_POSTGRES_PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
TEST_POSTGRES_USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
TEST_POSTGRES_PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")

ADMIN_URL = (
    f"postgresql+psycopg://{TEST_POSTGRES_USER}:{TEST_POSTGRES_PASSWORD}"
    f"@{TEST_POSTGRES_HOST}:{TEST_POSTGRES_PORT}/postgres"
)
MIGRATION_DB = "opcg_test_release_products"
MIGRATION_URL = (
    f"postgresql+psycopg://{TEST_POSTGRES_USER}:{TEST_POSTGRES_PASSWORD}"
    f"@{TEST_POSTGRES_HOST}:{TEST_POSTGRES_PORT}/{MIGRATION_DB}"
)

PREVIOUS_HEAD = "a9c4e17b6d52"
THIS_REVISION = "b6e3a9c15d47"

# (release_product_code, number of prints) - staging's real distribution.
STAGING_DISTRIBUTION = (("OP-01", 4), ("OP-02", 1), ("OP-03", 5), ("OP-04", 10))

# The identity/pricing-relevant columns that this migration must not touch.
PRINT_FIELDS_FINGERPRINT = (
    "SELECT md5(string_agg("
    "id || '|' || canonical_card_id || '|' || language || '|' || treatment || '|' || "
    "coalesce(release_product_code, '') || '|' || coalesce(artwork_key, '') || '|' || "
    "coalesce(image_url, '') || '|' || coalesce(artist, '') || '|' || "
    "verification_status || '|' || is_active, ',' ORDER BY id)) FROM card_prints"
)

CARD_PRINTS_COLUMNS = (
    "SELECT string_agg(column_name || ':' || data_type || ':' || is_nullable, ',' "
    "ORDER BY ordinal_position) FROM information_schema.columns "
    "WHERE table_name = 'card_prints'"
)


def _run_alembic(*args: str) -> str:
    env = dict(os.environ)
    env["DATABASE_URL"] = MIGRATION_URL
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"alembic {' '.join(args)} failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    return result.stdout + result.stderr


@pytest.fixture(scope="module")
def migrated_db():
    """A throwaway database at the previous head, loaded with a
    staging-shaped dataset plus one deliberately unexpected product code."""
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}"'))
            conn.execute(text(f'CREATE DATABASE "{MIGRATION_DB}"'))
    except OperationalError:
        admin.dispose()
        pytest.skip(f"No PostgreSQL server reachable at {TEST_POSTGRES_HOST}:{TEST_POSTGRES_PORT}")

    engine = create_engine(MIGRATION_URL)
    _run_alembic("upgrade", PREVIOUS_HEAD)

    with engine.begin() as conn:
        for code, count in STAGING_DISTRIBUTION:
            for n in range(count):
                card_code = f"{code.replace('-', '')}-{n:03d}"
                card_id = conn.execute(
                    text(
                        "INSERT INTO canonical_cards "
                        "(card_code, name_en, original_set_code, rarity, card_type) "
                        "VALUES (:card_code, :name, :set_code, 'R', 'Character') RETURNING id"
                    ),
                    {"card_code": card_code, "name": f"Card {card_code}", "set_code": code},
                ).scalar_one()
                conn.execute(
                    text(
                        "INSERT INTO card_prints (canonical_card_id, language, treatment, "
                        "release_product_code, artwork_key, image_url, verification_status, "
                        "is_active) VALUES (:card_id, 'jp', :treatment, :code, :artwork, "
                        ":image, 'verified', true)"
                    ),
                    {
                        "card_id": card_id,
                        "treatment": "base" if n % 2 == 0 else "parallel",
                        "code": code,
                        "artwork": f"art-{card_code}",
                        "image": f"https://img.example/{card_code}.png",
                    },
                )

        # A print this migration knows nothing about. It must survive with a
        # NULL release_product_id rather than being attached to any product.
        unexpected_card_id = conn.execute(
            text(
                "INSERT INTO canonical_cards "
                "(card_code, name_en, original_set_code, rarity, card_type) "
                "VALUES ('OP05-001', 'Future Card', 'OP-05', 'R', 'Character') RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO card_prints (canonical_card_id, language, treatment, "
                "release_product_code, artwork_key, verification_status, is_active) "
                "VALUES (:card_id, 'jp', 'base', 'OP-05', 'art-OP05-001', 'verified', true)"
            ),
            {"card_id": unexpected_card_id},
        )

    with engine.connect() as conn:
        before = {
            "print_fields": conn.execute(text(PRINT_FIELDS_FINGERPRINT)).scalar_one(),
            "columns": conn.execute(text(CARD_PRINTS_COLUMNS)).scalar_one(),
            "print_count": conn.execute(text("SELECT count(*) FROM card_prints")).scalar_one(),
        }

    output = _run_alembic("upgrade", "head")

    try:
        yield engine, before, output
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)'))
        admin.dispose()


def test_upgrade_reaches_this_revision_as_the_single_head(migrated_db):
    engine, _, _ = migrated_db

    with engine.connect() as conn:
        revisions = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()

    assert revisions == [(THIS_REVISION,)]


def test_four_bandai_jp_products_are_seeded(migrated_db):
    engine, _, _ = migrated_db

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT source_catalogue, official_code, display_name, first_seen_name, "
                "source_series_id, source_url, verification_status FROM release_products "
                "ORDER BY official_code"
            )
        ).fetchall()

    assert [r.official_code for r in rows] == ["OP-01", "OP-02", "OP-03", "OP-04"]
    assert {r.source_catalogue for r in rows} == {"bandai_jp"}
    assert {r.verification_status for r in rows} == {"verified"}
    assert [r.source_series_id for r in rows] == ["550101", "550102", "550103", "550104"]

    by_code = {r.official_code: r for r in rows}
    assert by_code["OP-01"].display_name == "ブースターパック ROMANCE DAWN【OP-01】"
    assert by_code["OP-02"].display_name == "ブースターパック 頂上決戦【OP-02】"
    assert by_code["OP-03"].display_name == "ブースターパック 強大な敵【OP-03】"
    assert by_code["OP-04"].display_name == "ブースターパック 謀略の王国【OP-04】"
    for row in rows:
        assert row.first_seen_name == row.display_name
        assert row.source_url.endswith(f"{row.official_code.replace('-', '').lower()}.php")


def test_aliases_are_seeded_with_their_kind_and_provenance(migrated_db):
    engine, _, _ = migrated_db

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT p.official_code, a.alias_kind, a.alias_name, a.source_url "
                "FROM release_product_aliases a JOIN release_products p ON p.id = a.product_id "
                "ORDER BY p.official_code, a.alias_kind, a.alias_name"
            )
        ).fetchall()

    assert len(rows) == 5
    official = [(r.official_code, r.alias_name) for r in rows if r.alias_kind == "bandai_official"]
    assert official == [
        ("OP-01", "ROMANCE DAWN"),
        ("OP-02", "頂上決戦"),
        ("OP-03", "強大な敵"),
        ("OP-04", "謀略の王国"),
    ]
    for row in rows:
        if row.alias_kind == "bandai_official":
            assert "onepiece-cardgame.com" in row.source_url

    renderings = [r for r in rows if r.alias_kind == "source_rendering"]
    assert [(r.official_code, r.alias_name, r.source_url) for r in renderings] == [
        ("OP-01", "ロマンスドーン", None)
    ]

    # The storefront rendering never became the product's published label.
    with engine.connect() as conn:
        display_name = conn.execute(
            text("SELECT display_name FROM release_products WHERE official_code = 'OP-01'")
        ).scalar_one()
    assert display_name == "ブースターパック ROMANCE DAWN【OP-01】"


def test_alias_unique_identity_is_product_kind_and_name(migrated_db):
    engine, _, _ = migrated_db

    with engine.connect() as conn:
        definition = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'uq_release_product_aliases_identity'"
            )
        ).scalar_one()

    assert definition == "UNIQUE (product_id, alias_kind, alias_name)"


def test_official_code_uniqueness_is_scoped_to_the_catalogue(migrated_db):
    engine, _, _ = migrated_db

    with engine.connect() as conn:
        index = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'uq_release_products_catalogue_official_code'"
            )
        ).scalar_one()

    assert "UNIQUE INDEX" in index
    assert "(source_catalogue, official_code)" in index
    assert "WHERE (official_code IS NOT NULL)" in index


def test_jp_and_en_op01_can_coexist_after_the_migration(migrated_db):
    """The dangerous future case, against the real migrated schema."""
    engine, _, _ = migrated_db

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO release_products (source_catalogue, official_code, display_name, "
                "first_seen_name, source_series_id, source_url, verification_status) VALUES "
                "('bandai_en', 'OP-01', 'BOOSTER PACK -ROMANCE DAWN- [OP-01]', "
                "'BOOSTER PACK -ROMANCE DAWN- [OP-01]', '569101', "
                "'https://en.onepiece-cardgame.com/products/boosters/op01.php', 'needs_review')"
            )
        )

    with engine.connect() as conn:
        catalogues = conn.execute(
            text(
                "SELECT source_catalogue FROM release_products WHERE official_code = 'OP-01' "
                "ORDER BY source_catalogue"
            )
        ).fetchall()

    assert catalogues == [("bandai_en",), ("bandai_jp",)]

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM release_products WHERE source_catalogue = 'bandai_en'"))


def test_all_twenty_staging_shaped_prints_backfill(migrated_db):
    engine, before, _ = migrated_db

    with engine.connect() as conn:
        mapped = conn.execute(
            text(
                "SELECT count(*) FROM card_prints WHERE release_product_id IS NOT NULL "
                "AND is_active AND verification_status = 'verified'"
            )
        ).scalar_one()
        distribution = conn.execute(
            text(
                "SELECT p.official_code, count(*) FROM card_prints c "
                "JOIN release_products p ON p.id = c.release_product_id "
                "GROUP BY p.official_code ORDER BY p.official_code"
            )
        ).fetchall()

    assert mapped == 20
    assert [tuple(row) for row in distribution] == list(STAGING_DISTRIBUTION)
    # 20 staging-shaped prints + the one unexpected-code print.
    assert before["print_count"] == 21


def test_every_print_maps_to_the_product_its_code_names(migrated_db):
    engine, _, _ = migrated_db

    with engine.connect() as conn:
        mismatches = conn.execute(
            text(
                "SELECT count(*) FROM card_prints c JOIN release_products p "
                "ON p.id = c.release_product_id WHERE c.release_product_code <> p.official_code"
            )
        ).scalar_one()

    assert mismatches == 0


def test_an_unexpected_code_is_left_null_and_reported(migrated_db):
    engine, _, output = migrated_db

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT release_product_code, release_product_id FROM card_prints "
                "WHERE release_product_code = 'OP-05'"
            )
        ).one()

    assert row.release_product_id is None
    assert "WARNING" in output
    assert "'OP-05': 1" in output


def test_no_card_print_pricing_or_identity_field_changed(migrated_db):
    engine, before, _ = migrated_db

    with engine.connect() as conn:
        after = conn.execute(text(PRINT_FIELDS_FINGERPRINT)).scalar_one()

    assert after == before["print_fields"]


def test_release_product_id_stays_nullable(migrated_db):
    engine, _, _ = migrated_db

    with engine.connect() as conn:
        nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'card_prints' AND column_name = 'release_product_id'"
            )
        ).scalar_one()

    assert nullable == "YES"


def test_the_fk_is_on_delete_restrict(migrated_db):
    engine, _, _ = migrated_db

    with engine.connect() as conn:
        definition = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'fk_card_prints_release_product_id_release_products'"
            )
        ).scalar_one()

    assert "FOREIGN KEY (release_product_id) REFERENCES release_products(id)" in definition
    assert "ON DELETE RESTRICT" in definition


def test_downgrade_restores_the_pre_migration_shape(migrated_db):
    engine, before, _ = migrated_db

    _run_alembic("downgrade", PREVIOUS_HEAD)

    with engine.connect() as conn:
        assert conn.execute(text(CARD_PRINTS_COLUMNS)).scalar_one() == before["columns"]
        assert conn.execute(text(PRINT_FIELDS_FINGERPRINT)).scalar_one() == before["print_fields"]
        assert conn.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_name IN ('release_products', 'release_product_aliases')"
            )
        ).scalar_one() == 0
        assert conn.execute(
            text("SELECT count(*) FROM pg_indexes WHERE indexname LIKE '%release_product%'")
        ).scalar_one() == 0
        assert conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == PREVIOUS_HEAD

    # Leave the database at head again so ordering between test files (and a
    # re-run of this module) never depends on this test having run.
    _run_alembic("upgrade", "head")
