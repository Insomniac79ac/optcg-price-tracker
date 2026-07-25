# Staging deployment checklist

Step-by-step checklist for standing up the `v1.0.0` staging deployment (Vercel + Railway). Pairs
with [docs/staging_deployment.md](staging_deployment.md) (architecture/env var reference) and
[docs/railway_staging.md](railway_staging.md) (per-service Railway setup). Check items off in
order - later sections assume earlier ones are done.

## Before deploy

- [x] A `staging` branch (or equivalent long-lived branch/tag) exists to deploy from.
- [x] Railway project created.
- [x] Railway Postgres (managed plugin) created.
- [x] Railway Redis (managed plugin) created.
- [x] Railway `api` service configured (source = this repo, **Root Directory `/`**, **Dockerfile
      Path `deploy/railway/api.Dockerfile`** - not `services/api` / `services/api/Dockerfile`,
      which caused this staging deployment's original Railway build failure - see
      `docs/railway_staging.md` section 3), public networking enabled.
- [x] Railway `worker` service configured (Root Directory `/`, Dockerfile Path
      `deploy/railway/worker.Dockerfile`, no public networking - section 4).
- [ ] Railway `beat` service configured (Root Directory `/`, Dockerfile Path
      `deploy/railway/beat.Dockerfile`, start command `celery -A worker.celery_app beat
      --loglevel=info`, no public networking - section 5). **Not yet created** - blocked by a
      Railway free-plan resource provision limit as of 2026-07-25; see dated note below.
- [ ] Vercel project configured with Root Directory `apps/web`. Confirm Railway is **not** building
      `apps/web` anywhere - `apps/web` deploys to Vercel only.
- [x] `deploy/railway/api.Dockerfile`, `deploy/railway/worker.Dockerfile`, and
      `deploy/railway/beat.Dockerfile` all build successfully locally from the repo root:
      `docker build -f deploy/railway/api.Dockerfile -t opcg-api-railway-test .` (and the
      worker/beat equivalents) - see `docs/railway_staging.md` "Local build verification".
- [ ] If Railway reports `couldn't locate the dockerfile path ... in code archive` for any
      service: check branch, commit/push status, Root Directory, and case-sensitive path - see
      `docs/railway_staging.md` "Troubleshooting: couldn't locate the dockerfile path ... in code
      archive".
- [x] `WORKER_CONCURRENCY=2` set on the Railway `worker` service (staging default - do not leave
      unset). If worker logs show a high prefork concurrency (e.g. `concurrency: 48`) and the
      service crash-loops with no traceback, this is almost certainly it - see
      `docs/railway_staging.md` "Worker concurrency". Do not deploy `beat` until `worker` is
      confirmed stable (no crash loop) with this set - `--concurrency` doesn't apply to `beat`.
- [x] Confirm which Railway environment you're actually deploying into - it may be named
      `production` in the dashboard even when it's the intended staging deployment (`APP_ENV`
      still `staging`). See `docs/railway_staging.md` "Operational warning: Railway environment
      named production" - don't rename/switch environments as an incidental fix. Confirmed as of
      2026-07-25: this deployment targets the dashboard environment actually named `staging`
      (`05d1eac2-...`), distinct from the `production`-named environment, which is left untouched.
- [ ] All env vars set on every service (see [.env.staging.example](../.env.staging.example) and
      `docs/staging_deployment.md` section 5) - double check none are left as the literal
      `change-me`/`<...>` placeholder. Done for `api`/`worker`; not yet applicable to `beat`
      (not created) or Vercel `web` (not set up).
- [x] `ADMIN_TOKEN` generated (`openssl rand -hex 32`) and set identically wherever it's needed
      (Railway `api`; `worker`/`beat` only if a specific job needs it).
- [ ] `API_JWT_SECRET` generated and set identically on Railway `api` and Vercel `web`. Generated
      and set on Railway `api` (2026-07-25); Vercel `web` side pending (out of scope for this
      pass).
- [ ] `SCRAPING_MODE=mock` on `api`/`worker`/`beat`. Confirmed `mock` on `api` and `worker`; `beat`
      not yet created.
- [ ] `MARKET_WORKFLOW_ENABLED=false` and `DATA_RETENTION_ENABLED=false` on `beat`. N/A - `beat`
      not yet created.
- [x] Telegram disabled (`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` both blank), or both pointed at a
      staging-only test bot/channel - never the production one.
- [ ] `CORS_ALLOWED_ORIGINS`/`CORS_ALLOW_ORIGIN_REGEX` on Railway `api` set to the Vercel staging
      domain (see "Known direct backend calls to fix before production" in
      `docs/staging_deployment.md` - several pages call `api` directly from the browser and will
      fail as CORS errors without this). Deliberately deferred until the Vercel staging URL
      exists.

## Deploy

- [x] Deploy Railway `api`. Confirm `GET <railway-api-url>/health` returns `{"status": "ok", ...}`.
- [x] Run migrations: `DATABASE_URL=<railway-postgres-url> bash scripts/staging_migrate.sh` (or the
      Railway-side `alembic upgrade head` command - see `docs/railway_staging.md` section 3).
- [x] Deploy Railway `worker`. Confirm it starts without crash-looping (check Railway's deploy
      logs).
- [ ] Deploy Railway `beat`. Confirm it starts without crash-looping. **Blocked** - see dated note.
- [ ] Deploy Vercel `web`, with `API_BASE_URL`/`API_INTERNAL_URL` (and `NEXT_PUBLIC_API_URL`, if
      used) already set to the Railway `api` service's public URL from the previous steps.
- [ ] Redeploy Vercel `web` once more if any env var was set/changed after the first deploy -
      `NEXT_PUBLIC_API_URL` and other build-time vars only take effect on the build they're present
      for.

