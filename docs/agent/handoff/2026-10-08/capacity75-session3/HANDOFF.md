# Capacity / RAW75 — session 3 handoff (2026-10-08)

STAGING ONLY. Production RED, untouched. PSA10 OFF. Mission incomplete; stopped at a
session boundary (next step needs a natural SNKR run ≥ 10:32:04Z) behind a verified
storage constraint.

Read first: this file, CONTINUATION.json, `../capacity75-resumed/LIVE_PROGRESS.md`,
`../capacity75-pause/HANDOFF.md`, `docs/agent/RAW_STORAGE_DAILY_ADMISSION.md`,
`docs/agent/YUYU_CLAIM_WAIT.md` (on `origin/staging`).

## Done this session

1. Pushed Codespace-only `docs/agent/handoff/2026-10-08/` to branch `handoff/2026-10-08`
   (commit 25bb4de, 159 files, nothing else). Not merged.
2. Codespace disk: 4.4G → 7.7G free (86% → 75% used). See `../disk-cleanup.md`.
3. Reconciled PR78/79/80 (below). PR80 delivery: CI engineering checks passed, collectors
   deployed, but the CI verify step **failed** with a `TimeoutError` in the public sale-exclusion
   API sweep (one of ~452 GETs hit the 30s socket timeout). Nothing redeployed or re-merged.
   The identical read-only verifier was rerun locally from a clean `origin/staging` (1b1b64d)
   worktree and **passed at 05:53:31Z** (`pr80-local-delivery-verification.json`,
   `pr80-local-verify.log`). This is a local receipt, not the CI strict artifact.
4. CURRENT_STATE regenerated from live staging at 05:53:16Z:
   `CURRENT_STATE-20261008T0553Z.yaml` + `staging-state-4f6180e61df3c6f3.json`
   (sha256 4f6180e6…). Not committed to staging, by design (STATE_GENERATOR.md).
5. Read-only measurements: `coverage-latest.json`, `baseline-20261008T052739Z.json`,
   `storage-projection-inputs.json`, `storage-forecast.json`, `raw-dedup-24h.json`,
   `post-pr80-natural-*.json`.

## PR checkpoint

| PR | merge | CI | staging delivery | natural verification | changed |
|---|---|---|---|---|---|
| 78 | 4995007 | 37717982746 SUCCESS | strict artifact 11526037188 verified (prior session) | all 10 components, resume-census-20261008T031814 | daily-v1 storage mode (OFF), migration f9e5b4a8c012 (2 indexes). No cron/budget/pacing/claim change; writers OFF |
| 79 | a6c0809 | engineering checks SUCCESS; delivery job FAILED (collector guard refused GREEN manifest before upload) | API/frontend only; collectors not delivered by PR79 | collector code delivered and verified via PR80 | bounded RAW body query + bundled Manrope font. No cron/budget/pacing/claim/writer change |
| 80 | 1b1b64d | 37730392225: all engineering SUCCESS; staging-automerge FAILED at verify (TimeoutError) | collectors deployed 05:18–05:21 (schedules identical before/after); local verifier rerun PASSED 05:53 | all 10 collectors ran natural turns on 1b1b64d 05:27–05:54; 158 Yuyu captures, peak 2 concurrent claims, 0 expired claims, 0 >24h | claim rule: ≤6×5s retry only on explicit four-claim contention. No cron/budget/pacing/writer change |

PR80 claim-wait under real contention is NOT yet naturally exercised (peak 2 < cap 4).
Need a natural busy window (prior evidence: 02–06Z) showing peak ≤4, no excess claims.

## Verified constraint: storage

Volume 3,402.8 MB / 10,000 MB (Railway metrics 05:28Z). DB 2,562,774,719 B; raw_snapshots
2,417,360,896 B (94%). Recurring rows 171,965,155 B/24h (Yuyu collector 101.1 MB, SNKR
collector 64.0 MB, Yuyu discovery 4.9 MB, obs+events ~1.9 MB). Provider volume slope
over 23:49→05:28 = 232 MB/day (short window, includes WAL).

At current load, no expansion: 3 GiB reserve reached in 14.5–16.4 days, volume full in
28–32 days. 30d: 9.59–10.37 GB; 90d: 21.98–24.29 GB. NEW100 / SNKR discovery / artwork
captures all add volume and are blocked by this.

Whole-body dedup is not a remedy: 0 of 3,327 recurring 24h bodies duplicate an earlier hash.
The remedy is the already-delivered dictionary writer (Yuyu canary: ~95% savings).
Activation requires (RAW_STORAGE_DAILY_ADMISSION.md) a natural SNKR writer sample first.
Volume resize is not reversible (Railway cannot downsize) → would fail AMBER rollback.

## Next session, in order

1. Re-read live state; confirm 1b1b64d still deployed on all 10 collectors + API + frontend,
   writers OFF, ledger 16/15 protected, recovery 35175 untouched.
2. AMBER preflight: enable SNKR writer only (canary mode, global 200 cap, 184 left), staging
   APP_ENV, before a natural SNKR RAW turn ≥ 10:32:04Z. Observe ONE ordinary turn, set OFF,
   independently verify original SHA/length for every new encoded row, measure physical bytes,
   runtime, lookup cost, admission skips, denials, leases. Do not invoke a job. The prior
   `snkr_storage_canary.py` helper is pinned to 4995007 and must be re-pinned to 1b1b64d,
   not have its checks weakened.
3. If SNKR passes: AMBER preflight for `daily-v1` on all 9 Yuyu + SNKR, then ≥24h natural
   physical-growth evidence; recompute 30/90d with 3 GiB reserve + 887,045,884 B NEW100 image bound.
4. Only after storage passes: NEW100 evaluation (all guards), then SNKR discovery from the
   3676/3677 checkpoint and zero-source exact approvals.

Earliest re-check: 2026-10-08 10:32Z = 18:32 Asia/Kuala_Lumpur (SNKR due). Claim-wait busy-window
evidence: 2026-10-09 02:00–06:00Z = 10:00–14:00 MYT.

## Never replay

SNKR intents 3676/3677; RAW recovery 35175; Yuyu storage canary evidence (16 encodings,
15 protected, 1 recovered); `recover_canary.py`; initial storage activation helper; PR77–80
deliveries (do not rerun staging-automerge — it redeploys collectors).
