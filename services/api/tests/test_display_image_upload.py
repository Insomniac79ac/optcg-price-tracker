"""Single-asset display-image mirroring to R2 (app.services.display_image_upload).

No network and no real bucket: the source fetch is the same fake fetcher the
verification tests use, R2 is the storing fake S3 client from the roundtrip
tests, and the public leg drives the *real* unauthenticated fetch function
through httpx.MockTransport. The images are real WebP bytes built by Pillow,
so decode, dimension and alpha checks run against a genuine image.

What these tests pin, in order of how much damage the failure would do:

  * The stored FULL fetch.sha256 is the identity. A mismatch, or its absence,
    blocks the upload outright - the 64-bit sha256_prefix is never a fallback,
    because the object's key *is* its digest.
  * An object already at the key is never overwritten, and is verified
    instead. Wrong bytes there are a hard failure, not a repair opportunity.
  * The bytes PUT are the exact verified source bytes, with
    ContentType=image/webp and the immutable Cache-Control - no re-encode, no
    transformation, no ETag used as an integrity check.
  * Both read-backs are compared against the *stored* digest, not against each
    other, so a consistently-wrong pair cannot pass.
  * Exactly one print is processed, and nothing is written to the database.
"""

from __future__ import annotations

import copy
import hashlib
import io
import tokenize
from pathlib import Path

import pytest

from app.services import display_image_upload as upload
from app.services.display_image_upload import (
    CACHE_CONTROL,
    CONTENT_TYPE,
    mirror_print,
)
from tests.test_check_r2_public_delivery import mock_fetcher
from tests.test_check_r2_roundtrip import StoringFakeS3Client
from tests.test_display_image_mirror import (  # noqa: F401  (db_session via conftest)
    BODY,
    BODY_SHA256,
    CANVAS,
    URL,
    fetcher_for,
    make_image_bytes,
    payload_for,
)
from tests.test_object_storage import FAKE_PUBLIC_BASE_URL, client_error, make_storage
from tests.test_prints import (
    make_canonical,
    make_legacy_card,
    make_mapping,
    make_print,
    make_source,
)

EXPECTED_KEY = f"display-images/sha256/{BODY_SHA256[:2]}/{BODY_SHA256}.webp"


def module_code() -> str:
    """The uploader's source with comments and string literals removed, so a
    forbidden name in prose does not read as a forbidden call."""
    source = Path(upload.__file__).read_text()
    return "\n".join(
        token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type not in (tokenize.COMMENT, tokenize.STRING)
    )


# --- fixtures ---------------------------------------------------------------


def _bootstrapped_payload(mapping_id: int, card_print_id: int, sha256: str = BODY_SHA256) -> dict:
    """Evidence as it exists after the 2026-08-14 bootstrap: the full digest
    persisted alongside the original truncated prefix."""
    payload = payload_for(mapping_id, card_print_id)
    payload["fetch"]["sha256"] = sha256
    payload["fetch"]["sha256_recorded_at"] = "2026-08-14T12:00:00+00:00"
    payload["fetch"]["sha256_origin"] = "bootstrap_refetch"
    return payload


def _make_asset(db_session, *, card_code: str, sha256: str = BODY_SHA256):
    canonical = make_canonical(db_session, card_code=card_code, name_en=card_code)
    legacy = make_legacy_card(db_session, card_code=card_code)
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
        "display_image": _bootstrapped_payload(mapping.id, print_row.id, sha256)
    }
    db_session.commit()
    return mapping, print_row


@pytest.fixture()
def asset(db_session):
    """One approved, bootstrapped SNKRDUNK display asset - staging in miniature."""
    return _make_asset(db_session, card_code="OP01-013")


def edit_evidence(db_session, mapping, mutate):
    """Apply `mutate` to a *copy* of the evidence and reassign it.

    Never mutate `mapping.match_explanation_json` in place first: the column
    is a plain JSON type with no MutableDict wrapper, so SQLAlchemy's
    committed value *is* the same dict object. Mutating it and then assigning
    a deepcopy leaves old == new, the flush emits no UPDATE, and the test
    silently exercises the unedited evidence. Same trap that
    display_image_mirror._with_bootstrap_digest documents, from the other side.
    """
    payload = copy.deepcopy(mapping.match_explanation_json)
    mutate(payload["display_image"])
    mapping.match_explanation_json = payload
    db_session.commit()


