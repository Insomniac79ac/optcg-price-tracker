# Capacity / RAW75: session 8 handoff (2026-10-10)

STAGING ONLY. Production RED, untouched. PSA10 OFF. No source job was triggered manually. No
mapping approval, no NEW100, no SNKRDUNK discovery. No schedule, budget, pacing or freshness
change. No RAW evidence deleted.

Numbers are **MEASURED** (source under `evidence/`, read-only tools in `tools/`) unless marked
CARRIED FORWARD or ESTIMATE.

## 0. Start state (07:51Z, `evidence/live-state-recheck.json`)

- An earlier, interrupted session-8 attempt (07:10–07:39Z) had opened PR #95, with auto-merge
  armed.
- All 10 collectors were on their activation deployments and digests, with daily-v1.
- PR #91's delivery was green with 0 rollout.
- The state was regenerated at 07:52Z. The 3 blockers are unchanged.

## 1. Delivery path: rollout made sequential (PR #95)

The delivery uploaded all ten collectors at once and had no automatic rollback. Auto-merge on
PR #95 was disarmed at ~07:50Z, before anything merged.

`deploy_staging_collectors.py` now does the following (see `STAGING_DELIVERY.md`):
- It proves every collector's rollback source before any upload.
- It starts a forward release only between 06:00 and 23:00 UTC.
- It uploads each collector in its own safe slot: at least 5 min after a fire, at least 8 min
  before the next, and with no open attempt.
- It verifies each collector before touching the next.
- It restores everything it touched, newest first, on any failure.

## 2. Storage (a): encode before the first INSERT. DELIVERED (PR #95, 05f099d)

- **Merged** at 08:17Z.
- **Rollout:** sequential, 08:18:11 → 08:39:52Z, with 0 retries
  (`evidence/pr95-delivery/`).
- **Delivery verification:** green at 08:59Z.
- **Natural turns:** one completed run per collector on 05f099d, with 0 failures, denials and
  safety faults (`evidence/natural-turns-05f099d-0903.json`).
- **No plaintext row version:** since the 08:04Z baseline, 90 encoded rows were written. The
  23 rows from already-released collectors produced **0 UPDATEs**. `raw_snapshots.n_tup_upd`
  grew by exactly 67, the number of rows written by not-yet-released collectors (insert then
  update) (`evidence/storage-baseline-prerelease.json`, `post-release-pr95-0900.json`).
- **Lossless:** all 5,878 encoded rows since activation (ids ≤ 44029) pass, including every new
  row. 0 failures and 0 expanded (`evidence/verify-lossless-0905.json`).
- **SNKR:** had no due work after the release, so it has written no encoded row on the new
  code yet. Session 9 must verify SNKR rows.

## 3. Request efficiency (workstream 1)

**Measured** (`evidence/request-efficiency-measure.json`, `requests-baseline-24h-0900.json`):

| | Yuyu | SNKR |
|---|---|---|
| Requests per capture, 24h to 09:00Z | 55.3 | 171.7 captured, 160.3 no_listing |
| Peak per 1800 s window, 24h | 8,458 of 9,000 (94.0%) | 2,958 of 3,100 (95.4%) |
| Peak per 1800 s window, 72h | 8,745 (97.2%) | 2,959 (95.5%) |

- **Per capture:** 2 documents, plus all scripts and styles re-downloaded every time, because
  interception disables the cache. Images, fonts, ads and analytics were already blocked.
- **Homepage share:** about 45% of each capture (ESTIMATE, from a local fully-aborted replay).
- **Warm-up:** Yuyu's warm-up exists because of a 403 on 2026-09-02. SNKR's is its
  source-wide-denial canary.
- **SNKR homepage RAW:** stored on every attempt, 287 rows and 18.92 MB in 24h.

