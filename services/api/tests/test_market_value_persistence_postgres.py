"""Market Value migration/writer proofs on disposable PostgreSQL only."""

import os
import subprocess
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.market_value_point import MarketValuePoint
from app.services.market_value_persistence import (
    MarketValuePointConflictError,
    persist_market_value_points,
    verify_market_value_points,
)
from app.services.market_value_replay import build_market_value_point_drafts
from tests.test_market_value_persistence import D1, D2, D3, replay_fixture


API_ROOT = Path(__file__).resolve().parents[1]
PARENT = "c4e9a2b7816d"
REVISION = "d5f7a9c2e4b6"
HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
PREFIX = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/"
ADMIN_URL = PREFIX + "postgres"
RELEASE_ID = 700001


def _alembic(url: str, action: str, revision: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", action, revision],
        cwd=API_ROOT,
        env=dict(os.environ, DATABASE_URL=url),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _create_database(name: str):
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError:
        admin.dispose()
        pytest.skip(f"Disposable PostgreSQL unavailable at {HOST}:{PORT}")
    return admin, create_engine(PREFIX + name)


def _drop_database(admin, engine, name: str) -> None:
    engine.dispose()
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(scope="module")
def pg_engine():
    name = "atlas_market_value_" + uuid.uuid4().hex[:10]
    admin, engine = _create_database(name)
    try:
        _alembic(PREFIX + name, "upgrade", "head")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO release_products (
                        id, source_catalogue, official_code, display_name,
                        first_seen_name, source_series_id, source_url,
                        verification_status
                    ) VALUES (
                        :id, 'bandai_jp', 'OP-TEST', 'Test release',
                        'Test release', 'test-release',
                        'https://example.test/release', 'verified'
                    )
                    """
                ),
                {"id": RELEASE_ID},
            )
        yield engine
    finally:
        _drop_database(admin, engine, name)


@pytest.fixture
def pg_session(pg_engine):
    with pg_engine.begin() as connection:
        connection.execute(text("TRUNCATE market_value_points RESTART IDENTITY"))
    with Session(pg_engine) as session:
        yield session
        session.rollback()


def test_market_value_migration_upgrade_downgrade_upgrade_cycle():
    name = "atlas_market_value_cycle_" + uuid.uuid4().hex[:10]
    admin, engine = _create_database(name)
    url = PREFIX + name
    try:
        _alembic(url, "upgrade", PARENT)
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT to_regclass('public.market_value_points')")
            ) is None

        _alembic(url, "upgrade", REVISION)
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT to_regclass('public.market_value_points')")
            ) == "market_value_points"
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION

        _alembic(url, "downgrade", PARENT)
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT to_regclass('public.market_value_points')")
            ) is None
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == PARENT

        _alembic(url, "upgrade", REVISION)
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT to_regclass('public.market_value_points')")
            ) == "market_value_points"
            assert connection.scalar(text("SELECT count(*) FROM market_value_points")) == 0
    finally:
        _drop_database(admin, engine, name)


def _base_values(**overrides):
    values = {
        "scope_kind": "overall",
        "release_product_id": None,
        "methodology_version": 1,
        "point_date": D1,
        "tracked_value_jpy": 100,
        "priced_print_count": 1,
        "total_physical_print_count": 1,
        "prior_point_date": None,
        "step_days": None,
        "prior_tracked_value_jpy": None,
        "prior_priced_print_count": None,
        "prior_total_physical_print_count": None,
        "comparable_print_count": None,
        "prior_comparable_value_jpy": None,
        "current_comparable_value_jpy": None,
        "step_ratio": None,
        "segment_number": 0,
        "performance_factor": Decimal("1"),
        "step_publication_eligible": None,
        "publication_reasons": None,
        "membership_revision": "current-corrected-card-print-release-v1:test",
        "prior_version_pairs": None,
        "current_version_pairs": "3:2",
    }
    values.update(overrides)
    return values


def test_postgres_constraints_natural_keys_fk_and_exact_numeric(pg_session, pg_engine):
    pg_session.add(MarketValuePoint(**_base_values()))
    exact = Decimal("1.1234567890123456789012345678901234567890123456789")
    pg_session.add(
        MarketValuePoint(
            **_base_values(
                point_date=D2,
                tracked_value_jpy=101,
                prior_point_date=D1,
                step_days=1,
                prior_tracked_value_jpy=100,
                prior_priced_print_count=1,
                prior_total_physical_print_count=1,
                comparable_print_count=1,
                prior_comparable_value_jpy=100,
                current_comparable_value_jpy=101,
                step_ratio=exact,
                performance_factor=exact,
                step_publication_eligible=True,
                publication_reasons="publishable",
                prior_version_pairs="3:2",
            )
        )
    )
    pg_session.commit()
    stored = pg_session.scalar(
        select(MarketValuePoint.step_ratio).where(MarketValuePoint.point_date == D2)
    )
    assert stored == exact

    with pytest.raises(IntegrityError), pg_engine.begin() as connection:
        connection.execute(
            MarketValuePoint.__table__.insert().values(**_base_values())
        )

    with pytest.raises(IntegrityError), pg_engine.begin() as connection:
        connection.execute(
            MarketValuePoint.__table__.insert().values(
                **_base_values(
                    point_date=D3,
                    release_product_id=RELEASE_ID,
                )
            )
        )

    with pytest.raises(IntegrityError), pg_engine.begin() as connection:
        connection.execute(
            MarketValuePoint.__table__.insert().values(
                **_base_values(
                    scope_kind="release",
                    release_product_id=999999999,
                )
            )
        )

    with pytest.raises(IntegrityError), pg_engine.begin() as connection:
        connection.execute(
            MarketValuePoint.__table__.insert().values(
                **_base_values(
                    point_date=D3,
                    priced_print_count=2,
                    total_physical_print_count=1,
                )
            )
        )

    # A truthful unavailable release step: no ratio and an explicit A2 reason.
    with pg_engine.begin() as connection:
        connection.execute(
            MarketValuePoint.__table__.insert().values(
                **_base_values(
                    scope_kind="release",
                    release_product_id=RELEASE_ID,
                )
            )
        )

        connection.execute(
            MarketValuePoint.__table__.insert().values(
                **_base_values(
                    scope_kind="release",
                    release_product_id=RELEASE_ID,
                    point_date=D2,
                    prior_point_date=D1,
                    step_days=1,
                    prior_tracked_value_jpy=100,
                    prior_priced_print_count=1,
                    prior_total_physical_print_count=1,
                    comparable_print_count=0,
                    prior_comparable_value_jpy=0,
                    current_comparable_value_jpy=0,
                    step_ratio=None,
                    segment_number=1,
                    performance_factor=Decimal("1"),
                    step_publication_eligible=False,
                    publication_reasons="non_positive_comparable_value",
                    prior_version_pairs="3:2",
                )
            )
        )

    with pytest.raises(IntegrityError), pg_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM release_products WHERE id = :id"),
            {"id": RELEASE_ID},
        )


def test_replay_writer_roundtrip_idempotency_and_mismatch_detection(pg_session):
    expected = build_market_value_point_drafts(
        replay_fixture(
            release_product_id=RELEASE_ID,
            contributor_churn_on_last=True,
        )
    )

    first = persist_market_value_points(pg_session, tuple(reversed(expected)))
    pg_session.commit()
    assert (first.inserted, first.existing, first.verified) == (6, 0, 6)
    insertion_order = tuple(
        (
            row.scope_kind,
            row.release_product_id,
            row.methodology_version,
            row.point_date,
        )
        for row in pg_session.scalars(
            select(MarketValuePoint).order_by(MarketValuePoint.id)
        )
    )
    assert insertion_order == tuple(row.natural_key for row in expected)
    verified = verify_market_value_points(pg_session, expected)
    assert verified.ok
    assert (verified.expected, verified.persisted, verified.verified) == (6, 6, 6)

    second = persist_market_value_points(pg_session, expected)
    pg_session.commit()
    assert (second.inserted, second.existing, second.verified) == (0, 6, 6)

    unavailable = [
        row
        for row in expected
        if row.point_date == D3 and row.scope_kind == "release"
    ][0]
    assert unavailable.step_publication_eligible is False
    assert unavailable.step_ratio is None
    assert unavailable.publication_reasons != "publishable"

    pg_session.execute(
        text(
            "UPDATE market_value_points "
            "SET tracked_value_jpy = tracked_value_jpy + 1 "
            "WHERE scope_kind = 'overall' AND point_date = :point_date"
        ),
        {"point_date": D2},
    )
    pg_session.commit()
    mismatch = verify_market_value_points(pg_session, expected)
    assert not mismatch.ok
    assert len(mismatch.mismatches) == 1
    assert mismatch.mismatches[0].fields == ("tracked_value_jpy",)

    with pytest.raises(MarketValuePointConflictError) as exc_info:
        persist_market_value_points(pg_session, expected)
    assert exc_info.value.mismatched_fields == ("tracked_value_jpy",)
