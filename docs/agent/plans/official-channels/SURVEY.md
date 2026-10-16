# Official data channels survey (PLAN ONLY)

Status: **PLAN ONLY**, for owner review. Written 2026-10-16 (15:28-15:50Z) on base
`origin/staging` at `6f42813`, branch `plan/official-channels`. STAGING ONLY. Production RED.
PSA10 OFF. No code, collectors, settings, staging writes, accounts, signups or payments.
Companion to `plan/source-survey` (SURVEY.md) and the combined plan on `plan/new-sources`.

Goal: permitted, structured routes to One Piece prices from sources that block scraping
(Aucfan, Suruga-ya, magi) or that we can't reach. No workaround of any block.

Evidence labels:
- **MEASURED**: observed in this session (a request and its result), or read from the repo.
- **UNVERIFIED**: from a web-search result about the page (official page title/snippet or a
  third party), not read from the page itself. Link given.
- **CARRIED FORWARD**: from an earlier committed plan (path given).
- **ESTIMATE**: my assumption or arithmetic.

---

## Plain summary (for the owner)

0. **Status (owner, 2026-10-16 21:45Z): Yahoo! and Rakuten are KIV; Aucfan, magi and エーツー are
   out unless the owner later decides to buy data (RED). No calls, signups or emails. See §6.**
1. **I could not read any official doc or call any API from here.** Every docs and API host was
   refused by this environment's network policy (MEASURED, §6). So everything below comes from
   search results about those pages (UNVERIFIED), and no listing counts were measured. Both
   shopping APIs need an app ID anyway, so no keyless calls were possible.
2. **Worth adding: the Yahoo! Shopping and Rakuten Ichiba item search APIs.** Both are free,
   official and return JSON with item name, price, shop and stock. They would add **shop asks
   from many small shops at once**, with explicit permission to use the data through the API.
   Owner action: register a free app on each (Yahoo! JAPAN ID, Rakuten ID). Then a thread can
   measure how many One Piece singles exist, from which shops, and whether names carry
   `OP05-118`. Yahoo requires a visible credit on any page that uses its data.
3. **Worth a quote request: Aucfan (sold prices) and Suruga-ya's operator A-two (エーツー).**
   Suruga-ya already supplies its product and 相場 data to business partners (POS systems,
   Mercari), so a data deal exists in principle. Aucfan sells its data commercially (MCP
   server, Pro Plus). Both are paid, so RED.
4. **magi and SNKRDUNK have no public API.** magi does B2B API integrations (eBay via
   BeeCruise), so ask (draft already in `plan/source-survey` Appendix B). SNKRDUNK stays on hold
   until the legal opinion.
5. **Not worth it:** affiliate networks (no product/price feeds found for TCG shops) and
   Amazon (API needs 10 sales in 30 days; few Japanese singles).
6. **Storage:** JSON APIs are compact per item, but raw responses must still be kept. Plan
   weekly full sweeps plus daily targeted queries, ≈1-2 MB/day per API (ESTIMATE).

---

## 1. Table

