# Staging deployment checklist

Step-by-step checklist for standing up the `v1.0.0` staging deployment (Vercel + Railway). Pairs
with [docs/staging_deployment.md](staging_deployment.md) (architecture/env var reference) and
[docs/railway_staging.md](railway_staging.md) (per-service Railway setup). Check items off in
order - later sections assume earlier ones are done.

## Before deploy

- [ ] A `staging` branch (or equivalent long-lived branch/tag) exists to deploy from.
- [ ] Railway project created.
- [ ] Railway Postgres (managed plugin) created.
- [ ] Railway Redis (managed plugin) created.
- [ ] Railway `api` service configured (source = this repo, **Root Directory `/`**, **Dockerfile
      Path `deploy/railway/api.Dockerfile`** - not `services/api` / `services/api/Dockerfile`,
      which caused this staging deployment's original Railway build failure - see
      `docs/railway_staging.md` section 3), public networking enabled.
- [ ] Railway `worker` service configured (Root Directory `/`, Dockerfile Path
      `deploy/railway/worker.Dockerfile`, no public networking - section 4).
- [ ] Railway `beat` service configured (Root Directory `/`, Dockerfile Path
      `deploy/railway/beat.Dockerfile`, start command `celery -A worker.celery_app beat
      --loglevel=info`, no public networking - section 5).
- [ ] Vercel project configured with Root Directory `apps/web`. Confirm Railway is **not** building
      `apps/web` anywhere - `apps/web` deploys to Vercel only.
- [ ] `deploy/railway/api.Dockerfile`, `deploy/railway/worker.Dockerfile`, and
      `deploy/railway/beat.Dockerfile` all build successfully locally from the repo root:
      `docker build -f deploy/railway/api.Dockerfile -t opcg-api-railway-test .` (and the
      worker/beat equivalents) - see `docs/railway_staging.md` "Local build verification".
- [ ] If Railway reports `couldn't locate the dockerfile path ... in code archive` for any
      service: check branch, commit/push status, Root Directory, and case-sensitive path - see
      `docs/railway_staging.md` "Troubleshooting: couldn't locate the dockerfile path ... in code
      archive".
- [ ] All env vars set on every service (see [.env.staging.example](../.env.staging.example) and
      `docs/staging_deployment.md` section 5) - double check none are left as the literal
      `change-me`/`<...>` placeholder.
- [ ] `ADMIN_TOKEN` generated (`openssl rand -hex 32`) and set identically wherever it's needed
      (Railway `api`; `worker`/`beat` only if a specific job needs it).
- [ ] `API_JWT_SECRET` generated and set identically on Railway `api` and Vercel `web`.
- [ ] `SCRAPING_MODE=mock` on `api`/`worker`/`beat`.
- [ ] `MARKET_WORKFLOW_ENABLED=false` and `DATA_RETENTION_ENABLED=false` on `beat`.
- [ ] Telegram disabled (`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` both blank), or both pointed at a
      staging-only test bot/channel - never the production one.
- [ ] `CORS_ALLOWED_ORIGINS`/`CORS_ALLOW_ORIGIN_REGEX` on Railway `api` set to the Vercel staging
      domain (see "Known direct backend calls to fix before production" in
      `docs/staging_deployment.md` - several pages call `api` directly from the browser and will
      fail as CORS errors without this).

## Deploy

- [ ] Deploy Railway `api`. Confirm `GET <railway-api-url>/health` returns `{"status": "ok", ...}`.
- [ ] Run migrations: `DATABASE_URL=<railway-postgres-url> bash scripts/staging_migrate.sh` (or the
      Railway-side `alembic upgrade head` command - see `docs/railway_staging.md` section 3).
- [ ] Deploy Railway `worker`. Confirm it starts without crash-looping (check Railway's deploy
      logs).
- [ ] Deploy Railway `beat`. Confirm it starts without crash-looping.
- [ ] Deploy Vercel `web`, with `API_BASE_URL`/`API_INTERNAL_URL` (and `NEXT_PUBLIC_API_URL`, if
      used) already set to the Railway `api` service's public URL from the previous steps.
- [ ] Redeploy Vercel `web` once more if any env var was set/changed after the first deploy -
      `NEXT_PUBLIC_API_URL` and other build-time vars only take effect on the build they're present
      for.

## Smoke

Run `STAGING_API_URL=<railway-api-url> STAGING_WEB_URL=<vercel-staging-url>
ADMIN_TOKEN=<staging-admin-token> bash scripts/staging_smoke_test.sh` and confirm:

- [ ] API `/health` works.
- [ ] Web `/dashboard` works.
- [ ] Admin token works (`/admin/system-check` returns 200, not `critical`).
- [ ] Saved views works (`/saved-views?limit=5` returns 200 or 401 - 401 without a signed-in
      session is expected/healthy).
- [ ] Analytics digest works (`/analytics/digest` - same 200-or-401 note as saved views; web
      `/analytics/digest` page itself returns 200).
- [ ] Catalog ops works (`/admin/catalog-coverage` returns 200; web `/admin/catalog-ops` page
      returns 200).
- [ ] Source health works - manually check `/admin/price-source-health` in the web UI (no dedicated
      smoke-test check for this route; it's a frontend-only aggregation page, same as
      `scripts/release_candidate_audit.sh` section 6b notes for `/admin/catalog-ops`).
- [ ] Command palette works - manually verify (Ctrl/Cmd+K opens, searches, navigates) on the
      deployed staging URL; not automatable via curl.
- [ ] Collection vault works (web `/collection/vault` returns 200 after following the sign-in
      redirect, same as `/collection`/`/dashboard`).

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
- [ ] Run `scripts/staging_smoke_test.sh` (see "Smoke" above) - don't consider staging live until
      it passes.
- [ ] Review Railway logs for all three services (`api`, `worker`, `beat`) for unexpected errors in
      the first few minutes after deploy.
- [ ] Review Vercel deployment logs (build log + function logs) for unexpected errors.
- [ ] Only then consider enabling live Yuyu-Tei staging refresh - flip `SCRAPING_MODE=live` on
      `api`/`worker`/`beat` deliberately, one service at a time, and only after everything above is
      green. Never enable SNKRDUNK live scraping or attempt to bypass its site protections - SNKRDUNK
      data stays manual-import-only regardless of environment (see `docs/staging_deployment.md`
      section 11).
