# Tranche: Collector v1 S6, card-page actions

## Page or component

- `/prints/[id]`: new "Your collection" panel under the card's identity
  (`PrintCollectorActions`): Add to collection (quantity, optional what you paid
  per card, optional date), Watch (optional target price), edit and remove.
  "In your collection ×N" badges on the "Other versions" strip.
- `/cards/code/[cardCode]`: ownership badges on version tiles, no add button.
- `/cards/[id]`: retired. 308 to `/prints/{id}` only when the legacy card
  reaches exactly one active print (API `GET /cards/{id}/print-destination`),
  otherwise 308 to `/cards/code/{cardCode}`; unknown id 404.
- `/sign-in` and `/account`: restyled in the homepage's visual language
  (chart-blue hero band, dotted sea, teal mono kicker, italic heavy headline,
  wave rule, outlined chapter numerals, `#111b20` panels).
- Header: an expired admin session on a public page gets the ordinary
  collector "Sign in" (was: only "Admin session expired / Sign in again").

## Emotional outcome

Owning a card is one tap from looking at it, and the page quietly remembers
that you own it. Signing in feels like part of the same atlas as the homepage.

## User's five-second impression

"This is my card, and I can keep it." The card art and name still lead; the
collection panel sits between identity and the money, never above the art.

## Must visibly change

- Print page shows the collector panel (invite when signed out; status and
  actions when signed in); owned versions carry a badge.
- Sign-in and account read as the homepage's family, not a generic panel.
- Expired-admin browser sees "Sign in" in the public header.

## Must not change

- Card art framing (uncropped `CardImageFrame`), identity block, prices,
  Market Value, Market Index and history sections on `/prints/[id]`.
- No price is computed in the browser. Unpriced stays "No market price yet".
- Admin pages keep the expired-admin re-authentication.
- No "portfolio", P/L, cost basis, hold/sell, position or ROI wording.

## Real data available

Accounts API v1 (`/me/collection`, `/me/watchlist`) through the same-origin
`/api/me` route; print detail siblings; new public legacy-card destination.

## Before evidence

(Contract written during implementation, before the before/after capture
and review; the tranche scope was fixed by PLAN E1 and the owner brief.)

Local dev server (origin/staging 7ca4024) against a local mock API with test
data and minted test sessions (signed out, collector, expired admin), widths
1440, 390, 320. Staging alias not reachable from the cloud session.

## Acceptance criteria

1. Collector panel order: art, identity, collection panel, current prices.
2. Add/Watch forms: 44px targets, labelled inputs, inline validation, blank
   optional fields sent as null (never 0), removal needs a second confirm.
3. Ownership badges only for exact entries; unresolved entries never badge.
4. 320px: no horizontal scroll; form fields stack to one column.
5. Redirects: exact-unique only; never redirect on lookup failure.
6. Sign-in/account: homepage hero, kicker, headline, wave; gold only on the
   primary action; copy unchanged.

## Verification

Vitest (component, redirect, shelf, auth, account logging), full web and API
suites, local before/after screenshots, fresh `cardpirate-visual-reviewer`
review. Staging alias check after delivery when reachable.

## Commit

One product-lane PR (web), after the data-lane PR adding
`GET /cards/{card_id}/print-destination`.
