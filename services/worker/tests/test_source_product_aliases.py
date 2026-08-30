"""The source-specific alias table's evidence standard, made executable.

Same shape as tests/test_release_product_aliases.py, and for the same reason: a
wrong product code does not make an approval uncertain, it makes it wrong while
looking corroborated. So most of what follows is refusals.

Two layers:

  * The always-on tests pin the derived FACTS as literals, so they run in CI
    where the frozen catalogues are not checked out (`data/official_snapshots/`
    is gitignored, ~1GB).
  * `test_every_source_alias_is_backed_by_its_products_contents` and
    `test_frozen_membership_matches_the_catalogues` re-derive those facts from
    the catalogues when they ARE present, so an alias added on a hunch - or a
    membership literal that has drifted from Bandai's own data - fails locally
    before it can reach a review.

Labels below are verbatim from SNKRDUNK discovery runs 1-9 (2026-08-27 to
2026-08-30, 793 candidates).
"""

import collections
import json
import pathlib

import pytest

from worker.matching.release_product_aliases import resolve_product_code
from worker.matching.source_product_aliases import (
    known_source_aliases,
    official_membership,
    resolve_source_product_code,
    source_alias_evidence,
)

SNAPSHOTS = pathlib.Path(__file__).resolve().parents[3] / "data" / "official_snapshots"

# label -> (product, a card code the product really contains)
ACCEPTED = [
    ("Booster Pack Final Battle", "OP-02", "OP02-001"),
    ("Booster Pack Formidable Enemy", "OP-03", "OP03-001"),
    ("Booster Pack The Kingdom Of Conspiracy", "OP-04", "OP04-001"),
]

# The nine foreign-prefix codes Bandai publishes INSIDE these products. Each is
# a reprint, and each must resolve - they are the cases a "prefix must match the
# product" shortcut would wrongly reject.
OFFICIAL_REPRINTS = [
    ("Booster Pack Formidable Enemy", "OP-03", "OP01-051"),
    ("Booster Pack Formidable Enemy", "OP-03", "ST01-012"),
    ("Booster Pack Formidable Enemy", "OP-03", "ST03-009"),
    ("Booster Pack Formidable Enemy", "OP-03", "ST04-003"),
    ("Booster Pack The Kingdom Of Conspiracy", "OP-04", "OP01-047"),
    ("Booster Pack The Kingdom Of Conspiracy", "OP-04", "OP01-078"),
    ("Booster Pack The Kingdom Of Conspiracy", "OP-04", "OP02-004"),
    ("Booster Pack The Kingdom Of Conspiracy", "OP-04", "OP02-085"),
    ("Booster Pack The Kingdom Of Conspiracy", "OP-04", "OP02-099"),
]


# --- the accepted aliases ----------------------------------------------------


@pytest.mark.parametrize("label, product, card_code", ACCEPTED)
def test_an_accepted_source_alias_resolves_to_its_product(label, product, card_code):
    assert resolve_source_product_code("snkrdunk", label, card_code) == product


@pytest.mark.parametrize("label, product, card_code", OFFICIAL_REPRINTS)
def test_an_official_reprint_inside_the_product_resolves(label, product, card_code):
    """The card code's own prefix names the set the card DEBUTED in, not the
    product this printing shipped in. These nine are published by Bandai inside
    the aliased product, so membership - not prefix - is what the guard tests."""
    assert resolve_source_product_code("snkrdunk", label, card_code) == product


def test_every_source_alias_carries_recorded_evidence():
    for label in known_source_aliases("snkrdunk"):
        assert source_alias_evidence("snkrdunk", label), f"{label!r} has no evidence"


def test_the_three_aliases_are_the_whole_table():
    """Pinned so a fourth row cannot be added without landing in this test and
    therefore in front of the evidence standard."""
    assert known_source_aliases("snkrdunk") == {
        "BOOSTERPACKFINALBATTLE": "OP-02",
        "BOOSTERPACKFORMIDABLEENEMY": "OP-03",
        "BOOSTERPACKTHEKINGDOMOFCONSPIRACY": "OP-04",
    }


# --- official resolution always wins -----------------------------------------


