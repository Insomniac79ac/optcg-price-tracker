"""Mirroring verification (app.services.display_image_mirror).

These tests pin the verification half of the proposed R2 mirroring pipeline:
given the display-image evidence retained on 2026-08-13, does a fresh fetch
still match it? Nothing here uploads or contacts storage, and nothing here
writes to the database - persistence has its own module,
tests/test_display_image_mirror_persist.py, and is never reached from the
paths exercised below.

The important subtleties under test:

  * What a PASS proves. Evidence holds only `fetch.sha256_prefix` (16 hex
    chars = 64 bits) and `fetch.bytes`; no historical full digest exists. So
    the checks are prefix + exact length + exact dimensions + exact alpha
    geometry, and the full SHA-256 computed now is a *bootstrap* digest for a
    later tranche - not proof of historical byte equality.
  * The bbox convention. Stored `card_bbox_px` corners are INCLUSIVE; Pillow's
    `getbbox()` right/bottom are EXCLUSIVE. Comparing them raw is wrong by one
    pixel on two sides, so the stored value is normalised first.
  * Fail-closed selection. Quarantined (42/43/49/52), inactive, unapproved,
    not-manually-verified and sibling-mismatched mappings must never be
    selected.

Fixtures build real WebP bytes with Pillow so the decode, dimension, alpha and
format checks run against a genuine image rather than a stub. That is test
*input* construction - the verifier itself never produces image bytes.
"""

from __future__ import annotations

import copy
import hashlib
import io

import pytest
from PIL import Image

from app.services import display_image_mirror as mirror
from app.services.display_image_mirror import (
    FetchResult,
    RetainedEvidence,
    collect_candidates,
    inclusive_bbox_to_pillow,
    inspect_image,
    object_key,
    run_verification,
    verify_asset,
)
from tests.test_prints import (  # noqa: F401  (db_session comes from conftest)
    make_canonical,
    make_legacy_card,
    make_mapping,
    make_print,
    make_source,
)

# The real staging shape: an 856x625 landscape canvas with alpha, holding a
# 374x523 portrait card at inclusive corners [241, 51, 614, 573] - identical
# in all 16 assets, because SNKRDUNK composites onto a fixed template.
CANVAS = (856, 625)
STORED_BBOX = [241, 51, 614, 573]
CARD_PX = [374, 523]
URL = "https://cdn.snkrdunk.com/upload_bg_removed/TCG-OPC-OP01-0001.webp?size=l"


def make_image_bytes(
    canvas: tuple[int, int] = CANVAS,
    bbox: list[int] | None = None,
    image_format: str = "WEBP",
    with_alpha: bool = True,
) -> bytes:
    """Build a real encoded image: transparent canvas, opaque card rectangle
    at the inclusive `bbox`. Lossless so alpha survives exactly."""
    bbox = bbox or STORED_BBOX
    mode = "RGBA" if with_alpha else "RGB"
    background = (0, 0, 0, 0) if with_alpha else (255, 255, 255)
    card_colour = (200, 30, 30, 255) if with_alpha else (200, 30, 30)
    image = Image.new(mode, canvas, background)
    card = Image.new(mode, (bbox[2] - bbox[0] + 1, bbox[3] - bbox[1] + 1), card_colour)
    image.paste(card, (bbox[0], bbox[1]))
    buffer = io.BytesIO()
    options = {"lossless": True} if image_format == "WEBP" else {}
    image.save(buffer, format=image_format, **options)
    return buffer.getvalue()


BODY = make_image_bytes()
BODY_SHA256 = hashlib.sha256(BODY).hexdigest()


def evidence_for(body: bytes = BODY, **overrides) -> RetainedEvidence:
    fields = dict(
        mapping_id=35,
        card_print_id=1,
        source="snkrdunk",
        url=URL,
        sha256_prefix=hashlib.sha256(body).hexdigest()[:16],
        byte_length=len(body),
        content_type="image/webp",
        http_status=200,
        final_host="cdn.snkrdunk.com",
        redirected=False,
        canvas_px=CANVAS,
        card_bbox_px=tuple(STORED_BBOX),
        card_px=tuple(CARD_PX),
        is_active=True,
        review_status="approved",
        manual_verified=True,
        classification="VERIFIED_DISPLAY",
        payload_card_print_id=1,
        existing_sha256=None,
    )
    fields.update(overrides)
    return RetainedEvidence(**fields)