def public_fetcher_for(body: bytes = BODY, status: int = 200):
    return mock_fetcher(status=status, body=body)


def run(db_session, print_id, client=None, *, body=BODY, public_body=None, public_status=200):
    client = client if client is not None else StoringFakeS3Client()
    storage = make_storage(client)
    outcome = mirror_print(
        db_session,
        print_id,
        storage,
        fetcher=fetcher_for(body),
        public_fetcher=public_fetcher_for(
            public_body if public_body is not None else body, public_status
        ),
    )
    return outcome, client


# --- the happy path: absent object -> PUT -> verify -------------------------


def test_absent_object_is_uploaded_and_verified_end_to_end(db_session, asset):
    mapping, print_row = asset

    outcome, client = run(db_session, print_row.id)

    assert outcome.ok, [s.detail for s in outcome.stages if not s.ok]
    assert [s.name for s in outcome.stages] == list(upload.STAGE_NAMES)
    assert outcome.mapping_id == mapping.id
    assert outcome.uploaded is True
    assert outcome.object_key == EXPECTED_KEY
    assert outcome.stored_sha256 == outcome.computed_sha256 == BODY_SHA256
    assert outcome.private_byte_length == outcome.public_byte_length == len(BODY)
    assert outcome.private_sha256 == outcome.public_sha256 == BODY_SHA256
    assert outcome.public_status == 200
    assert outcome.public_dimensions == CANVAS == outcome.expected_canvas_px
    assert outcome.exit_code == 0


def test_the_key_is_derived_from_the_verified_digest_and_not_hardcoded(db_session):
    """A different image must land on a different key, computed from its own
    digest - the key is content-addressed, not print-addressed."""
    other_body = make_image_bytes(canvas=(857, 625), bbox=[241, 51, 614, 573])
    other_sha = hashlib.sha256(other_body).hexdigest()
    mapping, print_row = _make_asset(db_session, card_code="OP01-099", sha256=other_sha)

    def retarget(display_image):
        display_image["geometry"]["canvas_px"] = [857, 625]
        display_image["fetch"]["bytes"] = len(other_body)
        display_image["fetch"]["sha256_prefix"] = other_sha[:16]

    edit_evidence(db_session, mapping, retarget)

    outcome, client = run(db_session, print_row.id, body=other_body)

    assert outcome.ok, [s.detail for s in outcome.stages if not s.ok]
    assert outcome.object_key == f"display-images/sha256/{other_sha[:2]}/{other_sha}.webp"
    assert outcome.object_key != EXPECTED_KEY
    # Nothing print-shaped in the key: no print id, no mutable alias.
    assert outcome.object_key.rsplit("/", 1)[-1] == f"{other_sha}.webp"


def test_put_receives_the_exact_verified_bytes(db_session, asset):
    outcome, client = run(db_session, asset[1].id)

    assert len(client.put_calls) == 1
    call = client.put_calls[0]
    assert call["Key"] == EXPECTED_KEY
    assert call["Body"] == BODY  # byte equality, not just equal length
    assert hashlib.sha256(call["Body"]).hexdigest() == BODY_SHA256
    assert len(call["Body"]) == len(BODY)


def test_put_sends_the_webp_content_type_and_immutable_cache_control(db_session, asset):
    outcome, client = run(db_session, asset[1].id)

    call = client.put_calls[0]
    assert call["ContentType"] == CONTENT_TYPE == "image/webp"
    assert call["CacheControl"] == CACHE_CONTROL == "public, max-age=31536000, immutable"
    # No ACL, no storage class, no tags, no metadata under a content-addressed key.
    assert set(call) == {"Bucket", "Key", "Body", "ContentType", "CacheControl"}


