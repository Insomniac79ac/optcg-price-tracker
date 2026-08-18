"""Serving a verified display image from our own R2 copy (see
app.services.display_image._owned_asset_url).

The 2026-08-15 persistence tranche recorded, on one mapping, that a verified
SNKRDUNK display image now also exists in our R2 bucket under a
content-addressed key - a provider and an object_key, and deliberately no
hostname (app.services.display_image_asset_persist explains why). This
tranche makes GET /prints *use* that record for card_print_id 1 only.

What these tests are really pinning is the set of things that must NOT
change when the origin of one image does:

  * the evidence - source, exact_print_verified, geometry, and every byte of
    match_explanation_json, which no read may write to;
  * every other print, whether it carries an owned_asset of its own, has
    only marketplace evidence, or falls back to canonical Bandai artwork;
  * the response contract - owned_asset is internal and must not leak;
  * the cost of a read - resolution is configuration plus string joining,
    with no R2 client constructed and no request made to anything.

And the URL itself must be *derived*, never stored: the same record under a
different R2_PUBLIC_BASE_URL must serve a different URL, because that is the
whole reason no hostname was persisted.
"""

from __future__ import annotations

import copy

import pytest
from sqlalchemy import event

from app.models import SourceCardMapping
from app.services import object_storage
from app.services.display_image import OWNED_ASSET_PRINT_IDS
from app.settings import settings
from tests.test_prints import (  # noqa: F401  (db_session/client come from conftest)
    make_canonical,
    make_legacy_card,
    make_mapping,
    make_print,
    make_source,
)

PUBLIC_BASE = "https://pub-testbucket.r2.dev"
SNKRDUNK_URL = "https://cdn.snkrdunk.com/upload_bg_removed/TCG-OPC-OP01-0001.webp?size=l"
BANDAI_URL = "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001.png?260630"

SHA256 = "9f4b1c0d5e6a2f7b8c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293"
OBJECT_KEY = f"display-images/sha256/{SHA256[:2]}/{SHA256}.webp"
EXPECTED_URL = f"{PUBLIC_BASE}/{OBJECT_KEY}"

GEOMETRY = {
    "canvas_px": [856, 625],
    "card_bbox_px": [241, 51, 614, 573],  # inclusive corners -> 374 x 523
    "card_px": [374, 523],
}

OWNED_ASSET = {
    "provider": "cloudflare_r2",
    "object_key": OBJECT_KEY,
    "sha256": SHA256,
    "byte_size": 48123,
    "width": 856,
    "height": 625,
    "content_type": "image/webp",
    "cache_control": "public, max-age=31536000, immutable",
    "verified_at": "2026-08-15T09:14:02+00:00",
    "verification_method": "source_private_public_sha256",
}

# The fetch block the 2026-08-13 verification wrote, later completed with a
# full digest by the bootstrap tranche. owned_asset must agree with it.
FETCH = {
    "sha256_prefix": SHA256[:16],
    "sha256": SHA256,
    "sha256_origin": "bootstrap_refetch",
    "bytes": 48123,
    "content_type": "image/webp",
    "final_host": "cdn.snkrdunk.com",
    "http_status": 200,
    "fetched_at": "2026-08-13T10:56:42+00:00",
}

VERIFIED_PAYLOAD = {
    "url": SNKRDUNK_URL,
    "source": "snkrdunk",
    "fetch": FETCH,
    "card_print_id": None,
    "verified_at": "2026-08-13T10:56:42+00:00",
    "verification_method": "offline_image_comparison_vs_bandai_canonical",
    "verification_version": "display-image-v1",
    "exact_print_verified": True,
    "full_card_preserved": True,
    "sample_present": False,
    "overlay_obscures_card": False,
    "classification": "VERIFIED_DISPLAY",
    "geometry": GEOMETRY,
}


