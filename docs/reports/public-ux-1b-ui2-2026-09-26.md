# Public UX 1B-UI2 review evidence

Status: PUBLIC_UX_1B_UI2_READY_FOR_REVIEW

Branch: `feature/public-ux-market-1b-ui`

Unchanged HEAD/base: `bc23e992faa84940e9747d877efb65b362acb411`

UI2 builds on the uncommitted UI1 working tree. The initial Git status and diff summary are preserved in `docs/ui/evidence/2026-09-26-public-ux-1b-ui2/initial-git-status.txt` and `initial-diff-stat.txt`.

## Final page order

1. Card Pirate Index
2. What moved
3. Market snapshot (English release heading when selected)
4. Cards in this market
5. Market structure

Market structure contains scoped Price distribution and source-coverage explanations, then a separate Broad Index structure subsection containing Index composition and Market breadth. Each is rendered once. Existing data sources, price bands, counts, and calculations are retained; supporting panels have quieter styling.

## Cards behavior

One `/prints` request uses `release_product_id`, `rarity`, `price_basis`, `sort=card_code_asc`, and `limit=6`. Legacy unresolved set bookmarks retain the existing server selector. Explicit release IDs take precedence. There is no browser filtering, ranking, randomization, pagination, or per-card enrichment request.

Cards use the existing print UI model, CardImageFrame, source/instrument vocabulary, selected-basis lookup, and JPY formatting. Each links to its exact print, shows its authoritative physical release code, and never substitutes Market Index for an unavailable selected-source value. Artwork stays uncropped and lazy-loaded.

Responses are tagged by selection and retry attempt. Previous cards retain their own basis labels, prices, and browse destination while refreshing. Late responses cannot overwrite a newer selection. Failure and Retry are section-local; empty cohorts have an explicit no-usable-price message.

Browse these cards carries only release ID and rarity, for example `/cards?release_product_id=186&rarity=SEC`; price basis is omitted.

## Files changed by UI2

- `apps/web/src/app/analytics/page.tsx`
- `apps/web/src/lib/marketAnalytics.ts`
- `apps/web/src/components/ui/MarketCardsSection.tsx` (new)
- `apps/web/src/components/ui/MarketCardsSection.test.tsx` (new)
- `apps/web/src/app/analytics/page.test.tsx`
- `apps/web/src/app/analytics/indexMovers.test.tsx`
- `apps/web/src/app/analytics/indexAnalytics.test.tsx`
- `apps/web/src/app/analytics/indexHero.test.tsx`
- `apps/web/src/lib/marketAnalytics.test.ts`

Earlier UI1 files remain in the working tree. This report and the UI2 browser evidence are additional untracked artifacts.

## Validation

308 tests passed across 9 files, including the existing UI1 suites and new cards/structure coverage. TypeScript, touched-file ESLint, and `git diff --check` passed. The mixed-code EB04-007 / OP-17 fixture remains in the server-selected cohort and links to the exact print. Tests cover all three current bases, a future source, unavailable selected-source values, request limits/order, supported catalogue links, empty/error/retry states, retained cards during refresh, and stale-response rejection.

Local Chrome checks at 390px and 1500px used mock API data and stand-in artwork only. Six screenshots plus `browser-check.json` are saved under `docs/ui/evidence/2026-09-26-public-ux-1b-ui2/`. Lazy artwork was allowed to load before screenshots. The final order, two-column mobile/six-column desktop grid, readable source prices, scoped/broad distinction, and absence of horizontal overflow passed. No browser page errors. Real staging data/artwork remains for the later Vercel Preview gate.

Request counts were measured at both viewports:

| Interaction | Overview requests added | Cards requests added | Index/composition/movers requests added |
|---|---:|---:|---:|
| Initial load | 1 | 1 | 1 each |
| Release change | 1 | 1 | 0 |
| Rarity change | 1 | 1 | 0 |
| Basis change | 1 | 1 | 0 |

## Resources and stop point

After validation: 14.66 GiB available / 46.8% free. Pre-existing evidence is preserved. The local development server was stopped.

No backend files or API contracts changed. No migrations, collectors, production access, dependency installation, Docker builds, production Next build, commits, pushes, or PR creation. UI1 and UI2 remain uncommitted for review.
