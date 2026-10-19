# New price sources: combined plan (PLAN ONLY), revision 2

Status: **APPROVED (P0 done)** by the owner 2026-10-19 00:34Z in the project thread "New sources decisions and
Dorasuta build"; decisions recorded in §7.1. Build starts with S0. Revision 2 written 2026-10-18 on branch
`plan/new-sources`, against `origin/staging` 99844c6. Revision 1 (394608b, 2026-10-16) is in git history.
STAGING ONLY. Production RED. PSA10 OFF.

**Supersedes** `plan/cardrush-source` (history at `1c6a511`, keeps the MEASURED CardRush audit). Nothing from
either plan has been built.

**What changed since revision 1:**
1. **Yuyu-Tei F1 foil rule** (owner 2026-10-17/18): ラメフォイル / 海賊旗フォイル titles are their own kind, never
   plain. 762 F1 proposals (about 79% Yuyu-Tei coverage) accepted, going live in owner-approved batches of about
   500 with a 48 h storage check after each. F3 dropped, no aliases. New sources follow the same foil rule (§2.3).
2. **Identity-capture batches resumed** (owner 2026-10-18), each ops-write batch owner-approved and dry-run first.
   About 225 captures left, about 300 MB one-off (ESTIMATE). The capture-day storage option was declined, so no
   image saving is assumed.
3. **Storage**: 2,807 MB left before the 3 GiB reserve (MEASURED, `storage-rates`, 2026-10-18 16:3xZ; owner figure
   about 2,825 MB), growth about 30 MB/day (owner figure; planning 33.3, last 24 h 27.2, MEASURED). The
   revision 1 budget (2,938 MB room, 23.35 MB/day) is obsolete. §4 is rebuilt on days until the reserve, the
   owner's standing watch (flag below 45 days).
4. **Delivery rule**: a PR that rolls out a collector merges **only** through the `staging-automerge` CI job
   (marked ready, no `hold-for-owner`). Never hand-merged, never GitHub native auto-merge armed by hand: both skip
   the rollout step. §5 marks which PRs roll out a collector.
5. **Outreach closed** (owner 2026-10-16 21:45Z): no emails or enquiries to any source. Aucfan, magi and エーツー
   are out unless the owner decides to buy data (RED); Yahoo! Shopping and Rakuten APIs are KIV. The CardRush
   permission email of revision 1 is therefore **not to be sent** and has been removed from this plan (still in
   394608b). CardRush Q1 can now clear only by the owner's written acceptance (decision N2).
6. **Import graph measured** (this revision, `scripts/collector_runtime_inputs.py` at 99844c6): both existing
   collectors import every module under `services/api/app/models/` through `models/__init__.py`, plus
   `raw_dictionary_storage.py`, `freshness_*.py`, `operational_health*.py` and `source_recovery.py`. The yuyutei
   collector also imports `exact_print_approval.py`, `source_mapping_proposals.py`, `official_asset_variant.py`
   and others. Revision 1 put shared code in those files, which would have redeployed all 10 Yuyu/SNKR services.
   Revision 2 keeps every new-source change outside those files (§2.7).

Labels: **MEASURED** (source given), **CARRIED FORWARD** (from a committed plan), **ESTIMATE**, **UNVERIFIED**.
"CR §x" = CardRush plan, "SV §x" = `plan/source-survey` SURVEY.md.

---

## Plain summary (for the owner)

1. **Order stays the same:** shared foundations, then Dorasuta shop prices, then Dorasuta buyback, then CardRush.
   Both shops are kept, on the same terms: honest bot name with a contact address, robots.txt read on every
   run, one request at a time, no images, and a full stop on any 403, 429, challenge page or notice from the site.
2. **Raw prices only.** Graded listings (PSA and others) are recognised and kept apart in storage. They never
   become prices while PSA10 is OFF.
3. **None of this redeploys the Yuyu-Tei or SNKRDUNK collectors** (design target, checked by a test in every PR).
   Three PRs roll out a collector, each only the new one: Dorasuta, the buyback job, CardRush. Those three merge
   only through the staging-automerge job.
4. **Storage:** both sources together add about 3 MB/day (ESTIMATE). Days until the reserve go from about 75
   (today plus the Yuyu work already approved) to about 68 with both sources (ESTIMATE). That stays above your
   45-day flag. If the SNKRDUNK discovery fix also goes ahead, it falls to about 57 days.
5. **Coverage:** with Yuyu F1 live, about 78% of prints have a raw price. Dorasuta could take that to about 91%
   and CardRush to about 96% (ESTIMATE). Biggest gains are SEC (55% to about 93%) and SR (74% to about 97%).
   Prints with two or more shop prices go from 334 to about 3,300 (ESTIMATE).
6. **You decided all of N1 to N16 on 2026-10-19 (§7.1).** No build until the owner says go.

---

## 1. Sources and status

