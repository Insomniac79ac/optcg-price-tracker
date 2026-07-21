from datetime import datetime, timedelta, timezone

from app.models import PriceObservation
from app.models.price_refresh_run import PriceRefreshRun
from app.models.snkrdunk_discovery_run import SnkrdunkDiscoveryRun
from app.services.price_source_health import (
    PriceSourceHealthFilters,
    compute_price_source_health,
    summarize_price_source_health,
)
from tests.test_source_mappings import make_card, make_mapping, make_source

NOW = datetime.now(timezone.utc)


def make_price(db_session, card, source, *, observed_at=None, price_jpy=1000, price_type="sell"):
    obs = PriceObservation(
        card_id=card.id,
        source_id=source.id,
        price_type=price_type,
        price_jpy=price_jpy,
        observed_at=observed_at or NOW,
    )
    db_session.add(obs)
    db_session.commit()
    db_session.refresh(obs)
    return obs


def make_refresh_run(
    db_session,
    *,
    status="completed",
    source_filter=None,
    started_at=None,
    finished_at=0,
    mappings_failed=0,
):
    started = started_at or NOW
    run = PriceRefreshRun(
        started_at=started,
        finished_at=started if finished_at == 0 else finished_at,
        status=status,
        scraping_mode="mock",
        source_filter=source_filter,
        limit_count=100,
        dry_run=False,
        mappings_failed=mappings_failed,
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


def make_discovery_run(db_session, *, status="blocked", started_at=None):
    run = SnkrdunkDiscoveryRun(
        started_at=started_at or NOW,
        status=status,
        seed_url="https://snkrdunk.example/seed",
    )
    db_session.add(run)
    db_session.commit()
    db_session.refresh(run)
    return run


# --- auth ------------------------------------------------------------------


def test_price_source_health_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    resp = TestClient(app).get("/admin/price-source-health")
    assert resp.status_code == 401


def test_price_source_health_gaps_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    resp = TestClient(app).get("/admin/price-source-health/gaps?gap_type=stale")
    assert resp.status_code == 401


# --- empty state -------------------------------------------------------------


def test_empty_sources_mappings_works(client, db_session):
    resp = client.get("/admin/price-source-health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["sources_count"] == 0
    assert data["summary"]["total_active_mappings"] == 0
    assert data["sources"] == []
    assert data["stale_prices"] == []
    assert data["missing_prices"] == []


def test_compute_price_source_health_empty(db_session):
    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    assert report.summary["sources_count"] == 0
    assert report.sources == []


# --- health status detection --------------------------------------------------


def test_healthy_source_detected(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    card = make_card(db_session, card_code="OP01-001", rarity="L")
    make_mapping(db_session, card, yuyutei)
    make_price(db_session, card, yuyutei, observed_at=NOW - timedelta(hours=1))
    make_refresh_run(db_session, status="completed", source_filter="yuyutei")

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    source_item = next(s for s in report.sources if s.source_name == "yuyutei")
    assert source_item.health_status == "healthy"
    assert source_item.recent_price_count == 1


def test_stale_source_detected(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    card = make_card(db_session, card_code="OP01-001", rarity="L")
    make_mapping(db_session, card, yuyutei)
    make_price(db_session, card, yuyutei, observed_at=NOW - timedelta(hours=48))

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    source_item = next(s for s in report.sources if s.source_name == "yuyutei")
    assert source_item.stale_price_count == 1
    assert source_item.health_status == "stale"


def test_failed_refresh_marks_error(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    card = make_card(db_session, card_code="OP01-001", rarity="L")
    make_mapping(db_session, card, yuyutei)
    make_price(db_session, card, yuyutei, observed_at=NOW - timedelta(hours=1))
    make_refresh_run(db_session, status="failed", source_filter="yuyutei")

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    source_item = next(s for s in report.sources if s.source_name == "yuyutei")
    assert source_item.latest_refresh_status == "failed"
    assert source_item.health_status == "error"


def test_blocked_source_marks_blocked(db_session):
    make_source(db_session, "snkrdunk")
    make_discovery_run(db_session, status="blocked")

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    source_item = next(s for s in report.sources if s.source_name == "snkrdunk")
    assert source_item.health_status == "blocked"
    assert any("blocked" in w.lower() for w in source_item.warnings)


def test_source_without_any_data_is_unknown(db_session):
    make_source(db_session, "yuyutei")
    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    source_item = next(s for s in report.sources if s.source_name == "yuyutei")
    assert source_item.health_status == "unknown"


# --- success rate ------------------------------------------------------------


def test_success_rate_calculation(db_session):
    make_source(db_session, "yuyutei")
    make_refresh_run(db_session, status="completed", source_filter="yuyutei", started_at=NOW - timedelta(hours=1))
    make_refresh_run(db_session, status="completed", source_filter="yuyutei", started_at=NOW - timedelta(hours=2))
    make_refresh_run(db_session, status="failed", source_filter="yuyutei", started_at=NOW - timedelta(hours=3))

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    source_item = next(s for s in report.sources if s.source_name == "yuyutei")
    assert source_item.recent_refresh_success_rate_pct == round(2 / 3 * 100, 2)
    assert source_item.error_count_7d == 1
    assert report.summary["recent_refresh_success_rate_pct"] == round(2 / 3 * 100, 2)


# --- freshness thresholds ------------------------------------------------------


def test_yuyutei_24h_freshness_threshold(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    fresh_card = make_card(db_session, card_code="OP01-001", rarity="L")
    stale_card = make_card(db_session, card_code="OP01-002", rarity="R")
    make_mapping(db_session, fresh_card, yuyutei)
    make_mapping(db_session, stale_card, yuyutei)
    make_price(db_session, fresh_card, yuyutei, observed_at=NOW - timedelta(hours=23))
    make_price(db_session, stale_card, yuyutei, observed_at=NOW - timedelta(hours=25))

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    source_item = next(s for s in report.sources if s.source_name == "yuyutei")
    assert source_item.recent_price_count == 1
    assert source_item.stale_price_count == 1


def test_snkrdunk_7d_freshness_threshold(db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    fresh_card = make_card(db_session, card_code="OP01-001", rarity="L")
    stale_card = make_card(db_session, card_code="OP01-002", rarity="R")
    make_mapping(db_session, fresh_card, snkrdunk)
    make_mapping(db_session, stale_card, snkrdunk)
    make_price(db_session, fresh_card, snkrdunk, observed_at=NOW - timedelta(days=6))
    make_price(db_session, stale_card, snkrdunk, observed_at=NOW - timedelta(days=8))

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    source_item = next(s for s in report.sources if s.source_name == "snkrdunk")
    assert source_item.recent_price_count == 1
    assert source_item.stale_price_count == 1


# --- breakdowns ----------------------------------------------------------------


def test_coverage_by_set(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    card_a = make_card(db_session, card_code="OP01-001", set_code="OP01", rarity="L")
    card_b = make_card(db_session, card_code="OP02-001", set_code="OP02", rarity="L")
    make_mapping(db_session, card_a, yuyutei)
    make_mapping(db_session, card_b, yuyutei)
    make_price(db_session, card_a, yuyutei, observed_at=NOW - timedelta(hours=1))

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    by_set = {i.key: i for i in report.coverage_by_set}
    assert by_set["OP01"].mapped_cards == 1
    assert by_set["OP01"].recent_price_cards == 1
    assert by_set["OP02"].missing_price_cards == 1


def test_coverage_by_rarity(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    card_a = make_card(db_session, card_code="OP01-001", rarity="L")
    card_b = make_card(db_session, card_code="OP01-002", rarity="R")
    make_mapping(db_session, card_a, yuyutei)
    make_mapping(db_session, card_b, yuyutei)

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    by_rarity = {i.key: i for i in report.coverage_by_rarity}
    assert by_rarity["L"].mapped_cards == 1
    assert by_rarity["R"].mapped_cards == 1


# --- gaps endpoint -------------------------------------------------------------


def test_stale_gap_endpoint_works(client, db_session):
    yuyutei = make_source(db_session, "yuyutei")
    card = make_card(db_session, card_code="OP01-001", rarity="L")
    make_mapping(db_session, card, yuyutei)
    make_price(db_session, card, yuyutei, observed_at=NOW - timedelta(hours=48))

    resp = client.get("/admin/price-source-health/gaps?gap_type=stale")
    assert resp.status_code == 200
    data = resp.json()
    assert data["gap_type"] == "stale"
    assert len(data["items"]) == 1
    assert data["items"][0]["issue_type"] == "stale_price"


def test_missing_gap_endpoint_works(client, db_session):
    yuyutei = make_source(db_session, "yuyutei")
    card = make_card(db_session, card_code="OP01-001", rarity="L")
    make_mapping(db_session, card, yuyutei)

    resp = client.get("/admin/price-source-health/gaps?gap_type=missing")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["issue_type"] == "missing_price"


def test_failed_refresh_gap_endpoint_works(client, db_session):
    yuyutei = make_source(db_session, "yuyutei")
    card = make_card(db_session, card_code="OP01-001", rarity="L")
    make_mapping(db_session, card, yuyutei)
    make_refresh_run(db_session, status="failed", source_filter="yuyutei")

    resp = client.get("/admin/price-source-health/gaps?gap_type=failed_refresh")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["issue_type"] == "refresh_failed"
    assert data["items"][0]["severity"] == "critical"


def test_blocked_gap_endpoint_works(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    card = make_card(db_session, card_code="OP01-001", rarity="L")
    make_mapping(db_session, card, snkrdunk)
    make_discovery_run(db_session, status="blocked")

    resp = client.get("/admin/price-source-health/gaps?gap_type=blocked")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["issue_type"] == "source_blocked"
    assert data["items"][0]["suggested_action"] == "use_manual_snkrdunk_import"


def test_gaps_endpoint_invalid_gap_type(client, db_session):
    resp = client.get("/admin/price-source-health/gaps?gap_type=bogus")
    assert resp.status_code == 400


# --- CLI -----------------------------------------------------------------------


def test_cli_prints_summary(db_session, monkeypatch, capsys):
    make_source(db_session, "yuyutei")

    import sys

    from app import price_source_health_report as cli_module

    monkeypatch.setattr(cli_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    old_argv = sys.argv
    sys.argv = ["price_source_health_report"]
    try:
        try:
            cli_module.main()
        except SystemExit as exc:
            assert exc.code == 0
    finally:
        sys.argv = old_argv

    captured = capsys.readouterr()
    assert "sources_count" in captured.out


# --- system check integration ---------------------------------------------------


def test_system_check_includes_price_source_health(client, db_session):
    resp = client.get("/admin/system-check")
    assert resp.status_code == 200
    names = {c["name"] for c in resp.json()["checks"]}
    assert "price_source_health_summary" in names


def test_system_check_warns_on_no_successful_refresh(client, db_session):
    yuyutei = make_source(db_session, "yuyutei")
    card = make_card(db_session, card_code="OP01-001", rarity="L")
    make_mapping(db_session, card, yuyutei)

    resp = client.get("/admin/system-check")
    checks = {c["name"]: c for c in resp.json()["checks"]}
    assert checks["price_source_health_summary"]["status"] == "warning"


# --- catalog coverage / card audit integration -----------------------------------


def test_catalog_coverage_includes_price_source_health_summary(client, db_session):
    make_source(db_session, "yuyutei")
    resp = client.get("/admin/catalog-coverage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["price_source_health"] is not None
    assert data["price_source_health"]["sources_count"] == 1


def test_card_audit_detects_source_price_missing(client, db_session):
    yuyutei = make_source(db_session, "yuyutei")
    card = make_card(db_session, card_code="OP01-001", rarity="L")
    make_mapping(db_session, card, yuyutei)

    resp = client.get("/admin/card-audit")
    assert resp.status_code == 200
    issues = resp.json()["issues"]
    assert any(i["issue_type"] == "source_price_missing" for i in issues)


def test_card_audit_detects_source_refresh_failed(client, db_session):
    yuyutei = make_source(db_session, "yuyutei")
    make_refresh_run(db_session, status="failed", source_filter="yuyutei")

    resp = client.get("/admin/card-audit")
    assert resp.status_code == 200
    issues = resp.json()["issues"]
    assert any(i["issue_type"] == "source_refresh_failed" for i in issues)


def test_summarize_price_source_health_matches_full_report(db_session):
    make_source(db_session, "yuyutei")
    full = compute_price_source_health(db_session, PriceSourceHealthFilters())
    summary_only = summarize_price_source_health(db_session)
    assert summary_only == full.summary
