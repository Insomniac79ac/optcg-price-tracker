"""The three release states of the asset-variant rename, on real PostgreSQL.

The rename ships as expand/deploy/contract, so there are three schemas an
operator can be looking at and two application generations that have to work
against them:

    STATE A   d4b17c9e2a83   what canonical staging runs today.
                             official_artwork_variant only.
    STATE B   b8d5f1c40e73   after the expand migration and the print-metadata
                             migration. BOTH variant columns, identity still
                             enforced on the legacy one. Old application and
                             new application must both work here - this is the
                             whole point of the release, and the tests below
                             are the proof.
    STATE C   a9f31c7d5b64   after the contract migration. official_asset_variant
                             only, identity moved onto it, legacy column gone.
                             The new application works; the old one no longer
                             can, deliberately.

The 20 canonical staging prints are carried through every state and checked
value by value, and the whole A->B->C->B->A cycle is exercised.

Seeding helpers are imported from test_official_asset_variant_migration_postgres
rather than copied, so the fixture shape cannot drift between the two modules.
Never touches canonical staging. Skips when no server answers.
"""

import subprocess

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from test_official_asset_variant_migration_postgres import (  # noqa: E402
    CARD_LIST,
    OLD_COLUMN,
    NEW_COLUMN,
    REPO_ROOT,
    _alembic,
    _new_card,
    _new_database,
    _row_fingerprint,
    _schema_state,
    _seed_staging_shape,
)

STATE_A = "d4b17c9e2a83"
EXPAND = "f2e6b3a71c85"
METADATA = "b8d5f1c40e73"
CONTRACT = "a9f31c7d5b64"

# STATE B is "expand plus metadata": the operator migrates staging to the
# metadata revision in one step, so that is the schema the old application
# actually has to survive.
STATE_B = METADATA
STATE_C = CONTRACT

METADATA_COLUMNS = (
    "official_rarity", "official_block_icon", "official_name", "official_effect_text",
)

# The card_prints columns app.models.CardPrint declared at bf7a71a - the
# revision deployed while State B is in force. Written down rather than
# imported because the whole point is to check the schema against a *previous*
# generation of the model; test_the_old_application_column_list_is_still_accurate
# keeps this honest against git.
DEPLOYED_REVISION = "bf7a71a"
OLD_APP_COLUMNS = (
    "id", "canonical_card_id", "language", "treatment", "release_product_code",
    "release_product_id", "artwork_key", OLD_COLUMN, "image_url", "artist",
    "verification_status", "is_active", "created_at", "updated_at",
)


def _columns(conn) -> set[str]:
    return set(
        conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'card_prints'"
            )
        ).scalars().all()
    )


def _seed_downstream(db) -> None:
    """One source mapping and one Market Index snapshot, both pointing at a
    print, so the release can be shown not to disturb what hangs off it.

    Both FKs onto card_prints are ON DELETE RESTRICT, which makes these rows a
    real check: a migration that recreated prints rather than altering them in
    place could not leave these intact.
    """
    with db.engine.begin() as conn:
        print_id = conn.execute(
            text("SELECT id FROM card_prints ORDER BY id LIMIT 1")
        ).scalar_one()
        card_id = conn.execute(
            text(
                "INSERT INTO cards (card_code, set_code, rarity, language) "
                "VALUES ('OP01-001', 'OP-01', 'L', 'jp') RETURNING id"
            )
        ).scalar_one()
        source_id = conn.execute(
            text(
                "INSERT INTO sources (name, base_url) "
                "VALUES ('yuyutei', 'https://yuyu-tei.jp') RETURNING id"
            )
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO source_card_mappings (card_id, source_id, source_card_id, "
                "card_print_id, is_active, review_status) "
                "VALUES (:card, :source, 'yt-1', :print_id, true, 'approved')"
            ),
            {"card": card_id, "source": source_id, "print_id": print_id},
        )
        conn.execute(
            text(
                "INSERT INTO market_index_snapshots (card_print_id, calculated_at, "
                "snapshot_date, calculation_method, source_count, coverage_status, "
                "confidence, index_value_jpy, index_version, source_semantics_version, "
                "provenance) VALUES (:print_id, now(), current_date, 'median', 1, 'full', "
                "'high', 1200, 1, 1, '{}')"
            ),
            {"print_id": print_id},
        )


