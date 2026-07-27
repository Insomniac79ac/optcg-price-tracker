# Route inventory

A complete inventory of this app's routes, for the final production-readiness audit. Three
sections: frontend public/user pages, frontend admin pages, and backend API routes. See
`docs/route_inventory.md` alongside `docs/deployment.md` (environment/deploy reference) and
`docs/release_checklist.md` (the checklist that links here for section D, post-deploy validation).

"Nav-linked" means reachable from `AppHeader` (the persistent top nav, `apps/web/src/components/
AppHeader.tsx`) or from another page's own links (e.g. `/admin/release-status` cross-links to
`/admin/system-check`/`/admin/logs`/`/admin/backup`) - not necessarily both.

## Public/user routes (frontend pages)

All of these are server-rendered Next.js pages under `apps/web/src/app/`. "Auth required" is
enforced by `apps/web/proxy.ts` (redirects an anonymous visitor to `/sign-in`, preserving the
original path+query as `callbackUrl`) - it does **not** gate `/`, `/search`, `/market/*`, or
`/cards/[id]`, which stay publicly browsable. This table predates the 2026-07-26 frontend
containment pass - see "Update (2026-07-26)" below for what changed (`/activity` is now gated,
`/` no longer redirects to `/dashboard`, and most rows' "Nav-linked" column is stale: the sidebar
only links a reduced route set now).

