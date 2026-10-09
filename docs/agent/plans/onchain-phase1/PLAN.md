# Onchain Phase 1: "Price Referee" plan

Status: **PLAN ONLY**, for owner review. Written 2026-10-08 on base `origin/staging`
336706a. No code, PR, deploy, staging write, wallet, key or transaction was made.
Numbers are MEASURED (with source and time) or ESTIMATED.

**Amendment 1 (2026-10-09):** adds workstream F (Packs: partner gacha integration),
records the owner decisions of 2026-10-09, adds Robinhood Chain as an optional second
anchor, and updates §E and the owner-decision list. Research was public sources and a
few read-only GETs only; no account, key, wallet or transaction was created.

Card Pirate becomes the independent price referee for the onchain One Piece card
market. It is not a marketplace, vault, token issuer or price feed for leveraged
products. It does not operate gacha; it may host **partner-run** packs (workstream F)
under the independence and disclosure rules in §F. Collector positioning ("not a crypto or trading terminal")
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
| Robinhood Chain (Arbitrum Orbit), contract or calldata | <$0.01 (ESTIMATED from gasPrice 0.02 gwei, 25–50k gas; L1 data fee unmeasured) | <$0.30 (ESTIMATED) | Optional second anchor only, see below |

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
4. **Optional second anchor: Robinhood Chain**, same write-once contract, only after
   the Base contract exists. Pre-conditions confirmed 2026-10-09 (MEASURED):
   - Permissionless: "Anyone can interact with the network … and deploy smart
     contracts" (docs.robinhood.com/chain). No allowlist or Robinhood account.
   - Terms (docs.robinhood.com/chain/terms-of-service) bar only comprehensively
     sanctioned jurisdictions (OFAC/UK/EU); Malaysia is not listed.
   - Public RPC `https://rpc.mainnet.chain.robinhood.com` (keyless, rate-limited,
     "not for production"); live `eth_chainId` = 4663, `eth_gasPrice` = 0.02 gwei.
   - Public explorer: `https://robinhoodchain.blockscout.com`.
   - Gas token ETH; canonical bridge via portal.arbitrum.io (≈10 min in, 7-day out).
   - Mainnet date 2026-07-01 seen only on third-party pages (not verified officially).
   It uses the same signer decision as Base; no extra work beyond a second deploy and
   a second write in the anchor job. Skip it if that is not wanted.

No token, ever.

### A3. Key management

**Owner decision 2026-10-09: start with K0 (no key, Bitcoin timestamps only).** The
Base (and optional Robinhood Chain) signer decision is **deferred**; K1–K3 below remain
the options for that later decision.

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
- No wallet connect, no affiliate links, no buy/sell CTAs, no token tickers in the
  price parts of the view. The only exception is the separate **Packs** area defined
  in §F (owner decision 2026-10-09), which has its own disclosure rules.

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

## F. Packs (partner gacha integration)

**Owner decision 2026-10-09:** partner gacha integration is in scope. Owner accepted
risk. Card Pirate hosts **partner-run** packs. It never operates its own gacha, holds
user funds or cards, sets odds, or funds buybacks.

**Goal:** collectors can open a partner pack from inside Market and see, on the pack
itself, how its contents compare with Card Pirate's own prices, with the commercial
relationship disclosed.

### F1. Partner options (research 2026-10-09)

