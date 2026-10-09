# Railway production deprecation, step 1 of 2: read-only inventory

Status: **INVENTORY ONLY**, for owner review. Written 2026-10-09 (09:55–10:25Z) on
base `origin/staging` 3fc3a9c.

**Authority.** The owner authorized this session to read production metadata and
data, for this inventory only. Nothing in production was stopped, redeployed,
changed, deleted, detached or written:
- Every database session ran with `default_transaction_read_only=on` and was
  rolled back.
- No Run Now, no variable change and no export.
- Secrets were held in process memory only and never printed or written. Two
  secrets were compared for equality; only the true/false result was recorded.

Staging was read only.

Every number below is **MEASURED**, with its source given in brackets. **ESTIMATED**
marks derived figures.

---

## Plain summary

1. **What runs.** The Railway `production` environment
   (`d84d1abf-04c5-4315-841c-1c8838ebec89`) runs three services, all RUNNING:
   - the API, last deployed 2026-08-18 from staging commit `6130c9d`;
   - Postgres 18;
   - Redis 8.2.9.

   It has no collectors, worker, beat or cron.
2. **Cost.** About **$1.91 per 30 days** at Railway list prices. That sits inside
   the Pro plan's $20 included usage, alongside staging's about $11.35, so
   removing production probably does not change the invoice today. (ESTIMATED from
   measured usage.)
3. **Exposure.**
   - The API has **no public domain**, so the open signal-event routes are not
     reachable from the internet.
   - Postgres (`sakura.proxy.rlwy.net:21415`) and Redis
     (`tokaido.proxy.rlwy.net:48223`) **do have public TCP proxies** that accept
     connections. They are password-protected.
   - Production's `ADMIN_TOKEN` is **identical to staging's**.
4. **Data.** There is **nothing worth keeping.**
   - Production Postgres has **zero tables**; both databases are about 7.7 MB of
     server overhead.
   - Redis holds 3 leftover Celery binding keys.
   - All price history (RAW from 2026-07-26, observations from 2026-08-08, index
     from 2026-08-21) lives in **staging**, not production.
5. **Recommendation.** Remove the two TCP proxies first, then delete the
   **production environment as a whole**, not the services. Service IDs are shared
   with staging, and deleting a service would delete it from staging too.

---

## 1. Inventory

Sources:
- `railway status --project c613898d-… --environment d84d1abf-… --json`;
- GraphQL `domains`, `tcpProxies`, `deploymentTriggers`,
  `volumeInstanceBackupList`;
- all read at 2026-10-09 09:55–10:20Z.

Production environment `d84d1abf-04c5-4315-841c-1c8838ebec89`, created
2026-07-23T15:37:25Z. Staging environment `05d1eac2-…` was created
2026-07-24T06:33:58Z. The project has 19 services; production has instances of
only 3.

| Service (service ID) | Type | Status | Last deploy | Source / commit | Public HTTP domain | Public TCP proxy | Cron | Volume (used / size) | Region |
|---|---|---|---|---|---|---|---|---|---|
| `optcg-price-tracker` (5290becf-6956-4c5c-ab16-01d865587e07) | App (API, Dockerfile `deploy/railway/api.Dockerfile`) | RUNNING, 1 replica, sleep off | 2026-08-18T15:34:22Z, deployment 782151cc | GitHub repo, branch `staging`, commit `6130c9d` "Prepare CardPirate Atlas for public MVP" | **none** (service and custom domains empty) | none | none | none | asia-southeast1 |
| `Redis` (bdc84418-d934-47f3-bb84-2f03cb7d8f5b) | Redis (image `redis:8.2.9`) | RUNNING | 2026-09-12T11:16:18Z, deployment 64ef0b31 | image | none | **tokaido.proxy.rlwy.net:48223 → 6379** (created 2026-07-23), TCP connect OPEN at 09:59:51Z | none | `redis-volume` 59.7 MB / 500 MB | sfo |
| `Postgres` (08c557d4-9d74-43fa-a0ac-5a909e731f4e) | Database (image `postgres-ssl:18`, PostgreSQL 18.6) | RUNNING, postmaster started 2026-08-30T14:49:18Z | 2026-08-30T14:48:14Z, deployment d65363c7 | image | none | **sakura.proxy.rlwy.net:21415 → 5432** (created 2026-07-23), TCP connect OPEN at 09:59:51Z | none | `postgres-volume` 91.0 MB / 500 MB | sfo |

