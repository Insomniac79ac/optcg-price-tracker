from datetime import datetime, timedelta, timezone

from app.models import SourceCardMapping
from app.models.price_refresh_run import PriceRefreshRun
from app.models.snkrdunk_discovery_run import SnkrdunkDiscoveryRun
from app.services.price_source_health import (
    PriceSourceHealthFilters,
    compute_price_source_health,
    summarize_price_source_health,
)
from app.services.source_mapping_identity import BROKEN, SourceMappingIdentity
from tests.exact_reporting_helpers import (
    make_canonical,
    make_compatibility_card,
    make_exact_mapping,
    make_exact_observation,
    make_legacy_mapping,
    make_print,
    make_source,
)

NOW = datetime.now(timezone.utc)


def make_exact_case(
    db_session,
    source,
    card_code,
    *,
    product_code="OP-01",
    asset_variant="base",
    rarity="R",
):
    canonical = make_canonical(db_session, card_code, rarity=rarity)
    print_row = make_print(
        db_session,
        canonical,
        product_code=product_code,
        asset_variant=asset_variant,
        rarity=rarity,
    )
    mapping = make_exact_mapping(db_session, print_row, source)
    return print_row, mapping


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
    _print, mapping = make_exact_case(db_session, yuyutei, "OP01-001", rarity="L")
    make_exact_observation(db_session, mapping, observed_at=NOW - timedelta(hours=1))
    make_refresh_run(db_session, status="completed", source_filter="yuyutei")

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    source_item = next(s for s in report.sources if s.source_name == "yuyutei")
    assert source_item.health_status == "healthy"
    assert source_item.recent_price_count == 1


