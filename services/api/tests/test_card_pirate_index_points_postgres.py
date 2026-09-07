"""Runs c9d2f47a6b31 for real on throwaway PostgreSQL databases.

Everything this file proves is invisible to the default suite. The suite runs
on in-memory SQLite, which does not enforce foreign keys unless
PRAGMA foreign_keys=ON is set (conftest does not set it), so the composite
carry key - the constraint that actually implements "a carried base must
resolve to the same scope and an identical index_value" - is entirely
unexercised there. A green SQLite run says nothing about it.

The cases below mirror section 8.5 of docs/card_pirate_index.md one for one,
so the methodology document's proof table and this file cannot drift apart
without a test failing.

Two behaviours are worth calling out because they are easy to get wrong and
neither is obvious from reading the DDL:

  * MATCH SIMPLE (the Postgres default) skips the ENTIRE foreign key when any
    referencing column is NULL. A carried base with a NULL index_value would
    therefore slip past the key unchecked - except that
    ck_cpi_points_base_has_value rejects it one constraint earlier. The two
    have to be read together, and test_carried_base_with_null_value_rejected
    is what keeps that true.

  * A CHECK constraint PASSES on NULL. movers_up = 1 beside a NULL
    movers_down makes the movers-sum check evaluate to NULL and therefore
    succeed, which is why ck_cpi_points_movers_pairing exists at all.

Never touches staging. Skips when no server answers.
"""

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

PREVIOUS_HEAD = "b8e3f1a70d95"
THIS_REVISION = "c9d2f47a6b31"

TABLE = "card_pirate_index_points"


def _alembic(url: str, *args: str):
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


@pytest.fixture(scope="module")
def migrated():
    db = _new_database("atlas_cpi_points_migration_test")
    try:
        _alembic(db.url, "upgrade", THIS_REVISION)
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _clean(migrated):
    """Each test starts from an empty table. The database is module-scoped so
    the migration runs once, but carry references make leftover rows an
    active hazard rather than mere noise."""
    with migrated.engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLE} RESTART IDENTITY"))
    yield


_COLUMNS = (
    "scope_kind, scope_key, methodology_version, index_version,"
    " source_semantics_version, point_date, index_value, is_base,"
    " carried_from_point_id, prior_point_date, step_days, chain_link_log_return,"
    " constituent_count, eligible_print_count, movers_up, movers_down,"
    " movers_flat, capped_count, unpublishable_reason, calculated_at"
)
_PLACEHOLDERS = ", ".join(f":{c.strip()}" for c in _COLUMNS.split(","))


def _values(**overrides) -> dict:
    values = {
        "scope_kind": "overall",
        "scope_key": "",
        "methodology_version": 1,
        "index_version": 3,
        "source_semantics_version": 2,
        "point_date": "2026-09-03",
        "index_value": None,
        "is_base": False,
        "carried_from_point_id": None,
        "prior_point_date": None,
        "step_days": None,
        "chain_link_log_return": None,
        "constituent_count": 0,
        "eligible_print_count": 0,
        "movers_up": None,
        "movers_down": None,
        "movers_flat": None,
        "capped_count": None,
        "unpublishable_reason": None,
        "calculated_at": "2026-09-07T20:00:00+00:00",
    }
    values.update(overrides)
    return values


def _insert(db, **overrides) -> int:
    with db.engine.begin() as conn:
        return conn.execute(
            text(f"INSERT INTO {TABLE} ({_COLUMNS}) VALUES ({_PLACEHOLDERS}) RETURNING id"),
            _values(**overrides),
        ).scalar_one()


def _rejected_by(db, **overrides) -> str:
    """Inserts a row that must fail, and returns the constraint that stopped
    it. Asserting on the NAME rather than merely on failure is the point: a
    row rejected by the wrong constraint would leave the intended one
    unproven."""
    with pytest.raises(IntegrityError) as excinfo:
        _insert(db, **overrides)
    return excinfo.value.orig.diag.constraint_name


# --- the shapes the methodology actually writes -----------------------------