Further details:
- **Deploy triggers.** The production API has **no deployment triggers**
  (`deploymentTriggers` returns empty), so it never redeploys on a push. The last
  three GitHub deployment records for "glistening-peace / production" are all from
  2026-08-18 (`83379fe`, `39a4823`, `6130c9d`), created by `railway-app[bot]`.
- **Volume backups.** Each volume has one manual backup named "Pre-Security-Patch
  Backup". Neither has a backup schedule.
  - Postgres: 2026-08-30T14:48Z, referenced 88 MB, expiresAt 2026-09-29 but still
    listed.
  - Redis: 2026-09-12T11:16Z, referenced 59 MB, expires 2026-10-12.
- **Production API configuration** (variable names only):
  - `ADMIN_TOKEN`, `API_JWT_SECRET`, plus Railway-injected `RAILWAY_*`.
  - **No `DATABASE_URL`, `REDIS_URL`, `APP_ENV` or `CORS_*`.** The running API is
    not connected to any database.
  - `ADMIN_TOKEN` **equals staging's**; `API_JWT_SECRET` differs. Compared in
    memory; only the boolean was kept.

## 2. Exposure

| Endpoint | Check | Result |
|---|---|---|
| Production API | Public domain lookup (`domains`, `tcpProxies`) | **No public domain or proxy.** No HTTP request is possible, so none was made. The open signal-event write routes (present in `6130c9d`, added 2026-07-11) are reachable only from inside the production private network, where no other service calls them |
| Postgres `sakura.proxy.rlwy.net:21415` | TCP connect only, no login | OPEN (password-protected) |
| Redis `tokaido.proxy.rlwy.net:48223` | TCP connect only, no login | OPEN (password-protected) |

The only internet-facing attack surface is the two password-protected database
proxies. The production database holds no data (§4), so the residual risk is
credential guessing against an empty server and Railway resource abuse, not data
loss.

## 3. Cost

Source: GraphQL `usage(projectId, groupBy:[ENVIRONMENT_ID, SERVICE_ID])`, window
2026-09-09 → 2026-10-09 (30 days). Unit prices from
https://docs.railway.com/reference/pricing/plans, fetched 2026-10-09:
- vCPU $0.000463/min;
- RAM $0.000231/GB-min;
- volume $0.000003472/GB-min;
- egress $0.05/GB.

Backups are priced at the volume rate (the page does not price backups; ESTIMATED).

| Service | vCPU-min | GB-min RAM | GB-min disk | GB-min backup | Egress GB | 30-day cost (ESTIMATED) |
|---|---|---|---|---|---|---|
| API | 60.38 (avg 0.0014 vCPU) | 5,488 (avg 0.127 GB) | 0 | 0 | 0 | **$1.30** |
| Postgres | 3.43 | 1,957 (avg 0.045 GB) | 3,896 | 59.4 | 0 | **$0.47** |
| Redis | 74.17 | 445 (avg 0.010 GB) | 2,580 | 16.3 | 0 | **$0.15** |
| **Production total** | | | | | | **$1.91** |
| Staging total (same window, for scale) | 4,308 | 32,561 | 101,856 | 22,130 | 28.1 | **$11.35** |

- The Pro plan is $20/month and includes $20 of usage.
- Production plus staging comes to about $13.26, under that allowance.
- So deleting production saves about $1.91 of usage but probably **$0 on the
  current invoice** (ESTIMATED).

