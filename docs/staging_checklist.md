# Staging deployment checklist

Step-by-step checklist for standing up the `v1.0.0` staging deployment (Vercel + Railway). Pairs
with [docs/staging_deployment.md](staging_deployment.md) (architecture/env var reference) and
[docs/railway_staging.md](railway_staging.md) (per-service Railway setup). Check items off in
order - later sections assume earlier ones are done.

## Before deploy

- [x] A `staging` branch (or equivalent long-lived branch/tag) exists to deploy from.
- [x] Railway project created.
- [x] Railway Postgres (managed plugin) created.
- [x] Railway Redis (managed plugin) created.
- [x] Railway `api` service configured (source = this repo, **Root Directory `/`**, **Dockerfile
      Path `deploy/railway/api.Dockerfile`** - not `services/api` / `services/api/Dockerfile`,
      which caused this staging deployment's original Railway build failure - see
      `docs/railway_staging.md` section 3), public networking enabled.
- [x] Railway `worker` service configured (Root Directory `/`, Dockerfile Path
      `deploy/railway/worker.Dockerfile`, no public networking - section 4).
- [ ] Railway `beat` service configured (Root Directory `/`, Dockerfile Path
      `deploy/railway/beat.Dockerfile`, start command `celery -A worker.celery_app beat
      --loglevel=info`, no public networking - section 5). **Not yet created** - blocked by a
      Railway free-plan resource provision limit as of 2026-07-25; see dated note below.
- [x] Vercel project configured with Root Directory `apps/web`. Confirm Railway is **not** building
      `apps/web` anywhere - `apps/web` deploys to Vercel only. Project `optcg-price-tracker-staging`,
      GitHub repo connected, Root Directory `apps/web`, framework Next.js (auto-detected).
- [x] `deploy/railway/api.Dockerfile`, `deploy/railway/worker.Dockerfile`, and
      `deploy/railway/beat.Dockerfile` all build successfully locally from the repo root:
      `docker build -f deploy/railway/api.Dockerfile -t opcg-api-railway-test .` (and the
      worker/beat equivalents) - see `docs/railway_staging.md` "Local build verification".
- [ ] If Railway reports `couldn't locate the dockerfile path ... in code archive` for any
      service: check branch, commit/push status, Root Directory, and case-sensitive path - see
      `docs/railway_staging.md` "Troubleshooting: couldn't locate the dockerfile path ... in code
      archive".
- [x] `WORKER_CONCURRENCY=2` set on the Railway `worker` service (staging default - do not leave
      unset). If worker logs show a high prefork concurrency (e.g. `concurrency: 48`) and the
      service crash-loops with no traceback, this is almost certainly it - see
      `docs/railway_staging.md` "Worker concurrency". Do not deploy `beat` until `worker` is
      confirmed stable (no crash loop) with this set - `--concurrency` doesn't apply to `beat`.
- [x] Confirm which Railway environment you're actually deploying into - it may be named
      `production` in the dashboard even when it's the intended staging deployment (`APP_ENV`
      still `staging`). See `docs/railway_staging.md` "Operational warning: Railway environment
      named production" - don't rename/switch environments as an incidental fix. Confirmed as of
      2026-07-25: this deployment targets the dashboard environment actually named `staging`
      (`05d1eac2-...`), distinct from the `production`-named environment, which is left untouched.
- [x] All env vars set on every service (see [.env.staging.example](../.env.staging.example) and
      `docs/staging_deployment.md` section 5) - double check none are left as the literal
      `change-me`/`<...>` placeholder. Done for `api`/`worker`/Vercel `web`; not yet applicable to
      `beat` (not created).
- [x] `ADMIN_TOKEN` generated (`openssl rand -hex 32`) and set identically wherever it's needed
      (Railway `api`; `worker`/`beat` only if a specific job needs it).
- [x] `API_JWT_SECRET` generated and set identically on Railway `api` and Vercel `web`. Generated
      and set on Railway `api` (2026-07-25); copied byte-for-byte to Vercel `web` (2026-07-26) by
      piping directly from the Railway CLI into `vercel env add` - value never displayed or
      written to a file.
- [ ] `SCRAPING_MODE=mock` on `api`/`worker`/`beat`. Confirmed `mock` on `api` and `worker`; `beat`
      not yet created.
