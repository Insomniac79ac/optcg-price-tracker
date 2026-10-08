# Onchain Phase 1: "Price Referee" plan

Status: **PLAN ONLY**, for owner review. Written 2026-10-08 on base `origin/staging`
336706a. No code, PR, deploy, staging write, wallet, key or transaction was made.
Numbers are MEASURED (with source and time) or ESTIMATED.

Card Pirate becomes the independent price referee for the onchain One Piece card
market. It is not a marketplace, vault, gacha operator, token issuer or price feed
for leveraged products. Collector positioning ("not a crypto or trading terminal")
and every invariant in `docs/agent/INVARIANTS.md` stay binding.

The owner-referenced file "Blockchain models for TCG trading.md" was **not found**
in the Codespace (searched 2026-10-08 ~13:15Z), so it is not committed here.

---

## 0. What exists today (MEASURED from repo at 336706a)

| Area | Fact | Source |
|---|---|---|
| Per-card daily publication | `market_index_snapshots`, unique `(card_print_id, snapshot_date)`. Fields: `index_value_jpy`, method, `source_count`, coverage, confidence, range, versions, freshness bounds, `provenance` | models/market_index_snapshot.py:82,139-258 |
| Day receipt | `market_index_snapshot_completions` (`receipt_kind='atomic'`), with `snapshot_content_digest` and `selected_print_ids_digest` | models/market_index_snapshot_completion.py:18-64 |
| Receipt digests | SHA-256 of canonical JSON (sorted keys, compact separators, UTC µs + `Z`); format `market-index-snapshot-content-v1`; rows sorted by `card_print_id`; only `id`/`created_at` excluded | docs/market_index_snapshot_completion.md:42-63 |
| Market Value | **Aggregate** series (`market_value_points`: Overall + per ReleaseProduct per day), forward-published only on receipt-backed days. Not a per-card value | models/market_value_point.py:200-254; docs/market_value_forward_publication.md:52-58 |
| Gaps | 2026-09-27/28 have snapshots but deliberately **no** receipts. Staging verifiers enforce 0 receipts / 0 gap rows | scripts/verify_staging_delivery.py:140,173-177 |
| Immutability | By convention: writers are `ON CONFLICT DO NOTHING`. No DB triggers; a manual UPDATE is technically possible | market_index_snapshot.py:16-24 |
| Public read API | `GET /prints/{id}/series?series=market_index` (archived daily points), `/analytics/market-value`. No endpoint exposes receipts or digests | api/prints.py:252; api/market_value.py |
| PSA10 | Parsed from the same SNKRDUNK page as RAW (`extract_psa10`); stored as `price_type='psa10_asking'`. 0 live observations. Excluded from Index/MV/CPI. No API or UI category. `PSA10_ENABLED` is not checked by app code | snkrdunk_collector/extractor.py:142-170; writer.py:416-480; market_index.py:653-657 |
| Sealed product | **Not tracked.** No box/pack price model, source or collector | repo search |
| Release products | `release_products(id, official_code, display_name, released_on, release_date_source, …)`. No announcement or region fields | models/release_product.py:118-136 |
| Graded identity | Only per-collection-item `grading_submissions(cert_number, grading_company, final_grade)`. No slab entity, no edition field. Exact-print key is `(canonical_card_id, language, release_product_id, official_asset_variant)` | models/grading_submission.py; card_print.py:136-170 |
| Admin curation | Review-queue patterns (`source-mapping-proposals`, `snkrdunk-candidates`) with `X-Admin-Token` + actor assertion | apps/web/src/app/admin/(protected)/ |
| Secrets | Provider env/secret store only, `check_secrets.sh`. No asymmetric signing key or KMS convention exists | docs/deployment.md §2 |

**Constraint found during planning (affects every API-touching PR).**
`verify_snkr_published_discovery_component.py` checks continuity over
`SNKR_PATHS = (services/snkrdunk_collector, services/api, …)`, because collector
images bundle `services/api`. Under current verification, **any change under
`services/api/`** breaks continuity with the installed collector upload 1b1b64d. Such
a change therefore needs a collector release (redeploy) and must respect capacity
quiet windows. Options are listed in §E.

---

## A. Onchain receipt anchoring

**Goal:** anyone can verify Card Pirate never rewrote a published per-card value or
a Market Value point.

