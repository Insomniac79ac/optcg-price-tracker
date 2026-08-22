"""Runs c2f7b48a91d6 for real on a throwaway PostgreSQL database loaded with
the exact shape of staging - the same 15 canonical card codes, the same 20
Card List image URLs (cache buster and all), and the same treatments, read
read-only from the canonical staging database on 2026-08-22 through
scripts/staging_db_read_check.py's five fingerprints.

Proves the 20 rows all resolve, that each value matches its own asset
basename, that nothing else on card_prints moves, and that downgrade restores
the pre-migration shape without disturbing the ReleaseProduct tables.

Never touches canonical staging: the URL is always a locally created
throwaway. Skips outright when no server answers."""

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
MIGRATION_DB = "opcg_test_artwork_variant"
MIGRATION_URL = (
    f"postgresql+psycopg://{TEST_POSTGRES_USER}:{TEST_POSTGRES_PASSWORD}"
    f"@{TEST_POSTGRES_HOST}:{TEST_POSTGRES_PORT}/{MIGRATION_DB}"
)

PREVIOUS_HEAD = "b6e3a9c15d47"
THIS_REVISION = "c2f7b48a91d6"

CARD_LIST = "https://www.onepiece-cardgame.com/images/cardlist/card"
CACHE_BUSTER = "?260630"

# (card_code, release_product_code, treatment, asset basename) - staging's own
# 20 rows, in id order.
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

EXPECTED_DISTRIBUTION = [("base", 13), ("p1", 5), ("p2", 2)]

# Everything this migration must leave exactly as it found it.
UNTOUCHED_FIELDS_FINGERPRINT = (
    "SELECT md5(string_agg("
    "id || '|' || canonical_card_id || '|' || language || '|' || treatment || '|' || "
    "coalesce(release_product_code, '') || '|' || coalesce(release_product_id::text, '') || "
    "'|' || coalesce(artwork_key, '') || '|' || coalesce(image_url, '') || '|' || "
    "coalesce(artist, '') || '|' || verification_status || '|' || is_active, "
    "',' ORDER BY id)) FROM card_prints"
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
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{MIGRATION_DB}"'))
    except OperationalError:
        admin.dispose()
        pytest.skip(f"No PostgreSQL server reachable at {TEST_POSTGRES_HOST}:{TEST_POSTGRES_PORT}")

    engine = create_engine(MIGRATION_URL)
    _run_alembic("upgrade", PREVIOUS_HEAD)

    with engine.begin() as conn:
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
            conn.execute(
                text(
                    "INSERT INTO card_prints (canonical_card_id, language, treatment, "
                    "release_product_code, artwork_key, image_url, verification_status, "
                    "is_active, release_product_id) VALUES (:card_id, 'jp', :treatment, "
                    ":code, :artwork_key, :image_url, 'verified', true, "
                    "(SELECT rp.id FROM release_products rp WHERE "
                    "rp.source_catalogue = 'bandai_jp' AND rp.official_code = :product_lookup))"
                ),
                {
                    "card_id": card_ids[card_code],
                    "treatment": treatment,
                    "code": product_code,
                    "product_lookup": product_code,
                    # A SHA-256-shaped key, deliberately unrelated to the
                    # basename: artwork_key is the bytes' digest, the variant
                    # is the address.
                    "artwork_key": f"{abs(hash(basename)):064x}"[:64],
                    "image_url": f"{CARD_LIST}/{basename}{CACHE_BUSTER}",
                },
            )

    with engine.connect() as conn:
        before = {
            "untouched": conn.execute(text(UNTOUCHED_FIELDS_FINGERPRINT)).scalar_one(),
            "columns": conn.execute(text(CARD_PRINTS_COLUMNS)).scalar_one(),
            "unique_index": conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'uq_card_prints_active_verified_identity'"
                )
            ).scalar_one(),
            "products": conn.execute(text("SELECT count(*) FROM release_products")).scalar_one(),
            "aliases": conn.execute(
                text("SELECT count(*) FROM release_product_aliases")
            ).scalar_one(),
        }
        assert conn.execute(text("SELECT count(*) FROM card_prints")).scalar_one() == 20

    output = _run_alembic("upgrade", "head")

    try:
        yield engine, before, output
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{MIGRATION_DB}" WITH (FORCE)'))
        admin.dispose()


