"""The frozen snapshot reader: parses, never derives, and never reaches out.

The apply engine's whole input-pinning story rests on this module reading the
same bytes twice and saying so, and on it refusing a snapshot that is not what
the caller asked for.
"""

import json
from pathlib import Path

import pytest

from app.services import snapshot_planner_input as S

CARD_LIST = "https://www.onepiece-cardgame.com/images/cardlist/card"


def _write(root: Path, *, entries=None, series=None, assets=None, manifest=None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    entries = entries if entries is not None else [
        {
            "entry_id": "OP01-001",
            "card_code": "OP01-001",
            "card_name": "モンキー・D・ルフィ",
            "rarity": "L",
            "category": "LEADER",
            "image_url": f"{CARD_LIST}/OP01-001.png?260101",
            "product_names": ["ROMANCE DAWN【OP-01】"],
            "source_series_id": "550101",
            "source_url": "https://www.onepiece-cardgame.com/cardlist/?series=550101",
            "product_title": "ROMANCE DAWN【OP-01】",
            "product_code": "OP-01",
            "fields": [
                {"name": "cost", "label": "コスト", "value": "2",
                 "image_alt": None, "image_src": None},
                {"name": "attribute", "label": "属性", "value": "-",
                 "image_alt": "斬", "image_src": "/images/slash.png"},
            ],
            "fragment_sha256": "f" * 64,
        }
    ]
    series = series if series is not None else [
        {
            "source_series_id": "550101",
            "display_name": "ROMANCE DAWN【OP-01】",
            "official_code": "OP-01",
            "source_url": "https://www.onepiece-cardgame.com/cardlist/?series=550101",
            "entry_count": 1,
        }
    ]
    assets = assets if assets is not None else [
        {"url": f"{CARD_LIST}/OP01-001.png?260101", "sha256": "a" * 64,
         "basename": "OP01-001.png"}
    ]
    manifest = manifest if manifest is not None else {
        "source_catalogue": "bandai_jp",
        "snapshot_version": 1,
        "started_at": "2026-08-22T14:31:59+00:00",
        "finished_at": "2026-08-22T14:32:15+00:00",
    }
    for name, rows in ((S.ENTRIES, entries), (S.SERIES, series), (S.ASSETS, assets)):
        (root / name).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
        )
    (root / S.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    return root


@pytest.fixture
def snapshot_root(tmp_path):
    return _write(tmp_path / "current")


def test_entries_come_back_with_their_published_blocks_intact(snapshot_root):
    snapshot = S.load_snapshot(snapshot_root)

    entry = snapshot.entries[0]
    assert entry.entry_id == "OP01-001"
    assert entry.card_name == "モンキー・D・ルフィ"
    assert entry.product_names == ("ROMANCE DAWN【OP-01】",)
    # Bandai's own div class is the key the planner reads by; renaming it here
    # would silently feed the wrong block to the wrong column.
    assert entry.field("cost").value == "2"
    assert entry.field("attribute").image_alt == "斬"


def test_nothing_is_normalised_on_the_way_in(snapshot_root):
    """A '-' stays a '-'; it is a published value meaning absence."""
    snapshot = S.load_snapshot(snapshot_root)

    assert snapshot.entries[0].field("attribute").value == "-"


def test_series_rebuild_carries_the_official_code(snapshot_root):
    snapshot = S.load_snapshot(snapshot_root)

    assert snapshot.series[0].official_code == "OP-01"
    assert snapshot.series[0].series_id == "550101"


def test_the_digest_provider_answers_only_for_fetched_assets(snapshot_root):
    provider = S.load_snapshot(snapshot_root).digest_provider()

    assert provider(f"{CARD_LIST}/OP01-001.png?260101") == "a" * 64
    # Never a guess: an asset the snapshot did not fetch has no digest, which
    # is what makes its print fall to needs_review.
    assert provider(f"{CARD_LIST}/OP99-999.png") is None


def test_identity_is_stable_across_reads(snapshot_root):
    assert S.load_snapshot(snapshot_root).identity == S.load_snapshot(snapshot_root).identity


def test_identity_changes_when_a_record_file_changes(snapshot_root):
    before = S.load_snapshot(snapshot_root).identity
    with (snapshot_root / S.ASSETS).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"url": "x", "sha256": "b" * 64}) + "\n")

    assert S.load_snapshot(snapshot_root).identity != before


def test_identity_changes_when_the_manifest_timestamps_change(snapshot_root):
    before = S.load_snapshot(snapshot_root).identity
    manifest = json.loads((snapshot_root / S.MANIFEST).read_text())
    manifest["finished_at"] = "2026-08-23T00:00:00+00:00"
    (snapshot_root / S.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")

    assert S.load_snapshot(snapshot_root).identity != before


def test_a_snapshot_from_another_catalogue_is_refused(tmp_path):
    root = _write(
        tmp_path / "current",
        manifest={"source_catalogue": "bandai_en", "snapshot_version": 1,
                  "started_at": "x", "finished_at": "y"},
    )

    with pytest.raises(S.SnapshotInputError, match="bandai_en"):
        S.load_snapshot(root, source_catalogue="bandai_jp")


def test_a_missing_record_file_is_refused_rather_than_read_as_empty(tmp_path):
    root = _write(tmp_path / "current")
    (root / S.ASSETS).unlink()

    with pytest.raises(S.SnapshotInputError, match="missing"):
        S.load_snapshot(root)


def test_a_missing_directory_is_refused(tmp_path):
    with pytest.raises(S.SnapshotInputError, match="not found"):
        S.load_snapshot(tmp_path / "nope")


def test_malformed_jsonl_names_the_line(tmp_path):
    root = _write(tmp_path / "current")
    good = json.dumps({"entry_id": "a", "card_code": "OP01-001"})
    (root / S.ENTRIES).write_text(f"{good}\nnot json\n", encoding="utf-8")

    with pytest.raises(S.SnapshotInputError, match=":2"):
        S.load_snapshot(root)


def test_an_entry_missing_its_identity_is_refused_not_defaulted(tmp_path):
    root = _write(tmp_path / "current")
    (root / S.ENTRIES).write_text(json.dumps({"card_name": "x"}) + "\n", encoding="utf-8")

    with pytest.raises(S.SnapshotInputError, match="entry_id"):
        S.load_snapshot(root)


def test_the_reader_performs_no_network_io():
    source = Path(S.__file__).read_text(encoding="utf-8")

    for forbidden in ("requests", "urllib.request", "httpx", "urlopen", "socket"):
        assert forbidden not in source


def test_describe_reports_what_a_run_should_pin_itself_to(snapshot_root):
    described = S.load_snapshot(snapshot_root).describe()

    assert described["source_catalogue"] == "bandai_jp"
    assert described["entries"] == 1
    assert described["assets_with_digest"] == 1
    assert len(described["snapshot_identity"]) == 64


def test_entry_source_records_the_series_each_occurrence_came_from(snapshot_root):
    snapshot = S.load_snapshot(snapshot_root)

    assert snapshot.entry_source["OP01-001"]["source_series_id"] == "550101"
    assert snapshot.entry_source["OP01-001"]["product_code"] == "OP-01"
