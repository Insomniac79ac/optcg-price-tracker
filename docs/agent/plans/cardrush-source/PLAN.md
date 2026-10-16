# CardRush price source: read-only audit + plan (PLAN ONLY)

Status: **PLAN ONLY**, for owner review. Written 2026-10-16 on base `origin/staging` at `1068d3c`
(PR #151 merge), branch `plan/cardrush-source`. STAGING ONLY. Production RED. PSA10 OFF.
Nothing in this session changed code, collectors, settings, prices, identity, Market Value, the
Index, staging data or Railway. No PR, no runbook dispatch, no source job.

Evidence labels:
- **MEASURED**: observed in this session (2026-10-16 14:13-14:15Z), read from the repo at
  `1068d3c`, or given by the owner with a named source.
- **CARRIED FORWARD**: measured by an earlier session and committed (path given). Re-check before use.
- **ESTIMATE**: my arithmetic or assumption. Every ESTIMATE in §1/§F is a placeholder for the
  audit in §0.3, which could not run (see §0.2).
- **UNVERIFIED**: background knowledge or a third-party snippet.

---

## Plain summary (for the owner)

1. **The audit could not run from here.** This cloud environment's network policy refuses
   `www.cardrush-op.jp` and `cardrush.media` (proxy 403 on CONNECT, MEASURED). No request
   reached CardRush. The plan below is complete, but its CardRush numbers are estimates until the
   audit in §0.3 runs (Q10 says how).
2. **What CardRush would add.** Raw coverage: today 1,681 of 4,316 card versions (39%) have no
   price from any source and only 334 have two (MEASURED, 2026-10-15 state). A third shop price
   could fill many of those gaps and turn many one-source prices into proper medians. PSA10: a
   second graded asking price besides SNKRDUNK, kept OFF and separate.
3. **A policy problem you should see first.** An earlier plan (data-platform, 2026-10-09) read
   a search snippet of CardRush's data policy that explicitly bans automated price collection
   (crawling/scraping) and bulk manual access for prices. The live page is 403. That is stricter
   than Yuyu-Tei's terms. This plan follows your decision (collect politely, legal opinion to
   cover it) but keeps the first live request behind your explicit acceptance of that clause (Q1).
4. **Storage fits if we read pack list pages, not every product page.** About 2 MB/day
   (ESTIMATE; range 0.7-7.3) plus about 30 MB once. That fits the 90-day test at both your
   planning and stress-B rates. Reading every product page daily would not fit (runway about 12-67
   days).
5. **Decisions you need to make** (§H, each with a default): accept the policy risk; which
   conditions count as raw (default 状態A/unlabeled only); sale and out-of-stock rules; whether
   CardRush joins the Index/Market Value median (default yes, after a 14-day hidden trial, with
   one planned break in the movement history); an honest crawler name; and letting a session reach
   CardRush to run the audit.

---

## 0. Step 0 and Step 1 results

### 0.1 Policy position (recorded, no stop)

| Item | Result | Label |
|---|---|---|
| `cardrush.media/data_policy` | 403 to everyone (owner checked 2026-10-16). From this session the proxy refused the host before any HTTP (CONNECT 403, 2026-10-16T14:14:10Z), so this session could not confirm the site's own 403. | MEASURED (owner); MEASURED (proxy) |
| Policy text | Data-platform plan §A6 (`origin/plan/data-platform:docs/agent/plans/data-platform/PLAN.md` ~L332) quotes a search snippet: 「独自コンテンツの無断使用、転載は禁止」; bans 「クローリングやスクレイピングを目的として…自動化された手段で…価格やその他コンテンツの情報を取得すること」 and 「販売価格や買取価格を得る目的で手動による大量のアクセス」. Its §A7 rates CardRush **W** (written permission) for display, redistribution and commercial use. | CARRIED FORWARD, UNVERIFIED (snippet) |
| Contact | info@cardrush-op.jp (data-platform §A6) | CARRIED FORWARD |
| Repo policy | Actions with legal/compliance implications are "stop and ask" (`docs/agent/AUTONOMY_POLICY.md:114`, `scripts/staging_policy.py` `legal_compliance`). Widespread blocking means containment, never evasion (`docs/agent/INVARIANTS.md:68-69`). | MEASURED (repo) |