def _downstream_state(db) -> tuple:
    with db.engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT count(*), min(card_print_id), min(review_status) "
                    "FROM source_card_mappings"
                )
            ).one(),
            conn.execute(
                text(
                    "SELECT count(*), min(card_print_id), min(calculation_method), "
                    "min(index_value_jpy), min(index_version) FROM market_index_snapshots"
                )
            ).one(),
        )


def _print_facts(db, variant_column: str) -> list[tuple]:
    """Every value of the 20 that this release promises not to touch."""
    with db.engine.connect() as conn:
        return [
            tuple(r)
            for r in conn.execute(
                text(
                    "SELECT id, canonical_card_id, language, treatment, release_product_code, "
                    f"release_product_id, artwork_key, image_url, {variant_column}, "
                    "verification_status, is_active FROM card_prints ORDER BY id"
                )
            ).all()
        ]


def _database_at(name: str, revision: str, *, downstream: bool = False):
    db = _new_database(name)
    _seed_staging_shape(db)
    if downstream:
        _seed_downstream(db)
    if revision != STATE_A:
        _alembic(db.url, "upgrade", revision)
    return db


@pytest.fixture(scope="module")
def state_a():
    db = _database_at("opcg_test_release_state_a", STATE_A, downstream=True)
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="module")
def state_b():
    db = _database_at("opcg_test_release_state_b", STATE_B, downstream=True)
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="module")
def state_c():
    db = _database_at("opcg_test_release_state_c", STATE_C, downstream=True)
    try:
        yield db
    finally:
        db.close()


# --- STATE A: what staging runs today --------------------------------------


def test_state_a_has_the_legacy_column_only(state_a):
    with state_a.engine.connect() as conn:
        columns = _columns(conn)

    assert OLD_COLUMN in columns
    assert NEW_COLUMN not in columns
    assert not set(METADATA_COLUMNS) & columns


def test_state_a_satisfies_every_column_the_deployed_application_declares(state_a):
    with state_a.engine.connect() as conn:
        columns = _columns(conn)

    assert set(OLD_APP_COLUMNS) <= columns


def test_the_old_application_column_list_is_still_accurate():
    """Keeps OLD_APP_COLUMNS honest against the revision actually deployed."""
    try:
        source = subprocess.run(
            ["git", "show", f"{DEPLOYED_REVISION}:services/api/app/models/card_print.py"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - git absent
        pytest.skip("git unavailable")
    if source.returncode != 0:
        pytest.skip(f"{DEPLOYED_REVISION} not resolvable in this checkout")

    declared = [
        line.split(":")[0].strip()
        for line in source.stdout.splitlines()
        if ": Mapped[" in line and "= mapped_column" in line
    ]
    assert declared == list(OLD_APP_COLUMNS)


# --- STATE B: both generations must work -----------------------------------


def test_state_b_carries_both_variant_columns_and_the_metadata_columns(state_b):
    with state_b.engine.connect() as conn:
        columns = _columns(conn)

    assert {OLD_COLUMN, NEW_COLUMN} <= columns
    assert set(METADATA_COLUMNS) <= columns


def test_state_b_satisfies_every_column_the_old_application_declares(state_b):
    """Half of the compatibility proof: nothing the deployed generation reads
    has gone away."""
    with state_b.engine.connect() as conn:
        columns = _columns(conn)

    assert set(OLD_APP_COLUMNS) <= columns


def test_state_b_satisfies_every_column_the_new_application_declares(state_b):
    """The other half, taken straight from the ORM model as it stands now."""
    from app.models import CardPrint

    with state_b.engine.connect() as conn:
        columns = _columns(conn)

    assert {c.name for c in CardPrint.__table__.columns} <= columns


def test_the_old_application_read_path_still_works_at_state_b(state_b):
    """The shape app.services.print_catalogue issues: prints joined to their
    canonical card and release product, addressed by the legacy column."""
    with state_b.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT cp.id, cc.card_code, rp.official_code, cp.treatment, "
                f"cp.{OLD_COLUMN} FROM card_prints cp "
                "JOIN canonical_cards cc ON cc.id = cp.canonical_card_id "
                "JOIN release_products rp ON rp.id = cp.release_product_id "
                "WHERE cp.is_active = true AND cp.verification_status = 'verified' "
                f"AND cp.{OLD_COLUMN} = 'base' ORDER BY cp.id"
            )
        ).all()

    assert len(rows) == 13
    assert {r[4] for r in rows} == {"base"}


