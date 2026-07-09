# optcg-price-tracker

Tracks One Piece Card Game (OPTCG) price changes across **Yuyu-Tei** and **SNKRDUNK**, so that
price trends and drops can be monitored over time.

## Planned stack

- **Web**: Next.js
- **API**: FastAPI
- **Database**: Postgres
- **Cache / queue**: Redis
- **Worker**: Python

## Development approach

Development starts with mock data. Live scraping of Yuyu-Tei and SNKRDUNK is added only after
the core data model, API, and worker pipeline work end-to-end against mock data.

## Local development workflow

```
docker compose up -d postgres api
docker compose exec api alembic upgrade head
docker compose exec api python -m app.seed
docker compose exec api python -m app.import_watchlist data/watchlists/opcg_watchlist.csv
```

- `alembic upgrade head` applies the database schema.
- `python -m app.seed` creates/updates the `sources` table (`yuyutei`, `snkrdunk`) only. It does
  **not** create sample cards - the real card catalog comes from importing a watchlist CSV. Pass
  `--demo-data` if you want placeholder demo cards for local testing:
  `docker compose exec api python -m app.seed --demo-data`.
- `python -m app.import_watchlist <csv>` imports/updates the real card catalog and its
  Yuyu-Tei/SNKRDUNK source mappings from a CSV file (see `data/watchlists/`).

### Resetting local dev data

To wipe local dev data (cards, source mappings, raw snapshots, price observations, SNKRDUNK
discovery data) and start clean, keeping/recreating the `sources` table:

```
docker compose exec api python -m app.reset_dev_db --confirm
```

This only runs when `ENVIRONMENT` (or `APP_ENV`) is set to `development` - it refuses to run
otherwise, and refuses to run at all without `--confirm`. It never touches CSV files, only
database rows.

## Status

This repository currently contains only the project skeleton (directory layout and config
placeholders). No application code has been written yet.