## Smoke

Run `STAGING_API_URL=<railway-api-url> STAGING_WEB_URL=<vercel-staging-url>
ADMIN_TOKEN=<staging-admin-token> bash scripts/staging_smoke_test.sh` and confirm:

- [x] API `/health` works.
- [ ] Web `/dashboard` works. N/A - Vercel not set up yet.
- [x] Admin token works (`/admin/system-check` returns 200, not `critical`).
- [x] Saved views works (`/saved-views?limit=5` returns 200 or 401 - 401 without a signed-in
      session is expected/healthy).
- [ ] Analytics digest works (`/analytics/digest` - same 200-or-401 note as saved views; web
      `/analytics/digest` page itself returns 200). API-side confirmed (401, healthy); web-page
      portion pending Vercel.
- [ ] Catalog ops works (`/admin/catalog-coverage` returns 200; web `/admin/catalog-ops` page
      returns 200). API-side confirmed (200); web-page portion pending Vercel.
- [ ] Source health works - manually check `/admin/price-source-health` in the web UI (no dedicated
      smoke-test check for this route; it's a frontend-only aggregation page, same as
      `scripts/release_candidate_audit.sh` section 6b notes for `/admin/catalog-ops`). Pending
      Vercel.
- [ ] Command palette works - manually verify (Ctrl/Cmd+K opens, searches, navigates) on the
      deployed staging URL; not automatable via curl. Pending Vercel.
- [ ] Collection vault works (web `/collection/vault` returns 200 after following the sign-in
      redirect, same as `/collection`/`/dashboard`). Pending Vercel.

## After deploy

- [ ] Create a staging backup once real-ish data exists (`scripts/db_backup.sh` pointed at the
      Railway Postgres connection string, or a manual `pg_dump` via Railway's Shell/CLI - see
      `docs/operations.md`'s backup/restore drill for the general pattern).
- [ ] Seed saved views if needed (`python -m app.seed_saved_views`, run inside the Railway `api`
      service, if this repo has that seed command - check `services/api/app/seed_saved_views.py`).
- [ ] Import a small test card catalog CSV if needed
      (`python -m app.import_watchlist <path-to-csv>`, run inside the Railway `api` service - do
      **not** pass `--demo-data` to `app.seed`, same rule as production per `docs/deployment.md`
      section 4).
- [x] Run `scripts/staging_smoke_test.sh` (see "Smoke" above) - don't consider staging live until
      it passes. Passed 2026-07-25 (API-only run; `STAGING_WEB_URL` not yet set).
- [ ] Review Railway logs for all three services (`api`, `worker`, `beat`) for unexpected errors in
      the first few minutes after deploy. Done for `api`/`worker`; `beat` not yet created.
- [ ] Review Vercel deployment logs (build log + function logs) for unexpected errors.
- [ ] Only then consider enabling live Yuyu-Tei staging refresh - flip `SCRAPING_MODE=live` on
      `api`/`worker`/`beat` deliberately, one service at a time, and only after everything above is
      green. Never enable SNKRDUNK live scraping or attempt to bypass its site protections - SNKRDUNK
      data stays manual-import-only regardless of environment (see `docs/staging_deployment.md`
      section 11).

## 2026-07-25 - API + worker deployed and verified; beat blocked

- **Staging API** (`optcg-price-tracker`, Railway environment `staging`): healthy.
  `/health` returns `status=ok`, `app_env=staging`, `database_connected=true`,
  `redis_connected=true`. `API_JWT_SECRET` generated and set (32+ bytes, value not recorded
  anywhere). `DATABASE_URL`/`REDIS_URL` rewired from manually-copied literals to native Railway
  service-variable references. Health check path set to `/health`. Restart policy unchanged
  (`ON_FAILURE`, 10 retries).
- **Staging worker**: created and deployed from `deploy/railway/worker.Dockerfile` on branch
  `staging`, no public networking. Verified via deploy logs and an in-container connectivity
  check: Celery started at `concurrency: 2`, connected to the staging Redis broker, and confirmed
  `database_connected: yes` / `redis_connected: yes` / `scraping_mode: mock`. No crash loop.
- **Staging beat**: **not created** - Railway reported "Free plan resource provision limit
  exceeded" when provisioning a fifth service in this project. No partial service was left behind.
  Requires a Railway plan upgrade or a deliberate resource decision before beat can be added;
  scheduled workflows (market intelligence digest, data retention pruning) do not run in staging
  until this is resolved.
- **Migrations**: staging Postgres was already at the repository's head revision
  (`e7a1c4d9b2f6`); `scripts/staging_migrate.sh` ran cleanly with no pending migrations.
- **Smoke tests**: `scripts/staging_smoke_test.sh` passed against the staging API domain
  (`STAGING_WEB_URL` intentionally omitted - no Vercel deployment yet). One transient failure was
  diagnosed and resolved along the way: `/admin/system-check` initially returned `critical`
  because the staging database's `sources` table (`yuyutei`, `snkrdunk`) had never been seeded;
  running `python -m app.seed` (additive, no demo cards) fixed this. Separately, `/admin/system-check`
  took ~14.7s on one run, just under the script's 15s timeout - likely due to the API/worker
  running in `asia-southeast1` while Postgres/Redis run in `sfo`; worth monitoring if it recurs.
- `SCRAPING_MODE` remains `mock` on both `api` and `worker`. No live scraping was enabled.
  `CORS_ALLOWED_ORIGINS` deliberately left unset pending the Vercel staging URL. Vercel, frontend,
  Google OAuth, and final CORS configuration are unchanged and out of scope for this pass.