### A1. What gets fingerprinted

For each receipt-backed `snapshot_date` **D**, the anchor payload is:

```
anchor_v1 = SHA-256( "cardpirate-anchor-v1" || D || index_root || mv_root
                     || snapshot_content_digest || selected_print_ids_digest )
```

- **`index_root`**: Merkle root over that day's `market_index_snapshots`, sorted by
  `card_print_id`.
  - Leaf = `SHA-256(0x00 || canonical_row_json)`, using exactly the
    `market-index-snapshot-content-v1` canonical row encoding, so it ties to the
    existing receipt digest.
  - Node = `SHA-256(0x01 || left || right)`. An odd node is promoted unchanged.
    Domain separation prevents leaf/node confusion.
- **`mv_root`**: Merkle root over that day's published `market_value_points` (Overall
  + each release), sorted by `(scope_kind, release_product_id)`, same scheme.
- Including the existing receipt digests means the anchor also commits to row count
  and selection.

**Size:** about 2,626 leaves/day (MEASURED: latest receipt 2026-10-07, session-3/5
state), tree depth 12. A single-card proof is about 12 × 32 B = 384 B (ESTIMATED).

**Proof:** the API returns
`{leaf_json, leaf_index, siblings[], index_root, mv_root, digests, D, anchor tx refs}`.
A verifier recomputes the leaf from the public value, folds the siblings, recomputes
`anchor_v1`, and compares it to the onchain value.

**Storage:** one `publication_anchors` row/day (date, roots, payload, chain refs,
OTS proof bytes ~1–5 KB) ≈ 0.2 MB/year (ESTIMATED). Proofs are recomputed on demand
from immutable rows, never stored per card.

### A2. Chain and method (fees MEASURED 2026-10-08 13:15–13:17Z, ETH $2,535.51, coingecko)

| Option | $/anchor | $/month (30) | Notes |
|---|---|---|---|
| OpenTimestamps (Bitcoin) | $0 | $0 | No key or wallet. Bitcoin permanence. Proof after hours. Not attributable to Card Pirate by itself |
| OP Mainnet, plain calldata | $0.00009 | $0.003 | Cheapest L2 |
| **Base, write-once contract mapping + event** | ~$0.0008 (ESTIMATED 2× plain) | **~$0.02–0.03** | `eth_call` verify from any node; contract state survives history pruning |
| Base, plain self-send | $0.00035 | $0.010 | Discovery needs an explorer/indexer |
| Base, EAS attest | $0.0046 (one real tx measured $0.0048) | $0.14 | Browsable easscan page; ~300k gas |
| Arbitrum, plain / EAS | $0.0012 / $0.015 | $0.04 / $0.46 | |
| Polygon PoS, plain | $0.0006 | $0.02 | |
| Ethereum L1, plain / EAS | $0.042 / $0.55 | $1.25 / $16.55 | Reference |

Raw inputs (MEASURED):
- Base gasPrice 0.006 gwei; GasPriceOracle l1BaseFee 0.670 gwei.
- OP 0.001 gwei.
- Arbitrum 0.0201 gwei.
- Polygon 276.9 gwei.
- L1 0.725 gwei.
- EAS on Base: 265k–330k gas over 10 recent attestations.
- Fees can spike 10–100×. Even 100× stays under $3/month on Base.

**Longevity:**
- OP-stack L2 batches leave L1 blobs after ~18 days, so old *logs/calldata* depend
  on L2 archive nodes and explorers.
- A public Base RPC refused receipts only ~100 min old without a token (MEASURED).
- **Contract storage** is held by every live node. That is the reason for a
  write-once mapping.
- Card Pirate also stores tx hash, block, and OTS proof alongside each receipt.

**Recommendation:**
1. **OpenTimestamps from day 1** (free, keyless).
2. **Base write-once anchor contract** (`mapping(uint64 day => bytes32)`, reverts on
   overwrite, emits `Anchored(day, payload)`), once custody is decided.
3. EAS later only if a browsable attestation page is wanted.

No token, ever.

### A3. Key management: RED (owner decides; nothing created this session)

