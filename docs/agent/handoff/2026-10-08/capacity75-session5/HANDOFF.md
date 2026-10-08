# Capacity / RAW75 — session 5 handoff (2026-10-08)

STAGING ONLY. Production RED, untouched. PSA10 OFF. **All RAW writers are OFF**
(verified 12:30:50Z, `daily/flags-after-rollback.json` + shard-6 rollback). Every
collector is on a deployment carrying the exact-commit 1b1b64d upload marker,
with an image digest identical to its original verified upload. Schedules,
budgets, pacing and claim rules are unchanged.

Mission incomplete. The SNKR compression canary PASSED. daily-v1 activation
stopped at a safeguard and was rolled back. Next step: a bounded tooling fix,
then re-activation.

## What happened

| Time (UTC) | Event | Evidence |
|---|---|---|
| 09:10:05 | SNKR verified upload f3286a0a redeployed (owner-authorized) → 18f66771, reported 1b1b64d. Runtime adoption verified on the 09:28 turn | `snkr-attested-restore.json`, `snkr-component-replay-852ccdc.json` |
| 09:37 | PR #83 merged (852ccdc): `scripts/collector_variables.py` safe path, re-pinned `scripts/snkr_storage_canary.py`, verifier resolution of skipped API builds. Railway SKIPPED all services. Delivery verify FAILED: the SNKR component check still read `api_sha: merge` as head | `ci/pr83-pr84-failure-excerpts.log` |
| 10:07 | PR #84 merged (7501143): component checks use the verifier's resolved API SHA. Delivery FAILED: the Vercel build errored on a transient Google Fonts fetch (`next/font/google` Fraunces). The alias stayed on 852ccdc. Not retried manually | same |
| 10:36 / 10:47:55 | PR #85 merged (f05facf): session-4 handoff, docs only. **Delivery GREEN.** Scope `skip` (18 files), no rollout or migration, all Railway services SKIPPED. `api_expectation` = skip → 1b1b64d. Component checks passed, frontend READY, 0 timeout retries | `ci/pr85-staging-delivery.json` |
| 10:57, 11:27 | Natural SNKR turns, writer OFF (baseline: 18 attempts in ~3.5 min; 19 attempts in ~4 min) | `canary/verify-canary-1157.json` context |
| 11:36:38 | SNKR writer ON (canary) via the safe path → 0edb80c6. Same image digest, marker preserved | `canary/snkr-writer-on-*.json` |
| 11:57–12:00:42 | **Canary turn** | `canary/verify-canary-1157.json` |
| 12:04:38 | SNKR writer OFF via the safe path → f05146ff SUCCESS | `canary/snkr-writer-off-*.json` |
| 12:08–12:18 | daily-v1 activation: SNKR and Yuyu 0,1,2,3,5 OK (identical digests). **Shard-6 refused**: Railway rebuilt the upload, so the digest became 9476… instead of the original 3abc…. The writer was on, but the image was not byte-identical | `daily/activation.log` |
| 12:21–12:30:50 | Rollback per the preflight trigger. 6 services via the tool. Shard-6 via an explicit redeploy of original upload 4b56336b, which restored digest 3abc…. All OFF | `daily/rollback.log`, `daily/shard6-rollback.json` |

## SNKR canary: PASS (MEASURED, `canary/verify-canary-1157.json`)

| Measure | Result |
|---|---|
| Encoded rows | 36 of 36 HTTP-200 SNKR bodies. 0 admission skips |
| Lossless check | Every row reconstructs exactly. Two independent decoders were used (a separate zstd path and the package decoder). Each matched the ledger SHA/length and the snapshot content_hash. Each base was older plaintext with the same URL, source and parser |
| Logical size | 31,229,577 B → 631,330 B encoded |
| Physical size | 631,330 B stored vs 4,011,228 B for the TOAST-compressed plaintext bases. **About 84% saved** |
| Runtime | 18 attempts in ~181 s (OFF baselines ~3.5–4 min). Limit was 293 s + 10 s |
| Requests | 2,882 (OFF turn 10:57: 2,959). No added requests |
| Lookup | Writer scope query: EXPLAIN ANALYZE 0.05–0.5 ms, ≤34 buffers |
| Denials / leases | 0 denials, 0 expired claims, 0 open attempts |
| Ledger | 16 → 52 (global canary cap 200) |

Partial daily-v1 window: 16 Yuyu encodings, all lossless (3,536,223 → 25,456 B).
Ledger is now 68 (`daily/verify-partial-daily-v1.json`). The recovery selection
for these is ids > 37661.