def test_upgrade_reaches_this_revision(migrated_db):
    engine, _, _ = migrated_db

    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).fetchall() == [
            (THIS_REVISION,)
        ]


def test_all_twenty_prints_resolve(migrated_db):
    engine, _, output = migrated_db

    with engine.connect() as conn:
        resolved = conn.execute(
            text("SELECT count(*) FROM card_prints WHERE official_artwork_variant IS NOT NULL")
        ).scalar_one()

    assert resolved == 20
    assert "resolved 20/20 card_prints rows" in output
    assert "WARNING" not in output


def test_distribution_matches_the_current_staging_assets(migrated_db):
    engine, _, _ = migrated_db

    with engine.connect() as conn:
        distribution = conn.execute(
            text(
                "SELECT official_artwork_variant, count(*) FROM card_prints "
                "GROUP BY 1 ORDER BY 1"
            )
        ).fetchall()

    assert [tuple(row) for row in distribution] == EXPECTED_DISTRIBUTION


def test_every_value_matches_its_own_asset_basename(migrated_db):
    engine, _, _ = migrated_db
    expected_by_basename = {
        basename: ("base" if "_p" not in basename else "p" + basename.split("_p")[1][:-4])
        for _, _, _, basename in STAGING_PRINTS
    }

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT cp.image_url, cp.official_artwork_variant, cc.card_code "
                "FROM card_prints cp JOIN canonical_cards cc ON cc.id = cp.canonical_card_id "
                "ORDER BY cp.id"
            )
        ).fetchall()

    assert len(rows) == 20
    for image_url, variant, card_code in rows:
        basename = image_url.split("/")[-1].split("?")[0]
        assert variant == expected_by_basename[basename]
        # The basename always names the print's own card.
        assert basename.startswith(card_code)


def test_the_cache_buster_was_ignored(migrated_db):
    engine, _, _ = migrated_db

    with engine.connect() as conn:
        still_busted = conn.execute(
            text("SELECT count(*) FROM card_prints WHERE image_url LIKE '%?260630'")
        ).scalar_one()

    # Every URL still carries the query string, and every row still resolved.
    assert still_busted == 20


def test_treatment_artwork_key_and_release_product_data_are_unchanged(migrated_db):
    engine, before, _ = migrated_db

    with engine.connect() as conn:
        assert conn.execute(text(UNTOUCHED_FIELDS_FINGERPRINT)).scalar_one() == before["untouched"]
        assert (
            conn.execute(text("SELECT count(*) FROM release_products")).scalar_one()
            == before["products"]
        )
        assert (
            conn.execute(text("SELECT count(*) FROM release_product_aliases")).scalar_one()
            == before["aliases"]
        )


def test_treatment_and_variant_are_independent_dimensions(migrated_db):
    """Both 'parallel' prints and 'normal' prints exist, and the variant is
    not a restatement of either label - it is the asset address."""
    engine, _, _ = migrated_db

    with engine.connect() as conn:
        pairs = conn.execute(
            text(
                "SELECT treatment, official_artwork_variant, count(*) FROM card_prints "
                "GROUP BY 1, 2 ORDER BY 1, 2"
            )
        ).fetchall()

    assert [tuple(row) for row in pairs] == [
        ("normal", "base", 13),
        ("parallel", "p1", 5),
        ("parallel", "p2", 2),
    ]


def test_the_verified_unique_index_is_untouched(migrated_db):
    engine, before, _ = migrated_db

    with engine.connect() as conn:
        after = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'uq_card_prints_active_verified_identity'"
            )
        ).scalar_one()

    assert after == before["unique_index"]
    assert "official_artwork_variant" not in after


