import { describe, expect, it } from "vitest";

import {
  ADMIN_MATCHER,
  FULL_MATCHER,
  PROTECTED_MATCHER,
  failClosedOutcome,
  guardDidEvaluate,
  guardOutcome,
  hasCollectorSession,
  hasSession,
  sessionGuardOutcome,
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
    for (const p of ["/collection", "/watchlist", "/analytics/collection"]) {
      expect(isMatched(p)).toBe(true);
      expect(guardOutcome(p, false)).toEqual({ kind: "redirect-sign-in" });
      expect(failClosedOutcome(p)).toEqual({ kind: "redirect-sign-in" });
    }
    expect(isMatched("/admin/logs")).toBe(true);
    expect(guardOutcome("/admin/logs", false)).toEqual({ kind: "redirect-admin-login" });
  });
});

describe("routes deleted in Collector v1 S1 are no longer guarded", () => {
  // They answer permanent redirects from next.config.ts (which run before the
  // proxy) or 404 (/grading), so the matcher no longer lists them.
  it.each([
    "/market/signals",
    "/market/opportunities",
    "/market/signal-events",
    "/market/report",
    "/market/report/latest",
    "/search",
    "/dashboard",
    "/activity",
    "/grading",
  ])("%s is not matched", (pathname) => {
    expect(isMatched(pathname)).toBe(false);
  });
});

describe("the public Market Index", () => {
  it("leaves the public Market Index alone", () => {
    expect(isMatched("/market/movers")).toBe(false);
    expect(PROTECTED_MATCHER.map(prefixOf)).not.toContain("/market/movers");
  });
});

describe("collector-private routes remain guarded", () => {
  it.each([
    "/collection",
    "/collection/vault",
    "/watchlist",
    "/analytics/collection",
    "/analytics/wishlist",
  ])("%s is guarded", (pathname) => {
    expect(isMatched(pathname)).toBe(true);
  });
});

