import { describe, expect, it } from "vitest";

import {
  ADMIN_MATCHER,
  FULL_MATCHER,
  LEGACY_CARD_DETAIL_MATCHER,
  NOT_FOUND_REWRITE_PATH,
  PROTECTED_MATCHER,
  failClosedOutcome,
  guardDidEvaluate,
  guardOutcome,
  hasCollectorSession,
  isLegacyCardDetailPath,
} from "./proxyGuard";

/** Next's matcher syntax, reduced to the prefix it actually guards:
 * "/collection/:path*" -> "/collection", "/cards/:id+" -> "/cards". */
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
  it.each(["/", "/cards", "/market/movers", "/prints/1", "/prints/13", "/sign-in"])(
    "%s is not guarded",
    (pathname) => {
      expect(isMatched(pathname)).toBe(false);
    },
  );

  it("guards the legacy card detail route but never the catalogue", () => {
    expect(isMatched("/cards")).toBe(false);
    expect(isMatched("/cards/1")).toBe(true);
    expect(isMatched("/cards/999")).toBe(true);
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

describe("isLegacyCardDetailPath", () => {
  it.each(["/cards/1", "/cards/999", "/cards/1/extra"])("is true for %s", (p) => {
    expect(isLegacyCardDetailPath(p)).toBe(true);
  });

  it.each(["/cards", "/prints/1", "/", "/market/movers"])("is false for %s", (p) => {
    expect(isLegacyCardDetailPath(p)).toBe(false);
  });
});

describe("the not-found rewrite target", () => {
  it("is not itself guarded, so the rewrite cannot re-enter the guard", () => {
    expect(isMatched(NOT_FOUND_REWRITE_PATH)).toBe(false);
  });

  it("sits outside /cards, whose dynamic segment would otherwise catch it", () => {
    expect(isLegacyCardDetailPath(NOT_FOUND_REWRITE_PATH)).toBe(false);
  });

  it("is a root-relative path", () => {
    expect(NOT_FOUND_REWRITE_PATH.startsWith("/")).toBe(true);
  });
});

describe("FULL_MATCHER composition", () => {
  it("is the three groups in order", () => {
    expect(FULL_MATCHER).toEqual([
      ...PROTECTED_MATCHER,
      ...LEGACY_CARD_DETAIL_MATCHER,
      ...ADMIN_MATCHER,
    ]);
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

  it("answers not-found for the legacy card detail route", () => {
    expect(guardOutcome("/cards/1", false)).toEqual({ kind: "not-found" });
    expect(guardOutcome("/cards/999", false)).toEqual({ kind: "not-found" });
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
    // Not one blanket response: the legacy card route stays not-found, and
    // ordinary protected tools stay a sign-in redirect.
    expect(failClosedOutcome("/cards/1")).toEqual({ kind: "not-found" });
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
