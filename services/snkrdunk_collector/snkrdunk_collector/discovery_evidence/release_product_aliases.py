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

EVIDENCE SOURCE FOR ROWS ADDED ON OR AFTER 2026-11-03 (owner, perfectionist). The frozen
catalogues are not in the repository (gitignored, operator machine) and the frozen Asia-EN half
is gone. Rows for EB-02 to EB-04 and OP-05, OP-06, OP-08 to OP-17 are proven against a fresh
capture of both Bandai catalogues instead: ops-readonly `bandai-label-evidence` run 41626034881,
committed verbatim as docs/agent/evidence/bandai-label-evidence-20261103.json (both series
pickers, and per code the series ids, titles and card-code memberships). The three checks are
unchanged and are re-derived from that file by the worker's test_release_product_aliases_capture.
Only labels SNKRDUNK actually printed were added: OP-07 ("500 Yeas in the Future", "The Future
After 500 years") matches no Bandai title and stays unresolved here.

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
    "BOOSTERPACKPARAMOUNTWAR": (
        "OP-02",
        "Bandai publishes this product as 'BOOSTER PACK -Paramount War- [OP-02]' "
        "(bandai_asia_en series 556102); the label equals that Latin title exactly "
        "once normalised, and it is the only title in either frozen catalogue that "
        "normalises to it. JP series 550102 "
        "'ブースターパック 頂上決戦【OP-02】' is the same product, proven by contents "
        "rather than by the shared code: both catalogues list an identical set of "
        "121 card codes. Atlas ReleaseProduct OP-02 carries the JP title and "
        "source_series_id 550102. Distinct from the SNKRDUNK-only label 'Booster "
        "Pack Final Battle', which renders the JP subtitle 頂上決戦 and is resolved "
        "by contents in source_product_aliases - Bandai publishes no such title.",
    ),
    "BOOSTERPACKPILLARSOFSTRENGTH": (
        "OP-03",
        "Bandai publishes this product as 'BOOSTER PACK -Pillars of Strength- "
        "[OP-03]' (bandai_asia_en series 556103); the label equals that Latin title "
        "exactly once normalised - the case difference SNKRDUNK introduces ('Of' "
        "for 'of') is folded by normalise_label and is not a difference in fact - "
        "and it is the only title in either frozen catalogue that normalises to it. "
        "JP series 550103 'ブースターパック 強大な敵【OP-03】' is the same product, "
        "proven by contents: both catalogues list an identical set of 127 card "
        "codes, including the four reprints Bandai carries inside OP-03. Atlas "
        "ReleaseProduct OP-03 carries the JP title and source_series_id 550103.",
    ),
    "BOOSTERPACKKINGDOMSOFINTRIGUE": (
        "OP-04",
        "Bandai publishes this product as 'BOOSTER PACK -Kingdoms of Intrigue- "
        "[OP-04]' (bandai_asia_en series 556104); the label equals that Latin title "
        "exactly once normalised, and it is the only title in either frozen "
        "catalogue that normalises to it. JP series 550104 "
        "'ブースターパック 謀略の王国【OP-04】' is the same product, proven by "
        "contents: both catalogues list an identical set of 124 card codes, "
        "including the five reprints Bandai carries inside OP-04. Atlas "
        "ReleaseProduct OP-04 carries the JP title and source_series_id 550104.",
    ),
    "EXTRABOOSTERANIME25THCOLLECTION": (
        "EB-02",
        "Bandai publishes this product as 'EXTRA BOOSTER -Anime 25th collection- [EB-02]' "
        "(bandai_asia_en series 556202) and 'エクストラブースター Anime 25th collection【EB-02】' "
        "(bandai_jp series 550202); the label equals the Latin title exactly once normalised, "
        "and no other series title in either catalogue normalises to it. Same product in both "
        "catalogues by contents: both list the same 87 card codes (digest 6d780bc4a571). "
        "SNKRDUNK labels seen: Extra Booster \"Anime 25th Collection\". Evidence: ops-readonly "
        "bandai-label-evidence run 41626034881 (2026-11-03), committed as "
        "docs/agent/evidence/bandai-label-evidence-20261103.json."
    ),
    "EXTRABOOSTERONEPIECEHEROINESEDITION": (
        "EB-03",
        "Bandai publishes this product as 'EXTRA BOOSTER -ONE PIECE Heroines Edition- "
        "[EB-03]' (bandai_asia_en series 556203) and 'エクストラブースター ONE PIECE Heroines "
        "Edition【EB-03】' (bandai_jp series 550203); the label equals the Latin title exactly "
        "once normalised, and no other series title in either catalogue normalises to it. "
        "Same product in both catalogues by contents: both list the same 62 card codes "
        "(digest e662cbe0450c). SNKRDUNK labels seen: Extra Booster \"ONE PIECE Heroines "
        "edition\". Evidence: ops-readonly bandai-label-evidence run 41626034881 (2026-11-03), "
        "committed as docs/agent/evidence/bandai-label-evidence-20261103.json."
    ),
    "EXTRABOOSTEREGGHEADCRISIS": (
        "EB-04",
        "Bandai publishes this product as 'EXTRA BOOSTER -EGGHEAD CRISIS- [EB-04]' "
        "(bandai_asia_en series 556204) and 'エクストラブースター EGGHEAD CRISIS【EB-04】' (bandai_jp "
        "series 550204); the label equals the Latin title exactly once normalised, and no "
        "other series title in either catalogue normalises to it. Same product in both "
        "catalogues by contents: both list the same 65 card codes (digest 23318590aef2). "
        "SNKRDUNK labels seen: Extra Booster \"EGGHEAD CRISIS\". Evidence: ops-readonly "
        "bandai-label-evidence run 41626034881 (2026-11-03), committed as "
        "docs/agent/evidence/bandai-label-evidence-20261103.json."
    ),
    "BOOSTERPACKAWAKENINGOFTHENEWERA": (
        "OP-05",
        "Bandai publishes this product as 'BOOSTER PACK -Awakening of the New Era- [OP-05]' "
        "(bandai_asia_en series 556105) and 'ブースターパック 新時代の主役【OP-05】' (bandai_jp series "
        "550105); the label equals the Latin title exactly once normalised, and no other "
        "series title in either catalogue normalises to it. Same product in both catalogues "
        "by contents: both list the same 125 card codes (digest 6a66e5aa27ae). SNKRDUNK "
        "labels seen: Booster Pack Awakening of the New Era; Booster Pack \"Awakening Of The "
        "New Era\". Evidence: ops-readonly bandai-label-evidence run 41626034881 (2026-11-03), "
        "committed as docs/agent/evidence/bandai-label-evidence-20261103.json."
    ),
    "BOOSTERPACKWINGSOFCAPTAIN": (
        "OP-06",
        "Bandai publishes this product as 'BOOSTER PACK -Wings of Captain- [OP-06]' "
        "(bandai_asia_en series 556106) and 'ブースターパック 双璧の覇者【OP-06】' (bandai_jp series "
        "550106); the label equals the Latin title exactly once normalised, and no other "
        "series title in either catalogue normalises to it. Same product in both catalogues "
        "by contents: both list the same 125 card codes (digest 73963f559c79). SNKRDUNK "
        "labels seen: Booster Pack Wings of Captain. Evidence: ops-readonly "
        "bandai-label-evidence run 41626034881 (2026-11-03), committed as "
        "docs/agent/evidence/bandai-label-evidence-20261103.json."
    ),
    "BOOSTERPACKTWOLEGENDS": (
        "OP-08",
        "Bandai publishes this product as 'BOOSTER PACK -Two Legends- [OP-08]' "
        "(bandai_asia_en series 556108) and 'ブースターパック 二つの伝説【OP-08】' (bandai_jp series "
        "550108); the label equals the Latin title exactly once normalised, and no other "
        "series title in either catalogue normalises to it. Same product in both catalogues "
        "by contents: both list the same 125 card codes (digest 3298914af2f9). SNKRDUNK "
        "labels seen: Booster Pack \"Two Legends\". Evidence: ops-readonly "
        "bandai-label-evidence run 41626034881 (2026-11-03), committed as "
        "docs/agent/evidence/bandai-label-evidence-20261103.json."
    ),
    "BOOSTERPACKEMPERORSINTHENEWWORLD": (
        "OP-09",
        "Bandai publishes this product as 'BOOSTER PACK -Emperors in the New World- [OP-09]' "
        "(bandai_asia_en series 556109) and 'ブースターパック 新たなる皇帝【OP-09】' (bandai_jp series "
        "550109); the label equals the Latin title exactly once normalised, and no other "
        "series title in either catalogue normalises to it. Same product in both catalogues "
        "by contents: both list the same 126 card codes (digest a499dba59c41). SNKRDUNK "
        "labels seen: Booster Pack \"Emperors In The New World\". Evidence: ops-readonly "
        "bandai-label-evidence run 41626034881 (2026-11-03), committed as "
        "docs/agent/evidence/bandai-label-evidence-20261103.json."
    ),
    "BOOSTERPACKROYALBLOOD": (
        "OP-10",
        "Bandai publishes this product as 'BOOSTER PACK -Royal Blood- [OP-10]' "
        "(bandai_asia_en series 556110) and 'ブースターパック 王族の血統【OP-10】' (bandai_jp series "
        "550110); the label equals the Latin title exactly once normalised, and no other "
        "series title in either catalogue normalises to it. Same product in both catalogues "
        "by contents: both list the same 125 card codes (digest 94f044442b94). SNKRDUNK "
        "labels seen: Booster Pack \"Royal Blood\". Evidence: ops-readonly "
        "bandai-label-evidence run 41626034881 (2026-11-03), committed as "
        "docs/agent/evidence/bandai-label-evidence-20261103.json."
    ),
    "BOOSTERPACKAFISTOFDIVINESPEED": (
        "OP-11",
        "Bandai publishes this product as 'BOOSTER PACK -A Fist of Divine Speed- [OP-11]' "
        "(bandai_asia_en series 556111) and 'ブースターパック 神速の拳【OP-11】' (bandai_jp series 550111); "
        "the label equals the Latin title exactly once normalised, and no other series title "
        "in either catalogue normalises to it. Same product in both catalogues by contents: "
        "both list the same 126 card codes (digest 994470bd3511). SNKRDUNK labels seen: "
        "Booster Pack \"A Fist of Divine Speed\". Evidence: ops-readonly bandai-label-evidence "
        "run 41626034881 (2026-11-03), committed as "
        "docs/agent/evidence/bandai-label-evidence-20261103.json."
    ),
    "BOOSTERPACKLEGACYOFTHEMASTER": (
        "OP-12",
        "Bandai publishes this product as 'BOOSTER PACK -Legacy of the Master- [OP-12]' "
        "(bandai_asia_en series 556112) and 'ブースターパック 師弟の絆【OP-12】' (bandai_jp series 550112); "
        "the label equals the Latin title exactly once normalised, and no other series title "
        "in either catalogue normalises to it. Same product in both catalogues by contents: "
        "both list the same 126 card codes (digest bbabef1c87d0). SNKRDUNK labels seen: "
        "Booster Pack \"LEGACY OF THE MASTER\". Evidence: ops-readonly bandai-label-evidence "
        "run 41626034881 (2026-11-03), committed as "
        "docs/agent/evidence/bandai-label-evidence-20261103.json."
    ),
    "BOOSTERPACKCARRYINGONHISWILL": (
        "OP-13",
        "Bandai publishes this product as 'BOOSTER PACK -Carrying on His Will- [OP-13]' "
        "(bandai_asia_en series 556113) and 'ブースターパック 受け継がれる意志【OP-13】' (bandai_jp series "
        "550113); the label equals the Latin title exactly once normalised, and no other "
        "series title in either catalogue normalises to it. Same product in both catalogues "
        "by contents: both list the same 128 card codes (digest 2c5b3417b8a8). SNKRDUNK "
        "labels seen: Booster Pack \"CARRYING ON HIS WILL\". Evidence: ops-readonly "
        "bandai-label-evidence run 41626034881 (2026-11-03), committed as "
        "docs/agent/evidence/bandai-label-evidence-20261103.json."
    ),
    "BOOSTERPACKTHEAZURESEASSEVEN": (
        "OP-14",
        "Bandai publishes this product as 'BOOSTER PACK -The Azure Sea’s Seven- [OP-14]' "
        "(bandai_asia_en series 556114) and 'ブースターパック 蒼海の七傑【OP-14】' (bandai_jp series "
        "550114); the label equals the Latin title exactly once normalised, and no other "
        "series title in either catalogue normalises to it. Same product in both catalogues "
        "by contents: both list the same 126 card codes (digest 62ed9c25be88). SNKRDUNK "
        "labels seen: Booster Pack \"THE AZURE SEA'S SEVEN\". Evidence: ops-readonly "
        "bandai-label-evidence run 41626034881 (2026-11-03), committed as "
        "docs/agent/evidence/bandai-label-evidence-20261103.json."
    ),
    "BOOSTERPACKADVENTUREONKAMISISLAND": (
        "OP-15",
        "Bandai publishes this product as 'BOOSTER PACK -Adventure on KAMI’s Island- [OP-15]' "
        "(bandai_asia_en series 556115) and 'ブースターパック 神の島の冒険【OP-15】' (bandai_jp series "
        "550115); the label equals the Latin title exactly once normalised, and no other "
        "series title in either catalogue normalises to it. Same product in both catalogues "
        "by contents: both list the same 125 card codes (digest 784ca78afbbb). SNKRDUNK "
        "labels seen: Booster Pack \"Adventure on KAMI’s Island\". Evidence: ops-readonly "
        "bandai-label-evidence run 41626034881 (2026-11-03), committed as "
        "docs/agent/evidence/bandai-label-evidence-20261103.json."
    ),
    "BOOSTERPACKTHETIMEOFBATTLE": (
        "OP-16",
        "Bandai publishes this product as 'BOOSTER PACK -THE TIME OF BATTLE- [OP-16]' "
        "(bandai_asia_en series 556116) and 'ブースターパック 決戦の刻【OP-16】' (bandai_jp series 550116); "
        "the label equals the Latin title exactly once normalised, and no other series title "
        "in either catalogue normalises to it. Same product in both catalogues by contents: "
        "both list the same 125 card codes (digest 911c023ba31f). SNKRDUNK labels seen: "
        "Booster Pack \"THE TIME OF BATTLE\". Evidence: ops-readonly bandai-label-evidence run "
        "41626034881 (2026-11-03), committed as "
        "docs/agent/evidence/bandai-label-evidence-20261103.json."
    ),
    "BOOSTERPACKTHEWORLDSSTRONGESTWARRIORS": (
        "OP-17",
        "Bandai publishes this product as 'BOOSTER PACK -The World's Strongest Warriors- "
        "[OP-17]' (bandai_asia_en series 556117) and 'ブースターパック 世界最強の戦士【OP-17】' (bandai_jp "
        "series 550117); the label equals the Latin title exactly once normalised, and no "
        "other series title in either catalogue normalises to it. Same product in both "
        "catalogues by contents: both list the same 130 card codes (digest d20c368c334b). "
        "SNKRDUNK labels seen: Booster Pack \"THE WORLD’S STRONGEST WARRIORS\". Evidence: "
        "ops-readonly bandai-label-evidence run 41626034881 (2026-11-03), committed as "
        "docs/agent/evidence/bandai-label-evidence-20261103.json."
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