def test_the_new_application_read_path_also_works_at_state_b(state_b):
    """The same query the new generation issues, against the same rows."""
    with state_b.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT cp.id, cc.card_code, rp.official_code, cp.treatment, "
                f"cp.{NEW_COLUMN}, cp.official_rarity FROM card_prints cp "
                "JOIN canonical_cards cc ON cc.id = cp.canonical_card_id "
                "JOIN release_products rp ON rp.id = cp.release_product_id "
                "WHERE cp.is_active = true AND cp.verification_status = 'verified' "
                f"AND cp.{NEW_COLUMN} = 'base' ORDER BY cp.id"
            )
        ).all()

    assert len(rows) == 13
    assert {r[4] for r in rows} == {"base"}
    # The metadata columns exist and are empty - nothing was backfilled.
    assert {r[5] for r in rows} == {None}


# The card_prints columns the two collector services mirror read-only - see
# services/{yuyutei,snkrdunk}_collector/*/models.py, both of which declare
# CardPrint as a lookup and emit no DDL. Neither names a variant column at
# all, so neither is affected by any state of this release; asserted rather
# than assumed because a price run failing mid-release would be silent until
# the next refresh.
COLLECTOR_MIRROR_COLUMNS = (
    "id", "canonical_card_id", "language", "treatment", "release_product_code",
    "artwork_key", "image_url", "verification_status", "is_active",
)


def test_the_collector_mirrors_keep_working_in_every_state(state_a, state_b, state_c):
    for db in (state_a, state_b, state_c):
        with db.engine.connect() as conn:
            assert set(COLLECTOR_MIRROR_COLUMNS) <= _columns(conn)
            # The join both collectors run to find a print for a mapping.
            conn.execute(
                text(
                    "SELECT cp.id, cp.treatment FROM source_card_mappings scm "
                    "JOIN card_prints cp ON cp.id = scm.card_print_id "
                    "WHERE cp.is_active = true AND cp.verification_status = 'verified'"
                )
            ).all()


def test_the_old_application_can_still_write_a_verified_print_at_state_b():
    """Writing is the harder half of compatibility: the verified CHECK and the
    identity index both still name the legacy column, so a row the deployed
    generation composes is still accepted - and still deduplicated."""
    db = _database_at("opcg_test_release_old_write", STATE_B)
    try:
        with db.engine.begin() as conn:
            card_id = _new_card(conn, "TEST-OLD-APP-WRITE")
            product_id = conn.execute(
                text("SELECT id FROM release_products ORDER BY id LIMIT 1")
            ).scalar_one()
            new_id = conn.execute(
                text(
                    "INSERT INTO card_prints (canonical_card_id, language, treatment, "
                    f"release_product_code, release_product_id, artwork_key, {OLD_COLUMN}, "
                    "image_url, verification_status, is_active) VALUES (:card, 'jp', 'normal', "
                    "'OP-01', :product, 'sha-old-app', 'p3', :image, 'verified', true) "
                    "RETURNING id"
                ),
                {"card": card_id, "product": product_id, "image": f"{CARD_LIST}/x_p3.png"},
            ).scalar_one()
        assert new_id

        # ...and the identity still bites on the legacy column.
        with pytest.raises(IntegrityError) as excinfo, db.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO card_prints (canonical_card_id, language, treatment, "
                    f"release_product_code, release_product_id, artwork_key, {OLD_COLUMN}, "
                    "verification_status, is_active) VALUES (:card, 'jp', 'normal', 'OP-01', "
                    ":product, 'sha-old-app-2', 'p3', 'verified', true)"
                ),
                {"card": card_id, "product": product_id},
            )
        assert "uq_card_prints_active_verified_identity" in str(excinfo.value)
    finally:
        db.close()


