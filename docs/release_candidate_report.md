# Release candidate report - v1.0.0-rc.1

Phase 11 output: a practical snapshot of release-candidate readiness, produced by (and meant to be
read alongside) `scripts/release_candidate_audit.sh`. This is not a marketing summary - it's the
working document you fill in each time the audit is run, until every checklist item is checked and
`docs/release_blockers.md` has no open `blocker`/`high` rows left.

## Release candidate version

`1.0.0-rc.1` (see `VERSION`, `GET /version`, `GET /admin/release-status`).

## Audit date

`2026-07-23 05:40 UTC`, git commit `a341e0b` (Phase 11 bug-bash pass; working tree has the fixes
below applied but not yet committed - see "Known warnings").

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

Nothing in this pass touched valuation/analytics/matching formulas or scraping behavior - every fix
below is a test, an audit script, an admin-safety confirmation gate, or a test-runner env issue.

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

- [x] `docker compose exec api pytest` passes - `1227 passed, 11 skipped` (see "Blockers fixed" -
      two collection-time crashes and one flaky test were fixed to get here; +4 from the new
      `test_repo_root.py` regression test added for RC-1).
- [x] `docker compose run --rm worker pytest` passes - `223 passed`.
- [x] `npm run build` (via `docker compose exec/run web`) succeeds.
- [x] `docker compose exec web npm test` (frontend component tests, Vitest) passes - `150 passed`
      across 32 test files. Not part of this checklist's original scope, but fixed and verified
      while adding a Part 8 regression test - see RC-6 in `docs/release_blockers.md`.
- [x] `alembic current` / `alembic heads` / `alembic upgrade head` apply cleanly - single head
      `e7a1c4d9b2f6`.

## API route checklist

Public/session-gated:

- [x] `GET /health`
- [x] `GET /version`
- [x] `GET /analytics/digest` (200 or 401 without a session) - `401` observed (no session sent).
- [x] `GET /collection/summary` (200 or 401 without a session) - `401` observed.
- [x] `GET /market/opportunities`
- [x] `GET /saved-views` (200 or 401 without a session) - `401` observed.

Admin (`X-Admin-Token`):

- [x] `GET /admin/system-check`
- [x] `GET /admin/env-check`
- [x] `GET /admin/release-status`
- [x] `GET /admin/catalog-coverage`
- [x] `GET /admin/price-source-health`
- [x] `GET /admin/source-mappings/quality`
- [x] `GET /admin/card-audit`
- [x] `GET /admin/performance/summary`
- [x] `GET /admin/cache/status`
- [x] `GET /admin/job-locks`
- [x] `GET /file-jobs` (the actual route backing the file-jobs list - see note below)
- [x] `GET /admin/logs`

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

All of the above returned `200` in this pass's `scripts/release_candidate_audit.sh`,
`scripts/phase10_ux_audit.sh`, and `scripts/phase7_audit.sh`/`phase8_audit.sh`/`phase9_audit.sh`
runs (web container reached via a locally-remapped port - see "Known warnings"; route paths
themselves are unaffected).

Note: `/admin/env-check` and `/admin/source-mappings` (as distinct from `/admin/source-mapping-
quality`) have no frontend page in this codebase today - the audit script skips them with a
warning rather than guessing a URL that doesn't exist. Confirmed still accurate in this pass.

## Admin safety checklist

- [x] Admin token is only ever persisted via `getAdminToken`/`setAdminToken`/`clearAdminToken` in
      `apps/web/src/lib/api.ts` - no other `localStorage` access to an admin/token-shaped key.
- [x] No saved view or recent-workflow payload includes a `token` field.
- [x] No `localStorage` key persists confirmation text.
- [x] Destructive admin actions (merge, restore, import) use `ConfirmActionModal` (with a typed
      `confirmPhrase` for the most dangerous ones), not a bare button or `window.confirm()`.
      **Gap found and fixed this pass**: `/admin/cards`' card-catalog CSV "Import for real" ran on
      a single click with no typed confirmation, unlike every other real/destructive admin action
      in the app. Now gated behind `ConfirmActionModal` with a typed `IMPORT` phrase - see RC-5 in
      `docs/release_blockers.md`. Manually reviewed every `variant="danger"`/`variant="real"`
      button in `apps/web/src/app/admin/**` - backup restore-replace (`RESTORE`), data-retention
      prune (`PRUNE`), cache clear (`CLEAR`), and job-lock force-release (`RELEASE`) were all
      already correctly gated.

