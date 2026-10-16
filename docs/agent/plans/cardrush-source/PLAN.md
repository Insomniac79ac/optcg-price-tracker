# CardRush price source: read-only audit + plan (PLAN ONLY)

Status: **PLAN ONLY**, for owner review, 2026-10-16, branch `plan/cardrush-source`.
- Base: `origin/staging` at `1068d3c` for the first revision (proxy-blocked audit, session `012tP9…`).
  This revision is on `49e611c` and contains the completed audit.
- Scope: STAGING ONLY. Production RED. PSA10 OFF.
- Nothing changed: code, collectors, settings, prices, identity, Market Value, the Index, staging data and
  Railway are untouched. No PR, no runbook dispatch, no source job.

**Audit authority and footprint.** This revision ran the read-only audit the owner asked for:
- **74 requests**, all to `www.cardrush-op.jp`, between 2026-10-16 14:31 and 14:41 UTC.
- One request at a time, at least 3 s apart (minimum measured gap 4.6 s).
- Every response was HTTP 200, with no 403, 429 or challenge. No image, CSS or JS was fetched.
- `cardrush.media/data_policy` was **not** requested: the owner had already seen a 403, and the brief stops on any 403.
- The HTML stayed in the session scratchpad only. It was not committed and not written to staging. Only the short
  excerpts below are kept.

Evidence labels:
- **MEASURED**: observed in the audit (bracketed source URL), read from the repo, or given by the owner with a source.
- **CARRIED FORWARD**: measured by an earlier session and committed (path given).
- **ESTIMATE**: arithmetic or assumption, with its basis.
- **UNVERIFIED**: third-party snippet or background knowledge.

"Sample" means the **4,506 unique products** parsed from the 66 listing pages fetched.

---

## Plain summary (for the owner)

1. **What CardRush adds.** CardRush lists about **14,820** One Piece products (MEASURED). Each card has one
   listing per condition. About 99% of the cards it carries have a plain "state A" listing, which is the
   comparable shop price (MEASURED in 4 complete sets).
   - Today 1,681 of 4,316 card versions have no price at all, and only 334 have two (CARRIED FORWARD).
   - A third shop price could fill many gaps and turn one-source prices into proper medians.
2. **PSA10.** About **2,176** graded listings (MEASURED). This could become a second PSA10 asking price besides
   SNKRDUNK, kept OFF and separate.
3. **Collecting is light.** The pack list pages show name, price and stock for 100 products each, so a daily
   refresh is about **150 pages**, taking about 12 minutes at polite spacing. Product pages are not needed (MEASURED).
4. **Storage.**
   - With compressed raw pages, CardRush adds about **3.4 MB/day** plus about **27 MB once** (ESTIMATE).
     That fits the 90-day rule at planning (+504 MB) and stress B (+123 MB).
   - Storing pages uncompressed would not fit at stress B (−350 MB). So compression is a precondition.
5. **Policy risk, read first.** An earlier plan quoted a search snippet of CardRush's data policy that bans automated
   price collection (UNVERIFIED; the live page is 403). Robots.txt itself blocks only four named AI bots (MEASURED).
6. **Decisions you need to make** (§H, each with a default):
   - accept the policy risk before any recurring collection;
   - which conditions count as raw (default 状態A/unlabeled only);
   - sale and out-of-stock rules;
   - whether CardRush joins the Index/Market Value median (default yes, after a 14-day hidden trial);
   - an honest crawler name.

---

## 0. Step 0: policy position (recorded, no stop)

| Item | Result | Label |
|---|---|---|
| Policy link | Every product page footer links 「当サイトの価格データ等の利用について」 to `https://cardrush.media/data_policy` | MEASURED [/product/2923 footer] |
| Policy page | 403 to everyone (owner checked 2026-10-16). Not requested by this audit (brief stops on 403). An earlier session's proxy also refused the host (CONNECT 403, 14:14:10Z). | MEASURED (owner); CARRIED FORWARD |
| Policy text | Data-platform plan §A6 (`origin/plan/data-platform:docs/agent/plans/data-platform/PLAN.md` ~L332) quotes a search snippet: 「独自コンテンツの無断使用、転載は禁止」; bans 「クローリングやスクレイピングを目的として…自動化された手段で…価格やその他コンテンツの情報を取得すること」 and 「販売価格や買取価格を得る目的で手動による大量のアクセス」. Its §A7 rates CardRush **W** (written permission) for display, redistribution and commercial use. | CARRIED FORWARD, UNVERIFIED (snippet) |
| Contact | info@cardrush-op.jp (data-platform §A6) | CARRIED FORWARD |
| robots.txt | See below. Disallows only GPTBot, Bytespider, TikTokSpider and meta-externalagent; no path is disallowed for any other agent | MEASURED [`/robots.txt`, HTTP 200, 110 B] |
| Repo policy | Actions with legal/compliance implications are "stop and ask" (`docs/agent/AUTONOMY_POLICY.md:114`, `scripts/staging_policy.py` `legal_compliance`). Widespread blocking means containment, never evasion (`docs/agent/INVARIANTS.md:68-69`). | MEASURED (repo) |

```
User-agent: GPTBot
User-agent: Bytespider
User-Agent: TikTokSpider
User-agent: meta-externalagent
Disallow: /
```

- **What robots.txt permits.** `/product-list`, `/product-group/*`, `/product/*`, `/new` and `/page/*` are allowed
  for a generic, honest user agent. The collector must never use one of the four listed agents and must re-read
  robots.txt on every run (§E).
