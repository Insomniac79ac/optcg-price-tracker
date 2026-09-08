"""The writer against real PostgreSQL, where the guarantees are actually enforced.

SQLite proves none of this. It does not enforce foreign keys under the suite's
configuration, its CHECK handling differs, and - the reason this file exists -
a rolled-back transaction there is not evidence about what Postgres does with
a rolled-back transaction containing an FK-bearing INSERT.

Three things are proved here and nowhere else:

  * A CARRIED BASE WRITTEN BY THE DAILY JOB SATISFIES THE COMPOSITE CARRY KEY.
    The FK proves target-exists, same-scope and identical-level in one
    constraint. If the head-only write window resolved the carry against the
    wrong row, this commit fails.
  * A FAILED VERIFICATION LEAVES NOTHING BEHIND, on a real transaction, read
    back through a SEPARATE session so the assertion cannot be satisfied by
    the writer's own in-memory state.
  * THE STAGING-SHAPED HEAD SURVIVES A CATCH-UP BYTE FOR BYTE, including
    Numeric(12,4) and Numeric(18,12) round-trips and the surrogate ids, which
    are the thing a rebuild would silently move.

Never touches staging. Skips when no server answers.
"""

import os
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.card_pirate_index_writer import (
    WriterAbort,
    run_writer,
    verify_persisted,
)
from app.models.canonical_card import CanonicalCard
from app.models.card_pirate_index_point import CardPirateIndexPoint
from app.models.card_print import CardPrint
from app.models.market_index_snapshot import MarketIndexSnapshot
from app.services.card_pirate_index import BASE_VALUE, SCOPE_OVERALL
from app.services.card_pirate_index_replay import Discrepancy, VerifyResult

REPO_ROOT = Path(__file__).resolve().parents[1]

HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
ADMIN_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/postgres"

D3, D4, D5, D6, D7, D8 = (date(2026, 9, d) for d in (3, 4, 5, 6, 7, 8))
STAMP = datetime(2026, 9, 7, 20, tzinfo=timezone.utc)
PROVENANCE = {
    "source_values": [
        {
            "source": "yuyutei",
            "reference_type": "sell",
            "contributes_to_index": True,
            "value_jpy": 100,
        }
    ]
}


def _alembic(url: str, *args: str):
    env = dict(os.environ)
    env["DATABASE_URL"] = url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="module")
def pg_engine():
    name = "atlas_cpi_writer_test"
    url = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/{name}"
    try:
        admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError:
        pytest.skip(f"No PostgreSQL server reachable at {HOST}:{PORT}")

    _alembic(url, "upgrade", "head")
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def pg_session(pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE card_pirate_index_points, market_index_snapshots,"
                " card_prints, canonical_cards RESTART IDENTITY CASCADE"
            )
        )
    with Session(pg_engine) as session:
        yield session
        session.rollback()


def _seed_prints(session) -> None:
    if session.get(CardPrint, 0) is not None:
        return
    for print_id in range(50):
        canonical = CanonicalCard(
            card_code=f"OP01-{print_id:03d}", name_en="x", card_type="CHARACTER"
        )
        session.add(canonical)
        session.flush()
        session.add(
            CardPrint(id=print_id, canonical_card_id=canonical.id, language="jp")
        )
    session.flush()


def seed_archive(session, days, *, iv: int = 3, ssv: int = 2, value: int = 100):
    """`days` is an iterable of dates, all 50 prints, one version pair."""
    _seed_prints(session)
    for point_date in sorted(days):
        for print_id in range(50):
            session.add(
                MarketIndexSnapshot(
                    card_print_id=print_id, calculated_at=STAMP,
                    snapshot_date=point_date, index_value_jpy=value,
                    calculation_method="median", source_count=1,
                    coverage_status="full", confidence="high",
                    index_version=iv, source_semantics_version=ssv,
                    provenance=PROVENANCE,
                )
            )
    session.commit()


ROW_COLUMNS = (
    CardPirateIndexPoint.id,
    CardPirateIndexPoint.point_date,
    CardPirateIndexPoint.index_value,
    CardPirateIndexPoint.is_base,
    CardPirateIndexPoint.carried_from_point_id,
    CardPirateIndexPoint.prior_point_date,
    CardPirateIndexPoint.step_days,
    CardPirateIndexPoint.chain_link_log_return,
    CardPirateIndexPoint.constituent_count,
    CardPirateIndexPoint.eligible_print_count,
    CardPirateIndexPoint.calculated_at,
    CardPirateIndexPoint.created_at,
)


def rows_via(engine_or_session) -> list[tuple]:
    """Read through whatever is handed in. The rollback tests read through a
    SECOND session, because a rolled-back write is only convincingly absent
    when a different transaction agrees it is."""
    stmt = select(*ROW_COLUMNS).order_by(CardPirateIndexPoint.point_date)
    if isinstance(engine_or_session, Session):
        engine_or_session.expire_all()
        return [tuple(r) for r in engine_or_session.execute(stmt)]
    with Session(engine_or_session) as fresh:
        return [tuple(r) for r in fresh.execute(stmt)]


def seed_staging_shaped_head(session) -> list[tuple]:
    """2026-09-03 base + three same-version steps, committed - the shape
    staging holds today."""
    seed_archive(session, (D3, D4, D5, D6))
    result = run_writer(session, calculated_at=STAMP, skip_lock=True)
    assert result.inserted == 4
    return rows_via(session)


def test_one_new_day_is_committed_and_the_head_is_untouched(pg_session, pg_engine):
    before = seed_staging_shaped_head(pg_session)
    seed_archive(pg_session, (D7,))

    result = run_writer(pg_session, calculated_at=STAMP, skip_lock=True)

    assert result.inserted == 1
    committed = rows_via(pg_engine)
    assert len(committed) == 5
    assert committed[:4] == before
    assert committed[0][2] == BASE_VALUE
    assert verify_persisted(pg_session).ok


