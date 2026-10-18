# Card Pirate roadmap (single source of truth)

As of 2026-10-18 23:00Z, staging `99844c6` (after #174). Staging only; production RED; PSA10 OFF.

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

Earlier owner decisions that still stand are recorded in the plans themselves: collector v1 §I
(2026-10-11), onchain owner decisions (2026-10-09), data-platform G1 (2026-10-11, now partly
superseded above), production deprecation (2026-10-09 and 2026-10-12), and the F1 foil rule
(2026-10-17/18, `plan/new-sources` header item 1).

## 2. KPIs (read-only runs, 2026-10-18 22:49 to 23:00Z)

Population: 4,316 active verified JP prints (`yuyu-coverage-gap`). Coverage target: 3,237 (75%).

| KPI | Value | Evidence |
|---|---|---|
| Operational coverage (a source checked the print within 24 h) | **60.6% to 67.2%** (2,616 to 2,902 prints). Yuyu-Tei alone is 2,616; SNKRDUNK adds at most 286. The exact union is NOT MEASURED. | MEASURED: `degraded-signals` 39174056368, `freshness-not-met` 39173908861 |
| Fresh usable coverage (listed price within 24 h) | **60.6% to 61.8%** (2,616 to 2,666). Yuyu-Tei 2,616; SNKRDUNK 50 (28 high-rarity + 22 other). | MEASURED: `yuyu-coverage-gap` 39174286814, `snkrdunk-coverage-gap` 39174353160 |
| Dual-source coverage (fresh) | **At most 50 prints (1.2%)**: only 50 prints have a fresh SNKRDUNK price. Exact count NOT MEASURED. Mapped dual-source was 334 on 2026-10-15 (CARRIED FORWARD, `plan/new-sources` §6). | as above |
| Checks within 23 h | **97.9%** of non-quarantined refresh items (2,840 of 2,902); 62 Yuyu-Tei items were past the 23 h dispatch point and not yet claimed. | MEASURED: `work-by-state` 39174132869 (`due_now`) |
| Checks within 24 h | **100%** of non-quarantined items (2,902 of 2,902; oldest Yuyu-Tei 23.3 h, SNKRDUNK 18.8 h). 97.7% of all 2,969 eligible items. The `freshness-deadline-deficit` blocker is gone. | MEASURED: `freshness-not-met` 39173908861, `staging-state` 39173902607 |
| Mappings older than 24 h | **67**, all SNKRDUNK and all quarantined by identity refusal (22 never checked, 45 last success over 24 h; oldest blocked since 2026-10-02). Plus 3 inactive Yuyu-Tei items. | MEASURED: `degraded-signals` 39174056368 |
| Zero-source prints (no fresh price) | **1,650 to 1,700 (38.2% to 39.4%)**. Zero mapped sources: NOT MEASURED. | derived from the two coverage-gap runs |
| Exact candidate backlog | Yuyu-Tei F1: **about 762** exact proposals accepted, waiting for owner-approved batches of about 500 (CARRIED FORWARD, `STAGING_MISSION.json` notes; F1 sizing 775 strict). SNKRDUNK: **82** exact candidates whose listing is not mapped. | `snkrdunk-coverage-gap-discovery` 39174490534 |
| Ambiguous backlog | Yuyu-Tei: **1,324** ambiguous candidates (1,293 prints); 830 more candidates whose release or card code does not resolve. SNKRDUNK: **218** ambiguous candidates (201 prints). | `yuyu-coverage-gap` 39174286814, SNKRDUNK runs above |
| Discovery yield | Yuyu-Tei: 67 discovery runs in 24 h, all completed; every gap print already has a Yuyu-Tei candidate for its code (class a = 0). SNKRDUNK: **2 new candidates in 14 days, last discovery attempt 2026-10-07**; 1,085 of 1,451 high-rarity prints have no SNKRDUNK candidate. | `work-by-state` 39174132869, `snkrdunk-coverage-gap-discovery` 39174490534 |
| Source failure rates (24 h) | Yuyu-Tei refresh: 2,763 captured, **0 failures**. SNKRDUNK refresh: 287 attempts, 50 captured, 236 no listing, 1 identity refusal, **0 denials or transient failures**. | `work-by-state` 39174132869 |
| Storage | Volume 3,980.4 MB; **2,798.3 MB** to the 3 GiB reserve. Planning 33.24 MB/day = **84 days**; last 24 h 26.81 MB = 104 days; worst 24 h 131.84 MB/day = 21 days. Database 3,112 MB, `raw_snapshots` 2,848 MB (92%). | MEASURED: `storage-rates` 39173904392, `table-sizes` 39174211637 |
| Market Value coverage | **NOT MEASURED.** Market Index snapshots write 2,626 rows a day (flat since 2026-10-11, 60.8% of prints), but no runbook reads the priced count or the receipt's expected count. | `capture-day-storage` 39174564306 |
| Health | Yuyu-Tei and SNKRDUNK HEALTHY, 0 raw-health actions. Blockers: `snkrdunk-identity-quarantine`, `quarantined-refresh-work` (70). Signed-out web smoke passed. Official images 4,316 of 4,316 mirrored. | `staging-state` 39173902607, `web-smoke` 39173905846, `official-images-status` 39173907292 |

To make the NOT MEASURED rows measurable: add the state generator's coverage block (mapped, one or
more sources, both sources, zero sources) and the latest Market Value receipt counts to the
`staging-state` ops summary, or add a `coverage-kpis` diagnostic (item 11d).

