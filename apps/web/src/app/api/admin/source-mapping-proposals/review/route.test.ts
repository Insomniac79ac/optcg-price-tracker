import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

const { getAdminIdentityForRouteHandler } = vi.hoisted(() => ({
  getAdminIdentityForRouteHandler: vi.fn(),
}));
vi.mock("@/lib/adminSession", () => ({ getAdminIdentityForRouteHandler }));

import { GET as getDetail } from "./groups/[id]/route";
import { GET as getGroups } from "./groups/route";
import { GET as getReleases } from "./releases/route";
import { GET as getSummary } from "./summary/route";

const ADMIN = { id: "admin", email: "admin@example.com" };

function request(path: string): NextRequest {
  return new NextRequest(`http://localhost${path}`);
}

describe("proposal review GET proxies", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    getAdminIdentityForRouteHandler.mockReset();
    getAdminIdentityForRouteHandler.mockResolvedValue(ADMIN);
    process.env.ADMIN_TOKEN = "server-only-token";
    global.fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response('{"ok":true}', { status: 200 })));
  });

  afterEach(() => {
    global.fetch = originalFetch;
    delete process.env.ADMIN_TOKEN;
  });

  it("forwards summary and releases to the persisted-review backend routes", async () => {
    expect((await getSummary(request("/api/admin/source-mapping-proposals/review/summary"))).status).toBe(200);
    expect((await getReleases(request("/api/admin/source-mapping-proposals/review/releases"))).status).toBe(200);
    const urls = vi.mocked(global.fetch).mock.calls.map(([url]) => url);
    expect(urls).toEqual([
      "http://api:8000/admin/source-mapping-proposals/review/summary",
      "http://api:8000/admin/source-mapping-proposals/review/releases",
    ]);
  });

  it("preserves every list query parameter and forwards detail IDs", async () => {
    await getGroups(request("/api/admin/source-mapping-proposals/review/groups?source=yuyutei&unresolved_release=true&q=OP01-001&limit=25&offset=50"));
    await getDetail(
      request("/api/admin/source-mapping-proposals/review/groups/1127?trace=fixture"),
      { params: Promise.resolve({ id: "1127" }) },
    );
    const urls = vi.mocked(global.fetch).mock.calls.map(([url]) => url);
    expect(urls[0]).toBe("http://api:8000/admin/source-mapping-proposals/review/groups?source=yuyutei&unresolved_release=true&q=OP01-001&limit=25&offset=50");
    expect(urls[1]).toBe("http://api:8000/admin/source-mapping-proposals/review/groups/1127?trace=fixture");
    expect(vi.mocked(global.fetch).mock.calls[0][1]?.method).toBe("GET");
  });

  it("returns 401 without contacting the backend when the admin session is missing", async () => {
    getAdminIdentityForRouteHandler.mockResolvedValueOnce(null);
    const response = await getSummary(request("/api/admin/source-mapping-proposals/review/summary"));
    expect(response.status).toBe(401);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("preserves a backend error status and JSON body", async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response('{"detail":"queue unavailable"}', { status: 503 }));
    const response = await getGroups(request("/api/admin/source-mapping-proposals/review/groups?limit=50"));
    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({ detail: "queue unavailable" });
  });
});
