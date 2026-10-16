# Japanese price source survey (PLAN ONLY)

Status: **PLAN ONLY**, for owner review. Written 2026-10-16 on base `origin/staging` at `1068d3c`,
branch `plan/source-survey`. STAGING ONLY. Production RED. PSA10 OFF. No code, collectors,
settings, staging writes, source jobs or PR.

Revision 2 (14:48-15:00Z): live retry after the owner widened network access. Revision 1
(desk study, commit `2d1e451`) is superseded where this says so.
Revision 3 (15:12-15:25Z): Dorasuta buyback follow-up (§2.6) and owner email drafts
(Appendix A: Aucfan, Appendix B: magi). There is no separate Dorasuta plan: the combined plan
on `plan/new-sources` (CardRush thread) reads from this file.

Evidence labels:
- **MEASURED**: observed in this session (requests logged in §7), or read from the repo / an
  owner-supplied figure with a named source.
- **CARRIED FORWARD**: from an earlier committed plan (path given). Re-check before use.
- **UNVERIFIED**: a web-search snippet or third-party page, not the source site itself.
- **ESTIMATE**: my assumption or arithmetic.

---

## Plain summary (for the owner)

1. **What was reachable.** magi and Dorasuta answered and were audited. Aucfan answered its
   very first request (robots.txt) with **429 Too Many Requests** and Suruga-ya with **403**, so
   per the rules I stopped there. Fullahead, Dorasuta's buyback site and Yuyu-Tei are still
   refused by this environment's network policy. Our Yuyu-Tei prices came from our own staging
   site instead.
2. **Add next: Dorasuta's shop prices.** Open robots.txt, member terms with no scraping or
   reproduction clause, one product per print with card number, rarity, parallel, condition and
   stock. Its prices order cards like Yuyu-Tei does but sit at different levels: median 25%
   apart, 10 of 18 cards more than 20% apart (MEASURED). It also prices prints Yuyu-Tei doesn't
   price for us: 6 of the 24 prints I checked.
3. **Keep Aucfan as the route to real sales, by licence only.** It is the only sold-price source
   with a clean path, and it rate-limited an anonymous robots.txt read, so scraping is not an
   option. Send the licence enquiry.
4. **magi is a "permission only" source.** Its item pages do expose sold prices, but finding
   them needs search pages that its robots.txt closes to AI agents (Claude named explicitly),
   and its terms ban commercial use and non-provided interfaces. Ask for consent or drop it.
5. **Storage:** Dorasuta fits if captured "light" (top page daily, full sweep weekly, ~1 MB/day).
   A daily full sweep at plain gzip (~6.5 MB/day) does not fit at stress B. Aucfan on top still
   fits, with a thin margin (+46 MB). All ESTIMATE from MEASURED page sizes.
6. **Revision 3:** the Dorasuta buyback audit still could not run (buy.dorasuta.jp refused by
   the network policy at 15:13Z; 0 requests reached it, §2.6). Email drafts for Aucfan and magi
   are in Appendices A and B, Japanese first; nothing has been sent.

---

## 1. Ranked table

Ranking is by robustness added (independent signal first, then coverage), and by whether a
legal route exists now.

