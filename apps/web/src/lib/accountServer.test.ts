import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));
const { mintApiToken } = vi.hoisted(() => ({ mintApiToken: vi.fn() }));
vi.mock("@/lib/collectorApi", () => ({ API_INTERNAL_URL: "http://api.test", mintApiToken }));

import { loadAccountOverview, logAccountUpstreamFailure } from "./accountServer";

const IDENTITY = { sub: "google-sub-123", email: "collector@example.test", name: "Test Collector" };
const TOKEN = "secret.bearer.token";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

const PROFILE = { email: IDENTITY.email, name: "Test Collector", member_since: "2026-10-15T00:00:00Z" };
const PREFERENCES = { currency: "JPY", collection_visibility: "private" };
const VALUE = { as_of: "2026-10-17", window: "7d", summary: { value_jpy: 1200, total_cards: 1 } };
const WATCHLIST = { currency: "JPY", as_of: "2026-10-17", entries: [] };

function respond(url: string, override: Record<string, Response> = {}) {
  const path = url.replace("http://api.test/me/", "");
  if (path in override) return override[path];
  if (path === "profile") return json(200, PROFILE);
  if (path === "preferences") return json(200, PREFERENCES);
  if (path === "collection/value?window=7d") return json(200, VALUE);
  if (path === "watchlist") return json(200, WATCHLIST);
  return json(500, {});
}

let errors: string[];

beforeEach(() => {
  errors = [];
  vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
    errors.push(args.map(String).join(" "));
  });
  mintApiToken.mockResolvedValue(TOKEN);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function expectNoPrivateData() {
  const all = errors.join("\n");
  expect(all).not.toContain(TOKEN);
  expect(all).not.toContain(IDENTITY.email);
  expect(all).not.toContain(IDENTITY.sub);
  expect(all).not.toContain("Test Collector");
}

describe("loadAccountOverview overview strip", () => {
  it("reads the 7D value and the watchlist with the same single token", async () => {
    const fetchMock = vi.fn(async (url: string) => respond(url));
    vi.stubGlobal("fetch", fetchMock);
    const overview = await loadAccountOverview(IDENTITY);
    expect(mintApiToken).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls.map(([url]) => url).sort()).toEqual([
      "http://api.test/me/collection/value?window=7d",
      "http://api.test/me/preferences",
      "http://api.test/me/profile",
      "http://api.test/me/watchlist",
    ]);
    for (const [, init] of fetchMock.mock.calls as unknown as [string, RequestInit][]) {
      expect(init.headers).toEqual({ Authorization: `Bearer ${TOKEN}` });
    }
    expect(overview).toMatchObject({ state: "ok", collection: VALUE, watchlist: WATCHLIST });
  });

  it("keeps the page when a strip read fails, with that part null", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      respond(url, { "collection/value?window=7d": json(503, {}), watchlist: json(200, WATCHLIST) })));
    const overview = await loadAccountOverview(IDENTITY);
    expect(overview).toMatchObject({ state: "ok", collection: null, watchlist: WATCHLIST });
    expect(errors).toEqual(["[account] GET /me/collection/value failed status=503"]);
  });

  it("keeps the page when a strip read throws", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.endsWith("/watchlist")) throw new TypeError("fetch failed");
      return respond(url);
    }));
    const overview = await loadAccountOverview(IDENTITY);
    expect(overview).toMatchObject({ state: "ok", collection: VALUE, watchlist: null });
    expect(errors).toEqual(["[account] GET /me/watchlist failed error=TypeError"]);
  });
});

describe("loadAccountOverview upstream logging", () => {
  it("logs nothing when every read succeeds", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => respond(url)));
    const overview = await loadAccountOverview(IDENTITY);
    expect(overview.state).toBe("ok");
    expect(errors).toEqual([]);
  });

  it("logs the step and status of a failed read, never the token or identity", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      url.endsWith("/profile") ? json(401, { detail: `bad token ${TOKEN} for ${IDENTITY.email}` }) : json(200, {})));
    const overview = await loadAccountOverview(IDENTITY);
    expect(overview.state).toBe("error");
    expect(errors).toEqual(["[account] GET /me/profile failed status=401"]);
    expectNoPrivateData();
  });

  it("does not log the accounts-disabled 404", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(404, { detail: "Not Found" })));
    expect((await loadAccountOverview(IDENTITY)).state).toBe("disabled");
    expect(errors).toEqual([]);
  });

  it("logs a network failure by error class only", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      const error = new Error(`connect ECONNREFUSED with ${TOKEN}`);
      error.name = "TypeError";
      throw error;
    }));
    expect((await loadAccountOverview(IDENTITY)).state).toBe("error");
    expect(errors).toContain("[account] GET /me/profile failed error=TypeError");
    expectNoPrivateData();
  });

  it("logs a token-minting failure by error class only", async () => {
    mintApiToken.mockRejectedValue(new RangeError(`API_JWT_SECRET ${TOKEN}`));
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    expect((await loadAccountOverview(IDENTITY)).state).toBe("error");
    expect(errors).toEqual(["[account] mint API token failed error=RangeError"]);
    expect(fetchMock).not.toHaveBeenCalled();
    expectNoPrivateData();
  });
});

describe("logAccountUpstreamFailure", () => {
  it("never echoes an arbitrary error name", () => {
    const error = new Error("x");
    error.name = "Bearer abc.def collector@example.test";
    logAccountUpstreamFailure("GET /me/profile", { error });
    expect(errors).toEqual(["[account] GET /me/profile failed error=unknown"]);
  });
});
