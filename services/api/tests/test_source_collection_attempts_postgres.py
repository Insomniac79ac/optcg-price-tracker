"""Runs b8e3f1a70d95 for real on throwaway PostgreSQL databases.

Covers what only a live engine can prove about this table: that the status and
failure_stage CHECKs genuinely refuse a value outside their vocabulary, that a
selected-but-never-started row is accepted with started_at NULL, that a finish
without a start is refused, that (batch_run_id, source_card_mapping_id) is
unique, that selection order survives, and that the FK ondelete choices behave
as designed - deleting a mapping removes its telemetry, deleting an observation
leaves the attempt row standing with a NULL reference.

That last pair is the point of the file. The whole reason this table exists is
that evidence disappeared; a schema where pruning an observation also deleted
the record explaining it would reproduce the original defect one level up.

Never touches staging. Skips when no server answers.
"""

import itertools
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

REPO_ROOT = Path(__file__).resolve().parents[1]

HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
ADMIN_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/postgres"

PREVIOUS_HEAD = "c4a7e9d15b83"
THIS_REVISION = "b8e3f1a70d95"

TABLE = "source_collection_attempts"


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


def _seed_subject(db: _Database) -> dict:
    """One source, one canonical card, one print, one mapping, one observation
    - the minimum a telemetry row can legally point at."""
    with db.engine.begin() as conn:
        source_id = conn.execute(
            text(
                "INSERT INTO sources (name, base_url) VALUES ('yuyutei', 'https://yuyu-tei.jp')"
                " RETURNING id"
            )
        ).scalar_one()
        canonical_id = conn.execute(
            text(
                "INSERT INTO canonical_cards (card_code, name_en, card_type)"
                " VALUES ('OP13-050', 'Boa', 'CHARACTER') RETURNING id"
            )
        ).scalar_one()
        print_id = conn.execute(
            text(
                "INSERT INTO card_prints (canonical_card_id, language, is_active)"
                " VALUES (:c, 'jp', true) RETURNING id"
            ),
            {"c": canonical_id},
        ).scalar_one()
        mapping_id = conn.execute(
            text(
                "INSERT INTO source_card_mappings"
                " (source_id, source_card_id, source_url, card_print_id, is_active, review_status)"
                " VALUES (:s, 'OP13-050', 'https://yuyu-tei.jp/x', :p, true, 'approved')"
                " RETURNING id"
            ),
            {"s": source_id, "p": print_id},
        ).scalar_one()
        observation_id = conn.execute(
            text(
                "INSERT INTO price_observations"
                " (source_id, observed_at, price_type, price_jpy, card_print_id,"
                "  source_card_mapping_id)"
                " VALUES (:s, now(), 'sell', 50, :p, :m) RETURNING id"
            ),
            {"s": source_id, "p": print_id, "m": mapping_id},
        ).scalar_one()
    return {
        "source_id": source_id,
        "mapping_id": mapping_id,
        "observation_id": observation_id,
    }


@pytest.fixture(scope="module")
def migrated():
    db = _new_database("atlas_attempts_migration_test")
    try:
        _alembic(db.url, "upgrade", THIS_REVISION)
        yield db, _seed_subject(db)
    finally:
        db.close()


def _insert(db, subject, **overrides):
    values = {
        "batch_run_id": "run0001",
        "source_id": subject["source_id"],
        "source_card_mapping_id": subject["mapping_id"],
        "selection_ordinal": 1,
        "status": "selected",
        "started_at": None,
        "finished_at": None,
        "failure_stage": None,
        "failure_reason": None,
        "source_denied": False,
        "price_observation_id": None,
    }
    values.update(overrides)
    with db.engine.begin() as conn:
        return conn.execute(
            text(
                f"INSERT INTO {TABLE} (batch_run_id, source_id, source_card_mapping_id,"
                " selection_ordinal, status, started_at, finished_at, failure_stage,"
                " failure_reason, source_denied, price_observation_id)"
                " VALUES (:batch_run_id, :source_id, :source_card_mapping_id,"
                " :selection_ordinal, :status, :started_at, :finished_at, :failure_stage,"
                " :failure_reason, :source_denied, :price_observation_id) RETURNING id"
            ),
            values,
        ).scalar_one()


