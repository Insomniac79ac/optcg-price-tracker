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
| `release_product_code` / release name | **Bandai only** | *(none)* | SNKRDUNK, Yuyu-Tei |
| Name, rarity | `canonical_cards` | *(none)* | SNKRDUNK |
| Treatment, language | `card_prints` | *(none)* | SNKRDUNK |
| Artwork | Bandai official card artwork | *(none)* | SNKRDUNK |

## Card code — a two-tier hierarchy

Bandai's public card list does not cover every collectible print (promos and
special products in particular), so requiring a Bandai record for *every* print
would block legitimate cards. `card_code_authority.py` resolves in order:

**1. Bandai card-level evidence.** `card_prints.image_url` holds Bandai's own
official card-list artwork URL, and Bandai encodes the card code in the path:

```
https://www.onepiece-cardgame.com/images/cardlist/card/OP04-083.png
https://www.onepiece-cardgame.com/images/cardlist/card/OP01-001_p2.png
```

The `_p<n>` suffix marks a parallel treatment's artwork and is not part of the
code. This URL is already fetched and perceptual-hash compared on every
validation run, so the code parsed from it is evidence the collector has
independently exercised — not a value copied from a spreadsheet.

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
