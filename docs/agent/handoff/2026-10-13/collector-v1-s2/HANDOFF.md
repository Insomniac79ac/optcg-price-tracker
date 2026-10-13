# Collector v1 S2 handoff: info pages, analytics and error tracking (2026-10-13)

Plan: `docs/agent/plans/collector-v1/PLAN.md` §F2, §G, §H row S2 and rule A5 (on
`plan/collector-v1`, d5b292f). Target: staging only. Production was not accessed.
Level: AMBER by path floor (`deploy/railway/api.Dockerfile`); no data, no migration.
No collector release.

## Plain summary

Card Pirate on staging now has About and "How we price cards" pages, draft Privacy and
Terms pages (marked as drafts, hidden from search) and footer links to all four.
Vercel Web Analytics is collecting page views and Sentry error tracking is live on the
website and the API. Nothing about prices, Market Value or the Index changed, and no
collector was touched (0 collector deployments).

## Status at handoff (2026-10-13 23:10Z)

| Item | State |
|---|---|
| PR | **#114 merged** 2026-10-13T22:12:57Z, merge `eaf9de78eccb8c5c47b2097aa2436e30e9d1a2b3`, after a rebase onto `66cc7f2` (fonts #117 and capacity session 12 #118 both merged first) |
| Delivery | CI run **38474994432**, all jobs green, receipt verified 22:25:33Z (§Delivery receipt) |
| Collector deployments | **0** (Railway records after the merge and after the owner's API redeploy) |
| Vercel variables | `NEXT_PUBLIC_SENTRY_DSN`, `NEXT_PUBLIC_VERCEL_WEB_ANALYTICS` present on Production (names only) |
| Railway API | `SENTRY_DSN` present (names only), added by the owner; API redeployed 22:56:24Z at `eaf9de7` |
| Analytics | **Working:** script and page-view beacon on every page tested (§Analytics) |
| Sentry API | Test error raised once 23:03:37Z; SDK active. Event content in Sentry: **owner to confirm** (no Sentry access in this session) |
| Sentry web | **Owner to trigger** after admin sign-in (§Sentry) |

Commits after the rebase: `d2b0677` pages and footer, `ddfeab3` web analytics and
Sentry, `40f0002` API Sentry, `49323c6` manifest (diff SHA-256
`2733f7ee…`, recovery commit `66cc7f2`).

## What was built

- **Pages:**
  - `/about` and `/methodology` are indexable and in the sitemap.
  - `/privacy` and `/terms` are noindex with a "Draft – under review" banner. Their operator is "Card Pirate", with placeholders `[CONTACT EMAIL]` and `[GOVERNING LAW]`. Not in the sitemap and not disallowed in robots, so crawlers can read the noindex.
  - Methodology states only rules from `docs/market_value.md`, `docs/market_index.md`, `INVARIANTS.md` and `docs/collector_accounts.md`, and a source comment in the page says so.
  - The Privacy draft discloses Vercel hosting and Web Analytics, Sentry, Cloudflare R2, Railway and Google sign-in (coming).
- **Analytics:** `apps/web/src/lib/analytics.ts`.
  - Only the nine §F2 events are allowed.
  - Properties are allowlisted to `page_type` and `release_code`.
  - Page views are sent as paths only, never `/admin` or `/api/`.
  - Mounted only when `NEXT_PUBLIC_VERCEL_WEB_ANALYTICS=1`.
  - Wired now: `sign_in_started`. S5-S8 wire the rest at their call sites through `trackEvent()`, which is the only allowed importer of `track()`, enforced by a test.
- **Sentry web:** `apps/web/src/lib/sentry.ts`, `instrumentation.ts`, `instrumentation-client.ts`, `lib/reportError.ts`.
  - `sendDefaultPii` is false, with no tracing, no replay and no session pings.
  - `beforeSend` scrubs Authorization, cookie and admin headers, cookies, bodies, query strings and the user.
  - Environment is `NEXT_PUBLIC_APP_ENV` (set to staging on Vercel); release is the build SHA.
  - Without `NEXT_PUBLIC_SENTRY_DSN` no SDK chunk is requested and CSP is unchanged. With it, `connect-src` gains only the ingest origin.
- **Sentry API:** `services/api/app/error_tracking.py`.
  - `sentry-sdk==2.70.0` is in `requirements-observability.txt`, installed only by `deploy/railway/api.Dockerfile`.
  - It is a no-op without `SENTRY_DSN`.
  - No locals, bodies, tracing or sessions; the same scrubbing as web.
  - Release is `RAILWAY_GIT_COMMIT_SHA`, falling back to `GIT_COMMIT`. **UNVERIFIED:** Railway documents that variable for GitHub deploys, but it is not in the service variable list and `/version` reports `git_commit: unknown`. Confirm on the first API test event; if release is empty, set `SENTRY_ENVIRONMENT`/a release source in S5.
- **Deliberate test errors:** admin only, read nothing and write nothing.
  - Web: `/api/admin/observability/sentry-test?target=web`.
  - API: `/api/admin/observability/sentry-test?target=api`, which proxies to `GET /admin/observability/sentry-test`.

## Owner steps (no secrets in chat) — done by the owner 2026-10-13

1. **Vercel Web Analytics:** vercel.com, project `optcg-price-tracker-staging`, open **Analytics**, press **Enable**.
2. **Sentry DSNs:** sentry.io, **Settings**, **Projects**, then for each of `card-pirate-web` and `card-pirate-api`, open **Client Keys (DSN)** and copy the DSN. While there, also turn on **Security & Privacy**, **Prevent Storing of IP Addresses** in both projects.
3. **Vercel variables:** project `optcg-price-tracker-staging`, **Settings**, **Environment Variables**, environment **Production** (this project's Production is staging):
   - `NEXT_PUBLIC_SENTRY_DSN` = the `card-pirate-web` DSN
   - `NEXT_PUBLIC_VERCEL_WEB_ANALYTICS` = `1`
4. **Railway variable:** project Card Pirate, environment **staging**, service **optcg-price-tracker** (the API only; not worker, beat or any collector), **Variables**:
   - `SENTRY_DSN` = the `card-pirate-api` DSN
5. Tell the session. Both `NEXT_PUBLIC_*` values are baked in at build time, so the web needs a new deployment after step 3. The #114 merge build picks them up if they are set before it merges. Setting the Railway variable redeploys the API.

Verification once set: sign in as admin and open both test URLs. Then check Sentry
**Issues** for `Deliberate Sentry test error (web)` and `(api)` tagged
`environment: staging` with a release SHA. Check Vercel **Analytics** for a page view.

## Vendor facts (checked 2026-10-13)

- Vercel Web Analytics on Hobby: 50,000 events/month, free, shared across the
  account. Collection pauses after the cap (3-day grace). **Custom events are not
  available on Hobby** (Pro only, 2 properties each). Page views work now; the §F2
  custom events only start being collected after the pre-revenue Pro decision (RED,
  owner). The code stays within Pro's 2-property limit.
- Sentry Developer: free, 1 user, 5k errors/month, 30-day retention.

## Tests and checks

| Check | Result |
|---|---|
| Web vitest | 130 files, 1682 passed (`evidence/web-vitest-final.txt`) |
| Node script tests | 21/21 |
| `tsc` | clean except 4 pre-existing `AppShell.test.tsx` errors (same on base) |
| Production build | passes without DSN and with a fake DSN + analytics flag |
| API full suite, Postgres 18 | `a3f6380`: **5169 passed, 41 skipped, 0 failed**. Base `b3862e6`: 5150 passed, 41 skipped. **Identical skip set** (`evidence/skip-comparison-a3f6380-vs-b3862e6.json`) |
| Collector import graph | snkrdunk, yuyutei: 0 changed runtime inputs (`evidence/import-graph-check-a3f6380.json`) |
| Staging policy | AMBER, eligible, 0 errors |
| End-to-end, real SDKs (local) | API test error captured with staging + SHA, no secret, cookie or query (`evidence/api-sentry-e2e-local.txt`). Browser error sent once, no query leak, no session (`evidence/browser-error-capture-local.txt`). No-op without DSN/flag (`evidence/network-probe-disabled-local.json`) |

**Re-run after the rebase onto `66cc7f2` (head `49323c6`, 2026-10-13 21:41-22:02Z):**

| Check | Result |
|---|---|
| Web vitest | 130 files, **1682 passed** (`evidence/web-vitest-49323c6.txt`) |
| API full suite, Postgres 18 | **5181 passed, 41 skipped, 0 failed** (`evidence/full-api-suite-49323c6-pg18.txt`). +12 passes are the PR #115/#116 tests now on the base. Skip set identical to `a3f6380` (only difference: the earlier log masked the local password) |
| Collector import graph | snkrdunk, yuyutei: **0** changed runtime inputs vs `a504e47`; no models/settings/requirements change (`evidence/import-graph-check-49323c6.json`) |
| Staging policy | AMBER, eligible, 0 errors; manifest rebuilt with the new diff hash and recovery commit `66cc7f2` |

Two local first-run issues were caught by comparing totals:

- `from tests.conftest import ...` in a new test re-imported conftest and broke DB overrides for later tests. Fixed.
- A random local Postgres password skipped 27 tests that hardcode `opcg:opcg@localhost:5544`. Re-run with that local password gives the 41-skip baseline. Same follow-up as S3 (shared `TEST_POSTGRES_URL` helper).

## Visual (ATLAS)

- Contract: `docs/ui/evidence/2026-10-13-collector-v1-s2-info-pages/CONTRACT.md`.
- Before (staging): `evidence/screens/before_*`.
- After (local production build):
  - first build: `evidence/screens-local/`;
  - revision: `evidence/screens-local-r1/`.
- Fresh reviewer, round 0: FAIL (Originality 3).
- Revision 1 added the homepage's Atlas primitives (chart-grid header, route-line divider), gold waypoint numbers, a desktop contents rail on the footer's container edge, and a collapsible mobile contents list with back links. A new reviewer then graded it **PASS, 4/4/4/4/4**.
- Non-blocking reviewer notes for a later tranche:
  - wide gap between column and rail at 1440;
  - mobile Methodology length;
  - the footer band tint;
  - the draft banner is the loudest element.
- Staging screenshots after merge: `evidence/screens-staging-after/` (desktop 1440 and mobile 390, full page and footer, 7 pages; `after.json`).

## PR #113 receipt (carried from S3, landed with this handoff)

Committed under `docs/agent/handoff/2026-10-13/collector-v1-s3/evidence/`:
`pr113-delivery/` and `deploy-records-after-pr113.json`.

| Item | Value |
|---|---|
| Merge commit | `b3862e6aa82acb0c0d565a75efbbb74fea02fd42`, merged 2026-10-13T11:08:22Z |
| CI run | `38386604468` |
| Artifacts | `staging-delivery-b3862e6…` 11808980140, `staging-credential-probe-6c2e166…` 11807090882, both expire 2027-01-11T10:54:57Z |
| Receipt | verified 2026-10-13T11:20:20Z, delivery scope `skip` (docs only), API expectation `skip` at `5d86629`, `production_accessed: false` |
| Collector deployments | **0** since 10:54Z (Railway records, observed 11:21:13Z) |

## Environment notes

- Disk was at 3.2 GB free at start. 9 dangling Docker volumes from earlier
  disposable test Postgres runs (1.84 GB, attached to no container) and the npm cache
  were removed to reach 5.2 GB. Named test containers were left alone.
- Worktree: `/workspaces/cp-cv1-s2`. The baseline-suite worktree was removed after use.

## Delivery receipt (PR #114)

`evidence/pr114-delivery/` (downloaded per the STAGING_DELIVERY checklist):

| Item | Value |
|---|---|
| Merge commit | `eaf9de78eccb8c5c47b2097aa2436e30e9d1a2b3`, 2026-10-13T22:12:57Z (native auto-merge by the delivery job) |
| CI run | `38474994432`, conclusion success, every job green |
| Artifacts | `staging-delivery-eaf9de7…` 11855810176, `staging-credential-probe-49323c6…` 11853682378; both expire 2027-01-11T22:02:30Z |
| Receipt | verified 2026-10-13T22:25:33Z; scope `full` (non-documentation change); frontend `dpl_2ZL3pgU8WaRCmPKvvuTCWsPY8Ekp` READY at `eaf9de7`; API expectation `build` at `eaf9de7`; migration revision `3b7d9c1a5e20` (unchanged); sale invariant 227 histories, 0 sale index inputs, 0 gap receipts; `production_accessed: false` |
| Delivery state | 2 blockers (`freshness-deadline-deficit`, `snkrdunk-identity-quarantine` 23). **No `deployment-provenance-divergence` after this web + API merge:** first real confirmation of the capacity session 12 fix (PR #115), session 13 item 4 |
| Railway records after merge (`evidence/deploy-records-after-pr114.json`) | API `optcg-price-tracker` SUCCESS and `market-index-snapshot` SUCCESS at `eaf9de7`; beat and worker SKIPPED; **0 collector deployments** |
| After the owner's `SENTRY_DSN` change (`evidence/deploy-records-after-sentry-dsn.json`, since 22:14Z) | API SUCCESS 22:56:24Z at `eaf9de7`; **0 collector deployments** |

## Staging verification (stable alias `optcg-price-tracker-staging.vercel.app`)

`evidence/screens-staging-after/after.json`, `evidence/staging-after-pages.json`:

| Page | Status | Robots | Draft banner | Footer links |
|---|---|---|---|---|
| `/`, `/cards`, `/analytics` | 200 | index, follow | none | 4 |
| `/about`, `/methodology` | 200 | index, follow | none | 4 |
| `/privacy`, `/terms` | 200 | **noindex, follow** | **"Draft – under review"** | 4 |

Desktop and mobile both; no horizontal overflow, no broken images, no console errors.

## Analytics

**Working.** `evidence/analytics-pageview-probe-staging.json` (tool `tools/analytics_view_probe.py`,
a normal non-automation browser, 2026-10-13 ~23:01Z):

- `/`, `/about`, `/methodology`, `/privacy`, `/terms`, `/cards`: each loads
  `/393b56be60fdc62b/script.js` (200) and sends one `POST /393b56be60fdc62b/view` (200).
- The probe added `?utm_probe=s2&email=x@example.com`; the beacon carried the path only
  (`"o":"…/about"`, `"dp":"/about"`). The query string never left the browser.
- An automated browser (`navigator.webdriver = true`) loads the script and queues the
  page view but sends no beacon (`evidence/analytics-deep-probe-webdriver.json`); Vercel
  ignores bots by design.
- The page views appearing in the Vercel **Analytics** dashboard is for the owner to
  confirm (no dashboard access from this session; the ingest endpoint returned 200).

**Correction to the first report (root cause).** At 22:28Z this session reported "no page
views, the value is probably not exactly `1`". **That was wrong.** Evidence:

- Vercel Web Analytics now serves its script from a project-specific first-party path
  (`/<id>/script.js`, `/<id>/view`), not `/_vercel/insights/*`. `tools/network_probe.py`
  only matched `/_vercel/insights`, so it could not see the requests; its local run had
  matched because local builds still use the old path.
- The pre-change deployment `dpl_2ZL3…` (fetched directly with `vercel curl --deployment`)
  serves the same content-hashed chunk `1axpxilvau68p.js` with
  `analyticsEnabled(){return!0}`. The flag was already on at the merge build.
- The owner's value edit (22:48:32Z) and the clean rebuild `dpl_8MBdB8C883ESoHd9EYx49CBD8udC`
  (source `redeploy` of `dpl_2ZL3…`, "Skipping build cache", 22:49:09Z, now on the alias)
  were therefore harmless but not needed. No further website redeploy was made.
- Follow-up: `tools/network_probe.py` should match `/script.js` + `/view` on any path, or
  read `window.va`.

## Sentry

- **API.** `SENTRY_DSN` present by name; the API redeployed (SUCCESS 22:56:24Z, `eaf9de7`),
  0 collector deployments. `GET /admin/observability/sentry-test` called **once** at
  2026-10-13T23:03:37Z with `X-Admin-Token` (value not recorded): HTTP 500 as designed
  (`evidence/api-sentry-test-call-staging.json`). The API log shows
  `DeliberateSentryTestError: Deliberate Sentry test error (api)` raised inside the
  `sentry_sdk` FastAPI/Starlette integration, so the SDK is initialised.
  - **Release SHA: expected missing.** `release()` reads `RAILWAY_GIT_COMMIT_SHA` then
    `GIT_COMMIT`; neither is in the service variables and `/health` reports
    `git_commit: unknown`. Owner to confirm on the event. Fix proposal for S5: pass the
    commit as a build arg or set a release source.
- **Web.** Server-side test route, admin session required (this session has none). Owner,
  signed in at `/admin/login`, opens once:
  `https://optcg-price-tracker-staging.vercel.app/api/admin/observability/sentry-test?target=web`
  (expect an error page; the error is captured by `instrumentation.ts`).
- **Owner checks in Sentry**, for `Deliberate Sentry test error (api)` in
  `card-pirate-api` and `(web)` in `card-pirate-web`:
  - `environment: staging`;
  - release SHA present (web expected `eaf9de7…`; API likely empty, see above);
  - no IP address, no `X-Admin-Token`/Authorization/Cookie headers, no query string,
    no user or other personal data.

## Pending

1. Owner: trigger the web test error and confirm both Sentry events and a page view in
   Vercel Analytics (above). Record the result in the next collector-v1 handoff.
2. API release SHA (S5 if missing).
3. This handoff PR's own receipt (expected scope `skip`, 0 collector deployments):
   download first in the next collector-v1 session.
4. Probe tool follow-up (Analytics section).