| Partner | Integration method | Settlement | Requirements on Card Pirate | Revenue terms | One Piece |
|---|---|---|---|---|---|
| **Collector Crypt (CC)**, wallet API | Documented server API (`docs.collectorcrypt.com/gacha/api`): `generatePack` returns a partially signed USDC transfer; the user signs in their own Solana wallet; `submitTransaction` → `openPack` (≤2 h, else auto-refund) → optional `buyback` (≤72 h). No iframe/SDK/Blinks found; demo repo `github.com/daxherrera/gacha-starter`; devnet at `dev-gacha.collectorcrypt.com` (MEASURED) | USDC on Solana; user pays the CC gacha wallet directly. Partner fees accrue in µUSDC and are paid to the partner's treasury wallet, **released manually by a CC admin** (MEASURED) | `x-api-key` (server-side secret; prefixes the onchain memo with the partner slug, e.g. `me-<uuid>`). Key needs `can_adopt` enabled on request. A receive-only Solana USDC address. Wallet-connect UI. No custody (MEASURED) | **Fee mechanics MEASURED:** per-pack fee carved out of pack EV, capped at min(10% of pack price, amount keeping EV ≥ pool floor). New accounts default to **split fee**: half on pack completion, half only if the card is bought back. **Headline rev share / partner ToS: not published** | Yes: `onepiece_50` $50, `onepiece_250` $250, `onepiece_1000` $1,000 (MEASURED `/api/machines`, 114 machines total). Partner variants `bf_op*`, `fb_op*` exist (`public:false`). **No language field; pools are mixed-language** (1/100 sampled names marked Japanese; PSA 72, Beckett 26, BGS 1, CGC 1, MEASURED) |
| CC, invoiced API | Off-chain: partner runs accounts and payments; CC holds won cards; monthly invoice (packs − partner fee − buybacks + shipping); credit limit from $50,000 (MEASURED `/gacha/invoiced-api`) | Fiat/USDC invoice to partner | Own payments, user ledger, credit exposure: **custody of user funds**. Rejected | Same fee model | Same pools |
| Phygitals B2B | **No public API, embed or white-label.** Powers Jupiter's packs incl. One Piece "Throne" (MEASURED docs.jup.ag gacha). Underdog Rips (sports only, US) and the Vegangster operator deal have no published method (Vegangster page 403) | USDC; Phygitals custodial; Privy embedded wallets (MEASURED ToS §3, §16) | Private negotiation (hello@phygitals.com). Creator Packs require supplying inventory; Vendor Program is listings only | **Undisclosed** | Yes (collection listed), language unstated; **odds and pools not published**; ToS §10–11 bans bots/scraping/distribution without written consent (MEASURED, still current) |
| Phygitals referral | Personal referral link | In-app credits, "no cash value" | Guidelines: "personal and non-commercial", no domains/ads using the name (MEASURED) | "percentage of qualifying purchases"; the 1% figure **not confirmed** (in-app page 429) | — |
| Courtyard referral | Personal referral link | Points → pack credit (5,000 pts = $25) or a $25+ buyback offer; sources conflict (MEASURED docs vs blog snippets) | Rules: personal and non-commercial, no cash value (MEASURED) | Credit only, first 6 referrals | — |
| Jupiter gacha | Front-end only (uses CC and Phygitals) | USDC | — | No integrator/referral fee in gacha docs (MEASURED) | Yes (via CC/Phygitals) |
| Beezie, Renaiss | No partner path found | — | — | Beezie 0.5% referral, Renaiss points only (ESTIMATED, third-party) | Unknown |

**Conclusion:** the only real, documented, revenue-earning path is **CC wallet API with
an adopted machine**. Referral programs pay credit only and forbid commercial site use:
**not usable**. Phygitals is a later, negotiated option.

**Partner activity figure:** "21 partner storefronts, $1.18M, five above $70K, ~6% of
GMV" appears only in a third-party note (4Pillars research, read via search snippet;
page 429). Whether $1.18M is revenue or GMV and which month is not confirmed. Treat as
ESTIMATED.

### F2. What Card Pirate runs (lightest option that earns revenue)

| Option | Revenue | Card Pirate runs | Custody | Verdict |
|---|---|---|---|---|
| F-0. Display only (pack facts + value check, link to CC) | None (attribution is by API key, so a plain link earns nothing) | Nothing new beyond §B | None | Ships first, as part of session 7 |
| **F-1. CC wallet API, adopted machine** | Per-pack fee | Server-side proxy route holding `x-api-key`; client wallet-connect; receive-only treasury address; event log | **None.** USDC goes user → CC gacha wallet; cards stay in CC vault, owned by the user's wallet | **Recommended** |
| F-2. CC invoiced API | Per-pack fee | Payments, balances, user ledger, credit line | User funds | Rejected |

**F-1 components:**
- **Proxy:** Next.js route handlers in `apps/web` (`/api/packs/*`) that add the API key
  and forward `generatePack`, `submitTransaction`, `openPack`, `pack/status` and
  `buyback`. The key is a server-only env secret, never `NEXT_PUBLIC_*`, never
  logged. Keeping it in `apps/web` avoids `services/api` and so needs **no collector
  redeploy** (§E continuity rule).
