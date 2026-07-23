# Changelog

All notable changes to the OPTCG price tracker are documented in this file. See
`docs/release_checklist.md` for the release process and `GET /version` / `GET /admin/release-status`
for a running deployment's build metadata.

## 1.0.0 - 2026-07-23

First stable release. Everything below `0.1.0` plus the Phase 11 release-candidate audit and bug
bash: no new product features, no formula changes, no scraping behavior changes relative to
`1.0.0-rc.1`. See `docs/release_candidate_report.md`, `docs/release_blockers.md`, and
`docs/releases/v1.0.0.md` for the full readiness writeup and release notes.

### Added

- `docs/releases/v1.0.0.md`: the first-tag release notes (major capabilities, admin/data safety
  notes, known limitations, upgrade/deployment notes, post-release monitoring checklist).
- A final v1.0 tagging checklist in `docs/release_checklist.md` (section G) covering the exact
  pre-tag command sequence and the manual `git tag`/`git push` steps.

### Changed

- `VERSION` bumped from `1.0.0-rc.1` to `1.0.0`.
- `docs/release_candidate_report.md` and `docs/release_blockers.md` updated to reflect the
  completed bug-bash pass: all blocker/high rows fixed or resolved, working tree confirmed clean,
  full test/audit re-run recorded.
- `scripts/release_candidate_audit.sh` banner text now reads "target: v1.0.0" (was
  "v1.0.0-rc.1") - cosmetic only, no check logic changed.

### Fixed

- N/A beyond what's already recorded as fixed in the `1.0.0-rc.1` entry below and
  `docs/release_blockers.md` (RC-1 through RC-9, all fixed; RC-7 deferred as cosmetic-only).

### Security

- No changes since `1.0.0-rc.1` - re-verified by this pass's `scripts/check_secrets.sh` run and the
  existing admin-token/JWT/rate-limit/header protections.

### Operations

- Re-ran the full verification suite (backend/worker/frontend tests, frontend build, Alembic
  migrations, `scripts/release_candidate_audit.sh`, `scripts/final_audit.sh`) against a clean git
  tree ahead of tagging.

### Known limitations

- SNKRDUNK automated discovery may be blocked by site protections; manual CSV import remains the
  documented fallback when that happens - see `docs/releases/v1.0.0.md`.
- Analytics and decision-support output is deterministic and rules-based, not financial advice.
- Single-user/local-admin style app - no multi-user auth system, no automatic buy/sell execution.
- Manual QA's viewport/responsiveness pass and a production smoke test against a real deployed
  stack are still recommended before/soon after tagging - not re-run in this pass (no browser
  automation or separate deploy target available in this environment); see
  `docs/release_candidate_report.md`.

## 1.0.0-rc.1 - 2026-07-23

Phase 11: a release-candidate audit pass over the app built out in `0.1.0` below - no new product
features, no formula changes, no scraping behavior changes. See `docs/release_candidate_report.md`
and `docs/release_blockers.md` for the full readiness writeup.

### Added

- `scripts/release_candidate_audit.sh` (`docs/release_candidate_report.md`,
  `docs/release_blockers.md`): a single fail-fast command covering secrets/repo hygiene, backend/
  worker tests, the frontend build, Alembic migrations, API and web route health, the phase 7-10
  audits, backup/restore and import/export dry-run checks, admin-safety and UI-text static checks,
  and release artifact presence - the one gate for "is this ready to tag `v1.0.0-rc.1`".

### Changed

- `docs/release_checklist.md`: added a "v1.0 release candidate checklist" section tying the new
  audit script to the rest of the existing pre-release/build/deploy/rollback checklist.
- `scripts/final_audit.sh`: now also verifies `scripts/release_candidate_audit.sh` exists and is
  executable, with an opt-in `RUN_RELEASE_CANDIDATE_AUDIT=true` to run it inline (off by default,
  same convention as the existing `RUN_PHASE7_AUDIT`/`RUN_PHASE9_AUDIT` flags).
- `VERSION` bumped to `1.0.0-rc.1`.

### Fixed

- N/A (audit pass - no functional changes were needed as a result of this phase).

### Security

- No changes - `scripts/check_secrets.sh` and the existing admin-token/JWT/rate-limit/header
  protections from `0.1.0` are unchanged; the release candidate audit re-verifies them, it does not
  add new ones.

### Operations

- Release-candidate readiness is now a single command
  (`scripts/release_candidate_audit.sh`) rather than several audits run and cross-checked by hand.

### Known limitations

- The release candidate audit's static admin-safety/UI-text checks are best-effort greps, not a
  full audit of every admin action - see `docs/manual_qa_checklist.md` for what still needs a
  manual pass before tagging.
- No `v1.0.0` tag has been cut yet - see `docs/release_blockers.md` for anything still open.

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
