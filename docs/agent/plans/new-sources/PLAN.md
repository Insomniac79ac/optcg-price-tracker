# New price sources: combined plan (PLAN ONLY)

Status: **PLAN ONLY**, awaiting owner approval before any build. Written 2026-10-16 on base
`origin/staging` 4cb52c3, branch `plan/new-sources`. STAGING ONLY. Production RED. PSA10 OFF.
No code, migration, collector, setting, staging write, source job or PR.

**Supersedes** `plan/cardrush-source` (kept as history at `1c6a511`; its PLAN.md is marked
superseded). The S1–S3 CardRush build was **not started**.

**Inputs:**
- `origin/plan/cardrush-source:docs/agent/plans/cardrush-source/PLAN.md` @ `1c6a511`, which carries the
  MEASURED CardRush audit (74 requests, 2026-10-16);
- `origin/plan/source-survey:docs/agent/plans/source-survey/SURVEY.md` @ `f3061f9` (rev 3, latest at writing). It
  carries the MEASURED Dorasuta, magi, Aucfan and Suruga-ya probes, the Dorasuta buyback follow-up (SV §2.6:
  host still refused by network policy at 15:13Z, 0 requests reached it), and the Aucfan (SV Appendix A) and
  magi (SV Appendix B) email drafts. These are referenced, not copied;
- the owner's answers of 2026-10-16:
  - Q1: plan default;
  - Q2–Q5 and Q7–Q13: accepted;
  - **Q6: splice, not break.**

Labels: **MEASURED** (source given), **CARRIED FORWARD** (from a committed plan), **ESTIMATE**,
**UNVERIFIED**. Section references like "CR §1.4" point to the CardRush plan, and "SV §2.1" to the survey.

---

## Plain summary (for the owner)

1. **Dorasuta's shop prices go live first.**
   - Its site is open to polite reading, and its terms have no scraping clause.
   - Its prices move independently enough from Yuyu-Tei to matter: a median 25% apart (MEASURED, 18 cards).
   - About 1 MB/day of storage (ESTIMATE).
2. **CardRush comes second, once your permission email gets an answer** (or you accept the risk in writing).
   It is the larger source, at about 14,820 listings including PSA10.
3. **Shared parts are built once and used by every new source.** They cover the grade field, product records,
   the card matcher, the collector frame, the guard that keeps hidden prices off public pages, and the
   **splice** that adds a source to Market Value and the Index without breaking their history.
4. **Storage.** Everything except CardRush fits with room to spare, remaining-50 batch included.
   - Stress B margin is about +234 MB (ESTIMATE).
   - **CardRush at a daily refresh does not fit on top** (−99 MB at stress B). At an every-48-hours refresh it
     fits thinly (+40 MB). We decide with measured numbers when CardRush is unblocked.
5. **Aucfan and magi are placeholders** until they reply to the licence and consent enquiries. Suruga-ya is parked
   and Fullahead is skipped.
6. **Decisions you need to make:** the 14 open questions in §6, each with a default. The CardRush email draft is
   the appendix, ready for you to send.

---

## 1. Sources and status

