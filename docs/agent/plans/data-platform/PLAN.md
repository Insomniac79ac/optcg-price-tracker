# Data Platform and Source Expansion plan

Status: **PLAN ONLY**, for owner review. Written 2026-10-09 on base `origin/staging`
3fc3a9c. No code, PR, deploy, staging write, collector, account, API key or
application was made. Research used public pages, robots.txt files, terms pages,
one public Cardmarket price-guide download and a few public product pages only.

Every number is **MEASURED** (with its source and time) or **ESTIMATED**. Legal
statements are **research, not legal advice**. **INFERRED** means not directly
verified. Quoted terms were read on 2026-10-09 unless marked otherwise.

Owner direction (2026-10-09): Card Pirate's product includes a **data service**.
Other platforms pull prices from Card Pirate's index and sources, and the consumer
site is one client. The B2B feed moves into the core roadmap. Onchain anchoring
(`plan/onchain-phase1`) is part of the data product's trust story. This
supersedes PROJECT_HANDOVER §8 ("do not expand source scope") **for planning
only**. Building any new source still needs approval of this plan.

Binding throughout: staging only, production RED, PSA10 OFF, and every rule in
`docs/agent/INVARIANTS.md`. That covers exact identity, the Yuyu sale-price policy,
receipt-gated Market Value and immutable history.

---

## Plain summary

1. **Card Pirate cannot yet sell data from any source without permission.**
   - **SNKRDUNK:** its terms ban scraping and commercial use without consent, and
     the English terms ban selling or licensing "any information obtained from
     the Service".
   - **Yuyu-Tei:** its terms do not mention scraping, but they ban "unauthorized
     reprinting" of site content "in all cases".
   - **Cardmarket:** prices may be usable inside an app from its free daily file.
     Its terms require written agreement for display via the API and forbid
     redistribution.
   - **eBay:** its licence forbids price indices, price modelling and resale of
     its data without eBay's written consent.
2. **The public site is on firmer ground than a paid feed, but SNKRDUNK is a live
   risk today.**
   - The current SNKRDUNK collector conflicts with SNKRDUNK's no-scraping clause on
     its face.
   - **The owner should decide how to handle that now**, independent of the data
     product.
3. **The first sellable product should be Card Pirate's own derived numbers, not
   raw shop prices.**
   - It contains per-card Index values in yen, the Market Value series and
     release aggregates.
   - It is delivered as a small REST API plus a daily file.
   - Each day is fingerprinted and anchored, so a buyer can prove the numbers were
     never changed afterwards.
   - The first customers are onchain card platforms. None of them has an
     independent Japanese One Piece fair-value feed today.
4. **Permission comes first.**
   - Email Yuyu-Tei and SNKRDUNK's operator (SODA) asking for written permission
     to publish and license derived prices. Get a short legal review.
   - The engineering work can be built on staging in parallel. Selling, or giving
     data to any outside party, waits for written permission.
5. **New sources should be added slowly and in a fixed order.**
   - Order: Cardmarket's free daily file (a single download a day, Japanese sets
     only, for context), then a licensed Japanese sold-price feed (Aucfan), then
     shops that grant permission (Torecolo, Card Rush, magi).
   - eBay only with a signed eBay agreement.
   - English-edition cards come later, as their own catalogue and never mixed with
     Japanese.
6. **Storage is the limit.**
   - Today staging uses 3,568 of 10,000 MB, with a 3 GiB reserve.
   - Any new page-scraping source needs the capacity mission's storage verdict
     first. The Cardmarket file is tiny.
7. **Owner actions:**
   - send 4 permission emails (Yuyu-Tei, SODA, Cardmarket, Aucfan); drafts are in §G;
   - get a short legal opinion;
   - decide the SNKRDUNK question;
   - choose the first design-partner customer.

---

## 0. What exists today (MEASURED from repo at 3fc3a9c unless marked)

| Area | Fact | Source |
|---|---|---|
| Identity | `CanonicalCard → CardPrint → SourceCardMapping → PriceObservation`. Exact print key is `(canonical_card_id, language, release_product_id, official_asset_variant)` | INVARIANTS.md:8; models/card_print.py:229-238 |
| Language | `CardPrint.language` exists (String(8), NOT NULL). The importer hard-codes `"jp"`. `ReleaseProduct.source_catalogue` allows `bandai_jp`, `bandai_asia_en` and `bandai_en`, but only `bandai_jp` is seeded | card_print.py:245; print_import_planner.py:70; release_product.py:9-23 |
| Catalogue | 4,316 active verified CardPrints (2,710 CanonicalCards), all Japanese | STATE_VERIFICATION.md:47 |
| Coverage | Mapped 2,635; operational 2,630; fresh usable 2,398; both sources 334; zero source 1,681 (2026-10-08 14:11Z) | handoff capacity75-session6/HANDOFF.md:111-117 |
| Currency | `PriceObservation.price_jpy` Integer. No currency column. Invariant: "Prices are stored in JPY" | price_observation.py:301; INVARIANTS.md:71 |
| Price types | Per-source strings: Yuyu `sell` (`buy` is auxiliary); SNKR `floor` and `psa10_asking`. `sold` is read by the index but not written by the collector | yuyutei writer.py:116; snkrdunk writer.py:25-28,419 |
| Market Index | Median of eligible cross-source prices. Yuyu sell ≤7d non-promo; SNKR ≥3 sold in 30d, else floor ≤7d. `INDEX_VERSION=3`. The doc says a future Cardmarket "needs a resolver and nothing else" | docs/market_index.md:11-76; market_index.py:135-148 |
| Market Value | Aggregate (Overall + per release), receipt-gated, insert-only | docs/market_value.md; market_value_forward_publication.md:29-58 |
| Card Pirate Index | Equal-weighted geometric, base 1000. "Every value in this index is JPY … any FX-adjusted variant … would be a new `methodology_version`" | docs/card_pirate_index.md:781-792 |
| Public API | FastAPI, **unversioned**, no partner auth. Public reads: `/prints*`, `/releases`, `/analytics/market-value*`, `/analytics/index*`, `/market/*`, `/search` | app/main.py:116,172-227; api/prints.py; api/market_value.py |
| Auth | Admin `X-Admin-Token`; users via bearer JWT. **No API-key mechanism** | route_inventory.md:86-91 |
| Rate limits | In-memory per-IP fixed window, single process. public_read 300 / 5 min | core/rate_limit.py; settings.py:59-64 |
| Caching | Redis on `/market/*`, `/analytics` (TTL 120 s). None on `prints.py` or `market_value.py` | cache_headers.py; settings.py:89-96 |
| Defect found | `PATCH/POST /market/signal-events/*` writes have **no auth dependency** | api/market.py:266-335 |
| RAW | Postgres `raw_snapshots`, with dictionary encoding (daily-v1, ≤8,192 rows / 32 MiB per day). Private R2 bucket `cardpirate-atlas-evidence-staging` (494 MB, quota unknown) is not used for collector RAW | RAW_STORAGE_WRITER.md; RAW_STORAGE_DAILY_ADMISSION.md:9-11; RAW_STORAGE_READERS.md:13 |
| Continuity rule | `SNKR_PATHS` includes `services/api`, so any `services/api` change is a collector release | scripts/verify_snkr_published_discovery_component.py:20-38 |

**Capacity (MEASURED, newest handoff capacity75-session7a NOTE.md, 2026-10-08 22:12Z):**

- **Volume:** 3,568.06 MB / 10,000 MB.
  - The capacity mission keeps a 3 GiB reserve, so about 3,210 MB of usable
    headroom remains (ESTIMATED arithmetic).
- **Growth:**
  - +90.38 MB in 8 h 29 m across daily-v1 activation, about 256 MB/day if
    extrapolated (ESTIMATED; mixed writer-off/on window).
  - Earlier windows measured about 208 MB/day (session 5) and 171 MB/day
    (session 6).
  - Carried-forward forecast: "14.5–16.4 days to the 3 GiB reserve", from before
    the writer took effect. **Session 7 recomputes it after 2026-10-09 13:56Z.**
- **Encoding (per body):**
  - SNKR: about 867 KB original, about 116 KB plaintext column and about 32 KB
    encoded (72.3% saved).
  - Yuyu: about 224 KB original, about 37 KB plaintext column and about 1.5 KB
    encoded (about 96% saved). Derived from the session-7a table.