def _payload(card_print_id: int, owned_asset=None, **overrides) -> dict:
    payload = copy.deepcopy(VERIFIED_PAYLOAD)
    payload["card_print_id"] = card_print_id
    if owned_asset is not None:
        payload["owned_asset"] = copy.deepcopy(owned_asset)
    payload.update(overrides)
    return payload


@pytest.fixture()
def public_base(monkeypatch):
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", PUBLIC_BASE)
    return PUBLIC_BASE


def _add_print(db_session, index: int, *, image_url=BANDAI_URL):
    """One canonical card + its legacy row + one print, all distinct."""
    code = f"OP01-{index:03d}"
    canonical = make_canonical(db_session, card_code=code, name_en=f"Card {index}")
    legacy = make_legacy_card(db_session, card_code=code)
    print_row = make_print(db_session, canonical, artwork_key=f"art-{index}", image_url=image_url)
    return {"canonical": canonical, "legacy": legacy, "print": print_row}


# The first print id past the allow-list, used for the outside-the-gate case.
# Derived from the allow-list itself so widening it again cannot leave this
# test silently asserting about a print that is now inside.
OUTSIDE_GATE_PRINT_ID = max(OWNED_ASSET_PRINT_IDS) + 1


@pytest.fixture()
def catalogue(db_session):
    """Prints covering every branch of the rule at once:

      1   verified SNKRDUNK evidence + an owned_asset  -> served from R2
      2   verified SNKRDUNK evidence + an owned_asset  -> served from R2
                                                          (also inside the gate)
      3   verified SNKRDUNK evidence, no owned_asset   -> marketplace URL
      4   no mapping at all                            -> Bandai fallback
      21  verified SNKRDUNK evidence + an owned_asset  -> NOT served from R2
                                                          (outside the gate)

    Print 21 is the important one: evidence byte-identical to print 1, and it
    must not move, because an owned_asset existing is never on its own a
    reason to switch origin. Prints 5..20 are filler that carries no mapping,
    so that print 21 really is the id past the allow-list rather than a number
    chosen by hand. Ids are contiguous from 1 because conftest drops and
    recreates the schema for every test, which the assertion states rather
    than assumes.
    """
    snkrdunk = make_source(db_session, "snkrdunk")
    ids = (1, 2, 3, 4)
    rows = {i: _add_print(db_session, i) for i in ids}
    filler = {i: _add_print(db_session, i) for i in range(5, OUTSIDE_GATE_PRINT_ID + 1)}
    rows.update(filler)
    assert [rows[i]["print"].id for i in ids] == [1, 2, 3, 4]
    assert rows[OUTSIDE_GATE_PRINT_ID]["print"].id == OUTSIDE_GATE_PRINT_ID
    assert OUTSIDE_GATE_PRINT_ID not in OWNED_ASSET_PRINT_IDS

    for i, owned in (
        (1, OWNED_ASSET),
        (2, OWNED_ASSET),
        (3, None),
        (OUTSIDE_GATE_PRINT_ID, OWNED_ASSET),
    ):
        make_mapping(
            db_session,
            rows[i]["legacy"],
            snkrdunk,
            rows[i]["print"],
            review_status="approved",
            match_explanation_json={"display_image": _payload(rows[i]["print"].id, owned)},
        )
    return rows


def _detail(client, print_id: int) -> dict:
    response = client.get(f"/prints/{print_id}")
    assert response.status_code == 200
    return response.json()


def _catalogue(client) -> dict[int, dict]:
    response = client.get("/prints", params={"limit": 100})
    assert response.status_code == 200
    return {item["card_print_id"]: item for item in response.json()["items"]}


def _normalize(items: dict[int, dict]) -> dict[int, dict]:
    """market_index.calculated_at is stamped per request, so it differs
    between any two calls regardless of what changed. Blank it out; a
    difference there is not a regression and must not mask a real one."""
    out = copy.deepcopy(items)
    for item in out.values():
        market_index = item.get("market_index")
        if isinstance(market_index, dict) and "calculated_at" in market_index:
            market_index["calculated_at"] = "<per-request>"
    return out


