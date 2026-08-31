"""Which release product a verified print belongs to, and what that product
may legitimately be called on a SNKRDUNK listing.

WHY THIS REPLACED A HARDCODED TABLE. Release verification used to ask
`RELEASE_REFERENCES[card_print.release_product_code]`, a five-entry dict
covering OP-01..OP-04 and EB-01. Two consequences, both measured on the
2026-08-31 canary of 30 approved mappings:

  * `release_product_code IS NULL` - every uncoded Bandai product, which is
    precisely the promotional/limited/event catalogue the uncoded-product
    tranche made approvable - returned None and failed closed with
    `authoritative_release_name_missing`. 18 of 30.
  * any coded product outside the five did the same. ST-04 twice.

So approvals had outrun collection: the gate could prove a printing that the
collector could then never price. The catalogue already knows which product a
print belongs to - `card_prints.release_product_id` - and already records what
that product is called, in `release_products` and `release_product_aliases`.
This module reads that, so the catalogue is the single authority.

THIS IS NOT A LOOSENING, and the distinction matters. What is checked is
unchanged: the listing's own release text must match an authoritative name for
the product the PRINT says it belongs to. What changed is where the expected
name comes from - a table this service re-declared, versus the catalogue that
owns the fact. Every failure mode is still a refusal:

    print has no release_product_id      -> refused (no authoritative identity)
    product row missing                  -> refused
    product not `verified`               -> refused
    product has no usable names           -> refused
    listing's name matches none of them  -> refused

WHAT IS DELIBERATELY *NOT* CONSULTED. The card code's set token. SNKRDUNK
derives a product code from the card-code prefix - ST01-012 -> "ST-01" - and
that is an inference about the CARD, not an observation about the product the
item shipped in. For a reprint the two legitimately differ: ST01-012 exists as
an OP-03 printing, and the old check called that `release_product_mismatch` on
a listing whose release NAME matched Bandai's official OP-03 name exactly. A
card code's prefix can never be evidence about which product a reprint belongs
to, so it no longer takes part in release verification. See writer.py.

WHERE THIS SITS AMONG THE OTHER PRODUCT-IDENTITY RESOLVERS, because there are
now four and they must not be mistaken for duplicates. Three of them answer
DIFFERENT questions, and the direction is what separates them:

  * worker.matching.source_product_aliases / release_product_aliases -
    LABEL -> PRODUCT CODE, at candidate parse time. Many storefront labels,
    one product; resolved by frozen catalogue membership.
  * api exact_print_approval - LABEL -> PRODUCT, at approval time, to decide
    WHICH printing a listing may be approved onto. Coded products narrow on
    `release_product_code`; uncoded ones on `release_product_id` via a
    `source_rendering` alias.
  * this module - PRODUCT -> NAMES, at collection time. The product is
    already chosen (the mapping names the print), so the only question left
    is whether the name the page displayed is one this product is known by.

A resolver that picks a product from a label must be conservative about
ambiguity, because picking wrong invents a fact. This one cannot pick wrong -
it is handed the product - so it may accept every name the catalogue records
for it. That is why it consults `source_rendering` aliases for CODED products
too, where `exact_print_approval.resolve_uncoded_product_id` deliberately
refuses to: there, a second route to a coded product could drift away from the
worker's contents-based one; here there is no route to drift, only a name to
recognise.

STATIC RELEASE_REFERENCES SURVIVE, narrowly. They carry Bandai names verified
against Bandai's own product pages, which is external attestation the
catalogue does not itself record a source URL for. They are consulted as an
ADDITIONAL source of accepted names for the five products they cover, and are
no longer the ceiling on which products can be collected.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from snkrdunk_collector.identity import release_names_match
from snkrdunk_collector.models import CardPrint, ReleaseProduct, ReleaseProductAlias
from snkrdunk_collector.release_reference import (
    MATCH_BANDAI_OFFICIAL,
    MATCH_SOURCE_RENDERING,
    get_release_reference,
)

# Alias kinds that carry a name BANDAI publishes, as opposed to a storefront's
# own spelling. Mirrors app/models/release_product_alias.py's constraint.
BANDAI_ALIAS_KINDS = ("bandai_official", "bandai_additional")
SOURCE_ALIAS_KIND = "source_rendering"

# Where an accepted name came from, for the audit record.
MATCH_CATALOGUE_PRODUCT = "Atlas catalogue product name"

# Refusal reasons. Named here because writer.py emits them verbatim and the
# operator greps them.
NO_PRODUCT_LINK = "authoritative_release_identity_missing"
PRODUCT_ROW_MISSING = "release_product_row_missing"
PRODUCT_UNVERIFIED = "release_product_unverified"
NO_NAMES = "authoritative_release_name_missing"


@dataclass(frozen=True)
class ReleaseIdentity:
    """The product a print belongs to, and every name it may be called by.

    `bandai_names` and `source_names` stay separate so a verification record
    can say which authority answered - the same reason
    release_reference.ReleaseReference keeps them apart. Collapsing them would
    let a storefront spelling be reported as a Bandai attestation.
    """

    product_id: int
    official_code: str | None
    display_name: str
    bandai_names: tuple[str, ...] = ()
    source_names: tuple[str, ...] = ()

    @property
    def is_uncoded(self) -> bool:
        return self.official_code is None

    def accepted_names(self) -> tuple[str, ...]:
        return (*self.bandai_names, *self.source_names)

    def describe(self) -> str:
        """How the product is named in a refusal message. Uses the surrogate
        id for an uncoded product rather than inventing a code for it."""
        if self.official_code:
            return self.official_code
        return f"uncoded product #{self.product_id} ({self.display_name!r})"

    def classify_match(self, observed_release_text: str | None) -> str | None:
        """Which authority the observed name agreed with, or None for no
        match. Bandai is checked first so a name that is both is reported as
        the stronger attestation."""
        for name in self.bandai_names:
            if release_names_match(observed_release_text, name):
                return MATCH_BANDAI_OFFICIAL
        for name in self.source_names:
            if release_names_match(observed_release_text, name):
                return MATCH_SOURCE_RENDERING
        return None


@dataclass(frozen=True)
class ReleaseIdentityResult:
    """Either an identity, or the reason there isn't one. Never both."""

    identity: ReleaseIdentity | None = None
    refusals: tuple[str, ...] = field(default_factory=tuple)