- **Position.** The owner decision of 2026-10-16 is the operating position: same footing as Yuyu-Tei/SNKRDUNK,
  derived values on Card Pirate, and no external delivery until the legal opinion covers CardRush.
  - The snippet names automated price collection specifically. So the first **recurring** collection (S4 canary)
    stays a RED owner step (Q1).
  - The one-off audit was run on the owner's explicit brief.

---

## 1. Step 1: audit results (MEASURED unless marked)

### 1.1 Site structure

The shop runs on the おちゃのこネット (ocnk) platform (image host `cardrush-bs.ocnk.net`).

| URL | What it is | Measured |
|---|---|---|
| `/product-list?page=N` | Every product in the shop, 100 per page | Header **14,820 件**. 149 pages; page 149 holds 20 items [/product-list, ?page=75, ?page=149] |
| `/product-group/{id}?page=N` | Pack, deck and category groups, 100 per page | 50 groups linked from `/group`. The sum of group headers is 16,020, so **a product can sit in several groups** |
| `/product/{id}` | One product (numeric id; highest seen 15,580) | 78–82 KB |
| `/new` | New arrivals | Header 234 件 |
| `/page/8`, `/page/44` | Condition guide; graded-card guide | |

- **Listing controls.** `num` takes 10/20/30/50/**100** (default 100). `sort` takes featured, price, price-desc and
  rank, with no id or date sort [listing `<select>`].
- **Default order.** In-stock items come first and sold-out items last. Page 1 of every group had 0 sold-out
  items; `/product-list?page=149` was 20/20 sold out.
- **Group sizes** [header counts on page 1 of each group]:
  - プロモ (5) 2,951;
  - 鑑定済カード (37) 2,176;
  - 傷アリ特価 (42) 1,730;
  - PRB-01 (52) 1,019;
  - PRB-02 (102) 761;
  - OP-01…OP-17 boosters 288–392 each;
  - EB-01…EB-04 183–256;
  - starter decks 64–158;
  - anniversary and promo sets 4–46;
  - ☆SALE☆ (1) 12;
  - デッキ販売 (3) 33;
  - 福袋&オリパ (7) 1.
- **Page counts.** A full group crawl is **188 pages**. Excluding groups 37/42/1/3/7 it is **145 pages**
  (ceil(count/100) per group).

### 1.2 Listing contents: everything needed is on the list page

Excerpt from `/product-group/27`, trimmed:

```html
<li class="list_item_cell list_item_15580 ">
  <div class="item_data" data-product-id="15580">
    <a href="https://www.cardrush-op.jp/product/15580" class="item_data_link">
      <span class="goods_name">〔状態C〕トラファルガー・ロー(パラレル/illust:Makitoshi)【SR/P】{OP01-047}</span>
      <span class="model_number_value">トラファルガーロー</span>
      <span class="figure">520円</span><span class="tax_label list_tax_label">(税込)</span>
      <p class="stock">在庫数 1枚</p>
```

- **Price.** Tax-included JPY. Present on every sampled product, sold-out included (0 nulls in 4,506).
- **Stock.** `在庫数 N枚` gives a count, `在庫なし` means sold out (still priced), and decks and oripa use `点`.
  - The product page says the count is online stock only: 「商品ページに表示されている在庫数は通販サイト上の在庫数となります。各店舗の在庫数とは異なります」 [/product/936].
- **Product page.** It adds nothing: same name, price and stock, a quantity picker, and 再入荷 on sold-out
  [/product/936, /2923, /320]. **No product page is needed for daily refresh.**
- **One product = one condition variant.** There is no condition selector on product pages. In 4 fully crawled
  sets, no two products shared name + variant + rarity + code + condition (0 collisions).

### 1.3 Name grammar

`[〔condition|graded〕][☆SALE☆][(qualifier)]name[(variant markers)]【rarity】{card code}`

| Element | Values seen | Count in sample (4,506) |
|---|---|---|
| Condition | none (= 〔状態A〕, per /page/8), 〔状態A-〕, 〔状態B〕, 〔状態C〕 | 2,019 / 1,142 / 1,003 / 222 |
| Graded | 〔PSA10鑑定済〕, 〔※状態難/PSA10鑑定済〕, 〔PSA9鑑定済〕, 〔※状態難/PSA9鑑定済〕, 〔※状態難/CGC鑑定済〕 | 97 / 17 / 3 / 2 / 1 |
| Sale | ☆SALE☆ prefix (group 1) | 12 |
| Qualifier before name | (赤白版), (鉛筆マーク無し) | 12+ |
| Variant markers | パラレル, illust:{artist}, 漫画背景/漫画絵, フルアート/foil, SP, ロゴ (ROUND ONE PIECEロゴ, 4周年ロゴ), ノーマル仕様, 修正前/修正後, CS20xx, 英語/English, China, 未開封/開封 | パラレル 1,716; illust 1,535; SP 276; 漫画 268; フルアート 157; ロゴ 112; foil 109; 未開封 41 |
| Rarity | C, UC, R, SR, SEC, L, P; `/P` parallel, `/SP` | |
| Code | `{OP01-047}`, `{EB02-026}`, `{ST20-005}`, `{P-101}`; `{-}` for DON!! and other uncoded items | `{-}` 250 |

- **/page/8.** Excerpt: 「■〔状態A〕 (商品名に状態表記の無い商品は〔状態A〕となります。) …●小さな白カケがある。●小さな擦れ傷やくすみがある。」.
  - A- adds friction gloss marks, tiny bends and dents.
  - B covers visible whitening, dents, light folds and nail marks.
  - C covers creases and overall damage.
- **/page/44.** 〔※状態難/…鑑定済〕 marks a slab with notable card or case flaws. A buyer cannot choose among the
  units in stock.