def _stored(db_session, card_print_id: int) -> dict:
    mapping = (
        db_session.query(SourceCardMapping).filter_by(card_print_id=card_print_id).one()
    )
    db_session.refresh(mapping)
    return copy.deepcopy(mapping.match_explanation_json)


class _StatementLog:
    def __init__(self) -> None:
        self.statements: list[str] = []

    @property
    def writes(self) -> list[str]:
        return [
            sql
            for sql in self.statements
            if sql.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}
        ]


@pytest.fixture()
def sql_log(db_session):
    """Every statement the request actually sends to the database."""
    log = _StatementLog()
    engine = db_session.get_bind()

    def _record(conn, cursor, statement, parameters, context, executemany):
        log.statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield log
    finally:
        event.remove(engine, "before_cursor_execute", _record)


# --- the rule itself --------------------------------------------------------


def test_print_1_is_served_from_the_owned_r2_asset(client, catalogue, public_base):
    """R2_PUBLIC_BASE_URL + owned_asset.object_key, exactly."""
    assert _detail(client, 1)["display_image"]["url"] == EXPECTED_URL
    assert _catalogue(client)[1]["display_image"]["url"] == EXPECTED_URL


def test_the_gate_is_an_explicit_allow_list(client, catalogue, public_base):
    """Widened to the twenty migrated prints on 2026-08-18 - but still an
    allow-list. A print outside it carries a byte-identical owned_asset and
    must not move: the record existing is never on its own a reason to switch
    origin."""
    assert OWNED_ASSET_PRINT_IDS == frozenset(range(1, 21))
    assert _detail(client, 1)["display_image"]["url"] == EXPECTED_URL
    assert _detail(client, 2)["display_image"]["url"] == EXPECTED_URL
    assert _detail(client, OUTSIDE_GATE_PRINT_ID)["display_image"]["url"] == SNKRDUNK_URL


def test_the_url_is_derived_from_config_not_stored(client, catalogue, public_base, monkeypatch):
    """Same record, different configured origin, different served URL - which
    is only possible if nothing about the hostname was persisted."""
    assert _detail(client, 1)["display_image"]["url"] == EXPECTED_URL

    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", "https://images.cardpirate.example")
    assert _detail(client, 1)["display_image"]["url"] == (
        f"https://images.cardpirate.example/{OBJECT_KEY}"
    )


def test_no_url_or_hostname_was_ever_persisted(db_session, catalogue):
    """The record the read path consumes holds a key and a provider only."""
    owned = _stored(db_session, 1)["display_image"]["owned_asset"]
    assert owned["object_key"] == OBJECT_KEY
    assert not any("url" in key for key in owned)
    assert not any(
        isinstance(value, str) and ("http" in value or "r2.dev" in value)
        for value in owned.values()
    )


@pytest.mark.parametrize(
    "base, reason",
    [
        (PUBLIC_BASE, "no trailing slash"),
        (PUBLIC_BASE + "/", "one trailing slash"),
        (PUBLIC_BASE + "///", "several trailing slashes"),
        ("  " + PUBLIC_BASE + "  ", "surrounding whitespace"),
    ],
)
def test_exactly_one_slash_joins_base_and_key(client, catalogue, monkeypatch, base, reason):
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", base)
    url = _detail(client, 1)["display_image"]["url"]
    assert url == EXPECTED_URL, reason
    assert "//" not in url.split("://", 1)[1], reason


def test_a_custom_domain_path_prefix_is_preserved(client, catalogue, monkeypatch):
    """A custom domain may serve the bucket under a path; the key appends to
    it rather than replacing it."""
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", "https://cdn.example.com/cards/")
    assert _detail(client, 1)["display_image"]["url"] == f"https://cdn.example.com/cards/{OBJECT_KEY}"


# --- everything that must not change ----------------------------------------