def _dedupe(names) -> tuple[str, ...]:
    seen, out = set(), []
    for name in names:
        cleaned = (name or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return tuple(out)


def resolve_release_identity(session: Session, card_print: CardPrint | None) -> ReleaseIdentityResult:
    """The authoritative product identity for one print, or a refusal.

    Fails closed at every step. A print whose product Atlas has not settled -
    no link, missing row, or a product still `unverified` - has no
    authoritative release name, and a listing cannot be checked against a name
    nobody has established.
    """
    if card_print is None:
        return ReleaseIdentityResult(refusals=("card_print_missing_for_release_identity",))

    if card_print.release_product_id is None:
        return ReleaseIdentityResult(
            refusals=(
                f"{NO_PRODUCT_LINK}:card_print={card_print.id},"
                f"release_product_code={card_print.release_product_code}",
            )
        )

    product = session.get(ReleaseProduct, card_print.release_product_id)
    if product is None:
        return ReleaseIdentityResult(
            refusals=(f"{PRODUCT_ROW_MISSING}:release_product_id={card_print.release_product_id}",)
        )
    if product.verification_status != "verified":
        # An unverified product's name is not yet an authority, so it cannot
        # be the expectation a listing is measured against.
        return ReleaseIdentityResult(
            refusals=(
                f"{PRODUCT_UNVERIFIED}:release_product_id={product.id},"
                f"status={product.verification_status}",
            )
        )

    aliases = session.scalars(
        select(ReleaseProductAlias).where(ReleaseProductAlias.product_id == product.id)
    ).all()

    bandai = [a.alias_name for a in aliases if a.alias_kind in BANDAI_ALIAS_KINDS]
    source = [a.alias_name for a in aliases if a.alias_kind == SOURCE_ALIAS_KIND]

    # The product's own catalogue names. `display_name` and `first_seen_name`
    # are what Bandai's card list published for the series, so they belong
    # with the Bandai-attested names rather than the storefront ones.
    bandai.extend([product.display_name, product.first_seen_name])

    # The statically verified Bandai references, where one exists for this
    # code. Additional evidence only - never the gate. See the module
    # docstring for why they are kept.
    reference = get_release_reference(product.official_code)
    if reference is not None:
        bandai.extend(reference.bandai_names())
        source.extend(reference.snkrdunk_renderings)

    identity = ReleaseIdentity(
        product_id=product.id,
        official_code=product.official_code,
        display_name=product.display_name,
        bandai_names=_dedupe(bandai),
        source_names=_dedupe(n for n in source if n not in set(_dedupe(bandai))),
    )
    if not identity.accepted_names():
        return ReleaseIdentityResult(
            refusals=(f"{NO_NAMES}:release_product_id={product.id}",)
        )
    return ReleaseIdentityResult(identity=identity)