_EXTRA_MAPPING_SEQ = itertools.count(51)


def _extra_mapping(db, subject) -> int:
    """A fresh mapping id, so uniqueness tests are not fighting the
    (batch_run_id, source_card_mapping_id) constraint instead of the one they
    mean to test. The module-scoped database is shared, so each call must mint
    a distinct source_card_id/source_url."""
    n = next(_EXTRA_MAPPING_SEQ)
    with db.engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO source_card_mappings"
                " (source_id, source_card_id, source_url, is_active, review_status)"
                " VALUES (:s, :code, :url, true, 'approved') RETURNING id"
            ),
            {"s": subject["source_id"], "code": f"OP13-{n:03d}",
             "url": f"https://yuyu-tei.jp/sell/opc/card/op13/{10000 + n}"},
        ).scalar_one()


# --- revision chain ---------------------------------------------------------


def test_upgrade_reaches_this_revision(migrated):
    db, _ = migrated
    with db.engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            THIS_REVISION
        )


def test_the_table_did_not_exist_before(migrated):
    db, _ = migrated
    fresh = _new_database("atlas_attempts_before_test")
    try:
        _alembic(fresh.url, "upgrade", PREVIOUS_HEAD)
        with fresh.engine.connect() as conn:
            exists = conn.execute(
                text("SELECT to_regclass(:t) IS NOT NULL"), {"t": TABLE}
            ).scalar_one()
        assert exists is False
    finally:
        fresh.close()


# --- status / stage vocabulary ---------------------------------------------


@pytest.mark.parametrize(
    "status",
    [
        "selected",
        "written",
        "validation_failed",
        "no_extraction_attempted",
        "operational_error",
        "mapping_load_failed",
        "skipped",
    ],
)
def test_every_documented_status_is_accepted(migrated, status):
    db, subject = migrated
    # Every status but 'selected' is terminal and must therefore say when it
    # finished. 'skipped' finishes WITHOUT ever having started - that is the
    # whole point of the lifecycle - so only the others get a started_at.
    terminal = status != "selected"
    started = "now()" if terminal and status != "skipped" else "NULL"
    finished = "now()" if terminal else "NULL"
    with db.engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {TABLE} (batch_run_id, source_id, source_card_mapping_id, status,"
                f" selection_ordinal, started_at, finished_at)"
                f" VALUES (:b, :s, :m, :st, 1, {started}, {finished})"
            ),
            {"b": f"ok-{status}", "s": subject["source_id"], "m": subject["mapping_id"],
             "st": status},
        )


def test_an_unknown_status_is_refused(migrated):
    db, subject = migrated
    with pytest.raises(DBAPIError):
        _insert(db, subject, batch_run_id="bad-status", status="nearly_written")


def test_an_unknown_failure_stage_is_refused(migrated):
    db, subject = migrated
    with pytest.raises(DBAPIError):
        _insert(db, subject, batch_run_id="bad-stage", failure_stage="vibes")


def test_failure_stage_may_be_null(migrated):
    db, subject = migrated
    _insert(db, subject, batch_run_id="null-stage", failure_stage=None)


# --- the selected/started distinction ---------------------------------------


def test_a_selected_row_needs_no_started_at(migrated):
    db, subject = migrated
    row_id = _insert(db, subject, batch_run_id="sel-nostart", status="selected")
    with db.engine.connect() as conn:
        started = conn.execute(
            text(f"SELECT started_at FROM {TABLE} WHERE id = :i"), {"i": row_id}
        ).scalar_one()
    assert started is None