| Rank | Source | Signal type | Independence vs Yuyu-Tei | Coverage of ~2,630 operational prints | Legal position | Storage (stored/day; one-off) | Build effort |
|---|---|---|---|---|---|---|---|
| 1 | **Dorasuta asks** (dorasuta.jp) | Shop **ask**, raw; condition tiers 状態A / 状態A特価 / 状態C(プレイ用); stock count | **Medium, MEASURED**: Spearman 0.984 (same ordering) but median abs diff 25%, 10/18 >20% apart, median ratio 0.87 | **ESTIMATE 85-95%**: every set has a list (60 series MEASURED); every OP-05 print code checked has a row; 6/24 checked prints have a Dorasuta ask but no Yuyu price | robots.txt has no `*` rules (open); member terms Art. 7 bans unlawful/unfair access, nothing on scraping or reproduction; catch-all 「その他当社が不適切と判断すること」 | **~1.0 MB light**; ~10 MB once (ESTIMATE from MEASURED 24 KB gzip/page) | **Low-medium**: server HTML, GET pagination, card number in name |
| 2 | **Aucfan** (licence) | **Sold** (Yahoo! Auctions, flea markets), raw + graded mixed in titles | **High** (ESTIMATE): auction clearing | ESTIMATE 35-55% with a sale in 30 d | **Contract only.** 429 on the first anonymous request (MEASURED); prices paywalled; data sold commercially (UNVERIFIED) | ~1.0 MB (JSON, ESTIMATE); ~10 MB | High: free-text titles, grade split |
| 3 | Dorasuta **buyback** (buy.dorasuta.jp) | **Buyback**, raw | ESTIMATE medium-high (different signal type) | ESTIMATE 25-45% | Not audited: host still refused by network policy on the 15:13Z retry (MEASURED, §2.6); WEB買取 rules readable on dorasuta.jp | ~0.1 MB weekly (ESTIMATE) | Low-medium |
| 4 | **magi** | **Sold** C2C (item JSON `status: traded`, price, `updated_at`), asks; PSA10-heavy | High (ESTIMATE) | Only ~384 active listings browsable without search (MEASURED: 1 singles series, 4 pages × 96) | **Permission only.** robots.txt disallows `/items/search` and `/products/search` for Claude-User, anthropic-ai, ClaudeBot, GPTBot…; terms Art. 8(v) and (dd) (MEASURED) | n/a without consent | High |
| 5 | **Suruga-ya** | Multi-shop asks + buyback (UNVERIFIED) | ESTIMATE medium | ESTIMATE 70-90% | **403 on the first request** (MEASURED); stopped | — | — |
| 6 | **Fullahead** | Shop asks + buyback (UNVERIFIED) | ESTIMATE low | ESTIMATE 70-90% | Not audited: refused by network policy (MEASURED) | — | — |
| — | CardRush (planned) | Shop asks, PSA10 ask | — | see `plan/cardrush-source` | Policy snippet bans automated collection (CARRIED FORWARD) | 2.0 MB; 30 MB (its plan) | its plan |
| — | Mercari / Rakuma | Sold C2C | High | High | No public API; rights clause (CARRIED FORWARD); not audited | — | — |
| — | Torecolo, 王の洞窟, Tier One | Shop asks | Low | Unknown | Not audited | — | — |

## 2. Per candidate

### 2.1 Dorasuta (dorasuta.jp, 株式会社エイアイツー) — MEASURED unless marked

- **robots.txt** (101 bytes): groups only for GPTBot (`Disallow:` empty, i.e. allow),
  OAI-SearchBot, ChatGPT-User (`Allow:`), Googlebot and Googlebot-image (`Disallow:` empty).
  No `User-agent: *` group, so nothing is disallowed for us.
- **Terms** (`/member/agreement`, 通販 会員規約) Art. 7 禁止事項: 「当社のサーバその他のコンピュータに
  不正にアクセスすること」 (no unauthorised access to our servers), 「他の利用者その他の第三者に迷惑と
  なる行為」 (no acts that trouble other users or third parties), 「その他当社が不適切と判断すること」
  (anything else we judge inappropriate). No clause on scraping, automated collection,
  reproduction or commercial use of prices. The terms bind members; we are not one. Art. 8 lets
  them suspend service under 「システムに負荷が集中した場合」 (load concentration), so low rates
  matter. No API or data licence offered.
- **Structure:** `/onepiece-cardgame/series-list` lists 60 series (OP-01…OP-17, EB-01…EB-04,
  PRB-01/02, ST-01…ST-36, a fest set). Each set list (`product-list?sid=…`) is server-rendered,
  40 rows per page, OP-05 = 272 rows over 7 pages, GET pagination
  (`form110200_mode=search&form110200_params[0]=pager&form110200_params[1]=N`). Rows grouped by
  rarity heading (`SEC/スーパーパラレル`, `SP`, `L/パラレル`, `R`, `UC`, `C`). Names carry the
  print: 「モンキー・D・ルフィ(SEC★/パラレル)(OP05-119)」, 「シャンクス(SP/SR/金箔)(OP09-004)【3周年SP】」,
  「ゴール・D・ロジャー(★SEC/ゴールドスーパーパラレル)(OP09-118)」. One product id per print; several
  prices per product by condition: product page `pid=471017` shows 状態A特価 ¥222 (stock 1),
  状態A ¥400 (stock 11), 状態C ¥320 (stock 32). Sold-out rows keep their last price with a
  `SOLDOUT` badge. Reprints are listed under the reprinting set (SP cards of OP-05 under OP-09).
