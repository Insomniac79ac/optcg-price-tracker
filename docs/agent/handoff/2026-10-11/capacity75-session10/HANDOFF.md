# Capacity / RAW75: session 10 handoff (2026-10-11)

STAGING ONLY. Production RED, untouched. PSA10 OFF.
- No source job was triggered manually.
- No mapping approval, no NEW100 approval, no SNKRDUNK discovery.
- No schedule, budget, pacing or freshness change.
- No RAW evidence deleted. No resize, no infrastructure change.
- **One collector release:** PR #103 (resolver 1.3 proposal digest) went to all 10 collectors as
  `a504e47`. It used the CI delivery job, one collector at a time, 15:52:38-16:31:08Z. §4 and §5.

**Owner decision (2026-10-11, after 23:00Z): `a504e47` is accepted as the new collector baseline.
No further release this session.**

Numbers are **MEASURED** (source under `evidence/`, read-only tools in `tools/`) unless marked
CARRIED FORWARD (CF) or ESTIMATE.

Session ran in two parts:
- **Part A (about 14:37-16:56Z):** steps 1-4, up to and including the PR #103 release by the CI
  delivery job.
- **Part B (23:04-23:35Z):** the Codespace had restarted between the parts. Part B ran read-only
  checks, the owner decision above, and this handoff.

## 0. Start gate (14:37Z, `evidence/live-state-start.json`, `evidence/trigger-status-start.json`)

- All 10 collectors are SUCCESS on their verified a852244 deployments and image digests, with the
  exact-commit marker.
- cron, start command and variables (daily-v1) are unchanged.
- **Session-9 test merge (PR #100, merged 2026-10-10 22:57:07Z): 0 deployment records of any
  status on all 10 collectors since then.** Before the trigger removal, every merge added one
  SKIPPED record per collector.
- GitHub triggers: none of the 10 collectors has a trigger, and auto-deploy is `false` on all of
  them. The API, worker, beat and market-index-snapshot keep theirs by design.
- State regenerated at 14:39:07Z (`CURRENT_STATE-start.yaml`). The 3 blockers are unchanged.

## Backup gate: not met at the start, MET at 15:32Z

`evidence/backups-1440.json`, `evidence/backups-recheck.json`, `evidence/backups-final.json`.
- **14:39Z and 14:54Z:** the newest backup was `pre-freshness-c4e8a1d7b902-staging-20260930T113837Z`
  (267 h old), with no schedule. Steps 1-3 ran first, and step 4 was prepared as a draft.
- **15:32Z:** the owner's **manual backup `2135eec8-6932-4344-bf3f-a1fee2fc3387`** (created
  2026-10-11 15:20:25Z, referencedMB 3,569) was present, along with a **daily schedule**: cron
  `22 9 * * *`, retention 518,400 s (6 days).
- The gate passed, and step 4 proceeded as AMBER (§4, §5).

## 1. SNKRDUNK 24h on a852244 (2026-10-10 14:31Z → 2026-10-11 14:31Z)

`evidence/requests-24h-a852244.json`, `evidence/snkr-24h-detail.json`,
`evidence/natural-turns-a852244.json`, `evidence/price-continuity-24h.json`.

| | Session 9 (7.7h, a852244) | **Full 24h, a852244** |
|---|---|---|
| SNKR requests per attempt | 88.6 (n=127) | **90.8** (n=318: captured 97.2 ×50, no_listing 89.6 ×268; max 179, reserved 300, 0 over reservation) |
| Homepage RAW | 7 in 7 turns with work | **16 in 16 turns with work (max 1 per turn), 1,075,908 bytes stored**, vs 287/day and 18.92 MB before (CF s8) |
| SNKR window peak / average (per 1800 s, limit 3,100) | 2,855 / 1,612 | **2,875 / 1,805** over 16 windows with work |
| Did the peak fall as the backlog drained? | n/a | **No.** The backlog drained by 10-10 17:32Z, and there was no SNKR work from 17:53Z to 08:53Z. When the refreshes came due again (09:00-14:30Z), windows ran 848-2,875 with peaks of 2,832, 2,875 and 2,820. The peak is set by per-turn admission filling the window, not by backlog size. It stays below the 3,100 limit |
| Denials / 403 / 429 / challenges | 0 | **0 / 0 / 0 / 0** across 48 SNKR runs (16 with work) |
| Failures / safety faults | 0 | **0 / 0** |

