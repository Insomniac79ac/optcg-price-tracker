"""Synthetic fixtures on disposable local PostgreSQL; never source-site requests."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os

import pytest
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (
    CanonicalCard,
    CardPrint,
    FreshnessAttempt,
    FreshnessPriceState,
    FreshnessWork,
    PriceObservation,
    RawSnapshot,
    ReleaseProduct,
    Source,
    SourceCardMapping,
    SourceDispatchBudget,
)
from app.services.freshness_queue import (
    admit_request,
    claim_due,
    complete_claim,
    plan_discovery_scope,
    plan_print_discovery,
    plan_refresh,
    plan_validation,
)

T0 = datetime(2026, 9, 30, tzinfo=timezone.utc)
URL = os.environ.get(
    "TEST_POSTGRES_URL", "postgresql+psycopg://opcg:opcg@localhost:5544/opcg_test"
)


@pytest.fixture()
def db():
    parsed = make_url(URL)
    if parsed.host not in {"localhost", "127.0.0.1"} or parsed.database != "opcg_test":
        pytest.skip("freshness tests require local disposable opcg_test")
    engine = create_engine(URL)
    try:
        with engine.connect():
            pass
    except OperationalError:
        engine.dispose()
        pytest.skip("disposable local PostgreSQL is unavailable")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    with factory.begin() as session:
        source = Source(name="snkrdunk", base_url="https://snkrdunk.com")
        canonical = CanonicalCard(
            card_code="OP01-001", name_en="Fixture", card_type="CHARACTER"
        )
        product = ReleaseProduct(
            source_catalogue="fixture",
            display_name="Fixture",
            first_seen_name="Fixture",
            source_series_id="fixture-1",
            source_url="https://example.test/fixture",
        )
        session.add_all([source, canonical, product])
        session.flush()
        card_print = CardPrint(
            canonical_card_id=canonical.id,
            language="jp",
            is_active=True,
            release_product_id=product.id,
            official_asset_variant="base",
            artwork_key="fixture-artwork",
            verification_status="verified",
        )
        session.add(card_print)
        session.flush()
        session.add(
            SourceDispatchBudget(
                source_id=source.id,
                enabled=True,
                request_limit=1000,
                window_seconds=86400,
                window_started_at=T0,
            )
        )
        source_id, print_id = source.id, card_print.id
    mapping_id = mapping(factory, source_id, print_id, 123)
    try:
        yield factory, source_id, mapping_id, print_id
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def mapping(factory, source, print_id, product_id):
    with factory.begin() as session:
        row = SourceCardMapping(
            source_id=source,
            card_print_id=print_id,
            source_card_id=str(product_id),
            source_url=f"https://snkrdunk.com/apparels/{product_id}",
            is_active=True,
            manual_verified=True,
            review_status="approved",
        )
        session.add(row)
        session.flush()
        return row.id


def snapshot(factory, source, at):
    with factory.begin() as session:
        row = RawSnapshot(
            source_id=source,
            source_url="https://snkrdunk.com/apparels/123",
            fetched_at=at,
            http_status=200,
            content_hash="a" * 64,
            raw_content="fixture",
        )
        session.add(row)
        session.flush()
        return row.id


def observation(
    factory, mapping_id, snapshot_id, at, category="raw", price=100, condition=None
):
    with factory.begin() as session:
        subject = session.get(SourceCardMapping, mapping_id)
        row = PriceObservation(
            source_id=subject.source_id,
            source_card_mapping_id=mapping_id,
            card_print_id=subject.card_print_id,
            raw_snapshot_id=snapshot_id,
            observed_at=at,
            price_type=category,
            condition_label=condition,
            price_jpy=price,
        )
        session.add(row)
        session.flush()
        return row.id


def claim(factory, source, at=T0, owner="worker", limit=1):
    with factory.begin() as session:
        return claim_due(
            session,
            source,
            owner,
            limit=limit,
            lease=timedelta(minutes=10),
            clock=lambda: at,
        )


def admit(factory, token, at=T0, ordinal=1, cost=1):
    with factory.begin() as session:
        return admit_request(
            session, token, ordinal=ordinal, cost=cost, clock=lambda: at
        )


def plan(factory, mapping_id, *, high=False, categories=None, at=T0, cost=1):
    with factory.begin() as session:
        return plan_refresh(
            session,
            mapping_id,
            categories or {"raw"},
            high_interest=high,
            clock=lambda: at,
            estimated_request_cost=cost,
        ).id


def finish(factory, token, at, **result):
    with factory.begin() as session:
        return complete_claim(session, token, clock=lambda: at, **result)


def test_coalescing_idempotent_plan_partial_capture_and_new_demand(db):
    factory, source, mapping_id, _ = db
    work_id = plan(factory, mapping_id, categories={"raw", "psa10"})
    assert plan(factory, mapping_id, categories={"psa10"}) == work_id
    first = claim(factory, source)[0]
    assert first.price_categories == ("psa10", "raw")
    assert claim(factory, source) == []
    # A new category planned while claimed is still due after a partial result.
    assert plan(factory, mapping_id, categories={"buy"}) == work_id
    admit(factory, first.claim_token)
    captured_at = T0 + timedelta(seconds=1)
    raw_id = snapshot(factory, source, captured_at)
    obs = observation(factory, mapping_id, raw_id, captured_at)
    finish(
        factory,
        first.claim_token,
        captured_at,
        outcome="captured",
        actual_request_cost=1,
        raw_snapshot_id=raw_id,
        observation_ids={"raw": obs},
        no_listing_categories={"psa10"},
    )
    with factory() as session:
        states = {
            s.price_category: s for s in session.scalars(select(FreshnessPriceState))
        }
        assert states["raw"].last_valid_price_observed_at == captured_at
        assert states["psa10"].availability == "no_listing"
        assert states["psa10"].last_valid_price_observed_at is None
        assert states["buy"].next_due_at == T0
        assert states["buy"].last_successfully_checked_at is None
    assert claim(factory, source, captured_at)[0].work_id == work_id


def test_unchanged_recapture_replay_and_conflicting_delivery(db):
    factory, source, mapping_id, _ = db
    plan(factory, mapping_id)
    for at in (T0, T0 + timedelta(hours=23)):
        token = claim(factory, source, at)[0].claim_token
        admit(factory, token, at)
        raw_id = snapshot(factory, source, at)
        # A later parse timestamp must not become the new freshness origin.
        obs = observation(
            factory, mapping_id, raw_id, at + timedelta(seconds=1), price=100
        )
        result = dict(
            outcome="captured",
            actual_request_cost=1,
            raw_snapshot_id=raw_id,
            observation_ids={"raw": obs},
        )
        assert finish(factory, token, at + timedelta(seconds=2), **result)
        assert not finish(factory, token, at + timedelta(seconds=3), **result)
        with pytest.raises(ValueError, match="conflicting"):
            finish(
                factory,
                token,
                at + timedelta(seconds=4),
                **{**result, "actual_request_cost": 0},
            )
    with factory() as session:
        state = session.scalar(select(FreshnessPriceState))
        assert state.last_valid_price_observed_at == T0 + timedelta(hours=23)
        assert session.scalar(select(SourceDispatchBudget.used_requests)) == 2
        assert session.scalar(select(func.count()).select_from(PriceObservation)) == 2


def test_no_listing_and_failures_preserve_price_and_overdue_deadline(db):
    factory, source, mapping_id, _ = db
    plan(factory, mapping_id, high=True)
    token = claim(factory, source)[0].claim_token
    admit(factory, token)
    raw_id = snapshot(factory, source, T0)
    obs = observation(factory, mapping_id, raw_id, T0)
    finish(
        factory,
        token,
        T0,
        outcome="captured",
        actual_request_cost=1,
        raw_snapshot_id=raw_id,
        observation_ids={"raw": obs},
    )
    at = T0 + timedelta(hours=3)
    token = claim(factory, source, at)[0].claim_token
    admit(factory, token, at)
    new_raw = snapshot(factory, source, at)
    with pytest.raises(ValueError, match="new current product capture"):
        finish(
            factory,
            token,
            at,
            outcome="captured",
            actual_request_cost=1,
            raw_snapshot_id=new_raw,
            observation_ids={"raw": obs},
        )
    finish(
        factory,
        token,
        at,
        outcome="no_listing",
        actual_request_cost=1,
        raw_snapshot_id=new_raw,
        no_listing_categories={"raw"},
    )
    plan(factory, mapping_id, high=True, at=at + timedelta(seconds=1))
    with factory() as session:
        state = session.scalar(select(FreshnessPriceState))
        assert state.last_valid_price_observed_at == T0
        assert state.last_successfully_checked_at == at
        assert state.availability == "no_listing"
        assert state.next_due_at == T0 + timedelta(hours=6)
    failed_at = T0 + timedelta(hours=6)
    token = claim(factory, source, failed_at)[0].claim_token
    admit(factory, token, failed_at)
    finish(
        factory, token, failed_at, outcome="transient_failure", actual_request_cost=1
    )
    with factory() as session:
        work = session.scalar(select(FreshnessWork))
        assert work.next_due_at == failed_at  # backoff cannot hide overdue work
        assert work.retry_not_before_at == failed_at + timedelta(minutes=15)
        assert work.last_successfully_checked_at == at
        assert work.last_attempted_at == failed_at
        assert (
            session.scalar(select(FreshnessPriceState)).last_valid_price_observed_at
            == T0
        )
    assert claim(factory, source, failed_at + timedelta(minutes=14)) == []


def test_old_historical_and_reprocessed_evidence_refused(db):
    factory, source, mapping_id, _ = db
    old_raw = snapshot(factory, source, T0 - timedelta(days=7))
    old_obs = observation(factory, mapping_id, old_raw, T0 - timedelta(days=7))
    plan(factory, mapping_id)
    token = claim(factory, source)[0].claim_token
    admit(factory, token)
    with pytest.raises(ValueError, match="new source raw snapshot"):
        finish(
            factory,
            token,
            T0,
            outcome="captured",
            actual_request_cost=1,
            raw_snapshot_id=old_raw,
            observation_ids={"raw": old_obs},
        )
    new_raw = snapshot(factory, source, T0)
    historical_obs = observation(factory, mapping_id, new_raw, T0 - timedelta(days=1))
    with pytest.raises(ValueError, match="new current product capture"):
        finish(
            factory,
            token,
            T0,
            outcome="captured",
            actual_request_cost=1,
            raw_snapshot_id=new_raw,
            observation_ids={"raw": historical_obs},
        )
    with factory() as session:
        assert (
            session.scalar(select(FreshnessPriceState.last_valid_price_observed_at))
            is None
        )
        assert session.scalar(select(SourceDispatchBudget.reserved_requests)) == 1


def test_concurrent_claims_expiry_stale_owner_and_unknown_crash_cost(db):
    factory, source, mapping_id, _ = db
    plan(factory, mapping_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda name: claim(factory, source, owner=name), ["a", "b"])
        )
    assert sorted(map(len, results)) == [0, 1]
    old = next(rows[0] for rows in results if rows)
    # Claiming alone is not an attempt to contact a source.
    with factory() as session:
        assert session.scalar(select(FreshnessWork.last_attempted_at)) is None
    new = claim(factory, source, T0 + timedelta(minutes=10), "recovery")[0]
    assert new.claim_token != old.claim_token
    with pytest.raises(ValueError, match="expired or replaced"):
        finish(
            factory,
            old.claim_token,
            T0 + timedelta(minutes=10),
            outcome="transient_failure",
            actual_request_cost=0,
        )
    with pytest.raises(ValueError, match="expired or replaced"):
        admit(factory, old.claim_token, T0 + timedelta(minutes=10))
    with factory() as session:
        attempt = session.scalar(
            select(FreshnessAttempt).where(
                FreshnessAttempt.claim_token == old.claim_token
            )
        )
        assert attempt.outcome == "expired"
        assert attempt.actual_request_cost is None
        assert attempt.charged_request_cost == 1
        assert session.scalar(select(SourceDispatchBudget.reserved_requests)) == 1
        assert session.scalar(select(SourceDispatchBudget.used_requests)) == 1


def test_shared_budget_concurrent_claimants_and_pause_of_already_claimed_work(db):
    factory, source, mapping_id, print_id = db
    plan(factory, mapping_id, cost=2)
    with factory.begin() as session:
        plan_discovery_scope(
            session, source, "release:OP01", due_at=T0, estimated_request_cost=2
        )
        plan_print_discovery(
            session, source, print_id, due_at=T0, estimated_request_cost=2
        )
        plan_validation(
            session, source, "candidate:1", due_at=T0, estimated_request_cost=2
        )
        session.scalar(select(SourceDispatchBudget)).request_limit = 4
    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(
            pool.map(lambda n: claim(factory, source, owner=str(n), limit=4), range(4))
        )
    claims = [c for batch in batches for c in batch]
    assert len(claims) == 2
    assert admit(factory, claims[0].claim_token)
    assert not admit(factory, claims[0].claim_token)  # replay must not dispatch again
    with pytest.raises(ValueError, match="upper bound"):
        admit(factory, claims[0].claim_token, ordinal=2, cost=2)
    finish(
        factory,
        claims[0].claim_token,
        T0,
        outcome="source_denial",
        actual_request_cost=1,
    )
    with pytest.raises(ValueError, match="paused"):
        admit(factory, claims[1].claim_token)
    assert claim(factory, source, T0 + timedelta(days=2), limit=100) == []
    with factory() as session:
        assert (
            session.scalar(select(SourceDispatchBudget.pause_reason)) == "source_denial"
        )
        assert session.scalar(select(SourceDispatchBudget.paused_until)) is None


def test_unconfigured_disabled_and_timed_pause_refuse_dispatch(db):
    factory, source, mapping_id, _ = db
    plan(factory, mapping_id)
    with factory.begin() as session:
        budget = session.scalar(select(SourceDispatchBudget))
        budget.enabled = False
    assert claim(factory, source) == []
    with factory.begin() as session:
        budget = session.scalar(select(SourceDispatchBudget))
        budget.enabled = True
        budget.paused_until = T0 + timedelta(hours=1)
    assert claim(factory, source) == []
    assert len(claim(factory, source, T0 + timedelta(hours=1))) == 1
    with factory.begin() as session:
        session.execute(delete(SourceDispatchBudget))
    with pytest.raises(ValueError, match="unconfigured"):
        claim(factory, source)


def test_identity_refusal_is_blocked_and_mapping_gate_rechecked(db):
    factory, source, mapping_id, _ = db
    plan(factory, mapping_id)
    token = claim(factory, source)[0].claim_token
    admit(factory, token)
    finish(factory, token, T0, outcome="identity_refusal", actual_request_cost=1)
    plan(factory, mapping_id, at=T0 + timedelta(days=1))
    assert claim(factory, source, T0 + timedelta(days=1)) == []
    with factory() as session:
        assert session.scalar(select(FreshnessWork.state)) == "blocked"
        assert session.scalar(select(SourceDispatchBudget.pause_reason)) is None
    with factory.begin() as session:
        session.get(SourceCardMapping, mapping_id).manual_verified = False
    with pytest.raises(ValueError, match="approved exact-print"):
        plan(factory, mapping_id)


def test_bounded_fairness_overdue_order_and_new_mapping_lane(db):
    factory, source, _, print_id = db
    lanes = {}
    for lane in ("high", "ordinary", "coverage"):
        for n in range(12):
            mid = mapping(factory, source, print_id, 1000 + len(lanes))
            wid = plan(factory, mid, high=lane != "ordinary")
            with factory.begin() as session:
                row = session.get(FreshnessWork, wid)
                if lane != "coverage":
                    row.last_successfully_checked_at = T0 - timedelta(days=1)
                    row.lane = lane
            lanes[wid] = lane
    with factory.begin() as session:
        for n in range(12):
            row = plan_discovery_scope(session, source, f"scope:{n}", due_at=T0)
            session.flush()
            lanes[row.id] = "discovery"
    selected = [claim(factory, source)[0] for _ in range(16)]
    for start in (0, 8):
        assert {lanes[c.work_id] for c in selected[start : start + 8]} == {
            "high",
            "ordinary",
            "discovery",
            "coverage",
        }
    # All high-interest first-time mappings still enter the coverage lane.
    assert [lanes[c.work_id] for c in selected].count("coverage") == 2
    with factory.begin() as session:
        older = plan_discovery_scope(
            session, source, "older", due_at=T0 - timedelta(days=1)
        )
        session.flush()
        older_id = older.id
    # Advance to the guaranteed discovery slot: the oldest scope wins there.
    due_claims = claim(factory, source, limit=4)
    assert older_id in {c.work_id for c in due_claims}


def test_resume_tail_fairness_and_seventy_is_only_a_chunk(db):
    factory, source, _, _ = db
    with factory.begin() as session:
        for n in range(141):
            plan_discovery_scope(session, source, f"scope:{n:03}", due_at=T0)
    first = claim(factory, source, limit=70)
    second = claim(factory, source, limit=70)
    assert len(first) == len(second) == 70
    assert not {c.work_id for c in first} & {c.work_id for c in second}
    # Frozen-clock progress cannot jump ahead of the unserved tail, even if
    # the original plan is replayed with its original due date.
    token = first[0].claim_token
    admit(factory, token)
    raw_id = snapshot(factory, source, T0)
    finish(
        factory,
        token,
        T0,
        outcome="discovery_progress",
        actual_request_cost=1,
        raw_snapshot_id=raw_id,
        resume_cursor={"version": 1, "existing_run_id": 42, "page": 7},
    )
    with factory.begin() as session:
        plan_discovery_scope(session, source, first[0].scope_key, due_at=T0)
    tail = claim(factory, source)[0]
    assert tail.work_id not in {c.work_id for c in first + second}
    resumed = claim(factory, source)[0]
    assert resumed.work_id == first[0].work_id
    assert resumed.resume_cursor == {"version": 1, "existing_run_id": 42, "page": 7}


def test_claim_transaction_releases_row_locks_before_io(db):
    factory, source, mapping_id, _ = db
    plan(factory, mapping_id)
    picked = claim(factory, source)[0]
    with factory.begin() as session:
        assert session.scalar(
            select(FreshnessWork)
            .where(FreshnessWork.id == picked.work_id)
            .with_for_update(nowait=True)
        )
        assert session.scalar(select(SourceDispatchBudget).with_for_update(nowait=True))


def test_invalid_discovery_mapping_lineage_is_rejected_by_database(db):
    factory, source, mapping_id, print_id = db
    with pytest.raises(IntegrityError):
        with factory.begin() as session:
            row = plan_discovery_scope(session, source, "scope", due_at=T0)
            row.source_card_mapping_id = mapping_id
            row.card_print_id = print_id
            session.flush()


@pytest.mark.parametrize(
    "include_prices,include_raw", [(False, False), (True, False), (True, True)]
)
def test_backup_roundtrip_disables_dispatch_and_fences_restored_claims(
    db, include_prices, include_raw
):
    import json
    from app.services.backup import export_backup, restore_backup, validate_backup

    factory, source, mapping_id, _ = db
    plan(factory, mapping_id)
    token = claim(factory, source)[0].claim_token
    admit(factory, token)
    raw_id = snapshot(factory, source, T0)
    obs = observation(factory, mapping_id, raw_id, T0)
    finish(
        factory,
        token,
        T0,
        outcome="captured",
        actual_request_cost=1,
        raw_snapshot_id=raw_id,
        observation_ids={"raw": obs},
    )
    with factory.begin() as session:
        plan_discovery_scope(session, source, "pending-scope", due_at=T0)
    active = claim(factory, source)[0]
    admit(factory, active.claim_token)
    with factory() as session:
        archive = json.loads(
            json.dumps(
                export_backup(
                    session,
                    include_prices=include_prices,
                    include_raw_snapshots=include_raw,
                )
            )
        )
    assert validate_backup(archive).valid
    assert archive["metadata"]["backup_version"] == 17
    assert archive["tables"]["freshness_price_states"][0]["last_observation_id"] == (
        obs if include_prices else None
    )
    assert archive["tables"]["freshness_attempts"][0]["raw_snapshot_id"] == (
        raw_id if include_raw else None
    )
    # Selective archives restore into a clean migrated destination. Existing
    # prices intentionally block replacement when prices were excluded.
    engine = factory.kw["bind"]
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with factory() as session:
        restored = restore_backup(
            session,
            archive,
            dry_run=False,
            mode="replace",
            confirm="RESTORE",
            skip_lock=True,
        )
        assert restored.valid, restored.errors
        assert any("disabled" in w for w in restored.warnings)
    with factory() as session:
        budget = session.scalar(select(SourceDispatchBudget))
        assert not budget.enabled and budget.reserved_requests == 0
        attempt = session.scalar(
            select(FreshnessAttempt).where(
                FreshnessAttempt.claim_token == active.claim_token
            )
        )
        assert attempt.outcome == "expired" and attempt.actual_request_cost is None
        assert (
            session.scalar(select(FreshnessPriceState.last_valid_price_observed_at))
            == T0
        )
    assert claim(factory, source, T0 + timedelta(days=1)) == []
    with pytest.raises(ValueError, match="expired or replaced"):
        finish(
            factory,
            active.claim_token,
            T0,
            outcome="transient_failure",
            actual_request_cost=0,
        )


def test_v15_archive_restores_without_inventing_work_or_limits(db):
    from app.services.backup import export_backup, restore_backup, validate_backup
    from app.services.freshness_backup import TABLES

    factory, _, _, _ = db
    with factory() as session:
        archive = export_backup(session)
    archive["metadata"]["backup_version"] = 15
    for name in TABLES:
        archive["tables"].pop(name)
    assert validate_backup(archive).valid
    with factory() as session:
        result = restore_backup(
            session,
            archive,
            dry_run=False,
            mode="replace",
            confirm="RESTORE",
            skip_lock=True,
        )
        assert result.valid, result.errors
        assert session.scalar(select(func.count()).select_from(FreshnessWork)) == 0
        assert (
            session.scalar(select(func.count()).select_from(SourceDispatchBudget)) == 0
        )


def test_source_budget_window_boundary_keeps_outstanding_reservations(db):
    factory, source, mapping_id, _ = db
    plan(factory, mapping_id, cost=3)
    with factory.begin() as session:
        budget = session.scalar(select(SourceDispatchBudget))
        budget.request_limit = 3
        budget.window_seconds = 5
        plan_discovery_scope(session, source, "other", due_at=T0)
    picked = claim(factory, source)[0]
    assert picked.reserved_request_cost == 3
    assert claim(factory, source, T0 + timedelta(seconds=5)) == []
    admit(factory, picked.claim_token, T0 + timedelta(seconds=6))
    finish(
        factory,
        picked.claim_token,
        T0 + timedelta(seconds=7),
        outcome="transient_failure",
        actual_request_cost=1,
    )
    assert len(claim(factory, source, T0 + timedelta(seconds=7))) == 1


def test_actual_cost_overrun_is_recorded_and_pauses_source(db):
    factory, source, mapping_id, _ = db
    plan(factory, mapping_id)
    picked = claim(factory, source)[0]
    admit(factory, picked.claim_token)
    finish(
        factory,
        picked.claim_token,
        T0,
        outcome="transient_failure",
        actual_request_cost=3,
    )
    with factory() as session:
        budget = session.scalar(select(SourceDispatchBudget))
        assert budget.used_requests == 3
        assert budget.pause_reason == "request_cost_overrun"
        assert session.scalar(select(FreshnessAttempt.actual_request_cost)) == 3
    assert claim(factory, source, T0 + timedelta(days=1)) == []


def test_result_writer_is_fenced_and_idempotent_in_one_transaction(db):
    from app.services.freshness_queue import lock_for_result

    factory, source, mapping_id, print_id = db
    plan(factory, mapping_id)
    picked = claim(factory, source)[0]
    admit(factory, picked.claim_token)
    raw_id = snapshot(factory, source, T0)
    for _ in range(2):
        with factory.begin() as session:
            if not lock_for_result(session, picked.claim_token, clock=lambda: T0):
                continue
            row = PriceObservation(
                source_id=source,
                source_card_mapping_id=mapping_id,
                card_print_id=print_id,
                raw_snapshot_id=raw_id,
                observed_at=T0,
                price_type="raw",
                price_jpy=100,
            )
            session.add(row)
            session.flush()
            complete_claim(
                session,
                picked.claim_token,
                outcome="captured",
                actual_request_cost=1,
                raw_snapshot_id=raw_id,
                observation_ids={"raw": row.id},
                clock=lambda: T0,
            )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(PriceObservation)) == 1
        assert session.scalar(select(SourceDispatchBudget.used_requests)) == 1


def test_yuyutei_nine_shard_membership_is_preserved(db):
    factory, source, mapping_id, print_id = db
    with factory.begin() as session:
        session.get(Source, source).name = "yuyutei"
        session.flush()
        session.get(SourceCardMapping, mapping_id).source_url = (
            "https://yuyu-tei.jp/sell/opc/card/op01/123"
        )
        session.flush()
        for n in range(9):
            session.add(
                SourceCardMapping(
                    source_id=source,
                    card_print_id=print_id,
                    source_card_id=str(200 + n),
                    source_url=f"https://yuyu-tei.jp/sell/opc/card/op01/{200+n}",
                    is_active=True,
                    review_status="approved",
                    manual_verified=False,
                )
            )
    with factory() as session:
        ids = session.scalars(select(SourceCardMapping.id)).all()
    for mid in ids:
        plan(factory, mid)
    claimed = []
    for shard in range(9):
        with factory.begin() as session:
            batch = claim_due(
                session,
                source,
                f"shard-{shard}",
                limit=70,
                lease=timedelta(minutes=10),
                yuyutei_shard_index=shard,
                clock=lambda: T0,
            )
            assert all(item.source_card_mapping_id % 9 == shard for item in batch)
            claimed.extend(item.source_card_mapping_id for item in batch)
    assert sorted(claimed) == sorted(ids)


def test_shard_cannot_consume_discovery_fairness_turn(db):
    factory, source, mapping_id, _ = db
    with factory.begin() as session:
        session.get(Source, source).name = "yuyutei"
        session.flush()
        session.get(SourceCardMapping, mapping_id).source_url = (
            "https://yuyu-tei.jp/sell/opc/card/op01/123"
        )
    plan(factory, mapping_id)
    with factory.begin() as session:
        plan_discovery_scope(session, source, "scope", due_at=T0)
        session.scalar(select(SourceDispatchBudget)).claim_sequence = 3
    with factory.begin() as session:
        assert (
            claim_due(
                session,
                source,
                "shard",
                limit=70,
                lease=timedelta(minutes=10),
                yuyutei_shard_index=mapping_id % 9,
                clock=lambda: T0,
            )
            == []
        )
    assert claim(factory, source)[0].kind == "discovery"


def test_malformed_scheduler_backup_fails_validation_before_restore(db):
    from app.services.backup import export_backup, restore_backup, validate_backup

    factory, _, _, _ = db
    with factory() as session:
        archive = export_backup(session)
    archive["tables"]["source_dispatch_budgets"][0]["used_requests"] = "unknown"
    validation = validate_backup(archive)
    assert not validation.valid
    assert any("used_requests" in error for error in validation.errors)
    with factory() as session:
        result = restore_backup(session, archive, dry_run=False, skip_lock=True)
        assert not result.valid
        assert session.scalar(select(SourceDispatchBudget.enabled))


def test_raw_and_psa10_can_share_price_type_without_confusing_grade(db):
    from app.services.freshness_queue import PriceCategory

    factory, source, mapping_id, _ = db
    plan(
        factory,
        mapping_id,
        categories={
            "raw": PriceCategory("floor"),
            "psa10": PriceCategory("floor", "PSA10"),
        },
    )
    picked = claim(factory, source)[0]
    admit(factory, picked.claim_token)
    raw_id = snapshot(factory, source, T0)
    raw_obs = observation(factory, mapping_id, raw_id, T0, category="floor")
    psa_obs = observation(
        factory, mapping_id, raw_id, T0, category="floor", condition="PSA10"
    )
    with pytest.raises(ValueError, match="new current product capture"):
        finish(
            factory,
            picked.claim_token,
            T0,
            outcome="captured",
            actual_request_cost=1,
            raw_snapshot_id=raw_id,
            observation_ids={"psa10": raw_obs},
        )
    finish(
        factory,
        picked.claim_token,
        T0,
        outcome="captured",
        actual_request_cost=1,
        raw_snapshot_id=raw_id,
        observation_ids={"raw": raw_obs, "psa10": psa_obs},
    )
    with factory() as session:
        states = session.scalars(select(FreshnessPriceState)).all()
        assert len(states) == 2
        assert {state.next_due_at for state in states} == {T0 + timedelta(hours=23)}
    assert picked.price_categories == ("psa10", "raw")


def test_homepage_capture_cannot_claim_a_product_no_listing_check(db):
    factory, source, mapping_id, _ = db
    plan(factory, mapping_id)
    token = claim(factory, source)[0].claim_token
    admit(factory, token)
    raw_id = snapshot(factory, source, T0)
    with factory.begin() as session:
        session.get(RawSnapshot, raw_id).source_url = "https://snkrdunk.com/"
    with pytest.raises(ValueError, match="planned source product"):
        finish(
            factory,
            token,
            T0,
            outcome="no_listing",
            actual_request_cost=1,
            raw_snapshot_id=raw_id,
            no_listing_categories={"raw"},
        )
    with factory() as session:
        assert (
            session.scalar(select(FreshnessPriceState.last_successfully_checked_at))
            is None
        )


def test_unknown_policy_version_cannot_be_replanned_or_dispatched(db):
    factory, source, mapping_id, _ = db
    work_id = plan(factory, mapping_id)
    with factory.begin() as session:
        session.get(FreshnessWork, work_id).policy_version = "future-unknown"
    with pytest.raises(ValueError, match="unsupported work freshness policy"):
        plan(factory, mapping_id)
    with pytest.raises(ValueError, match="unsupported work freshness policy"):
        claim(factory, source)
    with factory() as session:
        assert session.scalar(select(SourceDispatchBudget.reserved_requests)) == 0
