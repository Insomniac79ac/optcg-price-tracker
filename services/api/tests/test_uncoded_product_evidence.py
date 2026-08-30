"""The JP-only evidence standard for establishing an uncoded Bandai product.

Every rule is exercised against the FROZEN snapshots where they are checked
out, and against hand-built fixtures where they are not, so the standard is
tested rather than the fixture.
"""

import json
import pathlib

import pytest

from app.services.uncoded_product_evidence import (
    UNCODED_SERIES_IDS,
    UncodedProductEvidenceError,
    prove_asia_en_carries_no_uncoded_names,
    prove_uncoded_product,
)

SNAPSHOTS = pathlib.Path(__file__).resolve().parents[3] / "data" / "official_snapshots"
JP = SNAPSHOTS / "bandai_jp" / "current"
EN = SNAPSHOTS / "bandai_asia_en" / "current"

frozen = pytest.mark.skipif(
    not (JP / "entries.jsonl").exists() or not (EN / "entries.jsonl").exists(),
    reason="frozen catalogue snapshots are gitignored (~1GB) and not checked out",
)

# The six this tranche establishes, with their proven member counts.
SIX = [
    ("プレミアムカードコレクション - ベストセレクションvol.1 -", "550801", 12),
    ("プレミアムカードコレクション 25周年エディション", "550801", 10),
    ("スタンダードバトルパック2022 Vol.1", "550901", 3),
    ("スタンダードバトルパック2022 Vol.2", "550901", 4),
    ("スタンダードバトルパック Vol.3", "550901", 4),
    ("1st ANNIVERSARY SET", "550801", 3),
]


# --- 1. uncoded product identity -------------------------------------------
@frozen
@pytest.mark.parametrize("name, series_id, size", SIX)
def test_each_scoped_product_is_proven_from_the_frozen_jp_catalogue(name, series_id, size):
    ev = prove_uncoded_product(name, jp_root=JP, asia_en_root=EN, snapshot_identity="test")
    assert ev.product_name == name
    assert ev.source_series_id == series_id
    assert ev.source_series_id in UNCODED_SERIES_IDS
    assert len(ev.member_card_codes) == size
    assert len(set(ev.member_card_codes)) == size, "a card code appears twice"


# --- 10. no invented official_code -----------------------------------------
@frozen
@pytest.mark.parametrize("name, _s, _n", SIX)
def test_an_uncoded_product_never_acquires_an_official_code(name, _s, _n):
    """The whole point of the tranche, stated as a test: identity comes from
    the surrogate id and the frozen name, never from a code somebody minted."""
    ev = prove_uncoded_product(name, jp_root=JP, asia_en_root=EN, snapshot_identity="test")
    assert ev.official_code is None
    assert ev.as_provenance()["official_code"] is None


# --- 8. the JP-only rule, and that it is recorded ---------------------------
@frozen
def test_the_asia_en_absence_is_measured_not_assumed():
    proof = prove_asia_en_carries_no_uncoded_names(EN)
    assert "product_names=0" in proof
    assert "624" in proof


@frozen
@pytest.mark.parametrize("name, _s, _n", SIX)
def test_jp_only_validation_is_recorded_on_every_accepted_product(name, _s, _n):
    ev = prove_uncoded_product(name, jp_root=JP, asia_en_root=EN, snapshot_identity="test")
    assert ev.jp_only_validation is True
    assert "Nothing to agree with" in ev.asia_en_absence_proof
    assert ev.as_provenance()["jp_only_validation"] is True