def _initial_base(db, **overrides) -> int:
    """2026-09-03, the frozen clean start: is_base, no carry, exactly 1000."""
    return _insert(
        db,
        **_values(
            point_date="2026-09-03", index_value=1000, is_base=True,
            eligible_print_count=231, **overrides
        ),
    )


def _ordinary_step(db, prior_id=None, **overrides) -> int:
    """2026-09-04, the first real step: +0.000840502227 over 231 constituents,
    one mover up, nothing capped. The numbers are the recomputed staging
    values from section 17.1, so a fixture drifting from the methodology is
    visible."""
    return _insert(
        db,
        **_values(
            point_date="2026-09-04", index_value="1000.8409",
            prior_point_date="2026-09-03", step_days=1,
            chain_link_log_return="0.000840502227",
            constituent_count=231, eligible_print_count=281,
            movers_up=1, movers_down=0, movers_flat=230, capped_count=0,
            **overrides
        ),
    )


# --- revision chain ---------------------------------------------------------


def test_upgrade_reaches_this_revision(migrated):
    with migrated.engine.connect() as conn:
        assert conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == THIS_REVISION


def test_the_table_did_not_exist_before(migrated):
    fresh = _new_database("atlas_cpi_points_before_test")
    try:
        _alembic(fresh.url, "upgrade", PREVIOUS_HEAD)
        with fresh.engine.connect() as conn:
            assert conn.execute(
                text("SELECT to_regclass(:t) IS NOT NULL"), {"t": TABLE}
            ).scalar_one() is False
    finally:
        fresh.close()


def test_downgrade_drops_only_this_table(migrated):
    """Round-trips a separate database rather than the module fixture, and
    checks that every other table survives - the additive claim in the
    migration docstring is only worth making if it is tested."""
    db = _new_database("atlas_cpi_points_downgrade_test")
    try:
        _alembic(db.url, "upgrade", PREVIOUS_HEAD)
        with db.engine.connect() as conn:
            before = set(
                conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname='public'"
                    )
                ).scalars()
            )

        _alembic(db.url, "upgrade", THIS_REVISION)
        with db.engine.connect() as conn:
            after_upgrade = set(
                conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname='public'"
                    )
                ).scalars()
            )
        assert after_upgrade - before == {TABLE}

        _alembic(db.url, "downgrade", PREVIOUS_HEAD)
        with db.engine.connect() as conn:
            after_downgrade = set(
                conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname='public'"
                    )
                ).scalars()
            )
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == PREVIOUS_HEAD
        assert after_downgrade == before
    finally:
        db.close()


def test_upgrade_is_repeatable_after_downgrade(migrated):
    """A downgrade that cannot be re-upgraded is a one-way door. This is also
    the shape a deploy rollback takes."""
    db = _new_database("atlas_cpi_points_roundtrip_test")
    try:
        _alembic(db.url, "upgrade", THIS_REVISION)
        _alembic(db.url, "downgrade", PREVIOUS_HEAD)
        _alembic(db.url, "upgrade", THIS_REVISION)
        with db.engine.connect() as conn:
            assert conn.execute(
                text("SELECT to_regclass(:t) IS NOT NULL"), {"t": TABLE}
            ).scalar_one() is True
    finally:
        db.close()


# --- the carry: what is accepted --------------------------------------------


def test_initial_base_accepted(migrated):
    point_id = _initial_base(migrated)
    with migrated.engine.connect() as conn:
        row = conn.execute(
            text(
                f"SELECT is_base, carried_from_point_id, index_value FROM {TABLE}"
                " WHERE id = :i"
            ),
            {"i": point_id},
        ).one()
    assert row.is_base is True
    assert row.carried_from_point_id is None
    assert float(row.index_value) == 1000.0