| Route | Purpose | Auth required | Expected status (healthy) | Nav-linked |
|---|---|---|---|---|
| `/dashboard` | Personalized portfolio/wishlist/grading overview plus shared market widgets | Google sign-in | 200 | Yes (primary nav, brand link) |
| `/search` | Card search (Ctrl/Cmd+K opens it) | No | 200 | Yes (primary nav) |
| `/collection` | Collection tracker: items, valuation, CSV import/export, links to wishlist/grading | Google sign-in | 200 | Yes (primary nav) |
| `/collection/vault` | Collector vault view: grid of owned cards (CardVaultTile), search/set/rarity/variant/status/condition filters, valuation mode, sort, density, saved views | Google sign-in | 200 | Yes (Collection's "Vault View" nav child; linked from `/collection` and `/dashboard`) |
| `/analytics/collection` | Collection analytics: composition, valuation exposure, cost basis, concentration risk, grading exposure | Google sign-in | 200 | Yes (primary nav; linked from `/dashboard`, `/collection`, `/grading`) |
| `/analytics/wishlist` | Wishlist analytics: budget planning, target hits, priority exposure, acquisition planning | Google sign-in | 200 | Yes (primary nav; linked from `/dashboard`, `/wishlist`, `/analytics/collection`) |
| `/analytics/buy-decisions` | Buy decision support: deterministic review-buy/wait/skip/monitor scoring for wishlist cards | Google sign-in | 200 | Yes (primary nav; linked from `/dashboard`, `/wishlist`, `/analytics/wishlist`, `/market/opportunities`) |
| `/analytics/grading` | Grading ROI analytics: submission costs, outcomes, pending returns, and post-grade value | Google sign-in | 200 | Yes (primary nav; linked from `/dashboard`, `/grading`, `/analytics/collection`, `/collection`) |
| `/analytics/sell-decisions` | Sell decision support: deterministic sell/hold/grade-first/monitor scoring for owned cards | Google sign-in | 200 | Yes (primary nav; linked from `/dashboard`, `/collection`, `/analytics/collection`, `/market/opportunities`) |
| `/wishlist` | Wishlist tracker: target prices, CSV import/export, convert-to-collection | Google sign-in | 200 | Yes (primary nav) |
| `/grading` | Grading submission tracker (PSA/BGS/CGC/ARS/other) | Google sign-in | 200 | Yes (primary nav) |
| `/activity` | Collector activity timeline | No | 200 | Yes (primary nav) |
| `/market/report` | Market intelligence report (opportunities, portfolio snapshot, signal summary) | No | 200 (empty state if no report generated yet) | Yes (primary nav; links to opportunities, signal events, admin actions, admin workflow runs, collection) |
| `/market/opportunities` | Opportunity-scored market moves | No | 200 | Yes (primary nav) |
| `/market/signals` | Deterministic market signals (price moves, spreads, floor-vs-retail gaps) | No | 200 | Yes (primary nav) |
| `/market/signal-events` | Persistent signal events with watch/dismiss/resolve workflow | No | 200 | Yes (primary nav) |
| `/market/movers` | Public market-movers browsing page (the anonymous-visitor landing page) | No | 200 | Yes (admin dropdown - see note below) |
| `/cards/[id]` | Single card detail: prices, history, signals | No | 200 (404 for an unknown id) | Linked from search/collection/market pages, not the top nav directly |

Note: `/market/movers` lives in the "Admin" dropdown in `AppHeader.tsx` today for historical
reasons, even though it requires no auth and isn't an admin feature - it's the page anonymous
visitors get redirected to. Low-priority nav cleanup: consider moving it into `PRIMARY_LINKS`
instead (see "Navigation audit findings" below).

## Admin routes (frontend pages)

**Stale as of 2026-07-27 - see "Update (2026-07-27)" below.** The "Auth required: Admin token"
column below describes the pre-admin-login model (a browser-held `X-Admin-Token` in
`localStorage`). Every row now requires a role="admin" Auth.js session instead (`/admin/login`) -
the backend's own `X-Admin-Token` requirement is unchanged, but the browser no longer holds that
token itself; a server-side proxy injects it. Left as originally written rather than rewritten
row-by-row, consistent with this doc's existing convention for a superseded table (see the
2026-07-26 update's own "stale" note above for `Nav-linked`).

| Route | Purpose | Auth required | Expected status (healthy) | Nav-linked |
|---|---|---|---|---|
| `/admin/actions` | Manual triggers: refresh prices, snapshot portfolio/signals, generate report, full market refresh, send digest, run workflow | Admin token | 200 | Yes (admin dropdown) |
| `/admin/refresh-runs` | Price refresh run history | Admin token | 200 | Yes (admin dropdown) |
| `/admin/market-workflow-runs` | Market workflow run history | Admin token | 200 | Yes (admin dropdown; linked from release-status, market/report) |
| `/admin/backup` | JSON backup export/validate/restore | Admin token | 200 | Yes (admin dropdown; linked from release-status) |
| `/admin/system-check` | Read-only DB/backup/cross-reference consistency sweep, including a catalog-operations summary (card audit status, duplicate risk, mapping quality critical count, catalog coverage/price source health, latest import validation status) | Admin token | 200 | Yes (admin dropdown; linked from release-status, `/admin/card-duplicates`, `/admin/catalog-coverage`, `/admin/price-source-health`, `/admin/catalog-ops`) |
| `/admin/performance` | Table-growth counts, db index audit, latest slow requests; links to logs, system check, release status | Admin token | 200 | Yes (admin dropdown) |
| `/admin/env-check` | *(no frontend page - API-only, see below)* | Admin token | 200 | No - gap, see findings |
| `/admin/logs` | Structured app log search/prune | Admin token | 200 | Yes (admin dropdown; linked from release-status, system-check) |
| `/admin/release-status` | Version/build metadata + release-readiness rollup (system check, workflow run, backup, latest error) | Admin token | 200 | Yes (admin dropdown; linked from system-check) |
| `/admin/rate-limit/status` | *(no frontend page - API-only, see below)* | Admin token | 200 | No - gap, see findings |
| `/admin/source-mappings` | *(no frontend page - API-only, see below)* | Admin token | 200 | No - gap, see findings |
| `/admin/snkrdunk-candidates` | SNKRDUNK candidate review/match/reject | Admin token | 200 | Yes (admin dropdown) |
| `/admin/alerts` | Alert events + alert rule config | Admin token | 200 | Yes (admin dropdown) |
| `/admin/card-audit` | Card data-quality audit report | Admin token | 200 | Yes (admin dropdown; linked from `/admin/cards`, `/admin/catalog-coverage`, `/admin/price-source-health`, `/admin/card-duplicates`, `/admin/catalog-ops`) |
| `/admin/cards` | Canonical card catalog browse/search + bulk CSV import/export | Admin token | 200 | Yes (admin dropdown; linked from `/admin/card-audit`, `/admin/catalog-coverage`, `/admin/catalog-ops`) |
| `/admin/card-duplicates` | Duplicate canonical card review + safe merge (preview-only, no bulk/hard-delete) | Admin token | 200 | Yes (admin dropdown; linked from `/admin/card-audit`, `/admin/catalog-coverage`, `/admin/system-check`, `/admin/catalog-ops`) |
| `/admin/source-mapping-quality` | Source mapping quality review: low-confidence, stale, unverified, duplicate-source-URL mappings; recheck/replace-card actions | Admin token | 200 | Yes (admin dropdown; linked from `/admin/card-audit`, `/admin/import-validation`, `/admin/catalog-coverage`, `/admin/price-source-health`, `/admin/catalog-ops`) |
| `/admin/import-validation` | CSV import templates + dry-run validation (card catalog, source mappings, SNKRDUNK candidates, collection, wishlist) + report history | Admin token | 200 | Yes (admin dropdown; linked from `/admin/cards`, `/admin/card-audit`, `/admin/source-mapping-quality`, `/admin/backup`, `/admin/catalog-ops`) |
| `/admin/catalog-coverage` | Canonical card catalog coverage: mapping/recent-price/metadata completion, by set/rarity/variant/language, plus metadata/mapping/price/duplicate/mapping-quality gap drill-downs | Admin token | 200 | Yes (admin dropdown; linked from `/admin/cards`, `/admin/card-audit`, `/admin/source-mapping-quality`, `/admin/card-duplicates`, `/admin/system-check`, `/admin/actions`, `/admin/catalog-ops`) |
| `/admin/price-source-health` | Price source health: refresh success/failure, SNKRDUNK blocked status, stale/missing prices and mapping coverage by set/rarity, per-source health status | Admin token | 200 | Yes (admin dropdown; linked from `/admin/catalog-coverage`, `/admin/source-mapping-quality`, `/admin/refresh-runs`, `/admin/card-audit`, `/admin/system-check`, `/admin/actions`, `/admin/catalog-ops`) |
| `/admin/catalog-ops` | Catalog operations landing page: one dashboard linking card catalog, import validation, card audit, duplicate review, source candidate matching, mapping quality, catalog coverage, price source health, and system check, with a compact cross-subsystem summary | Admin token | 200 | Yes (admin dropdown; linked from `/admin/cards`, `/admin/card-audit`, `/admin/card-duplicates`, `/admin/source-mapping-quality`, `/admin/catalog-coverage`, `/admin/price-source-health`, `/admin/import-validation`, `/admin/system-check`) |
| `/admin/data-health` | *(does not exist)* | - | - | - |

## API routes (backend, `services/api`, mounted directly; also reachable via Next.js server-side
proxy routes under `apps/web/src/app/api/**` for the admin ones)