| Source | Signal | Legal position | Gate to next step |
|---|---|---|---|
| **Dorasuta asks** (dorasuta.jp) | Shop ask, raw, tiers 状態A / 状態A特価 / 状態C(プレイ用), stock (SV §2.1) | robots.txt has no `*` group (open); member terms have no scraping or reproduction clause; Art. 8 allows suspension on load (MEASURED, SV §2.1) | **First live source.** Plan approval (N1) + foundations S0 to S4 |
| **Dorasuta buyback** (buy.dorasuta.jp) | Shop buy price, raw | Not audited; host refused by this environment's network policy (MEASURED 2026-10-16) | Owner allows the host (N8), then the ≤40-request audit in SV §2.6 |
| **CardRush** (cardrush-op.jp) | Shop ask by condition; graded asks (CR §1) | robots.txt blocks only 4 AI bots (MEASURED); data policy page 403 (MEASURED); search snippet bans automated price collection (UNVERIFIED) | **Q1:** no email will be sent, so live only on the owner's written acceptance (N2), then storage re-check at C0 |
| Aucfan, magi, Suruga-ya / エーツー | Sold prices / shop asks | Contract or consent only | **Out**, no contact (owner 2026-10-16 21:45Z) |
| Yahoo! Shopping, Rakuten APIs | Shop asks | Official APIs | **KIV**, no app IDs, no calls |
| Fullahead | Shop asks | Not audited | Skipped |

---

## 2. Shared foundations (built once)

All additive, staging-only. Yuyu-Tei and SNKRDUNK behaviour and deployed code are unchanged.

### 2.1 `grade_key` and vocabulary (accepted Q13)

- Nullable `price_observations.grade_key VARCHAR(32)`; CHECK added `NOT VALID`, then validated. No backfill;
  NULL means "derive from `price_type` / `condition_label`".
- Vocabulary: `raw:A`, `raw:A-`, `raw:B`, `raw:C`, `raw:D`, `raw:damaged`, `raw:play`;
  `graded:<grader>:<grade>[:flawed]` (e.g. `graded:PSA:10`, `graded:BGS:9.5`, `graded:PSA:10:flawed`).
- **The ORM column is not added to `models/price_observation.py` in this work** (that file is in both collectors'
  import graph, §2.7). The new collectors write `grade_key` through their own table definition. The ORM line is
  folded into the next owner-approved Yuyu/SNKR redeploy, whenever that happens for its own reasons.

| Source text | grade_key |
|---|---|
| CardRush unlabeled / 〔状態A〕 | `raw:A` |
| CardRush 〔状態A-〕 / B / C | `raw:A-` / `raw:B` / `raw:C` |
| CardRush group 42 (傷アリ特価) member | `raw:damaged` (overrides the name label) |
| CardRush 〔PSA10鑑定済〕 / 〔※状態難/PSA10鑑定済〕 | `graded:PSA:10` / `graded:PSA:10:flawed` |
| Dorasuta 状態A / 状態A特価 / 状態C(プレイ用) | `raw:A` / `raw:damaged` / `raw:play` |
| Any new-source title with PSA, BGS, CGC, ARS, 鑑定 or a slab marker | `graded:<grader>:<grade>`; unparseable grade → `graded:unknown` |
| SNKRDUNK floor A-D, psa10_asking (read-time only) | `raw:A`…`raw:D`, `graded:PSA:10` |
| Yuyu-Tei sell (read-time only) | `raw:A` |

**Graded separation:** `graded:*` products are stored in RAW and `source_product_variants` only. They never
produce a `price_observations` row while PSA10 is OFF, never count as raw, and never feed Index, Market Value
or a public line. Turning graded on later is a separate RED decision.

### 2.2 Generic source records (unchanged from revision 1)

- `source_product_groups` (source, group key, URL, verbatim title, kind, resolved `release_product_id`, seen
  times): CardRush groups, Dorasuta `sid` series.
- `source_products` (one row per source product id: URL, group keys array, verbatim name, parsed code, rarity,
  variant markers, qualifier, foil marker, `match_status` + refusal code, nullable `card_print_id`, seen times).
- `source_product_variants` (product × `grade_key`: last price, stock, sale flag, last seen, last
  `raw_snapshot_id`). CardRush: one per product. Dorasuta: up to three per product.
- `source_variant_renderings` (reviewed marker text → `official_asset_variant` / artwork rule, per source;
  manual entries only).
- `sources` rows `dorasuta` and `cardrush` seeded (the `cardrush` row is inert without a collector).
  `source_mapping_proposal_groups.source_candidate_type` CHECK widened with `source_product`. Observations link
  through `source_card_mapping_id` + `raw_snapshot_id` and carry `grade_key`.
- ORM models for these tables live in a new module **not imported by `models/__init__.py`** (§2.7).

### 2.3 Resolver framework

