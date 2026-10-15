// Permanent (308) redirects for the pages deleted in Collector v1 S1
// (2026-10-13; docs/agent/plans/collector-v1/PLAN.md §F) and S8 (2026-10-15:
// the legacy collection and wishlist pages, PLAN §E3 and Q6). Wired into
// next.config.ts `redirects()`, which Next.js evaluates before the proxy, so
// a signed-out visitor is redirected rather than bounced through /sign-in.
//
// `:path*` matches zero or more segments, so each entry covers the bare page
// and any subpath (/market/report/latest, /analytics/digest/reports, ...).
// Next.js passes the query string through, so /search?q=luffy lands on
// /cards?q=luffy.
//
// /grading and /admin/market-workflow-runs have no successor and are
// deliberately absent: they answer 404.
export const LEGACY_REDIRECT_TARGETS: Readonly<Record<string, string>> = {
  "/analytics/buy-decisions": "/collection",
  "/analytics/sell-decisions": "/collection",
  "/analytics/portfolio-risk": "/collection",
  "/analytics/grading": "/collection",
  "/analytics/digest": "/collection",
  "/dashboard": "/collection",
  "/activity": "/collection",
  "/market/signals": "/analytics",
  "/market/signal-events": "/analytics",
  "/market/opportunities": "/analytics",
  "/market/report": "/analytics",
  "/search": "/cards",
  // S8: the legacy collection and wishlist pages. The wishlist is now the
  // watchlist; the old vault and collection analytics fold into /collection.
  "/collection/vault": "/collection",
  "/analytics/collection": "/collection",
  "/wishlist": "/watchlist",
  "/analytics/wishlist": "/watchlist",
};

export function legacyRedirects() {
  return Object.entries(LEGACY_REDIRECT_TARGETS).map(([from, destination]) => ({
    source: `${from}/:path*`,
    destination,
    permanent: true as const,
  }));
}
