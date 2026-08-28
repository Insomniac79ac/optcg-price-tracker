"""The alias table's evidence standard, made executable.

A wrong product code does not make an approval uncertain - it makes it wrong
while looking corroborated (see the module docstring). So these tests are less
about the happy path than about the refusals: every way a "closest product"
matcher would have guessed, and this table must not.

Two layers:

  * The always-on tests pin the derived FACTS - which labels resolve, which
    must not - as literals, so they run in CI where the frozen catalogues are
    not checked out (`data/official_snapshots/` is gitignored, ~1GB).
  * `test_every_alias_is_backed_by_a_published_bandai_title` re-derives those
    facts from the catalogues when they ARE present, so an alias added on a
    hunch fails locally before it can reach a review.

Labels below are verbatim from SNKRDUNK discovery run 1 (2026-08-27).
"""

import json
import pathlib

import pytest

from worker.matching.release_product_aliases import (
    alias_evidence,
    known_aliases,
    normalise_label,
    resolve_product_code,
)

SNAPSHOTS = pathlib.Path(__file__).resolve().parents[3] / "data" / "official_snapshots"


# --- the accepted aliases ----------------------------------------------------


@pytest.mark.parametrize(
    "label, expected",
    [
        ("Booster Pack ROMANCE DAWN", "OP-01"),
        ("Extra Booster Memorial Collection", "EB-01"),
    ],
)
def test_an_accepted_alias_resolves_to_its_product(label, expected):
    assert resolve_product_code(label) == expected


def test_every_alias_carries_recorded_evidence():
    for label in known_aliases():
        assert alias_evidence(label), f"alias {label!r} has no recorded evidence"


# --- normalisation the module already permits --------------------------------
#
# SNKRDUNK writes the same product several ways. None of these variations is a
# difference in fact, and all of them appear in the run-1 corpus or differ from
# it only in the ways normalise_label explicitly folds.


@pytest.mark.parametrize(
    "label",
    [
        'Booster Pack "ROMANCE DAWN"',   # verbatim, candidate 10
        "BOOSTER PACK ROMANCE DAWN",
        "booster pack romance dawn",
        "  Booster Pack  ROMANCE DAWN  ",
        "Booster Pack -ROMANCE DAWN-",   # Bandai's own Asia-EN punctuation
    ],
)
def test_quoting_case_spacing_and_dashes_are_not_differences_in_fact(label):
    assert resolve_product_code(label) == "OP-01"


@pytest.mark.parametrize(
    "label",
    [
        "EXTRA BOOSTER -Memorial Collection-",  # Bandai's Asia-EN title
        "extra booster memorial collection",
        'Extra Booster "Memorial Collection"',
    ],
)
def test_the_eb01_alias_folds_the_same_way(label):
    assert resolve_product_code(label) == "EB-01"


# --- refusals ----------------------------------------------------------------


@pytest.mark.parametrize("label", [None, "", "   ", "!!!", "Totally Unknown Product"])
def test_absent_or_unknown_labels_resolve_to_none(label):
    assert resolve_product_code(label) is None


@pytest.mark.parametrize(
    "label",
    [
        "Booster Pack ROMANCE DAWN 2",
        "Booster Pack ROMANCE DAWNS",
        "Booster Packs ROMANCE DAWN",
        "Extra Booster Memorial Collections",
        "Extra Booster Memorial Collection vol.2",
        "Extra Booster Anime 25th collection",  # a real DIFFERENT product, EB-02
    ],
)
def test_a_near_match_refuses(label):
    """One character of difference is a different product until someone says
    otherwise. EB-02 is the sharpest case: it is real, it is adjacent, and a
    fuzzy matcher would reach EB-01 for it."""
    assert resolve_product_code(label) is None


@pytest.mark.parametrize(
    "label",
    [
        "ROMANCE DAWN",
        "Booster Pack",
        "Memorial Collection",
        "Extra Booster",
        "Collection",
        "Booster Pack ROMANCE DAWN [OP-01] limited edition box",
    ],
)
def test_a_substring_on_either_side_refuses(label):
    """Neither a fragment OF an alias nor a label CONTAINING one resolves.
    Matching is whole-label equality in both directions."""
    assert resolve_product_code(label) is None


@pytest.mark.parametrize(
    "label, spans",
    [
        ("ONE PIECE CARD THE BEST", "PRB-01 and PRB-02"),
        ("Premium Booster ONE PIECE CARD THE BEST", "PRB-01 and PRB-02"),
        ("ONE PIECE", "PRB-01, PRB-02, EB-03 and ST-05"),
        ("Extra Booster", "EB-01 through EB-04"),
        ("Starter Deck", "ST-01 through ST-36"),
        ("Premium Card Collection", "15 uncoded members of the line"),
    ],
)
def test_a_label_that_could_name_more_than_one_product_refuses(label, spans):
    """These are exactly the labels a containment or closest-name matcher gets
    wrong: each is a genuine Latin fragment of several published product
    titles, so picking one would be picking whichever came first."""
    assert resolve_product_code(label) is None, f"{label!r} spans {spans}"