| Option | How | Pros | Cons |
|---|---|---|---|
| **K0. No key (OTS only)** | Stamp roots via public calendars | No secret at all. Ships first | Not attributable alone; hours latency; no explorer UX |
| **K1. Railway secret hot key + hardware-wallet contract owner** (recommended default) | Dedicated single-purpose key in a dedicated anchoring service's secret store. Wallet holds ≤$5 ETH. Owner (Ledger/Safe) owns the contract and can rotate the signer | Cheap, automated, existing secret convention. Blast radius = forged anchors until rotation, ≤$5 | Plaintext in PaaS secret store/process memory; platform compromise exposure |
| K2. Cloud KMS secp256k1 signer | AWS/GCP KMS key, IAM-scoped, audit log | Key never leaves HSM | New paid provider (~$1/key/month) = **RED: new external service**; integration work; cloud IAM becomes the secret |
| K3. Owner hardware wallet signs daily | Manual | Strongest | Breaks automation; missed days likely |

**Rules for any K1/K2 signer:**
- Single purpose; never reused.
- Never in git, CI logs or `NEXT_PUBLIC_*`.
- Funded ≤$5.
- The contract accepts only the current signer.
- **Rotation:** the owner calls `setSigner(new)`, and the rotation is logged
  publicly on the methodology page.

**If the key is leaked:**
- Rotate.
- Mark anchors between the leak and the rotation as "signer compromised; verify
  with OTS".
- Never delete history.

**If the key is lost:** rotate. Old anchors remain valid (stored onchain).

**Staging vs production:**
- Staging builds anchor to **Base Sepolia** (testnet) plus OTS.
- Mainnet anchoring of *public* prices is a **production** action (RED) and needs
  separate owner authorization.

### A4. Failure rules (hard)

- Anchoring runs **after** a receipt exists and **never** blocks, delays or alters
  publication. Failure leaves publication untouched and records `anchor_status=failed`.
- One anchor per receipt date. A missed day shows **"not anchored"**.
- A later anchor of an old date is allowed **only** as a clearly labelled late anchor:
  the payload carries D, and the chain timestamp is the true anchor time. The UI says
  "anchored late on <date>". It is never presented as same-day.
- **Genesis:** a one-time anchor of all receipts existing at launch, as one root over
  per-day anchors, labelled "genesis: proves no change after <genesis date>".
- 2026-09-27/28 have no receipts → **never** anchored; shown as gaps.
- The writer refuses a second anchor for a date; the contract also refuses overwrite.

### A5. Public verification

- Methodology page (collector language): "How to check we never changed a price".
- Open verifier, both forms:
  - A ~150-line Python/TypeScript script in the repo (`tools/verify_anchor`).
  - A static page (client-side, no backend trust).
- **Inputs:** card, date. **Fetch:** public value + proof from Card Pirate, root from
  any Base RPC/explorer and/or the OTS file.
- **Outputs:** match / mismatch / not anchored.

### A6. Running cost

**MEASURED fees:**
- ~$0.02–0.03/month on Base (contract) + $0 OTS.
- Wallet top-up ~$5 lasts years at current fees.

**ESTIMATED platform cost:** negligible. The anchoring job runs inside an existing
scheduled service or a tiny new cron.

---

## B. Onchain One Piece market view

**Goal:** show collectors how onchain prices, pack value and buyback offers compare
with Japanese market prices, honestly and like-for-like.

### B1. Sources and terms (MEASURED 2026-10-08 unless marked)