def test_ordinary_point_accepted_and_carries_nothing(migrated):
    _initial_base(migrated)
    point_id = _ordinary_step(migrated)
    with migrated.engine.connect() as conn:
        row = conn.execute(
            text(
                f"SELECT is_base, carried_from_point_id, constituent_count"
                f" FROM {TABLE} WHERE id = :i"
            ),
            {"i": point_id},
        ).one()
    assert row.is_base is False
    assert row.carried_from_point_id is None
    assert row.constituent_count == 231


def test_carried_base_accepted(migrated):
    """The v3 -> v4 boundary: a new segment opening at the previous segment's
    final published level rather than resetting to 1000."""
    _initial_base(migrated)
    step_id = _ordinary_step(migrated)
    carried_id = _insert(
        migrated,
        point_date="2026-09-05", index_value="1000.8409", is_base=True,
        index_version=4, carried_from_point_id=step_id, eligible_print_count=290,
    )
    with migrated.engine.connect() as conn:
        carried, source = conn.execute(
            text(
                f"SELECT p.index_value, s.index_value FROM {TABLE} p"
                f" JOIN {TABLE} s ON s.id = p.carried_from_point_id WHERE p.id = :i"
            ),
            {"i": carried_id},
        ).one()
    assert carried == source, "a carried base must open at exactly the source level"


def test_carried_base_is_exempt_from_the_base_value_rule(migrated):
    """Only an INITIAL base is pinned to 1000. If this ever regressed, every
    boundary would silently reset the visible level - the exact behaviour
    section 5 exists to forbid."""
    _initial_base(migrated)
    step_id = _ordinary_step(migrated)
    _insert(
        migrated,
        point_date="2026-09-05", index_value="1000.8409", is_base=True,
        index_version=4, carried_from_point_id=step_id, eligible_print_count=290,
    )


# --- the carry: what is rejected --------------------------------------------


def test_non_base_cannot_carry(migrated):
    _initial_base(migrated)
    step_id = _ordinary_step(migrated)
    assert _rejected_by(
        migrated,
        point_date="2026-09-06", index_value="1000.8409", is_base=False,
        carried_from_point_id=step_id, prior_point_date="2026-09-04", step_days=2,
        chain_link_log_return=0, constituent_count=5, eligible_print_count=5,
        movers_up=0, movers_down=0, movers_flat=5, capped_count=0,
    ) == "ck_cpi_points_carry_requires_base"


def test_self_carry_rejected(migrated):
    """The foreign key alone would accept a row pointing at itself, so this
    proves the CHECK is what forbids it - not the key."""
    _initial_base(migrated)
    with migrated.engine.begin() as conn:
        with pytest.raises(IntegrityError) as excinfo:
            conn.execute(
                text(
                    f"INSERT INTO {TABLE} ({_COLUMNS})"
                    f" VALUES ('overall', '', 1, 4, 2, '2026-09-05', 1000.8409, true,"
                    f" (SELECT COALESCE(MAX(id), 0) + 1 FROM {TABLE}),"
                    "  NULL, NULL, NULL, 0, 290, NULL, NULL, NULL, NULL, NULL,"
                    "  '2026-09-07T20:00:00+00:00')"
                )
            )
    assert excinfo.value.orig.diag.constraint_name == "ck_cpi_points_carry_not_self"


def test_cross_scope_carry_rejected(migrated):
    """An 'overall' segment may not inherit its level from a 'set' series.
    One composite key enforces this and the level equality together."""
    _initial_base(migrated)
    set_base_id = _insert(
        migrated,
        scope_kind="set", scope_key="OP-01", point_date="2026-09-03",
        index_value=1000, is_base=True, eligible_print_count=81,
    )
    assert _rejected_by(
        migrated,
        point_date="2026-09-05", index_value=1000, is_base=True, index_version=4,
        carried_from_point_id=set_base_id, eligible_print_count=290,
    ) == "fk_cpi_points_carried_from"


def test_carried_level_mismatch_rejected(migrated):
    _initial_base(migrated)
    step_id = _ordinary_step(migrated)
    assert _rejected_by(
        migrated,
        point_date="2026-09-05", index_value="1001.0000", is_base=True,
        index_version=4, carried_from_point_id=step_id, eligible_print_count=290,
    ) == "fk_cpi_points_carried_from"


