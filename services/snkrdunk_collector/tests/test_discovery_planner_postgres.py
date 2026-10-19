"""Automatic published discovery planning through the real PostgreSQL queue."""

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
    FreshnessWork,
    ReleaseProduct,
    Source,
    SourceCardMapping,
    SourceDispatchBudget,
)
from app.services.freshness_queue import claim_due
from snkrdunk_collector import due
from snkrdunk_collector.discovery import intent
from snkrdunk_collector.discovery_planner import plan_next_discovery

T0 = datetime(2026, 10, 19, 6, 27, tzinfo=timezone.utc)
SIX = timedelta(hours=6)


@pytest.fixture
def database():
    url = os.environ.get("SNKRDUNK_TEST_PG_URL")
    if not url:
        pytest.skip("disposable local PostgreSQL required")
    parsed = make_url(url)
    assert parsed.host in {"localhost", "127.0.0.1"} and parsed.database == "opcg_test"
    admin = create_engine(url)
    schema = "discovery_planner_test_" + uuid.uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    engine = create_engine(url, connect_args={"options": f"-c search_path={schema}"})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        source = Source(name="snkrdunk", base_url="https://snkrdunk.com")
        product = ReleaseProduct(
            source_catalogue="fixture",
            display_name="Fixture",
            first_seen_name="Fixture",
            source_series_id="fixture",
            source_url="https://example.test/",
        )
        session.add_all([source, product])
        session.flush()
        anchors = []
        for n in range(3):
            canonical = CanonicalCard(
                card_code=f"OP01-00{n + 1}", name_en="Fixture", card_type="CHARACTER"
            )
            session.add(canonical)
            session.flush()
            printing = CardPrint(
                canonical_card_id=canonical.id,
                release_product_id=product.id,
                language="jp",
                is_active=True,
                verification_status="verified",
                official_asset_variant="base",
                artwork_key=f"fixture-artwork-{n}",
            )
            session.add(printing)
            session.flush()
            mapping = SourceCardMapping(
                source_id=source.id,
                card_print_id=printing.id,
                source_url=f"https://snkrdunk.com/en/trading-cards/4000{n + 1}",
                source_card_id=f"4000{n + 1}",
                is_active=True,
                manual_verified=n < 2,  # the third is not an eligible anchor
                review_status="approved",
            )
            session.add(mapping)
            session.flush()
            anchors.append(mapping.id)
        session.add(
            SourceDispatchBudget(
                source_id=source.id,
                enabled=True,
                request_limit=3100,
                window_seconds=1800,
                window_started_at=T0,
            )
        )
        source_id = source.id
    try:
        yield factory, source_id, anchors
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()


def plan(factory, source_id, now):
    with factory() as session:
        work, reason = plan_next_discovery(session, source_id, now=now, interval=SIX)
        session.commit()
        return work, reason


def settle(factory, work_id, now, outcome="completed", inspected=("x",)):
    """Record a finished attempt the way a completed or refused scope ends."""
    with factory.begin() as session:
        work = session.get(FreshnessWork, work_id)
        work.state = "pending"
        work.attempt_count = 1
        work.next_due_at = now + timedelta(days=36500)
        work.resume_cursor = {
            **work.resume_cursor,
            "inspected_identities": list(inspected),
        }
        session.add(
            FreshnessAttempt(
                work_id=work_id,
                claim_token=str(uuid.uuid4()),
                claimed_by="test",
                claimed_at=now,
                finished_at=now,
                outcome=outcome,
                reserved_request_cost=300,
                charged_request_cost=0,
            )
        )


def test_plans_one_bounded_intent_the_adapter_accepts(database):
    factory, source_id, anchors = database
    work, reason = plan(factory, source_id, T0)
    assert reason is None
    assert work.scope_key == "snkr-published:auto-v1-20261019T062700Z"
    assert work.estimated_request_cost == 300 and work.state == "pending"
    cursor = work.resume_cursor
    assert cursor["anchor_mapping_ids"] == anchors[:2]
    assert (cursor["radius_start"], cursor["radius_end"], cursor["max_products"]) == (
        1,
        48,
        20,
    )
    assert cursor["explicit_published_discovery"] is True and cursor["version"] == 1
    # A second turn while the intent is open plans nothing.
    assert plan(factory, source_id, T0 + timedelta(minutes=30)) == (
        None,
        "discovery_open",
    )
    with factory() as session:
        claim = claim_due(
            session,
            source_id,
            "planner-test",
            limit=1,
            lease=timedelta(seconds=240),
            clock=lambda: T0,
            supported_kinds={"discovery"},
        )[0]
        _, _, _, identities = intent(session, claim)
        assert len(identities) == 2
        session.rollback()


