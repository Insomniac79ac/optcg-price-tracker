import { describe, expect, it } from "vitest";

import {
  ADMIN_MATCHER,
  FULL_MATCHER,
  PROTECTED_MATCHER,
  failClosedOutcome,
  guardDidEvaluate,
  guardOutcome,
  hasCollectorSession,
} from "./proxyGuard";

/** Next's matcher syntax, reduced to the prefix it actually guards:
 * "/collection/:path*" -> "/collection", "/admin/:path*" -> "/admin". */
const prefixOf = (entry: string) => entry.replace(/\/:.*$/, "");

/** True when Next's matcher would run the guard for `pathname`.
 * ":path*" matches zero or more segments (so it matches the bare prefix too);
 * ":id+" requires at least one. */
function isMatched(pathname: string): boolean {
  return FULL_MATCHER.some((entry) => {
    const prefix = prefixOf(entry);
    if (entry.includes(":path*")) {
      return pathname === prefix || pathname.startsWith(`${prefix}/`);
    }
    return pathname.startsWith(`${prefix}/`) && pathname.length > prefix.length + 1;
  });
}

describe("the public collector surface stays reachable while signed out", () => {
  it.each([
    "/",
    "/cards",
    "/market/movers",
    "/prints/1",
    "/prints/13",
    "/sign-in",
    // Public since 2026-09-01: /cards/:id is a printing chooser carrying no
    // legacy identity or pricing that could contradict the catalogue.
    "/cards/1",
    "/cards/999",
    "/cards/1/extra",
  ])("%s is not guarded", (pathname) => {
    expect(isMatched(pathname)).toBe(false);
  });

  it("G. lets an anonymous visitor through to the card page", () => {
    // The mechanism is that the route is not matched at all, so the guard
    // never runs for it and cannot block a signed-out collector - not that
    // guardOutcome returns "allow" (it is never consulted for this path).
    // Its user-specific panels are gated in the page instead, and every
    // endpoint behind them answers 401 on its own.
    for (const p of ["/cards/1", "/cards/999", "/cards/1/extra"]) {
      expect(isMatched(p), `${p} must not be guarded`).toBe(false);
    }
    expect(FULL_MATCHER.some((e) => e.startsWith("/cards"))).toBe(false);
  });

  it("G. keeps every unrelated protected route protected", () => {
    for (const p of ["/collection", "/wishlist", "/grading", "/dashboard", "/search", "/market/report"]) {
      expect(isMatched(p)).toBe(true);
      expect(guardOutcome(p, false)).toEqual({ kind: "redirect-sign-in" });
      expect(failClosedOutcome(p)).toEqual({ kind: "redirect-sign-in" });
    }
    expect(isMatched("/admin/logs")).toBe(true);
    expect(guardOutcome("/admin/logs", false)).toEqual({ kind: "redirect-admin-login" });
  });
});

describe("internal market analytics are guarded", () => {
  it.each([
    "/market/signals",
    "/market/opportunities",
    "/market/signal-events",
    "/market/report",
  ])("%s is guarded", (pathname) => {
    expect(isMatched(pathname)).toBe(true);
  });

  it("guards their subpaths too", () => {
    expect(isMatched("/market/report/latest")).toBe(true);
    expect(isMatched("/market/signals/42")).toBe(true);
  });

  it("leaves the public Market Index alone", () => {
    expect(isMatched("/market/movers")).toBe(false);
    expect(PROTECTED_MATCHER.map(prefixOf)).not.toContain("/market/movers");
  });
});

describe("/search is guarded", () => {
  it("is not reachable signed out", () => {
    expect(isMatched("/search")).toBe(true);
  });
});

describe("collector-private routes remain guarded", () => {
  it.each([
    "/collection",
    "/collection/vault",
    "/wishlist",
    "/grading",
    "/dashboard",
    "/activity",
    "/analytics/collection",
  ])("%s is guarded", (pathname) => {
    expect(isMatched(pathname)).toBe(true);
  });
});

describe("FULL_MATCHER composition", () => {
  it("is the two groups in order", () => {
    expect(FULL_MATCHER).toEqual([...PROTECTED_MATCHER, ...ADMIN_MATCHER]);
  });

  it("does not guard the card detail route", () => {
    expect(FULL_MATCHER.some((e) => e.startsWith("/cards"))).toBe(false);
  });

  it("has no duplicate entries", () => {
    expect(new Set(FULL_MATCHER).size).toBe(FULL_MATCHER.length);
  });
});