def test_stale_source_detected(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    _print, mapping = make_exact_case(db_session, yuyutei, "OP01-001", rarity="L")
    make_exact_observation(db_session, mapping, observed_at=NOW - timedelta(hours=48))

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    source_item = next(s for s in report.sources if s.source_name == "yuyutei")
    assert source_item.stale_price_count == 1
    assert source_item.health_status == "stale"


def test_failed_refresh_marks_error(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    _print, mapping = make_exact_case(db_session, yuyutei, "OP01-001", rarity="L")
    make_exact_observation(db_session, mapping, observed_at=NOW - timedelta(hours=1))
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
    make_refresh_run(
        db_session,
        status="completed",
        source_filter="yuyutei",
        started_at=NOW - timedelta(hours=1),
    )
    make_refresh_run(
        db_session,
        status="completed",
        source_filter="yuyutei",
        started_at=NOW - timedelta(hours=2),
    )
    make_refresh_run(
        db_session,
        status="failed",
        source_filter="yuyutei",
        started_at=NOW - timedelta(hours=3),
    )

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    source_item = next(s for s in report.sources if s.source_name == "yuyutei")
    assert source_item.recent_refresh_success_rate_pct == round(2 / 3 * 100, 2)
    assert source_item.error_count_7d == 1
    assert report.summary["recent_refresh_success_rate_pct"] == round(2 / 3 * 100, 2)


# --- freshness thresholds ------------------------------------------------------


def test_yuyutei_24h_freshness_threshold(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    _fresh_print, fresh_mapping = make_exact_case(
        db_session, yuyutei, "OP01-001", rarity="L"
    )
    _stale_print, stale_mapping = make_exact_case(
        db_session, yuyutei, "OP01-002", asset_variant="p1", rarity="R"
    )
    make_exact_observation(
        db_session, fresh_mapping, observed_at=NOW - timedelta(hours=23)
    )
    make_exact_observation(
        db_session, stale_mapping, observed_at=NOW - timedelta(hours=25)
    )

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    source_item = next(s for s in report.sources if s.source_name == "yuyutei")
    assert source_item.recent_price_count == 1
    assert source_item.stale_price_count == 1


def test_snkrdunk_7d_freshness_threshold(db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    _fresh_print, fresh_mapping = make_exact_case(
        db_session, snkrdunk, "OP01-001", rarity="L"
    )
    _stale_print, stale_mapping = make_exact_case(
        db_session, snkrdunk, "OP01-002", asset_variant="p1", rarity="R"
    )
    make_exact_observation(
        db_session, fresh_mapping, observed_at=NOW - timedelta(days=6)
    )
    make_exact_observation(
        db_session, stale_mapping, observed_at=NOW - timedelta(days=8)
    )

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    source_item = next(s for s in report.sources if s.source_name == "snkrdunk")
    assert source_item.recent_price_count == 1
    assert source_item.stale_price_count == 1


def test_sibling_prints_have_independent_mapping_health(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    canonical = make_canonical(db_session, "OP01-001")
    base = make_print(db_session, canonical, asset_variant="base")
    parallel = make_print(db_session, canonical, asset_variant="p1")
    base_mapping = make_exact_mapping(db_session, base, yuyutei, suffix="base")
    make_exact_mapping(db_session, parallel, yuyutei, suffix="parallel")
    make_exact_observation(
        db_session, base_mapping, observed_at=NOW - timedelta(hours=1)
    )

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    source_item = next(item for item in report.sources if item.source_name == "yuyutei")

    assert source_item.active_mapping_count == 2
    assert source_item.recent_price_count == 1
    assert source_item.missing_price_count == 1
    assert {gap.card_print_id for gap in report.missing_prices} == {parallel.id}


def test_legacy_mapping_is_visible_but_not_healthy_exact_coverage(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    card = make_compatibility_card(db_session, "OP01-001")
    mapping = make_legacy_mapping(db_session, card, yuyutei)

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    source_item = next(item for item in report.sources if item.source_name == "yuyutei")

    assert source_item.active_mapping_count == 0
    assert source_item.recent_price_count == 0
    assert source_item.legacy_compatibility_mapping_count == 1
    assert report.summary["legacy_compatibility_mapping_count"] == 1
    assert [item.mapping_id for item in report.legacy_compatibility_mappings] == [
        mapping.id
    ]
    assert (
        report.legacy_compatibility_mappings[0].identity_classification
        == "legacy_compatibility"
    )


def test_broken_mapping_remains_a_distinct_health_category(db_session, monkeypatch):
    source = make_source(db_session, "yuyutei")
    mapping = SourceCardMapping(
        id=999,
        source_id=source.id,
        card_print_id=123456,
        card_id=None,
        source_card_id="broken-listing",
        source_url="https://yuyutei.example/broken",
        is_active=True,
    )
    broken = SourceMappingIdentity(
        mapping=mapping,
        source=source,
        card_print=None,
        canonical_card=None,
        release_product=None,
        compatibility_card=None,
        classification=BROKEN,
    )
    monkeypatch.setattr(
        "app.services.price_source_health.load_source_mapping_identities",
        lambda _db, conditions=(): [broken],
    )

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())

    assert report.summary["broken_mapping_count"] == 1
    assert report.summary["exact_mapping_count"] == 0
    assert report.broken_mappings[0].mapping_id == mapping.id
    assert report.broken_mappings[0].identity_classification == "broken"


# --- breakdowns ----------------------------------------------------------------


def test_coverage_by_release_product(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    _print_a, mapping_a = make_exact_case(
        db_session, yuyutei, "OP01-001", product_code="OP-01", rarity="L"
    )
    make_exact_case(
        db_session,
        yuyutei,
        "OP02-001",
        product_code="OP-02",
        asset_variant="p1",
        rarity="L",
    )
    make_exact_observation(db_session, mapping_a, observed_at=NOW - timedelta(hours=1))

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    by_product = {i.key: i for i in report.coverage_by_release_product}
    assert by_product["OP-01"].mapped_prints == 1
    assert by_product["OP-01"].recent_price_prints == 1
    assert by_product["OP-02"].missing_price_prints == 1


def test_coverage_by_rarity(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    make_exact_case(db_session, yuyutei, "OP01-001", rarity="L")
    make_exact_case(db_session, yuyutei, "OP01-002", asset_variant="p1", rarity="R")

    report = compute_price_source_health(db_session, PriceSourceHealthFilters())
    by_rarity = {i.key: i for i in report.coverage_by_rarity}
    assert by_rarity["L"].mapped_prints == 1
    assert by_rarity["R"].mapped_prints == 1


# --- gaps endpoint -------------------------------------------------------------


def test_stale_gap_endpoint_works(client, db_session):
    yuyutei = make_source(db_session, "yuyutei")
    print_row, mapping = make_exact_case(db_session, yuyutei, "OP01-001", rarity="L")
    make_exact_observation(db_session, mapping, observed_at=NOW - timedelta(hours=48))

    resp = client.get("/admin/price-source-health/gaps?gap_type=stale")
    assert resp.status_code == 200
    data = resp.json()
    assert data["gap_type"] == "stale"
    assert len(data["items"]) == 1
    assert data["items"][0]["issue_type"] == "stale_price"
    assert data["items"][0]["card_print_id"] == print_row.id
    assert data["items"][0]["identity_classification"] == "exact"


def test_missing_gap_endpoint_works(client, db_session):
    yuyutei = make_source(db_session, "yuyutei")
    make_exact_case(db_session, yuyutei, "OP01-001", rarity="L")

    resp = client.get("/admin/price-source-health/gaps?gap_type=missing")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["issue_type"] == "missing_price"


def test_failed_refresh_gap_endpoint_works(client, db_session):
    yuyutei = make_source(db_session, "yuyutei")
    make_exact_case(db_session, yuyutei, "OP01-001", rarity="L")
    make_refresh_run(db_session, status="failed", source_filter="yuyutei")

    resp = client.get("/admin/price-source-health/gaps?gap_type=failed_refresh")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["issue_type"] == "refresh_failed"
    assert data["items"][0]["severity"] == "critical"


def test_blocked_gap_endpoint_works(client, db_session):
    snkrdunk = make_source(db_session, "snkrdunk")
    make_exact_case(db_session, snkrdunk, "OP01-001", rarity="L")
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
    make_exact_case(db_session, yuyutei, "OP01-001", rarity="L")

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
    make_exact_case(db_session, yuyutei, "OP01-001", rarity="L")

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