def test_interval_then_rotation_to_least_used_anchor(database):
    factory, source_id, anchors = database
    first, _ = plan(factory, source_id, T0)
    settle(factory, first.id, T0)
    assert plan(factory, source_id, T0 + SIX - timedelta(minutes=1)) == (
        None,
        "interval",
    )
    with factory.begin() as session:
        session.get(SourceCardMapping, anchors[1]).manual_verified = False
        session.get(SourceCardMapping, anchors[2]).manual_verified = True
    second, reason = plan(factory, source_id, T0 + SIX)
    assert reason is None
    # The never-used anchor leads; the used one follows.
    assert second.resume_cursor["anchor_mapping_ids"] == [anchors[2], anchors[0]]


def test_closed_or_short_budget_plans_nothing(database):
    factory, source_id, _ = database
    with factory.begin() as session:
        budget = session.scalar(select(SourceDispatchBudget))
        budget.paused_until = T0 + timedelta(hours=1)
    assert plan(factory, source_id, T0) == (None, "source_closed")
    with factory.begin() as session:
        budget = session.scalar(select(SourceDispatchBudget))
        budget.paused_until = None
        budget.reserved_requests = 2900
    assert plan(factory, source_id, T0) == (None, "request_budget")
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(FreshnessWork)) == 0


def test_repeated_failures_stop_planning(database):
    factory, source_id, _ = database
    now = T0
    for outcome in ("identity_refusal", "transient_failure"):
        work, _ = plan(factory, source_id, now)
        settle(factory, work.id, now, outcome=outcome)
        now += SIX
    assert plan(factory, source_id, now) == (None, "recent_failures")


def test_exhausted_neighbourhoods_wait_for_a_new_anchor(database):
    factory, source_id, anchors = database
    now = T0
    for _ in range(3):
        work, _ = plan(factory, source_id, now)
        settle(factory, work.id, now, inspected=())
        now += SIX
    assert plan(factory, source_id, now) == (None, "neighbourhoods_exhausted")
    with factory.begin() as session:
        session.get(SourceCardMapping, anchors[2]).manual_verified = True
    work, reason = plan(factory, source_id, now)
    assert reason is None and work.resume_cursor["anchor_pool_size"] == 3


def test_kill_switch_and_turn_hook(database, monkeypatch):
    factory, source_id, _ = database
    monkeypatch.setattr(due, "assert_lock_owned", lambda session: None)
    monkeypatch.setattr(due.settings, "SNKRDUNK_AUTO_DISCOVERY", False)
    with factory() as session:
        assert due.plan_auto_discovery(session, source_id, clock=lambda: T0) is None
    monkeypatch.setattr(due.settings, "SNKRDUNK_AUTO_DISCOVERY", True)
    with factory() as session:
        work = due.plan_auto_discovery(session, source_id, clock=lambda: T0)
    assert work is not None
    with factory() as session:
        assert session.get(FreshnessWork, work.id).resume_cursor["scope_key"] == (
            work.scope_key
        )


def test_planner_error_never_blocks_the_turn(database, monkeypatch):
    factory, source_id, _ = database
    monkeypatch.setattr(due.settings, "SNKRDUNK_AUTO_DISCOVERY", True)

    def broken(*args, **kwargs):
        raise RuntimeError("fixture")

    monkeypatch.setattr(
        "snkrdunk_collector.discovery_planner.plan_next_discovery", broken
    )
    with factory() as session:
        assert due.plan_auto_discovery(session, source_id, clock=lambda: T0) is None
        assert session.scalar(select(func.count()).select_from(FreshnessWork)) == 0
