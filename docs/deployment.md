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
| `APP_ENV` | yes | Must be `production`. The API refuses to start in production without `ADMIN_TOKEN` set (see `services/api/app/config_check.py`). |
| `DATABASE_URL` | yes | Full SQLAlchemy URL, e.g. `postgresql+psycopg://opcg:<password>@postgres:5432/opcg`. The user/password/db must match `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` below. |
| `REDIS_URL` | yes | e.g. `redis://redis:6379/0`. Used as the Celery broker/backend. |
| `ADMIN_TOKEN` | yes in production | Shared secret for `/admin/*` API routes - see [Admin token usage](#9-admin-token-usage). Generate with e.g. `openssl rand -hex 32`. |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | yes | Used to initialize the `postgres` container. Keep in sync with `DATABASE_URL`. |
| `SCRAPING_MODE` | yes | `mock` or `live`. Set to `live` for a real deployment. |
| `YUYUTEI_REQUEST_DELAY_MS` / `SNKRDUNK_REQUEST_DELAY_MS` | yes | Positive integers (milliseconds) - throttling between scrape requests. |
| `PRICE_REFRESH_INTERVAL_HOURS` | yes | Positive integer - how often Celery Beat schedules the Yuyu-Tei refresh. |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | optional | Both or neither. If only one is set, the worker logs a warning and skips sending alerts. |
| `NEXT_PUBLIC_API_URL` | yes | Public URL the browser uses to reach the API. **Baked into the web image at build time** (Next.js inlines `NEXT_PUBLIC_*` vars at `next build`) - changing it requires rebuilding the `web` image, not just restarting the container. |

Compose does **not** auto-load `.env.production` (it only auto-loads a file literally named
`.env`). Always pass `--env-file .env.production` explicitly, as shown below.

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