describe("guardOutcome - signed out", () => {
  it("sends normal protected routes to sign-in", () => {
    for (const p of [
      "/search",
      "/market/signals",
      "/market/opportunities",
      "/market/signal-events",
      "/market/report",
      "/dashboard",
      "/collection",
    ]) {
      expect(guardOutcome(p, false), p).toEqual({ kind: "redirect-sign-in" });
    }
  });

  it("sends admin routes to the admin login, but leaves that login reachable", () => {
    expect(guardOutcome("/admin/logs", false)).toEqual({ kind: "redirect-admin-login" });
    expect(guardOutcome("/admin/login", false)).toEqual({ kind: "allow" });
  });
});

describe("guardOutcome - signed in", () => {
  it("allows every matched route through", () => {
    for (const p of ["/search", "/market/report", "/dashboard", "/cards/1", "/admin/logs"]) {
      expect(guardOutcome(p, true), p).toEqual({ kind: "allow" });
    }
  });
});

describe("failClosedOutcome - authentication could not be evaluated", () => {
  it("never allows protected content through", () => {
    for (const p of [
      "/search",
      "/market/signals",
      "/market/opportunities",
      "/market/signal-events",
      "/market/report",
      "/dashboard",
      "/collection",
      "/wishlist",
      "/grading",
      "/activity",
      "/analytics/collection",
      "/cards/1",
      "/admin/logs",
    ]) {
      expect(failClosedOutcome(p).kind, `${p} must not be allowed`).not.toBe("allow");
    }
  });

  it("keeps each route's own established public behaviour", () => {
    // Not one blanket response: an admin route goes to the admin login and
    // ordinary protected tools stay a sign-in redirect.
    expect(failClosedOutcome("/market/signals")).toEqual({ kind: "redirect-sign-in" });
    expect(failClosedOutcome("/admin/logs")).toEqual({ kind: "redirect-admin-login" });
  });

  it("is exactly the signed-out policy", () => {
    for (const p of ["/search", "/cards/1", "/admin/logs", "/dashboard"]) {
      expect(failClosedOutcome(p)).toEqual(guardOutcome(p, false));
    }
  });

  it("still lets the admin login page render, since it is not protected content", () => {
    expect(failClosedOutcome("/admin/login")).toEqual({ kind: "allow" });
  });
});

describe("guardDidEvaluate", () => {
  const headers = (value: string | null) => ({ get: () => value });

  it("is true only for a response the guard marked", () => {
    expect(guardDidEvaluate(headers("1"))).toBe(true);
  });

  it("is false for an unmarked response - which is what Auth.js returns when it never ran the guard", () => {
    expect(guardDidEvaluate(headers(null))).toBe(false);
    expect(guardDidEvaluate(headers(""))).toBe(false);
    expect(guardDidEvaluate(headers("0"))).toBe(false);
  });
});

describe("hasCollectorSession", () => {
  it("accepts a real resolved session", () => {
    expect(hasCollectorSession({ user: { email: "collector@example.com" } })).toBe(true);
  });

  it("rejects the absence of a session", () => {
    expect(hasCollectorSession(null)).toBe(false);
    expect(hasCollectorSession(undefined)).toBe(false);
  });

  it("rejects a truthy value that is not a session", () => {
    // The case that made the guard fail open: Auth.js could not evaluate the
    // session, logged MissingSecret, and still handed the callback something
    // truthy. Boolean(req.auth) read that as "signed in".
    expect(hasCollectorSession({})).toBe(false);
    expect(hasCollectorSession({ error: "MissingSecret" })).toBe(false);
    expect(hasCollectorSession(new Error("MissingSecret"))).toBe(false);
    expect(hasCollectorSession("session")).toBe(false);
    expect(hasCollectorSession(true)).toBe(false);
    expect(hasCollectorSession(1)).toBe(false);
  });

  it("rejects a session whose user is not an object", () => {
    expect(hasCollectorSession({ user: null })).toBe(false);
    expect(hasCollectorSession({ user: "collector@example.com" })).toBe(false);
  });
});
