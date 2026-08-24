"""The apply engine's rules, exercised without a database where possible.

The engine's job is to REFUSE, so most of what is asserted here is a refusal:
which plans are ineligible and why, which canonical cards cannot establish a
baseline rarity, and which metadata may be filled in. The transactional
behaviour and every rollback path live in
test_canonical_import_apply_postgres, because "the whole run rolled back" is
only meaningful against a real transaction.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app import apply_canonical_print_import as apply_cli
from app.services import canonical_import_apply as A
from app.services import print_import_planner as P
from app.services.official_cardlist import OfficialCardEntry, RawField
from app.services.print_import_planner import (
    OfficialMetadata,
    PlannedPrint,
    ProposedCanonicalCard,
    ProposedReleaseProduct,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CARD_LIST = "https://www.onepiece-cardgame.com/images/cardlist/card"


def _metadata(**overrides) -> OfficialMetadata:
    values = {
        "official_rarity": "SR",
        "official_block_icon": "01",
        "official_name": "モンキー・D・ルフィ",
        "official_effect_text": "【起動メイン】…",
    }
    values.update(overrides)
    return OfficialMetadata(**values)


def _planned(**overrides) -> PlannedPrint:
    """A plan that is eligible in every respect, so a test can spoil exactly one."""
    values = dict(
        source_catalogue="bandai_jp",
        source_series_id="550101",
        source_url="https://www.onepiece-cardgame.com/cardlist/?series=550101",
        entry_id="OP01-001",
        official_product_code="OP-01",
        official_product_display_name="ROMANCE DAWN【OP-01】",
        card_code="OP01-001",
        official_card_name="モンキー・D・ルフィ",
        language="jp",
        official_image_url=f"{CARD_LIST}/OP01-001.png?260101",
        official_asset_variant="base",
        official_artwork_sha256="a" * 64,
        official_metadata=_metadata(),
        treatment=None,
        existing_canonical_card_id=None,
        existing_release_product_id=None,
        existing_card_print_id=None,
        outcome=P.OUTCOME_CREATE,
        creations=(P.CREATE_CANONICAL_CARD, P.CREATE_CARD_PRINT),
        verification_status=P.VERIFIED,
        flags=(),
        reasons=(),
        proposed_canonical_card=ProposedCanonicalCard(
            card_code="OP01-001",
            name_jp="モンキー・D・ルフィ",
            original_set_code="OP-01",
            rarity="L",
            card_type="Leader",
        ),
        proposed_release_product=ProposedReleaseProduct(
            source_catalogue="bandai_jp",
            official_code="OP-01",
            display_name="ROMANCE DAWN【OP-01】",
            first_seen_name="ROMANCE DAWN【OP-01】",
            source_series_id="550101",
            source_url="https://www.onepiece-cardgame.com/cardlist/?series=550101",
        ),
    )
    values.update(overrides)
    return PlannedPrint(**values)


# --- §2 eligibility -------------------------------------------------------


def test_a_fully_evidenced_create_plan_is_eligible():
    decision = A.evaluate_eligibility(_planned(), composable_card_codes={"OP01-001"})

    assert decision.eligible
    assert decision.reasons == ()


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"outcome": P.OUTCOME_NEEDS_REVIEW}, A.SKIP_NOT_CREATE),
        ({"outcome": P.OUTCOME_CONFLICT}, A.SKIP_NOT_CREATE),
        ({"outcome": P.OUTCOME_NO_CHANGE}, A.SKIP_NOT_CREATE),
        ({"verification_status": P.NEEDS_REVIEW}, A.SKIP_NOT_VERIFIED),
        ({"source_catalogue": "bandai_en"}, A.SKIP_WRONG_CATALOGUE),
        ({"official_asset_variant": None}, A.SKIP_NO_VARIANT),
        ({"official_image_url": None}, A.SKIP_NO_IMAGE),
        ({"official_artwork_sha256": None}, A.SKIP_NO_DIGEST),
        ({"card_code": "  "}, A.SKIP_NO_CARD_CODE),
    ],
)
def test_one_missing_thing_is_enough_to_refuse(overrides, reason):
    decision = A.evaluate_eligibility(_planned(**overrides), composable_card_codes={"OP01-001"})

    assert not decision.eligible
    assert reason in decision.reasons


@pytest.mark.parametrize("field", P.METADATA_FIELDS)
def test_every_one_of_the_four_metadata_values_is_required(field):
    planned = _planned(official_metadata=_metadata(**{field: None}))

    decision = A.evaluate_eligibility(planned, composable_card_codes={"OP01-001"})

    assert not decision.eligible
    assert A.SKIP_INCOMPLETE_METADATA in decision.reasons


def test_an_uncoded_product_with_nothing_established_is_refused():
    """The planner already blocks these; asserted rather than assumed, because
    the apply engine must not depend on that being true forever."""
    planned = _planned(official_product_code=None, existing_release_product_id=None)

    decision = A.evaluate_eligibility(planned, composable_card_codes={"OP01-001"})

    assert not decision.eligible
    assert A.SKIP_UNCODED_PRODUCT in decision.reasons


def test_an_uncoded_product_already_resolved_to_a_product_is_not_refused_for_that():
    planned = _planned(official_product_code=None, existing_release_product_id=7)

    decision = A.evaluate_eligibility(planned, composable_card_codes={"OP01-001"})

    assert A.SKIP_UNCODED_PRODUCT not in decision.reasons


def test_an_unestablished_rarity_no_longer_refuses_anything():
    """The rule this tranche removed. Since migration c7e91a4d2b60 the column
    is optional, so a card the catalogue gives no card-level rarity for is
    written with NULL - it is not a reason to leave 122 exact prints
    unimported."""
    baseline = A.CanonicalBaseline(
        card_code="EB03-003",
        status=A.BASELINE_MULTIPLE,
        expected_set_code="EB-03",
        candidates=("SPカード", "SR"),
        rarity=None,
        card_type="Character",
        name_jp="ウタ",
    )
    assert baseline.composable
    assert not baseline.rarity_established

    decision = A.evaluate_eligibility(
        _planned(card_code="EB03-003"),
        composable_card_codes={"EB03-003"},
        baselines={"EB03-003": baseline},
    )

    assert decision.eligible
    assert not hasattr(A, "SKIP_NO_BASELINE_RARITY")


# --- §4/§6 a promo: no original set, established by consensus ---------------


def _promo(entry_id, *, name="コビー", card_type="Character", rarity="P",
           product="PRB-01", coded=True):
    return _planned(
        entry_id=entry_id,
        card_code="P-014",
        official_product_code=product if coded else None,
        official_product_display_name=product,
        official_card_name=name,
        official_metadata=_metadata(official_name=name, official_rarity=rarity),
        proposed_canonical_card=ProposedCanonicalCard(
            card_code="P-014",
            name_jp=name,
            # The planner reads this out of the card code, and a promo's code
            # carries no set number.
            original_set_code=None,
            rarity=rarity,
            card_type=card_type,
        ),
    )


def test_a_promo_is_composable_with_no_original_set_at_all():
    """A promo has no set, so `expected_set_code` is absent BECAUSE there is
    none - not because one could not be read. That distinction is what makes
    it composable while a malformed code is not."""
    baseline = A.resolve_canonical_baseline("P-014", [_promo("P-014_p1"), _promo("P-014_p2")])

    assert baseline.is_promo is True
    assert baseline.expected_set_code is None
    assert baseline.composable is True
    assert (baseline.name_jp, baseline.card_type, baseline.rarity) == (
        "コビー", "Character", "P",
    )


def test_a_promos_canonical_row_never_takes_a_distribution_products_code():
    """P-014 is distributed in PRB-01. That is where a printing appeared, not
    the card's set, and it must never reach original_set_code."""
    baseline = A.resolve_canonical_baseline(
        "P-014", [_promo("P-014_p1", product="PRB-01"), _promo("P-014_r1", product="ST-16")]
    )

    assert baseline.expected_set_code is None
    for invented in ("PRB-01", "ST-16", "P", "PROMO", "PR"):
        assert baseline.expected_set_code != invented


