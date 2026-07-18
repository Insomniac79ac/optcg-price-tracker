# Operations

Common day-to-day commands. Examples use the dev stack (`docker-compose.yml`, container names
like `opcg-postgres`); for production swap in `docker compose -f docker-compose.prod.yml
--env-file .env.production ...` and the `-prod` container names (`opcg-postgres-prod`, etc.) - see
`docs/deployment.md`.

Local/dev shortcuts for the commands below also exist as `make` targets - run `make help` or see
the `Makefile` in the repo root.

## Before every production change

Run through this checklist for any change touching the production stack (deploy, migration,
config change) - each step links to the fuller reference section below:

1. **Backup DB** - `make prod-db-backup` (see [Database backup and restore
   drill](#database-backup-and-restore-drill)).
2. **Run release check** - `make release-check` (see `docs/release_checklist.md`), or the full
   fail-fast gate: `make final-audit`.
3. **Deploy** - `make prod-build && make prod-up` (see `docs/deployment.md`).
4. **Migrate** - `make prod-migrate`.
5. **Smoke test** - `ADMIN_TOKEN=<token> make prod-smoke` (see [Smoke test](#smoke-test)).
6. **Check logs** - `make prod-logs`, and `/admin/logs` for structured app errors (see
   [Observability and logs](#observability-and-logs)).
7. **Verify system check** - `GET /admin/system-check` via `/admin/system-check` in the app, or
   `curl -H "X-Admin-Token: $ADMIN_TOKEN" .../admin/system-check` (see [Check environment
   validation](#check-environment-validation)).

## Smoke test

`scripts/smoke_test.sh` (`make smoke-test`) checks that a running stack is actually healthy: API
`/health` (status + database connectivity), `/market/movers` returns valid data, admin auth
correctly rejects an unauthenticated request and accepts a valid `X-Admin-Token`, and the web app
responds. It prints `PASS`/`FAIL` per check and exits non-zero if anything failed - safe to use as
a deploy health gate.

**Locally** (against the dev stack from `docker compose up -d`):

```
ADMIN_TOKEN=<your dev ADMIN_TOKEN> make smoke-test
```

If `ADMIN_TOKEN` isn't set on the dev API at all, the API treats requests as development-mode
(see `docs/deployment.md`) and the "without a token" check will legitimately return something
other than 401 - set `ADMIN_TOKEN` for both the API container and this script if you want to
exercise the real auth path locally.

**After a deployment**, point it at the deployed URLs with the real admin token:

```
API_URL=https://api.example.com \
WEB_URL=https://app.example.com \
ADMIN_TOKEN=<production ADMIN_TOKEN> \
./scripts/smoke_test.sh
```

`API_URL` defaults to `http://localhost:8000`, `WEB_URL` to `http://localhost:3000`. `ADMIN_TOKEN`
is always required - the script fails the admin check if it's missing rather than skipping it.

## Health checks

`docker-compose.prod.yml` gives every service a Docker-level `healthcheck:` - `docker compose -f
docker-compose.prod.yml --env-file .env.production ps` shows each one's status
(`healthy`/`unhealthy`/`starting`) without hitting anything over HTTP yourself:

| Service | Healthcheck |
|---|---|
| `postgres` | `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB` |
| `redis` | `redis-cli ping` |
| `api` | `GET /health` returns HTTP 200 |
| `web` | `GET /api/health` returns HTTP 200 |

`api`, `worker`, and `beat` all wait for `postgres`+`redis` to report `healthy` (not just started)
before starting themselves; `web` additionally waits for `api`. A container stuck `starting` past
its `start_period` almost always means the thing it depends on isn't actually reachable yet (wrong
`DATABASE_URL`/`REDIS_URL`, or postgres still initializing) - check that container's own logs
first (see [Logs](#logs) below), not the dependent one's.

For an end-to-end functional check beyond "the process is healthy" (pages actually render, admin
auth actually works, ...), run `ADMIN_TOKEN=<token> make prod-smoke` - see
[scripts/prod_smoke_test.sh](../scripts/prod_smoke_test.sh) and the [Smoke test](#smoke-test)
section above for the dev-stack equivalent (`make smoke-test`).

## Logs

```
make prod-logs   # all services, follow mode
```

Or a single service (swap in `worker`/`beat`/`web`/`postgres`/`redis`):

```
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f api
```

Drop `-f` to print what's buffered and exit instead of following. Add `--since 1h` (or any Docker
duration) to bound how far back it reads on a long-lived container.

## Check environment validation

```
curl -H "X-Admin-Token: $ADMIN_TOKEN" "http://localhost:8000/admin/env-check"
```

Reports every startup safety check (ADMIN_TOKEN strength/default, DATABASE_URL's default
password, SCRAPING_MODE, market workflow schedule vars, Telegram config completeness, ...) - the
same checks the api and worker/beat services run at process startup (see
`services/api/app/core/env_validation.py`; production fails startup on any critical failure,
development only warns). Useful to re-check a live deployment's config without restarting
anything, e.g. right after rotating `ADMIN_TOKEN` (see `docs/deployment.md`'s "How to rotate
ADMIN_TOKEN"). `status` is `"ok"`, `"warning"`, or `"critical"`; each entry in `checks` carries its
own `status` (`pass`/`warning`/`fail`) and `severity` (`info`/`warning`/`critical`).

The web app's own env check (`NEXT_PUBLIC_API_URL`/`API_INTERNAL_URL` presence, no secret-like
`NEXT_PUBLIC_*` vars) runs at Docker build/start instead of via an API endpoint - see
`apps/web/scripts/check-env.js` (`npm run check-env` to run it manually).

## Check current version

```
curl http://localhost:8000/version
curl -H "X-Admin-Token: $ADMIN_TOKEN" "http://localhost:8000/admin/release-status"
```

`GET /version` (unauthenticated, same trust level as `GET /health`) reports `app`, `version`
(from the repo-root `VERSION` file), `git_commit` and `build_time` (both baked in at Docker build
time by `make prod-build` - see [Version and build metadata](deployment.md#14-version-and-build-metadata)
in docs/deployment.md), and `app_env`. `GET /health` includes `version`/`git_commit` too, for a
quick check without a separate call.

`GET /admin/release-status` (admin-token gated) is the fuller picture: the same version/build
fields plus the latest system check, market workflow run, backup, and error, and a
`release_readiness` summary (`system_check_status`, `critical_logs_last_24h`,
`latest_backup_available`). The `/admin/release-status` page in the web UI (linked from the admin
nav, `/admin/system-check`, and `/admin/actions`) shows the same thing - use it right after a
deploy as step D ("Post-deploy validation") of [docs/release_checklist.md](../docs/release_checklist.md).
The web app's own version (plus, best-effort, the backend's) is at `GET /api/version` on the
`web` container - unauthenticated, no admin token needed.

## Rollback

See [Rollback](deployment.md#rollback) in docs/deployment.md for the quick version, and
[docs/release_checklist.md](../docs/release_checklist.md) section E for the fuller checklist
(identify the previous commit/version, stop services, restore the DB backup only if the deploy
included a data-changing migration, redeploy the previous commit, re-run migrations only if the
schema needs to move as well, smoke test, check logs). The version/build metadata from [Check
current version](#check-current-version) above is what tells you what's actually running before
you decide whether a rollback is even needed.

## Check rate limit status

```
curl -H "X-Admin-Token: $ADMIN_TOKEN" "http://localhost:8000/admin/rate-limit/status"
```

Returns whether rate limiting is enabled and, for each of the five route groups (`public_read`,
`collection_write`, `admin`, `import_export`, `search`), its current limit, window, and
`active_keys` (distinct client IPs with a live counter right now - a large number here across a
short window is a sign of either real traffic growth or abuse worth investigating). See
"Security headers, CSP, and rate limiting" in `docs/deployment.md` for what each group covers and
why this is single-instance only.

**Adjusting limits**: set the matching env var in `.env.production` and restart the `api`
container - limits are read from `Settings` at request time, so no code change is needed:

```
RATE_LIMIT_PUBLIC_READ_PER_5M=300
RATE_LIMIT_COLLECTION_WRITE_PER_5M=60
RATE_LIMIT_ADMIN_PER_5M=120
RATE_LIMIT_IMPORT_EXPORT_PER_10M=20
RATE_LIMIT_SEARCH_PER_5M=120
```

**Temporarily disabling rate limits for troubleshooting** (e.g. a legitimate burst of traffic
getting 429'd, or narrowing down whether rate limiting is the cause of an issue): set
`RATE_LIMIT_ENABLED=false` in `.env.production` and restart `api`. This is safe to do temporarily
but generates a warning on `GET /admin/env-check` (and at startup) while it's off in production -
see [Check environment validation](#check-environment-validation) above. Re-enable it
(`RATE_LIMIT_ENABLED=true`, or just remove the line - `true` is the default) once you're done.

## Run Yuyu-Tei refresh manually

```
docker compose exec worker python -m worker.jobs.refresh_prices --source yuyutei --limit 100
```

Uses whatever `SCRAPING_MODE` (`mock`/`live`) is set in the environment - this command never
changes it. `--limit` defaults to 10 if omitted.

## Run refresh dry-run

```
docker compose exec worker python -m worker.jobs.refresh_prices --source yuyutei --dry-run
```

Fetches and parses without writing any new `price_observations`/`raw_snapshots` rows. The
`price_refresh_runs` audit row is still created either way.

## Import watchlist CSV

```
docker compose exec api python -m app.import_watchlist data/watchlists/opcg_watchlist.csv
```

Imports/updates cards and their Yuyu-Tei/SNKRDUNK source mappings. Safe to re-run.

## Import SNKRDUNK candidates CSV

```
docker compose exec worker python -m worker.jobs.import_snkrdunk_candidates /app/data/imports/snkrdunk_candidates.csv
```

Manual fallback for when live SNKRDUNK discovery isn't available. Does not scrape SNKRDUNK. Pass
`--auto-match-threshold 0.9` to override `SNKRDUNK_AUTO_MATCH_THRESHOLD` for this run.

## Ingest SNKRDUNK candidate prices

```
docker compose exec worker python -m worker.jobs.ingest_snkrdunk_candidate_prices --limit 100
```

Creates `price_observations` from SNKRDUNK candidates that are already matched to a card (via
import + review above). Pure DB-to-DB - does not scrape. Useful flags:

- `--dry-run` - report what would happen without writing rows.
- `--no-only-matched` - also consider `needs_review` candidates that already carry an advisory
  match, not just `auto_matched` ones.
- `--since-run-id <id>` - only candidates from a given `discovery_run_id` onward.

## Check refresh runs

Via the admin API (requires `X-Admin-Token`; see `docs/deployment.md`):

```
curl -H "X-Admin-Token: $ADMIN_TOKEN" \
  "http://localhost:8000/admin/refresh-runs?status=failed&limit=20"

curl -H "X-Admin-Token: $ADMIN_TOKEN" \
  "http://localhost:8000/admin/refresh-runs/<run_id>"
```

Or use the `/admin/refresh-runs` page in the web UI. `status` filters to `running`, `completed`,
`completed_with_warnings`, or `failed`.

## Check alert events

```
curl -H "X-Admin-Token: $ADMIN_TOKEN" \
  "http://localhost:8000/admin/alert-events?status=failed&limit=20"

curl -H "X-Admin-Token: $ADMIN_TOKEN" \
  "http://localhost:8000/admin/alert-events/<event_id>"
```

Or use the `/admin/alerts` page in the web UI. `status` filters to `pending`, `sent`, `failed`, or
`skipped_duplicate`; `event_type` filters to `price_up`, `price_down`, `yuyutei_buy_up`,
`stock_out`, or `refresh_failed`.

To manually trigger an alert check (normally runs automatically after each scheduled refresh):

```
docker compose exec worker python -m worker.jobs.check_alerts --dry-run
docker compose exec worker python -m worker.jobs.check_alerts
```

## Market workflow scheduling

The scheduled market intelligence workflow (refresh prices → snapshot portfolio/market signals →
generate report → optionally send a Telegram digest) is disabled by default. Celery Beat only adds
it to its schedule if `MARKET_WORKFLOW_ENABLED=true` (see
`services/worker/worker/celery_app.py::_build_beat_schedule`); see [Market workflow schedule
config](deployment.md#1c-market-workflow-schedule-config) in docs/deployment.md for the full env
var reference (`MARKET_WORKFLOW_SOURCE`/`_LIMIT`/`_SEND_TELEGRAM`/`_HOUR_UTC`/`_MINUTE_UTC`).
Changing any of these requires restarting `beat` to pick up the new schedule:

```
docker compose -f docker-compose.prod.yml --env-file .env.production restart beat
```

To run the workflow on demand (without waiting for or changing the schedule), via the admin API:

```
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"source": "yuyutei", "send_telegram": false, "dry_run": true}' \
  "http://localhost:8000/admin/actions/run-market-workflow"
```

Or use the "Run market workflow" action on `/admin/actions` in the web UI. `dry_run: true` runs
the full pipeline without writing new rows or sending a digest - use it to sanity-check a schedule
change before letting Beat run it for real. Past runs (scheduled or on-demand) are visible at
`/admin/market-workflow-runs` or `GET /admin/market-workflow-runs`.

## Telegram digest testing

Requires `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` both set (see [Telegram
config](deployment.md#1b-telegram-config)). Send (or dry-run) the latest market intelligence
report's digest independent of the scheduled workflow:

```
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"dry_run": true}' \
  "http://localhost:8000/admin/actions/send-market-report-digest"
```

`dry_run: true` formats the message and reports what would be sent without calling the Telegram
API - use this first to confirm formatting/content. Drop it (or set `false`) to actually send. Digest
sends are deduplicated per report by default; pass `"force": true` in the body to resend a report
that's already been sent. Requires a market intelligence report to already exist (generate one via
the market workflow above, or `POST /admin/actions/generate-market-report`) - returns
`report_id: null` if none exists yet.

## Reset local dev database

```
docker compose exec api python -m app.reset_dev_db --confirm
```

Deletes cards, source mappings, raw snapshots, price observations, and SNKRDUNK discovery data,
then re-seeds `sources`. **Development only** - refuses to run unless `ENVIRONMENT`/`APP_ENV` is
`development`, and refuses to run at all without `--confirm`. Never touches CSV files.

## Backup Postgres

```
docker exec opcg-postgres pg_dump -U opcg -d opcg -Fc -f /tmp/opcg-backup.dump
docker cp opcg-postgres:/tmp/opcg-backup.dump ./opcg-backup-$(date +%Y%m%d-%H%M%S).dump
```

`-Fc` (custom format) is compressed and lets `pg_restore` do selective/parallel restores.

**Production**: `make prod-backup` does the same two steps against `opcg-postgres-prod` via
`docker compose -f docker-compose.prod.yml exec`/`cp`, writing
`./opcg-backup-<timestamp>.dump`. Take one before every deploy that includes a migration - see
[Rollback](deployment.md#rollback) in docs/deployment.md.

## Restore Postgres

```
docker cp ./opcg-backup-<timestamp>.dump opcg-postgres:/tmp/restore.dump
docker exec opcg-postgres pg_restore -U opcg -d opcg --clean --if-exists /tmp/restore.dump
```

`--clean --if-exists` drops existing objects before recreating them, so this is safe to run
against a database that already has the schema applied. Run `alembic upgrade head` (or `make
prod-migrate` in production) afterward if the backup predates a newer migration.

**Production**: swap the container name for `opcg-postgres-prod` (`docker cp` and `docker exec`
both work directly against a named container regardless of which compose file started it, so no
`-f docker-compose.prod.yml` is needed for these two specifically):

```
docker cp ./opcg-backup-<timestamp>.dump opcg-postgres-prod:/tmp/restore.dump
docker exec opcg-postgres-prod pg_restore -U opcg -d opcg --clean --if-exists /tmp/restore.dump
```

## Database backup and restore drill

The manual `pg_dump`/`pg_restore` commands above are fine for a one-off backup before a deploy.
For routine production backups, use the automated scripts instead - they gzip a plain-SQL dump to
`data/backups/db/` (bind-mounted from the host via the `./data:/app/data` volume in
`docker-compose.prod.yml`), so backups survive container recreation:

```
make prod-db-backup              # scripts/db_backup.sh - gzipped pg_dump to data/backups/db/
make prod-db-backup-prune        # scripts/db_backup_prune.sh - dry run, keeps newest 14
make prod-db-backup-prune-apply  # scripts/db_backup_prune.sh --apply - actually deletes old backups
make prod-db-restore BACKUP=data/backups/db/opcg_db_backup_<ts>.sql.gz CONFIRM=RESTORE
```

`prod-db-restore` requires both `BACKUP=<path>` and `CONFIRM=RESTORE` - it refuses to run
otherwise, on top of `db_restore.sh`'s own `CONFIRM_RESTORE=RESTORE` check. It stops
api/worker/beat/web before restoring (postgres and redis keep running), restores the dump,
restarts whichever of those services were running, then runs `alembic upgrade head`. Run
`ADMIN_TOKEN=<token> make prod-smoke` afterward to confirm the stack is healthy.

There's also an on-demand `docker compose --profile backup run --rm db-backup` service in
`docker-compose.prod.yml` that does the same dump from inside the compose network, for
environments where you'd rather not shell out via `docker compose exec` from the host.

`GET /admin/db-backups` (admin-token protected, like the rest of `/admin/*`) lists the backup
files currently on disk (filename, size, created-at) by reading `DB_BACKUP_DIR`
(`data/backups/db` by default) - useful for confirming a scheduled backup actually ran without
shelling into the host:

```
curl -H "X-Admin-Token: $ADMIN_TOKEN" "http://localhost:8000/admin/db-backups"
```

## Observability and logs

The container logs in [Logs](#logs) above show everything a service printed - useful, but noisy,
unstructured, and gone once the container is recreated. `app_log_events` is a separate,
queryable table that api/worker/beat write structured rows to for the events that actually matter
for production debugging (startup failures, env/system-check failures, backup export/validate/
restore outcomes, CSV import errors, price refresh runs, market workflow runs, Telegram digest
sends, and Yuyu-Tei/SNKRDUNK scraping failures) - see `app.services.app_logging`
(`services/api/app/services/app_logging.py`) and its worker mirror
(`services/worker/worker/app_logging.py`).

**Where to view logs.** The `/admin/logs` page (linked from the admin nav, `/admin/actions`,
`/admin/system-check`, and `/admin/market-workflow-runs`) is the primary place - filter by level,
service, event type, or a message search, and open a row for its full message, context JSON, and
traceback. `/dashboard`'s "Workflow status" widget also surfaces a link to `/admin/logs` whenever
there's been an error or warning in the last 24 hours, so you don't have to go looking. The same
data is available via the API directly:

```
curl -H "X-Admin-Token: $ADMIN_TOKEN" "http://localhost:8000/admin/logs?level=error&since_hours=24"
curl -H "X-Admin-Token: $ADMIN_TOKEN" "http://localhost:8000/admin/logs/<id>"
curl -H "X-Admin-Token: $ADMIN_TOKEN" "http://localhost:8000/admin/observability/summary"
```

`GET /admin/observability/summary` is the fastest "is anything on fire" check - last-24h counts by
level plus the latest error, market workflow run, price refresh run, backup, and system-check
status in one call.

**What the levels mean.** `debug` < `info` < `warning` < `error` < `critical`, in ascending
severity - `info` is a normal lifecycle event (a run started/finished successfully), `warning` is
something recoverable that still finished the job (a failed CSV row, a blocked scrape that fell
back to manual import), `error` is a request or step that failed outright (a bad backup restore, a
crashed refresh run), and `critical` is reserved for the api/worker refusing to start at all
(invalid config, failed production environment validation).

**How to prune logs.** `app_log_events` has no automatic retention - use the "Prune logs" section
on `/admin/logs` (or `POST /admin/logs/prune`) to delete rows older than N days. Dry run is the
default (`dry_run: true`, returns `would_delete` without touching anything); set `dry_run: false`
to actually delete. Pruning anything younger than 7 days additionally requires
`confirm: "PRUNE"`, so a mistyped small number can't wipe out most of the table in one call:

```
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"older_than_days": 30, "dry_run": false}' \
  "http://localhost:8000/admin/logs/prune"
```

`app_log_events` rows are excluded from `GET /admin/backup/export` by default, same as prices/raw
snapshots/refresh runs - pass `include_logs=true` (or check "Include logs" on `/admin/backup`) to
include them in a backup.

This manual per-table prune is separate from the broader, scheduled retention policy covering
`app_log_events` and nine other high-volume tables - see [Data retention and
pruning](#data-retention-and-pruning).

**Why secrets are redacted.** `context_json` is sanitized before it's ever written - any key
containing `token`, `secret`, `password`, `key`, `authorization`, or `cookie` (case-insensitive,
substring match) is replaced with `[REDACTED]`, and request bodies are never logged at all. This
is enforced in `app_logging.sanitize_context`, not left to each call site to get right, so a
careless `context={...}` at some future call site can't leak a credential into a table that's
readable by anyone with the admin token and gets bundled into backups.

**When to SSH into server logs anyway.** `app_log_events` only has what the code explicitly
chose to log - for anything not covered above (a crash before the api process finishes importing,
a container that won't start, an OOM kill, raw request/response traffic, or debugging something
that never got instrumented), `docker compose logs` (see [Logs](#logs)) is still the source of
truth. Treat `/admin/logs` as the fast path for the events it covers, not a replacement for
container logs.

## API pagination and response size limits

As `price_observations`, `raw_snapshots`, `collector_activity_events`, `market_signal_events`,
and `app_log_events` grow, an unpaginated list endpoint would eventually return a response large
enough to slow the API down or make the browser struggle to render it. Every list endpoint that
reads from one of those tables (or anything else that can grow without bound - collection,
wishlist, grading submissions, market signals/opportunities/reports, search results, admin
logs/refresh-runs/workflow-runs/source-mappings/SNKRDUNK-candidates/alert-events/db-backups) is
paginated and carries a standard `pagination` metadata block. CSV/backup exports are the one
deliberate exception - see below.

**Limits.** Default page size is 100, capped at 500 (a handful of endpoints - `/collector/notes`,
`/search`, `/search/suggestions` - use a tighter documented max instead, matching how those
endpoints were already scoped before pagination metadata was added). An invalid `limit`/`offset`
is rejected with `422` rather than silently clamped - `limit <= 0`, `limit` over the endpoint's
max, or a negative `offset` all fail the request instead of reinterpreting it. This is enforced
either by FastAPI's `Query(..., ge=1, le=<max>)` on the route itself, or - for the couple of
surfaces that don't get that for free (e.g. `GET /admin/db-backups`) - by the shared
`parse_pagination()` helper in `app.core.pagination` (`services/api/app/core/pagination.py`).

**Response shape.** Every paginated response keeps its existing top-level shape (`items`,
`events`, `opportunities`, `signals`, `results`, `logs`, `reports`, ... - whatever it already
was) and adds a `pagination` object alongside it:

```json
{
  "pagination": {
    "total": 1000,
    "limit": 100,
    "offset": 0,
    "has_next": true,
    "has_previous": false,
    "next_offset": 100,
    "previous_offset": null
  }
}
```

`has_next`/`has_previous` are derived from the actual number of rows returned (not blindly from
`limit`), so a short final page is still correctly reported as the last one. `next_offset`/
`previous_offset` are `null` when there's no next/previous page - fetch the next page with
`?limit=<limit>&offset=<next_offset>`. This is built by `pagination_response()` in the same
`app.core.pagination` module, so every paginated endpoint's metadata is computed the same way
regardless of what its items array is called.

```
curl -H "X-Admin-Token: $ADMIN_TOKEN" "http://localhost:8000/admin/logs?limit=50&offset=50"
curl -H "X-Admin-Token: $ADMIN_TOKEN" "http://localhost:8000/market/opportunities?limit=20"
```

**Exports are not paginated.** `GET /collection/export.csv`, `GET /wishlist/export.csv`, and the
backup endpoints (`GET /admin/backup/export`, `POST /admin/backup/restore`) are intentionally
full exports - a CSV/backup that silently only contained one page of rows would be actively
wrong, not just slow. These endpoints do not accept `limit`/`offset` and carry no `pagination`
key.

**Response size warnings.** Independent of pagination, every response gets an
`X-Response-Size-Bytes` header (read off the `Content-Length` FastAPI already computes, so this
never buffers a second copy of the body just to measure it - see
`app.core.response_size.ResponseSizeMiddleware`,
`services/api/app/core/response_size.py`). A response larger than
`RESPONSE_SIZE_WARNING_BYTES` (env var, default `1000000` = ~1 MB) additionally records a
`warning`-level `app_log_events` row with `event_type=response_size_warning`, containing the
method, path, and size. This is visibility only - oversized responses are never blocked, same
philosophy as the slow-request logging above. Set `RESPONSE_SIZE_WARNING_ENABLED=false` to turn
off the warning writes entirely (the header itself is always added).

**Where to find large-response logs.**

```
curl -H "X-Admin-Token: $ADMIN_TOKEN" \
  "http://localhost:8000/admin/logs?event_type=response_size_warning"
```

Or filter `/admin/logs` in the UI by event type `response_size_warning`. `GET
/admin/performance/summary` also surfaces `response_size_warnings_last_24h`,
`slow_requests_last_24h`, and a `largest_recent_responses` list (the biggest few among the most
recent warnings) - the `/admin/performance` page shows these alongside table row counts and index
audit results, with a link straight into `/admin/logs` pre-filtered to
`event_type=response_size_warning`.

## Data retention and pruning

The tables that grow fastest (`raw_snapshots`, `price_observations`, `app_log_events`,
`collector_activity_events`, `market_signal_events`, and a handful of run/report/digest history
tables) have a retention policy enforced by `app.services.data_retention` - see `GET
/admin/data-retention/policy` for the full, current list, or the `/admin/data-retention` page
(linked from the admin nav, `/admin/performance`, `/admin/logs`, and `/admin/actions`).

**What is pruned, and what is never pruned.** Ten tables are ever touched:

| Table | Default retention | Notes |
|---|---|---|
| `raw_snapshots` | 30 days | |
| `app_log_events` | 60 days | error/critical rows kept 180 days |
| `collector_activity_events` | 365 days | |
| `price_refresh_runs` | 180 days | |
| `market_workflow_runs` | 180 days | |
| `market_report_digest_sends` | 180 days | |
| `market_intelligence_reports` | 365 days | |
| `portfolio_valuation_snapshots` | 365 days | thinned to 1/week beyond 90 days |
| `price_observations` | 365 days | thinned to 1/day beyond 90 days; latest observation per card/source/price type is never deleted regardless of age |
| `market_signal_events` | 365 days | only `dismissed`/`resolved` events age out - `open`/`watching` events are kept forever |

Everything else - `cards`, `sources`, `source_card_mappings`, `collection_items`,
`wishlist_items`, `grading_submissions`, `collector_tags`, `collector_groups`, `collector_notes`,
`alert_rules`, `dashboard_preferences`, and users - is a collector record, not high-volume
telemetry, and is never touched by any of this. There is no code path that can prune one of these
tables; they simply aren't in the prunable-tables list `POST /admin/data-retention/prune` and
`python -m app.prune_data_retention` both check against.

**Always dry-run first.** Every prune path defaults to `dry_run: true` (counts what *would* be
deleted, deletes nothing) and requires an explicit `confirm: "PRUNE"` to actually delete anything.
Run a dry run, sanity-check the counts, then apply:

```
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"dry_run": true}' \
  "http://localhost:8000/admin/data-retention/prune"

curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"dry_run": false, "confirm": "PRUNE"}' \
  "http://localhost:8000/admin/data-retention/prune"
```

Pass `"tables": ["raw_snapshots", "app_log_events"]` to limit either call to specific tables;
omitting `tables` (or passing an empty list) evaluates every prunable table. Each table prunes in
its own transaction, so one table erroring doesn't stop the rest - a failed table shows up as a
`warning` in the response instead.

**Back up the database before a real prune.** A prune is a real `DELETE`, same as any other
destructive operation - take a backup first (see [Database backup and restore
drill](#database-backup-and-restore-drill)):

```
make prod-db-backup
```

**Running from the UI.** `/admin/data-retention` shows the current policy table, lets you
multi-select which tables to evaluate, defaults to dry-run (checkbox, on by default), and only
shows the `PRUNE` confirmation input once you uncheck dry-run - the same guardrail as the backup
page's replace-restore confirmation.

**Running from the CLI.** `python -m app.prune_data_retention` (run inside the `api` container,
or anywhere with `DATABASE_URL` pointed at the same database) is the same logic as the API
endpoint, for a cron job or one-off maintenance without going through the API:

```
docker compose exec api python -m app.prune_data_retention                       # dry run, all tables
docker compose exec api python -m app.prune_data_retention --tables raw_snapshots,app_log_events
docker compose exec api python -m app.prune_data_retention --apply --confirm PRUNE
```

`--apply` without `--confirm PRUNE` exits non-zero without touching anything; a per-table error
during an actual prune is printed as that table's warning, not a nonzero exit.

**Scheduled pruning.** Celery Beat can run this automatically once a day - disabled by default,
same opt-in pattern as the market workflow schedule:

```
DATA_RETENTION_ENABLED=true      # default false - beat does not schedule pruning otherwise
DATA_RETENTION_HOUR_UTC=1        # default 1
DATA_RETENTION_MINUTE_UTC=0      # default 0
```

When enabled, the scheduled run always applies (`dry_run=false`, confirmed internally - there's no
unattended dry-run mode, since a dry run that nobody reads accomplishes nothing) and records a
summary `app_log_events` row (`service=worker`, `event_type=data_retention_prune`) with the
per-table results, visible on `/admin/logs`. A failure never takes down beat or worker startup -
it's caught, logged as `event_type=data_retention_prune_failed`, and beat continues scheduling
everything else normally.

## Worker job concurrency locking

Two triggers for the same job can overlap - an admin clicks "run market workflow" while the
scheduled Celery Beat run is still going, or a scheduled data retention prune fires while someone's
running the CLI version by hand. Without something preventing that, two concurrent runs can create
duplicate snapshots/report rows or step on each other's writes. `job_locks` (one row per lock name,
`services/api/app/models/job_lock.py`) is a simple mutual-exclusion lock every one of these jobs
acquires before doing any real work, backed by `app.services.job_locks`
(`services/api/app/services/job_locks.py`) on the api side and its mirror `worker.job_locks`
(`services/worker/worker/job_locks.py`) on the worker side - both talk to the same table.

**Lock names and TTLs.** A lock's TTL is a generous multiple of how long that job normally takes -
long enough that a merely-slow run is never mistaken for a crashed one, short enough that a
genuinely crashed job doesn't block its lock forever.

| Lock name                   | TTL     | Guards                                                  |
| ---------------------------- | ------- | -------------------------------------------------------- |
| `price_refresh`              | 30 min  | `worker.jobs.refresh_prices` (manual CLI, scheduled Yuyu-Tei refresh, on-demand via admin) |
| `market_workflow`            | 60 min  | `worker.jobs.run_market_workflow` (scheduled/manual), and `POST /admin/actions/full-market-refresh` |
| `portfolio_snapshot`         | 10 min  | `app.snapshot_portfolio_valuation` (CLI + admin action)   |
| `market_signal_snapshot`     | 10 min  | `app.services.market_signal_events.snapshot_market_signals` (CLI + admin action) |
| `market_report_generation`   | 10 min  | `app.services.market_report.generate_market_report` (CLI + admin action) |
| `telegram_market_digest`     | 5 min   | `app.services.telegram_market_digest.send_market_report_digest` (CLI + admin action) |
| `data_retention_prune`       | 30 min  | `app.services.data_retention.prune_tables` (CLI + admin action) and the worker's scheduled prune task |
| `backup_restore`             | 60 min  | `app.services.backup.restore_backup` (CLI + `POST /admin/backup/restore`) |

Acquisition is non-blocking: if a lock is already held and not expired, the caller fails
immediately rather than waiting for it to free up. A job that needs more than one lock (e.g.
`run_market_workflow` holding `market_workflow` while it calls `refresh_prices`, which acquires its
own `price_refresh` lock) always acquires a *different*-named lock, never the same one twice - so
there's no circular-wait condition and no deadlock is possible, regardless of nesting order.

**What happens on conflict.**

- Admin endpoints (`POST /admin/actions/refresh-prices`, `/full-market-refresh`,
  `/run-market-workflow`, `/snapshot-portfolio`, `/snapshot-market-signals`,
  `/generate-market-report`, `/send-market-report-digest`, `POST /admin/data-retention/prune`,
  `POST /admin/backup/restore`) return `409` with:

  ```json
  {
    "detail": "Job already running",
    "lock_name": "market_workflow",
    "expires_at": "2026-07-18T17:19:20.454454+00:00"
  }
  ```

- Every CLI script (`python -m worker.jobs.refresh_prices`, `python -m
  worker.jobs.run_market_workflow`, `python -m app.snapshot_portfolio_valuation`, `python -m
  app.snapshot_market_signals`, `python -m app.generate_market_report`, `python -m
  app.send_market_report_digest`, `python -m app.prune_data_retention`, `python -m
  app.restore_backup`) prints `Job already running: <lock_name>` and exits with status `2`.

- Each of these functions/scripts takes a `--skip-lock` CLI flag (or `skip_lock=True` kwarg)
  that bypasses locking entirely. **Test/dev only - never pass this in production**, and it is
  never exposed through the admin API/UI. Dry runs still acquire the lock by default (a dry-run
  preview racing a real run is exactly the kind of overlap this is meant to prevent).

**Inspecting and managing locks.** `GET /admin/job-locks` (admin token required) lists every
currently-active lock:

```json
{
  "locks": [
    {
      "lock_name": "market_workflow",
      "owner_id": "market_workflow:3f1e2a7c-...",
      "acquired_at": "2026-07-18T16:19:20.454454+00:00",
      "expires_at": "2026-07-18T17:19:20.454454+00:00",
      "status": "active",
      "metadata": {"source": "yuyutei", "limit": 10, "dry_run": false}
    }
  ]
}
```

`POST /admin/job-locks/cleanup-expired` marks any active-but-past-`expires_at` lock as `expired`
and returns `{"cleaned_up_count": N}` - a lock this happens to catches usually means a job crashed
without releasing it. `POST /admin/job-locks/{lock_name}/force-release` with body `{"confirm":
"RELEASE"}` releases an active lock outright, regardless of who holds it - **only use this if
you're sure the job actually crashed**; it does not check whether the job is still running, and
force-releasing a lock out from under a still-running job re-opens exactly the overlap this system
exists to prevent. A force release always records a `warning`-level `app_log_events` row
(`event_type=lock_force_released`) - this is meant to be rare and worth a human noticing. The
`/admin/job-locks` page mirrors all three of these, with the force-release confirmation requiring
you to type `RELEASE`.

**Where to see lock activity.** Every acquire/release/failed-acquire is an `app_log_events` row:

```
curl -H "X-Admin-Token: $ADMIN_TOKEN" "http://localhost:8000/admin/logs?event_type=lock_acquired"
curl -H "X-Admin-Token: $ADMIN_TOKEN" "http://localhost:8000/admin/logs?event_type=lock_released"
curl -H "X-Admin-Token: $ADMIN_TOKEN" "http://localhost:8000/admin/logs?event_type=lock_acquire_failed"
curl -H "X-Admin-Token: $ADMIN_TOKEN" "http://localhost:8000/admin/logs?event_type=lock_force_released"
curl -H "X-Admin-Token: $ADMIN_TOKEN" "http://localhost:8000/admin/logs?event_type=lock_expired_cleanup"
```

Repeated `lock_acquire_failed` attempts against the same still-active holder (e.g. a beat schedule
firing every few minutes while a slow job is still running) only log once, so a long-running job
doesn't flood `app_log_events` with one row per retry - a conflict against a *different* holder (the
lock changed hands) always logs again. `GET /admin/performance/summary` also surfaces
`active_job_locks`/`expired_job_locks` counts, and `GET /admin/system-check` includes three checks:
an informational active-lock count, a warning if any active lock is past its `expires_at`, and a
warning specifically if the `market_workflow` lock (the longest-running one) is stuck past its TTL.

## Reverse proxy troubleshooting

See "Production deployment behind HTTPS reverse proxy" in `docs/deployment.md` for initial setup
(Nginx/Caddy config, DNS, firewall). This section covers what to check once it's live but
something's wrong.

**Web loads but API data is missing** (pages render, but everything that needs the API shows
empty/error states): almost always `API_INTERNAL_URL` on the `web` container is wrong or `api`
isn't healthy. Check `GET https://yourdomain.com/api/backend-health` first - it calls
`API_INTERNAL_URL/health` from `web`'s own server-side code and reports what it got back,
including the specific connect/timeout error if `api` wasn't reachable at all. Then:
```
docker compose -f docker-compose.prod.yml --env-file .env.production exec web env | grep API_INTERNAL_URL
docker compose -f docker-compose.prod.yml --env-file .env.production ps api
```
`API_INTERNAL_URL` should be `http://api:8000` in the default setup - anything else (a public URL,
a typo'd service name) breaks server-side proxying even though `api` itself is perfectly healthy.

**502 from the reverse proxy**: the proxy reached the host/port it's configured for, but got
nothing usable back - almost always means the `web` container isn't up or isn't healthy yet, not a
proxy misconfiguration. Check:
```
docker compose -f docker-compose.prod.yml --env-file .env.production ps web
docker compose -f docker-compose.prod.yml --env-file .env.production logs --tail 100 web
curl -i http://127.0.0.1:3000/api/health
```
If the last command works from the host but the proxy still 502s, double check the proxy's
upstream address matches (`127.0.0.1:3000` for the Nginx example, `localhost:3000` for the Caddy
one) and that `docker-compose.prod.private.yml`'s port binding (if you're using it) is
`127.0.0.1:${WEB_PORT}:3000`, not some other host/port the proxy isn't pointed at.

**Upload fails** (CSV import, backup restore) with a proxy-level error rather than the app's own
validation error: check `client_max_body_size` (Nginx) or `request_body.max_size` (Caddy) - both
example configs set 50M, matching what backup/CSV uploads can reasonably need. Nginx's own default
is 1M, which is well below a real collection export - a request over the limit gets rejected by
the proxy itself (a plain `413`, no JSON body) before it ever reaches `web`/`api`, which can look
like a generic "upload failed" in the browser rather than an obviously-a-size-limit error.

**HTTPS certificate renewal**: Caddy renews automatically in the background - nothing to do.
Certbot (Nginx) installs a systemd timer (`certbot.timer`) that runs twice daily and only actually
renews within ~30 days of expiry - verify it's active with `systemctl list-timers | grep certbot`,
and test the renewal path itself (without waiting for expiry) with `sudo certbot renew --dry-run`.
If the timer isn't present, `sudo certbot install --nginx` or re-running the original `certbot
--nginx` command from the setup steps re-registers it.

**The admin token is still required** - a reverse proxy changes network topology, not
authentication. Every `/admin/*` (and `/snkrdunk/*`) request still needs `X-Admin-Token`, whether
it arrives via the proxy on the public domain or hits `api` directly; putting a proxy in front
doesn't add, remove, or substitute for that check. If you uncommented the optional `/api-backend`
proxy location, admin endpoints reached through it are exactly as protected as they were before -
see the warning comment on that location block in both example configs.

**Rate limit behavior behind a proxy**: `app.core.rate_limit` keys its per-IP counters off
`X-Forwarded-For` (falling back to the direct connection's IP if that header is absent - see
`app.core.rate_limit._client_ip`). Both example proxy configs already set this header correctly
(`proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for` in Nginx, `header_up X-Forwarded-For
{remote_host}` in Caddy). If every request behind your proxy is getting rate-limited together
(one client's traffic exhausting the limit for everyone), that's a sign `X-Forwarded-For` either
isn't being set or is being overwritten somewhere - all requests would appear to originate from
the proxy's own loopback IP instead of the real clients'. Verify with `GET
/admin/rate-limit/status` (see "Check rate limit status" above): `active_keys` staying at `1` under
real multi-client traffic is the tell.
