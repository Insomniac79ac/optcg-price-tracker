"""Additive display_image field on the print-centric public responses (see
app.services.display_image).

Background: every canonical Bandai artwork carries a baked-in "SAMPLE"
watermark, so it reads badly on a collector-facing catalogue. The
2026-08-13 display-image tranche fetched and inspected both marketplace
candidate sources and recorded the outcome on the mapping rows:

  * SNKRDUNK - 16 approved mappings verified VERIFIED_DISPLAY.
  * Yuyu-Tei - all 20 exact-product images carry a "yuyu-tei.jp" retailer
    overlay across the artwork, so none qualified.

These tests pin the selection rule that follows from that, and - more
importantly - pin the ways it must *fail closed*: unverified, quarantined,
overlay-bearing, or sibling-mismatched evidence must never reach the public
response, and the canonical identity fields must be untouched either way.
"""

from __future__ import annotations

import copy

import pytest

from tests.test_prints import (  # noqa: F401  (db_session/client come from conftest)
    make_canonical,
    make_legacy_card,
    make_mapping,
    make_print,
    make_source,
)

SNKRDUNK_URL = "https://cdn.snkrdunk.com/upload_bg_removed/TCG-OPC-OP01-0001.webp?size=l"
BANDAI_URL = "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-013.png?260630"

# The shape app.services.display_image requires, mirroring exactly what the
# verification tranche wrote to source_card_mappings.match_explanation_json.
VERIFIED_PAYLOAD = {
    "url": SNKRDUNK_URL,
    "source": "snkrdunk",
    "card_print_id": None,  # filled in per-test with the real print id
    "verified_at": "2026-08-13T10:56:42+00:00",
    "verification_method": "offline_image_comparison_vs_bandai_canonical",
    "verification_version": "display-image-v1",
    "exact_print_verified": True,
    "full_card_preserved": True,
    "sample_present": False,
    "overlay_obscures_card": False,
    "classification": "VERIFIED_DISPLAY",
}


def _payload(card_print_id: int, **overrides) -> dict:
    payload = copy.deepcopy(VERIFIED_PAYLOAD)
    payload["card_print_id"] = card_print_id
    payload.update(overrides)
    return payload


@pytest.fixture()
def sanji_pair(db_session):
    """Sanji base + parallel: one canonical card, two prints, one shared
    legacy card row - the real staging shape."""
    canonical = make_canonical(db_session, card_code="OP01-013", name_en="Sanji", rarity="R")
    legacy = make_legacy_card(db_session, card_code="OP01-013", rarity="R")
    base = make_print(db_session, canonical, treatment="normal", image_url=BANDAI_URL)
    parallel = make_print(
        db_session,
        canonical,
        treatment="parallel",
        artwork_key="art-2",
        image_url=BANDAI_URL.replace("OP01-013.png", "OP01-013_p2.png"),
    )
    return {
        "canonical": canonical,
        "legacy": legacy,
        "base": base,
        "parallel": parallel,
        "snkrdunk": make_source(db_session, "snkrdunk"),
    }


def _detail(client, print_id: int) -> dict:
    response = client.get(f"/prints/{print_id}")
    assert response.status_code == 200
    return response.json()


def _catalogue_item(client, print_id: int) -> dict:
    items = client.get("/prints", params={"limit": 100}).json()["items"]
    return next(i for i in items if i["card_print_id"] == print_id)


# --- fallback: no verified evidence anywhere --------------------------------


def test_bandai_canonical_is_the_fallback_when_nothing_is_verified(client, sanji_pair):
    """With no display evidence at all, the print still gets a display_image
    - the canonical Bandai URL, SAMPLE watermark and all."""
    detail = _detail(client, sanji_pair["base"].id)
    assert detail["display_image"] == {
        "url": BANDAI_URL,
        "source": "bandai",
        "exact_print_verified": True,
        # The canonical fallback is not an asset we own - "bandai" alone
        # cannot say that, which is exactly why this field exists.
        "owned_asset_selected": False,
        "geometry": None,
    }


def test_display_image_is_additive_and_never_replaces_canonical_fields(client, sanji_pair):
    """image_url/artwork_key stay canonical Bandai identity evidence even
    once a cleaner display image has been selected."""
    make_mapping(
        db_session_of(sanji_pair),
        sanji_pair["legacy"],
        sanji_pair["snkrdunk"],
        sanji_pair["base"],
        review_status="approved",
        match_explanation_json={"display_image": _payload(sanji_pair["base"].id)},
    )
    detail = _detail(client, sanji_pair["base"].id)
    assert detail["display_image"]["url"] == SNKRDUNK_URL
    assert detail["image_url"] == BANDAI_URL
    assert detail["artwork_key"] == "art-1"


