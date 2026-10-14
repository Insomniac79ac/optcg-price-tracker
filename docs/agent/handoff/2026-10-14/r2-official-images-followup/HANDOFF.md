# Official card images follow-up: daily job and share-image credit, 2026-10-14

Staging only. Production was not accessed. PSA10 stays OFF. There were no
collector settings or releases and no R2 object deletions or overwrites. No
identity, price, Market Index or Market Value changed. Evidence paths are
relative to this folder.

## Status

| Item | Status |
|---|---|
| Run lock in `app/official_images/lock.py` | **Delivered** (PR #120) |
| State blocker `official-images-check-failed` | **Delivered** (PR #120) |
| Share-image credit and corrected `docs/official_images.md` | **Delivered and live** on the staging alias |
| Railway cron service `official-images-mirror` | **Not created: needs the owner.** See [RAILWAY-STEPS.md](RAILWAY-STEPS.md) |
| First scheduled run exits 0; state report clean | **Pending** until the service exists. Its first run is the next 07:15 UTC after creation |

## Why the service is not created by tooling

The task asked for variables to be set via the documented tooling.

- The only supported Railway variable path is `scripts/collector_variables.py`.
  It accepts only the collector RAW keys and `APP_ENV`, and only for
  collectors.
- `scripts/tests/test_collector_variables.py` (`OnlyPathTests`) fails if any
  other repository tooling sets Railway variables.
- No repository tooling creates services.

Per the instruction, I stopped there and wrote click-by-click owner steps
instead. They copy `market-index-snapshot` as read from Railway on 2026-10-14:

- source `staging`, root `/`, Dockerfile `deploy/railway/api.Dockerfile`;
- watch paths `services/api/**` and `deploy/railway/api.Dockerfile`;
- restart policy `NEVER`, no healthcheck.

The variables are Railway references to the staging API service, so no
secret is copied by hand.

## The job (once created)

| | |
|---|---|
| Service | `official-images-mirror` (staging, API image) |
| Schedule | `15 7 * * *`: 07:15 UTC, outside 02:00-06:00 and 19:30-20:30 |
| Start command | `/bin/sh -c "python -m app.mirror_official_images --write --quiet && exec python -m app.check_official_images"` |
| Variables (names only) | `DATABASE_URL`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `R2_PUBLIC_BASE_URL` |

- **Start command.** The `/bin/sh -c` wrapper is required because Railway runs
  a start-command override in exec form (`docs/operations.md`, "Scheduled
  index jobs").
  - `exec` hands the health check's exit status to the container.
  - The chain is otherwise exactly the approved command.
- **Bandai limits.** These are the built-in, unchanged limits: one request at
  a time, at least 1 s apart (`MIN_INTERVAL_FLOOR`, cannot be lowered), and a
  stop after 5 consecutive transient failures.
- **Run lock.** This is a session-scoped PostgreSQL advisory lock, held on its
  own connection for the whole `--write` run.
  - A transaction lock would not work, because the mirror commits per print.
  - A second run exits 3 having fetched nothing.
  - The lock is released on error or process death.
- **Failure visibility.** Any non-zero exit (mirror failure, held lock or
  unhealthy check) ends the run as a failed deployment.
  - `generate_staging_state.py` then adds `official-images-check-failed` with
    the deployment id.
  - `SUCCESS` or an absent service adds nothing.
  - The service is also in `GITHUB_BUILT_SERVICES`, so its provenance is
    judged by watch patterns like `market-index-snapshot`.

## Image credit

- `apps/web/src/lib/shareCard.tsx`: every share/OG kind (home, print, market,
  release) now has `brand.imageCredit` as a second footer line.
  - The date and the independence disclaimer share line 1.
  - The canvas and footer height are unchanged, and no new copy string was
    added.
- `/cards/[id]` was not changed. It is retired in collector-v1 S6.
- `docs/official_images.md` now lists exactly where the credit appears:
  - the footer on every HTML page;
  - under the card on `/prints/[id]`;
  - every share image;
  - `/about` and `/terms`.

  It also says the credit is not under the card on `/cards/[id]`.
- **Visual review:** a fresh `cardpirate-visual-reviewer` returned **PASS**.
  - The credit is legible at full size, with no clipping and no line-1
    collision. The longest date ends near x=404 and the disclaimer starts near
    x=800.
  - **Minor:** about 8 px of bottom margin. The credit is about 693 px of the
    1132 px available, so it cannot wrap today.
  - **Minor:** 10 px footer text is unreadable as a thumbnail. This was
    already true of the old disclaimer, and the reviewer said not to enlarge
    it.
  - The reviewer did not open every before image, and its thumbnail judgement
    comes from pixel size, not a rendered thumbnail.
- **Images** (`evidence/share-images/`):
  - `before-*`: the staging alias before the merge.
  - `local-after-*`: `next dev` against the staging API.
  - `staging-after-*`: the staging alias at `4c53dfa`, including
    `release-1`.

## Gates

- **Import graph** (`evidence/import-graph-check.json`, head `7fa11d8`):
  - 0 PR files among SNKRDUNK's 62 and Yuyu-Tei's 73 runtime inputs.
  - 0 changed runtime inputs from base to head (basis: import-graph).
  - No `models/` or `settings.py` change.
- **Policy:** `scripts/staging_policy.py` gave AMBER, eligible. AMBER is
  declared for `source_envelope`, the recurring Bandai requests.
- **Local tests:**
  - scripts: 216 passed (`evidence/scripts-tests.txt`);
  - API official-images, including 3 real-PostgreSQL lock tests: 50 passed
    (`evidence/api-official-tests.txt`);
  - web vitest: 1683 passed (`evidence/web-vitest-summary.txt`).

## Delivery receipt

| PR | Merge | CI run | Artifacts (id, expiry) | Scope | Collector deployments |
|---|---|---|---|---|---|
| #120 | `4c53dfa` (2026-10-14T09:56:52Z, parent `99806ef`) | 38544725025 | `staging-delivery-4c53dfa2…` (11885720313, 2027-01-12)<br>`staging-credential-probe-52ed2a32…` (11883508284, 2027-01-12) | full | **0** |

- **Artifacts** are in `evidence/pr120-delivery/`.
- **Frontend:** `dpl_FYcFPLLQr2LMoUAcoXTBvXiDC1YC` READY at `4c53dfa`.
  `/api/version` reports web `source_commit` `4c53dfa`.
- **API:** `api_expectation` was `build` at `4c53dfa`. The watched changes
  were the three `services/api` files. The API runtime SHA reports as
  unknown, so this rests on Railway metadata.
- **Migration revision:** `3b7d9c1a5e20`, unchanged.
- **Railway records since the merge** (`evidence/deploy-records-after-pr120.json`):
  - `optcg-price-tracker` and `market-index-snapshot`: SUCCESS at `4c53dfa`;
  - `beat` and `worker`: SKIPPED;
  - every collector service: **0 records**.
- **State blockers after delivery:** only the existing
  `freshness-deadline-deficit` and `snkrdunk-identity-quarantine` (23). There
  is no `official-images-check-failed` and no provenance divergence.
- **CI flakes.** The first two CI attempts each failed on one unrelated flaky
  test, and nothing merged either time. Each was re-triggered with an empty
  commit, which leaves the manifest digest valid.
  - Run 38536722191 failed on `agent-state-tests`, a tempdir cleanup race in
    `test_collector_runtime_inputs.py`.
  - Run 38540558115 failed on `frontend-build`: `cards/discovery.test.tsx`
    "intersection appends" got 24 rows, not 48. It passed 3/3 locally with
    `--maxWorkers=2`.
  - The workflow token cannot re-run jobs (HTTP 403).

## Coordination

The Collector v1 S4 session (PR #121, API + `market-index-snapshot`) held off
until this delivery was released. It was told at 10:10Z. #121 merged at
10:27:31Z (`20f167e`), and its delivery run 38547720657 verified green at
10:40:58Z. The owner can now create the cron service.

Keep any delivery, and any manual run of the new job, out of 19:30-20:30Z:
tonight's 20:00 `market-index-snapshot` run is the S4 verification. The
07:15 UTC schedule already avoids it.

## Observations, not changed

- **`market-index-snapshot` start command.** Its live start command is
  `python -m app.market_index_daily_pipeline`. `docs/operations.md` still
  describes the older `/bin/sh -c "...snapshot && exec ...writer"` chain.
- **Local Postgres data.** `docker volume prune` was run on the codespace to
  free disk before this task. Any local Postgres data volumes are gone.

## Pending

1. **Owner:** create `official-images-mirror` using
   [RAILWAY-STEPS.md](RAILWAY-STEPS.md). #121 has been delivered, so this
   can be done now, outside 19:30-20:30Z.
2. **Next session, after creation:**
   - Read the service back from Railway (read-only): name, schedule, start
     command, restart policy, watch paths, variable names, and 0 collector
     deployments.
   - After the first 07:15 UTC run: its deployment status, the run log
     summary (`selected`, `mirrored`, `failed`, `stopped`; the health check
     is silent), and the regenerated state with no
     `official-images-check-failed`.
3. **This record's own receipt:** download the `staging-delivery-<merge>`
   artifact after its docs-only PR merges.