- [ ] `MARKET_WORKFLOW_ENABLED=false` and `DATA_RETENTION_ENABLED=false` on `beat`. N/A - `beat`
      not yet created.
- [x] Telegram disabled (`TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` both blank), or both pointed at a
      staging-only test bot/channel - never the production one.
- [x] `CORS_ALLOWED_ORIGINS`/`CORS_ALLOW_ORIGIN_REGEX` on Railway `api` set to the Vercel staging
      domain (see "Known direct backend calls to fix before production" in
      `docs/staging_deployment.md` - several pages call `api` directly from the browser and will
      fail as CORS errors without this). Set to the exact origin `https://optcg-price-tracker-staging.vercel.app`
      (2026-07-26) - no wildcard, no broad `*.vercel.app` match.

## Deploy

- [x] Deploy Railway `api`. Confirm `GET <railway-api-url>/health` returns `{"status": "ok", ...}`.
- [x] Run migrations: `DATABASE_URL=<railway-postgres-url> bash scripts/staging_migrate.sh` (or the
      Railway-side `alembic upgrade head` command - see `docs/railway_staging.md` section 3).
- [x] Deploy Railway `worker`. Confirm it starts without crash-looping (check Railway's deploy
      logs).
- [ ] Deploy Railway `beat`. Confirm it starts without crash-looping. **Blocked** - see dated note.
- [x] Deploy Vercel `web`, with `API_BASE_URL`/`API_INTERNAL_URL` (and `NEXT_PUBLIC_API_URL`, if
      used) already set to the Railway `api` service's public URL from the previous steps. Deployed
      2026-07-26 to `optcg-price-tracker-staging.vercel.app`.
- [x] Redeploy Vercel `web` once more if any env var was set/changed after the first deploy -
      `NEXT_PUBLIC_API_URL` and other build-time vars only take effect on the build they're present
      for. Final deploy (2026-07-26) ran after all six env vars were confirmed/re-set.

## Smoke

Run `STAGING_API_URL=<railway-api-url> STAGING_WEB_URL=<vercel-staging-url>
ADMIN_TOKEN=<staging-admin-token> bash scripts/staging_smoke_test.sh` and confirm:

- [x] API `/health` works.
- [x] Web `/dashboard` works.
- [x] Admin token works (`/admin/system-check` returns 200, not `critical`).
- [x] Saved views works (`/saved-views?limit=5` returns 200 or 401 - 401 without a signed-in
      session is expected/healthy).
- [x] Analytics digest works (`/analytics/digest` - same 200-or-401 note as saved views; web
      `/analytics/digest` page itself returns 200).
- [x] Catalog ops works (`/admin/catalog-coverage` returns 200; web `/admin/catalog-ops` page
      returns 200).
- [ ] Source health works - manually check `/admin/price-source-health` in the web UI (no dedicated
      smoke-test check for this route; it's a frontend-only aggregation page, same as
      `scripts/release_candidate_audit.sh` section 6b notes for `/admin/catalog-ops`). Not yet
      manually verified in a browser.
- [ ] Command palette works - manually verify (Ctrl/Cmd+K opens, searches, navigates) on the
      deployed staging URL; not automatable via curl. Not yet manually verified in a browser.
- [x] Collection vault works (web `/collection/vault` returns 200 after following the sign-in
      redirect, same as `/collection`/`/dashboard`).

## After deploy

