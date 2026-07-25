# Railway staging setup (api, worker, beat, Postgres, Redis)

Per-service Railway configuration for staging. Pairs with
[docs/staging_deployment.md](staging_deployment.md) (architecture/env var reference) and
[docs/staging_checklist.md](staging_checklist.md) (step-by-step deploy checklist). `apps/web` (the
Next.js frontend) deploys to **Vercel only** - Railway never builds or deploys it; none of the
three Railway services below reference `apps/web` at all.

All three Railway code services (`api`, `worker`, `beat`) build from **Railway-specific
Dockerfiles under `deploy/railway/`** (`api.Dockerfile`, `worker.Dockerfile`, `beat.Dockerfile`),
not the original `services/api/Dockerfile`/`services/worker/Dockerfile` directly - see "Why a
separate Dockerfile per Railway service" below for why. Nothing here changes local Docker Compose
(`docker-compose.yml`, `docker-compose.prod.yml`) or the original Dockerfiles - both keep working
exactly as before; the `deploy/railway/*.Dockerfile` files are additive, Railway-only build
definitions that `COPY` from the same `services/api`/`services/worker` source.

## Why a separate Dockerfile per Railway service

`services/api/Dockerfile` and `services/worker/Dockerfile` both use a bare `COPY requirements.txt
.` / `COPY . .`, which only resolves correctly if the Docker **build context** is that service's
own subdirectory (`services/api` or `services/worker`) - true locally because
`docker-compose.yml`/`docker-compose.prod.yml` both set `context: ./services/api` (or
`./services/worker`) explicitly.

On Railway, a service's "Root Directory" setting controls *both* where Railway looks for a
Dockerfile *and* the build context passed to `docker build` - if those two don't end up meaning
the same subdirectory (e.g. Root Directory left at the repo root while a Dockerfile path like
`services/api/Dockerfile` is typed in, or a service created without an explicit Root Directory at
all in a multi-language monorepo like this one, which has a Python `api`/`worker` and a Node
`apps/web` side by side), the build fails - typically surfacing in the Railway dashboard as a
generic **"error deploying from source"** with no further detail, and (with build logs available)
a `COPY failed: file not found in build context` or similar error from the `COPY requirements.txt
.` step, since `requirements.txt` isn't at the repo root.

This is exactly the failure mode this staging deployment hit. Rather than depend on getting Root
Directory scoping exactly right per service in the Railway dashboard (a setting that isn't
version-controlled and is easy to get wrong or leave unset), every Railway service below now
builds from the **repo root** as its context, with an explicit Dockerfile
(`deploy/railway/{api,worker,beat}.Dockerfile`) whose `COPY` lines spell out the full
`services/api/...`/`services/worker/...` path. This makes the Railway-side configuration identical
and trivial across all three services (Root Directory is always `/`; only the Dockerfile Path
differs) and makes the build reproducible from what's committed in git, not from dashboard clicks.

Verify locally before pushing (run from the repo root, not from `services/api`/`services/worker`):

```
docker build -f deploy/railway/api.Dockerfile -t opcg-api-railway-test .
docker build -f deploy/railway/worker.Dockerfile -t opcg-worker-railway-test .
docker build -f deploy/railway/beat.Dockerfile -t opcg-beat-railway-test .
```

## Services

### 1. Postgres (managed plugin)

Add Railway's Postgres plugin to the project. Railway provisions it and exposes connection info
(both a public and a private/internal networking URL) as plugin variables you can reference from
other services via Railway's variable-reference syntax (`${{Postgres.DATABASE_URL}}` or similar,
exact name depends on the plugin version - check the plugin's "Variables" tab).

- Prefer the **private networking** URL for the `api`/`worker`/`beat` services' `DATABASE_URL` -
  it's service-to-service traffic within Railway's network, not billed as external egress, and
  isn't reachable from the public internet.
