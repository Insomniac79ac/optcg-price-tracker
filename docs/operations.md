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
- `--no-only-matched` - also consider `suggested` candidates that already carry an advisory
  match, not just `matched` ones.
- `--since-run-id <id>` - only candidates from a given `discovery_run_id` onward.

## Review SNKRDUNK candidate matches

`snkrdunk_candidates.match_status` uses five values: `unmatched`, `suggested`, `ambiguous`,
`matched`, `rejected`. The worker's import/discovery jobs above only ever set the first four via
their own simpler tiered matcher (`worker.matching.snkrdunk_matcher`); `matched`/`rejected` beyond
that always come from an explicit human decision. The richer, deterministic 0-100 scorer in
`app.services.card_matching` (metadata-aware: card_code, set_code, rarity, name_en/name_jp,
character, variant, card_type, color) only runs when an admin asks for it, via:

```
curl -H "X-Admin-Token: $ADMIN_TOKEN" \
  "http://localhost:8000/admin/snkrdunk-candidates/<candidate_id>/matches"

curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" \
  "http://localhost:8000/admin/snkrdunk-candidates/<candidate_id>/rematch"

curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"status": "all", "limit": 200, "dry_run": true}' \
  "http://localhost:8000/admin/snkrdunk-candidates/rematch-all"

curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"card_id": 123, "review_notes": "confirmed"}' \
  "http://localhost:8000/admin/snkrdunk-candidates/<candidate_id>/approve-match"

curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"review_notes": "wrong card"}' \
  "http://localhost:8000/admin/snkrdunk-candidates/<candidate_id>/reject-match"
```

Or use the `/admin/snkrdunk-candidates` page in the web UI (status/confidence/score/card-code
filters, a match-detail modal per candidate, and a dry-run-first "rematch all" bulk action).
`approve-match` is the only place this workflow ever creates/updates a `source_card_mappings` row
(`manual_verified=true`, `review_status=approved`); `reject-match` never creates one and never
deletes an existing mapping. Ambiguous candidates (top two scores within 5 points) are never
auto-suggested - they always need a human pick.

## Catalog operations workflow

This is the entry point for every catalog/data-quality tool in "CSV import validation workflow",
"Catalog coverage workflow", and "Price source health workflow" below, plus card audit, duplicate
review, and SNKRDUNK candidate matching - all of it is also reachable from one landing page,
`/admin/catalog-ops` (nav-linked from the admin dropdown and cross-linked from every page it
covers), which shows a compact cross-subsystem summary (metadata completion, mapping coverage,
recent price coverage, duplicate risk count, mapping quality critical count, price source health
warnings, latest import validation status) alongside links to each tool.

Recommended end-to-end sequence when growing or cleaning up the catalog:

1. **Validate the CSV** using CSV import validation (`POST /admin/import-validation/{import_type}` or the
   `/admin/import-validation` page) - never writes imported data, only reports what it found.
2. **Dry-run the catalog import** (`POST /admin/cards/import.csv?dry_run=true`, or `python -m
   app.import_cards_csv <file> --dry-run`) and review the preview.
3. **Run the real import** (`dry_run=false`) once the dry-run preview looks right.
4. **Check card audit** (`GET /admin/card-audit` or `/admin/card-audit`) for identity/data-quality
   issues the import may have introduced.
5. **Check duplicate review** (`GET /admin/cards/duplicates` or `/admin/card-duplicates`) for any
   new duplicate-card risk.
6. **Merge duplicates only after previewing** - `GET /admin/cards/{source_card_id}/merge-preview`
   (or the "Preview merge" button in the UI) before `POST /admin/cards/merge`. Never merge from a
   bulk action without reviewing each preview first.