- **傷アリ特価 (damaged).** Group 42 holds only names labelled 〔状態A-〕 and 〔状態B〕 (100/100 on page 1, 20/20 on
  page 18).
  - **No キズ有り/傷アリ tag appears in any of the 4,506 names.** "Damaged" is a group-membership signal, not a name signal.
  - With raw = A/unlabeled only (B1-a), no damaged product can reach raw.
- **セール.** It appears only as the ☆SALE☆ prefix in group 1 (12 products, 11 sold out).

### 1.4 Coverage and variants (4 sets crawled completely)

| Set (group) | Products | Distinct prints | Products per print | Prints with an A/unlabeled listing | … in stock | Sold-out products |
|---|---|---|---|---|---|---|
| OP-01 (27) | 331 | 157 | 2.11 | 156 | 151 | 124 |
| OP-13 (103) | 368 | 177 | 2.08 | 177 | 173 | 110 |
| OP-17 (134) | 392 | 183 | 2.14 | 183 | 183 | 145 |
| EB-02 (59) | 256 | 106 | 2.42 | 106 | 86 | 110 |

- **Price relative to the A/unlabeled listing of the same print** (prints ≥ ¥500, sample), as median ratios:
  - A- 0.92 (n=479);
  - B 0.78 (n=446);
  - C 0.47 (n=155);
  - PSA10 6.27 (n=48).
- **Whole-shop estimates:**
  - About **6,900** raw candidates (unlabeled, coded, not sale, not sealed). ESTIMATE: 41–48% unlabeled in full sets × 14,820.
  - About **4,700–5,600** distinct prints (ESTIMATE: 9,078 pack-group products ÷ 2.15, plus promos ÷ about 2, less overlap).
- **PSA10.** 114 PSA10 products in the sample, 105 in stock.

### 1.5 Identity ambiguity (sample of 1,988 raw candidates: unlabeled, not sale, not 未開封)

| Class | Count | Share | Resolver implication (§C) |
|---|---|---|---|
| Uncoded `{-}` (DON!! and similar) | 99 | 5.0% | Quarantine unless the catalogue carries DON!! |
| Only raw listing for its code | 1,044 | 52.5% | Exact if code + release resolve to one print |
| Base print where the code also has variants | 357 | 18.0% | Exact if no variant markers and exactly one base print |
| Variant among several for the code | 476 | 23.9% | Needs explicit variant evidence; otherwise `REFUSAL_AMBIGUOUS` |
| Same text except a qualifier prefix (赤白版) | 12 | 0.6% | Distinct prints; quarantine until rendered |
| Listed in two pack groups (e.g. OP09 cards also in ST-23〜28) | 30 | 1.5% | Release ambiguous → refuse (existing rule) |

- Code + rarity is shared by more than one raw listing for **115 of 1,769** code/rarity pairs (6.5%).
- **ESTIMATE.** First-pass exact-and-unique rate about **65–75%**, with the rest quarantined. This is checked
  against the staging catalogue in S2/S4 (this audit read no staging data).

### 1.6 Bytes and requests

| Item | Value |
|---|---|
| Full 100-item list page | median **400,284 B** (min 315,590, max 425,075; n=44) |
| Product page | 78–82 KB (n=3) |
| Latency | median 1,582 ms, max 2,576 ms |
| One list page compressed: zlib-1 / gzip-9 / xz-9 | 29,435 / 22,550 / 17,282 B |
| Item block only (`<li>` run) | 309,874 B; gzip-9 12,455 B |
| Daily refresh (§E) | about 150 requests/day (145 group pages + robots + `/new` up to 3) plus about 27/day for a weekly sweep (ESTIMATE) |
| Audit total | 74 requests, 22.06 MB downloaded |

Card Pirate side (CARRIED FORWARD, `docs/agent/handoff/2026-10-15/capacity75-session13/CURRENT_STATE-end.yaml:538-602`):
- 4,316 canonical card versions;
- 2,635 have any source, 334 both, 1,681 none;
- Yuyu 2,690 refresh captures per 24 h;
- SNKRDUNK 304 refresh attempts per 24 h.

---

## A. Source position

- **Same footing as Yuyu-Tei and SNKRDUNK** (owner decision 2026-10-16): collect politely, show derived values on
  Card Pirate, and no external delivery (partner API, licensing, data product) until the legal opinion covers CardRush.
- **Policy page 403** (§0). The only text we have is a snippet that bans automated price collection.
  - That is stricter than Yuyu-Tei, where no scraping clause was found.
  - It is similar in kind to SNKRDUNK's, an owner-accepted risk (G1 in the data-platform plan).
  - robots.txt does not restrict generic agents (MEASURED).
- **Add CardRush to the legal-opinion scope**, as four questions:
  1. **Collection.** Automated, low-rate reading of public list pages despite a published but unreachable data
     policy that may ban it. Covers the effect of the policy being 403, and of robots.txt allowing it.
  2. **Public display of derived values.** Median, Market Value and Index that include CardRush, and an attributed
     per-source "CardRush (状態A)" line on the print page.
  3. **Licensing.** Whether derived values that include CardRush can be delivered externally. Default: no, until
     the opinion says yes.
  4. **PSA10.** Displaying a CardRush graded asking price (2,176 graded listings, MEASURED), and combining it with
     SNKRDUNK PSA10.
- **Parallel option** (owner action; an external message, not sent here). Ask RUSH for written permission at
  info@cardrush-op.jp. A yes removes the clause risk. See Q1.
- **Images.** None fetched, stored or shown (§E).

---

## B. Methodology options (RED: the owner decides)

Changing pricing methodology or the meaning of Index/Market Value is "stop and ask" (`AUTONOMY_POLICY.md:106-107`).