- New module `source_product_resolver.py`: `SourceEvidence.from_source_product(product, rules)` calls the
  existing `exact_print_approval.resolve_exact_print` **without modifying it**. Refusal codes,
  `NEEDS_REVIEW_REFUSALS` and manual-mapping precedence (manual always wins) are unchanged.
- Per-source rule modules supply parsing only: `cardrush_rules` (CR §1.3 grammar), `dorasuta_rules`
  (`name(rarity/variant)(CODE)【tag】`, SV §2.1).
- Shared rules: code required; release from the group, never from the code prefix; a product in two release
  groups is refused; variant only from explicit markers through `source_variant_renderings`; condition never
  affects identity; every non-exact outcome is quarantined.
- **Same kinds as Yuyu-Tei F1 (owner 2026-10-17):** a product is plain, parallel, special, or **foil**. Titles
  with ラメフォイル or 海賊旗フォイル are foil, never plain, and match only a foil print of the same card;
  with no foil print in the catalogue they stay unmatched (today true for all PRB foils, MEASURED 162 Yuyu
  listings). A bare promo "P" token never decides a kind. The two-way-unique rule (one product of a kind, one
  print of that kind, inside one release) is the only absence-based rule allowed.
- Listing identity: `dorasuta.jp …product?pid=N` → `dorasuta:N` and `www.cardrush-op.jp/product/N` →
  `cardrush:N`, with conformance vectors, **in the collector kit, not in `packages/opcg_source_identity`**
  (amended 2026-10-19: every file of that package is a runtime input of both existing collectors,
  `scripts/collector_runtime_inputs.py` `counts()`, so editing it would redeploy all 10 Yuyu/SNKR services).
  The hosts move into the shared package only inside an owner-approved Yuyu/SNKR redeploy (N13).

### 2.4 Collector kit and source etiquette

- `services/source_collector_kit/`: plain-HTTP fetch, robots gate, rate limiter, budget client, RAW-first
  writer, list-page work unit, health report, lossless counts, its own RAW parser registry. Each collector
  (`dorasuta_collector`, later `cardrush_collector`) is a thin package on it. Only the new collectors import it.
- **Etiquette (both sources, not configurable per run):**
  - honest user agent `CardPirateBot/1.0 (+<contact>)`, contact from an env variable (N16), never a browser UA,
    never one of the agents a robots.txt names;
  - robots.txt fetched at the start of every run; fetch failure or a disallow on a needed path = no run
    (fail closed);
  - one request at a time, 5 s spacing + jitter (Dorasuta Art. 8 load clause makes this a hard floor);
  - no images, no product pages in routine runs (list pages only), no login, no cookies beyond the session;
  - `source_dispatch_budgets` row per source.
- **Stop rule (N15):** any HTTP 403 or 429, a challenge or captcha page, a robots.txt change that disallows us,
  or any notice from the site (on-page notice, email to the contact address) stops that source at once:
  `source_denial` recorded, no retry, cron turned off by the owner, owner told the same day. Restart only on a
  new owner decision.
- Health: pages, header totals vs ids seen, parse failures, new/gone, identity outcomes by refusal code,
  quarantine count, **bytes stored per run**. `check_raw_health.py` learns each source; `verify-lossless`
  covers each new parser through the kit's registry.

### 2.5 Public-series guard (unchanged)

Register each new source in `services/source_instruments.py` `SOURCE_INSTRUMENTS` **before any row exists**
(today an unregistered source exposes every price_type, `source_instruments.py:99-103`). Hidden until its
cutover; after cutover only `raw:A` asks are public, as an attributed per-source line (Q7).

**Amended 2026-10-19 (read-path audit at 99844c6):** registration alone does not hide a source. These public
paths pick sources from the data and would show a new source's rows the day they exist: `print_series`
(`load_source_catalogue`, `default_series_requests`, `/prints/{id}/series` and `/analytics`),
`print_pricing` (`/prints/{id}/prices`, latest and history), `latest_prices`, `api/cards` (`/cards/{id}/prices`),
`market.get_market_movers` (`/market/movers`) and the worker's `check_alerts`. `customer_price_clause` only hides
Yuyu-Tei sale rows. S2 therefore adds one shared `PRE_CUTOVER_SOURCES` gate (`dorasuta`, `cardrush`) to
`customer_price_clause` (and the worker copy), the `print_series` source catalogue, `get_market_movers` and the
three `check_alerts` reads, plus an invariant test that pre-cutover sources stay out of `SOURCE_INSTRUMENTS`,
`INDEX_INPUT_PRICE_TYPES` and `AUXILIARY_ONLY_PRICE_TYPES` (Market Index, snapshots, analytics bases, Market Value,
CPI and collection valuation are safe only because of that). None of these files is a collector runtime input.
Cutover (D4/C4) removes the source from `PRE_CUTOVER_SOURCES`.

### 2.6 Splice at cutover (Q6: splice, not break; unchanged)

