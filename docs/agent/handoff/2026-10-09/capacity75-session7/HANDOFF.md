# Capacity / RAW75 — session 7 handoff (2026-10-09, 14:20Z–)

STAGING ONLY. Production RED, untouched. PSA10 OFF. No source job triggered, no mapping
approval, no NEW100, no SNKRDUNK discovery. No collector redeploy.

Every number below is **MEASURED** (source under `evidence/`, produced by the read-only tools in
`tools/`) unless it is marked CARRIED FORWARD or ESTIMATE.

## 0. Preconditions (`evidence/live-state.json`, 14:20:53Z)

The session started at 14:20Z, after the daily-v1 window ended at 13:56:11Z.

All 10 collectors are as they were at activation:
- The latest deployment is the activation deployment, status SUCCESS.
- The image digest is the original digest.
- `ENABLED=true`, `MODE=daily-v1`, `APP_ENV=staging`.

The only records created since activation are 30 SKIPPED records, from the PR #88, #89 and #90
docs merges. Every post-activation run reports its activation deployment id
(`census.json` `runs_post_activation`).

The start state is in `CURRENT_STATE-start.yaml`. The blockers are unchanged: freshness-deadline
deficit, SNKR identity quarantine and deployment-provenance divergence.

## 1. Is physical growth lower? Yes, materially, with caveats

### A. Where the 7a gap came from (`evidence/attribution.json`)

The writer `INSERT`s each new snapshot as **plaintext** first, so Postgres TOAST-compresses and
stores it. Only then does it `UPDATE` the row to the encoded envelope
(`raw_dictionary_storage._encode_new_snapshot`: `session.flush()` comes before
`_stored_raw_content = packed`).

The plaintext TOAST chunks become dead tuples. Their space is reusable only after autovacuum.
The raw_snapshots TOAST relation shows this: `n_tup_del` 88,495, `n_dead_tup` 14,234, and the
last autovacuum ran at 2026-10-09 11:03:03Z (90 autovacuums in total).

| Segment | raw_snapshots growth | New rows' stored bytes | Dead plaintext TOAST written (base-size proxy) | Balance |
|---|---|---|---|---|
| 13:43Z → 22:12Z (7a) | +63,496,192 B | 13.59 MB (SNKR 11.69, Yuyu 0.36, discovery 1.55) | 48.09 MB (SNKR 42.24, Yuyu 5.85) | 61.7 MB of 63.5 MB explained (97%); the rest is heap, index and chunk overhead. No vacuum in the segment. |
| 22:12Z → 14:24Z | +32,530,432 B | 16.27 MB | 119.08 MB | Vacuum ran (11:03Z). About 103 MB of dead space was reused, so the relation grew by roughly 2× the new live bytes. |
| Full 24h41m | +96,026,624 B (93.3 MB/day) | 29.9 MB | 167.2 MB | — |

So 7a's ~12 MB encoded vs ~63 MB growth gap is the transient plaintext, not the encoding. It
stays in the relation until vacuum, then gets reused.

**Plaintext alongside encoded:** no. The encoded rows store only the envelope:
`pg_column_size` equals `octet_length` of the envelope, because pglz does not compress base64.

**Indexes:** 13.4 MB in total; the dictionary scope index is 5.2 MB. The heap is 10.9 MB.

**By collector, 24h new stored bytes:**

| Collector | Rows | Stored |
|---|---|---|
| SNKR homepage (`https://snkrdunk.com/`, no attempt link) | 304 | 18.81 MB |
| SNKR item pages | 304 | 1.27 MB |
| Each Yuyu shard (v3) | ~290 | 0.48–0.52 MB |
| Yuyu discovery (not writer-eligible) | 102 | 3.69 MB |

**By kind (24h, stored column bytes):**

| Kind | daily-v1 | Writer-off day before (13:45Z → 13:45Z) |
|---|---|---|
| SNKR v2 | 20.08 MB | 64.45 MB |
| Yuyu v3 | 4.72 MB | 95.60 MB |
| Yuyu discovery | 3.69 MB | 4.79 MB |
| **Recurring total** | **28.5 MB** | **164.8 MB** |

New-row stored bytes are **−83%**. The day before also had 18.4 MB of one-off
`snkr-published-discovery-v1`.

### B. SNKR physical vs TOAST

