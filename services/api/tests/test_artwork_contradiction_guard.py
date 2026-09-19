"""The outside-survivor contradiction guard (PROTOTYPE - not wired in).

The guard's whole job is to notice that the product channel and the artwork
channel disagree about the same photo, and to refuse rather than pick a side.
So most of these tests are about what it must NOT do: it must not resurrect an
excluded print, must not widen a survivor set, must not override product
evidence, and must not veto a case where the two channels agree.

Candidate 10 is pinned here as a score relationship rather than as image bytes.
The bytes are a third party's listing photo and do not belong in the
repository; the numbers below are what the audit of 2026-08-29 measured from
them, and they are the thing the guard actually reasons over.
"""

import pytest

from app.services.artwork_contradiction_guard import (
    CONFLICT_CLASS_SPANS_SURVIVORS,
    CONFLICT_EQUIVALENT_OUTSIDE,
    CONFLICT_STRONGER_OUTSIDE,
    CONTRADICTION_COMPETITIVE_MARGIN,
    OUTCOME_NARROW,
    OUTCOME_NO_NARROW,
    OUTCOME_VETO,
    apply_contradiction_guard,
    evaluate_with_contradiction_guard,
)
from app.services.artwork_evidence import (
    STATUS_AMBIGUOUS,
    STATUS_EXACT,
    ArtworkVerdict,
    evaluate_artwork,
)
from app.services.exact_print_approval import (
    REFUSAL_UNRESOLVED_SOURCE_PRODUCT,
    ExactPrintApprovalError,
    SourceEvidence,
    resolve_exact_print,
)
from tests.test_artwork_evidence import _canvas, _png
from tests.test_exact_print_approval import catalogue  # noqa: F401 - fixture

# --- candidate 10, as measured on 2026-08-29 ---------------------------------
#
# Listing photo sha256 d833d762bdd053b71c028fa0f5597c25f6e805c8907a77da76bf2998ae40816e,
# which is OP01-120 `p2` - print 6140. Scores are phash16 distances under
# artwork-evidence/phash16-v2. Prints 2879 and 6138 are the byte-identical
# reprint pair and share one artwork_key, which is why 2879 being a survivor
# also makes 6138's class an inside class.
C10_SCORES = {2878: 130, 2879: 134, 2880: 34, 6138: 134, 6139: 72, 6140: 24}
C10_KEYS = {
    2878: "4862e0c635",  # p5, PRB-01
    2879: "4a996805b2",  # r1, PRB-01
    2880: "da97c9cfd9",  # r2, PRB-01
    6138: "4a996805b2",  # base, OP-01 - same artwork as 2879
    6139: "1a5bcc77f5",  # p1, OP-01
    6140: "c8f6748542",  # p2, OP-01 - the printing the photo actually shows
}
OP01_SURVIVORS = (6138, 6139, 6140)
PRB01_SURVIVORS = (2878, 2879, 2880)


def _verdict(status, survivors, *, chosen=None, best=None, runner=None, margin=None):
    scores = {p: C10_SCORES[p] for p in survivors}
    return ArtworkVerdict(
        status=status,
        card_print_id=chosen,
        winning_class=(chosen,) if chosen else (),
        best_score=best,
        runner_up_score=runner,
        margin=margin,
        card_print_ids_before=tuple(sorted(survivors)),
        card_print_ids_after=(chosen,) if chosen else tuple(sorted(survivors)),
        scores=scores,
    )


def _global_verdict():
    return ArtworkVerdict(
        status=STATUS_EXACT,
        card_print_id=6140,
        winning_class=(6140,),
        best_score=24,
        runner_up_score=34,
        margin=10,
        card_print_ids_before=tuple(sorted(C10_SCORES)),
        card_print_ids_after=(6140,),
        scores=dict(C10_SCORES),
    )


def test_candidate_10_wrong_product_set_is_vetoed_not_narrowed():
    """THE PINNED REGRESSION.

    If the product evidence wrongly resolves this OP-01 listing to PRB-01, the
    survivor set is the three PRB-01 printings and artwork returns `exact` on
    print 2880 at best 34, margin 96 - inside both thresholds, and wrong. The
    guard must see print 6140 scoring 24 outside that set and refuse.
    """
    survivor = _verdict(STATUS_EXACT, PRB01_SURVIVORS, chosen=2880, best=34, runner=130, margin=96)
    assert survivor.is_exact and survivor.card_print_id == 2880

    guarded = apply_contradiction_guard(survivor, _global_verdict(), PRB01_SURVIVORS, C10_KEYS)

    assert guarded.outcome == OUTCOME_VETO
    assert guarded.conflict == CONFLICT_STRONGER_OUTSIDE
    assert guarded.inside_best == 34
    assert guarded.outside_best == 24
    assert guarded.outside_best_prints == (6140,)
    # The veto must leave the survivor set exactly as it found it: no
    # resurrection of 6140, no narrowing to 2880.
    assert guarded.card_print_ids_after == PRB01_SURVIVORS
    assert 6140 not in guarded.card_print_ids_after
    assert "disagree" in guarded.as_diagnostic()


