"""Serving verified Yuyu-Tei v2 display evidence (the 2026-08-18 migration).

The approved MVP display policy accepts the Yuyu-Tei retailer watermark,
because it does not materially obscure the card, and ranks Yuyu-Tei ahead of
SNKRDUNK on image quality. What these tests pin is that the relaxation is
exactly that narrow:

  * a watermark may be *present*, and v2 evidence must say so explicitly -
    omitting the assertion fails closed rather than reading as "no watermark";
  * an overlay that *obscures* the card still fails, in every version;
  * historical v1 SNKRDUNK evidence keeps qualifying on its own terms and is
    never reinterpreted;
  * SNKRDUNK is still the fallback whenever Yuyu-Tei evidence is absent or
    does not qualify - priority only orders sources that already qualify;
  * a card-only 500x700 asset is described truthfully by a full-frame box,
    and every owned-asset identity check still has to agree;
  * none of it costs an R2 call or a database write on a read.
"""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import event

from app.services import object_storage
from app.services.display_image import (
    DISPLAY_SOURCE_PRIORITY,
    OWNED_ASSET_PRINT_IDS,
    VERIFICATION_VERSION_V2,
)
from app.services.display_image_object_key import object_key
from app.services.yuyutei_display_evidence import (
    VerifiedYuyuteiAsset,
    build_display_image,
)
from app.settings import settings
from tests.test_prints import (  # noqa: F401  (db_session/client come from conftest)
    make_canonical,
    make_legacy_card,
    make_mapping,
    make_print,
    make_source,
)

PUBLIC_BASE = "https://pub-testbucket.r2.dev"
BANDAI_URL = "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001.png?260630"
YUYUTEI_URL = "https://card.yuyu-tei.jp/opc/front/op04/10055.jpg"
SNKRDUNK_URL = "https://cdn.snkrdunk.com/upload_bg_removed/TCG-OPC-OP01-0001.webp?size=l"

YUYU_SHA = "440c9a4d2b01381bbeb61fa3b03d683e51533d04541ecab3b6bd676c7f4d85e5"
YUYU_KEY = object_key(YUYU_SHA, "jpg")
YUYU_BYTES = 646369

SNKR_SHA = "9f4b1c0d5e6a2f7b8c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293"

CACHE_CONTROL = "public, max-age=31536000, immutable"


def asset_for(card_print_id: int, mapping_id: int = 1) -> VerifiedYuyuteiAsset:
    return VerifiedYuyuteiAsset(
        card_print_id=card_print_id,
        mapping_id=mapping_id,
        source_url=YUYUTEI_URL,
        sha256=YUYU_SHA,
        byte_size=YUYU_BYTES,
        width=500,
        height=700,
        content_type="image/jpeg",
        cache_control=CACHE_CONTROL,
        object_key=YUYU_KEY,
    )


def yuyutei_payload(card_print_id: int, **overrides) -> dict:
    payload = build_display_image(asset_for(card_print_id), "2026-08-18T09:47:36+00:00")
    payload.update(overrides)
    return payload


# The v1 evidence the 2026-08-13 tranche wrote, unchanged.
def snkrdunk_payload(card_print_id: int, **overrides) -> dict:
    payload = {
        "url": SNKRDUNK_URL,
        "source": "snkrdunk",
        "card_print_id": card_print_id,
        "classification": "VERIFIED_DISPLAY",
        "exact_print_verified": True,
        "full_card_preserved": True,
        "sample_present": False,
        "overlay_obscures_card": False,
        "verification_version": "display-image-v1",
        "fetch": {"sha256": SNKR_SHA, "bytes": 48123, "content_type": "image/webp"},
        "geometry": {
            "canvas_px": [856, 625],
            "card_px": [374, 523],
            "card_bbox_px": [241, 51, 614, 573],
        },
    }
    payload.update(overrides)
    return payload


