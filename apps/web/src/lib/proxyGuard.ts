// Pure, framework-agnostic pieces of the request guard in ../../proxy.ts,
// split out so they can be unit tested without mocking Next.js's request
// internals or next-auth's `auth()` wrapper - see proxy.ts for how these are
// actually wired into the request pipeline.

// Routes that expose the signed-in caller's own data (portfolio, wishlist,
// grading submissions, personal analytics). Public catalogue and Market
// Index routes (/, /search, /cards/*, /market/*) are deliberately excluded -
// see collector-blueprint.pdf Phase 1/3. /admin/* is also deliberately
// excluded: the admin boundary lives in app/admin/layout.tsx, not here - see
// that file's comment for why Proxy must not be the sole authorization
// boundary for admin access.
export const PROTECTED_MATCHER = [
  "/collection/:path*",
  "/grading/:path*",
  "/wishlist/:path*",
  "/dashboard/:path*",
  "/activity/:path*",
  "/analytics/:path*",
];

/** Builds the redirect target for a signed-out visitor hitting a protected
 * route - always /sign-in (never /market/movers), always same-origin, and
 * always carries the full original pathname + query string so the caller
 * can return exactly where they started. */
export function buildSignInRedirect(origin: string, pathname: string, search: string): URL {
  const signInUrl = new URL("/sign-in", origin);
  signInUrl.searchParams.set("callbackUrl", `${pathname}${search}`);
  return signInUrl;
}