- **Identity risk:** parallel tiers need a mapping table (パラレル, スーパーパラレル,
  レッドスーパーパラレル, ゴールドスーパーパラレル, 金箔/銀箔, WANTED, キャラクターエディション) to our
  `official_asset_variant` p1…p7. Manual mappings first, as usual.
- **Independence (MEASURED, 18 pairs):** Dorasuta 状態A ask vs our current Yuyu-Tei
  `retail_sell` on staging (`/cards?q=<code>`, observed 2026-10-16 ~01:20Z), see §3.
- **Cost:** full sweep ≈ 30 booster/extra sets × 7 pages + 30 decks × 1.5 ≈ **255 pages**
  (ESTIMATE) ≈ 13 min at 3 s. Pages are 191-338 KB raw, **19-31 KB gzip, mean 24.2 KB**
  (MEASURED, 5 list pages). Plain gzip: 255 × 24 KB ≈ 6.2 MB/day + rows ≈ 6.5 MB/day. With the
  RAW writer's dictionary compression ESTIMATE ~6 KB/page (same assumption as the CardRush
  plan; to be measured).
  - **Light mode (recommended):** page 1 of every set daily (the SEC/SP/parallel rows, where
    prices move) + full sweep weekly: 60 + 255/7 ≈ 96 pages/day; ~0.6 MB RAW + ~0.4 MB rows ≈
    **1.0 MB/day** (ESTIMATE). Bulk commons at ¥50-100 change rarely.

### 2.2 Aucfan (aucfan.com) — stopped at request 1

- `GET /robots.txt` → **HTTP 429** (MEASURED 14:48Z). Stopped; no retry.
- Signal, data offer and paywall: see revision 1 / §8 sources (UNVERIFIED): sold data from
  ヤフオク! and flea markets, ~70 bn records, MCP server for AI access, premium ¥2,200/month,
  stated policy 「相場データを外部にも積極提供」. Licence path in data-platform §A6/§A7 (W→Y under
  contract), DP-6.
- A rate limit on robots.txt itself says anonymous automated access is unwelcome. Contract only.

### 2.3 magi (magi.camp, 株式会社ジラフ) — MEASURED

- **robots.txt** (2,884 bytes, Japanese comments): `User-Agent: *` disallows
  `/personal/register`, `/mypage/`, `/items/*/trade/new`. A named group for **Claude-SearchBot,
  Claude-User, anthropic-ai, Claude-Web**, GPTBot, CCBot, PerplexityBot, Amazonbot and others
  also disallows **`/items/search` and `/products/search`**; ClaudeBot gets the same plus
  `Crawl-delay: 1`. Comments (translated): search is 「高コスト経路」 (an expensive path, 2-3
  Elasticsearch queries per request, effectively infinite URL space); 59.0% of 159,124 search
  requests on 2026-09-01 09:00-11:00 JST were such crawlers; ClaudeBot rose to 600k/day from
  2026-10-12 and takes 18.8% of backend time; Cloud Armor rule 1045 DENY. This session is an AI
  agent, so it honours the Claude-User group.
- **Terms** (`/terms/use`) Art. 8 禁止事項, verbatim:
  - (v) 「当社の事前の書面による承諾なく、当社のサービス外で、商業目的で、当社が提供するあらゆるサービス、
    コンテンツ、情報、システム、機能、プログラム等の全部又は一部を利用すること」: using any of magi's
    services, content or information, in whole or part, outside the service for commercial
    purposes without prior written consent.
  - (dd) 「当社が提供するインターフェイスとは別の手法を用いてサービスにアクセスすること」: accessing
    the service by means other than the interfaces magi provides.
  - (bb) no adverse effect on its servers or networks.
  - Art. on IP: all ownership and IP in the service belongs to magi or its licensors.
- **Structure:** item pages carry a JSON object (`magi.vars.itemsShow`) with `status: "traded"`,
  `price` 329500, `selling_price` 339385, `quality`, `created_at`, `updated_at`, `name` with card
  number (e.g. `… SEC OP05-119 …`), condition in free text (`info`, e.g. PSA10), and
  `rakuma_exhibit: true` (listings cross-posted to Rakuma). So sold history exists per item,
  but the only lists outside search are the singles series (`/series/100148/items`, 4 pages ×
  96, mostly active PSA10 asks, no sold rows). Sold items can't be found without the
  disallowed search. Listing titles vary freely (`{OP05-119}`, `P-SEC OP13-119`,
  `[L] {OP06-022}`).
