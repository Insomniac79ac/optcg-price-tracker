# Capacity / RAW75 — session 7a morning check (2026-10-08 22:06–22:20Z)

STAGING ONLY, read-only. Production untouched. PSA10 OFF. **Result: CLEAN. Nothing changed.**
No rollback, no collector redeploy, no job triggered.

The daily-v1 observation window is still open until **2026-10-09 13:56:11Z (21:56 MYT)**.
The PR80 busy window is 2026-10-09 02:00–06:00Z (10:00–14:00 MYT).

All numbers are MEASURED. Sources are under `evidence/`, produced by the read-only tools in `tools/`.

## 1. Live state (`evidence/live-state.json`, 22:06:47Z)

All 10 collectors match their activation state:
- Latest deployment = the activation deployment, status SUCCESS.
- Image digest = the original digest.
- `ENABLED=true`, `MODE=daily-v1`, `APP_ENV=staging`.

The only deployment records created since activation are 10 **SKIPPED** records at
14:30:47–48Z. These are the PR #88 docs-only merge: watch paths skipped every service, so
nothing was built or activated. Every run event since each shard's activation reports its
activation deployment id and revision 1b1b64d (`census.json` `runs_post_activation`).

## 2. Lossless verification (`evidence/verify-since-activation.json`)

`verify_canary.py 13:45:05Z → now, ledger id > 37711`, repointed to this worktree. It checked
**517 rows** (ids 37937–38494).

- Every check passed on every row: encoded, same-scope older plaintext base, base hash,
  envelope base id, independent zstd SHA and length, package decoder equal to the independent
  decoder, encoded bytes, HTTP 200.
- `all_lossless=true`. No expanded rows.

| Collector | Rows | Fetched (UTC) | Original B | Encoded B | Plaintext-col B (base) | Saved vs plaintext col |
|---|---|---|---|---|---|---|
| snkrdunk | 364 | 13:58–18:59 | 315,561,672 | 11,687,442 | 42,240,656 | 72.3% |
| yuyu shard-0 | 22 | 21:04–21:35 | 4,924,743 | 33,308 | 814,279 | 95.9% |
| shard-1 | 24 | 20:38–22:04 | 5,341,898 | 36,376 | 884,102 | 95.9% |
| shard-2 | 9 | 21:37–22:09 | 2,006,795 | 13,994 | 332,393 | 95.8% |
| shard-3 | 17 | 21:11–22:11 | 3,776,388 | 26,426 | 625,930 | 95.8% |
| shard-4-v2 | 8 | 21:16–21:17 | 1,789,480 | 11,900 | 296,253 | 96.0% |
| shard-5 | 16 | 21:49–21:52 | 3,527,819 | 22,904 | 586,109 | 96.1% |
| shard-6 | 20 | 20:20–21:52 | 4,431,230 | 27,036 | 732,395 | 96.3% |
| shard-7 | 14 | 21:24–21:27 | 3,124,939 | 25,648 | 514,286 | 95.0% |
| shard-8 | 23 | 20:25–21:28 | 5,101,580 | 35,342 | 846,407 | 95.8% |

The first Yuyu `yuyutei-collector-v3` writer row was fetched at 20:20:01Z (shard-6). It is
verified lossless. All 10 collectors have now encoded under daily-v1.

## 3. Runtime and safety (`census.json`; runs counted from each shard's activation)

| Collector | Runs | Runs with work | Avg work-run s | Max s | Writer-off baseline avg / max s |
|---|---|---|---|---|---|
| snkrdunk | 17 | 11 | 155.5 | 180.6 | 172 / 192 |
| shard-0 | 17 | 3 | 107.9 | 140.5 | 134 / 165 |
| shard-1 | 17 | 4 | 73.3 | 81.2 | 105 / 125 |
| shard-2 | 17 | 2 | 41.7 | 73.1 | 110 / 170 |
| shard-3 | 16 | 1 | 186.7 | 186.7 | 122 / 149 |
| shard-4-v2 | 16 | 1 | 75.9 | 75.9 | 132 / 188 |
| shard-5 | 16 | 1 | 140.7 | 140.7 | 109 / 301 |
| shard-6 | 16 | 3 | 68.6 | 94.4 | 124 / 138 |
| shard-7 | 16 | 1 | 205.7 | 205.7 | 123 / 139 |
| shard-8 | 17 | 3 | 73.9 | 142.7 | 133 / 177 |