def test_carried_base_with_null_value_rejected(migrated):
    """Closes the MATCH SIMPLE escape hatch. Without
    ck_cpi_points_base_has_value the NULL index_value would disable the whole
    foreign key and this row would be accepted with an unverified carry."""
    _initial_base(migrated)
    step_id = _ordinary_step(migrated)
    assert _rejected_by(
        migrated,
        point_date="2026-09-05", index_value=None, is_base=True, index_version=4,
        carried_from_point_id=step_id,
        unpublishable_reason="insufficient_constituents", eligible_print_count=10,
    ) == "ck_cpi_points_base_has_value"


def test_forward_carry_reference_rejected(migrated):
    """The normal insert path can only carry from a point that ALREADY
    EXISTS. This is what makes the chain acyclic by construction, and it is
    why insertion order (ascending point_date within a scope) is a
    requirement rather than a style preference."""
    _initial_base(migrated)
    assert _rejected_by(
        migrated,
        point_date="2026-09-05", index_value=1000, is_base=True, index_version=4,
        carried_from_point_id=999999, eligible_print_count=290,
    ) == "fk_cpi_points_carried_from"


def test_carry_source_cannot_be_deleted(migrated):
    """ON DELETE RESTRICT: the chain cannot be silently truncated."""
    _initial_base(migrated)
    step_id = _ordinary_step(migrated)
    _insert(
        migrated,
        point_date="2026-09-05", index_value="1000.8409", is_base=True,
        index_version=4, carried_from_point_id=step_id, eligible_print_count=290,
    )
    with pytest.raises(IntegrityError) as excinfo:
        with migrated.engine.begin() as conn:
            conn.execute(text(f"DELETE FROM {TABLE} WHERE id = :i"), {"i": step_id})
    assert excinfo.value.orig.diag.constraint_name == "fk_cpi_points_carried_from"


def test_carry_source_level_cannot_be_updated(migrated):
    """ON UPDATE RESTRICT. This is the one place the append-only contract is
    enforced by the database rather than only by the absence of a writer."""
    _initial_base(migrated)
    step_id = _ordinary_step(migrated)
    _insert(
        migrated,
        point_date="2026-09-05", index_value="1000.8409", is_base=True,
        index_version=4, carried_from_point_id=step_id, eligible_print_count=290,
    )
    with pytest.raises(IntegrityError) as excinfo:
        with migrated.engine.begin() as conn:
            conn.execute(
                text(f"UPDATE {TABLE} SET index_value = 999.0000 WHERE id = :i"),
                {"i": step_id},
            )
    assert excinfo.value.orig.diag.constraint_name == "fk_cpi_points_carried_from"


# --- base-row rules ---------------------------------------------------------


def test_initial_base_must_be_exactly_base_value(migrated):
    assert _rejected_by(
        migrated,
        scope_kind="rarity", scope_key="SR", point_date="2026-09-03",
        index_value=1200, is_base=True, eligible_print_count=40,
    ) == "ck_cpi_points_initial_base_is_base_value"


def test_base_row_cannot_carry_a_step(migrated):
    assert _rejected_by(
        migrated,
        point_date="2026-09-03", index_value=1000, is_base=True,
        chain_link_log_return="0.001", eligible_print_count=231,
    ) == "ck_cpi_points_base_has_no_step"


def test_published_non_base_needs_a_prior_point(migrated):
    _initial_base(migrated)
    assert _rejected_by(
        migrated,
        point_date="2026-09-04", index_value="1000.8409", prior_point_date=None,
        constituent_count=231, eligible_print_count=281,
        movers_up=1, movers_down=0, movers_flat=230, capped_count=0,
    ) == "ck_cpi_points_step_requires_prior"


# --- publishability ---------------------------------------------------------


