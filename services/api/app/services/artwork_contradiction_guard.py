"""PROTOTYPE. An outside-survivor contradiction guard for artwork evidence.

NOT WIRED INTO ANYTHING. `exact_print_approval.resolve_exact_print` does not
import this module and its behaviour is unchanged; this exists to be measured
against the replay corpus before anyone decides whether it earns its place.

THE FAILURE IT EXISTS TO CATCH. Artwork evidence is evaluated only over the
prints some other channel already left standing. That is what stops it
resurrecting an excluded printing - but it also means artwork never sees the
print the photo actually shows if the product evidence excluded it. Staging
candidate 10 is the proof: the listing photo is OP01-120 `p2` (print 6140,
score 24). If the product evidence had resolved that listing to PRB-01 instead
of OP-01, the survivor set would be the three PRB-01 printings, and artwork
would return `exact` on print 2880 at best 34 with margin 96 - a confident,
auditable, wrong answer, with both ARTWORK_ACCEPT_MAX and ARTWORK_MARGIN_MIN
satisfied. Neither threshold can see the problem, because the print that would
have exposed it was never scored.

THE RULE. Score the listing twice: once over the survivor set exactly as today,
and once over EVERY active, verified print sharing the card code - the field
`exact_print_approval.sibling_prints_for_card_code` already returns. Then allow
narrowing only when the survivor answer is also the global answer. When the
strongest artwork evidence sits outside the survivor set, the two channels
disagree about the same photo, and the honest report is that disagreement.

WHAT IT DELIBERATELY DOES NOT DO. It never resurrects the outside print, never
overrides the product evidence, and never widens the survivor set: a veto
returns the survivors untouched and a diagnostic. It is strictly a brake. The
worst it can do to a correct answer is refuse to narrow it, which is the same
outcome as artwork evidence being switched off.

WHAT IT IS NOT. It is not a threshold change - ARTWORK_ACCEPT_MAX and
ARTWORK_MARGIN_MIN are untouched and unread here. It is not fuzzy artwork
identity either: classes are still `card_prints.artwork_key`, exact byte
identity of the official asset, so two genuinely different artworks are still
two classes no matter how close they score.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.artwork_evidence import (
    ARTWORK_ACCEPT_MAX,
    ARTWORK_MARGIN_MIN,
    STATUS_EXACT,
    ArtworkVerdict,
    evaluate_artwork,
)

# How much closer an outside-survivor artwork class has to be before its
# presence is treated as a contradiction rather than a distant runner-up.
#
# PROVISIONAL, and deliberately NOT derived from ARTWORK_MARGIN_MIN: that
# threshold answers "are these two artworks separable", which is a question
# about the picture. This one answers "do the product and artwork channels
# disagree", which is a question about the evidence, and the two do not have to
# move together. 0 means veto only when the outside class is at least as close
# as the winner - the smallest rule that still catches candidate 10.
CONTRADICTION_COMPETITIVE_MARGIN = 0

OUTCOME_NARROW = "narrow"
OUTCOME_VETO = "veto"
OUTCOME_NO_NARROW = "no_narrow"

CONFLICT_STRONGER_OUTSIDE = "artwork_stronger_outside_survivors"
CONFLICT_EQUIVALENT_OUTSIDE = "artwork_equivalent_outside_survivors"
CONFLICT_COMPETITIVE_OUTSIDE = "artwork_competitive_outside_survivors"
CONFLICT_CLASS_SPANS_SURVIVORS = "artwork_class_spans_survivor_boundary"


@dataclass(frozen=True)
class GuardedArtworkVerdict:
    """The survivor-set verdict, the global verdict, and what the guard did.

    `card_print_ids_after` is the contract that matters: on every outcome it is
    either the narrowed set the survivor verdict already proposed, or the
    survivor set unchanged. It never contains a print the caller did not pass
    in as a survivor.
    """

    outcome: str
    survivor_verdict: ArtworkVerdict
    global_verdict: ArtworkVerdict
    card_print_ids_after: tuple[int, ...]
    conflict: str | None = None
    detail: str | None = None
    inside_best: int | None = None
    outside_best: int | None = None
    outside_best_prints: tuple[int, ...] = ()
    class_spans_boundary: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def narrowed(self) -> bool:
        return self.outcome == OUTCOME_NARROW

    @property
    def vetoed(self) -> bool:
        return self.outcome == OUTCOME_VETO

    def as_diagnostic(self) -> str:
        if self.outcome != OUTCOME_VETO:
            return self.detail or self.outcome
        return (
            f"{self.conflict}: the survivor set's best artwork scores "
            f"{self.inside_best}, but print(s) {list(self.outside_best_prints)} "
            f"outside it score {self.outside_best}. The product and artwork "
            "channels disagree about this photo, so artwork narrows nothing."
        )


def _classes(verdict: ArtworkVerdict, artwork_keys: dict[int, str]) -> dict[str, list[int]]:
    """Group the scored prints into artwork classes, exactly as the evidence
    module does - by `artwork_key`, never by score proximity."""
    grouped: dict[str, list[int]] = {}
    for print_id in verdict.scores:
        key = artwork_keys.get(print_id) or f"unkeyed:{print_id}"
        grouped.setdefault(key, []).append(print_id)
    return grouped


def apply_contradiction_guard(
    survivor_verdict: ArtworkVerdict,
    global_verdict: ArtworkVerdict,
    survivor_ids: list[int] | tuple[int, ...],
    artwork_keys: dict[int, str],
    *,
    competitive_margin: int = CONTRADICTION_COMPETITIVE_MARGIN,
    veto_on_class_span: bool = False,
) -> GuardedArtworkVerdict:
    """The decision, as a pure function over two already-computed verdicts.

    Kept separate from the image pipeline so a measured score relationship can
    be pinned in a test without shipping the listing bytes that produced it.
    """
    survivors = tuple(sorted(survivor_ids))

    if not survivor_verdict.is_exact:
        return GuardedArtworkVerdict(
            outcome=OUTCOME_NO_NARROW,
            survivor_verdict=survivor_verdict,
            global_verdict=global_verdict,
            card_print_ids_after=survivors,
            detail=(
                f"survivor-set artwork is {survivor_verdict.status}; there is "
                "nothing for the guard to allow or refuse"
            ),
        )

    inside_best = survivor_verdict.best_score
    chosen = survivor_verdict.card_print_id

    # The global field may be unusable (an official asset that will not decode)
    # while the survivor field was fine. Absent evidence vetoes nothing.
    if not global_verdict.scores:
        return GuardedArtworkVerdict(
            outcome=OUTCOME_NARROW,
            survivor_verdict=survivor_verdict,
            global_verdict=global_verdict,
            card_print_ids_after=survivor_verdict.card_print_ids_after,
            inside_best=inside_best,
            detail="no global artwork field could be scored; survivor verdict stands",
            notes=("global_field_unscored",),
        )

    grouped = _classes(global_verdict, artwork_keys)
    survivor_set = set(survivors)

    winning_key = next(
        (k for k, members in grouped.items() if chosen in members),
        None,
    )
    spans = bool(
        winning_key is not None and set(grouped[winning_key]) - survivor_set
    )

    outside_best: int | None = None
    outside_prints: tuple[int, ...] = ()
    for key, members in sorted(grouped.items()):
        if set(members) & survivor_set:
            continue  # a class holding a survivor is not "outside"
        best = min(global_verdict.scores[m] for m in members)
        if outside_best is None or best < outside_best:
            outside_best = best
            outside_prints = tuple(sorted(members))

    def veto(conflict: str) -> GuardedArtworkVerdict:
        return GuardedArtworkVerdict(
            outcome=OUTCOME_VETO,
            survivor_verdict=survivor_verdict,
            global_verdict=global_verdict,
            card_print_ids_after=survivors,
            conflict=conflict,
            inside_best=inside_best,
            outside_best=outside_best,
            outside_best_prints=outside_prints,
            class_spans_boundary=spans,
        )

    if veto_on_class_span and spans:
        return veto(CONFLICT_CLASS_SPANS_SURVIVORS)

    if outside_best is not None and inside_best is not None:
        if outside_best < inside_best:
            return veto(CONFLICT_STRONGER_OUTSIDE)
        if outside_best == inside_best:
            return veto(CONFLICT_EQUIVALENT_OUTSIDE)
        if outside_best - inside_best < competitive_margin:
            return veto(CONFLICT_COMPETITIVE_OUTSIDE)

    return GuardedArtworkVerdict(
        outcome=OUTCOME_NARROW,
        survivor_verdict=survivor_verdict,
        global_verdict=global_verdict,
        card_print_ids_after=survivor_verdict.card_print_ids_after,
        inside_best=inside_best,
        outside_best=outside_best,
        outside_best_prints=outside_prints,
        class_spans_boundary=spans,
        detail=f"global artwork agrees with the survivor set on print {chosen}",
    )


def evaluate_with_contradiction_guard(
    listing_bytes: bytes | None,
    survivor_official: dict[int, bytes],
    global_official: dict[int, bytes],
    *,
    artwork_keys: dict[int, str] | None = None,
    accept_max: int = ARTWORK_ACCEPT_MAX,
    margin_min: int = ARTWORK_MARGIN_MIN,
    competitive_margin: int = CONTRADICTION_COMPETITIVE_MARGIN,
    veto_on_class_span: bool = False,
) -> GuardedArtworkVerdict:
    """Score the listing over the survivor set and over the whole card-code
    field, then apply the guard.

    `global_official` must be a superset of `survivor_official` - it is the
    card code's whole sibling set, including the prints product evidence
    excluded. Passing the survivor set for both reduces this to today's
    behaviour exactly.
    """
    keys = artwork_keys or {}
    survivor_verdict = evaluate_artwork(
        listing_bytes, survivor_official, artwork_keys=keys,
        accept_max=accept_max, margin_min=margin_min,
    )
    global_verdict = evaluate_artwork(
        listing_bytes, global_official, artwork_keys=keys,
        accept_max=accept_max, margin_min=margin_min,
    )
    return apply_contradiction_guard(
        survivor_verdict, global_verdict, list(survivor_official), keys,
        competitive_margin=competitive_margin,
        veto_on_class_span=veto_on_class_span,
    )
