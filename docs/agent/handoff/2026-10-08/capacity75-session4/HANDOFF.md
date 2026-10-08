# Capacity / RAW75 — session 4 handoff (2026-10-08)

STAGING ONLY. Production RED, untouched. PSA10 OFF. **All RAW writers OFF at
session end** (verified 08:46Z). Mission incomplete. The SNKRDUNK compression test
did not run: its preflight failed (see "SNKR test").

## Read first: the interruption left a writer ON

- The interrupted session set `RAW_DICTIONARY_STORAGE_ENABLED=true` (`MODE=canary`)
  on `snkrdunk-collector`. No GitHub or handoff record covers it.
- Railway shows deployment `0da9274b` created **07:25:18Z** from GitHub commit
  d42912b6 (`reason=deploy`). That was not CI: PR82's delivery decided `skip` and
  finished 07:22:12Z.
- Found ON 08:35:41Z. Set OFF 08:36:18Z (`snkr-writer-off-preflight.json`). The OFF
  deployment `518080ff` reached SUCCESS 08:37:15Z.
- **No data effect:**
  - Ledger is still 16 rows, newest 2026-10-07T23:06:05Z.
  - 0 SNKR attempts since 05:00Z and 0 SNKR RAW since 07:25Z. Nothing was due before
    10:32:04Z.
- **Side effect that persists:** a plain `railway variable set` on a GitHub-connected
  collector rebuilds from branch HEAD. It does not redeploy the attested
  `railway up` upload. SNKR now runs an **unattested GitHub build**:
  - `reported_sha=unknown`.
  - Service/package code is identical to 1b1b64d:
    `git diff 1b1b64d d42912b6 -- services packages apps/web` is empty.
  - `verify_snkr_published_discovery_component.verify()` REFUSES ("Unexpected
    deployed SNKR source or schedule", run read-only ~08:44Z).
  - Consequence: **every staging delivery, including docs-only, will fail its verify
    step until this is fixed.** That is why this handoff is on a branch, not landed.

## Damage check (Step 0)

1. **PR #81 was already merged.** The resume brief said it was not.
   - Delivery fix: f4b632d at 06:38:15Z. PR82 = d42912b at 07:10:21Z.
   - PR81 delivery: scope=`full`. `collector_services` was undeclared, so the
     collector step was a no-op. Verify FAILED with "Expected native staging
     deployments did not become ready". Cause: the manifest had `api_sha: merge`, but
     Railway SKIPPED the API build, which stayed on 1b1b64d.
   - PR82 delivery: scope=`skip`, verified 07:22:07Z, 0 timeout retries
     (`ci/pr82-staging-delivery.json`).
   - All 10 collectors, the API and market-index have SKIPPED entries for f4b632d and
     d42912b. Yuyu shards are still on the 05:19Z attested uploads (reported 1b1b64d).
     API and market-index are on 1b1b64d. Frontend is on d42912b (READY).
   - SNKR: see above.
2. **Writers:**
   - SNKR was ON and is now OFF.
   - shard-0: `false`.
   - shards 1–8: variable absent (code default false). They also have **no
     `APP_ENV`**. daily-v1 on them would raise `RawPayloadError` until
     `APP_ENV=staging` is set, which is another redeploy.
3. No in-progress Actions runs. No open PRs.
4. 0 expired claims, 0 open attempts, no advisory locks. 1 live Yuyu claim was a
   running shard.
5. **Local state:**
   - /tmp was wiped. All 80+ old worktrees are `prunable`.
   - Main checkout: 3 uncommitted 2026-10-04 edits on
     `feature/collection-freshness-adapters`, plus 1 stash. Left untouched.
   - New durable worktrees are under /workspaces/cp-s4.

## Delivery fix (Step 1)

Already merged (PR81). Audited on staging:
- **Allowlist is fail-closed.** Allowed: `docs/agent/handoff/**` and `docs/**/*.md`.
  Excluded: `STAGING_MISSION.json`, `CURRENT_STATE.yaml`, `docs/agent/evidence/**`.
  Renames, unknown status and empty diffs run `full`. A manifest that requests
  rollout or migration runs `full`.
- **Verifier retries:** timeout only, ≤2 retries (2s, 5s), identical assertion, and
  recorded in `get_timeout_retries`.
- **Tests:** `test_staging_delivery_scope.py` + `test_verify_staging_delivery.py`:
  26 OK.
- **Real use:** PR82 was the first docs-only skip in practice.
- **Follow-up:** script-only PRs must declare `api_sha` explicitly (the PR81 lesson).

## SNKR test (Step 2): PREFLIGHT FAILED, writer OFF

Restoring attestation needs a collector redeploy:
`deploymentRedeploy` of upload `f3286a0a` ("exact commit 1b1b64d",
`canRedeploy=true`), using the same mechanism as
`deploy_staging_collectors.redeploy_uploaded`. This session's permission classifier
denied that action. It was not worked around.

Without attestation, the unweakened SNKR identity check cannot pass, so the writer
stayed OFF. No blind retry. Record: `snkr-canary-preflight-FAILED.json`.

**Required procedure from now on:** writer toggles use
`railway variable set ... --skip-deploys` followed by `deploymentRedeploy` of the
attested upload. Never use a plain variable set.

The old helper `snkr_storage_canary-dcaa478b305e.py` calls a plain set and must be
re-pinned with this change. Pins:

| Item | SHA |
|---|---|
| staging head | d42912b6 |
| SNKR/Yuyu/API component | 1b1b64d |

Add an assertion that the code tree is identical between the two. The helper's
"Wait for two positive turns" rule should become ONE turn, per the mission.

SNKR due timeline: pending items fall due 10:32:04Z–18:01:34Z daily. Any :27/:57
turn in that range has work. 10:27 does not; 10:57 is the first.

## Yuyu request accounting (Step 3, read-only, MEASURED 08:44Z)

- **Per capture:** 55.42 charged requests on average (min 55, max 56), across 2,809
  attempts in 24h. The reservation is 300.
- **What one capture loads** (code read, `collect.py:258-330`, `browser.py:126-187`,
  `freshness_integration.py:225-341`): a fresh headless context per product, the
  yuyu-tei.jp homepage warm-up (403 workaround), then the product page. Waits are
  `domcontentloaded` + 1.5s.
- **What is charged:** every non-aborted sub-request costs 1 (scripts, CSS, XHR,
  iframes, non-ad third-party hosts). Images, fonts, media and listed ad hosts are
  aborted free. No retries, pagination or images.
- **Necessary:** the 2 documents. The rest is sub-resources.
- **Windows** (1800s, anchored to the live budget 08:23:57Z), last 48 windows:

| Measure | Value |
|---|---|
| Mean | 3,224 requests (35.8%) |
| Mean of 35 active windows | 49% |
| Zero windows | 13 (10-07 14:23–20:53Z) |
| Peak | 8,745 (97.2%) at 05:23Z |
| Windows >80% | 5 (03:23, 03:53, 04:23, 05:23, 05:53Z) |
| Windows >95% | 2 (04:23 at 95.4%, 05:23 at 97.2%) |

- **Per shard:** max 16 captures per turn, about 896 requests (10% of the envelope).
  Shards 6 and 7 peaked at 1,109 and 1,708 because two turns fell inside one window.
- **"40%" is an average.** The peak is 97%, and the high windows coincide with the
  02–06Z busy window.
- **Safe reductions for a later session** (regression-tested, AMBER, all lower the
  request count; none alters cadence/budget):
  1. Reuse one warmed context per turn, so the homepage loads once instead of 16
     times. INFERRED to cut per-capture cost by about half.
  2. Abort homepage sub-resources (only cookies are needed).
  3. Abort product-page scripts/CSS after fixture proof that extraction is
     server-rendered.

## Coverage / storage / due-work (MEASURED)

**Coverage** (`coverage-latest.json`, 08:44:50Z):

| Measure | Value |
|---|---|
| Denominator | 4,316 |
| Mapped | 2,635 |
| Operational | 2,630 |
| Fresh usable | 2,398 |
| Both sources | 334 |
| Zero source | 1,681 |
| Remaining to 75% | 607 |

Unchanged since session 3.

**Storage** (Railway metrics, 08:45Z):
- Volume: 3,448.2 / 10,000 MB.
- DB: 2,594,666,175 B. raw_snapshots: 2,448,441,344 B.
- Growth since 05:28Z: +45.4 MB volume and +31.9 MB DB over 3.3h, about 330 and
  230 MB/day. The window is short.
- The forecast was NOT recomputed (daily-v1 was not started). Carried forward:
  3 GiB reserve in 14.5–16.4 days, full in 28–32 days.

**Due-work** (`CURRENT_STATE-start.yaml`, 08:34Z):

| Source | Eligible | ≤23h | 23–24h | >24h | Due | Overdue | Never checked | Quarantined | Backoff | Claims expired |
|---|---|---|---|---|---|---|---|---|---|---|
| Yuyu | 2,616 | 2,570 | 46 | 0 | 46 | 0 | 0 | — | 0 | 0 |
| SNKR | 353 | 287 | 0 | 44 | 66 | 66 | 22 | 66 | — | 0 |

SNKR's >24h, never-checked and quarantined items are all blocked (identity
quarantine). This is unchanged.

