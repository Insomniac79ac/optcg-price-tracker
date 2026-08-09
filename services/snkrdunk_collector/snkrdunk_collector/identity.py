"""Generic SNKRDUNK card-title identity parser: card_code + rarity +
"<rarity>-P" => parallel treatment. Moved out of
spikes/snkrdunk-browser-feasibility/spike.py's parse_card_identity, which
was built and offline-tested against real SNKRDUNK card titles (L-P/R-P/
SR-P/SEC-P all observed live for different cards on 2026-08-09 - see that
spike's tests/test_rarity_parser.py) - not special-cased to any one card.
"""

import re

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


def parse_card_identity(title: str) -> dict[str, str | None]:
    """Titles look like "<name> <rarity token> [<card_code>] (<release>)...".
    The rarity token is whatever whitespace-delimited run of text
    immediately precedes the "[card_code]" bracket (skipping any trailing
    ":"-prefixed descriptor tokens, e.g. "L :開封済"). "<RARITY>-P" means
    parallel treatment; a bare rarity token means normal treatment. Text
    anywhere else in the title (after the bracket, e.g. a set/box name) is
    never considered.

    Returns {"card_code": ..., "rarity": ..., "treatment": ...}, all None if
    the title doesn't contain a recognizable "[card_code]" bracket at all -
    fail closed, never guess.
    """
    code_match = CARD_CODE_IN_TITLE_RE.search(title or "")
    if not code_match:
        return {"card_code": None, "rarity": None, "treatment": None}

    card_code = code_match.group(1)
    prefix = title[: code_match.start()].strip()
    tokens = [t for t in prefix.split() if t]

    while tokens and (tokens[-1].startswith(":") or tokens[-1].startswith("：")):
        tokens.pop()

    if not tokens:
        return {"card_code": card_code, "rarity": None, "treatment": None}

    last_token = tokens[-1]

    parallel_match = RARITY_PARALLEL_TOKEN_RE.match(last_token)
    if parallel_match:
        return {"card_code": card_code, "rarity": parallel_match.group(1), "treatment": "parallel"}

    if BARE_RARITY_TOKEN_RE.match(last_token):
        return {"card_code": card_code, "rarity": last_token, "treatment": "normal"}

    return {"card_code": card_code, "rarity": None, "treatment": None}


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
