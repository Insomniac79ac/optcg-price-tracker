"""A SOURCE's own product names -> Atlas release product codes, by contents.

WHY THIS IS A SEPARATE MODULE FROM release_product_aliases, and must stay one.

That module resolves a label only when the normalised label EQUALS a product
title Bandai itself publishes. That standard is not negotiable and is not
weakened here - it is the reason a "closest product" matcher can never reach
into the exact-print gate.

But it cannot express the case this module exists for. SNKRDUNK does not use
Bandai's English product names. It writes its own literal renderings of the
JAPANESE subtitles, and the two are simply different strings:

    SNKRDUNK label                          Bandai JP           Bandai Asia-EN
    Booster Pack Final Battle               頂上決戦【OP-02】      Paramount War
    Booster Pack Formidable Enemy           強大な敵【OP-03】      Pillars of Strength
    Booster Pack The Kingdom Of Conspiracy  謀略の王国【OP-04】     Kingdoms of Intrigue

No amount of care with strings closes that gap, and nothing SHOULD: a
translation is an inference, and this project does not infer product identity
from names. Widening the official table to admit these would be exactly the
weakening its docstring warns against.

WHAT IS USED AS EVIDENCE INSTEAD: CONTENTS. release_product_aliases' own rule 3
already settles product identity by card-code membership rather than by name
("proven by contents rather than by the shared code"). The same standard
applies here, and it is strictly stronger than a title match because it cannot
be satisfied by coincidence.

THE EVIDENCE STANDARD for a row in this table. All four must hold, and all four
are re-run by tests/test_source_product_aliases.py:

  1. The label does NOT resolve under the official table. Official always wins;
     this table is only ever consulted for what that one leaves unresolved.
  2. Every card code observed under the label, across the WHOLE discovered
     corpus, is a member of the proposed product's official membership - taken
     from the frozen Bandai catalogues, not from Atlas's own tables.
  3. That observed code set is contained by EXACTLY ONE Bandai product. If two
     products could both contain it, the label has not been identified and no
     row may be written.
  4. The JP and Asia-EN catalogues agree on that product's membership, so the
     set does not depend on which catalogue was read.

Measured on the 793-candidate corpus of 2026-08-30 (discovery runs 1-9), all
three rows below satisfy 1-4, and each label's observed code set turned out to
equal its product's official membership EXACTLY - 121, 127 and 124 codes, not a
subset. The nine foreign-prefix codes among them (OP01-051, ST01-012, ST03-009
and ST04-003 under OP-03; OP01-047, OP01-078, OP02-004, OP02-085 and OP02-099
under OP-04) are not anomalies: they are precisely the reprints Bandai itself
publishes inside those products, and their presence corroborates the
identification rather than undermining it.

THE RUNTIME GUARD, and why the membership is frozen into this file. A resolved
source alias is only honoured when the listing's OWN card code is a member of
that product. If SNKRDUNK ever prints a code under one of these labels that the
product does not contain, the label's meaning has drifted and the alias fails
CLOSED - it returns None, the listing carries no product evidence, and the
exact-print gate refuses it as unresolved. That is the same answer it gives
today, so a drift can only ever cost coverage, never correctness.

The membership is a literal here rather than a read of
`data/official_snapshots/`, for two reasons. The snapshots are gitignored
(~1GB) and are outside the worker image's build context, so they do not exist
at runtime. And the alias was justified against a SPECIFIC frozen catalogue, so
the guard must test against that same frozen evidence rather than against
something that can move underneath it.

WHAT THIS MODULE DELIBERATELY DOES NOT DO. No fuzzy matching, no substring
matching on either side, no stemming, no translation performed at runtime, and
no fallback that picks a "closest" product. The only comparison is equality of
the normalised whole label, against `release_product_aliases.normalise_label` -
imported rather than reimplemented, so the two tables can never come to
disagree about what a label is.
"""

from __future__ import annotations

from worker.matching.release_product_aliases import normalise_label, resolve_product_code