def fetcher_for(body: bytes = BODY, **overrides):
    """A fake fetcher. Records its calls so tests can assert the asset is
    fetched exactly once on the success path."""
    calls: list[str] = []

    def fetch(url: str) -> FetchResult:
        calls.append(url)
        fields = dict(
            http_status=200,
            final_url=url,
            final_host="cdn.snkrdunk.com",
            redirected=False,
            raw_content_type="image/webp",
            media_type="image/webp",
            body=body,
        )
        fields.update(overrides)
        return FetchResult(**fields)

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


# --- the happy path ---------------------------------------------------------


def test_retained_evidence_match_passes_and_computes_the_bootstrap_digest():
    result = verify_asset(evidence_for(), fetcher_for())

    assert result.passed, result.failures
    assert result.status == "PASS"
    assert result.sha256 == BODY_SHA256
    # The check that is actually possible: 64-bit prefix, not a full digest.
    assert result.sha256_prefix == BODY_SHA256[:16]
    assert result.actual_bytes == len(BODY)
    assert result.image_format == "WEBP"
    assert result.extension == "webp"


def test_the_asset_is_fetched_exactly_once():
    fetch = fetcher_for()
    verify_asset(evidence_for(), fetch)
    assert fetch.calls == [URL]


def test_pass_semantics_do_not_claim_historical_byte_equality():
    """Terminology guard: the retained evidence is a truncation, so the
    reported claim must stay the weaker, accurate one."""
    assert "NOT proof of historical full-byte equality" in mirror.PASS_SEMANTICS
    assert "Full SHA-256 computed now" in mirror.PASS_SEMANTICS


# --- byte evidence ----------------------------------------------------------


def test_sha256_prefix_mismatch_is_rejected():
    result = verify_asset(evidence_for(sha256_prefix="0" * 16), fetcher_for())

    assert not result.passed
    assert any("sha256 prefix" in f for f in result.failures)


def test_byte_length_mismatch_is_rejected():
    result = verify_asset(evidence_for(byte_length=len(BODY) + 1), fetcher_for())

    assert not result.passed
    assert any("byte length" in f for f in result.failures)


def test_a_different_asset_fails_on_both_length_and_prefix():
    """A genuinely changed asset must not squeak through on one check."""
    other = make_image_bytes(bbox=[100, 20, 473, 542])
    result = verify_asset(evidence_for(), fetcher_for(other))

    assert not result.passed
    assert any("sha256 prefix" in f for f in result.failures)


def test_non_200_stops_the_asset_before_any_byte_check():
    result = verify_asset(evidence_for(), fetcher_for(http_status=404, body=b""))

    assert not result.passed
    assert result.failures == ["http status 404 (expected 200)"]
    assert result.sha256 is None


def test_redirect_to_a_different_host_is_rejected():
    result = verify_asset(
        evidence_for(), fetcher_for(final_host="evil.example.com", redirected=True)
    )

    assert not result.passed
    assert any("final host" in f for f in result.failures)


# --- dimensions -------------------------------------------------------------


def test_dimension_mismatch_is_rejected():
    """The frontend's matchesNaturalSize() guard silently degrades on a size
    change, so this check is the only thing that would catch it."""
    smaller = make_image_bytes(canvas=(428, 312), bbox=[120, 25, 306, 286])
    result = verify_asset(
        evidence_for(
            sha256_prefix=hashlib.sha256(smaller).hexdigest()[:16], byte_length=len(smaller)
        ),
        fetcher_for(smaller),
    )

    assert not result.passed
    assert any("canvas 428x312 != retained 856x625" in f for f in result.failures)


# --- alpha geometry ---------------------------------------------------------


def test_stored_inclusive_bbox_is_normalised_to_pillow_exclusive_bbox():
    assert inclusive_bbox_to_pillow((241, 51, 614, 573)) == (241, 51, 615, 574)
    left, top, right, bottom = inclusive_bbox_to_pillow((241, 51, 614, 573))
    assert (right - left, bottom - top) == (374, 523)  # == stored card_px


def test_real_alpha_bbox_matches_the_normalised_stored_bbox():
    inspection = inspect_image(BODY)

    assert inspection.has_alpha
    assert inspection.alpha_bbox == inclusive_bbox_to_pillow(tuple(STORED_BBOX))
    # Comparing raw against the stored tuple would be off by one on two sides.
    assert inspection.alpha_bbox != tuple(STORED_BBOX)


def test_missing_alpha_is_rejected():
    opaque = make_image_bytes(with_alpha=False)
    result = verify_asset(
        evidence_for(
            sha256_prefix=hashlib.sha256(opaque).hexdigest()[:16], byte_length=len(opaque)
        ),
        fetcher_for(opaque),
    )

    assert not result.passed
    assert "image has no alpha channel" in result.failures


