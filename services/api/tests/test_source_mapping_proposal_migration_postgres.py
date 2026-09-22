"""Real PostgreSQL upgrade/downgrade coverage for revision f4c8a2d91b60."""

from __future__ import annotations

from dataclasses import replace
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import (
    CanonicalCard,
    CardPrint,
    PriceObservation,
    ReleaseProduct,
    Source,
    SourceCardMapping,
    SourceMappingProposalAlternative,
    SourceMappingProposalGroup,
)
from app.services.source_mapping_proposals import (
    AlternativePlan,
    ProposalPlan,
    persist_proposals,
)


ROOT = Path(__file__).resolve().parents[1]
HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
DATABASE = "opcg_test_source_mapping_proposals"
ADMIN_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/postgres"
DATABASE_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/{DATABASE}"
PREVIOUS = "e3a7c5d9b102"
REVISION = "f4c8a2d91b60"
CURRENT_HEAD = "b8e04219d6c3"


def _alembic(*args):
    env = {**os.environ, "DATABASE_URL": DATABASE_URL}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="module")
def migration_engine():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{DATABASE}"'))
            conn.execute(text(f'CREATE DATABASE "{DATABASE}"'))
    except OperationalError:
        admin.dispose()
        pytest.skip(f"No disposable PostgreSQL at {HOST}:{PORT}")
    engine = create_engine(DATABASE_URL)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)'))
        admin.dispose()


def test_upgrade_and_downgrade_source_scoped_alias_and_proposal_schema(migration_engine):
    _alembic("upgrade", PREVIOUS)
    _alembic("upgrade", REVISION)
    inspector = inspect(migration_engine)
    assert "source_id" in {c["name"] for c in inspector.get_columns("release_product_aliases")}
    assert "source_mapping_proposal_groups" in inspector.get_table_names()
    assert "source_mapping_proposal_alternatives" in inspector.get_table_names()
    indexes = {row["name"] for row in inspector.get_indexes("release_product_aliases")}
    assert "uq_release_product_aliases_source_identity" in indexes

    with migration_engine.connect() as conn:
        assert conn.scalar(text(
            "SELECT count(*) FROM release_product_aliases a JOIN sources s "
            "ON s.id = a.source_id WHERE a.alias_kind = 'source_rendering' "
            "AND s.name = 'snkrdunk'"
        )) == conn.scalar(text(
            "SELECT count(*) FROM release_product_aliases WHERE alias_kind = 'source_rendering'"
        ))
        assert conn.scalar(text("SELECT count(*) FROM source_mapping_proposal_groups")) == 0
        assert conn.scalar(text("SELECT count(*) FROM source_card_mappings")) == 0
        assert conn.scalar(text("SELECT count(*) FROM price_observations")) == 0

    _alembic("downgrade", PREVIOUS)
    inspector = inspect(migration_engine)
    assert "source_id" not in {c["name"] for c in inspector.get_columns("release_product_aliases")}
    assert "source_mapping_proposal_groups" not in inspector.get_table_names()
    # The remainder of this module exercises the current ORM. Preserve the
    # f4 round trip above, then advance through the additive decision schema.
    _alembic("upgrade", CURRENT_HEAD)


def _plan(source_id, identity, candidate_id, digest, alternatives):
    return ProposalPlan(
        source_id=source_id,
        source_name="snkrdunk",
        canonical_source_listing_identity=identity,
        source_url=f"https://snkrdunk.example.test/{candidate_id}",
        source_candidate_type="snkrdunk_candidate",
        source_candidate_id=candidate_id,
        canonical_card_id=None,
        card_code=None,
        release_product_id=None,
        resolution_status=(
            "release_unresolved" if not alternatives
            else "ambiguous" if len(alternatives) > 1
            else "exact"
        ),
        resolver_version="source-mapping-proposals/1.0",
        evidence_digest=digest,
        evidence_summary={"candidate_id": candidate_id, "version": digest[0]},
        resolution_reasons=("postgres_persistence_fixture",),
        alternatives=tuple(alternatives),
    )