The premise that "72% was measured against logical" does not hold:
- 7a's "Plaintext-col B (base)" column is `pg_column_size` of the base, which is the
  **TOAST-compressed physical size**.
- Comparing like for like, the 644 SNKR encoded rows store 21.36 MB. The same URLs' pre-activation
  writer-off plaintext has a median stored size of 73.40 MB. **daily-v1 is 71% smaller
  physically** (96% vs logical).

**Why the canary reached 84% and today reaches 70% (vs base physical):** base freshness.
- Hourly series: 11:00–14:00Z on 10-08 saved 81–84% with base age about 0.5 days. From 15:00Z,
  70–71% with base age 3.4–4.0 days. Average logical page size was unchanged at ~866 KB.
- The cause is the SNKR homepage. It is captured once per SNKR attempt (~304/day), so its 32
  most-recent scoped rows are all encoded within hours. Base selection then falls back to the
  **oldest** plaintext anchor (bases from 2026-10-02 to 10-08).
- Its delta is 35% of base (65 KB per capture), against 9–12% for item pages with day-old
  bases.

### C. Yuyu physical vs TOAST

- 2,609 encoded rows store 4.46 MB. The same-URL pre-activation median is 100.51 MB, so Yuyu is
  **96% smaller physically**. Base age is about 1 day.
- 7 eligible bodies stayed plaintext (0.26 MB). See section 2.

### D. Volume vs database

**24h growth:**

| Measure | Window | Growth |
|---|---|---|
| Volume, CLI `current_mb` | 13:43Z → 14:27Z | +120.25 MB |
| Volume, hourly series ×1.024 | 14:00 → 14:00 | +99.7 MB |
| Database | 13:43Z → 14:24Z | +112.59 MB (raw 96.03, other tables 16.56) |

**Writer-off day before (volume, hourly series):** +228.9 MB.

**What else is on the volume (~840 MB beyond `pg_database_size`):**
- WAL is 84 MB on disk now (5 segments, `pg_ls_waldir`). `max_wal_size` is 1 GB, and there is
  no archiving and no replication slot, so WAL fluctuates but does not accumulate.
- Temp files total 261 MB lifetime. They are transient.
- The other databases total 23 MB.
- The rest is filesystem and cluster overhead (pg_xact, catalogs) that the database size does
  not count.

The volume tracks the database within noise.

**Other-table growth:** 16.6 MB/day. `source_mapping_proposal_groups` is 50.5 MB with 4,655
dead tuples.

## Storage verdict: **PASS**, keep daily-v1 on

Both sources are physically smaller than TOAST, and growth is materially lower.

**Growth rates (`evidence/forecast.json`):**

| Measure | Full 24h | Since 7a (16.2h, post-vacuum steady) |
|---|---|---|
| Volume | 116.7 MB/day | 44.1 |
| Database | 109.4 | 66.4 |
| raw_snapshots | 93.3 | 48.2 |

The full-24h volume rate (116.7 MB/day) is down 44% from the 208 MB/day baseline (CARRIED
FORWARD) and 49% from the prior 24h measured here (228.9). Payload growth fell to 28.5 MB/day
from the 172 MB/day recurring baseline (CARRIED FORWARD).

**Forecast.** Volume 3,597.9 MB of 10,000; 3 GiB reserve = 3,221.2 MB; 3,180.8 MB room to the
reserve.

| Rate | Days to reserve | Days to full | 30d volume | 90d volume |
|---|---|---|---|---|
| Conservative, 116.7/day | **27.3 (≈ 2026-11-05)** | 54.8 | 7,100 MB (reserve breached) | 14,103 MB (does not fit) |
| Steady, 66.4/day | **47.9 (≈ 2026-11-26)** | 96.4 | 5,590 MB | 9,573 MB (reserve breached at day 48) |

**NEW100 needs** the 887.0 MB image bound plus, worst case all-SNKR, about +6.9 MB/day (ESTIMATE
from measured per-row sizes).

| Rate | Days to reserve | Need for 30d (incl. reserve) | Need for 90d (incl. reserve) |
|---|---|---|---|
| Conservative | 19.7 | 11,415 MB | 18,832 MB |
| Steady | 34.6 | 9,905 MB | 14,302 MB |

**The verdict does not allow NEW100 on a 90-day basis.** It needs 4.3–8.8 GB more headroom, or
the growth reductions below. NEW100 is not approved.