- **Verdict:** no robots-compliant way to collect sold prices at scale; terms ban commercial
  use. Written consent or a data deal only.

### 2.4 Suruga-ya (www.suruga-ya.jp) — stopped at request 1
- `GET /robots.txt` → **HTTP 403** (MEASURED 14:48Z). Stopped; no retry. Treat as "ask first".
  Revision 1's desk notes stand (per-print product pages with multi-shop prices; a suspicious
  ¥100-620 snippet for OP01-120 SEC).

### 2.5 Fullahead, Yuyu-Tei — not reached
- `www.fullahead-tcg.com`, `yuyu-tei.jp`: proxy 403 on CONNECT (MEASURED 14:48-14:49Z). Not
  requests to the sites. Dorasuta buyback: §2.6.

### 2.6 Dorasuta buyback (buy.dorasuta.jp)

**Result: not audited. The host is still refused by this environment's network policy.** The
follow-up ran under the same rules (≤40 requests, one at a time, ≥3 s, robots first, stop on
403/429/challenge, HTML only).

MEASURED:
- 2026-10-16 15:13Z `GET https://buy.dorasuta.jp/robots.txt` → proxy `CONNECT tunnel failed,
  response 403` (agent-proxy `connect_rejected` for `buy.dorasuta.jp:443`). Same at 14:49Z.
  The request never reached Dorasuta. The server-side fetch tool also fails
  (`getaddrinfo ENOTFOUND buy.dorasuta.jp`). `dorasuta.jp` itself stays reachable, so only the
  subdomain needs adding (Project settings → Cloud environment → gear → Network access →
  Allowed domains: `buy.dorasuta.jp`).
- Requests to buy.dorasuta.jp that reached the site: **0 of 40**. No robots.txt, terms, buylist,
  structure or price was observed, so no buyback figure in this file is measured.
- From pages already fetched in revision 2 (no new requests):
  - dorasuta.jp links a ネット買取 site per game; One Piece is
    `https://buy.dorasuta.jp/onepiece-cardgame` (top page, MEASURED link).
  - `/guideline` 中古品買取時の注意事項 (WEB buyback rules): ID check for sellers 18+, no sellers
    under 18; own items only; same-name bank account; 「買取見積(メール発行)の日付より５日経過し
    買取が完了できない場合、査定品の所有権を全て放棄したものとさせていただきます」 (if a buyback is not
    completed within 5 days of the emailed quote, ownership of the items is treated as
    abandoned); 「買取査定金額に対しての交渉はお受け出来かねます」 (no negotiation on appraised
    prices). These are seller rules; nothing on reading or reusing the price list.
  - Store X posts embedded on the top page announce buylist updates per store (e.g. Akihabara
    「買取表を更新しました」, 「明日からの強化買取」), with the caveat 「商品の状態や在庫状況によって減額
    の可能性があり、表示金額の適用外となる場合がございます」 (prices may be reduced for condition or
    stock and may not apply). So posted buy prices are **maximums for top condition**, and
    store buylists can differ from the web list.
- UNVERIFIED (review sites, revision 1): the web buylist updates weekly on Wednesdays; minimum
  buy-price guarantees for some rarities.

ESTIMATE, to replace once audited: weekly capture of the One Piece buylist, ≈30-60 pages,
≈0.1 MB/day stored; coverage 25-45% of operational prints (chase cards and staples); signal
type (3) buyback, new to the Index inputs. Plan for the audit, ≤40 requests: robots.txt (1),
terms/guide pages on the buy site (2-3), One Piece top + 3 set buylists, first and last page
each (≈8), 20 sampled prints matched to §3's Dorasuta asks to measure the ask/buy spread
(≤20), spare (≈8).

## 3. Independence: Dorasuta vs our Yuyu-Tei (MEASURED)

Dorasuta = 状態A list price (higher of two 状態A rows when a 特価 row exists; 【プレイ用】 rows
excluded), fetched 14:53-14:56Z. Yuyu-Tei = `source_values[yuyutei].value_jpy` on the staging
site's `/cards?q=<code>` seed data. Print matched by card code + rarity + release
(base / parallel p1 / SP reprint set).

