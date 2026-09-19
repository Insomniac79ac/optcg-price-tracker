from app.models import SourceCardMapping
from app.services.source_mapping_confidence import evaluate_source_mapping
from tests.exact_reporting_helpers import (
    make_canonical,
    make_compatibility_card,
    make_exact_mapping,
    make_exact_observation,
    make_legacy_mapping,
    make_print,
    make_source,
)


def _quality_items(client):
    response = client.get("/admin/source-mappings/quality")
    assert response.status_code == 200, response.text
    return response.json(), {
        item["mapping_id"]: item for item in response.json()["items"]
    }


def test_exact_cardless_mapping_is_not_penalized_for_compatibility_absence(
    client, db_session
):
    source = make_source(db_session)
    canonical = make_canonical(db_session, "OP01-201")
    print_row = make_print(db_session, canonical)
    mapping = make_exact_mapping(
        db_session,
        print_row,
        source,
        source_card_id=canonical.card_code,
        manual_verified=True,
    )
    make_exact_observation(db_session, mapping)

    body, items = _quality_items(client)
    item = items[mapping.id]

    assert body["summary"]["exact_mapping_count"] == 1
    assert item["identity_classification"] == "exact"
    assert item["confidence_scope"] == "exact_print"
    assert item["compatibility_card_id"] is None
    assert item["compatibility_card_status"] == "absent"
    assert "missing_card_reference" not in item["issue_types"]
    assert item["risk_level"] == "ok"


def test_exact_authoritative_confidence_is_independent_of_compatibility_card(
    client, db_session
):
    source = make_source(db_session)
    canonical = make_canonical(db_session, "OP01-202")
    print_without = make_print(db_session, canonical, asset_variant="base")
    print_with = make_print(db_session, canonical, asset_variant="p1")
    compatibility = make_compatibility_card(
        db_session, canonical.card_code, language="jp"
    )
    without = make_exact_mapping(
        db_session,
        print_without,
        source,
        suffix="without-compatibility",
        source_card_id=canonical.card_code,
        manual_verified=True,
    )
    with_card = make_exact_mapping(
        db_session,
        print_with,
        source,
        compatibility_card=compatibility,
        suffix="with-compatibility",
        source_card_id=canonical.card_code,
        manual_verified=True,
    )
    make_exact_observation(db_session, without)
    make_exact_observation(db_session, with_card)

    _, items = _quality_items(client)

    assert items[without.id]["match_confidence"] == items[with_card.id][
        "match_confidence"
    ]
    assert items[without.id]["match_confidence_label"] == items[with_card.id][
        "match_confidence_label"
    ]
    assert items[without.id]["compatibility_card_status"] == "absent"
    assert items[with_card.id]["compatibility_card_status"] == "present_valid"


def test_broken_compatibility_pointer_does_not_invalidate_exact_lineage(
    db_session,
):
    source = make_source(db_session)
    canonical = make_canonical(db_session, "OP01-203")
    print_row = make_print(db_session, canonical)
    mapping = make_exact_mapping(
        db_session,
        print_row,
        source,
        source_card_id=canonical.card_code,
        manual_verified=True,
    )
    baseline = evaluate_source_mapping(
        db_session, mapping, latest_price_observed_at=None, is_duplicate=False
    )

    # The production FK prevents this state; the shared outer-join projection
    # still reports it correctly if historical/restored data is inconsistent.
    mapping.card_id = 999_999
    db_session.commit()
    db_session.expire_all()
    mapping = db_session.get(SourceCardMapping, mapping.id)
    result = evaluate_source_mapping(
        db_session, mapping, latest_price_observed_at=None, is_duplicate=False
    )

    assert result.identity_classification == "exact"
    assert result.compatibility_card_status == "broken_reference"
    assert result.match_confidence == baseline.match_confidence
    assert result.match_confidence_label == baseline.match_confidence_label
    assert "broken_mapping_identity" not in result.issue_types


def test_sibling_print_freshness_is_mapping_and_print_scoped(client, db_session):
    source = make_source(db_session)
    canonical = make_canonical(db_session, "OP01-204")
    compatibility = make_compatibility_card(
        db_session, canonical.card_code, language="jp"
    )
    base = make_print(db_session, canonical, asset_variant="base")
    parallel = make_print(db_session, canonical, asset_variant="p1")
    base_mapping = make_exact_mapping(
        db_session,
        base,
        source,
        compatibility_card=compatibility,
        suffix="base-sibling",
        source_card_id=canonical.card_code,
        manual_verified=True,
    )
    parallel_mapping = make_exact_mapping(
        db_session,
        parallel,
        source,
        compatibility_card=compatibility,
        suffix="parallel-sibling",
        source_card_id=canonical.card_code,
        manual_verified=True,
    )
    observation = make_exact_observation(db_session, base_mapping)

    _, items = _quality_items(client)
    base_item = items[base_mapping.id]
    parallel_item = items[parallel_mapping.id]

    assert base_item["latest_price_observed_at"] == observation.observed_at.isoformat()
    assert "active_without_recent_price" not in base_item["issue_types"]
    assert parallel_item["latest_price_observed_at"] is None
    assert "active_without_recent_price" in parallel_item["issue_types"]