- **Request envelopes:**
  - Yuyu: 9,000 per 1,800 s, 55.4 requests per capture, peak window 97.2%.
  - SNKR: 3,100 per 1,800 s, 93% used in one turn (session 5).
- **Railway volumes cannot shrink.** A resize is RED (PROJECT_HANDOVER.md:1013-1015).
- **Quiet windows:**
  - PR80 busy window 2026-10-09 02:00–06:00Z.
  - daily-v1 observation until 2026-10-09 13:56:11Z.
  - Collector releases resume only if session 7's evidence passes.

---

## A. Licensing (first and blocking)

### A0. Method and limits

- **Fetched live:**
  - SNKRDUNK JP and EN terms and robots.txt;
  - eBay robots.txt, and the eBay API Licence via eBay's `edp.ebay.com` mirror;
  - LY Corp, Mercari and magi terms;
  - Torecolo and Card Rush robots;
  - the Cardmarket price-guide file;
  - Japanese statute text via e-Gov.
- **Could not fetch live (403):**
  - `yuyu-tei.jp`, which also blocked this Codespace's IP. The terms come from
    the Wayback copy of 2026-10-05 and robots from 2026-05-01.
  - `cardmarket.com`. The GTC comes from the Wayback copy of 2026-02-23, version
    20/02/2026; robots.txt is unknown.
  - `cardrush.media/data_policy` (search snippet only).
  - `pricecharting.com` and `psacard.com`.
  - Each item is marked where relevant.
- The Codespace 403 at Yuyu-Tei says nothing about the collectors. Session 7a
  measured 0 HTTP 403/429 across all 9 Yuyu shards.

### A1. Japanese law background (statute text verified on e-Gov; case law from background knowledge, NOT verified)

- **Bare prices are facts, not works.** Copyright Act Art. 2(1)(i) defines a work
  as 「思想又は感情を創作的に表現したもの」 ("a creative expression of thoughts or
  feelings"). Art. 10(2) excludes 「事実の伝達にすぎない雑報」 ("miscellaneous facts").
- **A database is protected only if creative** in its selection or systematic
  arrangement (Art. 12-2). A per-card price list is likely not creative
  (INFERRED).
- **Product photos and descriptive text are likely works.** Card Pirate must
  never copy source images or prose.
- **Analysis exceptions:** Art. 30-4 (information analysis) and Art. 47-5 (minor
  use incidental to analysis results) cover incidental copying. They **do not
  override contract**.
- **Unfair Competition Prevention Act (UCPA), 限定提供データ:**
  - Data openly available free to the public is excluded (Art. 19(1)(ix)ロ).
  - Public price pages are very likely not covered.
- **The real risk is contract (the terms of use) and tort.**
  - Tort: 翼システム (Tokyo DC 2001) held wholesale copying of a non-copyright
    database tortious. *Not verified this session.*
  - Contract: the binding force of browse-only consent under the 定型約款 rules
    (Civil Code 548-2) is weaker but not zero. *Not verified.*

### A2. Yuyu-Tei (retailer; asking 販売価格 and buy-list 買取価格)

Terms: https://yuyu-tei.jp/info/rule (Wayback 2026-10-05, page dated 2019年2月20日
改定). Operator: 株式会社スカラプレイス.

| Clause | Japanese (verbatim) | English |
|---|---|---|
| 適用範囲 | 「この利用規約…は商品購入の意図またはその他の目的の有無にかかわらず…情報の閲覧、その他あらゆる付随するサービスなど全てのサービスの利用に適用されます。…お客様は本規約に同意しているものとします。」 | Applies to all use, including browsing information, whatever the purpose. Visitors are deemed to agree. |
| 著作権について | 「当サイトにて使用されている画像及び文章、コンテンツの権利は当店に帰属します。如何なる場合であっても無断での転載を禁止といたします。」 | Rights to images, text and content belong to the shop. Unauthorized reprinting is prohibited in all cases. |
| 適用範囲 (resale) | 「自己又は第三者の利益を図る目的で転売するためのご注文はできません。」 | No orders for resale. This covers goods, not data. |
| 禁止事項 (member list) | No scraping, crawling, commercial-use or third-party-provision item. | — |

- **robots.txt** (Wayback 2026-05-01): no Disallow lines. There are crawl-delays
  for Slurp, serpstat, bing and Ahrefs only.
