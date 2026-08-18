"""Serving verified official Card List v3 evidence (the 2026-08-18 migration).

The approved display policy accepts the official SAMPLE overlay, and the
official card list ranks first. What these tests pin is that the relaxation is
narrow and the fallback chain still works print by print:

  * a SAMPLE may be *present*, and only when the evidence names the policy
    that accepts it - the flag alone is malformed and fails closed;
  * a SAMPLE on v1/v2 evidence still disqualifies, so the older contracts are
    not loosened by the new one;
  * an overlay that *obscures* the card fails in every version;
  * priority orders only sources that already qualify: a broken official
    mapping drops to Yuyu-Tei, and a broken Yuyu-Tei drops to SNKRDUNK,
    rather than the print failing;
  * the official assets are 600x838 and are described truthfully as
    full-frame, not forced into the 500x700 Yuyu-Tei geometry;
  * none of it costs an R2 call or a database write on a read.
"""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import event

from app.services import object_storage
from app.services.display_image import (
    DISPLAY_SOURCE_PRIORITY,
    OFFICIAL_SAMPLE_ACCEPTED,
    VERIFICATION_VERSION_V3,
)
from app.services.display_image_object_key import object_key
from app.services.official_display_evidence import (
    VerifiedOfficialAsset,
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
from tests.test_yuyutei_display_serving import (
    CACHE_CONTROL,
    YUYU_KEY,
    add_print,
    detail,
    snkrdunk_payload,
    yuyutei_payload,
)

PUBLIC_BASE = "https://pub-testbucket.r2.dev"
OFFICIAL_URL = "https://www.onepiece-cardgame.com/images/cardlist/card/OP04-044_p1.png?260806"
OFFICIAL_SHA = "78143df52ddbe696579e8066a0a870952b675f7f48a9e132d46b721155320581"
OFFICIAL_KEY = object_key(OFFICIAL_SHA, "png")
OFFICIAL_BYTES = 273948


def official_asset(card_print_id: int, **overrides) -> VerifiedOfficialAsset:
    base = dict(
        card_print_id=card_print_id,
        variant_id="OP04-044_p1",
        source_url=OFFICIAL_URL,
        sha256=OFFICIAL_SHA,
        byte_size=OFFICIAL_BYTES,
        width=600,
        height=838,
        content_type="image/png",
        cache_control=CACHE_CONTROL,
        object_key=OFFICIAL_KEY,
    )
    base.update(overrides)
    return VerifiedOfficialAsset(**base)


def official_payload(card_print_id: int, **overrides) -> dict:
    payload = build_display_image(official_asset(card_print_id), "2026-08-18T11:00:00+00:00")
    payload.update(overrides)
    return payload


@pytest.fixture()
def public_base(monkeypatch):
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", PUBLIC_BASE)
    return PUBLIC_BASE


def serve(db_session, client, payloads: dict[str, dict], print_id: int = 1) -> dict:
    """One print carrying a mapping per named source, then read it back."""
    rows = add_print(db_session, print_id)
    for source, payload in payloads.items():
        make_mapping(
            db_session,
            rows["legacy"],
            make_source(db_session, source),
            rows["print"],
            review_status="approved",
            match_explanation_json={"display_image": payload},
        )
    return detail(client, rows["print"].id)["display_image"]


# --- the v3 contract --------------------------------------------------------


def test_official_exact_asset_qualifies(db_session, client, public_base):
    image = serve(db_session, client, {"bandai": official_payload(1)})
    assert image["source"] == "bandai"
    assert image["exact_print_verified"] is True
    assert image["url"] == f"{PUBLIC_BASE}/{OFFICIAL_KEY}"


def test_accepted_sample_overlay_does_not_disqualify(db_session, client, public_base):
    """The whole point of v3: SAMPLE present, and still served."""
    payload = official_payload(1)
    assert payload["sample_present"] is True
    assert payload["overlay_policy"] == OFFICIAL_SAMPLE_ACCEPTED == "official_sample_accepted"
    assert serve(db_session, client, {"bandai": payload})["source"] == "bandai"


def test_sample_present_without_the_policy_marker_fails(db_session, client, public_base):
    """A SAMPLE is never accepted implicitly - the flag alone is malformed."""
    payload = official_payload(1)
    del payload["overlay_policy"]
    assert serve(db_session, client, {"bandai": payload})["source"] == "bandai"
    # falls back to the canonical hotlink, not the owned R2 asset
    image = serve(db_session, client, {"bandai": official_payload(2)}, print_id=2)
    assert image["url"].startswith(PUBLIC_BASE)


@pytest.mark.parametrize("policy", ["", "accepted", "retailer_overlay_accepted", None])
def test_a_wrong_overlay_policy_value_fails(db_session, client, public_base, policy):
    payload = official_payload(1, overlay_policy=policy)
    assert serve(db_session, client, {"bandai": payload})["source"] == "bandai"


def test_v1_and_v2_evidence_still_reject_a_sample(db_session, client, public_base):
    """The new contract must not loosen the older ones."""
    v2 = yuyutei_payload(1)
    v2["sample_present"] = True
    assert serve(db_session, client, {"yuyutei": v2})["source"] == "bandai", "v2 + SAMPLE must fail"

    v1 = snkrdunk_payload(2)
    v1["sample_present"] = True
    image = serve(db_session, client, {"snkrdunk": v1}, print_id=2)
    assert image["source"] == "bandai", "v1 + SAMPLE must fail"


def test_an_overlay_that_obscures_the_card_still_fails(db_session, client, public_base):
    payload = official_payload(1, overlay_obscures_card=True)
    assert serve(db_session, client, {"bandai": payload})["source"] == "bandai"
    assert serve(db_session, client, {"bandai": official_payload(2)}, print_id=2)[
        "url"
    ].startswith(PUBLIC_BASE)


def test_wrong_exact_print_identity_still_fails(db_session, client, public_base):
    """Evidence claiming another print can never be read onto this one."""
    payload = official_payload(999)
    assert serve(db_session, client, {"bandai": payload})["source"] == "bandai"
    assert serve(db_session, client, {"bandai": official_payload(2)}, print_id=2)[
        "url"
    ].startswith(PUBLIC_BASE)


def test_not_exact_print_verified_fails(db_session, client, public_base):
    payload = official_payload(1, exact_print_verified=False)
    image = serve(db_session, client, {"bandai": payload})
    assert image["url"] == "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001.png?260630"


# --- priority and fallback --------------------------------------------------


def test_official_ranks_first():
    assert DISPLAY_SOURCE_PRIORITY == ("bandai", "yuyutei", "snkrdunk")


def test_official_beats_a_valid_yuyutei(db_session, client, public_base):
    image = serve(
        db_session,
        client,
        {"yuyutei": yuyutei_payload(1), "bandai": official_payload(1)},
    )
    assert image["source"] == "bandai"
    assert image["url"] == f"{PUBLIC_BASE}/{OFFICIAL_KEY}"


def test_invalid_official_falls_back_to_yuyutei(db_session, client, public_base):
    """A broken official mapping must not fail the print."""
    broken = official_payload(1, overlay_obscures_card=True)
    image = serve(db_session, client, {"yuyutei": yuyutei_payload(1), "bandai": broken})
    assert image["source"] == "yuyutei"
    assert image["url"] == f"{PUBLIC_BASE}/{YUYU_KEY}"


def test_invalid_official_and_invalid_yuyutei_falls_back_to_snkrdunk(
    db_session, client, public_base
):
    broken_official = official_payload(1, exact_print_verified=False)
    broken_yuyu = yuyutei_payload(1, classification="CROPPED_OR_OBSCURED")
    image = serve(
        db_session,
        client,
        {
            "snkrdunk": snkrdunk_payload(1),
            "yuyutei": broken_yuyu,
            "bandai": broken_official,
        },
    )
    assert image["source"] == "snkrdunk"


def test_all_three_invalid_falls_back_to_canonical(db_session, client, public_base):
    image = serve(
        db_session,
        client,
        {
            "snkrdunk": snkrdunk_payload(1, exact_print_verified=False),
            "yuyutei": yuyutei_payload(1, exact_print_verified=False),
            "bandai": official_payload(1, exact_print_verified=False),
        },
    )
    assert image["source"] == "bandai"
    assert image["geometry"] is None, "the canonical fallback carries no geometry"


# --- geometry ---------------------------------------------------------------


def test_official_geometry_is_full_frame_600x838(db_session, client, public_base):
    image = serve(db_session, client, {"bandai": official_payload(1)})
    assert image["geometry"] == {
        "canvas_px": {"width": 600, "height": 838},
        "card_bbox_px": {"x": 0, "y": 0, "width": 600, "height": 838},
    }


def test_official_geometry_is_not_forced_into_the_yuyutei_shape(db_session, client, public_base):
    image = serve(db_session, client, {"bandai": official_payload(1)})
    assert image["geometry"]["canvas_px"] != {"width": 500, "height": 700}


def test_owned_asset_dimensions_must_match_the_geometry(db_session, client, public_base):
    payload = official_payload(1)
    payload["owned_asset"]["width"] = 500
    payload["owned_asset"]["height"] = 700
    image = serve(db_session, client, {"bandai": payload})
    assert image["url"] == OFFICIAL_URL, "must keep the source URL, not serve R2"


@pytest.mark.parametrize(
    "mutate, reason",
    [
        (lambda o: o.update(sha256="0" * 64), "digest is not the verified image's"),
        (lambda o: o.update(byte_size=1), "byte size disagrees with the fetch evidence"),
        (lambda o: o.update(object_key=object_key("0" * 64, "png")), "key is for another digest"),
        (lambda o: o.update(content_type="image/webp"), "content type contradicts the extension"),
    ],
)
def test_a_disagreeing_owned_asset_keeps_the_source_url(
    db_session, client, public_base, mutate, reason
):
    payload = official_payload(1)
    mutate(payload["owned_asset"])
    image = serve(db_session, client, {"bandai": payload})
    assert image["url"] == OFFICIAL_URL, reason
    assert image["source"] == "bandai", reason


def test_every_migrated_print_serves_its_own_official_asset(db_session, client, public_base):
    """All twenty, each with a distinct digest and 600x838 full-frame geometry."""
    official = make_source(db_session, "bandai")
    expected = {}
    for index in range(1, 21):
        rows = add_print(db_session, index)
        digest = f"{index:02x}" * 32
        asset = official_asset(
            rows["print"].id,
            sha256=digest,
            object_key=object_key(digest, "png"),
            byte_size=200000 + index,
            variant_id=f"OP04-{index:03d}",
        )
        make_mapping(
            db_session,
            rows["legacy"],
            official,
            rows["print"],
            review_status="approved",
            match_explanation_json={
                "display_image": build_display_image(asset, "2026-08-18T11:00:00+00:00")
            },
        )
        expected[rows["print"].id] = f"{PUBLIC_BASE}/{object_key(digest, 'png')}"

    assert sorted(expected) == list(range(1, 21))
    for print_id, url in expected.items():
        image = detail(client, print_id)["display_image"]
        assert image["url"] == url, print_id
        assert image["source"] == "bandai", print_id
        assert image["geometry"]["canvas_px"] == {"width": 600, "height": 838}, print_id


# --- cost of a read ---------------------------------------------------------


def test_serving_an_official_owned_asset_makes_no_r2_call(
    db_session, client, public_base, monkeypatch
):
    def boom(*args, **kwargs):
        raise AssertionError("R2 was contacted while serving a read")

    monkeypatch.setattr(object_storage.boto3, "client", boom)
    monkeypatch.setattr(object_storage.R2ObjectStorage, "from_settings", boom)
    monkeypatch.setattr(object_storage.R2ObjectStorage, "head_object", boom)
    monkeypatch.setattr(object_storage.R2ObjectStorage, "get_object_bytes", boom)
    monkeypatch.setattr(object_storage.R2ObjectStorage, "put_object", boom)

    assert serve(db_session, client, {"bandai": official_payload(1)})["url"] == (
        f"{PUBLIC_BASE}/{OFFICIAL_KEY}"
    )


def test_serving_writes_nothing_and_leaves_identity_untouched(db_session, client, public_base):
    rows = add_print(db_session, 1)
    make_mapping(
        db_session,
        rows["legacy"],
        make_source(db_session, "bandai"),
        rows["print"],
        review_status="approved",
        match_explanation_json={"display_image": official_payload(rows["print"].id)},
    )
    print_type = type(rows["print"])
    before = copy.deepcopy(
        (rows["print"].image_url, rows["print"].artwork_key, rows["print"].treatment)
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
        sql
        for sql in statements
        if sql.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}
    ]
    assert writes == []
    row = db_session.query(print_type).filter_by(id=rows["print"].id).one()
    assert (row.image_url, row.artwork_key, row.treatment) == before


