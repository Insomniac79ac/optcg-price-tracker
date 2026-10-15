# Tranche: Collector v1 S7, collection page

## Page or component

`/collection` (signed-in collectors only), rebuilt on the v1 accounts API
(`/me/collection`, `/me/collection/value`). Replaces the legacy table page.
The legacy `/collection/vault`, `/analytics/collection` and their components
stay until S8.

## Emotional outcome

"These are my cards, and I can see what they are worth today without the
page pretending to know more than it does."

## User's five-second impression

The collection's value as of a named day, how much of it is priced, then the
cards themselves, art first. Movement is context, never the headline.

## Must visibly change

- Homepage hero band with the value headline, "Prices as of 14 Oct" and
  "Priced: X of Y cards (Z%)". No price → "No prices yet", never ¥0.
- 7D / 30D / ALL chips; an unavailable window reads "—" with its reason
  in words, never 0%.
- History chart: recorded history solid; the day-one preview dashed,
  labelled as a preview.
- "What moved your collection", "By set", the art-first card grid
  (1 column at 320px, 2 at 390px), "What you paid" (only when entered) and
  "Needs a version".
- Edit and remove in a sheet; an empty state that sends the collector to
  find a card.

## Must not change

- Card art framing: uncropped `CardImageFrame` through the shared
  image helper; no raw Bandai URL.
- No price, change or total is computed in the browser: every number comes
  from the API response.
- No portfolio, P/L, cost basis, liquidation, hold/sell, position or ROI
  wording.
- Prices, Market Value, Market Index, identity and the daily pipeline.

## Real data available

`/me/collection` (entries, coverage, `as_of`), `/me/collection/value` per
window (movers, by set, paid, recorded history, preview) plus one additive
field, `cards`: every comparable version's change for the window (the list
the top-five movers are cut from), so each tile can show its own change.
Card art and version labels from the public print read (`/prints/{id}`).
Session state from Auth.js (collector only).

## Before evidence

Local dev server (origin/staging 50a03d0) against the local mock API with
test data and a minted collector session, widths 1440, 390, 320:
the legacy page is an admin-style form stack (import/export, tags and
groups, "Portfolio value over time", add-item form, status filters) that
calls the pre-v1 endpoints and fails against the v1 API. Staging alias not
reachable from the cloud session.

## Acceptance criteria

1. Order: value headline → chips → chart → movers → by set → grid →
   what you paid → needs a version.
2. Unpriced entries read "No price yet" and are left out of the total;
   coverage is always visible next to the value.
3. An unavailable window shows "—" and a reason, never 0%.
4. Grid: 2 columns at 390px, 1 at 320px; no horizontal scroll at 320px;
   art uncropped; 44px touch targets.
5. Preview line visually distinct (dashed, labelled) from recorded history.
6. Edit/remove happen in a sheet, removal needs a second confirm, the page
   refreshes from the API afterwards.
7. Empty, accounts-off and error states each render plainly.

## Verification

Vitest (page states, number honesty, chips, sheet), API test for `cards`,
full web and API suites, local before/after screenshots at 1440/390/320,
fresh `cardpirate-visual-reviewer` review, staging check after delivery when
reachable.

## Commit

One product-lane PR.