def test_only_allow_listed_prints_change_their_display_url(client, catalogue, monkeypatch):
    """The whole catalogue, before and after the owned assets become usable.
    Only the `url` of allow-listed prints that carry an owned_asset may
    differ - every other print, and every other field, byte for byte."""
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", None)
    before = _normalize(_catalogue(client))

    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", PUBLIC_BASE)
    after = _normalize(_catalogue(client))

    switched = {1, 2}
    assert set(before) == set(after)
    for print_id in sorted(set(before) - switched):
        assert after[print_id] == before[print_id], f"print {print_id} must be untouched"

    for print_id in sorted(switched):
        expected = copy.deepcopy(before[print_id])
        expected["display_image"]["url"] = EXPECTED_URL
        # The provenance flag tracks the URL branch, so it flips with it -
        # unconfigured R2 means the source URL was served, not an owned asset.
        assert before[print_id]["display_image"]["owned_asset_selected"] is False
        expected["display_image"]["owned_asset_selected"] = True
        assert after[print_id] == expected


def test_source_and_exact_print_verified_are_unchanged(client, catalogue, public_base):
    """The image is the same verified image; only where it is hosted moved."""
    display = _detail(client, 1)["display_image"]
    assert display["source"] == "snkrdunk"
    assert display["exact_print_verified"] is True


def test_geometry_is_unchanged(client, catalogue, public_base):
    display = _detail(client, 1)["display_image"]
    assert display["geometry"] == {
        "canvas_px": {"width": 856, "height": 625},
        "card_bbox_px": {"x": 241, "y": 51, "width": 374, "height": 523},
    }


def test_canonical_identity_fields_are_unchanged(client, catalogue, public_base):
    detail = _detail(client, 1)
    assert detail["image_url"] == BANDAI_URL
    assert detail["artwork_key"] == "art-1"


def test_bandai_fallback_prints_are_untouched(client, catalogue, public_base):
    """A print with no marketplace evidence never reaches this code path."""
    assert _detail(client, 4)["display_image"] == {
        "url": BANDAI_URL,
        "source": "bandai",
        "exact_print_verified": True,
        "owned_asset_selected": False,
        "geometry": None,
    }


