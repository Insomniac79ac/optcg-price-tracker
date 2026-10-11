# Collector Accounts v1: plan (PLAN ONLY)

**Status: APPROVED by the owner, 2026-10-11**, with the answers recorded in §I. The owner starts
S1 separately. Sections changed by the answers: §C3, §C4, §D1, §D2, §F, §F2, §G, §H, §I, Risks.

Prepared 2026-10-11 from `origin/staging` at `c086b8b` (PR #100 merge), worktree
`/workspaces/cp-collector-v1`, branch `plan/collector-v1`. STAGING ONLY. Production RED.
PSA10 OFF. Nothing in this session changed code, staging, Vercel, Railway or Google.

Evidence labels: **MEASURED** = read from the repo at `c086b8b` or from a read-only staging
query on 2026-10-11 08:27-08:45Z (connection forced `default_transaction_read_only=on`, via the
session-9 `tools/db.py` pattern). **CARRIED FORWARD** = from the session-9 capacity handoff
(`docs/agent/handoff/2026-10-10/capacity75-session9/HANDOFF.md`). **ESTIMATED** = my
arithmetic or vendor pages, not observed. **UNVERIFIED** = background knowledge or third-party
page that the build session must re-check.

---

## Plain summary (for the owner)

1. v1 lets a collector sign in with Google, add the exact card version they own (regular art,
   parallel, alternate art) from any card page, see what their collection is worth, how it moved
   over 7 days / 30 days / since they started, which cards moved it most, and how each set
   contributes. They can also keep a watchlist with target prices.
2. Values use the same rules as the public Market Value: sale prices from Yuyu-Tei are never
   used, missing prices show as "no price yet" (never ¥0), and a change we can't measure shows as
   unavailable (never 0%).
3. All the old trading-style pages (buy/sell decisions, signals, opportunities, reports, digest,
   dashboard, grading, activity, signed-in search) are deleted.
4. It takes **8 build sessions**, plus one later clean-up session that needs your decision. None
   of the 8 should redeploy the price collectors.
5. **You need to:** create a Google sign-in client (steps in §D2, about 20 minutes); create free
   Vercel Web Analytics and Sentry Developer accounts (§F2, decided); buy the custom domain
   (decided, §I Q1); choose the contact email and governing law and review the draft privacy
   policy and terms before sign-in opens to the public; move to Vercel Pro before any revenue
   (§H pre-launch gate).
6. Open decisions with recommended defaults are in §I. Storage impact is small: about 73 KB per
   active collector per year (ESTIMATED), well under 1% of today's daily database growth.

---

## 0. Verified current state (confirms the audit's known gaps)

| Known gap | Status | Evidence (MEASURED) |
|---|---|---|
| Collector sign-in effectively off | **Confirmed** | `apps/web/src/lib/auth.ts:241-252` has `Google` with no args (reads `AUTH_GOOGLE_ID/SECRET`) plus admin `Credentials`. `apps/web/src/app/sign-in/page.tsx:18-22,54-57` shows "Collector accounts are not enabled yet" unless both vars are set and not `change-me`. `docs/staging_deployment.md:81` says the vars are not set. |
| Collection/wishlist keyed to legacy `cards` | **Confirmed** | `services/api/app/models/collection_item.py:33`, `wishlist_item.py:29` FK `cards.id`. Picker is a `<select>` over `GET /cards` (`apps/web/src/app/collection/page.tsx:187,670-690`, `wishlist/page.tsx:125,405-426`). Staging `cards` = **25 rows**. |
| Valuation history not per user | **Confirmed** | `portfolio_valuation_snapshots` has no `user_id` (staging columns). `services/api/app/api/collection.py:264-311` ignores the user, cache key `collection_history:{days}:{limit}` (L307). Staging table: **12 rows, all zero, newest 2026-08-08**; the snapshot writers are dormant (`LEGACY_PRICE_REFRESH_ENABLED`, `MARKET_WORKFLOW_ENABLED` default false, `services/worker/worker/settings.py:45-66`). |
| Valuation not Market Value method | **Confirmed** | `services/api/app/services/portfolio_valuation.py:1-7,40-42`: retail = Yuyu sell, liquidation = Yuyu buy, floor = SNKRDUNK floor, keyed by legacy `card_id`. |
| `/prints/[id]` has no actions | **Confirmed** | `apps/web/src/app/prints/[id]/page.tsx:262-326`. Actions only on legacy `apps/web/src/app/cards/[id]/page.tsx:383-407`. |
| Finance language, dense tables | **Confirmed** | `collection/page.tsx:958-976` (Cost basis, P/L vs retail/liquidation/floor, Target sell), statuses hold/watch/sell/sold/grading (`collection_item.py:17-26`). No mobile layout, no images in the table. |
| No privacy/terms/about/methodology | **Confirmed** | No routes under `apps/web/src/app`; `components/Footer.tsx:18-32` has no links. |
| Legacy signal/digest/dashboard APIs admin-gated | **Confirmed** (PR #93/#94) | `apps/web/src/proxy.ts:148-166`, `lib/adminSession.ts:49-70`. |
| authfix NOTE open items | **Confirmed, each folded in** | Shared `dashboard_preferences` (single row `main_dashboard`, `services/dashboard.py:96-106`) → deleted with `/dashboard` (S1). Dashboard portfolio chart and recent activity global (`services/dashboard.py:166-186,302-303`) → deleted (S1). Saved views pinned to admin-only pages → staging `saved_views` has **0 rows**; seed presets removed in S1 (`app/seed_saved_views.py`). Stale Vercel branch preview vars → deleted in S5 with an `AUTH_SECRET` rotation. Old branch `fix/admin-auth-mutating-routes` → deleted in S1. |

**Additional facts the plan depends on (MEASURED):**

- **Accounts already half-exist.** `users` table (`app/models/user.py:9-22`: `google_sub`, `email`,
  `name`, `avatar_url`); FastAPI `require_current_user` verifies an HS256 JWT signed with
  `API_JWT_SECRET` and creates the user on first call (`app/auth.py:31-71`). Auth.js uses JWT
  sessions with no database adapter. Staging has **0 users, 0 collection items, 0 wishlist items**.
- **The per-user API token reaches the browser.** The collector session carries `apiToken` (1h
  HS256 JWT, `auth.ts:226-236`), which client code reads through `getSession()` and sends straight
  to Railway (`lib/api.ts:909-972`). FastAPI CORS defaults to `*` (`app/main.py:158-167`). No
  admin secret reaches the browser: `ADMIN_TOKEN` is server-only (`lib/adminProxy.ts:35-40`) and
  `scripts/check-env.js:23-49` blocks secret-like `NEXT_PUBLIC_*` names.
- **Daily per-version values already exist.** `market_index_snapshots`: **34,166 rows, 2,626
  versions, 2026-08-21 → 2026-10-10, 31.9 MB**, unique `(card_print_id, snapshot_date)` plus index
  `(card_print_id, calculated_at)`. These are the Market Value inputs (`docs/market_value.md`). The
  daily pipeline (`app/market_index_daily_pipeline.py`) gates Market Value on a completion receipt;
  latest receipt 2026-10-10 20:04Z (CARRIED FORWARD).
- **The legacy `cards` table cannot be dropped.** It is still referenced by **2,156 of 36,965**
  `price_observations.card_id` and **74 of 3,006** `source_card_mappings.card_id` (14 of those have
  no `card_print_id`). Price lineage depends on it.
- **The freshness "high interest" flag is not driven by collections** (`freshness_queue.py:193-238`,
  caller-supplied). v1 must keep it that way: making collected or watched cards high-interest would
  change source budgets (AMBER, capacity mission).

---

## A. Delivery scope: collector import graph (check only)

**MEASURED at `c086b8b`** (`scripts/collector_runtime_inputs.py`, `runtime_inputs()` for both
collectors): SNKRDUNK reaches 62 `app` modules, Yuyu-Tei 73. The union includes:

- `app/__init__.py`, `app/db.py`, `app/env.py`, **`app/settings.py`**
- **`app/models/__init__.py` and every model it imports**, including `user.py`,
  `collection_item.py`, `wishlist_item.py`, `portfolio_valuation_snapshot.py`,
  `dashboard_preference.py`, `market_signal_event.py`, `market_intelligence_report.py`,
  `analytics_digest_report.py`, `search_history.py`, `grading_submission.py`, …
- `app/services/__init__.py` and 20 service modules (freshness, identity, RAW storage; none of the
  collection, valuation, dashboard, signal or report services).

Per `counts()` (same file, L240-249), any change to those files, **any non-Python file under
`services/api/app/`**, or `services/api/{pyproject.toml,requirements.txt,setup.*,MANIFEST.in}`
is a collector release.

**So the expected answer "none" holds only if v1 follows these rules:**

1. Do **not** edit `app/models/__init__.py`, any existing model file, `app/settings.py`,
   `app/db.py`, `app/env.py`, `services/api/requirements.txt` or `pyproject.toml`.
2. New tables live in a new package `services/api/app/accounts/` (models, config, services,
   router). Nothing in the collector graph imports it. `alembic/env.py` (not installed in
   collectors) and `app/main.py` import it explicitly. New models reference `users.id` by FK only,
   with no relationship added to `User`.
3. New settings (feature flag, retention) are read in `app/accounts/config.py`, not `settings.py`.
4. Legacy model files and legacy settings flags stay in place until the deferred clean-up session
   S9 (they are inert once their routers and services are gone).
5. A backend dependency for error tracking (`sentry-sdk`) goes in a new
   `services/api/requirements-observability.txt` installed only by `deploy/railway/api.Dockerfile`.
   That path is not in `API_ALWAYS` and not under `app/`, so `counts()` returns false. The S2
   session must re-run the check to confirm before merging.
6. Every v1 PR adds a unit test that asserts `app/accounts/**` and every changed file are outside
   `runtime_inputs()` for both collectors, and each PR body records the check output. The delivery
   tooling is unchanged; its continuity check stays the backstop.

| Session | Touches collector import graph? | Collector release? |
|---|---|---|
| S1 legacy deletion (code) | No: deletes API services/routers/schemas, web, worker files; does not touch `models/*`, `settings.py` | **No** |
| S2 info pages + analytics/errors | No (web; API Sentry via rule 5) | **No** |
| S3 accounts data + API | No (new `app/accounts/`, Alembic migration) | **No** |
| S4 collection value history | No (`market_index_daily_pipeline.py`, `app/accounts/`) | **No** |
| S5 auth + account section | No (web, `app/main.py` CORS, `app/accounts/`) | **No** |
| S6 card-page actions | No (web; small `app/accounts/` read) | **No** |
| S7 collection page | No (web) | **No** |
| S8 watchlist + legacy collection removal | No (deletes legacy routers/services; legacy models untouched) | **No** |
| **S9 deferred clean-up** | **Yes**: removes legacy models from `models/__init__.py`, settings flags | **YES: collector release** (quiet window, sequential rollout, with the RED table-drop decision) |

Note: API merges still build the API, worker, beat and `market-index-snapshot` services through
their GitHub triggers (session-9 handoff §2a). That is the designed path and is verified by
`verify_staging_delivery`; it is not a collector redeploy.

---

## B. Data model

### B1. New tables (all in `app/accounts/`, one additive Alembic migration, AMBER)

Re-keying in place would mean editing `collection_item.py` and `wishlist_item.py` (collector
release) and keeping legacy columns (statuses, liquidation targets, grading links) that v1 drops.
Staging holds 0 rows, so new tables are equivalent to a re-key and cheaper to ship. Legacy tables
stay untouched and are listed for the S9 decision.

| Table | Columns (key ones) | Notes |
|---|---|---|
| `collection_entries` | `id`, `user_id` FK users ON DELETE CASCADE, `card_print_id` FK card_prints (nullable only when unresolved), `quantity` ≥1, `paid_jpy_per_card` nullable, `acquired_on` nullable, `note` (≤500), `legacy_collection_item_id` nullable, `legacy_card_id` nullable, `resolution` ∈ {`exact`, `unresolved`}, timestamps | Unique `(user_id, card_print_id)` where `card_print_id` is not null. CHECK: `resolution='exact'` ⇔ `card_print_id IS NOT NULL`. Condition is out of scope for v1 (raw only; PSA10 OFF). |
| `collection_entry_events` | `id`, `user_id`, `card_print_id`, `quantity_before`, `quantity_after`, `occurred_at` | Append-only holdings ledger (add/remove/quantity change). Lets history count only cards actually held each day. About 60 B per event (ESTIMATED). Deleted with the user. |
| `watchlist_entries` | `id`, `user_id` CASCADE, `card_print_id` (same nullable/resolution rule), `target_jpy` nullable, `note`, legacy ids, timestamps | Unique `(user_id, card_print_id)`. Replaces `wishlist_items`. |
| `user_preferences` | `user_id` PK/FK CASCADE, `currency` CHAR(3) default `'JPY'` CHECK in (`'JPY'`), `collection_visibility` default `'private'` CHECK in (`'private'`), `updated_at` | CHECK lists widen when a currency selector or sharing ships. No row = defaults. |
| `collection_value_points` | `user_id` CASCADE, `point_date`, `methodology_version`, `value_jpy` bigint null, `priced_cards`, `total_cards`, `priced_entries`, `total_entries`, `prior_point_date`, `comparable_cards`, `prior_comparable_jpy` (P), `current_comparable_jpy` (Q), `step_publishable`, `step_reason`, `segment_number`, `created_at` | PK `(user_id, point_date, methodology_version)`. Written once per completed market day (§C3). Insert-only, `ON CONFLICT DO NOTHING` then compare, like `market_value_writer`. |

### B2. Moving existing rows (exact and unique only, never guessed)

**Rule.** A legacy row maps to a CardPrint only when the legacy `card_id` reaches **exactly one**
CardPrint through **active** `source_card_mappings` (`card_id` → `card_print_id`), and that print
is active. Anything else is copied with `card_print_id = NULL`, `resolution='unresolved'`,
`legacy_card_id` kept. It is shown to the owner of the row as "needs a version choice", never
priced. Card-code matching is never used (INVARIANTS: release membership and identity are never
inferred from a code).

**Buckets on staging (MEASURED, read-only, 2026-10-11):**

| | Rows | Exact & unique | Unresolved |
|---|---|---|---|
| `collection_items` | **0** | 0 | 0 |
| `wishlist_items` | **0** | 0 | 0 |
| Dry run on all 25 legacy `cards` (in case rows appear before S3) | 25 | **10** (one active mapped print) | **15** (6 reach 2 prints; 9 reach none) |

The copy job is a CLI (`python -m app.accounts.migrate_legacy --dry-run|--write`) that is
idempotent on `legacy_*_id`. S3 runs it in dry-run mode on staging; `--write` only if rows exist.

### B3. Per-user valuation snapshots: size, schedule, retention

- **What is stored:** one `collection_value_points` row per user, per completed market day, only
  for users with at least one exact entry. Per-card detail is **not** stored: card-level movers are
  recomputed from `market_index_snapshots`, which is retained already.
- **Schedule:** a new independent stage in `app/market_index_daily_pipeline.py`, after the
  completion receipt is verified (same gate as Market Value), around 20:00 UTC. A missed day
  stays missing (a break), never backfilled with invented values.
- **Retention:** keep all (rows are small; history is the product). Deleted with the account.
- **Size (ESTIMATED):** ~115 B heap tuple + ~45 B across the PK index ≈ **160 B/row; plan with
  200 B/row** for bloat. So **73 KB per active collector per year**.

| Active collectors | Per year | Per day | vs measured DB growth 33.5 MB/day (CARRIED FORWARD) |
|---|---|---|---|
| 100 | 7.3 MB | 20 KB | 0.06% |
| 1,000 | 73 MB | 200 KB | 0.6% |
| 10,000 | 730 MB | 2 MB | 6% |

The holdings ledger adds ~60 B per user action (ESTIMATED; 1,000 users × 200 actions ≈ 12 MB
total). Room to the 3 GiB reserve is 3,137.6 MB (CARRIED FORWARD), so v1 at up to ~1,000 users
shortens the capacity mission's runway by about two days per year of operation (73 MB ÷ 33.5 MB/day). Build sessions report
actual table sizes in their handoff so the capacity mission can separate them from RAW growth.

**Zero-storage alternative:** derive history on every read from the ledger and
`market_index_snapshots`. It costs no storage, but a 500-card, 365-day chart reads about 180k
snapshot rows per uncached request (ESTIMATED). Recommended: points table; derive-on-read only for
the "how your current cards moved" preview (§C4).

### B4. Preferences needed by v1

`currency` (JPY only; selector shown, other options disabled with "coming later"), and
`collection_visibility` (private only; reserved for a future opt-in share, which needs a separate
privacy contract per `docs/reports/collector-public-context-2026-10-01.md:110`). Display name and
avatar come from Google (`users.name`, `avatar_url`). Nothing else is needed for v1.

**Currency architecture:** every API returns integer JPY plus `currency: "JPY"`. One web helper,
`formatMoney(valueJpy, preference)`, is the only place that formats money on collector pages.
A future FX layer converts in that helper from a stored daily rate table; stored prices stay JPY
(INVARIANTS). No FX code in v1.

### B5. Tables unused after legacy deletion: LIST ONLY (owner decision, RED to drop)

Row counts MEASURED 2026-10-11 (`count(*)`); sizes from `pg_total_relation_size`.

| Table | Rows | Size | Unused after | Notes |
|---|---|---|---|---|
| `analytics_digest_reports` | 0 | 32 KB | S1 | |
| `market_signal_events` | 7 | 168 KB | S1 | FK columns on `collector_activity_events`, `collector_notes` must drop first |
| `market_intelligence_reports` | 12 | 176 KB | S1 | same; `market_workflow_runs.market_report_id` |
| `market_report_digest_sends` | 0 | 40 KB | S1 | |
| `dashboard_preferences` | 0 | 32 KB | S1 | |
| `search_history` | 0 | 32 KB | S1 | |
| `market_workflow_runs` | 0 | 32 KB | S1 (if the workflow goes, §F) | admin page goes too |
| `portfolio_valuation_snapshots` | 12 | 40 KB | S8 | global, no user |
| `collection_items`, `wishlist_items` | 0, 0 | 48 KB, 56 KB | S8 | replaced by B1 |
| `collection_item_groups`, `collection_item_tags`, `collector_groups`, `collector_tags`, `collector_notes`, `collector_activity_events`, `card_tags`, `grading_submissions` | all 0 | ≈ 0.5 MB total | S8 | legacy collection features |
| `import_validation_reports`, `file_jobs` | 0, 0 | 96 KB | S8 if CSV import/export of legacy collection goes; check admin use first | |

**Keep:** `cards` (price lineage, above), `saved_views` (admin catalog-ops pinned views),
`alert_rules` (6 rows) / `alert_events` (worker `check_alerts`), `users`.

Dropping saves about 1.5 MB in total. It is a clean-up, not a storage remedy.

---

## C. Valuation method

### C1. Per-card value

- The value of one exact version on day *d* is its archived Atlas Market Index value
  `market_index_snapshots.index_value_jpy` for `snapshot_date = d`, **positive only**, from a day
  with a verified completion receipt. This is exactly the Market Value input (`docs/market_value.md`
  "usable value"), so the same eligibility already applies: Yuyu-Tei sale prices blanked
  (`market_index.py:238-296`, `source_semantics.is_customer_price`), struck prices never
  substituted, no forward fill, no nearest-date lookup, PSA10 never mixed in.
- "Value today" = the latest receipted day (`as_of`, shown on the page as "Prices as of 10 Oct").
  The live `/prints` headline may be newer intraday. The collection uses the receipted day so total,
  history and movers agree; card rows link to `/prints/[id]` for live detail.
- No positive value → **unpriced**. Shown as "No price yet", excluded from totals, never ¥0.

### C2. Collection value and coverage

`value(d) = Σ quantity × v(print, d)` over priced exact entries. Shown with coverage:
"Priced: 41 of 48 cards (85%)". Unresolved entries count as unpriced and are labelled. When no
entry is priced, value is null ("No prices yet"), not ¥0.

### C3. Change over 7D / 30D / ALL (same continuity rules as Market Value)

For adjacent receipted days *p* → *d*, comparable cards per version = `min(quantity held at p,
quantity held at d)` (from the ledger), only where the version has a positive value on both days,
equal index and source-semantics versions, and the same non-empty contributing (source,
reference_type) set. That is the A2 comparable rule.

`P = Σ units × v(p)`, `Q = Σ units × v(d)`, step ratio `Q/P`. **Adding or removing cards never
shows as a gain or loss**; they are entrants or leavers.

A step is publishable when `P > 0`, every adjacent day exists, and comparable value is at least 80%
of priced value at both ends (the Market Value guard). 7D/30D chain the publishable daily ratios
(integer products, divided once, 50-digit Decimal like `market_value_read`). ALL = since the
collection's first point, unavailable across any break. Any missing day or failed step makes the
window **unavailable with a reason** ("Not enough price history yet", "Prices missing on 27 Sep");
never 0%.

Market Value's **count thresholds** (≥300 comparable versions for Overall, size-aware release
gates) are population rules and would make every personal collection permanently unavailable. v1
drops them for personal collections and keeps the 80% value guard. This is a new derived measure,
not a change to Market Value. **Owner approved Q4 (2026-10-11):** keep the 80% value guard, drop the minimum card counts for
personal collections.

The September 27-28 gap predates any collection, so it can only affect the preview in §C4. There
it breaks the line like the Market chart does.

### C4. Movers, contributors, by release, acquisition

- **Movers / contributors** (on the page as "What moved your collection"): per version,
  `Δ = units × (v(d) − v(p))` over the comparable set for the selected window's endpoints. Ranked by
  absolute yen impact, with % and percentage-point contribution `100 × Δ / P`, and reconciled so
  `ΣΔ = Q − P` (same rule as Market Value A4B). Computed on read, nothing stored.
- **By release** ("By set"): group current entries by authoritative `CardPrint.release_product_id`
  (never the code prefix): value, priced/total cards, share of collection, and window change where
  the release subset passes the same step rule.
- **What you paid vs now** (only where the user entered it): over entries with
  `paid_jpy_per_card` **and** a current price: "You paid ¥X for 12 cards; they're priced at ¥Y
  today (+Z%)". Coverage is stated ("12 of 48 cards have a price paid"). Never mixed with unpriced
  or unpaid entries. Words used: "What you paid", "Priced today". Not cost basis, P/L or
  liquidation.
- **Day-one preview** (optional, derive-on-read, zero storage): "How your current cards moved over
  the last 30 days", using current holdings over archived snapshots, labelled as a preview and
  visually separate from the collection's own recorded history. **Owner approved Q5 (2026-10-11):**
  include it, clearly labelled as a preview.

### C5. Implementation reuse

Reuse the pure helpers in `app/services/market_value.py` (comparable-set test, step and window
math, Decimal context) through a new scope adapter in `app/accounts/valuation.py`. Do not edit
Market Value modules except to extract a shared pure helper if needed, with no behaviour change,
proven by the existing Market Value test suite and the A2 oracle tests.

---

## D. Auth and account

### D1. Mechanism

- Keep Auth.js v5 (`next-auth ^5.0.0-beta.31`), JWT sessions, no adapter. Google is collector
  sign-in. The admin `Credentials` provider stays as is (4h role expiry, server-only
  `ADMIN_TOKEN`). The admin allowlist migration (`docs/staging_deployment.md` §13 "Migration path")
  is **not** in v1.
- **Approved hardening (S5; owner approved Q2 on 2026-10-11, all four items below):**
  1. Stop putting `apiToken` on the session object. Collector pages call Next route handlers
     (`/api/me/**`) that mint a short-lived (5 min) API JWT server-side and call `API_INTERNAL_URL`.
     The browser never holds a bearer token.
  2. Restrict FastAPI CORS from `*` to the staging origin.
  3. `hasCollectorSession` (`lib/proxyGuard.ts:190-194`) must require `sessionKind === "collector"`
     on collector routes. An admin session on `/collection` gets the sign-in invite, not a broken
     page.
  4. Rotate `AUTH_SECRET` when the stale branch variables are deleted (authfix NOTE). This signs out
     the admin once; collectors don't exist yet.
- Users are created on first API call (existing `_get_or_create_user`, keyed by Google `sub`).

### D2. What the owner must do for Google sign-in (plain language)

**Owner decision Q1 (2026-10-11):** a custom domain will be bought (name TBD, likely through
Cloudflare Registrar). Until it exists, sign-in stays in Google **Testing** mode on the staging
`vercel.app` URL, so the steps below use the staging URL. When the domain is live, add its origin
and redirect URI to the same client (step 6), verify it in Google Search Console, and move the
Branding links (step 3) to it before **Publish app**.

You need a Google account. Nothing here costs money. Do it in a normal browser; don't paste the
secret into a chat with an AI agent.

1. Go to **console.cloud.google.com** and create a new project called "Card Pirate".
2. Open **Google Auth Platform** (it may be called "OAuth consent screen"), then **Get started**.
   - App name: `Card Pirate`
   - User support email: your email
   - Audience: **External**
   - Contact email: your email
3. Under **Branding**, add the app home page, privacy policy and terms links:
   - Home page: `https://optcg-price-tracker-staging.vercel.app` (the custom domain once bought, Q1)
   - Privacy policy: `…/privacy`
   - Terms: `…/terms`

   Google wants these on a domain you own and have verified in Google Search Console.
   `vercel.app` is a shared platform domain, and a third-party report says it cannot be verified
   (UNVERIFIED, §I Q1). While the app stays in **Testing** mode (step 5), you can leave these blank
   or use the staging links.
4. Under **Data access**, add only the scopes `openid`, `.../auth/userinfo.email` and
   `.../auth/userinfo.profile`. These are basic scopes and need no Google review.
5. Under **Audience**, leave the status as **Testing** and add yourself (and up to 99 testers) as
   test users. Only these people can sign in until you press **Publish app**. Publish only after you
   approve the privacy policy and terms (§G).
6. Under **Clients**, choose **Create client**, then **Web application**, named
   `Card Pirate staging`.
   - Authorized JavaScript origins: `https://optcg-price-tracker-staging.vercel.app`
   - Authorized redirect URIs: `https://optcg-price-tracker-staging.vercel.app/api/auth/callback/google`
     (add the custom-domain versions when the domain is live, Q1).
   - Click **Create**. Google shows a **Client ID** and **Client secret**.
7. In **vercel.com**, open project `optcg-price-tracker-staging`, then **Settings → Environment
   Variables**. Add both with the **Production** environment ticked (this project's "Production"
   is staging), and tick **Sensitive** for the secret:
   - `AUTH_GOOGLE_ID` = the Client ID
   - `AUTH_GOOGLE_SECRET` = the Client secret
8. Tell the build session it's done. It will redeploy, check that the variable *names* exist
   without reading values, and test sign-in with your test account.

Nothing new is set on Railway. `API_JWT_SECRET` already exists on both sides
(`docs/staging_deployment.md:79`). The session checks `AUTH_URL` and `AUTH_SECRET` names on Vercel.

### D3. Email sign-in: recommend NOT in v1

Auth.js email links need a database adapter (new tables for accounts and verification tokens) and
an email-sending service, which is a new external service (RED). Google covers the target users.
Revisit if users ask; Resend's free tier would be the default then (UNVERIFIED).

### D4. Account section (`/account`, signed-in only, noindex)

- **Profile:** Google name, avatar, email (read-only, "managed by Google"), member since.
- **Preferences:** currency selector showing JPY, with others disabled ("More currencies later").
- **Export my data:** downloads JSON plus CSV (collection, watchlist, preferences, profile).
  Generated on request, nothing stored.
- **Delete my account:** typed confirmation, then deletes the `users` row. ON DELETE CASCADE removes
  `collection_entries`, `collection_entry_events`, `watchlist_entries`, `user_preferences`,
  `collection_value_points`, plus legacy `collection_items`, `wishlist_items`, `collector_tags`,
  `collector_groups`, `saved_views`, `search_history` (existing FKs). Then sign out. Google keeps
  its own account; we store no Google tokens. Analytics hold no personal data (§F2). Error events
  carry no user id. Railway/Vercel request logs age out under the providers' retention (stated in the
  privacy policy).