"Auth required" - **none**: fully public (read-only, no PII). **user**: bearer JWT from
`Authorization: Bearer <token>` (minted by NextAuth on Google sign-in, verified by
`require_current_user`/`require_current_user_optional` in `app/auth.py`). **admin**: `X-Admin-Token`
header, verified by `require_admin_token` (`app/auth.py`), applied as a router-level dependency so
every route under the prefix inherits it - see "Admin auth audit findings" below for the full
per-endpoint sweep.

| Group | Representative routes | Auth | Expected status (healthy) |
|---|---|---|---|
| `/health` | `GET /health` | none | 200, `{"status": "ok", ...}` - exempt from rate limiting (Docker healthchecks poll it) |
| `/version` | `GET /version` | none | 200, version/git-commit/build-time |
| `/cards*` | `GET /cards`, `GET /cards/{id}`, `GET /cards/{id}/prices`, `POST`/`DELETE /cards/{id}/tags/{tag_id}` | none | 200 |
| `/search*` | `GET /search`, `GET /search/suggestions` | none | 200 |
| `/dashboard/*` | `GET`/`PATCH /dashboard/preferences`, `GET /dashboard/overview` | none (per-user personalization only via optional bearer) | 200 |
| `/collection/*` | `GET/POST /collection`, `GET /collection/summary`, `GET /collection/valuation(/history)`, `GET/PATCH/DELETE /collection/{id}`, tag/group assignment, `GET /collection/export.csv`, `POST /collection/import.csv` | user | 200 (401 without a valid bearer token) |
| `/wishlist/*` | `GET/POST /wishlist`, `GET /wishlist/summary`, `GET/PATCH/DELETE /wishlist/{id}`, `POST /wishlist/{id}/mark-purchased`, `POST /wishlist/{id}/convert-to-collection`, CSV import/export | user | 200 (401 without a valid bearer token) |
| `/grading/*` | `GET/POST /grading/submissions`, `GET /grading/summary`, `GET/PATCH/DELETE /grading/submissions/{id}` | user | 200 (401 without a valid bearer token) |
| `/analytics/*` | `GET /analytics/collection`, `GET /analytics/wishlist`, `GET /analytics/sell-decisions`, `GET /analytics/buy-decisions`, `GET /analytics/grading` | user | 200 (401 without a valid bearer token) |
| `/saved-views/*` | `GET/POST /saved-views`, `GET/PATCH/DELETE /saved-views/{id}`, `POST /saved-views/{id}/use`, `POST /saved-views/{id}/set-default`, `POST /saved-views/clear-default` | user | 200 (401 without a valid bearer token) |
| `/collector/*` | `GET/POST/PATCH/DELETE /collector/tags`, `/collector/groups`; `GET /collector/activity(/summary)`; `GET/POST/PATCH/DELETE /collector/notes` | none | 200 |
| `/market/*` | `GET /market/movers`, `/market/signals`, `/market/signal-events(/{id})` + dismiss/watch/resolve, `/market/opportunities`, `/market/report/latest`, `/market/reports(/{id})` | none | 200 |
| `/admin/*` (+ `/snkrdunk/*`) | See "Admin routes" table above plus `/admin/actions/*` (7 POST triggers), `/admin/backup/{export,validate,restore}`, `/admin/db-backups`, `/admin/db-index-audit`, `/admin/performance/summary`, `/admin/alert-events(/{id})`, `/admin/alert-rules/{id}`, `/snkrdunk/candidates(/{id})` + match/reject | admin | 200 (401/403 without `X-Admin-Token`, 500 if `ADMIN_TOKEN` is unset outside development) |
| `/admin/import-templates*`, `/admin/import-validation*` | `GET /admin/import-templates`, `GET /admin/import-templates/{type}.csv`, `POST /admin/import-validation/{import_type}` (dry-run only, never writes imported data), `GET /admin/import-validation/reports(/{id})` | admin | 200 (401/403 without `X-Admin-Token`) |

