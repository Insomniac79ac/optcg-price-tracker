// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
const { authMock } = vi.hoisted(() => ({ authMock: vi.fn() }));
vi.mock("@/lib/auth", () => ({ auth: authMock }));

import { proxyMe, upstreamPath } from "./meProxy";

const ORIGIN = "https://optcg-price-tracker-staging.vercel.app";
const COLLECTOR = { user: { id: "google-123", email: "collector@example.com" }, sessionKind: "collector" };
const ADMIN = { user: { id: "staging-admin", email: "admin@example.com", role: "admin" }, sessionKind: "admin" };

function req(path: string, init?: RequestInit): NextRequest {
  return new NextRequest(new Request(`${ORIGIN}${path}`, init));
}

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  vi.stubEnv("API_JWT_SECRET", "unit-test-api-jwt-secret");
  vi.stubEnv("AUTH_URL", ORIGIN);
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  authMock.mockReset();
});

describe("upstreamPath", () => {
  it.each([
    [undefined, "/me"],
    [["profile"], "/me/profile"],
    [["export", "collection.csv"], "/me/export/collection.csv"],
    [["collection", "value"], "/me/collection/value"],
    [["watchlist", "4"], "/me/watchlist/4"],
  ])("maps %j to %s", (segments, expected) => {
    expect(upstreamPath(segments as string[] | undefined)).toBe(expected);
  });

  it.each([
    // The legacy per-user routes went with the pre-v1 pages (Collector v1 S8).
    [["legacy", "collection"]],
    [["legacy", "collection", "12", "tags", "3"]],
    [["legacy", "wishlist", "4", "mark-purchased"]],
    [["legacy", "collector", "tags"]],
    [["legacy", "cards", "7", "tags", "2"]],
    [["legacy", "admin", "logs"]],
    [["legacy", "cards"]],
    [["legacy", "cards", "7"]],
    [["legacy"]],
    [["legacy", "collector", "something-else"]],
    [[".."]],
    [["profile", "..", "..", "admin"]],
    [["a%2Fb"]],
    [["with space"]],
  ])("refuses %j", (segments) => {
    expect(upstreamPath(segments as string[])).toBeNull();
  });
});

describe("proxyMe", () => {
  it("refuses a legacy path with 404 before touching the session or API", async () => {
    const res = await proxyMe(req("/api/me/legacy/admin/logs"), ["legacy", "admin", "logs"]);
    expect(res.status).toBe(404);
    expect(authMock).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([["signed out", null], ["an admin session", ADMIN]])("answers 401 for %s without calling the API", async (_label, session) => {
    authMock.mockResolvedValueOnce(session);
    const res = await proxyMe(req("/api/me/profile"), ["profile"]);
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses a cross-site DELETE with 403 before reading the session", async () => {
    const res = await proxyMe(
      req("/api/me?confirm=delete%20my%20account", { method: "DELETE", headers: { origin: "https://evil.example" } }),
      undefined,
    );
    expect(res.status).toBe(403);
    expect(authMock).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards a same-origin DELETE /me with the confirmation and a server-minted token", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    const res = await proxyMe(
      req("/api/me?confirm=delete%20my%20account", { method: "DELETE", headers: { origin: ORIGIN, "sec-fetch-site": "same-origin" } }),
      undefined,
    );
    expect(res.status).toBe(204);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api:8000/me?confirm=delete%20my%20account");
    expect(init.method).toBe("DELETE");
    expect(init.headers.Authorization).toMatch(/^Bearer ey/);
  });

  it("streams the API answer back without the token, private and uncached", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    fetchMock.mockResolvedValueOnce(
      new Response("id,quantity\n", {
        status: 200,
        headers: { "content-type": "text/csv; charset=utf-8", "content-disposition": 'attachment; filename="card-pirate-collection.csv"', "set-cookie": "x=1" },
      }),
    );
    const res = await proxyMe(req("/api/me/export/collection.csv"), ["export", "collection.csv"]);
    expect(res.status).toBe(200);
    expect(await res.text()).toBe("id,quantity\n");
    expect(res.headers.get("content-disposition")).toContain("card-pirate-collection.csv");
    expect(res.headers.get("cache-control")).toBe("private, no-store");
    expect(res.headers.get("set-cookie")).toBeNull();
    expect(res.headers.get("authorization")).toBeNull();
    for (const [, value] of res.headers.entries()) expect(value).not.toMatch(/Bearer|eyJ/);
  });

  it("passes the JSON body of a same-origin PUT", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    fetchMock.mockResolvedValueOnce(Response.json({ currency: "JPY", collection_visibility: "private" }));
    const body = JSON.stringify({ currency: "JPY" });
    const res = await proxyMe(req("/api/me/preferences", { method: "PUT", body, headers: { origin: ORIGIN } }), ["preferences"]);
    expect(res.status).toBe(200);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "PUT", body });
  });

  it("answers 502 when the API is unreachable", async () => {
    authMock.mockResolvedValueOnce(COLLECTOR);
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    const res = await proxyMe(req("/api/me/profile"), ["profile"]);
    expect(res.status).toBe(502);
  });
});