# source name -> normalised label -> (release_product_code, evidence)
#
# Only rows that pass all four checks in EVIDENCE STANDARD above. The evidence
# string records the contents proof so a later reader can re-check the row
# rather than take it on trust.
_SOURCE_ALIASES: dict[str, dict[str, tuple[str, str]]] = {
    "snkrdunk": {
        "BOOSTERPACKFINALBATTLE": (
            "OP-02",
            "SNKRDUNK's own rendering of the JP subtitle 頂上決戦 (Bandai JP series "
            "550102 'ブースターパック 頂上決戦【OP-02】'; Bandai's own Asia-EN name for "
            "the same product is 'Paramount War', so this label matches no published "
            "title and is unresolvable by name). Identified by contents: the 121 "
            "distinct card codes observed under this label across the 793-candidate "
            "corpus of 2026-08-30 are exactly OP-02's 121-code official membership, "
            "and OP-02 is the only Bandai product whose membership contains that set "
            "(next closest PRB-01, 11/121). JP and Asia-EN agree on the membership.",
        ),
        "BOOSTERPACKFORMIDABLEENEMY": (
            "OP-03",
            "SNKRDUNK's own rendering of the JP subtitle 強大な敵 (Bandai JP series "
            "550103 'ブースターパック 強大な敵【OP-03】'; Bandai's Asia-EN name is "
            "'Pillars of Strength'). Identified by contents: the 127 distinct card "
            "codes observed under this label are exactly OP-03's 127-code official "
            "membership - including the four reprints Bandai publishes inside OP-03 "
            "(OP01-051, ST01-012, ST03-009, ST04-003) - and OP-03 is the only product "
            "containing that set (next closest PRB-01, 17/127). JP and Asia-EN agree.",
        ),
        "BOOSTERPACKTHEKINGDOMOFCONSPIRACY": (
            "OP-04",
            "SNKRDUNK's own rendering of the JP subtitle 謀略の王国 (Bandai JP series "
            "550104 'ブースターパック 謀略の王国【OP-04】'; Bandai's Asia-EN name is "
            "'Kingdoms of Intrigue'). Identified by contents: the 124 distinct card "
            "codes observed under this label are exactly OP-04's 124-code official "
            "membership - including the five reprints Bandai publishes inside OP-04 "
            "(OP01-047, OP01-078, OP02-004, OP02-085, OP02-099) - and OP-04 is the "
            "only product containing that set (next closest PRB-01, 16/124). JP and "
            "Asia-EN agree.",
        ),
        "STARTDACKSBEASTSPIRATES": (
            "ST-04",
            "SNKRDUNK's own rendering of ST-04, whose Bandai JP title is "
            "'スタートデッキ 百獣海賊団【ST-04】' and whose Asia-EN title is "
            "'START DECK -Animal Kingdom Pirates- [ST-04]'. The label matches neither, "
            "and it additionally misspells 'Deck' as 'Dacks' - which is why it is "
            "resolved by CONTENTS and not by name: no typo correction, stemming or "
            "edit-distance step exists here or anywhere in this module, and adding one "
            "to reach this single row would create a general inference engine to solve "
            "a two-listing problem. Identified by contents: the 2 distinct card codes "
            "observed under this label across the 676-candidate corpus of 2026-08-30 "
            "(ST04-005, ST04-010) are both members of ST-04's 17-code official "
            "membership, and ST-04 is the only Bandai product in either frozen "
            "catalogue whose membership contains that set. JP series 550004 and Asia-EN "
            "series 556004 list an IDENTICAL 17-code membership, so check 4 holds "
            "without substitution. The observed set is a strict subset of the "
            "membership rather than equal to it, which the standard permits - checks 2 "
            "and 3 are containment and uniqueness, and equality was an observation "
            "about the three booster rows, never a requirement."
        ),
    },
}