**Implemented:** one warmed browser per due-work turn (PR #96, `COLLECTOR_TURN_BROWSER.md`).
- A turn-level meter forwards only requests from the bound attempt's own page. Everything
  else is aborted before it is sent.
- Each attempt settles before unbind.
- The attempt that warms the homepage pays for it.
- Any non-clean capture discards the browser.
- Discovery discards the turn first. This defect was found in review: a nested sync
  Playwright raises.
- Schedules, budgets, reservations, pacing and context options are unchanged. Nothing is
  spoofed or newly blocked.

**What happened at delivery.** See §4.

**Measured on the unintended GitHub builds** (09:58–10:30Z, `revision` null = no marker):
- 56 Yuyu captures, all `captured`.
- The warming attempt costs 55–56 requests and each following attempt costs 29. Full turns
  average **30.6 per capture (−45%)**.
- 0 failures, 0 denials, 0 optional_resource, 0 reservation overruns.
- **56/56 identical price, stock and promotion** versus each mapping's previous observation
  (`evidence/price-continuity-419210d-github-build.json`). The baseline window shows 281/281
  identical prices.

## 4. Incident: PR #96 merge auto-deployed all collectors in parallel

- **09:57:17Z:** the PR #96 merge (419210d) changed `services/*_collector/**`. These are the
  collectors' Railway watch patterns, so Railway's GitHub integration built and deployed it on
  **all ten collectors at once**, with no exact-commit marker. The verified 05f099d deployments
  became REMOVED.
- **09:58Z:** the sequential rollout refused at preflight, before any upload.
- **Rollback attempt 1** (10:00–10:29Z): no change. A marked, image-less SKIPPED record (left
  by the replay below) aborted the recovery scan. Fixed: `original_source` now skips such
  records.
- **Rollback attempt 2** (10:31–11:00:53Z): all ten restored, one at a time in safe slots, to
  their **verified 05f099d image digests** with daily-v1 and unchanged crons
  (`evidence/rollback-pr96.json`, `live-after-rollback.json`).
- **Second cause found.** Editing PR #95's description at 08:04Z fired an `edited` CI run. Its
  delivery job replayed the 05f099d rollout from 09:00 to 09:29Z. All uploads were SKIPPED and
  resolved to the already-active deployments, so no collector restarted. It held the delivery
  lock until 09:40Z (`evidence/pr95-replay-delivery/`).
- **Rule:** never edit a delivery PR after opening it.

## 4a. Fix forward: PR #97 merged without a rollout, PR #98 delivered it

- **PR #97 (3d8421b, merged 11:42:44Z):** scripts/docs only, so it built nothing on GitHub
  (each collector gained one SKIPPED record).
  - Its delivery job had armed native auto-merge. A merge poll then answered **HTTP 504** at
    11:42:38Z, and `bash -e` failed the job.
  - The disarm step lost the race to GitHub's merge. Staging held PR #96's code with **no
    rollout**.
- **Re-verified at 13:22Z:** all ten on their verified 05f099d digests, with unchanged cron,
  start command and daily-v1 (`evidence/live-before-pr98.json`).
- **PR #98:**
  - The merge-wait loops in `ci.yml` and `staging-delivery.yml` now retry a failed or unparsable
    PR read within the same 120-poll budget.
  - Successful reads are checked as before. Stub test: two 504s then merged gives exit 0; two
    504s then closed gives exit 1.
  - It also re-requests the sequential release. Policy AMBER, eligible.
  - The first CI run failed on a transient `next/font` fetch in `frontend-build`. An empty
    commit (fb63e4f) re-ran CI with the diff digest unchanged.
- **Merged 13:53:27Z (a852244).**
  - **Sequential rollout:** 13:54:52 → 14:31:00Z, one collector at a time, 0 build retries, 0
    snapshot redeploys.
  - **Delivery verification:** green at 14:57:38Z (`evidence/pr98-delivery/`).
  - **Independent recheck:** all ten SUCCESS on a852244, with cron, start command and daily-v1
    unchanged and 0 deployments since (`evidence/live-after-pr98.json`).
  - New digests and redeployable rollback sources are in `evidence/fleet-after-pr98.json`.
  - Blockers are unchanged: freshness-deadline-deficit, snkrdunk-identity-quarantine (23),
    deployment-provenance-divergence.

### Natural verification on a852244 (to 15:15Z)

| | Before (24h to 09:57Z) | After (a852244) |
|---|---|---|
| SNKR requests per attempt | 160.3 (n=182) | **88.1** (n=45, 2 turns): captured 81.3, no_listing 88.6 |
| SNKR homepage RAW | 1 per attempt (287/day, 18.92 MB/day) | **1 per turn** (2 rows, 67 KB each) |
| SNKR budget, 1800 s window | peak 2,958/3,100 (95.4%) | peak 2,855 (92.1%), window average 1,984 (64%) |
| Yuyu requests per capture | 55.3 | **No due work yet** (next due 18:22Z). Same code on the unverified builds: 30.6 |

- **SNKR:**
  - 2 completed turns, 45 attempts, 45 RAW.
  - 0 failures, 0 denials/403/429/challenges, 0 optional_resource, 0 safety faults, 0
    reservation overruns, 0 open attempts.
  - Price, stock and promotion identical on 1/1 captured observation with a previous one
    (`evidence/price-continuity-a852244-snkr-1500.json`).
- **Yuyu:** every shard completed at least one natural turn with 0 attempts, because nothing
  was due.
- **Budget peak caveat:**
  - The SNKR turn's admission, which is unchanged, fills the window budget. The first new-code
    turn therefore did 33 attempts for 2,855 requests, where 15 attempts fitted before.
  - Per-attempt and daily request volume fall. Per-window peaks fall only once the due backlog
    drains: 94 SNKR items are due within 3h.
  - No schedule, budget, reservation or pacing was changed.


## 5. Storage (b) and (c)

- **(b) Re-anchor the SNKR homepage: moot, not implemented.** On a852244 the homepage is
  stored once per turn: 2 rows in 2 turns, 67 KB each (MEASURED). That projects to about
  48 rows and 3.2 MB a day (ESTIMATE), down from 287 rows and 18.92 MB a day (MEASURED).
  Session 9 confirms this over 24h.
- **(c) `source_mapping_proposal_groups` (52.1 MB):** diagnosed, not fixed
  (`evidence/proposal-groups-bloat.json`).
  - It is not dead-tuple bloat: real bloat is about 5.3 MB (13% of heap, ESTIMATE).
  - 22,181 of 26,838 live rows (82.6%) are superseded versions, because `discovery_run_id` is
    part of the evidence digest (`source_mapping_proposals.py:174,190` → `_digest` at `:248`,
    `:612`). Every recurring discovery run re-versions unchanged listings: about 2,164
    versions a day, ≈ 5.3 MB/day (ESTIMATE). Of 3,079 versions since 10-09, only 93 changed
    anything else.
  - HOT updates are 0 because `superseded_at` is in the partial unique index predicate.
  - **Proposed for session 9 (R1, a collector release, because Yuyu imports the module):**
    leave `discovery_run_id` out of the digest input, keep it in the summary, and record the
    last-seen run separately so provenance is not lost. Include `resolution_status` in the
    digest. Expect about 70 versions a day.
  - Not done here, because it changes identity-evidence versioning semantics and would have
    been a third collector release.
  - R3 (per-table autovacuum) saves only about 4 MB. VACUUM FULL is not recommended: it takes
    an ACCESS EXCLUSIVE lock for 2–10 s (ESTIMATE) and blocks discovery persistence.


## 5a. Storage after this session (MEASURED unless noted)

- **`raw_snapshots` UPDATEs:** still 5,924 at 15:15Z, the same as at 09:00Z.
  - 702 more encoded ledger rows were written in that time (ids to 44745).
  - So 0 plaintext row versions have been written by any collector since its release.
- **Lossless:** 6,367 daily-v1 rows (37712–44518), including 1,147 SNKR rows and 209 new SNKR
  rows on encode-before-insert code. 0 failures, 0 expanded (`evidence/verify-lossless-1335.json`).
- **Volume:** 3,633.2 MB at 08:07Z → 3,636.7 MB at 15:15Z. That is +3.5 MB in 7.1h, about
  11.8 MB/day.
  - The window is short. Vacuum frees space that is then reused, which lowers the number.
  - Use it as an early signal only. Session 9 must measure a full 24h.
- **Room to the 3 GiB reserve:** 3,142 MB.
  - Worst case (116.7 MB/day): 27 days, ≈ 2026-11-06.
  - Session-7 steady rate (47.9 MB/day): 66 days, ≈ 2026-12-15.
  - Today's short window (11.8 MB/day): ~266 days (ESTIMATE, unconfirmed).

## 6. Owner storage brief

`OWNER_STORAGE_BRIEF.md`.
- **Recommendation:** grow the Railway volume 10 → 20 GB, billed by GB used at about
  $0.55–1.50 a month. Keep the growth fixes. No R2 archival now.
- **Decide by 2026-10-29.**
- **Volume:** 3,633.2 MB at 08:06Z. Growth over the last 17.7h was 47.9 MB/day.
- **Room to the 3 GiB reserve:** 3,146 MB, which is 27 days at the worst rate (≈ 11-06) and
  66 days at the measured rate (≈ 12-15).

## Quiet windows

| Window | Status |
|---|---|
| Busy window, 02:00–06:00Z (10:00–14:00 MYT) | No collector redeploys. The rollout refuses forward starts outside 06:00–23:00Z. |
| After any collector release | At least one natural turn per collector before the next release |
| 2026-10-10 18:22Z onward | First Yuyu refresh due on a852244. Do not release until every shard has done a natural turn with work |

## Next session (9) must verify
1. **Yuyu on a852244, the first natural turns with work:**
   - requests per capture below 55.3 (expect ≈ 30);
   - budget peak below 94%;
   - 100% identical price, stock and promotion on sampled mappings;
   - 0 denials/403/429/challenges, 0 reservation overruns, 0 lease leaks;
   - turn-browser discard rate.
2. **SNKR over a full 24h:**
   - requests per attempt (expect ≈ 88);
   - homepage RAW about one per turn, ≈ 3.2 MB/day;
   - whether the window peak falls once the backlog drains.
3. **Lossless:** every encoded row with id > 44518, and `raw_snapshots.n_tup_upd` still 5,924
   or close to it.
4. **Storage:** 24h volume growth, recomputed runway, and an update to the owner brief.
5. **Owner decision on the volume** (by 2026-10-29). If approved: AMBER backup, restore check,
   then resize outside the busy window.
6. **Storage (c) R1, collector release:** leave `discovery_run_id` out of the proposal evidence
   digest. Separate release, separate natural verification.
7. **Railway GitHub auto-deploy on collector services:**
   - Disable it as an AMBER staging infra change. It caused the PR #96 parallel build.
   - Until then, keep collector code changes out of the merge that requests the rollout.
8. **Remaining disarm/merge race:** if a delivery job fails while its PR still merges, recover
   with a follow-up PR, never a re-run.


**Never replay:**
- SNKR 3676/3677
- RAW recovery 35175
- Yuyu canary evidence
- completed deliveries PR77–98

**PSA10:** NOT READY, not activated.