### B1. Which conditions count as raw

| Option | What | Trade-off |
|---|---|---|
| **B1-a (default)** | 状態A = unlabeled names only (/page/8) | Comparable to Yuyu sell (a near-mint shop price). Coverage is still about 99% of listed prints (§1.4) |
| B1-b | A and A- | Almost no coverage gain (A exists for 99% of prints). Biases about 8% low (A- median 0.92 × A) |
| B1-c | Lowest of A/A-/B/C (SNKRDUNK floor precedent, `snkrdunk_collector/extractor.py:87-138`) | Pulls toward worn copies (B 0.78, C 0.47 × A). Not comparable to Yuyu |

- **Always excluded from raw:**
  - any product in group 42 (傷アリ特価);
  - 〔…鑑定済〕 graded slabs;
  - ☆SALE☆;
  - 未開封/開封 sealed promos;
  - decks (group 3);
  - oripa (group 7);
  - names with 英語/English/China.
- **Nothing is lost.** The raw HTML keeps every grade, so a later parser can derive A-/B/C series without new requests.

### B2. Sale (セール)

- **Default: excluded.** Stored as provenance with `promotion_state='sale'` (the column is source-neutral,
  `models/price_observation.py:140-144`). Never public, never in history, Index or Market Value. Same as the Yuyu
  promotion decision (`DECISIONS.md:17`).
- **Measured.** Sale appears only as ☆SALE☆ (12 products). There is no struck-through price to substitute.

### B3. Out of stock

Sold-out products keep a displayed price (MEASURED). 30–43% of products in the 4 full sets were sold out, but
the A listing was in stock for 81–100% of prints.

| Option | Trade-off |
|---|---|
| **B3-a (default): same as Yuyu.** A displayed price stays eligible regardless of stock, max age 7 days (`market_index.py` `_resolve_yuyutei_sell`, `YUYUTEI_SELL_MAX_AGE_DAYS=7`). Stock recorded in `stock_status` and `listing_count`. | Consistent, source-neutral rule. A sold-out shop price may be stale-high |
| B3-b: in-stock only | A price you can actually buy at. Coverage drops (EB-02: 86/106 prints). A value flickers with stock, creating Market Value leavers and entrants |
| B3-c: out-of-stock eligible for N days after last in-stock | Middle ground. It must live in the resolver/semantics, because the Index forbids source-specific aggregation (`market_index.py:31-37`) |

### B4. PSA10 (stays OFF)

- **Default: a separate graded series, OFF.**
  - Parse graded products into the CardRush product table with `grade_key`: `graded:PSA:10`,
    `graded:PSA:10:flawed` for 〔※状態難/…〕, `graded:PSA:9`, `graded:CGC:…`.
  - Write **no PSA10 observations** while PSA10 is OFF. This mirrors `scripts/snkr_storage_canary.py:135`, which
    asserts zero psa10 price states.
  - Raw HTML keeps them, and graded products also appear in the pack groups crawled daily (e.g. 10 in OP-01), so
    turning PSA10 on later needs no backfill crawl.
- **When the owner turns PSA10 on.**
  - CardRush becomes the second PSA10 asking source beside SNKRDUNK `psa10_asking`.
  - Default: exclude 状態難 slabs.
  - Never mixed into raw Index or Market Value (`INVARIANTS.md:59-61`).
  - The PSA10 combination rule is a separate decision at that point.

### B5. How CardRush combines with Yuyu-Tei and SNKRDUNK

Today the Index is `median_of_sources`, `INDEX_VERSION=3`, with one value per source and no weights
(`services/market_index.py:135-136, 414-585`). One value gives limited; two or more give full.

| Option | What | Trade-off |
|---|---|---|
| **B5-a (default): full peer, after a shadow trial.** CardRush 状態A becomes a third resolver: one value per print, the cheapest eligible A/unlabeled product, which is normally the only one (0 collisions, §1.2). Cutover on one chosen date. | Simplest and source-neutral (`market_index.py:31-37`). A median of three resists one outlier. Two of three inputs are dealer asks. **The cutover breaks movement comparability once** (see the bullets below this table) |
| B5-b: display only | An attributed CardRush line, no Index/Market Value input. No methodology change, but it does not fill the 1,681 unpriced versions in Market Value |
| B5-c: coverage only | A source-specific aggregation rule, which the Index design does not permit (`market_index.py:35-37`). Not recommended |

- **Why B5-a breaks comparability.** Two things change on cutover day:
  - the contributor set changes (`market_value.py:423-424`, `contributor_set_changed`);
  - the required `SOURCE_SEMANTICS_VERSION` bump (`source_semantics.py:101-116`) adds `source_semantics_version_changed`.
  - So Market Value starts a new segment that day, and 7D/30D windows cannot cross it for 7/30 days.
- **Card Pirate Index.** `services/card_pirate_index.py` reads only `index_value_jpy`, so it follows B5 with no
  change of its own.

---

## C. Identity

The rules are an exact physical CardPrint and an authoritative `release_product_id` (`DECISIONS.md:15-16`).
Ambiguity is never auto-approved; anything else is quarantined. Manual mappings always win (AGENTS.md, `INVARIANTS.md:14-17`).

### C1. Resolver rules (CardRush name → exact CardPrint)

Reuse `services/exact_print_approval.py` `resolve_exact_print` (:530-710). Add a new
`SourceEvidence.from_cardrush_candidate` next to `from_snkrdunk_candidate` and `from_yuyutei_candidate` (:185-268).
Inputs from one CardRush product:

