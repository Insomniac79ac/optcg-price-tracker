"""Owner-confirmed SNKRDUNK photos (owner 2026-11-04, plan B): honoured only for exactly what the
owner looked at, and never for anything the matcher did not compare."""

import json

import pytest

from snkrdunk_collector import owner_artwork as oa

PHOTO = "https://cdn.snkrdunk.com/upload_bg_removed/34fc4c78-b.webp"
ENTRY = {"mapping_id": 4456, "card_print_id": 5862, "listing": "102462", "photo_url": PHOTO,
         "confirmed_by": "owner", "verdict": "same", "confirmed_on": "2026-11-03"}
REFUSED = {"match": False, "hash_distances": {"average_hash": 24, "dhash": 9, "phash": 14},
           "aspect_ratio_relative_diff": 0.0}


def write(tmp_path, entries, **extra):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"schema_version": 1, "confirmations": entries, **extra}), encoding="utf-8")
    return path


def entries(tmp_path, *rows):
    return oa.confirmations(write(tmp_path, list(rows)))


def test_the_committed_file_loads():
    assert isinstance(oa.confirmations(), dict)


def test_an_exact_confirmation_turns_a_refused_comparison_into_an_owner_match(tmp_path):
    out = oa.confirm(REFUSED, mapping_id=4456, card_print_id=5862, listing="102462", photo_url=PHOTO,
                     entries=entries(tmp_path, ENTRY))
    assert out["match"] is True
    assert out["owner_confirmed"] == {"confirmed_on": "2026-11-03", "photo_url": PHOTO}
    assert out["hash_distances"] == REFUSED["hash_distances"]  # the matcher's evidence is kept


@pytest.mark.parametrize("change", [
    {"photo_url": PHOTO + "?v=2"},   # a changed photo is checked again
    {"card_print_id": 5861},         # remapped to another print
    {"listing": "102463"},           # another listing
    {"mapping_id": 4457},            # another mapping
])
def test_anything_other_than_what_the_owner_saw_is_left_to_the_matcher(tmp_path, change):
    args = {"mapping_id": 4456, "card_print_id": 5862, "listing": "102462", "photo_url": PHOTO, **change}
    assert oa.confirm(REFUSED, entries=entries(tmp_path, ENTRY), **args) is REFUSED


@pytest.mark.parametrize("comparison", [
    {"match": False, "available": False, "error": "image_fetch_failed"},
    {"match": False, "error": "decode_error:x"},
    {"match": False},  # no comparison ran
])
def test_an_uncompared_or_unreadable_photo_is_never_confirmable(tmp_path, comparison):
    out = oa.confirm(comparison, mapping_id=4456, card_print_id=5862, listing="102462", photo_url=PHOTO,
                     entries=entries(tmp_path, ENTRY))
    assert out is comparison


def test_a_matcher_match_is_returned_unchanged(tmp_path):
    ok = {"match": True, "hash_distances": {}}
    assert oa.confirm(ok, mapping_id=1, card_print_id=2, listing="3", photo_url=PHOTO,
                      entries=entries(tmp_path, ENTRY)) is ok


@pytest.mark.parametrize("bad", [
    {"confirmed_by": "claude"},
    {"verdict": "other:p1"},
    {"photo_url": "http://cdn.snkrdunk.com/x.webp"},
    {"confirmed_on": "3 Nov"},
    {"mapping_id": "4456"},
    {"card_print_id": True},
    {"listing": ""},
])
def test_the_file_fails_closed_on_any_malformed_entry(tmp_path, bad):
    with pytest.raises(ValueError):
        entries(tmp_path, {**ENTRY, **bad})


def test_duplicates_and_unknown_schema_fail_closed(tmp_path):
    with pytest.raises(ValueError):
        entries(tmp_path, ENTRY, dict(ENTRY))
    path = tmp_path / "v2.json"
    path.write_text(json.dumps({"schema_version": 2, "confirmations": []}), encoding="utf-8")
    with pytest.raises(ValueError):
        oa.confirmations(path)
