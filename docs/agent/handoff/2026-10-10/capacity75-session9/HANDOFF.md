# Capacity / RAW75: session 9 handoff (2026-10-10)

STAGING ONLY. Production RED, untouched. PSA10 OFF.
- No source job was triggered manually.
- No mapping approval, no NEW100, no SNKRDUNK discovery.
- No schedule, budget, pacing or freshness change.
- No RAW evidence deleted, no collector image changed.

Numbers are **MEASURED** (source under `evidence/`, read-only tools in `tools/`) unless marked
CARRIED FORWARD or ESTIMATE. The session ran 22:10-~22:50Z, which left 50 minutes of the
06:00-23:00Z change window.

## 0. Start gate (22:11Z, `evidence/live-state-start.json`)

- All 10 collectors are SUCCESS on their verified a852244 deployments and image digests, with the
  exact-commit marker.
- cron, start command and daily-v1 are unchanged.
- **0 deployments since PR #98.** The only records are 10 `SKIPPED` entries at 15:29Z: Railway's
  GitHub integration evaluating the PR #99 docs merge, with no build and no active-deployment
  change.
- State regenerated at 22:22:51Z (`CURRENT_STATE-start.yaml`). The 3 blockers are unchanged.

## 1. Request savings: HELD (a852244, 14:31Z → 22:13Z)

`evidence/requests-after-a852244-2215.json`, `natural-turns-a852244-2215.json`,
`price-continuity-a852244-2215.json`, `window-series-2215.txt`.

| | Before (24h to 09:00Z, CARRIED FORWARD s8) | After, a852244 (MEASURED) |
|---|---|---|
| Yuyu requests per capture | 55.3 | **31.5** mean, p50 29 (n=356, all `captured`, min 29, max 56) |
| Yuyu peak per 1800 s window | 8,458 / 9,000 (94.0%) | **2,419 / 9,000 (26.9%)**, window average 1,403 |
| Yuyu turn-browser warm-ups | n/a | 36 warm-ups (cost ≥ 45) in 36 turns with work, so **0 mid-turn discards** (cost proxy) |
| SNKR requests per attempt | 160.3 | **88.6** (n=127: captured 85.6 ×7, no_listing 89.0 ×120) |
| SNKR homepage RAW | 287 a day, 18.92 MB | **7 in 7 turns with work**, 466,789 bytes stored. 1 per turn |
| SNKR peak per 1800 s window | 2,958 / 3,100 | 2,855 in the first window, then 1,112, 582, 2,808, 1,808, 427, 1,692 (average 1,612) |

- **Price continuity:** 366 of 366 observations have a previous one, and all 366 have identical
  price, stock and promotion.
- **Natural turns:** 154 completed runs on a852244 across the 10 collectors: Yuyu 350 attempts,
  SNKR 127.
  - 0 failures;
  - 0 denials/403/429/challenges;
  - 0 optional_resource;
  - 0 safety faults (expired claims, reservation overruns, duplicate requests, wrong shard);
  - 0 attempts over their reservation.
- **The SNKR backlog drained by 17:32Z.**
  - Since 18:00Z every SNKR turn reports `due=66, selected=0`.
  - All 89 due SNKR items are `state=blocked`: 43 identity_refusal, 22 coverage, 23 quarantined
    validation and 1 source_denial. These are the known blockers.
  - The budget row is open (`used 0`, not paused). This is expected behaviour, not a stall.
  - Ordinary refreshes come due again about 23h after their 14:30-17:30Z checks. The **full-24h
    SNKR figures** (requests per attempt, homepage rows per day, and the steady-state window peak
    once the backlog has drained) therefore complete at about **2026-10-11 14:31Z**. Session 10
    re-measures.

## 2. Auto-deploy hole: CLOSED for the 10 collectors

**Mechanism (MEASURED, read-only, `evidence/autodeploy-status-before.json`):**
- Each collector, plus the API and the worker, had one Railway `DeploymentTrigger`: provider
  github, `Insomniac79ac/optcg-price-tracker`, branch `staging`, checkSuites false.
- Together with the service's watch patterns, that trigger is what built PR #96 on every
  collector at once.
- The Yuyu shards report `source: null` and `serviceInstanceAutoDeployStatus.canEnable=false`
  (`NO_REPO`). Their trigger fired anyway.
- The never-used parent `yuyutei-collector` was already in the target state: auto-deploy disabled
  and no trigger.