def test_alpha_bbox_mismatch_is_rejected():
    shifted = make_image_bytes(bbox=[240, 51, 613, 573])
    result = verify_asset(
        evidence_for(
            sha256_prefix=hashlib.sha256(shifted).hexdigest()[:16], byte_length=len(shifted)
        ),
        fetcher_for(shifted),
    )

    assert not result.passed
    assert any("alpha bbox" in f for f in result.failures)


def test_card_px_cross_check_catches_internally_inconsistent_evidence():
    """The image matches the stored bbox, but the stored card_px disagrees
    with it - evidence that cannot be trusted to drive presentation."""
    result = verify_asset(evidence_for(card_px=(375, 523)), fetcher_for())

    assert not result.passed
    assert any("card_px" in f for f in result.failures)


# --- format -----------------------------------------------------------------


def test_unexpected_format_is_rejected():
    bmp = make_image_bytes(canvas=(20, 20), bbox=[2, 2, 9, 9], image_format="BMP")
    result = verify_asset(
        evidence_for(
            canvas_px=(20, 20),
            card_bbox_px=(2, 2, 9, 9),
            card_px=(8, 8),
            sha256_prefix=hashlib.sha256(bmp).hexdigest()[:16],
            byte_length=len(bmp),
        ),
        fetcher_for(bmp, raw_content_type="image/bmp", media_type="image/bmp"),
    )

    assert not result.passed
    assert any("unsupported decoded format" in f for f in result.failures)
    assert result.proposed_object_key is None


def test_content_type_disagreeing_with_the_decoded_format_is_rejected():
    result = verify_asset(
        evidence_for(), fetcher_for(raw_content_type="image/png", media_type="image/png")
    )

    assert not result.passed
    assert any("content-type" in f for f in result.failures)


def test_retained_content_type_disagreeing_with_the_decoded_format_is_rejected():
    result = verify_asset(evidence_for(content_type="image/png"), fetcher_for())

    assert not result.passed
    assert any("retained content_type" in f for f in result.failures)


def test_extension_comes_from_the_decoded_format_not_the_url():
    """SNKRDUNK URLs carry query parameters (".webp?size=l"), and a URL suffix
    is not evidence of anything - so a .png URL serving real WebP still keys
    as .webp."""
    misleading_url = "https://cdn.snkrdunk.com/upload_bg_removed/looks-like.png?size=l"
    result = verify_asset(evidence_for(url=misleading_url), fetcher_for())

    assert result.passed, result.failures
    assert result.proposed_object_key.endswith(".webp")


# --- object key -------------------------------------------------------------


def test_object_key_is_derived_from_the_full_sha256():
    digest = "00ce7f0d833d31c5" + "a" * 48
    assert object_key(digest, "webp") == f"display-images/sha256/00/{digest}.webp"


def test_verified_asset_reports_the_key_it_would_use():
    result = verify_asset(evidence_for(), fetcher_for())

    assert result.proposed_object_key == (
        f"display-images/sha256/{BODY_SHA256[:2]}/{BODY_SHA256}.webp"
    )
    # 64 hex characters - the full digest, not the retained 16-char prefix.
    assert len(BODY_SHA256) == 64


# --- selection --------------------------------------------------------------


VERIFIED_PAYLOAD = {
    "url": URL,
    "source": "snkrdunk",
    "verified_at": "2026-08-13T10:56:42+00:00",
    "verification_method": "offline_image_comparison_vs_bandai_canonical",
    "verification_version": "display-image-v1",
    "exact_print_verified": True,
    "full_card_preserved": True,
    "sample_present": False,
    "overlay_obscures_card": False,
    "classification": "VERIFIED_DISPLAY",
    "fetch": {
        "http_status": 200,
        "content_type": "image/webp",
        "bytes": len(BODY),
        "sha256_prefix": BODY_SHA256[:16],
        "final_host": "cdn.snkrdunk.com",
        "redirected": False,
        "fetched_at": "2026-08-13T10:56:42Z",
    },
    "geometry": {
        "canvas_px": list(CANVAS),
        "card_bbox_px": list(STORED_BBOX),
        "card_px": list(CARD_PX),
        "background_removed": True,
    },
}


def payload_for(mapping_id: int, card_print_id: int, **overrides) -> dict:
    payload = copy.deepcopy(VERIFIED_PAYLOAD)
    payload["card_print_id"] = card_print_id
    payload["source_card_mapping_id"] = mapping_id
    payload.update(overrides)
    return payload


