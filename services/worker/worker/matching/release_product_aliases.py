"""SNKRDUNK product labels -> Atlas release product codes, by exact evidence only.

THE PROBLEM. The exact-print gate narrows on `release_product_code` - the
product a printing actually shipped in. SNKRDUNK publishes an English
marketing label in the listing title ("Booster Pack ROMANCE DAWN"); Atlas
stores the Japanese published name plus the bracketed code
("ブースターパック ROMANCE DAWN【OP-01】"). Nothing joins them automatically,
and the 2026-08-27 feasibility sample resolved 0 of 30 labels.

WHY THE TABLE IS EXPLICIT AND SHORT. The obvious shortcut - substring or
closest-name matching - is wrong here in a way that produces confident errors.
"ONE PIECE" alone appears in the Atlas names of PRB-01, PRB-02, EB-03 and
ST-05; a containment match would pick whichever came first. A product is one
of the three dimensions the gate narrows on, so a wrong product does not make
an approval merely uncertain - it makes it wrong while looking corroborated.

So: an alias resolves only on EXACT equality of the normalised whole label,
against an entry someone has justified. Everything else returns None, and
None is a first-class answer meaning "this listing carries no product
evidence" - the gate then simply has one fewer dimension to narrow on, which
is exactly right.

EVIDENCE STANDARD for adding a row. The Latin-script product title must appear
verbatim in the Atlas `release_products.display_name`, whose bracketed 【code】
supplies the code. A translated or paraphrased title is NOT evidence:
"Extra Booster Memorial Collection" is a plausible rendering of
"エクストラブースター メモリアルコレクション【EB-01】", but plausible is the
standard this module exists to refuse. Such labels stay unresolved until
someone confirms them against the product itself.

GROWING THE TABLE. Discovery records every label it could not resolve
(`unresolved_product_labels` on the run summary) so the gaps are visible and
can be added with evidence, rather than guessed at parse time.
"""

from __future__ import annotations

import re

# label (normalised) -> (release_product_code, evidence)
#
# Only entries whose Latin-script title appears verbatim in the Atlas product
# name. The evidence string is the Atlas display_name that justifies the row.
_ALIASES: dict[str, tuple[str, str]] = {
    "BOOSTERPACKROMANCEDAWN": (
        "OP-01",
        "release_products.display_name = 'ブースターパック ROMANCE DAWN【OP-01】' - "
        "the Latin title 'ROMANCE DAWN' appears verbatim in both.",
    ),
}


def normalise_label(label: str | None) -> str | None:
    """Upper-case, with quotes/punctuation/whitespace removed.

    SNKRDUNK writes the same product as `Booster Pack ROMANCE DAWN` and
    `Booster Pack "ROMANCE DAWN"` interchangeably; the quoting is not a
    difference in fact. Nothing else is folded - no word dropping, no
    stemming - so two genuinely different products cannot collide here.
    """
    if not label:
        return None
    cleaned = re.sub(r"[^A-Z0-9]", "", label.upper())
    return cleaned or None


def resolve_product_code(label: str | None) -> str | None:
    """The Atlas release product code this label names, or None.

    None means "no product evidence", never "probably this one".
    """
    key = normalise_label(label)
    if key is None:
        return None
    entry = _ALIASES.get(key)
    return entry[0] if entry else None


def alias_evidence(label: str | None) -> str | None:
    """Why the alias for this label is believed, for audit output."""
    key = normalise_label(label)
    entry = _ALIASES.get(key) if key else None
    return entry[1] if entry else None


def known_aliases() -> dict[str, str]:
    """Every alias currently trusted, as {normalised label: product code}."""
    return {label: code for label, (code, _) in _ALIASES.items()}
