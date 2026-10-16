# Japanese price source survey (PLAN ONLY)

Status: **PLAN ONLY**, for owner review. Written 2026-10-16 on base `origin/staging` at `1068d3c`,
branch `plan/source-survey`. STAGING ONLY. Production RED. PSA10 OFF. No code, collectors,
settings, staging writes, source jobs or PR.

Evidence labels:
- **MEASURED**: observed in this session (2026-10-16 14:27-14:45Z) or read from the repo / an
  owner-supplied figure with a named source.
- **CARRIED FORWARD**: from an earlier committed plan (path given). Re-check before use.
- **UNVERIFIED**: a web-search snippet or third-party page, not the source site itself.
- **ESTIMATE**: my assumption or arithmetic. Every coverage, independence and byte figure for a
  candidate is an ESTIMATE until the audit in §4 runs.

---

## Plain summary (for the owner)

1. **The live audit could not run.** This cloud environment's network policy refuses every
   candidate host (proxy 403 on CONNECT, MEASURED for aucfan.com, magi.camp, fullahead-tcg.com,
   suruga-ya.jp, dorasuta.jp, jp.mercari.com, and yuyu-tei.jp too). Zero requests reached any
   candidate. This survey is a desk study (search snippets + earlier plans); §4 is the audit to
   run once the hosts are allowed (D1).
2. **Add next, in this order:** (a) **Aucfan** as the only clean route to real *sales* prices
   (Yahoo! Auctions and flea-market sold data), by licence, not scraping; send the enquiry now.
   (b) **Dorasuta buyback list**: a third, genuinely different signal (what shops pay), cheap
   because it updates weekly. (c) **magi**: collector-to-collector sold listings, but only with
   magi's written consent; its terms forbid commercial use without it.
3. **Legal flags:** magi's terms ban commercial use outside the service without written consent
   (CARRIED FORWARD). Aucfan shows prices only to paying members and sells data commercially, so
   it is a contract, which is a paid service (RED). Suruga-ya, Fullahead and Dorasuta terms are
   unread (hosts blocked).
4. **Storage:** Dorasuta (~0.1 MB/day) and Aucfan (~1 MB/day) fit alongside CardRush at both
   rates. Adding magi too does **not** fit at stress B (−68 MB over 90 days) unless identical
   pages are de-duplicated or RAW moves to R2. All ESTIMATE.
5. **Not worth adding soon:** Fullahead (another shop ask, likely priced off the same market as
   Yuyu-Tei/CardRush), Mercari/Rakuma (terms, bot defence).

---

## 1. Ranked table

Ranking is by how much each source makes the Index more robust (independent signal first,
then coverage), not by row count. "Independence" = how far its prices are expected to move
apart from Yuyu-Tei asks. All coverage/independence/storage values are ESTIMATE.

| Rank | Source | Signal type | Independence vs Yuyu-Tei | Coverage of ~2,630 operational prints | Legal position | Storage (stored/day; one-off) | Build effort |
|---|---|---|---|---|---|---|---|
| 1 | **Aucfan** (licensed feed) | **Sold** (Yahoo! Auctions, flea markets), raw + graded mixed in titles | **High**: auction clearing prices, many sellers | 35-55% with ≥1 sale in 30 d; higher for chase prints, low for commons | Contract needed (W→Y under licence); paid service = RED. Prices paywalled (¥2,200/mo premium, UNVERIFIED) | ~1.0 MB (JSON); ~10 MB | **High**: free-text titles; 型番 present (e.g. `OP09-119`, UNVERIFIED); must split PSA/ARS/raw, lots, proxies |
| 2 | **Dorasuta** (buy.dorasuta.jp buyback) | **Buyback**, raw; shop asks also exist | **Medium-high**: different signal type; shop sets it, lags asks | 25-45% (buylists cover chase/staple prints) | Terms unread; plan at "collect politely" like Yuyu-Tei only after audit | ~0.1 MB (weekly capture); ~5 MB | **Low-medium**: list pages, weekly cadence (updated Wednesdays, UNVERIFIED) |
| 3 | **magi** (magi.camp) | **Sold** C2C (売り切れ listings keep price), asks; plus magi shop asks/buyback; PSA10 listings | **High** for C2C; medium for magi shop | 60-80% with a sold listing in 90 d | **Written consent required**: Art. 8(v) bans commercial use outside the service without prior written consent; (dd) bans non-provided interfaces; Cloud Armor bot defence (CARRIED FORWARD) | ~2.0 MB; ~20 MB | **High**: free text, condition grades (中古, 状態B), dedupe relists, outliers |
| 4 | **Suruga-ya** | Asks (multi-shop 取り扱い店舗一覧 per product) + buyback (kaitori) | **Medium**: several shops per print | 70-90% (one product per print, e.g. `OP01-120[SEC]:シャンクス`, UNVERIFIED) | Terms unread; affiliate programme exists (a possible sanctioned path, unverified). **Data-quality flag**: a snippet shows OP01-120 SEC at ¥100-620, far below market | ~1.5 MB (list pages); ~30 MB | **Medium**: per-print GL product ids help; parallel split unclear |
| 5 | **Fullahead** | Shop asks + buyback, raw | **Low**: one more shop ask in the same market | 70-90% | Terms unread; 15 single-game EC sites, no store (UNVERIFIED) | ~1.5 MB; ~30 MB | Medium |
| — | CardRush (planned) | Shop asks, PSA10 ask | Low-medium | see `plan/cardrush-source` | Policy snippet bans automated price collection (CARRIED FORWARD) | 2.0 MB; 30 MB (its plan) | its plan |
| — | Mercari / Rakuma | Sold C2C | High | High | Mercari Art. 21(1) rights to all materials; no public API; internal APIs disallowed (CARRIED FORWARD) | — | Not audited |
| — | Torecolo, 王の洞窟, Tier One | Shop asks (± buyback) | Low | Unknown | Torecolo listed as a permission candidate in data-platform §A (CARRIED FORWARD) | — | Not audited |