| Rank | Channel | Signal | Expected One Piece coverage | Independence vs Yuyu-Tei | Legal position | Storage | Effort | Cost | Owner must |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **Yahoo! Shopping 商品検索 v3** (`shopping.yahooapis.jp`) | Shop **ask**, in-stock flag, many stores | Unknown until measured; ESTIMATE medium (many small TCG stores list singles) | Medium (ESTIMATE): many independent stores; level drift like Dorasuta likely | Official API under LY Corp terms; **credit display mandatory** with official HTML (UNVERIFIED); storage/derived-value clauses not read | JSON; ESTIMATE ~15 KB gzip per 50-hit response; 1-2 MB/day weekly-sweep plan | Medium: free-text names, store dedupe | Free | Register a Client ID (Yahoo! JAPAN ID); allow host; decide on credit |
| 2 | **Rakuten Ichiba Item Search** (`openapi.rakuten.co.jp` / `app.rakuten.co.jp`) | Shop **ask**, availability, shop | Unknown; ESTIMATE medium-low (some small TCG shops; big TCG shops not confirmed) | Medium (ESTIMATE) | Official API; terms (Japanese original governs) not read; FAQ entry on paid tools exists, answer not read (UNVERIFIED) | JSON; `elements` field filter (ESTIMATE) keeps it small; ~1-2 MB/day | Medium | Free | Register an app (Rakuten ID): Application ID + access key; allow host |
| 3 | **Aucfan business data** | **Sold** (Yahoo! Auctions, Rakuten, flea markets) | ESTIMATE 35-55% of prints with a sale in 30 d | High (ESTIMATE): auction clearing | Contract. Public offer to supply 相場データ externally; MCP server; Pro Plus (UNVERIFIED) | Per contract, JSON | High: free-text titles, grade split | Paid, price unpublished (RED) | Send quote request (draft: `plan/source-survey` Appendix A) |
| 4 | **Suruga-ya data via 株式会社エーツー** | Shop **ask** (multi-shop marketplace) + 相場, possibly buyback | ESTIMATE high (one product per print, multi-shop) | Medium (ESTIMATE) | B2B precedent: MOOV POS gets Suruga-ya product **and 相場** data (2023); Suruga-ya cloud POS (2014); Mercari capital alliance with catalogue data (2025) (UNVERIFIED) | Per contract | Medium | Unknown, likely paid (RED) | New enquiry to エーツー (no draft yet; D4) |
| 5 | **magi B2B** (株式会社ジラフ) | **Sold** C2C + asks | ESTIMATE 60-80% with a sale in 90 d | High (ESTIMATE) | No public API; terms Art. 8(v)(dd) need written consent (MEASURED in source survey); does API integrations with partners (BeeCruise eBay sync, 2023, UNVERIFIED) | Per agreement | High | Unknown | Send consent request (draft: `plan/source-survey` Appendix B) |
| 6 | SNKRDUNK / 株式会社SODA | Marketplace ask, sold, PSA10 | Already a source | — | No public API found; partnerships are Yahoo! Auctions cross-listing, KREAM (UNVERIFIED) | — | — | — | Nothing new: data-platform email stays on HOLD for the legal opinion (CARRIED FORWARD) |
| — | Affiliate networks (A8.net, ValueCommerce, Rakuten Affiliate, もしも) | Links; possibly product search | Not found for CardRush, Fullahead, Dorasuta | — | Suruga-ya's own programme pays for links, no feed found; ValueCommerce has a 商品API (2007-2010 docs, current state unknown) (UNVERIFIED) | — | — | Free, needs a site review | Nothing now |
| — | Amazon Creators API (ex PA-API) | Ask (offers) | Low (few JP singles) | — | Needs Associates account + **10 qualifying sales in 30 days** (UNVERIFIED, affiliate.amazon.co.jp/creatorsapi) | JSON | Medium | Free | Nothing now |

## 2. Shopping APIs (check 1)

### 2.1 Yahoo! Shopping 商品検索 (v3) — UNVERIFIED unless marked
- **Doc:** https://developer.yahoo.co.jp/webapi/shopping/v3/itemsearch.html. Search by keyword,
  **JAN code**, genre category ID, brand ID or **store ID**; JSON. Last doc change 2026-02-06.
- **Returns (from doc/changelog snippets):** `hits[]` with name, price (tax-excluded fields
  added 2022: `taxExcludePrice`, `priceLabel/taxExcludeDefaultPrice`), seller (store) object,
  stock flag, URL, image; points fields revised 2025. Exact schema not read.
