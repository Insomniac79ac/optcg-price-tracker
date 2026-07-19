# Performance testing (Phase 7)

Phase 7 hardened the app for scale without adding product features: database index audit and
query optimization, data retention/pruning, frontend route performance cleanup, API pagination and
response size limits, worker job concurrency locks, read-endpoint caching, background file jobs
for large imports/exports, and this doc's load test / synthetic seed tooling to verify all of the
above actually hold up together before moving on to the next phase.

This doc covers the local workflow: seed realistic-volume synthetic data, load test the API and
web app against it, check the admin pages that report on what happened, and clean up afterward.
See ["Performance and scale operations"](operations.md#performance-and-scale-operations) in
`docs/operations.md` for the operational reference (what each admin page/endpoint shows) and
`scripts/phase7_audit.sh` for the automated version of this checklist.

## What Phase 7 optimized

| Area | Where |
|---|---|
| Database index audit | `GET /admin/db-index-audit`, `/admin/performance` page |
| Query optimization | `app.services.latest_prices`, `app.services.market`, indexes in `app/models/*.py` |
| Data retention / pruning | `app.services.data_retention`, `GET/POST /admin/data-retention/*`, `/admin/data-retention` page |
| Frontend route performance | `apps/web/src/app/**` (route-level code splitting, avoided over-fetching) |
| API pagination and response size limits | `app.core.pagination`, `app.core.response_size` |
| Worker job concurrency locks | `app.services.job_locks`, `GET/POST /admin/job-locks*` |
| Caching | `app.services.cache`, `GET/POST /admin/cache/*`, `/admin/cache` page |
| Background file jobs (large import/export) | `app.services.file_jobs`, `GET /file-jobs*`, `/admin/file-jobs` page |

None of the tooling below changes valuation, market signal, or opportunity scoring formulas, adds
product features, adds user accounts, or adds scraping logic - it only exercises what already
exists under more load and more data.

## Seed synthetic test data locally

`python -m app.seed_performance_data` creates deterministic, clearly-fake data so pagination,
caching, search, and the dashboard have enough volume to be worth load testing. Every row it
creates is namespaced so it can never be confused with real data:

- Cards use `card_code` `TEST-PERF-0001`, `TEST-PERF-0002`, ... (`set_code` `TEST-PERF`) - real
  card codes always look like `OP01-001` and never start with `TEST-PERF-`.
- Prices attach to a dedicated `test-perf-source` `Source` row - the real `yuyutei`/`snkrdunk`
  sources (`app.seed`) are never touched.
- Collection/wishlist rows belong to a dedicated test user (`google_sub=test-perf-seed-user`) - no
  real account is touched.
- Activity and log events are tagged `event_type=test_perf_seed`.

It's idempotent - re-running only tops up whatever's short of the requested counts, never
duplicates or overwrites existing rows.

```
# Always look before you leap:
docker compose exec api python -m app.seed_performance_data --dry-run

# Default volumes (100 cards, 20 price observations/card, 20 collection items,
# 20 wishlist items, 50 activity events, 50 log events):
docker compose exec api python -m app.seed_performance_data

# Bigger dataset, to stress pagination/cache/search harder:
docker compose exec api python -m app.seed_performance_data \
  --cards 1000 --price-observations-per-card 50 --collection-items 200 \
  --wishlist-items 200 --activity-events 500 --log-events 500
```

**Never run this in production unless you're intentionally testing production**, and even then it
refuses by default: if `APP_ENV`/`ENVIRONMENT` is `production`, it exits non-zero unless you also
pass `--allow-production-test-data`. Even with that flag, seeded data is still confined to the
`TEST-PERF-`/`test-perf-*` namespace above - it never touches real rows.

## Run the API load test

`scripts/load_test_api.sh` fires a small burst of concurrent `curl` requests (no k6/hey/ab/wrk
dependency) at the important read endpoints and reports success/failure counts and an average
duration per endpoint:

```
BASE_API_URL=http://127.0.0.1:8000 REQUESTS=20 CONCURRENCY=5 bash scripts/load_test_api.sh

# also load-test /admin/* endpoints:
ADMIN_TOKEN=local-dev-admin-token bash scripts/load_test_api.sh
```

A request "succeeds" if the server returned anything other than a connection failure or a 5xx -
this checks stability under a bit of concurrency, not authorization; a login-gated endpoint (e.g.
`/collection/valuation` with no bearer token) returning 401 quickly still counts as a pass. Exits
non-zero if any endpoint saw a connection failure or 5xx.

## Run the web load test

`scripts/load_test_web.sh` does the same thing against the important pages, printing PASS/FAIL per
route:

```
WEB_BASE_URL=http://127.0.0.1:3000 REQUESTS=10 CONCURRENCY=3 bash scripts/load_test_web.sh
```

A route passes if every request in the burst returned HTTP 200 (following redirects, same as
`scripts/web_route_smoke.sh` - a signed-out visit to e.g. `/dashboard` redirects to
`/market/movers`, which still counts as reachable/passing).

## Check cache hits

`GET /admin/cache/status` (or the `/admin/cache` page) shows the active backend, key count, and
configured TTLs. Every cached response also carries `X-Cache: HIT` / `X-Cache: MISS` and
`X-Cache-Key` response headers - `curl -sI` a cached endpoint (e.g. `/dashboard/overview`,
`/market/opportunities`) twice in a row and confirm the second call comes back `X-Cache: HIT`. See
["Cache operations"](operations.md#cache-operations) for the full reference, including how to
clear specific prefixes.

## Check slow request logs

Any request slower than `SLOW_REQUEST_MS` (default 1000ms) gets a warning `app_log_events` row
(`event_type=slow_request`), and any response larger than `RESPONSE_SIZE_WARNING_BYTES` (default
1MB) gets one too (`event_type=response_size_warning`). Both roll up on `GET
/admin/performance/summary` (`/admin/performance` page, "Slow requests" / "Largest recent
responses"), or query them directly:

```
curl -H "X-Admin-Token: $ADMIN_TOKEN" \
  "http://localhost:8000/admin/logs?event_type=slow_request&limit=20"
```

## Run a data retention dry-run

Every prune defaults to a dry run - see ["Data retention and
pruning"](operations.md#data-retention-and-pruning) for the full table-by-table policy:

```
docker compose exec api python -m app.prune_data_retention
```

This is safe to run against a load-tested/seeded database at any time - it only ever deletes rows
older than each table's retention window, and only with `--apply --confirm PRUNE`.

## Clean up test data

`python -m app.cleanup_performance_data` deletes exactly what `app.seed_performance_data` created
(the `TEST-PERF-`-prefixed cards and everything that references them, the dedicated test
source/user, and the `test_perf_seed`-tagged activity/log events) and nothing else. It requires an
explicit confirm flag and refuses to run without it:

```
docker compose exec api python -m app.cleanup_performance_data --confirm DELETE_TEST_PERF_DATA
```

Run this after you're done load testing locally - synthetic data left lying around will skew real
dashboard/collection views in a shared dev database.

## Automated Phase 7 audit

`scripts/phase7_audit.sh` runs the backend/worker test suites, checks the Phase 7 admin endpoints
respond, runs the web route smoke test, and (with `RUN_LOAD_TESTS=true`) both load test scripts -
see that script's header comment for the full list and env vars. It's also wired into
`scripts/final_audit.sh` behind `RUN_PHASE7_AUDIT=true`.

```
bash scripts/phase7_audit.sh
RUN_LOAD_TESTS=true bash scripts/phase7_audit.sh
```

**Warning:** do not run `app.seed_performance_data` against production data unless you are
intentionally load-testing production and have already confirmed with whoever owns that
environment - always dry-run first, and always clean up with
`app.cleanup_performance_data --confirm DELETE_TEST_PERF_DATA` afterward.