7. **Review SNKRDUNK candidates manually** (`/admin/snkrdunk-candidates`, see "Review SNKRDUNK
   candidate matches" above) - ambiguous candidates always need a human pick.
8. **Review source mapping quality** (`GET /admin/source-mappings/quality` or
   `/admin/source-mapping-quality`) for low-confidence, stale, unverified, or duplicate-source-URL
   mappings.
9. **Check catalog coverage** (`GET /admin/catalog-coverage` or `/admin/catalog-coverage`) - see
   "Catalog coverage workflow" below.
10. **Check price source health** (`GET /admin/price-source-health` or `/admin/price-source-health`)
    - see "Price source health workflow" below.
11. **Run a normal price refresh** - `POST /admin/actions/refresh-prices` (see "Run Yuyu-Tei refresh
    manually" above). This workflow never adds a new way to trigger a refresh beyond what already
    exists.
12. **Run system check** (`GET /admin/system-check` or `/admin/system-check`) - surfaces a
    `catalog_operations` summary (card audit status, duplicate risk count, mapping quality critical
    count, catalog coverage percentages, price source health status, latest import validation
    status, and a `warnings` list) built from the same summarized services the tools above use, so
    it stays fast even on a large catalog.

**Safety notes:**

- Never bypass SNKRDUNK (or Yuyu-Tei) website protections - if automated discovery reports
  `blocked`, use the manual CSV candidate import instead of forcing discovery through anyway (see
  "Import SNKRDUNK candidates CSV" above).
- Use manual imports when automated discovery is blocked - the manual `snkrdunk_candidates` CSV
  import + candidate review workflow is the supported fallback and does not scrape SNKRDUNK.
- Validation does not write imported data - `POST /admin/import-validation/{import_type}` only ever
  persists a summary row to `import_validation_reports`; it never writes to `cards`,
  `source_card_mappings`, or any other imported-data table.
- Merge tools never hard-delete cards - `POST /admin/cards/merge` marks the source card
  `is_active=false` with `merged_into_card_id` set (see "Fix source mapping gaps"/"Review duplicate
  risks" in "Catalog coverage workflow" below); the row and its history stay in the database.
- Never bulk merge cards without reviewing previews - `POST /admin/cards/duplicates/bulk-preview`
  is preview-only (no merge side effects); always inspect each `field_merge_preview`/
  `affected_records` before calling `POST /admin/cards/merge` for a given pair.

CLI reference (all run via `docker compose exec api python -m <module>`, matching the pattern used
throughout this file):

| Module | Purpose |
|---|---|
| `app.import_cards_csv <file> [--dry-run] [--overwrite]` | Import a canonical `card_catalog` CSV (same importer as `POST /admin/cards/import.csv`) |
| `app.export_cards_csv [--output PATH]` | Export the canonical card catalog to CSV (default `data/exports/cards_export.csv`) |
| `app.validate_import_csv <file> --type <type> [--strict] [--json] [--user-id N] [--no-save-report]` | Dry-run CSV validation (see "CSV import validation workflow" below); exits `0` if valid, `1` otherwise |
| `app.catalog_coverage_report [--set-code CODE] [--json] [--output PATH]` | Catalog coverage summary (see "Catalog coverage workflow" below) |
| `app.price_source_health_report [--source NAME] [--json] [--output PATH]` | Price source health summary (see "Price source health workflow" below) |

Also runnable end-to-end via `scripts/phase9_audit.sh` (fails fast, covers every admin endpoint
and CLI module above against a live `make dev-up` stack - see that script's header comment for env
vars).

## CSV import validation workflow

Before a larger `card_catalog`/`source_mappings`/`snkrdunk_candidates`/`collection`/`wishlist`
CSV is actually imported, validate it first - `app.services.import_templates` and
`app.services.import_validation` back a dedicated dry-run pass that never writes to the
database, no matter how clean the file is. The recommended flow:

1. **Download a template.** `GET /admin/import-templates` lists all five types (filename,
   description, required/optional columns, a download URL); `GET
   /admin/import-templates/{type}.csv` returns that type's header row plus a filled-in sample
   row. Also available from the "Download templates" section of `/admin/import-validation`.
2. **Fill in the CSV** using the template's columns - required columns must be present and
   non-blank on every row; optional columns can be left blank.
3. **Validate the upload**, without writing anything:

   ```
   curl -H "X-Admin-Token: $ADMIN_TOKEN" \
     -F "file=@cards.csv" \
     "http://localhost:8000/admin/import-validation/card_catalog?strict=false&max_preview_rows=100"
   ```

   `import_type` is one of `card_catalog`, `source_mappings`, `snkrdunk_candidates`,
   `collection`, `wishlist`. `strict=true` turns unknown (unrecognized) columns into errors
   instead of warnings. `collection`/`wishlist` also accept `user_id` to scope would_update/
   likely-duplicate detection to one user's existing rows - without it, every valid
   collection/wishlist row is reported as `would_create`. The response reports `valid`, a
   `summary` (total/valid/error/warning/duplicate row counts, plus would_create/would_update/
   would_skip), `columns` (required/optional/received/missing/unknown), and per-row `errors`/
   `warnings` (`row_number`, `field`, `value`, `code`, `message`) plus a bounded `preview` of
   what each row would do. Every call also persists a summary row to
   `import_validation_reports` (see `GET /admin/import-validation/reports` and `GET
   /admin/import-validation/reports/{id}` for history/detail) - nothing else is written.
4. **Review errors/warnings.** Fix every error (missing required fields, invalid values,
   unresolvable `card_code`/`source_name` references, ambiguous matches, ...) before proceeding;
   warnings (a normalized value, an inferred `set_code`, a likely duplicate, a low-confidence
   match, ...) are worth a look but don't block an import.
5. **Run a dry-run import** through the type's real importer once validation is clean enough -
   e.g. `POST /admin/cards/import.csv?dry_run=true` for `card_catalog`, `POST
   /collection/import.csv?dry_run=true` for `collection`, and so on (see this file's other
   import sections above). Validation and the real importers both resolve identity the same
   way (card_code/set_code/rarity/variant/language for cards, (source_id, source_url) for
   mappings, source_url for candidates, ...), but validation's preview is not a substitute for
   the real importer's own dry-run - always dry-run the actual import too before writing.
6. **Run the real import** (`dry_run=false`) once the dry-run preview looks right.
7. **Check `GET /admin/card-audit` and `GET /admin/source-mappings/quality`** afterward for any
   new duplicate-card or low-confidence-mapping issues the import introduced.

The `/admin/import-validation` page in the web UI covers steps 1-4 end to end (template
downloads, an upload form with strict-mode/max-preview-rows/user_id controls, and report
history) and is linked from the admin nav, `/admin/cards`, `/admin/card-audit`,
`/admin/source-mapping-quality`, and `/admin/backup`. `GET /admin/system-check` also surfaces
the latest validation report's status and warns if several validation reports have failed in
the last 7 days. This tool never scrapes anything and never bypasses website protections - it
only ever reads a CSV a human already produced.

CLI equivalent (also persists a report row by default):

```
docker compose exec api python -m app.validate_import_csv data/imports/cards.csv --type card_catalog
```

Flags: `--type` (required, one of the five types above), `--strict`, `--max-preview-rows N`
(default 100), `--json` (print the full JSON report instead of a summary), `--user-id N`
(collection/wishlist only), `--no-save-report` (skip persisting a report row). Exits `0` if the
file is valid, `1` otherwise - suitable for a pre-import CI/scripted check.

## Catalog coverage workflow

`GET /admin/catalog-coverage` (backed by `app.services.catalog_coverage`) answers "how complete
is the canonical card catalog" across sets/rarities/variants/languages - source mappings, recent
prices, collection/wishlist coverage, metadata completeness, and the duplicate/mapping-quality
risk already tracked by `app.services.card_identity_merge`/`app.services.source_mapping_confidence`.
Read-only: it never writes to the database, scrapes anything, or uses an LLM.

Recommended flow when growing or auditing the catalog:

1. **Import/validate catalog data** - see "CSV import validation workflow" above; import the
   canonical `card_catalog` rows (and their `source_mappings`) before checking coverage.
2. **Check catalog coverage.** `GET /admin/catalog-coverage` (optional `set_code`/`language`/
   `variant`/`rarity` filters, `include_inactive=true` to include merged/inactive cards in the
   totals) returns a top-line `summary`, per-dimension breakdowns (`coverage_by_set/rarity/
   variant/language`), and five gap lists (`metadata_gaps`, `mapping_gaps`, `price_gaps`,
   `duplicate_risks`, `mapping_quality_risks`). A Yuyu-Tei price counts as "recent" within 24
   hours of `observed_at`; a SNKRDUNK price within 7 days (Yuyu-Tei is scraped far more often -
   see "Run Yuyu-Tei refresh manually" above). For a large catalog, drill into one gap type at a
   time with `GET /admin/catalog-coverage/gaps?gap_type=<metadata|mapping|price|duplicate|
   mapping_quality>` (also takes `set_code`/`rarity`/`variant`/`language`/`severity`/`limit`/
   `offset`) rather than paging through the full report. The `/admin/catalog-coverage` page in
   the web UI covers both, and is linked from the admin nav, `/admin/cards`, `/admin/card-audit`,
   `/admin/source-mapping-quality`, `/admin/card-duplicates`, and `/admin/system-check`.
3. **Fix metadata gaps** - a card missing `card_code`/`name_en` is `critical`; missing
   `set_code`/`rarity`/`variant`/`language` is `warning`; missing `image_url`/`artist`/
   `character`/`color`/`card_type` is `review`. Fix via a `card_catalog` re-import (see the CSV
   import validation workflow) or `PATCH /admin/cards/{id}`.
4. **Fix source mapping gaps** - a card with zero active mappings to a supported source
   (`yuyutei`, `snkrdunk`) is `critical`; missing just one is `warning`. Add mappings via a
   `source_mappings` import or `POST /admin/source-mappings`.
5. **Review duplicate risks** - reuses `app.services.card_identity_merge`'s scoring
   (`MIN_MERGE_SCORE`) rather than a separate O(n²) scan; see `GET /admin/cards/duplicates` and
   "Card duplicate review" in the admin UI to actually merge.
6. **Review mapping quality risks** - reuses `app.services.source_mapping_confidence`'s
   `risk_level`; see `GET /admin/source-mappings/quality` to review/recheck/replace the flagged
   mapping.
7. **Rerun `GET /admin/card-audit` and `GET /admin/system-check`** afterward - both surface a
   catalog-coverage summary (mapping/recent-price/metadata coverage percentages, unmapped/
   duplicate/mapping-quality-risk counts) without repeating every gap the coverage page already
   lists individually; `system-check` warns when mapping or recent-price coverage drops below
   50%, metadata completion drops below 70%, or any duplicate/mapping-quality risk exists.

CLI equivalent (prints a summary; add `--json` for the full report, `--output PATH` to also
write it to a file):

```
docker compose exec api python -m app.catalog_coverage_report --set-code OP01
```

The report is cached under the `admin/catalog_coverage` prefix (see "Cache operations" below,
`CACHE_CATALOG_COVERAGE_TTL_SECONDS`, default 120s) and is invalidated by any write that changes
cards, source mappings, collection items, or wishlist items - see that write path's own
`CACHE_INVALIDATES`/`WRITE_CACHE_PREFIXES` list.

## Price source health workflow

`GET /admin/price-source-health` (backed by `app.services.price_source_health`) answers "is each
price source actually healthy right now": recent refresh success/failure, SNKRDUNK
automated-discovery blocked status, and stale/missing prices on active `source_card_mappings`.
Read-only - it never triggers a refresh, retries a blocked source, or scrapes anything.

Recommended flow:

1. **Check price source health.** `GET /admin/price-source-health` (optional `source`/`set_code`/
   `rarity`/`variant`/`language` filters, `include_inactive_mappings=true` to include inactive
   mappings) returns a `summary`, a per-`sources` breakdown (`health_status` one of `healthy`,
   `degraded`, `stale`, `blocked`, `error`, `unknown`), `coverage_by_set`/`coverage_by_rarity`, the
   `stale_prices`/`missing_prices` gap lists, recent `refresh_runs`, and `warnings`. Freshness
   thresholds match "Catalog coverage workflow" above: Yuyu-Tei within 24 hours, SNKRDUNK within 7
   days. Drill into `failed_refresh`/`blocked`/`low_coverage` gaps (not in the top-level report) via
   `GET /admin/price-source-health/gaps?gap_type=<stale|missing|failed_refresh|blocked|
   low_coverage>` (also takes `source`/`set_code`/`rarity`/`limit`/`offset`). The
   `/admin/price-source-health` page in the web UI covers both, and is linked from the admin nav,
   `/admin/catalog-coverage`, `/admin/source-mapping-quality`, `/admin/refresh-runs`,
   `/admin/card-audit`, and `/admin/system-check`.
2. **Review stale/missing prices** - a mapping with a price older than its source's freshness
   window is `stale`; one with no price observation at all is `missing`. Both point at
   `run_refresh_or_review_mapping`: usually just needs a normal refresh (below), but a mapping that
   stays missing/stale across several refreshes is worth checking for a broken `source_url`/
   `source_card_id` via `GET /admin/source-mappings/quality`.
3. **Run a normal refresh** - `POST /admin/actions/refresh-prices` (see `/admin/actions` in the web
   UI, or "Run Yuyu-Tei refresh manually" above) - the existing Celery-backed trigger. This
   workflow only ever reads `price_refresh_runs`/`snkrdunk_discovery_runs` status; it never adds a
   new way to trigger or retry a refresh beyond what already exists.
4. **Review source mapping quality** for any source reported `error` (latest refresh failed) via
   `GET /admin/source-mappings/quality` and "Check refresh runs" below (find the failed run, read
   `error_message`).
5. **Use the manual SNKRDUNK candidate import** ("Import SNKRDUNK candidates CSV" above) whenever a
   source reports `health_status: "blocked"` - that means `snkrdunk_discovery_runs.status ==
   "blocked"` (the site blocked automated discovery). Never bypass site protections to force
   discovery through anyway; the manual CSV import + "Review SNKRDUNK candidate matches" workflow
   above is the supported fallback and does not scrape SNKRDUNK.
6. **Rerun `GET /admin/card-audit` and `GET /admin/system-check`** afterward - both surface a
   price-source-health summary (via `app.services.price_source_health.summarize_price_source_health`)
   without repeating every stale/missing mapping the health page already lists individually;
   `system-check` warns on any blocked/error source, a recent refresh success rate below 80%, more
   than 20% of mappings without a recent price, more than 20% stale, or no successful refresh ever
   recorded.

CLI equivalent (prints a summary; add `--json` for the full report, `--output PATH` to also write
it to a file):

```
docker compose exec api python -m app.price_source_health_report --source yuyutei
```

The report is cached under the `admin/price_source_health` prefix (see "Cache operations" below,
`CACHE_PRICE_SOURCE_HEALTH_TTL_SECONDS`, default 60s - shorter than catalog coverage's, since
freshness is the whole point here) and is invalidated by any write that changes cards or source
mappings.

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

## Analytics digest

**What it summarizes.** One combined, deterministic snapshot of everything the analytics pages
already compute - collection analytics, wishlist analytics, buy decision support, sell decision
support, grading ROI, and portfolio risk - in a single response/report, plus a handful of
plain-template `deterministic_summary_lines` (e.g. "3 wishlist targets are at or below target
price."). See `services/api/app/services/analytics_digest.py` - it only reads and re-shapes what
those six services already computed for the interactive `/analytics/*` pages; it never recomputes
a valuation, a score, or a risk figure, and there is no AI/LLM involvement anywhere in it.

`GET /analytics/digest` (signed-in, user-scoped, `?valuation_mode=raw_market|graded_adjusted`) is
the live, always-fresh version - same request/response shape as every other `/analytics/*`
endpoint, cached under the `analytics_digest` prefix. `POST /admin/actions/generate-analytics-
digest` (and the CLI/worker paths below) additionally *persist* a row to `analytics_digest_reports`
so a digest's numbers can be compared over time - browsable at `/analytics/digest` (history table)
or via `GET /analytics/digest/reports` / `GET /analytics/digest/reports/{id}` / `GET
/analytics/digest/latest`. The persisted path is not user-scoped (it resolves the single collector
account, lowest user id - this app is not yet multi-tenant in practice, same simplification
`app.services.portfolio_valuation`'s own admin-only aggregate callers already make).

**How to generate from the CLI:**

```
docker compose exec api python -m app.generate_analytics_digest --valuation-mode raw_market
```

Prints `report_id`, `valuation_mode`, `risk_score`, `buy_review_count`, `sell_review_count`.
Acquires the `analytics_digest_generation` concurrency lock (see 'Worker job concurrency locking'
below); `--skip-lock` is test/dev only.

**How to generate from the admin UI.** The "Generate analytics digest" card on `/admin/actions`
(pick a valuation mode, click the button), or directly:

```
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"valuation_mode": "raw_market"}' \
  "http://localhost:8000/admin/actions/generate-analytics-digest"
```

A digest is also generated automatically, best-effort, after a successful non-dry-run run of
`POST /admin/actions/run-market-workflow` or `POST /admin/actions/full-market-refresh` (never for
a `dry_run` request) - a digest generation failure there is logged as a warning and never fails or
rolls back the workflow that already succeeded. This runs in the API process, not inside the
worker's own scheduled Celery Beat `run_market_workflow` job - that job has no access to the six
API-only analytics services the digest composes (see `worker/models.py`'s "no shared code with the
api service" convention), so a digest is not currently generated for a workflow run that Beat
triggers directly without going through the admin API. Run the CLI on a schedule of your own (e.g.
a host cron hitting the container) if you want a fully automatic, always-current digest history
independent of admin-triggered runs.

**How it differs from the market intelligence report.** The market report (`GET
/market/report/latest`, `services/api/app/services/market_report.py`) is about *market
opportunities* - ranked buy/sell/momentum/drop signals derived from price observations, plus a
portfolio value snapshot. The analytics digest is about *your collection's decision-support and
risk posture* - wishlist targets, buy/sell recommendations, grading ROI, and portfolio
concentration/data-quality/liquidity/grading-exposure risk. They read overlapping underlying data
but answer different questions and are generated/stored independently of each other.

## Saved views workflow

**What it does.** Single-user saved filter/sort/column presets for the dense analytics/admin/
collector list pages (e.g. "Review Buy" on `/analytics/buy-decisions`, "Critical Mapping Issues" on
`/admin/source-mapping-quality`) - backed by `app.services.saved_views` / the `saved_views` table.
Read/write, but never destructive: creating, updating, or deleting a saved view only ever touches
that one row, never the data the filters describe. There is no per-account scoping (no `user_id`
column, matching `dashboard_preferences`) - this is one shared, global preset store, since the app
has no multi-user accounts. Every endpoint is gated by the existing signed-in-session check
(`require_current_user`, the same bearer token `/dashboard`, `/collection`, `/wishlist`, and
`/grading` already require) purely as a sign-in gate, not a new permission tier - no `X-Admin-Token`
is ever required for `/saved-views/*`, even from an admin page.

**Recommended flow:**

1. **Save the current filter combination.** On any page with a `SavedViewBar` (see
   `docs/interface_design_system.md`, "Saved views," for the full page list), click "Save current
   view," name it, optionally pin it and/or mark it default, then Save -
   `POST /saved-views` with `filters_json` built from that page's own filter state.
2. **Reapply a saved view.** Pick it from the same bar's dropdown - this calls
   `POST /saved-views/{id}/use` (bumps `usage_count`/`last_used_at`) and applies its `filters_json`
   back onto the page's local filter state (no page in this app reads filters from the URL, so
   applying a view always means updating local state, never a query-string rewrite).
3. **Mark/clear a default.** "Set default" (`POST /saved-views/{id}/set-default`) unsets any other
   default sharing that page's `route_path`+`view_type` first - only one default per page. "Clear
   default" (`POST /saved-views/clear-default`, body `{route_path, view_type}`) unsets it without
   picking a replacement.
4. **Pin a view for the dashboard/catalog-ops shortcut sections.** Toggle "pinned" from
   "Manage views" (`PATCH /saved-views/{id}`) - pinned views across every scope then show up in
   `PinnedViewsSection` on `/dashboard` and (admin-scoped ones) `/admin/catalog-ops`.
5. **Seed the default presets** (Review Buy, Critical Mapping Issues, Stale Prices, ...) on a fresh
   or freshly-migrated database:
   ```
   docker compose exec api python -m app.seed_saved_views
   ```
   Idempotent by `(route_path, view_type, name)` - safe to run repeatedly (e.g. on every deploy);
   re-running against an already-seeded database inserts nothing.

**Avoid saving sensitive data.** `filters_json`/`sort_json`/`columns_json` are validated to be a
plain object (or `null`) and are rejected if any key name resembles a token/password/secret/
confirmation field - the primary defense is simply that no page's filter-serialization code
includes an admin token, an uploaded file, raw CSV contents, or confirm-modal state (e.g.
card-duplicates' "type MERGE to confirm" text) in the first place, since those are already separate
pieces of component state from a page's list filters; the backend check is a safety net, not the
main guarantee.

## Workflow shortcuts

**What it does.** A global `Cmd/Ctrl+K` command palette, a per-page
`QuickActionBar` of contextual shortcut pills, a `?` keyboard-shortcuts
reference modal, and a "Workflow Shortcuts" section on `/dashboard` - pure
frontend navigation convenience layered on top of the existing sidebar, no
new backend routes or tables. See `docs/interface_design_system.md`,
"Command palette and workflow shortcuts," for the full component/behavior
reference.

**Recommended flow:**

1. **Open the palette.** `Cmd/Ctrl+K` from anywhere (also `/` when nothing
   else is focused). Type to filter static commands (pages), saved views,
   and - once you've typed 2+ characters - matching cards. Recently used
   commands show first when the query is empty.
2. **Navigate.** `↑`/`↓` to move, `Enter` to go. Selecting a saved view or
   a card jumps straight to its page - same URL-params limitation saved
   views already have (see "Saved views workflow" above): the destination
   page's own filter bar still needs to be used to reapply a saved view's
   filters, a palette click can't pre-apply them.
3. **Admin/dry-run actions never execute from the palette.** Every admin
   command is navigation-only - it takes you to the admin page where the
   real dry-run/preview/confirm button already lives (e.g.
   `/admin/source-mapping-quality`, `/admin/card-duplicates`). The actual
   one-click dry-run/preview triggers live in that page's own
   `QuickActionBar` instead, wired directly to the page's existing handler
   function - no new write path is introduced anywhere in this feature.
4. **`g` then a key** jumps directly to a handful of high-traffic pages
   without opening the palette at all (`g d` dashboard, `g c` collection,
   `g v` vault, `g w` wishlist, `g b` buy decisions, `g s` sell decisions,
   `g r` portfolio risk, `g a` admin catalog ops) - press `?` for the full
   list any time.
5. **Recent-workflow tracking is `localStorage`-only**, not a new backend
   table or endpoint - it's per-browser, ephemeral, low-stakes UX
   convenience (which page/saved-view/card you opened most recently), not
   data that needs to survive a device change or appear in a backup/
   restore. It never stores an admin token, file contents, or confirm-
   modal text. If you clear browser storage, the "Recent" list in the
   palette and the recent-items row on the dashboard's "Workflow
   Shortcuts" section both just go back to empty - nothing else is
   affected.

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

**Phase 9 (catalog operations) coverage.** `pg_dump`/`pg_restore` above operate on the whole
database, so every catalog-operations table/field is captured automatically with no special
casing needed. The selective JSON backup (`GET /admin/backup/export`, `POST
/admin/backup/restore`, backed by `app.services.backup.MODEL_BY_TABLE`/`REQUIRED_TABLES` - see
"Large import/export jobs" below) also covers it explicitly: `cards` (a required table) includes
the expanded metadata fields and the card-merge fields (`merged_into_card_id`, `merged_at`,
`merge_notes`); `card_aliases` is a required table; `import_validation_reports` is an optional
table, included by passing `include_validation_reports=true` to `GET /admin/backup/export` - same
opt-in convention as prices/raw snapshots/refresh runs/logs (`/admin/backup`'s UI and
`app.export_backup`'s CLI currently only expose checkboxes/flags for that older set; call the
query param directly to include validation reports), since validation reports are diagnostic
history rather than data a restore strictly needs.
`GET /admin/system-check`'s `backup_tables_included` check fails if any table required for backup
coverage is ever missing from `MODEL_BY_TABLE`.

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

## Cache operations

Several expensive read endpoints (dashboard, portfolio valuation, market opportunities/signals/
reports, wishlist/grading summaries, search suggestions) are cached for a short TTL via
`app.services.cache` (`services/api/app/services/cache.py`) - Redis-backed by default, with an
in-memory fallback for local development only. This trades a small amount of staleness for
materially faster responses on pages that would otherwise recompute the same aggregate query on
every load.

**What is cached** (see the route handlers for exact cache keys):

| Endpoint | TTL setting |
| --- | --- |
| `GET /dashboard/overview` | `CACHE_DASHBOARD_TTL_SECONDS` |
| `GET /collection/valuation` (key includes `valuation_mode`) | `CACHE_COLLECTION_TTL_SECONDS` |
| `GET /collection/valuation/history` (key includes `days`/`limit`) | `CACHE_COLLECTION_TTL_SECONDS` |
| `GET /analytics/collection` (key includes `valuation_mode`/`include_sold`) | `CACHE_COLLECTION_TTL_SECONDS` |
| `GET /analytics/portfolio-risk` (key includes `valuation_mode`/`include_sold`) | `CACHE_COLLECTION_TTL_SECONDS` |
| `GET /analytics/digest` (key includes `valuation_mode`) | `CACHE_COLLECTION_TTL_SECONDS` |
| `GET /analytics/digest/latest` / `/reports` (key includes `valuation_mode`/`limit`/`offset`) | `CACHE_COLLECTION_TTL_SECONDS` |
| `GET /market/opportunities` (key includes filters/`limit`/`offset`) | `CACHE_MARKET_TTL_SECONDS` |
| `GET /market/signals` (key includes filters/`limit`/`offset`) | `CACHE_MARKET_TTL_SECONDS` |
| `GET /market/signal-events` (key includes filters/`limit`/`offset`) | `CACHE_MARKET_TTL_SECONDS` |
| `GET /market/report/latest` | `CACHE_MARKET_TTL_SECONDS` |
| `GET /market/reports` (key includes `limit`/`offset`) | `CACHE_MARKET_TTL_SECONDS` |
| `GET /wishlist/summary` | `CACHE_COLLECTION_TTL_SECONDS` |
| `GET /grading/summary` | `CACHE_COLLECTION_TTL_SECONDS` |
| `GET /search/suggestions` (key includes `q`/`limit`) | fixed 60s |

Every cached response carries `X-Cache: HIT` or `MISS`, and `X-Cache-TTL` (the TTL in seconds
used for that entry); `X-Cache-Key` is added too, but only in a development environment - it's
not something a production client should depend on.

**Why `GET /search` is not cached by default.** Unlike `/search/suggestions`, the full search
endpoint records `search_history` as a side effect of every call (see `app.services.search`).
Caching it would mean a repeated identical query silently stops being recorded, which would make
`/search/suggestions`' own "recently searched" suggestions quietly go stale - the side effect
matters more here than the read-speed win, so this endpoint is left out of the cached set on
purpose.

**Default TTLs and env vars** (`services/api/app/settings.py`):

- `CACHE_ENABLED` (default `true`) - the master switch; `false` disables caching outright, and
  every cached endpoint just computes its response fresh every time.
- `CACHE_BACKEND` (default `redis`) - one of `redis`, `memory`, `none`. `none` behaves like
  `CACHE_ENABLED=false`. `memory` uses a per-process, non-shared dict - fine for local
  development, but see the warning below about using it anywhere else.
- `CACHE_DEFAULT_TTL_SECONDS` (default `60`) - not directly read by any endpoint above (each has
  its own more specific setting), kept as a fallback default for future cached endpoints.
- `CACHE_DASHBOARD_TTL_SECONDS` (default `60`)
- `CACHE_MARKET_TTL_SECONDS` (default `120`)
- `CACHE_COLLECTION_TTL_SECONDS` (default `60`)

**Redis vs. memory backend.** `CACHE_BACKEND=redis` (the default) points at the same `REDIS_URL`
Celery already uses as its broker/result backend - every cache key is namespaced under
`occache:` so a cache clear (see below) can never delete Celery's own keys. If Redis is
unreachable, individual cache reads/writes fail closed (logged, then treated as an uncached
request) rather than crashing the request - **except** in a development environment
(`ENVIRONMENT`/`APP_ENV=development`), where the process instead falls back to the in-memory
backend for the rest of its lifetime, logging a `redis_unavailable_fallback` warning once. This
asymmetry is deliberate: an in-memory cache is per-process and not shared across
instances/workers, which is an acceptable trade in a single local dev process but a correctness
footgun in any real deployment (one instance's write would never invalidate another instance's
stale entry) - `GET /admin/system-check` warns if `CACHE_BACKEND=memory` outside of development.

**How to check cache status.**

```
curl -H "X-Admin-Token: $ADMIN_TOKEN" http://localhost:8000/admin/cache/status
```

Or the `/admin/cache` page (linked from the admin nav, `/admin/performance`, and
`/admin/actions`), which shows enabled/backend/hit-and-miss counts/key count and each TTL.
`GET /admin/performance/summary` also carries a `cache_enabled`/`cache_backend`/`cache_keys`
summary alongside its other counters.

**When and how to clear the cache.** Every write endpoint that changes cached data (collection,
wishlist, grading, market signal snapshot/report generation, price refresh, portfolio snapshot)
already invalidates the relevant cache prefixes itself - see the invalidation lists in each
service module's comments if you need the exact mapping. A manual clear is normally only needed
if you suspect a bug in that invalidation logic, or want to force every cached endpoint to
recompute immediately after a manual data fix:

```
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"prefix": "dashboard", "confirm": "CLEAR"}' \
  http://localhost:8000/admin/cache/clear

# omit "prefix" (or set it to null) to clear every cache key this app has written
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"confirm": "CLEAR"}' \
  http://localhost:8000/admin/cache/clear
```

`confirm` must be exactly `"CLEAR"` - same confirmation-phrase pattern as
`/admin/data-retention/prune` and `/admin/job-locks/{name}/force-release`. Useful prefixes:
`dashboard`, `collection_valuation`, `collection_history`, `collection_analytics`, `market_signals`,
`market_signal_events`, `market_opportunities`, `market_report` (and `market_reports`),
`wishlist`, `wishlist_summary`, `grading_summary`. Every cache clear (and every Redis
backend-failure/fallback event) is recorded to `app_log_events` - see `GET /admin/logs` - but
individual cache hits/misses are never logged, only the hit/miss counters shown on
`/admin/cache`.

## Large import/export jobs

Collection/wishlist CSV import, CSV export, and JSON backup export can all run as a tracked
background `file_jobs` row instead of inline in the request - see `app.models.file_job`,
`app.services.file_jobs`, `app.services.file_job_storage`, and `GET`/`POST /file-jobs*`
(`services/api/app/api/file_jobs.py`). This exists for the same reason as caching and
pagination: a large collection/wishlist/backup shouldn't have to block the request/response
cycle or risk a timeout.

**How processing actually runs.** Unlike price refresh/market workflow (which dispatch to a
Celery task in the separate `services/worker` deployable), file-job processing runs inside
*this* API process via FastAPI `BackgroundTasks` - `app.services.file_jobs.process_file_job()`,
called either synchronously (blocking the creating request) or deferred via `BackgroundTasks`
(202 returns immediately, the job finishes moments later), controlled by
`FILE_JOBS_SYNC_FALLBACK` (`app.env.file_jobs_sync_fallback_effective()`: unset defaults to
`true` in development, `false` otherwise). This was a deliberate choice, not an oversight: CSV
import/export and backup export/restore depend on this service's full model set (tags, groups,
grading submissions, per-user ownership) and its ~20-table backup registry
(`app.services.backup.MODEL_BY_TABLE`) - `services/worker` has a much smaller, separate model
set with no per-user auth concept, built for source-adapter/scraping-adjacent jobs against the
same database. Duplicating this service's CRUD/CSV/backup logic into that separate deployable
would mean maintaining two divergent copies of the same behavior for a feature with nothing to
do with scraping, so it wasn't done.

**When to use background mode.**

- `POST /collection/import.csv?background=true` / `POST /wishlist/import.csv?background=true` -
  same `dry_run`/`mode` semantics as the direct (`background=false`, the default) call; the
  response is `202 {"file_job_id": ..., "status": "queued"}` instead of the full import result.
  Poll `GET /file-jobs/{id}` for progress/summary/row errors.
- `POST /collection/export.csv/job`, `POST /wishlist/export.csv/job`,
  `POST /admin/backup/export/job` (admin-only) - generate the file in the background instead of
  in the response body; poll `GET /file-jobs/{id}` and download via
  `GET /file-jobs/{id}/download` once `status=success`.
- The direct, synchronous endpoints (`GET /collection/export.csv`, `GET /wishlist/export.csv`,
  `GET /admin/backup/export`) remain available and are what the frontend's plain "Export ...
  CSV"/"Download backup JSON" buttons still use - background mode is there for a collection/
  wishlist/backup large enough that generating or importing it inline risks a slow response or
  a request timeout. The direct CSV endpoints stream their body (`StreamingResponse` over
  `app.services.collection_csv.iter_collection_csv_rows` /
  `app.services.wishlist_csv.iter_wishlist_csv_rows`) rather than building the whole file in
  memory first, which is why they lose the `X-Response-Size-Bytes` header (see
  `app.core.response_size`'s own docstring) - a streamed response has no `Content-Length` to
  read that header's value off.

**Access control.** `GET/POST /file-jobs*` accepts *either* a signed-in user's bearer token
(scoped to that user's own `collection_import`/`wishlist_import`/`collection_export`/
`wishlist_export` jobs) *or* `X-Admin-Token` (full visibility across every job and owner,
including admin-only `backup_export` jobs) - see `app.auth.file_job_access`. A job owned by
another user 404s rather than 403s, same pattern as `/collection/{id}` for a different user's
item.

**Where files are stored.** `FILE_JOB_STORAGE_DIR` (default `data/file_jobs`, same convention as
`DB_BACKUP_DIR`) with `input/` and `output/` subdirectories - see
`app.services.file_job_storage`. Every on-disk filename is a freshly generated uuid (optionally
job-id-prefixed for output files); a caller's original filename is only ever kept for display
(`FileJob.original_filename`) and is never used to build a path.  `FILE_JOB_MAX_UPLOAD_MB`
(default `50`) caps upload size; allowed upload extensions are `.csv` and `.json` only. This
directory must never be committed - see `.gitignore`'s `data/file_jobs/*` rule and
`scripts/check_secrets.sh`'s check for it, mirroring `data/backups/`.

**Cleanup policy.** `file_jobs` rows in a terminal status (`success`, `failed`, `cancelled`)
older than `older_than_days` (default 7) are cleanup candidates - a queued or running job is
never touched, no matter its age. Unlike every other prunable table (`app.services.
data_retention`), this doesn't go through the generic `POST /admin/data-retention/prune` engine,
which only issues a bare `DELETE ... WHERE id IN (...)` - a file job's cleanup must *also*
delete its input/output files on disk, so it has its own dedicated endpoint instead:

```
curl -X POST -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"older_than_days": 7, "dry_run": false, "confirm": "CLEANUP"}' \
  http://localhost:8000/admin/file-jobs/cleanup
```

`dry_run` defaults to `true` (count only); `dry_run=false` requires `confirm="CLEANUP"`, same
confirmation-phrase pattern as `/admin/data-retention/prune` and `/admin/cache/clear`. `GET
/admin/data-retention/policy` still lists a `file_jobs` row for visibility, but it's
informational only - it points back at this endpoint rather than being prunable through
`/admin/data-retention/prune`. The `/admin/file-jobs` page (linked from the admin nav,
`/admin/backup`, and the collection/wishlist import/export sections) has this cleanup form
built in.

**Why old job files are pruned.** Every generated export/backup output and every uploaded
import file sits on local disk indefinitely otherwise - for a personal-scale app this is a slow
but real disk-growth leak, and (per "do not commit generated files") these must never end up in
git either, so periodic cleanup is the only thing bounding that directory's size.

**How to troubleshoot a failed file job.**

1. `GET /file-jobs/{id}` (or the `/admin/file-jobs` page) - `status=failed` jobs carry an
   `errors` field: a structural failure (e.g. a CSV missing a required column) shows a single
   `{"error": "..."}` entry; a completed-but-imperfect CSV import instead shows per-row errors
   (still `status=success`, since the import itself completed - see `errors_json` vs. job
   status in `app.services.file_jobs.complete_file_job`/`fail_file_job`).
2. `GET /admin/logs?event_type=file_job_failed` (or `file_job_created`/`file_job_started`/
   `file_job_success`/`file_job_cancelled`/`file_job_cleanup_completed`) - every lifecycle
   transition is recorded to `app_log_events`, same as job locks; individual progress updates
   are not.
3. `GET /admin/system-check` - warns if `FILE_JOB_STORAGE_DIR` isn't writable
   (`file_job_storage_writable`) or if any job has been `running` for over 2 hours
   (`stale_running_file_jobs`, likely a crashed/interrupted `BackgroundTasks` run rather than a
   job still genuinely working). `GET /admin/performance/summary` also carries
   `file_jobs_by_status` and `stale_running_file_jobs` counts.
4. A job stuck `running` past its expected duration can't be force-completed - cancel it
   (`POST /file-jobs/{id}/cancel`, or from the `/admin/file-jobs` page) and retry. Cancelling a
   `queued` job takes effect immediately; cancelling a `running` job only takes effect at that
   job's next cancellation checkpoint (collection/wishlist export jobs check between output
   chunks; CSV import and backup export are each one atomic, well-tested call into existing
   service code and are only checked once, before work begins - see the "if practical" note in
   `app.services.file_jobs`'s module docstring for why finer-grained cancellation wasn't added
   there).

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
| `price_observations` | 365 days | thinned to 1/day beyond 90 days; latest observation per series is never deleted regardless of age. A series is exact-print aware: `(card_print_id, source, price_type)` for print-linked rows, `(card_id, source, price_type)` for legacy rows where `card_print_id IS NULL`. Sibling prints that bridge through the same legacy `card_id` are therefore protected and thinned independently |
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
| `analytics_digest_generation` | 10 min | `app.services.analytics_digest.generate_analytics_digest` (CLI + admin action + best-effort after a market workflow run) |
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

## Performance and scale operations

Phase 7 added a set of admin pages/endpoints and scripts for checking and exercising this app's
performance and scale characteristics as data volume grows. See
[docs/performance_testing.md](performance_testing.md) for the full local workflow (seeding
synthetic data, running the load tests, cleaning up); this section is the operational reference
for what each piece shows.

| What | Where |
|---|---|
| Database index audit | `GET /admin/db-index-audit`, linked from `/admin/performance` |
| Performance summary (table row counts, slow requests, response size warnings, cache/job-lock/file-job status) | `GET /admin/performance/summary`, `/admin/performance` page |
| Data retention policy and pruning | `GET /admin/data-retention/policy`, `POST /admin/data-retention/prune`, `/admin/data-retention` page - see [Data retention and pruning](#data-retention-and-pruning) |
| Cache status and manual clear | `GET /admin/cache/status`, `POST /admin/cache/clear`, `/admin/cache` page - see [Cache operations](#cache-operations) |
| Worker job concurrency locks | `GET /admin/job-locks`, `POST /admin/job-locks/cleanup-expired`, `/admin/job-locks` page - see [Worker job concurrency locking](#worker-job-concurrency-locking) |
| Background file jobs (large import/export) | `GET /file-jobs`, `/admin/file-jobs` page - see [Large import/export jobs](#large-import-export-jobs) |
| Response size warnings | `X-Response-Size-Bytes` header on every response; a response over `RESPONSE_SIZE_WARNING_BYTES` also logs `event_type=response_size_warning` (see [Observability and logs](#observability-and-logs)) |
| Slow request logs | `X-Process-Time-Ms` header on every response; a request over `SLOW_REQUEST_MS` also logs `event_type=slow_request` |
| Load test scripts | `scripts/load_test_api.sh`, `scripts/load_test_web.sh` - curl-only, no external load testing tool required |

The five admin pages above (`/admin/performance`, `/admin/cache`, `/admin/job-locks`,
`/admin/data-retention`, `/admin/file-jobs`) all link to each other, plus `/admin/actions` and
`/admin/logs`, from the admin nav and from a "related pages" row on each page.

`scripts/phase7_audit.sh` runs the automated version of this checklist end-to-end (tests, all six
admin endpoints above, web route smoke test, and optionally the load tests) - see
[docs/performance_testing.md](performance_testing.md#automated-phase-7-audit).

## Phase 10 UX audit

Phase 10 was a mobile/tablet responsiveness and UX polish pass over the existing dense collector/
admin dashboard (responsive shell, responsive table system, filter/saved-view collapse, card vault/
detail responsiveness, modal responsiveness, empty/loading/error consistency, price/source display
audit, admin safety UI audit) - see [docs/interface_design_system.md](interface_design_system.md#phase-10--mobiletablet-responsiveness-and-ux-polish)
for the design rules it established. It adds no new pages/routes and no new product features.

### Running `scripts/phase10_ux_audit.sh`

```bash
make dev-up   # or: docker compose up -d
scripts/phase10_ux_audit.sh
```

Same fail-fast convention as `scripts/phase7_audit.sh`/`phase8_audit.sh`/`phase9_audit.sh` - stops
at the first failing step and prints `Phase 10 UX audit passed` at the end.

Env vars (all optional):

| Var | Default | Purpose |
|---|---|---|
| `SKIP_TESTS` | `false` | Set `true` to skip the `docker compose exec api pytest` / `docker compose run --rm worker pytest` steps |
| `ADMIN_TOKEN` | `local-dev-admin-token` | Sent as `X-Admin-Token` on the admin endpoint checks |
| `BASE_API_URL` | `http://127.0.0.1:8000` | Backend base URL |
| `BASE_WEB_URL` | `http://127.0.0.1:3000` | Frontend base URL |

What it checks:

1. `scripts/check_secrets.sh`
2. Backend/worker pytest suites (unless `SKIP_TESTS=true`)
3. HTTP 200 on every key web route touched by this phase (dashboard, collection, vault, wishlist,
   grading, the analytics pages, and the dense admin pages)
4. HTTP 200 on `/health`, `/saved-views`, `/analytics/digest`, `/analytics/buy-decisions`,
   `/analytics/sell-decisions` (public) and `/admin/catalog-coverage`, `/admin/price-source-health`,
   `/admin/source-mappings/quality` (admin-token-gated)
5. A Playwright viewport/overflow smoke test *if* Playwright (or an equivalent frontend test setup)
   already exists in `apps/web` - it doesn't as of this phase, so this step is a no-op that prints
   why it's skipped rather than adding a new test framework just for this check. If one is added
   later, wire it in here at 360×800 / 768×1024 / 1440×900 against `/dashboard`,
   `/collection/vault`, `/analytics/buy-decisions`, and `/admin/source-mapping-quality`, asserting
   `document.documentElement.scrollWidth <= window.innerWidth + <small tolerance>`.

### Manual QA checklist

Since there's no automated viewport/overflow test yet, mobile/tablet/desktop UX has to be checked
by hand after any layout/table/filter change. See
[docs/manual_qa_checklist.md](manual_qa_checklist.md) for the practical, page-by-page checklist
(desktop 1440px+, tablet 768px, mobile 360px, card detail, collection vault, analytics tables,
admin tables, modals, command palette, saved views, price basis labels, empty/loading/error states,
admin safety).

## Staging operations

Day-to-day commands for the Vercel (web) + Railway (api/worker/beat/Postgres/Redis) staging
deployment - see [docs/staging_deployment.md](staging_deployment.md) for the full architecture,
[docs/railway_staging.md](railway_staging.md) for per-service Railway setup, and
[docs/staging_checklist.md](staging_checklist.md) for the step-by-step deploy checklist. Everything
below targets the deployed staging URLs, not the local dev/prod Docker Compose stacks - swap in
your actual Railway `api` URL and Vercel staging URL wherever a placeholder appears.

**Read-only staging database access (validate before you trust any query)**:

```
python scripts/staging_db_read_check.py
```

Opens a fresh `railway connect Postgres --tunnel-only` SSH tunnel, connects read-only, and exits
non-zero unless five independent fingerprints prove the connection is the Atlas staging database:
required tables, Atlas-specific named indexes/constraints, print-lineage columns, the alembic head
this checkout expects, and non-empty invariants. Run it *before* any audit or data investigation,
and discard results from a connection it rejects.

**Why this is mandatory, and why `DATABASE_PUBLIC_URL` is not trusted on its own.** On 2026-08-21
the Postgres service's public TCP proxy was re-assigned (port 21415 -> 12258) and the CLI kept
injecting the stale `DATABASE_PUBLIC_URL` for a window. The old port still had a live Postgres on
it, so `railway run --service Postgres -- ... "$DATABASE_PUBLIC_URL"` **connected successfully**,
authenticated, and reported `current_database() = 'railway'` - indistinguishable from the real
thing - against an empty schema. An audit run that way reports "0 rows" for every table and looks
entirely plausible. Neither the endpoint nor the database name distinguishes the two databases;
only the schema does. The variable is a cache and can point anywhere, so validate the destination
rather than assuming it. Prefer the tunnel: `railway connect --tunnel-only` resolves through the
service itself over SSH and cannot land on a stale public proxy.

Two rules the checker encodes, worth remembering independently:

- **Zero rows is never proof of a valid database** - it is precisely what the wrong database
  returns. (`collection_items` is genuinely empty on staging, so it is deliberately excluded from
  the non-empty invariants; asserting it would fail against the real database.)
- **Counts printed by the checker are identity evidence, not an audit result.**

**Run migrations**:

```
DATABASE_URL=<railway-postgres-url> bash scripts/staging_migrate.sh
```

or, run inside the Railway `api` service directly (avoids needing `services/api`'s Python
dependencies installed locally):

```
railway run --service api alembic upgrade head
```

**Run the smoke test**:

```
STAGING_API_URL=<railway-api-url> STAGING_WEB_URL=<vercel-staging-url> \
ADMIN_TOKEN=<staging-admin-token> bash scripts/staging_smoke_test.sh
```

**Disable/enable workflow flags** - set on the Railway `beat` service, then redeploy/restart it for
the change to take effect (Celery beat only rebuilds its schedule at process start):

- `MARKET_WORKFLOW_ENABLED=false` (default for a first staging deploy) / `true` (once
  `api`/`worker`/`beat` are confirmed stable).
- `DATA_RETENTION_ENABLED=false` (default for a first staging deploy) / `true`.
- `SCRAPING_MODE=mock` (default, safe) / `live` (real Yuyu-Tei requests - only after everything
  else is verified; see [Safety notes](staging_deployment.md#11-safety-notes) in
  docs/staging_deployment.md). Never `live` for SNKRDUNK - that source stays manual-import-only.

**Check logs**:

- Railway: `railway logs --service api` (swap in `worker`/`beat`), or the Railway dashboard's Logs
  tab for each service.
- Vercel: the Vercel dashboard's Deployments -> a specific deployment's Build Logs (build-time
  errors) and Functions/Runtime Logs (request-time errors from `src/app/api/**` route handlers).

**Backup before real data imports** - `scripts/db_backup.sh`/`scripts/db_restore.sh` shell into a
*local* `postgres` Docker Compose container (`docker compose exec`), so they don't work as-is
against Railway's remote managed Postgres. For staging, either:

- run `pg_dump`/`pg_restore` directly against the Railway Postgres connection string from a machine
  with the Postgres client tools installed (`pg_dump "$DATABASE_URL" -Fc -f staging_backup.dump`),
  or
- use Railway's own Postgres plugin backup/restore feature if available on your plan (check the
  plugin's dashboard tab), or
- run `pg_dump` from inside the Railway `api` service's shell (`railway run --service api
  pg_dump ...`, if the `api` image has `pg_dump` available - it's a Python slim image and may not;
  installing a Postgres client isn't part of this staging pass).

Take a backup before importing a real/large card catalog or watchlist CSV into staging, same as you
would before a production import.

## Codespaces disk hygiene

The Codespace's `/` and `/workspaces` share one **32 GB** device; `/tmp` is a
separate 44 GB device. Validation work - Docker builds, throwaway Postgres
containers, downloaded marketplace images - fills the 32 GB device, and a full
disk fails in ways that look like something else: a Playwright collector run
whose disk ran out reports `watchdog_triggered:browser_launch` on every
mapping, which reads as a source problem and is really no free space.

Treat the Codespace as a scratch environment, never as backup storage.

**Before a large Docker build**
- Record `df -h /` first. Do not start one below **15 GB free**; the
  Playwright collector image alone is ~3.8 GB on top of a ~2 GB base.
- `docker builder prune -f` reclaims build cache only - always regenerable,
  and usually the largest safe win.

**After any task that created them**
- Remove throwaway containers and the images built only for that validation.
- Stop and remove throwaway Postgres containers *and* the anonymous volumes
  they leave behind (`docker run postgres` without `-v` creates one each
  time; 34 had accumulated by 2026-08-31, ~4.3 GB).
- **Never** blanket `docker volume prune`. It removes *named* volumes too, and
  `optcg-price-tracker_postgres_data`, `optcg-prod_opcg_postgres_data_prod`
  and `optcg-prod_opcg_redis_data_prod` are the local dev/prod compose
  databases. Remove anonymous (64-hex-named) volumes explicitly instead.
- **"Dangling" does not mean disposable, and this is the trap that actually
  fired.** On 2026-08-31 a cleanup step ran
  `docker volume ls -qf dangling=true` and removed everything it returned,
  destroying all three named volumes above. Docker calls a volume dangling
  when no *container* currently references it - and a compose database whose
  stack is merely stopped, the normal state in a Codespace, is dangling by
  that definition. The word describes attachment, not value. Never delete a
  volume because Docker labelled it dangling, and never use `dangling=true`,
  `docker volume prune` or `docker system prune --volumes` to *find* things to
  delete. Disposability is asserted by name, never inferred.
- **Use the helper**: `scripts/codespaces_cleanup.sh` plans by default and
  deletes only what you name explicitly:

  ```
  scripts/codespaces_cleanup.sh                                   # plan only
  scripts/codespaces_cleanup.sh --containers opcg-pg --images foo:bar \
      --build-cache --apply
  scripts/codespaces_cleanup.sh --volumes <exact-name> --apply \
      --confirm-volumes "delete these volumes"
  ```

  It never discovers volumes on its own, and refuses the three protected names
  even when they are passed explicitly. `scripts/tests/test_codespaces_cleanup.sh`
  pins that behaviour.
- Removing task-created containers, images and build cache individually (or
  through the helper) is always correct; only volumes need the extra
  confirmation, because a volume is the one resource here holding data the
  repo cannot rebuild.

**What not to accumulate**
- Do not keep marketplace/listing images downloaded during analysis unless
  they are an intentional project asset.
- Do not write large reports, PDFs or PNGs into the repo unless asked. Prefer
  a small JSON or text summary over an image-heavy evidence pack.
- Put temporary files under `/tmp` (separate, larger device) and delete them
  when the task ends.
- Staging dumps belong in `/home/codespace/backups` only for as long as the
  task needs them; staging itself is the source of truth.

**Two large directories that are NOT junk**
- `data/official_snapshots/` (~1 GB, gitignored) is the frozen Bandai
  catalogue. 951 MB of it is `bandai_jp/current/images`; the catalogue *facts*
  (`entries.jsonl`, `assets.jsonl`, `series.jsonl`, `manifest.json`,
  `analysis/`) are only ~25 MB. Every test that reads it skips cleanly when it
  is absent, and it is re-collectable via
  `python -m app.collect_official_cardlist_snapshot` - but re-collecting means
  re-fetching thousands of Bandai pages and images, so delete it only
  deliberately. Dropping just `bandai_jp/current/images` frees ~951 MB and
  keeps every alias/membership re-derivation test working.
- `docs/ui/evidence/` (~147 MB, mostly untracked) is ATLAS-loop before/after
  screenshots. They are *not* reproducible - they record how a past
  deployment looked - so archive them outside the Codespace rather than
  regenerating them.
