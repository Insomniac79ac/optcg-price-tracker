# Release candidate report - v1.0.0-rc.1

Phase 11 output: a practical snapshot of release-candidate readiness, produced by (and meant to be
read alongside) `scripts/release_candidate_audit.sh`. This is not a marketing summary - it's the
working document you fill in each time the audit is run, until every checklist item is checked and
`docs/release_blockers.md` has no open `blocker`/`high` rows left.

## Release candidate version

`1.0.0-rc.1` (see `VERSION`, `GET /version`, `GET /admin/release-status`).

## Audit date

`_TBD_` - fill in the date/time `scripts/release_candidate_audit.sh` was last run against this
checklist (UTC), and the git commit it was run against (`git rev-parse --short HEAD`).

## Scope

Phase 11 is an audit-and-hardening pass, not a feature phase:

- No new product features.
- No redesign of the app or its information architecture.
- No changes to valuation/pricing formulas.
- No changes to scraping behavior (Yuyu-Tei/SNKRDUNK adapters, request delays, discovery logic).
- No SNKRDUNK live scraping added.
- No bypassing of site protections.

Everything below either confirms existing Phase 1-10 work still holds, or catches gaps that matter
specifically for cutting a `v1.0.0` tag (secrets hygiene, migration safety, backup/restore
correctness, admin safety, release artifacts).

## Feature-complete summary

Phases 1-10 are complete going into this audit:

- **Core data/collection/valuation** - card catalog, price observations, collection tracker,
  portfolio valuation (retail/liquidation/market-floor/graded-adjusted).
- **Market intelligence** - deterministic signals, signal events with a review workflow,
  opportunity scoring, market intelligence reports, Telegram digest.
- **Production hardening** - `docker-compose.prod.yml`, security headers, rate limiting, secret
  redaction in logs, startup env validation.
- **Performance/scale tooling** - caching, pagination, background file jobs, job locks, load test
  scripts (`scripts/phase7_audit.sh`).
- **Analytics and decision support** - buy/sell decision support, grading ROI analytics, portfolio
  risk, analytics digest (`scripts/phase8_audit.sh`).
- **Catalog/matching/data quality ops** - source mapping quality review, card duplicate merge,
  catalog coverage, price source health, import validation (`scripts/phase9_audit.sh`).
- **TCG Vault interface design system** - `docs/interface_design_system.md`, applied across every
  route (`docs/frontend_styling_audit.md`).
- **Saved views, vault view, command palette, responsive polish** - `scripts/phase10_ux_audit.sh`.

## Test checklist

- [ ] `docker compose exec api pytest` passes.
- [ ] `docker compose run --rm worker pytest` passes.
- [ ] `npm run build` (via `docker compose exec/run web`) succeeds.
- [ ] `alembic current` / `alembic heads` / `alembic upgrade head` apply cleanly.

## API route checklist

Public/session-gated:

- [ ] `GET /health`
- [ ] `GET /version`
- [ ] `GET /analytics/digest` (200 or 401 without a session)
- [ ] `GET /collection/summary` (200 or 401 without a session)
- [ ] `GET /market/opportunities`
- [ ] `GET /saved-views` (200 or 401 without a session)

Admin (`X-Admin-Token`):

- [ ] `GET /admin/system-check`
- [ ] `GET /admin/env-check`
- [ ] `GET /admin/release-status`
- [ ] `GET /admin/catalog-coverage`
- [ ] `GET /admin/price-source-health`
- [ ] `GET /admin/source-mappings/quality`
- [ ] `GET /admin/card-audit`
- [ ] `GET /admin/performance/summary`
- [ ] `GET /admin/cache/status`
- [ ] `GET /admin/job-locks`
- [ ] `GET /file-jobs` (the actual route backing the file-jobs list - see note below)
- [ ] `GET /admin/logs`

Note: `/admin/catalog-ops` has no dedicated backend route - it's a frontend-only page aggregating
several of the routes above. `/admin/file-jobs?limit=5` (as sometimes referenced informally) is not
a real route; the real one is `GET /file-jobs`, admin-token-gated via `app.auth.file_job_access`.

## Web route checklist

Collector: `/dashboard`, `/search`, `/collection`, `/collection/vault`, `/wishlist`, `/grading`,
`/activity`.

Market/analytics: `/market/opportunities`, `/market/signals`, `/market/signal-events`,
`/analytics/digest`, `/analytics/collection`, `/analytics/wishlist`, `/analytics/buy-decisions`,
`/analytics/sell-decisions`, `/analytics/grading`, `/analytics/portfolio-risk`.

