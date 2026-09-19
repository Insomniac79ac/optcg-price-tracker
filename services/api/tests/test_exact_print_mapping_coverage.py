from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import event

from app.models import SourceCollectionAttempt
from app.services.exact_print_mapping_coverage import (
    AMBIGUOUS_MULTIPLE_EXACT_MAPPINGS,
    EXACT_APPROVED_ACTIVE,
    EXACT_INACTIVE,
    EXACT_NEEDS_REVIEW,
    EXACT_REJECTED,
    HAS_OBSERVATION,
    LEGACY_CARD_ONLY,
    NEVER_ATTEMPTED,
    SNKRDUNK,
    UNMAPPED,
    YUYUTEI,
    compute_exact_print_mapping_coverage,
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


def _row(report, print_id):
    return next(row for row in report.prints if row.card_print_id == print_id)


def _release(report, code):
    return next(row for row in report.releases if row.official_code == code)


def test_sibling_prints_remain_separate_and_release_product_controls_grouping(db_session):
    yuyu = make_source(db_session, YUYUTEI)
    canonical = make_canonical(
        db_session, "OP12-099", original_set_code="OP-12", rarity="SR"
    )
    op12_print = make_print(db_session, canonical, product_code="OP-12")
    op17_print = make_print(
        db_session,
        canonical,
        product_code="OP-17",
        asset_variant="p1",
        treatment="parallel",
    )
    make_exact_mapping(db_session, op17_print, yuyu)

    report = compute_exact_print_mapping_coverage(db_session)

    assert len(report.prints) == 2
    assert _row(report, op12_print.id).sources[YUYUTEI].mapping_state == UNMAPPED
    assert (
        _row(report, op17_print.id).sources[YUYUTEI].mapping_state
        == EXACT_APPROVED_ACTIVE
    )
    assert _release(report, "OP-12").total_verified_active_jp_prints == 1
    op17 = _release(report, "OP-17")
    assert op17.total_verified_active_jp_prints == 1
    assert op17.source_state_counts[YUYUTEI][EXACT_APPROVED_ACTIVE] == 1
    assert report.op17_mixed_code_findings == {
        "release_product_id": op17.release_product_id,
        "official_code": "OP-17",
        "display_name": "Product OP-17",
        "total_physical_prints": 1,
        "non_op17_card_code_prefix_prints": 1,
        "example_card_codes": ["OP12-099"],
        "grouping_basis": "card_prints.release_product_id",
        "prefix_used_for_membership": False,
    }


def test_card_id_only_mapping_is_legacy_only_and_never_exact_coverage(db_session):
    yuyu = make_source(db_session, YUYUTEI)
    canonical = make_canonical(db_session, "OP01-001")
    print_row = make_print(db_session, canonical)
    compatibility = make_compatibility_card(db_session, canonical.card_code)
    legacy = make_legacy_mapping(db_session, compatibility, yuyu)

    report = compute_exact_print_mapping_coverage(db_session)
    row = _row(report, print_row.id)

    assert row.sources[YUYUTEI].mapping_state == LEGACY_CARD_ONLY
    assert row.sources[YUYUTEI].exact_mapping_ids == ()
    assert row.sources[YUYUTEI].legacy_mapping_ids == (legacy.id,)
    assert report.overall["sources"][YUYUTEI][EXACT_APPROVED_ACTIVE] == 0
    assert report.overall["mapped_by_neither"] == 1


def test_source_states_are_independent_and_review_inactive_rejected_are_distinct(db_session):
    yuyu = make_source(db_session, YUYUTEI)
    snkr = make_source(db_session, SNKRDUNK)

    review_card = make_canonical(db_session, "OP02-001")
    review_print = make_print(db_session, review_card, product_code="OP-02")
    make_exact_mapping(
        db_session, review_print, yuyu, review_status="needs_review"
    )
    make_exact_mapping(db_session, review_print, snkr)

    inactive_card = make_canonical(db_session, "OP02-002")
    inactive_print = make_print(db_session, inactive_card, product_code="OP-02")
    make_exact_mapping(db_session, inactive_print, yuyu, is_active=False)

    rejected_card = make_canonical(db_session, "OP02-003")
    rejected_print = make_print(db_session, rejected_card, product_code="OP-02")
    make_exact_mapping(
        db_session, rejected_print, yuyu, review_status="rejected"
    )

    report = compute_exact_print_mapping_coverage(db_session)

    review = _row(report, review_print.id)
    assert review.sources[YUYUTEI].mapping_state == EXACT_NEEDS_REVIEW
    assert review.sources[SNKRDUNK].mapping_state == EXACT_APPROVED_ACTIVE
    assert _row(report, inactive_print.id).sources[YUYUTEI].mapping_state == EXACT_INACTIVE
    assert _row(report, rejected_print.id).sources[YUYUTEI].mapping_state == EXACT_REJECTED
    assert report.overall["mapped_by_snkrdunk_only"] == 1


def test_multiple_live_exact_mappings_are_ambiguous_not_silently_selected(db_session):
    yuyu = make_source(db_session, YUYUTEI)
    canonical = make_canonical(db_session, "OP03-001")
    print_row = make_print(db_session, canonical, product_code="OP-03")
    make_exact_mapping(db_session, print_row, yuyu, suffix="one")
    make_exact_mapping(db_session, print_row, yuyu, suffix="two")

    report = compute_exact_print_mapping_coverage(db_session)

    state = _row(report, print_row.id).sources[YUYUTEI]
    assert state.mapping_state == AMBIGUOUS_MULTIPLE_EXACT_MAPPINGS
    assert len(state.exact_mapping_ids) == 2
    assert state.evidence is None


def test_one_print_mapped_to_both_counts_once_per_source_with_evidence(db_session):
    yuyu = make_source(db_session, YUYUTEI)
    snkr = make_source(db_session, SNKRDUNK)
    canonical = make_canonical(db_session, "OP04-001")
    print_row = make_print(db_session, canonical, product_code="OP-04")
    yuyu_mapping = make_exact_mapping(db_session, print_row, yuyu)
    snkr_mapping = make_exact_mapping(db_session, print_row, snkr)
    make_exact_observation(
        db_session, yuyu_mapping, price_jpy=2400, price_type="sell"
    )
    make_exact_observation(
        db_session, snkr_mapping, price_jpy=2500, price_type="floor"
    )

    report = compute_exact_print_mapping_coverage(db_session)
    row = _row(report, print_row.id)

    assert report.overall["sources"][YUYUTEI][EXACT_APPROVED_ACTIVE] == 1
    assert report.overall["sources"][SNKRDUNK][EXACT_APPROVED_ACTIVE] == 1
    assert report.overall["mapped_by_both"] == 1
    assert report.overall["any_price_observation_coverage"] == 1
    assert report.overall["both_source_observation_coverage"] == 1
    assert row.sources[YUYUTEI].evidence.status == HAS_OBSERVATION
    assert row.sources[SNKRDUNK].evidence.status == HAS_OBSERVATION
    assert row.sources[YUYUTEI].current_representative.available is True
    assert row.sources[SNKRDUNK].current_representative.available is True


def test_attempted_without_observation_and_never_attempted_are_distinct(db_session):
    yuyu = make_source(db_session, YUYUTEI)
    canonical = make_canonical(db_session, "OP05-001")
    print_row = make_print(db_session, canonical, product_code="OP-05")
    mapping = make_exact_mapping(db_session, print_row, yuyu)
    now = datetime.now(timezone.utc)
    db_session.add(
        SourceCollectionAttempt(
            batch_run_id="coverage-test",
            source_id=yuyu.id,
            source_card_mapping_id=mapping.id,
            selection_ordinal=1,
            selected_at=now,
            started_at=now,
            finished_at=now,
            status="validation_failed",
        )
    )
    db_session.commit()

    report = compute_exact_print_mapping_coverage(db_session)
    row = _row(report, print_row.id)

    assert row.sources[YUYUTEI].evidence.status == "attempted_no_observation"
    assert row.sources[YUYUTEI].evidence.latest_collection_attempt_status == "validation_failed"
    assert row.sources[SNKRDUNK].mapping_state == UNMAPPED
    assert row.sources[SNKRDUNK].evidence is None

    second = make_canonical(db_session, "OP05-002")
    second_print = make_print(db_session, second, product_code="OP-05")
    make_exact_mapping(db_session, second_print, yuyu)
    rerun = compute_exact_print_mapping_coverage(db_session)
    assert _row(rerun, second_print.id).sources[YUYUTEI].evidence.status == NEVER_ATTEMPTED


def test_denominator_excludes_non_jp_inactive_unverified_and_invalid_identity(db_session):
    canonical = make_canonical(db_session, "OP06-001")
    included = make_print(db_session, canonical, product_code="OP-06")
    make_print(
        db_session,
        canonical,
        product_code="OP-06",
        asset_variant="p1",
        language="en",
    )
    make_print(
        db_session,
        canonical,
        product_code="OP-06",
        asset_variant="p2",
        active=False,
    )
    make_print(
        db_session,
        canonical,
        product_code="OP-06",
        asset_variant="p3",
        verification_status="unverified",
    )

    report = compute_exact_print_mapping_coverage(db_session)

    assert [row.card_print_id for row in report.prints] == [included.id]


def test_report_service_executes_select_statements_only(db_session):
    yuyu = make_source(db_session, YUYUTEI)
    canonical = make_canonical(db_session, "OP07-001")
    print_row = make_print(db_session, canonical, product_code="OP-07")
    make_exact_mapping(db_session, print_row, yuyu)
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.strip())

    event.listen(db_session.get_bind(), "before_cursor_execute", capture)
    try:
        compute_exact_print_mapping_coverage(db_session)
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", capture)

    assert statements
    assert all(statement.upper().startswith("SELECT") for statement in statements)
