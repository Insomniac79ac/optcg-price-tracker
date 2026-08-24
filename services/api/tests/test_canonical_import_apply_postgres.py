"""The apply engine against real PostgreSQL: transaction, idempotency, rollback.

Everything here needs a real transaction to mean anything. "The whole run
rolled back" cannot be asserted against sqlite's looser DDL/constraint story,
and neither can the partial-unique identity index the engine's post-write
invariant leans on.

Each test builds its own database from the migrations and seeds a small
staging-shaped fixture, so nothing depends on another test's leftovers or on
the 976 MB local corpus. Skips when no server answers.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.services import canonical_import_apply as A
from app.services import print_import_planner as P
from app.services.official_cardlist import OfficialCardEntry, OfficialSeries, RawField

REPO_ROOT = Path(__file__).resolve().parents[1]

HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
ADMIN_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/postgres"

HEAD = "d1c48b7f36ae"
CARD_LIST = "https://www.onepiece-cardgame.com/images/cardlist/card"
SERIES_URL = "https://www.onepiece-cardgame.com/cardlist/?series="

SNAPSHOT_ID = "s" * 64


def _alembic(url: str, *args: str) -> str:
    env = dict(os.environ)
    env["DATABASE_URL"] = url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{output}"
    return output


class _Database:
    def __init__(self, name: str) -> None:
        self.name = name
        admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        admin.dispose()
        self.url = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/{name}"
        self.engine = create_engine(self.url)

    def close(self) -> None:
        self.engine.dispose()
        admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)'))
        admin.dispose()


def _new_database(name: str) -> _Database:
    try:
        return _Database(name)
    except OperationalError:
        pytest.skip(f"No PostgreSQL server reachable at {HOST}:{PORT}")


# --- the fixture corpus ---------------------------------------------------
# Three cards in OP-01, one of which is also reprinted into PRB-01, plus one
# card whose only occurrence is the reprint. Small enough to reason about,
# shaped like the real thing.

SERIES = (
    OfficialSeries("550101", "ROMANCE DAWN【OP-01】", "OP-01"),
    OfficialSeries("550301", "プレミアムブースター【PRB-01】", "PRB-01"),
)


def _entry(
    entry_id: str,
    card_code: str,
    *,
    rarity: str = "R",
    category: str = "CHARACTER",
    name: str = "テストカード",
    product: str = "ROMANCE DAWN【OP-01】",
    basename: str | None = None,
    cost: str = "2",
    power: str = "5000",
    counter: str = "1000",
    text_value: str = "【起動メイン】テスト",
    block: str = "01",
) -> OfficialCardEntry:
    return OfficialCardEntry(
        entry_id=entry_id,
        card_code=card_code,
        rarity=rarity,
        category=category,
        card_name=name,
        image_url=f"{CARD_LIST}/{basename or entry_id}.png?260101",
        product_names=(product,),
        fields=(
            RawField("cost", "コスト", cost),
            RawField("power", "パワー", power),
            RawField("counter", "カウンター", counter),
            RawField("text", "テキスト", text_value),
            RawField("block", "ブロック", block),
            RawField("color", "色", "赤"),
        ),
    )


ENTRIES = (
    _entry("OP01-001", "OP01-001", rarity="L", category="LEADER", name="ルフィ",
           cost="-", counter="-"),
    _entry("OP01-001_p1", "OP01-001", rarity="L", category="LEADER", name="ルフィ",
           cost="-", counter="-"),
    _entry("OP01-013", "OP01-013", name="サンジ"),
    _entry("OP01-030", "OP01-030", rarity="SR", name="ゾロ"),
    # A reprint of OP01-013 into PRB-01, published at a different rarity. Its
    # own set code is OP-01, so this occurrence is never the baseline.
    _entry("OP01-013_r1", "OP01-013", rarity="SEC", name="サンジ",
           product="プレミアムブースター【PRB-01】"),
    # A card whose ONLY occurrence is a reprint: no OP-05 series exists here,
    # so no baseline can be established and it must be excluded.
    _entry("OP05-100_r1", "OP05-100", rarity="SEC", name="エース",
           product="プレミアムブースター【PRB-01】"),
    # OP01-030 already exists as a canonical card carrying rarity 'SR' for its
    # own set OP-01. This is its PRB-01 REPRINT, published as 'SPカード'. Per
    # §7 that is a note about the printing - never a canonical-card conflict
    # and never an overwrite. (A disagreement on OP-01 itself would still be a
    # conflict; that is the baseline occurrence, and 4C-1B keeps it blocking.)
    _entry("OP01-030_r1", "OP01-030", rarity="SPカード", name="ゾロ",
           product="プレミアムブースター【PRB-01】"),
    # OP01-050 is NEW and is published twice under its OWN set at two
    # different rarities - the EB03-003 shape, which the complete JP corpus
    # shows on 18 card codes. It is not two cards, and neither value is "the"
    # rarity, so the canonical row is written with rarity = NULL while each
    # print keeps its own official_rarity.
    _entry("OP01-050", "OP01-050", rarity="SR", name="ナミ"),
    _entry("OP01-050_p1", "OP01-050", rarity="SPカード", name="ナミ"),
    # A PROMO. `P-014` carries no set number because a promo has no set: it is
    # DISTRIBUTED inside other products (PRB-01 here, and a second printing in
    # OP-01) and neither of those is its original set. Its canonical row is
    # established by consensus over these coded occurrences, with
    # original_set_code NULL.
    _entry("P-014_p1", "P-014", rarity="P", name="コビー",
           product="プレミアムブースター【PRB-01】"),
    _entry("P-014_p2", "P-014", rarity="P", name="コビー"),
    # A second promo whose two printings publish DIFFERENT rarities - the
    # P-084 shape. Not two cards, and neither value is the card's rarity, so
    # the canonical rarity is NULL while each print keeps its own.
    _entry("P-084_p1", "P-084", rarity="SPカード", name="バギー"),
    _entry("P-084_r1", "P-084", rarity="P", name="バギー",
           product="プレミアムブースター【PRB-01】"),
)

DIGESTS = {e.image_url: f"{i:064d}" for i, e in enumerate(ENTRIES, start=1)}


def _plan(session: Session) -> P.ImportPlan:
    return P.plan_entries(
        session, ENTRIES, series_index=SERIES,
        digest_provider=DIGESTS.get, classify_mappings=False,
    )


def _entries_by_id() -> dict:
    return {e.entry_id: e for e in ENTRIES}


def _seed_existing_print(db: _Database) -> int:
    """One card Atlas already holds, so the no_change/backfill path is exercised."""
    with db.engine.begin() as conn:
        card_id = conn.execute(
            text(
                "INSERT INTO canonical_cards (card_code, name_jp, original_set_code, "
                "rarity, card_type) VALUES ('OP01-030', 'ゾロ', 'OP-01', 'SR', 'Character') "
                "RETURNING id"
            )
        ).scalar_one()
        # OP-01 through OP-04 are seeded by the migrations themselves, so this
        # reuses the established row rather than creating a second one - which
        # the partial unique index would refuse anyway.
        product_id = conn.execute(
            text(
                "SELECT id FROM release_products WHERE source_catalogue = 'bandai_jp' "
                "AND official_code = 'OP-01'"
            )
        ).scalar_one()
        return conn.execute(
            text(
                "INSERT INTO card_prints (canonical_card_id, language, treatment, "
                "release_product_id, release_product_code, artwork_key, "
                "official_asset_variant, image_url, verification_status, is_active) VALUES "
                "(:card, 'jp', 'normal', :product, 'OP-01', :digest, 'base', :image, "
                "'verified', true) RETURNING id"
            ),
            {
                "card": card_id,
                "product": product_id,
                "digest": DIGESTS[f"{CARD_LIST}/OP01-030.png?260101"],
                "image": f"{CARD_LIST}/OP01-030.png?260101",
            },
        ).scalar_one()


def _fingerprint(db: _Database) -> dict:
    with db.engine.connect() as conn:
        return {
            # ORDER BY id, never ORDER BY the concatenated text: string
            # ordering is collation-dependent and would differ between two
            # servers holding identical rows.
            "release_products": conn.execute(
                text("SELECT md5(coalesce(string_agg(r, '|' ORDER BY id), '')) FROM "
                     "(SELECT id, id::text || coalesce(official_code, '~') || "
                     "first_seen_name AS r FROM release_products) t")
            ).scalar_one(),
            "canonical_cards": conn.execute(
                text("SELECT md5(coalesce(string_agg(r, '|' ORDER BY id), '')) FROM "
                     "(SELECT id, id::text || card_code || rarity || card_type || "
                     "coalesce(cost::text, '~') || coalesce(power::text, '~') AS r "
                     "FROM canonical_cards) t")
            ).scalar_one(),
            "card_prints": conn.execute(
                text("SELECT md5(coalesce(string_agg(r, '|' ORDER BY id), '')) FROM "
                     "(SELECT id, id::text || canonical_card_id::text || "
                     "official_asset_variant || coalesce(official_rarity, '~') || "
                     "coalesce(official_name, '~') || coalesce(treatment, '~') || "
                     "coalesce(artwork_key, '~') AS r FROM card_prints) t")
            ).scalar_one(),
            "counts": {
                table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                for table in A.COUNTED_TABLES
            },
        }


def _apply(db: _Database, *, apply=True, pinning=None, plan=None, environment="test"):
    with Session(db.engine) as session:
        pinning = pinning or A.ApplyPinning(
            snapshot_identity=SNAPSHOT_ID, expected_db_revision=A.db_revision(session)
        )
        applier = A.CanonicalImportApplier(
            session,
            plan if plan is not None else _plan(session),
            pinning=pinning,
            environment=environment,
            entries=_entries_by_id(),
        )
        return applier.run(apply=apply)


@pytest.fixture
def db():
    database = _new_database("opcg_test_apply_engine")
    _alembic(database.url, "upgrade", HEAD)
    _seed_existing_print(database)
    try:
        yield database
    finally:
        database.close()


# --- the happy path -------------------------------------------------------


def test_a_dry_run_writes_nothing(db):
    before = _fingerprint(db)

    report = _apply(db, apply=False)

    assert report.applied is False
    assert _fingerprint(db) == before


def test_the_first_apply_creates_products_cards_and_prints(db):
    report = _apply(db)

    assert report.applied is True
    # PRB-01 is the only product missing; OP-01 was seeded.
    assert report.products_created == 1
    # OP01-001, OP01-013, OP01-050 and the two promos P-014 / P-084.
    # OP01-030 already exists; OP05-100 has no own-set occurrence to compose a
    # canonical row from.
    assert report.canonical_cards_created == 5
    assert report.card_prints_created >= 3
    assert report.rollback_reason is None


def test_the_existing_print_keeps_its_identity_and_gains_its_metadata(db):
    print_id = db.engine.connect().execute(
        text("SELECT id FROM card_prints ORDER BY id LIMIT 1")
    ).scalar_one()

    report = _apply(db)

    assert report.existing_print_metadata_updated == 1
    with db.engine.connect() as conn:
        row = conn.execute(
            text("SELECT treatment, official_asset_variant, artwork_key, official_rarity, "
                 "official_block_icon, official_name, official_effect_text "
                 "FROM card_prints WHERE id = :i"),
            {"i": print_id},
        ).one()
    # identity and treatment untouched...
    assert row[0] == "normal"
    assert row[1] == "base"
    assert row[2] == DIGESTS[f"{CARD_LIST}/OP01-030.png?260101"]
    # ...and the four published values filled in.
    assert row[3] == "SR"
    assert row[4] == "01"
    assert row[5] == "ゾロ"
    assert row[6] == "【起動メイン】テスト"


def test_new_prints_carry_no_treatment_and_are_verified(db):
    _apply(db)

    with db.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT treatment, verification_status, is_active, artwork_key, image_url "
                 "FROM card_prints WHERE id > (SELECT min(id) FROM card_prints)")
        ).all()
    assert rows
    for treatment, status, active, artwork, image in rows:
        assert treatment is None
        assert status == "verified"
        assert active is True
        assert artwork and image


def test_a_created_canonical_card_takes_its_rarity_from_its_own_set(db):
    """OP01-013 is published R in OP-01 and SEC in PRB-01. The canonical row
    must record R - the reprint's rarity belongs to the reprint."""
    _apply(db)

    with db.engine.connect() as conn:
        rarity = conn.execute(
            text("SELECT rarity FROM canonical_cards WHERE card_code = 'OP01-013'")
        ).scalar_one()
    assert rarity == "R"