def test_nothing_re_encodes_the_image(db_session, asset):
    """The uploaded bytes are the fetched bytes, so the source image survives
    exactly - Pillow is used for inspection only, never to produce bytes."""
    outcome, client = run(db_session, asset[1].id)

    assert client.objects[EXPECTED_KEY]["Body"] == BODY
    code = module_code()
    for forbidden in ("save", "resize", "crop", "convert", "thumbnail", "Image"):
        assert forbidden not in code, f"{forbidden!r} must not appear in the uploader"


# --- the digest gate --------------------------------------------------------


def test_stored_full_sha256_mismatch_blocks_the_upload(db_session, asset):
    mapping, print_row = asset
    # Prefix-consistent, so the evidence is internally valid and the run gets
    # all the way to the digest gate rather than being skipped as malformed.
    wrong = BODY_SHA256[:16] + "0" * 48
    assert wrong != BODY_SHA256
    edit_evidence(db_session, mapping, lambda di: di["fetch"].__setitem__("sha256", wrong))

    outcome, client = run(db_session, print_row.id)

    assert not outcome.ok
    assert outcome.failed_stage == "digest"
    assert "Refusing to upload" in outcome.stages[-1].detail
    assert client.put_calls == []
    assert client.objects == {}
    assert outcome.object_key is None


def test_a_matching_prefix_does_not_rescue_a_mismatched_full_digest(db_session, asset):
    """The prefix is 64 bits and is never the identity: a digest that agrees
    on its first 16 hex characters and differs after must still be refused."""
    mapping, print_row = asset
    near_miss = BODY_SHA256[:16] + "f" * 48
    assert near_miss != BODY_SHA256
    edit_evidence(db_session, mapping, lambda di: di["fetch"].__setitem__("sha256", near_miss))

    outcome, client = run(db_session, print_row.id)

    assert outcome.failed_stage == "digest"
    assert client.put_calls == []


def test_an_asset_with_no_stored_full_digest_is_refused(db_session, asset):
    mapping, print_row = asset
    edit_evidence(db_session, mapping, lambda di: di["fetch"].pop("sha256"))

    outcome, client = run(db_session, print_row.id)

    assert outcome.failed_stage == "digest"
    assert "not been bootstrapped" in outcome.stages[-1].detail
    assert client.put_calls == []


def test_source_bytes_that_fail_verification_never_reach_storage(db_session, asset):
    """Different bytes fail the verifier first (length/prefix/geometry), so the
    digest gate is not even the thing that stops it."""
    mapping, print_row = asset
    different = make_image_bytes(bbox=[10, 10, 100, 100])

    outcome, client = run(db_session, print_row.id, body=different)

    assert outcome.failed_stage == "verify"
    assert client.put_calls == []
    assert client.head_calls == []


# --- an object already at the key -------------------------------------------


def test_existing_valid_object_is_verified_and_never_overwritten(db_session, asset):
    client = StoringFakeS3Client()
    client.objects[EXPECTED_KEY] = {
        "Body": BODY,
        "ContentType": CONTENT_TYPE,
        "CacheControl": CACHE_CONTROL,
        "Metadata": {},
    }

    outcome, client = run(db_session, asset[1].id, client)

    assert outcome.ok, [s.detail for s in outcome.stages if not s.ok]
    assert outcome.uploaded is False
    assert client.put_calls == []  # the whole point
    assert client.objects[EXPECTED_KEY]["Body"] == BODY
    assert "not overwritten" in [s.detail for s in outcome.stages if s.name == "upload"][0]


def test_existing_object_with_wrong_bytes_of_the_same_length_fails_hard(db_session, asset):
    corrupted = bytearray(BODY)
    corrupted[-1] ^= 0x20
    client = StoringFakeS3Client()
    client.objects[EXPECTED_KEY] = {
        "Body": bytes(corrupted),
        "ContentType": CONTENT_TYPE,
        "CacheControl": CACHE_CONTROL,
        "Metadata": {},
    }

    outcome, client = run(db_session, asset[1].id, client)

    assert not outcome.ok
    assert outcome.failed_stage == "private"
    assert "!= stored fetch.sha256" in outcome.stages[-1].detail
    assert client.put_calls == []  # never repaired by overwriting
    assert client.objects[EXPECTED_KEY]["Body"] == bytes(corrupted)