- **Wallet connect:** Solana wallet adapter (Phantom, Solflare, Backpack), only on
  the Packs pages. Card Pirate never holds a key or signs for the user. One pack per
  signature: the multi-pack `generateYoloPacks` endpoint is not exposed.
- **Treasury:** a receive-only Solana USDC address created by the owner on their
  hardware wallet. Card Pirate's servers hold **no private key**. CC releases fees to
  that address manually, so no hot key or automation is needed. This is separate from
  the deferred Base anchor-key decision.
- **Rate limits:** CC states a 300/min/IP POST limit (MEASURED, §B1). The proxy uses
  per-user and global limits well below that.

### F3. Independence rules (hard)

1. **Same check for every pack.** The pack value check (§B4) is computed with the
   same code, inputs and Card Pirate prices for partner and non-partner packs. A
   partner flag is not an input to it.
2. **Shown on the partner pack itself,** including when the expected value is below the
   pack price. It is never hidden, collapsed or reordered for partner packs.
3. **Partners never influence displayed prices.** Partner data feeds only pack facts
   (price, odds, pool, buyback %, their own insured values, labelled as theirs). It is
   never a Card Pirate price input. Nothing from F writes to `market_index_snapshots`,
   `market_value_points` or any observation table.
4. **The fee lowers the pack's EV.** CC carves the partner fee from pack EV (MEASURED).
   So:
   - Card Pirate sets a **low fixed fee** (recommended ≤5% of pack price; owner sets).
   - The fee is shown in dollars next to the price.
   - The same machine bought directly from CC (without the Card Pirate fee) is listed
     beside it, with its own EV. Collectors can pick the cheaper route.
5. **Neutral on buyback.** CC's default split fee pays half the fee only on buyback,
   which would reward Card Pirate for steering collectors to sell back. Ask CC to set
   **non-split fee**. If refused, disclose it in the pack's disclosure line. In either
   case, buyback is shown neutrally: the offer, Card Pirate's price for that card if it
   is matched, and "keep" and "sell back" as equal-weight choices.
6. **Ordering:** packs sort by price, never by fee or partner status.
7. **Coverage honesty:** pools are mixed-language and Card Pirate prices only Japanese
   prints. The value check states "Card Pirate can check N% of this pack's value" and
   shows the platform's own values for the rest, labelled as theirs.
   - Mitigation (outreach item): ask CC whether a partner can run a **Japanese-only
     One Piece machine** (`can_build_machines` / `can_edit_hashlists` exist,
     MEASURED). That would make the Card Pirate check meaningful.
8. **Removal rule:** if a partner refuses to let the value check appear, or asks Card
   Pirate to change a price, the partner pack is removed. The rule is written on the
   methodology page.

### F4. Placement, copy and disclosure

- **Where:** Market → "Onchain market" → **Packs** tab, visually separate from price
  charts. No pack content appears on card pages, Index or Market Value.
- **Pack card (side by side):** pack price · Card Pirate fee · odds per tier · pool
  (browsable, with grader/grade/language where known) · buyback rate and window ·
  platform EV (theirs) · **Card Pirate value check** (coverage %, range) · same pack
  direct from CC.
- **Disclosure** next to the price on every partner pack: "Card Pirate earns $X if you
  open this pack." Add "…and $Y more if you sell the card back" while split fee applies.
  A methodology link explains the arrangement.
- **Collector language:** "open a pack", "graded cards held in a vault", "sell back
  within 3 days". No token tickers, "rip", "jackpot" or "win" language.