- **Price continuity:** 2,666 observations in the window (both sources), all with a previous one.
  - 2,664 have identical prices. The 2 changes are SNKR floors, plausibly real market moves:
    mapping 45 ¥5,444 → ¥5,999 and mapping 99 ¥3,900 → ¥4,000.
  - 2,658 have identical price, stock and promotion.
- **SNKR due work now:** 89 `blocked` (the known blockers: 43 identity_refusal, 22 coverage,
  23 quarantined validation, 1 source_denial, CF s9), 290 pending, 15 due at 15:00Z (normal
  turnover).
- **Yuyu, same 24h** (informational):
  - 31.2 requests per capture (n=2,616 captured, p50 29);
  - window peak 5,028 / 9,000 (55.9%) at 03:53Z in the busy window, average 2,305;
  - 2 transient failures (1 refresh, 1 discovery) and 1 optional_resource, all on shard-4-v2;
  - 0 denials.

## 2. Storage (owner decision 2026-10-11: no resize; grow within the 10 GB volume)

`evidence/volume-series.json`, `evidence/storage-model.json`, `evidence/per-capture-24h.json`,
`evidence/identity-capture-sizes.txt`.

**Units.** Railway's `DISK_USAGE_GB` metric × 1000 matches its own volume `currentSizeMB`
(3,562.7 MB at 14:39Z). Session 9 converted with × 1024. That basis is kept here because it is
continuous and about 86 MB more conservative. Railway-basis figures are in the evidence.

| | MEASURED |
|---|---|
| Volume at 10-11 14:00Z | 3,655.3 MB (s9 basis); 3,569.7 MB on the Railway basis |
| Room to the 3 GiB reserve (3,221.2 MB) | **3,123.4 MB** (3,209.1 on the Railway basis) |
| **24h growth on a852244**, 10-10 14:00 → 10-11 14:00Z, including the 02-06Z busy window | **18.8 MB/day** (s9: 33.5 CF, which included pre-a852244 hours) |
| Since session 9 (16h) | 20.8 MB/day |
| 42h (includes pre-a852244 hours) | 23.8 MB/day |
| Worst rolling 24h in the series (includes 10-10 04-06Z on the old code) | 34.2 MB/day |

**Runway to the reserve:**

| Rate | Days |
|---|---|
| 18.8 (24h) | 166 (≈ 2027-03-26) |
| 23.8 (42h) | 131 |
| 34.2 (worst rolling 24h) | 91 |
| 47.9 (CF s8) | 65 |
| 116.7 (CF s7, pre-encode code) | 27 |

**NEW100 storage need, recomputed from fresh rates.** The 4.3-8.8 GB figure is retired.
- It was session 7's total 90-day volume minus 10 GB at that session's 66-117 MB/day base growth.
  It was not NEW100's own cost.
- **One-off (artwork capture of 100 families: 100 Yuyu images + 217 official siblings = 317 full
  originals, plus 200 HTML pages):**
  - hard bound **887.0 MB**, re-derived: 317 × (base64 of the 2 MiB `MAX_IMAGE_BYTES` + 2 KB),
    the same formula and the same code constant;
  - measured-average estimate **133.1 MB**: 635,067 B per Yuyu image and 291,299 B per official
    image over 1,575 stored images, plus 31.9 KB per HTML page;
  - observed-maximum estimate 193.0 MB;
  - reuse check: **0 of the 217 official and 0 of the 100 Yuyu images are already stored** (the
    families are virgin by design), so reuse cannot shrink the bound.
- **Recurring (only the ongoing price checks for up to 100 new Yuyu mappings):**
  - 6.27 KB per refresh capture all-in: 24h volume growth / 3,003 attempts, which overstates the
    per-capture cost;
  - so 0.63 MB/day, 56 MB over 90 days.
- **90-day check, 3 GiB reserve kept, hard image bound:**

