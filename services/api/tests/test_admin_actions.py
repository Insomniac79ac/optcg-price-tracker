import pytest
from fastapi.testclient import TestClient

import app.api.admin_actions as admin_actions_module
from app.main import app
from app.models import MarketIntelligenceReport, PortfolioValuationSnapshot
from app.services.job_locks import LockHeldError, acquire_lock
from app.settings import settings

ACTION_PATHS = [
    "/admin/actions/refresh-prices",
    "/admin/actions/full-market-refresh",
]


@pytest.fixture()
def raw_client(db_session):
    """A TestClient without the `client` fixture's default X-Admin-Token
    header, so auth tests fully control what (if anything) is sent."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_real_celery(monkeypatch):
    """Every test in this module that reaches the refresh-triggering
    endpoints must go through a monkeypatched trigger_price_refresh - none of
    them should ever attempt a real Celery/Redis round trip."""

    def _unexpected_call(*args, **kwargs):
        raise AssertionError(
            "trigger_price_refresh was called without being monkeypatched in this test"
        )

    monkeypatch.setattr(admin_actions_module, "trigger_price_refresh", _unexpected_call)


# --- Auth -------------------------------------------------------------------


@pytest.mark.parametrize("path", ACTION_PATHS)
def test_admin_action_rejects_missing_token(raw_client, monkeypatch, path):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "secret-token")
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "APP_ENV", None)

    response = raw_client.post(path, json={})

    assert response.status_code == 401


@pytest.mark.parametrize("path", ACTION_PATHS)
def test_admin_action_rejects_invalid_token(raw_client, monkeypatch, path):
    monkeypatch.setattr(settings, "ADMIN_TOKEN", "secret-token")
    monkeypatch.setattr(settings, "ENVIRONMENT", None)
    monkeypatch.setattr(settings, "APP_ENV", None)

    response = raw_client.post(path, json={}, headers={"X-Admin-Token": "wrong-token"})

    assert response.status_code == 401


# --- POST /admin/actions/refresh-prices -------------------------------------


def test_refresh_prices_happy_path(client, monkeypatch):
    captured = {}

    def fake_trigger(source, limit, dry_run):
        captured.update(source=source, limit=limit, dry_run=dry_run)
        return "celery-task-id-123", {
            "id": 42,
            "status": "completed",
            "source_filter": source,
        }

    monkeypatch.setattr(admin_actions_module, "trigger_price_refresh", fake_trigger)

    response = client.post("/admin/actions/refresh-prices", json={"source": "yuyutei"})

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "run_id": 42,
        "job_id": "celery-task-id-123",
        "status": "completed",
        "warnings": [],
    }
    assert captured == {"source": "yuyutei", "limit": 10, "dry_run": False}


def test_refresh_prices_defaults_source_to_all(client, monkeypatch):
    captured = {}

    def fake_trigger(source, limit, dry_run):
        captured.update(source=source, limit=limit, dry_run=dry_run)
        return "job-1", {"id": 1, "status": "completed"}

    monkeypatch.setattr(admin_actions_module, "trigger_price_refresh", fake_trigger)

    response = client.post("/admin/actions/refresh-prices", json={})

    assert response.status_code == 200
    assert captured["source"] == "all"


def test_refresh_prices_rejects_invalid_source(client):
    response = client.post("/admin/actions/refresh-prices", json={"source": "ebay"})

    assert response.status_code == 400


def test_refresh_prices_rejects_non_positive_limit(client):
    response = client.post("/admin/actions/refresh-prices", json={"limit": 0})

    assert response.status_code == 422


def test_refresh_prices_surfaces_trigger_failure_as_502(client, monkeypatch):
    def fake_trigger(source, limit, dry_run):
        raise RuntimeError("broker unreachable")

    monkeypatch.setattr(admin_actions_module, "trigger_price_refresh", fake_trigger)

    response = client.post("/admin/actions/refresh-prices", json={})

    assert response.status_code == 502
    assert "broker unreachable" in response.json()["detail"]


def test_refresh_prices_returns_409_when_lock_held(client, monkeypatch):
    from datetime import datetime, timedelta, timezone

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    def fake_trigger(source, limit, dry_run):
        raise LockHeldError("price_refresh", "price_refresh:other", expires_at)

    monkeypatch.setattr(admin_actions_module, "trigger_price_refresh", fake_trigger)

    response = client.post("/admin/actions/refresh-prices", json={})

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "Job already running"
    assert body["lock_name"] == "price_refresh"
    assert body["expires_at"] == expires_at.isoformat()


# --- POST /admin/actions/full-market-refresh --------------------------------


def test_full_market_refresh_happy_path(client, monkeypatch, db_session):
    monkeypatch.setattr(
        admin_actions_module,
        "trigger_price_refresh",
        lambda source, limit, dry_run: ("job-9", {"id": 7, "status": "completed"}),
    )

    response = client.post("/admin/actions/full-market-refresh", json={"source": "all"})

    assert response.status_code == 200
    body = response.json()
    assert body["price_refresh_run_id"] == 7
    assert body["dry_run"] is False
    assert body["warnings"] == []
    # The legacy collection snapshot was removed (Collector v1 S8).
    assert body["portfolio_snapshot_id"] is None
    assert db_session.query(PortfolioValuationSnapshot).count() == 0
    # The legacy signal/report/digest steps were removed (Collector v1 S1).
    assert "market_report_id" not in body
    assert "market_signal_snapshot" not in body

    assert db_session.query(MarketIntelligenceReport).count() == 0


def test_full_market_refresh_dry_run_skips_snapshot(client, monkeypatch, db_session):
    monkeypatch.setattr(
        admin_actions_module,
        "trigger_price_refresh",
        lambda source, limit, dry_run: ("job-9", {"id": 8, "status": "completed"}),
    )

    response = client.post(
        "/admin/actions/full-market-refresh", json={"source": "all", "dry_run": True}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["price_refresh_run_id"] == 8
    assert body["portfolio_snapshot_id"] is None
    assert body["warnings"] == []


def test_full_market_refresh_warns_on_price_refresh_failure_without_failing_request(
    client, monkeypatch, db_session
):
    monkeypatch.setattr(
        admin_actions_module,
        "trigger_price_refresh",
        lambda source, limit, dry_run: (
            "job-9",
            {"id": 9, "status": "failed", "error_message": "adapter exploded"},
        ),
    )

    response = client.post("/admin/actions/full-market-refresh", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["price_refresh_run_id"] == 9
    assert any("adapter exploded" in w for w in body["warnings"])
    assert body["portfolio_snapshot_id"] is None


def test_full_market_refresh_surfaces_trigger_failure_as_502(client, monkeypatch, db_session):
    def fake_trigger(source, limit, dry_run):
        raise RuntimeError("broker unreachable")

    monkeypatch.setattr(admin_actions_module, "trigger_price_refresh", fake_trigger)

    response = client.post("/admin/actions/full-market-refresh", json={})

    assert response.status_code == 502


def test_full_market_refresh_rejects_invalid_source(client):
    response = client.post("/admin/actions/full-market-refresh", json={"source": "ebay"})

    assert response.status_code == 400


def test_full_market_refresh_returns_409_when_market_workflow_lock_held(client, db_session):
    # full_market_refresh_action acquires the real 'market_workflow' lock
    # itself (unlike refresh-prices, which learns about a conflict via the
    # worker's Celery result) - pre-acquire it directly
    # rather than mocking trigger_price_refresh, so this exercises the
    # endpoint's own with_job_lock(...) wrapper.
    acquire_lock("market_workflow", "market_workflow:other", 3600)

    response = client.post("/admin/actions/full-market-refresh", json={})

    assert response.status_code == 409
    body = response.json()
    assert body["detail"] == "Job already running"
    assert body["lock_name"] == "market_workflow"