- Railway's Postgres plugin injects a bare `postgresql://...` URL. This app uses SQLAlchemy with
  the `psycopg` (v3) driver, not `psycopg2` - a bare `postgresql://` URL makes SQLAlchemy default
  to the `psycopg2` dialect, which isn't installed (`services/api/requirements.txt`/
  `services/worker/requirements.txt` only install `psycopg[binary]`), and the app fails at import
  time with `ModuleNotFoundError: No module named 'psycopg2'` (confirmed locally - see "Local
  build verification" below). **Always rewrite the scheme to `postgresql+psycopg://...`** when
  setting `DATABASE_URL` on the code services - see `docs/deployment.md` section 11, same note for
  the production split.

### 2. Redis (managed plugin)

Add Railway's Redis plugin. Same private-networking preference as Postgres. Used as the Celery
broker/result backend and (when `CACHE_BACKEND=redis`) the API's response cache - see
`services/api/app/settings.py` and `docs/operations.md`.

### 3. `api` service

| Setting | Value |
|---|---|
| Source | this GitHub repo |
| Root Directory | `/` (repo root) |
| Dockerfile Path | `deploy/railway/api.Dockerfile` |
| Start command | Dockerfile default - do not override. The Dockerfile's `CMD` is `sh -c "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"`, which binds to whatever port Railway injects via the `PORT` env var (Railway sets this automatically - do not hardcode `PORT` yourself unless testing locally). |
| Public networking | **enabled** - generate a Railway public domain for this service (needed for the browser-direct calls documented in `docs/staging_deployment.md` section 4, and for Vercel's server-side proxy routes) |
| Health check path | `/health` (Railway's own healthcheck setting, separate from this app's Docker Compose healthchecks) |
| Env vars | see [.env.staging.example](../.env.staging.example) "Backend/Railway" section, plus `API_JWT_SECRET`, `CORS_ALLOWED_ORIGINS`, `CORS_ALLOW_ORIGIN_REGEX`. `SCRAPING_MODE` should stay `mock` for the first staging deploy (see `docs/staging_deployment.md` section 11). |

Run migrations against this service before the first smoke test (see section 7 of
`docs/staging_deployment.md` / `scripts/staging_migrate.sh`):

```
railway run --service api alembic upgrade head
```

or from the Railway dashboard's Shell for the `api` service:

```
alembic upgrade head
```

### 4. `worker` service

| Setting | Value |
|---|---|
| Source | same GitHub repo |
| Root Directory | `/` (repo root) |
| Dockerfile Path | `deploy/railway/worker.Dockerfile` |
| Start command | Dockerfile default - `celery -A worker.celery_app worker --loglevel=info`. Set it explicitly in Railway's service settings anyway (belt-and-suspenders - visible/auditable in the dashboard, not just implied by the Dockerfile's `CMD`). |
| Public networking | **disabled** - `worker` never serves HTTP, only consumes Celery tasks over Redis. Does not need to bind any port. |
| Health check | none needed (Railway has no Celery-aware healthcheck; `docker-compose.prod.yml`'s `celery inspect ping` healthcheck is Compose-specific and has no direct Railway equivalent - rely on Railway's deploy logs and `/admin/refresh-runs`/`/admin/system-check` in the web app instead) |
| Env vars | see [.env.staging.example](../.env.staging.example) - `APP_ENV`, `DATABASE_URL`, `REDIS_URL`, `SCRAPING_MODE=mock`, `YUYUTEI_REQUEST_DELAY_MS`, `SNKRDUNK_REQUEST_DELAY_MS`, `PRICE_REFRESH_INTERVAL_HOURS`, `CACHE_ENABLED`, `CACHE_BACKEND` (`ADMIN_TOKEN` only if a specific internal job needs it - none do by default) |

### 5. `beat` service

| Setting | Value |
|---|---|
| Source | same GitHub repo |
| Root Directory | `/` (repo root) |
| Dockerfile Path | `deploy/railway/beat.Dockerfile` (same `services/worker` source as `worker`, different default `CMD` - beat is just a different process from the same codebase, same as `docker-compose.yml`/`docker-compose.prod.yml`, which both build `worker`/`beat` from `services/worker` with only the `command:` differing) |
| Start command | Dockerfile default - `celery -A worker.celery_app beat --loglevel=info`. Set it explicitly in Railway's service settings too, same reasoning as `worker` above. |
| Public networking | **disabled** - beat only schedules, never serves HTTP or consumes tasks directly. Does not need to bind any port. |
| Env vars | same base set as `worker`, plus `MARKET_WORKFLOW_ENABLED=false` and `DATA_RETENTION_ENABLED=false` for the first staging deploy (see `docs/staging_deployment.md` section 11 "Safety notes") |

Disabling scheduled workflows by default means `beat` still runs (so its process/health is
verifiable) but the Celery beat schedule it builds
(`services/worker/worker/celery_app.py::_build_beat_schedule`) treats the market-intelligence
workflow entry as a no-op. Flip `MARKET_WORKFLOW_ENABLED=true` on the `beat` service (and redeploy
it) only once `api`/`worker`/`beat` have been confirmed stable per
`docs/staging_checklist.md`.

## Troubleshooting: "couldn't locate the dockerfile path ... in code archive"

Railway reports this when it cannot find the configured Dockerfile Path in the commit it just
pulled for the connected branch - the file exists somewhere in the repo's history, just not in
the tree Railway fetched. Check, in order:

1. **Branch** - which branch is the service's Source actually connected to (GitHub repo settings
   in the Railway dashboard for that service)? `deploy/railway/*.Dockerfile` may exist on one
   branch (e.g. `staging`) and not on another (e.g. `main`) if it hasn't been merged yet. Confirm
   with `git ls-tree -r origin/<branch> -- deploy/railway`.
