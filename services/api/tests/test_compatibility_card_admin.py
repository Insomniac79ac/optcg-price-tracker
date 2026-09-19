import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.admin_source_mapping_quality import (
    edit_mapping_compatibility_card,
    replace_mapping_card_compatibility_alias,
    router,
)
from app.models import PriceObservation, SourceCardMapping
from app.schemas import CompatibilityCardUpdateIn, LegacyReplaceCardAliasIn
from app.services.print_market_index import get_market_index_for_print
from app.services.source_mapping_confidence import (
    evaluate_source_mapping,
    suggested_cards_for_mapping,
)
from app.services.source_mapping_identity import load_source_mapping_identity
from tests.exact_reporting_helpers import (
    make_canonical,
    make_compatibility_card,
    make_exact_mapping,
    make_exact_observation,
    make_legacy_mapping,
    make_print,
    make_source,
)


def _mapping_operational_snapshot(mapping: SourceCardMapping) -> tuple:
    return (
        mapping.card_print_id,
        mapping.source_id,
        mapping.source_card_id,
        mapping.source_url,
        mapping.review_status,
        mapping.is_active,
        mapping.manual_verified,
        mapping.last_verified_at,
        mapping.match_confidence,
        mapping.match_confidence_label,
        mapping.match_explanation_json,
        mapping.last_match_checked_at,
    )


def _edit(db, mapping_id: int, compatibility_card_id: int | None, **overrides):
    return edit_mapping_compatibility_card(
        mapping_id,
        CompatibilityCardUpdateIn(
            compatibility_card_id=compatibility_card_id, **overrides
        ),
        db,
    )


def test_exact_compatibility_card_edit_preserves_authoritative_identity_and_history(
    db_session,
):
    source = make_source(db_session)
    canonical = make_canonical(db_session, "OP01-301")
    print_row = make_print(db_session, canonical)
    previous_card = make_compatibility_card(db_session, canonical.card_code)
    conflicting_card = make_compatibility_card(
        db_session, "OP01-999", variant="parallel"
    )
    mapping = make_exact_mapping(
        db_session,
        print_row,
        source,
        compatibility_card=previous_card,
        source_card_id=canonical.card_code,
        manual_verified=True,
        match_confidence=73,
        match_confidence_label="high",
        match_explanation_json={"persisted": "unchanged"},
    )
    observation = make_exact_observation(
        db_session, mapping, price_jpy=1300, price_type="sell"
    )
    before_state = _mapping_operational_snapshot(mapping)
    before_observation = (
        observation.id,
        observation.card_id,
        observation.source_card_mapping_id,
        observation.card_print_id,
        observation.source_id,
        observation.price_jpy,
    )
    before_confidence = evaluate_source_mapping(
        db_session, mapping, is_duplicate=False
    )
    before_index = get_market_index_for_print(db_session, print_row.id)

    result = _edit(
        db_session,
        mapping.id,
        conflicting_card.id,
        review_notes="Compatibility pointer only",
    )

    assert result.operation == "compatibility_card_updated"
    assert result.authoritative_card_print_id == print_row.id
    assert result.card_print_id == print_row.id
    assert result.previous_compatibility_card_id == previous_card.id
    assert result.new_compatibility_card_id == conflicting_card.id
    assert result.compatibility_card_id == conflicting_card.id
    assert result.pricing_identity_changed is False
    assert result.identity_classification == "exact"
    assert result.compatibility_card_status == "conflicting"
    assert result.deprecated_route is False

    db_session.refresh(mapping)
    db_session.refresh(observation)
    assert mapping.card_id == conflicting_card.id
    assert _mapping_operational_snapshot(mapping) == before_state
    assert (
        observation.id,
        observation.card_id,
        observation.source_card_mapping_id,
        observation.card_print_id,
        observation.source_id,
        observation.price_jpy,
    ) == before_observation
    assert load_source_mapping_identity(db_session, mapping.id).classification == "exact"

    after_confidence = evaluate_source_mapping(
        db_session, mapping, is_duplicate=False
    )
    assert after_confidence.match_confidence == before_confidence.match_confidence
    assert (
        after_confidence.exact_confidence_dimensions
        == before_confidence.exact_confidence_dimensions
    )
    after_index = get_market_index_for_print(db_session, print_row.id)
    assert after_index.model_dump(exclude={"calculated_at"}) == before_index.model_dump(
        exclude={"calculated_at"}
    )


