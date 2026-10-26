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
    asia_en_agreement,
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
    ev = prove_uncoded_product(name, jp_root=JP, asia_en_root=EN, snapshot_identity="test",
                               asia_en_absence_proof="2026-08-22 JP-only measurement")
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
    ev = prove_uncoded_product(name, jp_root=JP, asia_en_root=EN, snapshot_identity="test",
                               asia_en_absence_proof="2026-08-22 JP-only measurement")
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
    ev = prove_uncoded_product(name, jp_root=JP, asia_en_root=EN, snapshot_identity="test",
                               asia_en_absence_proof="2026-08-22 JP-only measurement")
    assert ev.jp_only_validation is True
    assert ev.as_provenance()["jp_only_validation"] is True


@frozen
def test_the_2026_08_asia_en_snapshot_is_incomplete_evidence():
    """It was parsed with the JP label only, so its uncoded entries carry no
    product names: step C refuses it rather than reading every product absent."""
    with pytest.raises(UncodedProductEvidenceError) as exc:
        asia_en_agreement(["OP01-001"], EN)
    assert exc.value.rule == "asia_en_incomplete"


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


# --- proposed rule 6 exception: a single-product catch-all series ----------

_FAMILY_SERIES = [
    {"source_series_id": "550701", "display_name": "ファミリーデッキセット",
     "official_code": None, "source_url": "https://x.test/550701"},
    {"source_series_id": "550901", "display_name": "プロモーションカード",
     "official_code": None, "source_url": "https://x.test/550901"},
]


def _family(tmp_path, second_names=("ファミリーデッキセット",)):
    return _mini(tmp_path, [
        {"entry_id": "A", "card_code": "FD01-001", "product_names": ["ファミリーデッキセット"],
         "image_url": "https://x.test/FD01-001.png", "source_series_id": "550701"},
        {"entry_id": "B", "card_code": "FD01-002", "product_names": list(second_names),
         "image_url": "https://x.test/FD01-002.png", "source_series_id": "550701"},
    ], series=_FAMILY_SERIES)


def test_rule_6_still_refuses_a_catchall_name_by_default(tmp_path):
    root = _family(tmp_path)
    with pytest.raises(UncodedProductEvidenceError) as exc:
        prove_uncoded_product("ファミリーデッキセット", jp_root=root, asia_en_root=root,
                              snapshot_identity="t", asia_en_absence_proof="n/a")
    assert exc.value.rule == "not_a_catchall"


def test_a_single_product_catchall_passes_only_when_allowed_and_is_recorded(tmp_path):
    root = _family(tmp_path)
    ev = prove_uncoded_product("ファミリーデッキセット", jp_root=root, asia_en_root=root,
                               snapshot_identity="t", asia_en_absence_proof="n/a",
                               allow_single_product_catchall=True)
    assert ev.single_product_catchall is True
    assert ev.member_card_codes == ("FD01-001", "FD01-002")
    assert ev.as_provenance()["single_product_catchall"] is True


def test_a_catchall_holding_another_product_stays_a_bucket(tmp_path):
    root = _family(tmp_path, second_names=("Other Product",))
    with pytest.raises(UncodedProductEvidenceError) as exc:
        prove_uncoded_product("ファミリーデッキセット", jp_root=root, asia_en_root=root,
                              snapshot_identity="t", asia_en_absence_proof="n/a",
                              allow_single_product_catchall=True)
    assert exc.value.rule == "not_a_catchall"


def test_the_promotion_bucket_is_never_a_single_product(tmp_path):
    root = _mini(tmp_path, [
        {"entry_id": "A", "card_code": "P-001", "product_names": ["Promo Pack"],
         "image_url": "https://x.test/P-001.png", "source_series_id": "550901"},
    ])
    with pytest.raises(UncodedProductEvidenceError) as exc:
        prove_uncoded_product("プロモーションカード", jp_root=root, asia_en_root=root,
                              snapshot_identity="t", asia_en_absence_proof="n/a",
                              allow_single_product_catchall=True)
    assert exc.value.rule == "not_a_catchall"


# --- step C amendment B: repeated codes ------------------------------------


def test_a_repeated_code_with_its_own_entry_and_image_is_a_second_printing(tmp_path):
    """A base and a holo reprint can show the same picture (owner 2026-10-26):
    Bandai lists them as two entries at two image addresses."""
    root = _mini(tmp_path, [
        {"entry_id": "P-106", "card_code": "P-106", "product_names": ["P"],
         "image_url": "https://x.test/P-106.png", "source_series_id": "550901"},
        {"entry_id": "P-106_p1", "card_code": "P-106", "product_names": ["P"],
         "image_url": "https://x.test/P-106_p1.png", "source_series_id": "550901"},
    ])
    (root / "assets.jsonl").write_text(
        "\n".join(json.dumps({"basename": b, "sha256": "a" * 64}) for b in ("P-106.png", "P-106_p1.png")) + "\n")
    ev = prove_uncoded_product("P", jp_root=root, asia_en_root=root,
                               snapshot_identity="t", asia_en_absence_proof="n/a")
    assert ev.member_card_codes == ("P-106",)
    assert ev.member_entry_ids == ("P-106", "P-106_p1")
    assert ev.repeated_card_codes == ("P-106",)


# --- step C amendment C: Asia-EN agreement per product ----------------------


