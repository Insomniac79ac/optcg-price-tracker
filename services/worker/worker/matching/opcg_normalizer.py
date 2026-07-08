"""Best-effort extraction of One Piece Card Game identifiers from free-text
listing titles (e.g. SNKRDUNK candidate titles). Used to narrow down
candidate-to-card matching; never treated as authoritative on its own.
"""

import re
import unicodedata

CARD_CODE_RE = re.compile(r"\b([A-Z]{1,5}\d{0,2}-\d{3,4})\b")
SET_BRACKET_RE = re.compile(r"[\[\(]([A-Z]{1,4}\d{0,2})[\]\)]")

# Ordered longest-first so multi-letter codes (e.g. "SEC") aren't shadowed by
# a shorter prefix match (e.g. "SP").
KNOWN_RARITIES = ("SEC", "SR", "SP", "UC", "L", "R", "C", "P")

VARIANT_KEYWORDS = {
    "パラレル": "parallel",
    "アートパラレル": "art_parallel",
    "マンガ": "manga",
    "漫画": "manga",
    "アルティメット": "ultimate",
    "parallel": "parallel",
}


def normalize_title(text: str | None) -> str:
    """Collapse full/half-width variants and stray whitespace for matching."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", normalized).strip()


def extract_card_code(text: str | None) -> str | None:
    if not text:
        return None
    match = CARD_CODE_RE.search(text.upper())
    return match.group(1) if match else None


def extract_set_code(text: str | None, card_code: str | None = None) -> str | None:
    if card_code and "-" in card_code:
        return card_code.split("-", 1)[0]
    if not text:
        return None
    match = SET_BRACKET_RE.search(text.upper())
    return match.group(1) if match else None


def extract_rarity(text: str | None) -> str | None:
    if not text:
        return None
    tokens = set(re.findall(r"[A-Za-z]+", text.upper()))
    for rarity in KNOWN_RARITIES:
        if rarity in tokens:
            return rarity
    return None


def extract_variant(text: str | None) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    for keyword, variant in VARIANT_KEYWORDS.items():
        if keyword.lower() in lowered:
            return variant
    return None