- **API, partner or affiliate programme:** none found.
- **Contact:** info@yuyu-tei.jp, TEL 0586-64-9710 (https://yuyu-tei.jp/info/act).
- **Not retrieved:** the body of the FAQ entry 「著作権について」.

### A3. SNKRDUNK (marketplace; lowest ask and sold 売買履歴)

**JP terms** (https://snkrdunk.com/terms, revised 2026年9月30日; 株式会社SODA;
Japanese law, Tokyo DC). Item numbers are INFERRED from list order.

| Clause | Japanese (verbatim) | English |
|---|---|---|
| 第1条3項 | 「利用者は、第2条1項に定める会員登録を行うことにより、本規約の全文を確認し、本規約に同意をしたものとみなされます。」 | Consent is deemed on **member registration**. |
| 第7条(6) | 「当社の事前の同意を得ずに営利を目的として本サービスを利用する行為…本サービスが予定している利用目的と異なる目的で本サービスを利用する行為。」 | Using the Service for profit without prior consent, or for an unintended purpose. |
| 第7条(13) | 「クローリング、スクレイピング又はこれらと類似する手段により本サービスにアクセスし、又は本サービスに関する情報を取得する行為。」 | Accessing or obtaining information by crawling, scraping or similar means. |
| 第7条(16) | 「他の利用者の情報を本サービスの利用に必要な範囲を超えて、収集したり蓄積したりする行為。」 | Collecting or storing other users' information beyond what use requires. |
| 第9条1項 | 「本サービスを構成するすべてのコンテンツ（写真、画像、デザイン、文章等）に関する権利は、当社又は当該権利を有する第三者に帰属しています。」 | All content (photos, images, design, text) belongs to SODA or the rights holders. |

**EN terms** (https://snkrdunk.com/en/terms, updated 2026-09-30; Singapore law for
users outside the US/HK):

- **Art. 1(3):** consent is deemed by "actual use of the Service".
- **Art. 3:** bans "Using the Service for commercial purposes without the prior
  consent of the Company" and "…copying, distributing, transmitting, displaying,
  … publishing, licensing, creating derivative works from, transferring, or
  selling any information or software obtained from the Service".
- **Art. 4(4):** no use "beyond the intended use of the Service … provided,
  however, that this shall not apply when the prior consent of the Company and
  the licensors … is obtained."

**robots.txt** (live): `*` disallows account and transaction paths, `/en/v1/*` and
`/item-histories`. Product pages and `/apparels/{id}/sales-histories` are not
disallowed.

**Channels:**
- information@snkrdunk.com;
- the JP help form at https://help.snkrdunk-guide.com/ja;
- **bd@soda-inc.jp** (SODA alliance team; from a 2025 PR Times snippet,
  **unverified**);
- スニダンBiz (https://snkrdunk.com/information/267) covers trade, not data.

**Existing-operations finding (new):** Card Pirate's SNKRDUNK collector already
does what 第7条(13) prohibits.
- The JP deemed consent attaches to registration, and the collector is logged
  out. The EN terms use browse-to-agree, and the collector reads the
  `/en/trading-cards/{id}` mirror.
- So the conflict is real but its enforceability is unclear.
- This is a **RED legal/compliance matter** under AUTONOMY_POLICY.md. It is
  raised in §G as decision G1. **Nothing was changed.**

### A4. Cardmarket (EU; EUR)

- **API: closed to new applicants.**
  - "Currently, we are not accepting applications for access to the Cardmarket
    API." (https://help.cardmarket.com/en/cardmarket-api)
  - Cardmarket 2025-08-11: "this system replaces plans to expand API access"
    (insight.cardmarket.com, "What's New 7/2025").
  - Even when open, it was "restricted to professional sellers and subject to a
    manual approval process".
  - Dedicated apps may not "constantly only request the public Marketplace
    resources".
  - Limits: 5,000 / 100,000 / 1,000,000 requests a day (private / commercial /
    powerseller), 30,000 marketplace requests a day, 600 a minute
    (apiv2.cardmarket.com docs).
- **GTC 20/02/2026** (German text governs; read via Wayback):
  - **§9:** "The API may only be used for managing your own contents. **The
    presentation of the trading cards and their respective prices require our
    prior written agreement.** The use of the API and the transfer and use of
    data for any other purpose is prohibited."
  - **§10:** "you are prohibited from disseminating or publicly reproducing
    contents of the online platform … unless the dissemination and public
    reproduction is envisaged within the use of the online platform".
- **Free daily files** (MEASURED 2026-10-09 by direct download):
  - Price guide: `downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_18.json`.
    - Game 18 is One Piece. 2.76 MB, 13,384 rows.
    - Fields: `avg, low, trend, avg1, avg7, avg30` and `-foil` twins, all in EUR.
    - No condition or language split.
  - Catalogue files `products_singles_18.json` (12,586) and `products_nonsingles_18.json`.
    - They carry `idExpansion` but no expansion names.
  - Cardmarket 2025-08-11 says these exports are "available to the public and
    updated daily. **Anyone can import and incorporate the data into their own
    applications, no extra permission or access point necessary.**"
  - No licence text addresses resale.
- **robots.txt:** unknown (Cloudflare 403).

### A5. eBay (US/global; asking via Browse, sold via Marketplace Insights)

- **Buy APIs (Browse):**
  - "intended for eBay partners only. You must apply for production access
    through the eBay Partner Network … no guarantee that your application … will
    be approved" (edp.ebay.com buy-requirements).
  - The Dec 2025 call-limits page listed Browse at 5,000 calls/day, with "Buy APIs
    require an additional license".
- **Marketplace Insights (sold data):**
  - Limited Release, and its docs now sit behind sign-in.
  - Community reports from mid-2026 say eBay grants it only to major partners
    (anecdotal).
- **API Licence Agreement** (developer.ebay.com/join/api-license-agreement via the
  edp mirror; date stamp Sept 3, 2025). Section numbers are as referenced
  in-text.
  - **Restricted APIs** = "any eBay APIs that provide information about market
    trends, pricing strategies, sales volumes…"
  - **§8.5:** may not "Electronically distribute via API the Restricted APIs data
    (**either in raw or aggregated form**) or allow [it] … to be downloaded in
    bulk". Pricing tools from Restricted API data need "eBay's express prior
    written consent", and eBay then gets an irrevocable licence to the tools and
    their outputs.
  - **Derivation:** "You must have eBay's express prior written permission to use
    or display eBay Content in any way that enables derivation of … **Average
    selling price** or gross merchandise sold for any eBay category."
  - **§9:** may not "Use eBay Content, either alone or in combination with
    third-party information, to **suggest or model prices** for items listed on
    eBay Site"; "Sell, rent, trade, distribute, lease (or otherwise commercialize)
    … eBay Content".
  - **§8.1:** displayed listings must be ≤6 h stale, other content ≤24 h. Content
    must not be "co-mingled or combined with non-eBay Content". It is to be
    deleted when no longer public.
  - **§5:** eBay owns derived works.
- **robots.txt** (v30.2, Aug 2026): "The use of robots or other automated means
  to access the eBay site without the express permission of eBay is strictly
  prohibited."

### A6. Other Japanese sources

| Source | One Piece? | Prices | Terms (verbatim → English) | robots | API / channel |
|---|---|---|---|---|---|
| **Card Rush** (cardrush-op.jp, 株式会社RUSH) | Yes | Asking; buy list on cardrush.media | data_policy (snippet; 403 live): 「独自コンテンツの無断使用、転載は禁止」 → unauthorised use or reprint banned; bans 「クローリングやスクレイピングを目的として…自動化された手段で…価格やその他コンテンツの情報を取得すること」 → automated price collection; and 「販売価格や買取価格を得る目的で手動による大量のアクセス」 → bulk manual access for prices | Blocks 4 AI/social bots only | None. info@cardrush-op.jp |
| **Torecolo** (NextOne Inc.) | Yes (c1073 singles, c2073 buy list) | Asking, stock, buy list | No 利用規約 or prohibited-acts clause found | `*` allows `/shop/g/`, `/shop/c/`. AI bots get Crawl-delay 10 | None found |
| **magi** (株式会社ジラフ) | Yes | Asking ("¥X~"); sold unconfirmed | Art. 8(v) 「当社の事前の書面による承諾なく、当社のサービス外で、商業目的で…情報…を利用すること」 → no commercial use outside the service without written consent; (dd) no access by non-provided interfaces | AI bots barred from search; Cloud Armor, 1.4 M bot requests in a week | None; written consent |
| **Mercari** | Yes (C2C) | Asking + SOLD | Art. 21(1) 「本サービスを構成するすべての素材に関する権利は、弊社又は当該権利を有する第三者に帰属」 → rights to all materials belong to Mercari or rights holders; Art. 7(3) personal info only within service | Internal `/v1/`, `/v2/` disallowed | No public search API |
| **Yahoo! Auctions** (LINEヤフー) | Yes | Sold (90 days) | Art. 8(3) 「本コンテンツを、当社サービスが予定している利用態様を超えて利用（複製、送信、転載、改変を含みます。）をしてはなりません」 → no use beyond intended (copying, reposting); Art. 15(5) no BOT operation | `/closedsearch/` (sold) **disallowed** | Auction Web API **ended 2018-02-22** |
| **Aucfan** (aggregator) | Yes (ヤフオク, flea markets) | Sold, about 70 bn records | Commercial data licence (it says it will supply 相場データ externally) | — | Sales contact; no public price list |
| Hareruya | **No OPTCG found** | — | — | — | Skip |
| Big Web, Card Labo, Torecacamp, Furu1 | Unverified / probably | — | Not read | Big Web allows all | Verify later |

### A7. Licensing table

Key: **Y** allowed · **N** prohibited · **?** unclear · **W** needs written
permission or a commercial agreement.

| Source | Display on public site | Derived redistribution (index/aggregates to third parties) | Commercial use | Raw-data resale | Driving clause |
|---|---|---|---|---|---|
| Yuyu-Tei | **?** (leaning Y for facts and aggregates) | **? → W** | **?** | **N** (W) | 「如何なる場合であっても無断での転載を禁止」; no scraping or commercial clause |
| SNKRDUNK | **? (leaning N) → W** | **N → W** | **N → W** | **N** | JP 第7条(6)(13); EN Art. 3 "…licensing … or selling any information obtained" |
| Cardmarket — free daily files | **? (leaning Y in-app; confirm)** | **N → W** | **?** | **N** | 2025: "Anyone can import and incorporate…"; GTC §10 no dissemination |
| Cardmarket — API | **W** (and closed) | **N** | **N** | **N** | GTC §9 "prior written agreement" |
| eBay — Browse (active) | **Y with conditions** (EPN approval, 6 h freshness, isolated display) | **N → W** | Only as an eBay-promoting app | **N** | §8.1(b), §9 |
| eBay — sold (Insights) | **N** (access unavailable) | **N** ("raw or aggregated") | **N** | **N** | §8.5; "suggest or model prices" |
| Card Rush / Card Labo | **W** | **W** | **W** | **N** | data_policy (snippet) |
| Torecolo | **?** (leaning Y with care) | **?** | **?** | **N** | No clause found; ask first |
| magi | **W** | **W** | **W** | **N** | Art. 8(v)(dd) |
| Mercari | **?** | **?** (high risk) | **?** | **N** | Art. 21(1) |
| Yahoo! Auctions direct | **N** | **N** | **N** | **N** | robots + LY Art. 8(3), 15(5) |
| Aucfan (licensed) | **W → Y** under contract | per contract | per contract | per contract | Commercial licence |
| PSA cert API | **?** (EUA unreadable) | **?** | **?** | **?** | Cert lookup "for the sole purpose of confirming data" |

### A8. Recommendation: which sources can feed what

| Feed | Today, without new permission | After written permission |
|---|---|---|
| **(1) Public consumer site** | Yuyu-Tei (current practice; attribution; no images or prose). Cardmarket price-guide file as EUR context, after written confirmation is requested and pending (lean yes). SNKRDUNK **only as an owner-accepted risk (G1)** | + SNKRDUNK, Torecolo, Card Rush, magi, Aucfan (context) |
| **(2) Paid data product** | **Nothing.** Even Card Pirate's own Index is derived from Yuyu-Tei + SNKRDUNK. Recommended posture: no external delivery, paid or free, until written permission (or a legal opinion) covers both index inputs | Derived values only (Index, Market Value, release aggregates, spreads), with each source's permission on file. Raw per-source quotes only where a licence explicitly grants resale |
| **(3) Neither, without a deal** | eBay (any price aggregate), Yahoo! Auctions direct, Mercari direct, magi, Card Rush, Cardmarket API, PSA data | — |

The Index is a single median over **both** current sources. A paid product therefore
needs permission from **both** Yuyu-Tei and SNKRDUNK. A "Yuyu-only" index for sale
would be a **methodology change (RED)**, so this plan does not propose one.

---

## B. Data product definition

### B1. Customers and needs

| Customer | Need | Fit for v1 |
|---|---|---|
| Onchain RWA / gacha platforms (Collector Crypt, Courtyard, Beezie, Phygitals, Alt) | Independent FMV for **Japanese** cards; tamper-evidence; daily is enough; graded later. None publishes an independent Japanese One Piece feed (INFERRED, §A research) | **Best.** Anchoring is the differentiator |
| Collection / portfolio apps (Collectr-style) | Per-card current value, history, release aggregates | Good |
| Japanese and overseas stores / exporters | Japan-market reference, ask vs buy-list spread | Later (needs buy-list licence) |
| Content sites / creators | Market Value charts, movers, embeddable widgets | Good (cheap tier or attribution-free widget later) |
| Marketplaces | Reference pricing, fraud checks | Later; often competitors of sources (licence conflict) |
| Leveraged / derivatives products | — | **Excluded by licence**, as in the onchain plan |

### B2. Products

| Product | Content | Source basis | v1? |
|---|---|---|---|
| **Index values** | Per-CardPrint daily Market Index JPY, method, source_count, coverage, confidence, freshness | Derived (both sources) | **Yes** |
| **Market Value series** | Overall + per-release, receipt-gated published points | Derived | **Yes** |
| **Release aggregates** | Per-release tracked value, movement, constituent counts | Derived | **Yes** |
| **Card Pirate Index** | Headline index level | Derived | **Yes** |
| History | Daily archived values since the clean start; Sep 27–28 gaps shown as gaps | Derived, immutable | **Yes** (archived only) |
| Per-card current price by source | Yuyu sell, SNKR floor/sold median, labelled by type | Raw per source | **No** until a source licence allows it |
| Regional context (EUR) | Cardmarket trend for Japanese prints | Cardmarket | No (display-only on site) |
| Graded (PSA10) series | Separate category | SNKR psa10_asking | Later (PSA10 OFF) |
| Sealed | Box/pack prices | Not tracked | Later |

### B3. Delivery

- **REST API `/v1`:** read-only, API key, daily-granularity data.
- **Bulk daily files:** JSON Lines + CSV per receipt date, in object storage
  behind signed URLs. Each file carries a manifest with SHA-256 and the day's
  `anchor_v1` root.
- **Webhooks (v2):** "day published" and "anchor confirmed" events only. **No
  intraday price pushes.**
- **Oracle-style attestations:**
  - A daily signed manifest (`{date, index_root, mv_root, digests, methodology
    versions}`), plus per-value Merkle proofs from onchain Phase 1 §A1
    (`/v1/proofs/{print_id}/{date}`). The proof format is reused, not redefined.
  - K0 (OpenTimestamps only) is enough for v1.
  - An Ed25519 manifest signature is a **new signing secret, so RED** (secrets
    policy). It follows the Base-key decision.
- **No feeds for leveraged products:** a licence clause, daily granularity only,
  and refusal of perps, lending-LTV liquidation or margin use cases.

### B4. What Card Pirate can license to customers (given A)

- **Licensing outbound is only possible after inbound rights exist** (§A8).
- Template terms, following the common pattern seen in JustTCG's terms:
  - non-exclusive, non-transferable and revocable;
  - display and internal analytics allowed;
  - **no resale, sublicence or repackaging as a feed**, and no competing API;
  - attribution "Prices: Card Pirate (cardpirate…)" plus each upstream
    attribution that a source licence requires;
  - no use for leveraged or derivative products;
  - caching allowed while subscribed.
- Each licence names exactly which upstream permissions it rests on, so a revoked
  upstream permission maps to the affected product fields.

### B5. Pricing observed (with sources)

| Service | Price | Notes |
|---|---|---|
| JustTCG (justtcg.com/pricing) | $0 / $19 / $49 / $149 per month | 1k–500k req/month; terms ban resale and competing APIs |
| TCG API (tcgapi.dev/pricing) | $0 / $9.99 / $19.99 / $49.99 / $99.99 | Commercial use needs Pro+ |
| Scrydex (scrydex.com/pricing) | $29 / $99 / $399 / custom | One Piece beta; whitelabel at enterprise |
| PriceCharting | Legendary about $49/mo for API + CSV (snippet, possibly dated) | Covers Japanese One Piece; sourced from eBay sales |
| PokemonPriceTracker | $9.99 non-commercial, $99 commercial | |
| Card Ladder | $20/mo or $200/yr Pro (consumer, not API) | eBay licensed its index for its price guide (snippet) |
| TCGplayer API | Closed to new developers ("no longer granting new API access") | |
| Cardmarket | Free daily file; API closed | |
| Scryfall | Free; prices via TCGplayer/Cardmarket partnerships | "Free catalogue, partner-sourced prices" model |

**Recommended pricing (ESTIMATED; owner decision G5):**
- No hobby tier at launch.
- **Design partner:** free 90-day evaluation under a written licence (no
  production resale).
- **Platform:** $149–299/month (daily API + bulk files + proofs, about 50k
  requests/month).
- **Enterprise / onchain:** custom, from about $500/month, with signed manifests,
  SLA and webhooks.

Revenue must not start until §A8 permissions exist. Some sources may require a
revenue share.

---

## C. Identity across markets

### C1. Rules (unchanged invariants, extended)

- **Japanese and English (and other-language) printings are different
  CardPrints, always.**
  - `CardPrint.language` already exists and is part of the exact key.
  - English needs `ReleaseProduct.source_catalogue='bandai_en'` (or
    `bandai_asia_en`) releases. The enum already allows them.
- **No cross-language mapping, ever.**
  - A SourceCardMapping must match `CardPrint.language` with the language
    **explicitly evidenced** by the source: the Cardmarket expansion, a PSA brand
    containing "JAPANESE", or an explicit eBay Language aspect plus title
    agreement.
  - Absence of a language fails closed. It is never defaulted.
- **Cross-language comparison only at `CanonicalCard` level**, labelled "same
  card, different printing", with no substitution, averaging or fill.
- `release_product_id` stays authoritative. English reprint products (PRB-01/02,
  English OP14/OP15 carrying EB04 content) are separate ReleaseProducts. The card
  code prefix is never used.
- **Coverage denominators stay per language.** The JP 4,316 denominator and the
  capacity75 metrics are unchanged; English gets its own.

### C2. English catalogue expansion (ESTIMATED)

- **Size:** about 4,500–5,500 English prints including parallels. Extrapolated
  from Limitless set counts (OP11 156 … PRB02 316) across OP-01..17, EB-01..03,
  PRB-01/02, ST-01..36 and promos.
- **Authority:** https://en.onepiece-cardgame.com/cardlist/ (no robots.txt
  published, 404). Bandai site terms are **not read**; read them before any
  import.
- **Cost:** CardPrint, release and artwork rows only, about 5–10 MB with images
  as URLs not blobs (ESTIMATED). Small.
- **Recommendation:** **defer** until a licensed English price source exists.
  Today none does (§A7). The catalogue itself is low-risk and could come earlier
  for collection tracking. That is owner decision G2b.

### C3. Per-source identification and exact-match feasibility (all ESTIMATED from small samples)

| Source | How cards are identified | Japanese exact-match | Fails closed |
|---|---|---|---|
| **Cardmarket** | Expansion → `idProduct` per art version; `(V.1)/(V.2)/(V.3)` are **ordinal, not semantic** (OP01-120 EN: V.1 trend about €5, V.2 about €113, V.3 about €2,400+). Reprint expansions are separate products. Japanese cards have had their own `-Japanese` expansions since 2023-09-18 (news.cardmarket.com). **Many are now titled "(Non-English)" and carry an article-level language filter including S-Chinese.** Price guide is per `idProduct`, all languages and conditions | Booster/EB/PRB/ST mapping 85–95% after one-time V.n curation per expansion (artwork evidence + admin review). Promos 50–70% | "(Non-English)" expansion prices: **fail closed or flag `mixed_language_aggregate`**. Cannot be a JP-exact price from the bulk file |
| **eBay** | Category 183454. Item specifics: Game, Set, Card Name, Card Number, Language, Rarity, Features, Graded/Grader/Grade/Cert. All seller-entered and inconsistent (e.g. an OP09 reprint listed under Set=OP05) | Raw: **25–40%** exact | **60–75% of raw listings fail closed.** Lots and multi-variation listings 100%. Language often unstated for English |
| **eBay graded + PSA cert** | Cert number → PSA brand "ONE PIECE JAPANESE OP01-ROMANCE DAWN", #120, variety "MANGA ALTERNATE ART" | 70–85% | Free-text variety needs a curated table; PRB reprint labelling unverified |
| **PSA cert direct** | Same; API single-cert lookup, 100 calls/day free | 80–90% | EUA unread |
| Torecolo | Card number in product code/URL (`OP17-109R`), Japanese rarity words, パラレル filters | High (structured codes) | Parallel sub-types need artwork confirmation |
| Card Rush | `{OP09-118}` in name, 【SEC】, `(パラレル/illust:…)` | High | Same |
| Mercari / Yahoo! Auctions | Free text | Low (similar to eBay raw, worse for Japanese abbreviations) | Most |

### C4. Condition, grading and sealed: separate categories

- **New observation dimensions:**
  - `item_class ∈ {raw_single, graded_single, sealed}`;
  - for graded: `grader`, `grade`, `cert_no`;
  - for raw: `condition_source` (verbatim) and `condition_bucket ∈ {NM+, LP, MP,
    HP/DMG, unknown}`.
- **Series never mix item_class, grader/grade or condition bucket.** This
  generalizes the PSA10 rule. Index and Market Value inputs stay `raw_single`
  NM+ only, as today (Yuyu standard stock, SNKR A).
- **Mapping (approximate; verbatim is always kept):**
  - Cardmarket MT/NM, eBay "Near Mint or Better" (400010) and SNKR A map to NM+.
  - Cardmarket EX, eBay Excellent/LP (400011/400015) and SNKR B map to LP.
  - Cardmarket GD/LP and eBay Very Good/MP map to MP.
  - Cardmarket PL/PO and eBay Poor/HP map to HP.
- **The Cardmarket price guide has no condition split.** Its bucket is
  `mixed_condition`, which is display-only and never an Index input.
- **Sealed** keys on a future `SealedProduct` identity, never on a CardPrint.

---

## D. Price semantics and currency

### D1. Price kinds per source (never mixed in one series)

| Source | Kind | Index input? | Display |
|---|---|---|---|
| Yuyu-Tei | `sell` (asking, shop-set) | Yes (current method) | Yes (non-sale only) |
| Yuyu-Tei | `buy` (buy-list) | No | Context only (spread), after permission |
| Yuyu-Tei | sale/promo | **Never** | **Never** (invariant) |
| SNKRDUNK | `sold` median (≥3 in 30 d) | Yes | Yes |
| SNKRDUNK | `floor` (lowest ask) | Fallback (current method) | Yes |
| SNKRDUNK | `psa10_asking` | Never (separate category) | Later, separate |
| Cardmarket file | `trend`, `avg1/7/30`, `low` (EUR, mixed language and condition) | **No** | EU context, labelled "Cardmarket price guide (all conditions)" |
| eBay Browse | active ask (USD etc.) | No | Only with eBay terms (isolated display), probably never |
| Aucfan (licensed) | sold (JPY) | **Candidate**: adding it is a **methodology change, so RED** | Per contract |
| Torecolo / Card Rush | `sell`, `buy` | **Candidate**, same RED | After permission |

The **sale/promo policy generalizes to every source**:
- A promotional, discounted, time-limited or struck-through price is stored as
  provenance only.
- It is never public, never an Index or Market Value input, and the former price
  is never substituted.
- Each new source's parser must classify `promotion_state` fail-closed (unknown
  is treated as sale).