## 3. Roadmap

| # | Item | Status | Class (next step) | Main blocker |
|---|---|---|---|---|
| 1 | RAW coverage to 75% | in progress (60.6% fresh) | AMBER | F1 approval runbook not built; owner approves each batch |
| 2 | Freshness (24 h target, 23 h dispatch) | in progress (met outside quarantine) | AMBER | 67 SNKRDUNK items in identity quarantine |
| 3 | Continuous discovery | in progress (Yuyu-Tei running, SNKRDUNK stalled) | AMBER | SNKRDUNK discovery fix not approved |
| 4 | PSA10 (separate category, never in Index) | planned (OFF) | owner decision, then AMBER | owner switch-on; six build pieces missing |
| 5 | Card pages | done | GREEN | none |
| 6 | Collection | done | GREEN | owner's signed-in check of `/account` |
| 7 | Watchlist | done | GREEN | owner choice on 7D change |
| 8 | Market intelligence | in progress (no plan for the next slice) | GREEN/AMBER | no plan |
| 9 | Sharing | blocked | GREEN | Next.js 16.3 |
| 10 | AI/search discoverability | done (staging) | GREEN | domain and public launch for indexing |
| 11 | Admin/ops (exception-driven) | in progress | AMBER (data lane) | KPI gaps in runbook summaries |
| 12 | Production | planned | RED | explicit owner authorization; domain |
| 13 | Additional sources (Dorasuta, CardRush) | planned (plan rev 2, nothing built) | owner decisions N1 to N16, then AMBER | plan approval (P0) |
| 14 | Data service (incl. §H first customer) | planned | AMBER (sandbox) | real values need PSA10 and production |
| 15 | Onchain Phase 1 (sessions 1 to 10, incl. Packs) | planned (plan only) | AMBER (session 1) | not scheduled |
| 16 | Partnerships (PCG, Collector Crypt) | planned | RED (external) | no PCG plan; CC outreach not sent |
| 17 | Production deprecation step 2 | done (2026-10-12) | none | none |
| 18 | Domain | planned (owner) | RED (paid) | owner purchase |
| 19 | Security audit 2026-10-16 open items | in progress | AMBER (data lane) | F15 owner check; L1 needs a collector release |
| 20 | Currency selector | planned (later) | RED (invariant amendment) | deferred |
| 21 | English-edition catalogue | planned (later) | AMBER | deferred |

### 1. RAW coverage to 75%

- **Status: in progress.** Fresh 60.6%, operational 60.6% to 67.2% (KPIs). Target 3,237 of 4,316.
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
- **Also:** identity-capture batches (resumed 2026-10-18; no batch has run since 2026-10-16 23:17Z;
  217 prints wait on a pending capture intent, 6 on a blocked one); 176 prints listed only in
  another Yuyu-Tei category.
- **Blocker:** the F1 approval runbook; owner approval per batch.
- **Owner decisions open:** approve each F1 batch and each capture batch (dry run first).
- **Superseded:** handover §36 priority 1 "resolve sustained storage headroom" before more write
  volume, and the 90-day fit rule, by the 2026-10-18 decision (captures resumed, 45-day watch).

