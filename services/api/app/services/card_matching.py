"""Deterministic candidate-to-card matching for source listings (SNKRDUNK
candidates today; reusable for Yuyu-Tei whenever a similar candidate flow
exists - see the module docstring note at the bottom) - see GET/POST
/admin/snkrdunk-candidates/*.

Distinct from worker.matching.snkrdunk_matcher, which the worker's own
import/discovery jobs already use to set a freshly-created candidate's
initial matched_card_id/match_confidence/match_status at ingest time (a
separate, pre-existing, lower-signal tiered matcher on a 0.0-1.0 scale).
This module does not replace or call into that - the api and worker
services share no code (see worker/models.py's own "no shared code with the
api service" convention). This module is the richer, metadata-aware scorer
behind the *admin review* tools (GET .../matches, POST .../rematch, POST
.../rematch-all) - explicitly triggered, on a 0-100 scale, and never on its
own creates or updates a source_card_mappings row (see
app.api.admin_snkrdunk_matching's approve-match endpoint for the only place
that happens, and only for a human-selected card).

No AI/LLM anywhere in this module - every signal below is a fixed,
deterministic point value applied to fields already stored on the candidate
and the canonical card. Nothing here fabricates a detection: extract_*/
detect_* only ever return a value they can point to in the source text.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Card, SnkrdunkCandidate
from app.services.card_catalog_import import VARIANT_SYNONYMS

CARD_CODE_RE = re.compile(r"\b([A-Z]{1,5}\d{0,2}-\d{3,4})\b")
SET_CODE_FROM_CARD_CODE_RE = re.compile(r"\b([A-Z]{1,5}\d{0,2})-\d{3,4}\b")
SET_BRACKET_RE = re.compile(r"[\[(]([A-Z]{1,5}\d{0,2})[\])]")
JAPANESE_CHAR_RE = re.compile(r"[぀-ヿ一-鿿]")
LATIN_LETTER_RE = re.compile(r"[A-Za-z]")

# (minimum score, label) pairs, checked highest-first.
CONFIDENCE_LABEL_THRESHOLDS = (
    (90, "exact"),
    (75, "high"),
    (55, "medium"),
    (35, "low"),
    (0, "very_low"),
)

# "If multiple cards tie within 5 points, mark as ambiguous."
AMBIGUOUS_TIE_MARGIN = 5

MIN_SCORE = 0
MAX_SCORE = 100

# match_status thresholds for rank_candidate_matches' caller (see
# app.api.admin_snkrdunk_matching) - kept here, next to the scoring they're
# derived from, rather than duplicated at each call site.
SUGGESTED_SCORE_THRESHOLD = 75
UNMATCHED_SCORE_THRESHOLD = 55


def confidence_label(score: int) -> str:
    for threshold, label in CONFIDENCE_LABEL_THRESHOLDS:
        if score >= threshold:
            return label
    return "very_low"


def normalize_text(value: str | None) -> str:
    """Collapses full/half-width variants and stray whitespace, lowercased -
    the shared baseline every text-signal comparison below runs on."""
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip().lower()


def normalize_card_code(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", "", value.strip().upper())
    return cleaned or None


def extract_card_code(text: str | None) -> str | None:
    if not text:
        return None
    match = CARD_CODE_RE.search(text.upper())
    return match.group(1) if match else None


def extract_set_code(text: str | None) -> str | None:
    """Prefers the set_code implied by a card_code found in the text (e.g.
    "OP01-001" -> "OP01"); falls back to a bracketed set label (e.g.
    "[OP01]")."""
    if not text:
        return None
    upper = text.upper()
    match = SET_CODE_FROM_CARD_CODE_RE.search(upper)
    if match:
        return match.group(1)
    match = SET_BRACKET_RE.search(upper)
    return match.group(1) if match else None


# Japanese variant keywords commonly seen in real SNKRDUNK listing titles -
# not part of app.services.card_catalog_import.VARIANT_SYNONYMS (which is
# scoped to the English/romanized input a human types into a CSV import),
# so kept here alongside the synonyms this function also recognizes.
JAPANESE_VARIANT_KEYWORDS = {
    "パラレル": "parallel",
    "アートパラレル": "alt_art",
    "マンガ": "manga",
    "漫画": "manga",
    "スペシャル": "sp",
    "リーダーパラレル": "leader_parallel",
}

_ALL_VARIANT_KEYWORDS: dict[str, str] = {**VARIANT_SYNONYMS, **JAPANESE_VARIANT_KEYWORDS}
# Longest keyword first, so e.g. "leader_parallel"/"リーダーパラレル" isn't
# shadowed by "leader"/"parallel" matching first.
_SORTED_VARIANT_KEYWORDS = sorted(_ALL_VARIANT_KEYWORDS, key=len, reverse=True)


def detect_variant(text: str | None) -> str | None:
    """Known synonyms only (English/romanized from
    app.services.card_catalog_import.VARIANT_SYNONYMS, plus common Japanese
    listing keywords) - anything else is left undetected rather than
    guessed."""
    if not text:
        return None
    lowered = normalize_text(text)
    for keyword in _SORTED_VARIANT_KEYWORDS:
        if keyword.lower() in lowered:
            return _ALL_VARIANT_KEYWORDS[keyword]
    return None


def _detect_language(text: str) -> str | None:
    """Best-effort, coarse language detection over already-normalized text -
    only ever "jp"/"en"/None (undetectable), never guessed beyond what's
    literally present."""
    if JAPANESE_CHAR_RE.search(text):
        return "jp"
    if LATIN_LETTER_RE.search(text):
        return "en"
    return None


@dataclass
class MatchExplanation:
    positive: list[str] = field(default_factory=list)
    negative: list[str] = field(default_factory=list)
    caps_applied: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"positive": self.positive, "negative": self.negative, "caps_applied": self.caps_applied}


@dataclass
class CandidateMatchResult:
    card_id: int
    card_code: str
    name_en: str | None
    name_jp: str | None
    set_code: str
    rarity: str
    variant: str | None
    score: int
    exact_card_code_match: bool
    explanation: MatchExplanation
    ambiguous: bool = False

    @property
    def confidence_label(self) -> str:
        return confidence_label(self.score)

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "card_code": self.card_code,
            "name_en": self.name_en,
            "name_jp": self.name_jp,
            "set_code": self.set_code,
            "rarity": self.rarity,
            "variant": self.variant,
            "score": self.score,
            "confidence_label": self.confidence_label,
            "ambiguous": self.ambiguous,
            "explanation": self.explanation.to_dict(),
        }


def _candidate_text_blob(candidate: SnkrdunkCandidate) -> str:
    parts = [candidate.title, candidate.normalized_title, candidate.raw_text]
    return normalize_text(" ".join(p for p in parts if p))


def _candidate_extracted_card_code(candidate: SnkrdunkCandidate) -> str | None:
    for source_text in (candidate.title, candidate.normalized_title, candidate.raw_text):
        code = extract_card_code(source_text)
        if code:
            return normalize_card_code(code)
    return None


def calculate_candidate_match(candidate: SnkrdunkCandidate, card: Card) -> CandidateMatchResult:
    """Scores one candidate/card pair, 0-100. See the module docstring for
    what this does and does not do; see the class docstring of
    MatchExplanation for how the result explains itself. `ambiguous` is
    always False here - only rank_candidate_matches (which compares a
    candidate against every card) can determine that, since it's a property
    of the *ranking*, not of a single pair."""
    positive: list[str] = []
    negative: list[str] = []
    caps_applied: list[str] = []
    score = 0

    text_blob = _candidate_text_blob(candidate)
    card_code_norm = normalize_card_code(card.card_code)

    detected_code_norm = normalize_card_code(candidate.detected_card_code)
    exact_card_code_match = detected_code_norm is not None and detected_code_norm == card_code_norm

    if exact_card_code_match:
        score += 60
        positive.append("exact card_code match")
    else:
        text_code_norm = _candidate_extracted_card_code(candidate)
        if text_code_norm is not None and text_code_norm == card_code_norm:
            score += 50
            positive.append("normalized card_code match from title/raw_text")

    candidate_set_code = candidate.detected_set_code or extract_set_code(text_blob)
    if candidate_set_code:
        if candidate_set_code.upper() == card.set_code.upper():
            score += 10
            positive.append("set_code match")
        else:
            score -= 25
            negative.append("set_code mismatch")

    if candidate.detected_rarity:
        if candidate.detected_rarity.upper() == card.rarity.upper():
            score += 5
            positive.append("rarity match")
        else:
            score -= 10
            negative.append("rarity mismatch")

    candidate_title_norm = normalize_text(candidate.normalized_title or candidate.title)

    name_en_norm = normalize_text(card.name_en)
    if name_en_norm:
        if candidate_title_norm and candidate_title_norm == name_en_norm:
            score += 25
            positive.append("exact name_en match")
        elif name_en_norm in text_blob:
            score += 10
            positive.append("partial name_en match")

    name_jp_norm = normalize_text(card.name_jp)
    if name_jp_norm:
        if candidate_title_norm and candidate_title_norm == name_jp_norm:
            score += 25
            positive.append("exact name_jp match")
        elif name_jp_norm in text_blob:
            score += 10
            positive.append("partial name_jp match")

    if card.character and normalize_text(card.character) in text_blob:
        score += 8
        positive.append("character match")

    candidate_variant = detect_variant(candidate.detected_variant) if candidate.detected_variant else None
    if candidate_variant is None:
        candidate_variant = detect_variant(text_blob)
    if candidate_variant is not None:
        card_variant_effective = normalize_text(card.variant) or "base"
        if candidate_variant == card_variant_effective:
            score += 12
            positive.append("variant match")
        else:
            score -= 20
            negative.append("variant mismatch")

    if card.card_type and normalize_text(card.card_type) in text_blob:
        score += 5
        positive.append("card_type match")

    if card.color and normalize_text(card.color) in text_blob:
        score += 3
        positive.append("color match")

    detected_language = _detect_language(text_blob)
    if detected_language is not None and card.language and detected_language != card.language:
        score -= 10
        negative.append("language mismatch")

    # "If set_code mismatch exists, do not allow score above 70 unless exact
    # card_code match exists."
    if "set_code mismatch" in negative and not exact_card_code_match and score > 70:
        score = 70
        caps_applied.append("set_code_mismatch_cap_70")

    # "If variant mismatch exists, do not allow score above 75."
    if "variant mismatch" in negative and score > 75:
        score = 75
        caps_applied.append("variant_mismatch_cap_75")

    score = max(MIN_SCORE, min(MAX_SCORE, score))

    return CandidateMatchResult(
        card_id=card.id,
        card_code=card.card_code,
        name_en=card.name_en,
        name_jp=card.name_jp,
        set_code=card.set_code,
        rarity=card.rarity,
        variant=card.variant,
        score=score,
        exact_card_code_match=exact_card_code_match,
        explanation=MatchExplanation(positive=positive, negative=negative, caps_applied=caps_applied),
    )


def explain_match(candidate: SnkrdunkCandidate, card: Card) -> dict:
    """Thin convenience wrapper around calculate_candidate_match for callers
    that only want the explanation, not the full scored result."""
    return calculate_candidate_match(candidate, card).explanation.to_dict()


def rank_candidate_matches(
    db: Session, candidate: SnkrdunkCandidate, limit: int = 10
) -> list[CandidateMatchResult]:
    """Scores `candidate` against every canonical card, ranks them, and
    flags the whole ranking as ambiguous when the top two are within
    AMBIGUOUS_TIE_MARGIN points of each other - unless the top result is an
    exact card_code match, which "should normally win" regardless of how
    close a lower-signal runner-up scores (see the module docstring).
    Zero/negative-score pairs are dropped entirely - not worth surfacing as
    a "match". Returns at most `limit` results, but ambiguity is decided
    from the full ranking first, before truncating."""
    cards = db.scalars(select(Card)).all()

    results = [calculate_candidate_match(candidate, card) for card in cards]
    results = [r for r in results if r.score > 0]
    results.sort(key=lambda r: (-r.score, r.card_code))

    ambiguous = (
        len(results) >= 2
        and not results[0].exact_card_code_match
        and (results[0].score - results[1].score) <= AMBIGUOUS_TIE_MARGIN
    )
    for r in results:
        r.ambiguous = ambiguous

    return results[:limit]