| Source | Signal | Legal position | Gate to next step |
|---|---|---|---|
| **Dorasuta asks** (dorasuta.jp) | Shop ask, raw, tiers 状態A / 状態A特価 / 状態C(プレイ用), stock (SV §2.1) | robots.txt has no `*` group (open); member terms have no scraping or reproduction clause (MEASURED, SV §2.1) | **Open: the next live source.** Gate is plan approval + shared foundations (§5 F1–F4) |
| **CardRush** (cardrush-op.jp) | Shop ask by condition grade; 2,176 PSA10/graded asks (CR §1) | robots.txt blocks only 4 AI bots; data policy page 403; snippet bans automated collection (UNVERIFIED) | **Permission pending (Q1).** No live request until RUSH says yes or the owner accepts the clause in writing; email in the Appendix |
| **Dorasuta buyback** (buy.dorasuta.jp) | Shop buy price, raw; a new signal type | Not yet audited; host still refused by network policy at 15:13Z (MEASURED, SV §2.6) | **Pending audit**: ≤40-request plan in SV §2.6, after the owner allows the host (N6) |
| **Aucfan** | Sold prices (auctions, flea markets) | Contract only: anonymous robots.txt got 429 (MEASURED, SV §2.2) | **Licence enquiry** (draft: SV Appendix A). Payment and Index use are RED |
| **magi** (magi.camp) | C2C sold, PSA10-heavy | robots.txt closes search to AI agents; terms ban commercial use and other interfaces (MEASURED, SV §2.3) | **Consent enquiry** (draft: SV Appendix B). No collection without written consent |
| **Suruga-ya** | Multi-shop asks + buyback (UNVERIFIED) | robots.txt returned 403 (MEASURED, SV §2.4) | **Parked.** No requests; email only if the owner chooses |
| **Fullahead** | Shop asks (UNVERIFIED) | Not audited | **Skipped** |

---

## 2. Shared foundations (built once)

Every item is additive and staging-only. Yuyu-Tei and SNKRDUNK behaviour is unchanged unless stated.

### 2.1 `grade_key` column and vocabulary (accepted Q13)

- **Column.** Nullable `price_observations.grade_key VARCHAR(32)`. The CHECK is added `NOT VALID`, then validated.
  No backfill, and NULL means "derive from `price_type`/`condition_label`".
- **Vocabulary:**
  - `raw:A`, `raw:A-`, `raw:B`, `raw:C`, `raw:D`, `raw:damaged`, `raw:play`;
  - `graded:<grader>:<grade>[:flawed]`, e.g. `graded:PSA:10`, `graded:PSA:10:flawed`, `graded:PSA:9`.
- **Per-source mapping:**

| Source text | grade_key |
|---|---|
| CardRush unlabeled / 〔状態A〕 | `raw:A` |
| CardRush 〔状態A-〕 / B / C | `raw:A-` / `raw:B` / `raw:C` |
| CardRush group 42 (傷アリ特価) member | `raw:damaged` (overrides the name label) |
| CardRush 〔PSA10鑑定済〕 / 〔※状態難/PSA10鑑定済〕 | `graded:PSA:10` / `graded:PSA:10:flawed` |
| Dorasuta 状態A / 状態A特価 / 状態C(プレイ用) | `raw:A` / `raw:damaged` / `raw:play` |
| SNKRDUNK floor A–D, psa10_asking (read-time only) | `raw:A`…`raw:D`, `graded:PSA:10` |
| Yuyu-Tei sell (read-time only) | `raw:A` |

`condition_label` keeps the verbatim source text. `price_type` keeps its meaning: `sell` for shop asks, `buy`
for buyback, `promotion_state='sale'` for sales.

### 2.2 Source and product-variant records (generic, not per-source)

- **Why generic.** Yuyu-Tei and SNKRDUNK keep their own `*_candidates` tables. New sources share three generic
  tables, so a third or fourth source needs no new migration.
- **`source_product_groups`.** Columns: source_id, group key, URL, verbatim title, kind
  (pack/promo/graded/damaged/sale/deck/other), resolved `release_product_id` (nullable), first and last seen.
  Covers CardRush product groups and Dorasuta `sid` series.
- **`source_products`.** One row per source product id. Columns:
  - source_id, source product id (unique per source), URL;
  - group keys (array; CardRush products sit in several groups, MEASURED);
  - verbatim name;
  - parsed code, rarity, variant markers and qualifier;
  - `match_status` (`unmatched|print_matched|identity_conflict|quarantined`) with a refusal code;
  - nullable `card_print_id`;
  - first and last seen.
- **`source_product_variants`.** One row per product × `grade_key`, with last price, stock, sale flag, last seen
  and last `raw_snapshot_id`.
  - CardRush has one variant per product: one product = one condition (MEASURED, CR §1.2).
  - Dorasuta has up to three per product: one product per print, with prices per tier (MEASURED, SV §2.1).
