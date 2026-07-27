# Staging deployment (Vercel + Railway)

Staging deployment of the OPTCG price tracker (`v1.0.0`) onto a split hosting topology: Vercel
hosts the Next.js frontend (`apps/web`), Railway hosts everything else (`api`, `worker`, `beat`,
managed Postgres, managed Redis). This document covers the target architecture, required env
vars, deploy order, migrations, smoke tests, rollback, and known limitations.

This is additive infrastructure/config work only - it does not change any valuation, analytics, or
matching formula, does not change scraping behavior, and does not add SNKRDUNK live scraping or
bypass any site protection. See [docs/railway_staging.md](railway_staging.md) for the Railway
service setup in full detail and [docs/staging_checklist.md](staging_checklist.md) for the
step-by-step deploy runbook. `docs/deployment.md` section 11 already covers the general shape of a
Vercel+Railway split for a *production* deploy - this document is the staging-specific version of
that, with staging-safe defaults (`SCRAPING_MODE=mock`, workflows disabled) and its own checklist.

## 1. Architecture overview

```
Browser
  |
  v
Vercel (apps/web, Next.js)
  |  - pages render server-side and client-side
  |  - Next.js API route handlers (src/app/api/**) proxy to Railway's api
  |    service using API_INTERNAL_URL/API_BASE_URL (server-side only)
  |  - a subset of pages call the Railway api service *directly* from the
  |    browser via NEXT_PUBLIC_API_URL - see section "Known direct backend
  |    calls to fix before production" below
  v
Railway
  |-- api service (FastAPI/uvicorn)      <- public HTTPS URL, /health, /version
  |-- worker service (Celery worker)      <- no public URL
  |-- beat service (Celery beat/scheduler) <- no public URL
  |-- Postgres (managed plugin)           <- private networking URL preferred
  |-- Redis (managed plugin)              <- private networking URL preferred
```