Position: the owner decision of 2026-10-16 (same footing as Yuyu-Tei/SNKRDUNK, derived values on
Card Pirate, no external delivery until the legal opinion covers CardRush) is recorded as the
operating position. Because the snippet names automated price collection specifically, this plan
treats the first live CardRush request after the audit (the S4 canary) as a RED owner step (Q1).

### 0.2 robots.txt and reachability

| Request (one at a time, ≥3 s apart) | Time (UTC) | Result | Label |
|---|---|---|---|
| `GET https://www.cardrush-op.jp/robots.txt` | 2026-10-16 ~14:14 (first request, time not logged) | Proxy CONNECT 403, no HTTP exchange with CardRush | MEASURED |
| `GET https://cardrush.media/data_policy` | 14:14:10 | Proxy CONNECT 403 | MEASURED |
| `GET https://www.cardrush-op.jp/` | 14:14:13 | Proxy CONNECT 403 | MEASURED |

- Requests to CardRush: **0 reached the site**, 3 refused by the proxy. Audit stopped there, as
  briefed (no workaround tried: no other fetch tool, mirror, cache or browser).
- robots.txt **not read this session**. Data-platform §A6 read it live on 2026-10-09: "Blocks 4
  AI/social bots only" (CARRIED FORWARD, 7 days old). If that still holds, the paths below are
  allowed for a generic agent. The build must re-read robots.txt before S4 and on every run (§E).
- The cause is this environment's network policy, not CardRush. It does not tell us whether
  CardRush blocks crawlers.

### 0.3 Audit protocol to run (≤150 requests)

Run by a session that can reach the host (Q10). Plain HTTP GET, honest User-Agent (Q8), one
request at a time, **≥3 s apart (recommend 5 s)**, stop on the first 403, 429, CAPTCHA or
challenge page, no images, CSS, JS or other sub-resources. Keep HTML in the scratchpad only, never
staging. Paste short excerpts into §1.

| # | What | Requests |
|---|---|---|
| 1 | `robots.txt`; stop if it disallows `/product-group/`, `/product/` or the search path | 1 |
| 2 | Home page (navigation to product groups); `/page/8` (condition definitions); `/page/44` (PSA guide) | 3 |
| 3 | Product-group (pack) list pages for 8 releases (e.g. OP-01, OP-05, OP-09, the newest OP, one EB, one ST, one PRB, promos): page 1 and page 2 of each | 16 |
| 4 | Same 8 groups: the list's own paging/sort/per-page parameters (largest page size the site offers), 1 each | 8 |
| 5 | Product pages: 10 per group, chosen to cover 状態A, unlabeled, A-, B, C, キズ有り/傷アリ特価, セール, 〔PSA10鑑定済〕, 未開封/開封, sold-out, パラレル, SP/manga/alt art | 80 |
| 6 | Search for 5 card codes known to have several prints (e.g. a leader with parallel and reprint), to count products per code | 5 |
| 7 | New-arrivals or newest-products listing (for discovery) | 1-2 |
| | **Total** | **≤115** (35 spare for retries of nothing; no retry on errors) |

Record for §1: URL patterns; whether list pages show price, stock and the full name (so a daily
refresh needs only list pages); name grammar (card code `{OP09-118}`, rarity 【SEC】, parallel
`(パラレル/illust:…)` per data-platform §C3, UNVERIFIED); how each condition appears; whether one
product = one condition variant; HTML bytes per list page and product page; products per list page;
total products per group and in the One Piece catalogue; denial/latency.

---

## 1. Audit numbers

All CardRush figures below are **ESTIMATE** (audit blocked). Repo figures are labelled.

| Quantity | Value | Label / basis |
|---|---|---|
| Card Pirate canonical card versions | 4,316; any source 2,635 (61.1%); both sources 334; none 1,681 | MEASURED, `docs/agent/handoff/2026-10-15/capacity75-session13/CURRENT_STATE-end.yaml:538-545` |
| Yuyu refresh captures / 24 h | 2,690 | same file :566-572 |
| SNKRDUNK refresh attempts / 24 h | 304 (54 captured, 250 no_listing) | same file :590-602 |
| CardRush One Piece products (all conditions, graded, sealed) | 6,000-15,000, mid 10,000 | ESTIMATE: a large share of 4,316 versions × 1-4 condition/graded listings each |
| Products per card version | 1-4, mid 2.5 | ESTIMATE |
| Products per list page | 40-100, mid 60 | ESTIMATE |
| List pages for the whole catalogue | 60-375, mid ~170 | ESTIMATE |
| HTML per list page / product page | 100-300 KB / 60-250 KB | ESTIMATE (Yuyu 224 KB, SNKR 290 KB per page, MEASURED in verify-lossless-from-53968, carried forward) |
| Stored bytes per refresh capture (dictionary-encoded vs previous same URL) | 2-15 KB, mid 6 KB | ESTIMATE from Yuyu ~0.9% (224 KB → 2.1 KB) and SNKR ~2.7% (290 KB → 7.7 KB), CARRIED FORWARD |
| Stored bytes per first (anchor) capture | ~16% of HTML, mid 32 KB | ESTIMATE from NEW50 ~37 KB per Yuyu product page (session-13 HANDOFF:58) |
| Name-only identity: exact-and-unique rate | not measured | target and gate in §C |