1. **Card code** from `{…}` (MEASURED grammar §1.3).
   - It is required: `{-}`, a missing code or two codes means refuse.
   - The code is checked against Bandai/catalogue. CardRush never supplies both sides of its own check (the
     principle of `docs/snkrdunk_identity_authority.md`).
2. **Release** comes from the product group the product was found under. That gives a release product code or
   an uncoded alias (`worker/matching/source_product_aliases.py`).
   - A product seen in **two pack groups**, or a group that does not resolve to exactly one release, means refuse
     (existing rule :666-676; 1.5% of the sample).
   - Never infer release from the code prefix: PRB-01 holds OP05 codes, for example.
3. **Variant.** パラレル, `illust:…`, 漫画, SP, フルアート/foil, ロゴ, ノーマル仕様, 修正前/後 and qualifier
   prefixes (赤白版, 鉛筆マーク無し) narrow to the variant family, as for SNKRDUNK (`snkrdunk_listing_evidence.py:1-60`).
   - `official_asset_variant` is set only from explicit evidence. An illustrator name alone is not enough.
   - No markers means the base print only.
4. **Rarity** (`【SR/P】`) is recorded. The `/P` and `/SP` suffix agrees with the parallel flag but is not a sole
   discriminator (existing rule :586-590).
5. **Condition, grade, sale and sealed** are parsed into `grade_key` and flags. They never affect print identity,
   only eligibility.
6. **Result.**
   - Exactly one print gives `print_matched`, then approval goes through the existing gate.
   - More than one gives `REFUSAL_AMBIGUOUS`. None gives `unmatched`. A conflict gives `identity_conflict`.
   - Every non-exact outcome is quarantined (`freshness_work.state='blocked'`), never retried by guess.
7. **Condition siblings.** One CardPrint has several CardRush products (A, A-, B, C, PSA10). Each is its own
   mapping (`uq_source_card_mappings_source_url` allows it). Only the A/unlabeled one is index-eligible (B1).

### C2. Ambiguity rate (MEASURED pattern, ESTIMATE rate)

- **Pattern** (§1.5).
  - 70.5% of raw candidates are either the only listing for their code or a marker-free base print. These should
    resolve by code + release.
  - 23.9% are variants among several for the code.
  - 5.0% are uncoded.
  - 1.5% are multi-group reprints.
- **Gate.** In S4 (first canary), go only if both hold:
  - at least 65% of 状態A products resolve exactly;
  - 0 resolve to a wrong print on a manual check of 50.
  - Otherwise rework C1 before widening.

### C3. Reuse

- `exact_print_approval.resolve_exact_print`, its refusal codes and `NEEDS_REVIEW_REFUSALS`.
- `worker/matching/opcg_normalizer.py` (`VARIANT_KEYWORDS`) and `source_product_aliases.py`.
- `packages/opcg_source_identity`. Add a CardRush canonical listing identity (`www.cardrush-op.jp/product/{id}` → product id) and conformance vectors.
  - Without it, mappings get a NULL identity and freshness refuses them (`__init__.py:27-34`, `freshness_queue.py:102-105`).
- Quarantine reporting: `scripts/quarantine_reporting.py`.
- Test fixtures come from this audit's excerpts and grammar (mock data first, `INVARIANTS.md:65-67`).

---

## D. Data model (additive migrations only)

Head today is `3b7d9c1a5e20` (MEASURED). Additive, reversible migrations are AMBER (`AUTONOMY_POLICY.md:74`).
The owner runs `alembic upgrade head` with a staging backup under 24 h old (`:148-149, :193`).

### D1. One grade/condition field on observations

Today grade lives in `price_type` plus free-text `condition_label`. SNKRDUNK raw `floor` stores the winning A–D
grade; PSA10 is `price_type='psa10_asking'` with `condition_label='PSA10'` (`snkrdunk_collector/writer.py:416-419, 480`).

- **New column.** Add nullable `price_observations.grade_key VARCHAR(32)`. Vocabulary:
  - `raw:A`, `raw:A-`, `raw:B`, `raw:C`, `raw:D`, `raw:damaged`;
  - `graded:<grader>:<grade>[:flawed]`, e.g. `graded:PSA:10`, `graded:PSA:10:flawed`, `graded:PSA:9`, `graded:CGC:10`.
  - CardRush unlabeled maps to `raw:A` (/page/8, MEASURED), so the first revision's `raw:unlabeled` is not needed.
  - Keep `condition_label` verbatim and keep `price_type`, so no reader changes.
- **Constraint.** The CHECK on the vocabulary is added `NOT VALID`, then validated. A nullable add with no default
  is metadata-only on PostgreSQL 16 (no table rewrite).
- **Existing rows.** **No backfill.** Readers treat NULL as "derive from price_type/condition_label". New SNKRDUNK
  writes may set the column later; that is optional.
- **Freshness.** `freshness_price_states` would get the same nullable column only if per-grade freshness is wanted.
  The default is no: only the counted 状態A category has freshness.

### D2. CardRush records

- **Source row.** A `sources` row `cardrush` (`base_url https://www.cardrush-op.jp`), seeded in the migration.
  Precedent: `f4c8a2d91b60` seeded `snkrdunk`.
- **`cardrush_product_groups`.** Group id, URL, verbatim title, resolved `release_product_id` (nullable), kind
  (pack/promo/graded/damaged/sale/deck/oripa), first and last seen. There are 50 groups today.
- **`cardrush_candidates`.** One row = one CardRush product = one condition variant. Columns:
  - product id (unique) and URL;
  - **group ids (array)**, because products sit in several groups (MEASURED);
  - verbatim name;
  - parsed code, rarity, variant markers and qualifier;
  - `grade_key`, sale and sealed flags;
  - last price and stock seen;
  - `match_status` (`unmatched|print_matched|identity_conflict`);
  - nullable `card_print_id`;
  - first and last seen.
  - It mirrors `yuyutei_candidates` and `snkrdunk_candidates`. There are about 14,820 rows today.
