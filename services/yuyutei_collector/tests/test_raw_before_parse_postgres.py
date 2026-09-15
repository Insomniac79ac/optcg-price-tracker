"""Production raw-before-parse flow under PostgreSQL transaction semantics.

The browser is replaced with fixed response bodies, but the batch selector,
attempt telemetry, independent snapshot session, classifier, validator, writer,
commits, rollbacks, and row locks are the production functions. The database is
created and dropped for every test and must be PostgreSQL 16.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import os
from threading import Barrier, Event
from time import monotonic
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from yuyutei_collector import collect, telemetry
from yuyutei_collector.batch import run_batch
from yuyutei_collector.browser import classify_capture as real_classify_capture
from yuyutei_collector.collect import PARSER_VERSION
from yuyutei_collector.db import Base
from yuyutei_collector.models import (
    CanonicalCard,
    CardPrint,
    PriceObservation,
    RawSnapshot,
    Source,
    SourceCardMapping,
    SourceCollectionAttempt,
)
from yuyutei_collector.telemetry import RawSnapshotPersistenceError


HOST = os.environ.get("TEST_POSTGRES_HOST", "localhost")
PORT = os.environ.get("TEST_POSTGRES_PORT", "5544")
USER = os.environ.get("TEST_POSTGRES_USER", "opcg")
PASSWORD = os.environ.get("TEST_POSTGRES_PASSWORD", "opcg")
ADMIN_URL = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/postgres"
DB_NAME = "atlas_raw_before_parse_test"

PRODUCT_URL = "https://yuyu-tei.jp/sell/opc/card/op01/10002"
HOMEPAGE_URL = "https://yuyu-tei.jp/"
PRODUCT_HTML = "<html><body>OP01-001 " + ("product evidence " * 80) + "</body></html>"
GOOD_EXTRACTION = {
    "extraction_status": "extracted",
    "fail_reasons": [],
    "extracted": {
        "card_code": "OP01-001",
        "treatment": "parallel",
        "sell_price_jpy": 34_800,
        "stock_status": "out_of_stock",
        "promotion_state": "sale",
    },
}
IDENTITY_FAILURE = {
    "extraction_status": "fail_closed",
    "fail_reasons": ["card_code_conflict:displayed=OP01-099,expected=OP01-001"],
    "extracted": {
        "card_code": "OP01-099",
        "treatment": "parallel",
        "sell_price_jpy": 34_800,
        "stock_status": "out_of_stock",
        "promotion_state": "none",
    },
}
PRICE_FAILURE = {
    "extraction_status": "fail_closed",
    "fail_reasons": ["sell_price_missing"],
    "extracted": {
        "card_code": "OP01-001",
        "treatment": "parallel",
        "sell_price_jpy": None,
        "stock_status": "out_of_stock",
        "promotion_state": "none",
    },
}


@dataclass(frozen=True)
class PgSubject:
    engine: object
    Session: object
    source_id: int
    mapping_id: int


@pytest.fixture()
def pg():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{DB_NAME}"'))
    except OperationalError:
        admin.dispose()
        pytest.skip(f"No PostgreSQL server reachable at {HOST}:{PORT}")

    url = f"postgresql+psycopg://{USER}:{PASSWORD}@{HOST}:{PORT}/{DB_NAME}"
    # A lock defect must fail promptly instead of turning this proof into an
    # unbounded test process.
    engine = create_engine(
        url,
        connect_args={"options": "-c lock_timeout=2000 -c statement_timeout=5000"},
    )
    with engine.connect() as conn:
        assert conn.execute(text("SHOW server_version_num")).scalar_one().startswith("16")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    with Session() as session:
        source = Source(name="yuyutei", base_url=HOMEPAGE_URL)
        canonical = CanonicalCard(card_code="OP01-001")
        session.add_all([source, canonical])
        session.flush()
        card_print = CardPrint(
            canonical_card_id=canonical.id,
            treatment="parallel",
            verification_status="verified",
            is_active=True,
        )
        session.add(card_print)
        session.flush()
        mapping = SourceCardMapping(
            source_id=source.id,
            card_print_id=card_print.id,
            source_card_id="OP01-001",
            source_url=PRODUCT_URL,
            is_active=True,
            review_status="approved",
        )
        session.add(mapping)
        session.commit()
        subject = PgSubject(engine, Session, source.id, mapping.id)

    playwright = MagicMock()
    playwright.__enter__.return_value = playwright
    playwright.__exit__.return_value = False
    with (
        patch.object(telemetry, "SessionLocal", Session),
        patch("yuyutei_collector.batch._mapping_delay_s", return_value=0.0),
        patch.object(collect, "pkg_version", return_value="test"),
        patch.object(collect, "_release_browser_objects", return_value=None),
        patch.object(collect, "sync_playwright", return_value=playwright),
    ):
        yield subject

    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)'))
    admin.dispose()


def _normal_homepage():
    return {
        "final_url": HOMEPAGE_URL,
        "http_status": 200,
        "navigation_ok": True,
        "page_title": "遊々亭",
        "classification": "normal_product",
        "classification_evidence": ["expected_content_present=True"],
        "html": "<html><body>遊々亭 homepage</body></html>",
    }


def _product(html=PRODUCT_HTML):
    return {
        "final_url": PRODUCT_URL,
        "http_status": 200,
        "navigation_ok": True,
        "page_title": "OP01-001",
        "html_bytes": len(html.encode("utf-8")),
        "elapsed_s": 0.1,
        "html": html,
    }


def _run(pg, *, extraction=GOOD_EXTRACTION, validate_only=False):
    extraction_patch = (
        patch.object(collect, "extract_with_agreement", side_effect=extraction)
        if isinstance(extraction, Exception)
        else patch.object(collect, "extract_with_agreement", return_value=extraction)
    )
    with (
        patch.object(collect, "warm_up_homepage", return_value=_normal_homepage()),
        patch.object(collect, "goto_and_capture_raw", return_value=_product()),
        extraction_patch,
    ):
        return run_batch(session_factory=pg.Session, validate_only=validate_only)


def _rows(pg):
    with pg.Session() as session:
        attempts = session.scalars(select(SourceCollectionAttempt)).all()
        snapshots = session.scalars(select(RawSnapshot)).all()
        observations = session.scalars(select(PriceObservation)).all()
        return attempts, snapshots, observations


def _assert_committed_link(pg):
    with pg.Session() as observer:
        attempt = observer.scalars(select(SourceCollectionAttempt)).one()
        snapshot = observer.scalars(select(RawSnapshot)).one()
        assert attempt.raw_snapshot_id == snapshot.id


def _persistence_kwargs(pg, *, run="concurrent-run", content=PRODUCT_HTML):
    return {
        "bind": pg.engine,
        "source_id": pg.source_id,
        "source_url": PRODUCT_URL,
        "http_status": 200,
        "raw_content": content,
        "parser_version": PARSER_VERSION,
        "batch_run_id": run,
        "source_card_mapping_id": pg.mapping_id,
    }


def _record_started_attempt(pg, run="concurrent-run"):
    assert telemetry.record_selected_batch(run, pg.source_id, [pg.mapping_id])
    assert telemetry.mark_attempt_started(run, pg.mapping_id)


def test_attempt_is_visible_before_independent_snapshot_session_and_success_links_one_row(pg):
    attempt_visible = Event()
    real_persist = telemetry.persist_response_snapshot

    def persist_after_visibility_check(**kwargs):
        # This observer is a third database session. It proves selection/start
        # committed before persist_response_snapshot creates its own session.
        with pg.Session() as observer:
            attempt = observer.scalars(select(SourceCollectionAttempt)).one()
            assert attempt.started_at is not None
            assert attempt.raw_snapshot_id is None
        attempt_visible.set()
        return real_persist(**kwargs)

    def classify_after_commit(step, expected_markers):
        _assert_committed_link(pg)
        return real_classify_capture(step, expected_markers)

    def parse_after_commit(*_args):
        _assert_committed_link(pg)
        return GOOD_EXTRACTION

    started = monotonic()
    with (
        patch.object(collect, "warm_up_homepage", return_value=_normal_homepage()),
        patch.object(collect, "goto_and_capture_raw", return_value=_product()),
        patch.object(
            collect,
            "persist_response_snapshot",
            side_effect=persist_after_visibility_check,
        ),
        patch.object(collect, "classify_capture", side_effect=classify_after_commit),
        patch.object(collect, "extract_with_agreement", side_effect=parse_after_commit),
    ):
        result = run_batch(session_factory=pg.Session)

    assert monotonic() - started < 5
    assert attempt_visible.is_set()
    assert result.status == "success"
    attempts, snapshots, observations = _rows(pg)
    assert (len(attempts), len(snapshots), len(observations)) == (1, 1, 1)
    attempt, snapshot, observation = attempts[0], snapshots[0], observations[0]
    assert attempt.status == "written"
    assert attempt.raw_snapshot_id == snapshot.id
    assert attempt.price_observation_id == observation.id
    assert observation.raw_snapshot_id == snapshot.id


def test_later_writer_rollback_preserves_snapshot_and_attempt_link(pg):
    real_writer = collect.validate_and_write_observation

    def flush_then_fail(**kwargs):
        write_result = real_writer(**kwargs)
        assert write_result.written
        _assert_committed_link(pg)
        with pg.Session() as observer:
            assert observer.scalars(select(PriceObservation)).all() == []
        raise RuntimeError("after observation flush")

    with patch.object(
        collect, "validate_and_write_observation", side_effect=flush_then_fail
    ):
        result = _run(pg)

    attempts, snapshots, observations = _rows(pg)
    assert result.results[0].stage == "operational_error"
    assert attempts[0].status == "operational_error"
    assert attempts[0].raw_snapshot_id == snapshots[0].id
    assert len(snapshots) == 1
    assert observations == []


@pytest.mark.parametrize(
    ("extraction", "terminal_status", "reason"),
    [
        (ValueError("bad markup"), "operational_error", "parser_failure:"),
        (IDENTITY_FAILURE, "validation_failed", "card_code_conflict"),
        (PRICE_FAILURE, "validation_failed", "sell_price_missing"),
    ],
)
def test_parser_identity_and_price_failures_keep_committed_evidence(
    pg, extraction, terminal_status, reason
):
    result = _run(pg, extraction=extraction)

    attempts, snapshots, observations = _rows(pg)
    assert result.results[0].stage == terminal_status
    assert attempts[0].status == terminal_status
    assert reason in attempts[0].failure_reason
    assert attempts[0].raw_snapshot_id == snapshots[0].id
    assert len(snapshots) == 1
    assert observations == []


def test_concurrent_identical_calls_share_one_locked_snapshot(pg):
    _record_started_attempt(pg)
    barrier = Barrier(2)

    def persist():
        barrier.wait(timeout=2)
        return telemetry.persist_response_snapshot(**_persistence_kwargs(pg))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(persist) for _ in range(2)]
        results = [future.result(timeout=8) for future in futures]

    assert len({result.raw_snapshot_id for result in results}) == 1
    assert sorted(result.created for result in results) == [False, True]
    attempts, snapshots, observations = _rows(pg)
    assert (len(attempts), len(snapshots), len(observations)) == (1, 1, 0)
    assert attempts[0].raw_snapshot_id == snapshots[0].id == results[0].raw_snapshot_id


def test_concurrent_conflicting_calls_leave_one_canonical_snapshot(pg):
    _record_started_attempt(pg)
    barrier = Barrier(2)

    def persist(content):
        barrier.wait(timeout=2)
        return telemetry.persist_response_snapshot(
            **_persistence_kwargs(pg, content=content)
        )

    contents = [PRODUCT_HTML + "-a", PRODUCT_HTML + "-b"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(persist, content) for content in contents]
        resolved = []
        conflicts = []
        for future in futures:
            try:
                resolved.append(future.result(timeout=8))
            except RawSnapshotPersistenceError as exc:
                conflicts.append(str(exc))

    assert len(resolved) == 1
    assert conflicts == ["attempt_snapshot_conflict"]
    attempts, snapshots, observations = _rows(pg)
    assert (len(attempts), len(snapshots), len(observations)) == (1, 1, 0)
    canonical_id = resolved[0].raw_snapshot_id
    assert attempts[0].raw_snapshot_id == snapshots[0].id == canonical_id
    assert snapshots[0].raw_content in contents


def test_production_validate_only_entry_writes_nothing(pg):
    with patch.object(collect, "persist_response_snapshot") as persist:
        result = _run(pg, validate_only=True)

    assert result.results[0].stage == "validated_only"
    assert _rows(pg) == ([], [], [])
    persist.assert_not_called()
