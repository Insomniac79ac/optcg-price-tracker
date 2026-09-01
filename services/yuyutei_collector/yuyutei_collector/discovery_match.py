"""What Atlas can say about a discovered product from its card code alone.

THIS MODULE CLASSIFIES. IT NEVER MATCHES. It reads canonical_cards and
card_prints and returns a cardinality statement. It creates no
source_card_mappings row, writes no price_observations row, approves nothing,
and imports none of the modules that could - see the import list above, which
is the whole proof.

THE ONLY INPUTS ARE THE EXACT PARSED CARD CODE AND HOW MANY OWN-SERIES SOURCE
PRODUCTS CARRY IT. Not the rarity token, not the JP name, not the (パラレル)
annotation, not the artwork, not a fuzzy name score, not "the first one" and
not a representative printing. Those are all real evidence and they are all
preserved on the candidate, but turning any of them into a print decision here
would be the guess this design exists to refuse.

print_matched THEREFORE REQUIRES 1:1 ON BOTH SIDES. One own-series Yuyu-Tei
product with the code, and one active Atlas card_print in its canonical family.
Either side being plural makes the code a statement about the family and not
about a printing: two source products (base and parallel, say) against one
active print would otherwise both claim that print, which is a stronger claim
than the code can support. When either side is plural the honest answer is
"the family, not the print", and that is what it returns.

THE SOURCE-SIDE COUNT MUST COME FROM THE COMPLETE OWN-SERIES LISTING for the
slug. A partial listing under-counts and would let a pair look like a single;
foreign-series cross-links over-count and would suppress a legitimate 1:1. The
caller owns that measurement - see discovery.enumerate_slug - and there is no
default here, so a caller that has not made it cannot accidentally assert 1.

A TRUNCATED LISTING PROVES NOTHING ABOUT SOURCE UNIQUENESS, so it fails closed.
When a product or page cap stopped the enumeration, the observed count is a
floor and the parallel that would have made it a pair may simply be on the page
that was never fetched. `source_listing_complete` carries that fact explicitly,
because it cannot be recovered from the count: one observed product is what a
genuinely single-product code and a truncated pair both look like.

FAIL CLOSED ON UNPROVABLE IDENTITY. card_code is UNIQUE in canonical_cards. If
the catalogue ever returns two rows for one code, its own identity invariant
is broken, and no classification built on it can be trusted - so the result is
identity_conflict with no print id, never a pick from the two.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from yuyutei_collector.models import CanonicalCard, CardPrint

# See app.models.yuyutei_candidate.MATCH_STATUSES for the full vocabulary.
UNMATCHED = "unmatched"
FAMILY_MATCHED = "family_matched"
PRINT_MATCHED = "print_matched"
IDENTITY_CONFLICT = "identity_conflict"


@dataclass(frozen=True)
class MatchClassification:
    match_status: str
    matched_card_print_id: int | None
    explanation: dict[str, Any]


def classify_card_code(
    session: Session,
    card_code: str | None,
    *,
    source_product_count: int,
    source_listing_complete: bool,
) -> MatchClassification:
    """Cardinality of `card_code`, on both sides, as a candidate status.

    `source_product_count` is how many own-series products in the SAME
    discovery listing carry this exact card code - 1 for a code that appears
    once, 2 for a base/parallel pair, and so on. `source_listing_complete` says
    whether that listing was read to the end; when it is False the count is a
    floor and source-side uniqueness is unproven. Both are keyword-only and
    neither has a default, because assuming "one product, whole listing" is
    exactly the over-claim this function exists to prevent.

    A print id is returned in exactly one case: a canonical card exists, the
    source listing was complete, this is the only own-series source product in
    it carrying the code, and exactly one ACTIVE card_print carries the
    canonical identity. Then the code implies that print with no judgement
    applied. Every other case returns None."""
    if not card_code:
        return MatchClassification(
            UNMATCHED, None, {"reason": "no_card_code_parsed", "card_code": None}
        )

    canonical_cards = (
        session.scalars(select(CanonicalCard).where(CanonicalCard.card_code == card_code))
        .unique()
        .all()
    )
    if not canonical_cards:
        return MatchClassification(
            UNMATCHED, None, {"reason": "no_canonical_card", "card_code": card_code}
        )
    if len(canonical_cards) > 1:
        # uq_canonical_cards_card_code says this cannot happen. If it does,
        # canonical identity is unprovable and discovery refuses to choose.
        return MatchClassification(
            IDENTITY_CONFLICT,
            None,
            {
                "reason": "canonical_card_code_not_unique",
                "card_code": card_code,
                "canonical_card_ids": sorted(card.id for card in canonical_cards),
            },
        )

    canonical = canonical_cards[0]
    print_ids = sorted(
        session.scalars(
            select(CardPrint.id).where(
                CardPrint.canonical_card_id == canonical.id,
                CardPrint.is_active.is_(True),
            )
        ).all()
    )
    base: dict[str, Any] = {
        "card_code": card_code,
        "canonical_card_id": canonical.id,
        "active_print_count": len(print_ids),
        "source_product_count": source_product_count,
        "source_listing_complete": source_listing_complete,
    }

    if print_ids:
        source_is_plural = source_product_count > 1
        prints_are_plural = len(print_ids) > 1
        # Unique is not the same as observed-once: only a complete listing can
        # say the sibling does not exist rather than was not looked at.
        source_is_unique = source_listing_complete and not source_is_plural
        if source_is_unique and not prints_are_plural:
            return MatchClassification(
                PRINT_MATCHED,
                print_ids[0],
                {**base, "reason": "unique_source_product_and_active_print"},
            )
        if source_is_plural and prints_are_plural:
            reason = "multiple_source_products_and_active_prints"
        elif prints_are_plural:
            reason = "multiple_active_prints"
        elif not source_is_plural:
            # Observed once in a listing that stopped early. The count is a
            # floor, so it is not evidence of uniqueness at all.
            reason = "source_listing_truncated"
        else:
            # One active print, several source products for the code: base and
            # parallel are distinct products and cannot both be that print.
            reason = "multiple_source_products"
        # The candidate print ids are recorded so a human reviewer can see the
        # whole choice they are being asked to make. Recording them is not
        # choosing one: matched_card_print_id stays NULL, and the
        # ck_yuyutei_candidates_print_requires_print_matched constraint stops
        # any later code from quietly filling it in.
        return MatchClassification(
            FAMILY_MATCHED,
            None,
            {**base, "reason": reason, "candidate_card_print_ids": print_ids},
        )
    # The family is known; no active printing exists to attach to. That is not
    # "no family", so it is not unmatched - it is a family with no exact print.
    return MatchClassification(
        FAMILY_MATCHED, None, {**base, "reason": "canonical_card_without_active_prints"}
    )