def test_a_promo_reads_nothing_from_an_uncoded_occurrence():
    """§4: the 45 uncoded promo occurrences stay needs_review and establish
    nothing. Here the uncoded one publishes a different name; it is not
    consulted, so consensus is still reached."""
    baseline = A.resolve_canonical_baseline(
        "P-014",
        [
            _promo("P-014_p1", name="コビー"),
            _promo("P-014_p2", name="コビー"),
            _promo("P-014", name="別の名前", coded=False),
        ],
    )

    assert baseline.composable is True
    assert baseline.name_jp == "コビー"


def test_a_promo_with_only_uncoded_occurrences_is_not_composable():
    baseline = A.resolve_canonical_baseline(
        "P-014", [_promo("P-014", coded=False), _promo("P-014_p1", coded=False)]
    )

    assert baseline.composable is False
    assert baseline.name_jp is None


def test_a_promos_disagreeing_rarity_is_null_not_a_refusal():
    """P-084 is 'SPカード' in OP-17 and 'P' in ST-25. Neither is the card's
    rarity, so the answer is NULL - and the card is still created."""
    baseline = A.resolve_canonical_baseline(
        "P-014",
        [_promo("P-014_p1", rarity="SPカード"), _promo("P-014_r1", rarity="P")],
    )

    assert baseline.status == A.BASELINE_MULTIPLE
    assert baseline.rarity is None
    assert baseline.rarity_established is False
    assert baseline.composable is True
    assert set(baseline.candidates) == {"SPカード", "P"}


def test_a_promos_disagreeing_name_fails_closed_rather_than_picking():
    """§6: a field requiring consensus that materially disagrees is left
    unset, never resolved by choosing an occurrence."""
    baseline = A.resolve_canonical_baseline(
        "P-014", [_promo("P-014_p1", name="コビー"), _promo("P-014_p2", name="別の名前")]
    )

    assert baseline.name_jp is None
    assert baseline.composable is False
    assert any("name_jp has no consensus" in d for d in baseline.disagreements)