- **Proposal groups.** Widen the `source_mapping_proposal_groups.source_candidate_type` CHECK to add
  `cardrush_candidate` (drop and re-add, `NOT VALID` then validate).
- **Observation links.** `price_observations.candidate_id` stays SNKRDUNK-only. CardRush observations link through
  `source_card_mapping_id` plus `raw_snapshot_id` only.
- **Mappings.** Existing `source_card_mappings`, one per CardRush product, with the canonical identity from
  `opcg_source_identity`.

### D3. Must-do guards before any CardRush row exists

- **Register the source.** Add CardRush to `services/source_instruments.py` `SOURCE_INSTRUMENTS`.
  - Today an unregistered source shows **every** price_type in public print series (`source_instruments.py:99-103, 174-187`; `print_series.py:46-52, 595-606`).
  - So B, C, damaged and sale rows would be charted publicly.
  - Until cutover, CardRush series must be hidden from public reads.
- **Ship semantics at cutover.** Unknown sources are classified eligible (`source_semantics.py:244-249, 267-269`).
  - No CardRush resolver exists until cutover, so nothing enters the Index.
  - The `SOURCE_SEMANTICS` entry and version bump ship only at the cutover (B5), not earlier, to avoid a second break.

### D4. Collector import-graph impact

| Change | Runtime input of | Consequence |
|---|---|---|
| `packages/opcg_source_identity` (CardRush identity) | both existing collectors | redeploy all 10 collector services |
| `services/raw_dictionary_storage.py` `PARSERS` += `cardrush-collector-v1` | both | same |
| `services/freshness_integration.py` `CATEGORIES`, `freshness_queue.py` (list-page work unit) | both | same |
| `source_instruments.py`, `exact_print_approval.py`, models | check with `scripts/collector_runtime_inputs.py` | likely both |
| New `services/cardrush_collector/` (plain HTTP, no `browser` module) | new collector only | new service |
| `scripts/collector_runtime_inputs.py` `COLLECTORS`, `scripts/deploy_staging_collectors.py` `NAMES` and the ≤10 collector cap, `scripts/product_lane.py`, `generate_staging_state.py`, `check_raw_health.py` | tooling (DATA lane) | cap must become 11 (Q11) |

- **Shared modules first.** Bundle all shared-module edits into **one** delivery with **one** 10-service rollout
  (S2), so the existing collectors move once.
- **Collector package after.** The CardRush package itself (S3) touches only the new service.

---

## E. Collector

| Item | Plan |
|---|---|
| Transport | Plain HTTP GET, one HTML document per request (all data is in server HTML, MEASURED). No images, CSS, JS or fonts. A slim Python image, not the Playwright base |
| robots.txt | Fetched at the start of every run. A run proceeds only if every path it will request is allowed for its user agent. An unreachable robots.txt means no run (fail closed) |
| User-Agent | Honest and identifying, with a contact URL (Q8), e.g. `CardPirateBot/1.0 (+https://<card-pirate-domain>/bot)`. Never one of the four agents robots.txt names |
| Daily fetch | The **145 pack/promo group pages** (`num=100`, groups other than 37/42/1/3/7). They carry name, price and stock (MEASURED), and the group gives release evidence (C1.2). Work unit = one list page. Refreshing a page refreshes every mapping on it |
| Weekly sweep | `/product-list?page=1..149` plus groups 37 and 42 (40 pages), spread over 7 days (about 27/day). It catches products in no pack group, verifies the lossless count against the 14,820 header, and refreshes group-42 exclusion membership |
| Discovery | Daily `/new` (up to 3 pages). New product ids also appear on the daily group pages. Weekly `/group` finds new packs. Discovery never approves; candidates go through §C |
| Product pages | Not used for refresh (MEASURED: no extra fields). At most 20/day, only for identity review of a quarantined product |
| Shards | One service and no shards. Four resumable segments of about 37 pages per run, with lease and timeout per segment |
| Schedule | One run per day at **16:00 UTC** (01:00 JST, shop quiet hours), finishing well before the 20:00 UTC index snapshot and outside 19:30–20:30. No collector change 02:00–06:00 UTC; releases 06:00–23:00 UTC. At least 5 min after and 8 min before Yuyu (`:00/:30` family) and SNKR (`:27/:57`) fires for deploy slots |
| Rate limit | One request at a time, **5 s spacing** (3 s floor) plus 0–1 s jitter. A full daily run is about 150 × (5 + 1.6) s ≈ **17 min** (ESTIMATE from measured latency) |
| Request budget | About 150/day plus about 27/day sweep, plus up to 20 product pages, so **about 200/day**. `source_dispatch_budgets` row 300/86,400 s, per-run cap 250. Setting the envelope is AMBER |
| Pagination drift | Order is in-stock-first, so items move when stock changes mid-run. Deduplicate by product id. Lossless check: distinct ids seen ≥ 99.5% of the sum of headers for the groups fetched; a shortfall re-queues the pages next run |
| Freshness target | The shared 24 h standard, with dispatch due at 23 h (`DECISIONS.md:18`). Failure does not count as refreshed, and no-listing does not refresh an old price |
| RAW | Persist the HTML before parsing (`INVARIANTS.md:65-69`). Dictionary-encode against the previous same-URL body once `cardrush-collector-v1` is in `PARSERS`. Shares daily admission (8,192 rows / 32 MiB encoded per UTC day, `raw_dictionary_storage.py:24-56`); CardRush needs about 150 rows and about 2 MB (ESTIMATE) |
| Health | Follows the `docs/agent/RAW_OPERATIONAL_HEALTH.md` contract (HEALTHY/DEGRADED/BLOCKED), and `check_raw_health.py` learns `cardrush`. Daily report: pages fetched, header totals, ids seen vs headers, parse failures, products seen/new/gone, identity outcomes by refusal code, quarantine count, bytes stored |
| Lossless | The `verify-lossless` runbook covers the CardRush parser: decode every encoded row back to its original SHA-256 |
| Containment | On the first 403, 429, CAPTCHA/challenge or robots disallow: pause the source (`source_denial`), no retry, tell the owner. Never rotate IPs or user agents, or use a browser, to get past a block |
| Images | Never requested, stored or shown publicly. No R2 mirror for CardRush |

