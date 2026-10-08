# Capacity / RAW75 — session 6 handoff (2026-10-08)

STAGING ONLY. Production RED, untouched. PSA10 OFF.

**daily-v1 is ACTIVE on all 10 collectors.** This is a deliberate, complete
activation; no partial state. Each collector runs its original verified 1b1b64d
upload image, with the original digest and exact-commit marker. Schedules,
budgets, pacing and claim rules are unchanged.

**24h observation window:**

| | UTC | MYT |
|---|---|---|
| Start (last activation) | 2026-10-08 13:56:11Z | 21:56 |
| End | 2026-10-09 13:56:11Z | 21:56 |

No collector redeploys inside the window except rollback.

## Done

1. **PR #87** merged at 7aa130b (13:27:08Z).
   - Change: `collector_variables` redeploys with `usePreviousImageTag:true`. It
     pins the original digest (`--expect-digest`), rolls back automatically to the
     original upload on any mismatch, and has an explicit `--restore` path. Every
     check is kept.
   - Tests: 137 in `scripts/tests`.
   - Delivery GREEN at 13:40:10Z: scope `full` (code), **no collector rollout**,
     Railway SKIPPED every service, `api_expectation` = skip → 1b1b64d, component
     checks passed, 0 timeout retries (`ci/pr87-staging-delivery.json`).
2. **Railway semantics.** The flag is undocumented in Railway's docs and CLI, so its
   behaviour was observed directly.
   - `usePreviousImageTag:false` schedules a build every time. Session-5 redeploys
     show 43–189 build-log lines; shard-6 954d0f1d rebuilt with a new digest.
   - `usePreviousImageTag:true` scheduled **no build**: 0 build-log lines on all 12
     redeploys this session.
3. **No-op trials** (OFF→OFF, 13:42Z):

   | Shard | Deployment | Digest before → after | Build-log lines |
   |---|---|---|---|
   | shard-6 | 39ea662f | 3abc… → 3abc… | 0 |
   | shard-1 | b48443f8 | aa73… → aa73… | 0 |

   Values read back intact (`trial/`).
4. **Config made consistent.** `APP_ENV=staging` was added to shards 4-v2, 7 and 8
   in the same verified change as activation. All 10 now read
   `ENABLED=true, MODE=daily-v1, APP_ENV=staging`
   (`daily/flags-after-activation.json`).
5. **daily-v1 activation** (`daily/activation.log`, per-service receipts in
   `daily/on-ok-*.json`). AMBER preflight: `daily/daily-v1-preflight.json`.

| Service | Activated (UTC) | Deployment | Digest (= original) |
|---|---|---|---|
| snkrdunk-collector | 13:45:05 | 13a65aff | 521ab4aa… |
| yuyutei-collector-shard-0 | 13:46:16 | b64110bb | db319645… |
| shard-1 | 13:47:37 | 00f7e0fa | aa73054a… |
| shard-2 | 13:48:46 | 69ff7905 | 67dcc4fb… |
| shard-3 | 13:50:06 | 7ddbd0f3 | 388d56bf… |
| shard-5 | 13:51:20 | 73702e82 | a2fcc0a4… |
| shard-6 | 13:52:42 | 64b19323 | 3abc15a2… |
| shard-7 | 13:53:46 | 6eaf9275 | 8f0649eb… |
| shard-8 | 13:55:17 | ce27c4a0 | 2040bf9d… |
| shard-4-v2 | 13:56:11 | a2e21e1e | 94987582… |

## First natural turns (MEASURED, `daily/verify-first-turns.json`)

**SNKRDUNK 13:57 turn: PASS.**
- 34 of 34 bodies encoded.
- **All lossless**: independent zstd and the package decoder agree with the ledger
  SHA/length and the snapshot hash, with 0 failed checks.
- Size: 29,584,063 B original → 638,297 B encoded, against ~3,838,958 B physical
  plaintext (about 83% saved).
- Runtime: 166 s, against the writer-off baseline of avg 172 s / max 192 s
  (`daily/baseline-writer-off-turns.jsonl`).
- 0 denials, 0 expired leases, 0 open attempts. Lookup 0.05–0.19 ms.
- Ledger: 68 → 102.