def db_session_of(fixture):
    """The fixture objects are already bound to the test session."""
    from sqlalchemy.orm import object_session

    return object_session(fixture["base"])


# --- verified SNKRDUNK is preferred -----------------------------------------


def test_verified_snkrdunk_image_is_preferred_over_bandai(client, sanji_pair):
    make_mapping(
        db_session_of(sanji_pair),
        sanji_pair["legacy"],
        sanji_pair["snkrdunk"],
        sanji_pair["base"],
        review_status="approved",
        match_explanation_json={"display_image": _payload(sanji_pair["base"].id)},
    )
    assert _detail(client, sanji_pair["base"].id)["display_image"] == {
        "url": SNKRDUNK_URL,
        "source": "snkrdunk",
        "exact_print_verified": True,
        # A verified source URL, but no owned asset was recorded for it.
        "owned_asset_selected": False,
        "geometry": None,
    }


def test_catalogue_and_detail_agree_on_the_display_image(client, sanji_pair):
    make_mapping(
        db_session_of(sanji_pair),
        sanji_pair["legacy"],
        sanji_pair["snkrdunk"],
        sanji_pair["base"],
        review_status="approved",
        match_explanation_json={"display_image": _payload(sanji_pair["base"].id)},
    )
    print_id = sanji_pair["base"].id
    assert _catalogue_item(client, print_id)["display_image"] == _detail(client, print_id)[
        "display_image"
    ]


# --- fail-closed cases -------------------------------------------------------


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"classification": "SAMPLE_PRESENT", "sample_present": True}, "SAMPLE still visible"),
        (
            {"classification": "OVERLAY_OBSCURES_CARD", "overlay_obscures_card": True},
            "retailer overlay obscures the card",
        ),
        (
            {"classification": "CROPPED_OR_DAMAGED", "full_card_preserved": False},
            "card content was cropped away",
        ),
        (
            {"classification": "ARTWORK_AMBIGUOUS", "exact_print_verified": False},
            "exact print not proven",
        ),
    ],
)
def test_unqualified_evidence_never_supplies_a_display_image(
    client, sanji_pair, overrides, reason
):
    """Anything short of a full VERIFIED_DISPLAY assertion falls back to
    Bandai. This is the Yuyu-Tei case (overlay) among others."""
    make_mapping(
        db_session_of(sanji_pair),
        sanji_pair["legacy"],
        sanji_pair["snkrdunk"],
        sanji_pair["base"],
        review_status="approved",
        match_explanation_json={"display_image": _payload(sanji_pair["base"].id, **overrides)},
    )
    detail = _detail(client, sanji_pair["base"].id)
    assert detail["display_image"]["source"] == "bandai", reason
    assert detail["display_image"]["url"] == BANDAI_URL


@pytest.mark.parametrize("review_status", ["needs_review", "rejected"])
def test_quarantined_mapping_never_supplies_a_display_image(client, sanji_pair, review_status):
    """Mappings 42/43/49/52 in staging are quarantined at needs_review with
    artwork hashes over threshold; they must be invisible to display
    selection even if evidence were somehow attached."""
    make_mapping(
        db_session_of(sanji_pair),
        sanji_pair["legacy"],
        sanji_pair["snkrdunk"],
        sanji_pair["base"],
        review_status=review_status,
        match_explanation_json={"display_image": _payload(sanji_pair["base"].id)},
    )
    assert _detail(client, sanji_pair["base"].id)["display_image"]["source"] == "bandai"


def test_inactive_mapping_never_supplies_a_display_image(client, sanji_pair):
    make_mapping(
        db_session_of(sanji_pair),
        sanji_pair["legacy"],
        sanji_pair["snkrdunk"],
        sanji_pair["base"],
        review_status="approved",
        is_active=False,
        match_explanation_json={"display_image": _payload(sanji_pair["base"].id)},
    )
    assert _detail(client, sanji_pair["base"].id)["display_image"]["source"] == "bandai"