- **`source_variant_renderings`.** Reviewed marker text → `official_asset_variant`/artwork rule, per source.
  Examples: CardRush `パラレル/illust:…`; Dorasuta スーパーパラレル, ゴールドスーパーパラレル, 金箔, WANTED.
  Manual entries only.
- **Seeds.** `sources` rows `dorasuta` and `cardrush` are seeded in the same migration. The `cardrush` row is inert
  without a collector.
- **Proposal groups.** `source_mapping_proposal_groups.source_candidate_type` CHECK widened with `source_product`.
- **Mappings.** Existing `source_card_mappings`, one per source product. Observations link through
  `source_card_mapping_id` + `raw_snapshot_id` and carry `grade_key`.

### 2.3 Resolver framework with per-source rules

- **One entry point.** `SourceEvidence.from_source_product(product, rules)` feeds the existing
  `exact_print_approval.resolve_exact_print`. The refusal codes, `NEEDS_REVIEW_REFUSALS` and manual-mapping
  precedence are unchanged (INVARIANTS.md:14-17).
- **Per-source rule modules** supply only parsing:
  - `cardrush_rules`: name grammar CR §1.3;
  - `dorasuta_rules`: `name(rarity/variant)(CODE)【tag】`, SV §2.1.
- **Shared rules for all sources:**
  - code required;
  - release from the group, never from the code prefix; a product in two release groups is refused;
  - a variant only from explicit markers via `source_variant_renderings`;
  - condition never affects identity;
  - every non-exact outcome is quarantined.
- **Listing identity.** `packages/opcg_source_identity` gains `dorasuta.jp …product?pid=N` → `dorasuta:N` and
  `www.cardrush-op.jp/product/N` → `cardrush:N`, with conformance vectors.

### 2.4 Collector framework

- **Package.** `services/source_collector_kit/` is a small library: plain-HTTP fetch, robots gate, rate limiter,
  budget client, RAW-first writer, list-page work unit, health report and lossless counts. Each new collector
  (`dorasuta_collector`, later `cardrush_collector`) is a thin package on top. The kit is a runtime input of the
  **new** collectors only, so Yuyu and SNKR are not in its import graph.
- **Shared settings per source:**
  - one service, no shards, resumable segments;
  - one request at a time, 5 s spacing (3 s floor) + jitter;
  - honest user agent `CardPirateBot/1.0 (+contact URL)` (Q8 accepted);
  - robots.txt read on every run, fail closed;
  - `source_dispatch_budgets` row per source;
  - stop with `source_denial` and no retry on 403/429/challenge;
  - no images ever.
- **Health and lossless.** Each run reports pages, header totals vs ids seen, parse failures, new/gone, identity
  outcomes by refusal code, quarantine count and bytes stored. It follows `RAW_OPERATIONAL_HEALTH.md`, and
  `check_raw_health.py` learns each source. `verify-lossless` covers each new parser in
  `raw_dictionary_storage.PARSERS`.
- **Quarantine.** `freshness_work.state='blocked'` plus `source_products.match_status`, reported by
  `scripts/quarantine_reporting.py`.

### 2.5 Public-series guard

- Register every new source in `services/source_instruments.py` `SOURCE_INSTRUMENTS` **before any row exists**.
  Today an unregistered source exposes every price_type publicly (`source_instruments.py:99-103`, CR §D3).
- New sources are **hidden** from public reads until their cutover. After cutover, only the counted category is
  public (`raw:A` ask), as an attributed per-source line (Q7 accepted).

### 2.6 Splice at cutover (Q6 owner decision: splice, not break)

- **Problem.** Adding a source bumps `SOURCE_SEMANTICS_VERSION` and changes contributor sets. Today
  `market_value._comparability_reason` then excludes every print (`source_semantics_version_changed`,
  `contributor_set_changed`, `market_value.py:397-426`). That starts a new segment, and 7D/30D windows can't
  cross it.