def add_print(db_session, index: int, *, image_url=BANDAI_URL):
    code = f"OP01-{index:03d}"
    canonical = make_canonical(db_session, card_code=code, name_en=f"Card {index}")
    legacy = make_legacy_card(db_session, card_code=code)
    row = make_print(db_session, canonical, artwork_key=f"art-{index}", image_url=image_url)
    return {"canonical": canonical, "legacy": legacy, "print": row}


@pytest.fixture()
def public_base(monkeypatch):
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", PUBLIC_BASE)
    return PUBLIC_BASE


def detail(client, print_id: int) -> dict:
    response = client.get(f"/prints/{print_id}")
    assert response.status_code == 200
    return response.json()


def display_image_for(db_session, client, payload, *, source="yuyutei", print_id=1):
    """One print, one mapping carrying `payload`, then read it back."""
    rows = add_print(db_session, print_id)
    make_mapping(
        db_session,
        rows["legacy"],
        make_source(db_session, source),
        rows["print"],
        review_status="approved",
        match_explanation_json={"display_image": payload},
    )
    return detail(client, rows["print"].id)["display_image"]


# --- the v2 contract --------------------------------------------------------


def test_verified_yuyutei_v2_evidence_qualifies(db_session, client, public_base):
    image = display_image_for(db_session, client, yuyutei_payload(1))
    assert image["source"] == "yuyutei"
    assert image["exact_print_verified"] is True
    assert image["url"] == f"{PUBLIC_BASE}/{YUYU_KEY}"


def test_retailer_overlay_present_does_not_fail_on_its_own(db_session, client, public_base):
    """The whole point of v2: a watermark being present is not a failure."""
    payload = yuyutei_payload(1)
    assert payload["retailer_overlay_present"] is True
    assert display_image_for(db_session, client, payload)["source"] == "yuyutei"


def test_an_overlay_that_obscures_the_card_still_fails(db_session, client, public_base):
    """Relaxed for presence, never for obstruction - and it fails closed to
    the canonical Bandai image rather than serving the asset anyway."""
    payload = yuyutei_payload(1, overlay_obscures_card=True)
    assert display_image_for(db_session, client, payload)["source"] == "bandai"


def test_v2_evidence_missing_the_overlay_assertion_fails(db_session, client, public_base):
    """Omission must never be read as 'no watermark'."""
    payload = yuyutei_payload(1)
    del payload["retailer_overlay_present"]
    assert display_image_for(db_session, client, payload)["source"] == "bandai"


@pytest.mark.parametrize("value", ["true", 1, None, "yes"])
def test_v2_overlay_assertion_must_be_a_real_boolean(db_session, client, public_base, value):
    payload = yuyutei_payload(1, retailer_overlay_present=value)
    assert display_image_for(db_session, client, payload)["source"] == "bandai"


def test_v1_evidence_keeps_qualifying_without_the_v2_assertion(db_session, client, public_base):
    """Historical SNKRDUNK evidence is not reinterpreted by the new contract."""
    payload = snkrdunk_payload(1)
    assert "retailer_overlay_present" not in payload
    assert display_image_for(db_session, client, payload, source="snkrdunk")["source"] == "snkrdunk"


def test_the_v2_version_string_is_what_triggers_the_stricter_check():
    assert VERIFICATION_VERSION_V2 == "display-image-v2"
    assert build_display_image(asset_for(1), "t")["verification_version"] == VERIFICATION_VERSION_V2


# --- full-frame geometry ----------------------------------------------------


def test_full_frame_500x700_geometry_qualifies(db_session, client, public_base):
    """A card-only asset: the card box is the whole frame, inclusive corners
    converted to a 500x700 box."""
    image = display_image_for(db_session, client, yuyutei_payload(1))
    assert image["geometry"] == {
        "canvas_px": {"width": 500, "height": 700},
        "card_bbox_px": {"x": 0, "y": 0, "width": 500, "height": 700},
    }


