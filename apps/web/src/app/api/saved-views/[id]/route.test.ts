import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
const { collectorAuthHeaders } = vi.hoisted(() => ({ collectorAuthHeaders: vi.fn() }));
vi.mock("@/lib/collectorApi", async () => {
  const { crossSiteRejection } = await import("@/lib/crossSite");
  return { collectorAuthHeaders, crossSiteRejection };
});

import { DELETE, GET } from "./route";

const params = (id: string) => ({ params: Promise.resolve({ id }) });
const req = (method = "GET") =>
  new NextRequest(
    new Request("http://localhost/api/saved-views/x", {
      method,
      headers: { origin: "http://localhost", "sec-fetch-site": "same-origin" },
    }),
  );

afterEach(() => vi.restoreAllMocks());

describe("/api/saved-views/[id] (audit F8, F13)", () => {
  it.each(["1%2F..%2Fadmin", "../me", "abc"])("404s a non-numeric id %j without calling the API", async (id) => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    expect((await GET(req(), params(id))).status).toBe(404);
    expect((await DELETE(req("DELETE"), params(id))).status).toBe(404);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(collectorAuthHeaders).not.toHaveBeenCalled();
  });

  it("forwards a numeric id", async () => {
    collectorAuthHeaders.mockResolvedValue({ Authorization: "Bearer t" });
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response('{"id":7}', { status: 200 }));
    const res = await GET(req(), params("7"));
    expect(res.status).toBe(200);
    expect(fetchSpy.mock.calls[0][0]).toBe("http://api:8000/saved-views/7");
  });

  it("does not echo a non-JSON upstream body to the browser", async () => {
    collectorAuthHeaders.mockResolvedValue({ Authorization: "Bearer t" });
    vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("<html>Internal detail: db=10.0.0.5</html>", { status: 500 }),
    );
    const res = await GET(req(), params("7"));
    const body = await res.json();
    expect(res.status).toBe(500);
    expect(body).toEqual({ error: "Invalid JSON from backend API", backend_status: 500 });
  });
});
