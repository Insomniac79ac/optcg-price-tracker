# Deployment

Deploying the OPTCG price tracker (api, web, worker, beat, postgres, redis) with
`docker-compose.prod.yml`. This does not change any application behavior - it only wires up
production-safe container config around the existing app.

## Quick deploy flow

The `Makefile`'s `prod-*` targets (all a thin wrapper around `docker compose -f
docker-compose.prod.yml --env-file .env.production ...`) cover the common path end to end. Each
step below links to the fuller reference section if you need more than the one-liner.

1. Create `.env.production` from the template: `cp .env.production.example .env.production` (see
   [section 1](#1-required-environment-variables)).
2. Set a strong `ADMIN_TOKEN` (>= 32 chars, not the local-dev default - see
   [How to rotate ADMIN_TOKEN](#1e-how-to-rotate-admin_token); `openssl rand -hex 32` works for a
   first value too, not just rotations).
3. Set `DATABASE_URL` (must not contain the default local password `opcg:opcg` - see
   [section 1](#1-required-environment-variables)).
4. Set `REDIS_URL`.
5. Configure Telegram if you want alerts/digests sent (`TELEGRAM_BOT_TOKEN` +
   `TELEGRAM_CHAT_ID` - both or neither, see [section 1b](#1b-telegram-config)).
6. Build: `make prod-build`.
7. Start: `make prod-up`.
8. Run migrations: `make prod-migrate`.
9. Smoke test: `ADMIN_TOKEN=<token> make prod-smoke` (runs `scripts/prod_smoke_test.sh` - see
   [docs/operations.md](operations.md#health-checks)).
10. View logs: `make prod-logs`.

Before any of this, `make prod-verify` is safe to run with no `.env.production` and no real
secrets at all - it checks `docker-compose.prod.yml` is well-formed, the images build, and (with
`RUN_TESTS=true`) the test suites pass. Good as a pre-deploy CI gate or a first sanity check on a
fresh checkout.

Cutting an actual release (not just a one-off deploy)? See
[docs/release_checklist.md](release_checklist.md) for the full pre-release/build/deploy/rollback/
emergency checklist, and `make release-check` (`scripts/release_check.sh`) to automate the
mechanical parts of it - git status, secrets, and compose config in one command. See
[docs/route_inventory.md](route_inventory.md) for the full list of routes (public, admin, API) this
app exposes, with auth requirements and nav-reachability for each.

Before treating a deploy as production-ready, run the final gate: `bash scripts/final_audit.sh` (or
`make final-audit`) - it fails fast through secrets, release-check, both compose configs, and the
api/worker test suites, then confirms every file this doc and the release checklist depend on
actually exists. `SKIP_TESTS=true` skips the pytest steps (e.g. dev stack not up);
`ALLOW_DIRTY=true` forwards through to `release_check.sh` for a dirty working tree.

**Deploying against a database with a large/production-scale amount of data?** Also run the Phase
7 performance audit first - `RUN_PHASE7_AUDIT=true bash scripts/final_audit.sh`, or directly `bash
scripts/phase7_audit.sh` (optionally with `RUN_LOAD_TESTS=true`) - to confirm pagination, caching,
data retention/pruning, worker job locks, and background file jobs all still hold up at that
volume before you cut over. See [docs/performance_testing.md](performance_testing.md).

## Rollback

If a deploy goes bad:

1. **Stop services**: `make prod-down` (or stop just the misbehaving one, e.g.
   `docker compose -f docker-compose.prod.yml --env-file .env.production stop api`, if
   `postgres`/`redis` are fine and you don't want to drop connections to them).
2. **Restore the DB backup** taken before the deploy (see
   [Backup Postgres](operations.md#backup-postgres) / [Restore Postgres](operations.md#restore-postgres)
   in docs/operations.md - `make prod-backup` takes the "before" one; restore with `pg_restore`
   against the `opcg-postgres-prod` container). Skip this step if the deploy didn't include a
   migration or other data change.
3. **Redeploy the previous image/commit**: `git checkout <previous-commit-or-tag>` (or point your
   registry/deploy tooling at the previous image tag if you build/push images elsewhere), then
   `make prod-build && make prod-up`.
4. **Run the smoke test again**: `ADMIN_TOKEN=<token> make prod-smoke` - don't consider the
   rollback done until this passes.

## 1. Required environment variables

Copy the template and fill in real values:

```
cp .env.production.example .env.production
```

`.env.production` is gitignored - never commit it. `docker-compose.prod.yml` reads it via
`env_file:` for the api/worker/beat/web containers.

| Variable | Required | Notes |
|---|---|---|
| `APP_ENV` | yes | Must be `production`. The API and worker/beat refuse to start in production if any critical env check fails (see [Production required env vars](#1a-production-required-env-vars--startup-validation) below). |
| `DATABASE_URL` | yes | Full SQLAlchemy URL, e.g. `postgresql+psycopg://opcg:<password>@postgres:5432/opcg`. The user/password/db must match `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` below. Must not contain the default local dev password (`opcg:opcg`). |
| `REDIS_URL` | yes | e.g. `redis://redis:6379/0`. Used as the Celery broker/backend. |
| `ADMIN_TOKEN` | yes in production | Shared secret for `/admin/*` API routes - see [Admin token usage](#9-admin-token-usage). Must be >= 32 characters and not the local-dev default. Generate with e.g. `openssl rand -hex 32`. |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | yes | Used to initialize the `postgres` container. Keep in sync with `DATABASE_URL`. |
| `SCRAPING_MODE` | yes | `mock` or `live`. Set to `live` for a real deployment. |
| `YUYUTEI_REQUEST_DELAY_MS` / `SNKRDUNK_REQUEST_DELAY_MS` | yes | Positive integers (milliseconds) - throttling between scrape requests. Must be >= 1000 when `SCRAPING_MODE=live`. |
| `PRICE_REFRESH_INTERVAL_HOURS` | yes | Positive integer - how often Celery Beat schedules the Yuyu-Tei refresh. |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | optional | Both or neither - see [Telegram config](#1b-telegram-config). |
| `MARKET_WORKFLOW_*` | optional | Disabled by default - see [Market workflow schedule config](#1c-market-workflow-schedule-config). |
| `NEXT_PUBLIC_API_URL` | yes | Public URL the browser uses to reach the API. **Baked into the web image at build time** (Next.js inlines `NEXT_PUBLIC_*` vars at `next build`) - changing it requires rebuilding the `web` image, not just restarting the container. |
| `API_INTERNAL_URL` | yes in production | Server-side-only URL the web app's Next.js API routes (`src/app/api/**`) use to reach `api` directly (e.g. `http://api:8000`), instead of `NEXT_PUBLIC_API_URL`. Never expose this as a `NEXT_PUBLIC_*` variable. |
| `API_JWT_SECRET` | yes in production | Shared between `api` and `web` - verifies the per-user bearer token the web app mints on sign-in. See [Per-user auth](#10-per-user-auth-google-login). Generate with e.g. `openssl rand -hex 32`, distinct from `ADMIN_TOKEN`. |
| `AUTH_SECRET` | yes in production | Auth.js's own session-encryption secret (web only). Generate with `openssl rand -base64 33`. |
| `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` | yes in production | From a Google Cloud OAuth 2.0 Client ID (web only). See [Per-user auth](#10-per-user-auth-google-login). |
| `CORS_ALLOWED_ORIGINS` / `CORS_ALLOW_ORIGIN_REGEX` | optional | Locks the API's CORS policy down to your deployed frontend's origin(s) instead of the dev default `*`. See `services/api/app/main.py`. |
| `WEB_PORT` | optional | Host port `web` is published on - default `3000`. See [section 6](#6-starting-production-services). |
| `RATE_LIMIT_ENABLED` | optional | Default `true`. See [section 12](#12-security-headers-csp-and-rate-limiting) - leaving this on is strongly recommended unless a reverse proxy already enforces limits. |
| `RATE_LIMIT_PUBLIC_READ_PER_5M` / `RATE_LIMIT_COLLECTION_WRITE_PER_5M` / `RATE_LIMIT_ADMIN_PER_5M` / `RATE_LIMIT_IMPORT_EXPORT_PER_10M` / `RATE_LIMIT_SEARCH_PER_5M` | optional | Per-route-group request limits - see [section 12](#12-security-headers-csp-and-rate-limiting) for defaults and what each group covers. |

Compose does **not** auto-load `.env.production` (it only auto-loads a file literally named
`.env`). Always pass `--env-file .env.production` explicitly, as shown below.

### 1a. Production required env vars & startup validation

`APP_ENV=production`, `DATABASE_URL`, `REDIS_URL`, and `ADMIN_TOKEN` are required in every
production deployment. Beyond just being *set*, they (and every optional var above) are checked
for safety/shape at process startup:

- `services/api/app/core/env_validation.py` (api) and its mirror `services/worker/worker/env_validation.py`
  (worker and beat - both run `celery -A worker.celery_app`, which imports this at module level)
  read the raw process environment and run the same set of checks in both services.
- **In production** (`APP_ENV`/`ENVIRONMENT=production`), a failed check raises at import time and
  the process refuses to start - `ADMIN_TOKEN` missing/the local-dev default/under 32 characters,
  `DATABASE_URL` containing the default local password, an invalid `SCRAPING_MODE`,
  `SCRAPING_MODE=live` without both request delays >= 1000ms, an invalid `MARKET_WORKFLOW_*`
  schedule value, or incomplete Telegram config are all hard failures.
- **In development**, the identical issue is logged as a warning instead - local defaults (the
  repo-root `.env`'s `local-dev-admin-token`, etc.) keep working unattended.
- One check is a warning-only exception to the "fails in production" rule above:
  `RATE_LIMIT_ENABLED=false` in production never blocks startup, only warns - disabling rate
  limiting is a deliberate operator choice (e.g. a reverse proxy already enforces limits), not
  necessarily a misconfiguration. See [section 12](#12-security-headers-csp-and-rate-limiting).

To check a running deployment's env validation status at any time (not just at startup):

```
curl -H "X-Admin-Token: $ADMIN_TOKEN" http://api:8000/admin/env-check
```

Returns `{"status": "ok" | "warning" | "critical", "app_env": ..., "checks": [...], "warnings":
[...], "errors": [...]}` - one entry per check, each with `status` (`pass`/`warning`/`fail`) and
`severity` (`info`/`warning`/`critical`). Also visible in the web UI at `/admin/system-check`'s
sibling env-check view. See the frontend equivalent in [section 1d](#1d-frontend-env-validation).

### 1b. Telegram config

`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are optional, but must be set together - if only one
is present, the worker logs a warning and skips sending alerts in development, and **fails
startup in production**. If `MARKET_WORKFLOW_SEND_TELEGRAM=true` (see below), both must be set
regardless of environment for the scheduled digest to actually send.

### 1c. Market workflow schedule config

Disabled by default - Celery Beat never runs the scheduled market intelligence workflow unless
`MARKET_WORKFLOW_ENABLED=true` (see `services/worker/worker/celery_app.py::_build_beat_schedule`).
When enabling it in production:

| Variable | Valid values | Default |
|---|---|---|
| `MARKET_WORKFLOW_ENABLED` | boolean-like (`true`/`false`/`1`/`0`/`yes`/`no`) | `false` |
| `MARKET_WORKFLOW_SOURCE` | `all`, `yuyutei`, `snkrdunk` | `yuyutei` |
| `MARKET_WORKFLOW_LIMIT` | positive integer, or blank for no limit | blank |
| `MARKET_WORKFLOW_SEND_TELEGRAM` | boolean-like | `false` |
| `MARKET_WORKFLOW_HOUR_UTC` | `0`-`23` | `0` |
| `MARKET_WORKFLOW_MINUTE_UTC` | `0`-`59` | `0` |

### 1d. Frontend env validation

`apps/web/scripts/check-env.js` (`npm run check-env`) checks that `NEXT_PUBLIC_API_URL` is set,
that `API_INTERNAL_URL` is set (skipped at Docker build time, since it's a runtime-only server
var), and - most importantly - that **no `NEXT_PUBLIC_*` variable name looks like a secret**
(contains `TOKEN`, `SECRET`, `PASSWORD`, or `KEY`). Next.js inlines every `NEXT_PUBLIC_*` var into
the client-side JS bundle verbatim at build time, so `NEXT_PUBLIC_ADMIN_TOKEN` or similar would
ship a real secret to every visitor's browser. `apps/web/Dockerfile` runs this at build time
(`node scripts/check-env.js build`, before `next build`); `npm start` runs it again at container
start (`node scripts/check-env.js start`, which also checks `API_INTERNAL_URL`). Fails the
build/start in production; only warns in development.

### 1e. How to rotate ADMIN_TOKEN

1. Generate a new token: `openssl rand -hex 32`.
2. Update `ADMIN_TOKEN` in `.env.production` (and wherever else it's stored - your hosting
   provider's secrets manager, CI/CD env vars, etc. - see [Secret handling](#2-secret-handling)).
3. Restart `api`, `worker`, and `beat` so they pick up the new value (all three validate it at
   startup - see [section 1a](#1a-production-required-env-vars--startup-validation)):
   ```
   docker compose -f docker-compose.prod.yml --env-file .env.production up -d api worker beat
   ```
4. Update any external client/script that sends `X-Admin-Token` (the web UI just prompts for a
   new one on its next admin request - see [Admin token usage](#9-admin-token-usage)).
5. Confirm the rotation took: `curl -H "X-Admin-Token: $ADMIN_TOKEN" http://api:8000/admin/env-check`
   should return `admin_token_present`/`admin_token_not_default`/`admin_token_length` all `pass`.

Rotate immediately (not on a routine schedule) if the token was ever committed to git, logged, or
otherwise exposed - see [Secret handling](#2-secret-handling) for why deleting/force-pushing
afterward doesn't undo that exposure.

## 2. Secret handling

`.env.production` holds real secrets (`ADMIN_TOKEN`, `POSTGRES_PASSWORD`, `DATABASE_URL`,
optionally `TELEGRAM_BOT_TOKEN`) and **must never be committed or pushed**. `.gitignore` ignores
all `.env*` files except `.env.example` and `.env.production.example` (which must only ever
contain placeholders, never real-looking values), and `scripts/check_secrets.sh` (`make
check-secrets`) fails the build if git is ever tracking a real env file - run it before pushing if
you're unsure.

In a real hosting environment, don't rely on an `.env.production` file on disk at all where you
can avoid it - configure these values through your hosting provider's own secret/environment
variable system instead (e.g. a cloud provider's secrets manager, your CI/CD platform's encrypted
environment variables, Docker/Kubernetes secrets, etc.), and generate `.env.production` from that
system at deploy time rather than storing it as a plain file on a shared machine.

**If a secret was ever committed to git** (even in a since-deleted commit - git history keeps
it), treat it as compromised: rotate it immediately (generate a new `ADMIN_TOKEN`, change the
Postgres password, regenerate the Telegram bot token, etc.) and update `.env.production`
everywhere it's deployed. Deleting the file or force-pushing history afterward does not undo
exposure to anyone who already cloned/fetched it.

To confirm your resolved production config (with real values filled in) is well-formed, without
ever writing those values anywhere they could get committed:

```
docker compose --env-file .env.production -f docker-compose.prod.yml config
```

This prints the fully-interpolated compose config to your terminal for review - don't redirect it
into a file inside the repo.

## 3. Database migrations

```
make prod-migrate   # docker compose -f docker-compose.prod.yml exec api alembic upgrade head
```

Run this once per deployment, after `postgres` is up and before `api`/`worker`/`beat` start
serving/processing (or immediately after, before relying on new tables/columns). Uses `exec`, not
`run --rm`, so it applies against the same running `api` container (and its already-validated env)
rather than a fresh one-off container.

## 4. Seed reference data

```
docker compose -f docker-compose.prod.yml --env-file .env.production exec api \
  python -m app.seed
```

Creates/updates the `sources` table (`yuyutei`, `snkrdunk`) only. Do **not** pass `--demo-data`
in production - that flag seeds placeholder cards for local dev/testing.

## 5. Import the card watchlist

```
docker compose -f docker-compose.prod.yml --env-file .env.production exec api \
  python -m app.import_watchlist data/watchlists/opcg_watchlist.csv
```

Imports/updates the real card catalog and its Yuyu-Tei/SNKRDUNK source mappings from a CSV (see
`data/watchlists/`). Safe to re-run - it upserts by card identity.

## 6. Starting production services

```
make prod-build   # docker compose -f docker-compose.prod.yml build
make prod-up      # docker compose -f docker-compose.prod.yml up -d
```

`web` is published to the host on `${WEB_PORT:-3000}` (set `WEB_PORT` in `.env.production` to
change it) - that's the one production service meant to be reachable directly, and what
`scripts/prod_smoke_test.sh`'s default `BASE_URL` targets. `api`, `postgres`, and `redis` are only
`expose`d on the Docker network (container-to-container) or not exposed at all - never published
to the host, and never should be. Put a reverse proxy (nginx, Caddy, Traefik, a cloud load
balancer, ...) in front of `web` for a real domain/TLS; if you need to reach `api` directly (e.g.
for `curl`-based admin checks without going through `web`), add your own `ports:` mapping for it
rather than relying on this file to publish it.

Every service starts only after its dependencies report healthy, not just started - `api`,
`worker`, and `beat` wait on `postgres`/`redis` healthchecks (`pg_isready` / `redis-cli ping`), and
`web` waits on `api`'s own `GET /health`. `docker compose ps` shows each container's health status;
see [Health checks](operations.md#health-checks) in docs/operations.md for the full healthcheck
reference and troubleshooting a container stuck `starting`/`unhealthy`.

## 7. Checking health

`docker compose -f docker-compose.prod.yml --env-file .env.production ps` shows each container's
Docker-level health status (`healthy`/`unhealthy`/`starting`) at a glance - see
[Health checks](operations.md#health-checks) in docs/operations.md for what each service's
healthcheck actually runs. For an end-to-end functional check (not just "is the process up"), run
`ADMIN_TOKEN=<token> make prod-smoke` (`scripts/prod_smoke_test.sh`) after every deploy.

From another container on the same network, or through your reverse proxy:

```
curl http://api:8000/health
```

Response:

```json
{
  "status": "ok",
  "app_env": "production",
  "database_connected": true,
  "redis_connected": true
}
```

`status` is `"degraded"` if `database_connected` is `false`. Also see:

```
docker compose -f docker-compose.prod.yml --env-file .env.production exec api \
  python -m app.check_config
docker compose -f docker-compose.prod.yml --env-file .env.production exec worker \
  python -m worker.jobs.check_config
```

Both print config/connectivity status and exit non-zero if misconfigured - useful in deploy
health checks.

## 8. Checking logs

```
make prod-logs   # docker compose -f docker-compose.prod.yml logs -f (all services)
```

Or a single service:

```
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f api
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f worker
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f beat
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f web
```

## 9. Admin token usage

`/admin/alert-events`, `/admin/alert-rules`, `/admin/refresh-runs`, and `/snkrdunk/candidates`
all require the `X-Admin-Token` header to match `ADMIN_TOKEN`:

```
curl -H "X-Admin-Token: $ADMIN_TOKEN" http://api:8000/admin/refresh-runs
```

Missing/invalid token → `401`. If `ADMIN_TOKEN` is unset and `APP_ENV`/`ENVIRONMENT` is not
`development`, the API refuses to start at all (see `services/api/app/main.py`).

In the web UI (`/admin/alerts`, `/admin/refresh-runs`, `/admin/snkrdunk-candidates`), the first
visit prompts for the admin token and stores it in the browser's `localStorage`; each admin page
has a "Clear admin token" button to log out. See `docs/operations.md` for day-to-day commands.

## 10. Per-user auth (Google login)

`/collection`, `/grading`, and `/collector` (tags/groups) require a signed-in user - each
person's portfolio is isolated by `user_id`. This is a completely separate mechanism from the
admin token above: `/admin/*` still requires only `X-Admin-Token`, with no interaction with user
accounts at all.

**How it works**: the web app uses [Auth.js](https://authjs.dev) (`next-auth@5`) with a Google
provider, in stateless JWT session mode (no database adapter - Auth.js itself never touches
Postgres). On sign-in, `apps/web/src/lib/auth.ts`'s `session` callback mints a *separate*,
short-lived (1 hour) HS256 bearer token signed with `API_JWT_SECRET`, exposed to client code as
`session.apiToken`. Every `/collection`/`/grading`/`/collector` request attaches this as
`Authorization: Bearer <token>`; the API verifies it with the same `API_JWT_SECRET`
(`services/api/app/auth.py::require_current_user`) and JIT-provisions a `User` row the first time
a given Google account is seen - there is no separate signup step. This two-token design (Auth.js's
own encrypted session cookie, plus this app-specific bearer token) exists because the API is
typically deployed on a different host/domain than the web app (see the Railway+Vercel section
below) - a cross-domain cookie would hit browser SameSite/third-party-cookie restrictions, and
replicating Auth.js's own JWE session-decryption in Python is needlessly fragile. A plain shared
secret + bearer header works identically regardless of hosting topology.

**Setup**:
1. In [Google Cloud Console](https://console.cloud.google.com/apis/credentials), create an OAuth
   2.0 Client ID of type "Web application".
2. Add an authorized redirect URI: `<your-web-origin>/api/auth/callback/google` (e.g.
   `https://your-app.vercel.app/api/auth/callback/google`, or `http://localhost:3000/api/auth/callback/google`
   for local dev).
3. Set `AUTH_GOOGLE_ID`/`AUTH_GOOGLE_SECRET` (web) from that client's id/secret, `AUTH_SECRET`
   (web) to a random value, and `API_JWT_SECRET` to the same random value on **both** `api` and
   `web`.

`/collection`/`/grading` pages are gated by `apps/web/middleware.ts`, which redirects an
unauthenticated visitor to `/` with a `callbackUrl` query param rather than rendering the page.

## 11. Split deployment: Vercel (web) + Railway (api/worker/beat/postgres/redis)

Vercel only runs the Next.js frontend well - it has no support for the long-lived Postgres/Redis
connections, Celery worker, or Celery beat scheduler this app also needs. A common split: deploy
`web` to Vercel, and everything else (`postgres`, `redis`, `api`, `worker`, `beat`) to Railway (or
Render/Fly.io - the same shape applies).

**Railway**:
- Use Railway's managed Postgres and Redis plugins rather than self-hosting those two containers.
- Deploy `api`, `worker`, and `beat` from their existing Dockerfiles (`services/api/Dockerfile`,
  `services/worker/Dockerfile`), with the same commands as `docker-compose.prod.yml` uses.
- Railway's Postgres plugin injects `DATABASE_URL` as a bare `postgresql://` string
  (`${{Postgres.DATABASE_URL}}`). This app uses sync SQLAlchemy via `psycopg` (v3), not an async
  driver, and normalizes the scheme itself at startup (`normalize_database_url()` in
  `app/settings.py`/`worker/settings.py`) - set `DATABASE_URL=${{Postgres.DATABASE_URL}}` directly
  on `api`/`worker`/`beat`, no manual scheme rewriting needed. (Staging is currently on a
  temporary manually-corrected reference predating this normalization - see
  `docs/railway_staging.md` section 1 for why, and don't simplify it until that code is deployed
  and verified there.)
- Set the same env vars as section 1 above (`ADMIN_TOKEN`, `API_JWT_SECRET`, etc.) on the `api`
  service; `worker`/`beat` don't need `API_JWT_SECRET` (they never verify bearer tokens).
- Run `alembic upgrade head` once against Railway's Postgres before serving traffic (a one-off
  Railway CLI/dashboard command, same migration as section 3 above).
- Only `api` needs a public domain; `worker`/`beat`/`postgres`/`redis` stay private.

**Vercel**:
- Import the repo with **Root Directory = `apps/web`** (a monorepo project setting).
- Set `NEXT_PUBLIC_API_URL` and `API_INTERNAL_URL` to the Railway API's public HTTPS URL (the
  former is inlined at build time; the latter replaces the docker-only `http://api:8000` default
  used by the server-side proxy routes under `src/app/api/**`).
- Set `AUTH_SECRET`, `AUTH_GOOGLE_ID`, `AUTH_GOOGLE_SECRET`, and `API_JWT_SECRET` (same value as
  Railway's) as Production + Preview environment variables.
- Set `CORS_ALLOWED_ORIGINS`/`CORS_ALLOW_ORIGIN_REGEX` on the Railway `api` service to your Vercel
  domain (and `https://.*\.vercel\.app` for preview deployments).

## 11a. Staging deployment (Vercel + Railway)

Section 11 above sketches the general shape of a Vercel+Railway split for a *production* deploy.
For a staging environment specifically - its own env vars, safe defaults (`SCRAPING_MODE=mock`,
scheduled workflows disabled), deploy order, migrations, smoke tests, and a step-by-step
checklist - see:

- [docs/staging_deployment.md](staging_deployment.md) - architecture overview, required env vars,
  deploy order, migration/smoke-test steps, rollback notes, known limitations, and safety notes.
- [docs/railway_staging.md](railway_staging.md) - per-service Railway setup (`api`, `worker`,
  `beat`, managed Postgres, managed Redis), reusing this repo's existing Dockerfiles.
- [docs/staging_checklist.md](staging_checklist.md) - the before/deploy/smoke/after-deploy
  checklist to run through for an actual staging deploy.
- [.env.staging.example](../.env.staging.example) - the staging env var template (placeholders
  only, never commit a real `.env.staging`).

## 12. Security headers, CSP, and rate limiting

This app has no user accounts and no external auth - the hardening here is aimed at basic
production abuse (scraping the API itself, brute-forcing the admin token, clickjacking the web
app), not a login/session security model.

**Run behind a reverse proxy, and use HTTPS.** Neither `docker-compose.prod.yml`'s `api`/`web`
services nor this app's own code terminate TLS - `api`/`postgres`/`redis` aren't published to the
host at all (see [section 6](#6-starting-production-services)), and `web` is published in plain
HTTP on `WEB_PORT`. Put a real reverse proxy (nginx, Caddy, Traefik, or your cloud provider's load
balancer) in front of `web` for a real domain and TLS certificate before exposing this to the
internet - Caddy in particular gets you automatic HTTPS (Let's Encrypt) with a few lines of
Caddyfile. If you're doing the [split Vercel + Railway deployment](#11-split-deployment-vercel-web--railway-apiworkerbeatpostgresredis)
instead, both platforms already terminate TLS for you.

**Security response headers** (`app.core.security_headers.SecurityHeadersMiddleware`, applied to
every API response) are fixed, not configurable - `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy: camera=(),
microphone=(), geolocation=()`, and `Content-Security-Policy: default-src 'none'; frame-ancestors
'none'` (this is a pure JSON API - it never itself embeds or is meant to be embedded as HTML, so a
maximally restrictive CSP is safe). `/admin/*` and `/snkrdunk/*` responses additionally get
`Cache-Control: no-store`, since those are the endpoints gated by `ADMIN_TOKEN` and must never be
cached by an intermediate proxy or the browser.

The **web app's CSP** (`apps/web/next.config.ts`) is necessarily looser, since it actually renders
HTML/JS: `script-src`/`style-src` allow `'unsafe-inline'` (Next.js injects an inline hydration
bootstrap script on every page; there's no nonce-based CSP wired up here) and dev builds
additionally allow `'unsafe-eval'` (required for fast refresh/HMR, dropped in production builds).
`connect-src` is built from `NEXT_PUBLIC_API_URL` at build time, so it only allows the actual
configured API origin (plus `localhost:8000`/`127.0.0.1:8000` as a dev-only convenience) - browser-
side requests to any other origin are blocked. If you add a new third-party script, font, or image
host, you'll need to widen the matching CSP directive in `next.config.ts` or it'll be silently
blocked (check the browser console for a CSP violation, not a generic network error).

**Rate limiting** (`app.core.rate_limit`) is in-memory, keyed by client IP + route group, no
external dependency. Five groups, each independently configurable via env var (defaults shown):

| Group | Applies to | Default limit | Window |
|---|---|---|---|
| `public_read` | Non-admin `GET` endpoints | `RATE_LIMIT_PUBLIC_READ_PER_5M=300` | 5 min |
| `collection_write` | Collection/wishlist/grading/note writes | `RATE_LIMIT_COLLECTION_WRITE_PER_5M=60` | 5 min |
| `admin` | All `/admin/*` and `/snkrdunk/*` (admin-token-gated) | `RATE_LIMIT_ADMIN_PER_5M=120` | 5 min |
| `import_export` | CSV import/export, backup export/validate/restore, DB backup listing | `RATE_LIMIT_IMPORT_EXPORT_PER_10M=20` | 10 min |
| `search` | `/search`, `/search/suggestions` | `RATE_LIMIT_SEARCH_PER_5M=120` | 5 min |

A request over its group's limit gets `429` with `{"detail": "Rate limit exceeded",
"retry_after_seconds": N}` and `Retry-After`/`X-RateLimit-Limit`/`X-RateLimit-Remaining`/
`X-RateLimit-Reset` headers (the last three are also included on successful responses, so a
well-behaved client can back off before actually hitting the limit). `GET /admin/rate-limit/status`
reports current state - see [how to check it](operations.md#check-rate-limit-status) in
docs/operations.md.

**Important: this is single-instance only.** Counters live in the `api` process's own memory -
running more than one `api` container/replica behind a load balancer means each instance enforces
its own limit independently (N instances effectively multiplies every limit by N, and an attacker
distributed across instances via round-robin evades limiting almost entirely). If you scale `api`
horizontally, move rate limiting to your reverse proxy (nginx's `limit_req`, Caddy's `rate_limit`
plugin, or similar) or a shared store (Redis, e.g. via `slowapi`) instead of relying on this
in-memory implementation - it exists to give a single-server deployment basic protection with zero
extra infrastructure, not to be a distributed rate limiter.

`RATE_LIMIT_ENABLED=false` disables all rate limiting (still safe to leave the security headers
and CSP on) - see [section 1a](#1a-production-required-env-vars--startup-validation) for why this
warns rather than fails startup in production.

## 13. Production deployment behind HTTPS reverse proxy

Everything in [section 6](#6-starting-production-services) gets a working deployment on plain HTTP
at whatever host/port `web` is published on. This section covers putting a real reverse proxy in
front of it for a real domain, HTTPS, and a smaller public attack surface - recommended for any
deployment reachable from the public internet.

**Recommended architecture**:

```
Internet -> Nginx or Caddy (TLS termination, port 443/80) -> web (127.0.0.1:3000)
                                                                -> api (internal Docker network only)
                                                                     -> postgres, redis (internal Docker network only)
```

Only `web` is reachable from outside the host at all, and only through the reverse proxy - not
directly on its Docker-published port. Everything else talks over the Docker Compose network's
internal DNS (`api`, `postgres`, `redis`), which nothing outside the host can reach regardless of
firewall rules.

**Why api/postgres/redis should stay unpublished**: `postgres` and `redis` have no
authentication/TLS of their own in this setup (see the "never expose Postgres/Redis publicly"
comments in `docker-compose.prod.yml`) - reachable-from-anywhere means anyone who finds the port
has the whole database. `api` does have `ADMIN_TOKEN`-gated admin routes and per-user JWT auth, so
it's less immediately catastrophic to expose, but every additional public listener is one more
thing to patch, monitor, and rate-limit - and `web`'s own server-side code never needs `api` to be
public in the first place (it talks to it over `API_INTERNAL_URL=http://api:8000`, the internal
Docker network address). The one caveat: this app's browser-side code calls the API *directly* for
the signed-in per-user pages (`/collection`, `/wishlist`, `/grading`, `/collector`) via
`NEXT_PUBLIC_API_URL` - see the comment on that variable in `.env.production.example`. If you want
those pages to work, `api` needs to be reachable from the browser somehow (either its own public
port, or the optional `/api-backend` proxy location in the example configs below) - every other
part of the app, including all `/admin/*` functionality, works with `api` fully private.

**Using `docker-compose.prod.private.yml`**: this override pins `web` to `127.0.0.1` only (instead
of every interface) and makes the "api/postgres/redis are never published" guarantee explicit
rather than implicit. Add it with a second `-f` to every prod compose command:

```
docker compose -f docker-compose.prod.yml -f docker-compose.prod.private.yml \
  --env-file .env.production up -d
```

(The `Makefile`'s `prod-*` targets use `docker-compose.prod.yml` alone - either pass the extra
`-f` by hand as above, or edit `PROD_COMPOSE` in the `Makefile` to include it by default once
you've set up a reverse proxy.)

### Nginx setup

1. Install Nginx and Certbot (`sudo apt install nginx certbot python3-certbot-nginx` on
   Debian/Ubuntu, or your distro's equivalent).
2. Copy `deploy/nginx/opcg.conf.example` to `/etc/nginx/sites-available/opcg.conf`, replace every
   `example.com` with your real domain, and symlink it into `sites-enabled/`:
   ```
   sudo cp deploy/nginx/opcg.conf.example /etc/nginx/sites-available/opcg.conf
   sudo ln -s /etc/nginx/sites-available/opcg.conf /etc/nginx/sites-enabled/
   ```
3. **Certbot note**: `certbot --nginx -d example.com -d www.example.com` will detect the server
   block from step 2, request a certificate, and rewrite the config's `ssl_certificate`/
   `ssl_certificate_key` lines to point at it automatically (matching the placeholder paths already
   in the example file). It also installs a systemd timer (`certbot.timer`) that handles renewal -
   no cron job to set up by hand. Verify the timer exists with `systemctl list-timers | grep
   certbot`.
4. `sudo nginx -t` to validate the config, then `sudo systemctl reload nginx`.
5. Bring up the app stack itself with the private compose override (see above), so `web` is only
   reachable via the Nginx you just configured.

### Caddy setup

1. Install Caddy (see https://caddyserver.com/docs/install for your distro).
2. Copy `deploy/caddy/Caddyfile.example` to `/etc/caddy/Caddyfile` and replace `example.com` with
   your real domain:
   ```
   sudo cp deploy/caddy/Caddyfile.example /etc/caddy/Caddyfile
   ```
3. `sudo systemctl reload caddy` (or `sudo systemctl restart caddy` if it wasn't running yet).
   Caddy requests and renews its own certificate automatically the first time it sees a request for
   the domain in the Caddyfile - no separate Certbot/ACME client step needed.
4. Bring up the app stack with the private compose override, same as the Nginx path above.

### DNS/domain checklist

- An `A` (and `AAAA`, if you have an IPv6 address) record for your domain pointing at the server's
  public IP, created *before* running Certbot/starting Caddy - both need the domain to already
  resolve to this host to issue a certificate for it.
- If using `www.example.com` too (the Nginx example config includes it), a second `A`/`CNAME`
  record for that name as well.
- DNS propagation can take minutes to hours depending on your registrar/provider and previous TTL -
  verify with `dig +short example.com` before troubleshooting a cert-issuance failure as anything
  else.

### Firewall checklist

- Allow `80` and `443` (inbound) - required for HTTP->HTTPS redirect, the ACME HTTP-01 challenge,
  and the actual HTTPS traffic.
- Restrict SSH (`22`, or whatever port you use) to known IPs/a VPN if at all possible, and disable
  password auth in favor of keys - the reverse proxy setup here doesn't change your SSH exposure,
  and it's a much more common actual break-in vector than anything in this app.
- Do **not** expose `5432` (Postgres), `6379` (Redis), or `8000` (api) unless you have a specific,
  deliberate reason to (e.g. temporary direct-API debugging - see the commented `/api-backend`
  location in the example proxy configs, and prefer removing it again once you're done). None of
  these need to be reachable from outside the host for the app to work; `docker-compose.prod.yml`
  and `docker-compose.prod.private.yml` already keep them off the host's published ports by
  default - a host firewall (`ufw`, `iptables`, your cloud provider's security group) is a second
  layer in case that default is ever changed by mistake.

### Smoke test through the reverse proxy

Once DNS resolves and the certificate is issued, re-run the smoke test against the public domain
instead of `127.0.0.1`:

```
WEB_BASE_URL=https://yourdomain.com ADMIN_TOKEN=<token> make prod-smoke
```

`API_URL` is optional and should only be set if you've deliberately exposed `api` (see the firewall
checklist above) - `scripts/prod_smoke_test.sh` verifies the backend transitively either way, since
`$WEB_BASE_URL/api/health` only reports `"ok"` if `web`'s server-side code can actually reach `api`
over `API_INTERNAL_URL`. `BASE_URL` still works as a deprecated alias for `WEB_BASE_URL` if you have
existing deploy scripts using it. See the env var comments at the top of `scripts/prod_smoke_test.sh`
for the full list.

## 14. Version and build metadata

Every image built by `make prod-build` is tagged with three values, baked in as Docker build args
(`GIT_COMMIT`/`BUILD_TIME`/`APP_VERSION` - see `services/api/Dockerfile`, `services/worker/Dockerfile`,
and `apps/web/Dockerfile`) and therefore fixed for the life of that image, regardless of what
`.env.production` says at runtime:

| Value | Source | Where it's read back |
|---|---|---|
| `APP_VERSION` | The repo-root `VERSION` file (e.g. `0.1.0`) | `GET /version`, `GET /health`, `GET /admin/release-status`, `GET /api/version` |
| `GIT_COMMIT` | `git rev-parse --short HEAD` at build time | same as above |
| `BUILD_TIME` | A UTC timestamp at build time | same as above |

`make prod-build` computes and passes all three automatically - no manual steps for a normal
release. To check a running deployment's version:

```
curl http://localhost:8000/version
curl -H "X-Admin-Token: $ADMIN_TOKEN" http://localhost:8000/admin/release-status
```

`GET /version` is unauthenticated (same trust level as `GET /health`) and returns `{"app": ...,
"version": ..., "git_commit": ..., "build_time": ..., "app_env": ...}`. `GET
/admin/release-status` (admin-token gated, and its `/admin/release-status` web page - linked from
the admin nav, `/admin/system-check`, and `/admin/actions`) additionally rolls up the latest
system check, market workflow run, backup, and error into one `release_readiness` summary - see
[docs/release_checklist.md](release_checklist.md) section D ("Post-deploy validation"). The web
app's own `GET /api/version` reports its own build metadata plus (best-effort) the backend's, for
a single call that covers both services.

If you build images outside of `make prod-build` (a separate CI/CD pipeline, a registry push
step), pass the same three build args yourself:

```
docker build --build-arg GIT_COMMIT=$(git rev-parse --short HEAD) \
  --build-arg BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --build-arg APP_VERSION=$(cat VERSION) \
  -t opcg-api ./services/api
```

Omitting them falls back to each Dockerfile's default (`unknown` for `GIT_COMMIT`/`BUILD_TIME`,
the `VERSION` file's contents or `0.1.0` for `APP_VERSION`) rather than failing the build - useful
for a quick local test build, but always pass real values for anything you intend to deploy, so a
rollback (see [Rollback](#rollback) above) can actually identify what's running.
