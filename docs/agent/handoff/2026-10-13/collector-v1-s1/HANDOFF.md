# Collector v1 S1 handoff: legacy deletion delivered to staging (2026-10-13)

Plan: `docs/agent/plans/collector-v1/PLAN.md` §F and §H row S1 (on `plan/collector-v1`).
Target: staging only. Production was not accessed (`production_accessed: false`).

## Plain summary

The old analytics decision pages, market signals/opportunities/report, dashboard,
activity, signed-in search, grading page and the market workflow are gone from
staging. Their URLs now redirect permanently (308) to `/collection`, `/analytics`
or `/cards`, or answer 404 where there is no successor. Market Value, the Card
Pirate Index, card and print pages are unchanged. No collector was redeployed, no
migration ran, and no data was deleted.

## Delivery

| Item | Value |
|---|---|
| PR | #110, marked ready 2026-10-13T06:45:18Z, native auto-merge by the delivery job |
| Head | `e6ffccba8f14397c7b6f986ed5eb4bdbc0971d1d` |
| Merge commit | `d55fc2082f3554639f9ccf1a8254d55f7691c8cc`, merged 2026-10-13T07:01:39Z, base `ceb4102` |
| CI run | `38358511322`: all 20 jobs success, including `engineering-gate`, `staging-automerge` |
| Classification | GREEN, no collector rollout, no migration requested |
| Size | S1 code commit `4220807`: 239 files, +885 / **−30,859** lines. Whole PR (incl. the two docs commits below): 265 files, +26,280 / −30,902 |