- **No dark patterns:**
  - No countdowns. The buyback deadline is a date, not a ticking timer.
  - No streaks, daily rewards, loyalty tiers or free spins.
  - No "near miss" or "so close" framing; no animation that teases higher tiers.
  - No live winners feed (CC's Ably feed is not used).
  - No multi-pack or auto-repeat.
  - No pre-checked "open again".
  - No push or email nudges.
- **UI process:** the visual design goes through the CardPirate collector UI skill
  and ATLAS loop as its own tranche (contract, before/after screenshots, fresh
  visual reviewer).

### F5. Accounts

- **Browsing packs** needs no sign-in.
- **Opening a pack** needs only a connected Solana wallet. Card Pirate creates no
  separate account, which is the lightest option.
- **Optional:** a signed-in collector (existing next-auth session used by
  Collection/Wishlist) can save a wallet address, so pulled cards appear in My
  Collection.
  - No `plan/collector-v1` branch exists (checked 2026-10-09).
  - When it lands, wallet linking should use its account model.

### F6. Analytics, attribution and revenue tracking

- **`pack_open_events`** (additive, in the web app's database or a new small table via
  §E rules):
  - Columns: `memo` (CC's, carries the slug), `machine_code`, `price_usdc`,
    `fee_usdc`, `fee_mode` (`full|split`), `status`
    (`generated|submitted|opened|refunded|bought_back`), `tx_signature`,
    `created_at`, `updated_at`.
  - Wallet address stored only as a salted hash. No IP or user agent.
- **Daily reconciliation** (read-only):
  - CC `getWinners?slug=<ours>` vs our events.
  - Treasury USDC receipts via a public Solana RPC, matched to CC payout releases.
  - Mismatches go to the admin page; nothing auto-corrects.
- **Admin view:** opens per machine, fee earned vs fee released, refund and buyback
  rates.
- **Public transparency (recommended):** a monthly line on the methodology page: packs
  opened via Card Pirate, fees earned.
- **Page analytics:** aggregate counts only (views, value-check expands, opens). No
  per-user funnel or retargeting.

### F7. Storage and requests (ESTIMATED)

- **Pack facts and pools:** already counted in §B6 (CC machines 1/day, pools 10–20/day).
  F adds none.
- **Per pack opened:** 3–5 user-initiated proxy calls to CC. They are not
  collector-budget requests and do not touch the SNKR/Yuyu budgets.
- **Reconciliation:** 2–5 requests/day.
- **Storage:** about 1 KB per event. Even 1,000 opens/month is about 1 MB/month,
  negligible against the capacity forecast.
- **RAW rule:** reconciliation responses are persisted before parsing, under the same
  invariant (<0.1 MB/day).

### F8. Revenue size (ESTIMATED)

- At a 5% fee: 100 Ocean Blue ($50) opens/month = $250/month, halved for cards not
  bought back under split fee.
- At a 5% fee: 20 Crew ($250) opens/month = $250/month.
- Actual volume is unknown until launch.

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
| 2 | Open verifier script + static page against OTS proofs (K0). Later: anchor contract on Base **Sepolia** (+ optional Robinhood Chain testnet), daily contract write | A | AMBER; contract part **RED decision first** (deferred Base key) | no | No if built as separate worker | Verifier: session 1. Contract: owner Base-key decision |
| 3 | Launch tracker: `launch_items` model + admin curation UI + public "Upcoming" page | C | AMBER (additive migration) | yes | Yes under (a) | — |
| 4 | Official JP/EN products/news watcher → RAW → admin proposal queue (≤2×/day) | C | AMBER (new source) | small | No (separate worker) | Session 3 |
| 5 | PSA10 activation: planner wiring, instrument entry, gating, API series, UI category, verifiers | D | AMBER | maybe | **Yes** (collector + API) | Capacity mission: daily-v1 24h + forecast pass |
| 6 | Onchain ingestion (CC API + Solana reads) + slab→CardPrint manual review queue (no public display) | B | AMBER (new source) | yes | Possibly (new worker) | Written terms permission; storage pass |
| 7 | Public "Onchain market" in Market + pack value check | B | GREEN/AMBER | no | No | Sessions 5 & 6; permission on file |
| 8 | Mainnet anchoring of production publications | A | **RED** (production) | — | — | Owner authorization |
| 9 | Packs F-1 on **devnet**: `apps/web` proxy routes (server-only API key), wallet connect, `pack_open_events`, reconciliation job, admin view, Packs tab UI tranche (ATLAS loop) with disclosure and value check | F | AMBER (new external integration, additive table) | yes (1 table) | **No** (`apps/web` only) | Session 7 (value check); CC API key with `can_adopt` + written terms; CC devnet access |
| 10 | Packs live on mainnet: adopted machine(s), treasury address, real USDC | F | **RED** (production, real money) | — | No | Session 9 verified on staging; owner treasury address; owner go-ahead |

**Packs (F) placement in the order:** F-0 (display only) ships inside session 7.
Session 9 can be built in parallel with session 8, because it needs neither PSA10
activation nor anchoring, only the value check from session 7. Session 10 is last.
F adds no collector capture, so it is not blocked by the capacity mission beyond what
already blocks sessions 6–7 (B ingestion needs the storage pass). F touches no
`services/api` code, so it causes no collector redeploys and is unaffected by quiet
windows.

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

## Owner decisions

**Decided 2026-10-09 (final):**
- Gacha integration in scope (owner accepted risk).
- Anchoring: Base primary + OpenTimestamps; Robinhood Chain optional second anchor
  (pre-conditions confirmed, §A2).
- Key custody: start with K0 (OpenTimestamps only); Base key deferred.
- Onchain view: a section inside Market.
- Launch tracker: auto-watch Bandai official JP/EN products/news only; curate the rest.

**Still open (with recommended defaults):**

1. **Which partner to approach first.**
   - Default: **Collector Crypt** (info@collectorcrypt.com, or a Discord ticket at
     discord.gg/CollectorCrypt). It is the only partner with a documented API, a
     partner fee model and published One Piece odds/pools. One email also covers the
     §B data-display permission.
   - Later: Phygitals (hello@phygitals.com), only if CC declines. Their terms are
     private and their odds/pools unpublished, so the value check could not run.
   - Magic Eden: still email for §B display permission (no pack partnership).
2. **Outreach contents (CC email).** Ask for:
   - an API key with `can_adopt` (and, if possible, `can_build_machines` /
     `can_edit_hashlists`) plus devnet access;
   - the partner terms of service and API-data licence, including **written
     permission to display machine facts, odds, pools and insured values** (§B);
   - **non-split (full) fee mode**, and the fee amount we intend (≤5%);
   - whether a partner can run a **Japanese-only One Piece machine**;
   - payout cadence for manual releases, minimum payout, and the treasury setup;
   - KYC or geo requirements on partners and players (blocked-address rules);
   - confirmation that Card Pirate may show its own independent value check, including
     when EV is below price, on the partner pack;
   - the actual revenue split, if any, beyond the adopted-machine fee.
   Introduce Card Pirate as an independent Japanese-market One Piece price referee,
   and state the independence rules (§F3) up front.
3. **Card Pirate pack fee level.** Default ≤5% of pack price (CC cap is 10%).
4. **Treasury address.** Default: a receive-only Solana USDC address on your
   hardware wallet. No server key.
5. **Base anchor key (deferred).** When ready: K1 (dedicated Railway secret hot key
   ≤$5, contract owned by hardware wallet/Safe) is the recommended default; see §A3.
6. **Robinhood Chain second anchor.** Default: add it with the Base contract (low
   cost); skip if you prefer one chain.
7. **X paid API for reprint news** (~$10/month ESTIMATED, new paid service). Default:
   no; curate.
8. **Data permissions (owner action).** Covered by outreach above for CC; email Magic
   Eden separately. Phygitals, Courtyard, Renaiss stay excluded unless they grant it.
9. **Genesis/backfill policy.** Default: one labelled genesis anchor of all existing
   receipts; no per-day backdating.
10. **Continuity constraint.** Default: option (a), API PRs are scheduled collector
    releases.
11. **Public fee transparency line.** Default: yes, monthly packs-opened and
    fees-earned on the methodology page.

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
  - Mitigations: inside Market, collector copy, no CTAs, wallets or tickers in the
    price view. Wallet connect and partner packs are confined to the Packs tab (§F4).
  - The pack check must avoid gambling framing.
- **Operational:**
  - API changes force collector releases (continuity).
  - Public RPC history pruning (MEASURED) → store own tx refs and OTS proofs.
  - L2 sequencer/upgradability risk mitigated by OTS.
- **Gacha (F):** owner accepted risk (2026-10-09). No feeds for leveraged products;
  no pre-order tokens or fee-share tokens; Card Pirate never operates its own gacha.
- **Independence perception (F):** earning from packs Card Pirate also rates.
  Mitigated by §F3 rules (same check, disclosure, direct-from-CC comparison, neutral
  buyback, removal rule) and the public fee line.
- **Partner dependency (F):** CC fee payouts are manual and terms unpublished; the
  API silently drops attribution on a wrong key (memo falls back to `cc-`, MEASURED).
  The daily reconciliation catches both.
- **Low check coverage (F):** pools are mixed-language (~1% Japanese in a 100-card
  sample, MEASURED). Without a Japanese-only machine, the Card Pirate value check
  covers a small share of pack value and must say so.