def test_a_skipped_row_finishes_without_ever_starting(migrated):
    """THE lifecycle case. The batch aborted before reaching this mapping: it
    was genuinely selected, genuinely never started, and genuinely reached a
    terminal outcome. All three must be representable at once, and an earlier
    CHECK ("finished implies started") made that impossible."""
    db, subject = migrated
    row_id = _insert(
        db, subject, batch_run_id="skip-finished", status="skipped",
        started_at=None, finished_at="2026-09-03T02:00:00Z",
    )
    with db.engine.connect() as conn:
        row = conn.execute(
            text(f"SELECT status, started_at, finished_at FROM {TABLE} WHERE id = :i"),
            {"i": row_id},
        ).one()
    assert row.status == "skipped"
    assert row.started_at is None
    assert row.finished_at is not None


def test_a_terminal_row_without_a_finish_is_refused(migrated):
    """The replacement rule: skipped rows must not be left permanently
    unfinished."""
    db, subject = migrated
    with pytest.raises(DBAPIError):
        _insert(
            db, subject, batch_run_id="skip-unfinished", status="skipped",
            started_at=None, finished_at=None,
        )


# finished_at is set EXACTLY WHEN the row is terminal. All four combinations
# are asserted together, because the earlier constraint was an implication
# rather than a biconditional and the one case it wrongly allowed - a
# 'selected' row carrying a finish time - was the one no test happened to
# cover.
@pytest.mark.parametrize(
    "label, status, finished, valid",
    [
        ("selected-unfinished", "selected", None, True),
        ("selected-finished", "selected", "2026-09-03T03:00:00Z", False),
        ("terminal-finished", "written", "2026-09-03T03:00:00Z", True),
        ("terminal-unfinished", "written", None, False),
    ],
)
def test_finished_at_is_set_exactly_when_the_row_is_terminal(
    migrated, label, status, finished, valid
):
    db, subject = migrated
    started = "2026-09-03T02:59:00Z" if status != "selected" else None
    kwargs = dict(
        batch_run_id=f"iff-{label}", status=status,
        started_at=started, finished_at=finished,
    )
    if valid:
        row_id = _insert(db, subject, **kwargs)
        with db.engine.connect() as conn:
            got = conn.execute(
                text(f"SELECT status, finished_at FROM {TABLE} WHERE id = :i"), {"i": row_id}
            ).one()
        assert got.status == status
        assert (got.finished_at is None) == (status == "selected")
    else:
        with pytest.raises(DBAPIError):
            _insert(db, subject, **kwargs)


def test_an_in_flight_row_stays_unfinished(migrated):
    """status='selected' with a started_at is the in-flight state, and it must
    still be refused a finish time - otherwise "is this attempt still running?"
    stops being answerable from the row."""
    db, subject = migrated
    _insert(
        db, subject, batch_run_id="in-flight-ok", status="selected",
        started_at="2026-09-03T02:59:00Z", finished_at=None,
    )
    with pytest.raises(DBAPIError):
        _insert(
            db, subject, batch_run_id="in-flight-bad", status="selected",
            started_at="2026-09-03T02:59:00Z", finished_at="2026-09-03T03:00:00Z",
        )


def test_a_selected_row_cannot_be_stamped_finished_by_update(migrated):
    """The constraint holds on transitions too, not just on insert."""
    db, subject = migrated
    row_id = _insert(db, subject, batch_run_id="iff-update", status="selected",
                     started_at=None, finished_at=None)
    with pytest.raises(DBAPIError):
        with db.engine.begin() as conn:
            conn.execute(
                text(f"UPDATE {TABLE} SET finished_at = now() WHERE id = :i"), {"i": row_id}
            )


def test_a_finish_before_its_start_is_refused(migrated):
    db, subject = migrated
    with pytest.raises(DBAPIError):
        _insert(
            db, subject, batch_run_id="backwards", status="written",
            started_at="2026-09-03T02:00:05Z", finished_at="2026-09-03T02:00:00Z",
        )


def test_selected_at_defaults_to_now(migrated):
    db, subject = migrated
    row_id = _insert(db, subject, batch_run_id="default-selected-at")
    with db.engine.connect() as conn:
        assert (
            conn.execute(
                text(f"SELECT selected_at IS NOT NULL FROM {TABLE} WHERE id = :i"), {"i": row_id}
            ).scalar_one()
            is True
        )