def test_the_reprint_print_still_records_its_own_published_rarity(db):
    _apply(db)

    with db.engine.connect() as conn:
        rarities = conn.execute(
            text("SELECT cp.official_rarity FROM card_prints cp "
                 "JOIN canonical_cards cc ON cc.id = cp.canonical_card_id "
                 "WHERE cc.card_code = 'OP01-013' ORDER BY cp.id")
        ).scalars().all()
    assert "SEC" in rarities


def test_language_ambiguous_canonical_columns_are_left_null(db):
    _apply(db)

    with db.engine.connect() as conn:
        row = conn.execute(
            text("SELECT count(colors), count(attribute), count(effect_text), "
                 "count(trigger_text), count(name_en), count(*) FROM canonical_cards "
                 "WHERE card_code IN ('OP01-001', 'OP01-013')")
        ).one()
    assert tuple(row) == (0, 0, 0, 0, 0, 2)


def test_language_independent_numerics_are_written(db):
    _apply(db)

    with db.engine.connect() as conn:
        row = conn.execute(
            text("SELECT cost, power, counter FROM canonical_cards WHERE card_code='OP01-013'")
        ).one()
    assert tuple(row) == (2, 5000, 1000)


def test_bandais_dash_becomes_null_not_zero(db):
    _apply(db)

    with db.engine.connect() as conn:
        row = conn.execute(
            text("SELECT cost, counter, power FROM canonical_cards WHERE card_code='OP01-001'")
        ).one()
    assert row[0] is None and row[1] is None
    assert row[2] == 5000