The PR also carried two docs-only commits that had not reached staging:
`a331c7a` (PR #108 Git-fetch record) and `eb9de28` (PR #109 delivery receipt).
Both were covered by the manifest's diff hash.

### Receipts (downloaded into `evidence/pr110-delivery/`)

| Artifact | Id | Expires |
|---|---|---|
| `staging-delivery-d55fc2082f3554639f9ccf1a8254d55f7691c8cc` | 11795455500 | 2027-01-11T06:45:20Z |
| `staging-credential-probe-e6ffccba8f14397c7b6f986ed5eb4bdbc0971d1d` | 11794176223 | 2027-01-11T06:45:20Z |

- `latest-staging-delivery.json`: verified 2026-10-13T07:14:06Z. Frontend
  `dpl_ENZZqLhJBvX3SRACYP5aWaGEL6jd` READY at `d55fc20`. API expectation
  `build` at `d55fc20` (watched API changes). Migration revision `6c2242f6f439`
  (unchanged). Routes `/`, `/prints/5661`, `/analytics` rendered. Sale invariant:
  227 public sale histories checked, 0 sale index inputs, 0 gap receipts.
  0 GET timeout retries.
- Delivery scope: `full` (non-documentation change).
- Credential probe: `STAGING_RAILWAY_TOKEN` VERIFIED, `production_accessed: false`.
- Railway records since 06:45Z (`evidence/deploy-records-after-pr110.json`):
  API `optcg-price-tracker`, `worker`, `beat`, `market-index-snapshot` each
  one SUCCESS deployment at `d55fc20` (07:01:41Z). **0 deployments on all 11
  collector services** (snkrdunk-collector, yuyutei-collector, shards 0-3,
  4-v2, 5-8) and on the two `tmp-*` services. No rollout was requested, so there
  is no `latest-collector-rollout.json`.

## Step 0 (owner Q7): passed before any deletion

`evidence/step0-closure.json` and `evidence/step0-staging-read.json`
(read-only, 2026-10-12T23:53Z).

- The import closure of Market Value, the Card Pirate Index writer/pipeline,
  market-index-snapshot and the public `cards`/`prints`/`releases`/
  `market_value` APIs (10 entry points, 103 modules) reads no market workflow
  output. Only `app.schemas`, `app.services.job_locks` and
  `app.services.latest_prices` mention those outputs (schema classes and comments).
- Staging: no dependent views and no functions or triggers mention the workflow
  tables. Exact counts: `market_workflow_runs` 0, `market_signal_events` 7
  (newest 2026-08-05), `market_intelligence_reports` 12 (newest 2026-08-08),
  `market_report_digest_sends` 0. The tables stay (RED to drop, plan §B5).

## What was deleted, redirected and kept

Redirected (308, query kept; `next.config.ts` `redirects()` from
`apps/web/src/lib/legacyRedirects.ts`, each covering subpaths):

| From | To |
|---|---|
| `/analytics/{buy-decisions,sell-decisions,portfolio-risk,grading,digest}`, `/dashboard`, `/activity` | `/collection` |
| `/market/{signals,signal-events,opportunities,report}` (incl. `/market/report/latest`) | `/analytics` |
| `/search` (`/search?q=luffy` → `/cards?q=luffy`) | `/cards` |

404, no successor: `/grading`, `/admin/market-workflow-runs`.

Deleted with them: their Next API routes and page-only components; the FastAPI
routers/endpoints, services, CLIs and schemas behind them (signals, signal
events, opportunities, market report and Telegram digest, analytics digest,
buy/sell decisions, portfolio risk, grading analytics, dashboard, activity
summary, search, market workflow runs/trigger); the worker's
`run_market_workflow`, its beat entry and the signal/report steps of
`refresh_prices`; seed saved-view presets; the stale branch
`fix/admin-auth-mutating-routes` (`evidence/stale-branch-deletion.json`,
restore command recorded there).

Kept: `/analytics` (public Market page), `/market/movers`, shared UI
components, `PinnedViewsSection` and `saved_views`, `TELEGRAM_*` for
`check_alerts`, `recentWorkflows`. Deferred: `/analytics/collection`,
`/analytics/wishlist`, the grading router and `GET /collector/activity` to S8;
model files, settings flags, the backup format bump, worker model mirrors and
`MARKET_WORKFLOW_*` env validation to S9. `full-market-refresh` keeps price
refresh and portfolio snapshot only.

## Staging checks after merge

Tools: `tools/capture.py` (same as before), `tools/admin_signed_out.py`,
`tools/deploy_records.py`. All read-only GETs or Railway reads.

- **Deleted URLs** (`evidence/after.json`, 07:16Z): all 14 redirect URLs answer
  308 to exactly the target above; `/grading` answers 404.
  `/admin/market-workflow-runs` answers 307 to `/admin/login` signed out,
  because the admin gate runs before routing (before S1 it was the same 307).
  The page is absent from the deployed build's route table
  (`evidence/vercel-build-log-d55fc20.txt`), so a signed-in admin gets 404. Its
  API (`/admin/market-workflow-runs`) and the Next proxy
  `/api/admin/market-workflow-runs` both answer 404.
- **Deleted APIs** (`evidence/admin-signed-out-after.json`): FastAPI
  `/admin/market-workflow-runs`, `/market/signals`, `/market/opportunities`,
  `/market/report/latest`, `/dashboard/overview`, `/search`,
  `/analytics/digest/latest`, `/analytics/buy-decisions` all 404; Next
  `/api/{admin/market-workflow-runs,market/signals,search,dashboard/overview}` 404.
- **Admin pages**: the deployed build contains all 23 kept admin pages plus
  `/admin/login`. Signed out, all 24 admin URLs 307 to `/admin/login`, which
  renders 200. Kept admin APIs (`/admin/release-status`,
  `/admin/observability/summary`, `/admin/data-retention/policy`) answer 401
  without a token, so they exist. **Not verified: signed-in rendering of the
  trimmed admin pages** (no admin credentials in this session; none were
  extracted). The owner can confirm in one pass: `/admin/actions`,
  `/admin/cache`, `/admin/release-status`, `/admin/system-check`.
- **Screenshots** (`evidence/screens/before_*`, `after_*`, desktop 1440 and
  mobile 390):
  - `/prints/5661`: pixel-identical (mobile) and 39 pixels (desktop).
  - `/cards`, `/market/movers`: under 1% (desktop) and 1-2% (mobile), one
    card-tile-sized region each: image loading, not layout.
  - `/`: hero card fan rotates and "Recently added" shifted by one new
    catalogue card. "Cards on the move" identical.
  - `/analytics` mobile: the *before* capture (2026-10-12T23:55Z) had 5 console
    errors and every section below the chart showed "could not be loaded". The
    *after* capture loads all sections with 0 console errors. Desktop differs
    by 0.59% in one tile.
  - All 10 page/viewport pairs: same titles, 0 broken images, 0 console errors
    after.
- **Market Value and Index unchanged**: normalized SHA-256 of
  `/analytics/market-value?window=7d`, `?window=30d`,
  `/analytics/market-value/releases`, `/analytics/market-value/movers` and
  `/releases` identical before and after. The `/analytics` page shows the same
  tracked value (¥5,676,725; 2,398 of 4,316 variants priced; 55.6%). The
  legacy `/market/movers` list changed by 1 byte: its code
  (`services/market.py`, `MarketMoverOut`) is unchanged by S1 and it carries
  live 24h/7d/30d changes and latest prices, so this is data drift.
- **Staging verifier**: green (delivery receipt above, written only on success).

## What S2 needs

Owner decision Q3 is made: **Vercel Web Analytics + Sentry Developer, both
free tiers.** Before S2 installs anything:

1. Owner enables Web Analytics on the Vercel project
   `prj_DCbF7bhFkkAdfMQLZWvOQbxEDDhr` and creates the Sentry Developer
   account (choose US or EU data region). Any paid plan is RED.
2. Owner confirms the Hobby plan's non-commercial wording is acceptable; if
   Card Pirate counts as commercial, the free fallback is Umami Cloud Hobby and
   the paid path is Vercel Pro (plan §F2, both need a new decision).
3. Keys: Sentry DSN as Vercel env vars and `SENTRY_DSN` on the Railway API,
   not in the repo. `sentry-sdk` goes in `services/api/requirements-observability.txt`
   installed only by `deploy/railway/api.Dockerfile` (plan §A rule 5); re-run
   the collector import-graph check before merging.
4. No PII, no session replay, `sendDefaultPii: false`, scrub `Authorization`
   and cookies; events and properties limited to plan §F2. Disclose both in
   the Privacy draft.

## S3's backup rule

S3 adds an additive Alembic migration (AMBER). Before applying it to staging:
confirm a staging Postgres backup **younger than 24 hours** (take a fresh one
if the newest is older) and record its id and time in the S3 handoff. The
migration only creates the new account tables; rollback is
`alembic downgrade` to `6c2242f6f439`, dropping the new empty tables. After it:
`alembic current` equals the new head, the new tables exist and are empty,
the legacy copy dry run reports 0/0, and the `/me` endpoints answer 404/401
while `COLLECTOR_ACCOUNTS_ENABLED` is off.

## Pending receipt

This handoff's own PR (docs-only, delivery scope expected `skip`, 0 collector
deployments): download its `staging-delivery-<merge sha>` artifact first in
the next session.