## Backup/restore checklist

- [x] `scripts/db_backup.sh`, `scripts/db_restore.sh`, `scripts/db_backup_prune.sh` exist and are
      executable.
- [x] `GET /admin/backup/export` returns valid JSON.
- [x] `POST /admin/backup/validate` on that export reports `valid: true`.
- [x] `POST /admin/backup/restore?dry_run=true` on that export returns `dry_run: true` (never a
      real, non-dry-run restore run by the audit).

## Import/export checklist

- [x] `GET /admin/cards/export.csv` returns 200.
- [x] `GET /collection/export.csv` / `GET /wishlist/export.csv` return 200 or 401 (session-gated) -
      `401` observed (no session sent).
- [x] `GET /admin/import-templates/card_catalog.csv` returns 200.
- [x] An invalid `card_catalog` CSV (missing `card_code`) is reported invalid by
      `POST /admin/import-validation/card_catalog` - no real data is ever imported by this audit.

## Production readiness checklist

- [x] `scripts/check_secrets.sh` passes (no tracked `.env*`, backup dumps, file-job outputs, or
      literal secret values). **Fixed this pass** - the script itself had two false-positive bugs
      (misattributed which `KEY=value` on a line it was judging, and truncated values containing
      `$`); see RC-3 in `docs/release_blockers.md`. No real secret was ever present.
- [ ] Git working tree is clean (or `STRICT_GIT=true` is used deliberately for a stricter gate) -
      **not clean as of this report**: this Phase 11 pass's own fixes are staged as uncommitted
      changes (see "Known warnings"). Commit them, then re-run `scripts/final_audit.sh` (default,
      no `ALLOW_DIRTY`) to confirm a clean pass.
- [x] `scripts/final_audit.sh` passes (`ALLOW_DIRTY=true` used for this run, for the reason above;
      re-run without it after committing).
- [x] Phase 7/8/9/10 audits pass (`SKIP_TESTS=true`, since the backend/worker/web build steps
      already ran once in this audit). Verified individually this pass.
- [ ] Production smoke test passes (`RUN_PROD_SMOKE=true`), run against an actual deployed stack
      before tagging, not just the dev stack. **Not run this pass** - no separate deployed stack
      was available in this environment (see "Environment constraints" below); `docker-compose
      .prod.yml`/`docker-compose.prod.private.yml config` were validated instead (both pass).
- [x] `VERSION`, `CHANGELOG.md`, and the docs listed in "Release artifact checks" (section 15 of
      `scripts/release_candidate_audit.sh`) all exist and are current.

## Known warnings

From this pass's `scripts/release_candidate_audit.sh` run:

- Git working tree has uncommitted changes (`STRICT_GIT=true` would hard-fail this) - expected
  mid-fix; see docs/release_blockers.md RC-8.
- `web route /admin/source-mappings does not exist in apps/web/src/app - skipping` - expected,
  documented above; no frontend page for this route by design.
- `web route /admin/env-check does not exist in apps/web/src/app - skipping` - expected, documented
  above; no frontend page for this route by design.

Also observed (not from the audit script, but worth recording):

- `docker compose exec web npm run build` succeeds but prints a Turbopack warning about `fs`/`path`
  tracing rooted at `next.config.ts` -> `src/app/api/version/route.ts`. The route already uses the
  recommended `turbopackIgnore` annotation; cosmetic build-log noise only - see RC-7.

## Release blockers

See `docs/release_blockers.md` for the tracked table. Summary as of this report:

**6 issues found this pass, all fixed; 1 deferred (cosmetic, no action needed); 1 open (expected -
uncommitted working tree, resolves on commit).** No open `blocker` rows remain. No open `high` rows
remain.

| ID | Severity | Area | Status |
|----|----------|------|--------|
| RC-1 | blocker | Backend tests (collection crash) | fixed |
| RC-2 | blocker | Backend tests (flaky ISO-week test) | fixed |
| RC-3 | high | `check_secrets.sh` false positives | fixed |
| RC-4 | high | `phase10_ux_audit.sh` session-gated routes | fixed |
| RC-5 | high | Admin safety - unconfirmed card import | fixed |
| RC-6 | high | Frontend test infra (`NODE_ENV`) | fixed |
| RC-7 | low | Turbopack build warning | deferred (cosmetic) |
| RC-8 | low | Dirty git tree | open (expected mid-fix) |

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

