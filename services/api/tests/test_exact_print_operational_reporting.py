from app.models import PriceObservation, SourceCardMapping
from app.schemas import CardAuditReportOut
from app.services.card_audit import run_card_audit
from app.services.system_check import (
    build_exact_print_semantic_checks,
    build_operational_identity_summary,
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


def _checks_by_name(db_session):
    return {
        check.name: check for check in build_exact_print_semantic_checks(db_session)
    }


def test_mapping_population_uses_exact_legacy_broken_contract(db_session):
    source = make_source(db_session)
    print_row = make_print(db_session, make_canonical(db_session, "OP01-001"))
    make_exact_mapping(db_session, print_row, source)
    make_legacy_mapping(
        db_session, make_compatibility_card(db_session, "OP01-002"), source
    )
    db_session.add(
        SourceCardMapping(
            card_id=None,
            card_print_id=None,
            source_id=source.id,
            source_card_id="malformed",
            source_url="https://yuyutei.example/malformed",
        )
    )
    db_session.commit()

    population = build_operational_identity_summary(db_session)["mapping_identity"]

    assert population == {
        "exact": 1,
        "legacy_compatibility": 1,
        "broken": 1,
        "broken_operational": 1,
    }


def test_card_audit_keeps_sibling_prints_and_compatibility_independent(db_session):
    source = make_source(db_session)
    canonical = make_canonical(db_session, "OP01-010")
    print_a = make_print(db_session, canonical, asset_variant="base")
    print_b = make_print(db_session, canonical, asset_variant="p1")
    mapping_a = make_exact_mapping(db_session, print_a, source, suffix="a")
    make_exact_mapping(db_session, print_b, source, suffix="b")
    make_exact_observation(db_session, mapping_a)
    make_legacy_mapping(
        db_session, make_compatibility_card(db_session, "OP01-010"), source
    )

    report = run_card_audit(db_session)

    assert report.modern_exact_print_audit == {
        "eligible_physical_prints": 2,
        "exact_mappings": 2,
        "active_exact_mappings": 2,
        "mappings_with_fresh_observations": 1,
        "mappings_without_fresh_observations": 1,
        "active_exact_mappings_non_priceable": 0,
        "broken_mappings": 0,
    }
    assert report.compatibility_audit["grandfathered_legacy_mappings"] == 1
    assert report.compatibility_audit["legacy_card_references"] == 1
    api_payload = CardAuditReportOut.model_validate(report.to_dict()).model_dump()
    assert api_payload["modern_exact_print_audit"]["exact_mappings"] == 2
    assert api_payload["compatibility_audit"][
        "grandfathered_legacy_mappings"
    ] == 1


def test_card_audit_surfaces_active_exact_mapping_to_non_priceable_print(db_session):
    source = make_source(db_session)
    print_row = make_print(
        db_session,
        make_canonical(db_session, "OP01-011"),
        verification_status="unverified",
    )
    make_exact_mapping(db_session, print_row, source)

    report = run_card_audit(db_session)

    assert report.modern_exact_print_audit["active_exact_mappings_non_priceable"] == 1
    issue = next(
        issue
        for issue in report.issues
        if issue.issue_type == "active_exact_mapping_non_priceable"
    )
    assert issue.severity == "critical"
    assert issue.details["card_print_ids"] == [print_row.id]


def test_clean_exact_print_semantic_population_passes(db_session):
    source = make_source(db_session)
    print_row = make_print(db_session, make_canonical(db_session, "OP01-020"))
    mapping = make_exact_mapping(db_session, print_row, source)
    make_exact_observation(db_session, mapping)

    checks = _checks_by_name(db_session)

    for name in (
        "mapping_identity_integrity",
        "exact_mapping_operational_state",
        "observation_identity_population",
        "modern_parent_population",
    ):
        assert checks[name].status == "pass"


def test_exact_print_semantic_checks_are_read_only(db_session):
    source = make_source(db_session)
    print_row = make_print(db_session, make_canonical(db_session, "OP01-022"))
    mapping = make_exact_mapping(db_session, print_row, source)
    make_exact_observation(db_session, mapping)
    before = (
        db_session.query(SourceCardMapping).count(),
        db_session.query(PriceObservation).count(),
    )

    build_exact_print_semantic_checks(db_session)

    assert not db_session.new
    assert not db_session.dirty
    assert not db_session.deleted
    assert before == (
        db_session.query(SourceCardMapping).count(),
        db_session.query(PriceObservation).count(),
    )


def test_grandfathered_mapping_does_not_fail_modern_pricing_health(db_session):
    source = make_source(db_session)
    make_legacy_mapping(
        db_session, make_compatibility_card(db_session, "OP01-021"), source
    )

    checks = _checks_by_name(db_session)
    summary = build_operational_identity_summary(db_session)

    assert summary["mapping_identity"]["legacy_compatibility"] == 1
    assert checks["mapping_identity_integrity"].status == "pass"
    assert checks["exact_mapping_operational_state"].status == "pass"
    assert checks["legacy_compatibility_population"].status == "pass"


def test_broken_exact_mapping_is_critical(db_session):
    source = make_source(db_session)
    db_session.execute(
        SourceCardMapping.__table__.insert().values(
            card_id=None,
            card_print_id=999_999,
            source_id=source.id,
            source_card_id="broken-exact",
            source_url="https://yuyutei.example/broken-exact",
            is_active=True,
            review_status="approved",
        )
    )
    db_session.commit()

    checks = _checks_by_name(db_session)

    assert checks["mapping_identity_population"].status == "pass"
    assert "broken=1" in checks["mapping_identity_population"].message
    assert checks["mapping_identity_integrity"].status == "fail"
    assert checks["mapping_identity_integrity"].severity == "critical"


def test_broken_observation_lineage_is_critical(db_session):
    source = make_source(db_session)
    print_a = make_print(db_session, make_canonical(db_session, "OP01-030"))
    print_b = make_print(
        db_session,
        make_canonical(db_session, "OP01-031"),
        asset_variant="p1",
    )
    mapping = make_exact_mapping(db_session, print_a, source)
    db_session.execute(
        PriceObservation.__table__.insert().values(
            card_id=None,
            source_id=source.id,
            source_card_mapping_id=mapping.id,
            card_print_id=print_b.id,
            price_type="sell",
            price_jpy=1200,
        )
    )
    db_session.commit()

    summary = build_operational_identity_summary(db_session)
    check = _checks_by_name(db_session)["observation_identity_population"]

    assert summary["observations"]["broken_inconsistent"] == 1
    assert check.status == "fail"
    assert check.severity == "critical"


def test_active_exact_mapping_to_inactive_print_is_critical(db_session):
    source = make_source(db_session)
    print_row = make_print(
        db_session, make_canonical(db_session, "OP01-040"), active=False
    )
    make_exact_mapping(db_session, print_row, source)

    summary = build_operational_identity_summary(db_session)
    check = _checks_by_name(db_session)["exact_mapping_operational_state"]

    assert summary["exact_mapping_operations"][
        "active_exact_to_non_priceable_print"
    ] == 1
    assert check.status == "fail"
    assert check.severity == "critical"


def test_broken_compatibility_pointer_is_separate_from_exact_integrity(db_session):
    source = make_source(db_session)
    db_session.execute(
        SourceCardMapping.__table__.insert().values(
            card_id=999_999,
            card_print_id=None,
            source_id=source.id,
            source_card_id="broken-legacy",
            source_url="https://yuyutei.example/broken-legacy",
            is_active=True,
            review_status="approved",
        )
    )
    db_session.commit()

    checks = _checks_by_name(db_session)
    summary = build_operational_identity_summary(db_session)

    assert summary["legacy_compatibility"]["broken_mapping_card_pointers"] == 1
    assert checks["mapping_identity_integrity"].status == "pass"
    assert checks["source_mappings_valid_card_id"].status == "fail"
    assert "Legacy compatibility" in checks["source_mappings_valid_card_id"].message


def test_exact_mapping_broken_optional_card_pointer_remains_exact(db_session):
    source = make_source(db_session)
    print_row = make_print(db_session, make_canonical(db_session, "OP01-050"))
    db_session.execute(
        SourceCardMapping.__table__.insert().values(
            card_id=999_999,
            card_print_id=print_row.id,
            source_id=source.id,
            source_card_id="exact-broken-compat",
            source_url="https://yuyutei.example/exact-broken-compat",
            is_active=True,
            review_status="approved",
        )
    )
    db_session.commit()

    summary = build_operational_identity_summary(db_session)
    checks = _checks_by_name(db_session)

    assert summary["mapping_identity"]["exact"] == 1
    assert summary["mapping_identity"]["broken"] == 0
    assert summary["legacy_compatibility"]["broken_mapping_card_pointers"] == 1
    assert checks["mapping_identity_integrity"].status == "pass"
    assert checks["source_mappings_valid_card_id"].status == "fail"