def test_mapping_without_display_evidence_falls_back(client, sanji_pair):
    """An approved mapping carrying only its price/identity evidence - the
    quarantined-then-revalidated shape - must not be mistaken for display
    evidence."""
    make_mapping(
        db_session_of(sanji_pair),
        sanji_pair["legacy"],
        sanji_pair["snkrdunk"],
        sanji_pair["base"],
        review_status="approved",
        match_explanation_json={"revalidation_2026_08_11": {"artwork": {"match": True}}},
    )
    assert _detail(client, sanji_pair["base"].id)["display_image"]["source"] == "bandai"


# --- sibling isolation -------------------------------------------------------


def test_sibling_display_images_never_cross(client, sanji_pair):
    """Base and parallel Sanji share a canonical card and a legacy card row.
    Evidence naming the base print must not surface on the parallel."""
    session = db_session_of(sanji_pair)
    make_mapping(
        session,
        sanji_pair["legacy"],
        sanji_pair["snkrdunk"],
        sanji_pair["base"],
        review_status="approved",
        match_explanation_json={"display_image": _payload(sanji_pair["base"].id)},
    )
    base = _detail(client, sanji_pair["base"].id)
    parallel = _detail(client, sanji_pair["parallel"].id)

    assert base["display_image"]["url"] == SNKRDUNK_URL
    assert parallel["display_image"]["source"] == "bandai"
    assert parallel["display_image"]["url"] != SNKRDUNK_URL


def test_payload_claiming_the_wrong_print_is_rejected(client, sanji_pair):
    """Defence in depth: even attached to the parallel's own mapping, a
    payload whose card_print_id names the sibling is refused."""
    make_mapping(
        db_session_of(sanji_pair),
        sanji_pair["legacy"],
        sanji_pair["snkrdunk"],
        sanji_pair["parallel"],
        review_status="approved",
        match_explanation_json={"display_image": _payload(sanji_pair["base"].id)},
    )
    assert _detail(client, sanji_pair["parallel"].id)["display_image"]["source"] == "bandai"


def test_non_https_display_url_is_rejected(client, sanji_pair):
    make_mapping(
        db_session_of(sanji_pair),
        sanji_pair["legacy"],
        sanji_pair["snkrdunk"],
        sanji_pair["base"],
        review_status="approved",
        match_explanation_json={
            "display_image": _payload(sanji_pair["base"].id, url="http://cdn.snkrdunk.com/x.webp")
        },
    )
    assert _detail(client, sanji_pair["base"].id)["display_image"]["source"] == "bandai"


# --- efficiency --------------------------------------------------------------