# GENERATED FROZEN-CATALOGUE EVIDENCE - NOT HAND-MAINTAINED LOGIC.
#
# The frozen official membership of every product reachable through this table.
# Each set is a mechanical projection of the frozen Bandai catalogues - card_code
# grouped by product_code over entries.jsonl - so nothing below was decided, it
# was read. There is no judgement encoded here to maintain, and editing a code in
# or out by hand would silently widen or narrow what the runtime guard accepts
# while still looking like reviewed data. A genuine change belongs upstream in
# the catalogue snapshot, followed by a regeneration and a re-run of the
# re-derivation test named at the bottom of this comment.
#
# This is the guard's authority, not Atlas's own card_prints - a source alias is
# checked against what BANDAI says the product contains.
#
# PROVENANCE. Generated on 2026-08-30 from data/official_snapshots/:
#
#   bandai_jp       snapshot_version 1, captured 2026-08-22T14:32:15Z
#     entries.jsonl sha256
#       90cce5da668cc17cd5153269bb59fe46e70c34a6adf455928cf4b06f4443ed75
#
#   bandai_asia_en  snapshot_version 1, captured 2026-08-26T11:53:48Z
#     snapshot_identity
#       549f3a39281a3bf78f3299017e7134555244ff4edb6252d335e9d65b02199978
#     entries.jsonl sha256
#       40d23870573fc9ca65d134799757f3034c4155e23cd06a6634c47ed54c6f5f1e
#
# Both catalogues yield IDENTICAL sets for all four products - check 4 of the
# EVIDENCE STANDARD - so the literals do not depend on which one was read.
# (ST-04 was added 2026-08-30: JP series 550004 and Asia-EN series 556004, 17
# codes each, identical.)
#
# FINGERPRINTS of the generated sets, sha256 over the sorted codes joined by
# newlines, so a hand edit is detectable even where the catalogues are absent:
#
#   OP-02  121 codes
#     0ed0be31b537642d7ec3f5a49b144c3979b56aac71a505a002400cea5c20efb8
#   OP-03  127 codes
#     0598f64006f5240a3c6e865f083b855f524cddecd38ddc5e6c41cd4675019b44
#   OP-04  124 codes
#     725acc384a56ebe87c22c093a3310511d5235d381eaa2ded22b4097e61c36a10
#   ST-04   17 codes
#     110aa1e4da853d565215a1271ce4f0e461775cb8dd8e1bc5f9515c079b7da3c8
#
# REGENERATION IS VERIFIED, NOT TRUSTED. tests/test_source_product_aliases.py::
# test_frozen_membership_matches_the_catalogues re-derives every set below from
# BOTH catalogues and fails on any drift; it skips only where the snapshots are
# not checked out (gitignored, ~1GB), and the pinned sizes still run in CI.
_OFFICIAL_MEMBERSHIP: dict[str, frozenset[str]] = {
    "ST-04": frozenset({
        # 17 card codes.
        "ST04-001", "ST04-002", "ST04-003", "ST04-004", "ST04-005",
        "ST04-006", "ST04-007", "ST04-008", "ST04-009", "ST04-010",
        "ST04-011", "ST04-012", "ST04-013", "ST04-014", "ST04-015",
        "ST04-016", "ST04-017",
    }),
    "OP-02": frozenset({
        # 121 card codes.
        "OP02-001", "OP02-002", "OP02-003", "OP02-004", "OP02-005",
        "OP02-006", "OP02-007", "OP02-008", "OP02-009", "OP02-010",
        "OP02-011", "OP02-012", "OP02-013", "OP02-014", "OP02-015",
        "OP02-016", "OP02-017", "OP02-018", "OP02-019", "OP02-020",
        "OP02-021", "OP02-022", "OP02-023", "OP02-024", "OP02-025",
        "OP02-026", "OP02-027", "OP02-028", "OP02-029", "OP02-030",
        "OP02-031", "OP02-032", "OP02-033", "OP02-034", "OP02-035",
        "OP02-036", "OP02-037", "OP02-038", "OP02-039", "OP02-040",
        "OP02-041", "OP02-042", "OP02-043", "OP02-044", "OP02-045",
        "OP02-046", "OP02-047", "OP02-048", "OP02-049", "OP02-050",
        "OP02-051", "OP02-052", "OP02-053", "OP02-054", "OP02-055",
        "OP02-056", "OP02-057", "OP02-058", "OP02-059", "OP02-060",
        "OP02-061", "OP02-062", "OP02-063", "OP02-064", "OP02-065",
        "OP02-066", "OP02-067", "OP02-068", "OP02-069", "OP02-070",
        "OP02-071", "OP02-072", "OP02-073", "OP02-074", "OP02-075",
        "OP02-076", "OP02-077", "OP02-078", "OP02-079", "OP02-080",
        "OP02-081", "OP02-082", "OP02-083", "OP02-084", "OP02-085",
        "OP02-086", "OP02-087", "OP02-088", "OP02-089", "OP02-090",
        "OP02-091", "OP02-092", "OP02-093", "OP02-094", "OP02-095",
        "OP02-096", "OP02-097", "OP02-098", "OP02-099", "OP02-100",
        "OP02-101", "OP02-102", "OP02-103", "OP02-104", "OP02-105",
        "OP02-106", "OP02-107", "OP02-108", "OP02-109", "OP02-110",
        "OP02-111", "OP02-112", "OP02-113", "OP02-114", "OP02-115",
        "OP02-116", "OP02-117", "OP02-118", "OP02-119", "OP02-120",
        "OP02-121",
    }),
    "OP-03": frozenset({
        # 127 card codes.
        "OP01-051", "OP03-001", "OP03-002", "OP03-003", "OP03-004",
        "OP03-005", "OP03-006", "OP03-007", "OP03-008", "OP03-009",
        "OP03-010", "OP03-011", "OP03-012", "OP03-013", "OP03-014",
        "OP03-015", "OP03-016", "OP03-017", "OP03-018", "OP03-019",
        "OP03-020", "OP03-021", "OP03-022", "OP03-023", "OP03-024",
        "OP03-025", "OP03-026", "OP03-027", "OP03-028", "OP03-029",
        "OP03-030", "OP03-031", "OP03-032", "OP03-033", "OP03-034",
        "OP03-035", "OP03-036", "OP03-037", "OP03-038", "OP03-039",
        "OP03-040", "OP03-041", "OP03-042", "OP03-043", "OP03-044",
        "OP03-045", "OP03-046", "OP03-047", "OP03-048", "OP03-049",
        "OP03-050", "OP03-051", "OP03-052", "OP03-053", "OP03-054",
        "OP03-055", "OP03-056", "OP03-057", "OP03-058", "OP03-059",
        "OP03-060", "OP03-061", "OP03-062", "OP03-063", "OP03-064",
        "OP03-065", "OP03-066", "OP03-067", "OP03-068", "OP03-069",
        "OP03-070", "OP03-071", "OP03-072", "OP03-073", "OP03-074",
        "OP03-075", "OP03-076", "OP03-077", "OP03-078", "OP03-079",
        "OP03-080", "OP03-081", "OP03-082", "OP03-083", "OP03-084",
        "OP03-085", "OP03-086", "OP03-087", "OP03-088", "OP03-089",
        "OP03-090", "OP03-091", "OP03-092", "OP03-093", "OP03-094",
        "OP03-095", "OP03-096", "OP03-097", "OP03-098", "OP03-099",
        "OP03-100", "OP03-101", "OP03-102", "OP03-103", "OP03-104",
        "OP03-105", "OP03-106", "OP03-107", "OP03-108", "OP03-109",
        "OP03-110", "OP03-111", "OP03-112", "OP03-113", "OP03-114",
        "OP03-115", "OP03-116", "OP03-117", "OP03-118", "OP03-119",
        "OP03-120", "OP03-121", "OP03-122", "OP03-123", "ST01-012",
        "ST03-009", "ST04-003",
    }),
    "OP-04": frozenset({
        # 124 card codes.
        "OP01-047", "OP01-078", "OP02-004", "OP02-085", "OP02-099",
        "OP04-001", "OP04-002", "OP04-003", "OP04-004", "OP04-005",
        "OP04-006", "OP04-007", "OP04-008", "OP04-009", "OP04-010",
        "OP04-011", "OP04-012", "OP04-013", "OP04-014", "OP04-015",
        "OP04-016", "OP04-017", "OP04-018", "OP04-019", "OP04-020",
        "OP04-021", "OP04-022", "OP04-023", "OP04-024", "OP04-025",
        "OP04-026", "OP04-027", "OP04-028", "OP04-029", "OP04-030",
        "OP04-031", "OP04-032", "OP04-033", "OP04-034", "OP04-035",
        "OP04-036", "OP04-037", "OP04-038", "OP04-039", "OP04-040",
        "OP04-041", "OP04-042", "OP04-043", "OP04-044", "OP04-045",
        "OP04-046", "OP04-047", "OP04-048", "OP04-049", "OP04-050",
        "OP04-051", "OP04-052", "OP04-053", "OP04-054", "OP04-055",
        "OP04-056", "OP04-057", "OP04-058", "OP04-059", "OP04-060",
        "OP04-061", "OP04-062", "OP04-063", "OP04-064", "OP04-065",
        "OP04-066", "OP04-067", "OP04-068", "OP04-069", "OP04-070",
        "OP04-071", "OP04-072", "OP04-073", "OP04-074", "OP04-075",
        "OP04-076", "OP04-077", "OP04-078", "OP04-079", "OP04-080",
        "OP04-081", "OP04-082", "OP04-083", "OP04-084", "OP04-085",
        "OP04-086", "OP04-087", "OP04-088", "OP04-089", "OP04-090",
        "OP04-091", "OP04-092", "OP04-093", "OP04-094", "OP04-095",
        "OP04-096", "OP04-097", "OP04-098", "OP04-099", "OP04-100",
        "OP04-101", "OP04-102", "OP04-103", "OP04-104", "OP04-105",
        "OP04-106", "OP04-107", "OP04-108", "OP04-109", "OP04-110",
        "OP04-111", "OP04-112", "OP04-113", "OP04-114", "OP04-115",
        "OP04-116", "OP04-117", "OP04-118", "OP04-119",
    }),
}


