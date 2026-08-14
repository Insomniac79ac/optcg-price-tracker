"""Bootstrap SHA-256 persistence (app.services.display_image_mirror
::persist_bootstrap_digests).

This is the only write in the mirroring pipeline so far, and it is deliberately
a narrow one: three additive keys inside an existing
``display_image.fetch`` block, written only after every selected asset has
been re-fetched and fully verified. What these tests exist to pin:

  * **Batch atomicity.** One verification failure, one row that changed under
    us, one contradicting stored digest - any of them and *nothing* is
    written. Partial bootstrap evidence would be worse than none, because a
    later run could not tell a bootstrapped asset from an unwritten one.
  * **Additive-only.** Every pre-existing key, inside display_image and
    outside it, survives byte-identically. `fetch.fetched_at` in particular is
    never touched: the full digest was established by a *later* re-fetch, and
    moving that timestamp would misrepresent it as historical evidence.
  * **Idempotency.** Re-running is a no-op, not a rewrite.
  * **Invisibility.** GET /prints is unchanged; the digest is internal
    verification evidence, not part of the public contract.
  * **The JSON write actually lands.** The column is a plain JSON type with no
    MutableDict wrapper, so an in-place nested mutation could silently
    no-op - one test commits and re-reads through a *separate* session to
    prove the value is really in the database.
"""

from __future__ import annotations

import copy
import hashlib
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.models import CardPrint, SourceCardMapping
from app.services import display_image_mirror as mirror
from app.services.display_image_mirror import (
    BOOTSTRAP_SHA256_ORIGIN,
    persist_bootstrap_digests,
    run_verification,
)
from tests.test_display_image_mirror import (
    BODY,
    BODY_SHA256,
    CANVAS,
    CARD_PX,
    STORED_BBOX,
    URL,
    fetcher_for,
    make_image_bytes,
    payload_for,
)
from tests.test_prints import (  # noqa: F401  (db_session/client come from conftest)
    make_canonical,
    make_legacy_card,
    make_mapping,
    make_print,
    make_source,
)

BANDAI_URL = "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-013.png?260630"

# A second top-level key on the same column, exactly like the real rows, which
# carry `production_run_2026_08_11` next to `display_image`. Nothing outside
# display_image may be disturbed by the write.
OTHER_EVIDENCE = {
    "production_run_2026_08_11": {
        "commit_sha": "04e7d8dc808b4bdc78a7d996fb11c94f8bf915f1",
        "raw_market": {"raw_floor_jpy": 24500, "raw_floor_condition": "B"},
    }
}


def full_payload(mapping_id: int, card_print_id: int, **overrides) -> dict:
    """The retained display_image evidence, with the fields the real rows
    carry that the selection contract does not require - so the test can prove
    they survive."""
    payload = payload_for(mapping_id, card_print_id, **overrides)
    payload.setdefault(
        "artwork_comparison", {"phash_distance": 4, "normalized_cross_correlation": 0.994}
    )
    payload.setdefault(
        "evidence_provenance",
        "retained approved mapping product_image_url, fetched once offline on 2026-08-13",
    )
    return payload


def make_asset(db_session, card_code: str, treatment: str, body: bytes = BODY, **payload_overrides):
    """One approved, manually verified SNKRDUNK mapping with real evidence."""
    canonical = make_canonical(db_session, card_code=card_code, name_en=f"Card {card_code}")
    legacy = make_legacy_card(db_session, card_code=card_code)
    print_row = make_print(
        db_session,
        canonical,
        treatment=treatment,
        artwork_key=f"art-{card_code}-{treatment}",
        image_url=BANDAI_URL,
    )
    mapping = make_mapping(
        db_session,
        legacy,
        make_source(db_session, "snkrdunk"),
        print_row,
        is_active=True,
        review_status="approved",
        manual_verified=True,
    )
    digest = hashlib.sha256(body).hexdigest()
    payload = full_payload(mapping.id, print_row.id, **payload_overrides)
    payload["fetch"] = {**payload["fetch"], "bytes": len(body), "sha256_prefix": digest[:16]}
    mapping.match_explanation_json = {"display_image": payload, **copy.deepcopy(OTHER_EVIDENCE)}
    db_session.commit()
    return mapping, print_row