- **Splice:**
  - On the cutover day D, the snapshot job computes each print's Market Index on **both** bases: old semantics
    without the new source, and new semantics with it.
  - The step D−1 → D uses the old basis at D, and the step D → D+1 uses the new basis at D.
  - Because Market Value is a chained ratio of comparable sums, the chain continues through D. History, 7D and
    30D stay continuous, and no level jump is attributed to the new source.
  - The Card Pirate Index uses the same basis rule for its constituents on D, so `METHODOLOGY_VERSION` stays 1
    (owner to confirm, §6 N11).
- **Additive schema:**
  - `market_index_splices`: day, from/to `SOURCE_SEMANTICS_VERSION`, source added, approved_at.
  - `market_index_splice_snapshots`: the old-basis rows for D only. `market_index_snapshots` keeps its
    `(card_print_id, snapshot_date)` key, `market_index_snapshot.py:82-84`.
- **Comparability change.** A version change is comparable only when a splice row exists for that boundary and
  both bases exist on D. Otherwise today's exclusion stands.
- **Rules:**
  - The machinery is built in F4, inert until a splice row exists.
  - Each source cutover is a separate splice. Splices are at least 14 days apart, and never on a day with
    another version change.
  - Ordinary contributor entries and exits after D (a print first gaining a Dorasuta price) stay
    `contributor_set_changed` as today.
- **Authority.** Using a splice is RED (methodology) at each cutover. Building it is AMBER.

---

## 3. Per-source sections

### 3.1 Dorasuta asks (first live source)

**Methodology** (proposed defaults; Q2–Q4 rules applied for source-neutrality):
- **Counted:** `raw:A` only.
- **Excluded from counting:** 状態A特価 (`raw:damaged`) and 状態C(プレイ用) (`raw:play`).
- **Stored in RAW and variants:** everything.
- **Sale:** provenance only.
- **Out of stock:** the accepted Q4 rule (Yuyu rule: eligible up to 7 days old, stock recorded). The survey's
  "in-stock only" (SV D2) is open as **N2**.
- **Index and Market Value:** a third or fourth median input via the splice, after shadow.

**Identity rules** (MEASURED grammar, SV §2.1):
- **Name grammar:** `name(rarity[/variant])(CODE)[【tag】]`, e.g. 「シャンクス(SP/SR/金箔)(OP09-004)【3周年SP】」.
- **Code** comes from the last `(XXnn-nnn)`. **Release** comes from the `sid` series; SP reprints are listed under the
  reprinting set, which is correct release evidence.
- **Variant markers** (パラレル, スーパーパラレル, レッドスーパーパラレル, ゴールドスーパーパラレル, 金箔/銀箔, WANTED,
  キャラクターエディション, ★) go through reviewed `source_variant_renderings` to p1…p7. Without a rendering the
  product is quarantined.
- **One product id per print** (MEASURED), so the expected collision rate is low. The ambiguity rate is
  **not yet measured**.
- **Gate in the canary:** at least 65% of sampled `raw:A` products resolve exactly, and 0 of 50 hand-checked
  resolve to a wrong print.

**Collector settings** (ESTIMATE from MEASURED structure):

| Item | Setting |
|---|---|
| Daily | Page 1 of each of the 60 series (rows are ordered SEC/SP/parallel first, where prices move) |
| Sweep | All about 255 list pages over a 6-day cycle (about 43/day), so every row is ≤ 7 days old (the Index ask max age) |
| Requests | About 103/day + robots + series-list ≈ **105/day**; budget row 200/86,400 s |
| Run time | About 105 × (5 + 1.5) s ≈ **11 min/day** |
| Slot | 15:00 UTC daily, clear of Yuyu/SNKR fires and quiet windows |
| Freshness | Page-1 rows 24 h; swept rows ≤ 7 days (**N3**) |
| Load | Terms Art. 8 lets Dorasuta suspend service on load, so the 5 s spacing is a hard floor for Dorasuta |

