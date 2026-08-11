"""Generic SNKRDUNK card-title identity parser: card_name + card_code +
rarity + "<rarity>-P" => parallel treatment, plus the title's own release
parenthetical. Moved out of spikes/snkrdunk-browser-feasibility/spike.py's
parse_card_identity, which was built and offline-tested against real
SNKRDUNK card titles (L-P/R-P/SR-P/SEC-P all observed live for different
cards on 2026-08-09 - see that spike's tests/test_rarity_parser.py) - not
special-cased to any one card.
"""

import re
import unicodedata

# Card codes as they appear in a title's own "[...]" bracket. Observed live
# forms: "OP01-001", "ST29-008", "PRB02-006", "EB03-054", "P-159" - a
# letters(+digits) set prefix, a dash, then a 2-3 digit number.
CARD_CODE_IN_TITLE_RE = re.compile(r"\[([A-Z]{1,4}\d{0,2}-\d{2,3})\]")

# The rarity-token itself, scoped to the run of text between the card name
# and the "[card_code]" bracket (never searched blindly across the whole
# title/page) - see parse_card_identity. "<rarity>-P" is the site's generic
# parallel-print marker. Must NOT match a bare "P" (the standalone Promo
# rarity - no dash) or a superficially similar suffix like "-RSP" (a
# distinct "red comic parallel" marker seen live on OP13-118) - anchoring
# the regex to the full token boundaries (^...$) rather than a substring
# search rules both out.
RARITY_PARALLEL_TOKEN_RE = re.compile(r"^([A-Z]{1,4})-P$")

# A bare (non-parallel) rarity token: letters/digits only, no separators.
BARE_RARITY_TOKEN_RE = re.compile(r"^[A-Z0-9]{1,4}$")


# The release/box parenthetical that follows the "[card_code]" bracket in a
# product title, e.g. "... [OP01-001] (ブースターパックロマンスドーン)通販...".
# Both ASCII and fullwidth brackets are accepted because SNKRDUNK's own
# titles mix them; only the FIRST parenthetical after the card code is read,
# so trailing site boilerplate ("通販・買取・相場｜スニダン") is never picked up.
RELEASE_PARENTHETICAL_RE = re.compile(r"[（(]([^）)]+)[）)]")

# The set token embedded in a card code ("OP01-001" -> "OP01").
CARD_CODE_SET_TOKEN_RE = re.compile(r"^([A-Z]{1,4}\d{0,2})-\d{2,3}$")

# Splits a set token into its letter prefix and (optional) digits so it can
# be rendered in card_prints.release_product_code's own convention, which
# hyphenates the two ("OP01" -> "OP-01", "ST29" -> "ST-29", "P" -> "P").
SET_TOKEN_PARTS_RE = re.compile(r"^([A-Z]+)(\d*)$")


def normalize_card_name(name: str | None) -> str | None:
    """Compare-ready form of a Japanese card name: NFKC-folded (so fullwidth
    and halfwidth punctuation/latin compare equal) with all whitespace
    removed. Deliberately generic - it normalizes source formatting only and
    never rewrites, aliases or special-cases any individual card's name."""
    if name is None:
        return None
    folded = unicodedata.normalize("NFKC", name)
    return "".join(folded.split()) or None


# Generic product-category prefixes a storefront puts in front of the real
# release name. These are SOURCE FORMATTING, not part of any product's
# identity - Bandai's own page prints "ブースターパック 強大な敵【OP-03】" too.
# Strictly a category-word list: never extend it with an individual product
# name, which would silently alias one release to another.
RELEASE_TEXT_PREFIXES = (
    "ブースターパック",
    "スタートデッキ",
    "プロモーションカード",
    "エクストラブースター",
    "BOOSTER PACK",
    "START DECK",
)

# A trailing "【OP-01】"-style product-code bracket, in either bracket style.
RELEASE_CODE_BRACKET_RE = re.compile(r"[【\[(（][^】\])）]*[】\])）]")

# Punctuation/separators a storefront may put between the prefix and the name.
RELEASE_EDGE_CHARS = " \t　-–—­:：・/|,、。«»\"'「」『』"


def normalize_release_text(text: str | None) -> str | None:
    """Compare-ready form of a release name.

    Normalizes only generic source formatting: NFKC folding (fullwidth vs
    halfwidth), product-code brackets, a leading product-category prefix,
    surrounding punctuation, all whitespace, and letter case. It does NOT
    translate, transliterate or alias product names - "ロマンスドーン" does
    not become "ROMANCE DAWN", because those are different strings and only
    Bandai can attest that a rendering is official (see release_reference.py).
    """
    if text is None:
        return None

    folded = unicodedata.normalize("NFKC", text)
    folded = RELEASE_CODE_BRACKET_RE.sub(" ", folded)
    folded = folded.strip(RELEASE_EDGE_CHARS)

    # Strip at most one leading category prefix, longest first so that a
    # prefix which is itself a prefix of another can't shadow it.
    for prefix in sorted(RELEASE_TEXT_PREFIXES, key=len, reverse=True):
        normalized_prefix = unicodedata.normalize("NFKC", prefix).casefold()
        if folded.casefold().startswith(normalized_prefix):
            folded = folded[len(normalized_prefix):]
            break

    collapsed = "".join(folded.split()).strip(RELEASE_EDGE_CHARS)
    return collapsed.casefold() or None


