# Capacity / RAW75: session 13 handoff (2026-10-15)

STAGING ONLY. Production RED, untouched. PSA10 OFF.
- No source job was triggered manually. 0 source requests by this session.
- No collector release, rollback or setting change: **0 collector deployments** all session.
- No mapping approval, no proposal review, no SNKRDUNK discovery.
- No schedule, budget, pacing, freshness-target or threshold change. No RAW evidence deleted.
- No resize, no infrastructure change.
- **0 database writes.** Every read used `default_transaction_read_only=on`.
  - The remaining-50 enqueue was not applied (§2).
  - The Yuyu duplicate close was not applied (§4).

The session started 03:47Z and was resumed at 03:55Z. All numbers are **MEASURED** (source under
`evidence/`, read-only tools in `tools/`) unless marked CARRIED FORWARD (CF) or ESTIMATE.

## 0. Start gate (03:47-04:00Z)

| Check | Result | Evidence |
|---|---|---|
| Disk | 5.6 GB free at 03:47Z (≥ 5 GB) | session log |
| Delivery running | None; no PR open | `gh pr list`, `gh run list` |
| All 10 collectors on `a504e47` | **Yes.** Exact-commit marker, SUCCESS; cron, start command and daily-v1 variables unchanged. **Active deployment and digest equal the PR #103 receipt on all 10, with 0 deployment records since the 2026-10-11 16:31:08Z rollout** | `live-state-start.json` (03:49:48Z), `fleet-vs-receipt-start.json` (03:57:46Z) |
| GitHub triggers | None on any collector; auto-deploy disabled on all 10 | `trigger-status-start.json` |
| Backup | Daily `4654fa96…` 2026-10-14 09:22Z (18.5 h old); schedule `22 9 * * *`, 6-day retention | `backups-start.json` |
| State | `CURRENT_STATE-start.yaml` (03:58:28Z): **3 blockers** (session 12: 2): `freshness-deadline-deficit`, `snkrdunk-identity-quarantine` (23), **`official-images-check-failed`** (new, §8) | `evidence/staging-state-137d6f4f28b9f9a3.json` |
| Receipts | PRs #117, #118, #122, #123, #124 downloaded (§9) | `evidence/pr<N>-delivery/` |

## 1. NEW50 natural evidence (work ids 3678-3727)

`evidence/new50-evidence.json` (04:00:56Z). These are ordinary scheduled Yuyu turns only; nothing was triggered.

| Measure | MEASURED |
|---|---|
| Outcomes | **50/50 `completed`** in one attempt each; 0 `identity_refusal`, 0 `transient_failure`, 0 blocked |
| When | 2026-10-13 16:11:42Z to 16:23:28Z (12 min), on shards due-3 (16), due-4 (16), due-5 (14) and due-6 (4) |
| Requests per capture | **avg 58.92**, min 58, max 60; total 2,946 (estimate was about 58); 0 over the 100 reservation |
| Identity | 50/50 cursor `identity_status: "unresolved; retained artwork evidence only"`. **No auto-approval.** Since the enqueue: **0 proposal reviews, 0 approved groups created, 0 mappings created or updated** |
| After capture | All 50 parked (`next_due_at` 2126), so they add **no recurring requests or storage** while unmapped |
| RAW written | 202 snapshots (50 product pages, 50 Yuyu images, 102 official images), all HTTP 200, none referenced by any other work row |
| Stored bytes (`pg_column_size`) | product HTML 1,865,902; Yuyu images 29,017,408; official images 29,561,452. **Total 60.44 MB (1.21 MB per capture)**, vs 65.2 MB estimate and 429.1 MB hard bound |
| Volume step | **+66.5 MB (s9)** from 16:05Z to 16:30Z on 10-13 (`volume-series-5min.json`): physical/stored = 1.10 |
| Denials | Yuyu since the enqueue: **0** 403/429/challenge/denial failures; all 5,049 RAW fetches HTTP 200; outcomes 127 discovery `completed` and 4,643 refresh `captured`, nothing else |
| Freshness | 0 actionable items over 24 h. Non-blocked max age: Yuyu 23.9 h (2,616 items), SNKR 21.5 h (287 items) (`freshness-detail.json`) |
| Coverage | operational **2,630 (change from 2,630: 0)**; mapped 2,635; fresh usable 2,398; both 334; zero 1,681; duplicate exact-print groups 0 (`coverage-start.json`, 04:13:28Z). Expected: captures never approve |

