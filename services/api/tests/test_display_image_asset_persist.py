"""Persisting display_image.owned_asset (app.services.display_image_asset_persist).

The write half of the R2 mirror: one additive evidence key, on one mapping,
only after that mapping's asset has been re-verified end to end in the same
run. All network work is faked exactly as in tests/test_display_image_upload.py -
the source fetch, the R2 client and the public GET are the same fakes - so
what is under test here is purely *what reaches the database, and when it
refuses to*.

What these tests pin:

  * Additive means additive. Every pre-existing display_image key - url,
    fetch, geometry, artwork_comparison, classification - must survive
    byte-identical, and so must the print's canonical identity columns.
  * No URL is stored. The r2.dev host is environment configuration; baking it
    into evidence would create a second source of truth next to
    R2_PUBLIC_BASE_URL that could silently go stale.
  * The write is guarded and short: network first, then a re-read that
    compares against what was verified, then one commit. Drift aborts.
  * Idempotency is by content, not by timestamp. A matching owned_asset is
    left completely alone; a conflicting one is a hard failure and is never
    overwritten.
  * The public API cannot leak it: DisplayImageOut has no owned_asset field.
  * Exactly one mapping row changes.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from app.models import SourceCardMapping
from app.services import display_image_asset_persist as persist_module
from app.services.display_image_asset_persist import (
    IDENTITY_FIELDS,
    OWNED_ASSET_KEY,
    PROVIDER,
    VERIFICATION_METHOD,
    build_owned_asset,
    persist_owned_asset,
)
from app.services.display_image_upload import CACHE_CONTROL, CONTENT_TYPE, mirror_print
from tests.test_display_image_mirror import BODY, BODY_SHA256, CANVAS, URL, fetcher_for
from tests.test_display_image_upload import (  # noqa: F401  (fixtures via conftest)
    EXPECTED_KEY,
    StoringFakeS3Client,
    _make_asset,
    asset,
    edit_evidence,
    make_storage,
    public_fetcher_for,
)
from tests.test_object_storage import FAKE_PUBLIC_BASE_URL
from tests.test_prints import make_canonical, make_legacy_card, make_mapping, make_print, make_source

FIXED_NOW = datetime(2026, 8, 15, 9, 30, 0, tzinfo=timezone.utc)


def mirror(db_session, print_id, client=None):
    """A full, passing mirror run against fakes - the precondition for a write."""
    client = client if client is not None else StoringFakeS3Client()
    storage = make_storage(client)
    outcome = mirror_print(
        db_session,
        print_id,
        storage,
        fetcher=fetcher_for(BODY),
        public_fetcher=public_fetcher_for(),
    )
    assert outcome.ok, [s.detail for s in outcome.stages if not s.ok]
    return outcome


def owned_asset_of(db_session, mapping_id: int) -> dict | None:
    """Read the block back through a genuinely fresh load, not the identity map."""
    db_session.expire_all()
    mapping = db_session.get(SourceCardMapping, mapping_id)
    return (mapping.match_explanation_json or {}).get("display_image", {}).get(OWNED_ASSET_KEY)


# --- successful additive persistence ----------------------------------------


def test_owned_asset_is_written_with_the_verified_values(db_session, asset):
    mapping, print_row = asset

    outcome = mirror(db_session, print_row.id)
    result = persist_owned_asset(db_session, outcome, now=FIXED_NOW)

    assert result.ok and result.written and not result.already_recorded
    assert result.mapping_id == mapping.id
    assert result.owned_asset == {
        "provider": "cloudflare_r2",
        "object_key": EXPECTED_KEY,
        "sha256": BODY_SHA256,
        "byte_size": len(BODY),
        "width": CANVAS[0],
        "height": CANVAS[1],
        "content_type": "image/webp",
        "cache_control": "public, max-age=31536000, immutable",
        "verified_at": FIXED_NOW.isoformat(),
        "verification_method": "source_private_public_sha256",
    }


def test_the_block_survives_a_fresh_database_read(db_session, asset):
    """A JSON column edit that is not tracked would leave every in-memory
    assertion above passing and nothing actually persisted."""
    mapping, print_row = asset

    persist_owned_asset(db_session, mirror(db_session, print_row.id), now=FIXED_NOW)

    stored = owned_asset_of(db_session, mapping.id)
    assert stored is not None
    assert stored["object_key"] == EXPECTED_KEY
    assert stored["sha256"] == BODY_SHA256
    assert stored["verified_at"] == FIXED_NOW.isoformat()


def test_key_digest_size_and_dimensions_are_persisted_exactly(db_session, asset):
    mapping, print_row = asset
    persist_owned_asset(db_session, mirror(db_session, print_row.id), now=FIXED_NOW)

    stored = owned_asset_of(db_session, mapping.id)
    assert stored["object_key"] == f"display-images/sha256/{BODY_SHA256[:2]}/{BODY_SHA256}.webp"
    assert stored["sha256"] == BODY_SHA256 and len(stored["sha256"]) == 64
    assert stored["byte_size"] == len(BODY)
    assert (stored["width"], stored["height"]) == CANVAS
    # The digest is the one stored in evidence, and the key is derived from it.
    fetch = db_session.get(SourceCardMapping, mapping.id).match_explanation_json["display_image"]["fetch"]
    assert stored["sha256"] == fetch["sha256"]
    assert stored["object_key"].endswith(f"{fetch['sha256']}.webp")


def test_content_type_and_cache_policy_are_persisted_from_what_r2_reported(db_session, asset):
    mapping, print_row = asset
    persist_owned_asset(db_session, mirror(db_session, print_row.id), now=FIXED_NOW)

    stored = owned_asset_of(db_session, mapping.id)
    assert stored["content_type"] == CONTENT_TYPE == "image/webp"
    assert stored["cache_control"] == CACHE_CONTROL == "public, max-age=31536000, immutable"
    assert stored["provider"] == PROVIDER == "cloudflare_r2"
    assert stored["verification_method"] == VERIFICATION_METHOD == "source_private_public_sha256"


# --- no URL, no duplicated source -------------------------------------------


def test_no_public_url_or_hostname_is_stored(db_session, asset):
    """The delivery host is configuration, not evidence: it differs per
    environment and will move to a custom domain."""
    mapping, print_row = asset
    outcome = mirror(db_session, print_row.id)
    assert outcome.public_url.startswith(FAKE_PUBLIC_BASE_URL)  # it *was* fetched

    persist_owned_asset(db_session, outcome, now=FIXED_NOW)
    stored = owned_asset_of(db_session, mapping.id)

    blob = repr(stored)
    assert "r2.dev" not in blob
    assert "http" not in blob
    assert FAKE_PUBLIC_BASE_URL not in blob
    assert outcome.public_url not in blob
    assert not any("url" in name for name in stored)


def test_the_source_url_is_not_duplicated_into_the_block(db_session, asset):
    mapping, print_row = asset
    persist_owned_asset(db_session, mirror(db_session, print_row.id), now=FIXED_NOW)

    display_image = db_session.get(SourceCardMapping, mapping.id).match_explanation_json[
        "display_image"
    ]
    assert URL not in repr(display_image[OWNED_ASSET_KEY])
    assert "snkrdunk" not in repr(display_image[OWNED_ASSET_KEY])
    # ...and the original provenance is still exactly where it was.
    assert display_image["url"] == URL


def test_the_stored_keys_are_exactly_the_agreed_set(db_session, asset):
    mapping, print_row = asset
    persist_owned_asset(db_session, mirror(db_session, print_row.id), now=FIXED_NOW)

    stored = owned_asset_of(db_session, mapping.id)
    assert set(stored) == set(IDENTITY_FIELDS) | {"verified_at"}


# --- everything else unchanged ----------------------------------------------


def test_every_pre_existing_evidence_key_is_untouched(db_session, asset):
    mapping, print_row = asset
    before = copy.deepcopy(mapping.match_explanation_json)

    persist_owned_asset(db_session, mirror(db_session, print_row.id), now=FIXED_NOW)

    db_session.expire_all()
    after = db_session.get(SourceCardMapping, mapping.id).match_explanation_json
    assert set(after) == set(before)  # nothing added outside display_image
    display_before = before["display_image"]
    display_after = copy.deepcopy(after["display_image"])
    assert display_after.pop(OWNED_ASSET_KEY)  # the only difference
    assert display_after == display_before
    # Named explicitly, because these are the ones that would matter.
    assert display_after["url"] == display_before["url"]
    assert display_after["fetch"] == display_before["fetch"]
    assert display_after["geometry"] == display_before["geometry"]
    assert display_after["classification"] == display_before["classification"]


def test_arbitrary_sibling_evidence_blocks_survive(db_session, asset):
    """artwork_comparison and anything else living beside display_image."""
    mapping, print_row = asset
    comparison = {"method": "phash", "distance": 0, "compared_at": "2026-08-13T10:00:00+00:00"}
    payload = copy.deepcopy(mapping.match_explanation_json)
    payload["artwork_comparison"] = comparison
    payload["display_image"]["artwork_comparison"] = {"nested": True}
    mapping.match_explanation_json = payload
    db_session.commit()

    persist_owned_asset(db_session, mirror(db_session, print_row.id), now=FIXED_NOW)

    db_session.expire_all()
    after = db_session.get(SourceCardMapping, mapping.id).match_explanation_json
    assert after["artwork_comparison"] == comparison
    assert after["display_image"]["artwork_comparison"] == {"nested": True}


def test_print_identity_columns_are_untouched(db_session, asset):
    mapping, print_row = asset
    image_url, artwork_key = print_row.image_url, print_row.artwork_key
    source_id, card_print_id = mapping.source_id, mapping.card_print_id

    persist_owned_asset(db_session, mirror(db_session, print_row.id), now=FIXED_NOW)

    db_session.expire_all()
    assert print_row.image_url == image_url
    assert print_row.artwork_key == artwork_key
    assert (mapping.source_id, mapping.card_print_id) == (source_id, card_print_id)
    assert mapping.review_status == "approved" and mapping.is_active is True


# --- idempotency and conflict -----------------------------------------------


def test_an_identical_owned_asset_is_left_alone_and_not_re_timestamped(db_session, asset):
    mapping, print_row = asset
    persist_owned_asset(db_session, mirror(db_session, print_row.id), now=FIXED_NOW)
    first = owned_asset_of(db_session, mapping.id)

    later = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    result = persist_owned_asset(db_session, mirror(db_session, print_row.id), now=later)

    assert result.ok and result.already_recorded and not result.written
    stored = owned_asset_of(db_session, mapping.id)
    assert stored == first
    assert stored["verified_at"] == FIXED_NOW.isoformat() != later.isoformat()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sha256", "f" * 64),
        ("object_key", "display-images/sha256/ff/" + "f" * 64 + ".webp"),
        ("byte_size", 999),
        ("width", 857),
        ("height", 626),
        ("content_type", "image/png"),
        ("cache_control", "no-store"),
        ("provider", "aws_s3"),
        ("verification_method", "eyeballed"),
    ],
)
def test_a_conflicting_owned_asset_is_a_hard_failure_and_is_never_overwritten(
    db_session, asset, field, value
):
    mapping, print_row = asset
    persist_owned_asset(db_session, mirror(db_session, print_row.id), now=FIXED_NOW)
    edit_evidence(
        db_session,
        mapping,
        lambda di: di[OWNED_ASSET_KEY].__setitem__(field, value),
    )
    tampered = owned_asset_of(db_session, mapping.id)

    result = persist_owned_asset(db_session, mirror(db_session, print_row.id), now=FIXED_NOW)

    assert not result.ok
    assert field in result.abort_reason
    assert "refusing to overwrite" in result.abort_reason
    assert owned_asset_of(db_session, mapping.id) == tampered  # untouched


def test_a_non_object_owned_asset_is_refused(db_session, asset):
    mapping, print_row = asset
    edit_evidence(db_session, mapping, lambda di: di.__setitem__(OWNED_ASSET_KEY, "yes"))

    result = persist_owned_asset(db_session, mirror(db_session, print_row.id), now=FIXED_NOW)

    assert not result.ok and "non-object" in result.abort_reason
    assert owned_asset_of(db_session, mapping.id) == "yes"


def test_a_differing_verified_at_alone_is_not_a_conflict(db_session, asset):
    """Timestamp is provenance, not identity - two runs of the same asset
    agree even though they ran at different moments."""
    mapping, print_row = asset
    persist_owned_asset(db_session, mirror(db_session, print_row.id), now=FIXED_NOW)
    edit_evidence(
        db_session,
        mapping,
        lambda di: di[OWNED_ASSET_KEY].__setitem__("verified_at", "2020-01-01T00:00:00+00:00"),
    )

    result = persist_owned_asset(db_session, mirror(db_session, print_row.id), now=FIXED_NOW)

    assert result.ok and result.already_recorded
    assert owned_asset_of(db_session, mapping.id)["verified_at"] == "2020-01-01T00:00:00+00:00"


# --- the guard --------------------------------------------------------------


def test_evidence_that_changed_after_verification_aborts_the_write(db_session, asset):
    mapping, print_row = asset
    outcome = mirror(db_session, print_row.id)

    # Drift between the network phase and the write phase.
    edit_evidence(db_session, mapping, lambda di: di.__setitem__("url", URL + "&changed=1"))

    result = persist_owned_asset(db_session, outcome, now=FIXED_NOW)

    assert not result.ok
    assert "changed between verification and write" in result.abort_reason
    assert owned_asset_of(db_session, mapping.id) is None


def test_a_mapping_unapproved_after_verification_aborts_the_write(db_session, asset):
    mapping, print_row = asset
    outcome = mirror(db_session, print_row.id)

    mapping.review_status = "needs_review"
    db_session.commit()

    result = persist_owned_asset(db_session, outcome, now=FIXED_NOW)

    assert not result.ok
    assert "no longer an eligible display-image asset" in result.abort_reason
    assert owned_asset_of(db_session, mapping.id) is None


def test_a_changed_stored_digest_after_verification_aborts_the_write(db_session, asset):
    """Not part of write_fingerprint, but it is the digest the whole record is
    keyed on, so it gets its own check."""
    mapping, print_row = asset
    outcome = mirror(db_session, print_row.id)
    replacement = BODY_SHA256[:16] + "a" * 48
    edit_evidence(db_session, mapping, lambda di: di["fetch"].__setitem__("sha256", replacement))

    result = persist_owned_asset(db_session, outcome, now=FIXED_NOW)

    assert not result.ok
    assert "stored fetch.sha256 changed" in result.abort_reason
    assert owned_asset_of(db_session, mapping.id) is None


def test_a_failed_mirror_can_never_produce_a_write(db_session, asset):
    mapping, print_row = asset
    storage = make_storage(StoringFakeS3Client())
    tampered = bytearray(BODY)
    tampered[7] ^= 0x40
    outcome = mirror_print(
        db_session,
        print_row.id,
        storage,
        fetcher=fetcher_for(BODY),
        public_fetcher=public_fetcher_for(bytes(tampered)),
    )
    assert not outcome.ok

    result = persist_owned_asset(db_session, outcome, now=FIXED_NOW)

    assert not result.ok
    assert "did not pass" in result.abort_reason
    assert owned_asset_of(db_session, mapping.id) is None


def test_network_work_is_finished_before_the_write_opens(db_session, asset):
    """No fetch may happen while a transaction is open: the fetchers are
    handed to the mirror phase and this module has none."""
    import io
    import tokenize
    from pathlib import Path

    source = Path(persist_module.__file__).read_text()
    # Identifiers only. Comments and docstrings discuss fetching at length,
    # and on 3.12 an f-string body is neither COMMENT nor STRING, so filtering
    # by token type alone would still catch prose inside one.
    names = {
        token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.NAME
    }
    for forbidden in ("httpx", "fetch", "get_object_bytes", "put_object", "head_object", "boto3"):
        offenders = [name for name in names if forbidden in name]
        assert not offenders, f"{offenders} must not appear in the persister"


# --- scope ------------------------------------------------------------------


def test_only_the_verified_mapping_changes(db_session, asset):
    mapping_one, print_one = asset
    mapping_two, print_two = _make_asset(db_session, card_code="OP01-014")
    before_two = copy.deepcopy(mapping_two.match_explanation_json)

    persist_owned_asset(db_session, mirror(db_session, print_one.id), now=FIXED_NOW)

    db_session.expire_all()
    assert owned_asset_of(db_session, mapping_one.id) is not None
    assert owned_asset_of(db_session, mapping_two.id) is None
    assert db_session.get(SourceCardMapping, mapping_two.id).match_explanation_json == before_two


def test_quarantined_and_unapproved_mappings_are_untouched(db_session, asset):
    mapping_one, print_one = asset
    quarantined, _ = _make_asset(db_session, card_code="OP01-015")
    quarantined.review_status = "needs_review"
    quarantined.is_active = False
    db_session.commit()
    before = copy.deepcopy(quarantined.match_explanation_json)

    persist_owned_asset(db_session, mirror(db_session, print_one.id), now=FIXED_NOW)

    db_session.expire_all()
    fresh = db_session.get(SourceCardMapping, quarantined.id)
    assert fresh.match_explanation_json == before
    assert OWNED_ASSET_KEY not in fresh.match_explanation_json["display_image"]
    assert fresh.review_status == "needs_review" and fresh.is_active is False


def test_a_bandai_fallback_print_is_untouched(db_session, asset):
    """A print with no eligible SNKRDUNK mapping keeps serving the canonical
    Bandai image and gains no evidence of any kind."""
    mapping_one, print_one = asset
    canonical = make_canonical(db_session, card_code="OP01-020", name_en="Zoro")
    bandai_print = make_print(
        db_session, canonical, treatment="normal", image_url="https://bandai.example/OP01-020.png"
    )

    persist_owned_asset(db_session, mirror(db_session, print_one.id), now=FIXED_NOW)

    db_session.expire_all()
    assert bandai_print.image_url == "https://bandai.example/OP01-020.png"
    assert (
        db_session.query(SourceCardMapping)
        .filter(SourceCardMapping.card_print_id == bandai_print.id)
        .count()
        == 0
    )


# --- the public API is unaffected -------------------------------------------


def test_get_prints_response_is_unchanged_by_the_new_evidence(db_session, client, asset):
    mapping, print_row = asset

    def snapshot():
        body = client.get("/prints").json()
        for item in body["items"]:
            # Recomputed per request from live observations; nothing to do
            # with display images, and it is a timestamp.
            (item.get("market_index") or {}).pop("calculated_at", None)
        return body

    before = snapshot()
    persist_owned_asset(db_session, mirror(db_session, print_row.id), now=FIXED_NOW)
    after = snapshot()

    assert after == before
    display = next(
        (p["display_image"] for p in after["items"] if p["card_print_id"] == print_row.id),
        None,
    )
    assert display is not None
    assert OWNED_ASSET_KEY not in display
    assert display["url"] == URL  # still the source URL, not an R2 one
    assert "r2.dev" not in repr(after)


def test_the_public_schema_has_no_owned_asset_field():
    """Structural, not incidental: DisplayImageOut cannot carry the internal
    record even if something tried to pass it.

    `owned_asset_selected` is a derived boolean, not the record: it says which
    read-path branch supplied `url` and carries no digest, key, byte size or
    cache policy. The record itself must still be absent."""
    from app.schemas import DisplayImageOut

    assert OWNED_ASSET_KEY not in DisplayImageOut.model_fields
    assert set(DisplayImageOut.model_fields) == {
        "url",
        "source",
        "exact_print_verified",
        "owned_asset_selected",
        "geometry",
    }
    assert DisplayImageOut.model_fields["owned_asset_selected"].annotation is bool


def test_build_owned_asset_is_pure(db_session, asset):
    """It reads an outcome and returns a dict - no session, no write."""
    outcome = mirror(db_session, asset[1].id)
    first = build_owned_asset(outcome, "2026-08-15T00:00:00+00:00")
    second = build_owned_asset(outcome, "2026-08-15T00:00:00+00:00")

    assert first == second
    assert owned_asset_of(db_session, asset[0].id) is None


# --- the command ------------------------------------------------------------


def _patch_cli(monkeypatch, db_session, client_obj=None):
    from app import mirror_display_image_to_r2 as cli
    from app.services import display_image_upload as upload
    from app.services.object_storage import R2ObjectStorage

    fake = client_obj if client_obj is not None else StoringFakeS3Client()
    monkeypatch.setattr(
        R2ObjectStorage, "from_settings", classmethod(lambda c, s=None: make_storage(fake))
    )
    monkeypatch.setattr(cli, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)
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
    return cli


def test_the_cli_writes_nothing_without_the_flag(monkeypatch, capsys, db_session, asset):
    """Persistence is never the default and never implied."""
    cli = _patch_cli(monkeypatch, db_session)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--print-id", str(asset[1].id)])

    assert exit_info.value.code == cli.EXIT_OK
    assert "no database row was created" in capsys.readouterr().out
    assert owned_asset_of(db_session, asset[0].id) is None


def test_the_cli_persists_with_the_flag_and_announces_the_write(
    monkeypatch, capsys, db_session, asset
):
    cli = _patch_cli(monkeypatch, db_session)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--print-id", str(asset[1].id), "--persist-owned-asset"])

    out = capsys.readouterr().out
    assert exit_info.value.code == cli.EXIT_OK
    assert "DATABASE WRITE - recording display_image.owned_asset" in out
    assert "owned_asset written to mapping" in out
    assert EXPECTED_KEY in out
    stored = owned_asset_of(db_session, asset[0].id)
    assert stored is not None and stored["sha256"] == BODY_SHA256


def test_the_cli_reports_an_idempotent_second_run(monkeypatch, capsys, db_session, asset):
    cli = _patch_cli(monkeypatch, db_session)
    with pytest.raises(SystemExit):
        cli.main(["--print-id", str(asset[1].id), "--persist-owned-asset"])
    capsys.readouterr()
    first = owned_asset_of(db_session, asset[0].id)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--print-id", str(asset[1].id), "--persist-owned-asset"])

    out = capsys.readouterr().out
    assert exit_info.value.code == cli.EXIT_OK
    assert "already recorded" in out and "verified_at not refreshed" in out
    assert owned_asset_of(db_session, asset[0].id) == first