def _asia(tmp_path, products):
    root = tmp_path / "asia"
    root.mkdir(exist_ok=True)
    (root / "series.jsonl").write_text(json.dumps(
        {"source_series_id": "556901", "display_name": "Promotion card", "official_code": None}) + "\n")
    rows = [{"source_series_id": "556901", "entry_id": f"{code}-{name}", "card_code": code, "product_names": [name]}
            for name, codes in products.items() for code in codes]
    (root / "entries.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return root


def test_asia_en_agreement_equal_set_agrees(tmp_path):
    root = _asia(tmp_path, {"Promotion Pack Vol.1": ["P-001", "P-002"]})
    status, name, proof = asia_en_agreement(["P-002", "P-001"], root)
    assert (status, name) == ("agrees", "Promotion Pack Vol.1")
    assert "same 2 card code" in proof


def test_asia_en_agreement_no_shared_code_is_japan_only(tmp_path):
    root = _asia(tmp_path, {"Promotion Pack Vol.1": ["P-001"]})
    status, name, proof = asia_en_agreement(["P-099"], root)
    assert (status, name) == ("absent", None)
    assert "Japan-only" in proof


def test_asia_en_agreement_partial_overlap_is_refused_for_review(tmp_path):
    root = _asia(tmp_path, {"Promotion Pack Vol.1": ["P-001", "P-002", "P-003"]})
    with pytest.raises(UncodedProductEvidenceError) as exc:
        asia_en_agreement(["P-001", "P-002"], root)
    assert exc.value.rule == "asia_en_disagrees"
    assert "Promotion Pack Vol.1" in exc.value.detail


def test_prove_records_agreement_when_no_proof_is_supplied(tmp_path):
    root = _mini(tmp_path, [
        {"entry_id": "A", "card_code": "P-001", "product_names": ["P"],
         "image_url": "https://x.test/P-001.png", "source_series_id": "550901"},
    ])
    asia = _asia(tmp_path, {"Promotion Pack EN": ["P-001"]})
    ev = prove_uncoded_product("P", jp_root=root, asia_en_root=asia, snapshot_identity="t")
    assert ev.jp_only_validation is False
    assert ev.asia_en_product == "Promotion Pack EN"


def test_asia_en_evidence_without_product_names_is_refused(tmp_path):
    root = _asia(tmp_path, {"Promotion Pack Vol.1": ["P-001"]})
    (root / "entries.jsonl").write_text(json.dumps(
        {"source_series_id": "556901", "entry_id": "x", "card_code": "P-001", "product_names": []}) + "\n")
    with pytest.raises(UncodedProductEvidenceError) as exc:
        asia_en_agreement(["P-099"], root)
    assert exc.value.rule == "asia_en_incomplete"


def test_empty_asia_en_evidence_is_refused(tmp_path):
    root = _asia(tmp_path, {})
    (root / "entries.jsonl").write_text("")
    with pytest.raises(UncodedProductEvidenceError) as exc:
        asia_en_agreement(["P-099"], root)
    assert exc.value.rule == "asia_en_incomplete"


def test_a_repeated_code_whose_addresses_collapse_to_one_variant_is_refused(tmp_path):
    root = _mini(tmp_path, [
        {"entry_id": "A", "card_code": "P-106", "product_names": ["P"],
         "image_url": "https://x.test/P-106.png", "source_series_id": "550901"},
        {"entry_id": "B", "card_code": "P-106", "product_names": ["P"],
         "image_url": "https://x.test/p-106.png", "source_series_id": "550901"},
    ])
    (root / "assets.jsonl").write_text(
        "\n".join(json.dumps({"basename": b, "sha256": "a" * 64}) for b in ("P-106.png", "p-106.png")) + "\n")
    with pytest.raises(UncodedProductEvidenceError) as exc:
        prove_uncoded_product("P", jp_root=root, asia_en_root=root,
                              snapshot_identity="t", asia_en_absence_proof="n/a")
    assert exc.value.rule == "internally_consistent"


# --- owner-cleared partial overlaps -------------------------------------------


def _cleared_case(tmp_path, asia_name):
    from app.services.uncoded_product_evidence import ASIA_EN_OWNER_CLEARED

    name = next(iter(ASIA_EN_OWNER_CLEARED))
    root = _mini(tmp_path, [
        {"entry_id": "A", "card_code": "OP03-001", "product_names": [name],
         "image_url": "https://x.test/OP03-001.png", "source_series_id": "550901"},
        {"entry_id": "B", "card_code": "OP03-002", "product_names": [name],
         "image_url": "https://x.test/OP03-002.png", "source_series_id": "550901"},
    ])
    asia = _asia(tmp_path, {asia_name: ["OP03-001"]})
    return name, root, asia


def test_an_owner_cleared_overlap_imports_as_japan_only(tmp_path):
    from app.services.uncoded_product_evidence import ASIA_EN_OWNER_CLEARED

    name = next(iter(ASIA_EN_OWNER_CLEARED))
    name, root, asia = _cleared_case(tmp_path, ASIA_EN_OWNER_CLEARED[name][0])
    ev = prove_uncoded_product(name, jp_root=root, asia_en_root=asia, snapshot_identity="t")
    assert ev.jp_only_validation is True
    assert ev.asia_en_product is None
    assert ev.asia_en_absence_proof.startswith("cleared as Japan-only (owner 2026-10-26")


def test_a_clearance_does_not_cover_an_overlap_with_another_asia_product(tmp_path):
    name, root, asia = _cleared_case(tmp_path, "Some other Asia prize")
    with pytest.raises(UncodedProductEvidenceError) as exc:
        prove_uncoded_product(name, jp_root=root, asia_en_root=asia, snapshot_identity="t")
    assert exc.value.rule == "asia_en_disagrees"
