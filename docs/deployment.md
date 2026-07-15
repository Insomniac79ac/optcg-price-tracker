# Deployment

Deploying the OPTCG price tracker (api, web, worker, beat, postgres, redis) with
`docker-compose.prod.yml`. This does not change any application behavior - it only wires up
production-safe container config around the existing app.

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
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm api \
  alembic upgrade head
```

Run this once per deployment, after `postgres` is up and before `api`/`worker`/`beat` start
serving/processing (or immediately after, before relying on new tables/columns).

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
docker compose -f docker-compose.prod.yml --env-file .env.production build
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
```

`api` and `web` are only `expose`d on the Docker network (container-to-container), not published
to the host - put a reverse proxy (nginx, Caddy, Traefik, a cloud load balancer, ...) in front of
them for external traffic, terminating TLS there. `postgres` and `redis` are not published to the
host at all; only reachable from other containers on the compose network.

## 7. Checking health

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
- Railway's Postgres plugin injects `DATABASE_URL` as a bare `postgresql://` string - rewrite the
  scheme to `postgresql+psycopg://` when setting it as the `api`/`worker`/`beat` env var (this app
  uses sync SQLAlchemy via `psycopg`, not an async driver).
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