**Rollback triggers** (`new50-amber-preflight.json`, s12): none fired. 0 denials; 0 of a maximum 5 transient
failures; 0 decisions; 66.5 MB against the 429.1 MB bound; no freshness regression.

## 2. Remaining 50: NOT ENQUEUED (fails the strict rule at the as-observed stress rate)

**Re-plan on current digests** (`new100-replan.json`, 04:03:27Z, read-only, resolver 1.3):
- **all 50 remaining candidates eligible, every guard PASS**: identity, bounded siblings, authoritative release, no active mapping, no reviewed decision, no capture scope, no shared print;
- the 50 ineligible are exactly the NEW50 candidates (`no_prior_capture_scope`), as expected;
- candidate 196 (OP13-083) has a new digest since 10-13 15:57Z with unchanged siblings. It is still eligible and must be enqueued with its live digest;
- remaining-50 images: 50 Yuyu + **115 official** (NEW50 had 102).

**One-off from NEW50's measured costs** (`remaining50-fit.json`):
- per stored unit: page 37,318 B, Yuyu image 580,348 B, official image 289,818 B;
- remaining 50: 64.21 MB stored × 1.10 = **70.6 MB (s9)**, vs the old hard bound of about 429 MB;
- recurring 0 while parked; the s12 allowance of 0.45 MB/day is kept.

**Base rates** (`storage-rates-ex-new50.json`; current code since the a852244 rollout, 109.4 h, 1,314 samples).
The NEW50 one-off is removed from the base, because otherwise it would be charged again for every day of the horizon.
The unadjusted figures are in `storage-rates-current-code.json`: planning 37.68 and stress 109.26 MB/day, both inflated by NEW50.

| Rate | MB/day | 90-day need with the remaining 50 | Margin (room 2,970.3 MB) | Margin with no batch |
|---|---|---|---|---|
| Planning (average) | **23.10** | 2,190.1 | **+780.2 fits** | +891.3 |
| Stress A, as observed (worst rolling 24 h, from 10-13 04:50Z) | **42.79** | 3,962.2 | **−991.9 does not fit** | **−880.8** |
| Stress B, transient excluded (worst from 10-14 03:50Z) | **26.41** | 2,488.0 | **+482.3 fits** | +593.4 |

**Why A and B differ: a transient.** On 2026-10-14 the volume rose **+17.7 MB at 04:05-04:15Z**, held, and fell **−16.9 MB at
05:05-05:15Z** (net normal growth). Cause unknown (Railway disk metric; likely temporary files or vacuum). Every rolling-24 h
window ending inside that hour carries it, so stress A is not net growth.
- Even with **no batch**, stress A gives only 69.4 days of runway, under the 90-day horizon.
- Stress B (26.41) is close to s12's 25.86 and to the last 24 h (26.32).

**Verdict: NOT ENQUEUED.** The owner's rule is "fit at BOTH rates". Excluding the transient is my judgment, not an
owner-defined rule, so I did not use it to pass the gate. The remaining 50 fits at planning and at stress B by +482 MB.
**Owner answer (a), 2026-10-15:** keep "days since the 10 October collector release". Exclude the spike only if
evidence shows its cause was not collection; enqueue nothing until confirmed.