def test_existing_object_with_a_different_length_fails_at_head(db_session, asset):
    client = StoringFakeS3Client()
    client.objects[EXPECTED_KEY] = {
        "Body": BODY + b"trailing",
        "ContentType": CONTENT_TYPE,
        "CacheControl": CACHE_CONTROL,
        "Metadata": {},
    }

    outcome, client = run(db_session, asset[1].id, client)

    assert outcome.failed_stage == "head"
    assert "Refusing to overwrite" in outcome.stages[-1].detail
    assert client.put_calls == []


# --- private read-back ------------------------------------------------------


def test_private_get_digest_mismatch_fails(db_session, asset):
    client = StoringFakeS3Client()
    corrupted = bytearray(BODY)
    corrupted[0] ^= 0xFF
    client.corrupt_body = bytes(corrupted)  # corrupts the read, not the write

    outcome, client = run(db_session, asset[1].id, client)

    assert outcome.failed_stage == "private"
    assert "!= stored fetch.sha256" in outcome.stages[-1].detail
    assert client.put_calls  # the PUT happened; the read-back is what failed


def test_private_get_length_mismatch_fails(db_session, asset):
    client = StoringFakeS3Client()
    client.corrupt_body = BODY[:-5]

    outcome, client = run(db_session, asset[1].id, client)

    assert outcome.failed_stage == "private"
    assert "byte length" in outcome.stages[-1].detail


def test_a_failed_get_fails_at_the_private_stage(db_session, asset):
    client = StoringFakeS3Client(get_error=client_error("AccessDenied", 403, "GetObject"))

    outcome, client = run(db_session, asset[1].id, client)

    assert outcome.failed_stage == "private"
    assert "AccessDenied" in outcome.stages[-1].detail


def test_a_failed_put_fails_at_the_upload_stage(db_session, asset):
    client = StoringFakeS3Client(put_error=client_error("AccessDenied", 403, "PutObject"))

    outcome, client = run(db_session, asset[1].id, client)

    assert outcome.failed_stage == "upload"
    assert "AccessDenied" in outcome.stages[-1].detail


def test_head_metadata_is_confirmed_after_upload(db_session, asset):
    outcome, client = run(db_session, asset[1].id)

    assert outcome.head_content_type == CONTENT_TYPE
    assert outcome.head_cache_control == CACHE_CONTROL
    assert outcome.head_content_length == len(BODY)
    # HEAD is called twice: once to decide whether to upload, once to confirm.
    assert len(client.head_calls) == 2


def test_etag_is_not_used_as_an_integrity_check():
    """ETag is an opaque server token, not a digest. It may be mentioned in a
    comment; it may not be read in code."""
    code = module_code()
    assert "etag" not in code.lower()


# --- public read-back -------------------------------------------------------


def test_public_get_digest_mismatch_fails(db_session, asset):
    tampered = bytearray(BODY)
    tampered[5] ^= 0x11

    outcome, client = run(db_session, asset[1].id, public_body=bytes(tampered))

    assert outcome.failed_stage == "public"
    assert "!= stored fetch.sha256" in outcome.stages[-1].detail
    assert outcome.public_sha256 != BODY_SHA256


def test_public_non_200_fails(db_session, asset):
    outcome, client = run(db_session, asset[1].id, public_body=b"", public_status=403)

    assert outcome.failed_stage == "public"
    assert "HTTP 403" in outcome.stages[-1].detail


def test_public_length_mismatch_fails(db_session, asset):
    outcome, client = run(db_session, asset[1].id, public_body=BODY[:-1])

    assert outcome.failed_stage == "public"
    assert "byte length" in outcome.stages[-1].detail


def test_public_request_is_unauthenticated(db_session, asset):
    storage = make_storage(StoringFakeS3Client())
    fetcher = mock_fetcher(body=BODY, extra_request_headers={"Authorization": "Bearer nope"})

    outcome = mirror_print(
        db_session, asset[1].id, storage, fetcher=fetcher_for(BODY), public_fetcher=fetcher
    )

    assert outcome.failed_stage == "public"
    assert "not a public read" in outcome.stages[-1].detail