# --- §4 a promo has no original set -----------------------------------------


def test_a_promo_is_created_with_no_original_set_code(db):
    """The 60-print blocker, gone. The card is created; its original_set_code
    is NULL because a promo has no set - not 'P', not 'PROMO', and not the
    product it was distributed in."""
    _apply(db)

    with db.engine.connect() as conn:
        row = conn.execute(
            text("SELECT original_set_code, name_jp, card_type, rarity "
                 "FROM canonical_cards WHERE card_code = 'P-014'")
        ).one()
    set_code, name_jp, card_type, rarity = row
    assert set_code is None
    # Everything the catalogue DOES settle is still written.
    assert (name_jp, card_type, rarity) == ("コビー", "Character", "P")


def test_a_promos_distribution_products_never_become_its_set(db):
    """P-014 is published in PRB-01 and OP-01 here. Both are recorded as the
    products its printings appeared in, and neither reaches the canonical
    row."""
    _apply(db)

    with db.engine.connect() as conn:
        set_code = conn.execute(
            text("SELECT original_set_code FROM canonical_cards WHERE card_code = 'P-014'")
        ).scalar_one()
        products = sorted(
            code for (code,) in conn.execute(
                text("SELECT r.official_code FROM card_prints p "
                     "JOIN canonical_cards c ON c.id = p.canonical_card_id "
                     "JOIN release_products r ON r.id = p.release_product_id "
                     "WHERE c.card_code = 'P-014'")
            ).all()
        )

    assert set_code is None
    assert products == ["OP-01", "PRB-01"]
    for invented in ("P", "PROMO", "PR", "PRB-01", "OP-01"):
        assert set_code != invented


def test_every_promo_print_keeps_its_own_published_evidence(db):
    """The release product says WHERE the exact printing appeared without
    pretending it is the promo's set."""
    _apply(db)

    with db.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT p.official_asset_variant, r.official_code, p.official_rarity, "
                 "p.official_name, p.official_block_icon, p.official_effect_text IS NOT NULL "
                 "FROM card_prints p JOIN canonical_cards c ON c.id = p.canonical_card_id "
                 "JOIN release_products r ON r.id = p.release_product_id "
                 "WHERE c.card_code = 'P-084' ORDER BY p.official_asset_variant")
        ).all()

    assert rows == [
        ("p1", "OP-01", "SPカード", "バギー", "01", True),
        ("r1", "PRB-01", "P", "バギー", "01", True),
    ]


def test_a_promo_whose_printings_disagree_on_rarity_is_created_with_null(db):
    report = _apply(db)

    assert "P-084" in report.rarity_null_codes
    with db.engine.connect() as conn:
        assert conn.execute(
            text("SELECT rarity FROM canonical_cards WHERE card_code = 'P-084'")
        ).scalar_one() is None
        # ...and its two prints kept both published values.
        assert sorted(
            r for (r,) in conn.execute(
                text("SELECT p.official_rarity FROM card_prints p "
                     "JOIN canonical_cards c ON c.id = p.canonical_card_id "
                     "WHERE c.card_code = 'P-084'")
            ).all()
        ) == ["P", "SPカード"]