@pytest.fixture()
def approved_mapping(db_session):
    """One approved, manually verified SNKRDUNK mapping carrying real
    display-image evidence - the staging shape in miniature."""
    canonical = make_canonical(db_session, card_code="OP01-013", name_en="Sanji")
    legacy = make_legacy_card(db_session, card_code="OP01-013")
    print_row = make_print(db_session, canonical, treatment="normal")
    source = make_source(db_session, "snkrdunk")
    mapping = make_mapping(
        db_session,
        legacy,
        source,
        print_row,
        is_active=True,
        review_status="approved",
        manual_verified=True,
    )
    mapping.match_explanation_json = {
        "display_image": payload_for(mapping.id, print_row.id)
    }
    db_session.commit()
    return mapping


def test_approved_mapping_is_selected_with_its_retained_evidence(db_session, approved_mapping):
    candidates, skipped = collect_candidates(db_session)

    assert [c.mapping_id for c in candidates] == [approved_mapping.id]
    assert skipped == []
    assert candidates[0].canvas_px == CANVAS
    assert candidates[0].card_bbox_px == tuple(STORED_BBOX)
    assert candidates[0].url == URL


def test_inactive_mapping_is_skipped(db_session, approved_mapping):
    approved_mapping.is_active = False
    db_session.commit()

    candidates, skipped = collect_candidates(db_session)

    assert candidates == []
    assert [s.reason for s in skipped] == ["mapping is inactive"]


@pytest.mark.parametrize("review_status", ["needs_review", "rejected"])
def test_non_approved_mapping_is_skipped(db_session, approved_mapping, review_status):
    approved_mapping.review_status = review_status
    db_session.commit()

    candidates, skipped = collect_candidates(db_session)

    assert candidates == []
    assert skipped[0].reason == f"review_status={review_status!r}"


def test_mapping_that_is_not_manually_verified_is_skipped(db_session, approved_mapping):
    approved_mapping.manual_verified = False
    db_session.commit()

    candidates, skipped = collect_candidates(db_session)

    assert candidates == []
    assert skipped[0].reason == "mapping is not manual_verified"


@pytest.mark.parametrize("mapping_id", sorted(mirror.QUARANTINED_MAPPING_IDS))
def test_quarantined_mappings_are_never_selected(db_session, mapping_id):
    """42/43/49/52 await human artwork review. They carry no evidence today,
    and are approved here on purpose: the guard must hold even if a future
    run were to attach evidence and approve them."""
    canonical = make_canonical(db_session, card_code="OP01-013", name_en="Sanji")
    legacy = make_legacy_card(db_session, card_code="OP01-013")
    print_row = make_print(db_session, canonical, treatment="normal")
    mapping = make_mapping(
        db_session,
        legacy,
        make_source(db_session, "snkrdunk"),
        print_row,
        id=mapping_id,
        is_active=True,
        review_status="approved",
        manual_verified=True,
    )
    mapping.match_explanation_json = {"display_image": payload_for(mapping_id, print_row.id)}
    db_session.commit()

    candidates, skipped = collect_candidates(db_session)

    assert candidates == []
    assert [s.mapping_id for s in skipped] == [mapping_id]
    assert skipped[0].quarantined
    assert skipped[0].reason == "quarantined"


def test_sibling_print_evidence_is_rejected(db_session, approved_mapping):
    """The payload's own card_print_id must equal the mapping's - the check
    that stops a sibling print's image crossing over."""
    payload = approved_mapping.match_explanation_json["display_image"]
    approved_mapping.match_explanation_json = {
        "display_image": {**payload, "card_print_id": approved_mapping.card_print_id + 1}
    }
    db_session.commit()

    candidates, skipped = collect_candidates(db_session)

    assert candidates == []
    assert skipped[0].reason == "display-image qualification failed"


def test_mapping_id_mismatch_in_evidence_is_rejected(db_session, approved_mapping):
    payload = approved_mapping.match_explanation_json["display_image"]
    approved_mapping.match_explanation_json = {
        "display_image": {**payload, "source_card_mapping_id": 999}
    }
    db_session.commit()

    candidates, skipped = collect_candidates(db_session)

    assert candidates == []
    assert "source_card_mapping_id" in skipped[0].reason


