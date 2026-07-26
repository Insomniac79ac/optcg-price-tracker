import { NextResponse } from "next/server";

import { auth } from "@/lib/auth";
import { buildSignInRedirect } from "@/lib/proxyGuard";

// Next.js 16 renamed the middleware.ts convention to proxy.ts (middleware.ts
// is now deprecated - https://nextjs.org/docs/app/api-reference/file-conventions/proxy).
// This is that migration: same request-guard behaviour, new file/export name.
//
// /collection, /grading, /wishlist, /dashboard, /activity, and /analytics/*
// require a signed-in collector - they expose the caller's own
// portfolio/wishlist/grading/analytics data. Public catalogue and Market
// Index routes (/, /search, /cards/*, /market/*) are deliberately NOT
// matched here.
//
// A signed-out visitor is sent to /sign-in (never /market/movers) with the
// full original path + query preserved as callbackUrl - see
// src/lib/proxyGuard.ts for the redirect construction and
// src/app/sign-in/page.tsx for how callbackUrl is validated before use.
//
// /admin/* is intentionally NOT handled here. Per Auth.js's own guidance,
// Proxy must never be the only authorization boundary for a protected
// resource - the real, server-side boundary for the whole admin route group
// is app/admin/layout.tsx. Keeping admin logic out of proxy avoids two
// divergent gates for the same routes.
export default auth((req) => {
  if (!req.auth) {
    return NextResponse.redirect(
      buildSignInRedirect(req.nextUrl.origin, req.nextUrl.pathname, req.nextUrl.search),
    );
  }
});

// Next.js statically parses `config.matcher` at build time - it must be a
// literal array in this file and can't be an imported constant (Turbopack
// build fails otherwise: "can't recognize the exported `config` field").
// This MUST stay identical to src/lib/proxyGuard.ts's PROTECTED_MATCHER -
// proxy.test.ts asserts that equality so the two can't silently drift.
export const config = {
  matcher: [
    "/collection/:path*",
    "/grading/:path*",
    "/wishlist/:path*",
    "/dashboard/:path*",
    "/activity/:path*",
    "/analytics/:path*",
  ],
};