**Storage** (ESTIMATE, SV §2.1):
- About **1.0 MB/day** (RAW dictionary-encoded about 0.6 + rows about 0.4) plus about **10 MB** once.
- Cap: **1.5 MB/day measured over 48 h**, or stop and re-plan (survey D7, **N5**).

### 3.2 CardRush (second live source, when Q1 clears)

**Status.** The plan is complete in CR §A–§H, with accepted answers Q2–Q5, Q7–Q13 and splice for Q6. The
differences from the CardRush plan:
- **Records.** Generic records (§2.2) replace `cardrush_candidates` and `cardrush_product_groups`. The fields
  are the same.
- **Grade.** A group-42 member gets `raw:damaged` regardless of its name label.
- **Cutover.** It uses the shared splice, not a break.

**Methodology (accepted):**
- **Raw:** unlabeled = 状態A only. Group 42, graded, ☆SALE☆, sealed, decks and oripa are excluded.
- **Sale:** provenance only.
- **Out of stock:** Yuyu rule.
- **PSA10:** kept in RAW and variants, with no PSA10 observations while OFF; 状態難 slabs are excluded when turned on.
- **Public:** an attributed 状態A line after cutover.

**Identity** (CR §C, MEASURED sample of 1,988 raw candidates, CR §1.5):
- 52.5% are the only listing for their code;
- 18.0% are a base print among variants;
- 23.9% are variants needing renderings;
- 5.0% are uncoded;
- 1.5% are in two pack groups (refused);
- 0.6% have a qualifier prefix.
- **ESTIMATE:** 65–75% exact on first pass.

**Collector** (CR §E):
- **Daily:** the 145 pack/promo group pages.
- **Weekly sweep:** `/product-list` (149 pages) plus groups 37/42, about 27/day.
- **Requests:** about 200/day, 5 s spacing, about 17 min/day, slot 16:00 UTC.

**Storage** (CR §F, ESTIMATE from MEASURED 400 KB list pages):

| Mode | Per day | Notes |
|---|---|---|
| Daily, encoded RAW | 3.4 MB | |
| Daily, plaintext | 9.2 MB | Does not fit |
| 48-hour cadence, encoded | 1.85 MB | Freshness target 48 h for CardRush only (**N4**) |

The one-off is about 27 MB in every mode.

### 3.3 Dorasuta buyback (pending audit)

- **Placeholder.** Store as `price_type='buy'`, **auxiliary-only**, like Yuyu `buy`
  (`AUXILIARY_ONLY_PRICE_TYPES`). It is never an Index or Market Value input and never public until a separate
  decision (**N12**).
- **Cadence:** weekly.
- **Storage:** about 0.1 MB/day + about 2 MB once (ESTIMATE, SV §1).
- **Next step:** the ≤40-request audit planned in SV §2.6 (robots.txt, terms, an OP-05 buylist) sets identity,
  cadence and the go/no-go. It needs `buy.dorasuta.jp` allowed in network access (N6). No buyback figure is measured yet.

### 3.4 Aucfan (placeholder: licence enquiry)

- **Route:** contract only (SV §2.2). Sold data from auctions and flea markets. Titles mix raw and graded, so
  `graded:*` would be split out by title rules.
- **On reply,** this section gets its own methodology: sales vs asks in the median, title-to-print rules and
  volume.
- **Approvals:** payment is RED (a paid service), and Index inclusion is RED (methodology).
- **Storage placeholder:** about 1.0 MB/day + about 10 MB once (ESTIMATE, SV §1).

### 3.5 magi (placeholder: consent enquiry)

- No collection without written consent from 株式会社ジラフ (terms Art. 8(v)/(dd), robots.txt search disallow
  for Claude agents, MEASURED SV §2.3).
- On consent, a section like Aucfan's follows. There is no storage budget until then.

---

## 4. One storage budget (ESTIMATE unless marked)

- **Owner figures** (MEASURED, 2026-10-16, `storage-rates` run 38898278774): room to the 3 GiB reserve
  **2,938 MB**; planning **23.35 MB/day**; stress B **27.58 MB/day**.