def test_candidate_10_narrows_on_its_correct_product_set():
    """The same photo, the same global field, the RIGHT survivor set. The
    guard must stay out of the way - a brake that also stops correct answers
    is not worth having."""
    survivor = _verdict(STATUS_EXACT, OP01_SURVIVORS, chosen=6140, best=24, runner=72, margin=48)
    guarded = apply_contradiction_guard(survivor, _global_verdict(), OP01_SURVIVORS, C10_KEYS)

    assert guarded.outcome == OUTCOME_NARROW
    assert guarded.card_print_ids_after == (6140,)
    assert guarded.inside_best == 24
    # 2880 is the nearest outside class and it is 10 further away, not closer.
    assert guarded.outside_best == 34
    assert guarded.outside_best_prints == (2880,)


def test_the_competitive_margin_is_off_by_default_and_costs_this_case_when_raised():
    """The measured trade-off, pinned so it cannot be changed silently.

    Candidate 10's correct answer sits 10 away from an outside class. Any
    competitive margin above 10 buys stricter contradiction detection by
    refusing this known-correct narrowing.
    """
    assert CONTRADICTION_COMPETITIVE_MARGIN == 0
    survivor = _verdict(STATUS_EXACT, OP01_SURVIVORS, chosen=6140, best=24, runner=72, margin=48)

    for margin, expected in ((0, OUTCOME_NARROW), (10, OUTCOME_NARROW), (11, OUTCOME_VETO),
                             (40, OUTCOME_VETO)):
        guarded = apply_contradiction_guard(
            survivor, _global_verdict(), OP01_SURVIVORS, C10_KEYS,
            competitive_margin=margin,
        )
        assert guarded.outcome == expected, margin


def test_an_equally_close_outside_artwork_is_a_veto():
    """A tie is not a coin toss. If an excluded print's artwork is exactly as
    close as the winner's, selecting the survivor is unjustified."""
    scores = dict(C10_SCORES)
    scores[2880] = 24  # as close as 6140
    global_verdict = ArtworkVerdict(
        status=STATUS_AMBIGUOUS, card_print_ids_before=tuple(sorted(scores)),
        card_print_ids_after=tuple(sorted(scores)), scores=scores, best_score=24, margin=0,
    )
    survivor = _verdict(STATUS_EXACT, OP01_SURVIVORS, chosen=6140, best=24, runner=72, margin=48)
    guarded = apply_contradiction_guard(survivor, global_verdict, OP01_SURVIVORS, C10_KEYS)
    assert guarded.outcome == OUTCOME_VETO
    assert guarded.conflict == CONFLICT_EQUIVALENT_OUTSIDE


def test_a_class_spanning_the_boundary_is_reported_but_does_not_veto_by_default():
    """Prints 2879 and 6138 share one artwork_key across two products. When
    6138 is a survivor and 2879 is not, the winning class straddles the
    boundary. That is worth recording, but on its own it is not a
    contradiction - the excluded twin was excluded by product evidence, and
    artwork agreeing with its twin says nothing new."""
    survivor = _verdict(STATUS_EXACT, OP01_SURVIVORS, chosen=6138, best=134, runner=134, margin=60)
    guarded = apply_contradiction_guard(survivor, _global_verdict(), OP01_SURVIVORS, C10_KEYS)
    assert guarded.class_spans_boundary is True
    assert guarded.outcome == OUTCOME_VETO  # 6140 at 24 is stronger, so it vetoes anyway
    assert guarded.conflict == CONFLICT_STRONGER_OUTSIDE

    strict = apply_contradiction_guard(
        survivor, _global_verdict(), OP01_SURVIVORS, C10_KEYS, veto_on_class_span=True
    )
    assert strict.conflict == CONFLICT_CLASS_SPANS_SURVIVORS


def test_a_non_exact_survivor_verdict_is_left_alone():
    """The guard only ever removes a narrowing. When artwork was not going to
    narrow anyway, it must add nothing and change nothing."""
    survivor = _verdict(STATUS_AMBIGUOUS, OP01_SURVIVORS)
    guarded = apply_contradiction_guard(survivor, _global_verdict(), OP01_SURVIVORS, C10_KEYS)
    assert guarded.outcome == OUTCOME_NO_NARROW
    assert guarded.card_print_ids_after == OP01_SURVIVORS


