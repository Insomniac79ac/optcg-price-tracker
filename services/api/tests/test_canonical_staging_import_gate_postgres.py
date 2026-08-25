"""4D-1 tests I and J: the confirmed staging path against a real database.

The database here is a DISPOSABLE one, built from the migrations by
tests/test_canonical_import_apply_postgres.py's harness and dropped afterwards.
Canonical staging is never touched: what is proved is that a run carrying a
real grant behaves exactly as the engine's own tests say the engine behaves -
it writes when everything agrees, and it still refuses everything the engine
refuses.

That is the point of J. The wrapper's job is to prove the target and ask for a
confirmation; it must not become a way to skip a planner conflict, an asset
digest that has drifted, a snapshot that has been recollected or a count that
has moved. Each of those is asserted here with a VALID grant in hand, because
"the guard still fires when the operator is fully authorised" is the only
version of that claim worth having.
"""

import pytest
from sqlalchemy.orm import Session

from app.services import canonical_import_apply as A
from app.services import print_import_planner as P
from tests.test_canonical_import_apply_postgres import (  # noqa: F401 - fixtures
    DIGESTS,
    HEAD,
    SNAPSHOT_ID,
    _alembic,
    _entries_by_id,
    _fingerprint,
    _new_database,
    _plan,
    _seed_existing_print,
)

CONFIRM = "IMPORT_FROZEN_BANDAI_TO_CANONICAL_STAGING"
STAGING_CHECKS = (
    ("session is read-only", True),
    ("fingerprint A - required tables", True),
    ("fingerprint B - named indexes/constraints", True),
    ("fingerprint C - print-lineage columns", True),
    ("fingerprint D - alembic revision", True),
    ("fingerprint E - non-empty invariants", True),
)


@pytest.fixture
def db():
    """A throwaway database at the repo head. Never canonical staging."""
    database = _new_database("opcg_test_staging_gate")
    _alembic(database.url, "upgrade", HEAD)
    _seed_existing_print(database)
    try:
        yield database
    finally:
        database.close()


def _attestation(revision: str) -> A.StagingTargetAttestation:
    """Shaped exactly as canonical_staging_target builds it, for this database.

    The revision is read from the disposable database, so the grant is bound to
    the thing actually in front of the engine - which is what makes this a test
    of the gate rather than of a constant.
    """
    return A.StagingTargetAttestation(
        railway_environment="staging",
        railway_service="Postgres",
        database="railway",
        db_revision=revision,
        checks=STAGING_CHECKS,
    )


def _grant(db) -> A.CanonicalStagingWriteGrant:
    with Session(db.engine) as session:
        revision = A.db_revision(session)
    return A.grant_canonical_staging_write(
        confirmation=CONFIRM, attestation=_attestation(revision)
    )


def _run(db, *, apply=True, pinning=None, plan=None, grant=None, environment="staging"):
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
            staging_grant=grant,
        )
        return applier.run(apply=apply)


# --- I. the confirmed staging path reaches the existing apply engine -------


def test_i_a_confirmed_grant_lets_the_engine_write(db):
    report = _run(db, grant=_grant(db))

    assert report.applied is True
    assert report.environment == "staging"
    assert report.card_prints_created > 0
    assert report.canonical_cards_created > 0


def test_i_the_same_run_without_a_grant_is_refused_and_writes_nothing(db):
    """The grant is the ONLY difference between this and the test above."""
    before = _fingerprint(db)

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _run(db, grant=None)

    assert excinfo.value.report.rollback_reason == "refused_environment"
    assert excinfo.value.report.applied is False
    assert _fingerprint(db) == before


def test_i_a_grant_bound_to_a_different_revision_writes_nothing(db):
    """A real grant pointed at the wrong database is still refused."""
    before = _fingerprint(db)
    grant = A.grant_canonical_staging_write(
        confirmation=CONFIRM, attestation=_attestation("not_this_databases_revision")
    )

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _run(db, grant=grant)

    assert excinfo.value.report.rollback_reason == "staging_target_revision_mismatch"
    assert _fingerprint(db) == before