def _walk(node):
    """Every (key, value) pair anywhere in a decoded JSON response."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def test_owned_asset_does_not_leak_into_the_response(client, catalogue, public_base):
    """Internal storage bookkeeping - digest, byte size, cache policy, when
    and how it was verified - is not part of the public contract. Only the
    URL crosses over, and only as a URL.

    Checked structurally rather than by substring: the object key is *in*
    the served URL by design, and it happens to contain the words "sha256"
    and the digest, so a text search would be meaningless here.
    """
    responses = [client.get("/prints", params={"limit": 100}).json(), _detail(client, 1)]
    internal = {"owned_asset", "object_key", "sha256", "byte_size", "cache_control", "provider"}
    for response in responses:
        leaked = {key for key, _ in _walk(response)} & internal
        assert not leaked, f"internal owned_asset fields leaked: {sorted(leaked)}"

    body = client.get("/prints/1").text
    assert OWNED_ASSET["cache_control"] not in body
    assert OWNED_ASSET["verification_method"] not in body
    assert str(OWNED_ASSET["byte_size"]) not in body

    assert set(_detail(client, 1)["display_image"]) == {
        "url",
        "source",
        "exact_print_verified",
        "owned_asset_selected",
        "geometry",
    }


# --- fallback: never emit a broken URL --------------------------------------


def test_missing_public_base_url_falls_back_to_the_source_image(client, catalogue, monkeypatch):
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", None)
    assert _detail(client, 1)["display_image"]["url"] == SNKRDUNK_URL


@pytest.mark.parametrize(
    "base, reason",
    [
        ("", "empty"),
        ("   ", "whitespace only"),
        ("http://pub-testbucket.r2.dev", "not https"),
        ("https:///path-only", "no hostname"),
        ("https://pub.r2.dev/?v=1", "carries a query string"),
        ("https://pub.r2.dev/#frag", "carries a fragment"),
        ("not-a-url", "not a URL at all"),
    ],
)
def test_malformed_public_base_url_falls_back_to_the_source_image(
    client, catalogue, monkeypatch, base, reason
):
    monkeypatch.setattr(settings, "R2_PUBLIC_BASE_URL", base)
    assert _detail(client, 1)["display_image"]["url"] == SNKRDUNK_URL, reason


@pytest.mark.parametrize(
    "owned, reason",
    [
        ("not-an-object", "owned_asset is a string"),
        ([], "owned_asset is a list"),
        (None, "owned_asset is null"),
        ({}, "owned_asset is empty"),
        ({"provider": "cloudflare_r2"}, "no object_key"),
        ({"provider": "cloudflare_r2", "object_key": ""}, "empty object_key"),
        ({"provider": "cloudflare_r2", "object_key": "   "}, "blank object_key"),
        ({"provider": "cloudflare_r2", "object_key": 12345}, "object_key is not a string"),
        ({"provider": "cloudflare_r2", "object_key": None}, "object_key is null"),
        ({"provider": "s3", "object_key": OBJECT_KEY}, "another provider"),
        ({"object_key": OBJECT_KEY}, "no provider"),
        ({"provider": "cloudflare_r2", "object_key": "/leading-slash.webp"}, "key escapes the base"),
        ({"provider": "cloudflare_r2", "object_key": "a/../../etc/passwd"}, "key has .. segments"),
        ({"provider": "cloudflare_r2", "object_key": "back\\slash.webp"}, "key has a backslash"),
        ({"provider": "cloudflare_r2", "object_key": "ctrl\nchar.webp"}, "key has a control char"),
    ],
)
def test_malformed_owned_asset_falls_back_to_the_source_image(
    client, db_session, catalogue, public_base, owned, reason
):
    mapping = db_session.query(SourceCardMapping).filter_by(card_print_id=1).one()
    explanation = copy.deepcopy(mapping.match_explanation_json)
    explanation["display_image"]["owned_asset"] = owned
    mapping.match_explanation_json = explanation
    db_session.commit()

    display = _detail(client, 1)["display_image"]
    assert display["url"] == SNKRDUNK_URL, reason
    # A bad owned_asset must cost nothing else: the image still renders, with
    # its geometry, from the evidence that was always there.
    assert display["source"] == "snkrdunk", reason
    assert display["geometry"] is not None, reason


def test_unverified_evidence_is_still_rejected_even_with_an_owned_asset(
    client, db_session, catalogue, public_base
):
    """An owned_asset can never rescue evidence that fails the display
    contract - the mirrored bytes of a bad image are still a bad image."""
    mapping = db_session.query(SourceCardMapping).filter_by(card_print_id=1).one()
    explanation = copy.deepcopy(mapping.match_explanation_json)
    explanation["display_image"]["overlay_obscures_card"] = True
    mapping.match_explanation_json = explanation
    db_session.commit()

    assert _detail(client, 1)["display_image"] == {
        "url": BANDAI_URL,
        "source": "bandai",
        "exact_print_verified": True,
        "owned_asset_selected": False,
        "geometry": None,
    }


# --- cost: no writes, no network --------------------------------------------


def test_serving_the_owned_asset_writes_nothing(client, db_session, catalogue, public_base, sql_log):
    before = _stored(db_session, 1)
    sql_log.statements.clear()

    assert _detail(client, 1)["display_image"]["url"] == EXPECTED_URL
    assert _catalogue(client)[1]["display_image"]["url"] == EXPECTED_URL

    assert sql_log.writes == [], f"read path emitted writes: {sql_log.writes}"
    assert _stored(db_session, 1) == before


def test_serving_the_owned_asset_makes_no_r2_call(client, catalogue, public_base, monkeypatch):
    """URL resolution only: no client is constructed, so not even a
    credentialed one is required, and no bucket operation is issued."""

    def boom(*args, **kwargs):  # pragma: no cover - a call here fails the test
        raise AssertionError("GET /prints must not touch R2")

    monkeypatch.setattr(object_storage.boto3, "client", boom)
    monkeypatch.setattr(object_storage.R2ObjectStorage, "from_settings", boom)
    monkeypatch.setattr(object_storage.R2ObjectStorage, "head_object", boom)
    monkeypatch.setattr(object_storage.R2ObjectStorage, "get_object_bytes", boom)
    monkeypatch.setattr(object_storage.R2ObjectStorage, "put_object", boom)
    # The two secret settings stay unset: a read path that needed them would
    # be over-privileged, and this asserts it does not.
    monkeypatch.setattr(settings, "R2_ACCESS_KEY_ID", None)
    monkeypatch.setattr(settings, "R2_SECRET_ACCESS_KEY", None)
    monkeypatch.setattr(settings, "R2_ACCOUNT_ID", None)
    monkeypatch.setattr(settings, "R2_BUCKET_NAME", None)

    assert _detail(client, 1)["display_image"]["url"] == EXPECTED_URL


# --- local consistency with the verified display evidence -------------------
#
# This read path makes no network call, so it can never ask R2 whether the
# object is really there. What it can do is refuse a record that disagrees
# with the display evidence sitting beside it in the same payload - because a
# record that disagrees is describing some other object, and swapping the URL
# to it would put the wrong picture, or no picture, in front of a collector.
#
# Every case below is a record that would pass a shape-only check.

OTHER_DIGEST = "1234567890abcdef" * 4  # 64 hex, valid, and not our image


def _serve_owned(db_session, **changes):
    """Rewrite print 1's owned_asset with `changes` applied."""
    mapping = db_session.query(SourceCardMapping).filter_by(card_print_id=1).one()
    explanation = copy.deepcopy(mapping.match_explanation_json)
    owned = explanation["display_image"]["owned_asset"]
    for name, value in changes.items():
        if value is _REMOVE:
            owned.pop(name, None)
        else:
            owned[name] = value
    mapping.match_explanation_json = explanation
    db_session.commit()


