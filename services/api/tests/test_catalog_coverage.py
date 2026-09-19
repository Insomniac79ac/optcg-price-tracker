from datetime import datetime, timedelta, timezone

from app.services.catalog_coverage import (
    CatalogCoverageFilters,
    compute_catalog_coverage,
    summarize_catalog_coverage,
)
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


def test_catalog_coverage_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get("/admin/catalog-coverage").status_code == 401


def test_catalog_coverage_gaps_requires_admin_token(db_session):
    from fastapi.testclient import TestClient

    from app.main import app

    response = TestClient(app).get("/admin/catalog-coverage/gaps?gap_type=mapping")
    assert response.status_code == 401


def test_empty_catalog_reports_physical_print_scope(client, db_session):
    response = client.get("/admin/catalog-coverage")
    assert response.status_code == 200
    body = response.json()

    assert body["summary"]["coverage_unit"] == "eligible_physical_print"
    assert body["summary"]["total_eligible_physical_prints"] == 0
    assert body["summary"]["exact_mapping_coverage_pct"] == 0.0
    assert body["summary"]["fresh_price_coverage_pct"] == 0.0
    assert body["mapping_gaps"] == []
    assert body["legacy_compatibility"]["summary"]["total_cards"] == 0


def test_denominator_is_active_verified_physical_prints(db_session):
    canonical = make_canonical(db_session, "OP01-001")
    make_print(db_session, canonical, asset_variant="base")
    make_print(
        db_session,
        canonical,
        asset_variant="p1",
        verification_status="unverified",
    )
    make_print(db_session, canonical, asset_variant="p2", active=False)

    report = compute_catalog_coverage(db_session, CatalogCoverageFilters())

    assert report.summary["total_eligible_physical_prints"] == 1
    assert report.summary["physical_prints_without_exact_mapping"] == 1