def test_an_old_application_write_is_what_the_contract_preflight_refuses():
    """The fail-closed half of the same fact. A row written through the legacy
    column alone leaves the two columns disagreeing, and the contract
    migration must refuse rather than drop the disagreement on the floor."""
    db = _database_at("opcg_test_release_divergence", STATE_B)
    try:
        with db.engine.begin() as conn:
            card_id = _new_card(conn, "TEST-DIVERGED")
            conn.execute(
                text(
                    "INSERT INTO card_prints (canonical_card_id, language, treatment, "
                    f"release_product_code, release_product_id, artwork_key, {OLD_COLUMN}, "
                    "verification_status, is_active) VALUES (:card, 'jp', 'normal', 'OP-01', "
                    "(SELECT id FROM release_products ORDER BY id LIMIT 1), 'sha-diverged', "
                    "'p7', 'verified', true)"
                ),
                {"card": card_id},
            )
        with db.engine.connect() as conn:
            before = _schema_state(conn)

        output = _alembic(db.url, "upgrade", CONTRACT, expect_success=False)

        assert "ABORTED" in output
        assert "disagree between" in output
        with db.engine.connect() as conn:
            # No partial DDL: the legacy column is still there, untouched.
            assert _schema_state(conn) == before
            assert OLD_COLUMN in _columns(conn)
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == METADATA
    finally:
        db.close()


# --- the 20 prints, state by state -----------------------------------------


def test_the_twenty_prints_are_identical_at_state_a_and_state_b(state_a, state_b):
    """Every value this release promises not to touch, compared row for row -
    with the variant read from the legacy column on both sides."""
    assert _print_facts(state_a, OLD_COLUMN) == _print_facts(state_b, OLD_COLUMN)
    assert len(_print_facts(state_b, OLD_COLUMN)) == 20

    with state_b.engine.connect() as conn:
        assert conn.execute(text(_row_fingerprint(OLD_COLUMN))).scalar_one() == \
            conn.execute(text(_row_fingerprint(NEW_COLUMN))).scalar_one()


def test_the_twenty_prints_are_identical_at_state_b_and_state_c(state_b, state_c):
    """The variant is read from the new column at both states, because that is
    the column that survives - and its values never changed."""
    assert _print_facts(state_b, NEW_COLUMN) == _print_facts(state_c, NEW_COLUMN)
    assert len(_print_facts(state_c, NEW_COLUMN)) == 20


def test_the_variant_distribution_holds_across_all_three_states(state_a, state_b, state_c):
    expected = [("base", 13), ("p1", 5), ("p2", 2)]

    def distribution(db, column):
        with db.engine.connect() as conn:
            return [
                tuple(r) for r in conn.execute(
                    text(f"SELECT {column}, count(*) FROM card_prints GROUP BY 1 ORDER BY 1")
                ).all()
            ]

    assert distribution(state_a, OLD_COLUMN) == expected
    assert distribution(state_b, OLD_COLUMN) == expected
    assert distribution(state_b, NEW_COLUMN) == expected
    assert distribution(state_c, NEW_COLUMN) == expected


def test_the_official_metadata_is_null_on_every_print_at_states_b_and_c(state_b, state_c):
    """b8d5f1c40e73 adds columns and writes nothing. NULL is the honest state
    until an importer populates them."""
    for db in (state_b, state_c):
        with db.engine.connect() as conn:
            counts = conn.execute(
                text(
                    "SELECT count(official_rarity), count(official_block_icon), "
                    "count(official_name), count(official_effect_text), count(*) "
                    "FROM card_prints"
                )
            ).one()
        assert tuple(counts) == (0, 0, 0, 0, 20)


def test_mappings_and_market_index_snapshots_are_untouched(state_a, state_b, state_c):
    """Both hang off card_prints.id through ON DELETE RESTRICT FKs, so they
    are evidence that no print was recreated on the way through."""
    assert _downstream_state(state_a) == _downstream_state(state_b)
    assert _downstream_state(state_b) == _downstream_state(state_c)

    mappings, snapshots = _downstream_state(state_c)
    assert mappings[0] == 1 and snapshots[0] == 1


