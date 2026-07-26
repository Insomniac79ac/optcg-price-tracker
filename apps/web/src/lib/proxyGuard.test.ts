import { describe, expect, it } from "vitest";

import { buildSignInRedirect, PROTECTED_MATCHER } from "./proxyGuard";

describe("PROTECTED_MATCHER", () => {
  it("covers every collector route that exposes personal data", () => {
    expect(PROTECTED_MATCHER).toEqual([
      "/collection/:path*",
      "/grading/:path*",
      "/wishlist/:path*",
      "/dashboard/:path*",
      "/activity/:path*",
      "/analytics/:path*",
    ]);
  });

  it("does not include /admin - that boundary lives in app/admin/layout.tsx, not proxy", () => {
    expect(PROTECTED_MATCHER.some((pattern) => pattern.startsWith("/admin"))).toBe(false);
  });

  it("does not automatically protect public catalogue or Market Index routes", () => {
    const publicPrefixes = ["/search", "/cards", "/market"];
    for (const prefix of publicPrefixes) {
      expect(PROTECTED_MATCHER.some((pattern) => pattern.startsWith(prefix))).toBe(false);
    }
  });
});

describe("buildSignInRedirect", () => {
  it("targets /sign-in, never /market/movers", () => {
    const url = buildSignInRedirect("https://staging.example.com", "/collection", "");
    expect(url.pathname).toBe("/sign-in");
  });

  it("stays on the same origin as the incoming request", () => {
    const url = buildSignInRedirect("https://staging.example.com", "/wishlist", "");
    expect(url.origin).toBe("https://staging.example.com");
  });

  it("preserves the full pathname and query string as callbackUrl", () => {
    const url = buildSignInRedirect(
      "https://staging.example.com",
      "/collection/vault",
      "?status=graded&sort=value",
    );
    expect(url.searchParams.get("callbackUrl")).toBe("/collection/vault?status=graded&sort=value");
  });

  it("preserves a bare path with no query string", () => {
    const url = buildSignInRedirect("https://staging.example.com", "/activity", "");
    expect(url.searchParams.get("callbackUrl")).toBe("/activity");
  });
});
