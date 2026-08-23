"""Runs b8d5f1c40e73 for real on throwaway PostgreSQL databases.

Covers what only a live engine can prove: that adding the four columns leaves
every existing value byte-identical, that the new columns really arrive NULL
on every pre-existing row, that the exact-print index and the verified CHECK
come through untouched, that the columns accept the corpus's actual values
(Japanese text, a hiragana typo, U+203C, a textual 'X' block icon) and that
the downgrade removes exactly those four and nothing else.

The fixture data is staging-shaped: the same 20 active+verified jp prints the
asset-variant migration test seeds, matching the canonical staging database as
read read-only on 2026-08-22.

Never touches canonical staging. Skips when no server answers."""

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

PREVIOUS_HEAD = "f2e6b3a71c85"
THIS_REVISION = "b8d5f1c40e73"

CARD_LIST = "https://www.onepiece-cardgame.com/images/cardlist/card"

VARIANT_COLUMN = "official_asset_variant"
NEW_COLUMNS = (
    "official_rarity",
    "official_block_icon",
    "official_name",
    "official_effect_text",
)

# Values taken verbatim from the 2026-08-22 JP corpus - the awkward ones on
# purpose, because a column that only ever stores 'SR' proves nothing.
NAME_TYPO = "シャーロット・フランぺ"   # EB01-056 in EB-01: a hiragana ぺ
EFFECT_U203C = "【ドン‼×2】【アタック時】相手のキャラ1枚までを、このターン中、パワー-3000。"
RARITY_JP = "SPカード"

# The canonical staging 20, exactly as the asset-variant migration test seeds
# them: (card_code, release_product_code, treatment, artwork basename).
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


def _row_fingerprint() -> str:
    """Every pre-existing column of every card_prints row, hashed in id order.

    Deliberately lists only the columns that existed before this migration: if
    any of them moved, this changes. The four new columns are checked
    separately, because on the way up they are expected to be NULL.
    """
    return (
        "SELECT md5(string_agg("
        "id || '|' || canonical_card_id || '|' || language || '|' || coalesce(treatment, '~') || "
        "'|' || coalesce(release_product_code, '') || '|' || "
        "coalesce(release_product_id::text, '') || '|' || coalesce(artwork_key, '') || "
        f"'|' || coalesce({VARIANT_COLUMN}, '') || "
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


def _columns(conn) -> dict:
    rows = conn.execute(
        text(
            "SELECT column_name, data_type, character_maximum_length, is_nullable, "
            "column_default FROM information_schema.columns "
            "WHERE table_name = 'card_prints'"
        )
    ).all()
    return {r[0]: r[1:] for r in rows}


def _schema_state(conn) -> dict:
    return {
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
        "format_check": conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_card_prints_official_asset_variant_format'"
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


def _seed_staging_shape(db: _Database) -> None:
    """The 20 staging prints, at the revision immediately before this one."""
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
            conn.execute(
                text(
                    "INSERT INTO card_prints (canonical_card_id, language, treatment, "
                    f"release_product_code, artwork_key, {VARIANT_COLUMN}, image_url, "
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
    """The staging-shaped 20, upgraded across this revision."""
    db = _new_database("opcg_test_print_metadata_ok")
    _seed_staging_shape(db)

    with db.engine.connect() as conn:
        before = {
            "fingerprint": conn.execute(text(_row_fingerprint())).scalar_one(),
            "count": conn.execute(text("SELECT count(*) FROM card_prints")).scalar_one(),
            "columns": _columns(conn),
            "state": _schema_state(conn),
        }
    output = _alembic(db.url, "upgrade", THIS_REVISION)
    try:
        yield db, before, output
    finally:
        db.close()


# --- the existing 20 prints -------------------------------------------------


def test_the_columns_did_not_exist_before(migrated):
    _, before, _ = migrated

    for name in NEW_COLUMNS:
        assert name not in before["columns"]
    assert before["count"] == 20


def test_no_existing_value_is_touched(migrated):
    """The whole-row fingerprint over every pre-existing column is identical."""
    db, before, _ = migrated

    with db.engine.connect() as conn:
        after = conn.execute(text(_row_fingerprint())).scalar_one()
        assert conn.execute(text("SELECT count(*) FROM card_prints")).scalar_one() == 20

    assert after == before["fingerprint"]


def test_every_existing_row_gets_null_metadata(migrated):
    """No backfill and no default: NULL is the honest state for a row that
    predates the columns."""
    db, _, _ = migrated

    with db.engine.connect() as conn:
        populated = conn.execute(
            text(
                "SELECT count(*) FROM card_prints WHERE "
                + " OR ".join(f"{name} IS NOT NULL" for name in NEW_COLUMNS)
            )
        ).scalar_one()

    assert populated == 0


def test_the_migration_reports_no_rows_updated(migrated):
    """Alembic's own output for this revision names no data statement."""
    _, _, output = migrated

    lowered = output.lower()
    assert THIS_REVISION in output
    for statement in ("update card_prints", "insert into card_prints", "delete from card_prints"):
        assert statement not in lowered


# --- the new columns --------------------------------------------------------


def test_the_four_columns_exist_and_are_nullable(migrated):
    db, _, _ = migrated

    with db.engine.connect() as conn:
        columns = _columns(conn)

    for name in NEW_COLUMNS:
        data_type, max_length, is_nullable, default = columns[name]
        assert is_nullable == "YES", name
        assert default is None, name


def test_the_column_types_are_what_was_declared(migrated):
    db, _, _ = migrated

    with db.engine.connect() as conn:
        columns = _columns(conn)

    assert columns["official_rarity"][:2] == ("character varying", 32)
    assert columns["official_block_icon"][:2] == ("character varying", 8)
    assert columns["official_name"][:2] == ("character varying", 255)
    # Text: unbounded, which is what an effect text needs and what
    # CanonicalCard.effect_text already uses.
    assert columns["official_effect_text"][0] == "text"
    assert columns["official_effect_text"][1] is None


def test_the_columns_accept_the_corpus_values_verbatim(migrated):
    """Japanese text, a hiragana typo, U+203C and a textual block icon - the
    four things a naive column type would have mangled."""
    db, _, _ = migrated

    with db.engine.begin() as conn:
        print_id = conn.execute(text("SELECT min(id) FROM card_prints")).scalar_one()
        conn.execute(
            text(
                "UPDATE card_prints SET official_rarity = :rarity, "
                "official_block_icon = :block, official_name = :name, "
                "official_effect_text = :effect WHERE id = :id"
            ),
            {
                "rarity": RARITY_JP, "block": "X", "name": NAME_TYPO,
                "effect": EFFECT_U203C, "id": print_id,
            },
        )

    with db.engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT official_rarity, official_block_icon, official_name, "
                "official_effect_text FROM card_prints WHERE id = :id"
            ),
            {"id": print_id},
        ).one()

    assert row[0] == RARITY_JP
    assert row[1] == "X"
    assert row[2] == NAME_TYPO
    assert row[3] == EFFECT_U203C
    assert "‼" in row[3]

    with db.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE card_prints SET official_rarity = NULL, official_block_icon = NULL, "
                "official_name = NULL, official_effect_text = NULL WHERE id = :id"
            ),
            {"id": print_id},
        )


