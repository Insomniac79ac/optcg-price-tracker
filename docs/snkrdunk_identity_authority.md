# SNKRDUNK identity authority

Which source is allowed to establish each expected identity field, and why the
answer differs per field.

## The rule that drives all of this

**SNKRDUNK may never supply both sides of its own check.** For every identity
dimension, the *expected* value must come from somewhere independent of the
page being validated. Where it comes from is field-specific.

| Field | Authority | Fallback | Never |
|---|---|---|---|
| `card_code` | Bandai card-level evidence | Verified Yuyu-Tei product for the same print | SNKRDUNK |
| Release name for a `release_product_code` | **Bandai only** | *(none)* | SNKRDUNK, Yuyu-Tei |
| Name, rarity | `canonical_cards` | *(none)* | SNKRDUNK |
| Treatment, language | `card_prints` | *(none)* | SNKRDUNK |
| Artwork | Bandai official card artwork | *(none)* | SNKRDUNK |

`release_product_code` itself is **not** a Bandai-published field. Bandai
publishes a product *code* for its numbered lines (`OP-01`, `ST-xx`, `EB-xx`,
`PRB-xx`) and a product *name* for every product; Atlas derives
`card_prints.release_product_code` from its own canonical card/set data, in
Bandai's `OP-01` format. What the table above places under Bandai authority is
the **name** that code resolves to. See
[snkrdunk_release_reference.md](snkrdunk_release_reference.md) for what that
code can and cannot represent.

## Card code — a two-tier hierarchy

Bandai's public card list does not cover every collectible print (promos and
special products in particular), so requiring a Bandai record for *every* print
would block legitimate cards. `card_code_authority.py` resolves in order:

**1. Bandai card-level evidence.** `card_prints.image_url` holds Bandai's own
official card-list artwork URL, and Bandai encodes the card code in the path:

```
https://www.onepiece-cardgame.com/images/cardlist/card/OP04-083.png
https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001_p2.png
https://www.onepiece-cardgame.com/images/cardlist/card/OP01-120_r1.png
```

The `_p<n>` / `_r<n>` suffix is not part of the code. This URL is already
fetched and perceptual-hash compared on every validation run, so the code
parsed from it is evidence the collector has independently exercised — not a
value copied from a spreadsheet.

**The published grammar.** Measured across the complete JP catalogue on
2026-08-22 (4,962 occurrences): `base` 2,821, `p1`–`p10` 1,680, `r1`–`r3` 461,
and nothing else — no other suffix family, and no unparseable basename. Both
families are read by `parse_official_asset_variant`
(`app/services/official_asset_variant.py`) into
`card_prints.official_asset_variant`.

**Why `official_asset_variant`, not `official_artwork_variant`.** The field was
originally named for artwork, which promised more than the evidence supports.
The suffix identifies the official **asset/occurrence**; it does not guarantee
the artwork differs. The same corpus contains **152 rN assets whose bytes are
byte-for-byte identical to a base asset**. The name was corrected to match what
the suffix actually discriminates.

**What the suffix does and does not mean.** A bare `CODE.png` and each
`CODE_pN.png` / `CODE_rN.png` are *distinct official assets* of the same card
code. That is all the suffix establishes:

- It **is** identity-bearing source evidence — the asset component of the
  exact-print key `(canonical_card_id, language, release_product_id,
  official_asset_variant)`.
- It says **nothing** about parallel, manga, special, alt-art, or any rarity
  rank. Bandai's Card List gives every sibling printing identical card code,
  rarity, category and product, and publishes no label distinguishing them at
  all — every one of the 459 rN assets whose card also has a base sibling
  carries the *same* rarity as that sibling. `treatment` in this repo is
  therefore an **Atlas editorial classification**, not source data, and must
  never be inferred from a filename.
- **Identical image bytes may still be distinct print identities.** When the
  product or the asset variant differs, the printings differ even though
  `artwork_key` — the SHA-256 of the bytes — is equal. `artwork_key` stays
  evidence; it is not identity, and it never was.

**Why rN had to be admitted.** Three cards publish both `_r1` and `_r2` inside
one product — OP01-120, OP05-074 and OP05-119, all in PRB-01 — with distinct
official entry ids, distinct asset addresses and distinct SHA-256 digests.
While the vocabulary knew only `base` and `pN`, all three collapsed to a NULL
variant and collided under the exact-print key. With rN read as a
discriminator, the corpus has no suffix-induced collision left.