On cutover day D the snapshot job computes each print's Market Index on both bases (old semantics without the
new source, new with it); D−1 → D uses the old basis, D → D+1 the new. History and 7D/30D stay continuous.
Additive `market_index_splices` and `market_index_splice_snapshots` tables; a version change is comparable only
when a splice row exists and both bases exist on D. Built inert in S4; each use is RED. One splice per source,
≥14 days apart, never on a day with another version change; CPI `METHODOLOGY_VERSION` stays 1 (N12).
`SOURCE_SEMANTICS_VERSION` is 3 today (MEASURED, `source_semantics.py:116`).

### 2.7 Keeping Yuyu-Tei and SNKRDUNK out of it (new)

- **Files no new-source PR may change** (they are runtime inputs of the existing collectors, MEASURED at
  99844c6): anything under `services/api/app/models/` that `models/__init__.py` imports, `models/__init__.py`
  itself, `db.py`, `settings.py`, `env.py`, `exact_print_approval.py`, `source_mapping_proposals.py`,
  `official_asset_variant.py`, `artwork_*.py`, `physical_artwork_proof.py`, `identity_evidence_scope.py`,
  `discovery_proposal_refresh.py`, `raw_dictionary_storage.py`, `freshness_integration.py`,
  `freshness_policy.py`, `freshness_queue.py`, `operational_health*.py`, `source_recovery.py`,
  `snkrdunk_urls.py`, `yuyutei_urls.py`.
- **Guard test** in S1: `collector_runtime_inputs.changed_runtime_inputs` for `yuyutei` and `snkrdunk` between
  the PR base and head must be empty on every new-source PR. A non-empty result fails the PR.
- **If a design step cannot avoid one of those files** (for example the freshness work-unit CHECK needs code in
  `freshness_queue.py`), that change is pulled out into **one** bundled PR that redeploys Yuyu/SNKR, needs the
  owner's explicit redeploy go (standing rule), merges through staging-automerge, and ideally rides the
  SNKRDUNK "-P" resolver redeploy if the owner approves that separately (N13).

---

## 3. Per-source sections

### 3.1 Dorasuta asks (first live source)

- **Counted:** `raw:A` only. 状態A特価 (`raw:damaged`) and 状態C(プレイ用) (`raw:play`) stored, not counted.
  Graded titles per §2.1. Sale = provenance only.
- **Out of stock:** Q4 rule (eligible up to 7 days, stock recorded), so all shop asks share one rule (N4).
  Sold-out rows keep a stale price on the site (MEASURED, SV §2.1): stored with stock 0, not counted beyond 7 days.
- **Identity** (MEASURED grammar): `name(rarity[/variant])(CODE)[【tag】]`; code from the last `(XXnn-nnn)`;
  release from the `sid` series (SP reprints sit under the reprinting set, which is correct release evidence);
  one product id per print (MEASURED). Variant markers (パラレル, スーパーパラレル, レッドスーパーパラレル,
  ゴールドスーパーパラレル, 金箔/銀箔, WANTED, キャラクターエディション, ★) go through reviewed renderings; none →
  quarantined. Dorasuta lists no promo series (60 series: OP, EB, PRB, ST, one fest set, MEASURED), so promos
  are not expected from it.
- **Canary gate:** ≥65% of sampled `raw:A` products resolve exactly, and 0 of 50 hand-checked resolve to a wrong
  print.
- **Collector** (ESTIMATE from MEASURED structure): daily page 1 of each of the 60 series (SEC/SP/parallel rows
  first) + all about 255 list pages over a 6-day sweep (about 43/day), so every row is ≤7 days old (N5). About
  105 requests/day, about 11 min/day, slot 15:00 UTC; budget row 200/86,400 s.
- **Storage** (ESTIMATE, SV §2.1): about **1.0 MB/day** (dictionary RAW about 0.6 + rows about 0.4) + about
  10 MB once. Cap 1.5 MB/day measured over 48 h, else stop and re-plan (N6).

### 3.2 Dorasuta buyback (after its audit)

- `price_type='buy'`, auxiliary-only like Yuyu `buy` (`AUXILIARY_ONLY_PRICE_TYPES`): never Index, Market Value
  or public until a separate decision (N9). Same etiquette and stop rule.
- Weekly. About **0.1 MB/day** + about 2 MB once (ESTIMATE, SV §1). Audit first (≤40 requests: robots.txt,
  terms, one buylist), which needs `buy.dorasuta.jp` allowed (N8). No buyback figure is measured yet.
- Lives in `dorasuta_collector` as a second job, so its PR rolls out only the Dorasuta service.

### 3.3 CardRush (when Q1 clears)

- Plan complete in CR §A-§H, with accepted Q2-Q5, Q7-Q13 and splice for Q6. Differences: generic records
  (§2.2), group-42 member = `raw:damaged`, shared splice, foil and graded rules from §2.1/§2.3.
