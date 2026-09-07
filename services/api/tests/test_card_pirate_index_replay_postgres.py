"""Replay against real PostgreSQL, where the carry foreign key actually fires.

The SQLite suite does not enforce foreign keys (conftest sets no
PRAGMA foreign_keys=ON), so everything the composite carry key guarantees -
same scope, identical level, target exists - is unproven there. A replay
writer that produced a carry the key would reject would pass the whole SQLite
suite and fail on the first real boundary in production.

This file closes that gap: it runs the migration on a throwaway database and
writes a real carried segment through `replay_scope`, so the writer is proved
against the constraint it has to satisfy.

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

from app.models.canonical_card import CanonicalCard
from app.models.card_print import CardPrint
from app.models.card_pirate_index_point import CardPirateIndexPoint
from app.models.market_index_snapshot import MarketIndexSnapshot
from app.services.card_pirate_index import BASE_VALUE
from app.services.card_pirate_index_replay import replay_scope, verify_scope

REPO_ROOT = Path(__file__).resolve().parents[1]

HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
ADMIN_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/postgres"

D3, D4, D5 = (date(2026, 9, d) for d in (3, 4, 5))
STAMP = datetime(2026, 9, 7, 20, tzinfo=timezone.utc)
PROVENANCE = {
    "source_values": [
        {"source": "yuyutei", "reference_type": "sell",
         "contributes_to_index": True, "value_jpy": 100}
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
    name = "atlas_cpi_replay_test"
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


def _seed(session, day_versions):
    """day_versions maps date -> (index_version, source_semantics_version)."""
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
    for point_date, (iv, ssv) in sorted(day_versions.items()):
        for print_id in range(50):
            session.add(
                MarketIndexSnapshot(
                    card_print_id=print_id, calculated_at=STAMP,
                    snapshot_date=point_date, index_value_jpy=100,
                    calculation_method="median", source_count=1,
                    coverage_status="full", confidence="high",
                    index_version=iv, source_semantics_version=ssv,
                    provenance=PROVENANCE,
                )
            )
    session.commit()


def test_replay_writes_a_carried_segment_the_foreign_key_accepts(pg_session):
    """The carry FK proves target-exists + same-scope + identical-level in one
    constraint. If the writer got any of the three wrong, this commit fails."""
    _seed(pg_session, {D3: (3, 2), D4: (3, 2), D5: (4, 2)})
    result, _ = replay_scope(pg_session, calculated_at=STAMP)
    pg_session.commit()

    assert result.inserted == 3
    rows = pg_session.scalars(
        select(CardPirateIndexPoint).order_by(CardPirateIndexPoint.point_date)
    ).all()
    base, step, carried = rows
    assert base.index_value == BASE_VALUE
    assert carried.is_base is True
    assert carried.carried_from_point_id == step.id
    assert carried.index_value == step.index_value
    assert carried.chain_link_log_return is None
    assert carried.prior_point_date is None


def test_replay_is_idempotent_on_postgres(pg_session):
    _seed(pg_session, {D3: (3, 2), D4: (3, 2), D5: (4, 2)})
    replay_scope(pg_session, calculated_at=STAMP)
    pg_session.commit()
    before = [
        (r.id, r.point_date, r.index_value, r.carried_from_point_id)
        for r in pg_session.scalars(
            select(CardPirateIndexPoint).order_by(CardPirateIndexPoint.point_date)
        )
    ]

    second, _ = replay_scope(pg_session, calculated_at=STAMP)
    pg_session.commit()
    after = [
        (r.id, r.point_date, r.index_value, r.carried_from_point_id)
        for r in pg_session.scalars(
            select(CardPirateIndexPoint).order_by(CardPirateIndexPoint.point_date)
        )
    ]
    assert second.inserted == 0
    assert before == after


def test_verify_passes_against_a_real_replay(pg_session):
    _seed(pg_session, {D3: (3, 2), D4: (3, 2), D5: (4, 2)})
    replay_scope(pg_session, calculated_at=STAMP)
    pg_session.commit()
    result = verify_scope(pg_session)
    assert result.ok, [str(d) for d in result.discrepancies]


def test_numeric_round_trips_at_the_column_precision(pg_session):
    """A level written and read back through Numeric(12,4) must be the same
    Decimal the estimator produced - otherwise verification would report a
    discrepancy on every row."""
    _seed(pg_session, {D3: (3, 2), D4: (3, 2)})
    _, series = replay_scope(pg_session, calculated_at=STAMP)
    pg_session.commit()
    stored = pg_session.scalars(
        select(CardPirateIndexPoint).order_by(CardPirateIndexPoint.point_date)
    ).all()
    for row, draft in zip(stored, series.points):
        assert row.index_value == draft.index_value
        assert isinstance(row.index_value, Decimal)
        if draft.chain_link_log_return is not None:
            assert row.chain_link_log_return == draft.chain_link_log_return
