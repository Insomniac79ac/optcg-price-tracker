// The public collector surface, in one place, so robots.txt and sitemap.xml
// cannot drift from each other or from what the request guard actually leaves
// reachable (src/lib/proxyGuard.ts).

/** Every route a signed-out visitor is meant to reach and a crawler is meant
 * to index. Deliberately only stable, canonical, parameter-free routes:
 * /prints/:id detail pages are real public pages but enumerating them would
 * mean querying the catalogue at build or request time, which is more
 * machinery than an MVP sitemap needs. They stay crawlable via /cards. */
export const PUBLIC_INDEXABLE_ROUTES = ["/", "/cards", "/market/movers"] as const;

/** Path prefixes a crawler is asked to stay out of: private collector data,
 * the admin surface, internal market analytics, the API proxy routes, and the
 * legacy card-keyed detail route.
 *
 * "/cards/" carries a trailing slash on purpose - it excludes /cards/123 while
 * leaving the public catalogue at /cards allowed. */
export const CRAWLER_DISALLOWED_PREFIXES = [
  "/admin",
  "/api/",
  "/collection",
  "/wishlist",
  "/grading",
  "/dashboard",
  "/activity",
  "/analytics/",
  "/search",
  "/market/signals",
  "/market/opportunities",
  "/market/signal-events",
  "/market/report",
  "/cards/",
  "/sign-in",
] as const;

/** The origin used to build absolute sitemap URLs.
 *
 * Read from NEXT_PUBLIC_SITE_URL so the same build can serve a preview host
 * and a custom domain without baking either into the source. Falls back to the
 * current staging origin rather than throwing: a sitemap with the wrong host
 * is a far smaller problem than a build that fails, and the value is easy to
 * set once a real domain exists. */
export function publicSiteUrl(): string {
  const configured = process.env.NEXT_PUBLIC_SITE_URL?.trim();
  const base = configured || "https://optcg-price-tracker-staging.vercel.app";
  return base.replace(/\/+$/, "");
}
