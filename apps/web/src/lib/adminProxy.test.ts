import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

const { getAdminIdentityForRouteHandler } = vi.hoisted(() => ({
  getAdminIdentityForRouteHandler: vi.fn(),
}));
vi.mock("@/lib/adminSession", () => ({ getAdminIdentityForRouteHandler }));

import { adminAuthHeaders, proxyAdminJson, requireAdminOrResponse } from "./adminProxy";

const ADMIN_IDENTITY = { id: "staging-admin", email: "admin@example.com" };

function req(url: string, init?: RequestInit): NextRequest {
  return new NextRequest(new Request(url, init));
}

describe("requireAdminOrResponse", () => {
  it("returns the identity for a valid admin session", async () => {
    getAdminIdentityForRouteHandler.mockResolvedValueOnce(ADMIN_IDENTITY);
    const result = await requireAdminOrResponse();
    expect(result).toEqual({ identity: ADMIN_IDENTITY });
  });

  it("returns a 401 response (never throws) when there is no admin session", async () => {
    getAdminIdentityForRouteHandler.mockResolvedValueOnce(null);
    const result = await requireAdminOrResponse();
    expect("response" in result).toBe(true);
    if ("response" in result) {
      expect(result.response.status).toBe(401);
    }
  });
});

describe("adminAuthHeaders", () => {
  const originalToken = process.env.ADMIN_TOKEN;
  afterEach(() => {
    process.env.ADMIN_TOKEN = originalToken;
  });

  it("reads ADMIN_TOKEN from process.env, server-side only", () => {
    process.env.ADMIN_TOKEN = "server-side-secret";
    expect(adminAuthHeaders()).toEqual({ "X-Admin-Token": "server-side-secret" });
  });

  it("returns no header when ADMIN_TOKEN is unset", () => {
    delete process.env.ADMIN_TOKEN;
    expect(adminAuthHeaders()).toEqual({});
  });
});

describe("proxyAdminJson", () => {
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

  it("returns 401 and never calls fetch when there is no admin session", async () => {
    getAdminIdentityForRouteHandler.mockResolvedValueOnce(null);
    const fetchSpy = vi.fn();
    global.fetch = fetchSpy;

    const res = await proxyAdminJson(req("http://localhost/api/admin/cache/status"), "/admin/cache/status");

    expect(res.status).toBe(401);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("returns 401 and never calls fetch for a signed-in non-admin (collector) session", async () => {
    // getAdminIdentityForRouteHandler itself already encodes "collector
    // session -> null" (see adminSession.test.ts) - this asserts the proxy
    // helper correctly treats that null the same as signed-out.
    getAdminIdentityForRouteHandler.mockResolvedValueOnce(null);
    const fetchSpy = vi.fn();
    global.fetch = fetchSpy;

    const res = await proxyAdminJson(req("http://localhost/api/admin/cards"), "/admin/cards");

    expect(res.status).toBe(401);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("injects the server-side ADMIN_TOKEN and ignores any caller-supplied X-Admin-Token header", async () => {
    getAdminIdentityForRouteHandler.mockResolvedValueOnce(ADMIN_IDENTITY);
    const fetchSpy = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    global.fetch = fetchSpy;

    await proxyAdminJson(
      req("http://localhost/api/admin/cache/status", {
        headers: { "x-admin-token": "attacker-supplied-value" },
      }),
      "/admin/cache/status",
    );

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe("http://api:8000/admin/cache/status");
    expect(init.headers["X-Admin-Token"]).toBe("server-side-secret");
  });

  it("forwards a POST body and sets Content-Type", async () => {
    getAdminIdentityForRouteHandler.mockResolvedValueOnce(ADMIN_IDENTITY);
    const fetchSpy = vi.fn().mockResolvedValue(new Response('{"ok":true}', { status: 200 }));
    global.fetch = fetchSpy;

    await proxyAdminJson(
      req("http://localhost/api/admin/cards/merge", {
        method: "POST",
        body: JSON.stringify({ from: 1, to: 2 }),
      }),
      "/admin/cards/merge",
    );

    const [, init] = fetchSpy.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ from: 1, to: 2 }));
    expect(init.headers["Content-Type"]).toBe("application/json");
  });

  it("does not forward a body for GET", async () => {
    getAdminIdentityForRouteHandler.mockResolvedValueOnce(ADMIN_IDENTITY);
    const fetchSpy = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    global.fetch = fetchSpy;

    await proxyAdminJson(req("http://localhost/api/admin/cache/status"), "/admin/cache/status");

    const [, init] = fetchSpy.mock.calls[0];
    expect(init.body).toBeUndefined();
    expect(init.headers["Content-Type"]).toBeUndefined();
  });

  it("uses emptyBodyFallback when the caller sent no body", async () => {
    getAdminIdentityForRouteHandler.mockResolvedValueOnce(ADMIN_IDENTITY);
    const fetchSpy = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    global.fetch = fetchSpy;

    await proxyAdminJson(
      req("http://localhost/api/admin/backup/export/job", { method: "POST" }),
      "/admin/backup/export/job",
      { emptyBodyFallback: "{}" },
    );

    const [, init] = fetchSpy.mock.calls[0];
    expect(init.body).toBe("{}");
  });

  it("returns 502 without leaking ADMIN_TOKEN when the backend is unreachable", async () => {
    getAdminIdentityForRouteHandler.mockResolvedValueOnce(ADMIN_IDENTITY);
    global.fetch = vi.fn().mockRejectedValue(new Error("connection refused"));

    const res = await proxyAdminJson(req("http://localhost/api/admin/cache/status"), "/admin/cache/status");
    const body = await res.json();

    expect(res.status).toBe(502);
    expect(JSON.stringify(body)).not.toContain("server-side-secret");
  });

  it("relays the backend's JSON response and status code", async () => {
    getAdminIdentityForRouteHandler.mockResolvedValueOnce(ADMIN_IDENTITY);
    global.fetch = vi.fn().mockResolvedValue(new Response('{"enabled":true}', { status: 200 }));

    const res = await proxyAdminJson(req("http://localhost/api/admin/cache/status"), "/admin/cache/status");
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(body).toEqual({ enabled: true });
  });
});
