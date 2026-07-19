"""GET /admin/data-retention/policy, POST /admin/data-retention/prune, and
app.services.data_retention - see that module's docstring for the full
retention policy."""

from datetime import datetime, timedelta, timezone

from app.models import (
    AppLogEvent,
    Card,
    CollectorActivityEvent,
    MarketSignalEvent,
    PortfolioValuationSnapshot,
    PriceObservation,
    RawSnapshot,
    Source,
)
from app.services.data_retention import PRUNABLE_TABLES, prune_tables
from app.services.job_locks import acquire_lock

NOW = datetime.now(timezone.utc)


def make_card(db_session, **overrides) -> Card:
    fields = dict(card_code="OP01-001", set_code="OP01", rarity="L", language="en")
    fields.update(overrides)
    card = Card(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_source(db_session, name: str = "yuyutei") -> Source:
    source = Source(name=name, base_url=f"https://{name}.example.com")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


# --- policy endpoint ---------------------------------------------------------


def test_policy_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain_client = TestClient(app)
    response = plain_client.get("/admin/data-retention/policy")
    assert response.status_code == 401


def test_policy_returns_policies(client, db_session):
    response = client.get("/admin/data-retention/policy")

    assert response.status_code == 200
    data = response.json()
    tables = {p["table"] for p in data["policies"]}
    # file_jobs is an informational-only entry (see 'Large import/export
    # jobs' in docs/operations.md) - its actual cleanup mechanism is POST
    # /admin/file-jobs/cleanup, not the generic prune_tables() engine, so it
    # isn't in PRUNABLE_TABLES.
    assert tables == set(PRUNABLE_TABLES) | {"file_jobs"}

    never_pruned = {
        "cards",
        "sources",
        "source_card_mappings",
        "collection_items",
        "wishlist_items",
        "grading_submissions",
        "collector_tags",
        "collector_groups",
        "collector_notes",
        "alert_rules",
        "dashboard_preferences",
    }
    assert tables.isdisjoint(never_pruned)

    raw_snapshots_policy = next(p for p in data["policies"] if p["table"] == "raw_snapshots")
    assert raw_snapshots_policy["retention_days"] == 30
    assert raw_snapshots_policy["enabled"] is True


# --- prune endpoint: dry-run / confirm gating -------------------------------


def test_prune_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    plain_client = TestClient(app)
    response = plain_client.post("/admin/data-retention/prune", json={"dry_run": True})
    assert response.status_code == 401


def test_prune_dry_run_does_not_delete(client, db_session):
    source = make_source(db_session)
    db_session.add(
        RawSnapshot(
            source_id=source.id,
            source_url="https://example.com/1",
            fetched_at=NOW - timedelta(days=100),
            http_status=200,
            content_hash="abc",
            raw_content="<html></html>",
        )
    )
    db_session.commit()

    response = client.post(
        "/admin/data-retention/prune",
        json={"dry_run": True, "tables": ["raw_snapshots"]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    result = data["results"][0]
    assert result["rows_would_delete"] == 1
    assert result["rows_deleted"] == 0

    assert db_session.query(RawSnapshot).count() == 1


def test_prune_returns_409_when_lock_held(client, db_session):
    acquire_lock("data_retention_prune", "data_retention_prune:other", 1800)

    response = client.post(
        "/admin/data-retention/prune",
        json={"dry_run": True, "tables": ["raw_snapshots"]},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "Job already running"
    assert body["lock_name"] == "data_retention_prune"


def test_prune_apply_requires_confirm(client, db_session):
    response = client.post(
        "/admin/data-retention/prune",
        json={"dry_run": False, "tables": ["raw_snapshots"]},
    )
    assert response.status_code == 400


def test_prune_apply_with_wrong_confirm_rejected(client, db_session):
    response = client.post(
        "/admin/data-retention/prune",
        json={"dry_run": False, "tables": ["raw_snapshots"], "confirm": "wrong"},
    )
    assert response.status_code == 400


def test_prune_apply_with_confirm_deletes(client, db_session):
    source = make_source(db_session)
    db_session.add(
        RawSnapshot(
            source_id=source.id,
            source_url="https://example.com/1",
            fetched_at=NOW - timedelta(days=100),
            http_status=200,
            content_hash="abc",
            raw_content="<html></html>",
        )
    )
    db_session.commit()

    response = client.post(
        "/admin/data-retention/prune",
        json={"dry_run": False, "tables": ["raw_snapshots"], "confirm": "PRUNE"},
    )

    assert response.status_code == 200
    data = response.json()
    result = data["results"][0]
    assert result["rows_deleted"] == 1
    assert db_session.query(RawSnapshot).count() == 0


def test_protected_tables_cannot_be_pruned(client, db_session):
    response = client.post(
        "/admin/data-retention/prune",
        json={"dry_run": True, "tables": ["cards", "collection_items"]},
    )

    assert response.status_code == 200
    data = response.json()
    for result in data["results"]:
        assert result["status"] == "skipped"
        assert result["rows_would_delete"] == 0


def test_omitted_tables_evaluates_all_prunable_tables(client, db_session):
    response = client.post("/admin/data-retention/prune", json={"dry_run": True})

    assert response.status_code == 200
    data = response.json()
    tables = {r["table"] for r in data["results"]}
    assert tables == set(PRUNABLE_TABLES)
    assert data["summary"]["tables_checked"] == len(PRUNABLE_TABLES)


# --- raw_snapshots / app_log_events counting and deletion -------------------


def test_raw_snapshots_old_rows_counted_and_deleted(db_session):
    source = make_source(db_session)
    db_session.add_all(
        [
            RawSnapshot(
                source_id=source.id,
                source_url="https://example.com/old",
                fetched_at=NOW - timedelta(days=31),
                http_status=200,
                content_hash="old",
                raw_content="<html></html>",
            ),
            RawSnapshot(
                source_id=source.id,
                source_url="https://example.com/new",
                fetched_at=NOW - timedelta(days=1),
                http_status=200,
                content_hash="new",
                raw_content="<html></html>",
            ),
        ]
    )
    db_session.commit()

    dry_run_result = prune_tables(db_session, dry_run=True, tables=["raw_snapshots"], now=NOW)
    assert dry_run_result.results[0].rows_would_delete == 1
    assert db_session.query(RawSnapshot).count() == 2

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["raw_snapshots"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 1
    remaining = db_session.query(RawSnapshot).all()
    assert len(remaining) == 1
    assert remaining[0].content_hash == "new"


def test_app_log_events_old_rows_counted_and_deleted(db_session):
    db_session.add_all(
        [
            AppLogEvent(
                created_at=NOW - timedelta(days=61),
                level="info",
                service="api",
                event_type="test",
                message="old info",
            ),
            AppLogEvent(
                created_at=NOW - timedelta(days=1),
                level="info",
                service="api",
                event_type="test",
                message="new info",
            ),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["app_log_events"], now=NOW)
    assert result.results[0].rows_would_delete == 1


def test_app_log_events_keeps_critical_logs_for_180_days(db_session):
    db_session.add_all(
        [
            AppLogEvent(
                created_at=NOW - timedelta(days=90),  # older than 60d default, within 180d
                level="critical",
                service="api",
                event_type="test",
                message="critical but recent-ish",
            ),
            AppLogEvent(
                created_at=NOW - timedelta(days=200),  # older than 180d
                level="error",
                service="api",
                event_type="test",
                message="error, truly old",
            ),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["app_log_events"], now=NOW)
    assert result.results[0].rows_would_delete == 1  # only the 200-day-old error row

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["app_log_events"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 1
    # Not an exact count: prune_tables acquires/releases the
    # data_retention_prune job lock around each call above, and those
    # acquire/release events are themselves logged to app_log_events (see
    # app.services.job_locks) - freshly created, so they're never pruned by
    # this 180-day-old cutoff and legitimately show up alongside the row
    # this test actually cares about.
    remaining_messages = {log.message for log in db_session.query(AppLogEvent).all()}
    assert "critical but recent-ish" in remaining_messages
    assert "error, truly old" not in remaining_messages


# --- price_observations: latest-per-series protection -----------------------


def test_latest_price_observation_is_protected(db_session):
    card = make_card(db_session)
    source = make_source(db_session)

    db_session.add_all(
        [
            PriceObservation(
                card_id=card.id,
                source_id=source.id,
                price_type="sell",
                price_jpy=100,
                observed_at=NOW - timedelta(days=500),  # only observation ever - must survive
            ),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["price_observations"], now=NOW)
    assert result.results[0].rows_would_delete == 0
    assert db_session.query(PriceObservation).count() == 1


def test_old_non_latest_price_observation_is_pruned(db_session):
    card = make_card(db_session)
    source = make_source(db_session)

    db_session.add_all(
        [
            PriceObservation(
                card_id=card.id,
                source_id=source.id,
                price_type="sell",
                price_jpy=100,
                observed_at=NOW - timedelta(days=500),  # old, NOT latest -> prunable
            ),
            PriceObservation(
                card_id=card.id,
                source_id=source.id,
                price_type="sell",
                price_jpy=150,
                observed_at=NOW - timedelta(days=1),  # latest -> protected
            ),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["price_observations"], now=NOW)
    assert result.results[0].rows_would_delete == 1

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 1
    remaining = db_session.query(PriceObservation).all()
    assert len(remaining) == 1
    assert remaining[0].price_jpy == 150


def test_price_observations_thinning_keeps_one_per_day_when_old(db_session):
    card = make_card(db_session)
    source = make_source(db_session)

    # Anchored to midnight UTC (not NOW's own time-of-day) so the +8h offset
    # below can never roll past midnight into the next calendar day - this
    # test's "three same-day rows" premise would otherwise be time-of-day
    # dependent (flaky depending on what time of day the suite happens to
    # run).
    base_day = (NOW - timedelta(days=200)).replace(hour=0, minute=0, second=0, microsecond=0)
    # Three observations on the same day, all older than the 90-day fresh
    # window and younger than the 365-day hard cutoff - thinning should keep
    # only one of these three. Plus one recent, definitely-latest row.
    db_session.add_all(
        [
            PriceObservation(
                card_id=card.id, source_id=source.id, price_type="sell", price_jpy=100,
                observed_at=base_day,
            ),
            PriceObservation(
                card_id=card.id, source_id=source.id, price_type="sell", price_jpy=110,
                observed_at=base_day + timedelta(hours=4),
            ),
            PriceObservation(
                card_id=card.id, source_id=source.id, price_type="sell", price_jpy=120,
                observed_at=base_day + timedelta(hours=8),
            ),
            PriceObservation(
                card_id=card.id, source_id=source.id, price_type="sell", price_jpy=999,
                observed_at=NOW - timedelta(days=1),
            ),
        ]
    )
    db_session.commit()

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["price_observations"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 2  # 3 same-day rows thinned to 1

    remaining = db_session.query(PriceObservation).order_by(PriceObservation.observed_at).all()
    assert len(remaining) == 2
    assert remaining[0].price_jpy == 100  # earliest of the day kept
    assert remaining[1].price_jpy == 999  # latest row, always kept


def test_price_observations_within_fresh_window_not_thinned(db_session):
    card = make_card(db_session)
    source = make_source(db_session)

    base_day = NOW - timedelta(days=10)  # within the 90-day fresh window
    db_session.add_all(
        [
            PriceObservation(
                card_id=card.id, source_id=source.id, price_type="sell", price_jpy=100,
                observed_at=base_day,
            ),
            PriceObservation(
                card_id=card.id, source_id=source.id, price_type="sell", price_jpy=110,
                observed_at=base_day + timedelta(hours=4),
            ),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["price_observations"], now=NOW)
    assert result.results[0].rows_would_delete == 0
    assert db_session.query(PriceObservation).count() == 2


# --- portfolio_valuation_snapshots: weekly thinning -------------------------


def test_portfolio_valuation_snapshots_thinning_keeps_one_per_week_when_old(db_session):
    base = NOW - timedelta(days=200)
    db_session.add_all(
        [
            PortfolioValuationSnapshot(
                created_at=base,
                total_items=1, total_quantity=1,
                items_missing_yuyutei_sell=0, items_missing_yuyutei_buy=0,
                items_missing_snkrdunk_floor=0, items_missing_cost_basis=0,
                cards_above_target_sell=0,
            ),
            PortfolioValuationSnapshot(
                created_at=base + timedelta(days=1),
                total_items=1, total_quantity=1,
                items_missing_yuyutei_sell=0, items_missing_yuyutei_buy=0,
                items_missing_snkrdunk_floor=0, items_missing_cost_basis=0,
                cards_above_target_sell=0,
            ),
            PortfolioValuationSnapshot(
                created_at=NOW - timedelta(days=1),
                total_items=1, total_quantity=1,
                items_missing_yuyutei_sell=0, items_missing_yuyutei_buy=0,
                items_missing_snkrdunk_floor=0, items_missing_cost_basis=0,
                cards_above_target_sell=0,
            ),
        ]
    )
    db_session.commit()

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["portfolio_valuation_snapshots"], confirm="PRUNE", now=NOW
    )
    # The two same-week old snapshots thin to 1; the recent one is untouched.
    assert apply_result.results[0].rows_deleted == 1
    assert db_session.query(PortfolioValuationSnapshot).count() == 2


# --- market_signal_events: open/watching protected, old dismissed pruned ---


def test_open_and_watching_signal_events_are_protected(db_session):
    old = NOW - timedelta(days=500)
    db_session.add_all(
        [
            MarketSignalEvent(
                signal_type="price_up_7d", dedupe_key="a", status="open",
                first_seen_at=old, last_seen_at=old,
            ),
            MarketSignalEvent(
                signal_type="price_up_7d", dedupe_key="b", status="watching",
                first_seen_at=old, last_seen_at=old,
            ),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["market_signal_events"], now=NOW)
    assert result.results[0].rows_would_delete == 0


def test_old_dismissed_and_resolved_signal_events_are_pruned(db_session):
    old = NOW - timedelta(days=400)
    recent = NOW - timedelta(days=10)
    db_session.add_all(
        [
            MarketSignalEvent(
                signal_type="price_up_7d", dedupe_key="old-dismissed", status="dismissed",
                first_seen_at=old, last_seen_at=old,
            ),
            MarketSignalEvent(
                signal_type="price_up_7d", dedupe_key="old-resolved", status="resolved",
                first_seen_at=old, last_seen_at=old,
            ),
            MarketSignalEvent(
                signal_type="price_up_7d", dedupe_key="recent-dismissed", status="dismissed",
                first_seen_at=recent, last_seen_at=recent,
            ),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["market_signal_events"], now=NOW)
    assert result.results[0].rows_would_delete == 2

    apply_result = prune_tables(
        db_session, dry_run=False, tables=["market_signal_events"], confirm="PRUNE", now=NOW
    )
    assert apply_result.results[0].rows_deleted == 2
    remaining = db_session.query(MarketSignalEvent).all()
    assert len(remaining) == 1
    assert remaining[0].dedupe_key == "recent-dismissed"


# --- collector_activity_events (simple cutoff table, sanity check) ---------


def test_collector_activity_events_old_rows_pruned(db_session):
    db_session.add_all(
        [
            CollectorActivityEvent(
                event_type="note_created", event_source="note",
                title="old", created_at=NOW - timedelta(days=400),
            ),
            CollectorActivityEvent(
                event_type="note_created", event_source="note",
                title="new", created_at=NOW - timedelta(days=1),
            ),
        ]
    )
    db_session.commit()

    result = prune_tables(db_session, dry_run=True, tables=["collector_activity_events"], now=NOW)
    assert result.results[0].rows_would_delete == 1