| Base growth | Need | Room | Margin |
|---|---|---|---|
| 18.8/day (fresh 24h) | 2,638 MB | 3,123 MB | **+485 MB, fits** |
| 23.8/day (42h) | 3,083 MB | 3,123 MB | +41 MB, fits (thin) |
| 34.2/day (worst rolling) | | | −896 MB, does not fit (largest batch: 5 families) |
| 33.5/day (CF s9) | | | −835 MB, does not fit (11 families) |

  With the measured-average image estimate instead of the hard bound, the margins are +1,239 MB at
  18.8 and −142 MB at 34.2.

**Where artwork captures land.** In **Postgres**, not R2: base64 JSON in `raw_snapshots`, stored
uncompressed. That is 636 MB of images today, about 23% of the database. A design that keeps
bytes in R2 with a SHA and pointer in Postgres is in `ARTWORK_EVIDENCE_R2_DESIGN.md` (design only,
no migration). It preserves original bytes, SHA and length verification, and never-delete.
Distributing `EVIDENCE_R2_*` to collectors is flagged as an owner (secrets) decision.

## 3. Auto-deploy fix made permanent (tooling only): PR #102

- `deploy_staging_collectors.refuse_github_triggers` reads `deploymentTriggers` and
  `serviceInstanceAutoDeployStatus` for **every** delivered collector. It refuses a forward
  release on any trigger, auto-deploy not exactly `false`, an unreadable status, or a missing
  collector.
- It is called by the sequential rollout before capture, slot or upload, and recorded in the
  receipt as `github_trigger_preflight`. `collector_variables.change` calls it before staging.
- Restore paths never call it.
- Tests:
  - trigger present → refuse with no slot or upload;
  - auto-deploy on → refuse;
  - missing or unreadable → refuse;
  - none → proceed, with all 10 checked;
  - rollback skips the check.
  - `scripts/tests`: 158 passed. pytest rollout + variables: 35 passed.
- Live read-only run (`evidence/trigger-preflight-live.json`): all 10 "no trigger, auto-deploy
  disabled".
- **Merge and receipt:** see §5.

## 4. Proposal digest: RELEASED as `a504e47` (PR #103), natural discovery not yet observed

### Release (MEASURED)

**Receipt.** The original rollout receipt is the CI artifact
`staging-delivery-a504e476d98ab49ad7773a0c8c6b71e9d927b125`:
- CI run 38151886392, artifact id 11709366163, expires 2027-01-09;
- the copy in this handoff is `evidence/pr103-delivery/.../evidence/latest-collector-rollout.json`,
  with `latest-staging-delivery.json` and `latest-delivery-scope.json` beside it.

**Release facts:**
- PR #103 merged 15:51:23Z, merge commit `a504e476d98ab49ad7773a0c8c6b71e9d927b125`, CI head
  `34507dd`.
- Rollout ran 15:52:38 → 16:31:08Z, `sequential: true`.
- `github_trigger_preflight`: "no trigger, auto-deploy disabled" on all 10 collectors. This is the
  PR #102 preflight's first real use.
- Order and times (Railway `createdAt`):

| Collector | Deployed (Railway `createdAt`) |
|---|---|
| snkrdunk-collector | 16:02:22Z |
| yuyutei-collector-shard-0 | 16:05:13Z |
| yuyutei-collector-shard-1 | 16:08:22Z |
| yuyutei-collector-shard-2 | 16:11:22Z |
| yuyutei-collector-shard-3 | 16:14:03Z |
| yuyutei-collector-shard-4-v2 | 16:17:07Z |
| yuyutei-collector-shard-5 | 16:20:07Z |
| yuyutei-collector-shard-6 | 16:23:07Z |
| yuyutei-collector-shard-7 | 16:26:22Z |
| yuyutei-collector-shard-8 | 16:29:12Z |

- Delivery verification `verified_at` 16:56:13Z:
  - frontend `dpl_7xXCRAkou9DcDvYhidRMSij9SMKF` READY at `a504e47`;
  - migration `f9e5b4a8c012`;
  - API built from its GitHub trigger (watched `services/api/**` change, by design);
  - API runtime `git_commit` reports "unknown", as in every earlier receipt;
  - `production_accessed: false`.

