# Capacity / RAW75: session 12 handoff (2026-10-13)

STAGING ONLY. Production RED, untouched. PSA10 OFF.
- No source job was triggered manually.
- No collector release, rollback or setting change: 0 collector deployments all session.
- No mapping approval, no proposal review. No SNKRDUNK discovery.
- No schedule, budget, pacing, freshness or check-threshold change. No RAW evidence deleted.
- No resize, no infrastructure change.
- Database reads used `default_transaction_read_only=on`. **One AMBER staging write: the 50 NEW50 capture intents (§3a).** 0 source requests by this session.

Numbers are **MEASURED** (source under `evidence/`, read-only tools in `tools/`) unless marked
CARRIED FORWARD (CF) or ESTIMATE. The session ran 14:39-16:12Z, after the 14:16Z start gate.

## 0. Start gate (14:39-14:48Z)

| Check | Result | Evidence |
|---|---|---|
| Disk | 2.79 GiB free at 14:39Z, below the 5 GB gate. Owner chose to free 3 items: 5 orphaned test-DB volumes from the collector-v1 S2 test runs (12:28-13:24Z), and the S1 and S2 worktree `node_modules`/`.next`. Result: **5.11 GiB (5.49 GB) free** | session log |
| Delivery running | None (#114 draft; fonts PR not opened) | `gh run list` |
| All 10 collectors on `a504e47` | **Yes.** Exact-commit marker, SUCCESS, active deployment and digest equal the PR #103 receipt, cron, start command and daily-v1 variables unchanged. **0 deployment records** on any collector since the 2026-10-11 16:31:08Z rollout | `live-state-start.json`, `fleet-vs-receipt-start.json` |
| GitHub triggers | None on any collector; auto-deploy disabled on all 10 | `trigger-status-start.json`, `live-state-start.json` (`trigger_preflight`) |
| Backup | Daily `e1a2c03c…` 2026-10-13 09:22Z (5.6 h old); schedule `22 9 * * *`, 6-day retention | `backups-start.json` |
| State | `CURRENT_STATE-start.yaml` (14:44:28Z): 3 blockers, the same as session 11 | `staging-state-16899c922881a135.json` |

## 1. Rollback-trigger decision: NOT FIRED. `a504e47` verified; window closed

`evidence/trigger-decision.json`, `evidence/trigger-window.json` (14:45Z).

**First full cycle complete.** All **67/67** recurring Yuyu discovery items had a completed attempt on
`a504e47`, the last one finishing **2026-10-12 14:18:37.6Z**. Discovery attempts on `a504e47`:
- 10-12: 67 completed, 3,732 requests;
- 10-13: 67 completed, 3,730 requests;
- 0 failures.

**One-time conversion finished.**
- Created per hour: 265 / 34 / 476 / 140 at 01-04Z on 10-12 (915), then 1,247 at 13Z and 2 at 14Z (1,249).
- Total **2,164 = 915 + 1,249**.
- Yuyu current pending groups on resolver 1.3: **2,164**; on 1.2: **0**. The 323 pending 1.2 groups left are SNKRDUNK, which has no new versions.

**24 h after the cycle** (2026-10-12 14:18:37Z → 10-13 14:18:37Z):

| Measure | MEASURED | Trigger |
|---|---|---|
| New proposal versions | **74** (Yuyu only, all 1.3 pending: 53 ambiguous, 13 release_unresolved, 8 unresolved_identity) | > 200 → **not fired** |
| What they replaced | 74 1.3 pending groups, i.e. real listing changes (reasons: 53 `multiple_eligible_sibling_prints_in_resolved_release`, 19 `source_series_does_not_resolve_to_release_product`, 8 `card_code_does_not_resolve_to_canonical_card`). No listing has more than 2 versions since the merge | |
| Early signal 10-13 01:12-04:15Z | **25 versions** (15/15 attempts completed, 836 requests) vs the **915** baseline on the same items | |
| Approved exact Yuyu / SNKR | **2,019 / 151** | unchanged |
| Approved with proof | **298** | **no proof lost** |
| Approved superseded / demoted / created since the merge | **0 / 0 / 0** | |
| Reviews since the merge (auto-approval check) | **0** | |
| Discovery failures since the rollout | **0** | |
| Proposal tables | groups 63,922,176 B + alternatives 16,384,000 B, 32,489 group rows; **+5.1 MB since session 11 (06:28Z 10-12)**, mostly the 1,249 one-time versions | |

**Verdict:** both triggers not fired. **`a504e47` is recorded as verified, and the rollback window is closed.**
Steady state is about 74 versions/day, roughly 0.22 MB/day at 2,990 B/version (ESTIMATE from MEASURED).

## 2. Provenance alarm fixed (tooling only): PR #115

`deployment-provenance-divergence` compared every service with the repository head, so it fired
after every docs or web merge. `scripts/generate_staging_state.py` now records a per-service
`provenance` decision:
- **Collectors:** current when `scripts/collector_runtime_inputs.py` reports no changed runtime input since the deployed commit.
- **API and market-index-snapshot:** current when no Railway watch-pattern path changed.
- **Frontend:** must still equal the head.
- **Still diverges:** off-history commits, platform and marker SHAs that disagree, and undeterminable graphs or patterns (fail closed).
- The blocker now names the divergent services.

| Evidence | Result |
|---|---|
| Live before merge (14:48Z, head `b3862e6`) | blockers **3 → 2**. All 10 collectors current on `a504e47` (0 changed inputs); API and snapshot current on `5d86629` (0 watched changes) |
| Counterfactual on real history (`provenance-counterfactual.json`) | Yuyu on `a852244`: **flagged** (2 runtime inputs changed by `a504e47`). SNKR on `a852244`: current (imports neither). API on `a504e47`: **flagged** (104 watched changes) |
| Tests | `test_generate_staging_state.py` 29 passed, 12 new, covering both cases |
| Delivery-job state at head `f1d9267` (after this non-collector merge) | **2 blockers**; provenance gone (`pr115-delivery/…/CURRENT_STATE.yaml`) |
| Collector deployments | **0** (no rollout requested; Railway records, §8) |

`docs/agent/STAGING_DELIVERY.md` records the rule.

## 3. NEW100: NEW50 APPROVED and enqueued (AMBER); NEW100 NOT APPROVED (fits only at the planning rate)

**Window (owner decision 2026-10-12: current collector code only).**
- From the `a852244` rollout `completed_at` **2026-10-10T14:31:00.43Z** (PR #98 receipt) to 2026-10-13T14:50Z.
- 5-minute Railway `DISK_USAGE_GB` samples strictly after the rollout: **868 samples, 72.25 h (≥ 72 h)**.
- Evidence: `volume-series-5min.json`, `storage-rates-current-code.json`.

| Rate | MB/day (s9 basis) | Runway with no batch |
|---|---|---|
| **Planning** = average daily growth over the window | **21.78** | 141.3 days |
| **Stress** = worst rolling 24 h inside it (from 10-12 13:20Z) | **25.86** | 119.0 days |
| Context: lowest rolling 24 h / last 24 h | 18.82 / 24.06 | |
| Consecutive days from the rollout | 18.9, 22.4, 24.2 | |

- Room to the 3 GiB reserve: **3,076.5 MB** (volume 3,702.2 MB at 14:50Z; reserve line unchanged since session 10). Horizon 90 days.
- Recurring cost per capture: 24.06 MB / 2,685 Yuyu attempts in the same 24 h = 8.96 KB (overstated).

**Batch fit** (`new100-storage.json`). Need = rate × 90 + one-off + recurring × 90; the hard
bound is the decision basis, as in sessions 10-11:

| Batch | One-off hard / estimate (MB) | Recurring MB/day | Planning margin (hard) | Stress margin (hard) |
|---|---|---|---|---|
| NEW100 (100 + 217 images) | 894.5 / 134.1 | 0.90 | **+141.2 fits** | **−226.0 does not fit** |
| **NEW50** (50 + 102 images) | 429.1 / 65.2 | 0.45 | **+646.9 fits** | **+279.7 fits** |
| NEW25 (25 + 51 images) | 214.5 / 32.6 | 0.22 | +881.6 | +514.4 |

**Re-plan on current digests** (`new100-replan.json`, 14:51Z; re-run before the apply as
`new100-replan-preapply.json`, §3a). Canonical resolver 1.3 on all 100 candidates of the 2026-10-07
plan: **100/100 eligible, 0 guard failures**, 0 sibling sets changed. Every stored group digest
now equals the live one, since the 1.3 re-version landed.

| Guard | Result | Evidence |
|---|---|---|
| Exact CardPrint identity (ambiguous family, 2-12 complete siblings, prints exist, same canonical card) | **PASS 100/100** | `new100-replan.json` |
| No duplicate active Yuyu mapping (prints or listing) | **PASS 100/100** | same |
| Authoritative `release_product_id` (never from code prefix) | **PASS 100/100** | same |
| Virgin family, no shared print between candidates | **PASS 100/100** | same |
| Shards | **PASS.** Captures are claimable by all 9 shards; refresh after a later mapping is `mapping_id % 9` (CF s11: 290-292 per shard) | CF `yuyu-shard-balance.txt` (s11) |
| 23h/24h feasibility | **PASS.** (2,616 + 50) × 31.1 = 82.9k/day vs 432k/day (19%); one-off 50 captures × about 58 requests ≈ 2.9k (ESTIMATE) | `requests-24h.json` |
| Measured source capacity (last 24 h) | **PASS.** Yuyu 2,616 captured, 2 transient failures, busiest window 4,527 / 9,000 (50%), 0 over reservation. SNKR peak 2,849 / 3,100 (< 2,945), 0 over reservation | `requests-24h.json` |
| Freshness not degraded | **PASS.** 0 actionable checks older than 24 h (non-blocked max age: Yuyu 21.9 h, SNKR 23.2 h); same 69 blocked items as before (§6) | `freshness-detail.json`, `coverage-start.json` |
| Storage, both rates | **NEW50 PASS; NEW100 planning only** | `new100-storage.json` |

**Batch verdict:**
- **NEW100: NOT APPROVED.** It fits only at the planning rate. Owner question below.
- **NEW50: fits at both rates, all non-storage guards PASS → AMBER, proceeded.** Enqueued 16:06:12Z (§3a).

**Owner question (NEW100).** NEW100 fails the stress rate by 226 MB on the hard bound (894.5 MB
of base64 2 MiB images); on the measured-average estimate (134.1 MB) it fits at both rates with
+534 MB. Options:
- (a) keep the hard bound: NEW50 now, the second 50 once room grows, after the NEW50 actuals are measured;
- (b) accept the measured-average estimate for the remaining 50, once NEW50's actual one-off bytes confirm it.

### 3a. Enqueue tool and apply

The tool is `scripts/yuyu_identity_capture_enqueue.py` (**PR #116**, GREEN).
- **Modes:** dry run by default, `--apply` explicit.
- **Pinned input:** the approved list is pinned by SHA-256.
- **Live checks:** each entry is re-resolved live with the same checks the collector's `load_intent` makes, plus: no active mapping, no reviewed decision, no other capture scope, no shared print.
- **Fail closed:** one failure means no write at all.
- **Idempotent:** an identical intent is a no-op.
- **Never approves:** it writes only through `plan_discovery_scope`; never proposals, reviews or mappings.
- **Not a collector release:** not in the collector import graph (`scripts/`; 0 changed runtime inputs, `import-graph-provenance-pr.json`).
- **Tests:** 12 Postgres tests, including the real collector `load_intent` accepting a written intent after a claim.

**Apply (AMBER), in order.** Preflight: `new50-amber-preflight.json` (impact, backup `e1a2c03c` at 6.7 h old,
rollback and triggers, verification).

1. PR #116 merged and its delivery verified (15:56:14Z).
2. **Re-plan immediately before the apply:** `new100-replan-preapply.json` (15:57:01Z): 100/100 eligible, 0 guard failures, **0 digest changes since 14:51Z**.
3. Approved list = the first 50 eligible in plan order: `new50-approved.json`, SHA-256 `906482e8d9958617627a34307d3dbd896d30d51cfd9ce4753dce82f49037a1f9`. 50 families, 102 official images.
4. Dry run (`new50-enqueue-dryrun.json`, 16:03:15Z): DRY_RUN_OK, 50 checked, 50 to enqueue, 0 already present, 0 writes.
5. **Apply** (`new50-enqueue-apply.json`, 16:06:12Z): **APPLIED, 50 intents written, work ids 3678-3727**; 0 proposal or mapping writes, 0 source requests.
6. Read back (`new50-postapply-check.txt`, 16:07Z): 50 rows, all `discovery`/`pending`/`attempt_count 0`, due 16:06:13Z, `yuyu-identity:<cid>:sha256:<digest>` scopes, `explicit_identity_capture` true, reserved cost 5,000. **0 attempts yet**, 0 approvals since the apply.

The intents are claimed by ordinary scheduled Yuyu turns. Nothing was triggered.

## 4. Storage and lossless

| | MEASURED |
|---|---|
| Volume (Railway `DISK_USAGE_GB`, s9 basis) | **3,702.2 MB** at 14:50Z; room to the 3 GiB reserve **3,076.5 MB** |
| Database (`pg_database_size`, 15:15Z) | 2,849,175,231 B (2,849.2 MB). `raw_snapshots` 2,631.5 MB (92%), proposal groups 63.9 MB, `market_index_snapshots` 36.8 MB, `freshness_attempts` 20.8 MB, `app_log_events` 17.3 MB, proposal alternatives 16.4 MB, `price_observations` 16.3 MB |
| **Collector-v1 S3 tables** (included above) | `collection_entries` 49,152 B, `collection_entry_events` 16,384 B, `watchlist_entries` 49,152 B, `user_preferences` 8,192 B, `collection_value_points` 8,192 B: **131,072 B total, 0 rows** |
| Growth, current code | planning 21.78 MB/day, stress 25.86 MB/day |
| Runway, no batch | 141.3 days (planning) / 119.0 days (stress) |
| Runway with NEW50 at its hard bound | (3,076.5 − 429.1) / (rate + 0.45): **119.1 days** planning / **100.6 days** stress (ESTIMATE from MEASURED) |
| 30 / 90-day projection (planning, no batch) | +653 MB / +1,960 MB (ESTIMATE) |

**Lossless** (`verify-lossless-from-50072.json`): every daily-v1 ledger row from 50072 to 53967 checked.
- 3,648 rows (Yuyu 3,065, SNKR 583);
- original 854.9 MB → encoded 9.5 MB;
- **0 failures, 0 expanded, `all_lossless: true`**; 0 writes, 0 source requests.
- Next floor (exclusive): **53967**.

## 5. Degraded signals (read-only, nothing changed)

The PR #101 receipt (2026-10-12) showed `snkrdunk` and `raw_due_work` DEGRADED. Live now:
`snkrdunk` DEGRADED, `yuyu` HEALTHY, `raw_due_work` DEGRADED (`degraded-signals.json`, 15:14Z).

**What they measure.** `app/services/operational_health.py` `aggregate()` over
`operational_health_sql.DUE_SQL`:
- **Eligible population:** approved, active, unsuperseded mappings on active verified prints (SNKR also `manual_verified`).
- **`overdue`:** never checked, or last success over 24 h old.
- **`quarantined`:** work `state='blocked'`.
- A source is DEGRADED with `due_work_deficit` if overdue or quarantined is above 0. Run summaries add `deadline_misses` and `never_checked`.
- `raw_due_work` is the worse of the two sources.

**Why.** Every overdue item is identity-quarantined work:

| Source | Work state | Eligible | Overdue | Never checked | Over 24 h |
|---|---|---|---|---|---|
| SNKRDUNK | **blocked** | 66 | **66** | 22 | 44 |
| SNKRDUNK | pending | 287 | **0** | 0 | 0 |
| Yuyu | pending | 2,616 | **0** | 0 | 0 |

The 66 are blocked since **2026-10-02 15:54Z** (22, earliest) and **2026-10-06 07:27-18:27Z** (the
rest). Their last successful checks were 2026-10-04 13:30Z to 10-05 11:29Z. Causes:
- 39 `artwork_not_confirmed_match: placeholder_image_url; no_raw_condition_price`;
- 22 `existing confirmed identity-validation refusal; explicit review required`;
- 2 placeholder image;
- 2 artwork `no_match`;
- 1 artwork unavailable on explicit capture.

Separately, 23 SNKR validation items have been blocked since 10-06 05:01-09:30Z.

| Signal | Classification | Proposed fix (not done) |
|---|---|---|
| `snkrdunk` DEGRADED | **Expected state that the check mislabels.** Quarantine is a correct identity guard (`snkrdunk-identity-quarantine` blocker), but the health check counts blocked items as deadline misses, so SNKR can never be HEALTHY while any quarantine exists. That would hide a real freshness regression | Count `state='blocked'` work as `identity_quarantine` only. Exclude it from `overdue`, `never_checked`, `deadline_misses` and `due_work_deficit` in `aggregate()`, and in the collector run summaries. Keep the quarantine visible as its own reason or blocker. Reporting change; owner/reviewer sign-off because it touches check semantics |
| `raw_due_work` DEGRADED | **Same cause** (worse of the two sources) | Follows from the fix above |
| Underlying | **Real backlog, not a regression:** 66 approved SNKR mappings that cannot refresh | Identity review (Priority 5), §6 |

## 6. Freshness (read-only, nothing changed)

`freshness-detail.json` (15:14Z). `deadline_compliance: not_met` is computed over **all** raw
refresh work in any state. **Every one of the 69 items behind it is blocked work.** 0 actionable
items miss the target. Non-blocked: Yuyu 2,616 items, max age 21.9 h; SNKR 287 items, max age
23.2 h.

| Source | Items | Cards | Miss | Since | Cause |
|---|---|---|---|---|---|
| Yuyu | 3 | OP09-077 base (never checked), OP16-118 p1 (178 h), OP16-119 p1 (177 h) | 1 never / about 7.4 days | 2026-10-06 05:13-05:47Z | **Mapping inactive**: mission containment, an existing exact print/source mapping takes precedence (duplicates contained 10-06). Their refresh work still sits in the freshness population |
| SNKR | 39 + 2 | placeholder-image artwork refusals | 216-218 h | 2026-10-06 10:57-11:34Z | SNKRDUNK shows a placeholder image, so the artwork cannot be confirmed (identity quarantine) |
| SNKR | 22 | existing validation refusals | never checked | 2026-10-02 15:54Z | Need explicit identity review |
| SNKR | 3 | artwork `no_match` (2), artwork unavailable (1) | 196-218 h | 2026-10-06 | Identity quarantine |

**Proposed fixes, ranked by effort (nothing changed):**
1. **Reporting (small, tooling):** compute deadline compliance over actionable work and report blocked items separately as quarantine or containment. Targets are unchanged; capacity misses stay visible. Owner sign-off, as for §5.
2. **Yuyu 3 contained duplicates (small, AMBER data hygiene):** their mappings are inactive. Exclude inactive mappings' work from the freshness population, or close those 3 work rows with a guarded tool. No RAW deleted.
3. **SNKR 22 validation refusals (medium, review):** explicit identity review. Fix the mapping where exact, or deactivate; never bulk-unquarantine.
4. **SNKR 44 artwork refusals (larger):** wait for real SNKRDUNK artwork, or use the physical-artwork proof path where a product capture shows it; otherwise deactivate after review.

## 7. Coverage

`coverage-start.json` (14:57:31Z), denominator 4,316:
- mapped 2,635;
- **operational 2,630 (change from 2,630: 0)**, 607 to the 75% target (3,237);
- fresh usable 2,398; both sources 334; zero sources 1,681;
- duplicate exact-print source groups 0.

Active mappings: Yuyu 2,622, SNKR 359.

## 8. Deliveries and receipts

| PR | Merge | CI run | Artifacts (id; expire) | Scope | Collector deployments |
|---|---|---|---|---|---|
| #106 session-11 handoff | `e1e2a0b` 2026-10-12 06:42Z | 38212930001 | `staging-delivery-e1e2a0b…` 11732495432, `staging-credential-probe-85854bb…` 11730217206; 2027-01-10 | `skip` (verified 06:54:25Z) | **0** (Railway: 0 records since 10-11 16:31Z) |
| #107-#112 | | | already committed in the production-deletion, R2-images and collector-v1 S1/S3 handoffs | | 0 each (those handoffs) |
| #113 collector-v1 S3 handoff | `b3862e6` 11:08:22Z | 38386604468 | `staging-delivery-b3862e6…` 11808980140, `staging-credential-probe-6c2e166…` 11807090882; 2027-01-11 | `skip` (verified 11:20:20Z) | **0** (`deploy-records-after-pr113.json`) |
| **#115** provenance tooling | `f1d9267` 15:07:29Z | 38416755490 | `staging-delivery-f1d9267…` 11826737626, `staging-credential-probe-b8a592a…` 11823888432; 2027-01-11 | `full` (scripts + docs), API `skip` on `5d86629`, revision `3b7d9c1a5e20` (verified 15:19:30Z) | **0** (no rollout file; Railway records, end check) |
| **#116** enqueue tool | `6e4079a` 15:33:24Z | 38420530144 | `staging-delivery-6e4079a…` 11829160566, `staging-credential-probe-25670f5…` 11825873439; 2027-01-11 | `full` (scripts + API test file), API `build` at `6e4079a` (expected), revision `3b7d9c1a5e20` (verified 15:56:14Z); delivery state 2 blockers | **0** (no rollout file; Railway: 0 records since 10-11 16:31Z at 16:10Z, `fleet-vs-receipt-end.json`) | | | | |
| This handoff | see PR | | **PENDING: session 13 downloads it first** | expected `skip` | expected 0 |

All receipts are under `evidence/pr<N>-delivery/`.

## 9. End-of-session state

`CURRENT_STATE-end.yaml` (16:10:40Z), `evidence/staging-state-f71ff96a20a70bd0.json`.
- **2 blockers:** `freshness-deadline-deficit` (§6: all 69 items are blocked work) and `snkrdunk-identity-quarantine` (23). The provenance false alarm is gone.
- All 10 collectors are still on `a504e47` with 0 deployment records (`live-state-end.json`, `fleet-vs-receipt-end.json`).
- API and market-index-snapshot are at `6e4079a`, the PR #116 build.
- `docs/agent/CURRENT_STATE.yaml` and `docs/agent/evidence/` are unchanged by this docs-only PR; CI regenerates them as run artifacts.

## Quiet windows

| Window | Status |
|---|---|
| 02:00-06:00Z | No collector change, ever |
| Collector releases | 06:00-23:00Z only, one collector per safe slot, via the CI delivery path |
| 19:30-20:30Z | No API or migration merge (daily snapshot and receipt about 20:00-20:05Z) |
| `a504e47` trigger window | **Closed** (verified) |
| NEW50 | Intents 3678-3727 due from 2026-10-13 16:06Z, claimed by ordinary Yuyu turns. Do not trigger, replay or re-enqueue. A rerun of the tool with the same list is a no-op |
| Collector-v1 S2 (#114) and fonts | Waiting for this report; then fonts first, S2 rebased onto it. Staging delivery stays serialized |

## Session 13 must verify

1. **Download this handoff PR's receipt first** into `evidence/pr<N>-delivery/`. Expect scope `skip` and 0 collector deployments.
2. **NEW50 natural evidence** (work ids 3678-3727), from ordinary turns only:
   - attempts and outcomes (`completed` vs `identity_refusal`, `transient_failure`);
   - request cost per capture (expected about 58);
   - RAW bytes per capture vs the 65.2 MB estimate and the 429.1 MB hard bound;
   - volume growth vs 21.78 / 25.86 MB/day;
   - 0 denials;
   - 0 mapping or proposal decisions written by captures;
   - Yuyu refresh freshness unchanged (0 actionable over 24 h).
   - Rollback triggers are in `new50-amber-preflight.json`. Then re-evaluate the remaining 50 (owner basis, §3).
3. **Lossless** from ledger id 53968 (floor exclusive 53967).
4. **Provenance**: after the next docs or web merge, the delivery state must show no `deployment-provenance-divergence`. It must reappear only for a real divergence.
5. **Owner answers**: NEW100 basis (§3), and the reporting fix for §5/§6 (blocked work vs deadline misses).
6. **Never replay:**
   - SNKR 3676/3677
   - RAW recovery 35175
   - Yuyu canary evidence
   - completed deliveries PR77-116 and this handoff PR
   - the NEW50 enqueue (list `906482e8…`): never re-applied with a different list for the same candidates

**PSA10:** NOT READY, not activated.