---

## A. Source position

- **Same footing as Yuyu-Tei and SNKRDUNK** (owner decision 2026-10-16): collect politely, show
  derived values on Card Pirate, no external delivery (partner API, licensing, data product) until
  the legal opinion covers CardRush.
- **Policy page 403** (§0.1). The only text we have is a snippet that bans automated price
  collection. This is stricter than Yuyu-Tei (no scraping clause found) and similar in kind to
  SNKRDUNK's (owner-accepted risk G1 in the data-platform plan).
- **Add CardRush to the legal-opinion scope**, as four questions:
  1. Collection: automated, low-rate reading of public pages despite a published (but unreachable)
     data policy that bans it; effect of the policy being 403; robots.txt allowing it.
  2. Public display of derived values: median/Market Value/Index that include CardRush, and an
     attributed per-source "CardRush (状態A)" line on the print page.
  3. Licensing: whether derived values that include CardRush can be delivered externally (partner
     API, paid product). Default: no, until the opinion says yes.
  4. PSA10: displaying a CardRush graded asking price, and combining it with SNKRDUNK PSA10.
- **Parallel option** (owner action, external message, not done here): ask RUSH for written
  permission at info@cardrush-op.jp. A yes removes the clause risk. Q1.
- Images: none fetched, stored or shown (§E).

---

## B. Methodology options (RED: the owner decides)

Changing pricing methodology or Index/Market Value meaning is "stop and ask"
(`AUTONOMY_POLICY.md:106-107`).

### B1. Which conditions count as raw

| Option | What | Trade-off |
|---|---|---|
| **B1-a (default)** | 状態A and unlabeled only | Comparable to Yuyu sell (near-mint shop price). Fewer data points where CardRush stocks only A-/B. |
| B1-b | A, A- | More coverage; A- is a visible-wear grade, so mixes condition into a near-mint median. |
| B1-c | Lowest of A/A-/B/C (SNKRDUNK precedent: raw floor = min over A-D, `snkrdunk_collector/extractor.py:87-138`) | Most coverage; pulls the median down toward worn copies. Not comparable to Yuyu. |

Always excluded from raw: キズ有り/傷アリ特価 (damaged), 〔PSA10鑑定済〕 and any graded slab,
未開封/開封 sealed products, bundles/lots. The raw HTML keeps every grade, so a later parser can
derive A-/B/C series without new requests.

### B2. Sale (セール)

- **Default: excluded.** Stored as provenance with `promotion_state='sale'` (the column is
  source-neutral, `models/price_observation.py:140-144`), never public, history, Index or Market
  Value. Same as the Yuyu promotion decision (`DECISIONS.md:17`). Never substitute a struck price.
- Alternative: treat a sale price as the current price. Rejected by the existing invariant.

### B3. Out of stock

