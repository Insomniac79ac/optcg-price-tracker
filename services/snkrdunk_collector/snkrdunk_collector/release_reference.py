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
both list "ロマンスドーン"). That transliteration is a RETAILER rendering with
no Bandai attestation, so it is deliberately NOT present in this table. A
SNKRDUNK OP-01 product will therefore fail the release-name check until a
human adds an attested rendering via `additional_official_names` with its own
source URL. Failing closed on a naming difference we cannot substantiate is
the intended behaviour - see docs/snkrdunk_release_reference.md.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseReference:
    """One release product's authoritative naming.

    `additional_official_names` exists for the case where Bandai itself
    publishes more than one rendering of the same product name. It is NOT an
    alias list: never add a name observed on a marketplace, however plausible
    - each entry needs its own Bandai source URL recorded beside it.
    """

    release_product_code: str
    bandai_official_name: str
    source_url: str
    additional_official_names: tuple[str, ...] = ()

    def accepted_names(self) -> tuple[str, ...]:
        return (self.bandai_official_name, *self.additional_official_names)


RELEASE_REFERENCES: dict[str, ReleaseReference] = {
    "OP-01": ReleaseReference(
        release_product_code="OP-01",
        bandai_official_name="ROMANCE DAWN",
        source_url="https://www.onepiece-cardgame.com/products/boosters/op01.php",
        # Intentionally empty - see the module docstring's OP-01 note.
        additional_official_names=(),
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


def get_release_reference(release_product_code: str | None) -> ReleaseReference | None:
    """None means "this collector has no authoritative name for that release"
    - callers must fail closed on it, never skip the check (see
    writer.validate_identity's authoritative_release_name_missing)."""
    if not release_product_code:
        return None
    return RELEASE_REFERENCES.get(release_product_code.strip().upper())