**Docs (checked 2026-10-10):**
- https://docs.railway.com/guides/github-autodeploys, "Disable automatic deployments".
- The public GraphQL schema: `serviceInstanceAutoDeployUpdate(input:{enabled:false})` ("Enables or
  disables auto-deploy for a service instance"). Rollback is
  `deploymentTriggerCreate(provider, repository, branch, checkSuites)`.

**Change (AMBER, `tools/autodeploy_disable.py`, `evidence/autodeploy-disable-*.json`):**
- Steps, applied one collector at a time:
  1. Run inside 06:00-23:00Z.
  2. Wait for the collector's own safe slot (`deploy_staging_collectors.wait_for_slot`: ≥ 5 min
     after a fire, ≥ 8 min before the next, and no open attempt).
  3. Check that the active deployment and digest are the verified a852244 ones and that the
     staged-changes patch is empty.
  4. Call the documented mutation.
  5. Wait 60 s, then re-check.
- **Every check passed on every collector:**
  - no trigger;
  - auto-deploy disabled;
  - **no new deployment record**;
  - the same active deployment and verified digest;
  - cron and start command unchanged;
  - an empty staged-changes patch;
  - variables unchanged (daily-v1).
- No image was built, redeployed or replaced, so no reuse-image redeploy was needed.
- Order: shard-0 canary at 22:16:34Z, then shards 1-8, then SNKR. Completion: see §2a.
- **Rollback:** `autodeploy_disable.py <name> <out> --restore` recreates the recorded trigger.
- **Not changed:**
  - **API** (`optcg-price-tracker`) and **worker** keep their GitHub triggers. The API is
    *delivered* by its GitHub build: `verify_staging_delivery.decide_api` requires a build for
    watched changes and a SKIPPED record otherwise. Removing its trigger would break API delivery.
  - The API's exposure, building on a merge to `services/api/**`, is the designed delivery path.
    It is serialized by the delivery concurrency group and verified. It is not the parallel
    collector problem.