| Option | Trade-off |
|---|---|
| **B3-a (default): same as Yuyu.** A displayed price stays eligible regardless of stock, max age 7 days (`market_index.py` `_resolve_yuyutei_sell`, `YUYUTEI_SELL_MAX_AGE_DAYS=7`). Stock recorded in `stock_status`. | Consistent source-neutral rule. A sold-out shop price may be stale-high (shops rarely lower prices on items they don't hold). |
| B3-b: in-stock only | Price is one you can actually buy at; coverage drops; a value flickers in and out with stock, which creates leavers/entrants in Market Value. |
| B3-c: out-of-stock eligible for N days after last in-stock | Middle ground; one more source-specific rule (the Index forbids source-specific aggregation, `market_index.py:31-37`, so it must live in the resolver/semantics, like the SNKRDUNK floor minimum). |

### B4. PSA10 (stays OFF)

- **Default: separate graded series, OFF.** Parse 〔PSA10鑑定済〕 products into the CardRush product
  table with `grade_key='graded:PSA:10'` (§D), write **no PSA10 observations** while PSA10 is OFF
  (mirrors `scripts/snkr_storage_canary.py:135`, which asserts zero psa10 price states). Raw HTML
  keeps them, so turning PSA10 on later needs no new requests or backfill crawl.
- When the owner turns PSA10 on: CardRush becomes the second PSA10 asking source beside SNKRDUNK
  `psa10_asking`. Never mixed into raw Index/Market Value (`INVARIANTS.md:59-61`). PSA10 combination
  rule (median of two asks? show both?) is a separate decision then.

### B5. How CardRush combines with Yuyu-Tei and SNKRDUNK

Today the Index is `median_of_sources`, `INDEX_VERSION=3`, one value per source, no weights
(`services/market_index.py:135-136, 414-585`); 1 value → limited, 2+ → full.

| Option | What | Trade-off |
|---|---|---|
| **B5-a (default): full peer, after a shadow trial.** CardRush 状態A becomes a third resolver (one value per print, cheapest eligible 状態A/unlabeled product). Cutover on one chosen date. | Simplest and source-neutral (what the code was designed for, `market_index.py:31-37`). Median of three is robust to one outlier. Two of three are dealer asks, so the median leans to shop prices. **Cutover breaks movement comparability once**: the contributor set changes (`market_value.py:423-424`, `_comparability_reason` `contributor_set_changed`) and the required `SOURCE_SEMANTICS_VERSION` bump (`source_semantics.py:101-116`) gives `source_semantics_version_changed` for every print, so Market Value starts a new segment that day and 7D/30D windows cannot cross it for 7/30 days. |
| B5-b: display only | Attributed CardRush line on the print page, no Index/Market Value input | No methodology change and no break. Does not fill the 1,681 unpriced versions in Market Value. |
| B5-c: coverage only (CardRush only where no other source) | | A source-specific aggregation rule, explicitly not permitted by the Index design (`market_index.py:35-37`). Not recommended. |

Card Pirate Index (`services/card_pirate_index.py`) reads only `index_value_jpy`, so it follows
whatever B5 decides with no own change.

---

## C. Identity

Rules: exact physical CardPrint and authoritative `release_product_id` (`DECISIONS.md:15-16`),
ambiguity never auto-approved, quarantine otherwise.

### C1. Resolver rules (CardRush name → exact CardPrint)

Reuse `services/exact_print_approval.py` `resolve_exact_print` (:530-710) with a new
`SourceEvidence.from_cardrush_candidate` (next to `from_snkrdunk_candidate` /
`from_yuyutei_candidate`, :185-268). Inputs from one CardRush product:

1. **Card code** from the name (`{OP09-118}` style, UNVERIFIED until §0.3). Required; mismatch or
   two codes → refuse.
2. **Release**: the product group (pack page) the product was found under → release product code
   or uncoded alias (`worker/matching/source_product_aliases.py`). A group that does not resolve to
   exactly one release → refuse even if one print remains (existing rule :666-676). Never infer
   release from the card-code prefix (reprints in PRB/EB/promos).
3. **Variant**: parallel/SP/manga markers (`パラレル`, `illust:…`, SP) → narrow to the parallel
   family only, like SNKRDUNK (`snkrdunk_listing_evidence.py:1-60`). `official_asset_variant` is
   set only from explicit evidence; an illustrator name is not enough on its own.
4. **Rarity** (【SEC】 etc.) is recorded but not a discriminator (existing rule :586-590).
5. **Condition/grade/sale/sealed** parsed into `grade_key` and flags (§D); they never affect print
   identity, only eligibility.
6. Result: exactly one print → `print_matched` (candidate) → approval through the existing gate;
   more than one → `REFUSAL_AMBIGUOUS`; none → `unmatched`; conflict → `identity_conflict`. All
   non-exact outcomes are quarantined (`freshness_work.state='blocked'`), never retried by guess.
7. One CardPrint may have several CardRush products (A, A-, B, PSA10). Each is its own mapping;
   only the 状態A/unlabeled one is index-eligible (B1).

### C2. Ambiguity rate

- **Not measured** (audit blocked). Expected pattern (UNVERIFIED): base prints resolve by code +
  release; parallels/alt arts with several art variants under one code are the ambiguous share.
- **Gate (proposed)**: the S0 audit measures it on the ~80 sampled products. Go if ≥80% of
  sampled 状態A/unlabeled products resolve exactly and 0 resolve to a wrong print on manual check;
  otherwise rework C1 before S2.

### C3. Reuse

- `exact_print_approval.resolve_exact_print`, refusal codes and `NEEDS_REVIEW_REFUSALS`.
- `worker/matching/opcg_normalizer.py` (`VARIANT_KEYWORDS`), `source_product_aliases.py`.
- `packages/opcg_source_identity`: add a CardRush canonical listing identity (product id from URL)
  and conformance vectors. Without it mappings get a NULL identity and freshness refuses them
  (`__init__.py:27-34`, `freshness_queue.py:102-105`).
- Quarantine reporting: `scripts/quarantine_reporting.py`.

---

## D. Data model (additive migrations only)

Head today: `3b7d9c1a5e20` (MEASURED). Additive/reversible migrations are AMBER
(`AUTONOMY_POLICY.md:74`); the owner runs `alembic upgrade head` with a staging backup <24 h old
(`:148-149, :193`).

### D1. One grade/condition field on observations

Today grade lives in `price_type` + free-text `condition_label` (SNKRDUNK raw `floor` stores the
winning A-D grade; PSA10 is `price_type='psa10_asking'`, `condition_label='PSA10'`,
`snkrdunk_collector/writer.py:416-419, 480`).

- Add nullable `price_observations.grade_key VARCHAR(32)`. Vocabulary:
  `raw:A`, `raw:A-`, `raw:B`, `raw:C`, `raw:D`, `raw:damaged`, `raw:unlabeled`,
  `graded:PSA:10` (extendable `graded:<grader>:<grade>`). Keep `condition_label` verbatim and keep
  `price_type` (no reader changes).
- CHECK on the vocabulary added `NOT VALID`, then validated. Nullable add with no default is
  metadata-only on PostgreSQL 16 (no table rewrite).
- Existing rows: **no backfill** (UPDATE on the price table is DATA and not needed). Readers treat
  NULL as "derive from price_type/condition_label". New SNKRDUNK writes may set it later; optional.
- `freshness_price_states` gets the same nullable column if per-grade freshness is wanted (default
  no: only the counted 状態A category has freshness).

### D2. CardRush records

- `sources` row `cardrush` (`base_url https://www.cardrush-op.jp`), seeded in the migration
  (precedent: `f4c8a2d91b60` seeded `snkrdunk`).
- `cardrush_product_groups`: group id, URL, verbatim title, resolved `release_product_id`
  (nullable), first/last seen. One row per pack page.
- `cardrush_candidates` (one row = one CardRush product = one condition variant): product id
  (unique), URL, group id, verbatim name, parsed card code, rarity, parallel marker, `grade_key`,
  sale/sealed flags, last price/stock seen, `match_status`
  (`unmatched|print_matched|identity_conflict`), `card_print_id` nullable, first/last seen.
  Mirrors `yuyutei_candidates`/`snkrdunk_candidates`.
- `source_mapping_proposal_groups.source_candidate_type` CHECK widened to add
  `cardrush_candidate` (drop + re-add, `NOT VALID` then validate).
- `price_observations.candidate_id` stays SNKRDUNK-only; CardRush observations link through
  `source_card_mapping_id` + `raw_snapshot_id` only.
- Mappings: existing `source_card_mappings`, one per CardRush product, canonical identity from
  `opcg_source_identity`.

### D3. Must-do guards before any CardRush row exists

- Register CardRush in `services/source_instruments.py` `SOURCE_INSTRUMENTS`. Today an
  unregistered source shows **every** price_type in public print series
  (`source_instruments.py:99-103, 174-187`; `print_series.py:46-52, 595-606`), so B/C/damaged/sale
  rows would be charted publicly. Until cutover, CardRush series must be hidden from public reads.
- Unknown sources are classified eligible (`source_semantics.py:244-249, 267-269`). No CardRush
  resolver exists until cutover, so nothing enters the Index; the `SOURCE_SEMANTICS` entry and
  version bump ship only at the cutover (B5), not earlier, to avoid a second break.

### D4. Collector import-graph impact

| Change | Runtime input of | Consequence |
|---|---|---|
| `packages/opcg_source_identity` (CardRush identity) | both existing collectors | redeploy all 10 collector services |
| `services/raw_dictionary_storage.py` `PARSERS` += `cardrush-collector-v1` | both | same |
| `services/freshness_integration.py` `CATEGORIES`, `freshness_queue.py` (list-page work unit) | both | same |
| `source_instruments.py`, `exact_print_approval.py`, models | check with `scripts/collector_runtime_inputs.py` | likely both |
| New `services/cardrush_collector/` | new collector only | new service |
| `scripts/collector_runtime_inputs.py` `COLLECTORS`, `scripts/deploy_staging_collectors.py` `NAMES` and the ≤10 collector cap, `generate_staging_state.py`, `check_raw_health.py` | tooling (DATA lane) | cap must become 11 (Q11) |

Plan: bundle all shared-module edits into **one** delivery with **one** 10-service rollout (S2),
so the existing collectors move once. The CardRush package itself (S3) touches only the new
service.

---

## E. Collector

| Item | Plan |
|---|---|
| Transport | Plain HTTP (no browser). One HTML document per request. No images, CSS, JS, fonts. A slim Python image, not the Playwright base. |
| robots.txt | Fetched at the start of every run; a run proceeds only if every path it will request is allowed for its User-Agent; unreachable robots.txt → no run (fail closed). |
| User-Agent | Honest, identifying, with a contact URL (Q8), e.g. `CardPirateBot/1.0 (+https://<card-pirate-domain>/bot)`. |
| What is fetched daily | **Pack list pages only** (largest page size the site offers), which carry name, price and stock for every product. Product pages only for discovery/identity review of a new product, capped (e.g. ≤50/day). If the audit shows list pages lack price or stock, stop and re-plan (§F scenario P does not fit). |
| Shards | One service, **no shards**. Volume is ~60-375 list pages/day (ESTIMATE). |
| Schedule | One run per day, 16:00 UTC (01:00 JST, shop quiet hours), finishing well before the 20:00 UTC index snapshot. No collector change 02:00-06:00 UTC; releases 06:00-23:00 UTC. |
| Rate limit | One request at a time, **5 s spacing** (floor 3 s), per-run cap 500 requests, `source_dispatch_budgets` row e.g. 500/86400. |
| Request budget | ESTIMATE 100-450/day (60-375 list pages + robots + ≤50 product pages + new-arrivals); at 5 s ≈ 8-38 min/day. |
| Freshness target | Shared 24 h standard, dispatch due at 23 h (`DECISIONS.md:18`). Work unit = list page; refreshing a page refreshes every mapping on it. Failure does not refresh success; no-listing does not refresh an old price. |
| New-product discovery | Daily: new-arrivals listing + group list pages already fetched (new product ids appear there); weekly: product-group index for new packs. Discovery never approves; candidates go through §C. |
| RAW | Persist HTML before parsing (`INVARIANTS.md:65-69`); dictionary-encoded against the previous same-URL body once `cardrush-collector-v1` is in `PARSERS`; shares daily admission (8,192 rows / 32 MiB encoded per UTC day, `raw_dictionary_storage.py:24-56`, today ~3,000 rows/day used by Yuyu+SNKR, ESTIMATE from §1 attempts). |
| Health | `docs/agent/RAW_OPERATIONAL_HEALTH.md` contract (HEALTHY/DEGRADED/BLOCKED); `check_raw_health.py` learns `cardrush`; daily report: pages fetched, parse failures, products seen/new/gone, identity outcomes, quarantine count, bytes stored. |
| Lossless | `verify-lossless` runbook covers the CardRush parser (decode every encoded row to the original SHA-256). |
| Containment | First 403, 429, CAPTCHA/challenge or robots disallow → pause source (`source_denial`), no retry, owner told. Never rotate IPs/UAs or use a browser to get past a block. |
| Images | Never requested, stored or shown publicly. No R2 mirror for CardRush. |

**Rollback triggers** (any one: stop the cron, keep data, report): any denial or challenge;
robots.txt change disallowing a needed path; >5 transient failures in a day; >2% list pages fail
to parse; any wrong-print match found on review; CardRush stored bytes >4 MB/day over 48 h
(§F budget) or the 90-day fit going negative at stress B; daily RAW admission rows >80%; any
CardRush value visible publicly before cutover; any message or notice from RUSH. Procedure:
disable the cardrush cron (owner, Railway), `collector_variables.restore` for any shared-module
rollout (`STAGING_DELIVERY.md:350-377`).

---

## F. Capacity

MEASURED (owner, capacity session 14 `storage-rates` run 38898278774, 2026-10-16): room to the
3 GiB reserve **2,938 MB**; planning **23.35 MB/day**; stress B **27.58 MB/day**. Fit rule
(`scripts/ops/storage_rates.py` `fit()`): need = (rate + new) × 90 + one-off ≤ room, at planning
**and** stress (owner rule). Note: the 23.35/27.58 run is not committed in the repo; the newest
committed rates are 23.10/26.41 (session 13).

### F1. Without CardRush

| Rate | 90-day need | Margin | Runway |
|---|---|---|---|
| Planning 23.35 | 2,101.5 MB | +836.5 | 125.8 d |
| Stress B 27.58 | 2,482.2 MB | +455.8 | 106.5 d |

Room for a new recurring source with a 30 MB one-off: **8.96 MB/day at planning, 4.73 MB/day
at stress B** (binding).

### F2. CardRush per day and one-off (all ESTIMATE)

| Scenario | Per day | One-off |
|---|---|---|
| **L: list pages (recommended)** | RAW 170 pages × 6 KB ≈ 1.0 MB; observations 3,000 counted rows × 250 B ≈ 0.75 MB; freshness/attempt rows ≈ 0.2 MB → **≈2.0 MB/day** (range 0.7-7.3) | anchors 170 × 32 KB ≈ 5.4 MB; candidates 10,000 × ~600 B ≈ 6 MB; mappings ~3 MB; ≤500 product pages for identity × 37 KB ≈ 18.5 MB → **≈30 MB** (range 15-50) |
| P-A: product pages, 状態A only (~3,000/day) | ≈18.75 MB/day | ≈96 MB |
| P-all: every product page (~10,000/day) | ≈190 MB/day (daily admission exhausted after ~5,000 rows, rest kept as ~32 KB plaintext) | ≈320 MB |

Observations are written only for counted categories (状態A/unlabeled raw; nothing for PSA10
while OFF); other grades live only in RAW.

### F3. Fit with CardRush

| Scenario | Planning: need / margin / runway | Stress B: need / margin / runway |
|---|---|---|
| L-low (0.7/day, 15 once) | 2,179.5 / **+758.5** / 121.5 d | 2,560.2 / **+377.8** / 103.4 d |
| **L-mid (2.0/day, 30 once)** | 2,311.5 / **+626.5** / 114.7 d | 2,692.2 / **+245.8** / 98.3 d |
| L-high (7.3/day, 50 once) | 2,808.5 / **+129.5** / 94.2 d | 3,189.2 / **−251.2 does not fit** / 82.8 d |
| P-A | **−947.0 does not fit** / 67.5 d | **−1,327.7** / 61.3 d |
| P-all | **does not fit** / 12.3 d | **does not fit** / 12.0 d |

Verdict: **L fits at both rates unless CardRush stores more than ~4.7 MB/day.** Per-product
daily capture does not fit.

### F4. If it doesn't fit (measured in S0/S5)

In order of preference: (1) larger list pages / fewer pages; (2) skip storing a RAW body
identical by hash to the previous same-URL body (store a reference row only; needs a design
decision, it changes the RAW writer used by both collectors); (3) RAW to R2 (data-platform plan
design; owner decision, paid service RED); (4) narrow scope to versions without a Yuyu price;
(5) grow the volume (owner, paid). Not proposed: enabling `raw_snapshots` retention (deletes
evidence) or a 48 h freshness target (changes a shared decision).

Also: if another one-off lands first (e.g. the remaining-50 batch, ~111 MB at session 13), re-run
`storage-rates` and this table before S4.

---

## G. Delivery sequence

All staging. One staging delivery at a time. No merges 19:30-20:30 UTC, no collector change
02:00-06:00 UTC, collector releases 06:00-23:00 UTC. Every session after S0 is DATA lane with a
regenerated `STAGING_MISSION.json`.

| Session | What | Lane / level | Canary | Owner approvals |
|---|---|---|---|---|
| **S0 audit** | Run §0.3 (≤150 req); fill §1; re-check robots; measure identity sample and bytes; re-cut §F; go/no-go | plan only, GREEN | — | Q10 (network access); Q1 if the owner wants the audit itself under Q1 |
| **S1 schema + guards** | Migration (D1, D2); `SOURCE_INSTRUMENTS` registration and public-series hiding (D3); tests. No collector code | DATA, AMBER (migration) | — | Owner runs `alembic upgrade head` (backup <24 h) |
| **S2 shared modules** | `opcg_source_identity` CardRush identity + vectors; `from_cardrush_candidate`; `PARSERS`; freshness list-page unit; tooling (COLLECTORS, NAMES, cap 11, state, raw health). One 10-service rollout, sequential, rollback restore | DATA, AMBER | existing collectors canary per `STAGING_DELIVERY.md` | Q11 |
| **S3 collector package** | `services/cardrush_collector/` + Dockerfile, built and tested against S0 fixtures only (mocks before live, `INVARIANTS.md:65-67`). No deploy | DATA, AMBER | — | — |
| **S4 activation canary** | Owner creates Railway service `cardrush-collector` (cron off), sets vars. Day 1-3: 1 product group (1-3 list pages) daily; day 4-7: 5 groups; then all. Observations written, hidden | AMBER new source + **RED (Q1, legal)** | 1 group → 5 → all | Q1 acceptance; Railway service; cron on |
| **S5 shadow (≥14 days)** | No code. Daily report: storage-rates, denials, parse, identity, CardRush 状態A vs Yuyu sell divergence; proposed cutover date | GREEN observe | — | — |
| **S6 cutover** | `SOURCE_SEMANTICS` CardRush entry + `SOURCE_SEMANTICS_VERSION` 3→4, CardRush resolver in `print_market_index.py`, public attributed series; release notes on the one-day movement break | DATA, **RED (methodology)** | single date, before 20:00 UTC snapshot | Q6, Q7, cutover date |
| later | PSA10 graded series (B4) | RED | — | Owner turns PSA10 on |

---

## H. Owner questions (each with a recommended default)

| # | Question | Default |
|---|---|---|
| Q1 | The CardRush data policy snippet bans automated price collection. Do you accept that risk for staging collection now, or wait for RUSH's written permission / the legal opinion? | Build S1-S3 now (no source calls). Start S4 only after you confirm in writing that you accept this specific clause; send a permission request to info@cardrush-op.jp in parallel. |
| Q2 | Which conditions count as raw? | 状態A and unlabeled only (B1-a). |
| Q3 | Sale prices? | Excluded, provenance only (B2). |
| Q4 | Out-of-stock prices? | Same as Yuyu: eligible up to 7 days old, stock recorded (B3-a). |
| Q5 | PSA10? | Parse, store RAW only, no PSA10 observations while OFF (B4). |
| Q6 | CardRush in the Index/Market Value median? | Yes, as a full peer after ≥14 days of shadow, on one cutover date; accept one movement-history break (B5-a). |
| Q7 | Public display? | After cutover: attributed "CardRush (状態A)" line per print, values only, no images, no prose; nothing public before. |
| Q8 | User-Agent? | Honest `CardPirateBot/1.0` with a contact URL (differs from SNKRDUNK's desktop-Chrome UA). |
| Q9 | If storage exceeds budget? | Shrink requests first; RAW→R2 decision before full rollout; never enable evidence deletion. |
| Q10 | How to run the S0 audit? | Add `www.cardrush-op.jp` (and `cardrush.media`) to this project's cloud environment allowed domains (Project settings → Cloud environment → gear → Network access), then a thread runs S0. Or run §0.3 yourself and paste results. |
| Q11 | Collector rollout cap 10 → 11 services? | Yes, in S2. |
| Q12 | Request spacing? | 5 s (brief floor 3 s), one run per day at 16:00 UTC. |

---

## Risks

- **Policy**: the strongest risk. The snippet is specific; a notice from RUSH means stop (rollback trigger).
- **Estimates**: every CardRush number is an ESTIMATE until S0. List pages lacking price/stock
  would force per-product capture, which does not fit storage.
- **Methodology break**: S6 starts a new Market Value segment for every print; 7D/30D windows are
  unavailable for 7/30 days after cutover.
- **Public leakage**: without D3, CardRush B/C/damaged rows would appear in public charts the
  moment they are written.
- **Shared RAW admission**: CardRush draws on the same 8,192-row/32 MiB daily admission as Yuyu
  and SNKRDUNK; overflow is stored as plaintext.
- **Dealer-ask bias**: two of three median inputs would be shop asking prices.