## 4. Data comparison

Source: read-only sessions on each environment's Postgres, 10:05–10:15Z. Each
connection's host and port were checked against that environment's own
`tcpProxies` record:
- production `:21415`;
- staging `:12258`.

**Production:**
- `pg_database`: `railway` 7,861,951 B and `postgres` 7,701,007 B.
- One schema (`public`) and **0 user tables**, so there is no `alembic_version`.
- Redis: `DBSIZE` 3, used memory 1.07 MB. The keys are
  `_kombu.binding.celery`, `_kombu.binding.celeryev` and
  `_kombu.binding.celery.pidbox`: queue bindings only, no cache, sessions or user
  data. Key names only were read.

**Staging:** `railway` 2,747,266,751 B, 54 tables, alembic `f9e5b4a8c012`.

| Table | Production rows | Production date range | Staging rows | Staging earliest → latest |
|---|---|---|---|---|
| raw_snapshots | absent | — | 40,472 | fetched_at 2026-07-26 09:31Z → 2026-10-09 10:01Z |
| price_observations | absent | — | 31,662 | observed_at 2026-08-08 06:14Z → 2026-10-09 10:01Z |
| market_index_snapshots | absent | — | 28,914 | snapshot_date 2026-08-21 → 2026-10-08 |
| market_index_snapshot_completions (receipts) | absent | — | 10 | snapshot_date 2026-09-29 → 2026-10-08 |
| market_value_points | absent | — | 2,820 | point_date 2026-08-21 → 2026-10-08 |
| card_pirate_index_points | absent | — | 36 | point_date 2026-09-03 → 2026-10-08 |
| canonical_cards / card_prints | absent | — | 2,710 / 4,316 | created 2026-08-08 → 2026-08-30 |
| source_card_mappings | absent | — | 3,006 | created 2026-07-26 → 2026-10-07 |
| release_products | absent | — | 65 | released_on 2022-07-08 → 2026-08-22 |
| cards (legacy) / sources | absent | — | 25 / 3 | created 2026-07-25 → 2026-08-18 |
| market_signal_events | absent | — | 7 | first_seen 2026-07-26 → last_seen 2026-08-08 |
| users / collection_items / wishlist_items | absent | — | 0 / 0 / 0 | — |
| analytics_digest_reports / grading_submissions | absent | — | 0 / 0 | — |

Findings:
- **Nothing in production predates staging or is missing from it.** All price
  history lives in staging.
- **The 2026-08-30 backup almost certainly holds no data.**
  - Its referenced size (88 MB) matches today's empty volume (91 MB).
  - The 2026-08-21 incident recorded in `scripts/staging_db_read_check.py:6-16`
    found an empty schema on port **21415**, which is this production proxy
    (MEASURED today). So production was already empty before that backup.
  - The backup's contents were not restored or opened, because that would be a
    write.
- Side note for the security work: staging has **0 users, 0 collection items and
  0 digest reports**. The unauthenticated digest and market GET routes listed in
  the security-fix inventory currently expose no private rows on staging.

## 5. References to production

Searches covered:
- the repo (`git grep` excluding `docs/reports` and handoffs);
- every staging service's variables (19 services; values scanned in memory for
  `21415`, `48223`, `tokaido.proxy`, `d84d1abf` and `production`; only service
  and variable names would be printed);
- GitHub settings;
- Vercel.

