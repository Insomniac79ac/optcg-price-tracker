"""How a SOURCE writes the name of an uncoded Bandai product.

WHY THIS IS NOT IN uncoded_product_evidence. That module establishes what a
product IS, and it reads Bandai and nothing else - a marketplace may never
contribute to a product's membership. This module records something different
and much weaker: the string one storefront happens to print for a product that
already exists. It is nomenclature, not identity, and the distinction is the
one `ReleaseProductAlias.alias_kind` exists to keep:

    bandai_official   what Bandai publishes. The authority.
    source_rendering  how a storefront writes it. Never a Bandai name.

Every row below is written to the database as `source_rendering`, so no
storefront spelling can ever be mistaken for, or promoted to, a Bandai name.

WHY THESE PRODUCTS NEED IT AT ALL. A coded product is reachable from a source
label through `release_product_code` - SNKRDUNK says "Booster Pack Final
Battle", the worker's contents-based alias resolves that to OP-02, and the
exact-print gate narrows on the code. An uncoded product HAS no code, and
inventing one is precisely what this tranche refuses to do. So the label is
resolved to the product's surrogate identity instead, through this table.

THE EVIDENCE STANDARD for a row here. It is the contents standard the worker's
`source_product_aliases` already applies, restated for products identified by
name rather than by code. All four must hold:

  1. The product itself is established from Bandai evidence alone, by
     `uncoded_product_evidence.prove_uncoded_product`. This module never
     creates a product and never widens one's membership.
  2. Every card code observed under the source label, across the whole
     discovered corpus, is a member of that product's Bandai membership.
  3. That observed code set is contained by EXACTLY ONE Bandai product. If two
     could contain it, the label has not been identified and no row is written.
  4. The label resolves to nothing under the coded standards, so this table is
     only ever consulted for what those leave unresolved.

Measured on the 676-candidate SNKRDUNK corpus of 2026-08-30. Five of the six
observed code sets are EQUAL to their product's full Bandai membership, not
merely contained by it; the sixth is a strict subset and is marked as such.

WHAT THIS DELIBERATELY DOES NOT DO. No fuzzy matching, no substring matching,
no translation, no typo correction, and no "closest product" fallback. The
only comparison is equality of the whole label. A label that is not listed
here resolves to nothing and the gate refuses it exactly as it does today.
"""

from __future__ import annotations

from dataclasses import dataclass

# The alias kind every row here is written as. Never bandai_official.
SOURCE_RENDERING = "source_rendering"


@dataclass(frozen=True)
class SourceRendering:
    """One source's label for one uncoded Bandai product, with its evidence."""

    source_name: str
    source_label: str
    product_name: str
    observed_card_codes: tuple[str, ...]
    membership_relation: str  # "equal" or "subset"
    evidence: str