def test_a_promos_formatting_only_name_split_also_fails_closed():
    """Two renderings of the same name are the same name - but picking one
    would be picking an occurrence, and storing the NFKC-folded form would
    store a rendering Bandai never published. Neither is evidence."""
    baseline = A.resolve_canonical_baseline(
        "P-014",
        [_promo("P-014_p1", name="モンキー・D・ルフィ"),
         _promo("P-014_p2", name="モンキー・Ｄ・ルフィ")],
    )

    assert baseline.name_jp is None
    assert any("formatting_tie" in d for d in baseline.disagreements)


def test_a_promos_disagreeing_card_type_fails_closed():
    baseline = A.resolve_canonical_baseline(
        "P-014", [_promo("P-014_p1"), _promo("P-014_p2", card_type="Event")]
    )

    assert baseline.card_type is None
    assert baseline.composable is False


def test_promo_consensus_does_not_depend_on_order():
    forward = A.resolve_canonical_baseline(
        "P-014", [_promo("P-014_p1", rarity="P"), _promo("P-014_r1", rarity="SPカード")]
    )
    backward = A.resolve_canonical_baseline(
        "P-014", [_promo("P-014_r1", rarity="SPカード"), _promo("P-014_p1", rarity="P")]
    )

    assert (forward.name_jp, forward.rarity, forward.status) == (
        backward.name_jp, backward.rarity, backward.status,
    )


def test_a_promo_print_is_eligible_once_its_card_is_composable():
    decision = A.evaluate_eligibility(
        _promo("P-014_p1"),
        composable_card_codes={"P-014"},
        baselines={"P-014": A.resolve_canonical_baseline("P-014", [_promo("P-014_p1")])},
    )

    assert decision.eligible
    assert A.SKIP_NO_ORIGINAL_SET_CODE not in decision.reasons


def test_a_malformed_card_code_is_still_refused():
    """A code with no readable set code that is ALSO not a promo shape. Absent
    because it could not be read, not because there is none - so nothing is
    composed from it, and it is not quietly routed into the promo path."""
    baseline = A.CanonicalBaseline(
        card_code="NOTACODE", status=A.BASELINE_NONE, expected_set_code=None,
        candidates=(), is_promo=False,
    )

    decision = A.evaluate_eligibility(
        _planned(card_code="NOTACODE"),
        composable_card_codes=set(),
        baselines={"NOTACODE": baseline},
    )

    assert not decision.eligible
    assert decision.reasons == (A.SKIP_NO_ORIGINAL_SET_CODE,)


def test_the_promo_path_is_not_reachable_from_a_malformed_code():
    baseline = A.resolve_canonical_baseline("NOTACODE", [_planned(card_code="NOTACODE")])

    assert baseline.is_promo is False
    assert baseline.composable is False


def test_a_set_code_with_no_own_set_occurrence_is_refused_for_its_own_reason():
    """The name and card type are read off the card's own-set printing. With
    no such occurrence there is no baseline to read them from, and copying
    them off an arbitrary reprint is the order-dependence this module
    refuses."""
    baseline = A.CanonicalBaseline(
        card_code="OP05-100", status=A.BASELINE_NONE, expected_set_code="OP-05",
        candidates=(), name_jp=None, card_type=None,
    )

    decision = A.evaluate_eligibility(
        _planned(card_code="OP05-100"),
        composable_card_codes=set(),
        baselines={"OP05-100": baseline},
    )

    assert decision.reasons == (A.SKIP_NO_BASELINE_OCCURRENCE,)


def test_a_print_on_an_existing_canonical_card_needs_no_baseline():
    """The composability question only arises when a row is being created."""
    planned = _planned(existing_canonical_card_id=42)

    decision = A.evaluate_eligibility(planned, composable_card_codes=set())

    assert decision.eligible


def test_the_engine_never_promotes_a_planner_decision():
    """No combination of complete evidence makes a needs_review plan eligible."""
    planned = _planned(outcome=P.OUTCOME_NEEDS_REVIEW, verification_status=P.NEEDS_REVIEW)

    decision = A.evaluate_eligibility(planned, composable_card_codes={"OP01-001"})

    assert not decision.eligible


# --- §3 canonical baseline ------------------------------------------------


def test_the_baseline_is_the_occurrence_from_the_cards_own_set():
    own_set = _planned(official_product_code="OP-01", entry_id="OP01-001")
    reprint = _planned(
        official_product_code="PRB-01",
        entry_id="OP01-001_r1",
        proposed_canonical_card=ProposedCanonicalCard(
            card_code="OP01-001",
            name_jp="モンキー・D・ルフィ",
            original_set_code="OP-01",
            rarity="SEC",
            card_type="Leader",
        ),
    )

    baseline = A.resolve_canonical_baseline("OP01-001", [reprint, own_set])

    assert baseline.status == A.BASELINE_UNIQUE
    assert baseline.rarity == "L"
    assert baseline.entry_id == "OP01-001"