def test_the_format_constraint_is_enforced_on_the_real_database(migrated_db):
    engine, _, _ = migrated_db

    for rejected in ("", "   ", "parallel", "_p1", "P1", "p0", "p01", "p-1", "foo"):
        with engine.begin() as conn, pytest.raises(Exception) as excinfo:
            conn.execute(
                text("UPDATE card_prints SET official_artwork_variant = :v WHERE id = 1"),
                {"v": rejected},
            )
        assert "ck_card_prints_official_artwork_variant_format" in str(excinfo.value)

    for accepted in ("base", "p1", "p10", "p101"):
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE card_prints SET official_artwork_variant = :v WHERE id = 1"),
                {"v": accepted},
            )

    with engine.begin() as conn:
        conn.execute(text("UPDATE card_prints SET official_artwork_variant = 'p2' WHERE id = 1"))


def test_downgrade_restores_the_pre_migration_shape(migrated_db):
    engine, before, _ = migrated_db

    _run_alembic("downgrade", PREVIOUS_HEAD)

    with engine.connect() as conn:
        assert conn.execute(text(CARD_PRINTS_COLUMNS)).scalar_one() == before["columns"]
        assert conn.execute(text(UNTOUCHED_FIELDS_FINGERPRINT)).scalar_one() == before["untouched"]
        assert conn.execute(
            text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conname = 'ck_card_prints_official_artwork_variant_format'"
            )
        ).scalar_one() == 0
        # The previous phase's tables are left exactly as they were.
        assert (
            conn.execute(text("SELECT count(*) FROM release_products")).scalar_one()
            == before["products"]
        )
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            PREVIOUS_HEAD
        )

    _run_alembic("upgrade", "head")


def test_an_unresolvable_row_is_left_null_and_reported(migrated_db):
    """A fresh database with one deliberately unparseable asset: the
    migration must still succeed, leave that row NULL, and say so."""
    engine, _, _ = migrated_db
    probe_db = "opcg_test_artwork_variant_unresolved"
    probe_url = MIGRATION_URL.replace(MIGRATION_DB, probe_db)

    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{probe_db}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{probe_db}"'))

    probe_engine = create_engine(probe_url)
    env = dict(os.environ)
    env["DATABASE_URL"] = probe_url

    def run(*args):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout + result.stderr

    try:
        run("upgrade", PREVIOUS_HEAD)
        with probe_engine.begin() as conn:
            card_id = conn.execute(
                text(
                    "INSERT INTO canonical_cards "
                    "(card_code, name_en, original_set_code, rarity, card_type) "
                    "VALUES ('OP01-001', 'Luffy', 'OP-01', 'L', 'Leader') RETURNING id"
                )
            ).scalar_one()
            for image_url in (
                None,
                f"{CARD_LIST}/OP01-002_p1.png",  # another card's asset
                f"{CARD_LIST}/OP01-001_px.png",  # unsupported suffix
                f"{CARD_LIST}/OP01-001.png",  # resolvable - proves it still works
            ):
                conn.execute(
                    text(
                        "INSERT INTO card_prints (canonical_card_id, language, treatment, "
                        "verification_status, is_active, image_url) "
                        "VALUES (:card_id, 'jp', 'normal', 'unverified', true, :image_url)"
                    ),
                    {"card_id": card_id, "image_url": image_url},
                )

        output = run("upgrade", "head")

        with probe_engine.connect() as conn:
            rows = conn.execute(
                text("SELECT image_url, official_artwork_variant FROM card_prints ORDER BY id")
            ).fetchall()

        assert [r.official_artwork_variant for r in rows] == [None, None, None, "base"]
        assert "resolved 1/4 card_prints rows - base=1" in output
        assert "WARNING: 3 card_prints rows have no resolvable" in output
        assert "not guessed" in output
    finally:
        probe_engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{probe_db}" WITH (FORCE)'))
        admin.dispose()