| Print | Dorasuta ¥ | Yuyu-Tei ¥ | ratio |
|---|---|---|---|
| OP05-036 UC | 50 | 80 | 0.62 |
| OP05-039 UC | 100 | 80 | 1.25 |
| OP05-054 UC | 100 | 80 | 1.25 |
| OP05-011 C | 100 | 80 | 1.25 |
| OP05-073 UC (sold out) | 200 | 80 | 2.50 |
| OP05-019 R | 200 | 120 | 1.67 |
| OP05-015 R parallel | 800 | 980 | 0.82 |
| OP05-034 R parallel | 800 | 580 | 1.38 |
| OP05-067 R parallel | 1,000 | 1,780 | 0.56 |
| OP05-001 L parallel | 1,500 | 1,980 | 0.76 |
| OP05-060 L parallel (sold out) | 5,000 | 9,980 | 0.50 |
| OP09-061 L parallel | 8,000 | 9,980 | 0.80 |
| OP05-118 SEC parallel (sold out) | 800 | 980 | 0.82 |
| OP05-119 SEC parallel (sold out) | 18,000 | 19,800 | 0.91 |
| OP09-118 SEC parallel | 3,000 | 2,980 | 1.01 |
| OP05-067 SP (OP-09) (sold out) | 25,000 | 29,800 | 0.84 |
| OP05-093 SP (OP-09) (sold out) | 6,000 | 5,980 | 1.00 |
| OP05-119 SP WANTED (OP-09) (sold out) | 50,000 | 59,800 | 0.84 |

- n = 18; Spearman 0.984; median ratio 0.87; median |log ratio| 0.223 (≈25%); 10 of 18 differ by
  >20%; for prints ≥¥500 at Yuyu-Tei (n = 12) median ratio 0.83, 4 of 12 >20%.
- Reading: same ordering of cards (expected across a ¥50-¥60,000 range), but levels move
  independently enough to matter, especially L parallels (0.50-0.80). Dorasuta tends cheaper
  on chase cards and dearer on bulk. Sold-out rows are stale asks: store them flagged, don't
  count them.
- **Gap filled:** 6 more sampled prints had a Dorasuta ask but no Yuyu-Tei price on staging:
  OP05-074, -091, -093, -100 SR base (¥200 each), OP05-118 SEC base (¥300), OP13-118 SEC
  parallel (¥7,000; all five OP13-118 prints lack a Yuyu-Tei price). Coverage share estimate
  from this: 6 of 24 = 25% of sampled prints gain a first price (ESTIMATE for the catalogue;
  sample biased to OP-05). Note: base L/R/SR/SEC prints missing Yuyu-Tei prices may be a
  mapping gap on our side, worth a separate look.
- 20 card codes were sampled (5 C/UC, 5 R/SR, 5 parallels, 5 SEC/high); 24 prints across them
  had a Dorasuta ask. 18 had a Yuyu-Tei price to compare, so the comparison has 18 pairs, not 20.

## 4. Storage fit (ESTIMATE)

MEASURED (owner, 2026-10-16, via `plan/cardrush-source` §F): room to the 3 GiB reserve
**2,938 MB**; planning **23.35 MB/day**; stress B **27.58 MB/day**. Rule: (rate + new) × 90 +
one-off ≤ room at both rates.

| Scenario (new on top of today) | New MB/day | One-off MB | Planning margin | Stress B margin |
|---|---|---|---|---|
| Today only | 0 | 0 | +836.5 | +455.8 |
| + CardRush L-mid | 2.0 | 30 | +626.5 | +245.8 |
| + CardRush + Dorasuta light | 3.0 | 40 | +526.5 | +145.8 |
| + CardRush + Dorasuta light + Aucfan | 4.0 | 50 | +426.5 | +45.8 (thin) |
| + CardRush + Dorasuta full daily, plain gzip | 8.5 | 40 | +31.5 | **−349.2 does not fit** |

Dorasuta light fits; Aucfan after it leaves under 50 MB of stress margin, so measure Dorasuta's
real stored bytes (dictionary ratio) before signing for Aucfan volume. Levers if short:
byte-identical RAW de-duplication (CardRush plan §F4 option 2), R2 (paid, RED).

## 5. Recommended order of adding sources

