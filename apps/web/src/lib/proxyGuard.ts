// Pure, framework-agnostic pieces of the request guard in ../../proxy.ts,
// split out so they can be unit tested without mocking Next.js's request
// internals or next-auth's `auth()` wrapper - see proxy.ts for how these are
// actually wired into the request pipeline.

// Routes that expose the signed-in caller's own data (portfolio, wishlist,
// grading submissions, personal analytics). Public catalogue and Market
// Index routes (/, /search, /cards/*, /market/*) are deliberately excluded -
// see collector-blueprint.pdf Phase 1/3.
export const PROTECTED_MATCHER = [
  "/collection/:path*",
  "/grading/:path*",
  "/wishlist/:path*",
  "/dashboard/:path*",
  "/activity/:path*",
  "/analytics/:path*",
];

// /admin/:path* matches /admin/login too (it's a subpath of /admin) - proxy.ts
// explicitly carves that one path back out at request time (see its comment)
// so the login page itself stays reachable while every other /admin/* route
// gets this same optimistic signed-out redirect. This is only ever an
// *optimistic* check (no session at all -> bounce before the round trip) -
// it does not and cannot check role="admin" itself; a signed-in
// non-admin (collector) session passes proxy fine and is instead safely
// rejected by app/admin/(protected)/layout.tsx, which remains the real
// authorization boundary (see that file's comment for why Proxy must never
// be the sole one).
export const ADMIN_MATCHER = ["/admin/:path*"];

export const FULL_MATCHER = [...PROTECTED_MATCHER, ...ADMIN_MATCHER];

/** Builds the redirect target for a signed-out visitor hitting a protected
 * collector route - always /sign-in (never /market/movers), always
 * same-origin, and always carries the full original pathname + query string
 * so the caller can return exactly where they started. */
export function buildSignInRedirect(origin: string, pathname: string, search: string): URL {
  const signInUrl = new URL("/sign-in", origin);
  signInUrl.searchParams.set("callbackUrl", `${pathname}${search}`);
  return signInUrl;
}

/** Same idea as buildSignInRedirect, for a signed-out visitor hitting a
 * protected /admin/* route - always /admin/login, never /sign-in (the
 * collector-only entry point - see src/app/sign-in/page.tsx). */
export function buildAdminLoginRedirect(origin: string, pathname: string, search: string): URL {
  const adminLoginUrl = new URL("/admin/login", origin);
  adminLoginUrl.searchParams.set("callbackUrl", `${pathname}${search}`);
  return adminLoginUrl;
}