- **Sign out.**

### D5. Signed-out experience

- Homepage "My collection" link: a signed-out visitor lands on an explainer at `/collection`
  ("Track what your cards are worth. Sign in with Google to start a collection.") with a sample
  layout. No redirect dead end.
- `/prints/[id]`: "Add to collection" and "Watch" buttons are visible; clicking opens a sign-in
  invite that returns to the same card (`callbackUrl` already sanitised by `lib/callbackUrl.ts`).
- While Google is in Testing mode, the sign-in page says sign-in is invite-only for now, rather
  than showing a Google error.

---

## E. Collector UX (ATLAS loop; one visual tranche per session)

Each UI session follows `docs/ui/ATLAS_LOOP.md`: tranche contract first
(`docs/ui/TRANCHE_TEMPLATE.md`), desktop and mobile screenshots before and after, a fresh
`cardpirate-visual-reviewer` agent as grader, and staging deployment plus stable alias verified
before claiming done. Art is always uncropped (`object-fit: contain`) through the shared helper
`resolveCardImageUrl()` (`lib/cardImage.ts:40`), which the card-images R2 session will repoint.
Never use a raw Bandai URL (today `collection/vault/page.tsx:433` and `cards/[id]/page.tsx:322` do;
both are removed).

### E1. Exact-version actions on `/prints/[id]` (S6)