| Source | Data available | Display allowed? | Redistribution allowed? | Unclear |
|---|---|---|---|---|
| Collector Crypt API (`api.collectorcrypt.com`, `gacha.collectorcrypt.com/api`) | Keyless. Listings, card catalogue, gacha machines (price, rarity odds, buyback %, pool via `/api/getNfts`, `insured_value`). POST limit 300/min/IP | UNCLEAR (no ToS found) | UNCLEAR | Terms, licence for API data |
| Collector Crypt onchain (Solana) | Metaplex metadata (Grading ID/Company/Grade, Insured Value). Buyback program `CcBuyM7s…`, VRF `ccvrfu3f…` | Onchain data public; trait text is theirs | UNCLEAR | |
| Magic Eden API | Keyless v2; `x-ratelimit-limit: 180`; CC collection floor/listings | UNCLEAR (API terms PDF 403) | UNCLEAR | API terms text |
| Jupiter gacha front-end | Docs: OP packs from CC and Phygitals; buyback windows 3d/7d | UNCLEAR | UNCLEAR | Terms |
| Phygitals | Docs only; buyback 85% FMV; odds not published | **No** (personal use; bots/scraping and distribution banned, ToS §10–11) | **No** | — |
| Courtyard (Polygon) | No public API; token traits Grader/Grade/Serial/Language/Set | **No** (§11.1 no public display/commercial; §14.8 no scraping) | **No** | One Piece coverage |
| Renaiss (BNB) | No API | **No** (§4.6 no scraping, no competing service) | **No** | — |
| Beezie | Press only ("up to 90% of FMV", ESTIMATED) | UNCLEAR (ToS not found) | UNCLEAR | Everything |
| OpenSea | API with key | Only with **written permission**; attribution required (ToS §10) | No | — |
| Tensor | API key by application | UNCLEAR | UNCLEAR | Terms |
| PSA cert API | Token; 100 calls/day free (MEASURED 429). Fields: Brand/SetName/CardNumber/Subject/Variety/Grade. **No language field** | UNCLEAR (EUA unreadable) | UNCLEAR | Terms |
| CGC, Beckett | Web lookup only | UNCLEAR | UNCLEAR | All |

**Rules:**
- Nothing is displayed publicly from a source until written permission or clear
  terms are on file (owner action: email Collector Crypt and Magic Eden first).
- Phygitals, Courtyard and Renaiss are **excluded** unless they grant permission.
- Onchain reads of public program accounts are the fallback data path, but trait
  text and FMV are still the platforms' content, so they stay gated by the same
  permission check.

### B2. Identity (fail closed)

- Card Pirate prices **Japanese** exact CardPrints. A slab maps only if **all** of
  these resolve to exactly one CardPrint:
  - grader + cert + grade;
  - language explicitly Japanese;
  - card number;
  - set/release (via `release_product_id`, never from the code prefix);
  - variant (alt art, parallel, manga).
- Otherwise the slab is shown **"unmatched"**.
- Cert lookup (PSA) carries language and variant only as free text, so every match
  goes through the existing manual-review queue pattern. There is no auto-approval
  of fuzzy matches.

**Match rate:**
- In a 50-card sample of the CC `onepiece_250` pool, **5/50 (10%) were explicitly
  Japanese**. Graders: 38 PSA, 11 Beckett, 1 none (MEASURED).
- **ESTIMATED exact-match rate: 5–8% of OP slabs**, because not all Japanese slabs
  resolve to one variant.
- English slabs have **no** Card Pirate price, since Card Pirate does not track
  English cards. They are shown as "no Japanese-market equivalent", never compared.

### B3. Like-for-like comparisons

- Onchain items are graded slabs. Compare them **only with Japanese PSA10 asks**
  (SNKRDUNK), never with raw prices.
- **Hard dependency on D (PSA10).**
- Other grades (PSA 9, BGS) have no Card Pirate counterpart → shown without
  comparison.

**What can ship before D:**
- The internal ingestion and matching review queue.
- A coverage/methodology page.
- Facts the platforms themselves publish (pack price, odds, buyback %), only if
  terms permit.
- No price comparison.

### B4. Pack value check

- Collector Crypt publishes odds per tier and the pool with `insured_value`. One
  Piece machines (MEASURED, `gacha.collectorcrypt.com/api/machines`):

  | Machine | Price | Odds C/U/R/E | Buyback | Platform EV |
  |---|---|---|---|---|
  | Ocean Blue | $50 | .80/.15/.04/.01 | 85% | $55.20 |
  | Crew | $250 | .75/.20/.04/.01 | 90% | $262.48 |
  | Emperor | $1,000 | .75/.20/.04/.01 | 93% | $1,021.20 |

- **Card Pirate check:** EV is recomputed using Card Pirate's Japanese PSA10 price
  (converted to USD with a stated FX source/time) **only for matched pool cards**.
  Unmatched cards keep the platform's own insured value, labelled as theirs.
- Show coverage (% of pool value matched), an uncertainty band, and buyback-adjusted
  value (buyback% × FMV).
- **Copy rules:**
  - "This is how the pack's contents compare with Japanese market prices."
  - No "worth it", no odds advice, no gambling framing.
  - Never shown for packs whose odds or pool are unpublished (Phygitals, Courtyard).