def test_public_url_is_built_from_the_public_base_url(db_session, asset):
    outcome, client = run(db_session, asset[1].id)

    assert outcome.public_url == f"{FAKE_PUBLIC_BASE_URL}/{EXPECTED_KEY}"
    assert outcome.public_host == "fake-public-host.r2.dev"


def test_public_dimension_mismatch_fails_the_frontend_geometry_guard(
    db_session, asset, monkeypatch
):
    """With real hashing this is unreachable behind the digest check, so the
    guard is exercised by injecting a wrong decode. It is kept because
    matchesNaturalSize() in the frontend silently falls back to unbounded
    presentation on any dimension change - a failure that is invisible unless
    something asserts it here."""
    real_inspect = upload.inspect_image

    def wrong_size(body: bytes):
        inspection = real_inspect(body)
        return type(inspection)(
            image_format=inspection.image_format,
            width=inspection.width + 1,
            height=inspection.height,
            has_alpha=inspection.has_alpha,
            alpha_bbox=inspection.alpha_bbox,
        )

    monkeypatch.setattr(upload, "inspect_image", wrong_size)

    outcome, client = run(db_session, asset[1].id)

    assert outcome.failed_stage == "public"
    assert "frontend geometry guard" in outcome.stages[-1].detail
    assert outcome.public_dimensions == (CANVAS[0] + 1, CANVAS[1])


def test_undecodable_public_bytes_fail(db_session, asset, monkeypatch):
    def explode(body: bytes):
        raise OSError("cannot identify image file")

    monkeypatch.setattr(upload, "inspect_image", explode)

    outcome, client = run(db_session, asset[1].id)

    assert outcome.failed_stage == "public"
    assert "failed to decode" in outcome.stages[-1].detail


# --- scope: one print, no database write ------------------------------------


def test_only_the_requested_print_is_processed(db_session, asset):
    mapping_one, print_one = asset
    other_body = make_image_bytes(bbox=[100, 100, 300, 400])
    mapping_two, print_two = _make_asset(
        db_session, card_code="OP01-014", sha256=hashlib.sha256(other_body).hexdigest()
    )
    other_url = "https://cdn.snkrdunk.com/upload_bg_removed/OTHER.webp?size=l"

    def retarget(display_image):
        display_image["url"] = other_url
        display_image["fetch"]["bytes"] = len(other_body)
        display_image["fetch"]["sha256_prefix"] = hashlib.sha256(other_body).hexdigest()[:16]
        display_image["geometry"]["card_bbox_px"] = [100, 100, 300, 400]
        display_image["geometry"]["card_px"] = [201, 301]

    edit_evidence(db_session, mapping_two, retarget)

    fetcher = fetcher_for(BODY)
    storage = make_storage(StoringFakeS3Client())
    client = storage._client
    outcome = mirror_print(
        db_session, print_one.id, storage, fetcher=fetcher, public_fetcher=public_fetcher_for()
    )

    assert outcome.ok, [s.detail for s in outcome.stages if not s.ok]
    assert outcome.mapping_id == mapping_one.id
    # Only the requested print's asset was fetched, headed, put and got.
    assert fetcher.calls == [URL]
    assert other_url not in fetcher.calls
    assert [c["Key"] for c in client.put_calls] == [EXPECTED_KEY]
    assert list(client.objects) == [EXPECTED_KEY]
    assert {c["Key"] for c in client.head_calls} == {EXPECTED_KEY}
    assert {c["Key"] for c in client.get_calls} == {EXPECTED_KEY}


def test_a_print_with_no_eligible_asset_fails_without_touching_storage(db_session, asset):
    outcome, client = run(db_session, 99999)

    assert outcome.failed_stage == "verify"
    assert "expected exactly 1 eligible display asset" in outcome.stages[-1].detail
    assert client.put_calls == [] and client.head_calls == []