**Immutability generalizes too:**
- Observations are append-only. Reparse never creates a source check.
- Published series, files and proofs are never rewritten.

### D2. Multi-currency design

- **Invariant amendment needed (RED decision, record in DECISIONS.md):** today
  "Prices are stored in JPY".
  - Proposed wording: "Every observation is stored in its **native currency** as
    the source shows it. JPY sources keep `price_jpy`. No conversion is ever
    stored as an observation."
- **Storage (fail-closed design):** a **new table**
  `regional_price_observations`. It reuses the same lineage
  (`source_card_mapping_id`, `card_print_id` composite FK, `raw_snapshot_id`)
  and adds `currency CHAR(3)`, `price_minor BIGINT`, `price_kind`, `item_class`,
  `condition_bucket`, `language_confidence` and `promotion_state`.
  - Non-JPY prices never enter `price_observations`, so no existing reader can
    take EUR as JPY.
  - AMBER additive migration.
- **FX layer:** `fx_rates(base, quote, rate, source, rate_date, published_at,
  fetched_at, raw_snapshot_id)`.
  - Proposed source: the **ECB euro reference rates** (daily, free; reuse terms
    to be verified before build). JPY↔USD goes cross via EUR.
  - The raw XML is stored as RAW, and rates are immutable once stored.