@pytest.fixture()
def asset(db_session):
    mapping, print_row = make_asset(db_session, "OP01-013", "normal")
    return mapping


def persist(db_session, fetcher=None, **kwargs):
    """Verify then persist, the way the CLI composes the two phases."""
    report = run_verification(db_session, fetcher=fetcher or fetcher_for(), **kwargs)
    return report, persist_bootstrap_digests(db_session, report)


def fetch_block(db_session, mapping_id: int) -> dict:
    db_session.expire_all()
    mapping = db_session.get(SourceCardMapping, mapping_id)
    return mapping.match_explanation_json["display_image"]["fetch"]


# --- the write --------------------------------------------------------------


def test_verified_asset_gets_the_full_digest_persisted(db_session, asset):
    report, outcome = persist(db_session)

    assert outcome.ok, outcome.abort_reason
    assert outcome.updated == [asset.id]
    assert outcome.already_bootstrapped == []
    assert report.passed == 1

    fetch = fetch_block(db_session, asset.id)
    assert fetch["sha256"] == BODY_SHA256
    assert len(fetch["sha256"]) == 64
    assert fetch["sha256"] == fetch["sha256"].lower()
    assert fetch["sha256"][:16] == fetch["sha256_prefix"]


def test_the_digest_is_the_hash_of_the_body_verified_in_this_run(db_session):
    """Not a replayed constant: a different asset persists a different digest,
    computed from the bytes its own verification fetched."""
    other_body = make_image_bytes(bbox=[100, 20, 473, 542], canvas=(856, 625))
    mapping, _ = make_asset(
        db_session,
        "OP02-001",
        "normal",
        body=other_body,
        geometry={
            "canvas_px": list(CANVAS),
            "card_bbox_px": [100, 20, 473, 542],
            "card_px": [374, 523],
        },
    )

    _, outcome = persist(db_session, fetcher=fetcher_for(other_body))

    assert outcome.ok, outcome.abort_reason
    assert fetch_block(db_session, mapping.id)["sha256"] == hashlib.sha256(other_body).hexdigest()


def test_provenance_fields_mark_this_as_a_bootstrap_refetch(db_session, asset):
    before = datetime.now(timezone.utc)
    persist(db_session)
    after = datetime.now(timezone.utc)

    fetch = fetch_block(db_session, asset.id)
    assert fetch["sha256_origin"] == BOOTSTRAP_SHA256_ORIGIN == "bootstrap_refetch"

    recorded_at = datetime.fromisoformat(fetch["sha256_recorded_at"])
    assert recorded_at.tzinfo is not None
    assert recorded_at.utcoffset() == timezone.utc.utcoffset(None)
    assert before <= recorded_at <= after


def test_the_historical_fetch_timestamp_is_not_moved(db_session, asset):
    """The full digest was established later, by a re-fetch. Rewriting
    fetched_at would make it read as historical evidence, which it is not."""
    original = copy.deepcopy(asset.match_explanation_json["display_image"]["fetch"])

    persist(db_session)

    fetch = fetch_block(db_session, asset.id)
    assert fetch["fetched_at"] == original["fetched_at"]
    assert fetch["sha256_recorded_at"] != fetch["fetched_at"]


@pytest.mark.parametrize(
    "key", ["bytes", "sha256_prefix", "fetched_at", "final_host", "redirected", "http_status", "content_type"]
)
def test_every_pre_existing_fetch_field_is_unchanged(db_session, asset, key):
    original = copy.deepcopy(asset.match_explanation_json["display_image"]["fetch"])

    persist(db_session)

    assert fetch_block(db_session, asset.id)[key] == original[key]


def test_only_the_three_bootstrap_keys_are_added_anywhere(db_session, asset):
    before = copy.deepcopy(asset.match_explanation_json)

    persist(db_session)

    db_session.expire_all()
    after = copy.deepcopy(db_session.get(SourceCardMapping, asset.id).match_explanation_json)

    # Everything outside display_image.fetch is identical, key for key.
    assert after["production_run_2026_08_11"] == before["production_run_2026_08_11"]
    assert set(after) == set(before)
    for key in before["display_image"]:
        if key != "fetch":
            assert after["display_image"][key] == before["display_image"][key], key

    added = set(after["display_image"]["fetch"]) - set(before["display_image"]["fetch"])
    assert added == {"sha256", "sha256_recorded_at", "sha256_origin"}
    for key, value in before["display_image"]["fetch"].items():
        assert after["display_image"]["fetch"][key] == value, key


