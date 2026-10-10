import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

const { getAdminIdentityForRouteHandler } = vi.hoisted(() => ({
  getAdminIdentityForRouteHandler: vi.fn(),
}));
vi.mock("@/lib/adminSession", () => ({ getAdminIdentityForRouteHandler }));

import { PATCH } from "./[id]/route";
import { POST as dismiss } from "./[id]/dismiss/route";
import { POST as resolve } from "./[id]/resolve/route";
import { POST as watch } from "./[id]/watch/route";

const ADMIN_IDENTITY = { id: "staging-admin", email: "admin@example.com" };
const params = { params: Promise.resolve({ id: "42" }) };

const WRITES = [
  { name: "PATCH", handler: PATCH, method: "PATCH", path: "/market/signal-events/42", body: '{"status":"watching"}' },
  { name: "dismiss", handler: dismiss, method: "POST", path: "/market/signal-events/42/dismiss", body: undefined },
  { name: "watch", handler: watch, method: "POST", path: "/market/signal-events/42/watch", body: undefined },
  { name: "resolve", handler: resolve, method: "POST", path: "/market/signal-events/42/resolve", body: undefined },
];

function req(method: string, body?: string, headers?: Record<string, string>): NextRequest {
  return new NextRequest(
    new Request("http://localhost/api/market/signal-events/42", { method, body, headers }),
  );
}

describe("signal-event write proxies are admin-only", () => {
  const originalFetch = global.fetch;
  const originalToken = process.env.ADMIN_TOKEN;

  beforeEach(() => {
    getAdminIdentityForRouteHandler.mockReset();
    process.env.ADMIN_TOKEN = "server-side-secret";
  });

  afterEach(() => {
    global.fetch = originalFetch;
    process.env.ADMIN_TOKEN = originalToken;
  });

  it.each(WRITES)("$name returns 401 and never calls the backend without an admin session", async (w) => {
    getAdminIdentityForRouteHandler.mockResolvedValueOnce(null);
    const fetchSpy = vi.fn();
    global.fetch = fetchSpy;

    const response = await w.handler(
      req(w.method, w.body, { "X-Admin-Token": "caller-supplied" }),
      params,
    );

    expect(response.status).toBe(401);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it.each(WRITES)("$name forwards to the backend with the server-side admin token", async (w) => {
    getAdminIdentityForRouteHandler.mockResolvedValueOnce(ADMIN_IDENTITY);
    const fetchSpy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 42, status: "watching" }), { status: 200 }),
    );
    global.fetch = fetchSpy;

    const response = await w.handler(req(w.method, w.body), params);

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ id: 42, status: "watching" });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url).endsWith(w.path)).toBe(true);
    expect(init.method).toBe(w.method);
    expect(init.headers["X-Admin-Token"]).toBe("server-side-secret");
    if (w.body !== undefined) expect(init.body).toBe(w.body);
  });
});