# --- owned_asset_selected: which branch supplied the URL ---------------------


def test_owned_official_asset_reports_owned_asset_selected(db_session, client, public_base):
    """source stays "bandai"; the new flag is what says it is ours."""
    image = serve(db_session, client, {"bandai": official_payload(1)})
    assert image["source"] == "bandai"
    assert image["owned_asset_selected"] is True


def test_owned_yuyutei_asset_reports_owned_asset_selected(db_session, client, public_base):
    image = serve(db_session, client, {"yuyutei": yuyutei_payload(1)})
    assert image["source"] == "yuyutei"
    assert image["owned_asset_selected"] is True


def test_canonical_bandai_fallback_reports_not_selected(db_session, client, public_base):
    """Same `source` string as an owned official asset, opposite provenance -
    the exact ambiguity this field resolves."""
    rows = add_print(db_session, 1)
    image = detail(client, rows["print"].id)["display_image"]
    assert image["source"] == "bandai"
    assert image["owned_asset_selected"] is False


def test_invalid_owned_evidence_falling_back_to_canonical_reports_not_selected(
    db_session, client, public_base
):
    image = serve(db_session, client, {"bandai": official_payload(1, exact_print_verified=False)})
    assert image["source"] == "bandai"
    assert image["owned_asset_selected"] is False


