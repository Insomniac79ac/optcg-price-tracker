import pytest
from fastapi.testclient import TestClient

import app.api.admin_actions as admin_actions_module
from app.main import app
from app.models import MarketIntelligenceReport, PortfolioValuationSnapshot
from app.settings import settings

ACTION_PATHS = [
    "/admin/actions/refresh-prices",
    "/admin/actions/snapshot-portfolio",
    "/admin/actions/snapshot-market-signals",
    "/admin/actions/generate-market-report",
    "/admin/actions/full-market-refresh",
    "/admin/actions/send-market-report-digest",
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


# --- POST /admin/actions/snapshot-portfolio ---------------------------------


def test_snapshot_portfolio_creates_a_snapshot(client, db_session):
    response = client.post("/admin/actions/snapshot-portfolio")

    assert response.status_code == 200
    snapshot_id = response.json()["snapshot_id"]
    assert db_session.get(PortfolioValuationSnapshot, snapshot_id) is not None


# --- POST /admin/actions/snapshot-market-signals ----------------------------


def test_snapshot_market_signals_on_empty_db(client, db_session):
    response = client.post("/admin/actions/snapshot-market-signals")

    assert response.status_code == 200
    assert response.json() == {"created_count": 0, "updated_count": 0, "resolved_count": 0}


# --- POST /admin/actions/generate-market-report -----------------------------


def test_generate_market_report_creates_a_report(client, db_session):
    response = client.post("/admin/actions/generate-market-report")

    assert response.status_code == 200
    report_id = response.json()["report_id"]
    assert db_session.get(MarketIntelligenceReport, report_id) is not None


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
    assert body["portfolio_snapshot_id"] is not None
    assert body["market_report_id"] is not None
    assert body["market_signal_snapshot"] == {"created": 0, "updated": 0, "resolved": 0}

    assert db_session.get(PortfolioValuationSnapshot, body["portfolio_snapshot_id"]) is not None
    assert db_session.get(MarketIntelligenceReport, body["market_report_id"]) is not None


def test_full_market_refresh_dry_run_skips_snapshots_and_report(client, monkeypatch, db_session):
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
    assert body["market_report_id"] is None
    assert body["market_signal_snapshot"] == {"created": 0, "updated": 0, "resolved": 0}
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
    # Steps 2-4 still run even though the refresh itself failed.
    assert body["portfolio_snapshot_id"] is not None
    assert body["market_report_id"] is not None


def test_full_market_refresh_reports_partial_failure_as_warning(client, monkeypatch, db_session):
    monkeypatch.setattr(
        admin_actions_module,
        "trigger_price_refresh",
        lambda source, limit, dry_run: ("job-9", {"id": 10, "status": "completed"}),
    )

    def failing_snapshot(db):
        raise RuntimeError("disk full")

    monkeypatch.setattr(admin_actions_module, "snapshot_portfolio_valuation", failing_snapshot)

    response = client.post("/admin/actions/full-market-refresh", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["portfolio_snapshot_id"] is None
    assert any("disk full" in w for w in body["warnings"])
    # The other two steps still complete despite the portfolio snapshot failing.
    assert body["market_report_id"] is not None


def test_full_market_refresh_surfaces_trigger_failure_as_502(client, monkeypatch):
    def fake_trigger(source, limit, dry_run):
        raise RuntimeError("broker unreachable")

    monkeypatch.setattr(admin_actions_module, "trigger_price_refresh", fake_trigger)

    response = client.post("/admin/actions/full-market-refresh", json={})

    assert response.status_code == 502


def test_full_market_refresh_does_not_fail_when_digest_fails(client, monkeypatch, db_session):
    monkeypatch.setattr(
        admin_actions_module,
        "trigger_price_refresh",
        lambda source, limit, dry_run: ("job-9", {"id": 11, "status": "completed"}),
    )

    def failing_digest(db, dry_run=False, force=False):
        raise RuntimeError("telegram api down")

    monkeypatch.setattr(admin_actions_module, "send_market_report_digest", failing_digest)

    response = client.post("/admin/actions/full-market-refresh", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["market_report_id"] is not None
    assert any("telegram api down" in w for w in body["warnings"])


def test_full_market_refresh_dry_run_never_sends_digest(client, monkeypatch, db_session):
    monkeypatch.setattr(
        admin_actions_module,
        "trigger_price_refresh",
        lambda source, limit, dry_run: ("job-9", {"id": 12, "status": "completed"}),
    )

    def _unexpected_digest_call(*args, **kwargs):
        raise AssertionError("send_market_report_digest must not be called on a dry run")

    monkeypatch.setattr(admin_actions_module, "send_market_report_digest", _unexpected_digest_call)

    response = client.post(
        "/admin/actions/full-market-refresh", json={"source": "all", "dry_run": True}
    )

    assert response.status_code == 200
    assert response.json()["dry_run"] is True


# --- POST /admin/actions/send-market-report-digest ---------------------------


def test_send_market_report_digest_no_report_found(client, db_session):
    response = client.post("/admin/actions/send-market-report-digest", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["report_id"] is None
    assert body["sent"] is False
    assert body["skipped_reason"] == "No market report found."


def test_send_market_report_digest_dry_run(client, monkeypatch, db_session):
    from app.services.market_report import generate_market_report

    generate_market_report(db_session)

    response = client.post(
        "/admin/actions/send-market-report-digest", json={"dry_run": True}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["sent"] is False
    assert "OPCG Market Report" in body["message_preview"]


def test_send_market_report_digest_skipped_without_telegram_config(client, db_session):
    from app.services.market_report import generate_market_report

    generate_market_report(db_session)

    response = client.post("/admin/actions/send-market-report-digest", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "skipped"
    assert body["sent"] is False
    assert "not configured" in body["skipped_reason"]


def test_send_market_report_digest_sends_when_configured(client, monkeypatch, db_session):
    from app.services.market_report import generate_market_report
    from app.settings import settings

    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setattr(
        "app.services.telegram_market_digest.send_telegram_message", lambda text: None
    )
    generate_market_report(db_session)

    response = client.post("/admin/actions/send-market-report-digest", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sent"
    assert body["sent"] is True

    second = client.post("/admin/actions/send-market-report-digest", json={})
    assert second.json()["status"] == "skipped"

    forced = client.post(
        "/admin/actions/send-market-report-digest", json={"force": True}
    )
    assert forced.json()["status"] == "sent"


def test_full_market_refresh_rejects_invalid_source(client):
    response = client.post("/admin/actions/full-market-refresh", json={"source": "ebay"})

    assert response.status_code == 400