- **Kept:** the merge-poll retry fix (PR #97/#98). No failed delivery job was re-run.
- **Regression / test merge:** this handoff PR is docs-only. Before this change, every merge left
  one SKIPPED record per collector. After its merge, each collector must show **0 new deployment
  records** of any status. Session 10 must record the result if this session's report has not
  (§2a).

## 2a. Auto-deploy change result and lossless (MEASURED)

**Rollout.** All 10 collectors went through one at a time, 22:16:34 → 22:33:37Z. Each was
`DISABLED`, with every check true (`evidence/autodeploy-disable-*.json`). Order: shard-0 (canary),
then 1, 2, 3, 4-v2, 5, 6, 7, 8, then SNKR.

**After-state** (`evidence/autodeploy-status-after.json`):
- All 10 collectors: auto-deploy `enabled:false`, 0 triggers.
- Still GitHub-triggered by design: the API (`optcg-price-tracker`), worker, beat and
  market-index-snapshot. These are not collectors; their delivery and verification depend on
  their GitHub builds.
- **Independent recheck at 22:33:46Z** (`evidence/live-after-autodeploy.json`):
  - all 10 SUCCESS on the verified a852244 deployments and digests, with the marker;
  - cron, start command and daily-v1 unchanged;
  - **0 deployment records** since the PR #99 SKIPPED records (15:29Z).

**Lossless:** `evidence/verify-lossless-final.json` re-verified every daily-v1 ledger row
(ids 37712 onward, including every row > 44518). **6,952 rows, ids 37712-45208, all lossless: 0 failures, 0 expanded.** SNKR 1,357 rows (1,147 at session 8, so +210 SNKR rows on encode-before-insert code); Yuyu 5,595. 0 database writes, 0 source requests.

**Test merge:** this PR. Its merge happens after this file is written. Expected: 0 new deployment records of any status on all 10 collectors (before this change, each merge added one SKIPPED record per collector). The session-9 report records the observed result; session 10 re-checks with `tools/live_now.py <merge time>`.

## 3. Storage

**Resize: NOT DONE. The approval is recorded and the procedure is ready (`RESIZE_PREFLIGHT.md`).**
- Railway exposes no API for volume size. Live Resize is dashboard-only.
- The newest Postgres backup is 10 days old (2026-09-30), and no backup schedule exists.
- The session had under 40 minutes of the change window left, overlapping the collector
  trigger change.
- An irreversible step was not rushed.

| | MEASURED | Source |
|---|---|---|
| Volume | 3,641.4 MB of 10,000 MB at 22:00Z (hourly) | `evidence/volume-series-26h.json` |
| 24h growth, 10-09 22:00 → 10-10 22:00Z | 3,607.9 → 3,641.4 = **+33.5 MB/day** (includes the 02-06Z busy window and pre-a852244 hours) | same |
| Since a852244, 14:00 → 22:00Z | +4.9 MB in 8h ≈ 14.7 MB/day (short window, no busy window yet) | same |
| Database | 2,794,206,911 bytes | `evidence/storage-2220.json` |
| `raw_snapshots.n_tup_upd` | **5,924**, unchanged since 09:00Z, so still 0 plaintext row versions | same |
| Daily-v1 ledger | 2,893 rows / 14.3 MB today, max id 45208 | same |

**Runway** (room to the 3 GiB reserve = 10,000 − 3,221 − 3,641.4 = **3,137.6 MB**):

| Rate | MB/day | Days | Reserve reached |
|---|---|---|---|
| Worst case (s7, CARRIED FORWARD) | 116.7 | 27 | ≈ 2026-11-06 |
| Session-8 steady (CARRIED FORWARD) | 47.9 | 65 | ≈ 2026-12-14 |
| **24h measured now** | **33.5** | **94** | **≈ 2027-01-12** |
| After the 20 GB resize (ESTIMATE) | 33.5 | ≈ 392 | 2027-11 |

**Storage (c) proposal-digest:** design and AMBER preflight in `PROPOSAL_DIGEST_PREFLIGHT.md`.
- Yuyu wrote 2,164 versions in 24h. Only 47 changed real evidence, and `candidate_id` was stable in
  all of them. Expected after the fix: about 47 a day.
- Main risk: 298 approved-exact groups carry digest-bound physical-artwork proofs.

**Lossless:** see §2a.

## 4. NEW100: NOT APPROVED

The prerequisites have not settled:
- the SNKR 24h on a852244 is incomplete;
- the resize is not done.

The storage guard fails on its own.

| Guard | Result |
|---|---|
| Storage headroom | **FAIL.** NEW100 needs 4.3-8.8 GB on a 90-day basis (CARRIED FORWARD s7), plus the 887 MB image bound. Room to the reserve is 3,137.6 MB (MEASURED). It passes only after the 20 GB resize |
| 23h/24h request feasibility | Pass on paper. (2,616 + 100) × 31.5 ≈ 85.6k requests a day against a 432k-a-day Yuyu budget (9,000 per 1,800 s), and the peak window is 26.9% (ESTIMATE from MEASURED rates) |
| Measured source capacity | 0 denials in 154 natural runs (MEASURED). A 24h Yuyu window on the new code completes 10-11 ~18:30Z |
| Exact CardPrint identity / no duplicate active Yuyu mapping / authoritative release_product_id / shard distribution | **Not evaluated**: the storage guard already fails. Duplicate active exact-print groups = 0 (state, 22:22Z) |

## 5. Deliveries this session

- **No collector release.** The collectors are unchanged on a852244.
- The handoff PR is docs-only (delivery scope skip, no rollout requested). See §2a for CI, merge,
  receipt and the test-merge result.

## 6. Freshness, due work, coverage (state 22:22Z, `CURRENT_STATE-start.yaml`)

- **Freshness:** deadline compliance `not_met`, sustained compliance unknown.
  - Yuyu: 2,619 mappings; 1 never checked; 2 checks older than 24h.
  - SNKR: 353; 22 never checked; 44 older than 24h (blocked/quarantined); 278 no_listing.
- **Due now (22:12Z):**
  - Yuyu 54, and 527 within 3h, which is normal turnover.
  - SNKR 89, all blocked.
- **Coverage:**
  - 2,635 of 4,316 canonical variants (61.05%) have one or more sources;
  - 334 have both;
  - 0 duplicate active exact-print groups.
- **Market Value receipts:** 12, the latest for 2026-10-10 completed 20:04:06Z. 0 rows on 09-27/28.

## Quiet windows

| Window | Status |
|---|---|
| 02:00-06:00Z (busy) | No collector change, no resize |
| 2026-10-11 ~14:31Z | SNKR full 24h on a852244 completes. Measure before any SNKR-affecting release |
| Resize | Run at a time with no collector release or post-release observation (for example 06:30-09:00Z), after a fresh backup |
| Storage (c) release | Only after the SNKR 24h figure is recorded and the test-merge result is confirmed. Then one natural discovery turn per shard |

## Session 10 must verify

1. **Test merge:** 0 new collector deployment records (not even SKIPPED) since this PR's merge,
   unless §2a already records it.
2. **SNKR 24h on a852244**, by ~10-11 14:31Z:
   - requests per attempt (≈ 88);
   - homepage RAW per day;
   - the window peak once refreshes come due again.
3. **Resize** per `RESIZE_PREFLIGHT.md`: fresh backup → Live Resize (dashboard) → verify.
4. **Storage (c)** release per `PROPOSAL_DIGEST_PREFLIGHT.md`, with the 298-proof guard.
5. Then **NEW100** re-evaluation against the full guard table.
6. The 24h volume growth again, including a busy window on a852244.
7. **Durable fix:** add a preflight in `deploy_staging_collectors.py` (or the state generator)
   that refuses when any collector has a GitHub deployment trigger, so a re-enabled trigger is
   caught.

**Never replay:**
- SNKR 3676/3677
- RAW recovery 35175
- Yuyu canary evidence
- completed deliveries PR77-99

**PSA10:** NOT READY, not activated.