def test_owned_asset_dimensions_must_match_the_geometry(db_session, client, public_base):
    """The client is told where the card sits inside canvas_px; an object of
    any other size would make that box point at the wrong pixels."""
    payload = yuyutei_payload(1)
    payload["owned_asset"]["width"] = 856
    payload["owned_asset"]["height"] = 625
    image = display_image_for(db_session, client, payload)
    assert image["source"] == "yuyutei"
    assert image["url"] == YUYUTEI_URL, "must fall back to the source URL, not serve R2"


def test_geometry_inconsistent_with_its_own_card_px_is_dropped(db_session, client, public_base):
    payload = yuyutei_payload(1)
    payload["geometry"]["card_px"] = [374, 523]
    assert display_image_for(db_session, client, payload)["geometry"] is None


# --- owned-asset identity ---------------------------------------------------


@pytest.mark.parametrize(
    "mutate, reason",
    [
        (lambda o: o.update(sha256=SNKR_SHA), "digest is not the verified image's"),
        (lambda o: o.update(byte_size=1), "byte size disagrees with the fetch evidence"),
        (lambda o: o.update(object_key=object_key(SNKR_SHA, "jpg")), "key is for another digest"),
        (lambda o: o.update(object_key=f"display-images/{YUYU_SHA}.jpg"), "key breaks the rule"),
        (lambda o: o.update(content_type="image/webp"), "content type contradicts the extension"),
        (lambda o: o.update(provider="s3"), "another provider"),
        (lambda o: o.update(verification_method="etag"), "a weaker verification method"),
    ],
)
def test_a_disagreeing_owned_asset_keeps_the_source_url(
    db_session, client, public_base, mutate, reason
):
    """Every failure keeps a working image rather than emitting a broken one."""
    payload = yuyutei_payload(1)
    mutate(payload["owned_asset"])
    image = display_image_for(db_session, client, payload)
    assert image["url"] == YUYUTEI_URL, reason
    assert image["source"] == "yuyutei", reason


# --- source priority --------------------------------------------------------


def test_yuyutei_ranks_ahead_of_snkrdunk():
    """Yuyu-Tei is the fallback below the official card list as of 2026-08-18,
    but still ranks ahead of SNKRDUNK."""
    assert DISPLAY_SOURCE_PRIORITY == ("bandai", "yuyutei", "snkrdunk")
    assert DISPLAY_SOURCE_PRIORITY.index("yuyutei") < DISPLAY_SOURCE_PRIORITY.index("snkrdunk")


def test_yuyutei_wins_when_both_sources_qualify(db_session, client, public_base):
    rows = add_print(db_session, 1)
    for source, payload in (
        ("snkrdunk", snkrdunk_payload(rows["print"].id)),
        ("yuyutei", yuyutei_payload(rows["print"].id)),
    ):
        make_mapping(
            db_session,
            rows["legacy"],
            make_source(db_session, source),
            rows["print"],
            review_status="approved",
            match_explanation_json={"display_image": payload},
        )
    image = detail(client, rows["print"].id)["display_image"]
    assert image["source"] == "yuyutei"
    assert image["url"] == f"{PUBLIC_BASE}/{YUYU_KEY}"


@pytest.mark.parametrize(
    "broken, reason",
    [
        ({"overlay_obscures_card": True}, "overlay obscures the card"),
        ({"exact_print_verified": False}, "not proven to be this exact print"),
        ({"classification": "CROPPED_OR_OBSCURED"}, "not classified for display"),
        ({"card_print_id": 999}, "evidence is about another print"),
    ],
)
def test_snkrdunk_remains_the_fallback_when_yuyutei_does_not_qualify(
    db_session, client, public_base, broken, reason
):
    """Priority only orders sources that already qualify. A Yuyu-Tei mapping
    that fails contributes nothing and must not suppress SNKRDUNK."""
    rows = add_print(db_session, 1)
    failing = yuyutei_payload(rows["print"].id)
    failing.update(broken)
    for source, payload in (
        ("snkrdunk", snkrdunk_payload(rows["print"].id)),
        ("yuyutei", failing),
    ):
        make_mapping(
            db_session,
            rows["legacy"],
            make_source(db_session, source),
            rows["print"],
            review_status="approved",
            match_explanation_json={"display_image": payload},
        )
    assert detail(client, rows["print"].id)["display_image"]["source"] == "snkrdunk", reason