- "Add to collection" (quantity, optional "what you paid" and date) and "Watch" (optional target
  price) on the exact version page. The version is the page's CardPrint, already labelled with
  Regular art / Alternate art / parallel and release, so there is no picker.
- "Other versions" rows get a small "In your collection ×2" badge.
- The `/cards/code/[cardCode]` chooser shows ownership badges per version, but no add button; the
  user chooses the exact version first.
- **Retire legacy `/cards/[id]`:** 308 redirect to `/prints/{id}` when the legacy card resolves
  exactly and uniquely per B2 (10 of 25 today, MEASURED); otherwise 308 to
  `/cards/code/{cardCode}`; unknown id → 404. Implemented as a server lookup page, like
  `app/market/movers/page.tsx`. Remove the legacy page's ownership, wishlist, grading and activity
  panels.

### E2. Collection page `/collection` (S7)

Mobile-first. Order:

1. Value headline with `as_of` and coverage.
2. 7D/30D/ALL change chips (unavailable shown as "—" with a reason tooltip).
3. History chart (preview line visually distinct if Q5).
4. "What moved your collection" (top 5 up/down by yen).
5. "By set" (release cards with value, share and change).
6. The cards themselves: an art-first grid on mobile (2 columns at 390px, 1 at 320px) with art,
   name, version label, ×quantity, value, and the change for the window. On desktop the same grid
   plus an optional compact list.