def test_exact_compatibility_card_can_be_cleared_and_remains_exact(db_session):
    source = make_source(db_session)
    canonical = make_canonical(db_session, "OP01-302")
    print_row = make_print(db_session, canonical)
    compatibility_card = make_compatibility_card(db_session, canonical.card_code)
    mapping = make_exact_mapping(
        db_session, print_row, source, compatibility_card=compatibility_card
    )

    result = _edit(db_session, mapping.id, None)

    assert result.new_compatibility_card_id is None
    assert result.compatibility_card_status == "absent"
    assert result.identity_classification == "exact"
    assert result.pricing_identity_changed is False
    db_session.refresh(mapping)
    assert mapping.card_id is None
    assert mapping.card_print_id == print_row.id


def test_legacy_compatibility_edit_stays_non_authoritative(db_session):
    source = make_source(db_session)
    previous_card = make_compatibility_card(db_session, "OP01-303")
    replacement_card = make_compatibility_card(
        db_session, "OP01-304", variant="parallel"
    )
    mapping = make_legacy_mapping(db_session, previous_card, source)
    before_state = _mapping_operational_snapshot(mapping)

    result = _edit(db_session, mapping.id, replacement_card.id)

    assert result.identity_classification == "legacy_compatibility"
    assert result.authoritative_card_print_id is None
    assert result.pricing_identity_changed is False
    db_session.refresh(mapping)
    assert mapping.card_id == replacement_card.id
    assert mapping.card_print_id is None
    assert _mapping_operational_snapshot(mapping) == before_state
    assert (
        load_source_mapping_identity(db_session, mapping.id).classification
        == "legacy_compatibility"
    )


def test_legacy_compatibility_card_cannot_be_cleared_into_broken_lineage(
    db_session,
):
    source = make_source(db_session)
    card = make_compatibility_card(db_session, "OP01-305")
    mapping = make_legacy_mapping(db_session, card, source)

    with pytest.raises(HTTPException) as raised:
        _edit(db_session, mapping.id, None)

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "legacy_compatibility_card_required"
    db_session.refresh(mapping)
    assert mapping.card_id == card.id
    assert mapping.card_print_id is None


def test_broken_mapping_cannot_be_repaired_by_compatibility_edit(db_session):
    source = make_source(db_session)
    card = make_compatibility_card(db_session, "OP01-306")
    mapping = SourceCardMapping(
        source_id=source.id,
        source_card_id="broken-listing",
        source_url="https://yuyutei.example/broken-listing",
        card_id=None,
        card_print_id=None,
        is_active=False,
        review_status="needs_review",
    )
    db_session.add(mapping)
    db_session.commit()

    with pytest.raises(HTTPException) as raised:
        _edit(db_session, mapping.id, card.id)

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "broken_mapping_identity"
    db_session.refresh(mapping)
    assert mapping.card_id is None
    assert mapping.card_print_id is None
    assert load_source_mapping_identity(db_session, mapping.id).classification == "broken"