**Not performed this pass** - no browser automation tool was available in this session (see
"Environment constraints"). Substituted where possible with: (a) HTTP-level route checks (every
route above returned 200/expected auth status), (b) static grep checks for anti-patterns (bare
`undefined`/`null`/`NaN` text, bare "Market" labels, admin-token persistence, bright gradients -
all clean per `scripts/phase10_ux_audit.sh` section 5), and (c) targeted source review of every
`variant="danger"`/`variant="real"` admin action (see "Admin safety checklist" above). The
viewport/responsiveness/visual items above still need an actual browser pass before tagging.

## Environment constraints hit during this pass

- **No browser automation available** - the manual QA checklist's viewport/responsiveness/visual
  items (Part 6/section 14 of `docs/manual_qa_checklist.md`) could not be exercised. Not an app
  bug; re-run this checklist by hand (or with a browser-automation tool) before tagging.
- **Port 3000 conflict** - a separate, already-running "prod-simulation" stack
  (`opcg-*-prod` containers) occupies port 3000 in this environment. Rather than stopping those
  containers, `docker-compose.yml`'s `web` service now supports `WEB_PORT` (default `3000`, same as
  before) precisely for this case - see "Running the dev stack when port 3000 is occupied" below
  for the permanent fix (this replaces the untracked `docker-compose.override.yml` workaround used
  earlier in this pass, which has been removed). Environment-only, not an app bug - no route path
  or app behavior changed, only which host port the container publishes to.

### Running the dev stack when port 3000 is occupied

If port 3000 is already occupied by `opcg-web-prod` or another stack, run dev with `WEB_PORT=3001`
and pass `BASE_WEB_URL=http://127.0.0.1:3001` to audit scripts:

```
WEB_PORT=3001 docker compose up -d --build api web worker

BASE_WEB_URL=http://127.0.0.1:3001 \
SKIP_TESTS=true RUN_PHASE_AUDITS=false \
bash scripts/release_candidate_audit.sh

BASE_WEB_URL=http://127.0.0.1:3001 \
SKIP_TESTS=true \
bash scripts/phase10_ux_audit.sh
```

`scripts/final_audit.sh` and `scripts/phase7_audit.sh`/`phase8_audit.sh` read `WEB_BASE_URL`
(not `BASE_WEB_URL`) for the same purpose - e.g. `WEB_BASE_URL=http://127.0.0.1:3001 bash
scripts/final_audit.sh`. Don't mix the two names up; each script's own header comment documents
which one it reads.

All `scripts/*.sh` audit/release scripts now resolve the repo root from their own file location
(`SCRIPT_DIR`/`BASH_SOURCE`) rather than `git rev-parse --show-toplevel`, so they work correctly
`cd`'d into the repo root as usual, and also when invoked by an absolute path from anywhere else
(e.g. `bash /path/to/repo/scripts/release_candidate_audit.sh` from `/`) - previously, running one
from outside the repo entirely produced a bare `docker compose` failure ("no configuration file
provided: not found") instead of a clear error, because the old `git rev-parse`-based lookup failed
silently and left the script's working directory wherever the caller started from.
- **Production smoke test not run** - `scripts/prod_smoke_test.sh` needs a deployed stack distinct
  from the dev stack used for this pass; not attempted here. Next action: run it against a real
  staging/production deploy before tagging, per the pre-existing checklist item above.

## Release recommendation

**Ready with warnings.**

No open `blocker` or `high` severity rows remain in `docs/release_blockers.md`. All automated
checks in this environment pass: secrets check, backend tests (1223 passed), worker tests (223
passed), frontend build, frontend component tests (150 passed), migrations, the full API/web route
checklist, admin-safety static checks, and `scripts/final_audit.sh`/`scripts/phase7-10_audit.sh`.

Before tagging `v1.0.0`:

1. Review and commit this pass's fixes (see `git status` - currently uncommitted).
2. Re-run `scripts/final_audit.sh` with no `ALLOW_DIRTY` override to confirm a clean-tree pass.
3. Complete the manual QA checklist's viewport/responsiveness/visual pass by hand (or with browser
   automation) - not performed in this session, see "Environment constraints" above.
4. Run `scripts/prod_smoke_test.sh` against an actual deployed stack, not just this dev stack.
5. Exercise one real (non-dry-run) backup export/restore cycle in a disposable environment.