- **Counted:** unlabeled = 状態A only. Group 42, graded, ☆SALE☆, sealed, decks, oripa excluded. PSA10 rows: RAW
  and variants only while OFF (CR §1.4 MEASURED 114 PSA10 products in a 4-set sample); 状態難 slabs excluded if
  ever turned on.
- **Identity** (MEASURED sample of 1,988 raw candidates, CR §1.5): 52.5% only listing for the code, 18.0% base
  among variants, 23.9% variants needing renderings, 5.0% uncoded, 1.5% in two pack groups (refused). First-pass
  exact 65-75% (ESTIMATE). CardRush has promo groups, so it is the only new source for P promos.
- **Collector** (CR §E): 145 pack/promo group pages + weekly sweep of `/product-list` (149 pages) and groups
  37/42. Slot 16:00 UTC.
- **Cadence (N7):** every 48 h by default (about 100 requests/day average, about 9 min/day), daily only if the
  C0 storage re-check allows it.
- **Storage** (CR §F, ESTIMATE from MEASURED 400 KB list pages): 48 h encoded **1.85 MB/day**; daily encoded
  3.4 MB/day; daily plaintext 9.2 MB/day (never). About 27 MB once in every mode.

---

## 4. Storage (days until the 3 GiB reserve)

**Inputs:** room 2,807 MB (MEASURED 2026-10-18); today's growth 30 MB/day (owner figure; MEASURED range 27.2 to
33.3). Yuyu work already approved: about 225 remaining captures, about 300 MB one-off (ESTIMATE); 762 F1 prints
put on refresh at about 4.2 KB per print per day, about 3.2 MB/day (ESTIMATE from MEASURED per-print rate).
This may double-count if the 30 MB/day already averages in capture days, so the table leans pessimistic.

**Days = (room − one-offs) ÷ daily growth.** All ESTIMATE.

| Step (cumulative) | New MB/day | One-off MB | Growth MB/day | Days to reserve |
|---|---|---|---|---|
| Today | 0 | 0 | 30.0 | **93** |
| + Yuyu captures + F1 refresh (approved) | 3.2 | 300 | 33.2 | **75** |
| + Dorasuta asks | 1.0 | 10 | 34.2 | **73** |
| + Dorasuta buyback | 0.1 | 2 | 34.3 | **72** |
| + CardRush, 48 h | 1.85 | 27 | 36.2 | **68** |
| CardRush daily instead of 48 h | 3.4 | 27 | 37.7 | 65 |
| + SNKRDUNK discovery fix (not approved; 100-250 MB once, about 4 MB/day) on CardRush 48 h | 4.0 | 175 | 40.2 | **57** |
| same, on CardRush daily | 4.0 | 175 | 41.7 | 55 |

**Per source (ESTIMATE):** Dorasuta asks 1.0 MB/day, Dorasuta buyback 0.1 MB/day, CardRush 1.85 MB/day at 48 h
(3.4 daily). Both sources together about 2.95 MB/day, under 10% of today's growth.

**What this means:**
- Every step stays above the 45-day flag.
- Revision 1's rule ((rate + new) × 90 + one-off ≤ room) now fails on today's growth plus the approved Yuyu work
  alone (33.2 × 90 + 300 = 3,288 MB > 2,807 MB), so it can no longer separate a good source from a bad one.
  Proposed replacement (N3): **admit a source only if days to reserve, re-measured with `storage-rates` and the
  per-source bytes diagnostic, stay ≥60 after adding it.** That leaves 15 days of warning above the flag.
- Under that rule, CardRush fits at 48 h (68) and daily (65) on today's numbers, but **not** if the SNKRDUNK
  discovery fix lands first (57 / 55). Then at C0 the choice is: CardRush 48 h anyway (still above 45), RAW
  byte-identical de-duplication first (CR §F4.2), or a bigger volume (owner, paid).
- Levers before paid storage: 48 h cadence for ask-only sources; RAW byte-identical de-duplication; narrowing
  CardRush to prints with fewer than two sources. Never RAW retention or deletion without an owner decision.
- Every widen step has a 48 h storage check; the per-source bytes diagnostic (S0) attributes bytes by source,
  so Dorasuta and CardRush checks can overlap Yuyu F1 batches without confusing the numbers.

---

## 5. Build split (PRs in order)

**Merge paths:**
- **Rollout PR:** changes a collector's runtime inputs and the manifest selects it. Marked ready, no
  `hold-for-owner`, merged **only** by the `staging-automerge` CI job, which rolls the collector out. Never
  hand-merged, never native auto-merge armed by hand. Never touches `.github/workflows/ops-readonly.yml`.
  Released 06:00-23:00 UTC, never 02:00-06:00, and the job itself holds out 19:30-20:30.