# --- the lifecycle paths, walked as real UPDATEs -----------------------------


def _walk(db, subject, batch, steps):
    """Insert a 'selected' row and apply each step as an UPDATE, so the CHECKs
    are evaluated on the actual transition rather than on a row conjured
    directly into its final shape."""
    row_id = _insert(db, subject, batch_run_id=batch, status="selected",
                     started_at=None, finished_at=None)
    for assignment in steps:
        with db.engine.begin() as conn:
            conn.execute(text(f"UPDATE {TABLE} SET {assignment} WHERE id = :i"), {"i": row_id})
    with db.engine.connect() as conn:
        return conn.execute(
            text(f"SELECT status, started_at, finished_at FROM {TABLE} WHERE id = :i"),
            {"i": row_id},
        ).one()


def test_selected_to_written_is_permitted(migrated):
    db, subject = migrated
    row = _walk(db, subject, "walk-written",
                ["started_at = now()", "status = 'written', finished_at = now()"])
    assert row.status == "written" and row.started_at and row.finished_at


def test_selected_to_started_to_validation_failed_is_permitted(migrated):
    db, subject = migrated
    row = _walk(db, subject, "walk-validation",
                ["started_at = now()",
                 "status = 'validation_failed', finished_at = now(),"
                 " failure_stage = 'validation'"])
    assert row.status == "validation_failed" and row.started_at


def test_selected_to_started_to_operational_error_is_permitted(migrated):
    db, subject = migrated
    row = _walk(db, subject, "walk-operational",
                ["started_at = now()",
                 "status = 'operational_error', finished_at = now(),"
                 " failure_stage = 'browser_launch'"])
    assert row.status == "operational_error" and row.started_at


def test_selected_to_skipped_without_a_start_is_permitted(migrated):
    """The transition the old CHECK made impossible."""
    db, subject = migrated
    row = _walk(db, subject, "walk-skip-nostart",
                ["status = 'skipped', finished_at = now()"])
    assert row.status == "skipped"
    assert row.started_at is None
    assert row.finished_at is not None


def test_selected_to_started_to_skipped_is_permitted(migrated):
    db, subject = migrated
    row = _walk(db, subject, "walk-skip-started",
                ["started_at = now()", "status = 'skipped', finished_at = now()"])
    assert row.status == "skipped" and row.started_at and row.finished_at


def test_the_schema_itself_does_not_freeze_terminal_rows(migrated):
    """Stated rather than assumed: terminal immutability is a RECORDER rule,
    enforced in yuyutei_collector.telemetry, which is the only writer. The
    CHECKs constrain row shape, not history, and a bare UPDATE still succeeds
    here - which is why the recorder refuses unconditionally and offers no
    bypass to switch off."""
    db, subject = migrated
    row_id = _insert(db, subject, batch_run_id="raw-update", status="written",
                     started_at="2026-09-03T02:00:00Z", finished_at="2026-09-03T02:00:05Z")
    with db.engine.begin() as conn:
        conn.execute(text(f"UPDATE {TABLE} SET status = 'skipped' WHERE id = :i"), {"i": row_id})
    with db.engine.connect() as conn:
        assert conn.execute(
            text(f"SELECT status FROM {TABLE} WHERE id = :i"), {"i": row_id}
        ).scalar_one() == "skipped"


# --- uniqueness and ordering ------------------------------------------------


def test_one_row_per_run_per_mapping(migrated):
    db, subject = migrated
    _insert(db, subject, batch_run_id="dup-run")
    with pytest.raises(IntegrityError):
        _insert(db, subject, batch_run_id="dup-run")


def test_the_same_mapping_may_appear_in_different_runs(migrated):
    db, subject = migrated
    _insert(db, subject, batch_run_id="run-a")
    _insert(db, subject, batch_run_id="run-b")


