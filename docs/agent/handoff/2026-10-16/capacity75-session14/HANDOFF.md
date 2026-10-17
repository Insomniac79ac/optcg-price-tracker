# Capacity / RAW75: session 14 handoff (2026-10-16)

STAGING ONLY. Production RED, untouched. PSA10 OFF.
- First session run entirely from a cloud session: every staging read and write went through the
  ops runbooks in GitHub Actions (`docs/agent/OPS_RUNBOOKS.md`). No database, Railway or secret access.
- No collector release, rollback or setting change: **0 collector deployments**.
- No schedule, budget, threshold or freshness change. No mapping approval.
- **One owner-approved write:** the remaining-50 enqueue (§2), 50 work rows. Nothing else was written.
- 0 source requests by this session. The 50 captures ran on the ordinary Yuyu schedule.

Numbers are MEASURED from `ops-summary` annotations (run ids below; artifact
`ops-<workflow>-<runbook>-<run id>`, 30-day retention for reads, 90 for writes) unless marked ESTIMATE.

## 0. Start gate

| Step | Result |
|---|---|
| #143 (register ops workflows) | Merged `1bdde86` 2026-10-16 12:05:38Z; verify 38898147180 success |
| ops-readonly / ops-write dispatchable | Yes (both registered by the #143 push) |
| ops-write approval gate | **Did not hold at first**: required reviewer added by the owner 12:26Z. Proof after #150: dry run 38907974275's `owner-approval` job waited for review |

## 1. Step 1 checks (2026-10-16 12:06-12:13Z, staging `1bdde86`)

| Check | Run | Result |
|---|---|---|
| staging-state | 38898271624 | Blockers `snkrdunk-identity-quarantine`, `quarantined-refresh-work`; yuyu HEALTHY, snkrdunk HEALTHY; 0 raw-health actions |
| official-images-status | 38898274419 | Latest mirror run SUCCESS; 4,316 prints, 0 missing, 0 digest mismatch; healthy |
| verify-lossless from 59328 | 38898281402 | 3,714 rows (Yuyu 3,194, SNKR 520), **0 failures, 0 expanded, all lossless**; next floor 63197 |
| storage-rates | 38898278774 | Volume 3,840.7 MB, room to reserve 2,938.0 MB; planning 23.35, stress as observed 109.26, stress A 42.79, **stress B (10-14 04Z transient excluded) 27.58** MB/day |
| fleet-vs-receipt | 38898276584 | All 10 collectors match the `a504e47` receipt; 0 deployment records after it |
| work-by-state | 38899083671 | Counts only (rows were not in the summary before #157) |

No regression; Step 2 went ahead.

**Storage fit for the batch** (owner rule: planning AND stress, transient excluded). 90-day need = rate × 90
+ one-off 70.6 + 0.45 × 90 MB, against 2,938.0 MB room:
- planning 23.35 → 2,212.6 MB: **fits**;
- stress B 27.58 → 2,593.3 MB: **fits**;
- stress A 42.79 → 3,962.2 MB: does not fit (information only; the owner's basis is B).

## 2. Remaining 50: ENQUEUED

| Run | What | Result |
|---|---|---|
| 38899254401 | Dry run | Refused at preflight: `staging-delivery.yml` has no runs endpoint (404). Fixed by **#150** (`4073625`, verify 38906152623) |
| 38907974275 | Dry run | DRY_RUN_OK, sha `6fe48067…` |
| 38972369303 | Apply | **Refused, nothing written**: the list hashed the re-plan time, so the apply re-plan never matched. Fixed by **#155** (`21b3e5b`, verify 38975007571) |
| 38976429257 | Dry run | DRY_RUN_OK, approved list **`54a6a88b54228ed0f088daa3d1a0d80185e4553cfaed562cccd104f73330488b`** |
| **38977099606** | **Apply** (owner approved) | **APPLIED, 50 written**, same sha |

Guards (dry run 38976429257, identical to 38907974275 except the sha):
- eligible 50, to_enqueue 50, already_enqueued 0;
- guard_failures only `no_prior_capture_scope` × 50: every candidate is new, so none of NEW50 (3678-3727) is in the list;
- storage fit at planning and stress B; candidate 196 (OP13-083) included on its live digest (the list is rebuilt from the live plan of every eligible candidate).

**Work ids:** **3728-3777** (50, contiguous; identity-capture-work 39012601383). Candidates include 196.

**Captures** (identity-capture-work 38980652834, 2026-10-16 23:17Z): 50 attempts in 24 h, **50 `completed`** on 50 items, last 23:17Z.
**0 source denials, 0 transient failures**, no 403/429/challenge, no other outcome. No rollback trigger fired.
Per item (39012601383, 2026-10-17 07:10Z): all 50 have 1 attempt, `last_outcome` `completed`, state `pending`, 0 denials, 0 transient failures; attempts ran 22:53:37-23:17:03Z. Yuyu identity-capture totals: 615 pending (ids 2766-3777), 3 blocked (3018-3020, older).

## 3. Tooling changed this session (all data lane, held for the owner)

| PR | Merge | Verify | Change |
|---|---|---|---|
| #143 | `1bdde86` | 38898147180 | Register ops-readonly / ops-write for dispatch |
| #150 | `4073625` | 38906152623 | ops-write preflight drops `staging-delivery.yml`; quarantine count/oldest and mirror run times in summaries |
| #155 | `21b3e5b` | 38975007571 | Approved-list sha holds content only (no re-plan time) |
| #157 | `4f77839` | 38980611073 | `written_work_ids` in the enqueue summary; diagnostic rows in summaries; `identity-capture-work` diagnostic |
| #158 | `58e5e87` | 39012579940 | `identity-capture-work` fits the summary: totals by state, newest 100 items, 24 h outcomes |

## 4. End of session (2026-10-17 06:03Z, staging `4f77839`)

| Check | Run | Result |
|---|---|---|
| staging-state | 39008429233 | Unchanged: same 2 blockers, quarantined refresh work **69** (oldest blocked since 2026-10-02 15:54Z); yuyu HEALTHY, snkrdunk HEALTHY; 0 raw-health actions |
| fleet-vs-receipt | 39008432028 | All 10 match `a504e47`; 0 deployment records after the receipt |
| official-images-status | 39008433309 | Healthy, 4,316 assets, 0 missing; last mirrored 2026-10-12 22:46Z; the 5 latest service runs are SKIPPED (merge-push deployments) |
| verify-lossless from 63197 | 39008434763 | 2,640 rows (Yuyu 2,506, SNKR 134), **0 failures, all lossless**; next floor **66241** |
| storage-rates | 39008430647 | Volume **3,934.1 MB**, room 2,844.6 MB. As observed: planning 34.78, stress (all bases) 131.84, last 24 h 97.01 MB/day |

**Storage reads high only because the remaining-50 one-off is not a named step yet.** `storage_events.json` names
only the NEW50 step, so the batch's one-off (captured 2026-10-16 about 22:40-23:20Z) is charged as daily growth.
- Volume rose 93.4 MB from 12:07Z to 06:03Z (17.9 h).
- Minus the 70.6 MB one-off estimate, that leaves 22.8 MB, about **30.6 MB/day** (ESTIMATE). That is in line with stress B 27.58.
- At that rate the 90-day need is about 2,795 MB, against 2,844.6 MB room (ESTIMATE): it fits, but barely.
- Not judged over bound, but **not verified**: session 15 must name the step and re-read (below).

## Quiet windows

| Window | Status |
|---|---|
| 02:00-06:00Z | Nothing collector-affecting (the enqueue apply counts) |
| 19:30-20:30Z | No write runbook, no merge |
| Merges | 06:00-23:00Z. #157 merged 23:17Z by the owner (override) |

## Owner decisions and notes carried

- GHSA-vcvr (Next `next/og`): fixed off by #153's static `/share` fallback (run 38922562795); still open for Next 16.3.
  Corrected in `docs/agent/security/2026-10-16-accounts-audit.md` in this PR.
- Next.js 16.3.x parked (staging verify `/sign-in` prefetch hang); 16.2.12 live.
- F15 `CORS_ALLOW_ORIGIN_REGEX`: owner checking on Railway. L1 waits for the next collector release.

## Session 15 must verify

1. **This handoff PR's delivery receipt**: expect scope `skip`, 0 collector deployments.
2. **Capture outcomes**: `db-diagnostic identity-capture-work` (after #158). The 50 work ids above all
   `completed`, 0 denials, ≤ 5 transient failures; identity unresolved (no auto-approval, 0 mappings created).
3. **Storage**: add a `rem50` step to `scripts/ops/storage_events.json` (2026-10-16 22:40-23:20Z, evidence: this
   handoff and run 38980652834). Then re-read `storage-rates`: planning and stress B ex-steps vs 23.35 / 27.58,
   and the 90-day need with no further batch vs room.
4. **Lossless** from ledger id 66242 (floor exclusive 66241).
5. **Official-images mirror**: the next scheduled 07:15Z run succeeds (the latest runs are merge-push SKIPPED).
6. **Never replay:**
   - SNKR 3676/3677, RAW recovery 35175, Yuyu canary evidence;
   - NEW50 work ids 3678-3727 and list `906482e8…`;
   - the remaining-50 work ids above and list `54a6a88b…`;
   - completed deliveries PR77 onward, including #143, #150, #155, #157, #158 and this handoff PR.

**PSA10:** NOT READY, not activated.