| # | Where | Reference | Assessment |
|---|---|---|---|
| R1 | `scripts/staging_db_read_check.py:6-16` | Comment describing the 2026-08-21 stale-proxy incident (port 21415, "both are `railway` on `sakura.proxy.rlwy.net`") | Historical. 21415 is the **production** proxy. Keep the guard; add one clarifying line when production is gone |
| R2 | GitHub deployment environment "glistening-peace / production" | Railway integration records; last deployment 2026-08-18 | Stale record. Can be deleted after step c |
| R3 | Production API variable `ADMIN_TOKEN` | Same value as staging `ADMIN_TOKEN` | A second copy of a live staging secret. Removed with the environment. Rotating staging's token is a separate RED secrets decision |
| R4 | Railway project `glistening-peace` | `production` environment plus 3 service instances, 2 volumes, 2 TCP proxies, 2 volume backups | Subject of step 2 |
| R5 | `Makefile` prod-* targets, `docker-compose.prod.yml`, `docker-compose.prod.private.yml`, `scripts/prod_verify.sh`, `scripts/prod_smoke_test.sh`, CI `prod-compose` job | Generic self-hosted docker-compose "production" tooling | **Not** Railway production; no host, ID or secret of it. Keep, per owner instruction not to delete production config files |
| R6 | `scripts/staging_migrate.sh`, `services/api/app/env.py` | `APP_ENV=production` guards | Safety guards, not references. Keep |

No references to production were found in:
- **Staging service variables:** 0 matches across 19 services.
- **Vercel:** one project only (`optcg-price-tracker-staging`). Its "Production"
  target is the staging frontend; GitHub's "Production" environment records its
  latest deployment as the PR #90 merge `1378820`. Its environment values are
  write-only and could not be read. Production Railway has no public domain, so
  they cannot point at it.
- **DNS:** production has no custom domains.
- **GitHub repository secrets and variables:** the listing was refused (HTTP 403),
  so these are **unverified**. The CI workflows reference only `STAGING_*`
  secrets.

## 6. Recommended deprecation sequence (step 2 of 2; each action needs the owner's specific authorization)

| Step | Action | Reversible? | Notes |
|---|---|---|---|
| a | **Archive:** none required. Record this inventory as the evidence of emptiness. If the owner still wants a copy: `pg_dumpall --globals-only` plus `pg_dump -Fc` of `railway` (expected <1 MB), stored in the private R2 bucket under `production-archive/2026-10-09/`, encrypted with `age` to an owner key, retained 90 days, verified with `pg_restore --list` | Reversible (read-only on production) | The valuable history is in **staging** (RAW since 2026-07-26). Back it up separately; it is unaffected by this deprecation |
| b1 | Remove the Postgres TCP proxy (`021a39f9-…`, :21415) and the Redis TCP proxy (`1db5f145-…`, :48223) | Reversible in function only: a new proxy gets a **new port**, the old port is not recoverable | Closes the only internet-facing surface first |
| b2 | Optionally stop the API deployment `782151cc` (or scale to 0) | Reversible (redeploy `782151cc`, canRedeploy=true) | It has no domain or database; stopping it only saves about $1.30/30 days |
| c1 | Confirm the staging-side safeguards: each of the 3 production service IDs also exists in staging (same IDs, e.g. Postgres `08c557d4-…` = staging `POSTGRES` in `generate_staging_state.py:30`); staging verification green before and after | — | **Never delete a service.** Services are project-wide, and deleting `Postgres`, `Redis` or `optcg-price-tracker` would delete the **staging** instances and the 2.7 GB staging database |
| c2 | Delete the **`production` environment** (`d84d1abf-…`). This removes only its 3 service instances, 2 volumes and their backups | **Irreversible** | Run only after b1 has held for at least one staging delivery cycle and the owner confirms (a). Re-check that `railway status` for staging is unchanged, then run the staging verifier |
| d1 | Delete the GitHub deployment environment "glistening-peace / production" | Irreversible (history records only) | Cosmetic |
| d2 | Add a clarifying line to `scripts/staging_db_read_check.py` (R1) and a dated note to PROJECT_HANDOVER §41 that production was removed | Reversible (docs) | Docs-only delivery |
| d3 | Decide whether to rotate staging `ADMIN_TOKEN` (R3) | — | RED (secrets policy); separate owner decision, via `collector_variables.py`-style verified path if collectors are affected |

None of these steps touch staging services, collectors, cron or quiet windows. The
only staging interaction is the before/after verification in c1–c2.
