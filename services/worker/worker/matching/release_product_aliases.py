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

EVIDENCE STANDARD for adding a row. The label must match, on the normalised
whole title, a product title **Bandai itself publishes**, and that title must
carry the product code in brackets. Two frozen official catalogues under
`data/official_snapshots/` supply those titles: `bandai_jp` publishes the
Japanese name ("ブースターパック ROMANCE DAWN【OP-01】") and `bandai_asia_en`
publishes Bandai's own Latin name for the same product ("BOOSTER PACK
-ROMANCE DAWN- [OP-01]"). Either is authority. A title someone translated or
paraphrased is not, and neither is a Latin fragment that merely happens to sit
inside a Japanese name.

Three checks, all of which must pass, and all of which are re-run by the tests:

  1. The normalised label equals a published catalogue title exactly - the
     whole title, code brackets removed. Not a substring of one.
  2. That normalised title is unique across BOTH catalogues, so the label
     names one product and could not have named another. (Normalising the JP
     titles alone is not safe: stripping non-Latin characters collapses
     "スタートデッキ 紫 モンキー・D・ルフィ【ST-18】" to "D", which four
     different starter decks share. Uniqueness is checked on the full set.)
  3. When the evidence comes from the Asia-EN catalogue, the JP and EN
     products under that code are shown to be the same product by their
     CONTENTS - identical card-code membership - not by the code agreeing.
     Codes are catalogue-scoped and the two catalogues do disagree about
     which products exist; membership is what settles identity.

WHY A LABEL CAN FAIL THIS EVEN WHEN ITS MEANING IS OBVIOUS. Bandai does not
publish every retail product as a coded series. The JP catalogue collects the
uncoded ones into three buckets - 限定商品収録カード (Limited Product Card),
プロモーションカード (Promotion card), ファミリーデッキセット - whose entries
carry `product_code: null` and which Atlas therefore holds no ReleaseProduct
for. A label naming one of those has nothing to resolve TO, and no amount of
confidence about what it means changes that. It stays unresolved. Section
"REFUSED LABELS" below records the ones already investigated so they are not
re-litigated.

REFUSED LABELS, and why - so the next reader does not re-derive them. All
three were investigated against the frozen catalogues on 2026-08-27.

  "Premium Card Collection 25th Anniversary Edition"
      Bandai publishes プレミアムカードコレクション 25周年エディション as a
      `product_names` value on entries in series 550801 限定商品収録カード,
      with `product_code: null`. It is one of FIFTEEN members of the
      プレミアムカードコレクション line in that same uncoded bucket (others
      include -ONE PIECE FILM RED-, -ベストセレクション vol.1..6-,
      -Live Action Edition-). The label does pick out exactly one of them, but
      there is no coded Bandai series and therefore no Atlas ReleaseProduct to
      resolve to. Refused for want of a target, not for want of clarity.

  "Weekly Shonen Jump 2024 Issue 3 All Applicants Service Recafig"
  "Weekly Shonen Jump 2023 6th and 7th issue All applicants service Recafig"
      A mail-in premium (応募者全員サービス), i.e. a distribution channel, not
      a product. Bandai files these under 限定商品収録カード (550801, as
      週刊少年ジャンプ応募者全員サービス) and プロモーションカード (550901, as
      several separately dated 週刊少年ジャンプ...応募者全員サービス names),
      all with `product_code: null`. One SNKRDUNK label can therefore span two
      uncoded buckets. Nothing to resolve to.

GROWING THE TABLE. Discovery records every label it could not resolve
(`unresolved_product_labels` on the run summary) so the gaps are visible and
can be added with evidence, rather than guessed at parse time.
"""

from __future__ import annotations

import re

# label (normalised) -> (release_product_code, evidence)
#
# Only entries that pass all three checks in EVIDENCE STANDARD above. The
# evidence string names the published Bandai title(s) and the frozen catalogue
# series they came from, so a later reader can re-check the row rather than
# take it on trust.
_ALIASES: dict[str, tuple[str, str]] = {
    "BOOSTERPACKROMANCEDAWN": (
        "OP-01",
        "Bandai publishes this product as 'BOOSTER PACK -ROMANCE DAWN- [OP-01]' "
        "(bandai_asia_en series 556101) and 'ブースターパック ROMANCE DAWN【OP-01】' "
        "(bandai_jp series 550101); the label equals the Latin title exactly once "
        "normalised, and no other catalogue title normalises to it. Atlas "
        "release_products.display_name for OP-01 is the JP title.",
    ),
    "EXTRABOOSTERMEMORIALCOLLECTION": (
        "EB-01",
        "Bandai publishes this product as 'EXTRA BOOSTER -Memorial Collection- "
        "[EB-01]' (bandai_asia_en series 556201); the label equals that Latin "
        "title exactly once normalised, and it is the only title in either frozen "
        "catalogue that normalises to it ('Memorial' occurs in exactly one series "
        "title across both). JP series 550201 "
        "'エクストラブースター メモリアルコレクション【EB-01】' is the same product, "
        "proven by contents rather than by the shared code: both series list an "
        "identical set of 61 card codes, including the EB01-048 and EB01-055 seen "
        "in discovery run 1. Atlas ReleaseProduct EB-01 carries the JP title and "
        "source_series_id 550201.",
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