- **Use:** conversions are computed at read time, and each response states
  `fx_source`, `rate_date` and the original amount.
- **JPY index stays JPY.**
  - A future currency selector only displays converted values labelled
    "converted at ECB rate of <date>".
  - An FX-adjusted index would be a **new methodology_version**
    (card_pirate_index.md:781-792), not a toggle on the existing one.
- **Cross-market comparison:** the same CardPrint (Japanese print on Cardmarket
  "(Japanese)" vs Yuyu), each in its own currency, plus a converted view with the
  FX timestamp. It is never averaged into a combined price.

### D3. Regional indices: recommendation

- **Keep the Card Pirate Index Japan-only (JPY, Japanese prints, Japanese
  sources).**
- Possible later **separate regional indices** (an EU index of Japanese prints in
  EUR; an English-print US index in USD), each with its own methodology,
  constituents and receipts.
- **No combined global index.** Prices mix language editions, conditions,
  price kinds and FX noise, which breaks the "same physical product" rule. A
  regional index needs licensed sold data. None is available now (Cardmarket
  file: mixed condition and language; eBay: prohibited).

---

## E. Capacity and architecture

### E1. Per-source budgets (ESTIMATED unless noted; sized against the MEASURED headroom of about 3.2 GB above the reserve)

| Source | Method | Requests/day | RAW per day | Observations per day | Verdict |
|---|---|---|---|---|---|
| **Cardmarket file** | 1 GET of the price guide (2.76 MB MEASURED) + weekly catalogue (2 files) | **1–3** | 2.76 MB raw; about 0.3–0.6 MB gzip (ESTIMATED). Store in **R2**, not Postgres: about 0.5 MB/day, about 15 MB/month | About 3,000–4,000 rows for mapped Japanese products × about 200 B with indexes, so about 0.7 MB/day in Postgres | **Fits easily** |
| ECB FX | 1 GET (about 2 KB) | 1 | Negligible | 3–5 rates | Fits |
| **Torecolo** (page capture) | About 2,000–3,000 OP singles, 24 h freshness, ≥10 s spacing | 2,000–3,000 documents (+ sub-resources if a browser is used; prefer plain HTTP) | Unknown page size. At 40–200 KB plaintext: 80–600 MB/day unencoded; with dictionary encoding 2–15 MB/day | about 0.5 MB/day | **Blocked on the storage verdict.** Needs encoding from day 1, or RAW in R2 |
| Card Rush | Same as Torecolo | Same | Same | Same | Permission + storage verdict |
| Aucfan (licence) | API / file per contract | Contract | Small (JSON) | Depends | Fits if JSON |
| eBay Browse | About 4,000 searches/day to cover JP prints | ≤5,000 (old cap) | JSON about 20–50 KB per call, so 80–200 MB/day | — | **Not recommended** (licence) |
| English catalogue | One-time import + weekly diff | <100 | <20 MB once | — | Fits |
| Data API | Reads only | — | Usage counters about 1 KB per key per day | — | Fits |

**Storage rule:**
- A new page-capture source starts only after the capacity mission publishes its
  24 h forecast (session 7) and the forecast shows ≥90 days to the 3 GiB reserve
  with the new source added.
- Otherwise the RAW body goes to R2 first: Postgres keeps the hash, size,
  pointer and parser version; the R2 object holds the body, write-once and
  lifecycle-locked.