def test_snkrdunk_remains_the_fallback_when_yuyutei_is_absent(db_session, client, public_base):
    image = display_image_for(db_session, client, snkrdunk_payload(1), source="snkrdunk")
    assert image["source"] == "snkrdunk"


def test_bandai_remains_the_last_resort_when_nothing_qualifies(db_session, client):
    rows = add_print(db_session, 1)
    image = detail(client, rows["print"].id)["display_image"]
    assert image["source"] == "bandai"
    assert image["url"] == BANDAI_URL


# --- the allow-list ---------------------------------------------------------


def test_every_allow_listed_print_can_serve_its_owned_asset(db_session, client, public_base):
    """All twenty migrated prints, each with its own distinct digest."""
    assert OWNED_ASSET_PRINT_IDS == frozenset(range(1, 21))
    yuyutei = make_source(db_session, "yuyutei")
    expected = {}
    for index in range(1, 21):
        rows = add_print(db_session, index)
        digest = f"{index:02x}" * 32
        asset = VerifiedYuyuteiAsset(
            card_print_id=rows["print"].id,
            mapping_id=0,
            source_url=f"{YUYUTEI_URL}?{index}",
            sha256=digest,
            byte_size=400000 + index,
            width=500,
            height=700,
            content_type="image/jpeg",
            cache_control=CACHE_CONTROL,
            object_key=object_key(digest, "jpg"),
        )
        make_mapping(
            db_session,
            rows["legacy"],
            yuyutei,
            rows["print"],
            review_status="approved",
            match_explanation_json={
                "display_image": build_display_image(asset, "2026-08-18T09:47:36+00:00")
            },
        )
        expected[rows["print"].id] = f"{PUBLIC_BASE}/{object_key(digest, 'jpg')}"

    assert sorted(expected) == list(range(1, 21))
    for print_id, url in expected.items():
        image = detail(client, print_id)["display_image"]
        assert image["url"] == url, print_id
        assert image["source"] == "yuyutei", print_id


# --- cost of a read ---------------------------------------------------------


def test_serving_a_yuyutei_owned_asset_makes_no_r2_call(
    db_session, client, public_base, monkeypatch
):
    """The URL is configuration plus string joining. No client is built and
    nothing is asked of R2 - a display URL must never cost a round trip."""

    def boom(*args, **kwargs):
        raise AssertionError("R2 was contacted while serving a read")

    monkeypatch.setattr(object_storage.boto3, "client", boom)
    monkeypatch.setattr(object_storage.R2ObjectStorage, "from_settings", boom)
    monkeypatch.setattr(object_storage.R2ObjectStorage, "head_object", boom)
    monkeypatch.setattr(object_storage.R2ObjectStorage, "get_object_bytes", boom)
    monkeypatch.setattr(object_storage.R2ObjectStorage, "put_object", boom)

    assert display_image_for(db_session, client, yuyutei_payload(1))["url"] == (
        f"{PUBLIC_BASE}/{YUYU_KEY}"
    )


def test_serving_a_yuyutei_owned_asset_writes_nothing(db_session, client, public_base):
    rows = add_print(db_session, 1)
    make_mapping(
        db_session,
        rows["legacy"],
        make_source(db_session, "yuyutei"),
        rows["print"],
        review_status="approved",
        match_explanation_json={"display_image": yuyutei_payload(rows["print"].id)},
    )
    before = copy.deepcopy(
        db_session.query(type(rows["print"])).filter_by(id=rows["print"].id).one().image_url
    )

    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        detail(client, rows["print"].id)
        client.get("/prints", params={"limit": 100})
    finally:
        event.remove(engine, "before_cursor_execute", record)

    writes = [
        sql for sql in statements if sql.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}
    ]
    assert writes == []
    assert (
        db_session.query(type(rows["print"])).filter_by(id=rows["print"].id).one().image_url
        == before
    )