def test_metadata_is_not_identity_on_a_live_engine(migrated):
    """Two verified prints of one card in one product still collide on the
    identity key even when their metadata differs - the unique index does not
    know these columns exist."""
    db, _, _ = migrated

    with db.engine.connect() as conn:
        indexdef = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'uq_card_prints_active_verified_identity'"
            )
        ).scalar_one()

    for name in NEW_COLUMNS:
        assert name not in indexdef


def test_the_verified_check_still_does_not_require_them(migrated):
    """Deliberately: every verified row that exists predates these columns."""
    db, _, _ = migrated

    with db.engine.connect() as conn:
        check = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_card_prints_verified_requires_fields'"
            )
        ).scalar_one()

    for name in NEW_COLUMNS:
        assert name not in check


def test_the_untouchable_schema_is_byte_identical(migrated):
    """The identity index, the verified check and the asset-variant format
    check come through the migration character for character unchanged."""
    db, before, _ = migrated

    with db.engine.connect() as conn:
        after = _schema_state(conn)

    assert after == before["state"]


def test_no_other_column_changed(migrated):
    db, before, _ = migrated

    with db.engine.connect() as conn:
        after = _columns(conn)

    assert set(after) - set(before["columns"]) == set(NEW_COLUMNS)
    for name, definition in before["columns"].items():
        assert after[name] == definition, name


# --- downgrade --------------------------------------------------------------


def test_downgrade_removes_only_the_four_columns():
    db = _new_database("opcg_test_print_metadata_down")
    try:
        _seed_staging_shape(db)
        with db.engine.connect() as conn:
            before_columns = _columns(conn)
            before_fingerprint = conn.execute(text(_row_fingerprint())).scalar_one()
            before_state = _schema_state(conn)

        _alembic(db.url, "upgrade", THIS_REVISION)
        # Populate them, so the downgrade is dropping real data rather than a
        # column full of NULLs - which is the case that would hide a mistake.
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE card_prints SET official_rarity = :rarity, "
                    "official_block_icon = 'X', official_name = :name, "
                    "official_effect_text = :effect"
                ),
                {"rarity": RARITY_JP, "name": NAME_TYPO, "effect": EFFECT_U203C},
            )

        _alembic(db.url, "downgrade", PREVIOUS_HEAD)

        with db.engine.connect() as conn:
            after_columns = _columns(conn)
            after_fingerprint = conn.execute(text(_row_fingerprint())).scalar_one()
            after_state = _schema_state(conn)
            count = conn.execute(text("SELECT count(*) FROM card_prints")).scalar_one()
            revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

        assert after_columns == before_columns
        assert after_fingerprint == before_fingerprint
        assert after_state == before_state
        assert count == 20
        assert revision == PREVIOUS_HEAD
    finally:
        db.close()


def test_upgrade_downgrade_upgrade_is_stable():
    """The cycle is repeatable - a migration that only works once is a
    migration that fails the first time it is re-run."""
    db = _new_database("opcg_test_print_metadata_cycle")
    try:
        _seed_staging_shape(db)
        _alembic(db.url, "upgrade", THIS_REVISION)
        with db.engine.connect() as conn:
            first = _columns(conn)

        _alembic(db.url, "downgrade", PREVIOUS_HEAD)
        _alembic(db.url, "upgrade", THIS_REVISION)

        with db.engine.connect() as conn:
            second = _columns(conn)
            count = conn.execute(text("SELECT count(*) FROM card_prints")).scalar_one()
            populated = conn.execute(
                text(
                    "SELECT count(*) FROM card_prints WHERE "
                    + " OR ".join(f"{name} IS NOT NULL" for name in NEW_COLUMNS)
                )
            ).scalar_one()

        assert second == first
        assert count == 20
        assert populated == 0
    finally:
        db.close()


def test_the_model_and_the_migrated_schema_agree():
    """A live database migrated to head carries exactly the columns the ORM
    declares - so nothing is only in the model, or only in the migration."""
    from app.models import CardPrint

    db = _new_database("opcg_test_print_metadata_parity")
    try:
        _alembic(db.url, "upgrade", "head")
        with db.engine.connect() as conn:
            columns = set(_columns(conn))

        assert set(CardPrint.__table__.columns.keys()) == columns
    finally:
        db.close()