# --- STATE C: the new schema, and the deliberate break ---------------------


def test_state_c_matches_the_orm_model_exactly(state_c):
    from app.models import CardPrint

    with state_c.engine.connect() as conn:
        columns = _columns(conn)

    assert columns == {c.name for c in CardPrint.__table__.columns}
    assert OLD_COLUMN not in columns


def test_state_c_enforces_identity_on_the_new_column(state_c):
    with state_c.engine.connect() as conn:
        state = _schema_state(conn)

    assert f"btree (canonical_card_id, language, release_product_id, {NEW_COLUMN})" in \
        state["index"]
    assert f"{NEW_COLUMN} IS NOT NULL" in state["verified_check"]
    assert list(dict(state["format_checks"])) == [
        "ck_card_prints_official_asset_variant_format"
    ]


def test_the_old_application_can_no_longer_read_at_state_c(state_c):
    """Intended, and the reason the contract migration is a separate release
    step an operator triggers only once the new application is healthy."""
    with pytest.raises(ProgrammingError) as excinfo, state_c.engine.connect() as conn:
        conn.execute(text(f"SELECT {OLD_COLUMN} FROM card_prints LIMIT 1"))

    assert OLD_COLUMN in str(excinfo.value)


def test_the_contract_migration_reports_its_preflight(state_c):
    """Belt and braces: the happy path really did run the preflight rather
    than skipping straight to the DDL."""
    db = _database_at("opcg_test_release_preflight_output", STATE_B)
    try:
        output = _alembic(db.url, "upgrade", CONTRACT)

        assert "preflight OK" in output
        assert "20 active+verified print(s)" in output
        assert f"{OLD_COLUMN} dropped" in output
    finally:
        db.close()


# --- the deployment order --------------------------------------------------


def test_the_documented_staging_order_runs_end_to_end():
    """The five steps a9f31c7d5b64's docstring writes down, in order, on one
    database - including the old-application checks that gate step D.

    Step B (deploying the new application) has no database action, so it is
    represented here by the thing that proves it possible: the new
    generation's queries answering correctly against the step-A schema while
    the old generation's queries still answer too.
    """
    db = _database_at("opcg_test_release_deployment_order", STATE_A, downstream=True)
    try:
        at_a = _print_facts(db, OLD_COLUMN)
        assert len(at_a) == 20

        # A. Migrate staging to the metadata revision. Nothing else changes.
        _alembic(db.url, "upgrade", STATE_B)
        with db.engine.connect() as conn:
            columns = _columns(conn)
            assert {OLD_COLUMN, NEW_COLUMN} <= columns
            assert set(OLD_APP_COLUMNS) <= columns
            # The old application is still the one identity is enforced for.
            assert f", {OLD_COLUMN})" in _schema_state(conn)["index"]

        # B/C. Both generations read the same 20 rows correctly.
        with db.engine.connect() as conn:
            old_reads = conn.execute(
                text(
                    f"SELECT id, {OLD_COLUMN} FROM card_prints "
                    "WHERE is_active = true AND verification_status = 'verified' ORDER BY id"
                )
            ).all()
            new_reads = conn.execute(
                text(
                    f"SELECT id, {NEW_COLUMN} FROM card_prints "
                    "WHERE is_active = true AND verification_status = 'verified' ORDER BY id"
                )
            ).all()
        assert [tuple(r) for r in old_reads] == [tuple(r) for r in new_reads]
        assert len(old_reads) == 20

        # D. Only now the contract migration, which re-proves the agreement.
        output = _alembic(db.url, "upgrade", CONTRACT)
        assert "preflight OK" in output

        # E. Verify: the new schema, the same 20 prints, nothing downstream moved.
        with db.engine.connect() as conn:
            assert OLD_COLUMN not in _columns(conn)
            assert f", {NEW_COLUMN})" in _schema_state(conn)["index"]
        assert _print_facts(db, NEW_COLUMN) == at_a
    finally:
        db.close()


# --- the round trip --------------------------------------------------------