def test_baseline_selection_does_not_depend_on_order():
    own_set = _planned(official_product_code="OP-01")
    reprint = _planned(
        official_product_code="PRB-01",
        proposed_canonical_card=ProposedCanonicalCard(
            "OP01-001", "モンキー・D・ルフィ", "OP-01", "SEC", "Leader"
        ),
    )

    forward = A.resolve_canonical_baseline("OP01-001", [own_set, reprint])
    backward = A.resolve_canonical_baseline("OP01-001", [reprint, own_set])

    assert forward.rarity == backward.rarity == "L"


def test_no_occurrence_from_the_cards_own_set_is_not_guessed_at():
    reprint = _planned(
        official_product_code="PRB-01",
        proposed_canonical_card=ProposedCanonicalCard(
            "OP01-001", "モンキー・D・ルフィ", "OP-01", "SEC", "Leader"
        ),
    )

    baseline = A.resolve_canonical_baseline("OP01-001", [reprint])

    assert baseline.status == A.BASELINE_NONE
    assert baseline.rarity is None
    assert not baseline.rarity_established
    # Nor is there a name or a card type to read from a baseline that does not
    # exist, so the row cannot be composed either - for that reason, not rarity.
    assert not baseline.composable


def test_two_disagreeing_rarities_write_null_rather_than_pick_one():
    """EB03-003 is published both as 'SR' and as 'SPカード' inside EB-03
    itself. Neither is the card's rarity, so the answer is NULL - never the
    first occurrence, the most common, or the highest."""
    a = _planned(official_product_code="EB-03", entry_id="EB03-003")
    b = _planned(
        official_product_code="EB-03",
        entry_id="EB03-003_p1",
        proposed_canonical_card=ProposedCanonicalCard(
            "EB03-003", "モンキー・D・ルフィ", "EB-03", "SPカード", "Leader"
        ),
    )

    baseline = A.resolve_canonical_baseline("EB03-003", [a, b])

    assert baseline.status == A.BASELINE_MULTIPLE
    assert baseline.rarity is None
    assert not baseline.rarity_established
    # Both published values are reported, so nothing is lost by not picking.
    assert set(baseline.candidates) == {"L", "SPカード"}
    # The card is still created: name, type and set code are all unambiguous.
    assert baseline.composable
    assert (baseline.name_jp, baseline.card_type, baseline.expected_set_code) == (
        "モンキー・D・ルフィ", "Leader", "EB-03",
    )


def test_disagreeing_own_set_names_do_block_composition():
    """A rarity that varies is ordinary. A NAME that varies between two
    occurrences of the card's own set is not - there is no baseline spelling
    to record, and picking one would depend on iteration order."""
    a = _planned(official_product_code="EB-03", entry_id="EB03-003")
    b = _planned(
        official_product_code="EB-03",
        entry_id="EB03-003_p1",
        proposed_canonical_card=ProposedCanonicalCard(
            "EB03-003", "別の名前", "EB-03", "L", "Leader"
        ),
    )

    baseline = A.resolve_canonical_baseline("EB03-003", [a, b])

    assert baseline.disagreements
    assert not baseline.composable


def test_several_baseline_occurrences_that_agree_are_one_answer():
    a = _planned(official_product_code="OP-01", entry_id="OP01-001")
    b = _planned(official_product_code="OP-01", entry_id="OP01-001_p1")

    baseline = A.resolve_canonical_baseline("OP01-001", [a, b])

    assert baseline.status == A.BASELINE_UNIQUE
    assert baseline.rarity == "L"


def test_a_promo_code_with_no_set_code_has_no_baseline():
    """`P-014` carries no set code, so the rule has nothing to match on."""
    promo = _planned(
        card_code="P-014",
        official_product_code=None,
        proposed_canonical_card=ProposedCanonicalCard(
            "P-014", "名前", None, "P", "Character"
        ),
    )

    baseline = A.resolve_canonical_baseline("P-014", [promo])

    assert baseline.status == A.BASELINE_NONE
    assert baseline.expected_set_code is None
    # And that, not the missing rarity, is what keeps it out of the import.
    assert not baseline.composable


def test_a_card_type_that_differs_between_occurrences_blocks_the_baseline():
    own_set = _planned(official_product_code="OP-01")
    other = _planned(
        official_product_code="OP-05",
        proposed_canonical_card=ProposedCanonicalCard(
            "OP01-001", "モンキー・D・ルフィ", "OP-01", "L", "Character"
        ),
    )

    baseline = A.resolve_canonical_baseline("OP01-001", [own_set, other])

    assert baseline.disagreements
    assert not baseline.composable