7. "What you paid" summary only when entered.
8. "Needs a version" section for unresolved entries.

Edit and remove happen in a sheet. Empty state invites the user to find a card. Copy: collection
language only. Banned words on collector pages: portfolio, P/L, cost basis, liquidation, hold/sell,
position, ROI.

### E3. Watchlist (S8)

- Rename everywhere public: route `/watchlist`; 308 redirects from `/wishlist` and
  `/analytics/wishlist`; nav "Watchlist"; title "Cards you're watching".
- API: new `/me/watchlist`. Legacy `/wishlist` FastAPI router deleted in S8 (0 rows, no external
  consumers). No compatibility alias needed beyond the web redirects.
- Per row: art, version, target price (editable), current value (C1) with "as of", distance to
  target ("¥1,200 above your target"), freshness ("Checked 3 h ago" from the print's
  `freshest_eligible_source_at`; unknown shown as unknown), 7D change (existing
  `market_index_change`; unavailable never 0%).
- No price alerts or emails in v1. They would need an email service (RED); list as v2.

### E4. Wording sweep ("collection", never "portfolio")

S1 through S8 remove "portfolio" from all public routes, copy, nav, page titles, metadata and OG
cards. MEASURED hits to clear include `PortfolioValuationHistoryChart`, `DashboardPortfolioChart`,
`/analytics/portfolio-risk`, and the "My collection" intent link (kept). The deleted share route
for private collections stays unavailable. Internal Python names (`portfolio_valuation.py`)
disappear in S8; DB table names are left for S9.

---

## F. Legacy deletion inventory

Full file-level inventory, from the read-only code audit at `c086b8b`, with paths and line refs:
see **Appendix F** below. Summary of decisions:

| Feature | Web route + components | Next API routes | FastAPI | Services / worker | Action |
|---|---|---|---|---|---|
| `/analytics/buy-decisions` | page, layout, test; `BuyDecisionActionGroups`, `BuyDecisionCandidateTable` | `api/analytics/buy-decisions` | `analytics.py:492-530` (keep router) | `buy_decision_support.py` | **Delete**; redirect → `/collection` |
| `/analytics/sell-decisions` | page, layout, test; `SellDecision*` | `api/analytics/sell-decisions` | `analytics.py:714-745` | `sell_decision_support.py` | **Delete**; → `/collection` |
| `/analytics/portfolio-risk` | page, layout, test | `api/analytics/portfolio-risk` | `analytics.py:563-583` | `portfolio_risk.py` | **Delete**; → `/collection` |
| `/analytics/grading` | page, layout, test; `GradingAnalyticsBreakdownTable`, `GradingSubmissionTable` | `api/analytics/grading` | `analytics.py:531-562` | `grading_analytics.py` | **Delete**; → `/collection` |
| `/grading` | page, layout | none (calls FastAPI directly) | `api/grading.py` router (`main.py:41,194`) | keep `services/grading.py` until S8 | **Delete page S1**; router deleted S8 with the legacy collection (it is the only grading writer; v1 has no grading) |
| `/analytics/digest` | page, layout, test | 4 digest routes + admin generate | `analytics.py:584-713`, `admin_actions.py:160-193` | `analytics_digest.py`, CLI | **Delete**; → `/collection` |
| `/market/signals` | page, layout | `api/market/signals` | `market.py:70-141` (keep router: `/market/movers`) | `market_signals.py` | **Delete**; → `/analytics` |
| `/market/signal-events` | page, layout; `MarketSignalEventStatusBadge`, orphan `MarketContextPanel` | 5 routes + test | `market.py:142-363`, `admin_actions.py:122-144` | `market_signal_events.py`, CLI | **Delete**; → `/analytics` |
| `/market/opportunities` | page, layout; `OpportunityCategoryBadge` | `api/market/opportunities` | `market.py:364-448` | `opportunity_scoring.py` | **Delete**; → `/analytics` |
| `/market/report` | page, layout; `AdminOnlyPageLayout` | report routes + 2 admin actions | `market.py:449-516`, `admin_actions.py:145-159,316-339` | `market_report.py`, `telegram_market_digest.py`, `telegram_client.py` (API copy only), CLIs | **Delete**; → `/analytics` (also removes the pre-existing `/market/report/latest` 500) |
| `/dashboard` | page, layout; `DashboardPortfolioChart`, `VaultHighlightsSection`, `WorkflowShortcutsSection`, `lib/dashboardWidgets` | overview, preferences | `api/dashboard.py` (`main.py:38,197`) | `services/dashboard.py` | **Delete**; → `/collection` (fixes shared preference + global widgets) |
| `/activity` | page, layout | none | `collector_activity.py` `/summary` only | — | **Delete page + `/summary`**; keep `GET /collector/activity` until S8 (legacy `/cards/[id]` uses it), then delete; → `/collection` |
| `/search` (signed-in) | page, layout; `SearchTypeBadge` | search, suggestions | `api/search.py` (`main.py:50,224`) | `search.py`; trim `search_ownership.py` (keep `require_user_id`); drop `search_health_probe` from `system_check.py` | **Delete**; `/search?q=` → `/cards?q=` |
| Market workflow | — | admin run action | `admin_actions.py:340-403`, `market_workflow_trigger.py`, `market_workflow_runs.py` | worker `run_market_workflow.py`, beat entry `celery_app.py:71-84`, signal/report steps in `refresh_prices.py:415-450`, worker copies of signal/report modules | **Delete** (staging flag is off; owner approved Q7 2026-10-11, including the admin run history page; S1 first proves no MV/CPI/`market-index-snapshot` reader, §H) |
| Not on the list: `/analytics/collection`, `/analytics/wishlist` | legacy-keyed, finance language | | | | **Delete in S8** with the legacy collection; redirect → `/collection`, `/watchlist` (owner approved Q6 2026-10-11) |

**Keep, with reasons:**
- `/analytics` index: it is the public Market page (sitemap, nav).
- Shared UI components (StatCard, PageHeader, DataTableShell, SeverityBadge, RiskBadge, …) used by
  admin pages.
- `PinnedViewsSection` and `saved_views` (admin catalog-ops). Reword "Pin to dashboard".
- `TELEGRAM_*` vars for worker `check_alerts`.
- `recentWorkflows` (CommandPalette).

**Cross-cutting edits:**
- `proxy.ts` matcher and `PROTECTED_MATCHER` (must stay identical; `proxy.test.ts`).
- SidebarNav, commandRegistry, CommandPalette/TopBar/AppShell test fixtures.
- Links in staying pages (collection, wishlist, CardActivityPanel, GradingSummaryPanel,
  OwnershipSummaryPanel, admin actions and market-workflow-runs pages).
- Cache prefix lists (`admin_cards.py`, `refresh_trigger.py`, `admin_card_merge.py`,
  `collection_csv.py`, `wishlist_csv.py`, `admin_data_retention.py`, admin cache page).
- Admin pages to trim: actions, cache, performance, system-check, backup, data-retention.
- Smoke/audit scripts under `scripts/` that hit deleted routes.
- Docs: `docs/route_inventory.md`, `docs/operations.md` and the others in Appendix F. Historical
  `docs/agent/*`, `docs/reports/*` and `docs/ui/evidence/*` are left alone.
- Already-dead code: `components/ui/MarketContextPanel.tsx`, `DecisionBadge.tsx`.
- Redirects are added in `next.config.ts` `redirects()` (permanent).

**Deferred to S9 (collector release):**
- Model files and their `models/__init__.py` lines.
- `CACHE_DASHBOARD_TTL_SECONDS`, `RATE_LIMIT_SEARCH_PER_5M`, `TELEGRAM_*` in API `settings.py`.
- Backup format bump (`backup.py:68-71,154-165`).
- Worker model mirrors (`services/worker/worker/models.py:455,490,527,560,607`).
- Env validation entries for `MARKET_WORKFLOW_*` in `api/app/core/env_validation.py`: not in the
  collector graph, but keep them with S9 for one coherent removal.

**Confirmed no public or admin dependency remains** after the cross-cutting edits. The audit grep
found no other importers. Each session re-runs the grep and the full web and API test suites.

---

## F2. Site analytics and error tracking (owner-facing)

Traffic today is tiny (staging, no public launch). Plan for up to 50k page views a month in the
first year (ESTIMATED). Prices were checked 2026-10-11 from vendor docs or third-party summaries
and are **UNVERIFIED** until the build session re-checks the vendor pricing page.