def test_the_full_a_to_c_and_back_round_trip_preserves_everything():
    """A -> B -> C -> B -> A, with the 20 prints checked at every stop.

    The way back is representable because the fixture holds only base and pN
    data; rN is what makes the C -> B step refuse, which the next test covers.
    """
    db = _database_at("opcg_test_release_round_trip", STATE_A, downstream=True)
    try:
        at_a = _print_facts(db, OLD_COLUMN)
        with db.engine.connect() as conn:
            schema_at_a = _schema_state(conn)
        downstream_at_a = _downstream_state(db)

        _alembic(db.url, "upgrade", STATE_B)
        with db.engine.connect() as conn:
            schema_at_b = _schema_state(conn)
        assert _print_facts(db, OLD_COLUMN) == at_a
        assert _print_facts(db, NEW_COLUMN) == at_a

        _alembic(db.url, "upgrade", CONTRACT)
        assert _print_facts(db, NEW_COLUMN) == at_a

        # ...and back down.
        _alembic(db.url, "downgrade", METADATA)
        with db.engine.connect() as conn:
            assert _schema_state(conn) == schema_at_b
        assert _print_facts(db, OLD_COLUMN) == at_a
        assert _print_facts(db, NEW_COLUMN) == at_a

        _alembic(db.url, "downgrade", STATE_A)
        with db.engine.connect() as conn:
            assert _schema_state(conn) == schema_at_a
            assert NEW_COLUMN not in _columns(conn)
        assert _print_facts(db, OLD_COLUMN) == at_a
        assert _downstream_state(db) == downstream_at_a
    finally:
        db.close()


def test_the_contract_downgrade_refuses_rn_rather_than_coercing_it():
    """rN has no legal spelling in the legacy vocabulary. Going back would
    have to rewrite it to 'base' - merging two distinct printings - so it
    aborts instead, leaving State C exactly as it was."""
    db = _database_at("opcg_test_release_downgrade_rn", STATE_C)
    try:
        with db.engine.begin() as conn:
            card_id = _new_card(conn, "OP05-074")
            conn.execute(
                text(
                    "INSERT INTO card_prints (canonical_card_id, language, treatment, "
                    f"release_product_id, artwork_key, {NEW_COLUMN}, verification_status, "
                    "is_active) VALUES (:card, 'jp', 'normal', "
                    "(SELECT id FROM release_products ORDER BY id LIMIT 1), 'sha-r1', 'r1', "
                    "'verified', true)"
                ),
                {"card": card_id},
            )
        with db.engine.connect() as conn:
            before = _schema_state(conn)
            rows = conn.execute(text("SELECT count(*) FROM card_prints")).scalar_one()

        output = _alembic(db.url, "downgrade", METADATA, expect_success=False)

        assert "DOWNGRADE ABORTED" in output
        assert "carry an rN" in output
        assert "would merge distinct printings" in output
        with db.engine.connect() as conn:
            assert _schema_state(conn) == before
            assert OLD_COLUMN not in _columns(conn)
            assert conn.execute(text("SELECT count(*) FROM card_prints")).scalar_one() == rows
            assert conn.execute(
                text(f"SELECT count(*) FROM card_prints WHERE {NEW_COLUMN} = 'r1'")
            ).scalar_one() == 1
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == CONTRACT
    finally:
        db.close()


def test_the_contract_downgrade_restores_the_dual_column_state():
    """Not the pre-expand schema: official_asset_variant stays, and identity
    goes back onto the legacy column with every value copied back."""
    db = _database_at("opcg_test_release_downgrade_ok", STATE_B)
    try:
        with db.engine.connect() as conn:
            schema_at_b = _schema_state(conn)
        _alembic(db.url, "upgrade", CONTRACT)

        output = _alembic(db.url, "downgrade", METADATA)

        assert "downgrade preflight OK" in output
        assert f"copied 20 {NEW_COLUMN} value(s) back into {OLD_COLUMN}" in output
        with db.engine.connect() as conn:
            assert _schema_state(conn) == schema_at_b
            assert {OLD_COLUMN, NEW_COLUMN} <= _columns(conn)
            assert conn.execute(
                text(
                    f"SELECT count(*) FROM card_prints "
                    f"WHERE {NEW_COLUMN} IS DISTINCT FROM {OLD_COLUMN}"
                )
            ).scalar_one() == 0
    finally:
        db.close()