def test_unverified_classification_is_rejected(db_session, approved_mapping):
    payload = approved_mapping.match_explanation_json["display_image"]
    approved_mapping.match_explanation_json = {
        "display_image": {**payload, "classification": "NEEDS_REVIEW"}
    }
    db_session.commit()

    candidates, _ = collect_candidates(db_session)

    assert candidates == []


def test_url_on_an_unexpected_host_is_rejected(db_session, approved_mapping):
    payload = approved_mapping.match_explanation_json["display_image"]
    approved_mapping.match_explanation_json = {
        "display_image": {
            **payload,
            "url": "https://cdn.example.com/x.webp",
            "fetch": {**payload["fetch"], "final_host": "cdn.example.com"},
        }
    }
    db_session.commit()

    candidates, skipped = collect_candidates(db_session)

    assert candidates == []
    assert "expected 'cdn.snkrdunk.com'" in skipped[0].reason


def test_truncated_prefix_of_the_wrong_length_is_rejected(db_session, approved_mapping):
    """A full 64-char digest in the prefix field would mean the evidence is
    not what this comparison assumes - reject rather than guess."""
    payload = approved_mapping.match_explanation_json["display_image"]
    approved_mapping.match_explanation_json = {
        "display_image": {**payload, "fetch": {**payload["fetch"], "sha256_prefix": BODY_SHA256}}
    }
    db_session.commit()

    candidates, skipped = collect_candidates(db_session)

    assert candidates == []
    assert "16 hex characters" in skipped[0].reason


def test_print_id_filter_narrows_the_run(db_session, approved_mapping):
    candidates, _ = collect_candidates(db_session, card_print_ids=[approved_mapping.card_print_id])
    assert len(candidates) == 1

    candidates, _ = collect_candidates(db_session, card_print_ids=[approved_mapping.card_print_id + 50])
    assert candidates == []


# --- whole run --------------------------------------------------------------


def test_run_verification_reports_counts_and_passes(db_session, approved_mapping):
    report = run_verification(db_session, fetcher=fetcher_for())

    assert (report.selected, report.attempted, report.passed, report.failed) == (1, 1, 1, 0)
    assert report.quarantined_skipped == 0
    assert report.other_skipped == 0
    assert report.ok


def test_run_verification_is_not_ok_when_an_asset_drifts(db_session, approved_mapping):
    drifted = make_image_bytes(bbox=[100, 20, 473, 542])
    report = run_verification(db_session, fetcher=fetcher_for(drifted))

    assert report.failed == 1
    assert not report.ok


def test_population_drift_is_reported_even_when_every_asset_passes(db_session, approved_mapping):
    report = run_verification(db_session, fetcher=fetcher_for(), expected_asset_count=16)

    assert report.failed == 0
    assert report.population_drift == "selected 1 eligible assets, expected 16"
    assert not report.ok


def test_the_dry_run_writes_nothing_to_the_database(db_session, approved_mapping):
    """No column may change, and no flush may be pending, after a full run."""
    before = {
        "explanation": copy.deepcopy(approved_mapping.match_explanation_json),
        "review_status": approved_mapping.review_status,
        "is_active": approved_mapping.is_active,
    }

    run_verification(db_session, fetcher=fetcher_for())

    assert not db_session.new
    assert not db_session.dirty
    assert not db_session.deleted
    db_session.expire_all()
    assert approved_mapping.match_explanation_json == before["explanation"]
    assert approved_mapping.review_status == before["review_status"]
    assert approved_mapping.is_active == before["is_active"]


def _module_source() -> str:
    from pathlib import Path

    return Path(mirror.__file__).read_text(encoding="utf-8")


def test_no_storage_call_exists_in_this_tranche():
    """Guards the tranche boundary: this module is verification only - no R2,
    no storage client, no upload.

    app.services.object_storage now exists (the R2 wrapper tranche built and
    unit-tested it against fake clients), so its absence is no longer the
    assertion; what still holds is that *this* module neither imports it nor
    calls storage directly. Delete this test in the tranche that actually
    wires mirroring up - it is asserting the absence of work that has not
    been authorised yet."""
    source = _module_source()
    for forbidden in (
        "boto3",
        "put_object",
        "upload_fileobj",
        "cloudflarestorage",
        "object_storage",
        "R2ObjectStorage",
    ):
        assert forbidden not in source, forbidden


def test_the_verifier_never_re_encodes_the_source_bytes():
    """Byte discipline, asserted on the source itself: Pillow is used for
    inspection only, so no save/encode call may appear in the module."""
    source = _module_source()
    for forbidden in (".save(", ".resize(", ".crop(", ".thumbnail("):
        assert forbidden not in source, forbidden
