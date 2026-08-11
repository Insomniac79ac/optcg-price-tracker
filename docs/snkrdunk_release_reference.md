# SNKRDUNK release-name validation

How the collector proves that a SNKRDUNK product belongs to the release its
linked `card_print` says it does, and how a storefront's own spelling of a
release name is handled without ever being mistaken for a Bandai name.

For the wider question of which source may establish each identity field, see
[snkrdunk_identity_authority.md](snkrdunk_identity_authority.md).

## Why two checks, not one

`services/snkrdunk_collector/snkrdunk_collector/writer.py` runs two
**independent** release checks. Both must pass.

| | Check | Fail reason |
|---|---|---|
| A | The set token in the page's own card code (`OP04-118` → `OP04` → `OP-04`) equals `card_prints.release_product_code` | `release_product_mismatch` |
| B | The page's own release name equals Bandai's authoritative name for that release code | `release_name_mismatch` |

Check A alone cannot detect a reprint or alternate product that carries an
unchanged card code but actually belongs to a different release product.
Check B is what catches that, so the two are never collapsed into one reason.

## The authority is Bandai, never SNKRDUNK

`release_reference.py` holds the table. Every entry is taken from Bandai's own
Japanese product page and cites its source URL.

| Code | Bandai official name | Source |
|---|---|---|
| OP-01 | `ROMANCE DAWN` | <https://www.onepiece-cardgame.com/products/boosters/op01.php> |
| OP-02 | `頂上決戦` | <https://www.onepiece-cardgame.com/products/boosters/op02.php> |
| OP-03 | `強大な敵` | <https://www.onepiece-cardgame.com/products/boosters/op03.php> |
| OP-04 | `謀略の王国` | <https://www.onepiece-cardgame.com/products/boosters/op04.php> |

Corroborated for OP-01 by Bandai's catalogue entry (JAN 4549660853268):
<https://www.bandai.co.jp/catalog/item.php?jan_cd=4549660853268000>

**Never populate this table from SNKRDUNK.** Deriving the expected name from
the same page being verified makes the check circular and worthless — the
failure mode behind the 2026-08-10 fabricated-evidence incident.

## What normalization is allowed

`identity.normalize_release_text` folds **source formatting only**:

- NFKC (fullwidth ↔ halfwidth)
- a trailing product-code bracket — `【OP-01】`, `[OP-01]`, `(OP-01)`
- one leading product-category prefix — `ブースターパック`, `スタートデッキ`, …
- surrounding punctuation and separators
- all whitespace
- letter case

It does **not** translate, transliterate, or alias. `ロマンスドーン` does not
become `ROMANCE DAWN`. `RELEASE_TEXT_PREFIXES` is a category-word list and must
never be extended with an individual product name — that would silently alias
one release to another.

## OP-01 — resolved via a declared source rendering

Bandai titles OP-01 in **Latin letters**: `ブースターパック ROMANCE DAWN【OP-01】`.

SNKRDUNK transliterates it into katakana: `ブースターパック ロマンスドーン`.
Amazon.co.jp does the same. That is a **retailer rendering with no Bandai
attestation**, so it is not recorded as a Bandai name.

It is instead declared under `snkrdunk_renderings` — storefront nomenclature,
kept separate from `bandai_official_name` and from
`additional_official_names` (which is reserved for renderings Bandai itself
publishes, and is empty):

```python
"OP-01": ReleaseReference(
    release_product_code="OP-01",
    bandai_official_name="ROMANCE DAWN",
    source_url="https://www.onepiece-cardgame.com/products/boosters/op01.php",
    additional_official_names=(),
    snkrdunk_renderings=("ロマンスドーン",),
),
```

An OP-01 product therefore passes check B, and the verification record reports
`release_name_match_authority = "SNKRDUNK source-specific rendering"` rather
than claiming a Bandai match. Renderings are scoped to their own release —
OP-01's does not satisfy OP-04.

Before this was declared, the offline cross-check of validation deployment
`906a8b60` (2026-08-11) put 12 of 15 re-approved mappings at pass and mappings
**36, 37 and 38** (all OP-01) at fail — a false negative on known-good
mappings, not a wrong-product detection.

## Unknown releases

`get_release_reference` returns `None` for any release code not in the table,
and the writer emits `authoritative_release_name_missing` rather than skipping
check B. An OP-05+ expansion therefore cannot bypass this gate by simply having
no entry — someone has to add the reference from an authoritative source first.
