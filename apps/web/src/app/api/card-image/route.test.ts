import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

const APPROVED =
  "https://www.onepiece-cardgame.com/images/cardlist/card/OP01-013_p2.png?260630";

function req(u?: string): Request {
  const url = new URL("http://localhost/api/card-image");
  if (u !== undefined) url.searchParams.set("u", u);
  return new Request(url.toString());
}

function imageResponse(
  body = new Uint8Array([137, 80, 78, 71]),
  headers: Record<string, string> = { "content-type": "image/png" },
): Response {
  return new Response(body, { status: 200, headers });
}

afterEach(() => vi.restoreAllMocks());

describe("GET /api/card-image", () => {
  it("re-serves an image from the approved host", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(imageResponse());

    const res = await GET(req(APPROVED));

    expect(res.status).toBe(200);
    expect(res.headers.get("Content-Type")).toBe("image/png");
    expect(fetchMock).toHaveBeenCalledWith(APPROVED, expect.objectContaining({ redirect: "manual" }));
  });

  it("strips the upstream CORP header by serving same-origin", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      imageResponse(undefined, {
        "content-type": "image/png",
        "cross-origin-resource-policy": "same-site",
      }),
    );

    const res = await GET(req(APPROVED));

    expect(res.headers.get("Cross-Origin-Resource-Policy")).toBe("same-origin");
  });

  it("refuses a host that is not on the allowlist", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");

    const res = await GET(req("https://evil.example.com/x.png"));

    expect(res.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses a lookalike hostname that only contains the approved one", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");

    const res = await GET(req("https://www.onepiece-cardgame.com.evil.tld/x.png"));

    expect(res.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refuses non-https targets, so it cannot reach internal services", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");

    expect((await GET(req("http://www.onepiece-cardgame.com/x.png"))).status).toBe(400);
    expect((await GET(req("http://169.254.169.254/latest/meta-data/"))).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("requires the u parameter and rejects a malformed url", async () => {
    expect((await GET(req())).status).toBe(400);
    expect((await GET(req("not-a-url"))).status).toBe(400);
  });

  it("does not follow redirects off the approved host", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 302, headers: { location: "https://evil.example.com/x.png" } }),
    );

    const res = await GET(req(APPROVED));

    expect(res.status).toBe(502);
  });

  it("refuses an upstream response that is not an image", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("<html>nope</html>", {
        status: 200,
        headers: { "content-type": "text/html" },
      }),
    );

    const res = await GET(req(APPROVED));

    expect(res.status).toBe(502);
  });

  it("refuses an oversized image", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(new Uint8Array(4), {
        status: 200,
        headers: { "content-type": "image/png", "content-length": String(9 * 1024 * 1024) },
      }),
    );

    const res = await GET(req(APPROVED));

    expect(res.status).toBe(502);
  });

  it("reports an upstream failure as a bad gateway rather than throwing", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network down"));

    const res = await GET(req(APPROVED));

    expect(res.status).toBe(502);
  });
});
