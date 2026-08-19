import { NextResponse } from "next/server";

import { auth } from "@/lib/auth";
import {
  GUARD_EVALUATED_HEADER,
  NOT_FOUND_REWRITE_PATH,
  buildAdminLoginRedirect,
  buildSignInRedirect,
  failClosedOutcome,
  guardDidEvaluate,
  guardOutcome,
  hasCollectorSession,
  type GuardOutcome,
} from "@/lib/proxyGuard";

// Next.js 16 renamed the middleware.ts convention to proxy.ts (middleware.ts
// is now deprecated - https://nextjs.org/docs/app/api-reference/file-conventions/proxy).
// This is that migration: same request-guard behaviour, new file/export name.
//
// Lives at src/proxy.ts, not apps/web/proxy.ts - Next.js's docs say the file
// belongs "at the same level as pages or app", and this project's app
// directory is src/app, not app. Placing it at the package root instead
// compiled without error and even showed up as "ƒ Proxy (Middleware)" in
// the build summary, but silently never ran at request time - confirmed via
// a local `next build && next start` repro (a hand-rolled proxy with no
// auth logic, just a response header, never appeared on any response) while
// diagnosing why staging's /collection etc. weren't redirecting.
//
// /collection, /grading, /wishlist, /dashboard, /activity, and /analytics/*
// require a signed-in collector - they expose the caller's own
// portfolio/wishlist/grading/analytics data. As of the 2026-08-18 MVP launch
// cleanup /search and the internal market-analytics routes (/market/signals,
// /market/opportunities, /market/signal-events, /market/report) join them,
// and /cards/:id+ is matched to answer not-found rather than redirect.
//
// The public collector product - /, /cards and /prints/:id - is deliberately
// NOT matched here and stays reachable while signed out. /market/movers is
// unmatched for the same reason: it is a temporary redirect into
// /cards?sort=index_desc (tranche 1A), and a public redirect must not be
// bounced through /sign-in.
//
// A signed-out visitor is sent to /sign-in (never /market/movers) with the
// full original path + query preserved as callbackUrl - see
// src/lib/proxyGuard.ts for the redirect construction and
// src/app/sign-in/page.tsx for how callbackUrl is validated before use.
//
// /admin/* gets the same *optimistic* treatment (redirect to /admin/login
// instead of /sign-in), with /admin/login itself carved back out below so
// it stays reachable while signed out. This is explicitly not the real
// admin authorization boundary - it only checks "is there any session at
// all", never role="admin" - and per Auth.js's own guidance, Proxy must
// never be the *only* authorization boundary for a protected resource. The
// real, server-side boundary for the whole admin route group is
// app/admin/(protected)/layout.tsx (requireAdminSession()), which also
// rejects a signed-in-but-non-admin (collector) session that this check
// alone would let through. Route Handlers get their own independent check
// too (see src/lib/adminProxy.ts) - proxy is purely a fast, optimistic
// UX redirect layered on top of both.
/** Turn a policy decision into the response that carries it out. */
function toResponse(outcome: GuardOutcome, origin: string, pathname: string, search: string) {
  switch (outcome.kind) {
    case "redirect-admin-login":
      return NextResponse.redirect(buildAdminLoginRedirect(origin, pathname, search));
    case "redirect-sign-in":
      return NextResponse.redirect(buildSignInRedirect(origin, pathname, search));
    case "not-found":
      return NextResponse.rewrite(new URL(NOT_FOUND_REWRITE_PATH, origin));
    case "allow":
      return NextResponse.next();
  }
}

// The guard proper. Every response it returns is marked, so the wrapper below
// can tell a decision this made from a request Auth.js let through without
// ever running it.
const evaluate = auth((req) => {
  const { pathname, search, origin } = req.nextUrl;
  const response = toResponse(
    guardOutcome(pathname, hasCollectorSession(req.auth)),
    origin,
    pathname,
    search,
  );
  response.headers.set(GUARD_EVALUATED_HEADER, "1");
  return response;
});

// Fail closed.
//
// auth() evaluates the session, and it can fail for reasons that have nothing
// to do with the caller: a missing AUTH_SECRET, a malformed one, a provider
// misconfiguration. Auth.js logs such a failure and lets the request continue,
// which on a matched route means serving protected content to anyone - the
// deployment-config hazard this wrapper exists to remove. Confirmed locally:
// with AUTH_SECRET unset every guarded route served normally.
//
// So a request is allowed through only when the guard demonstrably decided it
// was allowed. Anything else - a thrown error, or a response the guard never
// marked - falls back to the signed-out policy for that route. No internal
// error detail reaches the browser; the visitor sees the same sign-in redirect
// or not-found page a signed-out visitor would.
export default async function proxy(
  request: Parameters<typeof evaluate>[0],
  event: Parameters<typeof evaluate>[1],
) {
  const { pathname, search, origin } = new URL(request.url);
  try {
    const response = await evaluate(request, event);
    if (response && guardDidEvaluate(response.headers)) {
      return response;
    }
  } catch {
    // Swallowed on purpose - the reason is a server concern, and the response
    // below is the same one a signed-out visitor gets either way.
  }
  return toResponse(failClosedOutcome(pathname), origin, pathname, search);
}

// Next.js statically parses `config.matcher` at build time - it must be a
// literal array in this file and can't be an imported constant (Turbopack
// build fails otherwise: "can't recognize the exported `config` field").
// This MUST stay identical to src/lib/proxyGuard.ts's FULL_MATCHER (the
// concatenation of PROTECTED_MATCHER and ADMIN_MATCHER) - proxy.test.ts
// asserts that equality so the two can't silently drift.
export const config = {
  matcher: [
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
    "/cards/:id+",
    "/admin/:path*",
  ],
};