**Spike cause** (`evidence/spike-2026-10-14-04z-cause.json`, read-only): **not collection (shown).**
- Collection wrote **0.79 MB** of RAW in the 04Z hour (neighbouring hours 0.46-0.93 MB).
- All 10 collectors ran their ordinary 3 executions in that hour, exactly like every other hour.
- The spike is the **only** volume fall in 1,314 samples and the only rise above 3.3 MB outside NEW50. A collection cause would recur hourly or daily.
- Also excluded:
  - backup (dailies 09:22Z);
  - deployments (0 on 20 services, 03:30-05:30Z);
  - the image mirror (did not exist until 10-15 02:15Z);
  - agent sessions (no tool calls 03:50-05:20Z);
  - `raw_snapshots` vacuum (last 10-13 19:24Z).
- **Positive cause unidentified.** It is most likely Postgres-internal: temporary files, WAL or a vacuum of another table.
  The `pg_stat` timestamps keep only the latest run, and `temp_bytes` has no timestamps.

**Recomputed (stress B):** 26.41 MB/day; the remaining 50 fits with **+482.3 MB** (planning +780.2).
**Held: nothing enqueued, awaiting owner confirmation.**

## 3. Quarantine reporting fix (owner decision 2): PR #125

**State tooling only, GREEN.**
- New `scripts/quarantine_reporting.py`, used by `generate_staging_state.py` and therefore `check_raw_health.py`.
- The shared aggregate and its SQL (`app/services/operational_health*.py`) are **collector runtime inputs and were not
  touched**. `collector_runtime_inputs.py` reports **0 changed runtime inputs** for both collectors, so no collector release.

What it does:
- Blocked items are listed with the same `ELIGIBLE` population as `DUE_SQL`, in the same read-only transaction. They are removed from
  due/overdue/never-checked/over-24 h/deadline-misses.
- Run summaries lose only items blocked since before that run started and already overdue at its start, so a real miss is
  never hidden.
- **Always visible:** `quarantine` per source and in `raw_due_work` (count, overdue, never checked, oldest blocked-since and
  age, oldest successful-check age; zero/null when empty), `freshness.by_source.<s>.quarantine`, and a
  `quarantined-refresh-work` blocker (count, oldest blocked-since).
- `freshness-deadline-deficit` follows actionable work only.
- **Fail closed:** older evidence or an inconsistent list excludes nothing.
- No threshold, target, budget or guard changed.

| Evidence | Result |
|---|---|
| Live from the branch (04:18Z) | SNKR **DEGRADED → HEALTHY**, `raw_due_work` **DEGRADED → HEALTHY**, compliance `not_met` → unknown (instant only). Quarantine shown: SNKR 66 (66 overdue, 22 never checked), oldest blocked since **2026-10-02 15:54Z (300.4 h)**; freshness quarantine 69 (SNKR 66, Yuyu 3). Blockers: `freshness-deadline-deficit` gone, `quarantined-refresh-work` (69) added |
| Tests | `test_quarantine_reporting.py` **16 passed**: quarantined not overdue; **real overdue still fails** (DEGRADED, `due_work_deficit`, `not_met`, deficit blocker); count and oldest age shown, also when zero; runs keep items blocked after they started or not yet overdue; inconsistent/absent list excludes nothing. `scripts/tests` 232 passed before the new file |
| Delivery | **Merged `eae22a7` 06:14:56Z**, CI run 38689997328, scope `full`, API `skip` (on `e80ce63`), revision `3b7d9c1a5e20`, verified 06:26:25Z; **0 collector deployments** (no rollout file; `fleet-vs-receipt-end.json` 06:28Z) |
| CI note | The first draft run (04:21Z) failed on one unrelated web test, `cards/[id]/page.test.tsx` "F. an admin still gets the admin panel". It asserts the fetch mock right after the heading appears, which is a timing race, and this PR changes no web code. The `ready_for_review` run passed every job. **Flaky test; product-lane follow-up** |

## 4. Yuyu duplicates (owner decision 3): evidence complete, close NOT applied

