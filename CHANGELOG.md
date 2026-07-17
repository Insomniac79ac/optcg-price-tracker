# Changelog

All notable changes to the OPTCG price tracker are documented in this file. See
`docs/release_checklist.md` for the release process and `GET /version` / `GET /admin/release-status`
for a running deployment's build metadata.

## 0.1.0 - 2026-07-17

Initial tracked release - the application as it exists going into formal release versioning.

### Added

- **Price tracking**: Yuyu-Tei and SNKRDUNK price observations, scheduled and on-demand refresh
  runs, price history per card, and market movers.
- **Collection tracker**: per-user card collection with quantity, condition, purchase price/date/
  source, target sell price, status (hold/watch/sell/sold/grading), tags, and groups; CSV import/
  export.
- **Portfolio valuation**: retail/liquidation/market-floor valuation per item and portfolio-wide,
  graded-adjusted valuation mode, valuation history snapshots, and best/worst performer insights.
- **Market intelligence**: deterministic market signals (price moves, buy/sell spreads, floor-vs-
  retail gaps), persistent signal events with a review workflow (watch/dismiss/resolve),
  opportunity scoring, and generated market intelligence reports with a Telegram digest.
- **Wishlist**: target-price tracking with CSV import/export and conversion to collection items.
- **Grading tracker**: submission tracking (PSA/BGS/CGC/ARS/other) through the grading lifecycle,
  fees, and graded value feeding back into portfolio valuation.
- **Backup/restore**: full JSON export/import with merge or replace modes, internal-consistency
  validation, and automated gzipped Postgres backups with retention pruning.
- **Admin workflows**: manual/scheduled market workflow runs (refresh -> snapshot -> report ->
  digest), a system-check consistency sweep, structured app logs with search/prune, an
  observability summary, rate-limit status, and env/config validation endpoints and pages.
- **App/build versioning**: `VERSION` file, `GET /version`/`GET /api/version`, `GET
  /admin/release-status` and its `/admin/release-status` page, and Docker build args
  (`GIT_COMMIT`/`BUILD_TIME`/`APP_VERSION`) baked into every image.
- **Release process**: `docs/release_checklist.md` and `scripts/release_check.sh`
  (`make release-check`) for a repeatable pre-release/build/deploy/rollback checklist.

### Changed

- N/A (initial tracked release).

### Fixed

- N/A (initial tracked release).

### Security

- Admin routes (`/admin/*`, `/snkrdunk/*`) gated by a shared `X-Admin-Token`, with a hard startup
  failure in production if unset/weak/default.
- Per-user routes (`/collection`, `/grading`, `/collector`) gated by a short-lived bearer JWT minted
  on Google sign-in.
- Fixed security response headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
  `Permissions-Policy`, a restrictive `Content-Security-Policy`) on every API response.
- In-memory per-IP rate limiting across five route groups (public read, collection writes, admin,
  import/export, search).
- `app_log_events.context_json` secret redaction (token/secret/password/key/authorization/cookie
  substrings), so a careless log call can't leak a credential.
- Production-only startup validation for `ADMIN_TOKEN` strength/default, `DATABASE_URL`'s default
  password, `SCRAPING_MODE`, market workflow schedule vars, and Telegram config completeness.

### Operations

- `docker-compose.prod.yml` / `docker-compose.prod.private.yml` with per-service healthchecks,
  reverse proxy examples (Nginx/Caddy) and setup docs for HTTPS deployment.
- `Makefile` `prod-*` targets covering build/up/down/logs/migrate/smoke/backup/restore.
- `scripts/prod_smoke_test.sh`, `scripts/prod_verify.sh`, `scripts/check_secrets.sh`, and the
  database backup/restore/prune scripts.
- `docs/deployment.md` and `docs/operations.md` covering environment variables, secret handling,
  migrations, health checks, and day-to-day operational commands.