**Rollback triggers.** On any one of these: stop the cron, keep the data, report.
- any denial or challenge;
- a robots.txt change that disallows a needed path;
- more than 5 transient failures in a day;
- more than 2% of list pages fail to parse;
- a header total that moves more than 10% day-on-day;
- any wrong-print match found on review;
- CardRush stored bytes above 5 MB/day over 48 h (§F budget), or the 90-day fit going negative at stress B;
- daily RAW admission rows above 80%;
- any CardRush value visible publicly before cutover;
- any message or notice from RUSH.

**Procedure:** the owner disables the cardrush cron in Railway, and any shared-module rollout is reverted with
`collector_variables.restore` (`STAGING_DELIVERY.md:350-377`).

---

## F. Capacity

**Owner figures.** MEASURED by the owner (capacity session 14, `storage-rates` run 38898278774, 2026-10-16):
- room to the 3 GiB reserve **2,938 MB**;
- planning **23.35 MB/day**;
- stress B **27.58 MB/day**.

**Fit rule** (`scripts/ops/storage_rates.py` `fit()`): need = (rate + new) × 90 + one-off ≤ room, at planning
**and** stress B (owner rule).
- The 23.35/27.58 run is not committed; the newest committed rates are 23.10/26.41 (session 13).
- Stress A (42.79 in session 13) already fails without CardRush and is not the owner's gate.

### F1. Without CardRush

| Rate | 90-day need | Margin | Runway |
|---|---|---|---|
| Planning 23.35 | 2,101.5 MB | +836.5 | 125.8 d |
| Stress B 27.58 | 2,482.2 MB | +455.8 | 106.5 d |

With about a 27 MB one-off, the room for a new recurring source is **9.0 MB/day at planning** and **4.76 MB/day at
stress B**. Stress B is binding.

### F2. CardRush per day and one-off (ESTIMATE from MEASURED page sizes)

| Component | E (encoded RAW, recommended) | P (plaintext RAW) | Basis |
|---|---|---|---|
| Daily list pages (145) + `/new` (3) | 148 × 12 KB = 1.8 MB | 148 × 45 KB = 6.7 MB | 400 KB raw per page (MEASURED). E is same-URL dictionary encoding (≥25% saving required); 12 KB ≈ 3% of raw, because list order shifts daily, which is worse than Yuyu's 0.9% and SNKR's 2.7% product pages (CARRIED FORWARD). P is TOAST about 9× (zlib-1 measured 29 KB; pglz is weaker) |
| Weekly sweep (about 27/day) | 0.3 MB | 1.2 MB | same per page |
| Observations | 5,000 × 250 B = 1.25 MB | 1.25 MB | 状態A mapped only: about 6,900 candidates × about 72% exact (§1.5). No PSA10 rows while OFF |
| Freshness and attempt churn | 0.05 MB | 0.05 MB | about 150 work units/day (list pages, not products) |
| **Per day** | **≈3.4 MB** (range 2.0–5.5) | **≈9.2 MB** | |
| One-off | anchors 148 × 45 KB ≈ 6.7 + first sweep 189 × 45 KB ≈ 8.5 + candidates 14,820 × 600 B ≈ 8.9 + mappings about 3 → **≈27 MB** | same | |

Not proposed: daily product-page capture. That would be 14,820 pages/day, over 1 GB/day of raw, and beyond the
daily admission limit.

### F3. Fit with CardRush (need = (rate + new) × 90 + 27)

| Scenario | Planning: need / margin | Stress B: need / margin |
|---|---|---|
| **E-mid (3.4/day)** | 2,434.5 / **+503.5** | 2,815.2 / **+122.8** |
| E-high (5.5/day) | 2,623.5 / **+314.5** | 3,004.2 / **−66.2 does not fit** |
| P (9.2/day) | 2,956.5 / **−18.5 does not fit** | 3,337.2 / **−399.2 does not fit** |

**Verdict.**
- CardRush fits at both rates **only with dictionary-encoded RAW**, and only while it stores ≤ 4.7 MB/day.
- Plaintext RAW does not fit.
- The margin at stress B is about +123 MB. So S4 measures real `pg_column_size` per page before the full daily run is enabled.

### F4. If it doesn't fit (measured in S4/S5)

In order of preference:
1. Store the item block only. This is a RAW-semantics change and needs an owner decision. The item block is
   310 KB of the 400 KB page, so the saving is modest.
2. Skip storing a RAW body that is identical by hash to the previous same-URL body, and store a reference row
   only. This changes the RAW writer used by both collectors.
3. Narrow scope to versions without a Yuyu price.
4. Move RAW to R2. That is the data-platform design, an owner decision; a paid service is RED.
5. Grow the volume (owner, paid).

Not proposed: enabling `raw_snapshots` retention (it deletes evidence), or a 48 h freshness target (it changes a
shared decision).

