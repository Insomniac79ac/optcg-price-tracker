"""Real PostgreSQL locking and rollback coverage for exact proposal approval."""

from __future__ import annotations

import os
import threading

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.db import Base
from app.models import (
    PriceObservation,
    RawSnapshot,
    SourceCardMapping,
    SourceCollectionAttempt,
    SourceMappingProposalGroup,
)
from app.services.source_mapping_proposal_decision import approve_exact_proposal
from tests.test_source_mapping_proposal_decision import ACTOR, _request, _seed_yuyu


TEST_POSTGRES_URL = os.environ.get(
    "TEST_POSTGRES_URL", "postgresql+psycopg://opcg:opcg@localhost:5544/opcg_test"
)


@pytest.fixture()
def postgres_db():
    engine = create_engine(TEST_POSTGRES_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
    except OperationalError:
        engine.dispose()
        pytest.skip(f"No disposable PostgreSQL server reachable at {TEST_POSTGRES_URL}")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionFactory()
    try:
        yield engine, SessionFactory, session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_postgres_concurrent_identical_approvals_serialize_to_one_mapping(postgres_db):
    _, SessionFactory, seed_session = postgres_db
    _, _, _, _, _, group = _seed_yuyu(seed_session)
    group_id = group.id
    request = _request(group)
    barrier = threading.Barrier(2)
    results = []
    errors = []

    def approve():
        session = SessionFactory()
        try:
            barrier.wait(timeout=5)
            result = approve_exact_proposal(session, group_id, request, ACTOR)
            session.commit()
            results.append(result)
        except Exception as exc:  # recorded and asserted below
            session.rollback()
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=approve), threading.Thread(target=approve)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not errors
    assert len(results) == 2
    assert sorted(result.idempotent_replay for result in results) == [False, True]
    seed_session.expire_all()
    decided = seed_session.get(SourceMappingProposalGroup, group_id)
    assert decided.review_status == "approved"
    assert decided.selected_alternative_id is not None
    assert decided.resulting_source_card_mapping_id is not None
    assert seed_session.query(SourceCardMapping).count() == 1
    assert seed_session.query(PriceObservation).count() == 0
    assert seed_session.query(SourceCollectionAttempt).count() == 0
    assert seed_session.query(RawSnapshot).count() == 0


def test_postgres_service_and_source_writer_never_commit(postgres_db):
    _, SessionFactory, session = postgres_db
    _, _, _, _, _, group = _seed_yuyu(session)
    approve_exact_proposal(session, group.id, _request(group), ACTOR)

    observer = SessionFactory()
    try:
        assert observer.query(SourceCardMapping).count() == 0
        pending = observer.get(SourceMappingProposalGroup, group.id)
        assert pending.review_status == "pending"
    finally:
        observer.close()
    session.rollback()
    assert session.query(SourceCardMapping).count() == 0


def test_postgres_failure_after_mapping_flush_rolls_back_all_state(postgres_db, monkeypatch):
    _, _, session = postgres_db
    _, _, _, _, _, group = _seed_yuyu(session)
    import app.services.source_mapping_proposal_decision as decision_module

    real_writer = decision_module.approve_candidate_from_exact_proposal

    def fail_after_flush(*args, **kwargs):
        real_writer(*args, **kwargs)
        raise RuntimeError("forced PostgreSQL rollback")

    monkeypatch.setattr(decision_module, "approve_candidate_from_exact_proposal", fail_after_flush)
    with pytest.raises(RuntimeError, match="forced PostgreSQL rollback"):
        approve_exact_proposal(session, group.id, _request(group), ACTOR)
    session.rollback()
    session.expire_all()
    assert session.query(SourceCardMapping).count() == 0
    pending = session.get(SourceMappingProposalGroup, group.id)
    assert pending.review_status == "pending"
    assert pending.selected_alternative_id is None
    assert pending.resulting_source_card_mapping_id is None