def test_the_write_survives_commit_and_a_fresh_session_read(db_session, asset):
    """The JSON column has no mutation tracking, so this is the test that
    proves the new object assignment really reached the database rather than
    living only in the identity map."""
    persist(db_session)

    fresh = Session(bind=db_session.get_bind())
    try:
        reread = fresh.get(SourceCardMapping, asset.id)
        assert reread.match_explanation_json["display_image"]["fetch"]["sha256"] == BODY_SHA256
    finally:
        fresh.close()


# --- idempotency ------------------------------------------------------------


def test_re_running_is_idempotent_and_rewrites_nothing(db_session, asset):
    persist(db_session)
    first = copy.deepcopy(fetch_block(db_session, asset.id))

    _, outcome = persist(db_session)

    assert outcome.ok
    assert outcome.updated == []
    assert outcome.already_bootstrapped == [asset.id]
    # Same digest, and the recorded-at timestamp was not refreshed.
    assert fetch_block(db_session, asset.id) == first


def test_a_conflicting_stored_digest_hard_fails_without_overwriting(db_session, asset):
    """Once persisted, the full digest is the strongest identity evidence the
    record has. A run that disagrees with it aborts; it does not revise it."""
    conflicting = BODY_SHA256[:16] + "f" * 48
    payload = copy.deepcopy(asset.match_explanation_json)
    payload["display_image"]["fetch"]["sha256"] = conflicting
    payload["display_image"]["fetch"]["sha256_origin"] = BOOTSTRAP_SHA256_ORIGIN
    asset.match_explanation_json = payload
    db_session.commit()

    _, outcome = persist(db_session)

    assert not outcome.ok
    assert "refusing to overwrite" in outcome.abort_reason
    assert outcome.updated == []
    assert fetch_block(db_session, asset.id)["sha256"] == conflicting


def test_a_malformed_stored_digest_is_not_selected_at_all(db_session, asset):
    payload = copy.deepcopy(asset.match_explanation_json)
    payload["display_image"]["fetch"]["sha256"] = "not-a-digest"
    asset.match_explanation_json = payload
    db_session.commit()

    report, outcome = persist(db_session)

    assert report.selected == 0
    assert not outcome.ok
    assert fetch_block(db_session, asset.id)["sha256"] == "not-a-digest"


# --- batch atomicity --------------------------------------------------------


def test_one_verification_failure_writes_nothing_for_the_whole_batch(db_session):
    """Two eligible assets, one of which no longer matches its evidence: the
    healthy one must not be written either."""
    good, _ = make_asset(db_session, "OP01-013", "normal")
    # `bad`'s retained evidence describes different bytes, so when the fetcher
    # serves `good`'s image its length and prefix both mismatch.
    bad, _ = make_asset(
        db_session, "OP02-001", "normal", body=make_image_bytes(bbox=[100, 20, 473, 542])
    )
    report, outcome = persist(db_session, fetcher=fetcher_for(BODY))

    assert report.selected == 2
    assert not outcome.ok
    assert "verification did not pass" in outcome.abort_reason
    for mapping_id in (good.id, bad.id):
        assert "sha256" not in fetch_block(db_session, mapping_id)


def test_evidence_changed_between_verification_and_write_aborts(db_session, asset):
    report = run_verification(db_session, fetcher=fetcher_for())
    assert report.ok

    # A concurrent editor rewrites the retained byte length.
    payload = copy.deepcopy(asset.match_explanation_json)
    payload["display_image"]["fetch"]["bytes"] = len(BODY) + 1
    asset.match_explanation_json = payload
    db_session.commit()

    outcome = persist_bootstrap_digests(db_session, report)

    assert not outcome.ok
    assert "changed between verification and write" in outcome.abort_reason
    assert "sha256" not in fetch_block(db_session, asset.id)


