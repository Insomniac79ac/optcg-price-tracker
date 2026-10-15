import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
const { mintApiToken } = vi.hoisted(() => ({ mintApiToken: vi.fn() }));
vi.mock("@/lib/collectorApi", () => ({ API_INTERNAL_URL: "http://api.test", mintApiToken }));

import { loadCollectionPage, loadWatchlistPage } from "./collectionServer";

const IDENTITY = { sub: "google-123", email: "nami@example.com", name: "Nami" };
const TOKEN = "eyJ.test-token.sig";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  mintApiToken.mockReset();
});

describe("loadCollectionPage", () => {
  it("reads the collection and every window with one server-side token", async () => {
    mintApiToken.mockResolvedValueOnce(TOKEN);
    const fetchMock = vi.fn(async (url: string) => (String(url).endsWith("/me/collection") ? json({ entries: [] }) : json({ window: new URL(url).searchParams.get("window") })));
    vi.stubGlobal("fetch", fetchMock);

    const page = await loadCollectionPage(IDENTITY);
    expect(page.state).toBe("ok");
    if (page.state !== "ok") return;
    expect(page.values["7d"]).toEqual({ window: "7d" });
    expect(page.values.all).toEqual({ window: "all" });
    expect(mintApiToken).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls.map(([url]) => url).sort()).toEqual([
      "http://api.test/me/collection",
      "http://api.test/me/collection/value?window=30d",
      "http://api.test/me/collection/value?window=7d",
      "http://api.test/me/collection/value?window=all",
    ]);
    for (const [, init] of fetchMock.mock.calls as unknown as [string, RequestInit][]) {
      expect(init.headers).toEqual({ Authorization: `Bearer ${TOKEN}` });
      expect(init.cache).toBe("no-store");
    }
  });

  it("keeps the page when one window fails, with that window empty", async () => {
    mintApiToken.mockResolvedValueOnce(TOKEN);
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal("fetch", vi.fn(async (url: string) => (String(url).includes("30d") ? json({}, 500) : json({ entries: [] }))));
    const page = await loadCollectionPage(IDENTITY);
    expect(page.state).toBe("ok");
    if (page.state === "ok") expect(page.values["30d"]).toBeNull();
    expect(error).toHaveBeenCalledWith("[account] GET /me/collection/value 30d failed status=500");
  });

  it("is 'disabled' when the accounts API is switched off", async () => {
    mintApiToken.mockResolvedValueOnce(TOKEN);
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "Not Found" }, 404)));
    expect(await loadCollectionPage(IDENTITY)).toEqual({ state: "disabled" });
    expect(error).not.toHaveBeenCalled();
  });

  it("is an error, logged by status and class only, when the API fails", async () => {
    mintApiToken.mockResolvedValueOnce(TOKEN);
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError(`fetch failed for ${TOKEN} nami@example.com`); }));
    expect(await loadCollectionPage(IDENTITY)).toEqual({ state: "error" });
    const logged = error.mock.calls.map((call) => call.join(" ")).join("\n");
    expect(logged).toContain("[account] GET /me/collection failed error=TypeError");
    expect(logged).not.toMatch(/eyJ|nami@|google-123|Nami/);
  });

  it("is an error when the token cannot be minted", async () => {
    mintApiToken.mockRejectedValueOnce(new Error("API_JWT_SECRET is not configured"));
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    expect(await loadCollectionPage(IDENTITY)).toEqual({ state: "error" });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(error).toHaveBeenCalledWith("[account] mint API token failed error=Error");
  });
});

describe("loadWatchlistPage", () => {
  it("reads /me/watchlist with a server-side token", async () => {
    mintApiToken.mockResolvedValueOnce(TOKEN);
    const fetchMock = vi.fn(async () => json({ as_of: "2026-10-14", entries: [] }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await loadWatchlistPage(IDENTITY)).toEqual({ state: "ok", watchlist: { as_of: "2026-10-14", entries: [] } });
    expect(fetchMock).toHaveBeenCalledWith("http://api.test/me/watchlist", expect.objectContaining({ headers: { Authorization: `Bearer ${TOKEN}` }, cache: "no-store" }));
  });

  it("is 'disabled' on 404 and an error, logged by status only, otherwise", async () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    mintApiToken.mockResolvedValue(TOKEN);
    vi.stubGlobal("fetch", vi.fn(async () => json({}, 404)));
    expect(await loadWatchlistPage(IDENTITY)).toEqual({ state: "disabled" });
    vi.stubGlobal("fetch", vi.fn(async () => json({}, 502)));
    expect(await loadWatchlistPage(IDENTITY)).toEqual({ state: "error" });
    expect(error).toHaveBeenCalledWith("[account] GET /me/watchlist failed status=502");
  });
});