**Yuyu: no qualifying turn yet.**
- The shard turns after activation (shards 7, 8, 0, 1) did only recurring
  **discovery** work (`yuyutei-recurring-discovery-v1`). That parser is not
  writer-eligible, so 0 encodings is expected.
- The last Yuyu refresh capture was at 13:23:59Z. The next refresh items fall due
  from **19:00Z** (8), then the 20:00Z hour (42), 21:00Z (136) and 22:00Z (35).
- Yuyu daily-v1 encoding was already proven lossless today: 16 rows in session 5's
  12:08–12:30Z window, same code and mode.
- **Session 7 must verify the first Yuyu `yuyutei-collector-v3` writer turn first:**
  `tools/verify_canary.py <19:00Z> <now> 37711 out.json`. Repoint its
  `/workspaces` paths to the new worktree.
- On any lossless or integrity failure, roll back all 10 with `tools/rollout.py off`
  (rollback is allowed in the window).

## What session 7 must measure (after 2026-10-09 13:56:11Z)

1. **Physical growth per day** vs the 208 MB/day baseline (session 5, 3.8h window).
   Use the 24h volume and DB deltas from activation (pre-activation volume
   3,477.68 MB at 13:43Z; DB 2,641,794,751 B; raw 2,492,243,968 B).
2. **Per-collector savings:** encoded vs plaintext bytes by source/shard; admission
   skips (captured HTTP-200 eligible bodies not encoded, and why: no base, savings
   threshold, lock contention, daily cap 8,192 rows / 32 MiB).
3. **Lossless samples:** every new ledger row since id 37711, by two decoders.
4. **Runtime** per shard vs the writer-off baseline.
5. **Freshness:** Yuyu ≤23h/24h, SNKR due/overdue unchanged apart from quarantine.
6. **PR80 claim behaviour** in the 2026-10-09 02:00–06:00Z busy window: peak ≤4
   concurrent Yuyu claims, no excess claims, waits bounded (≤6×5s).
7. **Recompute 30/90-day forecasts** with the 3 GiB reserve and the 887,045,884-byte
   NEW100 image bound, only after a full 24h of evidence.

## State (MEASURED 14:11–14:12Z, `CURRENT_STATE-end.yaml`)

**Coverage:**

| Measure | Value |
|---|---|
| Mapped | 2,635 |
| Operational | 2,630 |
| Fresh usable | 2,398 |
| Both sources | 334 |
| Zero source | 1,681 |

Unchanged.

**Storage:**
- Volume: 3,487.03 MB / 10,000. DB: 2,649,028,287 B. raw_snapshots:
  2,498,994,176 B.
- Since 08:45Z (5.45h window): +38.8 MB, about 171 MB/day. Short window, mostly
  writer-off.
- Forecast: not recomputed.

**Due-work:**

| Source | ≤23h | 23–24h | >24h | Due | Overdue | Never checked | Backoff | Claimed | Expired claims | Quarantined |
|---|---|---|---|---|---|---|---|---|---|---|
| Yuyu | 2,616 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | — |
| SNKR | 267 | 20 | 44 | 86 | 66 | 22 | 0 | 0 | 0 | 66 (blocked identity quarantine, unchanged) |

## Quiet windows (no collector redeploys)

1. **2026-10-09 02:00–06:00Z (10:00–14:00 MYT):** PR80 busy window.
2. **daily-v1 observation:** until **2026-10-09 13:56:11Z (21:56 MYT)**. Rollback
   only.
3. **Onchain Phase 1 plan** (`plan/onchain-phase1`, a4cf278): any change under
   `services/api/` breaks SNKR continuity (`SNKR_PATHS` includes `services/api`),
   so it is a **collector release**. The earliest time such releases can resume is
   **2026-10-09 13:56:11Z (21:56 MYT)**, and later only if session 7's 24h
   evidence passes. Docs-only merges remain fine (scope `skip`).

## Carried forward (not built)

- **Yuyu request efficiency:** ~55 requests per capture, 97% peak window. This is
  the next capacity workstream after storage.
- **Admin-login helper:** add a collector refusal in the next collector release.
- **Fonts:** self-host frontend fonts. A Vercel build failed on a Google Fonts
  fetch (PR #84).
- **SNKR window:** ~93% of the 3,100-request window used in one turn (session 5).

Never replay: SNKR 3676/3677, RAW recovery 35175, Yuyu canary evidence, completed
deliveries (PR77–87).