- **Rule:** (rate + new) × 90 + one-off ≤ room at planning **and** stress B.
- **Remaining-50 batch:** 70.6 MB once + 0.45 MB/day recurring allowance (MEASURED basis,
  `capacity75-session13/HANDOFF.md:59`, `scripts/ops/enqueue_remaining.py:24`).

Cumulative, in delivery order:

| Added (cumulative) | MB/day | One-off MB | Total new MB/day | Total one-off | Planning margin | Stress B margin |
|---|---|---|---|---|---|---|
| Today only | 0 | 0 | 0 | 0 | +836.5 | +455.8 |
| + remaining-50 batch | 0.45 | 70.6 | 0.45 | 70.6 | +725.4 | +344.7 |
| + Dorasuta asks (light) | 1.0 | 10 | 1.45 | 80.6 | +625.4 | +244.7 |
| + Dorasuta buyback (weekly) | 0.1 | 2 | 1.55 | 82.6 | **+614.4** | **+233.7** |
| + CardRush, daily, encoded | 3.4 | 27 | 4.95 | 109.6 | +281.4 | **−99.3 does not fit** |
| + CardRush at 48 h instead | 1.85 | 27 | 3.40 | 109.6 | +420.9 | **+40.2 (thin)** |
| + Aucfan placeholder (on 48 h CardRush) | 1.0 | 10 | 4.40 | 119.6 | +320.9 | **−59.8 does not fit** |

- **What this means:**
  - Dorasuta asks, buyback and the remaining-50 batch fit comfortably.
  - CardRush fits only at a 48-hour cadence, and thinly, at today's stress B.
  - Aucfan on top does not fit without new room.
- **Admission rule.** Each later source is admitted only on a **re-run** of `storage-rates` with measured bytes
  from the earlier sources. Measured Dorasuta and CardRush ratios may be better or worse than these estimates.
- **Levers before paid storage**, in order:
  1. byte-identical RAW de-duplication (CR §F4.2);
  2. a 48-hour cadence for asks-only sources;
  3. narrowing scope to prints with fewer than two sources.
- **Never:** RAW retention or deletion.
- **RAW-to-R2 is a separate future plan, noted only here.** It is the data-platform design. It is a paid service
  (RED), it changes the RAW location for all sources, and it would lift the cap for CardRush daily plus Aucfan.
  It is out of scope.

---

## 5. Delivery sequence

**Conventions:**
- **Lanes.** Everything below is DATA lane (collectors, import graph, identity, prices, MI/MV, migrations,
  `docs/agent/`). Each delivery has a regenerated `STAGING_MISSION.json`.
- **One delivery at a time.** Draft PRs only, one staging delivery at a time.
- **Quiet windows.** No merges 19:30–20:30 UTC. No collector change 02:00–06:00 UTC. Collector releases only
  06:00–23:00 UTC, at least 5 min after and 8 min before a collector fire.