def test_unpublishable_point_accepted(migrated):
    """A mixed-version day is a real, recorded outcome - not an error and not
    an absent row."""
    _initial_base(migrated)
    point_id = _insert(
        migrated,
        point_date="2026-09-04", index_value=None,
        unpublishable_reason="mixed_version_day",
        constituent_count=0, eligible_print_count=300,
    )
    with migrated.engine.connect() as conn:
        assert conn.execute(
            text(f"SELECT unpublishable_reason FROM {TABLE} WHERE id = :i"),
            {"i": point_id},
        ).scalar_one() == "mixed_version_day"


def test_value_without_reason_and_reason_without_value_both_rejected(migrated):
    assert _rejected_by(
        migrated,
        point_date="2026-09-04", index_value=None, unpublishable_reason=None,
        constituent_count=0, eligible_print_count=10,
    ) == "ck_cpi_points_value_presence"

    _initial_base(migrated)
    assert _rejected_by(
        migrated,
        point_date="2026-09-04", index_value="1000.5", prior_point_date="2026-09-03",
        step_days=1, chain_link_log_return=0,
        unpublishable_reason="mixed_version_day",
        constituent_count=100, eligible_print_count=100,
        movers_up=0, movers_down=0, movers_flat=100, capped_count=0,
    ) == "ck_cpi_points_value_presence"


# --- breadth / mover invariants ---------------------------------------------


def test_breadth_missing_while_constituents_present_rejected(migrated):
    _initial_base(migrated)
    assert _rejected_by(
        migrated,
        point_date="2026-09-04", index_value="1000.8409",
        prior_point_date="2026-09-03", step_days=1, chain_link_log_return=0,
        constituent_count=231, eligible_print_count=281,
    ) == "ck_cpi_points_breadth_presence"


@pytest.mark.parametrize(
    "missing", ["movers_down", "movers_flat", "capped_count"],
)
def test_partial_mover_nulls_rejected(migrated, missing):
    """Each counter individually. Without the pairing check the sum check
    evaluates to NULL and a CHECK passes on NULL, so every one of these would
    be silently accepted."""
    _initial_base(migrated)
    overrides = {
        "point_date": "2026-09-04", "index_value": "1000.8409",
        "prior_point_date": "2026-09-03", "step_days": 1,
        "chain_link_log_return": 0,
        "constituent_count": 1, "eligible_print_count": 1,
        "movers_up": 1, "movers_down": 0, "movers_flat": 0, "capped_count": 0,
    }
    overrides[missing] = None
    assert _rejected_by(migrated, **overrides) == "ck_cpi_points_movers_pairing"


def test_movers_must_sum_to_constituent_count(migrated):
    _initial_base(migrated)
    assert _rejected_by(
        migrated,
        point_date="2026-09-04", index_value="1000.8409",
        prior_point_date="2026-09-03", step_days=1, chain_link_log_return=0,
        constituent_count=231, eligible_print_count=281,
        movers_up=1, movers_down=0, movers_flat=229, capped_count=0,
    ) == "ck_cpi_points_movers_sum"


def test_breadth_present_while_no_constituents_rejected(migrated):
    """The other direction of the biconditional. A base row reporting movers
    would be claiming a step it never took."""
    assert _rejected_by(
        migrated,
        point_date="2026-09-03", index_value=1000, is_base=True,
        eligible_print_count=231,
        movers_up=0, movers_down=0, movers_flat=0, capped_count=0,
    ) == "ck_cpi_points_breadth_presence"


def test_capped_count_cannot_exceed_constituents(migrated):
    _initial_base(migrated)
    assert _rejected_by(
        migrated,
        point_date="2026-09-04", index_value="1000.8409",
        prior_point_date="2026-09-03", step_days=1, chain_link_log_return=0,
        constituent_count=5, eligible_print_count=5,
        movers_up=1, movers_down=0, movers_flat=4, capped_count=6,
    ) == "ck_cpi_points_capped_le_constituents"