**Schedules and budgets:**
- Schedules unchanged: Yuyu 0/3/…/24 +30, SNKR 27,57.
- Budgets: Yuyu 9000/1800s, SNKR 3100/1800s.
- `flags-start.json` vs `flags-end.json` differ only in SNKR ENABLED true→false.

## Quiet windows (no collector-redeploying merges, writer toggles or collector redeploys)

1. **2026-10-09 02:00–06:00Z (10:00–14:00 MYT):** PR80 claim-wait busy-window
   evidence. Peak must be ≤4 claims, with no excess claims.
2. **SNKR canary, once rescheduled:** from 45 min before the chosen :27/:57 turn
   (pick one with due work, 10:57–17:57Z) until the OFF redeploy is SUCCESS. The OFF
   redeploy must finish before the next turn.
3. **daily-v1, once started:** 24h from activation. No collector redeploys.
4. Released: today's 09:45Z–~11:10Z window (the test did not run).

## Next session

Earliest useful re-check: now, if collector-redeploy permission is granted. Otherwise
human decision first.

1. **Human:** allow this agent to perform a staging collector `deploymentRedeploy`
   (classifier category "Production Deploy" fired on a staging action). Or have the
   human run it: redeploy upload f3286a0a for `snkrdunk-collector`.
2. Restore attestation **outside quiet windows**. Re-run the SNKR component verifier,
   which must pass.
3. Re-pin the canary helper (see above). Run the AMBER canary for ONE turn
   (10:57–17:57Z daily). Set OFF via skip-deploys + upload redeploy, then do lossless
   verification.
4. If it passes: set `APP_ENV=staging` on shards 1–8 and run daily-v1 AMBER.
   Observe for 24h, then recompute 30/90d.

Never replay: SNKR 3676/3677, RAW recovery 35175, Yuyu canary evidence, PR77–82
deliveries.