def release_names_match(observed: str | None, official: str | None) -> bool:
    """True only when both normalize to the same non-empty string."""
    left = normalize_release_text(observed)
    right = normalize_release_text(official)
    return bool(left) and left == right


def set_token_from_card_code(card_code: str | None) -> str | None:
    """"OP01-001" -> "OP01". Returns None for anything not shaped like a card
    code, so a caller can never silently compare against a partial parse."""
    match = CARD_CODE_SET_TOKEN_RE.match((card_code or "").strip())
    return match.group(1) if match else None


def normalize_set_token_to_release_product_code(set_token: str | None) -> str | None:
    """Render a set token in card_prints.release_product_code's convention:
    letters, hyphen, digits ("OP01" -> "OP-01"). Purely structural - no
    per-set lookup table, so a set this collector has never seen normalizes
    correctly on its first encounter."""
    match = SET_TOKEN_PARTS_RE.match((set_token or "").strip().upper())
    if not match:
        return None
    letters, digits = match.group(1), match.group(2)
    return f"{letters}-{digits}" if digits else letters


def parse_release_text(title: str) -> str | None:
    """The release/box name SNKRDUNK prints in the parenthetical immediately
    after the "[card_code]" bracket, e.g. "ブースターパックロマンスドーン".
    Retained as observed evidence; see writer.py for how it is corroborated
    against the print's release_product_code."""
    code_match = CARD_CODE_IN_TITLE_RE.search(title or "")
    if not code_match:
        return None
    match = RELEASE_PARENTHETICAL_RE.search(title, code_match.end())
    if not match:
        return None
    return match.group(1).strip() or None


def parse_card_identity(title: str) -> dict[str, str | None]:
    """Titles look like "<name> <rarity token> [<card_code>] (<release>)...".
    The rarity token is whatever whitespace-delimited run of text
    immediately precedes the "[card_code]" bracket (skipping any trailing
    ":"-prefixed descriptor tokens, e.g. "L :開封済"); everything before it
    is the card name. "<RARITY>-P" means parallel treatment; a bare rarity
    token means normal treatment.

    Returns {"card_code", "rarity", "treatment", "name", "release_text"},
    with the identity fields all None if the title doesn't contain a
    recognizable "[card_code]" bracket at all - fail closed, never guess.
    """
    empty: dict[str, str | None] = {
        "card_code": None,
        "rarity": None,
        "treatment": None,
        "name": None,
        "release_text": None,
    }

    code_match = CARD_CODE_IN_TITLE_RE.search(title or "")
    if not code_match:
        return empty

    card_code = code_match.group(1)
    release_text = parse_release_text(title)
    prefix = title[: code_match.start()].strip()
    tokens = [t for t in prefix.split() if t]

    while tokens and (tokens[-1].startswith(":") or tokens[-1].startswith("：")):
        tokens.pop()

    base = {**empty, "card_code": card_code, "release_text": release_text}

    if not tokens:
        return base

    last_token = tokens[-1]
    name = " ".join(tokens[:-1]).strip() or None

    parallel_match = RARITY_PARALLEL_TOKEN_RE.match(last_token)
    if parallel_match:
        return {**base, "rarity": parallel_match.group(1), "treatment": "parallel", "name": name}

    if BARE_RARITY_TOKEN_RE.match(last_token):
        return {**base, "rarity": last_token, "treatment": "normal", "name": name}

    # No recognizable rarity token: the whole prefix is the name.
    return {**base, "name": " ".join(tokens).strip() or None}


HTML_LANG_RE = re.compile(r"<html[^>]*\blang=[\"']([a-zA-Z-]+)[\"']", re.IGNORECASE)


def parse_page_language(html: str) -> str | None:
    """The <html lang="..."> attribute - confirmed live to genuinely differ
    between SNKRDUNK's Japanese product pages (lang="ja",
    https://snkrdunk.com/apparels/{id}) and English mirror pages (lang="en",
    https://snkrdunk.com/en/trading-cards/{id}) for the *same* underlying
    product. Used to reject a foreign-language page from being accepted as
    evidence for a jp-language card_print (see writer.py)."""
    match = HTML_LANG_RE.search(html or "")
    if not match:
        return None
    return match.group(1).lower()
