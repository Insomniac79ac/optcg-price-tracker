"""Mock published documents through the real PostgreSQL claim and singleton fences."""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    CanonicalCard,
    CardPrint,
    FreshnessAttempt,
    FreshnessPriceState,
    FreshnessWork,
    PriceObservation,
    RawSnapshot,
    ReleaseProduct,
    SnkrdunkCandidate,
    Source,
    SourceCardMapping,
    SourceDispatchBudget,
)
from app.services.freshness_queue import claim_due, plan_discovery_scope
from app.services.freshness_integration import Attempt, AdmissionStopped, CaptureResult
from snkrdunk_collector.discovery import RetainedDocument, consume
from snkrdunk_collector.run_lock import (
    COLLECTION_LOCK_KEY,
    LockLost,
    assert_lock_owned,
    collection_lock,
    pinned_session,
)
from test_discovery_runtime import ANCHOR, NEIGHBOUR, documents

T0 = datetime(2026, 10, 7, tzinfo=timezone.utc)


@pytest.fixture
def database():
    url = os.environ.get("SNKRDUNK_TEST_PG_URL")
    if not url:
        pytest.skip("disposable local PostgreSQL required")
    parsed = make_url(url)
    assert parsed.host in {"localhost", "127.0.0.1"} and parsed.database == "opcg_test"
    admin = create_engine(url)
    schema = "published_discovery_test_" + uuid.uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema}"})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        source = Source(name="snkrdunk", base_url="https://snkrdunk.com")
        canonical = CanonicalCard(
            card_code="OP01-001", name_en="Fixture", card_type="CHARACTER"
        )
        product = ReleaseProduct(
            source_catalogue="fixture",
            display_name="Fixture",
            first_seen_name="Fixture",
            source_series_id="fixture",
            source_url="https://example.test/",
        )
        session.add_all([source, canonical, product])
        session.flush()
        printing = CardPrint(
            canonical_card_id=canonical.id,
            release_product_id=product.id,
            language="jp",
            is_active=True,
            verification_status="verified",
            official_asset_variant="base",
            artwork_key="fixture-artwork",
        )
        session.add(printing)
        session.flush()
        anchor = SourceCardMapping(
            source_id=source.id,
            card_print_id=printing.id,
            source_url=ANCHOR,
            source_card_id="40001",
            is_active=True,
            manual_verified=True,
            review_status="approved",
        )
        session.add(anchor)
        session.flush()
        session.add(
            SourceDispatchBudget(
                source_id=source.id,
                enabled=True,
                request_limit=3100,
                window_seconds=1800,
                window_started_at=T0,
            )
        )
        scope = "snkr-published:postgres-mock-v1"
        work = plan_discovery_scope(
            session, source.id, scope, due_at=T0, estimated_request_cost=300
        )
        work.resume_cursor = {
            "version": 1,
            "scope_key": scope,
            "explicit_published_discovery": True,
            "anchor_mapping_ids": [anchor.id],
            "radius_start": 1,
            "radius_end": 1,
            "max_products": 20,
        }
        source_id = source.id
    try:
        yield engine, factory, source_id
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def start(session, source_id, clock):
    claim = claim_due(
        session,
        source_id,
        "offline-discovery",
        limit=1,
        lease=timedelta(seconds=240),
        clock=clock,
        supported_kinds={"discovery"},
    )[0]
    session.commit()
    return claim, Attempt(
        session, claim, ownership_check=assert_lock_owned, clock=clock
    )


def retained(attempt, source_id):
    responses = documents()

    def fetch(url):
        attempt.admit()
        status, body = responses[url]
        raw_id = attempt.snapshot(
            source_id, url, {"http_status": status, "html": body.decode()}, "mock-v1"
        )
        attempt.raw_snapshot_id = raw_id
        return RetainedDocument(url, body, raw_id, status)

    return fetch


def counts(factory):
    with factory() as session:
        return {
            model.__name__: session.scalar(select(func.count()).select_from(model))
            for model in (
                SnkrdunkCandidate,
                RawSnapshot,
                SourceCardMapping,
                PriceObservation,
                FreshnessPriceState,
            )
        }


def test_success_real_singleton_fence_checkpoint_and_replay(database):
    engine, factory, source_id = database
    with collection_lock(engine) as lock, pinned_session(lock, factory) as session:
        with collection_lock(engine) as competitor:
            assert not competitor.acquired
        claim, attempt = start(session, source_id, lambda: T0)
        result = consume(
            session, claim, freshness=attempt, fetch=retained(attempt, source_id)
        )
        assert attempt.finish(result)
        assert not attempt.finish(result)
        assert_lock_owned(session)
    assert counts(factory) == {
        "SnkrdunkCandidate": 1,
        "RawSnapshot": 4,
        "SourceCardMapping": 1,
        "PriceObservation": 0,
        "FreshnessPriceState": 0,
    }
    with factory() as session:
        work = session.get(FreshnessWork, claim.work_id)
        assert (
            work.resume_cursor["inspected_identities"] and work.next_due_at.year > 2100
        )
        assert work.attempt_count == 1
        assert session.scalar(select(FreshnessAttempt)).actual_request_cost == 4
        assert session.scalar(select(SourceDispatchBudget)).reserved_requests == 0
        assert session.scalar(select(SnkrdunkCandidate)).match_status == "unmatched"