def test_i_the_untouched_tables_invariant_still_holds_on_the_staging_path(db):
    report = _run(db, grant=_grant(db))

    for table in A.UNTOUCHED_TABLES:
        assert report.pre_counts[table] == report.post_counts[table]


def test_i_a_second_confirmed_run_is_idempotent(db):
    first = _run(db, grant=_grant(db))
    after_first = _fingerprint(db)

    second = _run(db, grant=_grant(db))

    assert first.applied and second.applied
    assert second.card_prints_created == 0
    assert second.canonical_cards_created == 0
    assert _fingerprint(db) == after_first


# --- H (on a real server). the dry run stays read-only --------------------


def test_h_a_confirmed_dry_run_writes_nothing(db):
    before = _fingerprint(db)

    report = _run(db, apply=False, grant=_grant(db))

    assert report.applied is False
    assert report.pre_counts == report.post_counts
    assert _fingerprint(db) == before


# --- J. the engine's protections cannot be bypassed by the wrapper --------


def test_j_a_planner_conflict_still_aborts_with_a_valid_grant(db):
    before = _fingerprint(db)
    with Session(db.engine) as session:
        plan = _plan(session)
    conflicted = P.ImportPlan(
        prints=[
            *plan.prints,
            _a_conflict(plan),
        ]
    )

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _run(db, plan=conflicted, grant=_grant(db))

    assert excinfo.value.report.rollback_reason == A.ABORT_PLANNER_CONFLICT
    assert _fingerprint(db) == before


def test_j_a_recollected_snapshot_still_aborts_with_a_valid_grant(db):
    before = _fingerprint(db)
    with Session(db.engine) as session:
        pinning = A.ApplyPinning(
            snapshot_identity=SNAPSHOT_ID,
            expected_db_revision=A.db_revision(session),
            expected_snapshot_identity="d" * 64,
        )

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _run(db, pinning=pinning, grant=_grant(db))

    assert excinfo.value.report.rollback_reason == "snapshot_identity_mismatch"
    assert _fingerprint(db) == before


def test_j_stale_pre_apply_counts_still_abort_with_a_valid_grant(db):
    before = _fingerprint(db)
    with Session(db.engine) as session:
        pinning = A.ApplyPinning(
            snapshot_identity=SNAPSHOT_ID,
            expected_db_revision=A.db_revision(session),
            expected_pre_counts={"card_prints": 99999},
        )

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _run(db, pinning=pinning, grant=_grant(db))

    assert excinfo.value.report.rollback_reason == "stale_pre_apply_counts"
    assert _fingerprint(db) == before


def test_j_a_pinned_revision_mismatch_still_aborts_with_a_valid_grant(db):
    before = _fingerprint(db)
    pinning = A.ApplyPinning(
        snapshot_identity=SNAPSHOT_ID, expected_db_revision="0000deadbeef"
    )

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _run(db, pinning=pinning, grant=_grant(db))

    assert excinfo.value.report.rollback_reason in (
        "db_revision_mismatch",
        "staging_target_revision_mismatch",
    )
    assert _fingerprint(db) == before


def test_j_an_existing_asset_digest_mismatch_still_aborts_with_a_valid_grant(db):
    """Drift on a print Atlas already holds. Seeded to disagree, then run."""
    from sqlalchemy import text

    before_change = _fingerprint(db)
    with db.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE card_prints SET artwork_key = :d WHERE artwork_key IS NOT NULL"
            ),
            {"d": "f" * 64},
        )
    after_change = _fingerprint(db)
    assert after_change != before_change

    with pytest.raises(A.ApplyRunFailed) as excinfo:
        _run(db, grant=_grant(db))

    assert excinfo.value.report.rollback_reason == A.ABORT_EXISTING_ASSET_DIGEST
    assert _fingerprint(db) == after_change


def _a_conflict(plan: P.ImportPlan) -> P.PlannedPrint:
    """A copy of a real planned print, marked as the planner marks a conflict."""
    import dataclasses

    return dataclasses.replace(
        plan.prints[0],
        outcome=P.OUTCOME_CONFLICT,
        verification_status=P.NEEDS_REVIEW,
        flags=(P.FLAG_CANONICAL_CARD_CONFLICT,),
        reasons=("the catalogue disagrees with the canonical row on name_jp",),
    )