- **Hold PR:** touches `ops-readonly.yml` (new diagnostics). Draft + `hold-for-owner`, merged by hand by the owner
  (or the coordinator when delegated). Never contains collector code.
- **Plain PR:** DATA lane, regenerated `STAGING_MISSION.json`, no collector selected, merged by staging-automerge
  with nothing to roll out.
- One staging delivery at a time. Every new-source PR carries the §2.7 guard test (Yuyu/SNKR inputs unchanged).

| # | PR | Merge path | Collector rollout | Owner step |
|---|---|---|---|---|
| P0 | Approve this plan and §7 | n/a | none | **Yes** |
| S0 | Diagnostic `source-bytes-by-source` (bytes per source per UTC day, RAW and rows) and `new-source-coverage` (priced prints by rarity and source count) | Hold | none | Hand merge |
| S1 | Additive migration: `grade_key`, generic source tables, splice tables, `sources` seeds, proposal CHECK widen; new-source ORM module outside `models/__init__`; §2.7 guard test | **Hold** (amended 2026-10-19: the owner merges and then runs the migration, so the receipt is red only between the two) | none | Merges, then runs `alembic upgrade head` (backup <24 h) |
| S2 | Pre-cutover gate on every public read path for `dorasuta`, `cardrush` (§2.5 amendment), before any row | Plain | none | n/a |
| S3 | Listing identity + vectors in the kit (§2.3, not `opcg_source_identity`); `source_product_resolver` + `dorasuta_rules` + `cardrush_rules`; foil/graded parsing; kit parser registry. Fixtures only | Plain | none | n/a |
| S4 | Splice machinery in MI snapshot, Market Value, CPI, inert; synthetic replay tests | Plain | none (worker/api only) | n/a |
| D0 | `source_collector_kit` + `dorasuta_collector` + Dockerfile, tested on SV §2.1 fixtures (mock data first); not selected by the manifest | Plain | none | n/a |
| D1 | Register `dorasuta` in deploy tooling (`COLLECTORS`, `NAMES`, cap 10 → 11, raw health) and select it in the manifest | **Rollout** | **Yes: `dorasuta-collector` only** | Before: creates the Railway service (cron off), variables incl. contact (N16), budget row. After: cron on for 3 sets |
| D2 | 48 h storage + identity check (read-only). Widen to 60 series + sweep by variable if ≤1.5 MB/day and the gate passes | n/a | none (variable change) | **Yes**: widen |
| D3 | Shadow ≥14 days, hidden; daily report (bytes, denials, parse, quarantine, Dorasuta vs Yuyu divergence) | n/a | none | n/a |
| D4 | Cutover: Dorasuta `SOURCE_SEMANTICS` entry, v3 → v4, splice row, attributed public line | Plain | none | **Yes, RED**: date and go |
| B0 | Buyback audit (≤40 requests), report only | n/a | none | Allows `buy.dorasuta.jp` (N8) |
| B1 | Buyback parser + weekly job inside `dorasuta_collector`, auxiliary-only | **Rollout** | **Yes: `dorasuta-collector` only** | Envelope, cron |
| C0 | Q1 cleared (N2) + `storage-rates` re-run; choose 48 h or daily (N7) under N3 | n/a | none | **Yes, RED** |
| C1 | `cardrush_collector` on the kit, CR §1 fixtures; not selected | Plain | none | n/a |
| C2 | Register `cardrush` in deploy tooling (cap 11 → 12), select it; canary OP-01 (4 pages) → 5 groups → all, 48 h check after each | **Rollout** | **Yes: `cardrush-collector` only** | Service, variables, each widen |
| C3 | Shadow ≥14 days | n/a | none | n/a |
| C4 | Cutover v4 → v5, ≥14 days after D4 | Plain | none | **Yes, RED** |

**Rollouts in total: three (D1, B1, C2), each of one new service.** Zero Yuyu/SNKR redeploys planned. If §2.7
forces one, it becomes a separate bundled PR with the owner's redeploy go (N13).

---

## 6. Expected coverage gain by rarity (ESTIMATE)

**Baseline** (MEASURED, `yuyu-coverage-gap` run 39014897188, 2026-10-17): 4,316 verified prints, 2,616 with a
fresh Yuyu-Tei price. **After Yuyu F1** (ESTIMATE from MEASURED `yuyu-f1-sizing` run 39076525684 by-rarity
rows, 762 proposals). SNKRDUNK adds under 1% today (28 high-rarity prints fresh, MEASURED) and is ignored.

**Assumed share of still-unpriced prints each source prices** (listed × resolves exactly; ESTIMATE from SV §2.1
and CR §1.5): Dorasuta base 75%, parallel 60%, reprint 55%, SP 60%, promo 0%; CardRush (on what Dorasuta
leaves) base 70%, parallel 55%, reprint 50%, SP 55%, promo 40%.