def test_constituents_cannot_exceed_eligible_prints(migrated):
    _initial_base(migrated)
    assert _rejected_by(
        migrated,
        point_date="2026-09-04", index_value="1000.8409",
        prior_point_date="2026-09-03", step_days=1, chain_link_log_return=0,
        constituent_count=300, eligible_print_count=281,
        movers_up=0, movers_down=0, movers_flat=300, capped_count=0,
    ) == "ck_cpi_points_constituents_le_eligible"


# --- scope + natural key ----------------------------------------------------


def test_duplicate_natural_key_rejected(migrated):
    _initial_base(migrated)
    _ordinary_step(migrated)
    assert _rejected_by(
        migrated,
        point_date="2026-09-04", index_value="1000.9",
        prior_point_date="2026-09-03", step_days=1, chain_link_log_return=0,
        constituent_count=231, eligible_print_count=281,
        movers_up=0, movers_down=0, movers_flat=231, capped_count=0,
    ) == "uq_cpi_points_point"


def test_same_day_is_allowed_in_a_different_scope(migrated):
    """The natural key is scope-qualified, so a set sub-index shares dates
    with the overall series without colliding."""
    _initial_base(migrated)
    _insert(
        migrated,
        scope_kind="set", scope_key="OP-01", point_date="2026-09-03",
        index_value=1000, is_base=True, eligible_print_count=81,
    )


def test_scope_key_pairing_enforced_in_both_directions(migrated):
    assert _rejected_by(
        migrated,
        scope_kind="overall", scope_key="OP-01", point_date="2026-09-03",
        index_value=1000, is_base=True, eligible_print_count=231,
    ) == "ck_cpi_points_scope_key_pairing"
    assert _rejected_by(
        migrated,
        scope_kind="set", scope_key="", point_date="2026-09-03",
        index_value=1000, is_base=True, eligible_print_count=81,
    ) == "ck_cpi_points_scope_key_pairing"


def test_unknown_scope_kind_rejected(migrated):
    assert _rejected_by(
        migrated,
        scope_kind="colour", scope_key="red", point_date="2026-09-03",
        index_value=1000, is_base=True, eligible_print_count=10,
    ) == "ck_cpi_points_scope_kind"


# --- the shape the future job depends on ------------------------------------


def test_natural_key_upsert_is_a_no_op_on_re_run(migrated):
    """ON CONFLICT DO NOTHING on the natural key is the idempotency contract
    the daily job and the replay both rely on. A re-run must not rewrite a
    carry, because surrogate ids would move under it."""
    _initial_base(migrated)
    step_id = _ordinary_step(migrated)
    carried_id = _insert(
        migrated,
        point_date="2026-09-05", index_value="1000.8409", is_base=True,
        index_version=4, carried_from_point_id=step_id, eligible_print_count=290,
    )
    with migrated.engine.begin() as conn:
        before = conn.execute(
            text(f"SELECT id, carried_from_point_id FROM {TABLE} ORDER BY id")
        ).all()
        inserted = conn.execute(
            text(
                f"INSERT INTO {TABLE} ({_COLUMNS}) VALUES ({_PLACEHOLDERS})"
                " ON CONFLICT (scope_kind, scope_key, methodology_version, point_date)"
                " DO NOTHING RETURNING id"
            ),
            _values(
                point_date="2026-09-05", index_value="1000.8409", is_base=True,
                index_version=4, carried_from_point_id=step_id,
                eligible_print_count=290,
            ),
        ).all()
        after = conn.execute(
            text(f"SELECT id, carried_from_point_id FROM {TABLE} ORDER BY id")
        ).all()
    assert inserted == [], "a re-run must insert nothing"
    assert before == after
    assert (carried_id, step_id) in after


def test_exactly_three_indexes_exist(migrated):
    """The methodology budgets for three: the primary key, the read path, and
    the foreign key's target. A fourth appearing means someone added an index
    the document did not account for."""
    with migrated.engine.connect() as conn:
        names = set(
            conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = :t"),
                {"t": TABLE},
            ).scalars()
        )
    assert names == {
        f"{TABLE}_pkey",
        "uq_cpi_points_point",
        "uq_cpi_points_carry_target",
    }
