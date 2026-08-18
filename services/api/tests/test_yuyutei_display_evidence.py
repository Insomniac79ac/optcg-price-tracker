"""Persisting Yuyu-Tei v2 display evidence
(app.services.yuyutei_display_evidence).

The write half of the 2026-08-18 migration. What these tests pin:

  * Additive means additive. Any pre-existing key on the mapping's
    match_explanation_json survives byte-identical, and the print's canonical
    identity columns are never written.
  * The watermark is recorded as *present*. Evidence that described it as
    absent would be a lie, and the build must not be able to produce one.
  * Geometry for a card-only asset is the whole frame, and is never invented
    canvas padding.
  * No URL or hostname reaches the owned_asset record.
  * Idempotency is by content: a matching record is left completely alone,
    verified_at included. A conflicting one is a hard failure and is never
    overwritten.
  * A mapping that belongs to another print is refused outright.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from app.models import SourceCardMapping
from app.services.display_image import _qualifies
from app.services.display_image_object_key import object_key
from app.services.yuyutei_display_evidence import (
    CARD_BBOX_SOURCE,
    DISPLAY_IMAGE_KEY,
    OWNED_ASSET_KEY,
    SOURCE,
    VERIFICATION_VERSION,
    VerifiedYuyuteiAsset,
    build_display_image,
    build_geometry,
    build_owned_asset,
    conflicts,
    persist_display_image,
)
from tests.test_prints import (  # noqa: F401  (db_session comes from conftest)
    make_canonical,
    make_legacy_card,
    make_mapping,
    make_print,
    make_source,
)

SHA = "440c9a4d2b01381bbeb61fa3b03d683e51533d04541ecab3b6bd676c7f4d85e5"
KEY = object_key(SHA, "jpg")
URL = "https://card.yuyu-tei.jp/opc/front/op04/10055.jpg"
BANDAI_URL = "https://www.onepiece-cardgame.com/images/cardlist/card/OP04-044_p1.png?260630"
CACHE_CONTROL = "public, max-age=31536000, immutable"
WHEN = datetime(2026, 8, 18, 9, 47, 36, tzinfo=timezone.utc)


@pytest.fixture()
def mapping(db_session):
    """One print and its Yuyu-Tei mapping, with no evidence yet - which is
    the real starting state: match_explanation_json IS NULL."""
    canonical = make_canonical(db_session, card_code="OP04-044", name_en="Kaido")
    legacy = make_legacy_card(db_session, card_code="OP04-044")
    print_row = make_print(db_session, canonical, artwork_key="art-13", image_url=BANDAI_URL)
    row = make_mapping(
        db_session,
        legacy,
        make_source(db_session, "yuyutei"),
        print_row,
        review_status="approved",
        match_explanation_json=None,
    )
    return {"print": print_row, "mapping": row}


def asset_for(mapping) -> VerifiedYuyuteiAsset:
    return VerifiedYuyuteiAsset(
        card_print_id=mapping["print"].id,
        mapping_id=mapping["mapping"].id,
        source_url=URL,
        sha256=SHA,
        byte_size=646369,
        width=500,
        height=700,
        content_type="image/jpeg",
        cache_control=CACHE_CONTROL,
        object_key=KEY,
    )


def stored(db_session, mapping_id: int) -> dict:
    row = db_session.get(SourceCardMapping, mapping_id)
    db_session.refresh(row)
    return copy.deepcopy(row.match_explanation_json)


# --- what gets built --------------------------------------------------------


def test_the_watermark_is_recorded_as_present_not_absent(mapping):
    payload = build_display_image(asset_for(mapping), WHEN.isoformat())
    assert payload["retailer_overlay_present"] is True
    assert payload["overlay_obscures_card"] is False
    assert payload["sample_present"] is False
    assert "overlay_policy" in payload, "the record must explain itself"


def test_built_evidence_qualifies_for_serving(mapping):
    """The build and the read path agree, which is the only thing that makes
    the migration useful."""
    payload = build_display_image(asset_for(mapping), WHEN.isoformat())
    assert payload["verification_version"] == VERIFICATION_VERSION == "display-image-v2"
    assert payload["source"] == SOURCE == "yuyutei"
    assert _qualifies(payload, mapping["print"].id) is True


def test_geometry_is_the_whole_frame_and_says_so(mapping):
    geometry = build_geometry(asset_for(mapping))
    assert geometry["canvas_px"] == [500, 700]
    assert geometry["card_px"] == [500, 700]
    assert geometry["card_bbox_px"] == [0, 0, 499, 699], "inclusive corners"
    assert geometry["card_bbox_source"] == CARD_BBOX_SOURCE == "full_frame_card_only_asset"


def test_no_url_or_hostname_reaches_the_owned_asset(mapping):
    owned = build_owned_asset(asset_for(mapping), WHEN.isoformat())
    assert owned["object_key"] == KEY
    assert not any("url" in name for name in owned)
    assert not any(
        isinstance(value, str) and ("http" in value or "r2.dev" in value)
        for value in owned.values()
    )


# --- writing ----------------------------------------------------------------


def test_evidence_is_written_once(db_session, mapping):
    outcome = persist_display_image(db_session, asset_for(mapping), now=WHEN)
    assert outcome.ok and outcome.written and not outcome.already_recorded

    payload = stored(db_session, mapping["mapping"].id)[DISPLAY_IMAGE_KEY]
    assert payload["source"] == "yuyutei"
    assert payload["url"] == URL
    assert payload["fetch"] == {"bytes": 646369, "sha256": SHA, "content_type": "image/jpeg"}
    assert payload[OWNED_ASSET_KEY]["object_key"] == KEY
    assert payload[OWNED_ASSET_KEY]["verified_at"] == WHEN.isoformat()


def test_a_second_run_changes_nothing(db_session, mapping):
    persist_display_image(db_session, asset_for(mapping), now=WHEN)
    first = stored(db_session, mapping["mapping"].id)

    later = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)
    outcome = persist_display_image(db_session, asset_for(mapping), now=later)

    assert outcome.ok and outcome.already_recorded and not outcome.written
    assert stored(db_session, mapping["mapping"].id) == first, "verified_at included"


def test_conflicting_evidence_is_a_hard_failure_and_is_never_overwritten(db_session, mapping):
    persist_display_image(db_session, asset_for(mapping), now=WHEN)
    before = stored(db_session, mapping["mapping"].id)

    other = VerifiedYuyuteiAsset(**{**asset_for(mapping).__dict__, "sha256": "0" * 64})
    outcome = persist_display_image(db_session, other, now=WHEN)

    assert not outcome.ok
    assert "conflicting" in outcome.abort_reason
    assert "fetch" in outcome.conflicts and OWNED_ASSET_KEY in outcome.conflicts
    assert stored(db_session, mapping["mapping"].id) == before


def test_pre_existing_keys_survive_byte_identical(db_session, mapping):
    """Additive: the migration writes one key and touches nothing beside it."""
    row = db_session.get(SourceCardMapping, mapping["mapping"].id)
    row.match_explanation_json = {
        "production_run_2026_08_11": {"batch": "cbe0695e9f18"},
        "incident_ref": "snkrdunk_2026-08-10_bulk_insert_unverified",
    }
    db_session.commit()

    persist_display_image(db_session, asset_for(mapping), now=WHEN)

    payload = stored(db_session, mapping["mapping"].id)
    assert payload["production_run_2026_08_11"] == {"batch": "cbe0695e9f18"}
    assert payload["incident_ref"] == "snkrdunk_2026-08-10_bulk_insert_unverified"
    assert DISPLAY_IMAGE_KEY in payload


def test_canonical_print_identity_is_never_written(db_session, mapping):
    before = (mapping["print"].image_url, mapping["print"].artwork_key)
    persist_display_image(db_session, asset_for(mapping), now=WHEN)
    db_session.refresh(mapping["print"])
    assert (mapping["print"].image_url, mapping["print"].artwork_key) == before


def test_a_mapping_for_another_print_is_refused(db_session, mapping):
    wrong = VerifiedYuyuteiAsset(**{**asset_for(mapping).__dict__, "card_print_id": 999})
    outcome = persist_display_image(db_session, wrong, now=WHEN)
    assert not outcome.ok
    assert "points at card_print" in outcome.abort_reason
    assert stored(db_session, mapping["mapping"].id) is None


def test_a_missing_mapping_is_refused(db_session, mapping):
    absent = VerifiedYuyuteiAsset(**{**asset_for(mapping).__dict__, "mapping_id": 4242})
    outcome = persist_display_image(db_session, absent, now=WHEN)
    assert not outcome.ok
    assert "does not exist" in outcome.abort_reason


# --- the conflict rule itself ----------------------------------------------


def test_timestamps_alone_are_never_a_conflict(mapping):
    asset = asset_for(mapping)
    first = build_display_image(asset, "2026-08-18T09:47:36+00:00")
    second = build_display_image(asset, "2026-08-19T23:00:00+00:00")
    assert conflicts(first, second) == []


@pytest.mark.parametrize(
    "field, value",
    [
        ("sha256", "0" * 64),
        ("byte_size", 1),
        ("width", 856),
        ("object_key", object_key("0" * 64, "jpg")),
        ("content_type", "image/webp"),
    ],
)
def test_any_identity_difference_is_a_conflict(mapping, field, value):
    asset = asset_for(mapping)
    first = build_display_image(asset, WHEN.isoformat())
    second = build_display_image(
        VerifiedYuyuteiAsset(**{**asset.__dict__, field: value}), WHEN.isoformat()
    )
    assert conflicts(first, second) != []