class _Remove:
    def __repr__(self) -> str:  # keeps parametrize ids readable
        return "<absent>"


_REMOVE = _Remove()


@pytest.mark.parametrize(
    "changes, reason",
    [
        # --- the digest ---
        ({"sha256": "not-a-digest"}, "sha256 is not hex at all"),
        ({"sha256": SHA256[:32]}, "sha256 is truncated"),
        ({"sha256": SHA256.upper()}, "sha256 is uppercase, not the stored form"),
        ({"sha256": SHA256 + "ff"}, "sha256 is too long"),
        ({"sha256": SHA256[:-1] + "g"}, "sha256 has a non-hex character"),
        (
            {"sha256": OTHER_DIGEST, "object_key": f"display-images/sha256/12/{OTHER_DIGEST}.webp"},
            "a perfectly valid digest and matching key - for a different image",
        ),
        # --- the key ---
        (
            {"object_key": f"display-images/sha256/12/{OTHER_DIGEST}.webp"},
            "valid-looking key naming another digest",
        ),
        (
            {"object_key": f"display-images/sha256/00/{SHA256}.webp"},
            "right digest, wrong fan-out directory",
        ),
        (
            {"object_key": f"display-images/{SHA256[:2]}/{SHA256}.webp"},
            "right digest, wrong prefix",
        ),
        (
            {"object_key": f"display-images/sha256/{SHA256[:2]}/{SHA256}.png"},
            "extension disagrees with the recorded content type",
        ),
        (
            {"object_key": f"display-images/sha256/{SHA256[:2]}/{SHA256}"},
            "no extension at all",
        ),
        (
            {"object_key": f"display-images/sha256/{SHA256[:2]}/{SHA256}.exe"},
            "extension outside the allow-list",
        ),
        # --- the byte size ---
        ({"byte_size": 48124}, "byte_size off by one from the verified fetch"),
        ({"byte_size": 0}, "byte_size zero"),
        ({"byte_size": -48123}, "byte_size negative"),
        ({"byte_size": "48123"}, "byte_size is a string"),
        ({"byte_size": True}, "byte_size is a bool"),
        # --- the dimensions ---
        ({"width": 855}, "width disagrees with geometry canvas_px"),
        ({"height": 624}, "height disagrees with geometry canvas_px"),
        ({"width": 625, "height": 856}, "width and height transposed"),
        ({"width": 0}, "width zero"),
        ({"height": None}, "height is null"),
        # --- the verification method ---
        ({"verification_method": _REMOVE}, "verification_method missing"),
        ({"verification_method": "sha256_only"}, "a weaker verification method"),
        ({"verification_method": ""}, "verification_method blank"),
        ({"verification_method": None}, "verification_method is null"),
        # --- required fields absent ---
        ({"sha256": _REMOVE}, "sha256 missing"),
        ({"byte_size": _REMOVE}, "byte_size missing"),
        ({"width": _REMOVE}, "width missing"),
        ({"height": _REMOVE}, "height missing"),
        ({"object_key": _REMOVE}, "object_key missing"),
        ({"provider": _REMOVE}, "provider missing"),
        ({"content_type": _REMOVE}, "content_type missing"),
        ({"cache_control": _REMOVE}, "cache_control missing"),
        ({"verified_at": _REMOVE}, "verified_at missing"),
        # --- the content type ---
        ({"content_type": "image/png"}, "content_type disagrees with the key extension"),
        ({"content_type": "text/html"}, "content_type is not an image at all"),
    ],
)
def test_inconsistent_owned_asset_falls_back_to_the_source_image(
    client, db_session, catalogue, public_base, changes, reason
):
    _serve_owned(db_session, **changes)

    display = _detail(client, 1)["display_image"]
    assert display["url"] == SNKRDUNK_URL, reason
    # Falling back must cost nothing else - the verified image still renders,
    # from the same source, with its geometry intact.
    assert display["source"] == "snkrdunk", reason
    assert display["exact_print_verified"] is True, reason
    assert display["geometry"] == {
        "canvas_px": {"width": 856, "height": 625},
        "card_bbox_px": {"x": 241, "y": 51, "width": 374, "height": 523},
    }, reason