describe("the market landscape is public, the collector analytics beneath it are not", () => {
  // The single most load-bearing distinction in this file, and the one that
  // was actually wrong before Analytics 1A-B: `/analytics/:path*` matched the
  // BARE /analytics as well as its children, so the public market landscape
  // answered 307 to /sign-in (verified at request time against a running dev
  // server, 2026-09-06). `:path+` requires at least one segment, which splits
  // the parent from its children exactly where the product needs it.

  it("leaves the bare /analytics reachable signed out", () => {
    expect(isMatched("/analytics")).toBe(false);
    // Whatever the URL carries, the page itself is still public: query strings
    // are not part of matching, and the landscape keeps all of its state there.
    expect(isMatched("/analytics?basis=source:yuyutei")).toBe(false);
  });

  it("still guards every legacy collector-data leaf beneath it", () => {
    for (const leaf of [
      "/analytics/collection",
      "/analytics/wishlist",
    ]) {
      expect(isMatched(leaf), `${leaf} must stay guarded`).toBe(true);
      expect(guardOutcome(leaf, false)).toEqual({ kind: "redirect-sign-in" });
      expect(failClosedOutcome(leaf)).toEqual({ kind: "redirect-sign-in" });
    }
  });

  it("uses :path+ for analytics and :path* for the routes whose parent is private", () => {
    // The neighbours must NOT be converted along with it: /collection and
    // /watchlist are real pages showing the caller's own data, so their bare
    // parent has to stay matched.
    expect(PROTECTED_MATCHER).toContain("/analytics/:path+");
    expect(PROTECTED_MATCHER).not.toContain("/analytics/:path*");
    for (const parent of ["/collection", "/watchlist"]) {
      expect(PROTECTED_MATCHER).toContain(`${parent}/:path*`);
      expect(isMatched(parent), `${parent} must stay guarded`).toBe(true);
    }
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
    for (const p of ["/collection", "/watchlist", "/analytics/collection"]) {
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
    for (const p of ["/collection", "/analytics/wishlist", "/cards/1", "/admin/logs"]) {
      expect(guardOutcome(p, true), p).toEqual({ kind: "allow" });
    }
  });
});

describe("failClosedOutcome - authentication could not be evaluated", () => {
  it("never allows protected content through", () => {
    for (const p of [
      "/collection",
      "/collection/vault",
      "/watchlist",
      "/analytics/collection",
      "/analytics/wishlist",
      "/cards/1",
      "/admin/logs",
    ]) {
      expect(failClosedOutcome(p).kind, `${p} must not be allowed`).not.toBe("allow");
    }
  });

  it("keeps each route's own established public behaviour", () => {
    // Not one blanket response: an admin route goes to the admin login and
    // ordinary protected tools stay a sign-in redirect.
    expect(failClosedOutcome("/watchlist")).toEqual({ kind: "redirect-sign-in" });
    expect(failClosedOutcome("/admin/logs")).toEqual({ kind: "redirect-admin-login" });
  });

  it("is exactly the signed-out policy", () => {
    for (const p of ["/collection", "/cards/1", "/admin/logs", "/analytics/wishlist"]) {
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

describe("hasSession (the /admin/* shape check)", () => {
  it("accepts a real resolved session of either kind", () => {
    expect(hasSession({ user: { email: "collector@example.com" }, sessionKind: "collector" })).toBe(true);
    expect(hasSession({ user: { email: "admin@example.com" }, sessionKind: "admin" })).toBe(true);
  });

  it("rejects the absence of a session", () => {
    expect(hasSession(null)).toBe(false);
    expect(hasSession(undefined)).toBe(false);
  });

  it("rejects a truthy value that is not a session", () => {
    // The case that made the guard fail open: Auth.js could not evaluate the
    // session, logged MissingSecret, and still handed the callback something
    // truthy. Boolean(req.auth) read that as "signed in".
    expect(hasSession({})).toBe(false);
    expect(hasSession({ error: "MissingSecret" })).toBe(false);
    expect(hasSession(new Error("MissingSecret"))).toBe(false);
    expect(hasSession("session")).toBe(false);
    expect(hasSession(true)).toBe(false);
    expect(hasSession(1)).toBe(false);
  });

  it("rejects a session whose user is not an object", () => {
    expect(hasSession({ user: null })).toBe(false);
    expect(hasSession({ user: "collector@example.com" })).toBe(false);
  });
});

describe("hasCollectorSession (Collector v1 S5: collector sessions only)", () => {
  it("accepts a resolved collector session", () => {
    expect(hasCollectorSession({ user: { email: "collector@example.com" }, sessionKind: "collector" })).toBe(true);
  });

  it("rejects admin sessions, active or expired, and sessions without a kind", () => {
    expect(hasCollectorSession({ user: { email: "admin@example.com", role: "admin" }, sessionKind: "admin" })).toBe(false);
    expect(hasCollectorSession({ user: {}, sessionKind: "admin", adminSessionExpired: true })).toBe(false);
    expect(hasCollectorSession({ user: { email: "collector@example.com" } })).toBe(false);
  });

  it("rejects everything hasSession rejects", () => {
    for (const value of [null, undefined, {}, { error: "MissingSecret" }, true, { user: null, sessionKind: "collector" }]) {
      expect(hasCollectorSession(value)).toBe(false);
    }
  });
});

describe("sessionGuardOutcome", () => {
  const collector = { user: { email: "collector@example.com" }, sessionKind: "collector" };
  const admin = { user: { email: "admin@example.com", role: "admin" }, sessionKind: "admin", adminSessionExpired: false };
  const expiredAdmin = { user: { email: "admin@example.com" }, sessionKind: "admin", adminSessionExpired: true };

  it.each(["/collection", "/collection/vault", "/watchlist", "/account", "/analytics/collection"])(
    "gives an admin session the sign-in invite on collector route %s",
    (path) => {
      expect(sessionGuardOutcome(path, admin)).toEqual({ kind: "redirect-sign-in" });
      expect(sessionGuardOutcome(path, expiredAdmin)).toEqual({ kind: "redirect-sign-in" });
      expect(sessionGuardOutcome(path, null)).toEqual({ kind: "redirect-sign-in" });
      expect(sessionGuardOutcome(path, collector)).toEqual({ kind: "allow" });
    },
  );

  it("keeps the admin routes on any session, with the expired-admin redirect", () => {
    expect(sessionGuardOutcome("/admin/logs", admin)).toEqual({ kind: "allow" });
    expect(sessionGuardOutcome("/admin/logs", expiredAdmin)).toEqual({ kind: "redirect-admin-login", expired: true });
    expect(sessionGuardOutcome("/admin/logs", null)).toEqual({ kind: "redirect-admin-login" });
    expect(sessionGuardOutcome("/admin/login", null)).toEqual({ kind: "allow" });
    // A collector passes the optimistic proxy; the admin layout rejects it.
    expect(sessionGuardOutcome("/admin/logs", collector)).toEqual({ kind: "allow" });
  });

  it("guards /account like the other collector routes", () => {
    expect(PROTECTED_MATCHER).toContain("/account/:path*");
  });
});