`evidence/yuyu-duplicates-evidence.json` (read-only). **All 3 qualify.** Each is a blocked work row on an inactive mapping,
and each duplicates exactly one active, approved, unsuperseded, manual-verified exact mapping on the same print and source.
That active mapping is fresh:

| Work | Card | Inactive mapping (listing) | Active exact mapping (listing), work, last check age | Rows a close removes |
|---|---|---|---|---|
| 2628 | OP16-118 (print 3841) | 2893 (`op16:10145`) | **1944** (`op16:10146`), work 1589, 5.3 h | work 1, attempts 1, price states 1 |
| 2629 | OP16-119 (print 3842) | 2894 (`op16:10147`) | **1945** (`op16:10148`), work 1590, 4.8 h | work 1, attempts 1, price states 1 |
| 2630 | OP09-077 (print 4886) | 2895 (`op09:10160`) | **1437** (`op09:10097`), work 1082, 21.0 h | work 1, attempts 0, price states 1 |

**Why not applied:**
- `freshness_work.state` allows only `pending`, `claimed` or `blocked` (`ck_freshness_work_state`), so there is no closed state.
- Nothing in the codebase retires work rows.
- "Close" can therefore only be a **row delete**, which cascades (`ON DELETE CASCADE`) to 2 attempt records and 3 price-state rows.
  RAW snapshots and price observations would stay.
- The decision approved "close", not deletion of attempt history.
- With §3 merged these 3 rows are already outside deadline compliance, reported as quarantine, so nothing is hidden or
  overdue in the meantime.

**Before/after counts:** blocked refresh work 69 / 69 (unchanged); Yuyu refresh work on inactive mappings 3 / 3.

**Rollback note** (if a delete is approved): the export holds every row (`to_jsonb`) of the work row, its attempts and its
price states. A rollback re-inserts them with the same ids, inside one transaction. The active mappings are never touched.

**Owner answer (b), 2026-10-15:** do not delete rows or attempt history; **leave them**. Follow-up proposal (not built):
`PROPOSAL-freshness-work-closed-state.md` covers an additive `closed` state.
- Migration plus close fields.
- Planners skip closed rows: `claim_due` selects `pending` only, and `_upsert_work` is `ON CONFLICT DO NOTHING`.
- A guarded close tool with rollback.
- Release impact: 0 collector deployments if the runtime modules are not edited.

## 5. Storage

| | MEASURED |
|---|---|
| Volume (Railway `DISK_USAGE_GB`, s9 basis) | **3,808.4 MB** at 04:00Z (s12: 3,702.2); room to the 3 GiB reserve **2,970.3 MB** |
| Of which NEW50 | +66.5 MB (one-off, §1) |
| Database (`pg_database_size`, 04:23Z) | 2,950,895,295 B (**2,950.9 MB**, +101.7 MB since s12). `raw_snapshots` 2,718.6 MB (92%), `market_index_snapshots` 41.8 MB, proposal groups 64.1 MB, alternatives 16.4 MB, `freshness_attempts` 23.8 MB, `app_log_events` 20.6 MB, `price_observations` 18.0 MB (`db-size-end.txt`) |
| Growth without the NEW50 one-off | planning **23.10**, stress A **42.79** / stress B **26.41** MB/day; last 24 h 26.32 |
| Runway, no further batch | **128.6 days** planning; 69.4 (A) / 112.5 (B) days stress |
| Runway with the remaining 50 | 123.1 planning; 67.1 (A) / 108.0 (B) days (ESTIMATE from MEASURED) |
| 30 / 90-day projection (planning) | +693 / +2,079 MB (ESTIMATE) |

## 6. Lossless

`evidence/verify-lossless-from-53968.json`: every daily-v1 ledger row from 53968 to **59328**.
- 4,944 rows (Yuyu 4,632, SNKR 312);
- original 1,127.7 MB → encoded 12.3 MB;
- **0 failures, 0 expanded, `all_lossless: true`**; 0 writes, 0 source requests.
- Next floor (exclusive): **59328**.

