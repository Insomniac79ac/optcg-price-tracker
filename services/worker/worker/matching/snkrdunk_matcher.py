"""Matches SNKRDUNK discovery candidates against the canonical `cards` table.

Match priority (first tier that yields exactly one unambiguous card wins):
  1. Exact card_code match.
  2. Exact Japanese card name + set_code.
  3. Japanese card name + rarity + variant.
  4. Fuzzy title match (advisory only, always needs_review).

Only tiers 1 and 2 are eligible to auto-match, and only when the resulting
confidence is at or above the configured threshold. Graded cards (PSA/BGS/ARS
in the listing's condition label) are never auto-matched, since
source_card_mappings has no separate slot for grading/condition.
"""

import difflib
import re
from dataclasses import dataclass
from typing import Protocol

from worker.matching.opcg_normalizer import normalize_title

TIER1_CARD_CODE_CONFIDENCE = 0.98
TIER2_NAME_SET_CONFIDENCE = 0.93
TIER3_NAME_RARITY_VARIANT_CONFIDENCE = 0.85
TIER4_FUZZY_MIN_RATIO = 0.5

AUTO_MATCH_ELIGIBLE_TIERS = (1, 2)

# \b doesn't help after the grader prefix since a trailing grade number
# (e.g. "PSA10") is still a word character, so match on a lookahead instead.
GRADED_CONDITION_RE = re.compile(r"\b(PSA|BGS|ARS)(?=\d|\s|$)", re.IGNORECASE)


class CardLike(Protocol):
    id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None


class CandidateLike(Protocol):
    normalized_title: str | None
    detected_card_code: str | None
    detected_set_code: str | None
    detected_rarity: str | None
    detected_variant: str | None
    condition_label: str | None


@dataclass
class MatchResult:
    matched_card_id: int | None
    match_confidence: float | None
    match_status: str
    reason: str


def is_graded_condition(condition_label: str | None) -> bool:
    return bool(condition_label and GRADED_CONDITION_RE.search(condition_label))


def _name_in_title(card: CardLike, title: str) -> bool:
    if not card.name_jp:
        return False
    return normalize_title(card.name_jp) in title


def match_candidate(
    candidate: CandidateLike,
    cards: list[CardLike],
    auto_match_threshold: float = 0.92,
) -> MatchResult:
    title = normalize_title(candidate.normalized_title)
    graded = is_graded_condition(candidate.condition_label)

    # Tier 1: exact card_code.
    if candidate.detected_card_code:
        matches = [c for c in cards if c.card_code == candidate.detected_card_code]
        if len(matches) == 1:
            return _finalize(matches[0], TIER1_CARD_CODE_CONFIDENCE, 1, graded, auto_match_threshold, "exact card_code match")
        if len(matches) > 1:
            return MatchResult(None, None, "ambiguous", "ambiguous card_code match")

    # Tier 2: Japanese name + set_code.
    if candidate.detected_set_code and title:
        matches = [
            c for c in cards
            if c.set_code == candidate.detected_set_code and _name_in_title(c, title)
        ]
        if len(matches) == 1:
            return _finalize(matches[0], TIER2_NAME_SET_CONFIDENCE, 2, graded, auto_match_threshold, "name_jp + set_code match")

    # Tier 3: Japanese name + rarity + variant (advisory only).
    if candidate.detected_rarity and title:
        matches = [
            c for c in cards
            if c.rarity == candidate.detected_rarity
            and (c.variant or None) == (candidate.detected_variant or None)
            and _name_in_title(c, title)
        ]
        if len(matches) == 1:
            return _finalize(
                matches[0], TIER3_NAME_RARITY_VARIANT_CONFIDENCE, 3, graded, auto_match_threshold,
                "name_jp + rarity + variant match",
            )

    # Tier 4: fuzzy title match (advisory only).
    best_card = None
    best_ratio = 0.0
    for card in cards:
        for label in (card.name_jp, card.name_en):
            if not label:
                continue
            ratio = difflib.SequenceMatcher(None, normalize_title(label), title).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_card = card

    if best_card is not None and best_ratio >= TIER4_FUZZY_MIN_RATIO:
        return _finalize(best_card, round(best_ratio, 2), 4, graded, auto_match_threshold, "fuzzy title match (advisory)")

    return MatchResult(None, None, "unmatched", "no candidate match found")


def _finalize(
    card: CardLike,
    confidence: float,
    tier: int,
    graded: bool,
    auto_match_threshold: float,
    reason: str,
) -> MatchResult:
    auto_eligible = (
        tier in AUTO_MATCH_ELIGIBLE_TIERS
        and confidence >= auto_match_threshold
        and not graded
    )
    if auto_eligible:
        return MatchResult(card.id, confidence, "matched", reason)

    if graded:
        reason = f"{reason} (graded condition, never auto-matched)"
    return MatchResult(card.id, confidence, "suggested", reason)