# --- end to end, over real pixels -------------------------------------------


def test_global_winner_inside_the_survivors_still_narrows():
    """The ordinary base/parallel case: the photo shows a surviving print and
    the excluded siblings look nothing like it."""
    art_p1, art_base, art_excluded = _png(31), _png(32), _png(33)
    listing = _canvas([(art_p1, (40, 90))])
    survivors = {1: art_p1, 2: art_base}
    field = {1: art_p1, 2: art_base, 3: art_excluded}
    keys = {1: "k1", 2: "k2", 3: "k3"}

    guarded = evaluate_with_contradiction_guard(listing, survivors, field, artwork_keys=keys)
    assert guarded.survivor_verdict.status == STATUS_EXACT
    assert guarded.outcome == OUTCOME_NARROW
    assert guarded.card_print_ids_after == (1,)


def test_guard_refuses_when_the_photo_matches_an_excluded_print():
    """The contradiction, over real pixels rather than pinned numbers."""
    art_survivor_a, art_survivor_b, art_excluded = _png(41), _png(42), _png(43)
    listing = _canvas([(art_excluded, (40, 90))])
    survivors = {1: art_survivor_a, 2: art_survivor_b}
    field = {1: art_survivor_a, 2: art_survivor_b, 3: art_excluded}
    keys = {1: "k1", 2: "k2", 3: "k3"}

    guarded = evaluate_with_contradiction_guard(listing, survivors, field, artwork_keys=keys)
    assert guarded.outcome in (OUTCOME_VETO, OUTCOME_NO_NARROW)
    if guarded.outcome == OUTCOME_VETO:
        assert guarded.conflict == CONFLICT_STRONGER_OUTSIDE
        assert guarded.outside_best_prints == (3,)
    # Whatever it decided, print 3 must not have been resurrected.
    assert 3 not in guarded.card_print_ids_after
    assert set(guarded.card_print_ids_after) <= {1, 2}


def test_shared_artwork_key_reprints_stay_ambiguous():
    """Exact artwork classes are unchanged by the guard: two prints of one
    artwork are still two prints of one artwork, and no amount of global
    context separates them."""
    art = _png(51)
    listing = _canvas([(art, (40, 90))])
    survivors = {1: art, 2: art}
    field = {1: art, 2: art, 3: _png(52)}
    keys = {1: "shared", 2: "shared", 3: "other"}

    guarded = evaluate_with_contradiction_guard(listing, survivors, field, artwork_keys=keys)
    assert guarded.survivor_verdict.status == STATUS_AMBIGUOUS
    assert set(guarded.survivor_verdict.winning_class) == {1, 2}
    assert guarded.outcome == OUTCOME_NO_NARROW
    assert guarded.card_print_ids_after == (1, 2)


def test_passing_one_field_for_both_reproduces_todays_behaviour():
    """The guard is a strict extension: with no outside prints to see, it can
    only ever agree with the verdict it was given."""
    art_a, art_b = _png(61), _png(62)
    listing = _canvas([(art_a, (40, 90))])
    field = {1: art_a, 2: art_b}
    keys = {1: "k1", 2: "k2"}

    today = evaluate_artwork(listing, field, artwork_keys=keys)
    guarded = evaluate_with_contradiction_guard(listing, field, field, artwork_keys=keys)
    assert guarded.survivor_verdict.status == today.status
    assert guarded.survivor_verdict.card_print_id == today.card_print_id
    assert guarded.outcome == OUTCOME_NARROW
    assert guarded.card_print_ids_after == today.card_print_ids_after
    assert guarded.outside_best is None


# --- containment -------------------------------------------------------------


def test_unresolved_source_product_is_still_fail_closed(catalogue):  # noqa: F811
    """The guard sits downstream of the product refusals and must not create a
    path around them: a listing whose product Atlas does not hold is refused
    before artwork is consulted at all."""
    with pytest.raises(ExactPrintApprovalError) as excinfo:
        resolve_exact_print(
            catalogue["db"],
            card_print_id=catalogue["prints"]["p2"].id,
            evidence=SourceEvidence(
                source_name="snkrdunk",
                source_url="https://snkrdunk.com/en/trading-cards/900001",
                card_code="OP02-013",
                product_label="Premium Card Collection 25th Anniversary",
            ),
        )
    assert excinfo.value.code == REFUSAL_UNRESOLVED_SOURCE_PRODUCT


def test_the_guard_is_not_wired_into_the_resolver():
    """This tranche measures the guard; it does not deploy it. If someone
    wires it in, that is a deliberate change and this test should be the thing
    that makes them say so."""
    import inspect

    from app.services import exact_print_approval

    source = inspect.getsource(exact_print_approval)
    assert "artwork_contradiction_guard" not in source