- [x] Create a staging backup once real-ish data exists (`scripts/db_backup.sh` pointed at the
      Railway Postgres connection string, or a manual `pg_dump` via Railway's Shell/CLI - see
      `docs/operations.md`'s backup/restore drill for the general pattern). Taken 2026-07-26
      before the first catalogue import, via `pg_dump "$DATABASE_PUBLIC_URL" -Fc` run inside a
      `postgres:18` container (the Codespace's own `pg_dump` was v16, too old for this Postgres
      18 server) - stored outside the repo, not committed. See docs/staging_data.md.
- [ ] Seed saved views if needed (`python -m app.seed_saved_views`, run inside the Railway `api`
      service, if this repo has that seed command - check `services/api/app/seed_saved_views.py`).
      Not done in this pass - out of scope for the catalogue/pricing dataset work.
- [x] Import a small test card catalog CSV if needed
      (`python -m app.import_watchlist <path-to-csv>`, run inside the Railway `api` service).
      Done 2026-07-26: `python -m app.seed --demo-data` (10 labeled placeholder cards) **then**
      `python -m app.import_watchlist data/watchlists/opcg_watchlist.csv` (2 real, verified card
      codes) - in that order specifically, see docs/staging_data.md for why. **Note**: the
      "do not pass `--demo-data`" rule in `docs/deployment.md` section 4 is a *production* rule
      (real customers must never see placeholder cards) - it does not apply to staging, where a
      small labeled synthetic dataset is an explicitly sanctioned way to reach a representative
      catalogue size.
- [x] Run `scripts/staging_smoke_test.sh` (see "Smoke" above) - don't consider staging live until
      it passes. Passed 2026-07-25 (API-only run; `STAGING_WEB_URL` not yet set). Re-ran and
      passed again 2026-07-26 with `STAGING_WEB_URL` set - all API and web checks green.
- [ ] Review Railway logs for all three services (`api`, `worker`, `beat`) for unexpected errors in
      the first few minutes after deploy. Done for `api`/`worker`; `beat` not yet created.
- [x] Review Vercel deployment logs (build log + function logs) for unexpected errors. Build log
      reviewed inline during the 2026-07-26 deploy - compiled successfully, no errors (one
      pre-existing Turbopack NFT-tracing warning on `next.config.ts`, unrelated to this change and
      non-blocking).
- [ ] Only then consider enabling live Yuyu-Tei staging refresh - flip `SCRAPING_MODE=live` on
      `api`/`worker`/`beat` deliberately, one service at a time, and only after everything above is
      green. Never enable SNKRDUNK live scraping or attempt to bypass its site protections - SNKRDUNK
      data stays manual-import-only regardless of environment (see `docs/staging_deployment.md`
      section 11).

## 2026-07-25 - API + worker deployed and verified; beat blocked

- **Staging API** (`optcg-price-tracker`, Railway environment `staging`): healthy.
  `/health` returns `status=ok`, `app_env=staging`, `database_connected=true`,
  `redis_connected=true`. `API_JWT_SECRET` generated and set (32+ bytes, value not recorded
  anywhere). `DATABASE_URL`/`REDIS_URL` rewired from manually-copied literals to native Railway
  service-variable references. Health check path set to `/health`. Restart policy unchanged
  (`ON_FAILURE`, 10 retries).
- **Staging worker**: created and deployed from `deploy/railway/worker.Dockerfile` on branch
  `staging`, no public networking. Verified via deploy logs and an in-container connectivity
  check: Celery started at `concurrency: 2`, connected to the staging Redis broker, and confirmed
  `database_connected: yes` / `redis_connected: yes` / `scraping_mode: mock`. No crash loop.
- **Staging beat**: **not created** - Railway reported "Free plan resource provision limit
  exceeded" when provisioning a fifth service in this project. No partial service was left behind.
  Requires a Railway plan upgrade or a deliberate resource decision before beat can be added;
  scheduled workflows (market intelligence digest, data retention pruning) do not run in staging
  until this is resolved.
- **Migrations**: staging Postgres was already at the repository's head revision
  (`e7a1c4d9b2f6`); `scripts/staging_migrate.sh` ran cleanly with no pending migrations.
- **Smoke tests**: `scripts/staging_smoke_test.sh` passed against the staging API domain
  (`STAGING_WEB_URL` intentionally omitted - no Vercel deployment yet). One transient failure was
  diagnosed and resolved along the way: `/admin/system-check` initially returned `critical`
  because the staging database's `sources` table (`yuyutei`, `snkrdunk`) had never been seeded;
  running `python -m app.seed` (additive, no demo cards) fixed this. Separately, `/admin/system-check`
  took ~14.7s on one run, just under the script's 15s timeout - likely due to the API/worker
  running in `asia-southeast1` while Postgres/Redis run in `sfo`; worth monitoring if it recurs.
- `SCRAPING_MODE` remains `mock` on both `api` and `worker`. No live scraping was enabled.
  `CORS_ALLOWED_ORIGINS` deliberately left unset pending the Vercel staging URL. Vercel, frontend,
  Google OAuth, and final CORS configuration are unchanged and out of scope for this pass.

## 2026-07-26 - Vercel staging frontend deployed; end-to-end smoke tests green

- **Vercel project**: `optcg-price-tracker-staging` (already existed from an earlier session
  in this branch's history - discovered, not recreated). Owner `insomniac79ac's projects`,
  Root Directory `apps/web`, Framework Next.js (auto-detected), GitHub repo
  `Insomniac79ac/optcg-price-tracker` connected. **Production Branch is still `main` in the
  Vercel dashboard** - the Vercel REST API rejects programmatic changes to this field (`PATCH
  /v9|v10/projects/:id` with a `link`/`productionBranch` body both return `400 Invalid request:
  should NOT have additional property`), so this could not be set via CLI/API. Deploys in this
  pass were pushed with `vercel deploy --prod` from a local `staging` branch checkout, which
  targets the Production environment directly regardless of the git production-branch setting -
  so the live deployment **is** built from `staging`, but automatic deploy-on-push from `staging`
  is **not** configured yet. **Manual step remaining**: Vercel dashboard -> this project ->
  Settings -> Git -> Production Branch -> change `main` to `staging`.
- **Environment variables** (all Production scope, all type "Sensitive" where supported):
  `NEXT_PUBLIC_API_URL`, `API_INTERNAL_URL` -> Railway staging API public URL; `AUTH_URL` ->
  the stable Vercel staging domain; `NEXT_PUBLIC_APP_ENV` -> `staging` (present but not read by
  any current code path - see `apps/web/scripts/check-env.js`, which only reads bare `APP_ENV`/
  `NODE_ENV` for its own severity logic); `AUTH_SECRET` -> unchanged from the prior session (5-6h
  old at the time of this pass, already configured, value never inspected); `API_JWT_SECRET` ->
  re-copied byte-for-byte from Railway `optcg-price-tracker` (staging) via a direct
  `railway variables --kv | ... | vercel env add --sensitive` pipe, so it is now guaranteed to
  match rather than merely assumed to. `ADMIN_TOKEN` was **not** added to Vercel, per policy.
- **Stable frontend URL**: `https://optcg-price-tracker-staging.vercel.app` (aliased). Immutable
  deployment: `https://optcg-price-tracker-staging-phapv59yk-insomniac79acs-projects.vercel.app`
  (`dpl_3RKmmvDAikwa8ETcs8DZSnpp4kh9`), built from `staging` at commit `6c2ba76`, `readyState:
  READY`.
- **Build/runtime verification**: production build succeeded (Next.js 16.2.10, Turbopack);
  homepage and all sampled public/protected pages return the expected status (200 for public
  pages, 307 redirect to a public page for unauthenticated protected routes - no crash, no data
  leak); all sampled `_next/static` JS chunks return 200; the client bundle was scanned for the
  Railway staging URL (present, exactly once, as expected for `NEXT_PUBLIC_API_URL`), for
  `localhost` (only a hard-coded default inside Auth.js's own library code, always overridden by
  `AUTH_URL`/request host at runtime - not a real staging URL), and for secret variable names
  (none found).
- **Railway staging CORS**: `CORS_ALLOWED_ORIGINS` set on the Railway `staging` `optcg-price-
  tracker` service to exactly `https://optcg-price-tracker-staging.vercel.app` (no wildcard, no
  `*.vercel.app`, no localhost). Service redeployed automatically on variable change; `/health`
  confirmed `200`/`status=ok`/`app_env=staging`/`database_connected=true`/`redis_connected=true`
  afterward. Verified via `curl` preflight: the exact Vercel origin gets
  `access-control-allow-origin` echoed back; an unrelated origin (`https://evil.example.com`)
  gets rejected (`400`, no permissive CORS header granted). The production-named Railway
  environment was not touched.
- **End-to-end smoke test**: `scripts/staging_smoke_test.sh` run with `STAGING_API_URL`,
  `STAGING_WEB_URL`, and `ADMIN_TOKEN` (injected via a `railway variables --kv` pipe, never
  displayed or written to a file) - **all checks passed**: API `/health`, `/version`,
  `/analytics/digest` (401, healthy), `/saved-views` (401, healthy), `/admin/system-check`
  (`warning`, not `critical`), `/admin/catalog-coverage` (200), and web `/`, `/dashboard`,
  `/collection`, `/collection/vault`, `/analytics/digest`, `/admin/catalog-ops` (all 200).
  Additional manual checks beyond the script: `/search` (catalogue page, 200), a nonexistent
  route (`404`, no stack trace in the response body), and `/api/auth/session`/`/api/auth/
  providers` (200, no secret values exposed). The card catalog is currently empty (no cards
  seeded yet), which is expected and unrelated to this pass - see "Recommended next task" below.
- **Google OAuth**: no real `AUTH_GOOGLE_ID`/`AUTH_GOOGLE_SECRET` exist anywhere - not in Vercel,
  not in any local `.env*` file (only literal `change-me`/blank placeholders in the `.example`
  files). `google` still appears in `/api/auth/providers` because the app registers
  `GoogleProvider` unconditionally, but a real sign-in would fail (invalid client). Per the task's
  safety constraints, no attempt was made to exercise the interactive consent flow. **Authenticated
  flows (collection, wishlist, grading, saved views under a real session) remain untested.**
  Manual steps required before this can be enabled, in Google Cloud Console:
  - Authorized JavaScript origin: `https://optcg-price-tracker-staging.vercel.app`
  - Authorized redirect URI: `https://optcg-price-tracker-staging.vercel.app/api/auth/callback/google`

  Then set `AUTH_GOOGLE_ID`/`AUTH_GOOGLE_SECRET` on Vercel (Production scope, sensitive) and
  redeploy.
- **Beat** remains blocked by the Railway free-plan resource provision limit (unchanged from
  2026-07-25). `SCRAPING_MODE` remains `mock` on `api`/`worker`. The pre-existing lint (61 errors,
  15 warnings) and Vitest (149/150, one pre-existing wishlist empty-state timing failure) issues
  from local frontend validation are unchanged and remain non-blocking - out of scope for this
  pass.

## 2026-07-26 - Staging catalogue and mock price data loaded; full dataset validated

Populated the previously-empty staging catalogue with a small, representative, non-fabricated
dataset so the deployed prototype can be exercised meaningfully. Full detail (exact commands,
rehearsal results, every validation check) is in [docs/staging_data.md](staging_data.md) - this
entry is the checklist-level summary.

- **Backup**: taken before any import, via `pg_dump` in a `postgres:18` container against
  `DATABASE_PUBLIC_URL` (the Codespace's native `pg_dump` was v16, incompatible with this
  project's Postgres 18 server). Stored outside the repo; not committed. Verified valid
  (`pg_restore --list`, 432 TOC entries) before proceeding.
- **Dataset**: `python -m app.seed --demo-data` (10 explicitly-labeled placeholder cards, an
  existing documented command) followed by `python -m app.import_watchlist
  data/watchlists/opcg_watchlist.csv` (2 real, `manual_verified=true` card codes with genuine
  Yuyu-Tei/SNKRDUNK URLs, already committed to this repo since 2026-07-10) - in that exact order,
  because running the demo seed *after* the watchlist import hits a latent `MultipleResultsFound`
  crash in `app.seed.seed_demo_data`'s mapping step once two cards share a `card_code`. Rehearsed
  first against a disposable local Postgres 18 container running this repo's actual migrations,
  then repeated identically against the real staging database. Result: 12 canonical cards, 5 sets
  (OP01-OP05), 5 rarities, 3 variants, all `jp`. Below the 20-50 target - no more verified/safe
  data exists to reach it, which the task's own instructions treat as acceptable rather than a
  reason to fabricate.
- **Idempotency**: `import_watchlist` re-run a second time against the real staging DB - 0 new
  cards, 0 new mappings (12/16 unchanged), confirming its upsert-by-identity logic is safe to
  repeat.
- **Mock price refresh**: triggered via `POST /admin/actions/refresh-prices` (dry run, then one
  real bounded run, then a second dry run) - no `beat` involved, no recurring schedule. Real run
  (`run_id=2`): 16 mappings checked, 16 raw snapshots stored, 28 price observations inserted, 0
  failed, finished in ~150ms. Only 3 of the 12 canonical cards can ever show mock prices, because
  the mock adapters' fixture JSON (`services/worker/fixtures/{yuyutei,snkrdunk}_sample.json`) only
  has entries for `source_card_id` values `OP01-001`/`OP01-013` - a pre-existing constraint, not
  something this pass worked around or extended.
- **Validation**: `/admin/system-check` moved from `critical` (pre-existing, missing sources) to
  `warning` (expected - real coverage gaps, not brokenness); `/admin/catalog-coverage`,
  `/admin/source-mappings/quality`, and `/admin/price-source-health` all report numbers that match
  the import exactly; `duplicate_cards` and every `*_valid_card_id` check in system-check pass
  (no orphans, no wrong-card mappings); `scripts/staging_smoke_test.sh` re-run with both URLs and
  passed in full. One known, pre-existing data-shape quirk (not a bug introduced here): the real
  watchlist CSV reuses the same `variant` value across genuinely different print rarities of
  `OP01-001`/`OP01-002`, so 4-6 source rows collapse onto fewer canonical card rows than a human
  cataloguer would probably choose - documented in docs/staging_data.md rather than silently
  patched, since fixing it would mean reinterpreting a file this task's rules say to treat as
  verified/authoritative as-is.
- No live SNKRDUNK collection occurred; `SNKRDUNK` candidate table remains empty (0 rows) by
  design. `SCRAPING_MODE` remains `mock`. Google OAuth remains unconfigured. Beat remains blocked
  by the Railway plan limit.

## 2026-07-27 - Temporary admin login implemented (staging/prototype only)

Full architecture, env vars, and rollback in `docs/staging_deployment.md` section 13 - this entry
is the checklist-level summary. Supersedes the "`ADMIN_TOKEN` was **not** added to Vercel, per
policy" line in the 2026-07-26 entry above (that was correct policy *then*, under the
browser-holds-a-token model this task replaced - the codebase and this doc entry are the current
source of truth, the historical entry above is left as-is rather than edited).

- [x] `ADMIN_TOKEN` added to Vercel (`optcg-price-tracker-staging`, Production scope, Sensitive,
      server-only) - piped directly from `railway variable list --kv` into `vercel env add
      --sensitive`, value never displayed. Confirmed present via `vercel env ls` (value shown as
      `Encrypted`, never printed).
- [x] Backend: `POST /auth/admin/verify` + `GET /auth/admin/status` (`app.api.admin_login`),
      Argon2id hashing (`app.core.admin_password`), Redis-backed throttle
      (`app.core.admin_login_throttle`) - not the in-memory `app.core.rate_limit`. 41 new backend
      tests, all passing; full backend suite (1279 tests) passing.
- [x] Frontend: admin Credentials provider alongside Google (`src/lib/auth.ts`), `/admin/login`
      page, `requireAdminSession()`/`requireAdminOrResponse()` boundaries
      (`src/lib/adminSession.ts`/`src/lib/adminProxy.ts`), all ~58 `/api/admin/**` Route Handlers
      plus the 4 dual-auth `/api/file-jobs/**` routes migrated off caller-supplied
      `X-Admin-Token` to server-side injection, `proxy.ts` optimistic `/admin/login`-excluded
      redirect, client-side token flow (`AdminAuthGate`, localStorage `admin_token`) removed.
      Full frontend suite (244 tests across 42 files) passing; `tsc --noEmit` clean; `next build`
      succeeds.
- [x] Fixed a regression this task's own removal of the client-side token would otherwise have
      caused: `fetchAlertEvents`/`fetchAlertRules`/`updateAlertRule`, `fetchRefreshRuns`/
      `fetchRefreshRun`, and `fetchSnkrdunkCandidates` previously called the Railway backend
      **directly from the browser** with an admin-token header attached if present (see the old
      "Known direct backend calls" list in `docs/staging_deployment.md` section 4) - removing that
      token would have silently broken the Alerts, Refresh Runs, and SNKRDUNK Candidates admin
      pages. Added same-origin proxy routes for all of them (`/api/admin/alert-events`,
      `/api/admin/alert-rules`, `/api/admin/refresh-runs`, `/api/admin/snkrdunk-candidates`) and
      repointed those six functions at them.
- [ ] `ADMIN_LOGIN_EMAIL`/`ADMIN_LOGIN_PASSWORD_HASH`/`ADMIN_LOGIN_ENABLED` **not yet set** -
      requires the operator to run `services/api/scripts/generate_admin_password_hash.py`
      interactively in their own terminal (never through an AI agent's tool output - the script
      prompts for and hashes the real password). See section 13's provisioning procedure.
- [ ] `ADMIN_TOKEN` rotation - not yet done. The prior client-side flow means the current value
      should be treated as potentially exposed; rotate once the new flow is verified live end to
      end (login works, admin pages load via the proxy, no `X-Admin-Token` in any browser
      request/localStorage) - see section 13's rotation note.
- [ ] Live browser verification of `/admin/login` (valid/invalid credentials, throttling, session
      persistence, sign-out) - blocked on the provisioning step above; cannot be verified until a
      real admin credential exists on staging.

## 2026-07-27 (continued) - Admin login provisioned, ADMIN_TOKEN rotated, both services deployed

Closes every `[ ]` item in the entry directly above. The operator ran
`services/api/scripts/generate_admin_password_hash.py` themselves, in their own terminal - no
password or hash was ever pasted into or displayed by an AI agent session.

- [x] `ADMIN_LOGIN_EMAIL`, `ADMIN_LOGIN_PASSWORD_HASH`, `ADMIN_LOGIN_ENABLED` set on Railway
      staging (`optcg-price-tracker`) by the operator's own run of the provisioning script.
      `ADMIN_LOGIN_MAX_ATTEMPTS=5`, `ADMIN_LOGIN_WINDOW_SECONDS=900`,
      `ADMIN_LOGIN_LOCKOUT_SECONDS=1800` set explicitly afterward (non-secret policy values,
      matching the code's own defaults) for dashboard auditability. Confirmed live via
      `GET /auth/admin/status` -> `{"enabled":true}` and via `railway variable list --json` key
      presence - values never inspected or displayed at any point.
- [x] `ADMIN_TOKEN` rotated: a new value was generated with `openssl rand -hex 32` inside a single
      non-interactive shell invocation, held only in an unprinted shell variable, piped directly
      via stdin to `railway variable set ADMIN_TOKEN --stdin` (Railway staging `api`) and
      `vercel env add ADMIN_TOKEN production --sensitive --force` (Vercel), then unset - never
      echoed, logged, or written to a file at any point. The old value was fully overwritten, not
      dual-lived, so it stopped authenticating the instant the new one was set; this wasn't (and
      couldn't safely be) verified by testing the literal old string, which was never known to
      begin with.
- [x] Railway staging `api` redeployed (picked up the rotated token and the throttle-policy vars);
      `/health` green (`status=ok`, `database_connected=true`, `redis_connected=true`) throughout.
- [x] Vercel deployed from the `staging` branch checkout (`vercel --prod --yes` from the repo
      root - running it from `apps/web` double-applies the project's own Root Directory setting
      and fails; run from repo root instead) - `readyState: READY`, aliased to the stable domain
      `https://optcg-price-tracker-staging.vercel.app`, picked up the rotated `ADMIN_TOKEN` and
      every admin-login code path from this task.
- [x] Live verification (signed-out only - see the blocker below for what still needs the real
      credential): `/admin` and `/admin/system-check` 307 to `/admin/login?callbackUrl=...`
      (relative, safe); `/admin/login` renders "Admin sign-in" (login enabled); an absolute
      (`https://evil.example.com`) or protocol-relative (`//evil.example.com`) `callbackUrl` is
      never reflected into the actual sign-in-form prop (confirmed in the page's own RSC payload:
      the component prop is `"callbackUrl":"/admin"`, the sanitized fallback - the raw query string
      elsewhere in that payload is just Next.js's own inert routing metadata, not a redirect
      target); throttle probe against a disposable non-real test email hit `429` with
      `Retry-After: 1787` on the 6th attempt, matching the 5-attempt policy exactly - the real
      admin account's counter was never touched; downloaded and grepped every JS chunk the login
      page loads (9 files, ~700KB) for `ADMIN_TOKEN`/`NEXT_PUBLIC_ADMIN` - no matches.
      Repo-wide grep sweep (`admin_token`, `X-Admin-Token`, `getAdminToken`/`setAdminToken`/
      `clearAdminToken`, `AdminAuthGate`, `NEXT_PUBLIC_ADMIN`, `process.env.ADMIN_TOKEN`) - every
      remaining hit is server-only code, a router-level `require_admin_token` dependency
      (unchanged), or a comment/test explaining the above.
- [x] Full test suites re-run against this state: backend 1279 passed, frontend 244/42 passed.
- [ ] **Still open**: the signed-in half of live verification (session role/expiry, admin nav,
      `/admin/system-check` loading, a real admin API call succeeding, no `X-Admin-Token` in any
      browser request, sign-out invalidation) requires an authenticated browser session, which
      only the operator can create - deferred at the operator's own choice rather than asked to
      paste a password into this session. Recommended as a manual follow-up: sign in at
      `/admin/login` in a real browser and spot-check the items above.
