"""Authoritative release-product reference, sourced from Bandai.

The authority for what a release product is *called* is Bandai's own Japanese
product page - never SNKRDUNK, and never a marketplace listing. SNKRDUNK's
release text is evidence to be checked *against* this table, never a source
for populating it. That direction matters: deriving the expected name from the
same page being verified would make the check circular and worthless, which is
the failure mode behind the 2026-08-10 fabricated-evidence incident.

Verified 2026-08-11 against the official product pages:
  OP-01  https://www.onepiece-cardgame.com/products/boosters/op01.php
         "ブースターパック ROMANCE DAWN【OP-01】"
  OP-02  https://www.onepiece-cardgame.com/products/boosters/op02.php
         "ブースターパック 頂上決戦【OP-02】"
  OP-03  https://www.onepiece-cardgame.com/products/boosters/op03.php
         "ブースターパック 強大な敵【OP-03】"
  OP-04  https://www.onepiece-cardgame.com/products/boosters/op04.php
         "ブースターパック 謀略の王国【OP-04】"
  Corroborated by Bandai's own catalogue entry for OP-01 (JAN 4549660853268):
         https://www.bandai.co.jp/catalog/item.php?jan_cd=4549660853268000

NOTE ON OP-01. Bandai titles this set in Latin letters - "ROMANCE DAWN" - not
in katakana. Marketplaces commonly transliterate it (Amazon.co.jp and SNKRDUNK
both list "ロマンスドーン"). That transliteration has no Bandai attestation, so
it is NOT recorded as a Bandai name; it lives in `snkrdunk_renderings` as
declared source-specific nomenclature. A match against it is reported as
MATCH_SOURCE_RENDERING so an audit record always shows which authority the
name agreed with. See docs/snkrdunk_release_reference.md.
"""

from dataclasses import dataclass


MATCH_BANDAI_OFFICIAL = "Bandai official name"
MATCH_SOURCE_RENDERING = "SNKRDUNK source-specific rendering"


@dataclass(frozen=True)
class ReleaseReference:
    """One release product's authoritative naming.

    Three deliberately separate fields, because they carry different weight
    and a verification record must be able to say which one matched:

    `bandai_official_name` - what Bandai publishes. The authority.

    `additional_official_names` - for when Bandai ITSELF publishes more than
    one rendering. Not an alias list: never add a name observed on a
    marketplace, and record a Bandai source URL beside every entry.

    `snkrdunk_renderings` - how SNKRDUNK writes this release. Explicitly
    SOURCE-SPECIFIC NOMENCLATURE, not a Bandai name and never presented as
    one. It exists so a known storefront spelling does not fail a mapping
    whose identity is otherwise fully proven, while keeping the provenance
    of the match visible in the audit record.
    """

    release_product_code: str
    bandai_official_name: str
    source_url: str
    additional_official_names: tuple[str, ...] = ()
    snkrdunk_renderings: tuple[str, ...] = ()

    def bandai_names(self) -> tuple[str, ...]:
        return (self.bandai_official_name, *self.additional_official_names)

    def accepted_names(self) -> tuple[str, ...]:
        return (*self.bandai_names(), *self.snkrdunk_renderings)


RELEASE_REFERENCES: dict[str, ReleaseReference] = {
    "OP-01": ReleaseReference(
        release_product_code="OP-01",
        bandai_official_name="ROMANCE DAWN",
        source_url="https://www.onepiece-cardgame.com/products/boosters/op01.php",
        # Bandai publishes exactly one rendering: the Latin "ROMANCE DAWN".
        additional_official_names=(),
        # SNKRDUNK transliterates it (Amazon.co.jp does too). Recorded here as
        # storefront nomenclature so OP-01 products are not failed for a
        # spelling difference - NOT as a Bandai name. A match against this
        # value is reported as MATCH_SOURCE_RENDERING, never as Bandai.
        snkrdunk_renderings=("ロマンスドーン",),
    ),
    "OP-02": ReleaseReference(
        release_product_code="OP-02",
        bandai_official_name="頂上決戦",
        source_url="https://www.onepiece-cardgame.com/products/boosters/op02.php",
    ),
    "OP-03": ReleaseReference(
        release_product_code="OP-03",
        bandai_official_name="強大な敵",
        source_url="https://www.onepiece-cardgame.com/products/boosters/op03.php",
    ),
    "OP-04": ReleaseReference(
        release_product_code="OP-04",
        bandai_official_name="謀略の王国",
        source_url="https://www.onepiece-cardgame.com/products/boosters/op04.php",
    ),
}

RELEASE_NAME_AUTHORITY = "Bandai official Japanese product page"


def classify_release_name_match(
    reference: ReleaseReference | None,
    observed_release_text: str | None,
    matcher,
) -> str | None:
    """Which authority the observed release name agreed with, so an audit
    record can distinguish "matched Bandai" from "matched a known storefront
    spelling". None means it matched neither.

    `matcher` is injected (identity.release_names_match) to keep this module
    free of a normalization dependency.
    """
    if reference is None:
        return None
    if any(matcher(observed_release_text, name) for name in reference.bandai_names()):
        return MATCH_BANDAI_OFFICIAL
    if any(matcher(observed_release_text, name) for name in reference.snkrdunk_renderings):
        return MATCH_SOURCE_RENDERING
    return None


def get_release_reference(release_product_code: str | None) -> ReleaseReference | None:
    """None means "this collector has no authoritative name for that release"
    - callers must fail closed on it, never skip the check (see
    writer.validate_identity's authoritative_release_name_missing)."""
    if not release_product_code:
        return None
    return RELEASE_REFERENCES.get(release_product_code.strip().upper())
