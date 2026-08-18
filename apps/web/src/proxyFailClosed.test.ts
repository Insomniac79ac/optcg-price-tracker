import { NextResponse } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GUARD_EVALUATED_HEADER } from "@/lib/proxyGuard";

// How `auth()` should behave for the case under test. Set before importing
// the proxy, which captures the wrapper at module scope.
type AuthMode =
  | { mode: "session"; session: unknown }
  | { mode: "throws"; error: Error }
  // Auth.js's observed behaviour on a configuration failure: it logs, never
  // runs the callback, and lets the request continue unmarked.
  | { mode: "swallows" };

let authMode: AuthMode = { mode: "session", session: null };

vi.mock("@/lib/auth", () => ({
  auth: (handler: (req: { nextUrl: URL; auth: unknown }) => NextResponse) => {
    return async (request: Request) => {
      if (authMode.mode === "throws") throw authMode.error;
      if (authMode.mode === "swallows") return NextResponse.next();
      return handler({ nextUrl: new URL(request.url), auth: authMode.session });
    };
  },
}));

const ORIGIN = "https://atlas.example.com";
const proxyModule = await import("./proxy");
const proxy = proxyModule.default as (
  request: Request,
  event?: unknown,
) => Promise<NextResponse>;

async function get(pathname: string) {
  return proxy(new Request(`${ORIGIN}${pathname}`), undefined);
}

/** Where a redirect response points, relative to the origin. */
const location = (res: NextResponse) =>
  (res.headers.get("location") ?? "").replace(ORIGIN, "");

/** A rewrite to the not-found path shows up as an internal rewrite header. */
const isNotFoundRewrite = (res: NextResponse) =>
  (res.headers.get("x-middleware-rewrite") ?? "").includes("__not-found__");

const PROTECTED_TOOLS = [
  "/search",
  "/market/signals",
  "/market/opportunities",
  "/market/signal-events",
  "/market/report",
  "/dashboard",
];

beforeEach(() => {
  authMode = { mode: "session", session: null };
});

describe("normal signed-out visitor", () => {
  it("gets the branded not-found for the legacy card route", async () => {
    const res = await get("/cards/1");
    expect(isNotFoundRewrite(res)).toBe(true);
    expect(location(res)).toBe("");
  });

  it.each(PROTECTED_TOOLS)("is redirected to sign-in from %s", async (path) => {
    const res = await get(path);
    expect(location(res)).toBe(`/sign-in?callbackUrl=${encodeURIComponent(path)}`);
  });

  it("is redirected to the admin login from an admin route", async () => {
    expect(location(await get("/admin/logs"))).toBe("/admin/login?callbackUrl=%2Fadmin%2Flogs");
  });
});

describe("signed-in visitor", () => {
  beforeEach(() => {
    authMode = { mode: "session", session: { user: { email: "collector@example.com" } } };
  });

  it("reaches protected tools", async () => {
    for (const path of PROTECTED_TOOLS) {
      const res = await get(path);
      expect(location(res), path).toBe("");
      expect(isNotFoundRewrite(res), path).toBe(false);
    }
  });

  it("keeps the existing legacy card-keyed behaviour", async () => {
    const res = await get("/cards/1");
    expect(isNotFoundRewrite(res)).toBe(false);
    expect(location(res)).toBe("");
  });
});

describe("auth evaluation throws (missing or malformed AUTH_SECRET)", () => {
  beforeEach(() => {
    authMode = { mode: "throws", error: new Error("MissingSecret: Please define a `secret`") };
  });

  it.each(PROTECTED_TOOLS)("keeps %s unavailable", async (path) => {
    const res = await get(path);
    expect(location(res), path).toBe(`/sign-in?callbackUrl=${encodeURIComponent(path)}`);
  });

  it("keeps the legacy card route on its own not-found policy", async () => {
    expect(isNotFoundRewrite(await get("/cards/1"))).toBe(true);
  });

  it("keeps admin routes unavailable", async () => {
    expect(location(await get("/admin/logs"))).toBe("/admin/login?callbackUrl=%2Fadmin%2Flogs");
  });

  it("never leaks the failure reason to the browser", async () => {
    const res = await get("/market/signals");
    const serialised = JSON.stringify([...res.headers.entries()]);
    expect(serialised).not.toMatch(/MissingSecret/i);
    expect(serialised).not.toMatch(/secret/i);
  });
});

describe("auth hands the guard a truthy value that is not a session", () => {
  // Exactly what a missing AUTH_SECRET produced: the callback ran, so the
  // response carried the guard marker, and a Boolean(req.auth) test read it as
  // "signed in" and served protected content.
  beforeEach(() => {
    authMode = { mode: "session", session: { error: "MissingSecret" } };
  });

  it.each(PROTECTED_TOOLS)("keeps %s unavailable", async (path) => {
    expect(location(await get(path)), path).toBe(
      `/sign-in?callbackUrl=${encodeURIComponent(path)}`,
    );
  });

  it("still answers not-found for the legacy card route", async () => {
    expect(isNotFoundRewrite(await get("/cards/1"))).toBe(true);
  });
});

describe("auth silently lets the request through without deciding", () => {
  beforeEach(() => {
    authMode = { mode: "swallows" };
  });

  it.each(PROTECTED_TOOLS)("still keeps %s unavailable", async (path) => {
    const res = await get(path);
    expect(location(res), path).toBe(`/sign-in?callbackUrl=${encodeURIComponent(path)}`);
  });

  it("still answers not-found for the legacy card route", async () => {
    expect(isNotFoundRewrite(await get("/cards/1"))).toBe(true);
  });

  it("is what the evaluation marker exists to catch", async () => {
    // An unmarked pass-through is indistinguishable from a real "allow"
    // without the marker - which is precisely the fail-open hazard.
    const unmarked = NextResponse.next();
    expect(unmarked.headers.get(GUARD_EVALUATED_HEADER)).toBeNull();
  });
});

describe("public routes are unaffected by an auth outage", () => {
  // They are not in config.matcher, so the guard never runs for them. Asserted
  // here so the fail-closed change can never be read as making them private.
  it("does not match any public collector route", () => {
    const matcher = proxyModule.config.matcher;
    for (const path of ["/", "/cards", "/market/movers", "/prints/1"]) {
      const matched = matcher.some((entry) => {
        const prefix = entry.replace(/\/:.*$/, "");
        return entry.includes(":path*")
          ? path === prefix || path.startsWith(`${prefix}/`)
          : path.startsWith(`${prefix}/`) && path.length > prefix.length + 1;
      });
      expect(matched, `${path} must stay public`).toBe(false);
    }
  });
});