def test_the_audit_only_examines_cards_the_safe_set_would_create():
    creating = _planned(card_code="OP01-001")
    existing = _planned(
        card_code="OP02-013", existing_canonical_card_id=5, proposed_canonical_card=None
    )

    audit = A.audit_canonical_baselines([creating, existing])

    assert set(audit.baselines) == {"OP01-001"}


def test_the_audit_reads_occurrences_the_planner_did_not_mark_create():
    """A card's own-set printing may itself be needs_review; it is still the
    evidence that settles the card's rarity."""
    own_set_needs_review = _planned(
        official_product_code="OP-01",
        outcome=P.OUTCOME_NEEDS_REVIEW,
        verification_status=P.NEEDS_REVIEW,
    )
    reprint_create = _planned(
        official_product_code="PRB-01",
        proposed_canonical_card=ProposedCanonicalCard(
            "OP01-001", "モンキー・D・ルフィ", "OP-01", "SEC", "Leader"
        ),
    )

    audit = A.audit_canonical_baselines([own_set_needs_review, reprint_create])

    assert audit.baselines["OP01-001"].rarity == "L"


# --- §4 which canonical columns may be written ---------------------------


def test_only_language_independent_numerics_are_read_from_the_entry():
    entry = OfficialCardEntry(
        entry_id="OP01-001",
        card_code="OP01-001",
        rarity="L",
        category="LEADER",
        card_name="モンキー・D・ルフィ",
        image_url=f"{CARD_LIST}/OP01-001.png",
        product_names=("ROMANCE DAWN【OP-01】",),
        fields=(
            RawField("cost", "コスト", "2"),
            RawField("power", "パワー", "5000"),
            RawField("counter", "カウンター", "-"),
            RawField("color", "色", "赤"),
            RawField("attribute", "属性", "-", image_alt="斬"),
        ),
    )

    baseline = A.resolve_canonical_baseline(
        "OP01-001", [_planned()], entries={"OP01-001": entry}
    )

    assert (baseline.cost, baseline.power) == (2, 5000)
    # Bandai's '-' is a published "no value", not a number.
    assert baseline.counter is None
    # colors and attribute are not on the baseline at all: the columns hold
    # English and the catalogue publishes Japanese.
    assert not hasattr(baseline, "colors")
    assert not hasattr(baseline, "attribute")


@pytest.mark.parametrize(
    "published, expected",
    [("2", 2), ("0", 0), ("12000", 12000), ("-", None), ("", None), (None, None), ("N/A", None)],
)
def test_a_numeric_block_is_parsed_or_left_alone(published, expected):
    assert A._numeric(published) == expected


def test_the_language_ambiguous_columns_are_named_as_deliberately_excluded():
    """A regression guard on the decision, not on the code path: if someone
    later adds colors or attribute to NUMERIC_FIELDS this fails loudly."""
    assert A.NUMERIC_FIELDS == ("cost", "power", "counter")
    assert "colors" not in A.NUMERIC_FIELDS
    assert "attribute" not in A.NUMERIC_FIELDS
    assert "effect_text" not in A.NUMERIC_FIELDS
    assert "trigger_text" not in A.NUMERIC_FIELDS


# --- §7 metadata backfill -------------------------------------------------


class _StoredPrint:
    def __init__(self, **values):
        self.id = values.pop("id", 7)
        self.artwork_key = values.pop("artwork_key", "a" * 64)
        for name in P.METADATA_FIELDS:
            setattr(self, name, values.pop(name, None))


def test_a_no_change_plan_fills_in_only_the_null_metadata():
    stored = _StoredPrint(official_rarity="SR")
    planned = _planned(outcome=P.OUTCOME_NO_CHANGE, existing_card_print_id=7)

    backfill = A.plan_metadata_backfill(planned, stored)

    assert backfill is not None
    assert set(backfill.values) == {
        "official_block_icon",
        "official_name",
        "official_effect_text",
    }
    assert "official_rarity" not in backfill.values


def test_nothing_to_fill_in_is_not_an_update():
    stored = _StoredPrint(**{name: getattr(_metadata(), name) for name in P.METADATA_FIELDS})
    planned = _planned(outcome=P.OUTCOME_NO_CHANGE, existing_card_print_id=7)

    assert A.plan_metadata_backfill(planned, stored) is None


def test_a_stored_value_that_disagrees_aborts_rather_than_being_overwritten():
    stored = _StoredPrint(official_rarity="R")
    planned = _planned(outcome=P.OUTCOME_NO_CHANGE, existing_card_print_id=7)

    with pytest.raises(A.ApplyAborted) as excinfo:
        A.plan_metadata_backfill(planned, stored)

    assert excinfo.value.reason == "existing_metadata_conflict"
    assert stored.official_rarity == "R"


def test_a_changed_asset_digest_aborts_the_backfill():
    stored = _StoredPrint(artwork_key="b" * 64)
    planned = _planned(outcome=P.OUTCOME_NO_CHANGE, existing_card_print_id=7)

    with pytest.raises(A.ApplyAborted) as excinfo:
        A.plan_metadata_backfill(planned, stored)

    assert excinfo.value.reason == A.ABORT_EXISTING_ASSET_DIGEST