| Step | What | Level | Canary | Owner approvals |
|---|---|---|---|---|
| **P0** | Approve this plan and the §6 answers | RED decisions | — | **Yes** |
| **F1** | Migration: `grade_key`, generic source tables (§2.2), splice tables (§2.6), `sources` seeds; public-series guard registrations (§2.5). No collector code | AMBER (additive migration) | — | Owner runs `alembic upgrade head` (backup under 24 h) |
| **F2** | Shared modules: `opcg_source_identity` hosts + vectors, `from_source_product` + rule modules, `PARSERS` entries, freshness list-page unit, tooling (`COLLECTORS`, `NAMES`, cap, lane, raw health). One sequential 10-service rollout with restore path | AMBER | existing collectors per `STAGING_DELIVERY.md` | Cap raise (**N10**) |
| **F3** | `source_collector_kit` + `dorasuta_collector` package and Dockerfile, tested only on fixtures from SV §2.1 (mock data first). No deploy | AMBER | — | — |
| **F4** | Splice machinery in MI snapshot, Market Value and CPI, inert without a splice row; replay tests on a synthetic cutover | AMBER (code; no methodology change until used) | replay on staging data via `ops-readonly` | — |
| **D1** | Dorasuta live canary: owner creates `dorasuta-collector` (cron off) and sets variables and budget. 3 sets in full daily (about 21 pages), observations hidden | AMBER (new source volume) | 3 sets | **Yes**: Railway service, variables, envelope, cron on |
| **D2** | **48 h storage check**: `storage-rates` + measured bytes per page; identity gate (§3.1). Go only if ≤ 1.5 MB/day projected and the gate passes; then widen to light mode (60 series + sweep) | GREEN (read-only) → AMBER widen | — | Widen: **yes** |
| **D3** | **Shadow ≥ 14 days**, hidden. Daily report: storage, denials, parse, quarantine, Dorasuta vs Yuyu divergence; proposed cutover date | GREEN | — | — |
| **D4** | **Splice cutover**: Dorasuta `SOURCE_SEMANTICS` entry, version v3→v4, resolver in `print_market_index.py`, splice row for D, attributed public line | **RED** (methodology) | single day, before the 20:00 UTC snapshot | **Yes**: date and go |
| **B1** | Dorasuta buyback (after its audit): parser + weekly job, auxiliary-only | AMBER | 1 set | **Yes**: envelope, cron |
| **C0** | **Q1 clears**: RUSH's written yes, or the owner's written acceptance of the clause. Re-run `storage-rates`; choose daily or 48 h (**N4**) | RED decision | — | **Yes** |
| **C1** | `cardrush_collector` package on the kit, fixtures from CR §1. No deploy | AMBER | — | — |
| **C2** | CardRush canary: OP-01 group (4 pages) daily for 3 days → 5 groups → all 145; observations hidden; **48 h storage check** as D2 | AMBER + RED (Q1 already cleared in C0) | 4 → 20 → 145 pages | **Yes**: service, variables, envelope, each widen |
| **C3** | Shadow ≥ 14 days (as D3) | GREEN | — | — |
| **C4** | Splice cutover for CardRush, v4→v5, at least 14 days after D4 | **RED** | single day | **Yes** |
| **A/M** | Aucfan or magi only after a written licence or consent; own plan section first | RED | — | **Yes** |
| — | Any external delivery of derived values (partner API, licensing) | RED | — | Blocked until the legal opinion covers each source |

---

## 6. Owner questions still open (merged, renumbered)

Already answered and not repeated: CR Q1 (plan default), Q2–Q5, Q7–Q13 accepted, Q6 splice.

| # | Question | Default |
|---|---|---|
| N1 | Make Dorasuta asks the first live source, in light mode (SV D1)? | **Yes** |
| N2 | Dorasuta out-of-stock: use the accepted Q4 rule (eligible ≤ 7 days, stock recorded) or the survey's in-stock only (SV D2)? | **Q4 rule**, so all shop asks follow one rule |
| N3 | Dorasuta freshness: page-1 rows daily, the rest on a 6-day sweep (all ≤ 7 days)? | **Yes** |
| N4 | CardRush storage: does not fit daily on top of the rest. Choose at C0 with measured numbers, falling back to a 48 h cadence (CardRush-only freshness 48 h)? | **Yes**: measure at C0, 48 h if still short; no paid storage |
| N5 | Dorasuta storage cap 1.5 MB/day measured over 48 h, else stop and re-plan (SV D7)? | **Yes** |
| N6 | Allow `buy.dorasuta.jp` for the buyback audit (SV D3); keep Fullahead skipped? | **Yes** / skipped |
| N7 | Send the Aucfan licence enquiry and the magi consent request (SV Appendix A and B)? | **Yes**, now; no payment without a separate RED approval |
| N8 | Send the CardRush permission email (Appendix) from your own address? | **Yes**, now |
| N9 | Suruga-ya: stay parked with no requests? | **Yes** |
| N10 | Collector service cap 10 → 11 at F2 (Dorasuta) and → 12 at C2 (CardRush)? | **Yes**, one step each |
| N11 | Splice rules: one splice per source, ≥ 14 days apart, CPI `METHODOLOGY_VERSION` stays 1? | **Yes** |
| N12 | Dorasuta buyback auxiliary-only (never Index/MV, not public) like Yuyu buy? | **Yes** |
| N13 | PSA10 or graded rows from every new source: RAW and variants only, PSA10 OFF (SV D8)? | **Yes** |
| N14 | Open a separate check of the Yuyu-Tei base-print mapping gaps seen in SV §3 (D9)? | **Yes**, a separate thread |