Two further properties, both established from Bandai's own Card List:

- **Suffix numbering spans products.** It is indexed per card code across every
  product, not per release. `OP01-001` has `_p2` in OP-01 while `_p1` and `_p3`
  belong to entirely different limited products, and `OP01-002` has `_p1` in
  OP-01 — the numbering is not contiguous within a release.
- **Suffix numbering is per catalogue, not global.** The Japanese
  (`www.onepiece-cardgame.com`) and Asia-English (`asia-en.onepiece-cardgame.com`)
  catalogues serve the same artwork files under *swapped* suffixes: Asia-EN
  `OP01-001_p1.png` is byte-identical to JP `OP01-001_p2.png`, and vice versa
  (verified 2026-08-21 by SHA-256). A suffix read from one catalogue therefore
  cannot be compared against a suffix read from another. The **image digest** is
  the only artwork identity that is stable across catalogues.

**2. Verified Yuyu-Tei product**, when Bandai has no card-level record. Valid
only when the Yuyu-Tei mapping is:

- for the **same** `card_print_id`
- `is_active = true`
- `review_status = 'approved'` **and** `manual_verified = true`
- carrying a `source_card_id` extracted from the source, and a `source_url` to cite

`manual_verified` is required in addition to `review_status`: approved-alone is
precisely what the 2026-08-10 incident showed to be insufficient.

**3. Nothing** → `card_code_authority_missing`, and validation fails closed. A
missing authority is never a reason to fall back on the mapping's own
SNKRDUNK-scoped `source_card_id`.

### What is never used to infer a card code

SNKRDUNK's title, the release code, the product ID, or artwork alone.

## Release / set — Bandai only, no fallback

The Yuyu-Tei fallback **does not apply** to release identity. Two independent
checks, both required:

| | Check | Fail reason |
|---|---|---|
| A | Set token in the page's own card code → `card_prints.release_product_code` | `release_product_mismatch` |
| B | Page's own release name → Bandai's name for that release code | `release_name_mismatch` |

Check A cannot catch a reprint carrying an unchanged card code but belonging to
a different release; check B is what does.

Both checks are scoped to **coded, numbered product lines**. `release_product_code`
is Atlas-derived from the card's canonical set data rather than read from a
Bandai product field, and it is the join key into `RELEASE_REFERENCES` — so
SNKRDUNK release verification does depend on it. Bandai also publishes many
limited and promotional products that carry a *name only*, and those cannot be
named by a release code at all; see
[snkrdunk_release_reference.md](snkrdunk_release_reference.md).

### Source-specific renderings

`ReleaseReference` keeps three separate fields so an audit record can always say
*which* authority a name agreed with:

- `bandai_official_name` — what Bandai publishes. The authority.
- `additional_official_names` — for when **Bandai itself** publishes more than
  one rendering. Each entry needs its own Bandai source URL. Currently empty.
- `snkrdunk_renderings` — how SNKRDUNK writes it. **Storefront nomenclature,
  not a Bandai name**, and never reported as one.

A match reports `MATCH_BANDAI_OFFICIAL` or `MATCH_SOURCE_RENDERING`
accordingly, and that value is recorded in the verification metadata.

**OP-01 is the live example.** Bandai titles it in Latin — `ROMANCE DAWN`.
SNKRDUNK transliterates it to `ロマンスドーン`, as Amazon.co.jp does. The
katakana is declared under `snkrdunk_renderings`, so an OP-01 product is not
failed for a spelling difference, while the record still shows the name matched
storefront nomenclature rather than Bandai. Renderings are scoped to their own
release — OP-01's does not satisfy OP-04.

## Provenance in verification metadata

No schema migration. Provenance is recorded inside the existing
`source_card_mappings.match_explanation_json` verification record:

```json
{
  "card_code_authority": "Bandai",
  "card_code_evidence": "https://www.onepiece-cardgame.com/images/cardlist/card/OP04-118.png?2606",
  "release_name_match_authority": "Bandai official name"
}
```

`card_code_authority` is `"Bandai"` or `"Yuyu-Tei"`. Never invent Bandai
evidence where none exists — record the Yuyu-Tei product URL instead.

## Re-using Yuyu-Tei evidence

Do **not** re-scrape Yuyu-Tei to establish values already retained in verified
mappings. Only request Yuyu-Tei again if a required card code genuinely has no
retained trustworthy evidence, and report that need first. The Yuyu-Tei cron and
collector are out of scope.