def test_a_catch_up_writes_ascending_and_verifies(pg_session, pg_engine):
    before = seed_staging_shaped_head(pg_session)
    seed_archive(pg_session, (D7, D8))

    result = run_writer(pg_session, calculated_at=STAMP, skip_lock=True)

    assert result.inserted == 2
    committed = rows_via(pg_engine)
    assert [r[1] for r in committed] == [D3, D4, D5, D6, D7, D8]
    assert [r[0] for r in committed] == sorted(r[0] for r in committed)
    assert committed[:4] == before
    assert verify_persisted(pg_session).ok


def test_a_carried_base_written_at_the_head_satisfies_the_carry_key(
    pg_session, pg_engine
):
    """The composite FK checks target-exists, same-scope and identical-level
    in one constraint, and it is IMMEDIATE. A daily run that opens a new
    version segment therefore has to resolve its carry against a row a
    previous run committed - if it resolved against the wrong row, or none,
    this commit fails."""
    seed_archive(pg_session, (D3, D4))
    run_writer(pg_session, calculated_at=STAMP, skip_lock=True)
    head = rows_via(pg_engine)[-1]

    seed_archive(pg_session, (D5,), iv=4)
    result = run_writer(pg_session, calculated_at=STAMP, skip_lock=True)

    assert result.inserted == 1
    carried = rows_via(pg_engine)[-1]
    assert carried[3] is True                 # is_base
    assert carried[4] == head[0]              # carried_from_point_id -> D4's id
    assert carried[2] == head[2]              # identical level
    assert carried[5] is None                 # no prior_point_date
    assert verify_persisted(pg_session).ok


def test_a_failed_verification_commits_nothing(pg_session, pg_engine, monkeypatch):
    before = seed_staging_shaped_head(pg_session)
    seed_archive(pg_session, (D7, D8))

    monkeypatch.setattr(
        "app.card_pirate_index_writer.verify_persisted",
        lambda db, seed=None: VerifyResult(
            scope_kind=SCOPE_OVERALL, scope_key="", stored_points=6,
            expected_points=6,
            discrepancies=[
                Discrepancy(
                    kind="field_mismatch", scope_kind=SCOPE_OVERALL,
                    scope_key="", point_date=D7, field="index_value",
                    stored=1, expected=2,
                )
            ],
        ),
    )

    with pytest.raises(WriterAbort):
        run_writer(pg_session, calculated_at=STAMP, skip_lock=True)

    # Read through a brand-new session: the rows are gone from the database,
    # not merely from the writer's session.
    assert rows_via(pg_engine) == before


def test_a_tampered_head_aborts_before_anything_is_written(pg_session, pg_engine):
    seed_staging_shaped_head(pg_session)
    pg_session.execute(
        text(
            "UPDATE card_pirate_index_points SET index_value = 1234.5678 "
            "WHERE point_date = :d"
        ),
        {"d": D4},
    )
    pg_session.commit()
    before = rows_via(pg_engine)
    seed_archive(pg_session, (D7,))

    with pytest.raises(WriterAbort) as exc:
        run_writer(pg_session, calculated_at=STAMP, skip_lock=True)

    assert "does not reconcile" in str(exc.value)
    assert rows_via(pg_engine) == before


def test_a_rerun_is_byte_identical_on_postgres(pg_session, pg_engine):
    seed_staging_shaped_head(pg_session)
    seed_archive(pg_session, (D7,))
    run_writer(pg_session, calculated_at=STAMP, skip_lock=True)
    after_first = rows_via(pg_engine)

    second = run_writer(
        pg_session,
        calculated_at=datetime(2026, 9, 8, 20, tzinfo=timezone.utc),
        skip_lock=True,
    )

    assert second.inserted == 0
    # A different calculated_at was offered and correctly ignored: nothing was
    # rewritten, so the stamp of the run that first published the day stands.
    assert rows_via(pg_engine) == after_first


def test_numeric_precision_survives_the_write_and_the_reverification(pg_session):
    seed_archive(pg_session, (D3, D4))
    run_writer(pg_session, calculated_at=STAMP, skip_lock=True)
    seed_archive(pg_session, (D5,), value=110)

    result = run_writer(pg_session, calculated_at=STAMP, skip_lock=True)

    assert result.inserted == 1
    row = pg_session.scalars(
        select(CardPirateIndexPoint).order_by(CardPirateIndexPoint.point_date)
    ).all()[-1]
    assert isinstance(row.index_value, Decimal)
    assert isinstance(row.chain_link_log_return, Decimal)
    assert row.index_value > Decimal("1000.0000")
    assert verify_persisted(pg_session).ok


def test_dry_run_against_a_read_only_transaction_takes_no_lock(
    pg_session, pg_engine
):
    """The staging dry-run runs inside SET TRANSACTION READ ONLY. If the
    writer's read-only path acquired a job lock - or wrote anything at all -
    this raises instead of reporting a plan.

    Takes `pg_session` only for its TRUNCATE: the dry-run itself deliberately
    runs on a different, read-only session.
    """
    seed_staging_shaped_head(pg_session)
    seed_archive(pg_session, (D7,))

    with Session(pg_engine) as read_only:
        read_only.execute(text("SET TRANSACTION READ ONLY"))
        result = run_writer(read_only, dry_run=True)

    assert result.dry_run is True
    assert result.inserted == 0
    assert [p.point_date for p in result.plan.planned] == [D7]
    assert len(rows_via(pg_engine)) == 4