**About the "missing" receipt.** At the start of part B, the receipt was wrongly reported as
missing. Only local disk had been searched, and `/tmp` (including the part-A worktrees under
`/tmp`) was wiped by the Codespace restart. The rollout itself runs inside the CI delivery job,
which uploads the receipt as a run artifact, so it was never lost. Part B cross-checked it against
primary sources and labels the result a **CROSS-CHECK of the original**, not a reconstruction
(`evidence/pr103-receipt-crosscheck.json`, `tools/receipt_crosscheck.py`):
- GitHub: merge commit = receipt `source_sha`; CI run success.
- Railway, all 10 collectors:
  - the receipt's deployment exists, is SUCCESS, its image digest equals the receipt, and its
    `cliMessage` carries the exact commit;
  - **exactly one deployment record per collector since the merge**, and it is that one.
- Rollback targets: the receipt's `before` deployments equal the session-8 verified a852244
  deployments and digests (`2026-10-10/capacity75-session8/evidence/fleet-after-pr98.json`) on
  all 10.
- No field had to be marked UNKNOWN.

**Rollback target** (the receipt's `before`, `a8522447c6933d05e94e01d5789cdcd5160c10da`):
- `evidence/rollback-source-check.json` (`tools/rollback_source_check.py`) shows, at 23:24:08Z, a
  redeployable source for all 10. The lookup is `collector_variables.original_source`, the same
  one the restore path uses.
- Railway shows these deployments as REMOVED, the normal state for a replaced deployment, with
  `canRedeploy: true` and digests equal to the receipt.

| Collector | Rollback deployment |
|---|---|
| snkrdunk-collector | `59171f15-ee6b-4489-8470-f520b9e5e5f7` |
| shard-0 | `209fc53c-8e15-4fc1-aac0-cdd2b3380ed4` |
| shard-1 | `cb8156c3-d4e4-4320-9a17-51cacd139f79` |
| shard-2 | `f572ef86-6e19-4909-9a9b-a4009f42108c` |
| shard-3 | `8a5889b1-c269-415b-a8ac-331cc6fbeb0b` |
| shard-4-v2 | `26808284-572d-4fea-bc93-f2fdefe51e85` |
| shard-5 | `a47093dc-ad60-4ede-ade4-7a42253a252a` |
| shard-6 | `7dd74cd4-5073-4e0a-ad6c-7beb181db582` |
| shard-7 | `d2c50819-5970-4935-b77e-cb3a3f66b64b` |
| shard-8 | `f98f53b9-237b-48f1-9bf7-b8ce19acdfb1` |

**Rollback triggers (owner):** either one of these.
1. More than **200 new proposal versions per day after the first full Yuyu discovery cycle** on
   `a504e47`. The first cycle is expected to re-version the current pending groups once (about
   2,164), so it is not a trigger.
   - The first cycle is complete when every pending Yuyu discovery work item (585 total, 3
     blocked) has at least one attempt on `a504e47`.
   - Then measure the following 24h.
2. **Any artwork proof lost:** approved exact Yuyu groups with a proof drop below **298**, or any
   approved group is superseded.

Procedure: the restore path in `scripts/deploy_staging_collectors.py`, one collector per safe slot,
06:00-23:00Z only.

### Read-only checks after the release (part B, MEASURED)

| Check | Result | Evidence |
|---|---|---|
| Fleet | All 10 SUCCESS on `a504e47` with the marker. Cron, start command and daily-v1 variables unchanged | `live-a504e47-2307Z.json` |
| GitHub triggers | None on any of the 10; auto-deploy disabled on all 10 | `live-a504e47-2307Z.json` |
| Backup gate | Manual backup `2135eec8…` created 15:20:25Z, 7.8 h old. Daily schedule `22 9 * * *`, 6-day retention | `backups-2307Z.json` |
| Approved exact (Yuyu) | **2,019**, unchanged | `post-release-health-2327Z.txt` |
| …of which with proof | **298**, unchanged | `post-release-health-2327Z.txt` |
| Approved exact (SNKR) | 151, unchanged | `post-release-health-2327Z.txt` |
| Approved groups superseded since the merge | **0** | `post-release-health-2327Z.txt` |
| New proposal versions since the merge | **0** | `post-release-health-2327Z.txt` |
| Proposal tables | 56.99 MB groups + 15.44 MB alternatives, 30,251 rows. Unchanged from the 15:34Z baseline | `post-release-health-2327Z.txt` |
| Collector runs on `a504e47` (16:33-23:05Z) | **All completed**: 13-14 per collector, at least one natural turn on every collector | `post-release-health-2327Z.txt` |
| Attempts | Yuyu 649 refresh captures at 31.1 requests each. SNKR 23 refreshes (no listing) at 79.5. 0 failures | `post-release-health-2327Z.txt` |

**Natural verification is incomplete.** The behaviour that changed, Yuyu discovery, has not run on
`a504e47`:
- last discovery attempt 14:15:53Z, before the release;
- next due 2026-10-12 01:12:59Z.

The receipt itself records `natural_runs_not_yet_verified: true`. Refresh turns ran naturally on
every collector, with 0 failures.

### Design and pre-release evidence (part A, MEASURED then)

Branch `capacity/proposal-digest-20261011`. Design per session-9 `PROPOSAL_DIGEST_PREFLIGHT.md`.


- `RESOLVER_VERSION` goes 1.2 → **1.3**. `evidence_digest` hashes the evidence **without**
  `discovery_run_id`, which `evidence_summary_json` still records as provenance.
- **Bridge for proofs recorded under 1.2:** `physical_artwork_proof.bound_evidence_digest`
  accepts a 1.2 baseline only if all of the following hold. A review never transfers across a
  real evidence change.
  - the capture cursor's own stored `evidence_summary` hashes to it under the 1.2 rule;
  - the cursor digest equals it;
  - that summary equals the current evidence in every field except `discovery_run_id`.
- **Before (MEASURED 14:4xZ, `evidence/proposal-current-status-start.txt`):**
  - Yuyu wrote **2,164 versions in 24h, all pending**: 1,326 ambiguous, 451 release_unresolved,
    379 unresolved_identity, 5 conflict, 3 exact-pending. SNKR wrote 0.
  - The approved exact groups: **2,019, of which 298 carry proofs, with 0 new versions in 24h.**
  - They cannot be re-versioned or demoted by the digest change, for two reasons: mapped listings
    produce no plan, and recurring discovery skips candidates with a reviewed current group
    (`reviewed_preserved`).
- **298-proof guard evidence:**
  - All 298 registry proofs have a capture cursor whose stored summary hashes (1.2) to the proof
    baseline: **298/298** (`evidence/proof-bridge-check.json`).
  - Read-only resolver replay over 20 sampled proof candidates (`evidence/resolver-replay-1.2.json`,
    `-1.3.json`):

| Code | Proofs that re-attach |
|---|---|
| Current 1.2 code | **0/20** (their 1.2 baselines went stale as `discovery_run_id` changed) |
| 1.3 with the bridge | **17/20** |

  - The 3 refusals are real evidence changes since review: listing text changed on 1219 and 1342;
    listing text and availability (out_of_stock → in_stock) changed on candidate 1.
  - Count of current approved exact groups with proof: 298 before. It must still be 298 after
    release.
- **Tests:**
  - an unchanged listing over 3 new runs is reused, not superseded;
  - a price, availability or text change still makes a new version;
  - hard guard: approved exact groups with proofs keep their row, digest, version, approval and
    proof through recurring discovery under 1.3. This test fails if any is superseded or loses its
    proof, and it failed against the 1.2 code;
  - a 1.2 review re-attaches only to identical evidence, and refuses on price, availability,
    listing-text or sibling change and on any cursor tampering.
- **Expected after release:**
  - a one-time re-version of the current **pending** groups (about 2,164 Yuyu, ≈ 4-5 MB ESTIMATE);
  - then about 47 versions a day (CF s9 basis).
- **Not changed:** identity guards, resolution logic, approval fences
  (`evidence_digest_changed` still fences superseded digests), Yuyu sale policy, schedules,
  budgets, pacing, freshness. Nothing is auto-approved.

## 5. Deliveries this session

| PR | Scope | Merge | Verification | Collector deployments |
|---|---|---|---|---|
| #102: GitHub-trigger preflight (tooling) | full (`scripts/`), no rollout requested | 15:04:16Z | CI delivery verified 15:15:44Z; artifact `staging-delivery-7503d71…` (`evidence/pr102-delivery/`) | **0.** No rollout receipt in the artifact, and no collector deployment record between 15:00Z and the PR #103 rollout (`evidence/live-vs-a852244-2305Z.json`: exactly 1 record per collector since 15:00Z, the PR #103 one) |
| #103: resolver 1.3 proposal digest (AMBER) | full, rollout of 10 collectors | 15:51:23Z | CI delivery verified 16:56:13Z (§4) | **10**, one per collector, sequential, 16:02-16:29Z |
| This handoff | docs-only (`docs/agent/handoff/**` plus the mission manifest, no rollout requested) | see PR | CI delivery job | expected 0 |

Not replayed: SNKR 3676/3677, RAW recovery 35175, Yuyu canary evidence, deliveries PR77-100,
#102, #103. No failed delivery job was re-run.

## 6. NEW100: NOT EVALUATED, NOT APPROVED

Step 5 runs only after steps 3-4 are stable. Step 4 is released, but its changed behaviour (Yuyu
discovery) has not run naturally yet (§4). The table below is evidence for session 11, not an
approval.

| Guard | Status |
|---|---|
| Storage headroom (current 10 GB volume, 3 GiB reserve, 90 days) | Passes at the fresh 24h rate with the hard 887 MB bound (+485 MB). Thin at the 42h rate (+41 MB). **Fails** at the worst rolling 24h (largest batch 5). Needs ≥ 48h of growth on the current code first (§2) |
| 23h/24h feasibility at about 31 requests per capture | Pass on paper: (2,616 + 100) × 31.2 ≈ 84.7k/day vs 432k/day (ESTIMATE from MEASURED) |
| Measured source capacity | 0 denials on a852244 (24h), 0 failures on `a504e47` so far |
| Exact CardPrint identity, no duplicate mapping, authoritative release, shard distribution | **Not evaluated.** The 2026-10-07 manifest's 100 digests are resolver-1.2 digests that include `discovery_run_id`. They are stale and **must be re-planned on 1.3 digests** before any guard is run |

## 7. Coverage, freshness, due work, Market Value

From `evidence/coverage-start.json` (15:00:55Z) and `CURRENT_STATE-start.yaml`.

- **Coverage** (denominator 4,316):

| | Count | Change |
|---|---|---|
| Mapped | 2,635 | |
| Operational | **2,630** | 0 from 2,630; 607 to the 75% target of 3,237 |
| Fresh usable | 2,398 | |
| Both sources | 334 | |
| Zero sources | 1,681 | |
| Duplicate exact-print source groups | 0 | |

- **Freshness:** deadline compliance `not_met`; sustained compliance unknown.
  - Yuyu: 2,619 mappings; 1 never checked; 2 checks older than 24h.
  - SNKR: 353; 22 never checked; 44 older than 24h (blocked); 278 no_listing.
- **Open non-blocked work:** 0 checks older than 24h, 0 without a first success.
- **Due now:** Yuyu 0; SNKR 15 pending plus 66 blocked refresh and 23 blocked validation.
- **Market Value:** latest atomic receipt for 2026-10-10 (2,626/2,626 rows). The 09-27/28 gaps are
  intact (0 rows). Today's run is due at about 20:00Z.

## 8. Lossless

Every daily-v1 ledger row from id 37712 to the ledger maximum at run time, 47828, was
re-verified: **9,422 rows, 0 failures, 0 expanded.**
- Part 1, ids 37712-47602 (9,300 rows): `evidence/verify-lossless-part1-progress.txt`. The run was
  stopped by this session's own 30-minute `timeout` after the 47602 batch, with failures=0 at every
  batch.
- Part 2, ids 47603-47828 (122 rows, all SNKR): `evidence/verify-lossless-part2.json`,
  `all_lossless: true`. Resumed with the new optional floor argument of `tools/verify_all.py`.
- 0 database writes, 0 source requests.
- Part 2 has no Yuyu rows because the Yuyu refresh cycle is currently bunched. All 2,616 checks
  happened between 10-10 ~18:00Z and 10-11 11:51Z, mostly in the busy window, and Yuyu due work
  is 0 until about 22:00Z. Freshness is unaffected (0 open non-blocked checks older than 24h).


## 9. End-of-session state

MEASURED 23:26:37Z, `evidence/coverage-end.json`:
- Coverage: mapped 2,635; operational **2,630**, 0 change from 2,630; fresh usable 2,398; both
  sources 334; zero sources 1,681; duplicate exact-print groups 0.
- Open non-blocked checks older than 24h: 0. Open non-blocked without a first success: 0.
- Due now: Yuyu refresh 45, oldest 22:56Z (normal turnover); SNKR 0.

**Regenerated state:** `CURRENT_STATE-end.yaml`, evidence `evidence/staging-state-6ac524c7f165f6b3.json`,
generated 23:25:47Z.
- Blockers: **2**, `freshness-deadline-deficit` and `snkrdunk-identity-quarantine` (23).
- `deployment-provenance-divergence` has cleared now that the collectors run the staging head
  commit.
- The canonical `docs/agent/CURRENT_STATE.yaml` and `docs/agent/evidence/` are not changed by this
  docs-only PR (they are outside the docs-only allowlist). The CI delivery job regenerates and
  uploads them as run artifacts.

## Quiet windows

| Window | Status |
|---|---|
| 02:00-06:00Z (busy) | No collector change, ever |
| Collector releases | 06:00-23:00Z only, one collector per safe slot, via the CI delivery path |
| 19:30-20:30Z | No API or migration merge (daily snapshot and receipt about 20:00-20:05Z) |
| 2026-10-12 01:12Z onward | First natural Yuyu discovery turns on `a504e47`. Leave the collectors alone until the first full cycle has been measured |
| NEW100 | Only after the proposal-digest release is verified (below) and NEW100 is re-planned on 1.3 digests |

## Session 11 must verify

1. **Proposal-digest natural verification** on `a504e47`. Rollback per §4 if a trigger fires.
   - first discovery turns from 2026-10-12 01:12Z: 0 discovery failures, 0 `stored proposal
     differs` errors, every new version at resolver 1.3;
   - approved exact Yuyu = 2,019, with proof = **298**, approved superseded = 0, SNKR approved
     exact = 151;
   - the one-time re-version of the pending groups (about 2,164) during the first full cycle,
     then **≤ 200 versions/day** (target about 47, CF s9) in the 24h after it;
   - proposal table growth over that 24h;
   - lossless green from ledger id 47829.
2. **Receipt persistence (tooling).** The owner asked that receipts move to a persistent path.
   - Finding: the rollout receipt was already persisted as a CI artifact (90-day retention, expires
     2027-01-09). The part-B "missing" report came from searching only local `/tmp`.
   - Remaining real gaps: artifact retention is finite, and operator-side files in `/tmp` do not
     survive a Codespace restart.
   - Proposed fix, for owner confirmation: each handoff downloads its delivery artifacts into its
     evidence folder (done by hand this session, `evidence/pr10{2,3}-delivery/`), and
     session-local operator output goes under `/workspaces/<worktree>`, never `/tmp`. A tooling
     change, such as a helper that fetches the artifact for a merged PR, is a GREEN scripts change.
3. **Storage:** at least 48h of growth on the current code, then redo the NEW100 storage check
   (§2).
4. **NEW100:** re-plan the 100 candidates on **1.3 digests**, then evaluate every guard with
   evidence. Approval stays AMBER and only if every guard passes, or the largest batch that fits
   storage, with the reserve and horizon unchanged.
5. **Never replay:**
   - SNKR 3676/3677
   - RAW recovery 35175
   - Yuyu canary evidence
   - completed deliveries PR77-100, #102, #103 and this handoff PR

**PSA10:** NOT READY, not activated.