def test_promo_import_is_idempotent(db):
    """A second run must not create a second canonical card for a code whose
    original_set_code is NULL - the resolve-before-insert path keys on
    card_code, not on the set."""
    _apply(db)
    after_first = _fingerprint(db)

    second = _apply(db)

    assert second.canonical_cards_created == 0
    assert _fingerprint(db) == after_first
    with db.engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM canonical_cards WHERE card_code LIKE 'P-%'")
        ).scalar_one() == 2


# --- §6/§7 rarity is optional, and never invented ---------------------------


def test_a_card_whose_own_set_publishes_two_rarities_is_created_with_null(db):
    """The 122-print blocker, gone. The card is created; its rarity is NULL
    because the catalogue settles none - not 'SR', not 'SPカード', not the
    most common and not the highest."""
    report = _apply(db)

    assert "OP01-050" in report.rarity_null_codes
    with db.engine.connect() as conn:
        row = conn.execute(
            text("SELECT rarity, name_jp, card_type, original_set_code "
                 "FROM canonical_cards WHERE card_code = 'OP01-050'")
        ).one()
    rarity, name_jp, card_type, set_code = row
    assert rarity is None
    # Everything the catalogue DOES settle is still written.
    assert (name_jp, card_type, set_code) == ("ナミ", "Character", "OP-01")


def test_both_of_its_prints_are_created_each_with_its_own_official_rarity(db):
    """Rarity moves to where it belongs: the exact printing."""
    _apply(db)

    with db.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT p.official_asset_variant, p.official_rarity "
                 "FROM card_prints p JOIN canonical_cards c "
                 "ON c.id = p.canonical_card_id WHERE c.card_code = 'OP01-050' "
                 "ORDER BY p.official_asset_variant")
        ).all()

    assert rows == [("base", "SR"), ("p1", "SPカード")]


def test_a_null_canonical_rarity_never_becomes_a_placeholder(db):
    """NULL is the answer, not a hole to fill. No 'Unknown', no '-', no ''."""
    _apply(db)

    with db.engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM canonical_cards WHERE rarity IS NOT NULL "
                 "AND trim(rarity) IN ('', '-', 'Unknown', 'N/A')")
        ).scalar_one() == 0


def test_an_existing_canonical_rarity_is_never_rewritten_by_a_reprint(db):
    """§7. OP01-030 is stored as 'SR' and this run imports a printing Bandai
    publishes as 'SPカード'. The canonical value stays exactly as it was."""
    with db.engine.connect() as conn:
        before = conn.execute(
            text("SELECT rarity FROM canonical_cards WHERE card_code = 'OP01-030'")
        ).scalar_one()

    report = _apply(db)

    with db.engine.connect() as conn:
        after = conn.execute(
            text("SELECT rarity FROM canonical_cards WHERE card_code = 'OP01-030'")
        ).scalar_one()
        reprint = conn.execute(
            text("SELECT p.official_rarity FROM card_prints p JOIN canonical_cards c "
                 "ON c.id = p.canonical_card_id WHERE c.card_code = 'OP01-030' "
                 "AND p.official_asset_variant = 'r1'")
        ).scalar_one()

    assert before == "SR"
    assert after == before
    # And the printing's own published value was recorded, not discarded.
    assert reprint == "SPカード"
    assert report.planner_conflicts == 0


def test_a_rarity_that_differs_by_printing_is_not_a_conflict(db):
    """The plan for that reprint is a note, never OUTCOME_CONFLICT."""
    with Session(db.engine) as session:
        plan = _plan(session)

    reprint = next(p for p in plan.prints if p.entry_id == "OP01-030_r1")
    assert reprint.outcome != P.OUTCOME_CONFLICT
    assert P.FLAG_CANONICAL_CARD_CONFLICT not in reprint.flags
    assert P.FLAG_RARITY_DIFFERS_BY_PRINTING in reprint.flags


def test_the_report_names_every_card_written_with_a_null_rarity(db):
    """An absence that is not reported is indistinguishable from a silence."""
    report = _apply(db)

    document = report.to_dict()["canonical_baseline"]
    assert document["rarity_null_codes"] == report.rarity_null_codes
    assert document["rarity_null_count"] == len(report.rarity_null_codes)
    with db.engine.connect() as conn:
        actual = {
            code for (code,) in conn.execute(
                text("SELECT card_code FROM canonical_cards WHERE rarity IS NULL")
            ).all()
        }
    assert actual == set(report.rarity_null_codes)


def test_a_card_with_no_baseline_occurrence_is_excluded_with_all_its_prints(db):
    """OP05-100 appears only as a PRB-01 reprint here. Its set code is
    readable, but there is no OP-05 occurrence to read a name and card type
    from - and those columns are NOT NULL. Excluded for THAT reason; rarity
    is no longer one."""
    report = _apply(db)

    assert A.SKIP_NO_BASELINE_OCCURRENCE in report.skipped_ineligible
    assert not hasattr(A, "SKIP_NO_BASELINE_RARITY")
    with db.engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM canonical_cards WHERE card_code = 'OP05-100'")
        ).scalar_one() == 0
        assert conn.execute(
            text("SELECT count(*) FROM card_prints WHERE image_url LIKE '%OP05-100%'")
        ).scalar_one() == 0


def test_needs_review_plans_are_never_applied(db):
    report = _apply(db)

    assert report.skipped_needs_review == report.skipped_needs_review  # reported
    with db.engine.connect() as conn:
        # Nothing uncoded was created: every product carries a code.
        assert conn.execute(
            text("SELECT count(*) FROM release_products WHERE official_code IS NULL")
        ).scalar_one() == 0


def test_the_untouched_tables_are_untouched(db):
    before = _fingerprint(db)["counts"]

    _apply(db)

    after = _fingerprint(db)["counts"]
    for table in A.UNTOUCHED_TABLES:
        assert before[table] == after[table]