## 7. Degraded signals and freshness

Before PR #125 (`degraded-signals.json`, 04:01Z): `snkrdunk` DEGRADED (`deadline_misses`, `due_work_deficit`,
`never_checked`), `yuyu` HEALTHY, `raw_due_work` DEGRADED.
- **Every** overdue item is blocked: SNKR 66 blocked (22 never checked, 44 over 24 h); SNKR pending 287 and Yuyu 2,616, 0 overdue.
- The 69 freshness `not_met` items are SNKR 66 plus Yuyu 3 (§4). 0 actionable.
- After PR #125, see §3 and the end state (§10).

## 8. Official-images mirror (not this lane; recorded only)

The `official-images-mirror` service exists (owner-created; schedule `15 7 * * *`).
- Its only deployment, `bd651b0c`, created **2026-10-15 02:15:00Z** at `e80ce63`, is **FAILED at build**: `railpack prepare exited with an error`.
- Railpack found no app at the repository root (`evidence/official-images-mirror-build-bd651b0c.log`).
- **Cause (read-only service settings comparison):** `official-images-mirror` has **`dockerfilePath: null`**. Railway
  therefore falls back to Railpack auto-detection. Railpack finds no app at the root: the context is filtered by `.dockerignore`
  to `packages/` and `services/`, and there is no `start.sh`.
- `market-index-snapshot`, which runs on the same API image, has `dockerfilePath: deploy/railway/api.Dockerfile` and root `/`.
- **Fix: a Railway service setting, not a repo change.** No PR.
  - Set the Dockerfile path to `deploy/railway/api.Dockerfile`, with root directory `/`, as on `market-index-snapshot`.
  - Set the restart policy to **`NEVER`**: it is `ON_FAILURE` now, but `docs/official_images.md` requires `NEVER`, so a failed run must not retry against Bandai.
  - Optional parity: `APP_ENV=staging` (unset, it falls back to "development"; the mirror does not read it).
  - Then redeploy once inside 06:00-23:00Z, not 19:30-20:30Z. The watch patterns already match the API image.
- With no successful deployment, the 07:15Z cron is not expected to run. The state blocker `official-images-check-failed` stays until a run succeeds.
- **Owner/product-lane action.** Per the owner, I did not change the service or retry the build. First run: **not happened at handoff (06:30Z)**; the 07:15Z cron is listed for session 14.

## 9. Deliveries and receipts

| PR | Merge | CI run | Artifacts (id; expire) | Scope | Collector deployments |
|---|---|---|---|---|---|
| #117 self-host fonts | `66cc7f2` 2026-10-13 | 38432821718 | `staging-delivery-66cc7f2…` 11834065802, `staging-credential-probe-572d2cf…` 11832276428; 2027-01-11 | `full`, API `skip` (verified 17:11:45Z) | **0** (no rollout file) |
| #118 session-12 handoff | `36ff37c` 2026-10-13 | 38428539757 | `staging-delivery-36ff37c…` 11830977935, `staging-credential-probe-6672d2b…` 11829243316; 2027-01-11 | `skip`, API `skip` | **0** |
| #119-#121 | | | already committed in the official-images and collector-v1 S4 handoffs | | 0 each |
| #122 official images follow-up record | `a196648` 2026-10-14 | 38551545019 | `staging-delivery-a196648…`, `staging-credential-probe-37a3d1e…` | `skip`, API `skip` | **0** |
| #123 collector-v1 S4 record | `98d2acf` 2026-10-14 | 38564068937 | `staging-delivery-98d2acf…`, `staging-credential-probe-f0ad87f…` | `skip`, API `skip` | **0** |
| #124 collector-v1 S5 | `e80ce63` 2026-10-14 14:44Z | 38580931280 | `staging-delivery-e80ce63…`, `staging-credential-probe-6fbaf42…` | `full`, API `build` at `e80ce63` | **0** |
| **#125** quarantine reporting | `eae22a7` 2026-10-15 06:14:56Z | 38689997328 | `staging-delivery-eae22a7…` 11952876935, `staging-credential-probe-3d29d6a…` 11952207313; 2027-01-13 | `full`, API `skip` on `e80ce63` (verified 06:26:25Z) | **0** | | | | |
| This handoff | see PR | | **PENDING: session 14 downloads it first** | expected `skip` | expected 0 |