def test_a_verified_source_url_without_an_owned_asset_is_not_selected(
    db_session, client, public_base
):
    """Verified evidence, but nothing mirrored: the source URL is served."""
    payload = official_payload(1)
    del payload["owned_asset"]
    image = serve(db_session, client, {"bandai": payload})
    assert image["source"] == "bandai"
    assert image["owned_asset_selected"] is False
    assert image["url"] == OFFICIAL_URL


def test_a_disagreeing_owned_asset_is_not_selected(db_session, client, public_base):
    payload = official_payload(1)
    payload["owned_asset"]["sha256"] = "0" * 64
    image = serve(db_session, client, {"bandai": payload})
    assert image["owned_asset_selected"] is False
    assert image["url"] == OFFICIAL_URL


def test_the_flag_never_changes_the_source_value(db_session, client, public_base):
    """Provenance metadata only: every source keeps its own name."""
    cases = {
        "bandai": (official_payload(1), "bandai"),
        "yuyutei": (yuyutei_payload(2), "yuyutei"),
        "snkrdunk": (snkrdunk_payload(3), "snkrdunk"),
    }
    for index, (source, (payload, expected)) in enumerate(cases.items(), start=1):
        image = serve(db_session, client, {source: payload}, print_id=index)
        assert image["source"] == expected
        assert isinstance(image["owned_asset_selected"], bool)