### B5. Positioning

- Lives as **"Onchain" inside Market** (`/analytics` → "Onchain market" section), not
  as a separate crypto page.
- Collector language ("graded cards held in vaults and traded as tokens").
- No wallet connect, no affiliate links, no buy/sell CTAs, no token tickers in the UI.

### B6. Storage and requests (ESTIMATED)

**Requests:**
- CC machines: 1/day.
- Pools: 3 machines × paged `getNfts`, about 10–20/day.
- ME stats: 1/day.
- PSA cert lookups only for new Japanese slabs (≤100/day free tier).
- Total about 30–150 requests/day.

**Storage:**
- RAW JSON persisted before parsing: about 1–3 MB/day (≈1% of the 208 MB/day
  MEASURED session-5 baseline).
- Parsed rows: about 300–600/day (pool snapshot rows).
- With daily-v1 dictionary encoding of repeated JSON, likely <0.5 MB/day.

**Fit:** fits once the capacity mission's storage forecast passes. It does **not**
fit "before" that gate per the capacity rule "no capture expansion before storage
passes".

This adds new source scope. Building it needs this plan approved, plus AMBER
preflights (new source, new collector schedule).

---

## C. Launch access tracker

**Goal:** a safer answer to cancelled pre-orders. Show what is coming, when, where to
enter lotteries, and what is being reprinted.

### C1. Sources (MEASURED 2026-10-08)

| Source | Published | robots | Terms | Method |
|---|---|---|---|---|
| onepiece-cardgame.com /products/, /news/ (JP) | Release dates (e.g. OP-18 2026.11.21, EB-05 2026.10.31), events, restrictions. **No RSS** | 404 (no file) | Footer: 無断転用・転載 prohibited | **Auto** ≤2×/day; store facts only (code, title, date); link out |
| en.onepiece-cardgame.com | EN dates (OP-18 shown Nov 20 vs JP Nov 21) | 404 | "may not be reproduced without permission" | **Auto** ≤1×/day, per-region dates |
| X @ONEPIECE_tcg / _EN / @ONEPIECEtcgSHOP | Reprints (e.g. EN reprint 2026-05-14), shop lotteries, face-ID notice (official shop from 8/22) | Scraping banned | Paid API only (~$10/month ESTIMATED pay-per-use) | **Curate** (or paid API: owner decision) |
| Premium Bandai | Pre-orders and lotteries | Disallows /mypage, /order_info, /search… | "Excessive operations" restrict accounts; geo-redirect | **Curate** |
| Official card shops, BASE SHOP | App lotteries with face ID | — | Identity-bound | **Curate (dates + link only)** |
| Yodobashi, Bic Camera | Store/web lotteries | Not retrievable (timeouts) | Not read | **Curate** |
| Amazon.co.jp | Invitation sales | Many disallows incl. availability | Robots/data-mining banned (ESTIMATED) | **Avoid** |
| Joshin, Toys"R"Us | App/QR lotteries | 403 (bot-protected) | Not read | **Curate** |
| 7net, Aeon, GEO, Hobby Station, card shops (Card Rush, Card Labo, Yellow Submarine) | Lottery notices | Mostly permissive | Not read | **Curate**; optional 1×/day news-page check only after terms are read from a JP IP |

**Never automate** cart, login, search, availability, entry forms, LivePocket, store
apps, stock polling, or second-level countdowns. That keeps it unlike a purchasing
bot. Never reproduce text or images.

### C2. Data model (additive migration, AMBER)

- **`launch_items`:**
  - Columns: `id`, `release_product_id` (nullable FK, **existing identity**; no new
    card identity), `region` (`jp|en|asia`), `kind` (`release|lottery|reprint|
    shortage|restock_notice`), `title_own_words`, `retailer`, `entry_method`
    (`web|app|in_store`), `id_requirement`, `window_start_at`, `window_end_at`
    (UTC), `announced_at`, `source_url`, `source_kind` (`official|retailer|x`),
    `status` (`proposed|published|withdrawn`), `curated_by`, `created_at`,
    `published_at`.
  - Rows are never edited after publish: a correction creates a new row and
    supersedes the old, keeping history.
- **`launch_source_snapshots`:** RAW HTML of official pages, persisted before
  parsing (invariant), about 0.5 MB/day (ESTIMATED).
