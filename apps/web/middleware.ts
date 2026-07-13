import { NextResponse } from "next/server";

import { auth } from "@/lib/auth";

// /collection, /grading, /wishlist, and /dashboard require a signed-in user -
// /dashboard is now a personalized overview of the caller's own
// portfolio/wishlist/grading data (plus shared market widgets), not the
// public market-movers browsing page it used to be (that moved to
// /market/movers, which stays public). /admin/* keeps its own separate
// ADMIN_TOKEN gate (AdminAuthGate), untouched by this middleware.
export default auth((req) => {
  if (!req.auth) {
    // NOT "/" - the root page unconditionally redirects to /dashboard,
    // which is itself gated by this same middleware, so bouncing an
    // anonymous visitor back to "/" here would loop forever. Land them on
    // a public page instead.
    const redirectUrl = new URL("/market/movers", req.nextUrl.origin);
    redirectUrl.searchParams.set("callbackUrl", req.nextUrl.pathname);
    return NextResponse.redirect(redirectUrl);
  }
});

export const config = {
  matcher: ["/collection/:path*", "/grading/:path*", "/wishlist/:path*", "/dashboard/:path*"],
};