**Remaining growth drivers, in order:**
1. Transient plaintext TOAST from insert-then-update: ~167 MB/day written, reclaimed only by
   vacuum.
2. The SNKR homepage, 18.8 MB/day: 66% of all new stored bytes, because of the oldest-anchor
   fallback.
3. Other tables: 16.6 MB/day.

**Not fixed this session.** Each fix is a collector release (an AMBER redeploy of all 10), and
the verdict is PASS. Proposals for session 8:
- (a) Encode before the first INSERT.
- (b) Re-anchor high-frequency URLs: keep a plaintext anchor when the base is older than about
  1 day, or when the recent window is fully encoded.
- (c) Measure the per-attempt SNKR homepage request together with the Yuyu request-efficiency
  work.

## 2. Other 24h evidence

**Lossless** (`evidence/verify-since-activation.json`, `tools/verify_all.py`):
- **Every** daily-v1 ledger row was checked: 3,253 rows, ids 37937–41328 (SNKR 644, Yuyu 2,609).
- Each was checked by the independent zstd decoder and the package decoder, against base hash,
  scope, envelope base id, SHA, length and encoded bytes.
- **0 failures, 0 expanded.** No rollback.

**Runtime** (`census.json` plus queries; full-turn window 13:56:11Z → 13:56:11Z, 432 Yuyu runs):

| Measure | Writer off (48h) | daily-v1 (24h) |
|---|---|---|
| Yuyu captured attempts, avg | 7.97 s | 8.62 s (+8%) |
| Yuyu captured attempts, p95 | 9.68 s | 11.61 s |
| Full 16-item turns | 155.7 s (233 turns) | 156.3 s (123 turns) |
| Busy-window full turns | — | 155.4 s (57) |
| Yuyu max | — | 215.9 s (limit 1,200) |
| SNKR work turn avg / max | 172 / 192 s (CARRIED FORWARD) | 159.4 / 180.6 s |

- Turn wall-clock is unchanged; the per-attempt increase is absorbed.
- Utilisation: 49 runs × 16 = 784 claimable per shard per day, against ~291 due.
- **Not a threat** to the 23h dispatch at current or NEW100 load (+100 items ≈ +11/shard/day).

**Admission skips** (`evidence/admission-skips.json`):
- 7 in 24h, all Yuyu, 0 SNKR: rows 38417, 38440, 38442, 40176, 40207, 40429 and 40748.
- Every one had a valid base and passed the savings threshold under the cap, and another shard
  committed a ledger row within 0.03–0.4 s.
- Cause: writer try-lock contention, the designed fail-open path. Hashes are intact.
- Rate: 7 of 3,224 eligible (0.22%), about 0.2 MB/day of extra plaintext.
- At NEW100 volume this projects to ~7–8/day, which is negligible.

**Daily cap:** the rolling 24h used 26.19 MB (78.1% of 32 MiB) and 3,247 rows (39.6% of 8,192).
An all-SNKR NEW100 would put bytes near ~99% of the cap, with the excess falling back to
plaintext.

**Safety, 24h:**
- 0 `source_denial`; 0 403, 429 or challenge.
- 0 expired claims, overruns, duplicates or wrong-shard.
- 0 runs not completed, 0 started without a finish, 0 open attempts.
- 2 Yuyu `transient_failure`s (attempts 16957 and 17416), both requeued for the next cycle.

## 3. Busy window: PR80 claim wait, 2026-10-09 02:00–06:00Z

- 996 Yuyu attempts from all 9 shards.
- **Peak concurrent claims: 3** (cap 4). 12 attempts started at concurrency 3, 0 at 4.
- 0 `active_claim_wait_bound` stops in 494 runs.
- The cap was never reached, so **0 waits occurred and contention was NOT exercised**, again.
- No excess claims and no expired leases.
- The PR80 claim-wait remains naturally untested. It is only reachable when 4 shards overlap.

## 4. Due-work and coverage (14:26–14:32Z)

**Due-work, refresh kind (`census.json`):**

| Source | Unblocked | ≤23h | 23–24h | >24h | Due | Never checked | Backoff | Claimed | Expired | Blocked |
|---|---|---|---|---|---|---|---|---|---|---|
| Yuyu | 2,616 | 2,616 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3 (2 >24h, 1 never; containment, unchanged) |
| SNKR | 287 | 270 | 17 | 0 | 17 | 0 | 0 | 0 | 0 | 66 (44 >24h, 22 never; identity quarantine, unchanged) |