- Bulk files and API exports always live in R2, never in Postgres.

### E2. Collector design per source

- **Cardmarket:**
  - A new `services/cardmarket_ingest` scheduled job (separate Railway cron
    service). Not a browser.
  - Stores each downloaded file as RAW: the R2 body, plus a `raw_snapshots` row
    with hash and pointer.
  - Then parses only products mapped through approved SourceCardMappings.
  - Mapping proposals use the existing proposal/review queue, with V.n curated by
    artwork evidence. **Never auto-approved.**
  - Due-work: one `freshness_work` item per source-day, not per card. A per-card
    "successful check" is defined as presence in that day's file.
  - Absence from the file is **not** a no-listing check. It fails closed and
    freshness does not advance.
- **Page-capture sources (Torecolo etc.):**
  - Reuse the Yuyu pattern: shared due-work, `source_dispatch_budgets` envelope,
    singleton or sharded claims, fail-closed on 403/429/challenge, RAW before
    parse, dictionary encoder, quiet windows.
  - Plain HTTP and robots honoured, including any Crawl-delay published for any
    group (use the strictest).
  - Identify the bot honestly with a contact URL.
- **API sources (Aucfan, eBay if ever):**
  - API JSON responses **are RAW**: stored before parse, hashed, retained by
    policy.
  - Each source's contract retention limit overrides ours. eBay, for example,
    requires deletion when content is no longer public and within 10 days of
    termination.
  - Where a licence forbids long retention, keep only the hash plus the parsed
    observation, and note it as a provenance exception in that source's doc.

### E3. Public Data API

- **Where it lives:** a **new service `services/data_api`** (FastAPI), deployed as
  its own Railway service.
  - It reuses models by importing them read-only.
  - It needs no change under `services/api` for its own endpoints, so it does
    **not** trigger collector releases.
  - Admin stays in `services/api`, and the consumer site keeps using
    `services/api`.
- **Migrations still live in `services/api/alembic`** (a collector release under
  the continuity rule). Options, with this recommendation:
  - (a) Batch all data-platform migrations into scheduled collector releases
    outside quiet windows (default, no verifier change).
  - **(b) Narrow `SNKR_PATHS`** to the modules the SNKR image actually imports
    (AMBER, a verification change that must be proven not weaker).
  - Three plans (onchain, collector-v1, data platform) now need `services/api`
    changes, so **(b) is recommended as an early capacity-mission item**.
    Coordinate with capacity session 7+ and do not pre-empt it.
- **DB access:**
  - A dedicated **read-only Postgres role**.
  - `statement_timeout` 5 s and its own small pool (≤5 connections), so partner
    traffic cannot starve collectors.
  - A read replica later, which is a new cost (RED if material).
- **Auth:**
  - API keys, `cp_live_…` and `cp_test_…`, shown once and stored as SHA-256 with
    a prefix for lookup, in `api_clients` and `api_keys`.
  - Scopes per product (`index:read`, `mv:read`, `bulk:read`, `proofs:read`).
  - Each key carries a `license_id` naming the upstream permissions it rests on.
  - Separate from the user JWT and collector-v1 accounts. Admin-only issuance.
  - **A new auth mechanism is RED** (authentication policy). Approving this plan
    approves the design. Production keys stay RED.
- **Rate limits and metering:**
  - Redis token bucket per key: default 10 req/s and a monthly quota per plan.
  - `api_usage_daily(key_id, date, endpoint_group, requests, bytes)`, flushed
    from Redis.
  - The existing in-memory per-IP limiter is unsuitable: it is per-process and
    per-IP.
- **Versioning:** `/v1/...`. Each response carries `methodology_version`,
  `index_version`, `source_semantics_version`, `as_of`, `receipt_date`,
  `license` and `attribution`. Breaking changes go to `/v2`, with ≥6 months'
  overlap promised.
- **Caching:**
  - Data changes once a day, so use ETag + `Cache-Control: public, max-age=300`.
  - Responses vary by key, so the cache is a key-agnostic CDN layer only for
    public metadata.
  - Bulk files are immutable per date: `max-age=31536000, immutable`.
- **Uptime:**
  - Staging is best effort.
  - Production target 99.5% monthly for the API. Bulk files are served from R2.
  - The status page is a later item. **Production is RED.**
- **Security:**
  - No user data in this service.
  - CORS off by default (server-to-server).
  - Keys never logged; the existing redaction covers `api_key`.
  - Abuse handling: revoke the key.
- **Fix noted:** the unauthenticated `/market/signal-events` writes in
  `services/api` should be fixed in their own security PR. That is RED-adjacent
  (auth policy) and **separate from this plan**. Flagged in Risks.

### E4. Endpoints v1 (proposal)

```
GET /v1/prints?release=&language=jp&cursor=          catalogue (exact identity fields)
GET /v1/prints/{print_id}/index?from=&to=            daily archived Market Index (JPY)
GET /v1/market-value?scope=overall|release&from=&to= receipt-gated points
GET /v1/releases                                      release products + aggregates
GET /v1/card-pirate-index?from=&to=                   headline index
GET /v1/days/{date}/manifest                          digests, roots, anchor refs, file URLs
GET /v1/proofs/{print_id}/{date}                      Merkle proof (onchain §A1 format)
GET /v1/bulk/{date}.jsonl.gz                          redirect to signed R2 URL
```

- No per-source raw price endpoints in v1.
- Gaps (2026-09-27/28) come back as explicit `{status:"gap"}`, never as a value.

---

## F. Sequencing

**Combined order.** "Cap" = capacity mission, "OC" = onchain Phase 1 plan
sessions, "CV1" = collector-v1 accounts plan. CV1 is not yet on any branch
(checked 2026-10-09), so its slots are placeholders.

| # | Step | Class | Migration | Collector redeploy? | Blocked by |
|---|---|---|---|---|---|
| 0 | **Owner:** decide G1 (SNKRDUNK); send permission emails (G-drafts); request legal opinion | RED (owner) | — | — | — |
| 1 | Cap session 7: 24 h daily-v1 assessment, 30/90-day storage forecast, storage verdict | (Cap) | — | Rollback only | 2026-10-09 13:56Z |
| 2 | Cap: continuity narrowing of `SNKR_PATHS` (option b), or confirm option (a) | AMBER | No | Yes (verifier) | Step 1 passes |
| 3 | OC session 1: Merkle builder, proof endpoint, OTS, `publication_anchors` | AMBER | 1 table | Yes under (a) | Step 1 (quiet windows) |
| 4 | CV1 first slice (accounts), per its own plan | per CV1 | per CV1 | per CV1 | Its plan |
| 5 | **DP-1** `services/data_api` on staging: `/v1` read endpoints (index, MV, releases, CPI, manifest), read-only role, API keys + scopes, Redis limits, metering. **Internal keys only** | AMBER (new service + additive tables); auth design RED-approved via this plan | `api_clients`, `api_keys`, `api_usage_daily` | Migrations only (batched with 3 under (a)) | Step 2 or a scheduled release |
| 6 | **DP-2** bulk daily files + manifests to R2 (staging bucket), proof endpoint wired from OC session 1 | AMBER | No | No | Steps 3, 5 |
| 7 | **DP-3** invariant amendment (native currency) + `regional_price_observations` + `fx_rates` (ECB) | RED decision → AMBER build | 2 tables | Migrations only | Owner G2a |
| 8 | **DP-4** Cardmarket price-guide ingest (Japanese expansions; EUR; context-only) + V.n curation queue; site display behind a flag | AMBER (new source) | No (uses DP-3) | No (separate cron service) | Step 7; Cardmarket written confirmation **or** owner accepting the public-file statement (G3) |
| 9 | **DP-5 first customer pilot** (external delivery needs production, so RED): one design partner, evaluation licence, daily API + bulk + proofs | **RED** (legal, production, new external party) | — | — | Written permission from **Yuyu-Tei and SNKRDUNK** (or a legal opinion the owner accepts); steps 5–6 verified |
| 10 | OC sessions 5/6 (PSA10 activation, onchain ingestion), per that plan | AMBER | per OC | Yes | Cap pass |
| 11 | **DP-6** licensed Japanese sold feed (Aucfan) as context, then a methodology proposal to add it to the Index | AMBER ingest; **RED** methodology | small | No | Aucfan contract (new paid service, RED) |
| 12 | **DP-7** first permitted page-capture shop (Torecolo or Card Rush) | AMBER (new source, substantial volume) | No | No (new collector service) | Written permission; storage verdict or RAW→R2 |
| 13 | DP-8 English catalogue (`bandai_en` releases, `language='en'` prints), separate coverage denominator | AMBER (large bulk insert) | No | No | Licensed EN price source in sight (G2b) |
| 14 | DP-9 webhooks + signed manifests (Ed25519) | RED (new signing secret) → AMBER | small | No | OC Base-key decision |
| 15 | eBay | **RED** (licence) | — | — | Signed eBay agreement. Default: not pursued |