### 2. Freshness

- **Status: in progress.** Every non-quarantined refresh item was checked within 24 h; 97.9% within
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

- **Status: in progress.** Live: Market page, Card Pirate Index, receipt-gated Market Value, Sets on
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
  a. No `ops-write` runbook to approve F1 proposal batches (item 1).
  b. `fleet-vs-receipt` still defaults to the PR #103 receipt, so it reports all nine yuyutei shards as
     mismatched after #173 (run 39174128557, `records_after_receipt` 9). Commit the #173 rollout
     receipt as the new baseline.
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

- **Status: planned.** `plan/new-sources` revision 2 (2026-10-18, owned by the cardpirate-data
  project): foundations S0 to S4, then Dorasuta asks (D0 to D4), Dorasuta buyback (B0, B1), then
  CardRush (C0 to C4). Nothing built.
- **Rules:** honest bot name with a contact address, robots.txt read every run, one request at a time,
  no images, full stop on any 403, 429, challenge or notice (§2.4). No Yuyu-Tei or SNKRDUNK redeploy
  (§2.7). The three rollout PRs (D1, B1, C2) merge only through `staging-automerge`.
- **ESTIMATE:** coverage about 91% with Dorasuta, about 96% with CardRush; storage about 68 days to the
  reserve with both (§4, §6).
- **Owner decisions open:** N1 to N16 (§7), in particular N1 plan approval, N8 allowing
  `buy.dorasuta.jp` in the cloud environment, N16 a contact address, N14 order against the SNKRDUNK
  discovery fix. N2 (CardRush acceptance) is covered by the 2026-10-16 and 2026-10-17 decisions; a
  one-line owner confirmation closes it.
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

- **Status: planned (owner).** Collector-v1 Q1 (2026-10-11): yes, name to be decided. No domain is
  recorded as bought. It gates Google sign-in publishing, the public launch, production and the R2
  image domain.
- **Class:** RED (paid).

### 19. Security audit 2026-10-16 open items

- **Status: in progress.** Fixed and live: A1 to A3, F1, D2, D3, F5, F8, F9, F11, F12, F13 and F14 web
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
- **After NEW100:** 615 capture work items exist in total (2766 to 3777, plus 3 blocked); 217 prints
  still wait on a pending capture intent. Batches resumed by owner decision 2026-10-18, but none has
  run since 2026-10-16 23:17Z.

## 6. Next 10 (highest value)

1. F1 approval runbook and the first batch of about 500 (item 1). Biggest coverage step.
2. Next identity-capture batch, dry run first (items 1 and 5).
3. Owner decisions on `plan/new-sources` N1 to N16, then build the foundations and Dorasuta asks
   (item 13).
4. SNKRDUNK discovery fix decision and build (item 3).
5. Review the 67 quarantined SNKRDUNK items one by one (item 2).
6. Ops readability PR: KPI fields in the staging-state summary, the #173 rollout receipt, the
   remaining-50 storage step (item 11).
7. Security data-lane batch (F2, F3, F4, F10, F13/F14 API) plus F15 owner check; L1 with the next
   collector release (item 19).
8. Next.js 16.3 retry by the written plan, then restore share cards (items 9 and 19).
9. Data service sandbox H-2 and the owner's reply to the requesting website (item 14).
10. Domain and the public launch gate, the path to production (items 18 and 12).

## 7. Sources read for this revision

`plan/collector-v1` (d5b292f), `plan/data-platform` (f7e8ecd), `plan/new-sources` (7cf782d),
`plan/cardrush-source` (96e7d19), `plan/source-survey` (f3061f9), `plan/official-channels` (fae9375),
`plan/onchain-phase1` (c2279e4), `plan/production-deprecation` (9b4857c),
`plan/profile-overview-number-input` (2fad635); [STAGING_MISSION.json](STAGING_MISSION.json) at
`99844c6`; [PROJECT_HANDOVER.md](PROJECT_HANDOVER.md); [AUTONOMY_POLICY.md](AUTONOMY_POLICY.md);
[DECISIONS.md](DECISIONS.md); handoff
[2026-10-16/capacity75-session14](handoff/2026-10-16/capacity75-session14/HANDOFF.md); merged PRs
#65 to #174; `ops-readonly` runs 39173902607 to 39174564306.