@pytest.mark.parametrize(
    "label, product",
    [("Booster Pack ROMANCE DAWN", "OP-01"), ("Extra Booster Memorial Collection", "EB-01")],
)
def test_an_official_alias_is_returned_unchanged(label, product):
    assert resolve_source_product_code("snkrdunk", label, "OP01-001") == product
    assert resolve_product_code(label) == product


def test_an_official_alias_is_not_subject_to_the_membership_guard():
    """The guard belongs to the source table only. An official title resolves on
    Bandai's own published name, and this module must not add a second, quieter
    condition to a decision the official standard already settled."""
    assert resolve_source_product_code("snkrdunk", "Booster Pack ROMANCE DAWN", "OP09-999") == "OP-01"


def test_no_source_alias_shadows_an_official_label():
    official = {"BOOSTERPACKROMANCEDAWN", "EXTRABOOSTERMEMORIALCOLLECTION"}
    assert official.isdisjoint(known_source_aliases("snkrdunk"))


# --- the membership guard fails CLOSED ---------------------------------------


@pytest.mark.parametrize(
    "label, card_code",
    [
        ("Booster Pack Final Battle", "OP09-001"),
        ("Booster Pack Final Battle", "OP03-001"),      # a real code, wrong product
        ("Booster Pack Formidable Enemy", "OP02-001"),  # ditto
        ("Booster Pack The Kingdom Of Conspiracy", "EB01-001"),
        ("Booster Pack Final Battle", "OP02-999"),      # in-range prefix, not published
    ],
)
def test_a_code_outside_the_products_membership_refuses(label, card_code):
    """The alias says what the label means; the guard says whether THIS listing
    is consistent with it. A code the product does not contain means the
    label's meaning has drifted, and the answer is no evidence - which lands on
    the same `source_product_unresolved` refusal the gate gives today."""
    assert resolve_source_product_code("snkrdunk", label, card_code) is None


@pytest.mark.parametrize("card_code", [None, "", "   "])
def test_a_missing_card_code_refuses(card_code):
    assert resolve_source_product_code("snkrdunk", "Booster Pack Final Battle", card_code) is None


def test_the_guard_is_case_and_whitespace_insensitive_only():
    assert resolve_source_product_code("snkrdunk", "Booster Pack Final Battle", " op02-001 ") == "OP-02"
    # Separator folding is NOT applied: collapsing punctuation in a membership
    # test would let two different codes compare equal, i.e. fail OPEN.
    assert resolve_source_product_code("snkrdunk", "Booster Pack Final Battle", "OP02001") is None


# --- source scoping ----------------------------------------------------------


@pytest.mark.parametrize("source", ["yuyutei", "SNKRDUNK", "", "unknown"])
def test_the_table_is_scoped_to_its_source(source):
    """These are SNKRDUNK's renderings. Another retailer using the same English
    words is not evidence about what THAT retailer means, and the source name is
    matched exactly - no case folding, so a typo'd source cannot borrow them."""
    assert resolve_source_product_code(source, "Booster Pack Final Battle", "OP02-001") is None


# --- refusals: no fuzzy, no substring, no translation at runtime --------------


@pytest.mark.parametrize("label", [None, "", "   ", "!!!", "Totally Unknown Product"])
def test_absent_or_unknown_labels_resolve_to_none(label):
    assert resolve_source_product_code("snkrdunk", label, "OP02-001") is None


@pytest.mark.parametrize(
    "label",
    [
        "Booster Pack Final Battles",
        "Booster Pack Final Battle 2",
        "Booster Pack Formidable Enemies",
        "Booster Packs Final Battle",
        "Booster Pack Formidable Enemy Vol.2",
    ],
)
def test_a_near_match_refuses(label):
    """One character of difference is a different product until someone says
    otherwise."""
    assert resolve_source_product_code("snkrdunk", label, "OP02-001") is None
    assert resolve_source_product_code("snkrdunk", label, "OP03-001") is None


@pytest.mark.parametrize(
    "label",
    [
        "Final Battle",
        "Formidable Enemy",
        "The Kingdom Of Conspiracy",
        "Booster Pack",
        "Booster Pack Final Battle [OP-02] sealed box",
        "Reprint of Booster Pack Final Battle",
    ],
)
def test_a_substring_on_either_side_refuses(label):
    """Neither a fragment OF an alias nor a label CONTAINING one resolves.
    Matching is whole-label equality in both directions."""
    assert resolve_source_product_code("snkrdunk", label, "OP02-001") is None


