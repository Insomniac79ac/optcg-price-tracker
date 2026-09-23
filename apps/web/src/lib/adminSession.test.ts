import { beforeEach, describe, expect, it, vi } from "vitest";

const { authMock, redirectMock, notFoundMock } = vi.hoisted(() => ({
  authMock: vi.fn(),
  redirectMock: vi.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT:${url}`);
  }),
  notFoundMock: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  }),
}));

let callbackPath = "/admin/source-mapping-proposals/1128?returnTo=%2Fadmin%2Fsource-mapping-proposals%3Fpage%3D4";
vi.mock("next/headers", () => ({ headers: async () => new Headers({ "x-atlas-admin-callback": callbackPath }) }));

vi.mock("@/lib/auth", () => ({ auth: authMock }));
vi.mock("next/navigation", () => ({ redirect: redirectMock, notFound: notFoundMock }));
// The real `server-only` package throws whenever `window` exists - true
// under this project's default jsdom test environment even though this is
// plainly a server-side unit test, not a rendered component. Stub it out
// rather than fight the environment.
vi.mock("server-only", () => ({}));

import { getAdminIdentityForRouteHandler, requireAdminSession } from "./adminSession";
import { proxyAdminJson } from "./adminProxy";
import { NextRequest } from "next/server";

beforeEach(() => {
  callbackPath = "/admin/source-mapping-proposals/1128?returnTo=%2Fadmin%2Fsource-mapping-proposals%3Fpage%3D4";
  authMock.mockReset();
  redirectMock.mockClear();
  notFoundMock.mockClear();
});

describe("requireAdminSession", () => {
  it("redirects an expired administrator with the exact callback and reason", async () => {
    authMock.mockResolvedValue({ user: { email: "admin@example.com" }, sessionKind: "admin", adminSessionExpired: true });
    await expect(requireAdminSession()).rejects.toThrow("NEXT_REDIRECT:");
    const destination = new URL(redirectMock.mock.calls[0][0], "https://atlas.example");
    expect(destination.pathname).toBe("/admin/login");
    expect(destination.searchParams.get("callbackUrl")).toBe(callbackPath);
    expect(destination.searchParams.get("reason")).toBe("session-expired");
    expect(notFoundMock).not.toHaveBeenCalled();
  });

  it("sanitizes a forged navigation hint without using it to authorize", async () => {
    callbackPath = "https://evil.example";
    authMock.mockResolvedValue(null);
    await expect(requireAdminSession()).rejects.toThrow("NEXT_REDIRECT:/admin/login?callbackUrl=%2Fadmin");
  });

  it("never treats a collector as expired admin even with an unrelated expiry flag", async () => {
    authMock.mockResolvedValue({ user: { email: "collector@example.com" }, sessionKind: "collector", adminSessionExpired: true });
    await expect(requireAdminSession()).rejects.toThrow("NEXT_NOT_FOUND");
  });
  it("returns the identity for a valid admin session", async () => {
    authMock.mockResolvedValueOnce({
      user: { id: "staging-admin", email: "admin@example.com", role: "admin" },
    });

    const identity = await requireAdminSession();

    expect(identity).toEqual({ id: "staging-admin", email: "admin@example.com" });
    expect(redirectMock).not.toHaveBeenCalled();
    expect(notFoundMock).not.toHaveBeenCalled();
  });

  it("redirects a signed-out visitor to /admin/login", async () => {
    authMock.mockResolvedValueOnce(null);

    await expect(requireAdminSession()).rejects.toThrow("NEXT_REDIRECT:/admin/login");
  });

  it("returns not-found for a signed-in collector session (role !== admin)", async () => {
    authMock.mockResolvedValueOnce({
      user: { id: "google-123", email: "collector@example.com" },
    });

    await expect(requireAdminSession()).rejects.toThrow("NEXT_NOT_FOUND");
    expect(redirectMock).not.toHaveBeenCalled();
  });

  it("returns not-found (not a redirect) for a session with an unexpected role value", async () => {
    authMock.mockResolvedValueOnce({
      user: { id: "x", email: "someone@example.com", role: "superadmin" },
    });

    await expect(requireAdminSession()).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("treats a role=admin session missing an email as not-admin (defensive)", async () => {
    authMock.mockResolvedValueOnce({ user: { id: "staging-admin", role: "admin" } });

    await expect(requireAdminSession()).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("never reads role from anything other than auth()'s own session - takes no request/header argument at all", () => {
    expect(requireAdminSession).toHaveLength(0);
  });
});

describe("real admin API authorization boundary", () => {
  it.each([
    null,
    { user: { email: "collector@example.com" }, sessionKind: "collector" },
    { user: { email: "admin@example.com" }, sessionKind: "admin", adminSessionExpired: true },
  ])("returns JSON 401 with no upstream call for unauthorized session %#", async (session) => {
    authMock.mockResolvedValue(session);
    const network = vi.spyOn(globalThis, "fetch");
    try {
      const response = await proxyAdminJson(new NextRequest("https://atlas.example/api/admin/cards"), "/admin/cards");
      expect(response.status).toBe(401);
      expect(response.headers.get("content-type")).toContain("application/json");
      expect(response.headers.get("location")).toBeNull();
      expect(await response.json()).toEqual({ error: "Admin session required." });
      expect(network).not.toHaveBeenCalled();
      expect(redirectMock).not.toHaveBeenCalled();
    } finally { network.mockRestore(); }
  });

  it("allows an active administrator API read", async () => {
    authMock.mockResolvedValue({ user: { role: "admin", email: "admin@example.com" }, sessionKind: "admin" });
    const network = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response('{"items":[]}'));
    try {
      const response = await proxyAdminJson(new NextRequest("https://atlas.example/api/admin/cards"), "/admin/cards");
      expect(response.status).toBe(200);
      expect(await response.json()).toEqual({ items: [] });
      expect(network).toHaveBeenCalledTimes(1);
    } finally { network.mockRestore(); }
  });
});

describe("getAdminIdentityForRouteHandler", () => {
  it("returns the identity for a valid admin session", async () => {
    authMock.mockResolvedValueOnce({
      user: { id: "staging-admin", email: "admin@example.com", role: "admin" },
    });

    const identity = await getAdminIdentityForRouteHandler();

    expect(identity).toEqual({ id: "staging-admin", email: "admin@example.com" });
  });

  it("returns null (never throws/redirects) for a signed-out request", async () => {
    authMock.mockResolvedValueOnce(null);

    const identity = await getAdminIdentityForRouteHandler();

    expect(identity).toBeNull();
    expect(redirectMock).not.toHaveBeenCalled();
    expect(notFoundMock).not.toHaveBeenCalled();
  });

  it("returns null for a signed-in collector session", async () => {
    authMock.mockResolvedValueOnce({
      user: { id: "google-123", email: "collector@example.com" },
    });

    const identity = await getAdminIdentityForRouteHandler();

    expect(identity).toBeNull();
  });
});