@pytest.mark.parametrize("boundary", ["before_insert", "before_commit"])
def test_expired_claim_preserves_raw_without_candidates(database, boundary):
    engine, factory, source_id = database
    now = [T0]
    with collection_lock(engine) as lock, pinned_session(lock, factory) as session:
        claim, attempt = start(session, source_id, lambda: now[0])

        def expire():
            now[0] = T0 + timedelta(seconds=241)

        if boundary == "before_insert":
            with pytest.raises(ValueError, match="expired"):
                consume(
                    session,
                    claim,
                    freshness=attempt,
                    fetch=retained(attempt, source_id),
                    settle=expire,
                )
        else:
            result = consume(
                session, claim, freshness=attempt, fetch=retained(attempt, source_id)
            )
            expire()
            with pytest.raises(ValueError, match="expired"):
                attempt.finish(result)
        session.rollback()
    assert (
        counts(factory)["RawSnapshot"] == 4
        and counts(factory)["SnkrdunkCandidate"] == 0
    )
    with factory() as session:
        assert session.scalar(select(FreshnessAttempt)).outcome is None


def test_late_denial_pause_commits_before_candidate_writes(database):
    engine, factory, source_id = database
    with collection_lock(engine) as lock, pinned_session(lock, factory) as session:
        claim, attempt = start(session, source_id, lambda: T0)
        with pytest.raises(AdmissionStopped, match="source_denial"):
            consume(
                session,
                claim,
                freshness=attempt,
                fetch=retained(attempt, source_id),
                settle=attempt.deny,
            )
        session.rollback()
        assert attempt.finish(
            CaptureResult("source_denial", raw_snapshot_id=attempt.raw_snapshot_id)
        )
    assert (
        counts(factory)["RawSnapshot"] == 4
        and counts(factory)["SnkrdunkCandidate"] == 0
    )
    with factory() as session:
        assert (
            session.scalar(select(SourceDispatchBudget)).pause_reason == "source_denial"
        )
        assert session.scalar(select(FreshnessAttempt)).outcome == "source_denial"


def test_singleton_loss_after_insert_rolls_back_without_reacquisition(database):
    engine, factory, source_id = database
    with collection_lock(engine) as lock, pinned_session(lock, factory) as session:
        claim, attempt = start(session, source_id, lambda: T0)
        result = consume(
            session, claim, freshness=attempt, fetch=retained(attempt, source_id)
        )
        session.execute(
            text("SELECT pg_advisory_unlock(:key)"), {"key": COLLECTION_LOCK_KEY}
        )
        with collection_lock(engine) as competitor:
            assert competitor.acquired
            with pytest.raises(LockLost):
                attempt.finish(result)
        with pytest.raises(LockLost):
            assert_lock_owned(session)
        session.rollback()
    assert (
        counts(factory)["RawSnapshot"] == 4
        and counts(factory)["SnkrdunkCandidate"] == 0
    )
    assert counts(factory)["PriceObservation"] == 0


def test_runtime_settles_late_browser_denial_before_insert(database, monkeypatch):
    from types import SimpleNamespace
    from snkrdunk_collector import discovery, browser
    import playwright.sync_api

    engine, factory, source_id = database
    with collection_lock(engine) as lock, pinned_session(lock, factory) as session:
        claim, attempt = start(session, source_id, lambda: T0)
        page = SimpleNamespace()
        context = SimpleNamespace(new_page=lambda: page, close=lambda: None)
        mock_browser = SimpleNamespace(
            new_context=lambda **kw: context, close=lambda: None
        )

        class Playwright:
            def __enter__(self):
                return SimpleNamespace(
                    chromium=SimpleNamespace(launch=lambda **kw: mock_browser)
                )

            def __exit__(self, *args):
                pass

        monkeypatch.setattr(playwright.sync_api, "sync_playwright", Playwright)
        monkeypatch.setattr(
            browser,
            "goto_and_capture",
            lambda *args, **kw: {"http_status": 200, "classification": "normal_page"},
        )
        monkeypatch.setattr(attempt, "install_browser", lambda context: None)

        def late_denial(page):
            assert (
                session.scalar(select(func.count()).select_from(SnkrdunkCandidate)) == 0
            )
            if not attempt.denied:
                attempt.deny()
            attempt.check()

        monkeypatch.setattr(attempt, "settle_browser", late_denial)
        fetch = retained(attempt, source_id)
        monkeypatch.setattr(
            discovery, "retained_fetch", lambda page, fresh, sid, url: fetch(url)
        )
        with pytest.raises(AdmissionStopped, match="source_denial"):
            discovery.run_discovery(session, claim, freshness=attempt)
        session.rollback()
        assert attempt.finish(
            CaptureResult("source_denial", raw_snapshot_id=attempt.raw_snapshot_id)
        )
    assert (
        counts(factory)["RawSnapshot"] == 4
        and counts(factory)["SnkrdunkCandidate"] == 0
    )
