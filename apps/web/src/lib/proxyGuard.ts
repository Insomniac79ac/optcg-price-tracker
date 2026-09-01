// Pure, framework-agnostic pieces of the request guard in ../../proxy.ts,
// split out so they can be unit tested without mocking Next.js's request
// internals or next-auth's `auth()` wrapper - see proxy.ts for how these are
// actually wired into the request pipeline.

// Routes that expose the signed-in caller's own data (portfolio, wishlist,
// grading submissions, personal analytics), plus the internal market-analytics
// surfaces that are not part of the collector MVP.
//
// The public collector product is exactly / and /cards, plus /prints/:id -
// those are deliberately absent here and must stay reachable while signed
// out. So is /market/movers, which since 2026-08-19 is a temporary redirect
// into /cards?sort=index_desc rather than a page: guarding it would bounce a
// signed-out visitor to /sign-in on the way to a public catalogue.
//
// Added 2026-08-18 for the MVP launch cleanup:
//   /search           - a signed-in "command center" over collection,
//                       wishlist, grading, notes and activity. Linked only
//                       from /dashboard, which is itself protected.
//   /market/signals, /market/opportunities, /market/signal-events,
//   /market/report    - analyst and data-health surfaces (signal counts,
//                       buy/sell scoring, data-quality warnings, stale
//                       intelligence reports). Unfinished for public use and
//                       at odds with the Market Index's own "not a buy or
//                       sell recommendation" framing.
// Note /market/movers is NOT matched: :path* would not match the bare
// /market/signals either, so each entry is listed with its own :path* form
// and /market/movers simply never appears.
export const PROTECTED_MATCHER = [
  "/collection/:path*",
  "/grading/:path*",
  "/wishlist/:path*",
  "/dashboard/:path*",
  "/activity/:path*",
  "/analytics/:path*",
  "/search/:path*",
  "/market/signals/:path*",
  "/market/opportunities/:path*",
  "/market/signal-events/:path*",
  "/market/report/:path*",
];

// /cards/:id was gated here until 2026-09-01, because the page rendered the
// legacy `cards` row's own name and price - and those rows disagree with
// canonical print identity (legacy OP01-001 is named "Monkey D. Luffy"; the
// canonical card is Roronoa Zoro), so a signed-out visitor would have been
// shown a wrong-card page.
//
// That page no longer exists. /cards/:id is now a printing chooser: its
// identity is resolved from the canonical print records for the card code
// (see resolveCanonicalPrintIdentity), it renders no card-level price, rarity
// or variant, and every printing links to its own print-scoped /prints/:id.
// There is nothing left on it that could contradict the catalogue, so it
// belongs with /, /cards and /prints/:id as public collector surface.
//
// Its user-specific panels are NOT made public by this: they are gated in the
// page itself on a real session, and every endpoint behind them independently
// answers 401 without a bearer token. The guard was never their authorization.

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

/** Whether a path is the admin login page, which must stay reachable while
 * signed out (it is the way back in) - including when auth evaluation itself
 * is broken, where it is the only page that can explain anything. */
export function isAdminLoginPath(pathname: string): boolean {
  return pathname === "/admin/login" || pathname.startsWith("/admin/login/");
}

/** What the guard should do with a matched request. Route policy lives here,
 * as a pure function, so the request-time wiring in proxy.ts has no branching
 * of its own to get wrong. */
export type GuardOutcome =
  | { kind: "allow" }
  | { kind: "redirect-sign-in" }
  | { kind: "redirect-admin-login" };

/** The policy for one matched path.
 *
 * `hasSession` is the ONLY input beyond the path: a request with no session
 * and a request whose authentication could not be evaluated at all are
 * deliberately handed the same conservative answer (see failClosedOutcome).
 * The two remain distinct at the call site, which is where the distinction
 * actually matters.
 */
export function guardOutcome(pathname: string, hasSession: boolean): GuardOutcome {
  if (pathname.startsWith("/admin")) {
    if (isAdminLoginPath(pathname)) return { kind: "allow" };
    return hasSession ? { kind: "allow" } : { kind: "redirect-admin-login" };
  }
  return hasSession ? { kind: "allow" } : { kind: "redirect-sign-in" };
}

/** The outcome when authentication could not be evaluated - a missing or
 * malformed AUTH_SECRET, a provider misconfiguration, anything that makes
 * auth() throw.
 *
 * Such a request must never be treated as authenticated, so this is exactly
 * the signed-out policy: a sign-in redirect for a collector route and the
 * admin login for an /admin route, rather than every path collapsing to one
 * response. It can never return "allow" for protected content - the only path
 * it lets through is the admin login page, which is not protected content.
 *
 * Public routes are unaffected because they are not matched by the guard at
 * all: an auth outage cannot take the catalogue down.
 */
export function failClosedOutcome(pathname: string): GuardOutcome {
  return guardOutcome(pathname, false);
}

/** Set on every response the guard itself produced.
 *
 * Auth.js's auth() wrapper swallows a configuration failure and lets the
 * request continue - which for a matched route means serving protected
 * content. That is fail-open, and unobservable from inside the callback,
 * because the callback simply never runs. Marking the responses the callback
 * DOES produce turns "did the guard actually decide this?" into something the
 * caller can check, and anything unmarked is treated as a failure. */
export const GUARD_EVALUATED_HEADER = "x-cardpirate-guard";

/** True only for a response this guard demonstrably produced. */
export function guardDidEvaluate(headers: { get(name: string): string | null }): boolean {
  return headers.get(GUARD_EVALUATED_HEADER) === "1";
}

/** Whether `auth` really is a resolved session for a signed-in caller.
 *
 * Deliberately not `Boolean(req.auth)`. When Auth.js cannot evaluate a session
 * - a missing or malformed AUTH_SECRET being the case that started this - it
 * logs the failure and still invokes the guard callback with a truthy value
 * that is not a session. Observed on a local `next build && next start` with
 * AUTH_SECRET unset: every guarded route was answered "allow" and served its
 * prerendered page, marker header and all, because a plain truthiness test
 * could not tell that value apart from a real session.
 *
 * So the shape is checked instead: a session is an object carrying a `user`.
 * Anything else - null, undefined, an error, a bare object - is treated as no
 * session, which routes the request into the signed-out (fail-closed) policy.
 */
export function hasCollectorSession(auth: unknown): boolean {
  if (!auth || typeof auth !== "object") return false;
  const user = (auth as { user?: unknown }).user;
  return Boolean(user && typeof user === "object");
}
