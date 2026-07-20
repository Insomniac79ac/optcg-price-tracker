import sys

import pytest

import app.api.admin_actions as admin_actions_module
from app.generate_analytics_digest import main as cli_main
from app.models import AnalyticsDigestReport, Card, CollectionItem, GradingSubmission, PriceObservation, Source
from app.services import cache as cache_module
from app.services.analytics_digest import generate_analytics_digest
from app.services.backup import export_backup
from app.services.collection_analytics import get_collection_analytics
from app.settings import settings

TEST_USER_ID = 1


@pytest.fixture(autouse=True)
def _cache_memory_backend(monkeypatch):
    """conftest's _cache_disabled_by_default turns caching off for every
    other test - this file explicitly re-enables it (memory backend, so no
    real Redis is needed) to exercise the endpoint's real cache behavior."""
    monkeypatch.setattr(settings, "CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "CACHE_BACKEND", "memory")
    cache_module.reset_state_for_tests()
    yield
    cache_module.reset_state_for_tests()


def make_card(db_session, **overrides) -> Card:
    fields = dict(
        card_code="OP01-001", name_en="Monkey D. Luffy", name_jp="モンキー・D・ルフィ",
        set_code="OP01", rarity="L", variant="leader", language="en",
    )
    fields.update(overrides)
    card = Card(**fields)
    db_session.add(card)
    db_session.commit()
    db_session.refresh(card)
    return card


def make_item(db_session, card: Card, **overrides) -> CollectionItem:
    fields = dict(card_id=card.id, quantity=1, user_id=TEST_USER_ID)
    fields.update(overrides)
    item = CollectionItem(**fields)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


def make_source(db_session, name: str) -> Source:
    existing = db_session.query(Source).filter_by(name=name).one_or_none()
    if existing is not None:
        return existing
    source = Source(name=name, base_url=f"https://{name}.example.com")
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)
    return source


def add_observation(db_session, card, source, *, price_type, price_jpy, **kwargs):
    from datetime import datetime, timezone

    obs = PriceObservation(
        card_id=card.id, source_id=source.id, price_type=price_type, price_jpy=price_jpy,
        observed_at=kwargs.pop("observed_at", None) or datetime.now(timezone.utc), **kwargs,
    )
    db_session.add(obs)
    db_session.commit()
    return obs


def make_submission(db_session, item: CollectionItem, **overrides) -> GradingSubmission:
    fields = dict(collection_item_id=item.id, grading_company="PSA", submission_status="planned")
    fields.update(overrides)
    submission = GradingSubmission(**fields)
    db_session.add(submission)
    db_session.commit()
    db_session.refresh(submission)
    return submission


def _seed_basic_collection(db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session, card_code="OP01-001")
    add_observation(db_session, card, snkrdunk, price_type="floor", price_jpy=1000)
    make_item(db_session, card, purchase_price_jpy=500)
    return card


# --- GET /analytics/digest ---------------------------------------------------


def test_digest_works_with_empty_data(client, db_session):
    response = client.get("/analytics/digest")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["portfolio_risk_score"] == 0
    assert body["summary"]["portfolio_risk_level"] == "low"
    assert body["summary"]["collection_value_jpy"] == 0
    assert body["summary"]["wishlist_target_hits"] == 0
    assert body["summary"]["buy_review_count"] == 0
    assert body["summary"]["sell_review_count"] == 0
    for key in ("collection", "wishlist", "buy_decisions", "sell_decisions", "grading", "portfolio_risk"):
        assert key in body["sections"]
    for key in (
        "top_buy_decisions", "top_sell_decisions", "top_risk_flags",
        "wishlist_target_hits", "grading_overdue", "missing_data",
    ):
        assert body["priority_items"][key] == []
    assert body["deterministic_summary_lines"] == [
        "Portfolio risk level: low.",
        "No urgent buy, sell, grading, or data quality items to review.",
    ]