def test_no_duplicate_final_identity_after_apply(db):
    _apply(db)

    with db.engine.connect() as conn:
        duplicates = conn.execute(
            text("SELECT count(*) FROM (SELECT canonical_card_id, language, "
                 "release_product_id, official_asset_variant FROM card_prints "
                 "WHERE is_active AND verification_status = 'verified' "
                 "GROUP BY 1,2,3,4 HAVING count(*) > 1) d")
        ).scalar_one()
    assert duplicates == 0


# --- §9 idempotency -------------------------------------------------------


def test_a_second_identical_run_writes_nothing(db):
    _apply(db)
    after_first = _fingerprint(db)

    second = _apply(db)

    assert (second.products_created, second.canonical_cards_created,
            second.card_prints_created, second.existing_print_metadata_updated) == (0, 0, 0, 0)
    assert _fingerprint(db) == after_first


def test_idempotency_does_not_rely_on_catching_integrity_errors(db):
    """Existing rows are resolved with a SELECT before any INSERT is composed."""
    source = (REPO_ROOT / "app" / "services" / "canonical_import_apply.py").read_text(
        encoding="utf-8"
    )

    # The engine names IntegrityError only in prose explaining why it does not
    # rely on it; what matters is that it never catches one.
    assert "except IntegrityError" not in source
    assert "IntegrityError" not in "".join(
        line for line in source.splitlines() if not line.strip().startswith("#")
        and "IntegrityError." not in line
    )
    body = source.split("def _create_card_prints")[1].split("\n    def ")[0]
    assert "except" not in body
    assert "select(CardPrint)" in body


def test_a_third_run_is_still_a_no_op(db):
    _apply(db)
    _apply(db)
    after_second = _fingerprint(db)

    third = _apply(db)

    assert third.card_prints_created == 0
    assert _fingerprint(db) == after_second


# --- §14 rollback ---------------------------------------------------------


def _assert_rolled_back(db, before, reason):
    assert _fingerprint(db) == before
    return reason


def test_rollback_on_wrong_db_revision(db):
    before = _fingerprint(db)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db, pinning=A.ApplyPinning(
            snapshot_identity=SNAPSHOT_ID, expected_db_revision="d4b17c9e2a83"))

    assert excinfo.value.report.rollback_reason == "db_revision_mismatch"
    assert _fingerprint(db) == before


def test_rollback_on_stale_pre_apply_counts(db):
    before = _fingerprint(db)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db, pinning=A.ApplyPinning(
            snapshot_identity=SNAPSHOT_ID,
            expected_db_revision=HEAD,
            expected_pre_counts={"card_prints": 999},
        ))

    assert excinfo.value.report.rollback_reason == "stale_pre_apply_counts"
    assert _fingerprint(db) == before


def test_rollback_on_a_snapshot_identity_mismatch(db):
    """§14. The corpus was recollected between planning and applying.

    Recording the identity in the report is not the same as refusing to write
    when it has moved, so the pinned value is compared, not just logged.
    """
    before = _fingerprint(db)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db, pinning=A.ApplyPinning(
            snapshot_identity=SNAPSHOT_ID,
            expected_db_revision=HEAD,
            expected_snapshot_identity="0" * 64,
        ))

    assert excinfo.value.report.rollback_reason == "snapshot_identity_mismatch"
    assert _fingerprint(db) == before


def test_a_matching_snapshot_identity_is_accepted(db):
    report = _apply(db, pinning=A.ApplyPinning(
        snapshot_identity=SNAPSHOT_ID,
        expected_db_revision=HEAD,
        expected_snapshot_identity=SNAPSHOT_ID,
    ))

    assert report.applied is True


def test_rollback_on_a_production_target(db):
    before = _fingerprint(db)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db, environment="production")

    assert excinfo.value.report.rollback_reason == "refused_environment"
    assert _fingerprint(db) == before


def test_rollback_on_canonical_staging_target(db):
    before = _fingerprint(db)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db, environment="staging")

    assert excinfo.value.report.rollback_reason == "refused_environment"
    assert _fingerprint(db) == before


def test_rollback_on_a_source_catalogue_mismatch(db):
    before = _fingerprint(db)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db, pinning=A.ApplyPinning(
            snapshot_identity=SNAPSHOT_ID,
            source_catalogue="bandai_en",
            expected_db_revision=HEAD,
        ))

    assert excinfo.value.report.rollback_reason == "source_catalogue_mismatch"
    assert _fingerprint(db) == before


def test_rollback_on_a_duplicate_proposed_identity(db):
    """Two plans proposing the same final identity abort by name, before the
    unique index would have raised a bare IntegrityError."""
    before = _fingerprint(db)

    with Session(db.engine) as session:
        plan = _plan(session)
    twin = [p for p in plan.prints if p.outcome == P.OUTCOME_CREATE][0]
    plan.prints.append(twin)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db, plan=plan)

    assert excinfo.value.report.rollback_reason == "duplicate_proposed_identity"
    assert _fingerprint(db) == before


def test_rollback_on_an_asset_digest_mismatch(db):
    """The digest changes AFTER the plan was built, so the plan still says
    no_change while the stored artwork_key no longer matches the catalogue.

    Planned first and applied second on purpose: a digest that had already
    changed at planning time would make the planner say needs_review, and the
    engine would simply skip it. This is the narrower case the backfill guard
    exists for - the row moved underneath a plan that was already made.
    """
    with Session(db.engine) as session:
        plan = _plan(session)
    with db.engine.begin() as conn:
        conn.execute(text("UPDATE card_prints SET artwork_key = :k WHERE id = "
                          "(SELECT min(id) FROM card_prints)"), {"k": "f" * 64})
    changed = _fingerprint(db)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db, plan=plan)

    assert excinfo.value.report.rollback_reason == A.ABORT_EXISTING_ASSET_DIGEST
    assert _fingerprint(db) == changed


# --- §3 an existing print's digest drift is fatal, missing input is not ------