@pytest.mark.parametrize(
    "label",
    [
        # Verbatim, candidates 5 and 9.
        "Weekly Shonen Jump 2024 Issue 3 All Applicants Service Recafig",
        "Weekly Shonen Jump 2023 6th and 7th issue All applicants service Recafig",
        "Weekly Shonen Jump All Applicants Service",
    ],
)
def test_an_applicant_service_label_stays_unresolved(label):
    """A mail-in premium is a distribution channel, not a product. Bandai files
    these under two different UNCODED buckets (限定商品収録カード 550801 and
    プロモーションカード 550901), so there is no ReleaseProduct to reach - however
    obvious the label's meaning is."""
    assert resolve_product_code(label) is None


@pytest.mark.parametrize(
    "label",
    [
        # Verbatim, candidates 2, 7, 12, 13, 19 and 25.
        "Premium Card Collection 25th Anniversary Edition",
        "Premium Card Collection -ONE PIECE FILM RED-",
    ],
)
def test_the_premium_card_collection_line_stays_unresolved(label):
    """Uncoded: プレミアムカードコレクション products live inside series 550801
    限定商品収録カード with product_code null, and Atlas holds no ReleaseProduct
    for them. Refused for want of a target, not for want of clarity."""
    assert resolve_product_code(label) is None


# --- the evidence itself, re-derived when the catalogues are present ---------


def _series(catalogue: str) -> list[dict]:
    path = SNAPSHOTS / catalogue / "current" / "series.jsonl"
    if not path.exists():
        pytest.skip(f"frozen catalogue not checked out: {path}")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _entry_card_codes(catalogue: str, series_id: str) -> set[str]:
    path = SNAPSHOTS / catalogue / "current" / "entries.jsonl"
    if not path.exists():
        pytest.skip(f"frozen catalogue not checked out: {path}")
    codes = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["source_series_id"] == series_id:
            codes.add(row["card_code"])
    return codes


def _published_titles() -> dict[str, set[str | None]]:
    """Normalised published title -> the official codes carrying it, across
    BOTH frozen catalogues. Titles are indexed with and without the bracketed
    code, since that is the form a storefront writes."""
    import re

    index: dict[str, set[str | None]] = {}
    for catalogue in ("bandai_jp", "bandai_asia_en"):
        for row in _series(catalogue):
            name = row["display_name"]
            for form in (name, re.sub(r"[\[【].*?[\]】]", "", name)):
                key = normalise_label(form)
                if key:
                    index.setdefault(key, set()).add(row["official_code"])
    return index


def test_every_alias_is_backed_by_a_published_bandai_title():
    """Check 1 and check 2 of the evidence standard, re-derived.

    Each alias key must equal a title Bandai publishes, and that title must
    name exactly one product code across both catalogues. An alias someone
    added from a plausible translation fails here.
    """
    index = _published_titles()
    for key, code in known_aliases().items():
        assert key in index, (
            f"alias {key!r} matches no published Bandai series title in either "
            "frozen catalogue - it is a guess, not evidence"
        )
        assert index[key] == {code}, (
            f"alias {key!r} is not one-to-one: published titles normalising to it "
            f"carry codes {sorted(map(str, index[key]))}, but the alias claims {code}"
        )


def test_eb01_is_the_same_product_in_both_catalogues():
    """Check 3. The EB-01 alias reads Bandai's Asia-EN Latin title but resolves
    against Atlas's JP prints, so the two catalogues' EB-01 must be shown to be
    the same product by CONTENTS. Codes are catalogue-scoped; membership is not.
    """
    jp = _entry_card_codes("bandai_jp", "550201")
    en = _entry_card_codes("bandai_asia_en", "556201")
    assert jp, "JP series 550201 is empty in the frozen catalogue"
    assert jp == en, (
        "JP EB-01 and Asia-EN EB-01 do not carry the same cards, so the code "
        f"alone does not establish they are one product (JP only: {sorted(jp - en)}, "
        f"EN only: {sorted(en - jp)})"
    )
    # The two cards discovery run 1 actually saw under this label.
    assert {"EB01-048", "EB01-055"} <= jp


def test_the_refused_labels_really_are_uncoded_in_the_catalogue():
    """The refusals are not squeamishness: Bandai publishes these names only as
    `product_names` inside series whose own official_code is null."""
    uncoded = {row["source_series_id"] for row in _series("bandai_jp") if not row["official_code"]}
    assert uncoded, "expected uncoded buckets in the JP catalogue"

    path = SNAPSHOTS / "bandai_jp" / "current" / "entries.jsonl"
    seen: dict[str, set[str]] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        for name in row.get("product_names") or []:
            seen.setdefault(name, set()).add(row["source_series_id"])

    for name in ("プレミアムカードコレクション 25周年エディション", "週刊少年ジャンプ応募者全員サービス"):
        assert name in seen, f"{name!r} is absent from the frozen JP catalogue"
        assert seen[name] <= uncoded, (
            f"{name!r} appears in a CODED series {sorted(seen[name] - uncoded)} - "
            "if Bandai has given it a product code, the refusal must be revisited"
        )