@pytest.mark.parametrize(
    "label, product",
    [
        # Bandai's OWN Asia-EN names for the same three products. They resolve
        # to nothing here because they are not what SNKRDUNK writes, and adding
        # them would belong in the official table on a title match, not here.
        ("Booster Pack Paramount War", "OP-02"),
        ("Booster Pack Pillars of Strength", "OP-03"),
        ("Booster Pack Kingdoms of Intrigue", "OP-04"),
        # The Japanese subtitles themselves. No translation happens at runtime.
        ("ブースターパック 頂上決戦", "OP-02"),
        ("頂上決戦", "OP-02"),
    ],
)
def test_no_translation_or_official_name_inference_happens_here(label, product):
    assert resolve_source_product_code("snkrdunk", label, "OP02-001") is None


@pytest.mark.parametrize(
    "label",
    [
        "Premium Card Collection 25th Anniversary Edition",
        "Standard Battle Pack Vol.3",
        'Booster Pack Vol.8 "Chaotic Dimensions"',
        "ONE PIECE FILM RED Finale Set",
        "Weekly Shonen Jump 2024 Issue 3 All Applicants Service Recafig",
    ],
)
def test_other_unresolved_labels_stay_unresolved(label):
    """Verbatim labels from the corpus that this tranche did NOT investigate.
    Adding three rows must not quietly resolve a fourth."""
    assert resolve_source_product_code("snkrdunk", label, "OP02-001") is None


# --- the frozen membership, pinned -------------------------------------------


@pytest.mark.parametrize(
    "product, size", [("OP-02", 121), ("OP-03", 127), ("OP-04", 124)]
)
def test_frozen_membership_sizes_are_pinned(product, size):
    assert len(official_membership(product)) == size


def test_membership_is_unknown_for_products_not_in_the_table():
    assert official_membership("OP-01") == frozenset()
    assert official_membership("nonsense") == frozenset()


# --- the evidence itself, re-derived when the catalogues are present ---------


def _entries(catalogue: str) -> list[dict]:
    path = SNAPSHOTS / catalogue / "current" / "entries.jsonl"
    if not path.exists():
        pytest.skip(f"frozen catalogue not checked out: {path}")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _membership(catalogue: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = collections.defaultdict(set)
    for row in _entries(catalogue):
        if row.get("product_code"):
            out[row["product_code"]].add(row["card_code"])
    return out


@pytest.mark.parametrize("product", ["OP-02", "OP-03", "OP-04"])
def test_frozen_membership_matches_the_catalogues(product):
    """The literal in the module is Bandai's data, not a transcription of it.

    Checked against BOTH catalogues, because check 4 of the evidence standard
    requires them to agree - a membership that depended on which catalogue was
    read would not be a fact about the product.
    """
    jp, en = _membership("bandai_jp"), _membership("bandai_asia_en")
    assert jp[product] == en[product], f"{product}: JP and Asia-EN disagree on contents"
    assert official_membership(product) == frozenset(jp[product])


@pytest.mark.parametrize("label, product, _code", ACCEPTED)
def test_every_source_alias_is_backed_by_its_products_contents(label, product, _code):
    """Check 3: the product this label names must be the ONLY Bandai product
    whose membership could contain the label's observed code set.

    The observed set is the module's own frozen membership, which the test
    above has already tied to the catalogues - so this asks the question that
    actually matters: is there a second product that would also have fitted?
    """
    jp = _membership("bandai_jp")
    observed = official_membership(product)
    containing = sorted(p for p, codes in jp.items() if observed <= codes)
    assert containing == [product], (
        f"{label!r} -> {product}: observed set is also contained by {containing}"
    )


def test_no_source_alias_could_have_been_an_official_one():
    """Check 1, re-derived: if a label DID equal a published Bandai title, it
    belongs in release_product_aliases under the official standard, not here."""
    for catalogue in ("bandai_jp", "bandai_asia_en"):
        path = SNAPSHOTS / catalogue / "current" / "series.jsonl"
        if not path.exists():
            pytest.skip(f"frozen catalogue not checked out: {path}")
    for label, _product, code in ACCEPTED:
        assert resolve_product_code(label) is None, (
            f"{label!r} resolves officially; it must not be a source alias"
        )