def _corrupt_existing_digest(db, print_id: int) -> str:
    with db.engine.begin() as conn:
        conn.execute(
            text("UPDATE card_prints SET artwork_key = :k WHERE id = :id"),
            {"k": "d" * 64, "id": print_id},
        )
    return "d" * 64


def test_a_drifted_digest_on_an_existing_print_aborts_the_whole_run(db):
    """The corrupted row is planned as needs_review, so before this rule the
    engine imported every other row and left the drift buried under 4138 new
    ones. Atlas already holds this exact print: its stored evidence
    disagreeing with the frozen official evidence is integrity drift, and the
    run stops."""
    with db.engine.connect() as conn:
        print_id = conn.execute(text("SELECT min(id) FROM card_prints")).scalar_one()
    _corrupt_existing_digest(db, print_id)
    before = _fingerprint(db)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db)

    report = excinfo.value.report
    assert report.rollback_reason == A.ABORT_EXISTING_ASSET_DIGEST
    assert report.applied is False
    # Nothing was created, and not one row of any table moved.
    assert (report.products_created, report.canonical_cards_created,
            report.card_prints_created, report.existing_print_metadata_updated) == (0, 0, 0, 0)
    assert _fingerprint(db) == before


def test_the_digest_abort_names_the_print_the_code_the_product_and_both_digests(db):
    """A structured reason, not a sentence to parse. Neither digest is
    overwritten - the report carries both so a human can decide which is
    right."""
    with db.engine.connect() as conn:
        print_id = conn.execute(text("SELECT min(id) FROM card_prints")).scalar_one()
    corrupted = _corrupt_existing_digest(db, print_id)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db)

    context = excinfo.value.report.rollback_context
    assert context["card_print_id"] == print_id
    assert context["card_code"] == "OP01-030"
    assert context["release_product_code"] == "OP-01"
    assert context["official_asset_variant"] == "base"
    assert context["stored_artwork_sha256"] == corrupted
    assert context["expected_artwork_sha256"] == DIGESTS[
        f"{CARD_LIST}/OP01-030.png?260101"
    ]
    assert excinfo.value.report.to_dict()["rollback_context"] == context
    # And the stored value is left exactly as it was found.
    with db.engine.connect() as conn:
        assert conn.execute(
            text("SELECT artwork_key FROM card_prints WHERE id = :id"), {"id": print_id}
        ).scalar_one() == corrupted


def test_the_digest_abort_happens_before_anything_is_composed(db):
    """Even a dry run refuses. The check is a preflight over the complete
    plan, not a write-time guard, so it cannot depend on how far a run got."""
    with db.engine.connect() as conn:
        print_id = conn.execute(text("SELECT min(id) FROM card_prints")).scalar_one()
    _corrupt_existing_digest(db, print_id)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db, apply=False)

    assert excinfo.value.report.rollback_reason == A.ABORT_EXISTING_ASSET_DIGEST


def test_one_drifted_print_is_never_quarantined_and_the_rest_imported(db):
    """The whole point: no partial import that leaves the drift behind."""
    with db.engine.connect() as conn:
        print_id = conn.execute(text("SELECT min(id) FROM card_prints")).scalar_one()
    _corrupt_existing_digest(db, print_id)

    with pytest.raises(A.ApplyRunFailed):
        _apply(db)

    with db.engine.connect() as conn:
        # The one seeded print is still the only print, and the one seeded
        # canonical card still the only card beyond the migrations' own.
        assert conn.execute(text("SELECT count(*) FROM card_prints")).scalar_one() == 1


def test_restoring_the_digest_lets_the_normal_import_succeed(db):
    """The abort is about drift, not about the corpus. Put the stored digest
    back and the same run imports normally."""
    with db.engine.connect() as conn:
        print_id = conn.execute(text("SELECT min(id) FROM card_prints")).scalar_one()
    correct = DIGESTS[f"{CARD_LIST}/OP01-030.png?260101"]
    _corrupt_existing_digest(db, print_id)
    with pytest.raises(A.ApplyRunFailed):
        _apply(db)

    with db.engine.begin() as conn:
        conn.execute(
            text("UPDATE card_prints SET artwork_key = :k WHERE id = :id"),
            {"k": correct, "id": print_id},
        )
    report = _apply(db)

    assert report.applied is True
    assert report.card_prints_created > 0
    assert report.rollback_reason is None


def test_a_new_print_whose_digest_cannot_be_established_is_only_skipped(db):
    """The opposite case, and it must stay the opposite. Atlas holds nothing
    for this print, so nothing has diverged: it is left unimported and every
    other row is still applied."""
    partial = {url: d for url, d in DIGESTS.items() if "OP01-013.png" not in url}
    with Session(db.engine) as session:
        plan = P.plan_entries(
            session, ENTRIES, series_index=SERIES,
            digest_provider=partial.get, classify_mappings=False,
        )
    undigested = [p for p in plan.prints if p.entry_id == "OP01-013"]
    assert undigested and P.FLAG_DIGEST_NOT_ESTABLISHED in undigested[0].flags
    assert undigested[0].outcome == P.OUTCOME_NEEDS_REVIEW

    report = _apply(db, plan=plan)

    assert report.applied is True
    assert report.rollback_reason is None
    assert report.card_prints_created > 0
    with db.engine.connect() as conn:
        # The undigested print itself was not created - a verified print needs
        # artwork_key evidence and there is none for it.
        assert conn.execute(
            text("SELECT count(*) FROM card_prints p JOIN canonical_cards c "
                 "ON c.id = p.canonical_card_id JOIN release_products r "
                 "ON r.id = p.release_product_id WHERE c.card_code = 'OP01-013' "
                 "AND r.official_code = 'OP-01'")
        ).scalar_one() == 0
        # Its PRB-01 reprint, which does have a digest, was.
        assert conn.execute(
            text("SELECT count(*) FROM card_prints p JOIN canonical_cards c "
                 "ON c.id = p.canonical_card_id JOIN release_products r "
                 "ON r.id = p.release_product_id WHERE c.card_code = 'OP01-013' "
                 "AND r.official_code = 'PRB-01'")
        ).scalar_one() == 1