def test_deprecated_replace_card_alias_delegates_without_approving(
    db_session,
):
    source = make_source(db_session)
    canonical = make_canonical(db_session, "OP01-307")
    print_row = make_print(db_session, canonical)
    previous_card = make_compatibility_card(db_session, canonical.card_code)
    replacement_card = make_compatibility_card(
        db_session, "OP01-308", variant="parallel"
    )
    mapping = make_exact_mapping(
        db_session,
        print_row,
        source,
        compatibility_card=previous_card,
        review_status="needs_review",
        is_active=False,
        manual_verified=False,
    )
    before_state = _mapping_operational_snapshot(mapping)

    result = replace_mapping_card_compatibility_alias(
        mapping.id,
        LegacyReplaceCardAliasIn(card_id=replacement_card.id, approve=True),
        db_session,
    )

    assert result.deprecated_route is True
    assert result.deprecated_approve_requested is True
    assert result.new_compatibility_card_id == replacement_card.id
    assert result.pricing_identity_changed is False
    db_session.refresh(mapping)
    assert mapping.card_id == replacement_card.id
    assert _mapping_operational_snapshot(mapping) == before_state
    assert mapping.review_status == "needs_review"
    assert mapping.is_active is False
    assert mapping.manual_verified is False


def test_compatibility_edit_rejects_missing_card_and_card_print_input(db_session):
    source = make_source(db_session)
    canonical = make_canonical(db_session, "OP01-309")
    print_row = make_print(db_session, canonical)
    mapping = make_exact_mapping(db_session, print_row, source)

    with pytest.raises(HTTPException) as raised:
        _edit(db_session, mapping.id, 999_999)
    assert raised.value.status_code == 404
    assert raised.value.detail["code"] == "compatibility_card_not_found"

    with pytest.raises(HTTPException) as legacy_raised:
        replace_mapping_card_compatibility_alias(
            mapping.id,
            LegacyReplaceCardAliasIn(card_id=999_999),
            db_session,
        )
    assert legacy_raised.value.status_code == 404
    assert legacy_raised.value.detail == "Card not found"

    with pytest.raises(ValidationError):
        CompatibilityCardUpdateIn(
            compatibility_card_id=None, card_print_id=print_row.id
        )
    with pytest.raises(ValidationError):
        LegacyReplaceCardAliasIn(
            card_id=999_999, card_print_id=print_row.id
        )
    db_session.refresh(mapping)
    assert mapping.card_print_id == print_row.id


def test_compatibility_edit_does_not_create_or_delete_observations(
    db_session,
):
    source = make_source(db_session)
    canonical = make_canonical(db_session, "OP01-310")
    print_row = make_print(db_session, canonical)
    card = make_compatibility_card(db_session, canonical.card_code)
    mapping = make_exact_mapping(db_session, print_row, source)
    observation = make_exact_observation(db_session, mapping)
    before_ids = [row.id for row in db_session.query(PriceObservation).all()]

    _edit(db_session, mapping.id, card.id)

    assert [row.id for row in db_session.query(PriceObservation).all()] == before_ids
    db_session.refresh(observation)
    assert observation.source_card_mapping_id == mapping.id
    assert observation.card_print_id == print_row.id


def test_api_routes_expose_explicit_compatibility_action_and_deprecated_alias():
    by_path_method = {
        (route.path, method): route
        for route in router.routes
        for method in getattr(route, "methods", set())
    }
    explicit = by_path_method[
        ("/admin/source-mappings/{mapping_id}/compatibility-card", "PATCH")
    ]
    alias = by_path_method[
        ("/admin/source-mappings/{mapping_id}/replace-card", "POST")
    ]

    assert explicit.deprecated is None
    assert alias.deprecated is True
    assert explicit.response_model.__name__ == "CompatibilityCardUpdateOut"
    assert alias.response_model is explicit.response_model


def test_exact_suggestions_never_present_compatibility_card_as_pricing_remap(
    db_session,
):
    source = make_source(db_session)
    canonical = make_canonical(db_session, "OP01-311")
    print_row = make_print(db_session, canonical)
    mapping = make_exact_mapping(db_session, print_row, source)
    make_compatibility_card(db_session, canonical.card_code)

    suggestions = suggested_cards_for_mapping(db_session, mapping)

    assert suggestions.identity_classification == "exact"
    assert suggestions.authoritative_card_print_id == print_row.id
    assert suggestions.suggestion_scope == "exact_print_review_required"
    assert suggestions.matches == []
    assert "Changing card_id would not change" in suggestions.message
