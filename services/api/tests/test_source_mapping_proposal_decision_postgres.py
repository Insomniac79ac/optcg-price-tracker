"""Real PostgreSQL locking and rollback coverage for exact proposal approval."""

from __future__ import annotations

import os
import threading

import pytest
from sqlalchemy import create_engine, text
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
    YuyuteiCandidate,
)
from app.services.source_mapping_proposal_decision import approve_exact_proposal
from tests.test_source_mapping_proposal_decision import ACTOR, _request, _seed_yuyu, _persist_one
from app.services.exact_print_approval import ExactPrintApprovalError
from app.services.current_source_mapping import (
    assert_print_source_available,
    lookup_current_mapping,
)


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


def test_postgres_different_listings_for_same_print_serialize_to_one_active_source(postgres_db):
    _, SessionFactory, session = postgres_db
    _, _, _, _, candidate, first = _seed_yuyu(session)
    second_candidate = YuyuteiCandidate(
        discovery_run_id=candidate.discovery_run_id,
        set_slug=candidate.set_slug, product_id="7002",
        source_url="https://yuyu-tei.jp/sell/opc/card/op17/7002",
        detected_card_code=candidate.detected_card_code,
        match_status="family_matched",
    )
    session.add(second_candidate)
    session.commit()
    second = _persist_one(session, "yuyutei", second_candidate.id)
    requests = [(first.id, _request(first)), (second.id, _request(second))]
    barrier = threading.Barrier(2)
    results, errors = [], []

    def approve(group_id, request):
        with SessionFactory() as worker:
            try:
                barrier.wait(timeout=5)
                result = approve_exact_proposal(worker, group_id, request, ACTOR)
                worker.commit()
                results.append(result)
            except Exception as exc:
                worker.rollback()
                errors.append(exc)

    threads = [threading.Thread(target=approve, args=pair) for pair in requests]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert all(not thread.is_alive() for thread in threads)
    assert len(results) == len(errors) == 1
    assert isinstance(errors[0], ExactPrintApprovalError)
    assert errors[0].code == "print_source_already_mapped"
    session.expire_all()
    assert session.query(SourceCardMapping).count() == 1
    assert sorted(g.review_status for g in session.query(SourceMappingProposalGroup)) == ["approved", "pending"]
    assert session.query(PriceObservation).count() == 0
    assert session.query(RawSnapshot).count() == 0


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


@pytest.mark.parametrize("lock_path", ["print_source", "listing"])
def test_source_approval_lock_allows_independent_raw_retention(postgres_db, lock_path):
    """Collectors must retain raw while an exact approval owns its source mutex."""
    _, SessionFactory, approval = postgres_db
    source, _, _, physical, candidate, _ = _seed_yuyu(approval)
    if lock_path == "print_source":
        assert_print_source_available(
            approval, source=source, card_print_id=physical.id
        )
    else:
        lookup_current_mapping(
            approval, source=source, url=candidate.source_url, for_update=True
        )

    with SessionFactory() as collector:
        collector.execute(text("SET LOCAL lock_timeout = '300ms'"))
        raw = RawSnapshot(
            source_id=source.id,
            source_url=candidate.source_url,
            http_status=200,
            content_hash="a" * 64,
            raw_content="retained mock source payload",
            parser_version="mock-source-lock",
        )
        collector.add(raw)
        collector.commit()
        raw_id = raw.id

    # A second supported approval must still wait for the same source mutex.
    with SessionFactory() as competitor:
        competitor.execute(text("SET LOCAL lock_timeout = '300ms'"))
        with pytest.raises(OperationalError, match="lock timeout"):
            if lock_path == "print_source":
                assert_print_source_available(
                    competitor, source=source, card_print_id=physical.id
                )
            else:
                lookup_current_mapping(
                    competitor,
                    source=source,
                    url=candidate.source_url,
                    for_update=True,
                )
        competitor.rollback()

    # The approval is still uncommitted; raw retention is independently durable.
    approval.rollback()
    assert approval.get(RawSnapshot, raw_id) is not None
    assert approval.query(SourceCardMapping).count() == 0


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