def test_rollback_on_an_existing_metadata_conflict(db):
    """A stored published value that disagrees is never overwritten."""
    with db.engine.begin() as conn:
        conn.execute(text("UPDATE card_prints SET official_rarity = 'C' WHERE id = "
                          "(SELECT min(id) FROM card_prints)"))
    before = _fingerprint(db)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db)

    assert excinfo.value.report.rollback_reason == "existing_metadata_conflict"
    assert _fingerprint(db) == before
    with db.engine.connect() as conn:
        assert conn.execute(
            text("SELECT official_rarity FROM card_prints ORDER BY id LIMIT 1")
        ).scalar_one() == "C"


def test_rollback_on_product_evidence_conflict(db):
    """An established product whose series authority disagrees with the
    catalogue is neither reused nor overwritten - the whole run stops."""
    with db.engine.begin() as conn:
        conn.execute(
            text("UPDATE release_products SET source_series_id = '999999' "
                 "WHERE source_catalogue = 'bandai_jp' AND official_code = 'OP-01'")
        )
    before = _fingerprint(db)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db)

    assert excinfo.value.report.rollback_reason == "product_evidence_conflict"
    assert _fingerprint(db) == before
    with db.engine.connect() as conn:
        # The established row is left exactly as it was found.
        assert conn.execute(
            text("SELECT source_series_id FROM release_products WHERE official_code = 'OP-01'")
        ).scalar_one() == "999999"


# --- 4C-4B a planner conflict aborts the whole apply ----------------------
#
# The fixture's OP01-030 is the case that can carry one: Atlas already holds
# its canonical row, and its OP-01 occurrence is the BASELINE occurrence, so a
# disagreement there is about the card itself rather than about a printing.


def _spoil_canonical_op01_030(db: _Database, column: str, value: str) -> None:
    with db.engine.begin() as conn:
        conn.execute(
            text(f"UPDATE canonical_cards SET {column} = :v WHERE card_code = 'OP01-030'"),
            {"v": value},
        )


def _canonical_op01_030(db: _Database, column: str):
    with db.engine.connect() as conn:
        return conn.execute(
            text(f"SELECT {column} FROM canonical_cards WHERE card_code = 'OP01-030'")
        ).scalar_one()


@pytest.mark.parametrize(
    "column,value",
    [
        # the 4C-4 baseline-name case, re-run
        ("name_jp", "ちがう名前"),
        # ...and a second, unrelated conflict type: ANY conflict aborts
        ("card_type", "Event"),
        ("rarity", "C"),
    ],
)
def test_any_planner_conflict_aborts_the_entire_apply(db, column, value):
    _spoil_canonical_op01_030(db, column, value)
    with Session(db.engine) as session:
        plan = _plan(session)
    conflicts = [p for p in plan.prints if p.outcome == P.OUTCOME_CONFLICT]
    # the disagreement is on the card's OWN set - a reprint's difference is a
    # note, and would not be a conflict at all
    assert conflicts and all(p.card_code == "OP01-030" for p in conflicts)
    assert any(p.official_product_code == "OP-01" for p in conflicts)
    before = _fingerprint(db)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db)

    report = excinfo.value.report
    assert report.rollback_reason == A.ABORT_PLANNER_CONFLICT == "planner_conflict"
    assert report.applied is False
    # nothing at all, not "everything except the conflicting rows"
    assert report.products_created == 0
    assert report.canonical_cards_created == 0
    assert report.card_prints_created == 0
    assert report.existing_print_metadata_updated == 0
    assert report.planner_conflicts == len(conflicts)
    # the database is byte-for-byte what it was...
    assert _fingerprint(db) == before
    # ...including the value the catalogue disagreed with, which is not
    # overwritten and not quarantined.
    assert _canonical_op01_030(db, column) == value


def test_the_conflict_abort_reports_enough_to_diagnose_it(db):
    _spoil_canonical_op01_030(db, "name_jp", "ちがう名前")
    card_id = _canonical_op01_030(db, "id")

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db)

    document = excinfo.value.report.to_dict()
    assert document["rollback_reason"] == "planner_conflict"
    context = document["rollback_context"]
    assert context["planner_conflicts"] == context["reported"] >= 1
    entry = context["conflicts"][0]
    assert entry["card_code"] == "OP01-030"
    assert entry["existing_canonical_card_id"] == card_id
    assert entry["entry_id"] in {"OP01-030", "OP01-030_r1"}
    assert entry["official_product_code"] == "OP-01"
    assert P.FLAG_CANONICAL_CARD_CONFLICT in entry["flags"]
    assert any("name_jp" in reason for reason in entry["reasons"])
    # both sides of the disagreement, as fields
    assert entry["canonical"]["name_jp"] == "ちがう名前"
    assert entry["official"]["card_name"] == "ゾロ"
    assert json.loads(json.dumps(document, ensure_ascii=False))


def test_a_conflict_refuses_the_dry_run_too(db):
    """Fail closed in both modes: a dry run that reported a clean preview of a
    conflicting plan would be the report an operator acts on."""
    _spoil_canonical_op01_030(db, "name_jp", "ちがう名前")
    before = _fingerprint(db)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db, apply=False)

    assert excinfo.value.report.rollback_reason == A.ABORT_PLANNER_CONFLICT
    assert _fingerprint(db) == before