## Why daily-v1 is not active (the next fix)

`collector_variables.change` redeploys with `usePreviousImageTag:false`. Railway
usually reuses the cached image, so the digest matches, but not always. It
rebuilt shard-6, and the tool's post-deploy digest check refused. The check is
correct: it caught a real non-determinism.

**Proposed fix for next session (GREEN tooling PR):**
1. Redeploy with `usePreviousImageTag:true` for variable-only changes, so Railway
   reuses the exact image.
2. Move the digest check to before the redeploy can go live, if the API allows,
   or keep it after and auto-redeploy the original upload on mismatch.
3. Rollback must target the original verified upload, not the active clone. The
   shard-6 rollback did exactly this.
4. Trial: one shard, OFF→OFF (no flag change), outside its turn. Confirm the digest
   is unchanged. Then run daily-v1 on all 10.

`tools/daily_v1.py` is the turn-aware driver used here. It redeploys only when the
service has no open attempt and its next turn is ≥4 min away. The admin-login
helper's collector refusal is deferred to the next collector release, because
`services/api` is a collector image input.

## Yuyu request capacity (carried forward from session 4, MEASURED there)

| Measure | Value |
|---|---|
| Requests per capture | 55.4 (homepage warm-up + product page and all their sub-resources). 2 documents are needed |
| 30-min windows, mean | 35.8% of the 9,000-request envelope |
| 30-min windows, peak | 97.2% (05:23Z) |
| Windows >80% | 5 (03:23–05:53Z) |
| Windows >95% | 2 |

NEW100 cannot be approved on request capacity until this is reduced. **The next
capacity workstream after storage:** measure reusing one warmed browser per turn,
and safe blocking of non-document requests. Do not change source pacing or make
traffic look less like a normal visitor.

Also observed: SNKR used 2,882 of 3,100 (93%) of its window in a single turn.
This is pre-existing (the OFF turn was similar). Note it before any SNKR
expansion.

## State (MEASURED 12:31Z, `CURRENT_STATE-end.yaml`)

**Coverage** (12:10Z):

| Measure | Value |
|---|---|
| Mapped | 2,635 |
| Operational | 2,630 |
| Fresh usable | 2,398 |
| Both sources | 334 |
| Zero source | 1,681 |

Unchanged.

**Storage:**
- Volume: 3,480.95 MB / 10,000. DB: 2,626,647,743 B. raw_snapshots:
  2,479,603,712 B.
- Growth vs 08:45Z (3.8h window): +32.8 MB volume, about 208 MB/day. This
  includes 52 encoded rows.
- Forecast not recomputed; it needs 24h of daily-v1 evidence. CARRIED FORWARD:
  14.5–16.4 days to the 3 GiB reserve.

**Due-work:**

| Source | ≤23h | 23–24h | >24h | Due | Overdue | Never checked | Backoff | Claimed | Expired | Quarantined |
|---|---|---|---|---|---|---|---|---|---|---|
| Yuyu | 2,563 | 53 | 0 | 53 | 0 | 0 | 0 | 0 | 0 | — |
| SNKR | 287 | 0 | 44 | 66 | 66 | 22 | — | 0 | 0 | 66 (blocked identity quarantine, unchanged) |

## Quiet windows (no collector redeploys)

1. **2026-10-09 02:00–06:00Z (10:00–14:00 MYT):** PR80 claim-wait busy window.
   Any daily-v1 activation must finish by **01:15Z (09:15 MYT)**, or start after
   **06:00Z (14:00 MYT)**.
2. **daily-v1, once activated:** 24h from the last service activation. Rollback
   only.
3. No canary window is open.

## Next session

Earliest: any time before 2026-10-09 00:00Z for the tooling fix. Activation must
finish by 01:15Z, or wait until after 06:00Z (14:00 MYT).

1. Re-read live state. Confirm all writers OFF, ledger 68, all collectors on
   marked uploads with the digests in `daily/` receipts.
2. Tooling PR: implement the fix above, with tests (docs/tooling only, no
   collector redeploy). Deliver via the normal path.
3. One-shard OFF→OFF trial. Confirm the digest is unchanged.
4. Run the daily-v1 AMBER preflight (reuse `daily/daily-v1-preflight.json`;
   recovery selection is ids > 37661). Activate all 10, confirm, then start the
   24h observation. Recompute 30/90d only after 24h.
5. Land this session's handoff if not landed, and the next one via the docs-only
   path.

Never replay: SNKR 3676/3677, RAW recovery 35175, Yuyu canary evidence, PR77–85
deliveries.
