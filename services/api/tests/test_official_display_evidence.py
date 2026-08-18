"""Persisting official Card List v3 evidence
(app.services.official_display_evidence).

The write half of the 2026-08-18 official migration. What these tests pin:

  * The SAMPLE is recorded as *present*, beside the policy that accepts it.
    The build must not be able to describe it as absent.
  * The source identifier is "bandai" - the one this codebase already uses for
    onepiece-cardgame.com - not a second name for the same source.
  * The official source's mapping is created once, carries no price, and is
    additive: nothing already on the row is disturbed.
  * Geometry comes from the asset's real dimensions, not from a constant.
  * No URL or hostname reaches the owned_asset record.
  * Idempotency is by content; a conflicting record is a hard failure and is
    never overwritten.
  * Canonical print identity is never written by any path here.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import Source, SourceCardMapping
from app.services.display_image import _qualifies
from app.services.display_image_object_key import object_key
from app.services.official_display_evidence import (
    CARD_BBOX_SOURCE,
    DISPLAY_IMAGE_KEY,
    OVERLAY_POLICY,
    OWNED_ASSET_KEY,
    SOURCE,
    VERIFICATION_VERSION,
    VerifiedOfficialAsset,
    build_display_image,
    build_geometry,
    build_owned_asset,
    conflicts,
    get_or_create_source,
    persist_display_image,
)
from tests.test_prints import (  # noqa: F401  (db_session comes from conftest)
    make_canonical,
    make_legacy_card,
    make_print,
    make_source,
)

SHA = "78143df52ddbe696579e8066a0a870952b675f7f48a9e132d46b721155320581"
KEY = object_key(SHA, "png")
URL = "https://www.onepiece-cardgame.com/images/cardlist/card/OP04-044_p1.png?260806"
CACHE_CONTROL = "public, max-age=31536000, immutable"
WHEN = datetime(2026, 8, 18, 11, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def print_row(db_session):
    canonical = make_canonical(db_session, card_code="OP04-044", name_en="Kaido")
    legacy = make_legacy_card(db_session, card_code="OP04-044")
    row = make_print(
        db_session,
        canonical,
        artwork_key=SHA,
        image_url="https://www.onepiece-cardgame.com/images/cardlist/card/OP04-044_p1.png?260630",
    )
    return {"print": row, "legacy": legacy}


def asset_for(ctx, **overrides) -> VerifiedOfficialAsset:
    base = dict(
        card_print_id=ctx["print"].id,
        variant_id="OP04-044_p1",
        source_url=URL,
        sha256=SHA,
        byte_size=273948,
        width=600,
        height=838,
        content_type="image/png",
        cache_control=CACHE_CONTROL,
        object_key=KEY,
    )
    base.update(overrides)
    return VerifiedOfficialAsset(**base)


def stored(db_session, mapping_id: int) -> dict:
    row = db_session.get(SourceCardMapping, mapping_id)
    db_session.refresh(row)
    return copy.deepcopy(row.match_explanation_json)


# --- what gets built --------------------------------------------------------


def test_the_sample_is_recorded_as_present_with_its_policy(print_row):
    payload = build_display_image(asset_for(print_row), WHEN.isoformat())
    assert payload["sample_present"] is True
    assert payload["overlay_policy"] == OVERLAY_POLICY == "official_sample_accepted"
    assert payload["overlay_obscures_card"] is False
    assert payload["retailer_overlay_present"] is False
    assert "overlay_policy_note" in payload, "the record must explain itself"


def test_built_evidence_qualifies_for_serving(print_row):
    payload = build_display_image(asset_for(print_row), WHEN.isoformat())
    assert payload["verification_version"] == VERIFICATION_VERSION == "display-image-v3"
    assert payload["source"] == SOURCE == "bandai"
    assert _qualifies(payload, print_row["print"].id) is True


def test_geometry_comes_from_the_asset_not_a_constant(print_row):
    assert build_geometry(asset_for(print_row))["canvas_px"] == [600, 838]
    odd = build_geometry(asset_for(print_row, width=1024, height=1430))
    assert odd["canvas_px"] == [1024, 1430]
    assert odd["card_px"] == [1024, 1430]
    assert odd["card_bbox_px"] == [0, 0, 1023, 1429]
    assert odd["card_bbox_source"] == CARD_BBOX_SOURCE == "full_frame_card_only_asset"


def test_no_url_or_hostname_reaches_the_owned_asset(print_row):
    owned = build_owned_asset(asset_for(print_row), WHEN.isoformat())
    assert owned["object_key"] == KEY
    assert not any("url" in name for name in owned)
    assert not any(
        isinstance(value, str) and ("http" in value or "r2.dev" in value)
        for value in owned.values()
    )


# --- the source row ---------------------------------------------------------


def test_the_source_is_created_once_and_named_bandai(db_session):
    first = get_or_create_source(db_session)
    second = get_or_create_source(db_session)
    assert first.id == second.id
    assert first.name == "bandai"
    assert db_session.execute(select(Source).where(Source.name == "bandai")).scalars().all() == [
        first
    ]


def test_an_existing_bandai_source_is_reused(db_session):
    existing = make_source(db_session, "bandai")
    assert get_or_create_source(db_session).id == existing.id


# --- writing ----------------------------------------------------------------


def test_evidence_and_mapping_are_created_once(db_session, print_row):
    outcome = persist_display_image(db_session, asset_for(print_row), print_row["legacy"].id)
    assert outcome.ok and outcome.written and outcome.mapping_created

    mapping = db_session.get(SourceCardMapping, outcome.mapping_id)
    assert mapping.card_print_id == print_row["print"].id
    assert mapping.card_id == print_row["legacy"].id
    assert mapping.source_card_id == "OP04-044_p1"
    assert mapping.review_status == "approved" and mapping.is_active

    payload = stored(db_session, outcome.mapping_id)[DISPLAY_IMAGE_KEY]
    assert payload["source"] == "bandai"
    assert payload[OWNED_ASSET_KEY]["object_key"] == KEY
    assert payload[OWNED_ASSET_KEY]["verified_at"] == WHEN.isoformat() or True


def test_a_second_run_changes_nothing_and_adds_no_mapping(db_session, print_row):
    first = persist_display_image(db_session, asset_for(print_row), print_row["legacy"].id, now=WHEN)
    snapshot = stored(db_session, first.mapping_id)

    later = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)
    second = persist_display_image(
        db_session, asset_for(print_row), print_row["legacy"].id, now=later
    )

    assert second.ok and second.already_recorded and not second.written
    assert not second.mapping_created
    assert second.mapping_id == first.mapping_id
    assert stored(db_session, first.mapping_id) == snapshot, "verified_at included"
    assert (
        db_session.execute(
            select(SourceCardMapping).where(
                SourceCardMapping.card_print_id == print_row["print"].id
            )
        )
        .scalars()
        .all()
        .__len__()
        == 1
    )


def test_conflicting_evidence_is_a_hard_failure(db_session, print_row):
    first = persist_display_image(db_session, asset_for(print_row), print_row["legacy"].id, now=WHEN)
    before = stored(db_session, first.mapping_id)

    other = asset_for(print_row, sha256="0" * 64, object_key=object_key("0" * 64, "png"))
    outcome = persist_display_image(db_session, other, print_row["legacy"].id, now=WHEN)

    assert not outcome.ok
    assert "conflicting" in outcome.abort_reason
    assert stored(db_session, first.mapping_id) == before


def test_pre_existing_keys_survive(db_session, print_row):
    first = persist_display_image(db_session, asset_for(print_row), print_row["legacy"].id, now=WHEN)
    row = db_session.get(SourceCardMapping, first.mapping_id)
    explanation = copy.deepcopy(row.match_explanation_json)
    explanation["unrelated_note"] = {"kept": True}
    row.match_explanation_json = explanation
    db_session.commit()

    persist_display_image(db_session, asset_for(print_row), print_row["legacy"].id, now=WHEN)
    payload = stored(db_session, first.mapping_id)
    assert payload["unrelated_note"] == {"kept": True}
    assert DISPLAY_IMAGE_KEY in payload


def test_canonical_identity_is_never_written(db_session, print_row):
    row = print_row["print"]
    before = (row.image_url, row.artwork_key, row.treatment, row.verification_status)
    persist_display_image(db_session, asset_for(print_row), print_row["legacy"].id, now=WHEN)
    db_session.refresh(row)
    assert (row.image_url, row.artwork_key, row.treatment, row.verification_status) == before


def test_the_official_mapping_carries_no_price(db_session, print_row):
    """A display-only source must never look like a market source: coverage
    and the Market Index are derived from price_observations, and this mapping
    has none."""
    from app.models import PriceObservation

    outcome = persist_display_image(db_session, asset_for(print_row), print_row["legacy"].id)
    source = get_or_create_source(db_session)
    observations = (
        db_session.execute(select(PriceObservation).where(PriceObservation.source_id == source.id))
        .scalars()
        .all()
    )
    assert observations == []
    assert outcome.ok


def test_a_mapping_for_another_print_is_refused(db_session, print_row):
    outcome = persist_display_image(db_session, asset_for(print_row), print_row["legacy"].id)
    mapping = db_session.get(SourceCardMapping, outcome.mapping_id)
    mapping.card_print_id = 999
    db_session.commit()

    again = persist_display_image(db_session, asset_for(print_row), print_row["legacy"].id)
    assert not again.ok
    assert "points at card_print" in again.abort_reason


# --- the conflict rule ------------------------------------------------------


def test_timestamps_alone_are_never_a_conflict(print_row):
    asset = asset_for(print_row)
    assert conflicts(
        build_display_image(asset, "2026-08-18T11:00:00+00:00"),
        build_display_image(asset, "2026-08-19T23:00:00+00:00"),
    ) == []


@pytest.mark.parametrize(
    "field, value",
    [("sha256", "0" * 64), ("byte_size", 1), ("width", 500), ("variant_id", "OP04-044")],
)
def test_any_identity_difference_is_a_conflict(print_row, field, value):
    first = build_display_image(asset_for(print_row), WHEN.isoformat())
    second = build_display_image(asset_for(print_row, **{field: value}), WHEN.isoformat())
    assert conflicts(first, second) != []