def test_selection_order_is_persisted(migrated):
    """Execution order must survive even for mappings that never ran."""
    db, subject = migrated
    for ordinal in (3, 1, 2):
        with db.engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {TABLE} (batch_run_id, source_id, source_card_mapping_id,"
                    " selection_ordinal, status) VALUES (:b, :s, :m, :o, 'selected')"
                ),
                {"b": f"ordinal-{ordinal}", "s": subject["source_id"],
                 "m": subject["mapping_id"], "o": ordinal},
            )
    with db.engine.connect() as conn:
        ordinals = conn.execute(
            text(
                f"SELECT selection_ordinal FROM {TABLE} WHERE batch_run_id LIKE 'ordinal-%'"
                " ORDER BY selection_ordinal"
            )
        ).scalars().all()
    assert ordinals == [1, 2, 3]


def test_selection_ordinal_may_not_be_null(migrated):
    """Batch-scoped telemetry: every row belongs to a recorded population, so
    there is no legitimate row without a position."""
    db, subject = migrated
    with pytest.raises(DBAPIError):
        _insert(db, subject, batch_run_id="null-ordinal", selection_ordinal=None)


def test_a_zero_or_negative_ordinal_is_refused(migrated):
    """NULL already means "no position"; a 0 would let a missing value pass
    for one."""
    db, subject = migrated
    for bad in (0, -1):
        with pytest.raises(DBAPIError):
            _insert(db, subject, batch_run_id=f"ordinal-bad-{bad}", selection_ordinal=bad)


def test_two_mappings_cannot_claim_the_same_position_in_one_run(migrated):
    """selection_ordinal was added so exact batch order survives log loss; a
    duplicate would destroy the fact it exists to preserve."""
    db, subject = migrated
    second_mapping = _extra_mapping(db, subject)
    _insert(db, subject, batch_run_id="dup-ordinal", selection_ordinal=7)
    with pytest.raises(IntegrityError):
        _insert(
            db, subject, batch_run_id="dup-ordinal",
            source_card_mapping_id=second_mapping, selection_ordinal=7,
        )


def test_the_same_position_in_different_runs_is_fine(migrated):
    db, subject = migrated
    _insert(db, subject, batch_run_id="pos-run-a", selection_ordinal=7)
    _insert(db, subject, batch_run_id="pos-run-b", selection_ordinal=7)


def test_positions_in_one_run_form_a_total_order(migrated):
    """With the column NOT NULL the unique constraint is a plain total
    ordering - no NULL escape hatch through which two rows could share a
    position."""
    db, subject = migrated
    second = _extra_mapping(db, subject)
    third = _extra_mapping(db, subject)
    _insert(db, subject, batch_run_id="total-order", selection_ordinal=1)
    _insert(db, subject, batch_run_id="total-order",
            source_card_mapping_id=second, selection_ordinal=2)
    with pytest.raises(IntegrityError):
        _insert(db, subject, batch_run_id="total-order",
                source_card_mapping_id=third, selection_ordinal=2)


# --- FK behaviour: the reason this table exists -----------------------------


def test_deleting_an_observation_keeps_the_attempt_and_nulls_the_reference():
    """SET NULL, not CASCADE. If an observation is pruned, the record that
    explains how it came to exist must outlive it - otherwise this table
    reproduces the very evidence loss it was created to end."""
    db = _new_database("atlas_attempts_fk_obs_test")
    try:
        _alembic(db.url, "upgrade", THIS_REVISION)
        subject = _seed_subject(db)
        row_id = _insert(
            db, subject, batch_run_id="obs-del", status="written",
            started_at="2026-09-03T00:00:00Z", finished_at="2026-09-03T00:00:05Z",
            price_observation_id=subject["observation_id"],
        )
        with db.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM price_observations WHERE id = :i"),
                {"i": subject["observation_id"]},
            )
        with db.engine.connect() as conn:
            row = conn.execute(
                text(f"SELECT status, price_observation_id FROM {TABLE} WHERE id = :i"),
                {"i": row_id},
            ).one()
        assert row.status == "written"
        assert row.price_observation_id is None
    finally:
        db.close()