def test_the_asset_changed_flag_alone_aborts_the_backfill():
    stored = _StoredPrint()
    planned = _planned(
        outcome=P.OUTCOME_NO_CHANGE,
        existing_card_print_id=7,
        flags=(P.FLAG_ASSET_CHANGED,),
    )

    with pytest.raises(A.ApplyAborted) as excinfo:
        A.plan_metadata_backfill(planned, stored)

    assert excinfo.value.reason == A.ABORT_EXISTING_ASSET_DIGEST


def test_backfill_is_only_offered_for_a_no_change_plan():
    assert A.plan_metadata_backfill(_planned(), _StoredPrint()) is None


# --- 4C-4B a planner conflict fails closed --------------------------------


class _FakeSession:
    """Exactly as much session as the conflict preflight uses: it re-reads the
    canonical row a conflict is about, and nothing else."""

    def __init__(self, rows=None):
        self.rows = rows or {}
        self.reads = []

    def get(self, model, pk):
        self.reads.append((model.__name__, pk))
        return self.rows.get(pk)


class _StoredCard:
    def __init__(self, **values):
        self.name_jp = values.get("name_jp", "ルフィ")
        self.rarity = values.get("rarity", "L")
        self.card_type = values.get("card_type", "Leader")
        self.original_set_code = values.get("original_set_code", "OP-01")


def _conflicted(**overrides) -> PlannedPrint:
    values = dict(
        outcome=P.OUTCOME_CONFLICT,
        verification_status=P.NEEDS_REVIEW,
        existing_canonical_card_id=41,
        flags=(P.FLAG_CANONICAL_CARD_CONFLICT,),
        reasons=(
            "existing canonical card #41 disagrees with the catalogue on "
            "name_jp ('ルフィ' vs 'モンキー・D・ルフィ')",
        ),
    )
    values.update(overrides)
    return _planned(**values)


def _preflight(prints, *, rows=None):
    session = _FakeSession(rows if rows is not None else {41: _StoredCard()})
    applier = A.CanonicalImportApplier(
        session,
        P.ImportPlan(prints=list(prints)),
        pinning=A.ApplyPinning(snapshot_identity="s" * 64),
        environment="test",
    )
    report = A.ApplyReport()
    applier._check_no_planner_conflicts(report)
    return report


def test_one_conflict_aborts_the_whole_run():
    with pytest.raises(A.ApplyAborted) as excinfo:
        _preflight([_planned(), _conflicted(), _planned(entry_id="OP01-013")])

    assert excinfo.value.reason == A.ABORT_PLANNER_CONFLICT
    assert A.ABORT_PLANNER_CONFLICT == "planner_conflict"


def test_a_plan_with_no_conflict_passes_the_preflight():
    report = _preflight([_planned(), _planned(outcome=P.OUTCOME_NO_CHANGE)])

    assert report.planner_conflicts == 0


def test_needs_review_is_not_a_conflict_and_does_not_abort():
    """An ambiguity the planner refused to resolve costs its own rows only."""
    report = _preflight(
        [
            _planned(outcome=P.OUTCOME_NEEDS_REVIEW, verification_status=P.NEEDS_REVIEW),
            _planned(outcome=P.OUTCOME_NEEDS_REVIEW, flags=(P.FLAG_ASSET_CHANGED,)),
            _planned(outcome=P.OUTCOME_NEEDS_REVIEW, flags=(P.FLAG_UNCODED_PRODUCT,)),
            _planned(),
        ]
    )

    assert report.planner_conflicts == 0


def test_the_abort_names_every_conflict_type_the_planner_can_raise():
    """Not the name case specifically: the outcome is what is read."""
    for reason in (
        "name_jp ('ルフィ' vs 'モンキー・D・ルフィ')",
        "rarity ('L' vs 'SR')",
        "card_type ('Leader' vs 'Character')",
    ):
        with pytest.raises(A.ApplyAborted) as excinfo:
            _preflight([_conflicted(reasons=(reason,))])

        assert excinfo.value.reason == A.ABORT_PLANNER_CONFLICT
        assert reason in excinfo.value.context["conflicts"][0]["reasons"]


def test_the_abort_context_carries_both_sides_of_the_disagreement():
    with pytest.raises(A.ApplyAborted) as excinfo:
        _preflight([_conflicted()])

    context = excinfo.value.context
    assert context["planner_conflicts"] == 1
    entry = context["conflicts"][0]
    assert entry["card_code"] == "OP01-001"
    assert entry["entry_id"] == "OP01-001"
    assert entry["existing_canonical_card_id"] == 41
    assert entry["official_product_code"] == "OP-01"
    assert entry["flags"] == [P.FLAG_CANONICAL_CARD_CONFLICT]
    assert entry["reasons"]
    # both sides, named rather than parsed out of a sentence
    assert entry["canonical"]["name_jp"] == "ルフィ"
    assert entry["official"]["card_name"] == "モンキー・D・ルフィ"
    assert json.dumps(context, ensure_ascii=False)