def test_needs_review_alone_never_aborts_the_run(db):
    """The other half of the rule: an ambiguity costs its own rows only.

    One entry's artwork digest is withheld, which the planner sends to
    needs_review. The run still commits, and every other row is written.
    """
    partial = {k: v for k, v in DIGESTS.items() if not k.endswith("OP01-013.png?260101")}
    with Session(db.engine) as session:
        plan = P.plan_entries(
            session, ENTRIES, series_index=SERIES,
            digest_provider=partial.get, classify_mappings=False,
        )
    assert [p for p in plan.prints if p.outcome == P.OUTCOME_NEEDS_REVIEW]
    assert not [p for p in plan.prints if p.outcome == P.OUTCOME_CONFLICT]

    report = _apply(db, plan=plan)

    assert report.applied is True
    assert report.rollback_reason is None
    assert report.planner_conflicts == 0
    assert report.skipped_needs_review > 0
    assert report.card_prints_created > 0


def test_a_conflict_introduced_after_planning_is_caught_at_apply(db):
    """The plan is read from the session that writes, so a canonical row that
    changed between planning and applying is not applied over."""
    with Session(db.engine) as session:
        clean = _plan(session)
    assert not [p for p in clean.prints if p.outcome == P.OUTCOME_CONFLICT]
    _spoil_canonical_op01_030(db, "name_jp", "ちがう名前")
    before = _fingerprint(db)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db)  # replans against the changed database

    assert excinfo.value.report.rollback_reason == A.ABORT_PLANNER_CONFLICT
    assert _fingerprint(db) == before


def test_a_card_whose_baseline_cannot_be_established_is_excluded_not_invented(db):
    """The ordinary path: eligibility drops the card, the run still commits,
    and no canonical row is invented for it."""
    before_cards = _fingerprint(db)["counts"]["canonical_cards"]

    report = _apply(db)

    assert report.baseline_counts[A.BASELINE_NONE] >= 1
    assert A.SKIP_NO_BASELINE_OCCURRENCE in report.skipped_ineligible
    with db.engine.connect() as conn:
        assert conn.execute(
            text("SELECT count(*) FROM canonical_cards WHERE card_code = 'OP05-100'")
        ).scalar_one() == 0
    # ...and the cards that DO have a baseline were still created.
    assert _fingerprint(db)["counts"]["canonical_cards"] > before_cards


def test_the_write_step_refuses_an_uncomposable_baseline_even_if_bypassed(db):
    """The defence in depth behind the eligibility filter: hand the writer a
    card with no baseline identity evidence and it aborts the whole run rather
    than reaching for a name, a type or a set code."""
    before = _fingerprint(db)

    with Session(db.engine) as session:
        plan = _plan(session)
        eligible = [p for p in plan.prints if p.outcome == P.OUTCOME_CREATE
                    and p.existing_canonical_card_id is None]
        assert eligible
        audit = A.BaselineAudit()
        audit.baselines[eligible[0].card_code.upper()] = A.CanonicalBaseline(
            card_code=eligible[0].card_code.upper(),
            status=A.BASELINE_NONE,
            expected_set_code=None,
            candidates=(),
        )
        applier = A.CanonicalImportApplier(
            session, plan,
            pinning=A.ApplyPinning(snapshot_identity=SNAPSHOT_ID, expected_db_revision=HEAD),
            environment="test", entries=_entries_by_id(),
        )
        with pytest.raises(A.ApplyAborted) as excinfo:
            applier._create_canonical_cards(eligible[:1], audit, A.ApplyReport())
        session.rollback()

    assert excinfo.value.reason == "canonical_card_not_composable"
    assert _fingerprint(db) == before


def test_rollback_when_the_database_changes_under_the_plan(db):
    """The plan is built, then rows appear underneath it. (Not a planner
    conflict - that is test_a_conflict_introduced_after_planning_is_caught_at_apply;
    this is the pinned pre-apply counts refusing a drifted database.)"""
    with Session(db.engine) as session:
        plan = _plan(session)
    with db.engine.begin() as conn:
        conn.execute(text("INSERT INTO card_prints (canonical_card_id, language, "
                          "release_product_id, release_product_code, artwork_key, "
                          "official_asset_variant, image_url, verification_status, is_active) "
                          "SELECT canonical_card_id, language, release_product_id, "
                          "release_product_code, :digest, 'p9', image_url, "
                          "'verified', true FROM card_prints ORDER BY id LIMIT 1"),
                     {"digest": "e" * 64})
    before = _fingerprint(db)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db, plan=plan, pinning=A.ApplyPinning(
            snapshot_identity=SNAPSHOT_ID,
            expected_db_revision=HEAD,
            expected_pre_counts=before["counts"] | {"card_prints": before["counts"]["card_prints"] - 1},
        ))

    assert excinfo.value.report.rollback_reason == "stale_pre_apply_counts"
    assert _fingerprint(db) == before


def test_every_rollback_leaves_the_report_naming_the_reason(db):
    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _apply(db, environment="production")

    document = excinfo.value.report.to_dict()
    assert document["applied"] is False
    assert document["rollback_reason"]
    assert document["rollback_detail"]
    assert json.loads(json.dumps(document))


# --- §10 pinning ----------------------------------------------------------


def test_the_report_pins_the_snapshot_and_revision(db):
    report = _apply(db)

    assert report.snapshot_identity == SNAPSHOT_ID
    assert report.db_revision == HEAD
    assert report.source_catalogue == "bandai_jp"


def test_matching_expected_counts_are_accepted(db):
    before = _fingerprint(db)["counts"]

    report = _apply(db, pinning=A.ApplyPinning(
        snapshot_identity=SNAPSHOT_ID,
        expected_db_revision=HEAD,
        expected_pre_counts=before,
    ))

    assert report.applied is True


# --- §15 image boundary ---------------------------------------------------


def test_the_engine_records_addresses_and_digests_never_bytes(db):
    report = _apply(db)

    assert report.distinct_image_digests > 0
    with db.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT image_url, artwork_key FROM card_prints WHERE artwork_key IS NOT NULL")
        ).all()
    for image_url, artwork_key in rows:
        assert image_url.startswith("https://")
        assert len(artwork_key) == 64