**First data-product milestone that could serve a real customer: step 9.**
- What it delivers: the "Card Pirate JP Index v1" pilot, with daily per-print
  Market Index (JPY), Market Value series, release aggregates, the Card Pirate
  Index, a bulk daily file and per-value proofs anchored by OpenTimestamps, for
  one onchain design partner.
- Engineering prerequisites: steps 3, 5 and 6.
- Hard gates: written source permission, then the owner's RED go-ahead for
  production.

**Per-step rules (all steps):**
- **Rollback:** native revert. Additive tables are left in place (no destructive
  downgrade). The data_api service is rolled back by deleting it, with no
  dependents. A source ingest is rolled back by pausing its cron, keeping RAW.
- **Verification:**
  - Mocks and fixtures before any live request.
  - Golden vectors for proofs and manifests.
  - Identity fail-closed tests per source (no cross-language map).
  - A strict staging delivery receipt and a natural-operation window.
- **Quiet windows:** steps 2, 3, 5 and 7, or any step touching `services/api`,
  avoid every capacity quiet window. New-source services (8, 11, 12) never
  share an envelope with Yuyu/SNKR and start at ≤10% of their planned budget.

---

## G. Owner decisions and actions

### G-decisions (recommended default first)

**G1. SNKRDUNK terms vs current collection (RED, new).** Options:
- **(a) Recommended:**
  - keep current collection unchanged (no volume increase, no new SNKR endpoints);
  - email SODA for consent now;
  - get a short legal opinion;
  - pause SNKR if SODA objects.
  - Tradeoff: continued exposure while waiting.
- (b) Pause SNKR collection now.
  - The Index drops to Yuyu-only, which is a methodology and coverage impact
    (RED). It would also stall the 75% mission (334 both-source prints).
- (c) Continue without asking. **Not recommended.** It blocks any paid product
  forever.

**G2a. Native-currency invariant amendment.**
- Default: approve the new-table design (§D2).
- Tradeoff: one more table versus the risk of mixing currencies in existing
  readers.

**G2b. English catalogue timing.**
- Default: defer until a licensed English price source exists.
- Alternative: import early for collection tracking only.

**G3. First new source.**
- **Default: the Cardmarket price-guide file**, context-only, Japanese
  expansions.
  - It costs 1 request a day, about 1 MB/day, and has the clearest public
    statement.
  - Send the confirmation email anyway.
- Alternatives:
  - Aucfan: the best data (Japanese sold), but paid, with an unknown price.
  - Torecolo: no explicit ban, but page capture is blocked on storage.

**G4. Data product scope v1.**
- **Default: derived-only** (Index, Market Value, releases, Card Pirate Index,
  history, proofs, bulk). No per-source raw quotes and no graded data.
- Tradeoff: less granular for customers, but legally the smallest ask.

**G5. Pricing approach.**
- **Default: free 90-day design-partner evaluation**, then Platform
  $149–299/month and enterprise custom (§B5).
- Alternative: a usage-metered model. Not recommended before metering exists.

**G6. Approach sources for commercial agreements?**
- **Default: yes, all four now**: Yuyu-Tei, SODA, Cardmarket and Aucfan.
  Torecolo and Card Rush follow after step 8.
- eBay: no for now. Its licence gives eBay ownership of derived outputs and bans
  price modelling.

**G7. Regional index design.**
- **Default:** the Japan-only JPY Card Pirate Index stays as it is. Separate
  regional indices come later, only with licensed sold data. **No combined
  index.**

**G8. Continuity rule.**
- Default: ask the capacity mission to schedule `SNKR_PATHS` narrowing (option b)
  as its next verification item.

**G9. First design partner.**
- Default: Collector Crypt, already in the onchain outreach. Add one line about
  the data feed to that email.

### G-actions (owner sends; drafts below; nothing has been sent)

**1. Yuyu-Tei.** Send to info@yuyu-tei.jp (the contact form needs an order
number). Japanese first, English for the owner's reference.

> 件名：価格データの掲載・ライセンスに関するご相談（Card Pirate）
>
> 遊々亭 ご担当者様
>
> 突然のご連絡失礼いたします。ワンピースカードゲームの日本版シングルカード相場を追跡する
> サイト「Card Pirate」を運営しております、[氏名]と申します。
>
> 現在、貴店の公開販売価格（セール価格を除く通常価格）を参考情報の一つとして、
> 1日1回程度の低頻度で取得し、カードごとの相場指数（複数ソースの中央値）として当サイトに
> 表示しております。画像・商品説明文は一切転載しておりません。
>
> 今後、この相場指数等の「集計・加工後の数値」を、他社サービス（コレクション管理アプリ等）
> へ有償で提供することを検討しております。貴店の利用規約「著作権について」を拝見し、
> 事前にご相談すべきと考えご連絡いたしました。
>
> つきましては、以下についてご意向をお聞かせいただけますでしょうか。
> 1. 当サイトでの、貴店価格に基づく数値の表示（出典「遊々亭」明記）の可否
> 2. 貴店価格を一部に含む集計値（指数・中央値等）の第三者への有償提供の可否と条件
> 3. 取得頻度・アクセス方法についてのご希望（ご指定の方法があれば従います）
>
> 貴店の個別価格をそのまま第三者に再販売することは想定しておりません。
> ご不明点やご懸念があれば、取得方法の変更や停止も含めて対応いたします。
> ご検討のほど、よろしくお願い申し上げます。
>
> [氏名] / Card Pirate / [メール] / [URL]

*English:* Card Pirate tracks Japanese One Piece prices and shows a median index
that uses your regular (non-sale) prices, collected about once a day. We copy no
images or text. We plan to license derived figures (index values and medians) to
other services and ask: (1) may we display figures based on your prices with
attribution; (2) may we license aggregates that include your prices, and on what
terms; (3) do you have a preferred access method or frequency? We will not resell
your individual prices and will change or stop collection if you prefer.

**2. SNKRDUNK / 株式会社SODA.** Send to bd@soda-inc.jp (unverified; cc
information@snkrdunk.com).

> 件名：取引相場データの利用許諾・提携のご相談（Card Pirate）
>
> 株式会社SODA アライアンスご担当者様
>
> ワンピースカードゲーム日本版の相場サイト「Card Pirate」を運営しております[氏名]です。
>
> 当サイトでは現在、スニダンの公開商品ページから、カードごとの最安出品価格および
> 売買履歴の集計値を低頻度で取得し、複数ソースの中央値として相場指数を表示しております。
> 貴社利用規約第7条（第6号・第13号）を確認し、現状の取得方法について事前のご同意をいただく
> べきと判断し、ご連絡いたしました。
>
> 以下についてご相談させてください。
> 1. 現在の取得・表示についてのご同意、またはご指定の取得方法（API・データ提供等）
> 2. スニダンのデータを一部に含む集計値（指数・中央値）を第三者へ有償提供する際の
>    ライセンス条件（出典表記、レベニューシェア等）
> 3. スニダンへの送客（商品ページへのリンク等）を含む提携の可能性
>
> 個別の取引データや出品者情報を再販売することは想定しておりません。
> ご意向に沿わない場合は、取得の停止を含めて速やかに対応いたします。
> ご検討をお願いいたします。
>
> [氏名] / Card Pirate / [メール] / [URL]

*English:* We currently collect lowest-ask and sold-history aggregates from public
SNKRDUNK pages at low frequency and show them in a median index. Having read terms
Art. 7(6)(13), we are seeking your consent. We ask about: (1) consent for current
collection and display, or a preferred method such as an API; (2) licence terms
for aggregates that include SNKRDUNK data (attribution, revenue share); (3) a
partnership that includes referral links. No reselling of individual
transactions. We will stop if you object.

**3. Cardmarket.** Send to the support contact in the Cardmarket help centre
(there is no API application form; applications are closed).

