"""PostgreSQL clean-restore coverage for the selective exact-lineage backup.

The normal suite uses SQLite. This test intentionally exercises the real
composite lineage FK and PostgreSQL ordering constraints, and follows the
repository convention of skipping when TEST_POSTGRES_URL is unavailable.
"""

from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  (registers every model on Base.metadata)
from app.db import Base
from app.models import (
    CardPrint,
    MarketIndexSnapshot,
    PriceObservation,
    RawSnapshot,
    SnkrdunkCandidate,
    SourceCardMapping,
    SourceCollectionAttempt,
)
from app.services.backup import export_backup, restore_backup, validate_backup
from tests._backup_exact_lineage_helpers import seed_exact_lineage

TEST_POSTGRES_URL = os.environ.get(
    "TEST_POSTGRES_URL", "postgresql+psycopg://opcg:opcg@localhost:5544/opcg_test"
)


@pytest.fixture()
def postgres_engine():
    engine = create_engine(TEST_POSTGRES_URL)
    try:
        with engine.connect():
            pass
    except OperationalError:
        engine.dispose()
        pytest.skip(f"No PostgreSQL server reachable at {TEST_POSTGRES_URL}")

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize("include_raw_snapshots", [True, False])
def test_postgres_clean_database_exact_lineage_round_trip(
    postgres_engine, include_raw_snapshots
):
    SessionFactory = sessionmaker(bind=postgres_engine, autoflush=False, autocommit=False)
    with SessionFactory() as source_session:
        ids = seed_exact_lineage(source_session)
        archive = export_backup(
            source_session,
            include_prices=True,
            include_raw_snapshots=include_raw_snapshots,
        )
    archive = json.loads(json.dumps(archive))
    validation = validate_backup(archive)
    assert validation.valid is True, validation.errors

    # A clean, already-migrated destination: schema exists, application rows do not.
    Base.metadata.drop_all(bind=postgres_engine)
    Base.metadata.create_all(bind=postgres_engine)

    with SessionFactory() as target_session:
        result = restore_backup(
            target_session,
            archive,
            dry_run=False,
            mode="merge",
            skip_lock=True,
        )
        assert result.valid is True, result.errors

        exact_mapping = target_session.get(SourceCardMapping, ids["exact_mapping_id"])
        legacy_mapping = target_session.get(SourceCardMapping, ids["legacy_mapping_id"])
        observation = target_session.get(PriceObservation, ids["observation_id"])
        attempt = target_session.get(SourceCollectionAttempt, ids["attempt_id"])

        assert target_session.get(CardPrint, ids["card_print_id"])
        assert exact_mapping.card_id is None
        assert exact_mapping.card_print_id == ids["card_print_id"]
        assert legacy_mapping.card_id == ids["legacy_card_id"]
        assert legacy_mapping.card_print_id is None
        assert observation.source_card_mapping_id == ids["exact_mapping_id"]
        assert observation.card_print_id == ids["card_print_id"]
        assert observation.source_id == ids["source_id"]
        assert observation.candidate_id == ids["candidate_id"]
        assert target_session.get(SnkrdunkCandidate, ids["candidate_id"])
        assert target_session.get(MarketIndexSnapshot, ids["market_snapshot_id"])

        if include_raw_snapshots:
            assert target_session.get(RawSnapshot, ids["raw_snapshot_id"])
            assert observation.raw_snapshot_id == ids["raw_snapshot_id"]
            assert attempt.raw_snapshot_id == ids["raw_snapshot_id"]
        else:
            assert target_session.get(RawSnapshot, ids["raw_snapshot_id"]) is None
            assert observation.raw_snapshot_id is None
            assert attempt.raw_snapshot_id is None