1. **Dorasuta asks, light mode.** The only candidate that is reachable, robots-open, without a
   restrictive clause, structured per print, and measurably independent in level. Build it
   behind mock data first (repo rule), then a canary of 3 sets. Tell the owner if CardRush
   should go first; both fit together.
2. **Aucfan licence enquiry now** (data-platform §G draft; add One Piece sold data, JP card
   numbers, PSA10 question, volume, price). Sales are priority (1) and this is the only legal
   route. Contract = paid service (RED); Index inclusion = methodology change (RED).
3. **Dorasuta buyback** (§2.6): allow `buy.dorasuta.jp`, run the ≤40-request audit (robots, terms, OP-05
   buylist). Weekly cadence, tiny storage, new signal type (3).
4. **magi: written consent request** (株式会社ジラフ). No collection without it.
5. **Suruga-ya: ask before any access** (403 to robots.txt). **Fullahead**: audit only if
   allowed and if a sold or buyback angle appears; otherwise defer.
6. Mercari, Rakuma, small shops: defer.

## 6. Owner decisions (recommended defaults)

| # | Decision | Recommended default |
|---|---|---|
| D1 | Dorasuta asks as the next source after (or alongside) CardRush | Yes, light mode; separate signal labelled `retail_sell`, Index inclusion is a separate methodology proposal (RED) |
| D2 | Count Dorasuta 状態C / 特価 / sold-out rows? | No: store in RAW, count 状態A in-stock only |
| D3 | Allow `buy.dorasuta.jp` and `www.fullahead-tcg.com` in network access for a follow-up audit | Yes for buy.dorasuta.jp; Fullahead optional |
| D4 | Send the Aucfan data-licence enquiry (Appendix A) | Yes, now; no payment without a separate RED approval |
| D5 | Ask magi for written consent (Appendix B) | Yes, now; otherwise drop magi |
| D6 | Suruga-ya | Ask by email before any further request; no retries |
| D7 | Storage budget | Dorasuta ≤1.5 MB/day measured over 48 h, or stop and re-plan |
| D8 | PSA10 rows (magi, Aucfan titles) | RAW only; PSA10 stays OFF |
| D9 | Base-print Yuyu-Tei gaps seen in §3 | Open a separate check of base L/R/SR/SEC mappings |

## 7. Request log (MEASURED, 2026-10-16 UTC)