def test_digest_uses_existing_services(client, db_session):
    _seed_basic_collection(db_session)

    response = client.get("/analytics/digest")

    assert response.status_code == 200
    body = response.json()

    direct_collection = get_collection_analytics(db_session, user_id=TEST_USER_ID)
    assert body["sections"]["collection"]["total_items"] == direct_collection.summary.total_items
    assert (
        body["sections"]["collection"]["raw_market_value_jpy"]
        == direct_collection.summary.raw_market_floor_value_jpy
    )
    assert body["summary"]["collection_value_jpy"] == direct_collection.summary.raw_market_floor_value_jpy


def test_deterministic_summary_lines_reflect_real_data(client, db_session):
    card = _seed_basic_collection(db_session)
    item = db_session.query(CollectionItem).filter_by(card_id=card.id).one()
    make_submission(db_session, item, submission_status="submitted")

    response = client.get("/analytics/digest")

    body = response.json()
    assert any("grading" in line.lower() and "active" in line.lower() for line in body["deterministic_summary_lines"])
    assert body["deterministic_summary_lines"][0] == f"Portfolio risk level: {body['summary']['portfolio_risk_level']}."


# --- GET /analytics/digest/latest, /reports, /reports/{id} ------------------


def test_latest_digest_endpoint_returns_404_when_none_exist(client, db_session):
    response = client.get("/analytics/digest/latest")
    assert response.status_code == 404


def test_latest_digest_endpoint_works(client, db_session):
    generate_analytics_digest(db_session, valuation_mode="raw_market")
    generate_analytics_digest(db_session, valuation_mode="graded_adjusted")

    response = client.get("/analytics/digest/latest")
    assert response.status_code == 200
    assert response.json()["valuation_mode"] == "graded_adjusted"

    scoped_response = client.get("/analytics/digest/latest", params={"valuation_mode": "raw_market"})
    assert scoped_response.status_code == 200
    assert scoped_response.json()["valuation_mode"] == "raw_market"


def test_digest_reports_list_works(client, db_session):
    generate_analytics_digest(db_session)
    generate_analytics_digest(db_session)

    response = client.get("/analytics/digest/reports")

    assert response.status_code == 200
    body = response.json()
    assert body["pagination"]["total"] == 2
    assert len(body["reports"]) == 2
    assert body["reports"][0]["id"] > body["reports"][1]["id"]