@pytest.mark.parametrize(
    "fetch_changes, reason",
    [
        ({"sha256": OTHER_DIGEST}, "owned_asset digest != display_image.fetch.sha256"),
        ({"sha256": _REMOVE}, "the evidence carries no full digest to compare against"),
        ({"sha256": None}, "fetch.sha256 is null"),
        ({"bytes": 99999}, "owned_asset byte_size != the verified fetched byte size"),
        ({"bytes": _REMOVE}, "the evidence records no byte size"),
        ({"bytes": "48123"}, "fetch.bytes is a string"),
    ],
)
def test_owned_asset_must_match_the_fetch_evidence(
    client, db_session, catalogue, public_base, fetch_changes, reason
):
    """The comparison is against the evidence, not against itself - moving the
    evidence must break the match just as surely as moving the record."""
    mapping = db_session.query(SourceCardMapping).filter_by(card_print_id=1).one()
    explanation = copy.deepcopy(mapping.match_explanation_json)
    fetch = explanation["display_image"]["fetch"]
    for name, value in fetch_changes.items():
        if value is _REMOVE:
            fetch.pop(name, None)
        else:
            fetch[name] = value
    mapping.match_explanation_json = explanation
    db_session.commit()

    display = _detail(client, 1)["display_image"]
    assert display["url"] == SNKRDUNK_URL, reason
    assert display["source"] == "snkrdunk", reason
    assert display["geometry"] is not None, reason


