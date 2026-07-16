# Operations

Common day-to-day commands. Examples use the dev stack (`docker-compose.yml`, container names
like `opcg-postgres`); for production swap in `docker compose -f docker-compose.prod.yml
--env-file .env.production ...` and the `-prod` container names (`opcg-postgres-prod`, etc.) - see
`docs/deployment.md`.

Local/dev shortcuts for the commands below also exist as `make` targets - run `make help` or see
the `Makefile` in the repo root.

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
