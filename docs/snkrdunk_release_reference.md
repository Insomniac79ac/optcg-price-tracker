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

## What this table can and cannot represent

**It covers coded, numbered product lines only** — `OP-xx`, `ST-xx`, `EB-xx`,
`PRB-xx`. Those are the products for which Bandai publishes a code, and they are
the only ones `release_product_code` can name.

**Uncoded products exist, and there are many.** Bandai's Card List carries
limited and promotional products that publish a *name only* — no code, no id, no
slug, no data attribute. Sampling two series pages on 2026-08-21 found **223
distinct products with no code at all** (196 under プロモーションカード, 27 under
限定商品収録カード), including the two extra `OP01-001` printings:
`プレミアムカードコレクション 25周年エディション` and
`週刊少年ジャンプ応募者全員サービス`. A series id cannot stand in for a product
id — one series page holds up to 196 different products.

So **`release_product_code` alone cannot represent every Bandai product**, and a
card belonging to an uncoded product cannot be given a release code without
inventing one. Note also that `card_prints.release_product_code` is *Atlas-derived*
from the card's canonical set data, not read from a Bandai product field —
although its `OP-01` format is Bandai's own. The SNKRDUNK release verification
below **does** use it, as the join key into `RELEASE_REFERENCES`.

**A product code is scoped to the catalogue that published it.** Bandai runs
more than one Card List catalogue, and they do not agree on the code space
(verified 2026-08-22 against the official sites):

| Catalogue | `OP-01` record | `EB-04` record |
|---|---|---|
| JP `www.onepiece-cardgame.com` | `ブースターパック ROMANCE DAWN【OP-01】`, 2022.07.22 | `エクストラブースター EGGHEAD CRISIS【EB-04】`, 2026-01-31 |
| Asia-EN `asia-en.onepiece-cardgame.com` | `BOOSTER PACK -ROMANCE DAWN- [OP-01]`, 2022-07-22 | `EXTRA BOOSTER -EGGHEAD CRISIS- [EB-04]`, 2026-01-31 |
| EN `en.onepiece-cardgame.com` | `BOOSTER PACK -ROMANCE DAWN- [OP01]`, 2022-12-02 | **no standalone record** — those cards ship inside `[OP14-EB04]` / `[OP15-EB04]` |

Four consequences, none of them cosmetic:

- The **same code names differently-dated products** — the two English
  catalogues publish different release dates for `OP-01`, so language alone does
  not identify a product record.
- A code may **not exist at all** in another catalogue, or may be a *composite*:
  the EN catalogue's series `569114` is titled `-THE AZURE SEA'S SEVEN-
  [OP14-EB04]` and contains cards whose codes begin `EB04-`. Check A's
  assumption — set token in the card code equals the product code — holds for the
  JP catalogue and **would fail on EN data**, where `EB04-011` belongs to product
  `OP14-EB04`.
- Even the rendering is unstable: `【OP-01】`, `[OP-01]` and `[OP01]` are all the
  same product. A code parsed from a page is a comparison aid, not identity.
- Series ids are catalogue-local too: EN `?series=569114` resolves, the same id
  on the JP catalogue returns `カードリストの取得に失敗しました`.

**This table is collector-local Python, not canonical database product
identity.** `RELEASE_REFERENCES` lives in one collector service and is invisible
to the API and to any future importer. A first-class product entity, able to
represent uncoded products and to survive Bandai renames, is designed in
`docs/release_product_entity_2026-08-21.pdf`; until that lands, this table is the
authority for release *names* and nothing else.

When it does land, **release product identity will not be keyed globally by
`official_code`.** The evidence above rules that out: a code is unique only
within the catalogue that published it, may be absent or composite in another,
and may carry a different release date under the same string. Identity will be a
surrogate id, with a code unique per source catalogue where a code exists at all
— and never unique on a product *name*.

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