def test_a_missing_fetch_block_blocks_the_switch(client, db_session, catalogue, public_base):
    """Nothing to compare against is not a pass."""
    mapping = db_session.query(SourceCardMapping).filter_by(card_print_id=1).one()
    explanation = copy.deepcopy(mapping.match_explanation_json)
    del explanation["display_image"]["fetch"]
    mapping.match_explanation_json = explanation
    db_session.commit()

    assert _detail(client, 1)["display_image"]["url"] == SNKRDUNK_URL


def test_geometry_and_owned_dimensions_must_agree_from_either_side(
    client, db_session, catalogue, public_base
):
    """Moving the canvas rather than the record breaks the match too - and
    because the client positions the card box inside canvas_px, serving an
    object of a different size would point that box at the wrong pixels."""
    mapping = db_session.query(SourceCardMapping).filter_by(card_print_id=1).one()
    explanation = copy.deepcopy(mapping.match_explanation_json)
    explanation["display_image"]["geometry"]["canvas_px"] = [900, 700]
    mapping.match_explanation_json = explanation
    db_session.commit()

    display = _detail(client, 1)["display_image"]
    assert display["url"] == SNKRDUNK_URL
    # That canvas no longer contains the recorded card box, so geometry is
    # dropped by the pre-existing validation - the image itself still serves.
    assert display["source"] == "snkrdunk"


def test_the_key_is_rederived_with_the_shared_rule(client, catalogue, public_base):
    """The accepted key is exactly what the mirror's own key function
    produces - asserted against that function, not against a literal, so the
    reader and the writer cannot drift apart."""
    from app.services.display_image_mirror import object_key as mirror_object_key

    assert OBJECT_KEY == mirror_object_key(SHA256, "webp")
    assert _detail(client, 1)["display_image"]["url"] == f"{PUBLIC_BASE}/{OBJECT_KEY}"


def test_consistency_checks_make_no_db_write_or_network_call(
    client, db_session, catalogue, public_base, sql_log, monkeypatch
):
    """A rejected record must be as cheap and as read-only as an accepted one."""

    def boom(*args, **kwargs):  # pragma: no cover - a call here fails the test
        raise AssertionError("validation must not touch R2")

    _serve_owned(db_session, byte_size=48124)
    before = _stored(db_session, 1)
    monkeypatch.setattr(object_storage.boto3, "client", boom)
    monkeypatch.setattr(object_storage.R2ObjectStorage, "from_settings", boom)
    monkeypatch.setattr(object_storage.R2ObjectStorage, "head_object", boom)
    sql_log.statements.clear()

    assert _detail(client, 1)["display_image"]["url"] == SNKRDUNK_URL

    assert sql_log.writes == [], f"read path emitted writes: {sql_log.writes}"
    assert _stored(db_session, 1) == before


@pytest.mark.parametrize(
    "digest, reason",
    [
        ("not-a-digest", "not hex"),
        (SHA256.upper(), "uppercase - not the form the digest is stored in"),
        (SHA256[:32], "truncated"),
        (SHA256 + "ab", "over-long"),
        ("", "empty"),
    ],
)
def test_the_digest_itself_must_be_a_full_sha256(
    client, db_session, catalogue, public_base, digest, reason
):
    """Isolates the digest-format rule from every other check.

    The evidence and the key are moved onto the *same* bad value here, so a
    record built entirely around a malformed digest is internally consistent
    and every downstream comparison would agree with it. Only the requirement
    that a SHA-256 be 64 lowercase hex characters can reject this - which is
    the point: a content-addressed key derived from a non-digest addresses
    nothing.
    """
    mapping = db_session.query(SourceCardMapping).filter_by(card_print_id=1).one()
    explanation = copy.deepcopy(mapping.match_explanation_json)
    display = explanation["display_image"]
    display["fetch"]["sha256"] = digest
    display["owned_asset"]["sha256"] = digest
    display["owned_asset"]["object_key"] = f"display-images/sha256/{digest[:2]}/{digest}.webp"
    mapping.match_explanation_json = explanation
    db_session.commit()

    assert _detail(client, 1)["display_image"]["url"] == SNKRDUNK_URL, reason
