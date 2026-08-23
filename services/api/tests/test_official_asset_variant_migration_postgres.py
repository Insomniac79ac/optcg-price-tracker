"""Runs f2e6b3a71c85 for real on throwaway PostgreSQL databases.

Covers what only a live engine can prove: that the column rename carries the
identity index, the verified check and every stored value across untouched,
that the widened CHECK really does admit rN (and still refuses r0/leading
zeros), that rN and base stay distinct identities even when their artwork_key
is byte-identical, and that the downgrade refuses rather than coercing rN data
back into a vocabulary that has no room for it.

The fixture data is staging-shaped: 20 active+verified jp prints across
OP-01 x4, OP-02 x1, OP-03 x5, OP-04 x10, with treatments 13 normal / 7
parallel and asset variants base=13 / p1=5 / p2=2, matching the canonical
staging database as read read-only on 2026-08-22. Those 20 rows are what this
migration must carry through unchanged.

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

PREVIOUS_HEAD = "d4b17c9e2a83"
THIS_REVISION = "f2e6b3a71c85"

CARD_LIST = "https://www.onepiece-cardgame.com/images/cardlist/card"

OLD_COLUMN = "official_artwork_variant"
NEW_COLUMN = "official_asset_variant"

# The canonical staging 20, exactly as test_exact_print_identity_migration_postgres
# seeds them: (card_code, release_product_code, treatment, artwork basename).
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


def _row_fingerprint(column: str) -> str:
    """Every column of every card_prints row, hashed in id order.

    The variant column is included under whatever it is currently called, so
    the same fingerprint is comparable across the rename - which is the whole
    point: if any *value* moved, this changes.
    """
    return (
        "SELECT md5(string_agg("
        "id || '|' || canonical_card_id || '|' || language || '|' || coalesce(treatment, '~') || "
        "'|' || coalesce(release_product_code, '') || '|' || "
        "coalesce(release_product_id::text, '') || '|' || coalesce(artwork_key, '') || "
        f"'|' || coalesce({column}, '') || "
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


def _schema_state(conn) -> dict:
    return {
        "columns": conn.execute(
            text(
                "SELECT column_name, data_type, character_maximum_length, is_nullable "
                "FROM information_schema.columns WHERE table_name = 'card_prints' "
                "AND column_name IN (:old, :new)"
            ),
            {"old": OLD_COLUMN, "new": NEW_COLUMN},
        ).all(),
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
        "format_checks": conn.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname LIKE 'ck_card_prints_official_%_format' ORDER BY conname"
            )
        ).all(),
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
                    f"release_product_code, artwork_key, {OLD_COLUMN}, image_url, "
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


def _insert_print(conn, card_id: int, variant: str | None, *, artwork_key: str,
                  product_offset: int = 0, treatment: str | None = "normal") -> int:
    return conn.execute(
        text(
            "INSERT INTO card_prints (canonical_card_id, language, treatment, artwork_key, "
            f"{NEW_COLUMN}, verification_status, is_active, release_product_id) "
            "VALUES (:card_id, 'jp', :treatment, :artwork_key, :variant, 'verified', true, "
            "(SELECT id FROM release_products ORDER BY id OFFSET :offset LIMIT 1)) RETURNING id"
        ),
        {
            "card_id": card_id, "variant": variant, "artwork_key": artwork_key,
            "offset": product_offset, "treatment": treatment,
        },
    ).scalar_one()


def _new_card(conn, card_code: str) -> int:
    return conn.execute(
        text(
            "INSERT INTO canonical_cards (card_code, name_en, original_set_code, rarity, "
            "card_type) VALUES (:code, :code, 'PRB-01', 'SEC', 'Character') RETURNING id"
        ),
        {"code": card_code},
    ).scalar_one()


@pytest.fixture(scope="module")
def migrated():
    """The happy path: the staging-shaped 20, upgraded."""
    db = _new_database("opcg_test_asset_variant_ok")
    _seed_staging_shape(db)

    with db.engine.connect() as conn:
        before = {
            "fingerprint": conn.execute(text(_row_fingerprint(OLD_COLUMN))).scalar_one(),
            "count": conn.execute(text("SELECT count(*) FROM card_prints")).scalar_one(),
            "state": _schema_state(conn),
            "variants": conn.execute(
                text(f"SELECT {OLD_COLUMN}, count(*) FROM card_prints GROUP BY 1 ORDER BY 1")
            ).all(),
        }
    output = _alembic(db.url, "upgrade", THIS_REVISION)
    try:
        yield db, before, output
    finally:
        db.close()


# --- the current 20 prints -------------------------------------------------


def test_the_twenty_prints_keep_every_value(migrated):
    """Not one row rewritten - the whole-row fingerprint is identical across
    the rename, with the variant column read under its new name."""
    db, before, _ = migrated

    with db.engine.connect() as conn:
        after = conn.execute(text(_row_fingerprint(NEW_COLUMN))).scalar_one()
        assert conn.execute(text("SELECT count(*) FROM card_prints")).scalar_one() == 20

    assert before["count"] == 20
    assert after == before["fingerprint"]


def test_the_variant_distribution_is_unchanged(migrated):
    db, before, _ = migrated

    with db.engine.connect() as conn:
        after = conn.execute(
            text(f"SELECT {NEW_COLUMN}, count(*) FROM card_prints GROUP BY 1 ORDER BY 1")
        ).all()

    assert [tuple(r) for r in before["variants"]] == [("base", 13), ("p1", 5), ("p2", 2)]
    assert [tuple(r) for r in after] == [("base", 13), ("p1", 5), ("p2", 2)]


def test_treatments_products_and_evidence_are_untouched(migrated):
    db, _, _ = migrated

    with db.engine.connect() as conn:
        treatments = conn.execute(
            text("SELECT treatment, count(*) FROM card_prints GROUP BY 1 ORDER BY 1")
        ).all()
        products = conn.execute(
            text(
                "SELECT rp.official_code, count(*) FROM card_prints cp "
                "JOIN release_products rp ON rp.id = cp.release_product_id GROUP BY 1 ORDER BY 1"
            )
        ).all()
        codes = conn.execute(
            text("SELECT release_product_code, count(*) FROM card_prints GROUP BY 1 ORDER BY 1")
        ).all()
        evidence = conn.execute(
            text(
                "SELECT count(artwork_key), count(image_url), count(*) FILTER "
                "(WHERE artwork_key LIKE 'sha-%') FROM card_prints"
            )
        ).one()

    assert [tuple(r) for r in treatments] == [("normal", 13), ("parallel", 7)]
    assert [tuple(r) for r in products] == [
        ("OP-01", 4), ("OP-02", 1), ("OP-03", 5), ("OP-04", 10)
    ]
    assert [tuple(r) for r in codes] == [("OP-01", 4), ("OP-02", 1), ("OP-03", 5), ("OP-04", 10)]
    assert tuple(evidence) == (20, 20, 20)


def test_the_migration_reports_the_same_distribution_on_both_sides(migrated):
    _, _, output = migrated

    assert f"20 card_prints rows, {OLD_COLUMN} distribution: base=13, p1=5, p2=2" in output
    assert f"20 card_prints rows, {NEW_COLUMN} distribution: base=13, p1=5, p2=2" in output


# --- the final schema ------------------------------------------------------


def test_the_column_was_renamed_not_replaced(migrated):
    db, before, _ = migrated

    with db.engine.connect() as conn:
        state = _schema_state(conn)

    assert [tuple(r) for r in before["state"]["columns"]] == [
        (OLD_COLUMN, "character varying", 16, "YES")
    ]
    assert [tuple(r) for r in state["columns"]] == [
        (NEW_COLUMN, "character varying", 16, "YES")
    ]


def test_the_identity_index_keeps_its_name_columns_and_predicate(migrated):
    db, _, _ = migrated

    with db.engine.connect() as conn:
        index = _schema_state(conn)["index"]

    assert (
        f"btree (canonical_card_id, language, release_product_id, {NEW_COLUMN})" in index
    )
    assert "UNIQUE INDEX uq_card_prints_active_verified_identity" in index
    assert "WHERE ((is_active = true) AND ((verification_status)::text = 'verified'::text))" in (
        index
    )
    # treatment, release_product_code and artwork_key stay out of identity.
    for gone in ("treatment", "release_product_code", "artwork_key"):
        assert gone not in index.split("WHERE")[0]


def test_the_verified_check_keeps_its_requirements(migrated):
    db, _, _ = migrated

    with db.engine.connect() as conn:
        check = _schema_state(conn)["verified_check"]

    assert f"{NEW_COLUMN} IS NOT NULL" in check
    assert OLD_COLUMN not in check
    assert "release_product_id IS NOT NULL" in check
    assert "artwork_key IS NOT NULL" in check
    # Unchanged: treatment is not required, release_product_code is not either.
    assert "release_product_code" not in check
    assert "treatment IS NOT NULL" not in check


def test_the_format_check_was_renamed_and_widened(migrated):
    db, before, _ = migrated

    with db.engine.connect() as conn:
        checks = dict(_schema_state(conn)["format_checks"])

    assert list(dict(before["state"]["format_checks"])) == [
        "ck_card_prints_official_artwork_variant_format"
    ]
    assert list(checks) == ["ck_card_prints_official_asset_variant_format"]
    definition = checks["ck_card_prints_official_asset_variant_format"]
    assert "'p'::text, 'r'::text" in definition or "IN ('p', 'r')" in definition
    assert NEW_COLUMN in definition


# --- the widened vocabulary ------------------------------------------------


@pytest.mark.parametrize("variant", ["base", "p1", "p10", "r1", "r3", "r10", "p101"])
def test_the_widened_check_admits_the_measured_grammar(migrated, variant):
    db, _, _ = migrated

    with db.engine.begin() as conn:
        card_id = _new_card(conn, f"TEST-OK-{variant}")
        _insert_print(conn, card_id, variant, artwork_key=f"sha-{variant}")
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM card_prints WHERE canonical_card_id = :i"), {"i": card_id})
        conn.execute(text("DELETE FROM canonical_cards WHERE id = :i"), {"i": card_id})


@pytest.mark.parametrize("variant", ["r0", "r01", "R1", "p0", "p01", "P1", "r", "r1a", "rN",
                                     "reverse", "", "  ", "BASE"])
def test_the_widened_check_still_refuses_everything_else(migrated, variant):
    """Widening to rN admitted one more *family*, not one more spelling."""
    db, _, _ = migrated

    with pytest.raises(IntegrityError) as excinfo, db.engine.begin() as conn:
        card_id = _new_card(conn, f"TEST-BAD-{variant or 'empty'}")
        _insert_print(conn, card_id, variant, artwork_key="sha-bad")
    assert "ck_card_prints_official_asset_variant_format" in str(excinfo.value)


# --- identity behaviour under the new column -------------------------------


def test_base_and_rn_stay_distinct_even_with_an_identical_artwork_key(migrated):
    """The measured case: 152 rN assets in the JP corpus are byte-for-byte
    identical to a base asset. Identical bytes must not merge two printings,
    because artwork_key is evidence and the asset variant is identity."""
    db, _, _ = migrated
    shared_key = "0" * 64

    with db.engine.begin() as conn:
        card_id = _new_card(conn, "TEST-IDENTICAL-BYTES")
        base_id = _insert_print(conn, card_id, "base", artwork_key=shared_key)
        r1_id = _insert_print(conn, card_id, "r1", artwork_key=shared_key)

    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT id, {NEW_COLUMN}, artwork_key FROM card_prints "
                "WHERE canonical_card_id = :i ORDER BY id"
            ),
            {"i": card_id},
        ).all()

    assert [(r.id, r[1]) for r in rows] == [(base_id, "base"), (r1_id, "r1")]
    assert {r.artwork_key for r in rows} == {shared_key}

    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM card_prints WHERE canonical_card_id = :i"), {"i": card_id})
        conn.execute(text("DELETE FROM canonical_cards WHERE id = :i"), {"i": card_id})


def test_r1_and_r2_in_one_product_are_two_identities(migrated):
    """OP01-120, OP05-074 and OP05-119 each publish _r1 and _r2 inside PRB-01.
    Under the pre-rN vocabulary both collapsed to NULL and collided; under
    this one they are simply two rows."""
    db, _, _ = migrated

    with db.engine.begin() as conn:
        card_id = _new_card(conn, "OP01-120")
        r1_id = _insert_print(conn, card_id, "r1", artwork_key="sha-r1")
        r2_id = _insert_print(conn, card_id, "r2", artwork_key="sha-r2")

    assert r1_id != r2_id

    # ...and the identity still bites: a second r1 in the same product is refused.
    with pytest.raises(IntegrityError) as excinfo, db.engine.begin() as conn:
        _insert_print(conn, card_id, "r1", artwork_key="sha-r1-again")
    assert "uq_card_prints_active_verified_identity" in str(excinfo.value)

    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM card_prints WHERE canonical_card_id = :i"), {"i": card_id})
        conn.execute(text("DELETE FROM canonical_cards WHERE id = :i"), {"i": card_id})


def test_the_same_rn_in_two_products_stays_distinct_through_the_product_id(migrated):
    """The suffix numbering spans products, so r1 is only unique *within* one.
    release_product_id is what separates them."""
    db, _, _ = migrated

    with db.engine.begin() as conn:
        card_id = _new_card(conn, "TEST-CROSS-PRODUCT")
        first = _insert_print(conn, card_id, "r1", artwork_key="sha-a", product_offset=0)
        second = _insert_print(conn, card_id, "r1", artwork_key="sha-b", product_offset=1)

    with db.engine.connect() as conn:
        products = conn.execute(
            text("SELECT release_product_id FROM card_prints WHERE id IN (:a, :b) ORDER BY id"),
            {"a": first, "b": second},
        ).scalars().all()

    assert len(set(products)) == 2

    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM card_prints WHERE canonical_card_id = :i"), {"i": card_id})
        conn.execute(text("DELETE FROM canonical_cards WHERE id = :i"), {"i": card_id})


def test_an_rn_print_may_carry_a_null_treatment(migrated):
    """rN is an address, never a classification. A verified rN print with no
    treatment at all is legal - the strongest statement that the suffix does
    not determine one."""
    db, _, _ = migrated

    with db.engine.begin() as conn:
        card_id = _new_card(conn, "TEST-NULL-TREATMENT")
        print_id = _insert_print(conn, card_id, "r2", artwork_key="sha-nt", treatment=None)

    with db.engine.connect() as conn:
        row = conn.execute(
            text(f"SELECT treatment, {NEW_COLUMN}, verification_status FROM card_prints "
                 "WHERE id = :i"),
            {"i": print_id},
        ).one()
    assert (row.treatment, row[1], row.verification_status) == (None, "r2", "verified")

    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM card_prints WHERE canonical_card_id = :i"), {"i": card_id})
        conn.execute(text("DELETE FROM canonical_cards WHERE id = :i"), {"i": card_id})


# --- downgrade -------------------------------------------------------------


def test_downgrade_restores_the_previous_contract_on_pre_rn_data():
    db = _new_database("opcg_test_asset_variant_downgrade_ok")
    try:
        _seed_staging_shape(db)
        with db.engine.connect() as conn:
            before = _schema_state(conn)
            fingerprint = conn.execute(text(_row_fingerprint(OLD_COLUMN))).scalar_one()
        _alembic(db.url, "upgrade", THIS_REVISION)

        output = _alembic(db.url, "downgrade", PREVIOUS_HEAD)

        assert "downgrade preflight OK" in output
        with db.engine.connect() as conn:
            assert _schema_state(conn) == before
            assert conn.execute(text(_row_fingerprint(OLD_COLUMN))).scalar_one() == fingerprint
            assert conn.execute(
                text(f"SELECT count({OLD_COLUMN}) FROM card_prints")
            ).scalar_one() == 20
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == PREVIOUS_HEAD
    finally:
        db.close()


def test_downgrade_aborts_rather_than_coercing_rn_data():
    db = _new_database("opcg_test_asset_variant_downgrade_blocked")
    try:
        _seed_staging_shape(db)
        _alembic(db.url, "upgrade", THIS_REVISION)
        with db.engine.begin() as conn:
            card_id = _new_card(conn, "OP05-074")
            _insert_print(conn, card_id, "r1", artwork_key="sha-r1")
        with db.engine.connect() as conn:
            before = _schema_state(conn)
            fingerprint = conn.execute(text(_row_fingerprint(NEW_COLUMN))).scalar_one()

        output = _alembic(db.url, "downgrade", PREVIOUS_HEAD, expect_success=False)

        assert "DOWNGRADE ABORTED" in output
        assert "carry an rN" in output
        assert "would merge distinct printings" in output
        with db.engine.connect() as conn:
            # No partial DDL, and nothing rewritten to 'base' or NULL.
            assert _schema_state(conn) == before
            assert conn.execute(text(_row_fingerprint(NEW_COLUMN))).scalar_one() == fingerprint
            assert conn.execute(
                text(f"SELECT count(*) FROM card_prints WHERE {NEW_COLUMN} LIKE 'r%'")
            ).scalar_one() == 1
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == THIS_REVISION
    finally:
        db.close()


def test_a_full_upgrade_downgrade_cycle_from_scratch_leaves_the_schema_stable():
    """head -> base and back, on an empty database: proves both directions of
    every step compose, with no data in play at all."""
    db = _new_database("opcg_test_asset_variant_roundtrip")
    try:
        # This revision, not "head": the cycle under test is this migration's
        # own two directions, and a later migration must not be able to change
        # what this test means.
        _alembic(db.url, "upgrade", THIS_REVISION)
        with db.engine.connect() as conn:
            head_state = _schema_state(conn)

        _alembic(db.url, "downgrade", PREVIOUS_HEAD)
        _alembic(db.url, "upgrade", THIS_REVISION)

        with db.engine.connect() as conn:
            assert _schema_state(conn) == head_state
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == THIS_REVISION
    finally:
        db.close()