def test_digest_report_detail_works(client, db_session):
    report = generate_analytics_digest(db_session)

    response = client.get(f"/analytics/digest/reports/{report.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == report.id
    assert body["summary"]["valuation_mode"] == "raw_market"
    assert "sections" in body and "priority_items" in body


def test_digest_report_detail_404_for_missing_report(client, db_session):
    response = client.get("/analytics/digest/reports/999999")
    assert response.status_code == 404


# --- CLI ----------------------------------------------------------------


def test_cli_creates_digest_row(db_session, monkeypatch, capsys):
    make_card(db_session)
    monkeypatch.setattr("app.generate_analytics_digest.SessionLocal", lambda: db_session)
    monkeypatch.setattr(sys, "argv", ["generate_analytics_digest", "--valuation-mode", "raw_market"])

    cli_main()

    assert db_session.query(AnalyticsDigestReport).count() == 1
    out = capsys.readouterr().out
    assert "report_id:" in out
    assert "valuation_mode: raw_market" in out
    assert "buy_review_count:" in out
    assert "sell_review_count:" in out


# --- POST /admin/actions/generate-analytics-digest ---------------------------


def test_admin_generate_digest_requires_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    raw_client = TestClient(app)
    response = raw_client.post("/admin/actions/generate-analytics-digest", json={})
    assert response.status_code == 401


def test_admin_generate_digest_creates_a_report(client, db_session):
    _seed_basic_collection(db_session)

    response = client.post(
        "/admin/actions/generate-analytics-digest", json={"valuation_mode": "raw_market"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valuation_mode"] == "raw_market"
    assert "report_id" in body
    assert "portfolio_risk_score" in body
    assert "buy_review_count" in body
    assert "sell_review_count" in body
    assert db_session.get(AnalyticsDigestReport, body["report_id"]) is not None


# --- Worker integration: best-effort digest after market workflow -----------


def test_market_workflow_creates_digest_after_successful_non_dry_run(client, monkeypatch, db_session):
    make_card(db_session)
    monkeypatch.setattr(
        admin_actions_module,
        "trigger_market_workflow",
        lambda source, limit, send_telegram, dry_run: (
            "job-1",
            {
                "market_workflow_run_id": 1,
                "status": "success",
                "price_refresh_run_id": 10,
                "portfolio_snapshot_id": 20,
                "signal_events_created": 0,
                "signal_events_updated": 0,
                "signal_events_resolved": 0,
                "market_report_id": 30,
                "telegram_digest_status": None,
                "warnings": [],
            },
        ),
    )

    assert db_session.query(AnalyticsDigestReport).count() == 0

    response = client.post("/admin/actions/run-market-workflow", json={"source": "yuyutei"})

    assert response.status_code == 200
    assert response.json()["warnings"] == []
    assert db_session.query(AnalyticsDigestReport).count() == 1


def test_dry_run_market_workflow_does_not_create_digest(client, monkeypatch, db_session):
    monkeypatch.setattr(
        admin_actions_module,
        "trigger_market_workflow",
        lambda source, limit, send_telegram, dry_run: (
            "job-1",
            {
                "market_workflow_run_id": None,
                "status": "success",
                "price_refresh_run_id": 10,
                "portfolio_snapshot_id": None,
                "signal_events_created": 0,
                "signal_events_updated": 0,
                "signal_events_resolved": 0,
                "market_report_id": None,
                "telegram_digest_status": None,
                "warnings": [],
            },
        ),
    )

    response = client.post(
        "/admin/actions/run-market-workflow", json={"source": "yuyutei", "dry_run": True}
    )

    assert response.status_code == 200
    assert db_session.query(AnalyticsDigestReport).count() == 0


def test_full_market_refresh_creates_digest_after_successful_non_dry_run(
    client, monkeypatch, db_session
):
    make_card(db_session)
    monkeypatch.setattr(
        admin_actions_module,
        "trigger_price_refresh",
        lambda source, limit, dry_run: ("job-9", {"id": 7, "status": "completed"}),
    )

    response = client.post("/admin/actions/full-market-refresh", json={"source": "all"})

    assert response.status_code == 200
    assert db_session.query(AnalyticsDigestReport).count() == 1


def test_full_market_refresh_dry_run_does_not_create_digest(client, monkeypatch, db_session):
    monkeypatch.setattr(
        admin_actions_module,
        "trigger_price_refresh",
        lambda source, limit, dry_run: ("job-9", {"id": 8, "status": "completed"}),
    )

    response = client.post(
        "/admin/actions/full-market-refresh", json={"source": "all", "dry_run": True}
    )

    assert response.status_code == 200
    assert db_session.query(AnalyticsDigestReport).count() == 0


# --- Backup -------------------------------------------------------------


def test_backup_includes_analytics_digest_reports(client, db_session):
    generate_analytics_digest(db_session)

    body = export_backup(db_session)
    assert len(body["tables"]["analytics_digest_reports"]) == 1


# --- Cache invalidation --------------------------------------------------


def test_digest_cache_invalidates_after_collection_write(client, db_session):
    card = make_card(db_session)

    first = client.get("/analytics/digest")
    assert first.headers["X-Cache"] == "MISS"
    second = client.get("/analytics/digest")
    assert second.headers["X-Cache"] == "HIT"

    response = client.post("/collection", json={"card_id": card.id, "quantity": 1, "status": "hold"})
    assert response.status_code == 201

    third = client.get("/analytics/digest")
    assert third.headers["X-Cache"] == "MISS"
    assert third.json()["sections"]["collection"]["total_items"] == 1