Shard-3 (186.7 s, 16 items) and shard-7 (205.7 s, 14 items) ran above their own writer-off
max. Both are well inside the 1,200 s limit.

- **Like-for-like:** full 16-item Yuyu turns average 152.7 s under daily-v1 (4 turns), against
  155.5 s writer-off over the prior 56h (239 turns).
- **Per item:** 8.23 s under daily-v1 against 7.49 s writer-off.
- **Shard-7 21:24Z turn:** items took 10.9–13.5 s while shard-8 ran concurrently. The writer
  uses a non-blocking try-lock, so this is not lock waiting.
- Session 7 should keep watching per-item runtime.

**Safety, all zero:**
- 0 `source_denial` and 0 other failure outcomes.
- run counters http_403/429, challenge, transient, parsing, identity, unexpected_skip: all 0.
- 0 expired claims, 0 reservation overruns, 0 duplicate requests, 0 wrong-shard.
- 0 runs not completed.
- Claims at 22:12Z: 0 (Yuyu and SNKR); expired 0; open attempts 0.

**Claims:** peak concurrent Yuyu claims since activation was 2 (limit 4).

**Admission skips:** 3 Yuyu writer-eligible HTTP-200 bodies stayed plaintext. 0 for SNKR.
- Rows 38417 (shard-8, 21:26:55Z), 38440 and 38442 (shard-0, 21:34Z).
- Each had a plaintext base in scope, would have passed the savings threshold (about 2.0 KB
  packed against about 37 KB base), and was under the daily cap. Another shard encoded a row
  within ±0.1 s of each one.
- So the cause was **try-lock contention**, the designed fail-open path. Hashes are intact.
  Not an integrity issue (`evidence/admission-skips.json`).

46 `yuyutei-recurring-discovery-v1` bodies are not writer-eligible, as expected.

## 4. Due-work (`census.json`, 22:12Z, kind=refresh)

| Source | ≤23h | 23–24h | >24h | Never checked | Due | Overdue | Backoff | Claimed | Expired claims | Blocked (quarantine) |
|---|---|---|---|---|---|---|---|---|---|---|
| Yuyu (unblocked 2,616) | 2,557 | 59 | 0 | 0 | 59 | 0 | 0 | 0 | 0 | 3 |
| SNKR (unblocked 287) | 287 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 66 |

**Yuyu:**
- The 59 due items are the 23–24h band. They are pending and are claimed by the next turns.
- The 3 blocked items are 2026-10-06 mission-containment items (inactive mappings). They are
  excluded from the session-6 Yuyu table (2,616). Two are >24h and one was never checked.

**SNKR:**
- The 66 blocked items are the unchanged identity quarantine: 44 >24h and 22 never checked.
  Session 6's "overdue 66" were these items.
- Session 6's 20 items in the 23–24h band have since been refreshed.
- No unblocked SNKR work is due, so SNKR turns since 18:59Z have claimed nothing. That is
  expected.

## 5. Storage (`census.json` volume and db)

- **Window:** 13:43:29Z (pre-activation) → 22:12:37Z = **8 h 29 m**.
- **Volume:** 3,477.68 → **3,568.06 MB / 10,000** = **+90.38 MB**.
- **DB:** 2,641,794,751 → 2,709,567,167 B (+67,772,416). raw_snapshots: 2,492,243,968 →
  2,555,740,160 B (+63,496,192).
- Forecasts were not recomputed. Session 7 does that with the full 24h.

## Next

Session 7 runs the full 24h assessment after **2026-10-09 13:56:11Z (21:56 MYT)**, following
the session-6 HANDOFF list. This includes the PR80 busy-window claim behaviour
(02:00–06:00Z) and the Yuyu per-item runtime noted above.