# (source, exact source label) -> rendering. Exact whole-label equality only.
UNCODED_SOURCE_RENDERINGS: tuple[SourceRendering, ...] = (
    SourceRendering(
        source_name="snkrdunk",
        source_label="Premium Card Collection -Best Selection vol.1-",
        product_name="プレミアムカードコレクション - ベストセレクションvol.1 -",
        observed_card_codes=(
            "OP01-029", "OP01-057", "OP02-005", "OP02-036", "OP02-106", "OP02-117",
            "OP03-121", "OP04-105", "ST03-012", "ST03-017", "ST04-016", "ST05-014",
        ),
        membership_relation="equal",
        evidence=(
            "The 12 distinct card codes observed under this label across the "
            "676-candidate corpus of 2026-08-30 are EXACTLY the 12-code Bandai "
            "membership of JP series 550801 product "
            "'プレミアムカードコレクション - ベストセレクションvol.1 -', and that product is "
            "the only one in the frozen JP catalogue whose membership contains the set. "
            "Every one of the 12 is a _p2/_p3 parallel asset Atlas did not previously "
            "hold, so the identification is not an artefact of Atlas's own coverage."
        ),
    ),
    SourceRendering(
        source_name="snkrdunk",
        source_label="Premium Card Collection 25th Anniversary Edition",
        product_name="プレミアムカードコレクション 25周年エディション",
        observed_card_codes=(
            "OP01-001", "OP01-013", "OP01-016", "OP01-022",
            "ST01-002", "ST01-005", "ST01-008", "ST01-010",
        ),
        membership_relation="subset",
        evidence=(
            "The 8 distinct card codes observed under this label are a strict SUBSET of "
            "the 10-code Bandai membership of JP series 550801 product "
            "'プレミアムカードコレクション 25周年エディション', which is the only product in "
            "the frozen JP catalogue containing the set. The two unobserved members are "
            "P-001 (a promo code Atlas holds no canonical card for) and ST01-006 - which "
            "IS observed in the corpus, under the SNKRDUNK typo "
            "'Premium Card Collection 25th Anniversary Editionl'. That typo is "
            "deliberately NOT given a row: exact whole-label matching refuses it, and "
            "correcting a storefront's spelling would be inference, not evidence."
        ),
    ),
    SourceRendering(
        source_name="snkrdunk",
        source_label="Standard Battle Pack Vol.1",
        product_name="スタンダードバトルパック2022 Vol.1",
        observed_card_codes=("OP01-021", "OP01-033", "ST04-011"),
        membership_relation="equal",
        evidence=(
            "The 3 distinct card codes observed under this label are EXACTLY the 3-code "
            "Bandai membership of JP series 550901 product 'スタンダードバトルパック2022 "
            "Vol.1', the only product containing the set. Note the Bandai name carries a "
            "year ('2022') the SNKRDUNK label omits; the identification is by contents, "
            "so the differing prose costs nothing and is never matched on."
        ),
    ),
    SourceRendering(
        source_name="snkrdunk",
        source_label="Standard Battle Pack Vol.2",
        product_name="スタンダードバトルパック2022 Vol.2",
        observed_card_codes=("ST01-007", "ST02-007", "ST03-007", "ST04-010"),
        membership_relation="equal",
        evidence=(
            "The 4 distinct card codes observed under this label are EXACTLY the 4-code "
            "Bandai membership of JP series 550901 product 'スタンダードバトルパック2022 "
            "Vol.2', the only product containing the set."
        ),
    ),
    SourceRendering(
        source_name="snkrdunk",
        source_label="Standard Battle Pack Vol.3",
        product_name="スタンダードバトルパック Vol.3",
        observed_card_codes=("OP01-035", "ST01-011", "ST03-005", "ST06-006"),
        membership_relation="equal",
        evidence=(
            "The 4 distinct card codes observed under this label are EXACTLY the 4-code "
            "Bandai membership of JP series 550901 product 'スタンダードバトルパック Vol.3', "
            "the only product containing the set. Bandai drops the '2022' from Vol.3's "
            "name that Vol.1 and Vol.2 carry; contents, not prose, is what identifies it."
        ),
    ),
    SourceRendering(
        source_name="snkrdunk",
        source_label="1st ANNIVERSARY SET",
        product_name="1st ANNIVERSARY SET",
        observed_card_codes=("OP01-006", "OP02-015", "OP03-013"),
        membership_relation="equal",
        evidence=(
            "The 3 distinct card codes observed under this label are EXACTLY the 3-code "
            "Bandai membership of JP series 550801 product '1st ANNIVERSARY SET', the "
            "only product containing the set. The label happens to equal the Bandai name "
            "here, but it is still recorded as a source_rendering: the product was "
            "identified by contents, and a coincidence of spelling is not authority."
        ),
    ),
)


def renderings_for(source_name: str) -> tuple[SourceRendering, ...]:
    return tuple(r for r in UNCODED_SOURCE_RENDERINGS if r.source_name == source_name)


def rendering_for_label(source_name: str, label: str) -> SourceRendering | None:
    """Exact whole-label equality. No normalisation of any kind."""
    for row in UNCODED_SOURCE_RENDERINGS:
        if row.source_name == source_name and row.source_label == label:
            return row
    return None