def test_exact_dimensions_use_print_canonical_product_and_listing_evidence(
    client, db_session
):
    source = make_source(db_session)
    canonical = make_canonical(
        db_session,
        "OP01-205",
        name_en="Authoritative Name",
        name_jp="権威名",
    )
    print_row = make_print(
        db_session,
        canonical,
        product_code="OP-02",
        asset_variant="p1",
        treatment="parallel",
        rarity="SP",
        language="jp",
    )
    print_row.official_name = "公式名"
    db_session.commit()
    mapping = make_exact_mapping(
        db_session,
        print_row,
        source,
        source_card_id=canonical.card_code,
        source_url=(
            "https://yuyutei.example/products/OP-02/OP01-205_p1-parallel"
        ),
        manual_verified=True,
    )
    make_exact_observation(db_session, mapping)

    _, items = _quality_items(client)
    item = items[mapping.id]
    dimensions = item["exact_confidence_dimensions"]

    assert item["canonical_card_id"] == canonical.id
    assert item["card_print_id"] == print_row.id
    assert item["release_product_id"] == print_row.release_product_id
    assert item["canonical_card_code"] == "OP01-205"
    assert item["canonical_name_en"] == "Authoritative Name"
    assert item["release_product_code"] == "OP-02"
    assert item["official_asset_variant"] == "p1"
    assert item["treatment"] == "parallel"
    assert item["official_rarity"] == "SP"
    assert dimensions["card_code"]["status"] == "match"
    assert dimensions["release_product"]["status"] == "match"
    assert dimensions["official_asset_variant"]["status"] == "match"
    assert dimensions["treatment"]["status"] == "match"
    assert dimensions["language"] == {
        "status": "not_observed",
        "expected": "jp",
        "observed": None,
    }


def test_legacy_and_broken_populations_have_no_modern_exact_score(client, db_session):
    source = make_source(db_session)
    legacy = make_legacy_mapping(
        db_session,
        make_compatibility_card(db_session, "OP01-206"),
        source,
        manual_verified=True,
    )
    broken = SourceCardMapping(
        source_id=source.id,
        source_card_id="broken-listing",
        source_url="https://yuyutei.example/broken-listing",
        card_id=None,
        card_print_id=None,
        is_active=False,
        review_status="needs_review",
        manual_verified=True,
    )
    db_session.add(broken)
    db_session.commit()

    body, items = _quality_items(client)

    assert body["summary"]["legacy_compatibility_mapping_count"] == 1
    assert body["summary"]["broken_mapping_count"] == 1
    assert items[legacy.id]["confidence_scope"] == "compatibility_only"
    assert items[legacy.id]["match_confidence"] is None
    assert items[legacy.id]["compatibility_match_confidence"] is not None
    assert items[legacy.id]["latest_price_observed_at"] is None
    assert items[broken.id]["confidence_scope"] == "structural_failure"
    assert items[broken.id]["match_confidence"] is None
    assert items[broken.id]["risk_level"] == "critical"
    assert "broken_mapping_identity" in items[broken.id]["issue_types"]


def test_exact_suggestions_do_not_offer_legacy_card_as_authoritative_target(
    client, db_session
):
    source = make_source(db_session)
    canonical = make_canonical(db_session, "OP01-207")
    print_row = make_print(db_session, canonical)
    mapping = make_exact_mapping(db_session, print_row, source)
    make_compatibility_card(db_session, canonical.card_code)

    response = client.get(f"/admin/source-mappings/{mapping.id}/suggested-cards")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["identity_classification"] == "exact"
    assert body["authoritative_card_print_id"] == print_row.id
    assert body["suggestion_scope"] == "exact_print_review_required"
    assert body["matches"] == []
    assert "Changing card_id would not change" in body["message"]


def test_live_exact_calculation_ignores_stale_persisted_legacy_score_and_recheck_replaces_it(
    client, db_session
):
    source = make_source(db_session)
    canonical = make_canonical(db_session, "OP01-208")
    print_row = make_print(db_session, canonical)
    mapping = make_exact_mapping(
        db_session,
        print_row,
        source,
        source_card_id=canonical.card_code,
        manual_verified=True,
        match_confidence=1,
        match_confidence_label="very_low",
        match_explanation_json={
            "negative": ["legacy card mismatch"],
            "display_image": {"owned_asset": {"url": "https://assets.example/a"}},
        },
    )
    make_exact_observation(db_session, mapping)

    _, items = _quality_items(client)
    current = items[mapping.id]
    assert current["match_confidence"] != 1
    assert current["match_confidence_label"] != "very_low"

    response = client.post(
        "/admin/source-mappings/recheck-quality", json={"dry_run": False}
    )
    assert response.status_code == 200, response.text
    db_session.refresh(mapping)
    assert mapping.match_confidence == current["match_confidence"]
    assert mapping.match_confidence_label == current["match_confidence_label"]
    assert mapping.match_explanation_json["identity_classification"] == "exact"
    assert mapping.match_explanation_json["display_image"] == {
        "owned_asset": {"url": "https://assets.example/a"}
    }
