# Operations

Common day-to-day commands. Examples use the dev stack (`docker-compose.yml`, container names
like `opcg-postgres`); for production swap in `docker compose -f docker-compose.prod.yml
--env-file .env.production ...` and the `-prod` container names (`opcg-postgres-prod`, etc.) - see
`docs/deployment.md`.

Local/dev shortcuts for the commands below also exist as `make` targets - run `make help` or see
the `Makefile` in the repo root.

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

`-Fc` (custom format) is compressed and lets `pg_restore` do selective/parallel restores. For
production, use the `opcg-postgres-prod` container name instead.

## Restore Postgres

```
docker cp ./opcg-backup-<timestamp>.dump opcg-postgres:/tmp/restore.dump
docker exec opcg-postgres pg_restore -U opcg -d opcg --clean --if-exists /tmp/restore.dump
```

`--clean --if-exists` drops existing objects before recreating them, so this is safe to run
against a database that already has the schema applied. Run `alembic upgrade head` afterward if
the backup predates a newer migration.