The browser's primary path is Vercel frontend routes. Server-side Next.js route handlers proxy
backend API calls to Railway's `api` service over its public URL (Railway does not expose a
network path from Vercel to a "private only" service - see [section
4](#4-known-direct-backend-calls-to-fix-before-production)/[section
9](#9-known-limitations) for why `api` must have a public URL in this topology regardless).
`worker` and `beat` never need a public URL - they only consume/schedule Celery jobs against
Redis/Postgres.

## 2. Vercel services

One Vercel project:

| Setting | Value |
|---|---|
| Service name | `web` |
| Root directory | `apps/web` (monorepo project setting) |
| Framework preset | Next.js (auto-detected) |
| Build command | existing project command - `npm run build` (`package.json`'s `build` script, unchanged) |
| Install command | existing project command - `npm ci` (Vercel's Next.js default; this repo only has `package-lock.json`, no other lockfile) |
| Output | Next.js default / Vercel-managed (no static export - this app uses server-side API routes and SSR) |
| Environment | Preview or a dedicated "staging" environment/branch (Vercel's Preview Deployments, or a custom environment on paid plans) |

**What was actually done (2026-07-26)**: rather than a Preview environment on the main
production-named project, this deployed to its own dedicated Vercel project,
`optcg-price-tracker-staging`, with env vars in **Production** scope (not Preview) so the
deployment gets a stable, permanent domain (`optcg-price-tracker-staging.vercel.app`) instead of
an ephemeral per-commit preview URL. The project's Git "Production Branch" setting could not be
changed from `main` to `staging` via the Vercel REST API (`PATCH /v9|v10/projects/:id` rejects a
`link`/`productionBranch` body with a schema error) - it remains a manual dashboard step
(Settings -> Git -> Production Branch). Until that's changed, deploys are pushed explicitly via
`vercel deploy --prod` from a local `staging` checkout rather than triggered automatically by
`git push`.

Environment variables (Production scope on the dedicated staging project):

| Variable | Value | Notes |
|---|---|---|
| `NEXT_PUBLIC_APP_ENV` | `staging` | Set for visibility/future use. Not read by any current frontend code path (`apps/web/scripts/check-env.js` reads bare `APP_ENV`/`NODE_ENV`, not this). Never a secret. |
| `API_INTERNAL_URL` | Railway `api` service's public HTTPS URL | **Required.** Read server-side only by every route handler under `apps/web/src/app/api/**`. Falls back to `http://api:8000` (the Docker Compose service DNS name) when unset - that fallback only works inside the local Docker Compose network, so this must always be set explicitly on Vercel. |
| `NEXT_PUBLIC_API_URL` | Railway `api` service's public HTTPS URL, or blank | Only needed if you want the browser-direct pages/functions listed in [section 4](#4-known-direct-backend-calls-to-fix-before-production) to work. Baked into the client bundle at build time - changing it requires a redeploy. **Never** set this to a bare `/api` path; the direct calls it feeds do not go through the Next.js proxy layer. |
| `AUTH_URL` | the stable Vercel staging domain (`https://optcg-price-tracker-staging.vercel.app`) | Auth.js's canonical base URL - avoids relying on header-based origin detection. |
| `API_JWT_SECRET` | shared secret, same value as the Railway `api` service | Required for per-user auth (`/collection`, `/grading`, `/collector`) - see `docs/deployment.md` section 10. Copy it byte-for-byte (e.g. `railway variables --kv | grep ^API_JWT_SECRET= | cut -d= -f2- | vercel env add API_JWT_SECRET production --sensitive`) rather than retyping it. |
| `AUTH_SECRET` | random value (`openssl rand -base64 33`) | Auth.js session-encryption secret. |
| `AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET` | staging OAuth client credentials | Use a separate Google OAuth client from production, with `<vercel-staging-domain>/api/auth/callback/google` as an authorized redirect URI. **Not yet set** - no real credentials exist for staging as of 2026-07-26; Google sign-in is untested until these are created and added. |
| `ADMIN_TOKEN` | same value as the Railway `api` service's `ADMIN_TOKEN` | **Server-only, Production scope, Sensitive.** Added 2026-07-27 as part of the temporary admin-login task (section 13) - read only by `src/lib/adminProxy.ts` inside `/api/admin/**` Route Handlers, server-side, to authenticate to the Railway backend. The browser never receives this value; see section 13 for why this is now safe to set here at all (it wasn't, before that task - see the superseded note this replaces). |

`API_BASE_URL` and bare `APP_ENV` (listed in earlier drafts of this doc) were deliberately **not**
set: neither is read anywhere in `apps/web`'s application code (confirmed by search), so adding
them would just be inert configuration.

**Do not** set any `NEXT_PUBLIC_ADMIN_TOKEN` (or any other `NEXT_PUBLIC_*` variable that looks like
a secret) - `apps/web/scripts/check-env.js` fails the build/start if it finds one. `ADMIN_TOKEN`
itself (no `NEXT_PUBLIC_` prefix) is now intentionally set here - see the table row above and
section 13.

## 3. Railway services

Four services (two managed plugins, two/three code services) in one Railway project - see
[docs/railway_staging.md](railway_staging.md) for full per-service setup:

| Service | Type | Public URL? |
|---|---|---|
| Postgres | managed plugin | no (private networking only) |
| Redis | managed plugin | no (private networking only) |
| `api` | code service, `deploy/railway/api.Dockerfile`, Root Directory `/` | **yes** - `/health`, `/version`, and everything the browser/Vercel proxy needs to reach |
| `worker` | code service, `deploy/railway/worker.Dockerfile`, Root Directory `/`, command `celery -A worker.celery_app worker --loglevel=info` | no |
| `beat` | code service, `deploy/railway/beat.Dockerfile`, Root Directory `/`, command `celery -A worker.celery_app beat --loglevel=info` | no |

`apps/web` (the Next.js frontend) is **not** a Railway service at all - it deploys to Vercel only
(section 2 above). None of the three Railway services build or reference `apps/web`.

Each Railway service builds from the **repo root** as its Docker build context, using a
Railway-specific Dockerfile under `deploy/railway/` rather than the original
`services/api/Dockerfile`/`services/worker/Dockerfile` directly - see "Why a separate Dockerfile
per Railway service" in [docs/railway_staging.md](railway_staging.md) for why (short version: those
original Dockerfiles assume the build context is their own subdirectory, which only holds if
Railway's Root Directory setting is scoped exactly right - easy to get wrong in a multi-language
monorepo, and the cause of this staging deployment's original Railway build failure).

## 4. Known direct backend calls to fix before production

Most of the app already goes through Next.js server-side proxy routes (`apps/web/src/app/api/**`,
using `API_INTERNAL_URL`) - notably every `/admin/*` curation workflow added after the original
build (SNKRDUNK candidate matching, source-mapping quality review, card duplicate/merge, catalog
coverage, price source health, saved views, analytics digest, dashboard overview, backup
export/restore, etc. - see `fetchAdminJson`/`authedGet` callers wired to a `src/app/api/**` route
in `apps/web/src/lib/api.ts`).

However, a meaningful set of older functions in `apps/web/src/lib/api.ts` call the backend
**directly from the browser** via `NEXT_PUBLIC_API_URL` (this was already true before this staging
work, and is documented as a known tradeoff in `docs/deployment.md` section 6/13). Rewriting all of
these to go through a server proxy route is a real, multi-file frontend change - out of scope for
this staging pass (risk of regressions outweighs the benefit for a first staging deploy). They are
listed here so staging config accounts for them, and so a future pass can migrate them
incrementally:

**Public reads** (`apiGet`, no auth header, genuinely unauthenticated backend routes):
- `fetchCards`, `fetchCard`, `fetchCardPrices` - card catalog/detail/prices (`/cards/*`)
- `fetchMarketMovers` - `/market/movers` (used by `/market/movers`, a public page)

`fetchAlertEvents`/`fetchAlertEvent`/`fetchAlertRules`/`updateAlertRule`,
`fetchRefreshRuns`/`fetchRefreshRun`, and `fetchSnkrdunkCandidates` **used to** be in this
direct-from-browser bucket too (`/admin/alert-events`, `/admin/alert-rules`, `/admin/refresh-runs`,
`/snkrdunk/candidates` - all `require_admin_token` on the backend), relying on the same
browser-held admin token as every other admin page. The admin-login task (section 13) removed that
token entirely, so as of 2026-07-27 these seven now go through a same-origin Next.js proxy route
(`/api/admin/alert-events`, `/api/admin/alert-rules`, `/api/admin/refresh-runs`,
`/api/admin/snkrdunk-candidates` - `src/lib/adminProxy.ts`) like every other admin page, authorized
by the Auth.js session cookie instead. `matchSnkrdunkCandidate`/`rejectSnkrdunkCandidate` remain
direct-to-backend but are dead code - no page currently calls them (the live snkrdunk-candidates
page uses the newer `/admin/snkrdunk-candidates/*` proxy routes for match/reject actions instead).

**Per-user pages** (`authedGet`/`authedPost`/`authedPatch`/`authedDelete`, bearer token from the
NextAuth session attached): every read/write behind `/collection`, `/wishlist`, `/grading`, and
`/collector` (tags/groups/notes/activity) - e.g. `fetchCollectionItems`, `createCollectionItem`,
`fetchGradingSubmissions`, `createGradingSubmission`, `fetchWishlistItems`,
`createWishlistItem`, `fetchCollectorTags`, `createCollectorTag`, `fetchCollectorActivity`, and
their corresponding update/delete functions.

**What this means for staging**:
- `NEXT_PUBLIC_API_URL` **must** be set to the Railway `api` service's public HTTPS URL, or
  `/dashboard`, `/collection`, `/wishlist`, `/grading`, `/collector`, `/market/movers`, and card
  detail pages will fail with network errors in the browser. (The admin alert/refresh-run/snkrdunk
  pages no longer need this - see the `fetchAlertEvents` note above.)
- Because the browser calls a different origin (`*.up.railway.app`) than the page is served from
  (`*.vercel.app`), Railway's `api` service **must** set `CORS_ALLOWED_ORIGINS`/
  `CORS_ALLOW_ORIGIN_REGEX` to the Vercel staging domain (see `services/api/app/main.py`), or every
  one of these calls fails as a CORS error, not a 4xx/5xx - check the browser console, not just
  the Network tab's status codes, if these pages don't load.
- `api` therefore cannot be made Railway-private-only for this app in its current form, unlike a
  pure API-gateway architecture - see [Known limitations](#9-known-limitations).

## 5. Required staging environment variables

See [.env.staging.example](../.env.staging.example) for the full annotated list (Vercel frontend
vars, Railway backend vars, workflow vars, Telegram vars). Summary:

**Vercel (web)**: `APP_ENV`, `NEXT_PUBLIC_APP_ENV`, `API_BASE_URL`, `API_INTERNAL_URL`,
`NEXT_PUBLIC_API_URL` (see section 4), `API_JWT_SECRET`, `AUTH_SECRET`, `AUTH_GOOGLE_ID`,
`AUTH_GOOGLE_SECRET`.

**Railway (api, worker, beat - shared)**: `APP_ENV`, `DATABASE_URL`, `REDIS_URL`, `ADMIN_TOKEN`,
`SCRAPING_MODE`, `YUYUTEI_REQUEST_DELAY_MS`, `SNKRDUNK_REQUEST_DELAY_MS`,
`PRICE_REFRESH_INTERVAL_HOURS`, `CACHE_ENABLED`, `CACHE_BACKEND`.

**Railway api only**: `API_JWT_SECRET`, `CORS_ALLOWED_ORIGINS`, `CORS_ALLOW_ORIGIN_REGEX`.

**Railway beat only**: `MARKET_WORKFLOW_ENABLED=false`, `MARKET_WORKFLOW_SOURCE`,
`MARKET_WORKFLOW_LIMIT`, `MARKET_WORKFLOW_SEND_TELEGRAM=false`, `DATA_RETENTION_ENABLED=false`.

**Telegram (optional, all services that send alerts)**: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` -
omit both, or point at a staging-only test channel/bot. Never the production bot/channel.

## 6. Deployment order

1. Create the Railway project; add the Postgres and Redis managed plugins first (other services
   depend on their connection strings existing).
2. Create the Railway `api` service from this GitHub repo, with Root Directory `/` and Dockerfile
   Path `deploy/railway/api.Dockerfile` (see `docs/railway_staging.md` section 3 - do **not** point
   Root Directory at `services/api` with the original `services/api/Dockerfile`; that combination
   is what caused this staging deployment's original Railway build failure). Set its env vars
   (section 5). Deploy it and confirm `GET /health` responds before continuing.
3. Run migrations against the Railway Postgres (`scripts/staging_migrate.sh` - see section 7).
4. Create the Railway `worker` service (same repo, Root Directory `/`, Dockerfile Path
   `deploy/railway/worker.Dockerfile`). Set its env vars. Deploy.
5. Create the Railway `beat` service (same repo, Root Directory `/`, Dockerfile Path
   `deploy/railway/beat.Dockerfile`). Set its env vars, with workflows disabled (section 5). Deploy.
6. Create the Vercel project with Root Directory `apps/web`. Set its env vars (section 2), pointing
   `API_INTERNAL_URL`/`API_BASE_URL` (and `NEXT_PUBLIC_API_URL`, if used) at the now-running Railway
   `api` service's public URL.
7. Deploy Vercel. If any Vercel env var changed after the first deploy (common - you don't know the
   Railway `api` URL until step 2 finishes), redeploy Vercel once more so the build picks it up
   (`NEXT_PUBLIC_API_URL` is baked in at build time).
8. Run `scripts/staging_smoke_test.sh` against the deployed URLs (section 7/8, and
   `docs/staging_checklist.md`).

## 7. Migration steps

Use `scripts/staging_migrate.sh` (see the script's own header for full usage):

```
DATABASE_URL=<railway-postgres-url> bash scripts/staging_migrate.sh
```

Run this once after the Railway Postgres plugin and `api` service both exist, before relying on
`api`/`worker`/`beat` to serve real traffic. If running it locally is impractical (the Python
dependencies in `services/api/requirements.txt` aren't installed locally), run the equivalent
command directly inside the deployed Railway `api` service instead (Railway dashboard's "Shell" /
`railway run`, or a one-off Railway CLI command):

```
railway run --service api alembic upgrade head
```

## 8. Smoke tests

`scripts/staging_smoke_test.sh` (see its header for the full env var reference):

```
STAGING_API_URL=https://<railway-api-url> \
STAGING_WEB_URL=https://<vercel-staging-url> \
ADMIN_TOKEN=<staging-admin-token> \
bash scripts/staging_smoke_test.sh
```

Checks API `/health`, `/version` (if present), `/analytics/digest`, `/saved-views?limit=5`, the two
admin checks (`/admin/system-check`, `/admin/catalog-coverage`) if `ADMIN_TOKEN` is set, and the
web app's `/`, `/dashboard`, `/collection`, `/collection/vault`, `/analytics/digest`, and
`/admin/catalog-ops` routes. Prints `PASS`/`FAIL` per check; does not run any destructive action.

## 9. Rollback notes

- **Frontend (Vercel)**: use Vercel's own deployment history - "Instant Rollback" to the previous
  deployment from the project dashboard, or `git revert`/redeploy the previous commit. No database
  is involved on the Vercel side, so this is always safe and immediate.
- **Backend (Railway)**: redeploy the previous commit/image for `api`/`worker`/`beat` from the
  Railway dashboard's deployment history, or `git checkout <previous-commit> && git push` to the
  branch Railway tracks.
- **Database**: if a migration ran as part of the deploy being rolled back, restore the most recent
  backup taken before that migration (see `docs/operations.md`'s backup/restore drill - the same
  `scripts/db_backup.sh`/`scripts/db_restore.sh` pattern applies, pointed at the Railway Postgres
  connection string instead of the local `postgres` container). Skip this step if the deploy didn't
  change the schema or existing data.
- Re-run `scripts/staging_smoke_test.sh` after any rollback - don't consider it complete until it
  passes.

## 10. Known limitations

- **Railway's "error deploying from source" diagnosis was inferred from repo structure, not
  confirmed by a build log.** An initial Railway deploy of this staging setup failed with only a
  generic "error deploying from source" message and no detailed log available. Based on how
  `services/api/Dockerfile`/`services/worker/Dockerfile` assume their build context is their own
  subdirectory (see `docs/railway_staging.md` "Why a separate Dockerfile per Railway service"),
  the most likely cause is a Root Directory/build-context mismatch - not confirmed against an
  actual failing build log. The fix applied (repo-root-context `deploy/railway/*.Dockerfile` files)
  removes that whole class of failure regardless of the exact variant, and all three images have
  been verified to build and run locally (see `docs/railway_staging.md` "Local build
  verification"). If a real Railway deploy still fails after this change, capture the actual build
  log before further changes - do not re-guess.
- **`api` cannot be Railway-private-only** while the direct browser calls in [section
  4](#4-known-direct-backend-calls-to-fix-before-production) exist - it needs a public HTTPS URL
  reachable from the browser, with CORS configured for the Vercel domain. This differs from the
  ideal "browser only ever talks to Vercel" architecture the task describes; the gap is tracked in
  section 4, not silently worked around.
- **Vercel never runs `apps/web`'s `start` script** (`npm start` / `node scripts/check-env.js
  start && next start ...`) - Vercel builds with `next build` and serves pages through its own
  managed runtime, not this repo's Docker `CMD`. This means the `API_INTERNAL_URL`-presence check
  in `check-env.js`'s `start` phase never runs on Vercel; a missing `API_INTERNAL_URL` on Vercel
  fails silently at request time (each proxy route falls back to `http://api:8000`, which doesn't
  resolve outside Docker, so the browser sees a 502 from that route) rather than failing the build
  up front. Double-check `API_INTERNAL_URL` is set in the Vercel dashboard - there is no automated
  gate catching a missing value the way there is in the Docker/Compose path.
- **`APP_ENV=staging` is not a recognized value in the backend's own env validation**
  (`services/api/app/core/env_validation.py`/`services/worker/worker/env_validation.py` only
  special-case `production` and `development` - anything else, including `staging`, is treated
  like "not production", so the hard production-only startup checks (`ADMIN_TOKEN` shape/length,
  `SCRAPING_MODE=live` minimum delays, Telegram completeness) do not hard-fail on staging the way
  they would in a real production deploy). This is existing app behavior, intentionally left
  unchanged for this staging pass (no formula/validation-logic changes) - set staging values
  correctly by hand regardless of what startup validation would or wouldn't catch (see
  [.env.staging.example](../.env.staging.example)).
- **Single Railway region/instance assumptions in the app's rate limiting** (`app.core.rate_limit`)
  carry over unchanged from production - see `docs/deployment.md` section 12. Not a staging-specific
  concern, just worth knowing if `api` is ever scaled to multiple Railway replicas.
- **No staging-specific test data seed script** is added here - use
  `python -m app.seed` (reference `sources` rows) and a small watchlist CSV import
  (`python -m app.import_watchlist <path>`, run inside the Railway `api` service) if you want
  realistic data rather than an empty catalog. Do not use `app.seed_performance_data` against
  staging unless you specifically want synthetic load-test data.

## 11. Safety notes

- Staging starts with `SCRAPING_MODE=mock` on `api`/`worker`/`beat` - no real requests to
  Yuyu-Tei/SNKRDUNK. Do not switch to `live` until `api`/`worker`/`beat` have been running stably on
  staging for a while and you've deliberately decided to exercise the real scrape path (staging's
  own dry-run/mock refresh is sufficient for most verification).
- `MARKET_WORKFLOW_ENABLED=false` and `DATA_RETENTION_ENABLED=false` by default on the `beat`
  service for the first staging deploy - enable them explicitly, and only after confirming
  `api`/`worker`/`beat` are stable, per `docs/staging_checklist.md`.
- Never attempt a SNKRDUNK live-scrape or any bypass of Yuyu-Tei/SNKRDUNK site protections, in
  staging or production. SNKRDUNK data only ever enters this app through the existing manual
  candidate-import workflow (`/admin/snkrdunk-candidates` uploading manually-collected listings),
  regardless of environment.
- Never commit `.env.staging` (only `.env.staging.example`, with placeholders, is tracked - see
  `.gitignore` and `scripts/check_secrets.sh`).

## 12. Frontend containment deploy (2026-07-26)

Collector-first redesign, Phase 1 (`collector-blueprint.pdf`) - closes the audit's frontend
findings (unauthenticated visitors redirected to `/market/movers`, `/` redirecting to `/dashboard`,
`/activity` ungated, admin nav/commands visible with no session concept, `/admin/*` gated only
client-side after the page shell rendered) before the visual redesign begins. Full route-level
detail is in `docs/route_inventory.md`'s "Update (2026-07-26)" section; this entry is the
deploy/infra record.

**What changed**: `middleware.ts` -> `proxy.ts` (Next.js 16 rename); signed-out redirect target is
now `/sign-in` (never `/market/movers`), with `callbackUrl` preserved and validated same-origin-only;
`/` is a real public Discover page instead of a redirect; `/activity` and `/analytics/*` are now in
the protected matcher; public/collector nav and the command palette are reduced to a working route
set with `requires_admin`/`scope` actually enforced; `/admin/*` gets a shared server-side boundary
(`app/admin/layout.tsx`, unconditional `notFound()` - no `role` field exists yet) in front of the
existing client-side `AdminAuthGate`. Backend `X-Admin-Token` enforcement, the database, pricing,
image models, and Market Index are unchanged.

**Deploy mechanics** (not a change to the topology in section 2, just a record of what actually
running a deploy looked like): this Vercel project's Git "Production Branch" is still `main` (see
section 2's "What was actually done"), so `git push origin staging` does **not** auto-deploy it -
every deploy in this pass was `vercel deploy --prod` run explicitly from a `staging` checkout,
authenticated with `vercel login`/a pasted `VERCEL_TOKEN` (never committed, only exported into the
shell environment for the duration of the deploy command).

**Two bugs found only by live-verifying the first deploy, not by `next build` or the test
suite** - both are recorded in commit `0ca3f40`'s message in full; summarized here because they're
exactly the kind of thing a future proxy.ts change could reintroduce silently:

1. `proxy.ts` was placed at `apps/web/proxy.ts` (package root). This project's app router lives at
   `src/app`, and Next.js's docs say proxy.ts belongs "at the same level as pages or app" - at the
   root it compiled cleanly and even showed as `ƒ Proxy (Middleware)` in the `next build` summary,
   but was never invoked at request time, on Vercel *or* locally via `next build && next start`.
   Fixed by moving it to `src/proxy.ts`.
2. Once discoverable, `auth()`'s internal session check threw `UntrustedHost`
   (https://errors.authjs.dev#untrustedhost) and - critically - failed *open*, letting the
   "protected" route render normally instead of redirecting. Fixed with `trustHost: true` in
   `src/lib/auth.ts`'s NextAuth config (safe on Vercel - its edge network sets the Host header
   itself, it can't be spoofed by the client).

Neither bug was visible in `npm run build`, `npm test`, or a code review of the diff - both only
showed up by actually curling the deployed protected routes and checking for a 307, which is why
section 8's smoke tests and the "Live staging verification" step in this kind of task matter even
when the build and test suite are green. **Post-fix, live-verified against
`https://optcg-price-tracker-staging.vercel.app`**: `/collection`, `/dashboard`, `/wishlist`,
`/grading`, `/activity` (including `?query=strings`) all 307 to `/sign-in?callbackUrl=...`; `/`,
`/search`, `/market/movers` stay 200; `/admin/system-check`, `/admin/backup`, `/admin/cards` all
404 with no admin shell/content in the response (verified the response body, not just the status
code - Next.js's RSC flight payload echoes the requested route segments even on a 404 page, which
looks like a match for an `admin`/page-name grep but isn't a content leak).

**Still true, unchanged by this task**: Google OAuth has no real credentials on staging (`/sign-in`
correctly shows "collector accounts are not enabled" rather than a broken sign-in button); there is
no admin session/login yet, so `/admin/*` is unconditionally unreachable from the browser - use
direct backend tooling (`curl -H "X-Admin-Token: ..."`, per `docs/operations.md`) until the
dedicated admin-login task lands.

## 13. Temporary admin login (2026-07-27)

**Staging/prototype only.** This entire mechanism - the Credentials provider, the backend
verify endpoint, the Redis-backed throttle - exists solely to unblock admin access on staging
before Google OAuth is configured, and is designed to be deleted wholesale once section 13's
[migration path](#migration-path-to-google-oauth) lands. It is not a general-purpose auth system
and should not be extended (no password reset, no registration, no second admin account, no
role other than `"admin"`).

**Why this was needed**: the frontend-containment task (section 12) closed `/admin/*` to the
browser entirely - a safe default, but with no way back in short of direct backend `curl` calls.
Google OAuth (the eventual real answer) has no staging credentials yet. This bridges that gap.

### Architecture

```
Browser
  -> Auth.js Credentials login (email + password, /admin/login)
  -> src/lib/auth.ts's adminAuthorize() (server-side)
  -> POST https://<railway-api>/auth/admin/verify
     -> Redis-backed throttle check (app.core.admin_login_throttle)
     -> Argon2id verify against ADMIN_LOGIN_PASSWORD_HASH (app.core.admin_password)
     -> { id, email, role: "admin" }  (nothing else - no ADMIN_TOKEN, no hash, no secret)
  -> Auth.js JWT session, role="admin" claim, 4h expiry (independent of the
     underlying session cookie's own lifetime)

Authenticated admin browser request
  -> Next.js /admin/* page or /api/admin/** Route Handler
  -> requireAdminSession() / requireAdminOrResponse() (src/lib/adminSession.ts, src/lib/adminProxy.ts)
     - calls Auth.js auth() server-side; never trusts a client-supplied role/header
  -> server-side ADMIN_TOKEN read from process.env, injected as X-Admin-Token
  -> Railway api service (app.auth.require_admin_token - unchanged)
```

The browser never receives `ADMIN_TOKEN`, `API_JWT_SECRET`, or `ADMIN_LOGIN_PASSWORD_HASH` at any
point in this flow.

### Admin login password vs. `ADMIN_TOKEN` - deliberately two different secrets

- `ADMIN_TOKEN` is the pre-existing backend bearer token (`app.auth.require_admin_token`),
  completely unchanged by this task. It now lives **server-side only** - Railway (`api` service)
  and Vercel (server-only, Production scope, Sensitive - see section 2) - and is injected into
  every outbound `/admin/*` backend request by `src/lib/adminProxy.ts`. The browser never sees it.
- The admin login password is a **separate** credential, known only to the human operator and
  never derived from or comparable to `ADMIN_TOKEN`. Its Argon2id hash
  (`ADMIN_LOGIN_PASSWORD_HASH`) is the only form of it that ever touches disk or an environment
  variable - see `app.core.admin_password` and the provisioning procedure below.

### Environment variables (names only - see each service's dashboard for current values)

**Railway `api` service:**
- `ADMIN_LOGIN_ENABLED` - defaults to `false`; the login endpoint also independently requires
  both of the next two variables to be set regardless of this flag.
- `ADMIN_LOGIN_EMAIL`
- `ADMIN_LOGIN_PASSWORD_HASH` - a standard encoded Argon2id hash string, never the plaintext.
- `ADMIN_LOGIN_MAX_ATTEMPTS` (default `5`), `ADMIN_LOGIN_WINDOW_SECONDS` (default `900`),
  `ADMIN_LOGIN_LOCKOUT_SECONDS` (default `1800`) - throttle policy, optional overrides.
- `ADMIN_TOKEN` - pre-existing, unchanged.
- `REDIS_URL` - pre-existing, now also backs the login throttle (`app.core.admin_login_throttle`,
  deliberately separate from `app.core.rate_limit`'s in-memory limiter).

**Vercel (web) - server-only, no `NEXT_PUBLIC_` prefix on any of these:**
- `ADMIN_TOKEN` - new as of this task (section 2's table).
- `API_INTERNAL_URL`, `AUTH_SECRET` - pre-existing, unchanged; also used by the admin Credentials
  provider (`src/lib/auth.ts`).

### Rate-limit / lockout behaviour

Two independent Redis-backed counters per attempt (`app.core.admin_login_throttle`): the
normalized submitted email, and the caller's IP where available. Either one reaching
`ADMIN_LOGIN_MAX_ATTEMPTS` failures within `ADMIN_LOGIN_WINDOW_SECONDS` locks that counter for
`ADMIN_LOGIN_LOCKOUT_SECONDS`. A successful login clears only the account-level counter (never the
IP one - see the function's own docstring for why). Every failure path - wrong password, unknown
email, throttled, disabled, Redis unavailable - returns one of exactly two generic response shapes;
none of them reveal which case applies.

### Session duration

4 hours, enforced as a `roleExpiresAt` claim inside the JWT itself (`ADMIN_SESSION_MAX_AGE_MS` in
`src/lib/auth.ts`) rather than via Auth.js's global `session.maxAge` - kept independent of whatever
session lifetime is eventually appropriate for collector Google sign-in.

### Provisioning the admin credential

Never run interactively through an AI coding agent's tool output. See
`services/api/scripts/generate_admin_password_hash.py`'s own docstring for the full procedure; the
short version:

```
cd services/api
python3 scripts/generate_admin_password_hash.py
```

Prompts for email + password (hidden input, min 16 chars), hashes it with Argon2id, and writes only
the email and hash to Railway (`staging`/`optcg-price-tracker`) - refuses to run against anything
with "prod" in the environment name. Enables `ADMIN_LOGIN_ENABLED` last, only after both values are
confirmed present. The plaintext password is never written anywhere; store it in a password
manager.

### `ADMIN_TOKEN` rotation status

**Rotated, 2026-07-27.** The prior client-side flow (`AdminAuthGate`, localStorage `admin_token`)
meant a tester's browser could have held the raw backend `ADMIN_TOKEN` value, so it was treated as
potentially exposed. A new value was generated with `openssl rand -hex 32` inside a single
non-interactive shell invocation, held only in an unprinted shell variable, and piped directly via
stdin to `railway variable set ADMIN_TOKEN --stdin` (Railway staging `api`) and
`vercel env add ADMIN_TOKEN production --sensitive --force` (Vercel) before being unset - never
echoed, logged, or written to a file. Both services were redeployed afterward and confirmed
healthy. The old value was fully overwritten (not dual-lived), so it stopped authenticating the
moment the new one was set - not independently re-tested against the literal old string, which was
never known to begin with.

### Rollback procedure

Setting `ADMIN_LOGIN_ENABLED=false` on Railway immediately disables new logins (existing sessions
remain valid until their 4h expiry) without touching any code. To remove the mechanism entirely:
revert the commit(s) for this task, then remove `ADMIN_LOGIN_*` variables from Railway and
`ADMIN_TOKEN` from Vercel. The backend's `require_admin_token` dependency and direct
`X-Admin-Token` curl-based access (`docs/operations.md`) are unaffected either way.

### Migration path to Google OAuth

Once Google OAuth has real staging credentials and an admin-email allowlist is implemented:
1. Add the allowlist check (e.g. a `role` derived from `token.email` matching a configured list)
   to `src/lib/auth.ts`'s `jwt`/`session` callbacks, replacing the Credentials-provider branch.
2. Remove the admin Credentials provider, `/admin/login`, `POST /auth/admin/verify`,
   `app.core.admin_login_throttle`, `app.core.admin_password`, and all `ADMIN_LOGIN_*` variables.
3. `src/lib/adminSession.ts`/`src/lib/adminProxy.ts` (the `role === "admin"` check itself) do not
   need to change - they already only care about the session's `role` claim, not how it got there.