If another one-off lands first (for example the remaining-50 batch, about 111 MB at session 13), re-run
`storage-rates` and this table before S4.

---

## G. Delivery sequence

- **Ground rules.** All work is on staging, one staging delivery at a time. Every session after S0 is DATA lane
  with a regenerated `STAGING_MISSION.json`.
- **Quiet windows.** No merges 19:30–20:30 UTC. No collector change 02:00–06:00 UTC. Collector releases only
  06:00–23:00 UTC.

| Session | What | Lane / level | Canary | Owner approvals |
|---|---|---|---|---|
| **S0 audit** | **Done 2026-10-16** (this revision): 74 requests, §0–§1 | plan only, GREEN | — | — |
| **S1 schema + guards** | Migration (D1, D2); `SOURCE_INSTRUMENTS` registration and public-series hiding (D3); tests. No collector code | DATA, AMBER (migration) | — | Owner runs `alembic upgrade head` (backup under 24 h) |
| **S2 shared modules** | `opcg_source_identity` CardRush identity + vectors; `from_cardrush_candidate`; `PARSERS`; freshness list-page unit; tooling (COLLECTORS, NAMES, cap 11, lane, state, raw health). One sequential 10-service rollout with rollback restore | DATA, AMBER | existing collectors canary per `STAGING_DELIVERY.md` | Q11 |
| **S3 collector package** | `services/cardrush_collector/` + Dockerfile, built and tested on fixtures from §1 only (mocks before live). No deploy | DATA, AMBER | — | — |
| **S4 activation canary** | Owner creates Railway service `cardrush-collector` (cron off) and sets variables. Days 1–3: **OP-01 group, 4 pages** daily. Days 4–7: 5 groups (about 20 pages). Then all 145. Measure stored bytes per page, identity gate (C2), drift. Observations written, hidden | AMBER new source + **RED (Q1, legal)** | 4 → 20 → 145 pages | Q1 acceptance; Railway service; cron on; budget envelope |
| **S5 shadow (≥14 days)** | No code. Daily report: storage-rates, denials, parse, identity, CardRush 状態A vs Yuyu sell divergence; proposed cutover date | GREEN observe | — | — |
| **S6 cutover** | `SOURCE_SEMANTICS` CardRush entry + `SOURCE_SEMANTICS_VERSION` 3→4, CardRush resolver in `print_market_index.py`, public attributed series; release notes on the one-day movement break | DATA, **RED (methodology)** | single date, before the 20:00 UTC snapshot | Q6, Q7, cutover date |
| later | PSA10 graded series (B4) | RED | — | Owner turns PSA10 on |
| — | Any external delivery | RED | — | Blocked until the legal opinion covers CardRush |

---

## H. Owner questions (each with a recommended default)

| # | Question | Default |
|---|---|---|
| Q1 | The CardRush data policy snippet bans automated price collection. Do you accept that risk for recurring staging collection now, or wait for RUSH's written permission or the legal opinion? | Build S1–S3 now (no source calls). Start S4 only after you confirm in writing that you accept this specific clause. Send a permission request to info@cardrush-op.jp in parallel |
| Q2 | Which conditions count as raw? | 状態A = unlabeled only (B1-a); exclude group 42, graded, sale, sealed |
| Q3 | Sale prices? | Excluded, provenance only (B2) |
| Q4 | Out-of-stock prices? | Same as Yuyu: eligible up to 7 days old, stock recorded (B3-a) |
| Q5 | PSA10? | Parse and keep in RAW and candidates, with no PSA10 observations while OFF. Exclude 状態難 slabs when turned on (B4) |
| Q6 | CardRush in the Index/Market Value median? | Yes, as a full peer after ≥14 days of shadow, on one cutover date. Accept one break in movement history (B5-a) |
| Q7 | Public display? | After cutover: an attributed "CardRush (状態A)" line per print, values only, no images, no prose. Nothing public before |
| Q8 | User-Agent? | Honest `CardPirateBot/1.0` with a contact URL |
| Q9 | If storage exceeds budget? | Shrink stored RAW first (F4.1–2). Make the RAW→R2 decision before full rollout. Never enable evidence deletion |
| Q10 | Network access for collection | Resolved for the audit. This session reached `www.cardrush-op.jp` (the earlier session could not). Confirm that the Railway collector egress is allowed in S4 |
| Q11 | Collector rollout cap 10 → 11 services? | Yes, in S2 |
| Q12 | Request spacing and slot? | 5 s (3 s floor), one run per day at 16:00 UTC, about 17 min |
| Q13 | Grade field name and vocabulary? | `grade_key` with `raw:*` / `graded:<grader>:<grade>[:flawed]` (D1), no backfill |

---

## Risks

- **Policy.** This is the strongest risk. The snippet is specific, and a notice from RUSH means stop (a rollback trigger).
- **Storage margin.** At stress B the margin is +123 MB at E-mid, and it goes negative above about 4.7 MB/day.
  S4 must measure before the full run.
- **Identity.** About 24% of raw candidates are variants among several prints for their code. Until variant
  evidence is reviewed, those prints get no CardRush value.
- **Pagination drift.** In-stock-first ordering can skip items within a run. The lossless count catches this and
  pages are re-queued.
- **Methodology break.** S6 starts a new Market Value segment for every print. 7D/30D windows are unavailable for
  7/30 days after cutover.
- **Public leakage.** Without D3, CardRush B, C, damaged and sale rows would appear in public charts the moment they are written.
- **Shared RAW admission.** CardRush uses the same daily admission as Yuyu and SNKRDUNK, but needs only about 150 rows/day.
- **Dealer-ask bias.** Two of three median inputs would be shop asking prices.