---

## Appendix: CardRush permission email (draft; the owner sends)

To: info@cardrush-op.jp. Placeholders are in 【 】. Nothing has been sent.

### 日本語

件名：価格データの参照に関するご相談（ONE PIECEカードゲーム相場サイト「Card Pirate」）

株式会社RUSH
カードラッシュ ワンピース ご担当者様

突然のご連絡失礼いたします。ONE PIECEカードゲームの相場情報サイト「Card Pirate」（【サイトURL】）を
運営しております【氏名】と申します。

貴社サイト（www.cardrush-op.jp）の公開商品一覧ページに掲載されている販売価格・在庫表示を、
相場の参考値として参照させていただけないか、ご相談のためご連絡いたしました。
フッターの「当サイトの価格データ等の利用について」（cardrush.media/data_policy）を拝見しようとしましたが、
現在アクセスできない状態のため、直接お問い合わせさせていただきます。

想定している利用方法は以下のとおりです。
1. 取得方法：商品一覧ページのみを1日1回、1リクエストずつ5秒以上の間隔をあけて取得します（1日あたり約150〜200ページ）。
   画像は一切取得・保存・表示いたしません。robots.txt を毎回確認し、連絡先を明記した専用のUser-Agentを使用します。
2. 利用目的：複数店舗の価格から算出する相場の参考値（中央値など）の計算にのみ使用します。
3. 表示：貴社の個別の商品名・説明文・画像を転載することはありません。表示する場合は算出値のみとし、
   出典として「カードラッシュ」を明記いたします。
4. 第三者提供：貴社の価格データを第三者へ提供・販売することはいたしません。
5. 停止：ご要望があれば、ただちに取得を停止し、ご指示に従います。

上記の範囲での参照をご許可いただけますでしょうか。条件やご懸念点がございましたら、
それに沿って運用いたします。許可いただけない場合も、その旨ご返信いただければ取得は行いません。

お忙しいところ恐れ入りますが、ご検討のほどよろしくお願い申し上げます。

【氏名】
Card Pirate 運営
【メールアドレス】
【サイトURL】

### English

Subject: Request regarding use of price data (One Piece Card Game price site "Card Pirate")

To the CardRush One Piece team, RUSH Co., Ltd.

My name is 【name】 and I run "Card Pirate" (【site URL】), a price reference site for the One Piece
Card Game.

I am writing to ask whether we may refer to the selling prices and stock indications shown on the public
product list pages of your site (www.cardrush-op.jp) as one input to market reference values. I tried to
read the "About the use of price data on this site" page linked in your footer
(cardrush.media/data_policy), but it is currently not accessible, so I am asking you directly.

What we propose:
1. Collection: product list pages only, once a day, one request at a time at least 5 seconds apart
   (about 150–200 pages a day). No images are fetched, stored or shown. We check robots.txt on every run
   and use a dedicated User-Agent that includes our contact details.
2. Purpose: only to calculate reference values (such as a median) across several shops.
3. Display: we do not reproduce your product names, descriptions or images. Where shown, only the
   calculated values appear, with "CardRush" credited as a source.
4. Third parties: we do not provide or sell your price data to anyone.
5. Stopping: on your request we stop collecting immediately and follow your instructions.

Would you allow this use within the scope above? If you have conditions or concerns, we will operate
accordingly. If you do not allow it, a short reply is enough and we will not collect.

Thank you for considering this request.

【name】
Card Pirate
【email】
【site URL】