Full per-route detail (exact path, method, response model) is in each router module under
`services/api/app/api/` - this table is intentionally a grouped summary, not a duplicate of the
OpenAPI schema (`GET /openapi.json` on a running instance is the source of truth for that).

Note: the command palette's "recent workflows" tracking (see
`docs/interface_design_system.md`, "Command palette and workflow shortcuts")
is `localStorage`-only - there is no `/workflow/recent` or similar backend
route. Don't go looking for one; it was a deliberate choice, not an
oversight.

## Findings from this audit (2026-07-17)

**Navigation audit** - no broken links found (verified: every `AppHeader` link resolves to an
existing page; `npm run build` succeeds with all pages listed above present in the route manifest).
Two small gaps, left as-is rather than force-fixed since neither blocks release:

- `/market/movers` sits in the admin dropdown despite being a public page - cosmetic only.
- Three admin API endpoints have no dedicated frontend page: `GET /admin/env-check`, `GET
  /admin/rate-limit/status`, and `/admin/source-mappings`. All three are reachable via `curl -H
  "X-Admin-Token: $ADMIN_TOKEN"` (see `docs/operations.md`) and are already exercised by
  `scripts/prod_smoke_test.sh` (env-check) and the backend test suite; they just don't have a UI.

Already satisfied, verified during this audit rather than newly built:
`/admin/release-status` links to `/admin/system-check`, `/admin/logs`, and `/admin/backup`;
`/market/report` links to `/market/opportunities`, `/market/signal-events`, `/admin/actions`, and
`/admin/market-workflow-runs`; `/collection` links to `/wishlist` and `/grading`; `/collection`,
`/grading`, and `/dashboard` all link to `/analytics/collection`, which links back to `/collection` and
links to `/analytics/wishlist`; `/wishlist` and `/dashboard` also link to `/analytics/wishlist`, which
links back to `/wishlist` and `/analytics/collection`. `/dashboard`, `/collection`,
`/analytics/collection`, and `/market/opportunities` all link to `/analytics/sell-decisions`, which
links back to `/collection`, `/analytics/collection`, and `/market/opportunities`. `/dashboard`,
`/wishlist`, `/analytics/wishlist`, and `/market/opportunities` all link to
`/analytics/buy-decisions`, which links back to `/wishlist`, `/analytics/wishlist`, and
`/market/opportunities`. `/dashboard`, `/grading`, `/analytics/collection`, and `/collection` all
link to `/analytics/grading`, which links back to `/grading` and `/analytics/collection`.