def test_catalogue_never_reads_raw_snapshots(client, sanji_pair):
    """Yuyu-Tei's image URLs live only inside raw_snapshots HTML. Serving
    display images must never pull that into a public request path, so this
    asserts the catalogue issues no raw_snapshots query at all."""
    session = db_session_of(sanji_pair)
    make_mapping(
        session,
        sanji_pair["legacy"],
        sanji_pair["snkrdunk"],
        sanji_pair["base"],
        review_status="approved",
        match_explanation_json={"display_image": _payload(sanji_pair["base"].id)},
    )

    statements: list[str] = []
    from sqlalchemy import event

    engine = session.get_bind()

    def record(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        assert client.get("/prints", params={"limit": 100}).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert statements, "expected the catalogue request to issue queries"
    # Matches the table, not price_observations.raw_snapshot_id (a column
    # the pricing queries legitimately select).
    touched = [
        s
        for s in statements
        if "from raw_snapshots" in s.lower() or "join raw_snapshots" in s.lower()
    ]
    assert not touched, touched


# --- additive geometry contract ---------------------------------------------


GEOMETRY = {
    "canvas_px": [856, 625],
    "card_bbox_px": [241, 51, 614, 573],   # inclusive corners -> 374 x 523
    "card_px": [374, 523],
}


def _with_geometry(card_print_id: int, geometry) -> dict:
    payload = _payload(card_print_id)
    if geometry is not None:
        payload["geometry"] = geometry
    return {"display_image": payload}


def _attach(fixture, explanation, print_key="base", **overrides):
    return make_mapping(
        db_session_of(fixture),
        fixture["legacy"],
        fixture["snkrdunk"],
        fixture[print_key],
        review_status=overrides.pop("review_status", "approved"),
        match_explanation_json=explanation,
        **overrides,
    )


def test_geometry_is_exposed_as_xywh_from_inclusive_corner_evidence(client, sanji_pair):
    """The stored bbox is [left, top, right, bottom] with inclusive corners;
    the public contract is x/y/width/height, so each span gains one pixel."""
    _attach(sanji_pair, _with_geometry(sanji_pair["base"].id, GEOMETRY))

    geometry = _detail(client, sanji_pair["base"].id)["display_image"]["geometry"]
    assert geometry == {
        "canvas_px": {"width": 856, "height": 625},
        "card_bbox_px": {"x": 241, "y": 51, "width": 374, "height": 523},
    }


def test_bandai_fallback_has_no_geometry(client, sanji_pair):
    """The canonical artwork's card already fills its asset - there is nothing
    to bound it to, and a client must render it plainly."""
    display = _detail(client, sanji_pair["base"].id)["display_image"]

    assert display["source"] == "bandai"
    assert display["geometry"] is None


def test_display_image_without_geometry_still_serves_the_image(client, sanji_pair):
    """Geometry is additive: evidence predating it must still supply its URL."""
    _attach(sanji_pair, _with_geometry(sanji_pair["base"].id, None))

    display = _detail(client, sanji_pair["base"].id)["display_image"]
    assert display["url"] == SNKRDUNK_URL
    assert display["geometry"] is None


@pytest.mark.parametrize(
    "geometry, reason",
    [
        ({"canvas_px": [0, 625], "card_bbox_px": [241, 51, 614, 573]}, "zero canvas width"),
        ({"canvas_px": [856, 0], "card_bbox_px": [241, 51, 614, 573]}, "zero canvas height"),
        ({"canvas_px": [-856, 625], "card_bbox_px": [241, 51, 614, 573]}, "negative canvas"),
        ({"canvas_px": [856, 625], "card_bbox_px": [241, 51, 240, 573]}, "zero-width bbox"),
        ({"canvas_px": [856, 625], "card_bbox_px": [241, 51, 614, 50]}, "zero-height bbox"),
        ({"canvas_px": [856, 625], "card_bbox_px": [-1, 51, 614, 573]}, "negative x"),
        ({"canvas_px": [856, 625], "card_bbox_px": [241, -1, 614, 573]}, "negative y"),
        ({"canvas_px": [856, 625], "card_bbox_px": [241, 51, 900, 573]}, "bbox past right edge"),
        ({"canvas_px": [856, 625], "card_bbox_px": [241, 51, 614, 900]}, "bbox past bottom edge"),
        ({"canvas_px": [856], "card_bbox_px": [241, 51, 614, 573]}, "canvas wrong arity"),
        ({"canvas_px": [856, 625], "card_bbox_px": [241, 51, 614]}, "bbox wrong arity"),
        ({"canvas_px": ["856", 625], "card_bbox_px": [241, 51, 614, 573]}, "canvas not numeric"),
        ({"canvas_px": [856, 625], "card_bbox_px": [241, 51, 614, 573],
          "card_px": [999, 523]}, "card_px contradicts the bbox"),
        ({"canvas_px": [856, 625]}, "bbox missing"),
        ("not-an-object", "geometry is not an object"),
    ],
)
def test_malformed_geometry_is_rejected_but_the_image_is_kept(
    client, sanji_pair, geometry, reason
):
    """Rejecting geometry must degrade to plain presentation, never drop a
    verified image or emit a box a client could scale by."""
    _attach(sanji_pair, _with_geometry(sanji_pair["base"].id, geometry))

    display = _detail(client, sanji_pair["base"].id)["display_image"]
    assert display["url"] == SNKRDUNK_URL, reason
    assert display["geometry"] is None, reason


def test_geometry_appears_on_the_catalogue_too(client, sanji_pair):
    _attach(sanji_pair, _with_geometry(sanji_pair["base"].id, GEOMETRY))
    item = _catalogue_item(client, sanji_pair["base"].id)

    assert item["display_image"]["geometry"]["card_bbox_px"]["width"] == 374


def test_quarantined_mapping_supplies_neither_image_nor_geometry(client, sanji_pair):
    _attach(
        sanji_pair,
        _with_geometry(sanji_pair["base"].id, GEOMETRY),
        review_status="needs_review",
    )
    display = _detail(client, sanji_pair["base"].id)["display_image"]

    assert display["source"] == "bandai"
    assert display["geometry"] is None


def test_canonical_identity_fields_survive_geometry(client, sanji_pair):
    _attach(sanji_pair, _with_geometry(sanji_pair["base"].id, GEOMETRY))
    detail = _detail(client, sanji_pair["base"].id)

    assert detail["image_url"] == BANDAI_URL
    assert detail["artwork_key"] == "art-1"
    assert detail["card_code"] == "OP01-013"