- **Retail vs sealed market price:** sealed product is **not tracked**. Show the
  official retail price as a fact only. No market comparison until a sealed-price
  workstream exists (out of scope).

### C3. Display

- "Upcoming" (under Releases or Market):
  - upcoming releases with per-region dates;
  - open/closing lottery windows (day/hour precision);
  - reprints;
  - history.
- Alerts later, after collector accounts exist.

---

## D. PSA10 activation readiness

**Built:**
- Same-page SNKRDUNK parse (`extract_psa10`), adding no extra requests.
- Observation storage (`psa10_asking`, `condition_label='PSA10'`).
- Freshness category `psa10` in the model.
- Exclusion from Index/MV/CPI.

**Missing:**
1. Planner/scheduler wiring for the `psa10` freshness category, with budget accounting.
2. Source instrument registry entry (`reference_type`).
3. Public API: a distinct graded series (`/prints/{id}/series?series=psa10_ask`).
   `/prices` must label or filter PSA10 and never mix it with raw.
4. UI: a "PSA 10 ask (SNKRDUNK)" category on card pages, distinct from Market Value,
   with collector copy.
5. Market Value rule: stays **excluded** (invariant: a distinct category).
6. A freshness/health section in state and verifiers.
7. Writer flag gating actually checked in app code. Today `PSA10_ENABLED` is not
   read anywhere.

**Impact:**
- Requests: +0 (same page).
- Rows: about 353 SNKR mappings → ≤353 psa10 obs/day (≈0.1 MB/day ESTIMATED).
- RAW: unchanged.
- The SNKR window already reaches **93% of its 3,100-request budget in one turn**
  (MEASURED session 5, 2,882 requests). PSA10 adds none, but any SNKR expansion must
  respect that.

**Dependency:** the capacity mission must first finish:
- daily-v1 activation;
- 24h physical-growth evidence;
- recomputed 30/90-day forecasts with the 3 GiB reserve;
- the PR80 busy-window evidence.

**Earliest safe activation:** the day after the daily-v1 24h window closes and
forecasts pass. ESTIMATED **≥2026-10-10**, since daily-v1 was not yet active at
13:15Z on 2026-10-08.

**Evidence required:**
- A natural SNKR turn with PSA10 rows for exact mapped prints.
- 0 PSA10 rows in Index/MV inputs.
- API/UI category verified.
- Runtime and budget unchanged.

PSA10 stays **OFF** until then.

---

## E. Sequencing and dependencies

**API-touching PRs imply a collector release** (continuity over `services/api`).
Choose one:
- **(a)** Treat them as collector releases, scheduled outside quiet windows. This is
  the default and needs no verifier change.
- **(b)** A separate verification PR narrowing `SNKR_PATHS` to the modules the
  collector actually imports. AMBER: a verification change that must be proven not
  weaker, reviewed explicitly.

Until then, prefer putting anchoring and launch ingestion in a **new service/package**
(e.g. `services/anchor_worker`) whose reads use the public API or read-only DB
access. Public API endpoints still live in `services/api`.

| # | Session / PR | Workstream | Class | Migration | Redeploys collectors? | Blocked by |
|---|---|---|---|---|---|---|
| 1 | Merkle builder + proof endpoint + OTS stamping (staging); `publication_anchors` table; methodology page draft | A | AMBER (additive migration) | yes (1 table) | **Yes** under (a), since it touches services/api | Quiet windows only |
| 2 | Anchor contract (Base **Sepolia**), signer per custody decision, daily anchor job, open verifier script + static page | A | **RED decision first** (custody), then AMBER | no | No if built as separate worker | Owner key-custody decision |
| 3 | Launch tracker: `launch_items` model + admin curation UI + public "Upcoming" page | C | AMBER (additive migration) | yes | Yes under (a) | — |
| 4 | Official JP/EN products/news watcher → RAW → admin proposal queue (≤2×/day) | C | AMBER (new source) | small | No (separate worker) | Session 3 |
| 5 | PSA10 activation: planner wiring, instrument entry, gating, API series, UI category, verifiers | D | AMBER | maybe | **Yes** (collector + API) | Capacity mission: daily-v1 24h + forecast pass |
| 6 | Onchain ingestion (CC API + Solana reads) + slab→CardPrint manual review queue (no public display) | B | AMBER (new source) | yes | Possibly (new worker) | Written terms permission; storage pass |
| 7 | Public "Onchain market" in Market + pack value check | B | GREEN/AMBER | no | No | Sessions 5 & 6; permission on file |
| 8 | Mainnet anchoring of production publications | A | **RED** (production) | — | — | Owner authorization |