Why this order beats "most rows first": Suruga-ya and Fullahead would add the most rows, but
mostly as more shop asks that are likely to move with Yuyu-Tei; one more ask makes a median
look stronger without adding a new kind of evidence. Sold prices (Aucfan, magi) and buyback
(Dorasuta) can disagree with asks, which is what lets the Index detect a stale or inflated ask.

## 2. Per candidate

### 2.1 Aucfan (aucfan.com, 株式会社オークファン)
- **Signal:** sold prices aggregated from ヤフオク!, 楽天, Yahoo!ショッピング and flea-market apps;
  ~70 bn records (UNVERIFIED, press release). One Piece listings show 型番 and grade in the
  title, e.g. 「【ARS鑑定 10+】モンキー・D・ルフィ SEC ★ OP09-119 … 」 45,500円, 99 bids
  (UNVERIFIED snippet). Graded and raw are mixed and must be separated by title parsing.
- **Terms / robots:** not read (host blocked). Prices need Aucfan Premium (月額2,200円,
  UNVERIFIED), so scraping would also mean scraping behind a paywall: **not proposed**.
- **Data offer:** Aucfan says it will 「自社の『相場データ』を外部にも積極提供」 ("actively provide
  its market-price data externally", UNVERIFIED press release) and released an **MCP server**
  giving generative AI access to its sold data (announced for 2025-12, UNVERIFIED). Commercial
  licence path is already in data-platform §A6/§A7 (W→Y under contract) and step 11 (DP-6).
- **Structure:** one row per auction/sale, not per variant. Sold history is the product.
- **Cost:** under licence, prefer a daily delta of new sales filtered to One Piece; ~1 MB/day.
  Per-print querying (2,630 calls/day) is only acceptable if the contract allows it.

### 2.2 magi (magi.camp, 株式会社ジラフ)
- **Signal:** C2C listings; sold items stay visible as 「この商品は売り切れです」 with their price,
  e.g. OP05-119 SEC (スーパーパラレル) ¥329,500 and ¥284,000; OP05-060 P-L ¥2,375 / ¥2,000;
  OP05-034 P-R ¥1,200 (UNVERIFIED snippets). PSA10 listings exist (OP01-120 PSA10 ¥128,000
  sold). magi also runs shops (Akihabara; One Piece mail order since 2024-02) and posts buyback
  prices in blog articles (UNVERIFIED).
- **Terms (CARRIED FORWARD, data-platform §A6):** Art. 8(v)
  「当社の事前の書面による承諾なく、当社のサービス外で、商業目的で…情報…を利用すること」
  = "using information … for commercial purposes outside our service without our prior written
  consent" is prohibited. (dd): no access through interfaces magi does not provide. AI bots
  barred from search; Cloud Armor in front.
- **Structure:** card number and rarity code in titles (`OP05-119`, `P-L`, `P-R`, `P-SEC`);
  condition as 中古 / 状態B plus free text ("裏面に小さな白かけ"). Many listings per print;
  some pages show 「最終更新日時:半年以上前」, so sold dates need care.
- **Cost:** set-level "recent sold" list pages, ~150 pages/day × ~8 KB stored ≈ 1.2 MB + rows
  ≈ 2 MB/day. Only with written consent.

### 2.3 Dorasuta (dorasuta.jp, buy.dorasuta.jp; ドラゴンスター)
- **Signal:** buyback price list on buy.dorasuta.jp, updated weekly on Wednesdays; minimum
  buy-price guarantees for some rarities (UNVERIFIED review sites). Singles also sold in stores
  and online (asks).
- **Terms / robots:** not read (host blocked). Audit first.
- **Structure:** unknown; buylists usually list card number + rarity, raw only, one price per
  variant at top condition.
- **Cost:** weekly freshness is enough for a weekly-updated list: ~50 pages/week ≈ 7
  requests/day averaged; ~0.1 MB/day.

### 2.4 Suruga-ya (suruga-ya.jp)
- **Signal:** product pages per print (e.g. `/product/other/GL498403`, titled like
  `OP01-120[SEC]:シャンクス`) listing several shops' prices (取り扱い店舗一覧), plus a buyback
  (kaitori) channel (UNVERIFIED).
- **Terms:** the general terms were not found by search; only affiliate, MyPage and privacy
  terms surfaced. None of those snippets mention crawling (UNVERIFIED).
- **Flag:** a snippet gives OP01-120 SEC used price ¥100-620, implausibly low; possible stale
  page or mis-assigned variant. Measure in §4 before trusting anything.
- **Cost:** per-product daily capture (~2,630 pages × ~10 KB) ≈ 26 MB/day does **not** fit;
  list/search pages only, ~1.5 MB/day.

### 2.5 Fullahead (fullahead-tcg.com)
- Shop asks + buyback, 15 game-specific EC sites, no physical store, plans eBay sales
  (UNVERIFIED, BEENOS press release and comparison sites). One Piece site URL not confirmed.
- Low independence expected: another retail ask in the same market. Defer.

### 2.6 Noted only
- **Mercari / Rakuma:** best C2C sold volume, but no public API, internal APIs disallowed, rights
  clause Art. 21(1) (CARRIED FORWARD). Data-platform §A8 puts it in "neither, without a deal".
- **Torecolo, 王の洞窟, Tier One:** small shop asks; revisit only as permission-granting shops.

### 2.7 Side observation (CardRush)
- `https://www.cardrush-op.jp/robots.txt` returned **HTTP 200** from this environment at
  2026-10-16 ~14:28Z (one request, body not read, MEASURED). `plan/cardrush-source` recorded a
  403 at 14:13Z, so its host may now be allowed. That plan's S0 audit may be able to run.

## 3. Storage fit (ESTIMATE)

MEASURED (owner, 2026-10-16, via `plan/cardrush-source` §F): room to the 3 GiB reserve
**2,938 MB**; planning **23.35 MB/day**; stress B **27.58 MB/day**. Rule: (rate + new) × 90 +
one-off ≤ room at both rates.

| Scenario (new on top of today) | New MB/day | One-off MB | Planning margin | Stress B margin |
|---|---|---|---|---|
| Today only | 0 | 0 | +836.5 | +455.8 |
| + CardRush L-mid | 2.0 | 30 | +626.5 | +245.8 |
| + CardRush + Dorasuta | 2.1 | 35 | +612.5 | +231.8 |
| + CardRush + Dorasuta + Aucfan | 3.1 | 45 | +512.5 | +131.8 |
| + CardRush + Dorasuta + Aucfan + magi | 5.1 | 65 | +312.5 | **−68.2 does not fit** |
| + all five candidates + CardRush | 8.1 | 125 | **−17.5** | **−398.2** |

So: at most two new sources besides CardRush fit at stress B without changing storage. magi or
Suruga-ya needs `plan/cardrush-source` §F4 option 2 (store a reference row when a RAW body is
byte-identical to the last capture of the same URL) or R2 (paid, RED).

## 4. Audit to run once hosts are allowed (S0)

Per site: ≤40 requests, one at a time, ≥3 s apart, honest User-Agent, robots.txt first and
obeyed, stop on the first 403/429/CAPTCHA/challenge, no images, HTML only, no login, no paywall.

| Step | Requests | Output |
|---|---|---|
| robots.txt + terms page (+ privacy/data policy) | 2-4 | Quoted clauses with translation: scraping, reproduction, commercial use, API/licence |
| One set list / buylist / sold list page per 3 sets (old, mid, newest) | 6-9 | Card number / rarity / parallel fields, condition labels, variants per product, sold-date exposure, bytes per page (raw and gzip) |
| 20 sampled prints (stratified: 5 commons/uncommons, 5 R/SR, 5 parallels, 5 SEC/manga/alt-art) | ≤20 | Price per print; matched / ambiguous / missing |
| Spare | ≤7 | Pagination / re-check |

Coverage MEASURED = matched / 20 in the sample; total ESTIMATE = share × 2,630 with a
Wilson 95% interval. Independence: for the same 20 prints, compare against our current
Yuyu-Tei price from staging (read-only query): median |log(price/yuyu)|, Spearman rank
correlation, and share of prints differing by >20%. Rule of thumb: Spearman ≥0.95 and median
diff ≤10% = "tracks Yuyu-Tei closely" (low independence). Note this session had no staging DB
access either, so the Yuyu-Tei side also has to come from the audit session.

Aucfan is audited by reading its public data-service pages only (no paywalled prices); the
real answers come from the licence enquiry.

## 5. Recommended order of adding sources

1. **Owner: allow the hosts (D1)** and run §4 for Dorasuta, Suruga-ya, magi (terms only), Aucfan
   (public pages only), Fullahead. No build before that.
2. **Aucfan licence enquiry now** (data-platform §G draft, add the One Piece sold-data and
   PSA10 questions). It is the only sold-price source with a clean legal route, and sales are
   priority (1). Ingest only after a contract (RED: paid service; adding to the Index is a
   methodology change, RED).
3. **Dorasuta buyback** as the first build after CardRush, if §4 finds no ban: new signal type
   (3), lowest cost, low effort. Stored and shown as buyback context, not in the ask median.
4. **magi consent request now**; build sold capture only with written consent. Highest
   independence among scrapeable-in-principle sites, but legally blocked and storage-tight.
5. **Suruga-ya** only if §4 clears its data-quality flag and terms, and storage is solved.
6. **Fullahead, Mercari, Rakuma, small shops:** defer.

## 6. Owner decisions (recommended defaults)

| # | Decision | Recommended default |
|---|---|---|
| D1 | Allow `aucfan.com`, `magi.camp`, `dorasuta.jp`, `buy.dorasuta.jp`, `www.suruga-ya.jp`, `www.fullahead-tcg.com` (and `yuyu-tei.jp` for the comparison) in the project's cloud environment (Project settings → Cloud environment → gear → Network access), then a thread runs §4 | Yes |
| D2 | Send the Aucfan data-licence enquiry | Yes, now; no payment without a separate RED approval |
| D3 | Ask magi (株式会社ジラフ) for written consent to collect and display prices | Yes, now; no magi collection until granted |
| D4 | How buyback and sold prices enter the product | Separate labelled signals beside the ask median; any change to Index inputs is a separate methodology proposal (RED) |
| D5 | Freshness for buyback sources | Weekly is acceptable for a weekly-updated list (it does not change the shared daily freshness rule for asks) |
| D6 | Storage budget per new source | ≤2 MB/day each; total new ≤4.7 MB/day at stress B until dedupe or R2 is decided |
| D7 | Fullahead, Mercari, Rakuma, small shops | Defer; revisit after D2/D3 answers |
| D8 | PSA10 from Aucfan/magi | Capture graded rows into RAW only; PSA10 stays OFF |

## Sources (all UNVERIFIED unless noted)

- Aucfan MCP server press release: https://netshop.impress.co.jp/r/prtimes/items/000000492.000008833
- Aucfan data provision statement: https://www.value-press.com/pressrelease/27402
- Aucfan One Piece sold listings: https://aucfan.com/intro/q-one
- magi terms: https://magi.camp/terms/use ; listings e.g. https://magi.camp/items/278280845 , https://magi.camp/items/386699820
- Dorasuta buyback reviews: https://price-base.com/useful/dragonstar-review , https://minhyo.jp/dragon-star
- Suruga-ya product pages: https://www.suruga-ya.jp/product/other/GL498403 ; affiliate terms https://www.suruga-ya.jp/affiliate_new/af_kiyaku.html
- Fullahead: https://www.beenos.com/file/press-release/6955/20250716_BCR.pdf , https://price-base.com/useful/fulahead-review
- Earlier plans (CARRIED FORWARD): `origin/plan/data-platform:docs/agent/plans/data-platform/PLAN.md` §A6-A8, `origin/plan/cardrush-source:docs/agent/plans/cardrush-source/PLAN.md` §F
- Coverage baseline (MEASURED, repo): `docs/agent/handoff/2026-10-13/capacity75-session12/evidence/coverage-start.json` (operational 2,630; fresh usable 2,398)