2. **Commit/push status** - is the file committed and pushed to that exact branch? `git log
   --oneline -- deploy/railway/worker.Dockerfile` and `git status`.
3. **Root Directory** - must be `/` (repo root), not `services/worker` or anything else; the
   Dockerfile Path is resolved relative to Root Directory.
4. **Case sensitivity** - the path is case-sensitive; `Worker.dockerfile` or `worker.Dockerfile `
   (trailing space) will not match `deploy/railway/worker.Dockerfile`.

## Local build verification

Confirmed working from the repo root (not `services/api`/`services/worker`):

```
docker build -f deploy/railway/api.Dockerfile    -t opcg-api-railway-test    .
docker build -f deploy/railway/worker.Dockerfile -t opcg-worker-railway-test .
docker build -f deploy/railway/beat.Dockerfile   -t opcg-beat-railway-test   .
```

All three build successfully. Runtime-verifying the `api` image (no real Postgres/Redis - a
placeholder `DATABASE_URL`/`REDIS_URL`, same as what you'd use before the Railway Postgres/Redis
plugins exist yet):

```
docker run --rm \
  -e APP_ENV=staging \
  -e DATABASE_URL="postgresql+psycopg://placeholder:placeholder@localhost:5432/placeholder" \
  -e REDIS_URL="redis://localhost:6379/0" \
  -e ADMIN_TOKEN=test \
  -e SCRAPING_MODE=mock \
  -e PORT=8000 \
  -p 8001:8000 \
  opcg-api-railway-test
```

The app starts and serves `GET /health` even without a reachable database/Redis - it reports
`{"status": "degraded", "database_connected": false, "redis_connected": false, ...}` rather than
crashing, so the image itself is verifiable without real Railway DB/Redis vars in hand. Two
scheme-related gotchas confirmed while testing this locally:

- A **bare** `DATABASE_URL=postgresql://...` (exactly what Railway's Postgres plugin injects,
  unmodified) makes the app crash at import time with `ModuleNotFoundError: No module named
  'psycopg2'` - always rewrite the scheme to `postgresql+psycopg://` (see section 1 above).
- With the scheme corrected, the app starts fine and only reports `database_connected: false` at
  runtime (an actually-unreachable host, expected with a placeholder) - it does not fail the
  build or crash at startup.

## Deploy command reference (Railway CLI)

If using the Railway CLI instead of the dashboard (`npm i -g @railway/cli`, or see Railway's docs
for other install methods - this is optional; the dashboard covers everything below too):

```
railway login
railway link                      # link this repo checkout to the Railway project
railway up --service api          # deploy api
railway up --service worker       # deploy worker
railway up --service beat         # deploy beat
railway run --service api alembic upgrade head   # run migrations
railway logs --service api        # tail logs for a service
```

No Vercel CLI or Railway CLI dependency is added to this repo - both are optional, external tools
you run from your own machine/CI, not something this codebase depends on.