def test_the_conflict_count_is_exact_and_the_sample_is_bounded():
    conflicts = [_conflicted(entry_id=f"OP01-{i:03d}") for i in range(60)]

    with pytest.raises(A.ApplyAborted) as excinfo:
        _preflight(conflicts)

    context = excinfo.value.context
    assert context["planner_conflicts"] == 60
    assert context["reported"] == A.CONFLICT_CONTEXT_LIMIT
    assert len(context["conflicts"]) == A.CONFLICT_CONTEXT_LIMIT


def test_the_preflight_reads_only_the_conflicting_cards_canonical_row():
    session = _FakeSession({41: _StoredCard()})
    applier = A.CanonicalImportApplier(
        session,
        P.ImportPlan(prints=[_planned(existing_canonical_card_id=9), _conflicted()]),
        pinning=A.ApplyPinning(snapshot_identity="s" * 64),
        environment="test",
    )

    with pytest.raises(A.ApplyAborted):
        applier._check_no_planner_conflicts(A.ApplyReport())

    assert session.reads == [("CanonicalCard", 41)]


def test_a_conflict_is_never_demoted_to_needs_review_or_mutated():
    """The planner's decision is read, never edited."""
    conflict = _conflicted()

    with pytest.raises(A.ApplyAborted):
        _preflight([conflict])

    assert conflict.outcome == P.OUTCOME_CONFLICT
    # and even if one were somehow handed to the writer, it is not eligible.
    assert not A.evaluate_eligibility(
        conflict, composable_card_codes={"OP01-001"}
    ).eligible


def test_the_conflict_preflight_runs_before_anything_is_composed():
    """Ordering, read from the source: after pinning, before every write."""
    source = (
        REPO_ROOT / "app" / "services" / "canonical_import_apply.py"
    ).read_text(encoding="utf-8")
    execute = source.split("def _execute")[1].split("\n    def ")[0]

    at = execute.index("_check_no_planner_conflicts")
    assert execute.index("self._check_pinning") < at
    for later in (
        "self._create_products",
        "self._create_canonical_cards",
        "self._create_card_prints",
        "self._backfill_existing_metadata",
        "self._session.flush()",
        "self._session.commit()",
    ):
        assert at < execute.index(later), later
    # and it reads the COMPLETE plan, not the eligible subset
    body = source.split("def _check_no_planner_conflicts")[1].split("\n    def ")[0]
    assert "self._plan.prints" in body


def test_the_two_fatal_disagreements_are_one_vocabulary():
    """Artwork drift and identity drift are named separately, both fatal."""
    assert A.ABORT_PLANNER_CONFLICT != A.ABORT_EXISTING_ASSET_DIGEST
    assert A.ABORT_PLANNER_CONFLICT not in (
        A.SKIP_NOT_CREATE,
        A.SKIP_NO_DIGEST,
        A.SKIP_NO_BASELINE_OCCURRENCE,
    )


# --- §11 CLI safety -------------------------------------------------------