> Subject: Permission to display and license figures derived from your public price-guide export (One Piece)
>
> Hello Cardmarket team,
>
> I run Card Pirate, an independent price tracker for Japanese-edition One Piece
> Card Game cards. Your August 2025 update says the daily product catalogue and price
> guide exports may be imported into applications without extra permission. Before
> using them, we would like written confirmation of the following:
>
> 1. May we display the price-guide values (trend, avg1/7/30) for Japanese-expansion
>    One Piece products on our public site, attributed and linked to Cardmarket?
> 2. May we include figures derived from them (e.g. EUR/JPY spreads, not the raw
>    values) in a paid data API for business customers? If so, on what terms?
> 3. Is there a preferred download frequency (we would fetch once per day)?
>
> We do not use the Cardmarket API, and would not redistribute the export files
> themselves. Thank you,
> [Name], Card Pirate, [email], [URL]

**4. Aucfan (オークファン).** Send to Aucfan's corporate/data sales contact
(find it on aucfan.co.jp).

> 件名：トレーディングカード相場データのご提供（法人利用）について
>
> 株式会社オークファン ご担当者様
>
> ワンピースカードゲーム日本版の相場サイト「Card Pirate」の[氏名]です。
> 貴社が相場データの外部提供を進めていると拝見し、ご相談いたします。
> ワンピースカード（シングル・日本版）の落札・成約データ（カード名、型番、価格、日時、
> 状態等）について、以下の条件をお教えください。
> 1. 提供形式（API・ファイル）と更新頻度、料金体系
> 2. 当サイトでの表示、および集計値（中央値・指数）の第三者への有償提供の可否
> 3. 元データの保存期間に関する制限
> よろしくお願いいたします。
> [氏名] / Card Pirate / [メール] / [URL]

**5. eBay.** **Do not send now** (G6). If it is ever needed, the route is an eBay
Partner Network application plus a written-consent request for "pricing tools"
under licence §8.5. Note that eBay would own the derived outputs.

**6. Legal opinion.** A short engagement with a Japanese IT/data lawyer.
Questions to ask:
- Do the browsewrap terms (Yuyu-Tei 適用範囲, SNKRDUNK EN Art. 1(3)) bind a
  logged-out collector?
- Does 「無断での転載を禁止」 reach bare price facts and derived medians?
- What is the tort exposure for systematic collection (翼システム line)?
- Is licensing derived indices that mix two sources' facts permissible?
- Which law applies to the SNKRDUNK EN terms (Singapore)?

**7. Collector Crypt.** Add one paragraph to the existing onchain outreach (onchain
plan G2): "We are also preparing a daily, anchored Japanese One Piece fair-value
feed (per-card index, release aggregates, Merkle proofs). Would you evaluate it as
a design partner?"

---

## Risks

1. **SNKRDUNK terms vs the current collector (high, existing).**
   - The no-scraping clause (第7条(13)) applies to today's operation, not only to
     the future product.
   - Enforceability is unclear (registration-tied consent), but a cease request
     would remove half the Index inputs.
   - Mitigation: G1(a), the consent request and a legal opinion.
2. **No permission, no product.**
   - Every paid path depends on written permission from at least two parties who
     may refuse or ask for revenue share.
   - The engineering (DP-1, DP-2) stays useful for the consumer site and the
     onchain verifier either way.
3. **Methodology lock-in.**
   - If a source refuses, changing Index inputs is RED and breaks the history
     comparability that customers buy.
   - Mitigation: version the methodology; never silently swap inputs.
4. **Cardmarket language and condition mixing.**
   - "(Non-English)" expansions may blend Japanese and Simplified Chinese, and
     the file has no condition split.
   - Mitigation: display only, `mixed_language_aggregate` flag, never an Index
     input.
5. **eBay licence traps.**
   - eBay owns derived works, bans price modelling and requires 6 h freshness.
   - Any eBay use could taint the data product. Kept out by default.
6. **Storage.**
   - About 3.2 GB of headroom, and the forecast is pending.
   - A careless page-capture source could consume weeks of headroom. Volumes
     cannot shrink, and a resize is RED.
   - Mitigation: storage rule §E1, RAW to R2.
7. **Continuity rule bottleneck.**
   - Three plans need `services/api` changes, so collector releases pile up
     inside narrow windows.
   - Mitigation: G8 / step 2.
8. **Identity drift across languages.**
   - English expansion adds about 5,000 near-duplicate codes.
   - Mitigation: language evidence required on every mapping, separate
     denominators, no defaulting.
9. **Security.**
   - New API keys and a new public surface.
   - Also an **existing** unauthenticated write route
     (`/market/signal-events/*`, api/market.py:266-335), which should get its own
     security fix (RED auth policy), outside this plan.
10. **Customer misuse.**
    - FMV used for lending or liquidation.
    - Mitigation: licence exclusion, daily granularity only, no webhooks on
      price moves.
11. **Unverified research.**
    - Yuyu-Tei terms are from the Wayback copy and not live.
    - The Card Rush policy comes from a snippet.
    - The bd@soda-inc.jp address is unverified.
    - The Cardmarket GTC is the English informational version (German governs).
    - The Cardmarket robots.txt is unknown.
    - The PSA EUA is unread.
    - Re-check all of these before any build.
12. **Stale docs.**
    - `docs/yuyutei_collector_operations.md` still describes a once-daily cron.
    - `CURRENT_STATE.yaml` dates from 2026-10-06.
    - Partners reading docs could be misled. Refresh them before any external
      sharing.

---

## Sources (fetched 2026-10-09 unless marked)

- Yuyu-Tei terms: http://web.archive.org/web/20261005051001id_/https://yuyu-tei.jp/info/rule ·
  robots: http://web.archive.org/web/20260501083637/https://yuyu-tei.jp/robots.txt ·
  contact: https://yuyu-tei.jp/info/act
- SNKRDUNK: https://snkrdunk.com/terms · https://snkrdunk.com/en/terms · https://snkrdunk.com/robots.txt ·
  https://snkrdunk.com/information/267
- Japanese statutes: e-Gov (laws.e-gov.go.jp): Copyright Act Arts. 2, 10, 12-2, 30-4, 47-5;
  UCPA Arts. 2(7), 19(1)(ix)
- Cardmarket: https://help.cardmarket.com/en/cardmarket-api ·
  https://insight.cardmarket.com/en/Insight/Articles/whats-new-on-cardmarket-7-2025 ·
  https://apiv2.cardmarket.com/ws/documentation/API_2.0:Main_Page ·
  https://web.archive.org/web/20260223003416/https://www.cardmarket.com/en/Policies/GeneralTermsAndConditions ·
  https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_18.json ·
  https://news.cardmarket.com/en/OnePiece/japanese-cards-and-expansions-on-cardmarket
- eBay: https://edp.ebay.com/join/api-license-agreement · https://edp.ebay.com/api-docs/buy/static/buy-requirements.html ·
  https://web.archive.org/web/20251225183350/https://developer.ebay.com/develop/get-started/api-call-limits ·
  https://www.ebay.com/robots.txt ·
  https://developer.ebay.com/api-docs/user-guides/static/mip-user-guide/mip-enum-condition-descriptor-ids-for-trading-cards.html
- Card Rush: https://www.cardrush-op.jp/ · https://cardrush.media/data_policy (snippet) ·
  Torecolo: https://www.torecolo.jp/shop/c/c1073/ · magi: https://magi.camp/terms/use ·
  Mercari: https://static.jp.mercari.com/tos · LY Corp: https://www.lycorp.co.jp/ja/company/terms/ ·
  Yahoo API changelog: https://developer.yahoo.co.jp/changelog/auctions.html
- PSA: https://www.psacard.com/publicapi/documentation (snippet)
- Comparables: https://justtcg.com/pricing · https://justtcg.com/terms · https://tcgapi.dev/pricing ·
  https://scrydex.com/pricing · https://docs.tcgplayer.com/docs/getting-started · https://scryfall.com/docs/api ·
  https://www.cardladder.com/go-pro · https://optcgapi.com/ · https://www.pricecharting.com (snippets)
- English card list: https://en.onepiece-cardgame.com/cardlist/
- Repo: see §0 citations; handoff `docs/agent/handoff/2026-10-08/capacity75-session{5,6,7a}`;
  onchain plan `plan/onchain-phase1` c2279e4 `docs/agent/plans/onchain-phase1/PLAN.md`.