The SNKR budget window at 13:53:57Z used 2,863 of 3,100 requests (92%).

**Coverage (`evidence/coverage-latest.json`):**

| Measure | Value |
|---|---|
| Mapped | 2,635 |
| Operational | 2,630 |
| Fresh usable | 2,399 |
| Both sources | 334 |
| Zero source | 1,681 |
| Duplicate exact-print groups | 0 |
| Open checks >24h | 0 |

Unchanged.

## 5. Fix delivered: collector continuity narrowed (PR #91, AMBER, tooling/CI only)

`scripts/collector_runtime_inputs.py` derives the `services/api` modules each collector imports
from Git objects, taking the union at the installed component and at head. Both component
verifiers use it via `collector_continuity`. The rules are in `docs/agent/STAGING_DELIVERY.md`.
The preflight is `docs/agent/evidence/collector-continuity-preflight-20261009.json`.

**Still fails continuity:** the collector directory, its Dockerfile, the identity package,
imported modules at either commit, package data and packaging/requirements files.

**Falls back to the full path set** on an unreadable commit, a syntax error, an unresolved
`app` import or any dynamic import.

**Proof it is not weaker:**
- 20 tests. Mutation checks: an empty import set fails 11; the old behaviour fails 3.
- The real-import comparison shows nothing missing from the static set: SNKR 58 loaded vs 62
  static; Yuyu 65 vs 73.
- Every historical commit that touched collector runtime code still fails
  (`evidence/continuity-narrowing-examples.json`).

**What it unblocks:** the parked auth fix 1bae1c2 (`app/api/market.py`) now passes continuity,
so it is **no longer a collector release**. It still needs its own delivery session; see that
prompt.

**CI:** the SNKR and Yuyu verifier tests, which previously ran in no CI job, now run in
`agent-state-tests`.

**PR #91 result: merged d4e1b88 at 14:57:32Z.**
- All CI checks passed, including `agent-state-tests` with the new tests.
- staging-automerge delivery was **green**, verified at 15:09:17Z:
  - scope `full`, **no collector rollout requested**;
  - `api_expectation` = skip on 1b1b64d;
  - both component checks pass on 1b1b64d.
  - Receipt: `evidence/pr91-staging-delivery.txt`.
- Live re-read at 15:10:11Z (`evidence/live-state-end.json`):
  - all 10 collectors are still on their activation deployments with original digests, writers
    on daily-v1;
  - the only new records are SKIPPED.

End state: `CURRENT_STATE-end.yaml` (15:10:53Z). Blockers are unchanged.

## Quiet windows

| Window | Status |
|---|---|
| daily-v1 observation | **Ended** 2026-10-09 13:56:11Z (21:56 MYT) |
| Busy window, 02:00–06:00Z daily (10:00–14:00 MYT) | Avoid collector redeploys. Not a formal window now. |
| API-only changes | No longer collector releases once PR #91 is delivered, unless they touch an imported module, package data or packaging |

There is **no active quiet window** as of this handoff.

## Next session (8): `docs/agent/handoff/2026-10-09/capacity75-session7/`

1. Re-read live state.
   - Confirm all 10 collectors are still on their activation digests and PR #91's delivery
     receipt is green with 0 rollout.
   - Regenerate CURRENT_STATE.
2. **Next workstream: Yuyu requests per capture.** About 55 requests against 2 documents, with a
   97% peak budget (CARRIED FORWARD). Include the SNKR homepage-per-attempt request (2,863/3,100
   at 13:53Z).
3. Storage follow-ups (collector release, AMBER):
   - (a) encode before the first INSERT;
   - (b) re-anchor high-frequency URLs (the SNKR homepage);
   - (c) bloat in `source_mapping_proposal_groups`.
4. **Runway:** 27–48 days to the 3 GiB reserve (≈ 2026-11-05 to 11-26). An owner storage decision
   (growth reduction vs volume resize, which is irreversible) is needed well before then.
5. NEW100 is not allowed by storage until there is ≥4.3–8.8 GB more 90-day headroom.

**Never replay:**
- SNKR 3676/3677
- RAW recovery 35175
- Yuyu canary evidence
- completed deliveries (PR77–87, PR91)

**PSA10:** NOT READY (0 live observations, activation unknown). Not activated.