**For each session:**
- **Rollback:** native revert. Additive tables are left in place (no destructive
  downgrade).
- **Tests:** mocks/fixtures before live; Merkle and proof golden vectors; identity
  fail-closed tests.
- **Verification:** strict staging delivery receipt + natural observation.

**Quiet windows (newest capacity handoff, session 5 + session 6 state at 13:15Z):**
- 2026-10-09 **02:00–06:00Z** (no collector redeploys).
- **24h after daily-v1 activation** (rollback only). daily-v1 was not yet active at
  plan time; its window will be published in the capacity session-6 handoff.
- Collector-redeploying sessions (1, 3, 5) must avoid both.

**Collector-accounts v1:**
- No `plan/collector-v1` branch exists (checked 2026-10-08).
- When it lands, alerts for launch items (C) and onchain watch (B) should use its
  account model, not a parallel one.

---

## Owner decisions (with recommended defaults)

1. **Key custody (RED).**
   - Default: **K0 now (OTS only) → K1 later** (dedicated Railway secret hot key ≤$5,
     contract owned by your hardware wallet/Safe, rotation documented).
   - Tradeoff: K2 (KMS) is safer but adds a paid provider (also RED); K3 breaks
     automation.
2. **Chain.**
   - Default: **Base** (write-once contract) + **OpenTimestamps**.
   - Tradeoff: OP is ~3× cheaper but less collector-recognisable. EAS adds a
     browsable page for ~$0.14/month. L1 is the strongest but costs $1.25–16.55/month.
3. **Where the onchain view lives.**
   - Default: **section inside Market** ("Onchain market").
   - Tradeoff: a separate page is more visible but pulls the brand toward
     "crypto terminal".
4. **Gacha affiliate links.**
   - Default: **No.**
   - Tradeoff: revenue vs referee independence. Links would make Card Pirate a
     promoter of a gambling-like product it is rating.
5. **Launch tracker: automation vs curation.**
   - Default: **auto-watch official Bandai JP/EN products/news only** into an admin
     queue; **curate everything else**.
   - Tradeoff: full curation is safest but laborious; X paid API (~$10/month) speeds
     reprint news (new paid service: your call).
6. **Data permissions (owner action).**
   - Email Collector Crypt and Magic Eden for written display permission before any
     B display.
   - Accept exclusion of Phygitals, Courtyard and Renaiss unless they grant it.
7. **Genesis/backfill policy.**
   - Default: one labelled genesis anchor of all existing receipts; no per-day
     backdating.
8. **Continuity constraint.**
   - Default: option (a), API PRs are scheduled collector releases.

## Risks

- **Storage:**
  - B adds 1–3 MB/day RAW (ESTIMATED), and C ~0.5 MB/day.
  - Both are blocked until the capacity forecast passes.
  - A is negligible.
- **Identity match rate:**
  - Only ~10% of the sampled CC One Piece pool is Japanese (MEASURED). Exact match is
    ESTIMATED at 5–8%.
  - Most onchain OP slabs will show "no Japanese-market equivalent".
  - The view's value may be limited. Validate with a larger read-only sample before
    building B public display.
- **Terms of use:** no platform grants display rights explicitly. Three forbid it.
  OpenSea needs written permission. PSA API terms are unread. B public display is
  gated on written permission.
- **Brand positioning:**
  - An onchain section risks "crypto terminal" drift.
  - Mitigations: inside Market, collector copy, no CTAs, affiliates, wallets or
    tickers.
  - The pack check must avoid gambling framing.
- **Operational:**
  - API changes force collector releases (continuity).
  - Public RPC history pruning (MEASURED) → store own tx refs and OTS proofs.
  - L2 sequencer/upgradability risk mitigated by OTS.
- **Regulatory:** reporting EV of gacha packs could read as promotion. Keep it
  descriptive, with no links. No feeds for leveraged products. No hosting of gacha,
  pre-order tokens or fee-share tokens.