**Admin auth audit** - every `/admin/*` and `/snkrdunk/*` FastAPI router applies
`Depends(require_admin_token)` at the router level (not per-endpoint), so there is no way to add a
new admin endpoint that accidentally skips the check. Verified with a repo-wide grep of every
`APIRouter(prefix=...)` under `app/api/` plus `services/api/tests/test_admin_auth.py` (a
parametrized sweep across 15 representative `/admin/*`/`/snkrdunk/*` GET endpoints) and
`test_admin_actions.py` (all 7 `POST /admin/actions/*` triggers) asserting 401 with no/wrong token
and 200 with the right one. Every Next.js proxy route under `apps/web/src/app/api/admin/**` reads
`X-Admin-Token` from the incoming request header and forwards it - none hardcode a token. No
`NEXT_PUBLIC_*` variable name looks like a secret (enforced both statically by
`scripts/check_secrets.sh` and at build/start time by `apps/web/scripts/check-env.js`).

**Secrets audit** - `scripts/check_secrets.sh` now also checks for tracked backup files
(`*.sql.gz`, `opcg_backup_*.json`) and literal (non-placeholder) values for
`ADMIN_TOKEN`/`TELEGRAM_BOT_TOKEN`/`POSTGRES_PASSWORD`/`API_JWT_SECRET`/`AUTH_SECRET`/
`AUTH_GOOGLE_SECRET`/`DATABASE_URL` outside the two allowed `.env*.example` files, and for any
secret-shaped `NEXT_PUBLIC_*` variable name anywhere in the tree. `.gitignore` now also excludes
`data/backups/`, `*.sql.gz`, and `opcg_backup_*.json`.

## Update (2026-07-26) - collector-first redesign, Phase 1: frontend containment

This audit's findings (anonymous visitors redirected to `/market/movers`, `/` redirecting to
`/dashboard`, `/activity` ungated, static nav arrays with no role filtering, `/admin/*` gated only
client-side by `AdminAuthGate` after the page shell had already rendered) were the basis for a
follow-up implementation task, `collector-blueprint.pdf`. That task changed:

- **`apps/web/middleware.ts` -> `apps/web/proxy.ts`** - Next.js 16 renamed the convention; same
  request-guard behaviour, new file/export name. The static `config.matcher` (Next.js requires
  this to be a literal array, not an imported constant) lives in `proxy.ts` and must stay
  identical to `src/lib/proxyGuard.ts`'s `PROTECTED_MATCHER`, which `proxy.test.ts` enforces.