Admin: `/admin/catalog-ops`, `/admin/cards`, `/admin/import-validation`, `/admin/card-audit`,
`/admin/card-duplicates`, `/admin/snkrdunk-candidates`, `/admin/source-mapping-quality`,
`/admin/catalog-coverage`, `/admin/price-source-health`, `/admin/system-check`, `/admin/actions`,
`/admin/backup`, `/admin/cache`, `/admin/data-retention`, `/admin/file-jobs`, `/admin/job-locks`,
`/admin/logs`, `/admin/performance`, `/admin/refresh-runs`, `/admin/release-status`.

Note: `/admin/env-check` and `/admin/source-mappings` (as distinct from `/admin/source-mapping-
quality`) have no frontend page in this codebase today - the audit script skips them with a
warning rather than guessing a URL that doesn't exist.

## Admin safety checklist

- [ ] Admin token is only ever persisted via `getAdminToken`/`setAdminToken`/`clearAdminToken` in
      `apps/web/src/lib/api.ts` - no other `localStorage` access to an admin/token-shaped key.
- [ ] No saved view or recent-workflow payload includes a `token` field.
- [ ] No `localStorage` key persists confirmation text.
- [ ] Destructive admin actions (merge, restore, import) use `ConfirmActionModal` (with a typed
      `confirmPhrase` for the most dangerous ones), not a bare button or `window.confirm()`.

## Backup/restore checklist

- [ ] `scripts/db_backup.sh`, `scripts/db_restore.sh`, `scripts/db_backup_prune.sh` exist and are
      executable.
- [ ] `GET /admin/backup/export` returns valid JSON.
- [ ] `POST /admin/backup/validate` on that export reports `valid: true`.
- [ ] `POST /admin/backup/restore?dry_run=true` on that export returns `dry_run: true` (never a
      real, non-dry-run restore run by the audit).

## Import/export checklist

- [ ] `GET /admin/cards/export.csv` returns 200.
- [ ] `GET /collection/export.csv` / `GET /wishlist/export.csv` return 200 or 401 (session-gated).
- [ ] `GET /admin/import-templates/card_catalog.csv` returns 200.
- [ ] An invalid `card_catalog` CSV (missing `card_code`) is reported invalid by
      `POST /admin/import-validation/card_catalog` - no real data is ever imported by this audit.

## Production readiness checklist

- [ ] `scripts/check_secrets.sh` passes (no tracked `.env*`, backup dumps, file-job outputs, or
      literal secret values).
- [ ] Git working tree is clean (or `STRICT_GIT=true` is used deliberately for a stricter gate).
- [ ] `scripts/final_audit.sh` passes.
- [ ] Phase 7/8/9/10 audits pass (`SKIP_TESTS=true`, since the backend/worker/web build steps
      already ran once in this audit).
- [ ] Production smoke test passes (`RUN_PROD_SMOKE=true`), run against an actual deployed stack
      before tagging, not just the dev stack.
- [ ] `VERSION`, `CHANGELOG.md`, and the docs listed in "Release artifact checks" (section 15 of
      `scripts/release_candidate_audit.sh`) all exist and are current.

## Known warnings

Fill in from the most recent `scripts/release_candidate_audit.sh` run's "Warnings" list. Leave
`_none recorded yet_` until the audit has actually been run against a live stack.

`_none recorded yet_`

## Release blockers

See `docs/release_blockers.md` for the tracked table. Summary as of this report:

`_no known blockers - see docs/release_blockers.md_`

## Manual QA required before tag

Automated checks cannot substitute for these - see `docs/manual_qa_checklist.md` for the full
page-by-page pass:

- [ ] Mobile (360px), tablet (768px), and desktop (1440px+) pass for every primary route.
- [ ] Command palette (Ctrl/Cmd+K) opens, searches, and navigates correctly.
- [ ] Saved views: create, apply, set default, delete, across at least the vault view and one
      analytics page.
- [ ] Card detail page (`/cards/[id]`) and `/collection/vault` render correctly with real data.
- [ ] `/admin/catalog-ops` correctly links out to every catalog-operations sub-page.
- [ ] `/admin/price-source-health` reflects a real price refresh run's state.
- [ ] Import validation UI (`/admin/import-validation`) correctly previews errors on a bad CSV
      before any real import is attempted.
- [ ] A real (non-dry-run) backup export/restore cycle is exercised at least once in a disposable
      environment - the automated audit only ever exercises the dry-run/validate path.