- **Limits:** since 2022-06-21 the 50,000/day cap was replaced by **30 requests per minute per
  application ID** (changelog https://developer.yahoo.co.jp/changelog/2022-05-20-shopping294.html);
  a "1 query/second to the same URL" guide; when limited, HTTP 500 until it clears; exact
  conditions not published (FAQ https://developer.yahoo.co.jp/webapi/shopping/faq.html).
- **Terms:** sites and apps using the APIs must show a **credit** with the official HTML,
  linked to the API docs; modifying the HTML or breaking the placement rules can lead to
  suspension (https://developer.yahoo.co.jp/attribution/). Usage is under LY Corporation's
  common terms. Clauses on storing results, commercial use and derived values: **not read**.
- **Signup:** a Client ID (application ID) registered with a Yahoo! JAPAN ID. No keyless
  access, so no calls were made.
- **What it would add:** asks from Yahoo! stores (small TCG shops; Suruga-ya, CardRush,
  Fullahead or Dorasuta stores not confirmed). `store_id` filter lets us pin known shops;
  in-stock filter avoids stale asks.
- **Cost plan (ESTIMATE):** a sweep by set code (`OP05` etc. + One Piece genre), 50 hits per
  call, deep pages capped (≈1,000 results/query is the usual cap, unverified) → ~600 calls per
  full sweep = 20 min at 30/min. Raw JSON ~100 KB per call, ~15 KB gzip → ~9 MB per sweep.
  Weekly sweep + daily top-value queries (≈60 calls) ≈ **1.3 + 0.9 ≈ 2 MB/day**.

### 2.2 Rakuten Ichiba Item Search — UNVERIFIED unless marked
- **Doc:** https://webservice.rakuten.co.jp/documentation/ichiba-item-search (version
  2026-07-01). Requires `applicationId` **and an access key** (header or query).
- **Returns (third-party summaries; schema not read):** item name, price, item code, URL, shop
  name/code, availability, review data, images. Official FAQ notes extra fields (size/colour)
  need other calls (https://webservice.faq.rakuten.net/hc/en-us/articles/25589776667545).
- **Limits:** **1 request per second per Application ID**; up to 5 apps per developer; keep the
  app ID private (FAQ https://webservice.faq.rakuten.net/hc/en-us/articles/900001974383 ,
  https://webservice.faq.rakuten.net/hc/en-us/articles/900001970586).
- **Terms:** https://webservice.rakuten.co.jp/guide/rule (Japanese original governs). Storage,
  display/credit and derived-value clauses **not read**. An official FAQ asks "Is it possible
  to provide a paid tool using the Rakuten API?" and points to a prohibited-acts clause; answer
  not read (https://webservice.faq.rakuten.net/hc/en-us/articles/900001970826). Read both
  before any commercial use (D2).
- **What it would add:** asks from Rakuten shops. A Rakuten search page for One Piece TCG shows
  small shops (ヨツバ商店, WebShopびーだま, イーバリュー) (UNVERIFIED,
  https://search.rakuten.co.jp/search/mall/ONE+PIECE/406864/); big TCG shops not confirmed.
- **Cost plan (ESTIMATE):** 30 hits per call; at 1/s a 2,630-card sweep is 44 min. Weekly sweep
  + daily targeted ≈ 1-2 MB/day if the field filter trims responses.

### 2.3 What to measure once app IDs exist (≤40 calls per API, read-only)
- Listing count for One Piece singles (genre + "ワンピースカード" + rarity words), top 20 stores
  by listing count, and whether CardRush / Fullahead / Suruga-ya / Dorasuta stores appear.
- Share of item names with a card number (`OP\d\d-\d{3}`, `ST\d\d-`, `EB\d\d-`, `PRB\d\d-`,
  `P-\d{3}`), and with a parallel/rarity marker.
- 20 sampled prints vs our staging Yuyu-Tei prices (same method as source survey §3).
- Bytes per raw response, gzip.

## 3. Affiliate feeds (check 2) — UNVERIFIED
- **Suruga-ya:** runs its own affiliate programme (terms https://www.suruga-ya.jp/affiliate_new/af_kiyaku.html ,
  page https://www.suruga-ya.jp/affiliate.html): link-based rewards on Suruga-ya JP sales,
  marketplace sales excluded, admission after review. No product/price feed mentioned.
- **CardRush, Fullahead, Dorasuta:** no affiliate programme or feed found.
- **ValueCommerce:** historically offered a 商品API / product database for affiliates
  (2007-2010 coverage, e.g. https://internet.watch.impress.co.jp/cda/news/2007/11/09/17464.html);
  current terms and TCG merchants unknown.
- **A8.net, もしも, Rakuten Affiliate:** no TCG-shop feed found. Rakuten Affiliate pricing data
  is the same Ichiba API with an affiliate ID.
- **Amazon:** Creators API needs an approved Associates account and ≥10 qualifying sales in
  the past 30 days (https://affiliate.amazon.co.jp/creatorsapi). Low value for JP singles.
- Verdict: affiliate feeds are not a price channel for our shops. Searching the merchant lists
  inside A8/ValueCommerce needs an affiliate account (owner, optional, D6).

## 4. Aucfan business data (check 3) — UNVERIFIED
- **Consumer:** aucfan.com price view needs Premium (月額2,200円) (source survey §2.2).
- **Business tool:** オークファンプロ Plus, for EC/auction/reuse businesses, built on ~68 bn sale
  records (2018 release https://aucfan.co.jp/wp-content/uploads/20180702_AF_Aucfan-Pro-Plusリニューアル_FIX.pdf).
- **AI access:** aucfan.com **MCP server** formally released, giving generative AI direct access
  to ~70 bn sale records; aimed at EC and reuse businesses
  (https://netshop.impress.co.jp/r/prtimes/items/000000492.000008833).
- **Data provision:** states it will actively supply its 相場データ externally
  (https://www.value-press.com/pressrelease/27402).
- **Pricing:** no published API or licence price found.
- **Contact route:** aucfan.co.jp corporate enquiry form (not opened: host refused, §6). Draft
  ready: `plan/source-survey` SURVEY.md Appendix A. Add: "is the MCP server licensable for a
  daily server-to-server pull, and what does it return for One Piece singles?"

## 5. magi and SNKRDUNK (check 4) — UNVERIFIED unless marked
- **magi (株式会社ジラフ):** no public API or data offer found. B2B integration precedent: BeeCruise
  (BEENOS) automated magi ↔ eBay listing sync with API linkage, 2023-10
  (https://beenos.com/file/press-release/6162/20231002_bcr.pdf); capital alliance with Marui
  (2022). Route: consent/data request, draft in `plan/source-survey` Appendix B.
- **SNKRDUNK (株式会社SODA):** no public API or data partnership found. Partnerships: Yahoo!
  Auctions sneaker cross-listing and a free authentication service with LY Corp (2025-11),
  KREAM (UNVERIFIED, https://www.commercepick.com/archives/tag/soda). 2026-03: used-item market
  price display added for all categories **except trading cards** (UNVERIFIED, same source).
  Route unchanged: data-platform §G-actions 2 (bd@soda-inc.jp) on HOLD until the legal opinion
  (CARRIED FORWARD, `origin/plan/data-platform:docs/agent/plans/data-platform/PLAN.md`).
- **Suruga-ya (added, not in the brief's check 4 but answers its goal):** product and 相場 data
  are supplied to business partners: MOOV POS integration with エーツー's EC, 2023-11
  (https://ascii.jp/elem/000/004/174/4174006/ , https://netshop.impress.co.jp/node/905);
  Suruga-ya cloud POS with ~7 m master + 相場 records, 2014; Mercari capital alliance using ~30 m
  catalogue records, 2025. A licensed route is plausible; robots.txt returned 403 to us
  (MEASURED in source survey), so this is the only route.

## 6. Status: owner decision 2026-10-16 21:45Z (supersedes §7-§8)

**All channels are parked. No app IDs, no host allowlist, no API calls, no emails or
enquiries.** The owner is not asking any source for permission. Nothing in §7 or §8 is to be
acted on until the owner reopens it.

| Channel | Status | Needed to resume |
|---|---|---|
| Yahoo! Shopping 商品検索 v3 | **KIV** (keep in view) | Owner decision to resume; owner registers a Client ID (Yahoo! JAPAN ID) and stores it as an env secret only; allow `shopping.yahooapis.jp` and `developer.yahoo.co.jp`; a thread reads the full terms (storage, derived values) and the credit rule, then runs §2.3 (≤40 calls); owner accepts the credit display (D2) |
| Rakuten Ichiba Item Search | **KIV** | Owner decision to resume; owner registers an app (Application ID + access key) as env secrets only; allow `openapi.rakuten.co.jp`, `app.rakuten.co.jp`, `webservice.rakuten.co.jp`; a thread reads the full terms including the paid-tool FAQ, then runs §2.3 (≤40 calls) |
| Aucfan business data | **Out**: no contact | A separate owner **RED** decision to buy data; only then a quote request (draft kept in `plan/source-survey` Appendix A, not to be sent before that) |
| magi (株式会社ジラフ) | **Out**: no contact, no collection | A separate owner **RED** decision to buy or licence data; draft kept in `plan/source-survey` Appendix B, not to be sent before that |
| Suruga-ya via エーツー | **Out**: no contact | A separate owner **RED** decision to buy data; no draft written |
| SNKRDUNK / SODA | Unchanged (existing source) | Nothing new; the data-platform email stays on HOLD for the legal opinion |
| Affiliate networks, Amazon | Not pursued | New owner request |

### 6.1 Requests made (MEASURED, 2026-10-16 15:29-15:31Z)

One request per host, 3 s apart, `curl` default UA:

| Host | Result |
|---|---|
| webservice.rakuten.co.jp, app.rakuten.co.jp, openapi.rakuten.co.jp | proxy refused (no response) |
| developer.yahoo.co.jp, shopping.yahooapis.jp | proxy refused |
| www.a8.net, www.valuecommerce.ne.jp, affiliate.rakuten.co.jp | proxy refused |
| aucfan.co.jp, snkrdunk.com, about.snkrdunk.com, jiraffe.co.jp | proxy refused |

The server-side fetch tool also failed for webservice.rakuten.co.jp (`getaddrinfo ENOTFOUND`).
No request reached any of these sites. No 403/429 from a site was involved.

## 7. Recommended order (superseded by §6; kept for reference)

1. **Owner registers free app IDs** on Yahoo! Developer Network and Rakuten Web Service, stores
   them as environment secrets (never committed), and allows `shopping.yahooapis.jp`,
   `openapi.rakuten.co.jp`, `app.rakuten.co.jp`, `developer.yahoo.co.jp`,
   `webservice.rakuten.co.jp` in network access. A thread then reads both terms in full and runs
   §2.3 (≤40 calls each).
2. **Send the Aucfan quote request** (Appendix A of the source survey, plus the MCP question).
3. **Send a data enquiry to エーツー for Suruga-ya** (D4).
4. **Send the magi consent request** (Appendix B of the source survey).
5. Build an API source only after §2.3 shows enough One Piece singles with card numbers, and
   the terms allow storage and derived values. Each is a new source in `plan/new-sources`.

## 8. Owner decisions (answered in §6: D1-D3 KIV, D4-D5 no, D6 no, D7 unchanged)

| # | Decision | Recommended default |
|---|---|---|
| D1 | Register Yahoo! and Rakuten app IDs | Yes, free; owner does it, IDs go to env secrets only |
| D2 | Accept Yahoo!'s mandatory credit on public pages that use its data | Yes if §2.3 shows value; otherwise skip Yahoo |
| D3 | Allow the API and docs hosts listed in §7 | Yes |
| D4 | Ask エーツー (Suruga-ya) for a data quote | Yes; I can draft it (JA + EN) on request |
| D5 | Aucfan and magi emails | Send the existing drafts |
| D6 | Open an affiliate account just to search merchant lists | No; low expected value |
| D7 | SNKRDUNK | No change: hold for the legal opinion |