| Rarity (all kinds) | Prints | Priced now | After Yuyu F1 | + Dorasuta | + CardRush | Priced after both | 2+ shop sources |
|---|---|---|---|---|---|---|---|
| L | 307 | 130 (42%) | 260 (85%) | +32 | +9 | 301 (98%) | 245 |
| SEC | 128 | 30 (23%) | 70 (55%) | +37 | +12 | 119 (93%) | 81 |
| SP | 129 | 117 (91%) | 117 (91%) | +7 | +3 | 127 (98%) | 100 |
| SR | 616 | 195 (32%) | 458 (74%) | +105 | +31 | 595 (97%) | 462 |
| R | 882 | 509 (58%) | 694 (79%) | +121 | +39 | 854 (97%) | 689 |
| UC | 717 | 515 (72%) | 527 (74%) | +111 | +42 | 680 (95%) | 544 |
| C | 1,478 | 1,113 (75%) | 1,245 (84%) | +142 | +50 | 1,437 (97%) | 1,217 |
| P (promo) | 57 | 5 (9%) | 5 (9%) | 0 | +21 | 26 (46%) | 2 |
| TR | 2 | 2 | 2 | 0 | 0 | 2 | 2 |
| **Total** | **4,316** | **2,616 (61%)** | **3,378 (78%)** | **+555** | **+207** | **4,140 (96%)** | **3,342 (77%)** |

- "2+ shop sources" today: 334 prints (CARRIED FORWARD, 2026-10-15 state). This is what makes the median
  meaningful: about 3,300 prints would have two or three independent shop asks (ESTIMATE).
- **Low case** (every resolve rate 40% lower): about 3,900 prints priced, about 90% (ESTIMATE).
- The new sources also reach base prints that Yuyu-Tei cannot tell apart (SEC base 1 of 38 priced today):
  Dorasuta lists one product per print, which is exactly where Yuyu-Tei's listing data is ambiguous.
- Measured by S0's `new-source-coverage` diagnostic in each shadow report; these estimates are replaced then.

---

## 7. Owner decisions (approve in one go)

Already decided and not repeated: CR Q1 plan default, Q2-Q5, Q7-Q13 accepted, Q6 splice; outreach closed
(no emails; Aucfan, magi, エーツー out; Yahoo/Rakuten KIV); Yuyu F1 foil rule, F3 dropped, captures resumed.

| # | Decision | Recommended | Why (one line) |
|---|---|---|---|
| N1 | Approve this plan: foundations, then Dorasuta asks (light mode), then buyback, then CardRush | **Yes** | Dorasuta is open, cheap (1 MB/day) and fills the base-print gap Yuyu-Tei can't. |
| N2 | CardRush Q1: since no email will be sent, do you accept in writing that CardRush runs under the §2.4 etiquette and stop rule, despite the unread data policy? | **Yes, live start still gated at C0** | You asked to keep both sources; the email route is closed, and stop-on-notice limits the risk of the unverified clause. |
| N3 | Storage rule: admit a source only if days to reserve stay ≥60 after adding it (45-day flag unchanged) | **Yes** | The old 90-day rule already fails on today's growth, so it can't judge new sources. |
| N4 | Dorasuta out of stock: Q4 rule (eligible ≤7 days, stock recorded) | **Yes** | One rule for every shop ask. |
| N5 | Dorasuta freshness: page 1 daily, rest on a 6-day sweep (all ≤7 days) | **Yes** | Chase cards stay daily at about 105 requests/day. |
| N6 | Dorasuta cap: 1.5 MB/day measured over 48 h, else stop and re-plan | **Yes** | Catches a bad bytes estimate before it costs days of runway. |
| N7 | CardRush cadence: 48 h by default, daily only if N3 still holds at C0 | **48 h** | Saves 1.55 MB/day; shop asks move slowly. |
| N8 | Allow `buy.dorasuta.jp` in Project settings > environment > Network access for the ≤40-request audit | **Yes** | Buy prices are a new signal and the audit is tiny. |
| N9 | Dorasuta buyback auxiliary-only (never Index, Market Value or public) | **Yes** | Same treatment as Yuyu `buy`; no methodology change. |
| N10 | Graded rows from new sources: RAW and variants only, no observations, PSA10 OFF | **Yes** | Keeps raw prices clean and graded data ready for later. |
| N11 | Collector service cap 10 → 11 at D1 and → 12 at C2 | **Yes** | One new service each, one step at a time. |
| N12 | Splice: one per source, ≥14 days apart, CPI `METHODOLOGY_VERSION` stays 1 | **Yes** | History stays continuous and each cutover is checked on its own. |
| N13 | No Yuyu/SNKR redeploy for new sources; anything unavoidable goes in one bundled redeploy PR needing your go | **Yes** | Honours the standing rule; three rollouts touch only new services. |
| N14 | Order versus the SNKRDUNK discovery fix (if you approve it): CardRush first, SNKRDUNK fix after | **CardRush first** | SNKRDUNK fix first would push CardRush below the 60-day rule (57 days). |
| N15 | Stop rule: 403, 429, challenge, robots disallow or any site notice stops the source until you decide | **Yes** | Your instruction, made a hard rule in the kit. |
| N16 | Contact in the user agent: a dedicated address you create (not your personal email), stored as an env variable | **Yes, you supply it before D1** | Honest identification without exposing a personal address or committing it. |