def test_postgres_persistence_batching_idempotency_and_history(migration_engine):
    with Session(migration_engine, autoflush=False) as session:
        source = session.scalar(select(Source).where(Source.name == "snkrdunk"))
        assert source is not None
        release = ReleaseProduct(
            source_catalogue="bandai_jp",
            official_code="PG-TEST",
            display_name="PostgreSQL test release",
            first_seen_name="PostgreSQL test release",
            source_series_id="pg-test",
            source_url="https://bandai.example.test/pg-test",
            verification_status="verified",
        )
        family = CanonicalCard(
            card_code="PGTEST-001", name_en="PostgreSQL test", card_type="Character"
        )
        session.add_all([release, family])
        session.flush()
        first_print = CardPrint(
            canonical_card_id=family.id,
            language="jp",
            release_product_code=release.official_code,
            release_product_id=release.id,
            artwork_key="sha256:pg-test:base",
            official_asset_variant="base",
            verification_status="verified",
            is_active=True,
        )
        second_print = CardPrint(
            canonical_card_id=family.id,
            language="jp",
            release_product_code=release.official_code,
            release_product_id=release.id,
            artwork_key="sha256:pg-test:p1",
            official_asset_variant="p1",
            verification_status="verified",
            is_active=True,
        )
        session.add_all([first_print, second_print])
        session.commit()

        plans = [
            _plan(source.id, "pg-listing-1", 1, "1" * 64, [
                AlternativePlan(first_print.id, True),
            ]),
            _plan(source.id, "pg-listing-2", 2, "2" * 64, [
                AlternativePlan(first_print.id, True),
            ]),
            _plan(source.id, "pg-listing-3", 3, "3" * 64, [
                AlternativePlan(first_print.id, False),
                AlternativePlan(second_print.id, False),
            ]),
        ]
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(migration_engine, "before_cursor_execute", capture)
        try:
            with patch.object(session, "flush", wraps=session.flush) as flush:
                first = persist_proposals(session, plans)
        finally:
            event.remove(migration_engine, "before_cursor_execute", capture)
        session.commit()

        lookup_selects = [
            statement for statement in statements
            if statement.lstrip().upper().startswith("SELECT")
            and "source_mapping_proposal_groups" in statement
        ]
        assert first.created_groups == 3
        assert first.created_alternatives == 4
        assert len(lookup_selects) <= 2
        assert flush.call_count == 1
        assert session.query(SourceMappingProposalGroup).filter_by(
            review_status="pending", superseded_at=None
        ).count() == 3
        assert session.query(SourceMappingProposalAlternative).filter_by(
            card_print_id=first_print.id
        ).count() == 3

        second = persist_proposals(session, plans)
        session.commit()
        assert second.created_groups == 0
        assert second.created_alternatives == 0
        assert second.superseded_groups == 0
        assert second.reused_groups == 3

        changed = replace(
            plans[0],
            evidence_digest="a" * 64,
            evidence_summary={"candidate_id": 1, "version": "changed"},
        )
        changed_result = persist_proposals(session, [changed])
        session.commit()
        assert changed_result.created_groups == 1
        assert changed_result.superseded_groups == 1

        restored = persist_proposals(session, [plans[0]])
        session.commit()
        assert restored.created_groups == 0
        assert restored.created_alternatives == 0
        assert restored.reused_groups == 1
        assert restored.superseded_groups == 1
        assert session.query(SourceMappingProposalGroup).count() == 4
        assert session.query(SourceMappingProposalGroup).filter_by(
            superseded_at=None
        ).count() == 3
        assert session.query(SourceCardMapping).count() == 0
        assert session.query(PriceObservation).count() == 0


@pytest.mark.parametrize("plan_count", [1, 25, 100])
def test_postgres_proposal_lookup_query_growth_is_bounded(migration_engine, plan_count):
    with Session(migration_engine, autoflush=False) as session:
        source = session.scalar(select(Source).where(Source.name == "snkrdunk"))
        assert source is not None
        plans = [
            _plan(
                source.id,
                f"pg-performance-{plan_count}-{index}",
                plan_count * 1000 + index,
                f"{plan_count * 1000 + index:064x}",
                [],
            )
            for index in range(1, plan_count + 1)
        ]
        statements = []

        def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(migration_engine, "before_cursor_execute", capture)
        try:
            started = time.perf_counter()
            with patch.object(session, "flush", wraps=session.flush) as flush:
                result = persist_proposals(session, plans)
            elapsed = time.perf_counter() - started
        finally:
            event.remove(migration_engine, "before_cursor_execute", capture)
        session.rollback()

        selects = [
            statement for statement in statements
            if statement.lstrip().upper().startswith("SELECT")
            and "source_mapping_proposal_groups" in statement
        ]
        inserts = [
            statement for statement in statements
            if statement.lstrip().upper().startswith("INSERT")
            and "source_mapping_proposal_groups" in statement
        ]
        print(
            f"plans={plan_count} selects={len(selects)} inserts={len(inserts)} "
            f"flushes={flush.call_count} elapsed={elapsed:.6f}s"
        )
        assert result.created_groups == plan_count
        assert len(selects) <= 2
        assert flush.call_count == 1
