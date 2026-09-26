# Public UX 1B-UI1 review evidence

Status: PUBLIC_UX_1B_UI1_READY_FOR_REVIEW

Branch: `feature/public-ux-market-1b-ui`

Unchanged HEAD/base: `bc23e992faa84940e9747d877efb65b362acb411`

## Behavior

- Market Release choices use `/releases` order and English release labels. New navigation writes `release_product_id`; unique legacy `set` bookmarks canonicalize with `replaceState`. Explicit release IDs take precedence. Clear removes release and rarity while retaining basis.
- Market snapshot leads with the server's priced/total count and coverage, followed by median and typical price range. Source observed/usable/constrained/unavailable distinctions remain intact. The previous snapshot stays visible while refreshing.
- Move % and Index impact request distinct server cohorts with `order=move|impact`. Rows retain server order, artwork, exact print links, direction, and archived prices. Impact points become primary in impact mode.
- Index, composition, and movers remain broad-market and independent of Market release, rarity, and price basis. Existing lower panels remain in place. Cards in this market has not been implemented.

## Changed frontend files

- `apps/web/src/app/analytics/page.tsx`
- `apps/web/src/components/ui/CardPirateIndexHero.tsx`
- `apps/web/src/components/ui/IndexMoversPanel.tsx`
- `apps/web/src/components/ui/MarketLandscapeFilters.tsx`
- `apps/web/src/components/ui/MarketLandscapeSections.tsx`
- `apps/web/src/lib/marketAnalytics.ts`
- `apps/web/src/lib/cardPirateIndex.ts`
- `apps/web/src/app/analytics/page.test.tsx`
- `apps/web/src/app/analytics/indexMovers.test.tsx`
- `apps/web/src/app/analytics/indexHero.test.tsx`
- `apps/web/src/app/analytics/indexAnalytics.test.tsx`
- `apps/web/src/app/page.test.tsx` (required mover-order fixture field)
- `apps/web/src/lib/marketAnalytics.test.ts` (new)

## Validation

285 tests passed across 8 files: analytics page, movers, Index hero, Index analytics, Index library, Market analytics library, Home discovery, and print library. Includes the mixed-code `EB04-007` / OP-17 fixture, scope URL/history, section-local failures, distinct mover cohorts, stale-response protection, and server aggregate preservation. No backend tests or live API calls were used to validate membership.

TypeScript (`tsc --noEmit`), touched-file ESLint, and `git diff --check` passed. No backend files changed.

Local Chrome checks at 390px and 1500px passed with mock API responses and stand-in artwork. Six screenshots and the request/check manifest are in `docs/ui/evidence/2026-09-26-public-ux-1b-ui1/`. Checked broad snapshot, release/rarity selection, English labels, impact mode, Back/Forward, Clear preserving basis, source constraint states, legacy URL replacement, broad Index request isolation, image width, and absence of horizontal overflow. No browser page errors. Screenshots were visually inspected; native mobile navigation remains fixed as before.

## URL examples

- Broad: `/analytics`
- Release: `/analytics?release_product_id=186`
- Release and rarity: `/analytics?release_product_id=186&rarity=SEC`
- Source and scope: `/analytics?basis=source%3Asnkrdunk&release_product_id=186&rarity=SEC`
- Legacy: `/analytics?set=OP-17&rarity=SEC` becomes `/analytics?rarity=SEC&release_product_id=186` using replace.

Mover mode remains local and does not alter these URLs.

## Resources and stop point

After validation: 14.71 GiB available / 47.0% of filesystem capacity. All 695 pre-existing untracked files remain present. The local development server has been stopped.

No dependencies installed, Docker state recreated, production accessed, backend files changed, commits created, pushes performed, or PR opened. Changes are left uncommitted for review.
