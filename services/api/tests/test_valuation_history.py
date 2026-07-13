from datetime import datetime, timedelta, timezone

from app.models import PortfolioValuationSnapshot


def make_snapshot(db_session, **overrides) -> PortfolioValuationSnapshot:
    fields = dict(
        total_items=1,
        total_quantity=1,
        total_cost_basis_jpy=1000,
        retail_value_jpy=1200,
        liquidation_value_jpy=900,
        market_floor_value_jpy=1150,
        pnl_vs_retail_jpy=200,
        pnl_vs_liquidation_jpy=-100,
        pnl_vs_market_floor_jpy=150,
        items_missing_yuyutei_sell=0,
        items_missing_yuyutei_buy=0,
        items_missing_snkrdunk_floor=1,
        items_missing_cost_basis=0,
        cards_above_target_sell=1,
        graded_adjusted_value_jpy=1300,
        pnl_vs_graded_adjusted_jpy=300,
        items_using_graded_value=1,
        items_using_raw_fallback=0,
        items_missing_graded_adjusted_value=0,
    )
    fields.update(overrides)
    snapshot = PortfolioValuationSnapshot(**fields)
    db_session.add(snapshot)
    db_session.commit()
    db_session.refresh(snapshot)
    return snapshot


def test_history_empty_returns_empty_list(client, db_session):
    response = client.get("/collection/valuation/history")

    assert response.status_code == 200
    assert response.json() == []


def test_history_returns_snapshots(client, db_session):
    snapshot = make_snapshot(db_session)

    response = client.get("/collection/valuation/history")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == snapshot.id
    assert body[0]["total_items"] == 1
    assert body[0]["total_quantity"] == 1
    assert body[0]["total_cost_basis_jpy"] == 1000
    assert body[0]["retail_value_jpy"] == 1200
    assert body[0]["liquidation_value_jpy"] == 900
    assert body[0]["market_floor_value_jpy"] == 1150
    assert body[0]["pnl_vs_retail_jpy"] == 200
    assert body[0]["pnl_vs_liquidation_jpy"] == -100
    assert body[0]["pnl_vs_market_floor_jpy"] == 150
    assert body[0]["items_missing_snkrdunk_floor"] == 1
    assert body[0]["cards_above_target_sell"] == 1
    assert "created_at" in body[0]


def test_history_returns_graded_adjusted_fields(client, db_session):
    snapshot = make_snapshot(
        db_session,
        graded_adjusted_value_jpy=1300,
        pnl_vs_graded_adjusted_jpy=300,
        items_using_graded_value=1,
        items_using_raw_fallback=0,
        items_missing_graded_adjusted_value=0,
    )

    response = client.get("/collection/valuation/history")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == snapshot.id
    assert body[0]["graded_adjusted_value_jpy"] == 1300
    assert body[0]["pnl_vs_graded_adjusted_jpy"] == 300
    assert body[0]["items_using_graded_value"] == 1
    assert body[0]["items_using_raw_fallback"] == 0
    assert body[0]["items_missing_graded_adjusted_value"] == 0


def test_history_days_filter_excludes_old_snapshots(client, db_session):
    now = datetime.now(timezone.utc)
    old = make_snapshot(db_session, created_at=now - timedelta(days=10))
    recent = make_snapshot(db_session, created_at=now - timedelta(days=1))

    response = client.get("/collection/valuation/history", params={"days": 7})

    assert response.status_code == 200
    ids = [row["id"] for row in response.json()]
    assert recent.id in ids
    assert old.id not in ids


def test_history_days_30_default(client, db_session):
    now = datetime.now(timezone.utc)
    old = make_snapshot(db_session, created_at=now - timedelta(days=60))
    recent = make_snapshot(db_session, created_at=now - timedelta(days=5))

    response = client.get("/collection/valuation/history", params={"days": 30})

    assert response.status_code == 200
    ids = [row["id"] for row in response.json()]
    assert recent.id in ids
    assert old.id not in ids


def test_history_days_90(client, db_session):
    now = datetime.now(timezone.utc)
    within_90 = make_snapshot(db_session, created_at=now - timedelta(days=80))
    beyond_90 = make_snapshot(db_session, created_at=now - timedelta(days=100))

    response = client.get("/collection/valuation/history", params={"days": 90})

    assert response.status_code == 200
    ids = [row["id"] for row in response.json()]
    assert within_90.id in ids
    assert beyond_90.id not in ids


def test_history_days_all_returns_everything(client, db_session):
    now = datetime.now(timezone.utc)
    old = make_snapshot(db_session, created_at=now - timedelta(days=400))
    recent = make_snapshot(db_session, created_at=now)

    response = client.get("/collection/valuation/history", params={"days": "all"})

    assert response.status_code == 200
    ids = [row["id"] for row in response.json()]
    assert old.id in ids
    assert recent.id in ids


def test_history_invalid_days_returns_400(client, db_session):
    response = client.get("/collection/valuation/history", params={"days": "bogus"})

    assert response.status_code == 400


def test_history_limit_caps_results(client, db_session):
    for _ in range(5):
        make_snapshot(db_session)

    response = client.get("/collection/valuation/history", params={"limit": 2})

    assert response.status_code == 200
    assert len(response.json()) == 2