def _normalise_card_code(card_code: str | None) -> str | None:
    """Upper-cased and stripped, and nothing else.

    Both Bandai and SNKRDUNK write a card code as `OP03-021`, so no separator
    folding is needed or wanted here: collapsing punctuation would let two
    genuinely different codes compare equal, which in a membership guard means
    failing OPEN.
    """
    if card_code is None:
        return None
    cleaned = card_code.strip().upper()
    return cleaned or None


def resolve_source_product_code(
    source_name: str, label: str | None, card_code: str | None
) -> str | None:
    """The Atlas release product code this source's label names, or None.

    None means "no product evidence" - never "probably this one". The caller
    treats it exactly as it treats an unresolved official label, so every
    refusal path below lands on the existing `source_product_unresolved`
    behaviour rather than on anything new.

    ORDER MATTERS AND IS NOT AN OPTIMISATION. The official table is consulted
    first and its answer is returned unconditionally, so a label Bandai
    publishes can never be shadowed by a source-specific row.
    """
    official = resolve_product_code(label)
    if official is not None:
        return official

    entry = _SOURCE_ALIASES.get(source_name, {}).get(normalise_label(label))
    if entry is None:
        return None
    product_code, _evidence = entry

    # FAIL CLOSED. The alias says what the label means; this says whether THIS
    # listing is consistent with it. A code the product does not contain means
    # the label's meaning has drifted, and the honest answer is no evidence.
    code = _normalise_card_code(card_code)
    if code is None or code not in _OFFICIAL_MEMBERSHIP[product_code]:
        return None
    return product_code


def source_alias_evidence(source_name: str, label: str | None) -> str | None:
    """Why the alias for this source's label is believed, for audit output."""
    entry = _SOURCE_ALIASES.get(source_name, {}).get(normalise_label(label))
    return entry[1] if entry else None


def known_source_aliases(source_name: str) -> dict[str, str]:
    """Every alias trusted for this source, as {normalised label: product code}."""
    return {
        label: code for label, (code, _) in _SOURCE_ALIASES.get(source_name, {}).items()
    }


def official_membership(product_code: str) -> frozenset[str]:
    """The frozen Bandai membership the guard tests against. Empty if unknown."""
    return _OFFICIAL_MEMBERSHIP.get(product_code, frozenset())
