# Card Pirate roadmap (single source of truth)

As of 2026-10-28 15:20Z, staging `7df197b` (after #237). Staging only; production RED; PSA10 OFF.
Previous revision: 2026-10-18 23:00Z (`99844c6`, after #174).

This file is the one place that says what Card Pirate is building, in what order, and where each item
stands. Plan branches (`plan/*`), handoffs and reports are the detail behind it.

## Rules for this file

1. **Newer owner decisions override older plans.** Where a plan conflicts with a later owner decision,
   the old item is marked **superseded** here with the decision that replaced it. The plan text itself
   is history and is not edited.
2. **Status comes from evidence, not plan text**: merged PRs, CI delivery receipts, and read-only
   `ops-readonly` runs (run ids below). Each status is one of: done, in progress, planned, blocked,
   superseded.
3. **Class** follows [AUTONOMY_POLICY.md](AUTONOMY_POLICY.md): GREEN, AMBER (preflight and rollback)
   or RED (owner decision). An item lists the class of its next step.
4. Live numbers go stale. Re-read the runbooks before acting on any number here
   ([OPS_RUNBOOKS.md](OPS_RUNBOOKS.md)). Labels: MEASURED (run id given), CARRIED FORWARD (from a
   named document), ESTIMATE, NOT MEASURED.
5. Update this file in the same PR as any owner decision or delivery that changes an item's status.

## 1. Owner decisions that override older plans

| Date | Decision | Superseded plan items |
|---|---|---|
| 2026-10-16 | Add Dorasuta and CardRush now. | The rule against a third source before two-source stability ([PROJECT_HANDOVER.md](PROJECT_HANDOVER.md) §8, "do not expand source scope"); `plan/data-platform` plain summary 5 and §G6 source order (Cardmarket and Aucfan first, shops later); `plan/source-survey` §5 order. |
| 2026-10-16 | No permission requests to sources. Collect public pages with an honest User-Agent, respect robots.txt, stop on any 403 or 429. (Outreach closed 21:45Z, recorded in `plan/official-channels` §6.) | `plan/data-platform`: "permission comes first" (plain summary 4), §A8, §G1 holds, §G6, G-actions 1, 2 and 6, the permission gates of §F steps 9 and 12; `plan/source-survey` §6 D4 to D6 and email appendices A and B; `plan/official-channels` §7 and §8; `plan/cardrush-source` §A parallel email and Q1 default; `plan/onchain-phase1` §B1 "written permission on file" for public pages. |
| 2026-10-17 | Repo stays public. The legal opinion is not a gate. | `plan/data-platform` G-actions 6, §G6 (second half), §H2 and §F step 9 gate wording; `plan/official-channels` §6 (SNKRDUNK hold); `plan/cardrush-source` §A external-delivery hold. RED still applies to new commitments: contracts, paying for data, publishing Terms and Privacy. |
| 2026-10-18 | Identity captures resumed; no storage cut built (captures are a one-off of about 300 MB against 2,825 MB free). Storage watch: flag the owner below 45 days to the 3 GiB reserve. | The 2026-10-17 capture pause; capture-day storage options A to G (D9 report, 2026-10-18); #172 (closed unmerged); the 90-day storage-fit rule in `plan/source-survey` §4, `plan/cardrush-source` §F3 and the session 14 handoff. |
| 2026-10-18 | Collector PRs are delivered only by the `staging-automerge` CI job, never hand-merged. | Hand merges of `hold-for-owner` PRs that change a collector (#171 left the shards on old code: [plans/coverage-gap-d9/F1-ROLLOUT.md](plans/coverage-gap-d9/F1-ROLLOUT.md)). |
| 2026-10-23 | The coordinator merges owner-approved queue PRs itself; `.github` changes stay `hold-for-owner` (owner merges by hand). | The owner hand-merging every queue PR ([AUTONOMY_POLICY.md](AUTONOMY_POLICY.md)). |
| 2026-10-24 | Domain `cardpirate.app` bought (Vercel Pro). Staging is `staging.cardpirate.app`, kept out of search engines; `cardpirate.app` is reserved for launch. | Item 18 "owner purchase". |
| 2026-10-26 | Yuyu-Tei after a challenge pause: one owner-approved probe, never a blind unpause (`yuyu-source-probe`). | Clearing a source pause by hand. |
| 2026-10-27 | SNKRDUNK parser-bug refusals return through `snkr-parser-requeue`: one canary, then the rest only after the canary captures a price. | Bulk unquarantine (still never done). |
| 2026-10-28 | Market Value plan A: each published day keeps the membership frozen with it; new prints count from the day they arrive; a release's chain restarts only when its own prints change (#235). | `docs/market_value.md` "one digest of today's catalogue" replay for forward publication. |
| 2026-10-28 | SNKRDUNK option A: log what the product page requests before changing the price wait again (#237). | Guessing the price request's address or timing. |
| 2026-10-30 | New sources: no new-source code until Yuyu-Tei and SNKRDUNK are healthy again; then the coordinator rebases and drives D0 (#185) and the Dorasuta rollout. | ROADMAP item 13 "N1 to N16 still open" (all answered 2026-10-19). |
| 2026-10-30 | Source health monitor: a daily report (lands about 10:00 MYT) and a 4-hourly change alert, both read-only Claude scheduled tasks, push only. | None (new). |
| 2026-10-30 | SNKRDUNK prices: best listed grade with its label, never the cheapest; grade A only until a spliced cutover lets the index count A only while B to D stay visible (DECISIONS.md). No grade-A listing is a confident no listing. | Cheapest-grade SNKRDUNK floor (`extract_raw_conditions` min over A to D). |

Earlier owner decisions that still stand are recorded in the plans themselves: collector v1 §I
(2026-10-11), onchain owner decisions (2026-10-09), data-platform G1 (2026-10-11, now partly
superseded above), production deprecation (2026-10-09 and 2026-10-12), and the F1 foil rule
(2026-10-17/18, `plan/new-sources` header item 1).

## 2. KPIs (read-only runs, 2026-10-28 15:07 to 15:20Z)

Population: **4,528** active verified JP prints (was 4,316 on 2026-10-18; about 212 added by the
2026-10-26 catalogue imports, incl. new coded release EB-05). Coverage target: 75% = 3,396.

| KPI | Value | Evidence |
|---|---|---|
| Fresh usable coverage (listed price within 24 h) | **78.8%** (3,569 of 4,528), all Yuyu-Tei. SNKRDUNK fresh: **0** (down since the 2026-10-26 page change, item 24). The 75% target is met by Yuyu-Tei alone. | MEASURED: `yuyu-coverage-gap` 40713172523, `snkrdunk-coverage-gap` 40713438280 |
| Dual-source coverage (fresh) | **0** while SNKRDUNK is down. SNKRDUNK has 353 mapped refresh items; 352 are quarantined, 1 (the requeue canary) is retrying. | MEASURED: `work-by-state` 40714288258 |
| Checks within 24 h | Yuyu-Tei: all 3,569 non-quarantined items (oldest 24.0 h); 162 due now at 15:19Z. SNKRDUNK: the 1 open item at 59.8 h, so the `freshness-deadline-deficit` blocker is back. | MEASURED: `freshness-not-met` 40713902705, `staging-state` 40712497491 |
| Quarantined refresh work | **355**: SNKRDUNK 352 (283 from the 2026-10-26 parser bug, 69 older), Yuyu-Tei 3 inactive. | MEASURED: `degraded-signals` 40713642431 |
| Source activity (24 h) | Yuyu-Tei refresh: 3,695 captured, 0 failures; 68 discovery runs. SNKRDUNK refresh: 4 attempts, all transient (`prices_not_loaded`). | MEASURED: `work-by-state` 40714288258 |
| Yuyu-Tei gap (959 prints) | b ambiguous/pending 483, code listed only in another category 327, capture intent pending 34, release never enumerated 61, all release listings mapped to siblings 54 (ESTIMATE). | MEASURED: `yuyu-coverage-gap` 40713172523 |
| SNKRDUNK gap (1,556 high-rarity targets) | release has no SNKRDUNK anchor 1,139; ambiguous proposals 228; quarantined 53; all code listings mapped to siblings 116. Last new candidate 2026-10-20. | MEASURED: `snkrdunk-coverage-gap` 40713438280 |
| Storage | Volume 4,308.8 MB; **2,469.9 MB** to the 3 GiB reserve. Planning 33.61 MB/day = **73 days**; last 24 h 30.25 MB = 82 days; worst 24 h 131.84 MB/day = 19 days. Database 3,410 MB, `raw_snapshots` 3,060 MB (90%). | MEASURED: `storage-rates` 40712789101, `table-sizes` 40714636747 |
| Official images | **212 of 4,528 prints have no mirrored copy** (the 2026-10-26 imports); last mirrored 2026-10-12; check unhealthy (item 26). | MEASURED: `official-images-status` 40712963235 |
| Market Value | Publication halted 2026-10-26 to 2026-10-28 (catalogue imports broke the replay); fixed by #235, migration `001d92ba8eb9` and the legacy freeze (2026-10-28). Last published day 2026-10-25 (64 days, 60 scopes); catch-up expected at the 2026-10-28 20:00Z run. | MEASURED: `db-diagnostic market-value-membership` 40672545623 |
| Health | Yuyu-Tei HEALTHY; SNKRDUNK **DEGRADED**; 1 raw-health action. Blockers: `freshness-deadline-deficit`, `snkrdunk-identity-quarantine`, `quarantined-refresh-work`. | MEASURED: `staging-state` 40712497491 |

Still NOT MEASURED: the exact union with both sources (SNKRDUNK adds 0 today), Market Value priced
coverage (item 11d).

## 3. Roadmap

| # | Item | Status | Class (next step) | Main blocker |
|---|---|---|---|---|
| 1 | RAW coverage to 75% | target met by Yuyu-Tei alone (78.8% fresh); second source down | AMBER | SNKRDUNK recovery (item 24); remaining Yuyu-Tei gap is identity |
| 2 | Freshness (24 h target, 23 h dispatch) | in progress (Yuyu-Tei met; SNKRDUNK deficit) | AMBER | 352 SNKRDUNK items quarantined (283 parser bug, item 24) |
| 3 | Continuous discovery | in progress (Yuyu-Tei running, SNKRDUNK stalled; last candidate 2026-10-20) | AMBER | SNKRDUNK discovery fix not approved |
| 4 | PSA10 (separate category, never in Index) | planned (OFF) | owner decision, then AMBER | owner switch-on; six build pieces missing |
| 5 | Card pages | done | GREEN | none |
| 6 | Collection | done | GREEN | owner's signed-in check of `/account` |
| 7 | Watchlist | done | GREEN | owner choice on 7D change |
| 8 | Market intelligence | in progress (Market Value frozen-membership fix delivered 2026-10-28; no plan for the next slice) | GREEN/AMBER | catch-up publish to confirm; no plan |
| 9 | Sharing | blocked | GREEN | Next.js 16.3 |
| 10 | AI/search discoverability | done (staging) | GREEN | domain and public launch for indexing |
| 11 | Admin/ops (exception-driven) | in progress | AMBER (data lane) | KPI gaps in runbook summaries |
| 12 | Production | planned | RED | explicit owner authorization; domain |
| 13 | Additional sources (Dorasuta, CardRush) | in progress (S1 migration `7a52e9b48e8a` applied; nothing collects) | owner decisions N1 to N16, then AMBER | plan approval (P0) |
| 14 | Data service (incl. §H first customer) | planned | AMBER (sandbox) | real values need PSA10 and production |
| 15 | Onchain Phase 1 (sessions 1 to 10, incl. Packs) | planned (plan only) | AMBER (session 1) | not scheduled |
| 16 | Partnerships (PCG, Collector Crypt) | planned | RED (external) | no PCG plan; CC outreach not sent |
| 17 | Production deprecation step 2 | done (2026-10-12) | none | none |
| 18 | Domain | done (`cardpirate.app`, 2026-10-24; staging on `staging.cardpirate.app`) | none | none |
| 19 | Security audit 2026-10-16 open items | in progress | AMBER (data lane) | F15 owner check; L1 still open (missed #224, #231 and #237) |
| 20 | Currency selector | planned (later) | RED (invariant amendment) | deferred |
| 21 | English-edition catalogue | planned (later) | AMBER | deferred |
| 22 | Per-PR mission files (stop manifest conflicts) | done (in use on every PR since 2026-10-19) | none | none |
| 24 | SNKRDUNK recovery after the 2026-10-26 page change | in progress | AMBER (collector release) | the page's price request is not seen (diagnostic #237 live) |
| 25 | Catalogue Phase 2 (official series import) | in progress (steps A to C, family batches, promo consensus) | AMBER (owner-approved imports) | remaining batches and step D |
| 26 | Official image mirror for new prints | blocked (212 prints unmirrored) | GREEN/AMBER | mirror run logs not read yet |
| 27 | RAW storage compression (sibling dictionaries) | on (`collector-sibling-on` applied 2026-10-25 08:23Z) | AMBER | none; measure its effect on the planning rate |

### 1. RAW coverage to 75%

- **Update 2026-10-28: target met by Yuyu-Tei alone.** Fresh 78.8% (3,569 of 4,528; target 3,396).
  F1 batches 1 to 3 applied (2026-10-19, 2026-10-20, 2026-10-24 13:14Z); the batch 3 refresh-backfill
  dry run failed on 2026-10-25 06:41Z, but every eligible Yuyu-Tei mapping (3,569) is fresh, so no
  backfill is outstanding. `enqueue-capture-batch` dry runs failed on 2026-10-19 and were not retried.
  The second source is down (item 24), so dual-source coverage is 0. Remaining Yuyu-Tei gap (959) is
  identity, not discovery (KPIs).
- **Status (2026-10-18): in progress.** Fresh 60.6%, operational 60.6% to 67.2% (KPIs). Target 3,237 of 4,316.
- **Source:** [PROJECT_HANDOVER.md](PROJECT_HANDOVER.md) §36, §39, §46; capacity75 handoffs (newest:
  [handoff/2026-10-16/capacity75-session14](handoff/2026-10-16/capacity75-session14/HANDOFF.md));
  D9 coverage gap ([plans/coverage-gap-d9](plans/coverage-gap-d9/F1-ROLLOUT.md), owned by the
  cardpirate-data project).
- **Done:** F1 unique-listing-kind rule merged (#171) and delivered to the nine yuyutei shards by #173
  (`2bcbe90`, rollout and CI passed 2026-10-18). Yuyu NEW100 captures done (see §5). Read-only
  coverage-gap diagnostics (#156, #166, #169, #174).
- **Next:** approve F1 proposals in owner-approved batches of about 500 with a 48 h storage check
  after each. ESTIMATE: Yuyu-Tei coverage 60.6% to about 78% if all are approved and refresh.
  No `ops-write` runbook for these approvals exists yet (`scripts/ops/run.py` lists only
  `enqueue-remaining-50`).
- **Also:** identity-capture batches (resumed 2026-10-18; no batch has run since 2026-10-16 23:17Z).
  The 217 prints in class `b_capture_intent:pending` are already captured (a finished capture parks
  as `pending`); they wait on evidence review, not on a new batch. `enqueue-remaining-50` only
  replays the finished NEW100 plan, so a new batch needs a new runbook. 176 prints are listed only in
  another Yuyu-Tei category.
- **Blocker:** the F1 approval runbook; owner approval per batch.
- **Owner decisions open:** approve each F1 batch and each capture batch (dry run first).
- **Superseded:** handover §36 priority 1 "resolve sustained storage headroom" before more write
  volume, and the 90-day fit rule, by the 2026-10-18 decision (captures resumed, 45-day watch).

### 2. Freshness

- **Update 2026-10-28:** Yuyu-Tei met (all 3,569 within 24 h). SNKRDUNK: 352 quarantined (283 from
  the 2026-10-26 parser bug, returning through `snkr-parser-requeue` once item 24 lands; 69 older,
  still per-item review), 1 open requeue canary at 59.8 h; `freshness-deadline-deficit` is back.
- **Status (2026-10-18): in progress.** Every non-quarantined refresh item was checked within 24 h; 97.9% within
  23 h. The `freshness-deadline-deficit` blocker of the 2026-10-06 snapshot is gone.
- **Source:** [DECISIONS.md](DECISIONS.md) 2026-10-04; handover §13 to §15, §37.
- **States (24 h):** listed (captured) Yuyu-Tei 2,763, SNKRDUNK 50; no_listing SNKRDUNK 236;
  failure 0 transient, 0 denials, 1 identity refusal; quarantined 70 (67 SNKRDUNK refresh, 3 Yuyu-Tei
  inactive); backoff 0.
- **Blocker:** the 67 SNKRDUNK quarantined items (identity refusals, mostly placeholder artwork).
  They need explicit per-item review; never bulk-unquarantine (handover §17).
- **Planned:** the high-interest tier (4 h target, 3 h dispatch; handover §13). Driving it from
  collections changes source budgets (collector-v1 §0: AMBER).
- **Owner decisions open:** none.

### 3. Continuous discovery

- **Metric:** variants with no exact source evidence. Yuyu-Tei: 1,700 prints without an eligible
  mapping, and every one has a Yuyu-Tei candidate for its code, so the Yuyu-Tei gap is identity, not
  discovery. SNKRDUNK: 1,085 of 1,451 high-rarity prints have no SNKRDUNK candidate.
- **Status: in progress.** Yuyu-Tei recurring discovery runs (67 runs in 24 h, last 2026-10-18
  14:41Z). SNKRDUNK published-sitemap discovery has not run since 2026-10-07.
- **Source:** handover §19, §33; SNKRDUNK coverage gap diagnostics (#174); `plan/new-sources` §4
  ("SNKRDUNK discovery fix (not approved)", 100 to 250 MB once, about 4 MB/day, ESTIMATE).
- **Blocker:** owner decision on the SNKRDUNK discovery fix and its order against CardRush (N14).
- **Class:** AMBER (substantial source-volume increase).

### 4. PSA10

- **Status: planned, OFF.** 0 PSA10 observations on staging (CARRIED FORWARD, data-platform §H1).
- **Rule:** separate category, never in the Market Index, Market Value or Card Pirate Index
  ([INVARIANTS.md](INVARIANTS.md), data-platform §D1, §C4).
- **Source:** `plan/data-platform` §H1 and §F step H-4; `plan/onchain-phase1` §D and session 5;
  handover §18, §40.
- **Built:** parser `extract_psa10` and the writer. **Missing:** planner wiring (a collector release),
  flag enforcement (`PSA10_ENABLED` is read by no app code), instrument `reference_type`, separate
  series and API field, verifiers, a UI category.
- **Blocker:** the owner's switch-on (CLAUDE.md: PSA10 OFF unless the owner asks).
- **Superseded:** the activation gate in data-platform G1 and H-4, by the 2026-10-16 and 2026-10-17
  decisions.
- **Class:** owner decision, then AMBER build with a SNKRDUNK collector release.

### 5. Card pages

- **Status: done.** Collector v1 S6 (#131, #132), design cleanup (#154, #163, #167).
- **Follow-up:** gold chips and tabs on `/cards` and Market, and small `/analytics` controls, are still
  on the old design (design cleanup handoff).

### 6. Collection

- **Status: done.** Accounts tables and `/me` API (S3, #112), value history (S4, #121), `/collection`
  (S7, #133), overview strip and grouped number input (#168). Owner click-through passed 2026-10-16.
- **Open:** the owner's signed-in check of `/account` on staging after #168 (agents cannot sign in).

### 7. Watchlist

- **Status: done.** S8 (#134, #135).
- **Owner decision open:** the 7D change is computed archive to archive, not from the live
  `market_index_change` as collector-v1 §E3 worded it. Keep, or switch (small API change).
- **Later:** price alerts and emails (v2; an email service is RED).

### 8. Market intelligence

- **Update 2026-10-28:** Market Value stopped publishing on 2026-10-26: the 2026-10-26 catalogue
  imports changed the one catalogue digest the nightly replay checked every published day against
  (`missing=64 mismatched=3840`). Fixed by plan A (#235): each day is replayed with its own frozen
  membership (`market_value_memberships`, migration `001d92ba8eb9` applied 2026-10-28 11:15Z, legacy
  membership frozen 11:37Z after its digest matched exactly). Rankings use each day's frozen basket.
  Expected: the 2026-10-28 20:00Z run publishes 2026-10-26 onward.
- **Status (2026-10-18): in progress.** Live: Market page, Card Pirate Index, receipt-gated Market Value, Sets on
  the Move. The legacy market workflow and intelligence pages were deleted in S1 (#110, collector-v1
  Q7).
- **Blocker:** no plan exists for the next slice. Methodology changes are RED.

### 9. Sharing

- **Status: blocked.** Share cards serve a static image (#153) while Next.js stays on 16.2.12, which
  closes the `next/og` advisory path. Generated cards come back after Next.js 16.3.6+ (retry plan in
  [security/2026-10-16-accounts-audit.md](security/2026-10-16-accounts-audit.md)).
- **Collection sharing:** private only (collector-v1 §B4); an opt-in share needs a privacy contract
  (RED: private data exposure).

### 10. AI/search discoverability

- **Status: done on staging** (handover §20, §29). Not re-checked live here: the staging hosts are
  out of reach from cloud sessions; the signed-out web smoke passed (39173905846).
- **Next:** indexing needs the domain and the public launch gate (collector-v1 §H).

### 11. Admin and ops, exception-driven

- **Status: in progress.** Runbooks (#139, #143, #150, #155, #157, #158), guardrails as code (#139),
  raw health with 0 actions, collector-token check (#130).
- **Gaps found while writing this file:**
  a. F1 approval runbook `approve-f1-batch` (ops-write, about 500 per owner-approved batch, dry run
     first): #176.
  b. #176 commits the #173 rollout receipt and makes `fleet-vs-receipt` compare each collector with
     the newest receipt that deployed it (default chain PR #103 then PR #173: snkrdunk on a504e47,
     the nine shards on 2bcbe90). Was: all nine shards mismatched against the PR #103 receipt (run
     39174128557).
  c. `scripts/ops/storage_events.json` still lacks the remaining-50 step (session 15 item).
  d. The `staging-state` summary carries no coverage, dual-source, zero-source or Market Value
     numbers; the full `CURRENT_STATE.yaml` is only in the artifact, which cloud sessions cannot
     download. The committed [CURRENT_STATE.yaml](CURRENT_STATE.yaml) dates from 2026-10-06.
- **Class:** AMBER, data lane; workflow changes carry `hold-for-owner`.

### 12. Production

- **Status: planned. RED.** No production exists (the old Railway production was deleted 2026-10-12).
- **Definition (owner):** an intentional environment with the same code lineage; healthy Postgres and
  Redis; new production secrets; auth callbacks; admin not public; tested backup and restore;
  production-safe collector capacity; monitoring; tested rollback; an isolated Vercel domain; explicit
  Railway production config; a migration and seed plan; explicit human authorization.
- **Prerequisites:** domain (item 18); public launch gate (collector-v1 §H: contact email and
  governing law filled, Privacy and Terms approved, draft banner and noindex removed, Google sign-in
  published); Vercel Pro before any revenue (RED).
- **Blocker:** explicit owner authorization for each step.

### 13. Additional sources

- **Update 2026-10-30:** all owner decisions N1 to N16 were answered on 2026-10-19 (`plan/new-sources`
  b3a75d8f, §7.1); none is open. N2 (CardRush acceptance) recorded in writing; N3 yes (admit a source
  only if days to reserve stay 60 or more); N14 superseded (SNKRDUNK first); N16 supplied, never
  committed, set by the owner as Railway variable `SOURCE_COLLECTOR_CONTACT` before D1.
- **Built:** S0 (#178), S1 (#181, migration `7a52e9b48e8a` applied 2026-10-28), S2 (#182), S3 (#183),
  S4 (#184), all merged 2026-10-19/20 and inert. **D0** (#185, collector kit and Dorasuta collector, no
  rollout) is a draft stacked on the old S3 branch, untouched since 2026-10-20; it needs a rebase onto
  `staging`. The coordinator drives it (owner 2026-10-30).
- **Order (owner 2026-10-30, perfectionist):** no new-source code until Yuyu-Tei and SNKRDUNK are both
  healthy again (Yuyu-Tei source pause since 2026-10-29 07:36Z; SNKRDUNK price fix, item 24). Then D0
  rebase, then D1 (Dorasuta collector rollout only, after the N3 storage re-check and the owner's Railway
  service and contact variable), then D2 to D4 per plan; then buyback (B0, B1), then CardRush (C0 to C4).
- **Rules:** honest bot name with a contact address, robots.txt read every run, one request at a time,
  no images, full stop on any 403, 429, challenge or notice (§2.4). No Yuyu-Tei or SNKRDUNK redeploy
  (§2.7). The three rollout PRs (D1, B1, C2) merge only through `staging-automerge`.
- **ESTIMATE:** coverage about 91% with Dorasuta, about 96% with CardRush; storage about 68 days to the
  reserve with both (§4, §6), to be re-measured at D1 and C0.
- **Superseded:** `plan/cardrush-source` (by `plan/new-sources`, 2026-10-16); `plan/source-survey` §5
  order, §6 D4 to D6 and its email drafts; the "no third source" rule.
- **Class:** AMBER per new source; each cutover (SOURCE_SEMANTICS bump, D4 and C4) is RED.

### 14. Data service

- **Status: planned.** `plan/data-platform` (2026-10-09, amended 2026-10-11). Nothing built (no
  `services/data_api`).
- **§H first customer:** synthetic sandbox now (step H-2: partner API scaffold with made-up sample data,
  shareable); real values only after PSA10 (item 4) and production (item 12). Also H-1: reply to the
  requesting website with the §H5 questions (the owner sends it).
- **Superseded:** the permission-first and outreach holds (plain summary 4, §A8, §G1, §G6, G-actions
  1, 2, 6) and the legal-opinion gates (step 9, §H2), by the 2026-10-16 and 2026-10-17 decisions.
  G-actions 3 to 5 (Cardmarket, Aucfan, eBay emails) and H-Q3 are superseded by outreach closed.
- **Owner decisions open:** G2a (native-currency amendment), G4 (v1 scope), G5 (pricing), G9 (first
  design partner), H-Q1, H-Q2.
- **Class:** H-2 is AMBER (additive tables in a module no collector imports); external delivery is
  RED.

### 15. Onchain Phase 1

- **Status: planned (plan only, 2026-10-09).** Sessions 1 to 10 in `plan/onchain-phase1` §E; none
  built (no `publication_anchors`, `launch_items` or Packs code).
- **Next:** session 1, Merkle builder, proof endpoint, OpenTimestamps stamping on staging
  (AMBER, one additive table). New tables must live outside `app/models/__init__.py`, which every
  collector imports, or they trigger a collector release (`plan/new-sources` header item 6).
- **Owner decisions open:** the 11 defaults in the plan's owner list (first partner Collector Crypt,
  pack fee, treasury address, Base key, X API no, genesis policy, and others).
- **Superseded:** §B1 "written permission on file" for public-page sources (2026-10-16). Partner APIs
  (Collector Crypt wallet API for Packs) still need the partner's key and terms; that is item 16.
- **Class:** sessions 1 to 7 and 9 AMBER; session 2's contract, 8 (mainnet) and 10 (real money) RED.

### 16. Partnerships (PCG, Collector Crypt)

- **Status: planned.** Collector Crypt is the default first partner for Packs (onchain §F, F-1) and the
  data service (data-platform G9); the outreach email is drafted in the plan and not sent. **PCG is
  not in any plan branch** (all nine `plan/*` branches read 2026-10-18).
- **Blocker:** the owner sends any partner message; a short PCG brief is needed first.
- **Class:** RED (external party).

### 17. Production deprecation step 2

- **Status: done.** Proxies removed and the Railway production environment deleted 2026-10-12
  09:50:07Z by the owner, verified (plans/production-deprecation/INVENTORY.md §8; #107, #108). The
  `staging_db_read_check.py` note landed. Staging `ADMIN_TOKEN` rotation was folded into collector-v1
  S5 (INVENTORY §8); not re-verified here.

### 18. Domain

- **Update 2026-10-28: done.** `cardpirate.app` bought 2026-10-24 (Vercel Pro); staging serves
  `staging.cardpirate.app`, kept out of search engines; `cardpirate.app` waits for launch.
- **Status (2026-10-18): planned (owner).** Collector-v1 Q1 (2026-10-11): yes, name to be decided. No domain is
  recorded as bought. It gates Google sign-in publishing, the public launch, production and the R2
  image domain.
- **Class:** RED (paid).

### 19. Security audit 2026-10-16 open items

- **Update 2026-10-28:** L1 (`hide_parameters=True` in `app/db.py`) is still open: it missed the
  collector releases #224, #231 and #237. Attach it to the next one. Other open items unchanged (not
  re-verified).
- **Status (2026-10-18): in progress.** Fixed and live: A1 to A3, F1, D2, D3, F5, F8, F9, F11, F12, F13 and F14 web
  parts, CSP enforced (#136 to #165, #170).
- **Open:** F15 `CORS_ALLOW_ORIGIN_REGEX` on Railway (owner checking); F13 and F14 API parts, F2, F3,
  F4, F10, S1, I1 (data lane); F6, F7 (migrations on protected tables); D4 (npm); L1
  `hide_parameters` (needs a collector release: it missed #173 and now waits for the next one);
  D1 remainder (Next.js 16.3, parked).
- **Source:** [security/2026-10-16-accounts-audit.md](security/2026-10-16-accounts-audit.md).

### 20. Currency selector (later)

- **Status: planned, later.** `plan/data-platform` §D2: native-currency invariant amendment,
  `regional_price_observations`, ECB `fx_rates`, conversion at read time. Owner decision G2a (RED:
  invariant amendment).

### 21. English-edition catalogue (later)

- **Status: planned, later.** `plan/data-platform` §C2 and step 13 (DP-8): about 4,500 to 5,500 prints,
  separate prints and denominator, no cross-language mapping. Default G2b: defer until an English price
  source is in sight.

### 22. Per-PR mission files (stop manifest conflicts)

- **Update 2026-10-28: done.** Every PR since 2026-10-19 carries `docs/agent/missions/<branch>.json`;
  the fleet lives in `STAGING_FLEET.json`. One gap remains: GitHub refuses to arm native auto-merge
  on a PR that is already clean, so a PR whose delivery job waits behind another delivery fails at
  "Refuse missing safeguards" (#224, #233). Workaround: draft, then ready. Fix: a small `ci.yml`
  change (owner decision).
- **Status (2026-10-19): in progress.** Owner GO 2026-10-19 09:24Z: build now, deliver last (after #180, #179,
  #178, #181 and #182 merge or close), draft with hold-for-owner. The first collector PR on the new
  layout is the live test: staging-automerge in an allowed collector window, with "Deploy
  mission-scoped staging collectors" and the delivery verification passing. Built as planned below,
  plus one rule the plan missed: after a collector delivery, the next merge pins the fleet's
  component SHAs ([STAGING_DELIVERY.md](STAGING_DELIVERY.md#per-pr-mission-files-2026-10-19)).
- **Problem.** Every DATA-lane PR edits the one shared `docs/agent/STAGING_MISSION.json`. After each
  merge the next PR has a text conflict on it, and even without one its `diff_sha256` goes stale: the
  hash covers a two-dot diff against the moving `staging` tip, so any merge to `staging` changes it.
  Each PR then needs a thread to merge `staging`, regenerate the hash and wait for CI, so delivery is
  serialized behind thread availability. A third cause: the hash covers git's abbreviated index
  lines, so a long-lived checkout and CI's fresh clone can disagree.
- **Plan (smallest safe change, one PR):**
  1. Split the file in two. Per-PR mission `docs/agent/missions/<branch>.json` holds what describes
     one change: mission, classification, red decisions, impacts, safeguards, `diff_sha256`, and the
     deploy request (`collector_services`, `raw_dependency_migration`). Fleet state
     `docs/agent/STAGING_FLEET.json` holds what carries forward: `deployment_verification`
     (components, revision, checks) and `operational_notes`. Only PRs that move the fleet (collector
     or migration PRs, already one at a time through staging-automerge) edit it.
  2. `staging_policy.change_evidence` hashes the PR's own change set: `git diff --binary --full-index
     $(git merge-base base head) head`, excluding only that PR's mission file. Merging `staging` into a
     PR no longer changes the hash unless the merge itself edits the PR's files, and full index lines
     remove the clone-size dependence.
  3. policy-gate keeps running the base copy of the evaluator, unchanged in strictness: DATA lane needs
     exactly one added mission file, no other file under `docs/agent/missions/` may change, impacts
     must cover every changed file exactly once (the fleet file included), same RED, AMBER and
     classification rules. `product_lane.py` treats `docs/agent/missions/**` and the fleet file as
     DATA, as the manifest is today. The hook and lane checks are untouched.
  4. Delivery (`ci.yml` staging-automerge, `staging-delivery.yml`) finds the one mission file the
     merge added, builds the old manifest shape in a temp file (fleet state plus that mission) and
     passes it with `--manifest`. The "full delivery with an unchanged manifest" refusal becomes "full
     delivery without exactly one added mission file". Fails closed.
  5. Verifiers (`staging-verify.yml`, `verify_yuyu_raw_reader_component.py`,
     `verify_snkr_published_discovery_component.py`) read the fleet file.
  6. Tests: `test_staging_policy`, `test_staging_delivery_scope`, `test_product_lane`,
     `test_claude_guardrails`, `test_collector_runtime_inputs`, plus cases for zero, two and edited
     mission files. Docs: CLAUDE.md, AUTONOMY_POLICY.md, OPS_RUNBOOKS.md.
- **Bootstrap.** policy-gate runs the base copy, so the switch PR itself carries one last old-style
  `STAGING_MISSION.json`; the next PR is the first on the new layout. Mission files are small and
  stay as history.
- **What it does not change.** Staging must still be up to date before a PR is marked ready, and CI
  re-runs on the updated head. Updating is then a conflict-free merge (`update_pull_request_branch`)
  with no hash regeneration, so the coordinator or any thread can do it.
- **Effort:** M. One DATA-lane PR, about 300 to 500 lines with tests, plus a short docs follow-up if
  split. **Risk:** AMBER. It changes the gate and the delivery path for collector rollouts. Mitigations:
  every new branch fails closed, the evaluator rules are unchanged, the first delivery after it is a
  docs PR (scope skip) before any collector PR, recovery is a native revert. Needs hold-for-owner
  (touches `.github/`) and an `Independent security review:` line, since it is policy tooling.
- **Blocker:** the delivery queue ahead of it.

### 23. Rollout receipts readable by sessions

- **Status: planned, plan only** (owner request 2026-10-18 23:43Z: plan, don't build).
- **Problem.** A collector rollout receipt exists only in the `staging-delivery-<sha>` CI artifact,
  which cloud sessions cannot download, so the #173 fleet check needed the owner to download and
  upload it by hand.
- **Plan:** [plans/rollout-receipt-publish/PLAN.md](plans/rollout-receipt-publish/PLAN.md). The
  delivery job prints the receipt as `rollout-receipt` annotations (readable over REST), and
  `fleet-vs-receipt` fetches receipts from recent delivery artifacts inside Actions. No commit to
  `staging` from the job (needs a branch-rule bypass and starts a CI run per rollout).
- **Effort:** S, about 150 lines (ESTIMATE). Class AMBER, `hold-for-owner` (touches `.github/`).
- **Blocker:** owner go. Not started.

### 24. SNKRDUNK recovery after the 2026-10-26 page change

- **Status: in progress.** SNKRDUNK changed its product page on 2026-10-26 ~08:29Z (CSS-module class
  names, fixed by #223/#224; photo by reference and prices after load, #231) and again around
  2026-10-29: the page now carries its size-chips response in a React Query stream script and makes no
  price request, so every capture failed `prices_not_loaded` (#237 trace and a live check of
  /apparels/93511 and /apparels/142630, 2026-10-30).
- **Fix (collector release, SNKRDUNK only):** read the embedded size-chips for the page's own product,
  require every rendered chip to agree with it, keep the network wait as a fallback; raw price is grade A
  only (owner 2026-10-30); no grade-A listing is a confident no listing; readable Railway log lines.
- **Then:** canary requeue of a listed card, `snkr-parser-requeue` rest (283), fleet pin.
- **Later:** the full grade rule (B to D with labels, index A only) at a spliced SOURCE_SEMANTICS step,
  built with Dorasuta's cutover (CPI, Market Value, collection valuation, charts and splice creation
  still need splice wiring).
- **Owner decision open:** audit the no-listing facts recorded between 2026-10-26 ~08:29Z and the fix.

### 25. Catalogue Phase 2 (official series import)

- **Status: in progress.** `catalogue-import` runbook (#217), step C rules and family batches
  (#219), promo consensus (#221). Applied on 2026-10-26: EB-05, family deck set, flagship battle,
  standard battle and its promos (about 212 prints).
- **Next:** remaining batches (promotion packs, premium card collections, magazines, events and
  prizes, other limited), then step D (Asia Mini-tin, TC-01/02, DON!!).
- **Side effect learned:** an import changes the Market Value membership. Since #235 that starts the
  affected release's segment and no longer breaks publication.

### 26. Official image mirror for new prints

- **Status: blocked.** 212 prints (the 2026-10-26 imports) have no mirrored official image; the
  check has been unhealthy since then and nothing has been mirrored since 2026-10-12.
- **Found 2026-10-31:** every pending print fetched from Bandai, then failed at R2 with a bare
  `ClientError`; each run cost one Bandai request per pending print, and the multi-line summary hit
  Railway's 500 logs/s cap, hiding the end. Reads from the bucket still work (site images load).
- **Fix (owner, perfectionist):** R2 preflight before any Bandai request, stop at the first R2 error,
  reasons name operation, code and HTTP status, one bounded summary line. Then the owner checks the
  R2 token the mirror uses (expiry, Object Read & Write on the assets bucket) against the logged code.

### 27. RAW storage compression (sibling dictionaries)

- **Status: on.** `RAW_DICTIONARY_SIBLING` behind `collector-sibling-on/off` (commit `a773762`, 2026-10-25),
  applied 2026-10-25 08:23Z. Planning rate 33.61 MB/day (2026-10-28) against 33.24 (2026-10-18), with
  more prints and more Yuyu-Tei refreshes; its own saving is NOT MEASURED.

## 4. Done and not to repeat

Collector v1 S1 to S8 (#110 to #135); the 2026-10-16 security pass and follow-ups (#136 to #170);
ops runbooks and guardrails (#139 to #158); design cleanup a to c (#154, #163, #167); profile strip
(#168); D9 diagnostics and F1 (#156, #166, #169, #171, #173, #174); official images on R2 (#101);
production deletion (#107, #108). Never-replay list: session 14 handoff "Session 15 must verify" 6.

## 5. Yuyu NEW100

- **Captures: done.** NEW50 (work ids 3678 to 3727, 2026-10-13) and remaining 50 (3728 to 3777, applied
  2026-10-16 in run 38977099606): all 100 have one completed attempt, 0 denials, 0 transient failures
  (`identity-capture-work` 39174417652). Never replay either list.
- **Identity:** no auto-approval; their proposals go through the resolver (now with F1) and the
  approval batches in item 1.
- **After NEW100:** 615 capture work items exist in total (2766 to 3777), all attempted; 3 blocked
  (3018 to 3020). The 217 prints in class `b_capture_intent:pending` are already captured and wait on
  evidence review. Batches resumed by owner decision 2026-10-18; none has run since 2026-10-16 23:17Z,
  and the next one needs a runbook that plans uncaptured listings (`enqueue-remaining-50` only replays
  NEW100).

## 6. Next 10 (highest value, 2026-10-28)

1. SNKRDUNK price fix from the #237 evidence, canary, then requeue the 283 (item 24). Restores the
   second source.
2. ~~Confirm the Market Value catch-up publish and rankings after the 2026-10-28 20:00Z run
   (item 8).~~ Done 2026-10-29: 2026-10-26..28 published under the frozen v2 membership
   (market-value-membership 40762476093); 7D view live.
3. Audit the possibly false SNKRDUNK no-listing facts recorded since 2026-10-26 (item 24, owner).
4. Official image mirror for the 212 new prints (item 26).
5. Catalogue Phase 2 remaining batches, then step D (item 25).
6. Yuyu-Tei identity backlog: 483 ambiguous, 327 listed only in another category (item 1).
   2026-10-29: #239 binds reviews to listing identity, not price, and adds Claude as a reviewer;
   14 captures await review (handoff/2026-10-29/coordinator-handoff.md).
7. SNKRDUNK discovery fix decision (item 3) and the 69 older quarantined items, one by one (item 2).
8. Owner decisions on `plan/new-sources` N1 to N16, then Dorasuta (item 13).
9. Ops readability: KPI fields in the staging-state summary, `fleet-vs-receipt` against the newest
   receipts, the auto-merge-on-clean-PR fix (items 11, 22, 23).
10. Security data-lane batch, L1 with the next collector release (item 19); then the launch gate
    toward production (item 12).

## 7. Sources read for this revision

2026-10-28 revision: `ops-readonly` runs 40712497491 (staging-state), 40712789101 (storage-rates),
40712963235 (official-images-status), 40713172523 (yuyu-coverage-gap), 40713438280
(snkrdunk-coverage-gap), 40713642431 (degraded-signals), 40713902705 (freshness-not-met),
40714288258 (work-by-state), 40714636747 (table-sizes), 40672545623 (market-value-membership);
`ops-write` run history (F1, sibling, catalogue-import, apply-migration, market-value-freeze-legacy,
snkr-parser-requeue); merged PRs #175 to #237.

2026-10-18 revision: `plan/collector-v1` (d5b292f), `plan/data-platform` (f7e8ecd), `plan/new-sources` (7cf782d),
`plan/cardrush-source` (96e7d19), `plan/source-survey` (f3061f9), `plan/official-channels` (fae9375),
`plan/onchain-phase1` (c2279e4), `plan/production-deprecation` (9b4857c),
`plan/profile-overview-number-input` (2fad635); [STAGING_MISSION.json](STAGING_MISSION.json) at
`99844c6`; [PROJECT_HANDOVER.md](PROJECT_HANDOVER.md); [AUTONOMY_POLICY.md](AUTONOMY_POLICY.md);
[DECISIONS.md](DECISIONS.md); handoff
[2026-10-16/capacity75-session14](handoff/2026-10-16/capacity75-session14/HANDOFF.md); merged PRs
#65 to #174; `ops-readonly` runs 39173902607 to 39174564306.
