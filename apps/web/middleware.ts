import { NextResponse } from "next/server";

import { auth } from "@/lib/auth";

// Only /collection, /grading, and /wishlist require a signed-in user -
// price/market browsing (/cards, /market/*, /dashboard) stays public, and
// /admin/* keeps its own separate ADMIN_TOKEN gate (AdminAuthGate),
// untouched by this middleware.
export default auth((req) => {
  if (!req.auth) {
    const redirectUrl = new URL("/", req.nextUrl.origin);
    redirectUrl.searchParams.set("callbackUrl", req.nextUrl.pathname);
    return NextResponse.redirect(redirectUrl);
  }
});

export const config = {
  matcher: ["/collection/:path*", "/grading/:path*", "/wishlist/:path*"],
};
