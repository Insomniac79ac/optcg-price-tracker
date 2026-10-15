# Tranche: Collector v1 S8, watchlist (product part)

## Page or component

`/watchlist` (signed-in collectors only), new, on the v1 accounts API
(`/me/watchlist`). It replaces the legacy `/wishlist`. The legacy pages
`/wishlist`, `/collection/vault`, `/analytics/collection` and
`/analytics/wishlist` are deleted and answer 308s: the first two old wishlist
paths go to `/watchlist`, the old vault and collection analytics go to
`/collection` (Q6). Their route handlers, components and `lib/api.ts`
functions go with them. The legacy FastAPI routers stay until the data-lane
PR that follows.

## Emotional outcome

"These are the cards I want, and I can see how close each one is to my price
without being pushed to buy."

## User's five-second impression

The cards you're watching, art first. Each row shows today's value, how far
it is from your target and how it moved this week. Nothing flashes or urges.

## Must visibly change

- Title "Cards you're watching", kicker "Watchlist", count and "Prices as of".
- One row per watched version: art, name, version, value "as of", target
  (editable in a sheet), distance ("¥1,200 above your target"), freshness
  ("Checked 3 h ago"; "Check time unknown" when unknown), 7D change.
- An unpriced version reads "No price yet" with no distance. An unavailable
  7D change reads "—" with its reason, never 0%.
- "Needs a version" for watches carried over from the old wishlist that
  match more than one version.
- Empty state that sends the collector to find a card.
- Nav label "Watchlist" (sidebar, command palette, `g w`).

## Must not change

- Card art is uncropped: `CardImageFrame` through the shared image helper.
- No number is computed in the browser. Value, gap and change come from the
  API.
- No alerts or emails. No buy/sell, portfolio, P/L, position or ROI wording.
- Prices, Market Value, Market Index, identity and the daily pipeline.

## Real data available

`/me/watchlist` (value, `target_gap_jpy`, `as_of`), plus three additive
fields per entry:
- `checked_at`: `freshest_eligible_source_at` on the archived row the value
  comes from.
- `change_7d_pct` and `change_7d_reason`: this version's change over the 7
  days ending `as_of`, under the collection movers' comparability rules.

The list also gains `change_7d_from` and `change_7d_missing_dates`. The
change is read from the same archive as the value, so the two always agree;
the live `market_index_change` would compare against a different current
value. Art and version labels come from `/prints/{id}`.

## Before evidence

Local dev server (origin/staging 4e169c3) against the mock API with test
data and a collector session, at 1440, 390 and 320. `/wishlist` is an
admin-style form stack (priority, max buy price, preferred condition, CSV
import/export, filters) that fails to load ("Failed to load wishlist from
the API."). `/analytics/wishlist` and `/analytics/collection` say "Budget
planning, target hits" and fail the same way. `/collection/vault` is the
legacy grid. The staging alias is not reachable from the cloud session.

## Acceptance criteria

1. Every row: art, name and version, value with "as of", target, distance,
   freshness, 7D change, Edit.
2. Unpriced reads "No price yet", never ¥0. An unavailable 7D change shows "—"
   with a reason, never 0%. Unknown freshness says unknown.
3. Mobile first: no horizontal scroll at 320 and 390, art uncropped,
   44px targets, Edit opens a bottom sheet.
4. The four old paths 308 to exactly one target each, never into a second
   redirect, and their subpaths follow.
5. No legacy page, route handler or component is left reachable or orphaned.

## Verification

- Vitest: page states, number honesty, sheet edit, loader, redirects, nav.
- API tests for `checked_at` and the 7D change.
- Full web and API suites.
- Local before and after screenshots at 1440, 390 and 320, plus a states
  audit (overflow, 44px, objectFit, redirects).
- Fresh `cardpirate-visual-reviewer` review.
- Staging check after delivery, when reachable.

## Commit

One product-lane PR (security review line: proxy, meProxy, next.config
redirects, accounts router). The legacy FastAPI routers, services and the
worker portfolio snapshot follow in a separate data-lane PR.