### 7.1 Owner decisions recorded 2026-10-19

The owner answered on 2026-10-19 00:34Z using the **revision 1 numbering** (394608b §6). Each answer is mapped
to the revision 2 number below. Quoted text is the owner's.

| Rev 1 # | Owner answer | Rev 2 # | Recorded decision |
|---|---|---|---|
| N1 | "yes" | N1 | Plan approved: foundations, then Dorasuta asks (light mode), then buyback, then CardRush. |
| N2 | "Q4 rule" | N4 | Dorasuta out of stock follows the Q4 rule (eligible up to 7 days, stock recorded). |
| N3 | "yes" | N5 | Dorasuta page 1 daily, the rest on a 6-day sweep (all rows 7 days old or newer). |
| N4 | "yes (measure at C0, 48 h fallback, no paid storage)" | N7 | CardRush cadence chosen at C0 on measured numbers; 48 h if storage is short; no paid storage. |
| N5 | "yes" | N6 | Dorasuta cap 1.5 MB/day measured over 48 h, else stop and re-plan. |
| N6 | "yes" | N8 | `buy.dorasuta.jp` allowed for the 40-request audit; Fullahead stays skipped. See note 2. |
| N7 | "no (no permission requests)" | (outreach) | No Aucfan or magi enquiry. Confirms outreach closed (owner 2026-10-16). |
| N8 | "no email; owner accepts the CardRush clause in writing here, so Q1 is cleared" | N2 | **Q1 cleared** by the owner's written acceptance. No email is sent. CardRush still waits for C0 and runs under the §2.4 etiquette and stop rule. |
| N9 | "yes (parked)" | (Suruga-ya) | Suruga-ya stays parked, no requests. |
| N10 | "yes" | N11 | Collector service cap 10 to 11 at D1, 11 to 12 at C2. |
| N11 | "yes" | N12 | One splice per source, 14 days or more apart, CPI `METHODOLOGY_VERSION` stays 1. |
| N12 | "yes" | N9 | Dorasuta buyback is auxiliary-only (never Index, Market Value or public). |
| N13 | "yes" | N10 | Graded rows from new sources: RAW and variants only, no observations, PSA10 OFF. |
| N14 | "yes (separate thread)" | (none) | Separate check of the Yuyu-Tei base-print mapping gaps (SV §3, D9), in its own thread, outside this build. |

Also recorded:
- **N15 stop rule**: already the owner's standing instruction (2026-10-16: honest UA, robots.txt respected, stop
  on any 403 or 429). Built as written in §2.4.
- **N13 (rev 2), no Yuyu/SNKR redeploy**: follows the standing rule that a Yuyu/SNKR redeploy needs the owner's
  go. The §2.7 guard test is built in S1.

**Answered 2026-10-19 09:50Z (owner; nothing left open):**
1. **N3 (rev 2): yes.** Admit a source only if days to reserve stay 60 or more after adding it; 45-day flag
   unchanged.
2. **N14 (rev 2): superseded.** The SNKRDUNK discovery fix (#180) is approved and delivering on 2026-10-19, so
   SNKRDUNK goes first. At C0, re-measure storage with #180's real bytes and apply N3; if CardRush fails 60 days
   at daily cadence, use the 48 h fallback (N7). The ordering question is closed.
3. **N16 (rev 2): supplied** to the thread. The address is **never committed** (not in code, docs, fixtures or
   PR text). The owner sets it as Railway variable `SOURCE_COLLECTOR_CONTACT` on the `dorasuta-collector`
   service before D1 (and on `cardrush-collector` before C2). The kit refuses every request while it is unset.

Notes:
1. Nothing in S0 to D0 needs the open items.
2. `buy.dorasuta.jp`, `dorasuta.jp` and `www.cardrush-op.jp` were all still refused by this cloud environment's
   proxy on 2026-10-19 00:36Z (CONNECT 403, MEASURED). The owner said to run the buyback audit (B0) from a new
   thread in the `cardpirate-data` project if this one is refused. S0 to D0 use committed fixtures and do not
   need either host.

---

## 8. Risks

- CardRush's policy text is unread (403); N2 is a legal-risk acceptance, not a permission.
- Dorasuta's exact-match rate is not measured; the canary gate decides.
- Storage estimates use a 6 KB/page dictionary ratio that has not been measured on either site.
- A Yuyu F1 batch, a capture batch and a new-source widen inside the same 48 h are separable only with S0.
