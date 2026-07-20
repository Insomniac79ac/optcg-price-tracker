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
enforced by `apps/web/middleware.ts` (redirects an anonymous visitor to `/market/movers`) - it does
**not** gate `/search`, `/market/*`, `/activity`, or `/cards/[id]`, which stay publicly browsable.

| Route | Purpose | Auth required | Expected status (healthy) | Nav-linked |
|---|---|---|---|---|
| `/dashboard` | Personalized portfolio/wishlist/grading overview plus shared market widgets | Google sign-in | 200 | Yes (primary nav, brand link) |
| `/search` | Card search (Ctrl/Cmd+K opens it) | No | 200 | Yes (primary nav) |
| `/collection` | Collection tracker: items, valuation, CSV import/export, links to wishlist/grading | Google sign-in | 200 | Yes (primary nav) |
| `/analytics/collection` | Collection analytics: composition, valuation exposure, cost basis, concentration risk, grading exposure | Google sign-in | 200 | Yes (primary nav; linked from `/dashboard`, `/collection`, `/grading`) |
| `/analytics/wishlist` | Wishlist analytics: budget planning, target hits, priority exposure, acquisition planning | Google sign-in | 200 | Yes (primary nav; linked from `/dashboard`, `/wishlist`, `/analytics/collection`) |
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

All gated client-side by `AdminAuthGate`/`getAdminToken()` (an `X-Admin-Token` stored in
`localStorage`, entered once via the token-prompt form) and server-side by every underlying
`/admin/*` API call requiring the same token - see "Admin auth audit findings" below.

| Route | Purpose | Auth required | Expected status (healthy) | Nav-linked |
|---|---|---|---|---|
| `/admin/actions` | Manual triggers: refresh prices, snapshot portfolio/signals, generate report, full market refresh, send digest, run workflow | Admin token | 200 | Yes (admin dropdown) |
| `/admin/refresh-runs` | Price refresh run history | Admin token | 200 | Yes (admin dropdown) |
| `/admin/market-workflow-runs` | Market workflow run history | Admin token | 200 | Yes (admin dropdown; linked from release-status, market/report) |
| `/admin/backup` | JSON backup export/validate/restore | Admin token | 200 | Yes (admin dropdown; linked from release-status) |
| `/admin/system-check` | Read-only DB/backup/cross-reference consistency sweep | Admin token | 200 | Yes (admin dropdown; linked from release-status) |
| `/admin/performance` | Table-growth counts, db index audit, latest slow requests; links to logs, system check, release status | Admin token | 200 | Yes (admin dropdown) |
| `/admin/env-check` | *(no frontend page - API-only, see below)* | Admin token | 200 | No - gap, see findings |
| `/admin/logs` | Structured app log search/prune | Admin token | 200 | Yes (admin dropdown; linked from release-status, system-check) |
| `/admin/release-status` | Version/build metadata + release-readiness rollup (system check, workflow run, backup, latest error) | Admin token | 200 | Yes (admin dropdown; linked from system-check) |
| `/admin/rate-limit/status` | *(no frontend page - API-only, see below)* | Admin token | 200 | No - gap, see findings |
| `/admin/source-mappings` | *(no frontend page - API-only, see below)* | Admin token | 200 | No - gap, see findings |
| `/admin/snkrdunk-candidates` | SNKRDUNK candidate review/match/reject | Admin token | 200 | Yes (admin dropdown) |
| `/admin/alerts` | Alert events + alert rule config | Admin token | 200 | Yes (admin dropdown) |
| `/admin/card-audit` | Card data-quality audit report | Admin token | 200 | Yes (admin dropdown) |
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
| `/analytics/*` | `GET /analytics/collection`, `GET /analytics/wishlist`, `GET /analytics/sell-decisions` | user | 200 (401 without a valid bearer token) |
| `/collector/*` | `GET/POST/PATCH/DELETE /collector/tags`, `/collector/groups`; `GET /collector/activity(/summary)`; `GET/POST/PATCH/DELETE /collector/notes` | none | 200 |
| `/market/*` | `GET /market/movers`, `/market/signals`, `/market/signal-events(/{id})` + dismiss/watch/resolve, `/market/opportunities`, `/market/report/latest`, `/market/reports(/{id})` | none | 200 |
| `/admin/*` (+ `/snkrdunk/*`) | See "Admin routes" table above plus `/admin/actions/*` (7 POST triggers), `/admin/backup/{export,validate,restore}`, `/admin/db-backups`, `/admin/db-index-audit`, `/admin/performance/summary`, `/admin/alert-events(/{id})`, `/admin/alert-rules/{id}`, `/snkrdunk/candidates(/{id})` + match/reject | admin | 200 (401/403 without `X-Admin-Token`, 500 if `ADMIN_TOKEN` is unset outside development) |

Full per-route detail (exact path, method, response model) is in each router module under
`services/api/app/api/` - this table is intentionally a grouped summary, not a duplicate of the
OpenAPI schema (`GET /openapi.json` on a running instance is the source of truth for that).

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
links back to `/collection`, `/analytics/collection`, and `/market/opportunities`.

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
