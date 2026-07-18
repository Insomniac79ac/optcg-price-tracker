# apps/web

Next.js dashboard for the OPTCG price tracker. Fetches directly from the API in the browser
using `NEXT_PUBLIC_API_URL` (defaults to `http://localhost:8000`).

## Development

```bash
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) — it redirects to `/dashboard`.

## Pages

- `/` — redirects to `/dashboard`.
- `/dashboard` — table of cards from `GET /cards`.
- `/cards/[id]` — card detail, price chart, and price observations from `GET /cards/{id}` and
  `GET /cards/{id}/prices`.

See `docs/route_inventory.md` at the repo root for the full, current route list (the list above
is not kept up to date as new pages are added).

## Checking bundle size

`npm run build` (or `npm run build:profile`, an alias for the same thing) prints each route's
page size and First Load JS. Watch specifically for regressions on pages that shouldn't need a
large client bundle - most pages here don't render a chart, and Recharts (`recharts`) is the
single biggest dependency in this app.

To see what actually landed in the built output without adding the `@next/bundle-analyzer`
dependency to this project:

```bash
npm run build
ls -la .next/static/chunks | sort -k5 -n -r | head -20   # largest chunks, biggest first
grep -rl "recharts" .next/static/chunks/*.js              # confirm which chunks include it
```

Recharts should only show up in a handful of chunks (the dynamically-imported chart components -
see `next/dynamic(..., { ssr: false })` in the callers of `PriceChart`/
`PortfolioValuationHistoryChart`/`DashboardPortfolioChart`), not in the main/shared bundle every
page loads. If you want a full interactive treemap instead of grepping chunk files by hand,
`npx @next/bundle-analyzer` can be run as a one-off without adding it to `package.json` - see that
package's own README for the `next.config.ts` wrapper it needs.