| Option | Cost at ≤50k events/mo | Cookies / consent banner | Data location | Effort | Staging vs prod |
|---|---|---|---|---|---|
| **Vercel Web Analytics** | Hobby: 50k events/mo free, collection pauses at the cap; Pro: $0.03 per 1k extra ([Vercel docs](https://vercel.com/docs/analytics/limits-and-pricing)) | Cookieless (hashed, daily-rotating identifier) → no banner normally needed | Vercel (US) | Lowest: `@vercel/analytics` one component plus custom events | Per Vercel project, automatic |
| **Plausible Cloud** | No free tier; Starter about $9/mo for 10k page views (third-party summaries) | Cookieless, no banner | EU | Low (script tag) | Separate site per env |
| **Umami** | Cloud Hobby free, about 100k events/mo, 6 months retention (UNVERIFIED); self-host free but needs its own database, which must not be the capacity-bound staging Postgres | Cookieless | Cloud: vendor; self-host: yours | Low (cloud) / Medium (self-host) | Separate website id |
| **PostHog Cloud** | 1M events/mo free ([PostHog FAQ](https://posthog.com/faq)) | Cookies by default; cookieless needs config; session replay must be switched off | US or EU | Medium | Separate project |
| **Sentry** (errors) | Developer plan free: 1 user, 5k errors/mo (third-party summaries) | Error events only, no cookies set by default; turn off replay and PII | US or EU (choose at sign-up) | Low for Next (`@sentry/nextjs`); API via rule A5 | `environment=staging` tag |

**Decision (owner approved Q3, 2026-10-11; all free tiers):**
- **Site analytics:** Vercel Web Analytics on the current plan.
- **Errors:** Sentry Developer for the web app (client and server), plus the FastAPI API through
  `requirements-observability.txt`.
- **Hosting plan (separate from analytics):** Vercel Hobby is for non-commercial use. Moving to
  **Vercel Pro** is a hosting decision required **before any revenue starts** (gacha fees, partner
  API). It is a pre-launch gate in §H, not an S2 task. Umami is no longer the fallback.
- **RED:** any paid plan is an owner decision. Free tiers need only an account the owner creates.

**Banner:** cookieless analytics plus error tracking without PII should not need a consent banner
under Malaysia's PDPA or EU/UK ePrivacy as commonly applied, but both must be disclosed in the
privacy policy. This is a legal judgement, so the owner confirms via §G (UNVERIFIED).

**What to track (no personal data, no session replay):**
- Page views.
- Custom events: `sign_in_started`, `sign_in_completed`, `collection_add`, `collection_remove`,
  `watch_add`, `watch_remove`, `account_export`, `account_delete`, `share_card`.
- Properties limited to page type and release code. Never user id, email or card quantity. Never
  prices the user paid.
- Errors: release (git SHA), route, environment; `sendDefaultPii: false`; scrub `Authorization`
  and cookies.

Set the provider keys as Vercel env vars, plus `SENTRY_DSN` on the Railway API. The DSN is not a
secret by design, but keep it out of the repo.

---

## G. Legal and info pages (drafts to the owner; content is RED)

All pages are public, indexable (except where noted), linked from the footer, and use collector
language. Legal pages ship marked "Draft – under review" and stay noindex until the owner
approves the text. Public Google sign-in (Publish app) waits for that approval.

- **About** (`/about`): what Card Pirate is (independent price tracker for Japanese One Piece Card
  Game singles); not affiliated with Bandai, Shueisha or Toei; operated by "Card Pirate"; contact
  (placeholder).
- **How we price cards / Methodology** (`/methodology`): exact versions (regular art, alternate
  art, parallels are separate); sources (Yuyu-Tei listed and buy prices, SNKRDUNK listings and
  sales, as currently used); sale prices never used; Market Index per card; Market Value for the
  market and sets; freshness (24h target); coverage; unavailable vs 0; 27-28 Sep 2026 gap; how
  collection value and change are computed (§C); PSA10 not included. Derived from
  `docs/market_value.md` and `docs/market_index.md`; no methodology change.
- **Privacy policy** (`/privacy`) outline:
  1. Who we are ("Card Pirate") and contact (`[CONTACT EMAIL]` placeholder).
  2. What we collect: Google name, email, avatar and Google account id; collection and watchlist
     entries and anything you enter (what you paid, notes); preferences.
  3. Analytics (Vercel Web Analytics, cookieless, no personal data) and error tracking (Sentry,
     what an error report contains).
  4. Hosting providers and locations: Vercel, Railway, Cloudflare R2 (card images), Google
     sign-in, Vercel Web Analytics and Sentry.
  5. Purpose and legal basis.
  6. Retention: account data until you delete it; logs per provider.
  7. Your rights: access/export, correction, deletion (self-serve), complaints; PDPA (Malaysia),
     UK/EU GDPR rights for visitors there.
  8. International transfers.
  9. Children (not directed at under-13s, or 16s where applicable).
  10. Changes to the policy.
  11. Effective date.
- **Terms** (`/terms`) outline:
  1. Service description.
  2. Prices are estimates for information only, not offers, appraisals or financial advice; no
     guarantee of accuracy or availability.
  3. Accounts and acceptable use (no scraping of Card Pirate, no abuse).
  4. Your content (collection data is yours; licence to store and display it to you).
  5. Third-party trademarks; independent publisher.
  6. Liability limits.
  7. Termination and deletion.
  8. Governing law: `[GOVERNING LAW]` placeholder (owner decides before public launch).
  9. Changes and contact.

**Owner decision Q8 (2026-10-11):** drafts name the operator as **"Card Pirate"** and use
placeholders `[CONTACT EMAIL]` and `[GOVERNING LAW]` (the terms' "Malaysia default" is a suggestion
only, not written into the draft). No personal name appears in any draft. The owner fills the
placeholders before public launch. A lawyer review is recommended before public launch (RED:
legal/compliance).

---

## H. Sequencing

Global rules for every session:
- Own worktree; disk check first.
- Merge only between **06:00 and 23:00 UTC**, never in the 02:00-06:00 UTC busy window.
- No API/migration merge between 19:30 and 20:30 UTC (daily snapshot and receipt about 20:00-20:05).
- Not during the capacity mission's planned Postgres backup/resize window (06:30-09:00 UTC on the
  day it is announced in its handoff).
- Not during an announced SNKRDUNK 24h measurement or post-release observation (newest capacity
  handoff; currently the SNKR 24h on a852244 completes about 2026-10-11 14:31Z).
- Each session ends with a handoff per PROJECT_HANDOVER §43a, including new-table byte sizes for the
  capacity mission.
- No session redeploys collectors except S9.

| # | Session | Scope | Level | Migration / rollback | Tests | Staging verification | Collectors |
|---|---|---|---|---|---|---|---|
| **S1** | Legacy deletion (code) | **Preflight (Q7):** prove by code search plus a read-only staging check that nothing in Market Value, the Card Pirate Index or `market-index-snapshot` reads the market workflow's output (its tables, rows or files). If anything does, S1 stops and reports; nothing is deleted. Then: all of §F except the S8 items and S9 deferrals. Redirects. Admin page trims. Docs. Delete the old `fix/admin-auth-mutating-routes` branch. Seed presets removed. | GREEN (deleting code; no data) | No migration. Rollback = revert PR (API/web redeploy). | Full web (`vitest`) and API (`pytest`) suites; redirect tests; proxy matcher parity; import-graph test | Every deleted URL 308s to its target or 404s; admin pages load; `/analytics`, `/cards`, `/prints` unchanged; delivery receipt shows collectors untouched | None |
| **S2** | Info pages + analytics + errors | About, Methodology (final, owner skims), Privacy and Terms **drafts** (noindex), footer links. Install Vercel Web Analytics plus Sentry Developer (web, API via A5), free tiers (Q3 approved). Events per §F2. Legal drafts use operator "Card Pirate" with contact-email and governing-law placeholders (Q8). | GREEN for pages; provider gate cleared (Q3 approved 2026-10-11); owner creates the free accounts | No DB. Rollback = revert; remove env vars | Page render and metadata tests; analytics no-PII unit test (event payload allowlist); Sentry `beforeSend` scrubbing test | Pages live on staging alias; a test error appears in Sentry tagged `staging`; analytics shows a page view | None |
| **S3** | Accounts data + API (dark) | `app/accounts/` models (B1), Alembic migration, legacy copy CLI (dry run), `/me/collection`, `/me/watchlist`, `/me/preferences`, `/me/export`, `DELETE /me`, valuation service (C1, C2, C4 current/movers/by-release/paid) behind `COLLECTOR_ACCOUNTS_ENABLED` (in `accounts/config.py`) | **AMBER** (additive migration) | **Preflight: confirm a completed Railway Postgres backup less than 24 h old** (owner is enabling daily Railway backups). If none, stop and ask the owner to take a manual backup; do not migrate. Migration only creates tables; rollback = `alembic downgrade` dropping the new empty tables. | Tenant isolation (user A never sees B); FK cascade on delete; unresolved rows never priced; unpriced ≠ 0; Yuyu sale excluded (fixture); struck price not substituted; coverage math; import-graph test; Postgres tests | `alembic current` on staging = new head; tables exist and are empty; legacy dry-run report (expect 0/0); endpoints 404/401 while flag off | None |
| **S4** | Collection value history | Daily pipeline stage writing `collection_value_points` after the receipt gate; 7D/30D/ALL read with the 80% value guard and no minimum card counts (Q4 approved); day-one preview, clearly labelled (Q5 approved) | **AMBER** (changes the daily `market-index-snapshot` job's work; additive) | Stage is independent: its failure cannot block Market Value or CPI (same pattern as existing stages). Rollback = revert; delete rows by `methodology_version` (non-published, private, reversible). | Step/window math vs an oracle; quantity changes never count as gain or loss; missing day = break; 80% guard; idempotent rerun; MV and CPI stage results unchanged | Observe the next natural 20:00Z run: JSON report shows the new stage; MV and CPI inserted counts unchanged in pattern; points written for test users only | None |
| **S5** | Auth + account section | BFF route handlers, `apiToken` off the session (Q2), CORS restricted, collector-only session guard, `/account` (D4), signed-out invites (D5), sign-in page copy, delete stale Vercel branch vars + rotate `AUTH_SECRET`, enable flag. **Owner must have finished D2 steps 1-7** (Testing mode on the staging `vercel.app` URL until the custom domain exists, Q1). | Auth policy gate cleared (Q2 approved 2026-10-11); AMBER (env changes) | Rollback = revert; unset `COLLECTOR_ACCOUNTS_ENABLED`; Google client can be disabled by the owner | Auth unit tests (collector vs admin session, expired admin, no token in client bundle or session JSON); export contents; delete cascades; CSRF on mutating routes | Owner test account signs in on staging; export downloads; delete removes the user (verified by read-only count); admin login still works; browser devtools show no bearer token | None |
| **S6** | Card-page actions (UI tranche 1) | §E1 + `/cards/[id]` retirement | GREEN | No migration. Rollback = revert. | Component tests; redirect mapping tests (exact-unique only) | ATLAS: tranche contract, before/after desktop and mobile screenshots, fresh visual reviewer, staging alias verified | None |
| **S7** | Collection page (UI tranche 2) | §E2 | GREEN | Revert | Component tests incl. unavailable states, unpriced, coverage, 320/390px | ATLAS as above | None |
| **S8** | Watchlist + legacy collection removal (UI tranche 3) | §E3; delete legacy `/collection/vault`, old collection/wishlist pages, `/analytics/collection`, `/analytics/wishlist` (Q6 approved; redirected to `/collection`, `/watchlist`), legacy collection/wishlist/grading/tags/groups/notes/activity/CSV FastAPI routers and services, worker portfolio snapshot (check `check_alerts` first) | GREEN (0 rows; code only) | Revert | Full suites; redirects | ATLAS; deleted endpoints 404; staging delivery receipt | None |
| **S9** | Deferred clean-up (**DEFERRED**, Q9: revisit after v1 has run 30 days; not scheduled) | Remove legacy models and settings flags; backup format bump; worker mirrors; table drops from B5 if approved | **RED** (destructive migration) + collector release | Fresh backup; drop migration with a tested restore path; collector rollout per `STAGING_DELIVERY.md` (06:00-23:00Z, per-collector safe slot, sequential, auto-restore) | Full suites; backup/restore round trip | Collectors SUCCESS on new verified digests; lossless and continuity checks per capacity tooling | **YES** |

**Public launch gate** (not a session): the custom domain is bought, live on Vercel and verified in
Google Search Console, and the Google Branding links point to it (Q1); the owner fills the
contact-email and governing-law placeholders (Q8) and approves Privacy and Terms (and lawyer review
if chosen); the legal pages lose their draft banner and noindex; then the owner presses **Publish
app** in Google. Before that, sign-in is limited to test users on the staging `vercel.app` URL.

**Pre-revenue hosting gate** (not a session; separate from analytics): Vercel Hobby is
non-commercial. Before any revenue starts (gacha fees, partner API), the owner moves the web
project to **Vercel Pro** (RED: paid, owner decision). No revenue feature ships to the public while
the project is on Hobby.

**Card images (Q1, related, outside v1 sessions):** the custom domain will also serve the R2 card
images, replacing the rate-limited `r2.dev` public URL. Switching `R2_PUBLIC_BASE_URL` belongs to
the card-images R2 work, not to S1-S8.

Order dependencies: S2 before S5 (privacy URL and disclosures). S3 before S4-S8. S1 can run in
parallel with S2/S3. S6-S8 are visual tranches and run one at a time with `/clear` between them.

---

## I. Owner decisions (answered 2026-10-11; plan APPROVED)

Each question kept its recommended default except where noted. Original tradeoffs are in git
history (`ac4c4bf`).

1. **Custom domain: YES.** The owner will buy one (name TBD, likely via Cloudflare Registrar;
   about $10-15 a year, ESTIMATED, RED: paid). Until then, Google sign-in stays in **Testing** mode
   on the staging `vercel.app` URL (§D2). The domain will also serve the R2 card images, instead of
   `r2.dev`, which Cloudflare rate-limits (§H, card images).
2. **API token off the browser: YES.** `apiToken` off the session, BFF route handlers, CORS
   restricted to the staging origin, collector-only session guard (§D1, S5).
3. **Analytics and errors: Vercel Web Analytics + Sentry Developer, free tiers** (§F2, S2).
   Vercel Hobby is non-commercial: moving to Vercel Pro is a hosting decision required before
   revenue starts (gacha fees, partner API). Recorded as a separate pre-revenue gate in §H.
4. **Personal-collection change rule: YES.** Keep the 80% value guard; drop the minimum card counts
   for personal collections (§C3, S4).
5. **Day-one preview chart: YES**, clearly labelled as a preview (§C4, S4).
6. **Delete `/analytics/collection` and `/analytics/wishlist`: YES, in S8**, redirected to
   `/collection` and `/watchlist` (§F, §H).
7. **Drop the market workflow and its admin run-history page: YES**, on one condition: S1 first
   proves, by code search plus a read-only staging check, that nothing in Market Value, the Card
   Pirate Index or `market-index-snapshot` reads the market workflow's output. If anything does, S1
   stops and reports (§F, §H S1).
8. **Operator, contact, governing law:** drafts use **"Card Pirate"** as operator, with placeholders
   for contact email and governing law. No personal name in drafts. The owner decides before public
   launch (§G, §H launch gate). Lawyer review before public launch: still recommended.
9. **Table drops (B5) and the S9 collector release: DEFERRED.** Revisit after v1 has run 30 days.
   S9 is not scheduled (§H).
10. **Grading: ACCEPT.** No grading in v1; legacy grading data (0 rows on staging) goes with the
    legacy collection. PSA10 stays OFF.

Also recorded: **S3 preflight** must confirm a completed Railway Postgres backup less than 24 h old
(the owner is enabling daily Railway backups); if there is none, S3 stops and asks the owner to take
a manual backup (§H S3).

---

## Risks

- **Storage (capacity mission's binding constraint):** v1 adds about 73 KB per active collector per
  year plus a small ledger (ESTIMATED, §B3). The day-one preview and movers read existing snapshots
  and store nothing. Risk is low below about 1,000 users. The S4 handoff records real sizes.
- **Accidental collector release:** the biggest delivery risk. Collectors import every model and
  `settings.py`. Rules A1-A6 plus a per-PR import-graph test prevent it, and the delivery continuity
  check would refuse an unrequested change. Any slip must be handled as a sequential rollout inside
  the quiet windows, never a forced merge.
- **Daily pipeline coupling (S4):** a bug in the new stage could delay Market Value publication.
  Mitigation: an independent stage after MV and CPI, its own transaction and lock, failure never
  blocks them, observed on a natural 20:00Z run.
- **Google consent screen domain:** mitigated by the owner's decision to buy a custom domain
  (Q1). Until it is live and verified, sign-in stays in Testing mode (up to 100 named users), so
  public launch waits on the domain.
- **Commercial use on Vercel Hobby:** Hobby is non-commercial. Any revenue feature (gacha fees,
  partner API) before the move to Vercel Pro would breach the plan terms. Mitigation: the §H
  pre-revenue hosting gate.
- **Market workflow removal (S1):** if any Market Value, CPI or `market-index-snapshot` path reads
  workflow output, deleting it could break daily publication. Mitigation: the S1 preflight proof
  (Q7); S1 stops on any reader.
- **Migration without a fresh backup (S3):** mitigated by the S3 preflight (completed backup
  < 24 h old or stop).
- **Auth change surface (S5):** BFF and CORS changes could break remaining per-user pages. Mitigation:
  legacy per-user pages are deleted by S8; tests check that no bearer token is exposed; admin login
  is regression-tested.
- **Wrong identity:** only exact-unique legacy mappings are copied; unresolved rows are never priced;
  ownership is always on an exact CardPrint chosen on its own page.
- **Legal:** privacy and terms are drafts with "Card Pirate" as operator and placeholders for
  contact email and governing law until the owner decides and approves; analytics banner judgement
  is UNVERIFIED.
- **Vendor terms:** free-tier caps (Vercel analytics collection pauses at 50k events/mo; Sentry
  5k errors/mo) are UNVERIFIED and must be re-checked in S2.

---

## Appendix F: file-level legacy inventory (MEASURED at `c086b8b`, read-only audit)

Paths under `apps/web/src/` (web) or `services/api/app/` (api) unless absolute.

**Routing / nav / SEO:**
- `proxy.ts:149-165` and `lib/proxyGuard.ts:16-58` (edit; keep `/analytics/:path+` until S8).
- Tests: `lib/proxyGuard.test.ts`, `proxyFailClosed.test.ts`, `proxy.test.ts`.
- `components/ui/SidebarNav.tsx:67-76`, `lib/commandRegistry.ts:107-125`.
- Fixtures: `CommandPalette.test.tsx:7,274,385`, `TopBar.test.tsx:90-96`,
  `AppShell.test.tsx:172,248`, `lib/recentWorkflows.test.ts:15-24`, `SavedViewBar.test.tsx:47-135`.
- `lib/publicRoutes.ts:36-44`: keep the disallow entries.
- Links: `collection/page.tsx:552-562,1116`, `wishlist/page.tsx:345`,
  `analytics/collection/page.tsx:82-100`, `analytics/wishlist/page.tsx:69,75`,
  `components/ui/CardActivityPanel.tsx:83`, `GradingSummaryPanel.tsx:25`,
  `OwnershipSummaryPanel.tsx:104`, `admin/(protected)/actions/page.tsx:15,177,339,360,558-636`,
  `admin/(protected)/market-workflow-runs/page.tsx:200`.
- `PinnedViewsSection.tsx:13-31` (trim labels), `SaveViewModal.tsx:122` (reword).

**Per feature (web / Next API / `lib/api.ts` lines / FastAPI / service / schemas / tests):**

| Feature | Web | Next API | `lib/api.ts` | FastAPI | Service | `schemas.py` | Tests |
|---|---|---|---|---|---|---|---|
| buy-decisions | `app/analytics/buy-decisions/*`, `components/BuyDecision*` | `app/api/analytics/buy-decisions/route.ts` | 4385-4492 | `api/analytics.py:41,492-530` | `services/buy_decision_support.py` | 3682-3752 | `tests/test_buy_decision_support.py`; `seed_saved_views.py:15-31` |
| sell-decisions | `app/analytics/sell-decisions/*`, `components/SellDecision*` | `…/sell-decisions/route.ts` | 4278-4384 | `analytics.py:69,714-745` | `sell_decision_support.py` | 3599-3681 | `test_sell_decision_support.py`; seed 39-55 |
| portfolio-risk | `app/analytics/portfolio-risk/*` | `…/portfolio-risk/route.ts` | 4631-4815 | `analytics.py:67,563-583` | `portfolio_risk.py` | 3867-4048 | `test_portfolio_risk.py`, edit `test_market_analytics.py`; seed 63-71 |
| analytics/grading | `app/analytics/grading/*`, `GradingAnalyticsBreakdownTable`, `GradingSubmissionTable` | `…/grading/route.ts` | 4493-4630 | `analytics.py:59,531-562` | `grading_analytics.py` | 3753-3866 | `test_grading_analytics.py` |
| /grading | `app/grading/*` | — | 3982-4025, 458-507 (keep `GradingSubmission` types until S8) | `api/grading.py`, `main.py:41,194`, `core/rate_limit.py:61` (S8) | keep `services/grading.py` until S8 | 2138-2209 (S8) | `test_grading.py` (S8) |
| digest | `app/analytics/digest/*` | 4 routes + `api/admin/actions/generate-analytics-digest` | 4816-5023 | `analytics.py:10,40,584-713`; `admin_actions.py:25,160-193` | `analytics_digest.py`, `generate_analytics_digest.py`; job lock `job_locks.py:91` | 4049-4197 | `test_analytics_digest.py`; edit `test_private_read_route_auth.py`, `test_admin_actions.py`, web `privateReadProxies.test.ts`, `mutatingRouteAuth.test.ts` |
| signals | `app/market/signals/*` | `app/api/market/signals` | 2518-2606 (keep `MarketSignals` L175) | `market.py:29,70-141` | `market_signals.py` | 3024-3071 (keep `MarketSignalsOut` L1780) | `test_market_signals.py` |
| signal-events | `app/market/signal-events/*`, `MarketSignalEventStatusBadge`, `ui/MarketContextPanel` | 5 routes + `signalEventWrites.test.ts`; admin `snapshot-market-signals` | 2607-2724 | `market.py:142-363`; `admin_actions.py:122-144` | `market_signal_events.py`, `snapshot_market_signals.py`; job lock L89 | 3072-3122 | `test_market_signal_events.py` + edits listed in the audit |
| opportunities | `app/market/opportunities/*`, `OpportunityCategoryBadge` | `app/api/market/opportunities` | 2725-2810 | `market.py:30,364-448` | `opportunity_scoring.py` | 3123-3170 | `test_opportunity_scoring.py`; edit `test_collector.py`, `test_cache.py` |
| report | `app/market/report/*`, `admin/AdminOnlyPageLayout(.test)` | report routes; admin `generate-market-report`, `send-market-report-digest` | 3297-3365, 3437-3518 | `market.py:449-516`; `admin_actions.py:27,28,31,145-159,316-339` | `market_report.py`, `telegram_market_digest.py`, `telegram_client.py`, 2 CLIs; job locks L90, L92 | 3233-3353 | `test_market_report.py`, `test_telegram_market_digest.py` |
| dashboard | `app/dashboard/*`, `DashboardPortfolioChart`, `ui/VaultHighlightsSection`, `ui/WorkflowShortcutsSection`, `lib/dashboardWidgets` | overview, preferences | 5219-5405 | `api/dashboard.py`, `main.py:38,197` | `services/dashboard.py` | 4238-4362 | `test_dashboard.py`; edit `test_cache.py`; admin cache page L23,172 |
| activity | `app/activity/*`, `SearchTypeBadge` | — | 5493 only | `collector_activity.py:58-70`, `schemas.py:204` | keep `activity_timeline.py` until S8 | — | — |
| search | `app/search/*` | search, suggestions | 5532-5617 | `api/search.py`, `main.py:50,224`; `core/rate_limit.py:57,83,110,120,128` | `search.py`; trim `search_ownership.py`; `system_check.py:500-502` | 4363-4402 | `test_search*.py` (keep the migration test); edit `test_system_check.py`, `test_saved_views.py`, `test_rate_limit.py:73` |

**Worker:**
- `services/worker/worker/celery_app.py:15,71-84,138-164`; `jobs/run_market_workflow.py`;
  `jobs/refresh_prices.py:16-17,63-66,83-90,415-450`.
- Modules `market_signals.py`, `market_signal_events.py`, `opportunity_scoring.py`,
  `market_report.py`, `market_report_digest.py`.
- `data_retention.py:69-95`, `job_locks.py:31,33`.
- Tests `test_run_market_workflow.py`, `test_market_report_digest.py`; edit `test_celery_app.py`,
  `test_refresh_prices.py`, `test_data_retention.py`.
- Env vars `MARKET_WORKFLOW_*` (`worker/settings.py:61-66,114-142`, `worker/env_validation.py`,
  `.env.*.example`).
- Admin: `admin_actions.py:340-403`, `services/market_workflow_trigger.py`,
  `api/market_workflow_runs.py` (`main.py:223`), admin page and nav (`adminNavigation.ts:27`),
  `release_status.py:44`, `observability.py:65`, `system_check.py:463`.

**Scripts to edit:** `web_route_smoke.sh`, `phase8_audit.sh`, `phase10_ux_audit.sh`,
`release_candidate_audit.sh`, `staging_smoke_test.sh`, `prod_smoke_test.sh` (stale; production
RED, edit text only), `smoke_test.sh`, `load_test_api.sh`, `load_test_web.sh`.

**Docs to edit:**
- `docs/route_inventory.md` (lines 16-39, 62, 99-109, 137-190), `docs/operations.md`.
- `staging_checklist.md`, `interface_design_system.md`, `manual_qa_checklist.md`,
  `release_checklist.md`, `deployment.md`, `performance_testing.md`, `staging_deployment.md`,
  `staging_data.md`, `release_blockers.md`, `release_candidate_report.md`,
  `frontend_styling_audit.md`, `market_index.md`, `apps/web/README.md`.

---

## Sources

- Repo at `c086b8b`; read-only staging queries 2026-10-11 08:27-08:45Z.
- Capacity handoff: `docs/agent/handoff/2026-10-10/capacity75-session9/HANDOFF.md`.
- Authfix note: `docs/agent/handoff/2026-10-10/authfix/NOTE.md`.
- Vercel Web Analytics limits: https://vercel.com/docs/analytics/limits-and-pricing (checked 2026-10-11).
- PostHog free tier: https://posthog.com/faq (checked 2026-10-11).
- Umami Cloud: https://docs.umami.is/docs/cloud/faq (third-party summaries; UNVERIFIED).
- Plausible and Sentry prices: third-party summaries (last9.io, costbench.com, toolpick.dev), UNVERIFIED.
- Google authorized domains: https://developers.google.com/identity/verification/authentication-verification
  and https://developers.google.com/apps-script/guides/client-verification; the `vercel.app` point
  is from a third-party report, UNVERIFIED.