def test_exact_null_card_id_counts_as_mapping_and_fresh_price(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    canonical = make_canonical(db_session, "OP01-001")
    print_row = make_print(db_session, canonical, rarity="L")
    mapping = make_exact_mapping(db_session, print_row, yuyutei)
    make_exact_observation(db_session, mapping, observed_at=NOW - timedelta(hours=1))

    report = compute_catalog_coverage(db_session, CatalogCoverageFilters())
    source = next(item for item in report.sources if item.source_name == "yuyutei")

    assert mapping.card_id is None
    assert report.summary["prints_with_any_exact_mapping"] == 1
    assert report.summary["prints_with_any_fresh_source_observation"] == 1
    assert report.summary["exact_mapping_coverage_pct"] == 100.0
    assert source.mapped_print_count == 1
    assert source.fresh_price_print_count == 1


def test_source_coverage_is_reported_per_source(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    snkrdunk = make_source(db_session, "snkrdunk")
    first = make_print(db_session, make_canonical(db_session, "OP01-001"))
    second = make_print(
        db_session,
        make_canonical(db_session, "OP01-002"),
        asset_variant="p1",
    )
    yuyu_first = make_exact_mapping(db_session, first, yuyutei, suffix="yuyu-first")
    make_exact_mapping(db_session, second, yuyutei, suffix="yuyu-second")
    snkr_first = make_exact_mapping(db_session, first, snkrdunk, suffix="snkr-first")
    make_exact_observation(db_session, yuyu_first, observed_at=NOW - timedelta(hours=1))
    make_exact_observation(
        db_session,
        snkr_first,
        observed_at=NOW - timedelta(days=1),
        price_type="floor",
    )

    report = compute_catalog_coverage(db_session, CatalogCoverageFilters())
    by_source = {item.source_name: item for item in report.sources}

    assert by_source["yuyutei"].mapped_print_count == 2
    assert by_source["yuyutei"].fresh_price_print_count == 1
    assert by_source["snkrdunk"].mapped_print_count == 1
    assert by_source["snkrdunk"].fresh_price_print_count == 1


def test_sibling_prints_are_independent_and_one_price_cannot_cover_another(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    legacy = make_compatibility_card(db_session, "OP01-001")
    canonical = make_canonical(db_session, "OP01-001")
    base = make_print(db_session, canonical, asset_variant="base")
    parallel = make_print(db_session, canonical, asset_variant="p1")
    base_mapping = make_exact_mapping(
        db_session, base, yuyutei, compatibility_card=legacy, suffix="base"
    )
    make_exact_mapping(
        db_session, parallel, yuyutei, compatibility_card=legacy, suffix="parallel"
    )
    make_exact_observation(
        db_session, base_mapping, observed_at=NOW - timedelta(hours=1)
    )

    report = compute_catalog_coverage(db_session, CatalogCoverageFilters())

    assert report.summary["total_eligible_physical_prints"] == 2
    assert report.summary["prints_with_any_exact_mapping"] == 2
    assert report.summary["prints_with_any_fresh_source_observation"] == 1
    assert (
        report.summary["physical_prints_with_exact_mapping_but_no_fresh_observation"]
        == 1
    )
    assert {gap.card_print_id for gap in report.price_gaps} == {parallel.id}


def test_legacy_mapping_is_separate_and_does_not_cover_a_print(db_session):
    yuyutei = make_source(db_session, "yuyutei")
    legacy_card = make_compatibility_card(db_session, "OP01-001")
    legacy_mapping = make_legacy_mapping(db_session, legacy_card, yuyutei)
    make_print(db_session, make_canonical(db_session, "OP01-001"))

    report = compute_catalog_coverage(db_session, CatalogCoverageFilters())

    assert legacy_mapping.card_print_id is None
    assert report.summary["legacy_compatibility_mapping_count"] == 1
    assert report.summary["exact_source_mapping_count"] == 0
    assert report.summary["physical_prints_without_exact_mapping"] == 1
    assert report.legacy_compatibility.summary["cards_with_yuyutei_mapping"] == 1


def test_exact_mapping_without_fresh_observation_is_a_price_gap(client, db_session):
    yuyutei = make_source(db_session, "yuyutei")
    print_row = make_print(db_session, make_canonical(db_session, "OP01-001"))
    make_exact_mapping(db_session, print_row, yuyutei)

    response = client.get("/admin/catalog-coverage/gaps?gap_type=price")
    assert response.status_code == 200
    body = response.json()

    assert body["pagination"]["total"] == 1
    assert body["items"][0]["identity_scope"] == "physical_print"
    assert body["items"][0]["card_print_id"] == print_row.id
    assert body["items"][0]["issue_types"] == [
        "exact_mapping_without_fresh_observation"
    ]


def test_mapping_gap_pagination_is_print_scoped(client, db_session):
    for number in range(3):
        canonical = make_canonical(db_session, f"OP01-00{number}")
        make_print(
            db_session,
            canonical,
            asset_variant="base" if number == 0 else f"p{number}",
        )

    response = client.get(
        "/admin/catalog-coverage/gaps?gap_type=mapping&limit=2&offset=0"
    )
    body = response.json()

    assert len(body["items"]) == 2
    assert body["pagination"]["total"] == 3
    assert body["pagination"]["has_next"] is True
    assert all(item["identity_scope"] == "physical_print" for item in body["items"])


def test_legacy_metadata_gap_remains_under_compatibility_scope(client, db_session):
    make_compatibility_card(db_session, "OP01-001", name_en=None)

    response = client.get("/admin/catalog-coverage/gaps?gap_type=metadata")
    assert response.status_code == 200
    body = response.json()

    assert body["pagination"]["total"] == 1
    assert body["items"][0]["identity_scope"] == "legacy_compatibility"


def test_gaps_endpoint_rejects_unknown_type(client, db_session):
    response = client.get("/admin/catalog-coverage/gaps?gap_type=bogus")
    assert response.status_code == 400


def test_catalog_coverage_cli_prints_physical_summary(db_session, monkeypatch, capsys):
    make_print(db_session, make_canonical(db_session, "OP01-001"))

    import sys

    from app import catalog_coverage_report as cli_module

    monkeypatch.setattr(cli_module, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
    old_argv = sys.argv
    sys.argv = ["catalog_coverage_report"]
    try:
        try:
            cli_module.main()
        except SystemExit as exc:
            assert exc.code == 0
    finally:
        sys.argv = old_argv

    assert "total_eligible_physical_prints" in capsys.readouterr().out


def test_system_check_keeps_legacy_summary_contract_for_later_tranche(
    client, db_session
):
    make_compatibility_card(db_session, "OP01-001")

    response = client.get("/admin/system-check")

    assert response.status_code == 200
    names = {check["name"] for check in response.json()["checks"]}
    assert "catalog_coverage_summary" in names


def test_card_audit_keeps_legacy_compatibility_summary(client, db_session):
    make_compatibility_card(db_session, "OP01-001")

    response = client.get("/admin/card-audit")
    assert response.status_code == 200
    assert response.json()["catalog_coverage"]["total_cards"] == 1


def test_summary_only_function_remains_legacy_for_unmodified_system_checks(db_session):
    make_compatibility_card(db_session, "OP01-001")

    summary = summarize_catalog_coverage(db_session)

    assert summary["total_cards"] == 1
    assert "total_eligible_physical_prints" not in summary