- **Protected matcher** now covers `/collection`, `/grading`, `/wishlist`, `/dashboard`,
  `/activity` (previously ungated - this closed the audit's finding), and `/analytics/*`. `/admin`
  is deliberately not in the matcher - see below.
- **Signed-out redirect target is `/sign-in`, never `/market/movers`** - a new neutral page that
  preserves the full `callbackUrl` (validated same-origin-only by `src/lib/callbackUrl.ts`, which
  rejects absolute/protocol-relative targets), explains that collector accounts require
  Google sign-in, and only shows the sign-in action when `AUTH_GOOGLE_ID`/`AUTH_GOOGLE_SECRET` are
  actually configured (they still aren't, in this staging build - Google OAuth remains
  unavailable, unchanged from this audit's finding).
- **`/` is now a real public Discover page** (`apps/web/src/app/page.tsx`), not a redirect to
  `/dashboard`. Links to `/search` (Cards) and `/market/movers` (Market Index); explains that
  collection/wishlist/grading need an account.
- **Public nav reduced to Discover (`/`), Cards (`/search`), Market Index (`/market/movers`)**;
  a collector session additionally sees My Collection, Wishlist, Grading, Activity. The old
  Opportunities/Signals/Signal Events/Report/Buy Decisions/Sell Decisions/Portfolio Risk/Analytics
  Digest links and the Admin/Admin-More dropdowns are gone from `SidebarNav.tsx` and
  `commandRegistry.ts` (enforced via a `requires_admin`/`scope` check in
  `visibleCommands()`, not just advisory metadata) - **routes still exist and are still directly
  reachable**, per this audit's own "no broken links" finding; they're just not linked from nav or
  the command palette pending a later product decision. This makes most "Nav-linked" values in the
  tables above stale for the current build.
- **`/admin/*` now has a shared server-side boundary**: `apps/web/src/app/admin/layout.tsx` calls
  `notFound()` unconditionally (no `role` field exists yet on the session/JWT - see
  `src/lib/auth.ts`), before any admin page shell, chrome, or nav renders. This replaces
  `AdminAuthGate` as the *first* gate - `AdminAuthGate` still exists and still gates each page's
  own data fetch as defense in depth, but a signed-out or non-admin visitor now gets a 404 before
  reaching it. Every Next.js `/api/admin/**` route handler was re-verified as still doing what this
  audit already found: forwarding the caller-supplied `X-Admin-Token` header to the backend rather
  than holding a secret itself, so the backend's `require_admin_token` dependency (unchanged) is
  still the real enforcement point - this task did not touch it.
- Not done in this task (tracked as the next one): a real admin login. Until then, admin access is
  direct backend tooling (`curl -H "X-Admin-Token: ..."`, per `docs/operations.md`) only.

## Update (2026-07-27) - temporary admin login (staging/prototype only)

Closes the previous update's "tracked as the next one" gap. Full architecture in
`docs/staging_deployment.md` section 13. Changes relevant to this inventory:

- **New public route**: `/admin/login` - email/password form, generic error, outside the
  `(protected)` route group so it stays reachable without a session. Auth required: none (that's
  the point - it's where a session is established). Links back to Discover; no Google button (see
  `src/app/sign-in/page.tsx` for that, unchanged).
- **New route group**: every existing `/admin/*` page moved under `app/admin/(protected)/*`
  (Next.js route groups don't affect the URL - `/admin/cache` is still `/admin/cache`). "Auth
  required" for the entire "Admin routes" table above is now **admin session** (`role="admin"` on
  the Auth.js session, established via `/admin/login`), not a raw token - the previous
  `AdminAuthGate`/localStorage flow is deleted (`getAdminToken`/`setAdminToken`/`clearAdminToken`
  no longer exist in `apps/web/src/lib/api.ts`).
- **New index page**: `/admin` - the default post-login destination and `SidebarNav`'s single
  "Admin" entry target. Not present before this task.
- **Backend**: one new unauthenticated endpoint, `POST /auth/admin/verify` (+ `GET
  /auth/admin/status`), deliberately outside `require_admin_token` - it's what *establishes* an
  admin session, not a consumer of one. Grants no access to any other `/admin/*` route by itself.
  Every other backend `/admin/*`/`/snkrdunk/*` route's `require_admin_token` dependency is
  completely unchanged.
- **Six frontend data-fetch functions stopped calling the backend directly from the browser**:
  `fetchAlertEvents`/`fetchAlertRules`(+`fetchAlertEvent`/`updateAlertRule`),
  `fetchRefreshRuns`/`fetchRefreshRun`, and `fetchSnkrdunkCandidates` used to call
  `NEXT_PUBLIC_API_URL` directly with an admin-token header attached if present (see the
  now-superseded "Known direct backend calls" list this replaces in `docs/staging_deployment.md`
  section 4) - removing the browser-held token would have silently broken them. They now go
  through same-origin Next.js proxy routes (`/api/admin/alert-events`, `/api/admin/alert-rules`,
  `/api/admin/refresh-runs`, `/api/admin/snkrdunk-candidates`) like every other admin page.
- **"Admin auth audit findings" above is otherwise still accurate** for the backend: every
  `/admin/*`/`/snkrdunk/*` router still applies `Depends(require_admin_token)` at the router
  level, unchanged. What changed is *who supplies that header* - every Next.js
  `/api/admin/**` Route Handler now reads `ADMIN_TOKEN` from its own server-side `process.env`
  (`src/lib/adminProxy.ts`) and ignores any caller-supplied `X-Admin-Token`, rather than
  forwarding whatever the browser sent.
- Google OAuth remains unconfigured, unchanged. This mechanism is explicitly temporary - see
  `docs/staging_deployment.md` section 13's migration path for its planned removal.