def test_a_quarantined_or_unapproved_mapping_is_not_mirrored(db_session, asset):
    mapping, print_row = asset
    mapping.review_status = "needs_review"
    db_session.commit()

    outcome, client = run(db_session, print_row.id)

    assert outcome.failed_stage == "verify"
    assert client.put_calls == []


def test_nothing_is_written_to_the_database(db_session, asset):
    mapping, print_row = asset
    before = copy.deepcopy(mapping.match_explanation_json)
    print_image_url, print_artwork_key = print_row.image_url, print_row.artwork_key

    outcome, client = run(db_session, print_row.id)

    assert outcome.ok, [s.detail for s in outcome.stages if not s.ok]
    assert not db_session.new and not db_session.dirty and not db_session.deleted

    db_session.expire_all()
    assert mapping.match_explanation_json == before
    assert "owned_asset" not in mapping.match_explanation_json["display_image"]
    assert mapping.match_explanation_json["display_image"].get("url") == URL
    assert print_row.image_url == print_image_url
    assert print_row.artwork_key == print_artwork_key


def test_the_uploader_writes_no_owned_asset_and_no_evidence_key(db_session, asset):
    """Persisting the mirrored location is a later tranche. Nothing here may
    create an owned_asset row, or edit the evidence block."""
    code = module_code()
    for forbidden in (
        "owned_asset",
        "OwnedAsset",
        "match_explanation_json",
        "commit",
        "flush",
        "image_url",
        "artwork_key",
        "delete_object",
        "delete_objects",
        "list_objects",
    ):
        assert forbidden not in code, f"{forbidden!r} must not appear in the uploader"

    from app import models

    assert not hasattr(models, "OwnedAsset")


def test_the_uploader_reuses_the_existing_verifier_and_key_format():
    """A second copy of either would be free to drift from the one the public
    API and the persisted evidence already agree on."""
    from app.services import display_image_mirror

    assert upload.run_verification is display_image_mirror.run_verification
    assert upload.object_key is display_image_mirror.object_key
    assert upload.inspect_image is display_image_mirror.inspect_image


# --- the command ------------------------------------------------------------


def test_the_cli_has_no_all_flag_and_takes_exactly_one_print(capsys):
    """One print per invocation, by construction. The first tranche that
    writes real card bytes must not be pointable at the catalogue by typo."""
    from app import mirror_display_image_to_r2 as cli

    with pytest.raises(SystemExit):
        cli.main(["--all"])
    with pytest.raises(SystemExit):
        cli.main([])  # --print-id is required

    code = Path(cli.__file__).read_text()
    assert '"--all"' not in code
    assert 'action="append"' not in code


def test_the_cli_exits_two_when_r2_is_unconfigured(monkeypatch, capsys):
    from app import mirror_display_image_to_r2 as cli
    from app.settings import settings as live_settings

    for name in (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET_NAME",
        "R2_PUBLIC_BASE_URL",
    ):
        monkeypatch.setattr(live_settings, name, None)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--print-id", "1"])

    assert exit_info.value.code == cli.EXIT_NOT_CONFIGURED
    assert "not configured" in capsys.readouterr().out


def test_the_cli_reports_the_outcome_and_exits_zero(monkeypatch, capsys, db_session, asset):
    from app import mirror_display_image_to_r2 as cli
    from app.services.object_storage import R2ObjectStorage

    client = StoringFakeS3Client()
    monkeypatch.setattr(
        R2ObjectStorage, "from_settings", classmethod(lambda c, s=None: make_storage(client))
    )
    monkeypatch.setattr(cli, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(
        cli,
        "mirror_print",
        lambda db, print_id, storage: upload.mirror_print(
            db,
            print_id,
            storage,
            fetcher=fetcher_for(BODY),
            public_fetcher=public_fetcher_for(),
        ),
    )

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--print-id", str(asset[1].id)])

    out = capsys.readouterr().out
    assert exit_info.value.code == cli.EXIT_OK
    assert "[OK] source bytes == R2 bytes == public bytes" in out
    assert EXPECTED_KEY in out
    assert BODY_SHA256 in out
    assert "UPLOADED (key was empty)" in out
    assert "no database row was created, updated or deleted" in out