def test_deleting_the_mapping_neither_blocks_nor_erases_its_telemetry():
    """The delete-behaviour decision, proved on a live engine.

    A. Six months of history must NOT vanish because a mapping was deleted.
    B/C. And telemetry must not block that delete either. A plain id gives
    both; CASCADE gave the first away and RESTRICT would have given the second.
    """
    db = _new_database("atlas_attempts_fk_map_test")
    try:
        _alembic(db.url, "upgrade", THIS_REVISION)
        subject = _seed_subject(db)
        _insert(db, subject, batch_run_id="map-del", status="written",
                started_at="2026-09-03T02:00:00Z", finished_at="2026-09-03T02:00:05Z")
        with db.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM price_observations WHERE source_card_mapping_id = :m"),
                {"m": subject["mapping_id"]},
            )
            # This must simply succeed - no RESTRICT, no error.
            conn.execute(
                text("DELETE FROM source_card_mappings WHERE id = :m"),
                {"m": subject["mapping_id"]},
            )
        with db.engine.connect() as conn:
            row = conn.execute(
                text(f"SELECT status, source_card_mapping_id FROM {TABLE}")
            ).one()
        assert row.status == "written"
        assert row.source_card_mapping_id == subject["mapping_id"]  # history intact
    finally:
        db.close()


def test_deleting_the_source_neither_blocks_nor_erases_its_telemetry():
    db = _new_database("atlas_attempts_fk_source_test")
    try:
        _alembic(db.url, "upgrade", THIS_REVISION)
        subject = _seed_subject(db)
        _insert(db, subject, batch_run_id="src-del", status="written",
                started_at="2026-09-03T02:00:00Z", finished_at="2026-09-03T02:00:05Z")
        with db.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM price_observations WHERE source_id = :s"),
                {"s": subject["source_id"]},
            )
            conn.execute(
                text("DELETE FROM source_card_mappings WHERE source_id = :s"),
                {"s": subject["source_id"]},
            )
            conn.execute(text("DELETE FROM sources WHERE id = :s"), {"s": subject["source_id"]})
        with db.engine.connect() as conn:
            row = conn.execute(text(f"SELECT status, source_id FROM {TABLE}")).one()
        assert row.status == "written"
        assert row.source_id == subject["source_id"]
    finally:
        db.close()


# --- downgrade --------------------------------------------------------------


def test_downgrade_removes_the_table_and_upgrade_restores_it():
    db = _new_database("atlas_attempts_downgrade_test")
    try:
        _alembic(db.url, "upgrade", THIS_REVISION)
        _alembic(db.url, "downgrade", PREVIOUS_HEAD)
        with db.engine.connect() as conn:
            assert (
                conn.execute(text("SELECT to_regclass(:t) IS NOT NULL"), {"t": TABLE}).scalar_one()
                is False
            )
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == PREVIOUS_HEAD
        _alembic(db.url, "upgrade", THIS_REVISION)
        with db.engine.connect() as conn:
            assert (
                conn.execute(text("SELECT to_regclass(:t) IS NOT NULL"), {"t": TABLE}).scalar_one()
                is True
            )
    finally:
        db.close()


def test_downgrade_leaves_price_observations_untouched():
    db = _new_database("atlas_attempts_downgrade_obs_test")
    try:
        _alembic(db.url, "upgrade", THIS_REVISION)
        subject = _seed_subject(db)
        with db.engine.connect() as conn:
            before = conn.execute(
                text("SELECT count(*), sum(price_jpy) FROM price_observations")
            ).one()
        _alembic(db.url, "downgrade", PREVIOUS_HEAD)
        with db.engine.connect() as conn:
            after = conn.execute(
                text("SELECT count(*), sum(price_jpy) FROM price_observations")
            ).one()
        assert before == after
        assert subject["observation_id"] is not None
    finally:
        db.close()