One request at a time, ≥3 s apart, honest User-Agent `CardPirateSourceSurvey/0.1 (read-only
research; one request at a time)` (first probe used curl's default), HTML only, no images, no
login.

| Site | Requests | Notes |
|---|---|---|
| aucfan.com | 1 | robots.txt → 429; stopped |
| www.suruga-ya.jp | 1 | robots.txt → 403; stopped |
| magi.camp | 6 | robots.txt ×2, /terms/use, one item page, /series/100148/items, /card_titles/129 |
| dorasuta.jp | 13 | robots.txt ×2, top, /onepiece-cardgame, /guideline, /member/agreement, series-list, 5 set-list pages, 1 product page |
| www.fullahead-tcg.com, buy.dorasuta.jp, yuyu-tei.jp | 0 reached | proxy refused (buy.dorasuta.jp retried 15:13Z, still refused) |
| our staging site (vercel) | 20 | `/cards?q=<code>` for the comparison |

Raw bodies were kept in the session scratchpad only (not committed, not stored in staging).

## 8. Sources

- Dorasuta: https://dorasuta.jp/robots.txt , https://dorasuta.jp/member/agreement ,
  https://dorasuta.jp/onepiece-cardgame/series-list , https://dorasuta.jp/onepiece-cardgame/product-list?sid=7202 ,
  https://dorasuta.jp/onepiece-cardgame/product?pid=471017
- magi: https://magi.camp/robots.txt , https://magi.camp/terms/use , https://magi.camp/items/278280845 ,
  https://magi.camp/series/100148/items
- Aucfan (UNVERIFIED): https://netshop.impress.co.jp/r/prtimes/items/000000492.000008833 ,
  https://www.value-press.com/pressrelease/27402 , https://aucfan.com/intro/q-one
- Suruga-ya / Fullahead (UNVERIFIED): https://www.suruga-ya.jp/product/other/GL498403 ,
  https://price-base.com/useful/fulahead-review
- Earlier plans (CARRIED FORWARD): `origin/plan/data-platform:docs/agent/plans/data-platform/PLAN.md` §A6-A8,
  `origin/plan/cardrush-source:docs/agent/plans/cardrush-source/PLAN.md` §F
- Coverage baseline (MEASURED, repo): `docs/agent/handoff/2026-10-13/capacity75-session12/evidence/coverage-start.json`

---

## Appendix A. Email draft: Aucfan (オークファン)

Status: **DRAFT, not sent.** The owner sends it. It replaces data-platform §G-actions 4 (same
asks, plus One Piece specifics and the PSA10 question data-platform H-Q3 asked for). A paid
contract is a new paid service (RED); this email only asks for terms.

- **To:** Aucfan's corporate / data-provision contact (法人向けお問い合わせ on aucfan.co.jp).
  Address not verified: aucfan.com refused this session with 429 and aucfan.co.jp was not
  requested.
- **Fill in:** [氏名] / [Name], [メール] / [email], [URL]. Delete the PSA10 line if the owner
  prefers not to signal graded interest.

### Japanese (to send)

> 件名：ワンピースカード相場（落札・成約）データの法人利用についてのご相談（Card Pirate）
>
> 株式会社オークファン 法人営業・データ提供ご担当者様
>
> 突然のご連絡失礼いたします。ワンピースカードゲーム日本版のシングルカード相場を追跡する
> サイト「Card Pirate」を運営しております、[氏名]と申します。
>
> 貴社が相場データの外部提供を進めておられること、また aucfan.com の MCP サーバーを公開
> されたことを拝見し、データのご提供についてご相談したくご連絡いたしました。
> 当サイトは現在、国内ショップの販売価格をもとにカードごとの相場指数を算出しておりますが、
> 実際の成約価格を加えることで、指数の正確さを高めたいと考えております。
>
> 対象として想定しているデータは以下のとおりです。
> - 対象：ワンピースカードゲーム（日本語版）のシングルカード
> - 項目：商品タイトル、カード番号（例：OP05-119）、成約価格（円）、成約日時、出品元
>   （ヤフオク!・フリマ等）、状態・鑑定の表記（タイトルに含まれる範囲で構いません）
> - 期間：直近の成約に加え、可能であれば過去12か月分
> - 規模：カード約2,600種、1日1回程度の差分更新
>
> つきましては、以下についてお教えいただけますでしょうか。
> 1. 提供形式（API・ファイル・MCP 等）、更新頻度、料金体系、試用（トライアル）の可否
> 2. 当サイトでの表示（出典「オークファン」明記）、および当サイトが算出する集計値
>    （中央値・相場指数）を第三者へ有償提供することの可否と条件
> 3. 取得した元データの保存期間、再計算・監査目的での保管に関する制限
> 4. PSA 等の鑑定品（例：PSA10）の成約データを、未鑑定品と区別して取得できるか
>
> 元データ（個別の成約記録）をそのまま第三者へ再販売することは想定しておりません。
> 貴社の利用規約・データ提供条件に沿った方法でのみ利用いたします。
> ご検討のほど、よろしくお願い申し上げます。
>
> [氏名]
> Card Pirate
> [メール] / [URL]

### English (owner's reference)

> Subject: Business use of One Piece card sold-price data (Card Pirate)
>
> Dear Aucfan corporate sales / data provision team,
>
> I run Card Pirate, a site that tracks prices of Japanese-edition One Piece Card Game singles.
> We saw that Aucfan provides market-price data to outside parties and has released an MCP
> server for aucfan.com, and we would like to discuss a data supply. Our per-card index is
> currently built from Japanese shops' asking prices; adding real sold prices would make it
> more accurate.
>
> The data we have in mind:
> - Scope: Japanese-language One Piece Card Game singles.
> - Fields: listing title, card number (e.g. OP05-119), sold price (JPY), sold date and time,
>   marketplace (Yahoo! Auctions, flea markets, …), condition / grading text (as far as it
>   appears in the title).
> - Period: recent sales, and if possible the past 12 months.
> - Volume: about 2,600 cards, a daily delta update.
>
> Could you tell us:
> 1. The delivery format (API, file, MCP, …), update frequency, pricing, and whether a trial is
>    possible.
> 2. Whether we may display the data on our site (credited to Aucfan), and whether we may
>    provide our own aggregates (medians, market index) to third parties for a fee, and on what
>    terms.
> 3. Any limits on how long we may keep the raw data, including for recalculation and audit.
> 4. Whether sales of graded cards (e.g. PSA10) can be supplied separately from raw cards.
>
> We do not intend to resell individual sale records as they are, and will use the data only
> as your terms and supply conditions allow.
>
> Kind regards,
> [Name], Card Pirate, [email] / [URL]

## Appendix B. Email draft: magi (株式会社ジラフ)

Status: **DRAFT, not sent.** The owner sends it. Until magi answers in writing, Card Pirate
collects nothing from magi (terms Art. 8(v), (dd); robots.txt AI-agent group, §2.3). The email
says plainly that a 6-request survey read happened (§7), so magi hears it from us.

- **To:** magi's operator 株式会社ジラフ, via the magi お問い合わせ form or Jiraffe's corporate
  contact. Address not verified (not requested in this session).
- **Fill in:** [氏名] / [Name], [メール] / [email], [URL].

### Japanese (to send)

> 件名：magi の取引価格データの利用許諾についてのご相談（Card Pirate）
>
> 株式会社ジラフ magi ご担当者様
>
> 突然のご連絡失礼いたします。ワンピースカードゲーム日本版のシングルカード相場を追跡する
> サイト「Card Pirate」を運営しております、[氏名]と申します。
>
> 当サイトでは、カードごとの相場指数を国内ショップの販売価格から算出しております。
> magi の個人間取引の成約価格は、ショップ価格とは異なる独立した相場の指標として大変有益だと
> 考えており、利用のご許諾をお願いしたくご連絡いたしました。
>
> 利用規約第8条（v）「当社の事前の書面による承諾なく、当社のサービス外で、商業目的で…
> 利用すること」および（dd）、ならびに robots.txt で AI エージェントによる検索ページの利用を
> 制限されていることを拝見しております。そのため、書面でのご承諾をいただくまで、magi からの
> データ取得は一切行いません。なお、調査のため 2026年10月16日に robots.txt（2回）・利用規約・
> 公開ページ3ページの計6回、1件ずつ間隔を空けて閲覧したことをご報告いたします。
>
> ご相談したい内容は以下のとおりです。
> 1. ワンピースカード（シングル）の成約データ（商品名、カード番号、成約価格、成約日、
>    状態・鑑定の区分）を、貴社ご指定の方法（データ提供・API・ファイル等）で利用することの可否と条件
> 2. 当サイトでの表示（出典「magi」明記、商品ページへのリンク付き）、および集計値
>    （中央値・相場指数）を第三者へ有償提供することの可否と条件
> 3. 貴社サーバーへの負荷をかけない取得方法・頻度のご指定（1日1回程度の差分を想定）
>
> 出品者の個人情報や個別の出品内容をそのまま転載・再販売することは想定しておりません。
> ご許諾いただけない場合は、その旨を承り、magi のデータは利用いたしません。
> ご検討のほど、よろしくお願い申し上げます。
>
> [氏名]
> Card Pirate
> [メール] / [URL]

### English (owner's reference)

> Subject: Permission to use magi transaction price data (Card Pirate)
>
> Dear magi team at Jiraffe Inc.,
>
> I run Card Pirate, a site that tracks prices of Japanese-edition One Piece Card Game singles.
> Our per-card index is built from Japanese shops' asking prices. Sold prices from magi's
> collector-to-collector trades would be a valuable, independent signal, and we are writing to
> ask for permission to use them.
>
> We have read Art. 8(v) of your terms (no commercial use outside the service without prior
> written consent) and (dd), and that your robots.txt restricts AI agents from search pages. We
> will therefore collect no data from magi until we have your written consent. For
> transparency: on 16 October 2026 we made six requests (robots.txt twice, the terms and three
> public pages), one at a time and spaced apart, as part of a survey.
>
> We would like to ask:
> 1. Whether, and on what terms, we may use One Piece singles sold data (item name, card number,
>    sold price, sold date, condition / grading) through a method you specify (data supply, API,
>    file, …).
> 2. Whether we may display it on our site (credited to magi, with links to item pages) and
>    provide our aggregates (medians, market index) to third parties for a fee, and on what
>    terms.
> 3. A collection method and frequency that puts no load on your servers (we assume a daily
>    delta).
>
> We will not copy or resell sellers' personal data or individual listings. If you decline, we
> will not use magi data.
>
> Kind regards,
> [Name], Card Pirate, [email] / [URL]