def test_geometry_changed_between_verification_and_write_aborts(db_session, asset):
    report = run_verification(db_session, fetcher=fetcher_for())

    payload = copy.deepcopy(asset.match_explanation_json)
    payload["display_image"]["geometry"]["card_bbox_px"] = [240, 51, 613, 573]
    asset.match_explanation_json = payload
    db_session.commit()

    outcome = persist_bootstrap_digests(db_session, report)

    assert not outcome.ok
    assert "sha256" not in fetch_block(db_session, asset.id)


@pytest.mark.parametrize(
    "column, value",
    [("review_status", "needs_review"), ("is_active", False), ("manual_verified", False)],
)
def test_mapping_becomes_ineligible_between_verification_and_write_aborts(
    db_session, asset, column, value
):
    report = run_verification(db_session, fetcher=fetcher_for())
    assert report.ok

    setattr(asset, column, value)
    db_session.commit()

    outcome = persist_bootstrap_digests(db_session, report)

    assert not outcome.ok
    assert "no longer an eligible display-image asset" in outcome.abort_reason
    assert "sha256" not in fetch_block(db_session, asset.id)


def test_a_batch_with_one_conflicting_digest_writes_none_of_the_others(db_session):
    good, _ = make_asset(db_session, "OP01-013", "normal")
    conflicted, _ = make_asset(db_session, "OP05-001", "normal")
    payload = copy.deepcopy(conflicted.match_explanation_json)
    payload["display_image"]["fetch"]["sha256"] = BODY_SHA256[:16] + "e" * 48
    conflicted.match_explanation_json = payload
    db_session.commit()

    _, outcome = persist(db_session)

    assert not outcome.ok
    assert outcome.updated == []
    assert "sha256" not in fetch_block(db_session, good.id)


# --- what must not be touched -----------------------------------------------


def test_quarantined_mappings_are_never_written(db_session):
    """42/43/49/52 are approved and carry evidence here on purpose - the
    quarantine guard, not their review state, is what must keep them out."""
    canonical = make_canonical(db_session, card_code="OP03-001", name_en="Quarantined")
    legacy = make_legacy_card(db_session, card_code="OP03-001")
    print_row = make_print(db_session, canonical, treatment="normal", image_url=BANDAI_URL)
    source = make_source(db_session, "snkrdunk")
    quarantined = []
    for mapping_id in sorted(mirror.QUARANTINED_MAPPING_IDS):
        mapping = make_mapping(
            db_session,
            legacy,
            source,
            print_row,
            id=mapping_id,
            source_card_id=f"ext-{mapping_id}",
            is_active=True,
            review_status="approved",
            manual_verified=True,
        )
        mapping.match_explanation_json = {
            "display_image": full_payload(mapping_id, print_row.id)
        }
        quarantined.append(mapping)
    db_session.commit()
    before = {m.id: copy.deepcopy(m.match_explanation_json) for m in quarantined}

    report, _ = persist(db_session)

    assert report.selected == 0
    assert report.quarantined_skipped == 4
    for mapping_id, original in before.items():
        db_session.expire_all()
        assert db_session.get(SourceCardMapping, mapping_id).match_explanation_json == original


def test_canonical_identity_columns_are_untouched(db_session, asset):
    print_row = db_session.get(CardPrint, asset.card_print_id)
    before = (print_row.image_url, print_row.artwork_key, print_row.canonical_card_id)

    persist(db_session)

    db_session.expire_all()
    print_row = db_session.get(CardPrint, asset.card_print_id)
    assert (print_row.image_url, print_row.artwork_key, print_row.canonical_card_id) == before
    assert print_row.image_url == BANDAI_URL


def test_mapping_identity_columns_are_untouched(db_session, asset):
    before = (
        asset.card_id,
        asset.card_print_id,
        asset.source_id,
        asset.source_card_id,
        asset.review_status,
        asset.is_active,
    )

    persist(db_session)

    db_session.expire_all()
    mapping = db_session.get(SourceCardMapping, asset.id)
    assert (
        mapping.card_id,
        mapping.card_print_id,
        mapping.source_id,
        mapping.source_card_id,
        mapping.review_status,
        mapping.is_active,
    ) == before