def test_the_jp_only_substitution_is_refused_when_asia_en_does_carry_names(tmp_path):
    """The substitution is conditional. If Asia-EN ever publishes uncoded
    product names, the cross-catalogue rule applies again and this refuses."""
    root = tmp_path / "asia"
    root.mkdir()
    (root / "series.jsonl").write_text(
        json.dumps({"source_series_id": "556901", "display_name": "Promotion card",
                    "official_code": None, "source_url": "https://x.test/1"}) + "\n",
        encoding="utf-8",
    )
    (root / "entries.jsonl").write_text(
        json.dumps({"source_series_id": "556901", "card_code": "OP01-001",
                    "product_names": ["Standard Battle Pack Vol.1"],
                    "product_title": "Promotion card"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(UncodedProductEvidenceError) as exc:
        prove_asia_en_carries_no_uncoded_names(root)
    assert exc.value.rule == "asia_en_has_names"


# --- refusals: the standard's rules, one by one -----------------------------
@frozen
@pytest.mark.parametrize(
    "name, rule",
    [
        # Rule 6 - the three catch-all series are buckets, not products.
        ("プロモーションカード", "not_a_catchall"),
        ("限定商品収録カード", "not_a_catchall"),
        ("ファミリーデッキセット", "not_a_catchall"),
        # Rule 2 - a coded product must use the strict standard.
        ("ブースターパック ROMANCE DAWN【OP-01】", "uncoded_only"),
        ("ブースターパック 頂上決戦【OP-02】", "uncoded_only"),
        # Rule 1 - no substring, no prefix, no similarity.
        ("プレミアムカードコレクション", "exact_name"),
        ("スタンダードバトルパック", "exact_name"),
        ("スタンダードバトルパック2022 Vol.9", "exact_name"),
        ("1st ANNIVERSARY", "exact_name"),
        ("2nd ANNIVERSARY SET ", "exact_name"),
        # A source's English rendering is not a catalogue name.
        ("Standard Battle Pack Vol.1", "exact_name"),
        ("Premium Card Collection -Best Selection vol.1-", "exact_name"),
    ],
)
def test_a_name_that_does_not_meet_the_standard_is_refused(name, rule):
    with pytest.raises(UncodedProductEvidenceError) as exc:
        prove_uncoded_product(name, jp_root=JP, asia_en_root=EN, snapshot_identity="test")
    assert exc.value.rule == rule


@pytest.mark.parametrize("name", ["", "   ", " 1st ANNIVERSARY SET", "1st ANNIVERSARY SET "])
def test_an_untrimmed_or_empty_name_is_refused_before_any_file_is_read(name, tmp_path):
    with pytest.raises(UncodedProductEvidenceError) as exc:
        prove_uncoded_product(name, jp_root=tmp_path, asia_en_root=tmp_path,
                              snapshot_identity="test", asia_en_absence_proof="n/a")
    assert exc.value.rule == "exact_name"


def _mini(tmp_path, entries, series=None):
    root = tmp_path / "jp"
    root.mkdir(exist_ok=True)
    series = series or [
        {"source_series_id": "550801", "display_name": "限定商品収録カード",
         "official_code": None, "source_url": "https://x.test/550801"},
        {"source_series_id": "550901", "display_name": "プロモーションカード",
         "official_code": None, "source_url": "https://x.test/550901"},
    ]
    (root / "series.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in series) + "\n", encoding="utf-8")
    (root / "entries.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in entries) + "\n", encoding="utf-8")
    (root / "assets.jsonl").write_text(
        "\n".join(json.dumps({"basename": f"{e['card_code']}.png", "sha256": "a" * 64},
                             ensure_ascii=False)
                  for e in entries if e.get("card_code")) + "\n", encoding="utf-8")
    return root


def test_a_product_spanning_two_series_is_refused(tmp_path):
    """Rule 3. A product must have one authority page to cite."""
    root = _mini(tmp_path, [
        {"entry_id": "A", "card_code": "OP01-001", "product_names": ["P"],
         "image_url": "https://x.test/OP01-001.png", "source_series_id": "550801"},
        {"entry_id": "B", "card_code": "OP01-002", "product_names": ["P"],
         "image_url": "https://x.test/OP01-002.png", "source_series_id": "550901"},
    ])
    with pytest.raises(UncodedProductEvidenceError) as exc:
        prove_uncoded_product("P", jp_root=root, asia_en_root=root,
                              snapshot_identity="t", asia_en_absence_proof="n/a")
    assert exc.value.rule == "one_series"


def test_one_entry_naming_two_products_disqualifies_the_whole_product(tmp_path):
    """Rule 4. A membership with a hole in it is not a membership - the
    ambiguous entry is never simply dropped."""
    root = _mini(tmp_path, [
        {"entry_id": "A", "card_code": "OP01-001", "product_names": ["P"],
         "image_url": "https://x.test/OP01-001.png", "source_series_id": "550801"},
        {"entry_id": "B", "card_code": "OP01-002", "product_names": ["P", "Q"],
         "image_url": "https://x.test/OP01-002.png", "source_series_id": "550801"},
    ])
    with pytest.raises(UncodedProductEvidenceError) as exc:
        prove_uncoded_product("P", jp_root=root, asia_en_root=root,
                              snapshot_identity="t", asia_en_absence_proof="n/a")
    assert exc.value.rule == "unambiguous_membership"


def test_a_member_with_no_fetched_asset_digest_is_refused(tmp_path):
    """Rule 5. A verified print needs artwork_key evidence; without a digest
    the product cannot produce one, so it is refused before anything exists."""
    root = _mini(tmp_path, [
        {"entry_id": "A", "card_code": "OP01-001", "product_names": ["P"],
         "image_url": "https://x.test/OP01-001.png", "source_series_id": "550801"},
    ])
    (root / "assets.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(UncodedProductEvidenceError) as exc:
        prove_uncoded_product("P", jp_root=root, asia_en_root=root,
                              snapshot_identity="t", asia_en_absence_proof="n/a")
    assert exc.value.rule == "internally_consistent"


def test_a_duplicated_card_code_under_one_product_is_refused(tmp_path):
    root = _mini(tmp_path, [
        {"entry_id": "A", "card_code": "OP01-001", "product_names": ["P"],
         "image_url": "https://x.test/OP01-001.png", "source_series_id": "550801"},
        {"entry_id": "B", "card_code": "OP01-001", "product_names": ["P"],
         "image_url": "https://x.test/OP01-001.png", "source_series_id": "550801"},
    ])
    with pytest.raises(UncodedProductEvidenceError) as exc:
        prove_uncoded_product("P", jp_root=root, asia_en_root=root,
                              snapshot_identity="t", asia_en_absence_proof="n/a")
    assert exc.value.rule == "internally_consistent"