Collector deployments: 0 records on all 10 collectors since 2026-10-11 16:31:08Z (`fleet-vs-receipt-start.json`;
end check `fleet-vs-receipt-end.json`).

## 10. End-of-session state

`CURRENT_STATE-end.yaml` (06:28:42Z, head `eae22a7`), `evidence/staging-state-d95753e633842f3d.json`.
- **3 blockers:**
  - `snkrdunk-identity-quarantine` (23);
  - **`quarantined-refresh-work` (69, oldest blocked since 2026-10-02 15:54Z)**;
  - `official-images-check-failed` (§8).
- `freshness-deadline-deficit` is gone: 0 actionable misses.
- `operational_health`: yuyu **HEALTHY**, snkrdunk **HEALTHY** (quarantine 66 shown separately), `raw_due_work` **HEALTHY**, deadline misses 0.
- **No `deployment-provenance-divergence`** after this non-collector merge: the session-12 provenance check is verified.
- All 10 collectors are still on `a504e47` with the PR #103 deployments and digests and 0 deployment records (`live-state-end.json`, `fleet-vs-receipt-end.json`).
- The delivery-job state at `eae22a7` agrees (`pr125-delivery/…/CURRENT_STATE.yaml`).

## Quiet windows

| Window | Status |
|---|---|
| 02:00-06:00Z | No collector change, ever |
| Collector releases | 06:00-23:00Z only, one collector per safe slot, via the CI delivery path |
| Merges | 06:00-23:00Z only; never 19:30-20:30Z (daily snapshot and receipt about 20:00-20:05Z) |
| Draft PRs | A non-draft PR to `staging` arms native auto-merge as soon as CI passes: open as draft outside the merge window |
| NEW50 | Complete (50/50). **Never replay or re-enqueue** work ids 3678-3727 or list `906482e8…` |
| Remaining 50 | Not enqueued; waits for Q1. Re-plan again before any apply (candidate 196 digest moved) |
| Official images | Owner/product lane; cron 07:15Z once the service builds |

## Session 14 must verify

1. **Download this handoff PR's receipt first** into `evidence/pr<N>-delivery/`. Expect scope `skip` and 0 collector deployments.
2. **Official-images-mirror first run** (07:15Z daily): not yet happened at handoff. Record whether the owner applied the setting fix (§8) and whether the run succeeded (the `official-images-check-failed` blocker clears only after a successful run).
3. **Owner follow-ups:**
   - Remaining 50: confirmation of the spike exclusion (§2). If confirmed: re-plan, dry run, enqueue with the PR #116 tool, AMBER.
   - Yuyu duplicates: left as they are; the `closed`-state proposal is a data-lane follow-up (§4).
4. **Quarantine reporting live:** state shows `quarantined-refresh-work` with the count and oldest time, and no `freshness-deadline-deficit` unless actionable work misses. A real miss must still raise it.
5. **Lossless** from ledger id 59329 (floor exclusive 59328).
6. **Storage:** the stress rate with and without the 10-14 04Z transient; volume vs 23.10 / 26.41 MB/day.
7. **Never replay:**
   - SNKR 3676/3677
   - RAW recovery 35175
   - Yuyu canary evidence
   - NEW50 work ids 3678-3727
   - completed deliveries PR77 onward, including #125 and this handoff PR

**PSA10:** NOT READY, not activated.