def _cli(*args: str):
    return subprocess.run(
        [sys.executable, "-m", "app.apply_canonical_print_import", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )


@pytest.mark.parametrize("environment", ["production", "prod", "PRODUCTION", "Prod"])
def test_the_cli_hard_refuses_production(environment):
    result = _cli("--database-url", "postgresql+psycopg://x/y", "--environment", environment,
                  "--apply")

    assert result.returncode == 2
    assert "REFUSED" in result.stderr


def test_the_cli_refuses_canonical_staging():
    """Not authorised in this tranche even though it is a real environment."""
    result = _cli("--database-url", "postgresql+psycopg://x/y", "--environment", "staging",
                  "--apply")

    assert result.returncode == 2
    assert "REFUSED" in result.stderr


def test_apply_without_an_acknowledged_environment_is_refused():
    result = _cli("--database-url", "postgresql+psycopg://x/y", "--apply")

    assert result.returncode == 2
    assert "--environment" in result.stderr


def test_an_environment_outside_the_allowlist_is_refused():
    result = _cli("--database-url", "postgresql+psycopg://x/y", "--environment", "somewhere",
                  "--apply")

    assert result.returncode == 2
    assert "allowlist" in result.stderr


def test_the_cli_accepts_a_pinned_snapshot_identity():
    """§10. `--expect-snapshot` reaches the pinning the engine actually checks."""
    args = apply_cli.build_parser().parse_args(
        ["--database-url", "sqlite://", "--expect-snapshot", "abc123"]
    )

    assert args.expect_snapshot == "abc123"


def test_a_pinned_snapshot_identity_defaults_to_unpinned():
    args = apply_cli.build_parser().parse_args(["--database-url", "sqlite://"])

    assert args.expect_snapshot is None
    assert A.ApplyPinning(snapshot_identity="x").expected_snapshot_identity is None


def test_the_allowlist_and_refusal_list_are_what_this_tranche_authorises():
    assert A.ALLOWED_APPLY_ENVIRONMENTS == ("test", "development", "staging_copy")
    for refused in ("production", "prod", "staging"):
        assert refused in A.REFUSED_APPLY_ENVIRONMENTS
    assert not set(A.ALLOWED_APPLY_ENVIRONMENTS) & set(A.REFUSED_APPLY_ENVIRONMENTS)


def test_the_read_only_planner_cli_still_has_no_write_path():
    """The reason this is a second command: adding --apply to the planner
    would make its read-only promise conditional."""
    source = (REPO_ROOT / "app" / "plan_canonical_print_import.py").read_text(encoding="utf-8")

    # The prose says "there is no --apply"; what matters is that no argument
    # named that is ever registered, and that nothing writes.
    assert 'add_argument("--apply"' not in source
    assert "session.add" not in source
    assert "commit()" not in source


def test_the_apply_module_is_the_only_one_that_commits():
    engine = (REPO_ROOT / "app" / "services" / "canonical_import_apply.py").read_text(
        encoding="utf-8"
    )
    planner_source = (REPO_ROOT / "app" / "services" / "print_import_planner.py").read_text(
        encoding="utf-8"
    )

    assert "commit()" in engine
    assert "commit()" not in planner_source


# --- §16 tables this engine must never write -----------------------------


def test_the_untouched_tables_are_named_and_checked():
    assert set(A.UNTOUCHED_TABLES) == {
        "source_card_mappings",
        "price_observations",
        "market_index_snapshots",
    }
    assert set(A.UNTOUCHED_TABLES) <= set(A.COUNTED_TABLES)


def test_no_write_to_a_forbidden_table_appears_in_the_engine():
    source = (REPO_ROOT / "app" / "services" / "canonical_import_apply.py").read_text(
        encoding="utf-8"
    )

    for model in ("SourceCardMapping", "PriceObservation", "MarketIndexSnapshot"):
        assert model not in source, f"{model} must not be reachable from the apply engine"
    # The legacy `cards` table, whose model is app.models.card.Card. Matched on
    # the import line rather than the bare word, so CanonicalCard - which this
    # engine does write - is not mistaken for it.
    assert "from app.models import CanonicalCard, CardPrint, ReleaseProduct" in source
    assert "app.models.card import" not in source


# --- §12 report -----------------------------------------------------------


def test_the_report_carries_everything_the_audit_asks_for():
    report = A.ApplyReport(snapshot_identity="deadbeef", db_revision="a9f31c7d5b64")

    document = report.to_dict()

    for key in (
        "snapshot_identity", "db_revision", "started_at", "finished_at",
        "products_created", "canonical_cards_created", "card_prints_created",
        "existing_print_metadata_updated", "skipped_needs_review", "planner_conflicts",
        "rollback_reason", "rollback_context",
    ):
        assert key in document
    assert json.dumps(document)  # serialisable as it stands


def test_an_abort_carries_named_values_not_only_a_sentence():
    """The digest refusal is read as fields, never by parsing the message."""
    aborted = A.ApplyAborted(
        A.ABORT_EXISTING_ASSET_DIGEST,
        "card_print #3 ...",
        {"card_print_id": 3, "stored_artwork_sha256": "d" * 64},
    )

    assert aborted.context["card_print_id"] == 3
    # And a refusal with no structured evidence still has an empty mapping,
    # so a caller never has to guard the attribute.
    assert A.ApplyAborted("refused_environment", "prod").context == {}


def test_the_two_asset_conditions_are_one_vocabulary_and_are_opposites():
    """A missing digest on a NEW print skips one row; a drifted digest on an
    EXISTING print aborts the run. Named separately, deliberately."""
    assert A.SKIP_NO_DIGEST != A.ABORT_EXISTING_ASSET_DIGEST
    assert A.ABORT_EXISTING_ASSET_DIGEST == "existing_asset_digest_mismatch"

    # Missing input is still only an eligibility reason.
    decision = A.evaluate_eligibility(
        _planned(official_artwork_sha256=None), composable_card_codes={"OP01-001"}
    )
    assert decision.reasons == (A.SKIP_NO_DIGEST,)


def test_the_digest_preflight_reads_the_whole_plan_not_the_eligible_subset():
    """An asset_changed plan is needs_review, so it is never eligible. A check
    that only looked at eligible rows would never see it."""
    source = (
        REPO_ROOT / "app" / "services" / "canonical_import_apply.py"
    ).read_text(encoding="utf-8")
    body = source.split("def _check_existing_asset_digests")[1].split("\n    def ")[0]

    # It iterates the whole plan, and is not handed the eligible subset.
    assert "self._plan.prints" in body
    assert "def _check_existing_asset_digests(self) -> None:" in source
    # And it runs before the first write helper is called.
    execute = source.split("def _execute")[1].split("\n    def ")[0]
    assert execute.index("_check_existing_asset_digests") < execute.index(
        "self._create_products"
    )