def test_a_bandai_fallback_print_is_untouched(db_session, asset):
    """A print with no display-image evidence keeps serving canonical Bandai
    artwork, exactly as prints 8/9/15/18 do on staging."""
    canonical = make_canonical(db_session, card_code="OP04-001", name_en="Fallback")
    fallback = make_print(
        db_session, canonical, treatment="normal", artwork_key="art-fb", image_url=BANDAI_URL
    )
    before = (fallback.image_url, fallback.artwork_key)

    persist(db_session)

    db_session.expire_all()
    reread = db_session.get(CardPrint, fallback.id)
    assert (reread.image_url, reread.artwork_key) == before


# --- the public contract ----------------------------------------------------


def _display_image(client, print_id: int) -> dict:
    response = client.get(f"/prints/{print_id}")
    assert response.status_code == 200
    return response.json()["display_image"]


def test_get_prints_response_is_unchanged_by_persistence(db_session, client, asset):
    before = _display_image(client, asset.card_print_id)

    _, outcome = persist(db_session)
    assert outcome.ok

    after = _display_image(client, asset.card_print_id)
    assert after == before
    assert after["url"] == URL
    assert after["source"] == "snkrdunk"
    assert after["geometry"] == {
        "canvas_px": {"width": CANVAS[0], "height": CANVAS[1]},
        "card_bbox_px": {
            "x": STORED_BBOX[0],
            "y": STORED_BBOX[1],
            "width": CARD_PX[0],
            "height": CARD_PX[1],
        },
    }


def test_the_persisted_digest_is_not_exposed_publicly(db_session, client, asset):
    persist(db_session)

    payload = client.get(f"/prints/{asset.card_print_id}").json()

    assert BODY_SHA256 not in str(payload)
    assert "sha256" not in str(payload["display_image"])


def _catalogue(client) -> dict:
    """The whole /prints payload, minus the one value that legitimately
    differs between any two requests: market_index.calculated_at is stamped
    per request from the wall clock, not from anything this tranche stores."""
    payload = client.get("/prints").json()
    for item in payload["items"]:
        if item.get("market_index"):
            item["market_index"].pop("calculated_at", None)
    return payload


def test_the_whole_catalogue_payload_is_unchanged_by_persistence(db_session, client, asset):
    before = _catalogue(client)

    _, outcome = persist(db_session)
    assert outcome.ok

    assert _catalogue(client) == before


# --- mode separation --------------------------------------------------------


def test_dry_run_verification_alone_writes_nothing(db_session, asset):
    """run_verification is what --dry-run calls; on its own it must never
    produce a write, however many times it runs."""
    before = copy.deepcopy(asset.match_explanation_json)

    run_verification(db_session, fetcher=fetcher_for())
    run_verification(db_session, fetcher=fetcher_for())

    assert not db_session.dirty
    assert not db_session.new
    db_session.expire_all()
    assert db_session.get(SourceCardMapping, asset.id).match_explanation_json == before


def test_persistence_refuses_a_report_it_did_not_verify_cleanly(db_session, asset):
    """The precondition is the report itself: a failed verification can never
    be turned into a write by calling the persist function directly."""
    report = run_verification(db_session, fetcher=fetcher_for(make_image_bytes(bbox=[100, 20, 473, 542])))
    assert not report.ok

    outcome = persist_bootstrap_digests(db_session, report)

    assert not outcome.ok
    assert "sha256" not in fetch_block(db_session, asset.id)


def test_no_storage_or_migration_work_appeared_in_this_tranche():
    """Tranche boundary, again: persistence is a JSON key on an existing
    column - no storage client, and no new Alembic revision."""
    from pathlib import Path

    source = Path(mirror.__file__).read_text(encoding="utf-8")
    for forbidden in ("boto3", "put_object", "upload_fileobj", "cloudflarestorage"):
        assert forbidden not in source, forbidden

    versions = Path(mirror.__file__).parents[2] / "alembic" / "versions"
    migrations = list(versions.glob("*.py"))
    assert not [m for m in migrations if "sha256" in m.read_text(encoding="utf-8").lower()]
